#!/usr/bin/env python3
"""Capture the Production Orchestrator demo as 1080p segments via headless
Chromium. Correct Playwright video pattern: close the page/context first,
then save_as names the recorded file."""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path("/tmp/po-captures")
OUT.mkdir(exist_ok=True)
CHROMIUM = "/home/jamessesler/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"

def record_shot(browser, name: str, actions) -> str:
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(OUT),
        record_video_size={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    page.goto(BASE)
    actions(page)
    page.close()
    video = ctx.videos[0] if hasattr(ctx, "videos") and ctx.videos else page.video
    path = str(OUT / f"shot-{name}.webm")
    video.save_as(path)
    ctx.close()
    print("saved", path)
    return path

def start_rush(page, settle_ms=7000):
    page.wait_for_timeout(1500)
    try:
        page.click("text=Rush order", timeout=4000)
    except Exception as e:
        print("scenario click failed:", e)
    page.wait_for_timeout(settle_ms)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)

    # X: scenario chips on the landing state
    record_shot(browser, "X-chips", lambda pg: pg.wait_for_timeout(3000))

    # B: intake card + first feed rows
    def shot_b(pg):
        start_rush(pg)
    record_shot(browser, "B-intake", shot_b)

    # C: production board with the conflict visible
    def shot_c(pg):
        start_rush(pg)
        try:
            pg.locator("text=Production board").scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        pg.wait_for_timeout(2000)
    record_shot(browser, "C-board", shot_c)

    # D: interrupt row + technical proof expansion (proposal hash)
    def shot_d(pg):
        start_rush(pg)
        for label in ("Technical proof", "Holding the write", "Stopped at a real Strands interrupt"):
            try:
                pg.click(f"text={label}", timeout=2500)
                break
            except Exception:
                continue
        pg.wait_for_timeout(2500)
    record_shot(browser, "D-interrupt", shot_d)

    # E: reject path
    def shot_e(pg):
        start_rush(pg)
        try:
            pg.click("text=Keep current schedule", timeout=5000)
        except Exception as e:
            print("reject click failed:", e)
        pg.wait_for_timeout(5000)
    record_shot(browser, "E-reject", shot_e)

    # F: approve path
    def shot_f(pg):
        start_rush(pg)
        try:
            pg.click("text=Approve coordinated plan", timeout=5000)
        except Exception as e:
            print("approve click failed:", e)
        pg.wait_for_timeout(6000)
    record_shot(browser, "F-approve", shot_f)

    browser.close()

print("done")
for f in sorted(Path(OUT).glob("shot-*.webm")):
    print(f.name, f.stat().st_size)