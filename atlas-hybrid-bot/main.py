#!/usr/bin/env python3
"""Atlas hybrid bot — full browser automation + MediaPipe/regex labeling (no LLM)."""

from __future__ import annotations

import argparse
import os
import time

from dotenv import load_dotenv

from browser_automation import SegmentRow, VideoBrowserBot
from config import (
    ATLAS_LABEL_MODE,
    DEFAULT_FRAME_INTERVAL,
    DEFAULT_PORTAL_URL,
    DEFAULT_SEGMENT_DURATION,
)
from frame_extractor import extract_frames_from_video, format_timestamp
from hybrid_annotator import AtlasHybridPipeline
from frame_utils import frames_from_base64_list
from label_generator import usable_draft
from label_pipeline import (
    atlas_guide_cleaner,
    generate_label_hybrid,
    resolve_hand_tag,
)

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _chunk_frames(
    frames: list[tuple[float, str]],
    start_seconds: float,
    segment_duration: float,
) -> list[tuple[float, str]]:
    end_seconds = start_seconds + segment_duration
    return [frame for frame in frames if start_seconds <= frame[0] < end_seconds]


def process_live_task(
    bot: VideoBrowserBot,
    segment_duration: float = 3.0,
    interval_seconds: float = 1.0,
    global_context=None,
):
    """Capture frames from the in-page player and fill Atlas segment rows (no LLM)."""
    bot.prepare_video_playback()
    segments = bot.discover_segments()
    if not segments:
        print("[Hybrid]: No Atlas segment rows found. Open a labeling task and retry.")
        return False

    remember = getattr(bot, "remember_original_drafts", None)
    if callable(remember):
        segments = remember(segments)

    if global_context is None:
        pass  # minimalist mode: no cross-clip glossary rewriting

    print(f"\n[Hybrid]: Correcting {len(segments)} segment labels (ATLAS guide linter)...")
    pipeline = AtlasHybridPipeline()
    processed_any = False
    previous_label = None

    try:
        for index, segment in enumerate(segments):
            duration = segment.duration_seconds
            bot.play_segment_clip(segment.number)
            chunk = bot.capture_segment_frames(
                start_seconds=segment.start_seconds,
                segment_duration=duration,
                interval_seconds=interval_seconds,
                trust_play_segment=True,
            )
            if not chunk:
                print(
                    f"[Hybrid]: No frames for Segment {segment.number} "
                    f"@ {segment.start_seconds}s. Skipping."
                )
                continue

            start_str = format_timestamp(segment.start_seconds)
            end_str = format_timestamp(
                segment.end_seconds
                if segment.end_seconds is not None
                else segment.start_seconds + duration
            )
            draft = usable_draft(segment.draft_label)
            next_draft = None
            if index + 1 < len(segments):
                next_draft = usable_draft(segments[index + 1].draft_label)
            if segment.draft_label and draft is None:
                print("[Hybrid]: Ignoring No Action draft; using frames + rules only.")
            elif draft:
                print(f"[Hybrid]: AI draft: '{draft}'")

            try:
                label = generate_label_hybrid(
                    [frame[1] for frame in chunk],
                    pipeline,
                    previous_label=previous_label,
                    draft_label=draft,
                    duration_seconds=duration,
                    frame_timestamps=[frame[0] for frame in chunk],
                    frames_have_video=getattr(bot, "last_frames_have_video", False),
                    next_label=next_draft,
                    global_context=global_context,
                    segment_start_seconds=segment.start_seconds,
                )
            except Exception as exc:
                print(
                    f"[Hybrid]: Segment {segment.number} error: {exc}. "
                    "Using minimal draft cleaner."
                )
                label = "No Action"
                if draft:
                    frame_arrays = frames_from_base64_list(
                        [frame[1] for frame in chunk]
                    ) if chunk else []
                    motion = pipeline.analyze_frame_motion_from_memory(
                        frame_arrays,
                        draft_label=draft,
                    )
                    hand = resolve_hand_tag(draft, motion.detected_hand)
                    label = atlas_guide_cleaner(
                        draft,
                        previous_label=previous_label,
                        mp_hand_tag=hand,
                        duration_seconds=duration,
                    )

            print(f"\n--- Segment {segment.number} [{start_str} -> {end_str}] ---")
            print(f"Generated Label: '{label}'")

            processed_any = True
            if label == "No Action" and draft:
                kept = atlas_guide_cleaner(
                    draft,
                    previous_label=previous_label,
                    mp_hand_tag=resolve_hand_tag(draft, "with right hand"),
                    duration_seconds=duration,
                )
                print(
                    "[Hybrid]: Keeping guide-cleaned draft "
                    f"'{kept}' instead of No Action."
                )
                if kept != "No Action":
                    bot.fill_segment_label(
                        segment.number,
                        kept,
                        start_seconds=segment.start_seconds,
                    )
                    previous_label = kept
                else:
                    previous_label = segment.draft_label
                continue

            bot.fill_segment_label(
                segment.number,
                label,
                start_seconds=segment.start_seconds,
            )
            previous_label = label
            time.sleep(0.4)
    finally:
        pipeline.close()

    return processed_any


