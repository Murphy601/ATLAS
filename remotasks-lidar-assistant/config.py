"""Paths and tunables. Default workflow attaches to IX Browser — it never launches Chrome."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

USER_DATA_DIR = ROOT / "user_data_dir"
DEBUG_CAPTURES = ROOT / "debug_captures"
LATEST_FRAME = DEBUG_CAPTURES / "latest_frame.pcd"
ANALYSIS_RESULT = DEBUG_CAPTURES / "analysis_result.json"

PORTAL_URL = "https://www.remotasks.com/lidarlite/"

OVERLAY_HOST = "127.0.0.1"
OVERLAY_PORT = 8765

# IX Browser / Chrome DevTools. You open the profile; the engine only attaches.
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
CDP_PORTS = range(9222, 9232)
TASK_WAIT_SECONDS = float(os.environ.get("TASK_WAIT_SECONDS", "600"))
ATTACH_WAIT_SECONDS = float(os.environ.get("ATTACH_WAIT_SECONDS", "180"))

BROWSER_CHANNEL = "chrome"

PLANE_DISTANCE_THRESHOLD = 0.12
PLANE_RANSAC_N = 3
PLANE_ITERATIONS = 400
DBSCAN_EPS = 0.6
DBSCAN_MIN_POINTS = 25
MIN_CLUSTER_POINTS = 25
MIN_EXTENT_M = 0.15

POLL_INTERVAL_SEC = 0.4

CAPTURE_EXTENSIONS = (".pcd", ".bin", ".ply")
CAPTURE_URL_TOKENS = ("pointcloud", "point-cloud", "point_cloud")
CAPTURE_FRAME_TOKENS = ("lidar", "pcd", "cloud", "scan", "points")
SKIP_CONTENT_TYPES = (
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "image/",
    "font/",
    "audio/",
    "video/mp4",
    "video/webm",
)
