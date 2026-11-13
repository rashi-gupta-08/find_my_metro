from datetime import timedelta
import hashlib
import os
import subprocess
import sys
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.app.auth import COOKIE, digest, limit
from backend.app.db import iso, utcnow
from backend.app.main import app
from backend.app.models import AuthSession, Device, Observation, User
from backend.app.config import Settings
from test_pipeline import sensor

ORIGIN = {"Origin": "http://localhost:5173"}
BODY = {"username": "passenger", "password": "a-long-private-password", "display_name": "Passenger"}


def register(client, **changes):
    result = client.post("/api/v1/auth/register", headers=ORIGIN, json={**BODY, **changes})
    assert result.status_code == 201, result.text
    return result.json(), {**ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]}


def test_passwords_hashed_sessions_not_stored_in_plaintext(session):
    with TestClient(app) as client:
        result, headers = register(client)
        token = client.cookies.get(COOKIE)
        stored = session.get(User, result["user"]["id"])
        assert stored.password_hash.startswith("$argon2id$")
        assert BODY["password"] not in stored.password_hash
        assert session.get(AuthSession, digest(token)) is not None
        assert session.get(AuthSession, token) is None
        assert not result["user"]["verified_contributor"]
        assert "httponly" in client.post("/api/v1/auth/login", headers=ORIGIN, json={k: BODY[k] for k in ("username", "password")}).headers["set-cookie"].lower()


def test_registration_cannot_grant_admin_or_verified_status(session):
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register", headers=ORIGIN, json={**BODY, "role": "admin"}).status_code == 422
        assert client.post("/api/v1/auth/register", headers=ORIGIN, json={**BODY, "verified_contributor": True}).status_code == 422


def test_login_normalizes_username_and_rejects_wrong_password(session):
    with TestClient(app) as client:
        register(client)
        assert client.post("/api/v1/auth/login", headers=ORIGIN, json={"username": "PASSENGER", "password": BODY["password"]}).status_code == 200
        assert client.post("/api/v1/auth/login", headers=ORIGIN, json={"username": "passenger", "password": "wrong-long-password"}).status_code == 401
        assert client.post("/api/v1/auth/login", headers=ORIGIN, json={"username": "not_registered", "password": "wrong-long-password"}).json()["detail"] == "Incorrect username or password"


def test_mutations_require_origin_and_csrf(session):
    with TestClient(app) as client:
        result, headers = register(client)
        assert client.post("/api/v1/auth/logout", headers=ORIGIN, json={}).status_code == 403
        assert client.post("/api/v1/auth/logout", headers={**headers, "Origin": "https://attacker.example"}, json={}).status_code == 403
        assert client.post("/api/v1/auth/logout", headers=headers, json={}).status_code == 200
        assert client.get("/api/v1/auth/me").json()["user"] is None


def test_login_requires_permitted_origin(session):
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register", json=BODY).status_code == 403


def test_password_change_revokes_all_sessions(session):
    with TestClient(app) as one, TestClient(app) as two:
        result, headers = register(one)
        assert two.post("/api/v1/auth/login", headers=ORIGIN, json={k: BODY[k] for k in ("username", "password")}).status_code == 200
        assert one.post("/api/v1/auth/password", headers=headers, json={"current_password": BODY["password"], "new_password": "a-new-private-password"}).status_code == 200
        assert two.get("/api/v1/auth/me").json()["user"] is None
        assert one.post("/api/v1/auth/login", headers=ORIGIN, json={"username": "passenger", "password": BODY["password"]}).status_code == 401
        assert one.post("/api/v1/auth/login", headers=ORIGIN, json={"username": "passenger", "password": "a-new-private-password"}).status_code == 200


def test_account_deletion_reauthenticates_and_removes_owned_reports(session):
    with TestClient(app) as client:
        result, headers = register(client)
        session.add(Observation(event_id="report-to-delete", source="crowd", payload={"authenticated_contributor": result["user"]["id"]},
                                received_at=iso(utcnow()), fingerprint="f"*64, available_at=iso(utcnow())))
        session.commit()
        assert client.post("/api/v1/auth/account/delete", headers=headers, json={"current_password": "wrong"}).status_code == 401
        assert client.post("/api/v1/auth/account/delete", headers=headers, json={"current_password": BODY["password"]}).status_code == 200
        session.expire_all()
        assert session.get(User, result["user"]["id"]) is None
        assert session.get(Observation, "report-to-delete") is None
        assert client.get("/api/v1/auth/me").json()["user"] is None


