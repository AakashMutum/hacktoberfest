"""Failure drills: invalid API key, no internet, a slow model and a closed WebSocket.

Each drill starts its own server on a spare port with a broken provider, then checks the API
and the page: a clear status, a labelled fallback, and no raw exception text anywhere.
Usage: .venv\\Scripts\\python scripts\\failure_drills.py
"""
import io
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright
from websockets.sync.client import connect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
RAW = ("Traceback", "ClientError", "API key not valid", "API_KEY_INVALID", "Failed to fetch", "RESOURCE_EXHAUSTED",
       "ConnectError", "ProxyError", "ReadTimeout", "Internal Server Error", "NetworkError")
results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}", flush=True)


class SlowModel(BaseHTTPRequestHandler):
    """An OpenAI-compatible endpoint that takes 15 s to answer."""

    def do_POST(self):
        time.sleep(15)
        body = json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *a):
        pass


def start_server(port: int, env_overrides: dict) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER")}
    env.update({"HOST": "127.0.0.1", "PORT": str(port), "PYTHONIOENCODING": "utf-8"}, **env_overrides)
    proc = subprocess.Popen([PY, "-m", "backend"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(90):
        try:
            h = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2).json()
            if h["llm"]["state"] != "loading":
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(1)
    proc.kill()
    raise RuntimeError(f"server on {port} did not start")


def uncached_image() -> bytes:
    img = Image.open(os.path.join(ROOT, "docs", "sample-scam-sms.png")).convert("RGB")
    img.putpixel((1, 1), (int(time.time()) % 255, 7, 7))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def flagged_uncached(port: int, timeout: float = 40) -> str | None:
    cache_path = os.path.join(ROOT, "data", "investigation_cache.json")
    cached = set()
    if os.path.exists(cache_path):
        cached = {k.split("|")[0] for k in json.load(open(cache_path, encoding="utf-8"))}
    httpx.post(f"http://127.0.0.1:{port}/api/stream/control", json={"action": "speed", "speed": 16})
    with connect(f"ws://127.0.0.1:{port}/ws", open_timeout=10) as ws:
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(ws.recv(timeout=5))
            for t in msg.get("txns", []):
                if t["action"] in ("hold", "block") and t["txn_id"] not in cached:
                    httpx.post(f"http://127.0.0.1:{port}/api/stream/control", json={"action": "pause"})
                    return t["txn_id"]
    return None


def investigate(port: int, tid: str, wait: float) -> dict | None:
    with connect(f"ws://127.0.0.1:{port}/ws", open_timeout=10) as ws:
        reply = httpx.post(f"http://127.0.0.1:{port}/api/investigate/{tid}", params={"lang": "en"}, timeout=30).json()
        if reply["status"] == "done":
            return reply["result"]
        end = time.time() + wait
        while time.time() < end:
            try:
                msg = json.loads(ws.recv(timeout=max(0.5, end - time.time())))
            except TimeoutError:
                break
            if msg.get("type") == "investigation" and msg["txn_id"] == tid:
                return msg["result"]
    return None


def page_text_check(port: int, name: str, expect_badge: str, shot: str):
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1366, "height": 768})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}")
        page.wait_for_timeout(3000)
        badge = page.locator(".lamps .lamp").nth(1).inner_text()
        text = page.locator("body").inner_text()
        page.screenshot(path=os.path.join(ROOT, "docs", "drills", shot))
        b.close()
    raw = [r for r in RAW if r in text]
    check(f"{name}: header shows status", expect_badge.lower() in badge.lower(), badge.replace("\n", " "))
    check(f"{name}: no raw error text on page", not raw and not errors, ", ".join(raw + errors))


def drill(name: str, port: int, env: dict, expect_state: str, expect_msg: str, expect_badge: str, wait: float, shot: str):
    print(f"\n== {name} ==", flush=True)
    proc = start_server(port, env)
    try:
        h = httpx.get(f"http://127.0.0.1:{port}/api/health").json()["llm"]
        check(f"{name}: status after warm-up", h["state"] == expect_state and h.get("error") == expect_msg, f"{h['state']} · {h.get('error')}")
        tid = flagged_uncached(port)
        if tid:
            r = investigate(port, tid, wait)
            ok = r is not None and r["source"] == "fallback" and r["label"] == "Template (model unavailable)"
            check(f"{name}: investigation falls back with label", ok, f"{r['label']} · {r['error']}" if r else "no result")
            if r:
                check(f"{name}: no raw text in result", not any(x in json.dumps(r) for x in RAW))
        else:
            check(f"{name}: found an uncached flagged payment", False)
        sr = httpx.post(f"http://127.0.0.1:{port}/api/scan-screenshot", files={"file": ("x.png", uncached_image(), "image/png")}, timeout=60)
        check(f"{name}: scan gives a short message", sr.status_code in (503, 504) and not any(x in sr.text for x in RAW), f"HTTP {sr.status_code} {sr.json().get('detail')}")
        page_text_check(port, name, expect_badge, shot)
    finally:
        proc.kill()


def ws_drill(port: int):
    print("\n== closed WebSocket ==", flush=True)
    proc = start_server(port, {"LLM_PROVIDER": "gemini"})
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1366, "height": 768})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}")
        page.wait_for_timeout(3000)
        proc.kill()
        proc.wait()
        page.wait_for_timeout(2500)
        lamp = page.locator(".lamps .lamp").first.inner_text()
        check("closed WebSocket: header says connection lost", "connection lost" in lamp.lower(), lamp.replace("\n", " "))
        page.get_by_role("button", name="Reset").click()
        page.locator("button", has_text="Launch attack").click()
        page.wait_for_timeout(1500)
        t0 = time.time()
        page.evaluate("1 + 1")
        check("closed WebSocket: page still responsive", time.time() - t0 < 1.0, f"{(time.time() - t0) * 1000:.0f} ms")
        text = page.locator("body").inner_text()
        raw = [r for r in RAW if r in text]
        check("closed WebSocket: actions show a plain message", "server is not reachable" in text and not raw, ", ".join(raw) or "plain message shown")
        page.screenshot(path=os.path.join(ROOT, "docs", "drills", "ws-closed.png"))
        proc = start_server(port, {"LLM_PROVIDER": "gemini"})
        page.wait_for_timeout(4000)
        lamp = page.locator(".lamps .lamp").first.inner_text()
        check("closed WebSocket: reconnects when the server returns", lamp.lower().startswith("live") or "paused" in lamp.lower(), lamp.replace("\n", " "))
        check("closed WebSocket: no page errors", not errors, "; ".join(errors))
        b.close()
    proc.kill()


def main() -> int:
    os.makedirs(os.path.join(ROOT, "docs", "drills"), exist_ok=True)
    slow = ThreadingHTTPServer(("127.0.0.1", 8765), SlowModel)
    threading.Thread(target=slow.serve_forever, daemon=True).start()
    drill("invalid API key", 8101, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "invalid-key-for-drill"},
          "offline", "model provider rejected the API key", "rejected the API key", 15, "invalid-key.png")
    drill("no internet", 8102, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "drill-key", "HTTPS_PROXY": "http://127.0.0.1:9",
                                "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"},
          "offline", "model provider unreachable (network)", "unreachable", 15, "no-internet.png")
    drill("slow model", 8103, {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://127.0.0.1:8765/v1", "LLM_MODEL": "gemma-4"},
          "slow", "model did not answer within 10 s", "did not answer", 30, "slow-model.png")
    ws_drill(8104)
    slow.shutdown()
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} drill checks passed.")
    if failed:
        print("Failed: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
