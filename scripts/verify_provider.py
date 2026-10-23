"""Run one real investigation and one real screenshot scan against the configured provider."""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from backend import investigator  # noqa: E402
from backend.engine import Engine  # noqa: E402


async def main():
    provider = await investigator.resolve_provider()
    print("resolved provider:", provider, "| model:", investigator.model_for(provider) if provider else None)
    if provider is None:
        print("No provider reachable. Nothing to verify.")
        return 1
    warm = await investigator.warm_up()
    print("warm-up:", json.dumps(warm))

    e = Engine(seed=42)
    rec = None
    while rec is None:
        for r in e.next_batch():
            if r["action"] == "block":
                rec = r
                break
    print(f"\ninvestigating {rec['txn_id']}: {rec['sender_vpa']} -> {rec['receiver_vpa']} Rs {rec['amount']:,.0f} risk {rec['risk']:.3f}")
    for lang in ("en", "ta"):
        res = await investigator.investigate(rec, lang, e.tools())
        print(json.dumps({k: res[k] for k in ("source", "provider", "model", "mode", "label", "latency_ms", "message_source", "error")}, ensure_ascii=False))
        print(json.dumps({k: res[k] for k in ("verdict", "reason", "customer_message", "analyst_note")}, ensure_ascii=False, indent=1))
        print("tools called:", [c["name"] for c in res["tool_calls"]])

    img = os.path.join(ROOT, "docs", "sample-scam-sms.png")
    with open(img, "rb") as f:
        data = f.read()
    try:
        scan = await investigator.scan_image(data, "image/png", "en")
        print("\nscan:", json.dumps(scan, ensure_ascii=False, indent=1))
    except Exception as exc:
        print("\nscan FAILED:", type(exc).__name__, str(exc)[:300])
    return 0


sys.exit(asyncio.run(main()))