def test_expired_session_cannot_submit(session):
    with TestClient(app) as client:
        _, headers = register(client)
        stored = session.get(AuthSession, digest(client.cookies.get(COOKIE)))
        stored.expires_at = iso(utcnow()-timedelta(seconds=1))
        session.commit()
        assert client.post("/api/v1/crowd-reports/batch", headers=headers, json={"reports": [{}]}).status_code == 401


def test_passengers_cannot_view_admin_audit_or_import_timetable(session):
    with TestClient(app) as client:
        _, headers = register(client)
        assert client.get("/api/v1/events").status_code == 403


def test_report_status_is_private_outside_tests(session, monkeypatch):
    from backend.app.config import settings
    with TestClient(app) as first, TestClient(app) as second:
        one, _ = register(first)
        register(second, username="other_user")
        session.add(Observation(event_id="private-event-id", source="crowd", payload={"authenticated_contributor": one["user"]["id"]},
                                received_at=iso(utcnow()), fingerprint="a"*64, status="queued", available_at=iso(utcnow())))
        session.commit()
        monkeypatch.setattr(settings, "app_env", "local")
        assert first.get("/api/v1/events/private-event-id").status_code == 200
        assert second.get("/api/v1/events/private-event-id").status_code == 404


def test_device_keys_are_scoped_and_revocable(session, trip):
    session.add(Device(node_id="node-yellow-outbound-1", key_hash=digest("secure-device-token"), created_at=iso(utcnow())))
    session.commit()
    with TestClient(app) as client:
        assert client.post("/api/v1/sensor-events", headers={"X-API-Key": "secure-device-token"}, json=sensor(trip, 1)).status_code == 202
        assert client.post("/api/v1/sensor-events", headers={"X-API-Key": "secure-device-token"}, json=sensor(trip, 2)).status_code == 401
        stored = session.get(Device, "node-yellow-outbound-1"); stored.disabled = True; session.commit()
        assert client.post("/api/v1/sensor-events", headers={"X-API-Key": "secure-device-token"}, json=sensor(trip, 1)).status_code == 401


def test_body_limit_and_host_validation(session):
    with TestClient(app) as client:
        assert client.post("/api/v1/sensor-events", content=b"x"*140000).status_code == 413
        assert client.get("/api/v1/network", headers={"Host": "attacker.example"}).status_code == 400
        response = client.get("/api/v1/network")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-request-id"]


def test_shared_rate_limit_counts_failed_requests(session):
    from fastapi import HTTPException
    limit("person", "test", 2)
    limit("person", "test", 2)
    with pytest.raises(HTTPException) as error:
        limit("person", "test", 2)
    assert error.value.status_code == 429


def test_forwarded_ip_is_used_only_for_explicitly_trusted_proxy(monkeypatch):
    from backend.app.auth import client_identity
    from backend.app.config import settings
    from starlette.requests import Request
    request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": [(b"x-forwarded-for", b"198.51.100.7")]})
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "")
    assert client_identity(request) == "127.0.0.1"
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    assert client_identity(request) == "198.51.100.7"


def test_password_hashing_has_bounded_memory_concurrency(monkeypatch):
    from fastapi import HTTPException
    from backend.app import auth
    import threading
    semaphore = threading.BoundedSemaphore(1)
    semaphore.acquire()
    monkeypatch.setattr(auth,"hash_slots",semaphore)
    with pytest.raises(HTTPException) as error:
        auth.hash_password("long-secret-password")
    assert error.value.status_code == 429
    semaphore.release()


def test_production_configuration_fails_closed():
    common = dict(_env_file=None, app_env="production", auth_secret="x"*64)
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(**common, database_url="sqlite:///:memory:")
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(**common, database_url="postgresql+psycopg://runtime:secret@db/metro", secure_cookies=False)
    with pytest.raises(ValueError, match="Simulation"):
        Settings(_env_file=None, app_env="local", auth_secret="x"*64, simulation_enabled=True)


def test_local_profile_has_no_demo_routes_or_mock_network(tmp_path):
    environment = {**os.environ, "APP_ENV": "local", "AUTH_SECRET": "x"*64, "DATABASE_URL": "sqlite:///"+(tmp_path/"local.db").as_posix(),
                   "SIMULATION_ENABLED": "false", "NETWORK_FILE": "", "SENSOR_API_KEY": "", "ADMIN_API_KEY": "", "CROWD_TOKENS": ""}
    code = "from backend.app.main import app; from backend.app.network import network_payload; assert not any('/demo/' in getattr(r, 'path', '') for r in app.routes); assert network_payload()['stations'] == []; assert network_payload()['simulated'] is False"
    result = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode()
