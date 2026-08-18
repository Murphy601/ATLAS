"""Non-LLM / hybrid Atlas label pipeline: MediaPipe hands + state memory + regex linter."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

try:
    import mediapipe as mp
except ImportError:  # pragma: no cover - optional at import for lint-only tests
    mp = None

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
    detected_hand: str = "with right hand"
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
    _hands: object | None = field(default=None, repr=False)

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

    def _ensure_mediapipe(self):
        if mp is None:
            raise RuntimeError(
                "mediapipe is not installed. Run: pip install mediapipe opencv-python numpy"
            )
        if self._hands is None:
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        return self._hands

    def close(self) -> None:
        if self._hands is not None:
            self._hands.close()
            self._hands = None

    def analyze_frame_motion_from_memory(
        self,
        frame_arrays: list[np.ndarray],
        sample_rate: int = 2,
    ) -> HandMotionProfile:
        """Wrist velocity vectors from BGR/RGB numpy frames (browser capture path)."""
        if not frame_arrays:
            return HandMotionProfile()
        try:
            hands = self._ensure_mediapipe()
        except RuntimeError:
            return HandMotionProfile()

        left_positions: list[tuple[float, float] | None] = []
        right_positions: list[tuple[float, float] | None] = []
        sampled = frame_arrays[:: max(1, sample_rate)]

        for frame in sampled:
            rgb = _to_rgb(frame)
            results = hands.process(rgb)
            left_pos, right_pos = None, None
            if results.multi_hand_landmarks and results.multi_handedness:
                for landmarks, handedness in zip(
                    results.multi_hand_landmarks,
                    results.multi_handedness,
                ):
                    label = handedness.classification[0].label
                    if self.ego_swap_hands:
                        label = "Right" if label == "Left" else "Left"
                    wrist = landmarks.landmark[0]
                    pos = (wrist.x, wrist.y)
                    if label == "Left":
                        left_pos = pos
                    else:
                        right_pos = pos
            left_positions.append(left_pos)
            right_positions.append(right_pos)

        v_left = _mean_wrist_velocity(left_positions)
        v_right = _mean_wrist_velocity(right_positions)
        detected = _hand_from_velocities(v_left, v_right, self.motion_threshold)
        start_left = left_positions[0] is not None if left_positions else False
        start_right = right_positions[0] is not None if right_positions else False
        return HandMotionProfile(
            v_left=v_left,
            v_right=v_right,
            detected_hand=detected,
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
        motion = self.analyze_frame_motion_from_memory(frame_arrays)
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


def _hand_from_velocities(v_left: float, v_right: float, threshold: float) -> str:
    if v_left > threshold and v_right > threshold:
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
