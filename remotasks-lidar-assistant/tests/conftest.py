from pathlib import Path

import numpy as np


def write_ascii_pcd(path: Path, points: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\n"
        "FIELDS x y z\n"
        "SIZE 4 4 4\n"
        "TYPE F F F\n"
        "COUNT 1 1 1\n"
        f"WIDTH {len(points)}\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {len(points)}\n"
        "DATA ascii\n"
    )
    body = "\n".join(f"{x:.5f} {y:.5f} {z:.5f}" for x, y, z in points)
    path.write_text(header + body + "\n", encoding="utf-8")
    return path


def synthetic_scene(rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng(0)
    gx, gy = np.meshgrid(np.linspace(-8, 8, 40), np.linspace(-8, 8, 40))
    ground = np.column_stack([gx.ravel(), gy.ravel(), rng.normal(0, 0.01, gx.size)])

    def box(center, size, count):
        return center + rng.uniform(-0.5, 0.5, size=(count, 3)) * size

    car = box(np.array([4.0, 0.0, 0.8]), np.array([4.0, 1.8, 1.5]), 400)
    cone = box(np.array([-3.0, 2.5, 0.45]), np.array([0.4, 0.4, 0.9]), 120)
    return np.vstack([ground, car, cone])
