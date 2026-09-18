#!/usr/bin/env python3
"""
Capture demo presentation screenshots from the live RMP workspace.

Requires: pip install playwright && playwright install chromium
Server must be running: uvicorn server:app --host 127.0.0.1 --port 8000

Usage:
  python scripts/capture_demo_screenshots.py
  python scripts/capture_demo_screenshots.py --mission-id test1 --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_OUT = PROJECT_ROOT / "output" / "demo" / "screenshots"
DEFAULT_MISSION = "test1"
SHOTS = [
    ("01_rmp_editor.png", "RMP document editor with seeded content"),
    ("02_rmp_workspace_full.png", "Full workspace including toolbar and right rail"),
]


def _session_cookie_for_admin() -> tuple[str, str]:
    from src.auth_service import create_session, get_user_by_login_id

    user = get_user_by_login_id("admin")
    if not user:
        raise SystemExit("Admin user not found. Log in once via UI or bootstrap auth.")
    token, _exp = create_session(user["id"])
    return "session", token


def capture(base_url: str, mission_id: str, out_dir: Path) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright required: pip install playwright && playwright install chromium"
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    cookie_name, cookie_value = _session_cookie_for_admin()
    url = f"{base_url.rstrip('/')}/#/mission/{mission_id}/rmp"
    written: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        context.add_cookies(
            [
                {
                    "name": cookie_name,
                    "value": cookie_value,
                    "url": base_url.rstrip("/"),
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)

        # Editor-focused crop
        editor = page.locator(".report-workspace").first
        if editor.count():
            path1 = out_dir / SHOTS[0][0]
            editor.screenshot(path=str(path1))
            written.append(path1)
            print(f"Wrote {path1} — {SHOTS[0][1]}")
        else:
            path1 = out_dir / SHOTS[0][0]
            page.screenshot(path=str(path1), full_page=False)
            written.append(path1)
            print(f"Wrote {path1} (fallback full viewport)")

        path2 = out_dir / SHOTS[1][0]
        page.screenshot(path=str(path2), full_page=True)
        written.append(path2)
        print(f"Wrote {path2} — {SHOTS[1][1]}")

        browser.close()

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture demo RMP screenshots")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mission-id", default=DEFAULT_MISSION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    capture(args.base_url, args.mission_id, args.out_dir)


if __name__ == "__main__":
    main()
