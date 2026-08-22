from browser_engine import LidarBrowser


def test_captures_pcd_and_pointcloud_urls():
    browser = LidarBrowser()
    assert browser._should_capture("https://cdn.example/frame.pcd", "application/octet-stream", 200)
    assert browser._should_capture("https://api.example/v1/pointcloud?id=9", "application/json", 200)
    assert browser._should_capture(
        "https://api.example/lidar/frame/12",
        "application/octet-stream",
        200,
    )


def test_skips_html_js_and_failed_responses():
    browser = LidarBrowser()
    assert not browser._should_capture("https://www.remotasks.com/lidarlite/", "text/html", 200)
    assert not browser._should_capture("https://cdn.example/app.js", "application/javascript", 200)
    assert not browser._should_capture("https://cdn.example/frame.pcd", "application/octet-stream", 404)
    assert not browser._should_capture("https://cdn.example/iframe.html", "text/html", 200)


def test_guess_extension():
    assert LidarBrowser._guess_extension("https://x/a.pcd", b"abc") == ".pcd"
    assert LidarBrowser._guess_extension("https://x/a", b'{"points":[]}') == ".json"
    assert LidarBrowser._guess_extension("https://x/a", b"VERSION 0.7\n") == ".pcd"
    assert LidarBrowser._guess_extension("https://x/a", b"\x00\x01\x02") == ".bin"


def test_write_capture_creates_latest_and_stamp(tmp_path):
    browser = LidarBrowser(captures_dir=tmp_path)
    path = browser._write_capture("https://cdn.example/scan.pcd", b"VERSION 0.7\n" + b"x" * 64)
    assert path.name == "latest_frame.pcd"
    assert path.exists()
    assert (tmp_path / "frame_0000.pcd").exists()
    assert browser.saved_frames
