"""Gemma 4 investigator: explains a flagged transaction using native function calling.

Providers:
  gemini  -> gemma-4-26b-a4b-it through the google-genai SDK (GEMINI_API_KEY)
  ollama  -> gemma4:e4b on a local Ollama server via /api/chat with tools
Any failure or timeout falls back to a deterministic template, marked source="fallback".
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from typing import Callable

import httpx

from . import policy

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
TIMEOUT_S = 6.0
VISION_TIMEOUT_S = 20.0
LANG_NAMES = {"en": "English", "ta": "Tamil", "hi": "Hindi"}

TOOL_SPECS = [
    {
        "name": "get_account_history",
        "description": "Recent payment history and profile of a UPI account (VPA): account age, usual spend, last payments.",
        "parameters": {"type": "object", "properties": {"vpa": {"type": "string", "description": "UPI VPA, e.g. name@bank"}}, "required": ["vpa"]},
    },
    {
        "name": "get_graph_neighbours",
        "description": "Accounts that send money to and receive money from a VPA, with pass-through ratios that indicate mule behaviour.",
        "parameters": {"type": "object", "properties": {"vpa": {"type": "string"}}, "required": ["vpa"]},
    },
    {
        "name": "get_risk_factors",
        "description": "The scorer's risk probability and top contributing factors for a transaction id.",
        "parameters": {"type": "object", "properties": {"txn_id": {"type": "string"}}, "required": ["txn_id"]},
    },
]


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "gemini").lower()


def model_name() -> str:
    return OLLAMA_MODEL if provider() == "ollama" else GEMINI_MODEL


def available() -> bool:
    if provider() == "ollama":
        return True
    return bool(os.getenv("GEMINI_API_KEY"))


def _prompt(txn: dict, lang: str) -> str:
    return (
        "You are a fraud investigator for a UPI payments app in India. A risk scorer flagged a payment.\n"
        f"Transaction: id={txn['txn_id']}, from {txn['sender_vpa']} to {txn['receiver_vpa']}, "
        f"amount ₹{txn['amount']:,.0f}, hour {txn['hour']}:00, risk {txn['risk']:.2f}, proposed action '{txn['action']}'.\n"
        "Use the tools to check the risk factors, the payer's history and the payee's graph neighbours before deciding.\n"
        "Then reply with ONLY a JSON object, no markdown, with keys:\n"
        '  "verdict": one of "allow", "nudge", "hold", "block" (a proportional response; prefer the least disruptive one that keeps the customer safe),\n'
        '  "reason": one or two plain English sentences citing the specific evidence,\n'
        f'  "customer_message": a short, calm message to the payer written in {LANG_NAMES.get(lang, "English")}, no jargon,\n'
        '  "analyst_note": one terse line for a fraud analyst.'
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    data = json.loads(m.group(0))
    out = {}
    for key in ("verdict", "reason", "customer_message", "analyst_note"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"missing {key}")
        out[key] = data[key].strip()
    if out["verdict"] not in ("allow", "nudge", "hold", "block"):
        raise ValueError("bad verdict")
    return out


def fallback(txn: dict, lang: str, error: str | None = None) -> dict:
    factors = txn.get("factors", [])
    top = ", ".join(f["label"].lower() for f in factors[:3]) or "a combination of weak signals"
    action = txn["action"]
    return {
        "verdict": action,
        "reason": f"Risk {txn['risk']:.2f} driven mainly by {top}.",
        "customer_message": policy.customer_message(action, lang, txn["amount"], txn["receiver_vpa"]),
        "analyst_note": "; ".join(f"{f['label']}={_fmt(f['value'])} (+{f['contribution']:.2f})" for f in factors[:4]),
        "source": "fallback",
        "model": None,
        "tool_calls": [],
        "error": error,
    }


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


async def investigate(txn: dict, lang: str, tools: dict[str, Callable]) -> dict:
    if not available():
        return fallback(txn, lang, "GEMINI_API_KEY not set")
    try:
        runner = _gemini if provider() == "gemini" else _ollama
        result = await asyncio.wait_for(runner(txn, lang, tools), timeout=TIMEOUT_S)
        return result
    except asyncio.TimeoutError:
        return fallback(txn, lang, f"timed out after {TIMEOUT_S:.0f}s")
    except Exception as exc:  # any provider failure must not break the stream
        return fallback(txn, lang, f"{type(exc).__name__}: {str(exc)[:160]}")


def _call_tool(tools, name, args, log):
    fn = tools.get(name)
    result = fn(**args) if fn else {"error": f"unknown tool {name}"}
    log.append({"name": name, "args": args})
    return result


async def _gemini(txn: dict, lang: str, tools: dict[str, Callable]) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    decls = [types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=t["parameters"]) for t in TOOL_SPECS]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=decls)],
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=_prompt(txn, lang))])]
    log: list = []
    for _ in range(4):
        resp = await client.aio.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
        calls = resp.function_calls or []
        if not calls:
            out = _extract_json(resp.text or "")
            return {**out, "source": "gemma", "model": GEMINI_MODEL, "tool_calls": log, "error": None}
        contents.append(resp.candidates[0].content)
        parts = [types.Part.from_function_response(name=c.name, response={"result": _call_tool(tools, c.name, dict(c.args or {}), log)})
                 for c in calls]
        contents.append(types.Content(role="user", parts=parts))
    raise RuntimeError("too many tool rounds")


async def _ollama(txn: dict, lang: str, tools: dict[str, Callable]) -> dict:
    messages = [{"role": "user", "content": _prompt(txn, lang)}]
    tool_defs = [{"type": "function", "function": t} for t in TOOL_SPECS]
    log: list = []
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for _ in range(4):
            r = await client.post(f"{OLLAMA_HOST}/api/chat", json={
                "model": OLLAMA_MODEL, "messages": messages, "tools": tool_defs, "stream": False,
                "options": {"temperature": 0.2},
            })
            r.raise_for_status()
            msg = r.json()["message"]
            calls = msg.get("tool_calls") or []
            if not calls:
                out = _extract_json(msg.get("content", ""))
                return {**out, "source": "gemma", "model": OLLAMA_MODEL, "tool_calls": log, "error": None}
            messages.append(msg)
            for c in calls:
                fn = c["function"]
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args)
                messages.append({"role": "tool", "tool_name": fn["name"],
                                 "content": json.dumps(_call_tool(tools, fn["name"], args, log))})
    raise RuntimeError("too many tool rounds")


VISION_PROMPT = (
    "This image is a screenshot of a payment request, UPI collect request, QR payment page or SMS/chat message "
    "received by an Indian mobile user. Read it carefully and reply with ONLY a JSON object with keys:\n"
    '  "payee": the VPA, phone number or name being paid, or null,\n'
    '  "amount": the rupee amount as a number, or null,\n'
    '  "urgency": "low", "medium" or "high",\n'
    '  "pressure_cues": list of short phrases quoted or paraphrased from the image that pressure the reader,\n'
    '  "scam_signals": list of short descriptions of scam indicators (e.g. impersonation, refund trick, KYC threat, collect request disguised as receiving money),\n'
    '  "risk_contribution": a number from 0 to 1 for how much this evidence should raise the risk of paying,\n'
    '  "summary": one sentence in {lang}.'
)


def _vision_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text.strip(), re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    d = json.loads(m.group(0))
    rc = float(d.get("risk_contribution") or 0)
    amount = d.get("amount")
    try:
        amount = float(str(amount).replace(",", "").replace("₹", "")) if amount not in (None, "") else None
    except ValueError:
        amount = None
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
    if not available():
        raise RuntimeError("Screenshot scanning needs Gemma: set GEMINI_API_KEY or LLM_PROVIDER=ollama")
    prompt = VISION_PROMPT.replace("{lang}", LANG_NAMES.get(lang, "English"))

    async def run():
        if provider() == "gemini":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            resp = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=[types.Content(role="user", parts=[types.Part.from_bytes(data=data, mime_type=mime),
                                                             types.Part.from_text(text=prompt)])],
                config=types.GenerateContentConfig(temperature=0.1),
            )
            return _vision_json(resp.text or "")
        async with httpx.AsyncClient(timeout=VISION_TIMEOUT_S) as client:
            r = await client.post(f"{OLLAMA_HOST}/api/chat", json={
                "model": OLLAMA_MODEL, "stream": False,
                "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(data).decode()]}],
            })
            r.raise_for_status()
            return _vision_json(r.json()["message"]["content"])

    result = await asyncio.wait_for(run(), timeout=VISION_TIMEOUT_S)
    return {**result, "model": model_name()}
