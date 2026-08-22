"""Paths and tunables for the Remotasks LiDAR assistant."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

USER_DATA_DIR = ROOT / "user_data_dir"
DEBUG_CAPTURES = ROOT / "debug_captures"
LATEST_FRAME = DEBUG_CAPTURES / "latest_frame.pcd"
ANALYSIS_RESULT = DEBUG_CAPTURES / "analysis_result.json"

PORTAL_URL = "https://www.remotasks.com/lidarlite/"

OVERLAY_HOST = "127.0.0.1"
OVERLAY_PORT = 8765

# Playwright: prefer installed Chrome (better against anti-bot) else bundled Chromium.
BROWSER_CHANNEL = "chrome"

# Ground-plane RANSAC
PLANE_DISTANCE_THRESHOLD = 0.12
PLANE_RANSAC_N = 3
PLANE_ITERATIONS = 400

# DBSCAN clustering (Open3D units = metres if the cloud is metric)
DBSCAN_EPS = 0.6
DBSCAN_MIN_POINTS = 25

# Drop tiny clusters that are likely noise
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
