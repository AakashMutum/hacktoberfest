import asyncio

import pytest

from backend import investigator as inv

TXN = {"txn_id": "T1", "sender_vpa": "a@ybl", "receiver_vpa": "b@ybl", "amount": 45000.0, "hour": 2,
       "risk": 0.91, "action": "block", "factors": [{"label": "First-time payee", "value": 1.0, "contribution": 2.1}]}
TOOLS = {"get_risk_factors": lambda txn_id: {"risk": 0.91},
         "get_account_history": lambda vpa: {"vpa": vpa},
         "get_graph_neighbours": lambda vpa: {"vpa": vpa}}
ANSWER = {"verdict": "block", "reason": "New payee at 2am.", "customer_message": "We stopped this payment.", "analyst_note": "night, new payee"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def reset_tools():
    inv._no_tools.clear()
    inv._tool_failures.clear()
    yield
    inv._no_tools.clear()
    inv._tool_failures.clear()


def test_no_provider_gives_labelled_template():
    r = inv.fallback(TXN, "en", "no model provider reachable")
    assert r["source"] == "fallback"
    assert r["label"] == "Template (model unavailable)"
    assert r["mode"] is None and r["provider"] is None


def test_unreachable_resolution_falls_back(monkeypatch):
    async def none():
        return None
    monkeypatch.setattr(inv, "resolve_provider", none)
    r = run(inv.investigate(TXN, "ta", TOOLS))
    assert r["source"] == "fallback" and r["message_source"] == "template"
    assert inv.in_script(r["customer_message"], "ta")


def test_function_calling_label(monkeypatch):
    async def fc(provider, txn, lang, tools):
        return dict(ANSWER), [{"name": "get_risk_factors", "args": {"txn_id": "T1"}}]
    monkeypatch.setattr(inv, "_function_calling", fc)
    r = run(inv.investigate(TXN, "en", TOOLS, provider="ollama"))
    assert r["source"] == "model" and r["mode"] == "function_calling"
    assert r["label"] == "Gemma 4 E4B · local · function calling"


def test_tool_rejection_switches_to_context_injection(monkeypatch):
    async def fc(*a):
        raise ValueError("tools not supported")

    async def ci(provider, txn, lang, tools):
        return dict(ANSWER)
    monkeypatch.setattr(inv, "_function_calling", fc)
    monkeypatch.setattr(inv, "_context_injection", ci)
    r = run(inv.investigate(TXN, "en", TOOLS, provider="gemini"))
    assert r["mode"] == "context_injection"
    assert r["label"] == "Gemma 4 26B · Gemini API · context injection"
    assert "tools not supported" in r["mode_note"]
    assert "gemini" not in inv._no_tools
    run(inv.investigate(TXN, "en", TOOLS, provider="gemini"))
    assert "gemini" in inv._no_tools


def test_wrong_script_uses_template_message(monkeypatch):
    async def fc(provider, txn, lang, tools):
        return dict(ANSWER), []
    monkeypatch.setattr(inv, "_function_calling", fc)
    r = run(inv.investigate(TXN, "hi", TOOLS, provider="ollama"))
    assert r["source"] == "model" and r["message_source"] == "template"
    assert inv.in_script(r["customer_message"], "hi")


def test_timeout_is_labelled_fallback(monkeypatch):
    async def slow(*a):
        await asyncio.sleep(5)
    monkeypatch.setattr(inv, "_function_calling", slow)
    monkeypatch.setattr(inv, "timeout_for", lambda p: 0.05)
    r = run(inv.investigate(TXN, "en", TOOLS, provider="openai_compat"))
    assert r["source"] == "fallback" and "timed out" in r["error"]


def test_parse_answer_validates():
    with pytest.raises(ValueError):
        inv.parse_answer('{"verdict": "explode", "reason": "x", "customer_message": "y", "analyst_note": "z"}')
    assert inv.parse_answer('Sure: {"verdict": "Hold", "reason": "x", "customer_message": "y", "analyst_note": "z"}')["verdict"] == "hold"


def test_replayed_keeps_provenance():
    original = {**ANSWER, "source": "model", "label": "Gemma 4 26B · Gemini API · function calling"}
    r = inv.replayed(original)
    assert r["replayed"] is True
    assert r["label"] == "Gemma 4 26B · Gemini API · function calling · replayed from cache"
    assert r["reason"] == original["reason"]


def test_safe_mode_never_queues(engine):
    engine.reset()
    rec = next(r for r in iter(lambda: engine.next_batch(), None) for r in r if r["action"] in ("hold", "block"))
    engine.safe_mode = True
    try:
        reply = engine.request_investigation(rec["txn_id"], "en")
        assert reply["status"] == "done"
        assert reply["result"]["source"] == "fallback" or reply["result"].get("replayed")
        assert not engine.pending
    finally:
        engine.safe_mode = False
        engine.reset()


def test_transient_server_error_does_not_disable_tools(monkeypatch):
    class ServerError(Exception):
        code = 500

    async def fc(*a):
        raise ServerError("internal")

    async def ci(provider, txn, lang, tools):
        return dict(ANSWER)
    monkeypatch.setattr(inv, "_function_calling", fc)
    monkeypatch.setattr(inv, "_context_injection", ci)
    r = run(inv.investigate(TXN, "en", TOOLS, provider="gemini"))
    assert r["mode"] == "context_injection"
    assert "gemini" not in inv._no_tools
