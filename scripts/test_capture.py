"""Standalone screenshot diagnostic.

Usage:
    ./.Search/Scripts/python.exe scripts/test_capture.py
    ./.Search/Scripts/python.exe scripts/test_capture.py --url https://www.stats.gov.cn/ --save state/shot.jpg
    ./.Search/Scripts/python.exe scripts/test_capture.py --chrome "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"

Exit code 0 = JPEG captured; 1 = failure (error is printed and also visible in
/api/health.screenshots.last_error after an API research run).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from claimlab.config import load_settings  # noqa: E402
from claimlab.evidence import capture as capture_module  # noqa: E402
from claimlab.evidence.capture import ScreenshotCapturer, detect_chrome  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.chrome:
        settings.screenshot_chrome = args.chrome
    settings.screenshot_enabled = True
    capturer = ScreenshotCapturer(settings)
    print("chrome       :", capturer.chrome or "(not found)")
    print("detected     :", detect_chrome(settings.screenshot_chrome) or "(none)")
    print("websockets   :", "available" if capture_module.websockets else "missing")
    print("enabled      :", capturer.enabled)
    print("reason       :", capturer.reason or "-")
    print("profile_root :", Path(settings.state_dir) / "screenshot-profiles")
    if not capturer.enabled:
        return 1
    shot = await capturer.capture(args.url, args.snippet, timeout_ms=args.timeout_ms)
    print("error        :", shot.error or "-")
    print("bytes        :", len(shot.data))
    print("matched      :", shot.matched)
    if shot.data:
        if args.save:
            Path(args.save).write_bytes(shot.data)
            print("saved        :", args.save)
        return 0
    print("\nNext checks:")
    print("  1. Run this in a normal user PowerShell, not a restricted/sandboxed shell.")
    print("  2. Run Chrome manually: chrome --headless=new --disable-gpu --dump-dom about:blank")
    print("  3. Try Edge with --chrome \"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe\".")
    print("  4. If crashpad reports OpenProcess/access denied, antivirus or sandbox is blocking Chrome.")
    print("  5. Set EVIDENCE_SCREENSHOTS=false while you debug; screenshots are best-effort.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Test headless Chrome screenshot capture")
    parser.add_argument("--url", default="https://www.stats.gov.cn/")
    parser.add_argument("--snippet", default="国家统计局")
    parser.add_argument("--chrome", default="", help="explicit chrome/edge executable")
    parser.add_argument("--timeout-ms", type=int, default=8000)
    parser.add_argument("--save", default="")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
