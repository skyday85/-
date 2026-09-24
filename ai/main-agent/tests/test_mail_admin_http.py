from __future__ import annotations

import importlib


def test_mail_admin_http_permissions_and_scoped_inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_ORGANIZATION_ID", "company-a")
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_USER_ID", "boss")
    monkeypatch.setenv("MAIL_BOOTSTRAP_OWNER_EMAIL", "boss@example.com")
    monkeypatch.setenv("MAIL_DATABASE_PATH", str(tmp_path / "mail.sqlite3"))
    monkeypatch.setenv("FLEET_API_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("FLEET_MAIN_AGENT_API_KEY", "local-test-key")

    from fastapi.testclient import TestClient
    service = importlib.import_module("http_api.app")
    service = importlib.reload(service)
    client = TestClient(service.app)
    boss = {"X-Authenticated-User": "boss", "X-Organization-Id": "company-a"}
    employee = {"X-Authenticated-User": "staff", "X-Organization-Id": "company-a"}

    bootstrap = client.get("/client/bootstrap?platform=mac", headers=boss)
    assert bootstrap.status_code == 200
    assert bootstrap.json()["mail_identity"]["role"] == "owner"

    created = client.post("/mail/admin/users", headers=boss, json={
        "user_id": "staff", "email": "staff@example.com",
        "display_name": "Staff", "role": "member",
    })
    assert created.status_code == 200
    assert created.json()["user_id"] == "staff"

    assert client.get("/mail/admin/users", headers=employee).status_code == 403
    assert client.get("/mail/inbox", headers=employee).json() == []
    assert client.get("/mail/inbox", headers={
        "X-Authenticated-User": "staff", "X-Organization-Id": "company-b",
    }).status_code == 403

    forged_grant = client.post("/mail/admin/grants", headers=boss, json={
        "owner_user_id": "boss", "provider": "gmail", "account_id": "not-linked",
        "recipient_user_id": "staff",
    })
    assert forged_grant.status_code == 403

    raw_rule = client.post("/mail/admin/rules", headers=boss, json={
        "owner_user_id": "boss", "provider": "gmail", "account_id": "not-linked",
        "match_text": "invoice", "destination": "finance@example.com",
    })
    assert raw_rule.status_code == 422

    user_off = client.post("/mail/admin/users/staff/status", headers=boss, json={"active": False})
    assert user_off.status_code == 200
    assert client.get("/client/bootstrap?platform=mac", headers=employee).status_code == 403
