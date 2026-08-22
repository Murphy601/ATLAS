"""Attach to the IX Browser tab you opened and work the EGO task on screen."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config
from browser_engine import LidarBrowser
from caption_engine import lint_subgoal
from ego_task import apply_caption_fixes, play_open_video, read_clips, run_quality_assistant
from overlay import start_overlay_thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("ego.main")


def analyze_frame(path: Path) -> list[dict]:
    from pcd_parser import PointCloudAnalyzer

    analyzer = PointCloudAnalyzer(path)
    cuboids = analyzer.extract_object_cuboids()
    dest = analyzer.write_summary(cuboids)
    print(json.dumps({"source": str(path), "object_count": len(cuboids), "cuboids": cuboids}, indent=2))
    logger.info("Wrote %s", dest)
    return cuboids


def _write_report(payload: dict) -> Path:
    dest = config.ANALYSIS_RESULT
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def run_ego_task(write: bool, run_linters: bool, cdp_url: str | None) -> dict:
    logger.info("Open IX Browser yourself, then open the EGO task. The engine will not launch Chrome.")
    browser = LidarBrowser()
    try:
        browser.attach(cdp_url=cdp_url, timeout_s=config.ATTACH_WAIT_SECONDS)
        page = browser.wait_for_task_page(timeout_s=config.TASK_WAIT_SECONDS)
        play_open_video(page)
        clips = [clip.to_dict() for clip in read_clips(page)]
        reports = apply_caption_fixes(page, clips, write=write)
        linter_clicked = run_quality_assistant(page) if run_linters else False
        payload = {
            "mode": "ego",
            "url": page.url,
            "watched_video": True,
            "clip_count": len(clips),
            "wrote_captions": sum(1 for r in reports if r.get("wrote")),
            "quality_assistant": linter_clicked,
            "submitted": False,
            "hte_edited": False,
            "clips": reports,
        }
        dest = _write_report(payload)
        print(json.dumps(payload, indent=2))
        logger.info("Report: %s — IX window left open, task not submitted", dest)
        return payload
    finally:
        browser.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EGO annotation engine: attach to your IX Browser task tab (never launches Chrome)"
    )
    parser.add_argument("--cdp-url", default=None, help="CDP URL (default http://127.0.0.1:9222)")
    parser.add_argument("--dry-run", action="store_true", help="Lint clips but do not type into the page")
    parser.add_argument("--no-linters", action="store_true", help="Do not click Quality Assistant")
    parser.add_argument("--overlay", action="store_true", help="Start the localhost overlay (off by default)")
    parser.add_argument("--no-overlay", action="store_true", help="Deprecated: overlay is already off by default")
    parser.add_argument(
        "--analyze-only",
        type=Path,
        help="Skip the browser and analyze an existing .pcd/.bin/.json file",
    )
    parser.add_argument("--lint-text", default=None, help="Lint a single subgoal caption and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config.DEBUG_CAPTURES.mkdir(parents=True, exist_ok=True)

    if args.lint_text is not None:
        result = lint_subgoal(args.lint_text)
        print(json.dumps({"original": result.original, "rewritten": result.rewritten, "issues": [i.__dict__ for i in result.issues]}, indent=2))
        return 0 if result.ok else 1

    if args.analyze_only is not None:
        analyze_frame(args.analyze_only)
        return 0

    if args.overlay and not args.no_overlay:
        start_overlay_thread()
        logger.info("Overlay: http://%s:%s", config.OVERLAY_HOST, config.OVERLAY_PORT)

    run_ego_task(write=not args.dry_run, run_linters=not args.no_linters, cdp_url=args.cdp_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
