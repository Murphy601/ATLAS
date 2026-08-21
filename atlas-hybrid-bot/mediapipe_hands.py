"""MediaPipe hand tracking — legacy Solutions API + Tasks API (mediapipe 1.0+)."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np

try:
    import mediapipe as mp
except ImportError:
    mp = None  # type: ignore[assignment]

HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"

_hand_tracker: "HandTracker | None" = None
_init_warning_printed = False


def _ensure_hand_model() -> Path:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 500_000:
        return MODEL_PATH
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"[Hybrid]: Downloading MediaPipe hand model (~7.5 MB) to {MODEL_PATH.name}..."
    )
    urllib.request.urlretrieve(HAND_MODEL_URL, MODEL_PATH)
    return MODEL_PATH


class HandTracker:
    """Detect left/right wrist positions from RGB frames."""

    def __init__(self) -> None:
        self._backend: str | None = None
        self._legacy = None
        self._tasks = None

    def _init_legacy(self) -> None:
        self._legacy = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._backend = "legacy"

    def _init_tasks(self) -> None:
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision import (
            HandLandmarker,
            HandLandmarkerOptions,
            RunningMode,
        )

        model_path = _ensure_hand_model()
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._tasks = HandLandmarker.create_from_options(options)
        self._backend = "tasks"

    def ensure_ready(self) -> None:
        global _init_warning_printed
        if self._backend is not None:
            return
        if mp is None:
            raise RuntimeError("mediapipe is not installed")
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
            self._init_legacy()
            return
        try:
            self._init_tasks()
        except Exception as exc:
            if not _init_warning_printed:
                print(
                    f"[Hybrid]: MediaPipe Tasks init failed ({exc}). "
                    "Hand detection disabled — using draft text + regex only."
                )
                _init_warning_printed = True
            raise

    def process_rgb(
        self,
        rgb: np.ndarray,
        *,
        ego_swap_hands: bool,
    ) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
        """Return (left_wrist_xy, right_wrist_xy) in normalized coords."""
        self.ensure_ready()
        left_pos: tuple[float, float] | None = None
        right_pos: tuple[float, float] | None = None

        if self._backend == "legacy":
            results = self._legacy.process(rgb)
            if results.multi_hand_landmarks and results.multi_handedness:
                for landmarks, handedness in zip(
                    results.multi_hand_landmarks,
                    results.multi_handedness,
                ):
                    label = handedness.classification[0].label
                    if ego_swap_hands:
                        label = "Right" if label == "Left" else "Left"
                    wrist = landmarks.landmark[0]
                    pos = (wrist.x, wrist.y)
                    if label == "Left":
                        left_pos = pos
                    else:
                        right_pos = pos
            return left_pos, right_pos

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._tasks.detect(mp_image)
        if result.hand_landmarks:
            for index, hand_landmarks in enumerate(result.hand_landmarks):
                label = "Right"
                if result.handedness and index < len(result.handedness):
                    categories = result.handedness[index]
                    if categories:
                        label = categories[0].category_name or "Right"
                if ego_swap_hands:
                    label = "Right" if label == "Left" else "Left"
                wrist = hand_landmarks[0]
                pos = (wrist.x, wrist.y)
                if label == "Left":
                    left_pos = pos
                else:
                    right_pos = pos
        return left_pos, right_pos

    def close(self) -> None:
        if self._legacy is not None:
            self._legacy.close()
            self._legacy = None
        if self._tasks is not None:
            self._tasks.close()
            self._tasks = None
        self._backend = None


def get_hand_tracker() -> HandTracker:
    global _hand_tracker
    if _hand_tracker is None:
        _hand_tracker = HandTracker()
    return _hand_tracker


def close_hand_tracker() -> None:
    global _hand_tracker
    if _hand_tracker is not None:
        _hand_tracker.close()
        _hand_tracker = None
