import base64
import os

import cv2


def extract_frames_from_video(
    video_path: str, interval_seconds: float = 1.0
) -> list[tuple[float, str]]:
    """Reads a local video file, extracts keyframes, and encodes them to base64."""
    if not os.path.exists(video_path):
        print(f"[Frame Extractor Error]: File not found: {video_path}")
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[Frame Extractor Error]: Unable to open video: {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval = max(1, int(round(fps * interval_seconds)))

    timestamp_frames = []
    frame_count = 0

    print(f"[Frame Extractor]: Processing '{video_path}'...")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % frame_interval == 0:
            current_sec = frame_count / fps
            resized_frame = cv2.resize(frame, (640, 360))
            _, buffer = cv2.imencode(".jpg", resized_frame)
            base64_str = base64.b64encode(buffer).decode("utf-8")
            timestamp_frames.append((current_sec, base64_str))

        frame_count += 1

    cap.release()
    print(f"[Frame Extractor]: Extracted {len(timestamp_frames)} keyframes.")
    return timestamp_frames


def format_timestamp(seconds: float) -> str:
    """Converts raw float seconds into MM:SS format."""
    total_seconds = max(0, int(seconds))
    mins = total_seconds // 60
    secs = total_seconds % 60
    return f"{mins:02d}:{secs:02d}"
