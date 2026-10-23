"""Capture desktop and 390 px screenshots of the running app for visual checks."""
import os
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".shots")
os.makedirs(OUT, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(URL)
    page.wait_for_timeout(6000)
    page.hover(".rail-list")
    page.wait_for_timeout(800)
    flagged = page.locator(".row.block .row-main, .row.hold .row-main").first
    if flagged.count():
        flagged.click()
        page.wait_for_timeout(2500)
    page.screenshot(path=os.path.join(OUT, "desktop.png"))
    m = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    m.on("pageerror", lambda e: errors.append(str(e)))
    m.goto(URL)
    m.wait_for_timeout(4000)
    m.screenshot(path=os.path.join(OUT, "mobile-stream.png"))
    for tab in ("graph", "phone", "score"):
        m.get_by_role("tab", name=tab).click()
        m.wait_for_timeout(1500)
        m.screenshot(path=os.path.join(OUT, f"mobile-{tab}.png"), full_page=True)
    overflow = m.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    print("horizontal overflow at 390px:", overflow)
    print("errors:", errors or "none")
    browser.close()
