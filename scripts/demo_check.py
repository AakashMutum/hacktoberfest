"""Exercise every endpoint of a running Circuit Breaker server and report clearly what works.

Usage: .venv\\Scripts\\python scripts\\demo_check.py [base_url]
Exit code 0 when every required check passes. Model checks are required only when a provider is ready.
"""
import io
import json
import os
import sys
import time

import httpx
from PIL import Image
from websockets.sync.client import connect

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
WS = BASE.replace("http", "ws", 1) + "/ws"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "docs", "sample-scam-sms.png")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}", flush=True)
    return ok


def wait_ws(ws, pred, timeout: float):
    end = time.time() + timeout
    while time.time() < end:
        try:
            msg = json.loads(ws.recv(timeout=max(0.1, end - time.time())))
        except TimeoutError:
            break
        hit = pred(msg)
        if hit:
            return hit
    return None


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=90)
    try:
        h = c.get("/api/health").json()
    except httpx.HTTPError as exc:
        print(f"Cannot reach {BASE}: {exc}. Start the server first (scripts\\run_demo.ps1).")
        return 2
    llm = h["llm"]
    # A configured provider is expected to answer; warm-up state alone can lag behind a transient error.
    model_expected = llm.get("provider") is not None
    check("GET /api/health", h.get("ok") is True,
          f"provider={llm.get('provider')} model={llm.get('model')} state={llm.get('state')}" + (f" error={llm.get('error')}" if llm.get("error") else ""))
    check("GET /api/copy", set(c.get("/api/copy").json()["copy"]) == {"en", "ta", "hi"})
    c.post("/api/safe-mode", json={"enabled": False})
    check("POST /api/stream/control reset", c.post("/api/stream/control", json={"action": "reset"}).status_code == 200)
    check("POST /api/stream/control speed", c.post("/api/stream/control", json={"action": "speed", "speed": 16}).json()["speed"] == 16)

    with connect(WS, open_timeout=10) as ws:
        flagged = wait_ws(ws, lambda m: next((t for t in m.get("txns", []) if t["action"] in ("hold", "block")), None), 30)
        if not check("WS /ws stream delivers a flagged payment", flagged is not None):
            return summary()
        tid = flagged["txn_id"]
        check("GET /api/metrics", c.get("/api/metrics").json()["circuit_breaker"]["seen"] > 0)
        check("GET /api/txn/{id}", c.get(f"/api/txn/{tid}").json()["txn_id"] == tid)
        g = c.get(f"/api/graph/{tid}").json()
        check("GET /api/graph/{id}", len(g["nodes"]) > 1, f"{len(g['nodes'])} nodes, {g['suspect_count']} suspects")
        check("POST /api/stream/control pause", c.post("/api/stream/control", json={"action": "pause"}).json()["running"] is False)

        reply = c.post(f"/api/investigate/{tid}", params={"lang": "en"}).json()
        result = reply.get("result")
        if reply["status"] == "pending":
            wait_for = 75 if llm.get("provider") == "ollama" else 20
            msg = wait_ws(ws, lambda m: m if m.get("type") == "investigation" and m["txn_id"] == tid else None, wait_for)
            result = msg["result"] if msg else None
        if check("POST /api/investigate/{id}", result is not None, result["label"] if result else "no result over WebSocket"):
            if model_expected:
                check("investigation came from the model", result["source"] == "model",
                      f"{result['label']} in {result['latency_ms'] / 1000:.1f} s" if result["source"] == "model" else f"fallback: {result.get('error')}")
            else:
                check("investigation fallback is labelled", result["label"] == "Template (model unavailable)")

    check("POST /api/lang/ta", c.post("/api/lang/ta").json()["lang"] == "ta")
    c.post("/api/lang/en")

    # A one-pixel change gives an image the cache has never seen, so this exercises a live model call.
    img = Image.open(SAMPLE).convert("RGB")
    img.putpixel((0, 0), (int(time.time()) % 256, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = c.post("/api/scan-screenshot", files={"file": ("sample.png", buf.getvalue(), "image/png")}, data={"lang": "en"})
    if model_expected:
        ok = r.status_code == 200
        ok = ok and not r.json().get("replayed")
        check("POST /api/scan-screenshot (live, not from cache)", ok, f"{r.json()['label']} in {r.json()['latency_ms'] / 1000:.1f} s, payee={r.json()['payee']}" if ok else r.text[:200])
    else:
        check("POST /api/scan-screenshot reports unavailable", r.status_code == 503, r.json().get("detail", "")[:120])

    big = b"\0" * (7 * 1024 * 1024)
    try:
        r = c.post("/api/scan-screenshot", files={"file": ("big.png", big, "image/png")})
        check("oversized upload rejected", r.status_code == 413, f"HTTP {r.status_code}")
    except httpx.HTTPError as exc:
        check("oversized upload rejected", False, f"connection error: {type(exc).__name__}")

    sm = c.post("/api/safe-mode", json={"enabled": True}).json()
    check("POST /api/safe-mode", sm["enabled"] is True, f"{sm['cached_results']} cached results")
    c.post("/api/safe-mode", json={"enabled": False})

    a = c.post("/api/redteam/attack").json()
    check("POST /api/redteam/attack", a["injected"] > 0, f"breaker {a['cb_rate']:.1%}, rules A {a['rules_rate']:.1%}, rules B {a['tight_rate']:.1%}")
    ad = c.post("/api/redteam/adapt").json()
    check("POST /api/redteam/adapt", ad["after"]["rate"] > ad["before"]["rate"],
          f"{ad['before']['rate']:.1%} -> {ad['after']['rate']:.1%} in {ad['train_seconds']:.1f} s")
    check("GET /api/redteam", len(c.get("/api/redteam").json()["attacks"]) >= 1)
    check("GET /api/llm-status", "state" in c.get("/api/llm-status").json())
    c.post("/api/stream/control", json={"action": "reset"})
    c.post("/api/stream/control", json={"action": "speed", "speed": 1})
    return summary()


def summary() -> int:
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        print("Failed: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
