"""Duration-aware and motion-weighted frame selection for Vision API calls."""

from __future__ import annotations

import base64

from dataclasses import dataclass

import cv2
import numpy as np

from config import MAX_FRAMES_PER_SEGMENT, MIN_FRAMES_PER_SEGMENT

STATIC_MOTION_THRESHOLD = 2.5
ACTIVE_MOTION_THRESHOLD = 6.0
HIGH_MOTION_MAX_FRAMES = 10


@dataclass(frozen=True)
class SegmentMotionProfile:
    """Motion cues for pick up vs hold and adaptive frame density."""

    start_has_contact: bool = False
    has_active_motion: bool = False
    mean_motion: float = 0.0
    peak_motion: float = 0.0
    is_static: bool = False
    reliable: bool = False


def max_frames_for_duration(duration_seconds: float | None) -> int:
    """More frames for short segments where micro-actions are easy to miss."""
    if duration_seconds is None:
        return MAX_FRAMES_PER_SEGMENT
    if duration_seconds < 2.0:
        return max(MIN_FRAMES_PER_SEGMENT, 8)
    if duration_seconds < 5.0:
        return max(MIN_FRAMES_PER_SEGMENT, 10)
    return MAX_FRAMES_PER_SEGMENT


def _decode_gray(jpeg_b64: str) -> np.ndarray | None:
    try:
        raw = base64.b64decode(jpeg_b64)
        array = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
        return image
    except Exception:
        return None


def motion_score(prev_gray: np.ndarray | None, gray: np.ndarray | None) -> float:
    """Mean absolute pixel delta between consecutive frames."""
    if prev_gray is None or gray is None:
        return 0.0
    if prev_gray.shape != gray.shape:
        gray = cv2.resize(gray, (prev_gray.shape[1], prev_gray.shape[0]))
    diff = cv2.absdiff(prev_gray, gray)
    return float(np.mean(diff))


def ensure_start_frame(
    frames: list[str],
    timestamps: list[float] | None,
    start_seconds: float | None = None,
) -> tuple[list[str], list[float] | None]:
    """Keep Frame 0 (segment start) first — required for pick up vs hold baseline."""
    if not frames:
        return frames, timestamps
    if timestamps and start_seconds is not None:
        start_index = min(
            range(len(timestamps)),
            key=lambda index: abs(timestamps[index] - start_seconds),
        )
        if start_index != 0:
            reordered_frames = [frames[start_index]] + [
                frame for index, frame in enumerate(frames) if index != start_index
            ]
            reordered_times = [timestamps[start_index]] + [
                time for index, time in enumerate(timestamps) if index != start_index
            ]
            return reordered_frames, reordered_times
    return frames, timestamps


def select_motion_keyframes(
    frames: list[str],
    timestamps: list[float] | None,
    max_frames: int,
) -> tuple[list[str], list[float] | None]:
    """Prefer start frame plus peaks of hand motion instead of uniform subsampling."""
    if len(frames) <= max_frames:
        return frames, timestamps

    grays: list[np.ndarray | None] = [_decode_gray(frame) for frame in frames]
    scores: list[float] = [0.0]
    for index in range(1, len(grays)):
        scores.append(motion_score(grays[index - 1], grays[index]))

    must_keep = {0, len(frames) - 1}
    ranked = sorted(
        range(len(frames)),
        key=lambda index: scores[index],
        reverse=True,
    )
    chosen = list(must_keep)
    for index in ranked:
        if len(chosen) >= max_frames:
            break
        if index not in chosen:
            chosen.append(index)
    chosen = sorted(chosen)

    picked_frames = [frames[index] for index in chosen]
    picked_times = None
    if timestamps:
        picked_times = [timestamps[index] for index in chosen if index < len(timestamps)]
    return picked_frames, picked_times


def analyze_segment_motion(
    frames: list[str],
    timestamps: list[float] | None = None,
) -> SegmentMotionProfile:
    """Infer start contact and active manipulation from pixel motion deltas."""
    del timestamps  # reserved for future timestamp-weighted analysis
    if not frames:
        return SegmentMotionProfile()
    grays: list[np.ndarray | None] = [_decode_gray(frame) for frame in frames]
    scores: list[float] = [0.0]
    for index in range(1, len(grays)):
        scores.append(motion_score(grays[index - 1], grays[index]))
    if len(scores) < 2:
        return SegmentMotionProfile()
    tail = scores[1:]
    mean_motion = float(sum(tail) / len(tail))
    peak_motion = float(max(tail))
    start_delta = scores[1]
    start_has_contact = start_delta < STATIC_MOTION_THRESHOLD
    has_active_motion = (
        peak_motion >= ACTIVE_MOTION_THRESHOLD
        or mean_motion >= STATIC_MOTION_THRESHOLD * 1.8
    )
    is_static = peak_motion < STATIC_MOTION_THRESHOLD and mean_motion < STATIC_MOTION_THRESHOLD
    return SegmentMotionProfile(
        start_has_contact=start_has_contact,
        has_active_motion=has_active_motion,
        mean_motion=mean_motion,
        peak_motion=peak_motion,
        is_static=is_static,
        reliable=True,
    )


def prepare_segment_frames(
    frames: list[str],
    timestamps: list[float] | None = None,
    duration_seconds: float | None = None,
    start_seconds: float | None = None,
    motion_profile: SegmentMotionProfile | None = None,
) -> tuple[list[str], list[float] | None]:
    """Apply start-frame guarantee, motion peaks, and duration-aware cap."""
    profile = motion_profile or analyze_segment_motion(frames, timestamps)
    ordered, ordered_times = ensure_start_frame(frames, timestamps, start_seconds)
    if profile.is_static and len(ordered) > 1:
        static_times = [ordered_times[0]] if ordered_times else None
        return [ordered[0]], static_times
    limit = max_frames_for_duration(duration_seconds)
    if profile.has_active_motion:
        limit = max(limit, min(len(ordered), HIGH_MOTION_MAX_FRAMES))
    return select_motion_keyframes(ordered, ordered_times, limit)
