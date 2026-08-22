"""Runs the focus-survival regression pages under a real browser.

These are DOM/timing bugs in the card's own guard logic, not something the
Python test suite (which never loads a browser) can see. Each page wraps
the real settings card inside a synthetic `hui-card` shadow root - exactly
how Home Assistant hosts every custom card - and drives a scenario that
lost user input before the fix in `_isEditingField()`.

    docker run --rm -v "$PWD:/repo" -w /repo mcr.microsoft.com/playwright/python:latest \
        python tests/frontend/run.py

Exits non-zero if any page fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

PAGES = [
    "focus_survives_frequent_hass_updates.html",
    "focus_survives_timer_collision.html",
]


def main() -> int:
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in PAGES:
            page = browser.new_page()
            page.goto((HERE / name).as_uri())
            page.wait_for_function(
                "document.title === 'PASS' || document.title === 'FAIL'", timeout=15000
            )
            result = page.evaluate("window.RESULT")
            ok = page.title() == "PASS"
            print(f"{'PASS' if ok else 'FAIL'}  {name}  {result}")
            if not ok:
                failures.append(name)
            page.close()
        browser.close()

    if failures:
        print(f"\n{len(failures)} of {len(PAGES)} failed: {', '.join(failures)}")
        return 1
    print(f"\nAll {len(PAGES)} passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
