"""Run the demo tour headless in Safe mode with all non-local network blocked.

Saves a screenshot per step to docs/tour/ and an animated docs/demo-tour.gif.
Usage: .venv\\Scripts\\python scripts\\tour_check.py [base_url]
"""
import os
import sys

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "tour")
STEPS = 10


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    httpx.post(f"{BASE}/api/safe-mode", json={"enabled": True}, timeout=10)
    problems: list[str] = []
    frames: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(BASE) or route.request.url.startswith("ws://127.0.0.1") else route.abort())
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
        page.goto(BASE)
        page.wait_for_timeout(2500)
        page.get_by_role("button", name="Demo tour").click()
        for i in range(STEPS):
            page.wait_for_timeout(6000 if i in (1, 7, 8) else 3500)
            title = page.locator(".tour h2").inner_text()
            status = page.locator(".tour-status").all_inner_texts()
            path = os.path.join(OUT, f"step-{i + 1:02d}.png")
            page.screenshot(path=path)
            frames.append(path)
            print(f"step {i + 1}: {title}" + (f"  [status: {status[0]}]" if status else ""))
            if status:
                problems.append(f"step {i + 1} status: {status[0]}")
            if i == 3:
                label = page.locator(".row .note .src").first.inner_text()
                print("   explanation label:", label)
                if "replayed from cache" not in label.lower():
                    problems.append(f"step 4 label not a cached model output: {label}")
            if i in (4, 5):
                line = page.locator(".gemma-line").first.inner_text()
                print("   phone label:", line)
                if "replayed from cache" not in line.lower():
                    problems.append(f"step {i + 1} phone message is not cached model output: {line}")
            if i == 7:
                print("   red team:", page.locator("[aria-label='Red team'] .src").all_inner_texts())
            if i == 8:
                scan = page.locator("[aria-label='Screenshot scan'] .src.c-pass").all_inner_texts()
                print("   scan:", scan or page.locator("[aria-label='Screenshot scan'] .err").all_inner_texts())
                if not scan:
                    problems.append("scan step showed no model reading")
            page.keyboard.press("Space")
        page.wait_for_timeout(800)
        if page.locator(".tour").count():
            problems.append("tour did not close after the last step")
        page.get_by_role("button", name="Demo tour").click()
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        if page.locator(".tour").count():
            problems.append("Esc did not close the tour")
        browser.close()
    httpx.post(f"{BASE}/api/safe-mode", json={"enabled": False}, timeout=10)

    images = [Image.open(f).convert("RGB").resize((960, 600)) for f in frames]
    images[0].save(os.path.join(ROOT, "docs", "demo-tour.gif"), save_all=True, append_images=images[1:], duration=2200, loop=0, optimize=True)
    print("\nproblems:", problems or "none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
