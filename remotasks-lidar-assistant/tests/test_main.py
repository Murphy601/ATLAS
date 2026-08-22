from main import analyze_frame, parse_args

from tests.conftest import synthetic_scene, write_ascii_pcd


def test_analyze_only_writes_json(tmp_path, capsys):
    frame = write_ascii_pcd(tmp_path / "latest_frame.pcd", synthetic_scene())
    cuboids = analyze_frame(frame)
    assert isinstance(cuboids, list)
    out = capsys.readouterr().out
    assert "cuboids" in out


def test_parse_args_analyze_only(tmp_path):
    args = parse_args(["--analyze-only", str(tmp_path / "f.pcd"), "--no-overlay"])
    assert args.no_overlay is True
    assert args.analyze_only.name == "f.pcd"
