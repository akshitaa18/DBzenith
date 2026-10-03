from fastapi.testclient import TestClient

from app.api.v1.routes.health import router
from app.main import app


class FakeDB:
    def execute(self, statement):
        return None


def test_readiness_uses_database_dependency() -> None:
    from app.api.v1.routes.health import get_db

    def fake_get_db():
        yield FakeDB()

    app.dependency_overrides[get_db] = fake_get_db
    try:
        response = TestClient(app).get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "ok"}
    finally:
        app.dependency_overrides.clear()
