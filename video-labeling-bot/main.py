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
    GLOBAL_SWEEP_INTERVAL_SECONDS,
    TWO_PASS_ENABLED,
)
from frame_extractor import extract_frames_from_video, format_timestamp
from label_generator import (
    GlobalVideoContext,
    analyze_global_video_context,
    apply_context_fixes,
    generate_label_from_frames,
    rewrite_generic_animal_draft,
    usable_draft,
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
    return [
        frame
        for frame in frames
        if start_seconds <= frame[0] < end_seconds
    ]


def process_live_task(
    bot: VideoBrowserBot,
    segment_duration: float = 3.0,
    interval_seconds: float = 1.0,
    global_context: GlobalVideoContext | None = None,
):
    """Captures frames from the in-page player and fills Atlas segment label rows."""
    bot.prepare_video_playback()
    segments = bot.discover_segments()
    if not segments:
        print("[Pipeline]: No Atlas segment rows found. Open a labeling task and retry.")
        return False

    remember = getattr(bot, "remember_original_drafts", None)
    if callable(remember):
        segments = remember(segments)

    if global_context is None and TWO_PASS_ENABLED:
        capture_timeline = getattr(bot, "capture_live_frames", None)
        if callable(capture_timeline):
            print("[Pipeline]: Pass 1 — full-video observation sweep for object glossary...")
            sweep_frames = capture_timeline(
                interval_seconds=GLOBAL_SWEEP_INTERVAL_SECONDS
            )
            if sweep_frames:
                draft_hints = [
                    usable_draft(segment.draft_label) or ""
                    for segment in segments
                ]
                global_context = analyze_global_video_context(
                    [frame[1] for frame in sweep_frames],
                    frame_timestamps=[frame[0] for frame in sweep_frames],
                    segment_drafts=[draft for draft in draft_hints if draft],
                )
            else:
                print("[Pipeline]: Pass 1 sweep skipped (no timeline frames).")
        else:
            print("[Pipeline]: Pass 1 sweep skipped (capture_live_frames unavailable).")

    print(f"\n[Pipeline]: Pass 2 — correcting {len(segments)} segment labels...")
    processed_any = False

    previous_label = None
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
                f"[Pipeline]: No frames for Segment {segment.number} "
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
            print("[Pipeline]: Ignoring No Action draft; labeling from frames.")
        elif draft:
            print(f"[Pipeline]: AI draft: '{draft}'")
        label = generate_label_from_frames(
            [frame[1] for frame in chunk],
            previous_label=previous_label,
            draft_label=draft,
            duration_seconds=duration,
            frame_timestamps=[frame[0] for frame in chunk],
            frames_have_video=getattr(bot, "last_frames_have_video", False),
            next_label=next_draft,
            global_context=global_context,
            segment_start_seconds=segment.start_seconds,
        )

        print(f"\n--- Segment {segment.number} [{start_str} -> {end_str}] ---")
        print(f"Generated Label: '{label}'")

        processed_any = True
        if label == "No Action" and draft:
            kept = apply_context_fixes(
                rewrite_generic_animal_draft(draft),
                draft,
                previous_label,
            )
            print(
                "[Pipeline]: Model said No Action but an AI draft already describes "
                f"work. Keeping '{kept}' instead of writing No Action."
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
    return processed_any


def process_video_task(
    bot: VideoBrowserBot | None,
    video_path: str,
    segment_duration: float = 3.0,
    interval_seconds: float = 1.0,
    segments: list[SegmentRow] | None = None,
):
    """Optional local-file fallback: extract keyframes then write Atlas segment rows."""
    keyframes = extract_frames_from_video(video_path, interval_seconds=interval_seconds)
    if not keyframes:
        print("[Pipeline]: No frames retrieved. Task aborted.")
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

    print(f"\n[Pipeline]: Processing video in {segment_duration}-second segments...")

    previous_label = None
    for segment in segments:
        chunk = _chunk_frames(keyframes, segment.start_seconds, segment_duration)
        if not chunk:
            continue

        start_str = format_timestamp(segment.start_seconds)
        end_str = format_timestamp(segment.start_seconds + segment_duration)
        label = generate_label_from_frames(
            [frame[1] for frame in chunk], previous_label=previous_label
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


def _pause_for_review_then_submit(
    bot: VideoBrowserBot,
    auto_submit: bool,
    fingerprint: str = "",
) -> str:
    """Returns submitted, skipped, or relabel if the clip changed during review."""
    if auto_submit:
        print("[Pipeline]: AUTO_SUBMIT is enabled. Submitting without review.")
        bot.submit_final_task()
        return "submitted"

    try:
        input(
            "\n[Review Mode]: Inspect the filled Atlas labels in the browser, "
            "then press ENTER to click Submit practice clip. "
            "After that I stay on the next clip (Ctrl+C to stop)..."
        )
    except EOFError:
        print(
            "\n[Review Mode]: No interactive stdin. Skipping submit. "
            "Re-run with --auto-submit only after you have verified labels."
        )
        return "skipped"

    current = bot.episode_fingerprint()
    if fingerprint and current and current != fingerprint and bot.has_open_episode():
        print(
            "[Pipeline]: The open clip changed before submit "
            "(Next task was already clicked). Labeling this new clip instead."
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
    """Label, review/submit, then keep going when Next task opens the next clip."""
    episode = 0
    print(
        "[Pipeline]: Live queue mode. I will keep labeling after each submit. "
        "Click Next task when it appears, or I will click it. Ctrl+C to stop."
    )
    while max_episodes is None or episode < max_episodes:
        if not bot.has_open_episode():
            bot.ensure_labeling_ready(timeout=90.0)
        if not bot.has_open_episode():
            if not bot.wait_for_new_episode("", timeout=next_timeout):
                print("[Pipeline]: No clip opened. Stopping the queue.")
                return
        fingerprint = bot.episode_fingerprint()
        episode += 1
        print(f"\n[Pipeline]: Labeling clip {episode}...")
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
            print(f"[Pipeline]: Clip {episode} failed: {exc}")
            processed = False
        if not processed:
            print("[Pipeline]: Nothing to label on this page. Waiting for the next clip...")
            if not bot.wait_for_new_episode(fingerprint, timeout=next_timeout):
                return
            episode -= 1
            continue

        result = _pause_for_review_then_submit(bot, auto_submit, fingerprint)
        if result == "relabel":
            episode -= 1
            continue
        if result == "skipped":
            print("[Pipeline]: Submit skipped. Waiting in case you open the next clip.")
        else:
            print(
                "[Pipeline]: Submitted. Click Next task if it is on screen. "
                "I will start labeling as soon as the next clip loads — I am not exiting."
            )
        if max_episodes is not None and episode >= max_episodes:
            return
        advanced = bot.wait_for_new_episode(fingerprint, timeout=next_timeout)
        if not advanced:
            print("[Pipeline]: Next clip did not load. Checking Tasks...")
            bot.open_work_queue()
            if bot.has_open_episode() and bot.episode_fingerprint() != fingerprint:
                continue
            print("[Pipeline]: Queue looks idle. Stopping.")
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Atlas Capture live video timestamping and action-labeling pipeline."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_PORTAL_URL,
        help="Atlas audit portal URL.",
    )
    parser.add_argument(
        "--video",
        default=os.getenv("SAMPLE_VIDEO", ""),
        help="Optional local MP4 fallback. Default is live in-page capture (no file).",
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
        help="Submit without the interactive review pause. Default is review-then-submit.",
    )
    parser.add_argument(
        "--mode",
        choices=("practice", "assessment", "auto"),
        default=os.getenv("ATLAS_LABEL_MODE", ATLAS_LABEL_MODE),
        help="practice = training Practice assessment; assessment = graded 70%% test; auto = practice then graded.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=_env_flag("HEADLESS", False),
        help="Run Chromium headless. Manual login requires headed mode.",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        default=_env_flag("SKIP_BROWSER", False),
        help="Generate labels only from --video; do not launch Playwright.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    os.environ["ATLAS_LABEL_MODE"] = args.mode
    portal_url = args.url
    sample_video = (args.video or "").strip()
    auto_submit = args.auto_submit

    bot = None
    try:
        if args.skip_browser:
            if not sample_video or not os.path.exists(sample_video):
                print(
                    "[Notice]: --skip-browser requires a local --video file. "
                    "Live Atlas capture needs the browser."
                )
                return
            process_video_task(
                None,
                sample_video,
                segment_duration=args.segment_duration,
                interval_seconds=args.frame_interval,
            )
            print("\n[Pipeline]: Browser skipped. Label generation complete.")
            return

        if args.headless:
            print(
                "[Notice]: Headless mode cannot do the first-run manual login. "
                "Use headed mode at least once so ./browser_session stores cookies."
            )

        bot = VideoBrowserBot(headless=args.headless)
        bot.start(portal_url)
        bot.wait_for_manual_login(timeout=300)

        if sample_video and os.path.exists(sample_video):
            print(f"[Pipeline]: Using local video fallback '{sample_video}'.")
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
        print("\n[Pipeline]: Stopped by Ctrl+C. Closing the browser.")
    except Exception as e:
        if _is_browser_disconnect(e):
            print(
                "[Execution Error]: Chrome closed while the bot was reading the page. "
                "Leave the Chrome window open — do not close it. Then re-run: "
                ".\\venv\\Scripts\\python.exe main.py"
            )
        else:
            print(f"[Execution Error]: {e}")
    finally:
        if bot is not None:
            bot.stop()


if __name__ == "__main__":
    main()
