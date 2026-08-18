import base64

import cv2
import numpy as np

from frame_utils import decode_jpeg_bytes, frames_from_base64_list


def test_decode_roundtrip():
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    image[:, :] = (40, 80, 120)
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    decoded = decode_jpeg_bytes(buf.tobytes())
    assert decoded is not None
    assert decoded.shape[0] == 48


def test_frames_from_base64_list():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", image)
    payload = base64.b64encode(buf.tobytes()).decode("utf-8")
    frames = frames_from_base64_list([payload, payload])
    assert len(frames) == 2
