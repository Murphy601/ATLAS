import pytest
from main import analyze_frame, parse_args

from tests.conftest import synthetic_scene, write_ascii_pcd


def test_analyze_only_writes_json(tmp_path, capsys):
    pytest.importorskip("open3d")
    frame = write_ascii_pcd(tmp_path / "latest_frame.pcd", synthetic_scene())
    cuboids = analyze_frame(frame)
    assert isinstance(cuboids, list)
    out = capsys.readouterr().out
    assert "cuboids" in out


def test_parse_args_analyze_only(tmp_path):
    args = parse_args(["--analyze-only", str(tmp_path / "f.pcd"), "--no-overlay"])
    assert args.no_overlay is True
    assert args.analyze_only.name == "f.pcd"


def test_run_ego_task_falls_back_when_no_live_devtools(monkeypatch):
    import main as ego_main

    monkeypatch.setattr(ego_main, "discover_cdp_http_urls", lambda: [])
    monkeypatch.setattr(
        ego_main,
        "_drive_open_ix_window",
        lambda write=True: {"mode": "ego-window", "played": True, "wrote_captions": 0},
    )
    result = ego_main.run_ego_task(write=False, run_linters=False, cdp_url=None)
    assert result["mode"] == "ego-window"
    assert result["played"] is True
