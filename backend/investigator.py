"""Gemma 4 investigator and screenshot scanner with a provider chain.

LLM_PROVIDER = auto | ollama | gemini | openai_compat
auto tries: local Ollama (model present) -> Gemini API (GEMINI_API_KEY) -> OpenAI-compatible (LLM_BASE_URL) -> template.

Each call runs in one of two modes:
  function_calling   the model calls get_account_history / get_graph_neighbours / get_risk_factors itself
  context_injection  the backend runs the three lookups and puts the results in the prompt
If a provider rejects tools or returns malformed calls, it is switched to context_injection.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from typing import Callable

import httpx

from . import policy

LANG_NAMES = {"en": "English", "ta": "Tamil", "hi": "Hindi"}
SCRIPT_RANGES = {"ta": (0x0B80, 0x0BFF), "hi": (0x0900, 0x097F)}
VERDICTS = ("allow", "nudge", "hold", "block")

TOOL_SPECS = [
    {
        "name": "get_account_history",
        "description": "Profile and recent payments of a UPI account (VPA): account age, usual spend, last payments.",
        "parameters": {"type": "object", "properties": {"vpa": {"type": "string", "description": "UPI VPA, e.g. name@bank"}}, "required": ["vpa"]},
    },
    {
        "name": "get_graph_neighbours",
        "description": "Accounts that pay into and receive from a VPA, with pass-through ratios that indicate mule behaviour.",
        "parameters": {"type": "object", "properties": {"vpa": {"type": "string"}}, "required": ["vpa"]},
    },
    {
        "name": "get_risk_factors",
        "description": "The scorer's risk probability and top contributing factors for a transaction id.",
        "parameters": {"type": "object", "properties": {"txn_id": {"type": "string"}}, "required": ["txn_id"]},
    },
]


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def ollama_url() -> str:
    return _env("OLLAMA_URL", _env("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")


def model_for(provider: str) -> str:
    return {
        "ollama": _env("OLLAMA_MODEL", "gemma4:e4b"),
        "gemini": _env("GEMINI_MODEL", "gemma-4-26b-a4b-it"),
        "openai_compat": _env("LLM_MODEL", "gemma-4"),
    }.get(provider, "")


def timeout_for(provider: str) -> float:
    return 60.0 if provider == "ollama" else 10.0


def pretty_model(provider: str, model: str) -> str:
    m = model.lower()
    if "e4b" in m:
        name = "Gemma 4 E4B"
    elif "e2b" in m:
        name = "Gemma 4 E2B"
    elif "26b" in m:
        name = "Gemma 4 26B"
    elif "31b" in m:
        name = "Gemma 4 31B"
    elif "gemma" in m:
        name = "Gemma 4"
    else:
        name = model
    where = {"ollama": "local", "gemini": "Gemini API", "openai_compat": "OpenAI-compatible API"}[provider]
    return f"{name} · {where}"


def provenance(provider: str | None, model: str | None, mode: str | None) -> str:
    if not provider:
        return "Template (model unavailable)"
    return f"{pretty_model(provider, model or '')} · {(mode or '').replace('_', ' ')}"


# ---------- provider resolution ----------
_ollama_probe: dict = {"at": 0.0, "ok": False}


async def _ollama_ready() -> bool:
    if time.monotonic() - _ollama_probe["at"] < 20:
        return _ollama_probe["ok"]
    ok = False
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(f"{ollama_url()}/api/tags")
            names = {m.get("name", "") for m in r.json().get("models", [])}
            want = model_for("ollama")
            ok = want in names or f"{want}:latest" in names
    except Exception:
        ok = False
    _ollama_probe.update(at=time.monotonic(), ok=ok)
    return ok


async def resolve_provider() -> str | None:
    choice = _env("LLM_PROVIDER", "auto").lower()
    if choice == "ollama":
        return "ollama" if await _ollama_ready() else None
    if choice == "gemini":
        return "gemini" if _env("GEMINI_API_KEY") else None
    if choice == "openai_compat":
        return "openai_compat" if _env("LLM_BASE_URL") else None
    if await _ollama_ready():
        return "ollama"
    if _env("GEMINI_API_KEY"):
        return "gemini"
    if _env("LLM_BASE_URL"):
        return "openai_compat"
    return None


# Providers whose tool calls failed twice in a row go straight to context injection.
_no_tools: set[str] = set()
_tool_failures: dict[str, int] = {}
TOOL_FAILURE_LIMIT = 2


# ---------- prompts and validation ----------
def _task(txn: dict, lang: str) -> str:
    return (
        "You are a fraud investigator for a UPI payments app in India. A risk scorer flagged a payment.\n"
        f"Transaction {txn['txn_id']}: {txn['sender_vpa']} -> {txn['receiver_vpa']}, ₹{txn['amount']:,.0f}, "
        f"hour {txn['hour']}:00, risk {txn['risk']:.2f}, proposed action '{txn['action']}'.\n"
    )


def _answer_spec(lang: str) -> str:
    return (
        "Reply with ONLY a JSON object with keys:\n"
        '"verdict": one of "allow","nudge","hold","block" (the least disruptive response that keeps the payer safe);\n'
        '"reason": one English sentence citing specific evidence;\n'
        f'"customer_message": at most two short calm sentences to the payer, written in {LANG_NAMES[lang]}'
        + (" script" if lang != "en" else "") + ";\n"
        '"analyst_note": a terse English line under 20 words.'
    )


def _fc_prompt(txn: dict, lang: str) -> str:
    return (_task(txn, lang)
            + "In your first reply, call all three tools together: get_risk_factors for the transaction, "
            "get_account_history for the payer and get_graph_neighbours for the payee. Then decide.\n"
            + _answer_spec(lang))


def _ci_prompt(txn: dict, lang: str, tools: dict[str, Callable]) -> str:
    ctx = {
        "risk_factors": tools["get_risk_factors"](txn_id=txn["txn_id"]),
        "payer_history": tools["get_account_history"](vpa=txn["sender_vpa"]),
        "payee_neighbours": tools["get_graph_neighbours"](vpa=txn["receiver_vpa"]),
    }
    return _task(txn, lang) + "Evidence from the bank's systems:\n" + json.dumps(ctx, ensure_ascii=False, separators=(",", ":")) + "\n" + _answer_spec(lang)


def in_script(text: str, lang: str) -> bool:
    if lang not in SCRIPT_RANGES:
        return True
    lo, hi = SCRIPT_RANGES[lang]
    return any(lo <= ord(ch) <= hi for ch in text)


def parse_answer(text: str) -> dict:
    m = re.search(r"\{.*\}", (text or "").strip(), re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    data = json.loads(m.group(0))
    out = {}
    for key in ("verdict", "reason", "customer_message", "analyst_note"):
        val = data.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"missing {key}")
        out[key] = val.strip()
    out["verdict"] = out["verdict"].lower()
    if out["verdict"] not in VERDICTS:
        raise ValueError("bad verdict")
    return out


def _finish(answer: dict, txn: dict, lang: str, provider: str, mode: str, started: float, tool_calls: list) -> dict:
    message_source = "model"
    if not in_script(answer["customer_message"], lang):
        answer["customer_message"] = policy.customer_message(txn["action"], lang, txn["amount"], txn["receiver_vpa"])
        message_source = "template"
    model = model_for(provider)
    return {
        **answer, "source": "model", "provider": provider, "model": model, "mode": mode,
        "label": provenance(provider, model, mode), "message_source": message_source,
        "latency_ms": round((time.perf_counter() - started) * 1000), "tool_calls": tool_calls, "error": None,
    }


def replayed(result: dict) -> dict:
    """A cached model result served again, keeping its original provenance."""
    return {**result, "replayed": True, "label": f"{result['label']} · replayed from cache"}


def fallback(txn: dict, lang: str, error: str | None = None) -> dict:
    factors = txn.get("factors", [])
    top = ", ".join(f["label"].lower() for f in factors[:3]) or "a combination of weak signals"
    action = txn["action"]
    return {
        "verdict": action,
        "reason": f"Risk {txn['risk']:.2f} driven mainly by {top}.",
        "customer_message": policy.customer_message(action, lang, txn["amount"], txn["receiver_vpa"]),
        "analyst_note": "; ".join(f"{f['label']}={_fmt(f['value'])} (+{f['contribution']:.2f})" for f in factors[:4]),
        "source": "fallback", "provider": None, "model": None, "mode": None,
        "label": provenance(None, None, None), "message_source": "template",
        "latency_ms": 0, "tool_calls": [], "error": error,
    }


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def _run_tool(tools, name, args, log):
    fn = tools.get(name)
    if fn is None:
        raise ValueError(f"model called unknown tool {name}")
    log.append({"name": name, "args": args})
    return fn(**args)


# ---------- provider calls ----------
async def _ollama_chat(messages: list, tools: list | None = None, json_mode: bool = False, timeout: float = 60.0, num_predict: int = 200) -> dict:
    body = {"model": model_for("ollama"), "messages": messages, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_predict": num_predict}}
    if tools:
        body["tools"] = tools
    if json_mode:
        body["format"] = "json"
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{ollama_url()}/api/chat", json=body)
        r.raise_for_status()
        return r.json()["message"]


async def _openai_chat(messages: list, tools: list | None = None, json_mode: bool = False, timeout: float = 10.0) -> dict:
    body = {"model": model_for("openai_compat"), "messages": messages, "temperature": 0.2, "max_tokens": 300}
    if tools:
        body["tools"] = tools
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {_env('LLM_API_KEY')}"} if _env("LLM_API_KEY") else {}
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{_env('LLM_BASE_URL').rstrip('/')}/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


def _gemini_client():
    from google import genai
    return genai.Client(api_key=_env("GEMINI_API_KEY"))


def _gemini_config(json_mode: bool = False, **kw):
    """Gemma 4 on the Gemini API thinks at length by default (25 s+); minimal thinking keeps a call near 4 s."""
    from google.genai import types
    extra = {"thinking_config": types.ThinkingConfig(thinking_level="minimal")}
    if json_mode:
        extra["response_mime_type"] = "application/json"
    return types.GenerateContentConfig(temperature=kw.pop("temperature", 0.2), **extra, **kw)


async def _function_calling(provider: str, txn: dict, lang: str, tools: dict) -> tuple[dict, list]:
    log: list = []
    if provider == "gemini":
        from google.genai import types
        client = _gemini_client()
        decls = [types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=t["parameters"]) for t in TOOL_SPECS]
        config = _gemini_config(
            tools=[types.Tool(function_declarations=decls)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=_fc_prompt(txn, lang))])]
        for _ in range(4):
            resp = await client.aio.models.generate_content(model=model_for("gemini"), contents=contents, config=config)
            calls = resp.function_calls or []
            if not calls:
                return parse_answer(resp.text or ""), log
            contents.append(resp.candidates[0].content)
            parts = [types.Part.from_function_response(name=c.name, response={"result": _run_tool(tools, c.name, dict(c.args or {}), log)}) for c in calls]
            contents.append(types.Content(role="user", parts=parts))
        raise ValueError("too many tool rounds")

    tool_defs = [{"type": "function", "function": t} for t in TOOL_SPECS]
    messages: list = [{"role": "user", "content": _fc_prompt(txn, lang)}]
    for _ in range(4):
        if provider == "ollama":
            msg = await _ollama_chat(messages, tools=tool_defs, timeout=timeout_for(provider))
        else:
            msg = await _openai_chat(messages, tools=tool_defs, timeout=timeout_for(provider))
        calls = msg.get("tool_calls") or []
        if not calls:
            return parse_answer(msg.get("content") or ""), log
        messages.append(msg)
        for c in calls:
            fn = c["function"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args)
            result = json.dumps(_run_tool(tools, fn["name"], args, log), ensure_ascii=False)
            if provider == "ollama":
                messages.append({"role": "tool", "tool_name": fn["name"], "content": result})
            else:
                messages.append({"role": "tool", "tool_call_id": c.get("id", fn["name"]), "content": result})
    raise ValueError("too many tool rounds")


async def _context_injection(provider: str, txn: dict, lang: str, tools: dict) -> dict:
    prompt = _ci_prompt(txn, lang, tools)
    if provider == "gemini":
        resp = await _gemini_client().aio.models.generate_content(
            model=model_for("gemini"), contents=prompt, config=_gemini_config(json_mode=True))
        return parse_answer(resp.text or "")
    messages = [{"role": "user", "content": prompt}]
    if provider == "ollama":
        msg = await _ollama_chat(messages, json_mode=True, timeout=timeout_for(provider))
    else:
        msg = await _openai_chat(messages, json_mode=True, timeout=timeout_for(provider))
    return parse_answer(msg.get("content") or "")


def _transient(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(code, int) and (code >= 500 or code == 429)


async def investigate(txn: dict, lang: str, tools: dict[str, Callable], provider: str | None = None) -> dict:
    """Never raises. Returns a model result with provenance, or the labelled template fallback."""
    lang = lang if lang in LANG_NAMES else "en"
    provider = provider or await resolve_provider()
    if provider is None:
        return fallback(txn, lang, "no model provider reachable")
    started = time.perf_counter()
    deadline = timeout_for(provider)
    mode_note = None if provider not in _no_tools else "tool calling disabled after repeated failures"
    if provider not in _no_tools:
        try:
            answer, log = await asyncio.wait_for(_function_calling(provider, txn, lang, tools), timeout=deadline)
            _tool_failures[provider] = 0
            return _finish(answer, txn, lang, provider, "function_calling", started, log)
        except asyncio.TimeoutError:
            return fallback(txn, lang, f"{provider} timed out after {deadline:.0f}s")
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return fallback(txn, lang, f"{provider} unreachable: {type(exc).__name__}")
        except Exception as exc:
            # Tools rejected (4xx) or malformed calls twice in a row: context injection from now on.
            # A transient server error only falls back for this call.
            mode_note = f"function calling failed: {type(exc).__name__}: {str(exc)[:120]}"
            if not _transient(exc):
                _tool_failures[provider] = _tool_failures.get(provider, 0) + 1
                if _tool_failures[provider] >= TOOL_FAILURE_LIMIT:
                    _no_tools.add(provider)
    remaining = max(1.0, deadline - (time.perf_counter() - started))
    try:
        answer = await asyncio.wait_for(_context_injection(provider, txn, lang, tools), timeout=remaining)
        return {**_finish(answer, txn, lang, provider, "context_injection", started, []), "mode_note": mode_note}
    except asyncio.TimeoutError:
        return fallback(txn, lang, f"{provider} timed out after {deadline:.0f}s")
    except Exception as exc:
        return fallback(txn, lang, f"{provider} error: {type(exc).__name__}: {str(exc)[:120]}")


async def warm_up() -> dict:
    """Load the model with a tiny request. Returns a status dict for the header badge."""
    provider = await resolve_provider()
    if provider is None:
        return {"provider": None, "model": None, "state": "offline", "error": "no model provider reachable", "last_latency_ms": None}
    t0 = time.perf_counter()
    try:
        msgs = [{"role": "user", "content": "Reply with the single word OK."}]
        if provider == "ollama":
            await _ollama_chat(msgs, timeout=120.0, num_predict=4)
        elif provider == "openai_compat":
            await _openai_chat(msgs, timeout=10.0)
        else:
            await _gemini_client().aio.models.generate_content(
                model=model_for("gemini"), contents="Reply with the single word OK.", config=_gemini_config(temperature=0.0))
        state, error = "ready", None
    except Exception as exc:
        state, error = "offline", f"{type(exc).__name__}: {str(exc)[:160]}"
    return {"provider": provider, "model": model_for(provider), "state": state, "error": error,
            "last_latency_ms": round((time.perf_counter() - t0) * 1000)}


# ---------- screenshot scan ----------
VISION_PROMPT = (
    "This image is a screenshot of a payment request, UPI collect request, QR payment page or SMS/chat message "
    "received by an Indian mobile user. Read it and reply with ONLY a JSON object with keys:\n"
    '"payee": the VPA, phone number or name being paid, or null;\n'
    '"amount": the rupee amount as a number, or null;\n'
    '"urgency": "low", "medium" or "high";\n'
    '"pressure_cues": list of short phrases from the image that pressure the reader;\n'
    '"scam_signals": list of short scam indicators (impersonation, refund trick, KYC threat, collect request disguised as receiving money);\n'
    '"risk_contribution": number 0 to 1 for how much this should raise the risk of paying;\n'
    '"summary": one sentence in {lang}.'
)


def parse_scan(text: str) -> dict:
    m = re.search(r"\{.*\}", (text or "").strip(), re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    d = json.loads(m.group(0))
    amount = d.get("amount")
    try:
        amount = float(str(amount).replace(",", "").replace("₹", "").replace("Rs", "").strip()) if amount not in (None, "") else None
    except ValueError:
        amount = None
    try:
        rc = float(d.get("risk_contribution") or 0)
    except (TypeError, ValueError):
        rc = 0.0
    return {
        "payee": d.get("payee") or None,
        "amount": amount,
        "urgency": d.get("urgency") if d.get("urgency") in ("low", "medium", "high") else "medium",
        "pressure_cues": [str(x) for x in (d.get("pressure_cues") or [])][:6],
        "scam_signals": [str(x) for x in (d.get("scam_signals") or [])][:6],
        "risk_contribution": max(0.0, min(1.0, rc)),
        "summary": str(d.get("summary") or ""),
    }


async def scan_image(data: bytes, mime: str, lang: str) -> dict:
    provider = await resolve_provider()
    if provider is None:
        raise RuntimeError("no model provider reachable (start Ollama with gemma4:e4b, or set GEMINI_API_KEY or LLM_BASE_URL)")
    prompt = VISION_PROMPT.replace("{lang}", LANG_NAMES.get(lang, "English"))
    t0 = time.perf_counter()

    async def run():
        if provider == "gemini":
            from google.genai import types
            resp = await _gemini_client().aio.models.generate_content(
                model=model_for("gemini"),
                contents=[types.Content(role="user", parts=[types.Part.from_bytes(data=data, mime_type=mime), types.Part.from_text(text=prompt)])],
                config=_gemini_config(json_mode=True, temperature=0.1),
            )
            return parse_scan(resp.text or "")
        b64 = base64.b64encode(data).decode()
        if provider == "ollama":
            msg = await _ollama_chat([{"role": "user", "content": prompt, "images": [b64]}], json_mode=True,
                                     timeout=timeout_for(provider), num_predict=300)
        else:
            msg = await _openai_chat([{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}], json_mode=True, timeout=timeout_for(provider))
        return parse_scan(msg.get("content") or "")

    result = await asyncio.wait_for(run(), timeout=timeout_for(provider) + 30)
    model = model_for(provider)
    return {**result, "provider": provider, "model": model, "label": f"{pretty_model(provider, model)} · vision",
            "latency_ms": round((time.perf_counter() - t0) * 1000)}
