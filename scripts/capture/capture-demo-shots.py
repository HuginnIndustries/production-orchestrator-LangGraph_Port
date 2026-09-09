#!/usr/bin/env python3
"""Capture Production Orchestrator demo shots for the submission video.

Fixes over v1:
- NO scenario click: app.js boot() auto-runs rush-order; clicking the chip
  re-triggers newScenario() and resets to the spinner (the "falls back to
  front page" bug).
- Each shot is ONE continuous recording >= its narration length; assembly
  must NOT -stream_loop (the "same first screen repeats" bug).
- device_scale_factor=2 + record_video_size 3840x2160: supersampled VP8 so
  the 1080p downscale is crisp (v1's 850 kbps 1080p source read as 480p).
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path("/tmp/po-captures-4k")
OUT.mkdir(exist_ok=True)
CHROMIUM = "/home/jamessesler/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"

def record(browser, name, actions):
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=2,
        record_video_dir=str(OUT),
        record_video_size={"width": 3840, "height": 2160},
    )
    page = ctx.new_page()
    page.goto(BASE)
    actions(page)
    page.close()  # video must be closed-page before save_as
    path = str(OUT / f"shot-{name}.webm")
    page.video.save_as(path)
    ctx.close()
    print("saved", path)

def wait_rendered(page):
    """Wait until the run has rendered the decision buttons (run finished)."""
    page.wait_for_selector("text=Keep current schedule", timeout=30000)
    page.wait_for_timeout(1500)  # settle animations

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)

    def shot_b(pg):
        wait_rendered(pg); pg.wait_for_timeout(31000)
    record(browser, "B-intake", shot_b)

    def shot_c(pg):
        wait_rendered(pg)
        pg.locator("text=Production board").scroll_into_view_if_needed(timeout=5000)
        pg.wait_for_timeout(2000); pg.wait_for_timeout(25000)
    record(browser, "C-board", shot_c)

    def shot_d(pg):
        wait_rendered(pg)
        pg.click("text=Technical proof", timeout=5000)
        pg.wait_for_timeout(4000); pg.wait_for_timeout(14000)
    record(browser, "D-interrupt", shot_d)

    def shot_e(pg):
        wait_rendered(pg)
        pg.click("text=Keep current schedule", timeout=5000)
        pg.wait_for_timeout(9000)
    record(browser, "E-reject", shot_e)

    def shot_f(pg):
        wait_rendered(pg)
        pg.click("text=Approve coordinated plan", timeout=5000)
        pg.wait_for_timeout(9000)
    record(browser, "F-approve", shot_f)

    browser.close()
print("done")