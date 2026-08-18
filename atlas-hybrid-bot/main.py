#!/usr/bin/env python3
"""CLI for the non-LLM Atlas hybrid annotator (MediaPipe + regex draft surgery)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from hybrid_annotator import AtlasHybridPipeline, DEFAULT_LEXICON
from frame_utils import frames_from_base64_list

load_dotenv()


def _load_segments(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "segments" in payload:
        return payload["segments"]
    raise ValueError("segments JSON must be a list or {\"segments\": [...]}")


def run_video_segments(video: Path, segments_path: Path) -> int:
    segments = _load_segments(segments_path)
    pipeline = AtlasHybridPipeline()
    try:
        for index, seg in enumerate(segments, start=1):
            start = float(seg["start"])
            end = float(seg["end"])
            draft = str(seg.get("draft") or seg.get("draft_label") or "")
            obj = seg.get("object") or seg.get("target_object")
            label = pipeline.process_segment(
                str(video),
                start,
                end,
                draft,
                target_object=obj,
            )
            print(f"[Segment {index}] {start:.2f}s–{end:.2f}s → {label!r}")
    finally:
        pipeline.close()
    return 0


def run_demo() -> int:
    """Regex-only demo (no video / MediaPipe required)."""
    from hybrid_annotator import transform_draft_non_llm

    pipeline = AtlasHybridPipeline()
    segments = [
        {
            "start": 0.0,
            "end": 2.5,
            "draft": "picking up blue package and clothes",
            "object": "glass cleaner pouch",
        },
        {
            "start": 2.5,
            "end": 6.0,
            "draft": "pick up blue package then wipe table",
            "object": "glass cleaner pouch",
        },
    ]
    for seg in segments:
        duration = seg["end"] - seg["start"]
        held = pipeline.state_memory.object_held(seg["object"])
        corrected = pipeline.resolve_state_verbs(
            seg["draft"],
            is_held_from_memory=held,
            start_has_contact=False,
        )
        out = pipeline.lint_atlas_syntax(
            corrected,
            duration,
            "with right hand",
        )
        pipeline.state_memory.update_from_label(
            out,
            "with right hand",
            seg["object"],
        )
        print(f"[{seg['start']}s–{seg['end']}s] {out!r}")

    print("\n[Demo] transform_draft_non_llm (standalone):")
    print(
        transform_draft_non_llm(
            "picking up blue package and clothes",
            2.5,
            "with left hand",
        )
    )
    return 0


def run_frames_json(frames_path: Path, segments_path: Path) -> int:
    """Process base64 JPEG frames from a JSON export (browser integration path)."""
    frames_doc = json.loads(frames_path.read_text(encoding="utf-8"))
    frames_b64 = frames_doc.get("frames") or frames_doc
    arrays = frames_from_base64_list(frames_b64)
    segments = _load_segments(segments_path)
    pipeline = AtlasHybridPipeline()
    try:
        for index, seg in enumerate(segments, start=1):
            label = pipeline.process_frame_batch(
                arrays,
                float(seg["start"]),
                float(seg["end"]),
                str(seg.get("draft") or ""),
                target_object=seg.get("object"),
            )
            print(f"[Segment {index}] → {label!r}")
    finally:
        pipeline.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atlas hybrid annotator — MediaPipe hands + regex (no LLM)."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run regex/state demo without video or MediaPipe.",
    )
    parser.add_argument("--video", type=Path, help="Local MP4 path.")
    parser.add_argument(
        "--segments",
        type=Path,
        help='JSON list: [{"start":0,"end":2.5,"draft":"...","object":"..."}]',
    )
    parser.add_argument(
        "--frames-json",
        type=Path,
        help="JSON file with base64 JPEG frames (integration export).",
    )
    args = parser.parse_args(argv)

    if args.demo:
        return run_demo()
    if args.video and args.segments:
        return run_video_segments(args.video, args.segments)
    if args.frames_json and args.segments:
        return run_frames_json(args.frames_json, args.segments)

    parser.print_help()
    print(
        "\nExamples:\n"
        "  python main.py --demo\n"
        "  python main.py --video clip.mp4 --segments segments.json\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
