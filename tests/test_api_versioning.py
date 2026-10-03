from fastapi.testclient import TestClient

from app.main import app


def test_old_unversioned_health_path_is_not_exposed() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 404
