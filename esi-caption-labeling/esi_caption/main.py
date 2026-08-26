"""Attach to an already-open IX or MoreLogin profile and label the MultiMango task."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .task import run_labeling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hierarchical egocentric caption labeling on an already-open antidetect profile."
    )
    parser.add_argument(
        "--browser",
        choices=("ix", "morelogin"),
        default="ix",
        help="Which already-open profile family to attach to.",
    )
    parser.add_argument("--cdp-url", default="", help="Optional DevTools http://127.0.0.1:PORT")
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Fill L3/L2/L1 but do not click Submit Captions.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_labeling(
            args.browser,
            submit=not args.no_submit,
            cdp_url=args.cdp_url or None,
        )
    except KeyboardInterrupt:
        print("\n[esi] stopped (browser window left open)", flush=True)
        return 0
    except Exception as exc:
        print(f"[esi] failed: {exc}", flush=True)
        return 1
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