def process_video_task(
    bot: VideoBrowserBot | None,
    video_path: str,
    segment_duration: float = 3.0,
    interval_seconds: float = 1.0,
    segments: list[SegmentRow] | None = None,
):
    """Local MP4 fallback: extract keyframes then write Atlas segment rows."""
    keyframes = extract_frames_from_video(video_path, interval_seconds=interval_seconds)
    if not keyframes:
        print("[Hybrid]: No frames retrieved. Task aborted.")
        return

    if segments is None and bot is not None:
        try:
            segments = bot.discover_segments()
        except Exception:
            segments = []

    if not segments:
        total_frames = len(keyframes)
        chunk_size = max(1, int(round(segment_duration / interval_seconds)))
        segments = [
            SegmentRow(
                number=(index // chunk_size) + 1,
                start_seconds=keyframes[index][0],
                locator_index=index // chunk_size,
            )
            for index in range(0, total_frames, chunk_size)
        ]

    print(f"\n[Hybrid]: Processing video in {segment_duration}-second segments...")
    pipeline = AtlasHybridPipeline()
    previous_label = None

    try:
        for segment in segments:
            chunk = _chunk_frames(keyframes, segment.start_seconds, segment_duration)
            if not chunk:
                continue

            start_str = format_timestamp(segment.start_seconds)
            end_str = format_timestamp(segment.start_seconds + segment_duration)
            draft = usable_draft(segment.draft_label)
            label = generate_label_hybrid(
                [frame[1] for frame in chunk],
                pipeline,
                previous_label=previous_label,
                draft_label=draft,
                duration_seconds=segment_duration,
                frame_timestamps=[frame[0] for frame in chunk],
            )

            print(f"\n--- Segment {segment.number} [{start_str} -> {end_str}] ---")
            print(f"Generated Label: '{label}'")

            if bot is not None:
                bot.fill_segment_label(
                    segment.number,
                    label,
                    start_seconds=segment.start_seconds,
                )
                time.sleep(1)
            previous_label = label
    finally:
        pipeline.close()


def _pause_for_review_then_submit(
    bot: VideoBrowserBot,
    auto_submit: bool,
    fingerprint: str = "",
) -> str:
    if auto_submit:
        print("[Hybrid]: AUTO_SUBMIT enabled. Submitting without review.")
        bot.submit_final_task()
        return "submitted"

    try:
        input(
            "\n[Review Mode]: Inspect filled Atlas labels in the browser, "
            "then press ENTER to click Submit practice clip. "
            "After that I stay on the next clip (Ctrl+C to stop)..."
        )
    except EOFError:
        print(
            "\n[Review Mode]: No interactive stdin. Skipping submit. "
            "Re-run with --auto-submit after you verify labels."
        )
        return "skipped"

    current = bot.episode_fingerprint()
    if fingerprint and current and current != fingerprint and bot.has_open_episode():
        print(
            "[Hybrid]: The open clip changed before submit. "
            "Labeling the new clip instead."
        )
        return "relabel"
    bot.submit_final_task()
    return "submitted"


def run_live_queue(
    bot: VideoBrowserBot,
    segment_duration: float = 3.0,
    interval_seconds: float = 1.0,
    auto_submit: bool = False,
    max_episodes: int | None = None,
    next_timeout: float | None = None,
):
    episode = 0
    print(
        "[Hybrid]: Live queue mode (no LLM). Label → review/submit → next clip. "
        "Ctrl+C to stop."
    )
    while max_episodes is None or episode < max_episodes:
        if not bot.has_open_episode():
            bot.ensure_labeling_ready(timeout=90.0)
        if not bot.has_open_episode():
            if not bot.wait_for_new_episode("", timeout=next_timeout):
                print("[Hybrid]: No clip opened. Stopping.")
                return
        fingerprint = bot.episode_fingerprint()
        episode += 1
        print(f"\n[Hybrid]: Labeling clip {episode}...")
        try:
            processed = process_live_task(
                bot,
                segment_duration=segment_duration,
                interval_seconds=interval_seconds,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if _is_browser_disconnect(exc):
                raise
            print(f"[Hybrid]: Clip {episode} failed: {exc}")
            processed = False
        if not processed:
            print("[Hybrid]: Nothing to label. Waiting for next clip...")
            if not bot.wait_for_new_episode(fingerprint, timeout=next_timeout):
                return
            episode -= 1
            continue

        result = _pause_for_review_then_submit(bot, auto_submit, fingerprint)
        if result == "relabel":
            episode -= 1
            continue
        if result == "skipped":
            print("[Hybrid]: Submit skipped. Waiting for next clip.")
        else:
            print(
                "[Hybrid]: Submitted. Click Next task if shown — "
                "labeling resumes when the next clip loads."
            )
        if max_episodes is not None and episode >= max_episodes:
            return
        advanced = bot.wait_for_new_episode(fingerprint, timeout=next_timeout)
        if not advanced:
            print("[Hybrid]: Next clip did not load. Checking Tasks...")
            bot.open_work_queue()
            if bot.has_open_episode() and bot.episode_fingerprint() != fingerprint:
                continue
            print("[Hybrid]: Queue idle. Stopping.")
            return


def _is_browser_disconnect(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "connection closed",
            "target closed",
            "browser has been closed",
            "driver crashed",
        )
    )


def run_demo() -> int:
    """Regex/state demo without browser or video."""
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
        out = pipeline.lint_atlas_syntax(corrected, duration, "with right hand")
        pipeline.state_memory.update_from_label(
            out, "with right hand", seg["object"]
        )
        print(f"[{seg['start']}s–{seg['end']}s] {out!r}")
    print("\n[Demo]", transform_draft_non_llm("picking up blue package", 2.5, "with left hand"))
    return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Atlas hybrid bot — browser automation + MediaPipe/regex (no LLM)."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_PORTAL_URL,
        help="Atlas audit portal URL.",
    )
    parser.add_argument(
        "--video",
        default=os.getenv("SAMPLE_VIDEO", ""),
        help="Optional local MP4 fallback. Default is live in-page capture.",
    )
    parser.add_argument(
        "--segment-duration",
        type=float,
        default=DEFAULT_SEGMENT_DURATION,
        help="Segment length in seconds.",
    )
    parser.add_argument(
        "--frame-interval",
        type=float,
        default=DEFAULT_FRAME_INTERVAL,
        help="Keyframe sampling interval in seconds.",
    )
    parser.add_argument(
        "--auto-submit",
        action="store_true",
        default=_env_flag("AUTO_SUBMIT", False),
        help="Submit without interactive review pause.",
    )
    parser.add_argument(
        "--mode",
        choices=("practice", "assessment", "auto"),
        default=os.getenv("ATLAS_LABEL_MODE", ATLAS_LABEL_MODE),
        help="practice = Practice assessment; assessment = graded; auto = practice then graded.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=_env_flag("HEADLESS", False),
        help="Headless Chromium (requires prior headed login for cookies).",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        default=_env_flag("SKIP_BROWSER", False),
        help="Label from --video only; no Playwright.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run regex/state demo without browser.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.demo:
        raise SystemExit(run_demo())

    os.environ["ATLAS_LABEL_MODE"] = args.mode
    portal_url = args.url
    sample_video = (args.video or "").strip()
    auto_submit = args.auto_submit

    bot = None
    try:
        if args.skip_browser:
            if not sample_video or not os.path.exists(sample_video):
                print(
                    "[Hybrid]: --skip-browser requires --video. "
                    "Live Atlas capture needs the browser."
                )
                return
            process_video_task(
                None,
                sample_video,
                segment_duration=args.segment_duration,
                interval_seconds=args.frame_interval,
            )
            print("\n[Hybrid]: Browser skipped. Label generation complete.")
            return

        if args.headless:
            print(
                "[Notice]: Headless mode needs a prior headed login so "
                "./browser_session stores cookies."
            )

        bot = VideoBrowserBot(headless=args.headless)
        bot.start(portal_url)
        bot.wait_for_manual_login(timeout=300)

        if sample_video and os.path.exists(sample_video):
            print(f"[Hybrid]: Local video fallback '{sample_video}'.")
            process_video_task(
                bot,
                sample_video,
                segment_duration=args.segment_duration,
                interval_seconds=args.frame_interval,
            )
            _pause_for_review_then_submit(bot, auto_submit)
        else:
            run_live_queue(
                bot,
                segment_duration=args.segment_duration,
                interval_seconds=args.frame_interval,
                auto_submit=auto_submit,
            )

    except KeyboardInterrupt:
        print("\n[Hybrid]: Stopped by Ctrl+C.")
    except Exception as exc:
        if _is_browser_disconnect(exc):
            print(
                "[Hybrid]: Browser closed while running. Re-run:\n"
                "  .\\venv\\Scripts\\python.exe main.py"
            )
        else:
            print(f"[Hybrid]: {exc}")
    finally:
        if bot is not None:
            bot.stop()


if __name__ == "__main__":
    main()
