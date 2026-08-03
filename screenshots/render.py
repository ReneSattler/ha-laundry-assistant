"""Render the README screenshots from screenshots/demo.html.

Kept in the repo so the screenshots stay reproducible instead of being
one-off artifacts nobody can regenerate - a stale screenshot showing an
older UI is its own kind of wrong documentation.

Usage (any environment with playwright installed):

    pip install playwright && playwright install chromium
    python screenshots/render.py

Or without installing anything locally:

    docker run --rm -v "$PWD:/repo" -w /repo \
      mcr.microsoft.com/playwright/python:latest \
      python screenshots/render.py

Each entry below maps a demo.html query string to an output file. The demo
page renders the real card code with a mocked hass object, so what lands in
the PNG is what Home Assistant would show - minus the icons, which are
emoji stand-ins here because MDI is part of the frontend bundle.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DEMO_URL = (HERE / "demo.html").as_uri()

# (output file, query string). The demo frame is 420px wide plus 32px of
# body padding on each side.
WIDTH = 484
SHOTS = [
    ("cards-running-en.png", "?scenario=running&lang=en"),
    ("cards-idle-en.png", "?scenario=idle&lang=en"),
    ("cards-running-de.png", "?scenario=running&lang=de"),
    ("cards-idle-de.png", "?scenario=idle&lang=de"),
    ("cards-anomaly-en.png", "?scenario=anomaly&lang=en"),
    ("cards-anomaly-de.png", "?scenario=anomaly&lang=de"),
]


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for filename, query in SHOTS:
            page = browser.new_page(
                viewport={"width": WIDTH, "height": 900},
                device_scale_factor=2,  # crisp on high-DPI displays
            )
            page.goto(DEMO_URL + query)
            # The cards render synchronously once the script has run, but
            # give layout a beat so nothing is captured mid-reflow.
            page.wait_for_selector("laundry-assistant-settings-card ha-card")
            page.wait_for_timeout(600)
            page.screenshot(path=str(HERE / filename), full_page=True)
            print(f"wrote {filename}")
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
