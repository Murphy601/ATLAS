import argparse
import os
import time

from dotenv import load_dotenv

from browser_automation import VideoBrowserBot
from config import (
    DEFAULT_FRAME_INTERVAL,
    DEFAULT_PORTAL_URL,
    DEFAULT_SAMPLE_VIDEO,
    DEFAULT_SEGMENT_DURATION,
)
from frame_extractor import extract_frames_from_video, format_timestamp
from label_generator import generate_label_from_frames

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def process_video_task(
    bot: VideoBrowserBot | None,
    video_path: str,
    segment_duration: float = 3.0,
    interval_seconds: float = 1.0,
):
    """Processes video chunks, generates labels, and writes output to the browser UI."""
    keyframes = extract_frames_from_video(video_path, interval_seconds=interval_seconds)
    if not keyframes:
        print("[Pipeline]: No frames retrieved. Task aborted.")
        return

    total_frames = len(keyframes)
    chunk_size = max(1, int(round(segment_duration / interval_seconds)))

    print(f"\n[Pipeline]: Processing video in {segment_duration}-second segments...")

    for i in range(0, total_frames, chunk_size):
        chunk = keyframes[i : i + chunk_size]
        if not chunk:
            continue

        start_sec = chunk[0][0]
        end_sec = chunk[-1][0] + interval_seconds

        start_str = format_timestamp(start_sec)
        end_str = format_timestamp(end_sec)

        base64_batch = [frame_data[1] for frame_data in chunk]
        label = generate_label_from_frames(base64_batch)

        print(f"\n--- Segment [{start_str} -> {end_str}] ---")
        print(f"Generated Label: '{label}'")

        if label != "No Action" and bot is not None:
            bot.add_timestamp_and_label(start_str, end_str, label)
            time.sleep(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Video timestamping and action-labeling pipeline."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_PORTAL_URL,
        help="Annotation portal URL.",
    )
    parser.add_argument(
        "--video",
        default=DEFAULT_SAMPLE_VIDEO,
        help="Path to the local MP4 video.",
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
        help="Submit without the interactive review pause.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=_env_flag("HEADLESS", False),
        help="Run Chromium headless.",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        default=_env_flag("SKIP_BROWSER", False),
        help="Generate labels only; do not launch Playwright.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    portal_url = args.url
    sample_video = args.video
    auto_submit = args.auto_submit

    bot = None
    try:
        if not args.skip_browser:
            bot = VideoBrowserBot(headless=args.headless)
            bot.start(portal_url)
            bot.wait_for_manual_login(timeout=60)

        if os.path.exists(sample_video):
            process_video_task(
                bot,
                sample_video,
                segment_duration=args.segment_duration,
                interval_seconds=args.frame_interval,
            )

            if bot is None:
                print("\n[Pipeline]: Browser skipped. Label generation complete.")
            elif auto_submit:
                bot.submit_final_task()
            else:
                try:
                    input(
                        "\n[Review Mode]: Verify generated inputs in the browser, then press ENTER to submit..."
                    )
                except EOFError:
                    print(
                        "\n[Review Mode]: No interactive stdin. Skipping submit. "
                        "Re-run with --auto-submit to submit without review."
                    )
                else:
                    bot.submit_final_task()
        else:
            print(
                f"\n[Notice]: Place a video file named '{sample_video}' in the project root to run testing."
            )

    except Exception as e:
        print(f"[Execution Error]: {e}")
    finally:
        if bot is not None:
            bot.stop()


if __name__ == "__main__":
    main()
