"""Decode in-memory JPEG/base64 frames for hybrid CV pipeline."""

from __future__ import annotations

import base64

import cv2
import numpy as np


def decode_jpeg_bytes(payload: bytes) -> np.ndarray | None:
    array = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    return image


def decode_jpeg_base64(payload: str) -> np.ndarray | None:
    try:
        raw = base64.b64decode(payload)
    except Exception:
        return None
    return decode_jpeg_bytes(raw)


def frames_from_base64_list(frames_b64: list[str]) -> list[np.ndarray]:
    decoded: list[np.ndarray] = []
    for frame in frames_b64:
        image = decode_jpeg_base64(frame)
        if image is not None:
            decoded.append(image)
    return decoded
