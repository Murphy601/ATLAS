from pathlib import Path

import pytest

open3d = pytest.importorskip("open3d")

from pcd_parser import PointCloudAnalyzer

from tests.conftest import synthetic_scene, write_ascii_pcd


def test_missing_file_returns_empty(tmp_path: Path):
    analyzer = PointCloudAnalyzer(tmp_path / "missing.pcd")
    assert analyzer.extract_object_cuboids() == []


def test_empty_cloud_returns_empty(tmp_path: Path):
    import numpy as np

    path = write_ascii_pcd(tmp_path / "empty.pcd", np.empty((0, 3)))
    analyzer = PointCloudAnalyzer(path)
    assert analyzer.extract_object_cuboids() == []


def test_extracts_cuboids_from_synthetic_scene(tmp_path: Path):
    path = write_ascii_pcd(tmp_path / "latest_frame.pcd", synthetic_scene())
    cuboids = PointCloudAnalyzer(path).extract_object_cuboids()
    assert len(cuboids) >= 1
    for box in cuboids:
        assert {"x", "y", "z", "dx", "dy", "dz", "theta", "rotation"} <= box.keys()
        assert box["dx"] > 0 and box["dy"] > 0 and box["dz"] > 0


def test_json_and_bin_loaders(tmp_path: Path):
    import json

    import numpy as np

    points = np.array([[0.0, 0.0, 1.0], [0.2, 0.0, 1.0], [0.0, 0.2, 1.1]], dtype=np.float32)
    json_path = tmp_path / "cloud.json"
    json_path.write_text(json.dumps({"points": points.tolist()}), encoding="utf-8")
    loaded = PointCloudAnalyzer(json_path)._load_json(json_path)
    assert loaded.shape == (3, 3)

    bin_path = tmp_path / "cloud.bin"
    np.hstack([points, np.ones((3, 1), dtype=np.float32)]).astype(np.float32).tofile(bin_path)
    loaded_bin = PointCloudAnalyzer(bin_path)._load_bin(bin_path)
    assert loaded_bin.shape == (3, 3)


def test_write_summary(tmp_path: Path):
    dest = tmp_path / "analysis_result.json"
    path = write_ascii_pcd(tmp_path / "frame.pcd", synthetic_scene())
    analyzer = PointCloudAnalyzer(path)
    cuboids = analyzer.extract_object_cuboids()
    written = analyzer.write_summary(cuboids, dest)
    assert written.exists()
    assert "cuboids" in written.read_text(encoding="utf-8")
