from pathlib import Path

import cv2
import numpy as np

from frame_extractor import extract_frames_from_video, format_timestamp


def test_format_timestamp():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(3.9) == "00:03"
    assert format_timestamp(65) == "01:05"
    assert format_timestamp(-1) == "00:00"


def test_extract_frames_from_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.mp4"
    assert extract_frames_from_video(str(missing)) == []


def test_extract_frames_from_synthetic_video(tmp_path):
    video_path = tmp_path / "sample.mp4"
    fps = 10
    width, height = 80, 60
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    assert writer.isOpened()
    for index in range(fps * 3):
        frame = np.full((height, width, 3), (index * 8) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    frames = extract_frames_from_video(str(video_path), interval_seconds=1.0)
    assert len(frames) >= 3
    timestamp, encoded = frames[0]
    assert timestamp == 0.0
    assert isinstance(encoded, str)
    assert len(encoded) > 100
