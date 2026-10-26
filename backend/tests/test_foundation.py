"""Verify shared infrastructure behavior without implementing teammate features."""

import os

import pytest

from app import create_app


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("DB_USER", "")
    monkeypatch.setenv("DB_PASSWORD", "")
    return create_app({"TESTING": True})


def test_liveness_does_not_claim_database_readiness(app):
    client = app.test_client()
    live = client.get("/api/v1/live")
    assert live.status_code == 200
    assert live.json["data"] == {"status": "ok"}
    assert live.headers["X-Request-ID"] == live.json["meta"]["request_id"]
    assert live.headers["Cache-Control"] == "no-store"
    readiness = client.get("/api/v1/health")
    assert readiness.status_code == 503
    assert readiness.json["data"]["database"] == "unavailable"


def test_only_allowed_origin_receives_credentialed_cors(app):
    client = app.test_client()
    allowed = client.get("/api/v1/live", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert allowed.headers["Access-Control-Allow-Credentials"] == "true"
    denied = client.get("/api/v1/live", headers={"Origin": "https://unapproved.example.invalid"})
    assert "Access-Control-Allow-Origin" not in denied.headers
    preflight = client.options("/api/v1/live", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Content-Type"})
    assert preflight.status_code == 200
    assert "Content-Type" in preflight.headers["Access-Control-Allow-Headers"]


def test_unimplemented_feature_routes_are_not_mock_services(app):
    response = app.test_client().post("/api/v1/admin/login", json={})
    assert response.status_code == 404
    assert response.json["error"]["code"] == "not_found"


def test_database_failure_does_not_expose_driver_details(app, monkeypatch):
    import importlib
    import pymysql
    app.config.update(DB_USER="synthetic_test_user", DB_PASSWORD="synthetic_test_only")

    def fail_connection(**options):
        raise pymysql.OperationalError("PRIVATE_DRIVER_DETAIL")

    monkeypatch.setattr(importlib.import_module("app.health").pymysql, "connect", fail_connection)
    response = app.test_client().get("/api/v1/health")
    assert response.status_code == 503
    assert "PRIVATE_DRIVER_DETAIL" not in response.get_data(as_text=True)


def test_hosted_configuration_has_no_development_secret_fallback(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://site.example.invalid")
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="Hosted environments"):
        create_app({"TESTING": True})


@pytest.mark.database
@pytest.mark.skipif(os.getenv("RUN_DATABASE_INTEGRATION") != "1", reason="No disposable MySQL configured")
def test_real_mysql_connectivity():
    response = create_app({"TESTING": True}).test_client().get("/api/v1/health")
    assert response.status_code == 200
    assert response.json["data"]["database"] == "ok"
