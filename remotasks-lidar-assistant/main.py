"""Orchestrate browser capture, cuboid analysis, and the local overlay."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import config
from browser_engine import LidarBrowser
from overlay import start_overlay_thread
from pcd_parser import PointCloudAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("lidar.main")


def analyze_frame(path: Path) -> list[dict]:
    analyzer = PointCloudAnalyzer(path)
    cuboids = analyzer.extract_object_cuboids()
    dest = analyzer.write_summary(cuboids)
    print(json.dumps({"source": str(path), "object_count": len(cuboids), "cuboids": cuboids}, indent=2))
    logger.info("Wrote %s", dest)
    return cuboids


def watch_captures(browser: LidarBrowser, stop_after: float | None = None) -> None:
    seen_mtime: float | None = None
    started = time.monotonic()
    latest = config.LATEST_FRAME
    logger.info("Waiting for captured frames in %s", config.DEBUG_CAPTURES)
    logger.info("Log in manually in the Playwright window, then open a LiDAR Lite task.")
    while True:
        if latest.exists():
            mtime = latest.stat().st_mtime
            if seen_mtime is None or mtime > seen_mtime:
                seen_mtime = mtime
                try:
                    analyze_frame(latest)
                except Exception:
                    logger.exception("Analysis failed for %s", latest)
        if stop_after is not None and (time.monotonic() - started) >= stop_after:
            break
        time.sleep(config.POLL_INTERVAL_SEC)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remotasks LiDAR Lite local annotation assistant")
    parser.add_argument("--url", default=config.PORTAL_URL, help="Task portal URL")
    parser.add_argument("--headless", action="store_true", help="Launch without a visible window")
    parser.add_argument("--no-overlay", action="store_true", help="Do not start the localhost Three.js overlay")
    parser.add_argument(
        "--analyze-only",
        type=Path,
        help="Skip the browser and analyze an existing .pcd/.bin/.json file",
    )
    parser.add_argument("--watch-seconds", type=float, default=None, help="Stop the watch loop after N seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config.DEBUG_CAPTURES.mkdir(parents=True, exist_ok=True)

    if args.analyze_only is not None:
        analyze_frame(args.analyze_only)
        return 0

    if not args.no_overlay:
        start_overlay_thread()
        logger.info("Overlay: http://%s:%s", config.OVERLAY_HOST, config.OVERLAY_PORT)

    browser = LidarBrowser(headless=args.headless)
    try:
        browser.launch()
        browser.goto(args.url)
        watch_captures(browser, stop_after=args.watch_seconds)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    finally:
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
