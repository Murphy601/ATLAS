from flask.testing import FlaskClient

from overlay import create_app


def test_overlay_serves_empty_result_when_missing(tmp_path):
    app = create_app(tmp_path / "analysis_result.json")
    client: FlaskClient = app.test_client()
    home = client.get("/")
    assert home.status_code == 200
    assert b"LiDAR cuboid overlay" in home.data
    data = client.get("/api/result").get_json()
    assert data["object_count"] == 0
    assert data["cuboids"] == []
