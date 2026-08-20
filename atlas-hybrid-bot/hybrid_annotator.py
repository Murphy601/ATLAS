"""Non-LLM / hybrid Atlas label pipeline: MediaPipe hands + state memory + regex linter."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import cv2
import math
import numpy as np

from mediapipe_hands import close_hand_tracker, get_hand_tracker

SHORT_WINDOW_MAX_SECONDS = 3.5
DEFAULT_MOTION_THRESHOLD = 0.015

DEFAULT_LEXICON: dict[str, str] = {
    "blue package": "glass cleaner pouch",
    "red package": "glass cleaner pouch",
    "clothes": "garment",
    "clothing": "garment",
    "container": "sachet",
    "shirt": "grey shirt",
    "basin": "black basin",
    "tool": "hoe",
}


@dataclass
class SegmentStateMemory:
    """Cross-segment object state (pick up vs hold continuity)."""

    left_hand_object: str | None = None
    right_hand_object: str | None = None

    def object_held(self, target: str | None) -> bool:
        if not target:
            return False
        key = target.casefold()
        return key in {
            (self.left_hand_object or "").casefold(),
            (self.right_hand_object or "").casefold(),
        }

    def update_from_label(
        self,
        label: str,
        detected_hand: str,
        target_object: str | None,
    ) -> None:
        if not label or label == "No Action":
            return
        blob = label.lower()
        if any(v in blob for v in ("place", "put down", "set ")):
            self.left_hand_object = None
            self.right_hand_object = None
            return
        if not target_object or not any(v in blob for v in ("hold", "pick up", "pass")):
            return
        if "both hands" in detected_hand:
            self.left_hand_object = target_object
            self.right_hand_object = target_object
        elif "left hand" in detected_hand:
            self.left_hand_object = target_object
        elif "right hand" in detected_hand:
            self.right_hand_object = target_object


@dataclass(frozen=True)
class HandMotionProfile:
    v_left: float = 0.0
    v_right: float = 0.0
    peak_left: float = 0.0
    peak_right: float = 0.0
    vy_left: float = 0.0
    vy_right: float = 0.0
    angular_left: float = 0.0
    angular_right: float = 0.0
    detected_hand: str = "with right hand"
    work_hand: str | None = None
    stabilize_hand: str | None = None
    hand_confidence: float = 0.0
    start_left_contact: bool = False
    start_right_contact: bool = False
    frames_analyzed: int = 0


@dataclass
class AtlasHybridPipeline:
    """
    Deterministic annotator: MediaPipe wrist velocity + draft regex surgery.
    No LLM calls. Designed to run on CPU from in-memory frames or a video file.
    """

    lexicon: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_LEXICON))
    state_memory: SegmentStateMemory = field(default_factory=SegmentStateMemory)
    ego_swap_hands: bool = True
    motion_threshold: float = DEFAULT_MOTION_THRESHOLD
    _hand_from_draft_fallback: bool = True

    def __post_init__(self) -> None:
        swap = os.getenv("EGO_SWAP_HANDS", "true").strip().lower()
        if swap in {"0", "false", "no"}:
            self.ego_swap_hands = False
        threshold = os.getenv("HAND_MOTION_THRESHOLD", "").strip()
        if threshold:
            try:
                self.motion_threshold = float(threshold)
            except ValueError:
                pass

    def close(self) -> None:
        close_hand_tracker()

    def analyze_frame_motion_from_memory(
        self,
        frame_arrays: list[np.ndarray],
        sample_rate: int = 2,
        draft_label: str | None = None,
    ) -> HandMotionProfile:
        """Wrist velocity vectors from BGR/RGB numpy frames (browser capture path)."""
        if not frame_arrays:
            return HandMotionProfile(
                detected_hand=_hand_tag_from_draft(draft_label) or "with right hand"
            )

        left_positions: list[tuple[float, float] | None] = []
        right_positions: list[tuple[float, float] | None] = []
        sampled = frame_arrays[:: max(1, sample_rate)]

        try:
            tracker = get_hand_tracker()
            for frame in sampled:
                rgb = _to_rgb(frame)
                left_pos, right_pos = tracker.process_rgb(
                    rgb,
                    ego_swap_hands=self.ego_swap_hands,
                )
                left_positions.append(left_pos)
                right_positions.append(right_pos)
        except Exception as exc:
            print(
                f"[Hybrid]: Hand tracking unavailable ({exc}). "
                "Using draft hand tags + regex only."
            )
            draft_hand = _hand_tag_from_draft(draft_label) or "with right hand"
            return HandMotionProfile(detected_hand=draft_hand)

        v_left = _mean_wrist_velocity(left_positions)
        v_right = _mean_wrist_velocity(right_positions)
        peak_left = _peak_wrist_velocity(left_positions)
        peak_right = _peak_wrist_velocity(right_positions)
        vy_left = _mean_wrist_vertical_delta(left_positions)
        vy_right = _mean_wrist_vertical_delta(right_positions)
        center = _rotation_center(left_positions, right_positions)
        angular_left = _angular_sweep(left_positions, center)
        angular_right = _angular_sweep(right_positions, center)
        detected = _hand_from_velocities(v_left, v_right, self.motion_threshold)
        draft_hand = _hand_tag_from_draft(draft_label)
        if draft_hand and v_left <= self.motion_threshold and v_right <= self.motion_threshold:
            detected = draft_hand
        work_hand, stabilize_hand, confidence = _infer_hand_roles(
            peak_left,
            peak_right,
            angular_left,
            angular_right,
            self.motion_threshold,
        )
        start_left = left_positions[0] is not None if left_positions else False
        start_right = right_positions[0] is not None if right_positions else False
        return HandMotionProfile(
            v_left=v_left,
            v_right=v_right,
            peak_left=peak_left,
            peak_right=peak_right,
            vy_left=vy_left,
            vy_right=vy_right,
            angular_left=angular_left,
            angular_right=angular_right,
            detected_hand=detected,
            work_hand=work_hand,
            stabilize_hand=stabilize_hand,
            hand_confidence=confidence,
            start_left_contact=start_left,
            start_right_contact=start_right,
            frames_analyzed=len(sampled),
        )

    def analyze_frame_motion(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        sample_fps: float = 10.0,
    ) -> HandMotionProfile:
        """Wrist velocity from a video file segment."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return HandMotionProfile()
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)
        step = max(1, int(fps / max(sample_fps, 1.0)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        frames: list[np.ndarray] = []
        current = start_frame
        while cap.isOpened() and current <= end_frame:
            ok, frame = cap.read()
            if not ok:
                break
            if (current - start_frame) % step == 0:
                frames.append(frame)
            current += 1
        cap.release()
        return self.analyze_frame_motion_from_memory(frames, sample_rate=1)

    def resolve_state_verbs(
        self,
        draft_text: str,
        *,
        is_held_from_memory: bool,
        start_has_contact: bool,
    ) -> str:
        """pick up → hold when object was already held or Frame 0 shows contact."""
        if not draft_text:
            return draft_text
        if not (is_held_from_memory or start_has_contact):
            return draft_text
        return re.sub(r"\bpick up\b", "hold", draft_text, flags=re.IGNORECASE)

    def lint_atlas_syntax(
        self,
        draft_text: str,
        duration_sec: float,
        detected_hand: str,
    ) -> str:
        """Lexicon lock, imperative verbs, clause cap, hand tag injection."""
        if not draft_text or draft_text.strip() == "No Action":
            return draft_text
        text = draft_text.strip()

        for generic, exact in self.lexicon.items():
            text = re.sub(
                rf"\b{re.escape(generic)}\b",
                exact,
                text,
                flags=re.IGNORECASE,
            )

        replacements = {
            "holding": "hold",
            "picking up": "pick up",
            "scrubbing": "scrub",
            "wiping": "wipe",
            "washing": "wash",
            "placing": "place",
        }
        for src, dst in replacements.items():
            text = re.sub(rf"\b{src}\b", dst, text, flags=re.IGNORECASE)

        text = re.sub(r"\s+(and|then)\s+", ", ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+,\s+", ", ", text)
        text = " ".join(text.split())

        clauses = [part.strip() for part in text.split(",") if part.strip()]
        if duration_sec < SHORT_WINDOW_MAX_SECONDS and len(clauses) > 1:
            text = clauses[0]
        elif clauses:
            text = ", ".join(clauses)

        text = re.sub(r"\bin both hands\b", "with both hands", text, flags=re.IGNORECASE)
        text = re.sub(r"\bin left hand\b", "with left hand", text, flags=re.IGNORECASE)
        text = re.sub(r"\bin right hand\b", "with right hand", text, flags=re.IGNORECASE)

        if not any(
            tag in text
            for tag in ("with left hand", "with right hand", "with both hands")
        ):
            text = f"{text} {detected_hand}".strip()

        return text.strip(" ,")

    def process_frame_batch(
        self,
        frame_arrays: list[np.ndarray],
        start_sec: float,
        end_sec: float,
        draft_label: str,
        target_object: str | None = None,
    ) -> str:
        """In-memory frames → deterministic Atlas label (no LLM)."""
        duration = max(0.2, end_sec - start_sec)
        motion = self.analyze_frame_motion_from_memory(
            frame_arrays,
            draft_label=draft_label,
        )
        return self._finalize_segment(
            draft_label,
            duration,
            motion,
            target_object,
        )

    def process_segment(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        draft_label: str,
        target_object: str | None = None,
    ) -> str:
        """Video file segment → deterministic Atlas label (no LLM)."""
        duration = max(0.2, end_sec - start_sec)
        motion = self.analyze_frame_motion(video_path, start_sec, end_sec)
        return self._finalize_segment(
            draft_label,
            duration,
            motion,
            target_object,
        )

    def _finalize_segment(
        self,
        draft_label: str,
        duration: float,
        motion: HandMotionProfile,
        target_object: str | None,
    ) -> str:
        held_memory = self.state_memory.object_held(target_object)
        start_contact = motion.start_left_contact or motion.start_right_contact
        corrected = self.resolve_state_verbs(
            draft_label,
            is_held_from_memory=held_memory,
            start_has_contact=start_contact,
        )
        final = self.lint_atlas_syntax(corrected, duration, motion.detected_hand)
        self.state_memory.update_from_label(
            final,
            motion.detected_hand,
            target_object,
        )
        return final


def transform_draft_non_llm(
    draft_text: str,
    segment_duration: float,
    detected_hand: str = "with right hand",
    lexicon: dict[str, str] | None = None,
) -> str:
    """Standalone regex draft rewriter (no CV). Useful for unit tests."""
    pipe = AtlasHybridPipeline(lexicon=lexicon or dict(DEFAULT_LEXICON))
    return pipe.lint_atlas_syntax(draft_text, segment_duration, detected_hand)


def _to_rgb(frame: np.ndarray) -> np.ndarray:
    if frame.ndim != 3:
        return frame
    if frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def _mean_wrist_velocity(positions: list[tuple[float, float] | None]) -> float:
    valid = [pos for pos in positions if pos is not None]
    if len(valid) < 2:
        return 0.0
    distances: list[float] = []
    prev = valid[0]
    for pos in valid[1:]:
        dx = pos[0] - prev[0]
        dy = pos[1] - prev[1]
        distances.append(float(np.sqrt(dx * dx + dy * dy)))
        prev = pos
    return float(np.mean(distances)) if distances else 0.0


def _peak_wrist_velocity(positions: list[tuple[float, float] | None]) -> float:
    """Max frame-to-frame wrist displacement — wiping strokes spike; static hold stays near zero."""
    valid = [pos for pos in positions if pos is not None]
    if len(valid) < 2:
        return 0.0
    distances: list[float] = []
    prev = valid[0]
    for pos in valid[1:]:
        dx = pos[0] - prev[0]
        dy = pos[1] - prev[1]
        distances.append(float(np.sqrt(dx * dx + dy * dy)))
        prev = pos
    return float(max(distances)) if distances else 0.0


def _mean_wrist_vertical_delta(positions: list[tuple[float, float] | None]) -> float:
    """Mean vertical wrist delta; positive values indicate downward motion in frame space."""
    valid = [pos for pos in positions if pos is not None]
    if len(valid) < 2:
        return 0.0
    deltas: list[float] = []
    prev = valid[0]
    for pos in valid[1:]:
        deltas.append(float(pos[1] - prev[1]))
        prev = pos
    return float(np.mean(deltas)) if deltas else 0.0


def _rotation_center(
    left_positions: list[tuple[float, float] | None],
    right_positions: list[tuple[float, float] | None],
) -> tuple[float, float]:
    """Pivot for angular sweep: midpoint of first frame with both wrists, else frame center."""
    if left_positions and right_positions:
        left0 = left_positions[0]
        right0 = right_positions[0]
        if left0 is not None and right0 is not None:
            return ((left0[0] + right0[0]) / 2.0, (left0[1] + right0[1]) / 2.0)
        if left0 is not None:
            return left0
        if right0 is not None:
            return right0
    return (0.5, 0.5)


def _angular_sweep(
    positions: list[tuple[float, float] | None],
    center: tuple[float, float],
) -> float:
    """Cumulative angular change (radians) of a wrist path around center."""
    valid = [pos for pos in positions if pos is not None]
    if len(valid) < 3:
        return 0.0
    angles = [
        math.atan2(pos[1] - center[1], pos[0] - center[0]) for pos in valid
    ]
    sweep = 0.0
    for index in range(1, len(angles)):
        delta = angles[index] - angles[index - 1]
        while delta > math.pi:
            delta -= 2.0 * math.pi
        while delta < -math.pi:
            delta += 2.0 * math.pi
        sweep += abs(delta)
    return float(sweep)


def _hand_activity_score(
    peak_velocity: float,
    angular_sweep: float,
    *,
    angular_weight: float = 0.35,
    angular_min_rad: float = 0.08,
) -> float:
    """
    Combined wrist activity for role inference.

    Wiping often shows low mean/peak linear motion but clear angular sweep around
    the held object. Angular only counts above angular_min_rad to ignore static jitter.
    """
    linear = peak_velocity
    rotational = angular_sweep * angular_weight if angular_sweep >= angular_min_rad else 0.0
    return max(linear, rotational)


def _infer_hand_roles(
    peak_left: float,
    peak_right: float,
    angular_left: float,
    angular_right: float,
    threshold: float,
) -> tuple[str | None, str | None, float]:
    """
    Wiping/tool hand = higher peak wrist velocity (stroke spikes).
    When peaks are too weak to compare, fall back to angular sweep (subtle wipes).

    Stabilizer rotation in middle segments can inflate angular on the hold hand;
    we ignore angular whenever either peak is strong enough to compare directly.

    Returns (work_hand, stabilize_hand, confidence 0..1).
    """
    min_act = threshold * 1.8
    peak_max = max(peak_left, peak_right)
    strong_peaks = peak_max >= min_act * 1.5

    if peak_max >= min_act:
        slower = min(peak_left, peak_right)
        if slower > 0.0:
            if peak_left >= peak_right * 1.45:
                confidence = min(1.0, (peak_left - peak_right) / max(peak_left, 1e-6))
                return "left hand", "right hand", confidence
            if peak_right >= peak_left * 1.45:
                confidence = min(1.0, (peak_right - peak_left) / max(peak_right, 1e-6))
                return "right hand", "left hand", confidence
        if strong_peaks:
            return None, None, 0.0

    act_left = _hand_activity_score(peak_left, angular_left)
    act_right = _hand_activity_score(peak_right, angular_right)
    work_act = max(act_left, act_right)
    if work_act < min_act:
        return None, None, 0.0
    slower = min(act_left, act_right)
    if slower <= 0.0 or work_act / slower < 1.45:
        return None, None, 0.0
    if act_left >= act_right * 1.45:
        confidence = min(1.0, (act_left - act_right) / max(act_left, 1e-6))
        return "left hand", "right hand", confidence
    if act_right >= act_left * 1.45:
        confidence = min(1.0, (act_right - act_left) / max(act_right, 1e-6))
        return "right hand", "left hand", confidence
    return None, None, 0.0


def infer_clip_hand_roles(
    motion_profiles: list[HandMotionProfile | None],
    threshold: float = DEFAULT_MOTION_THRESHOLD,
) -> tuple[str | None, str | None, float]:
    """
    Pick the single segment with the clearest work/stabilize asymmetry.

    Aggregating max peak per hand across segments lets noisy seek-fallback frames
    on segments 2–4 wash out a clear wipe signal from segment 1.
    """
    best_work: str | None = None
    best_stab: str | None = None
    best_conf = 0.0
    for motion in motion_profiles:
        if motion is None or motion.frames_analyzed < 3:
            continue
        work, stab, conf = _infer_hand_roles(
            motion.peak_left,
            motion.peak_right,
            motion.angular_left,
            motion.angular_right,
            threshold,
        )
        if conf > best_conf:
            best_work, best_stab, best_conf = work, stab, conf
    return best_work, best_stab, best_conf


def stabilizer_rotation_sweep(
    label: str,
    motion: HandMotionProfile | None,
) -> float | None:
    """Angular sweep (radians) of the wrist named in the hold/rotate clause."""
    if motion is None:
        return None
    match = re.search(
        r"\b(?:hold|rotate)\s+.+?\s+with\s+(left hand|right hand)\b",
        label or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    hand = match.group(1).lower()
    return motion.angular_left if hand == "left hand" else motion.angular_right


def _hand_tag_from_draft(draft: str | None) -> str | None:
    """Parse 'in both hands' / 'with right hand' from Atlas draft text."""
    if not draft:
        return None
    blob = draft.casefold()
    if "both hands" in blob:
        return "with both hands"
    if "left hand" in blob:
        return "with left hand"
    if "right hand" in blob:
        return "with right hand"
    return None


def _hand_from_velocities(v_left: float, v_right: float, threshold: float) -> str:
    if v_left > threshold and v_right > threshold:
        slower = min(v_left, v_right)
        faster = max(v_left, v_right)
        if slower > 0 and faster / slower < 1.5:
            return "with both hands"
    if v_left > v_right and v_left > threshold:
        return "with left hand"
    if v_right > v_left and v_right > threshold:
        return "with right hand"
    if v_left > threshold:
        return "with left hand"
    if v_right > threshold:
        return "with right hand"
    return "with right hand"


# Back-compat aliases from the design doc
AtlasDeterministicPipeline = AtlasHybridPipeline
AtlasInMemoryPipeline = AtlasHybridPipeline
