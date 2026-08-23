"""Open3D point-cloud loader and oriented cuboid extractor."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

import config

logger = logging.getLogger("lidar.parser")

try:
    import open3d as o3d
except ImportError:  # pragma: no cover - exercised only when Open3D is missing
    o3d = None  # type: ignore[assignment]


class PointCloudAnalyzer:
    """Read a captured frame and emit oriented 3D bounding cuboids."""

    def __init__(self, frame_path: Path | None = None) -> None:
        self.frame_path = Path(frame_path or config.LATEST_FRAME)

    def extract_object_cuboids(self) -> list[dict[str, Any]]:
        """
        Remove ground with RANSAC, cluster with DBSCAN, return OBB cuboids.

        Each cuboid dict contains center (x, y, z), extent (dx, dy, dz),
        rotation matrix, yaw (theta), and point count.
        """
        if not self.frame_path.exists():
            logger.error("Missing point cloud: %s", self.frame_path)
            return []

        points = self._load_points(self.frame_path)
        if points.size == 0:
            logger.warning("Empty point cloud: %s", self.frame_path)
            return []

        cloud = self._to_open3d(points)
        remaining = self._remove_ground(cloud)
        if remaining is None or len(remaining.points) < config.MIN_CLUSTER_POINTS:
            logger.warning("No off-ground points remaining after plane segmentation")
            return []

        labels = np.array(
            remaining.cluster_dbscan(
                eps=config.DBSCAN_EPS,
                min_points=config.DBSCAN_MIN_POINTS,
                print_progress=False,
            )
        )
        cuboids: list[dict[str, Any]] = []
        for cluster_id in sorted(set(labels.tolist()) - {-1}):
            indices = np.where(labels == cluster_id)[0]
            if indices.size < config.MIN_CLUSTER_POINTS:
                continue
            cluster = remaining.select_by_index(indices.tolist())
            cuboid = self._cluster_to_cuboid(cluster, cluster_id)
            if cuboid is not None:
                cuboids.append(cuboid)
        logger.info("Extracted %d cuboid(s) from %s", len(cuboids), self.frame_path.name)
        return cuboids

    def write_summary(self, cuboids: list[dict[str, Any]], dest: Path | None = None) -> Path:
        dest = Path(dest or config.ANALYSIS_RESULT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": str(self.frame_path),
            "object_count": len(cuboids),
            "cuboids": cuboids,
        }
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return dest

    def _load_points(self, path: Path) -> np.ndarray:
        suffix = path.suffix.lower()
        if suffix in {".pcd", ".ply"} and o3d is not None:
            cloud = o3d.io.read_point_cloud(str(path))
            pts = np.asarray(cloud.points)
            if pts.size:
                return pts.astype(np.float64)
        if suffix == ".bin":
            return self._load_bin(path)
        if suffix == ".json":
            return self._load_json(path)
        if suffix == ".pcd":
            ascii_pts = self._load_pcd_ascii(path)
            if ascii_pts.size:
                return ascii_pts
        raw = path.read_bytes()
        stripped = raw.lstrip()
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            return self._load_json(path)
        if stripped.startswith(b"#") or stripped.startswith(b"VERSION") or stripped.startswith(b"FIELDS"):
            return self._load_pcd_ascii(path)
        return self._load_bin(path)

    @staticmethod
    def _load_bin(path: Path) -> np.ndarray:
        data = np.fromfile(path, dtype=np.float32)
        if data.size == 0:
            return np.empty((0, 3), dtype=np.float64)
        for width in (4, 3):
            if data.size % width == 0:
                pts = data.reshape((-1, width))[:, :3]
                if np.isfinite(pts).all():
                    return pts.astype(np.float64)
        logger.error("Could not reshape binary cloud %s (%d floats)", path, data.size)
        return np.empty((0, 3), dtype=np.float64)

    @staticmethod
    def _load_json(path: Path) -> np.ndarray:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Invalid JSON point cloud %s: %s", path, exc)
            return np.empty((0, 3), dtype=np.float64)
        points = _json_points(payload)
        if points is None:
            logger.error("JSON %s has no recognizable xyz array", path)
            return np.empty((0, 3), dtype=np.float64)
        return np.asarray(points, dtype=np.float64)

    @staticmethod
    def _load_pcd_ascii(path: Path) -> np.ndarray:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        data_index = next((i for i, line in enumerate(lines) if line.strip().upper() == "DATA ASCII"), None)
        if data_index is None:
            logger.error("Unsupported or binary PCD without Open3D: %s", path)
            return np.empty((0, 3), dtype=np.float64)
        rows = []
        for line in lines[data_index + 1 :]:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue
        return np.asarray(rows, dtype=np.float64) if rows else np.empty((0, 3), dtype=np.float64)

    def _to_open3d(self, points: np.ndarray):
        if o3d is None:
            raise RuntimeError("open3d is required for cuboid extraction")
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(points)
        return cloud

    def _remove_ground(self, cloud):
        if len(cloud.points) < config.PLANE_RANSAC_N:
            return cloud
        try:
            _model, inliers = cloud.segment_plane(
                distance_threshold=config.PLANE_DISTANCE_THRESHOLD,
                ransac_n=config.PLANE_RANSAC_N,
                num_iterations=config.PLANE_ITERATIONS,
            )
        except Exception:
            logger.exception("RANSAC plane segmentation failed")
            return cloud
        if len(inliers) < max(config.MIN_CLUSTER_POINTS, int(0.2 * len(cloud.points))):
            return cloud
        remaining = cloud.select_by_index(inliers, invert=True)
        logger.info("Removed %d ground inliers; %d points remain", len(inliers), len(remaining.points))
        return remaining

    @staticmethod
    def _cluster_to_cuboid(cluster, cluster_id: int) -> dict[str, Any] | None:
        try:
            obb = cluster.get_oriented_bounding_box()
        except Exception:
            logger.exception("Oriented bounding box failed for cluster %s", cluster_id)
            return None
        extent = np.asarray(obb.extent, dtype=float)
        if np.any(extent < config.MIN_EXTENT_M):
            return None
        center = np.asarray(obb.center, dtype=float)
        rotation = np.asarray(obb.R, dtype=float)
        yaw = float(np.arctan2(rotation[1, 0], rotation[0, 0]))
        return {
            "id": int(cluster_id),
            "x": round(float(center[0]), 4),
            "y": round(float(center[1]), 4),
            "z": round(float(center[2]), 4),
            "dx": round(float(extent[0]), 4),
            "dy": round(float(extent[1]), 4),
            "dz": round(float(extent[2]), 4),
            "theta": round(yaw, 4),
            "center": [round(float(v), 4) for v in center],
            "extent": [round(float(v), 4) for v in extent],
            "rotation": [[round(float(v), 6) for v in row] for row in rotation],
            "point_count": int(len(cluster.points)),
        }


def _json_points(payload: Any) -> list[list[float]] | None:
    if isinstance(payload, dict):
        for key in ("points", "xyz", "cloud", "data"):
            if key in payload:
                return _json_points(payload[key])
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and {"x", "y", "z"} <= first.keys():
            return [[float(p["x"]), float(p["y"]), float(p["z"])] for p in payload]
        if isinstance(first, (list, tuple)) and len(first) >= 3:
            return [[float(p[0]), float(p[1]), float(p[2])] for p in payload]
    return None
