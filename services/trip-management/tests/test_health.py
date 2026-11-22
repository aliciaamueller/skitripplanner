"""GET /health reports whether this service can use its own database."""

import db
from app import app


def test_health_is_ok_when_the_database_works():
    response = app.test_client().get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["service"] == "trip-management"
    assert "version" in body


def test_health_is_503_when_the_database_is_unreachable(monkeypatch):
    def no_database(attempts=3):
        raise OSError("database down")

    monkeypatch.setattr(db, "get_connection", no_database)
    response = app.test_client().get("/health")
    assert response.status_code == 503
    assert response.get_json()["db"] == "unavailable"
