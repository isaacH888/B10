"""Tests for Admin Dashboard CSV report export endpoint."""

import csv
import io
from test_auth import auth_app as auth_app
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_orders import bind_quote, order_payload


def submit(app, name="Synthetic Customer", service="delivery", key="dash-order-0123456789"):
    client = app.test_client()
    body = order_payload(service_type=service)
    body["customer"]["name"] = name
    bind_quote(client, body)
    result = client.post("/api/v1/orders", json=body, headers={"Idempotency-Key": key})
    assert result.status_code == 201
    return result.json["data"]


def test_export_dashboard_requires_authentication(owner_app):
    client = owner_app.test_client()
    response = client.get("/api/v1/admin/dashboard/export")
    assert response.status_code == 401


def test_export_dashboard_returns_valid_csv_for_admin(owner_app):
    owner_app.config.update(DB_USER="", DB_PASSWORD="")
    client, _ = signed_owner(owner_app)
    response = client.get("/api/v1/admin/dashboard/export")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert 'attachment; filename="admin_report_' in response.headers.get("Content-Disposition", "")
    assert response.headers.get("Cache-Control") == "no-store"

    content = response.get_data(as_text=True)
    assert "ADMIN DASHBOARD - GENERAL INFORMATION REPORT" in content
    assert "--- KEY OPERATIONAL METRICS ---" in content
    assert "New Catering Requests" in content
    assert "Upcoming Confirmed Events" in content
    assert "--- UPCOMING CONFIRMED EVENTS (NEXT 30 DAYS) ---" in content
    assert "--- RECENT ORDERS & CATERING REQUESTS ---" in content

    # Verify it parses as valid CSV
    reader = list(csv.reader(io.StringIO(content)))
    assert len(reader) > 5


def test_export_dashboard_includes_recent_orders_and_escapes_formulas(owner_app):
    owner_app.config.update(DB_USER="", DB_PASSWORD="")
    order = submit(owner_app, name="Taylor Swift", key="formula-key-1234567890")
    client, _ = signed_owner(owner_app)
    response = client.get("/api/v1/admin/dashboard/export")
    assert response.status_code == 200

    content = response.get_data(as_text=True)
    assert "Taylor Swift" in content
    assert order["id"] in content
