from fastapi.testclient import TestClient

from api.main import app


def test_health_returns_ok_and_min_app_version():
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # 기본값 — MIN_APP_VERSION env로 조절
    assert body["min_app_version"] == "1.0.0"
