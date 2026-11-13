from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.auth import create_password_reset, digest
from backend.app.db import iso, transaction, utcnow
from backend.app.main import app
from backend.app.models import PasswordReset, SecurityAudit, User
from test_security import BODY, ORIGIN, register

NEW_PASSWORD = "new-private-recovery-password"


def grant_for(user_id):
    with transaction() as session:
        return create_password_reset(session, user_id)[0]


def redeem(client, token, password=NEW_PASSWORD, headers=ORIGIN):
    return client.post("/api/v1/auth/password/reset", headers=headers,
                       json={"token": token, "new_password": password})


def test_recovery_is_single_use_preserves_identity_and_revokes_all_sessions(session):
    with TestClient(app) as first, TestClient(app) as second:
        result, _ = register(first)
        user_id = result["user"]["id"]
        assert second.post("/api/v1/auth/login", headers=ORIGIN,
                           json={"username": BODY["username"], "password": BODY["password"]}).status_code == 200
        token = grant_for(user_id)
        stored = session.get(PasswordReset, digest(token))
        assert stored is not None
        assert session.get(PasswordReset, token) is None
        # Issuing a recovery link alone must not interrupt access.
        assert first.get("/api/v1/auth/me").json()["user"]["id"] == user_id
        assert redeem(first, token).status_code == 200
        assert first.get("/api/v1/auth/me").json()["user"] is None
        assert second.get("/api/v1/auth/me").json()["user"] is None
        assert redeem(first, token).status_code == 400
        assert first.post("/api/v1/auth/login", headers=ORIGIN,
                          json={"username": BODY["username"], "password": BODY["password"]}).status_code == 401
        logged_in = first.post("/api/v1/auth/login", headers=ORIGIN,
                               json={"username": BODY["username"], "password": NEW_PASSWORD})
        assert logged_in.status_code == 200
        assert logged_in.json()["user"] == result["user"]
        session.expire_all()
        assert session.get(User, user_id).password_hash.startswith("$argon2id$")
        assert "password_reset_sessions_revoked" in session.scalars(select(SecurityAudit.action)).all()


@pytest.mark.parametrize("case", ["expired", "invalid", "disabled", "replaced"])
def test_invalid_grants_never_change_password(session, case):
    with TestClient(app) as client:
        result, _ = register(client)
        user_id = result["user"]["id"]
        token = grant_for(user_id)
        old_hash = session.get(User, user_id).password_hash
        if case == "expired":
            session.get(PasswordReset, digest(token)).expires_at = iso(utcnow()-timedelta(seconds=1))
            session.commit()
        elif case == "invalid":
            token = "invalid-recovery-token"*2
        elif case == "disabled":
            session.get(User, user_id).disabled = True
            session.commit()
        else:
            grant_for(user_id)
        response = redeem(client, token)
        assert response.status_code == 400
        assert response.json()["detail"] == "Recovery link is invalid or expired. Ask for a new link."
        session.expire_all()
        assert session.get(User, user_id).password_hash == old_hash


def test_recovery_checks_origin_and_password_policy_before_consuming_grant(session):
    with TestClient(app) as client:
        result, _ = register(client)
        token = grant_for(result["user"]["id"])
        assert redeem(client, token, headers={"Origin": "https://attacker.invalid"}).status_code == 403
        assert redeem(client, token, password="short").status_code == 422
        assert redeem(client, token).status_code == 200
        assert "no-store" in client.get("/api/v1/auth/me").headers["cache-control"]


def test_password_change_cancels_outstanding_recovery(session):
    with TestClient(app) as client:
        result, headers = register(client)
        token = grant_for(result["user"]["id"])
        assert client.post("/api/v1/auth/password", headers=headers,
                           json={"current_password": BODY["password"], "new_password": NEW_PASSWORD}).status_code == 200
        assert redeem(client, token).status_code == 400


def test_recovery_is_rate_limited_without_exposing_users(session):
    with TestClient(app) as client:
        for _ in range(10):
            assert redeem(client, "invalid-recovery-token"*2).status_code == 400
        response = redeem(client, "invalid-recovery-token"*2)
        assert response.status_code == 429
        assert response.headers["retry-after"]
        assert not any(getattr(route,"path","")=="/api/v1/auth/password/reset/request" for route in app.routes)


def test_login_trims_username_but_never_alters_password(session):
    with TestClient(app) as client:
        register(client)
        response = client.post("/api/v1/auth/login", headers=ORIGIN,
                               json={"username": " PASSENGER ", "password": BODY["password"]})
        assert response.status_code == 200
        assert client.post("/api/v1/auth/login", headers=ORIGIN,
                           json={"username": "passenger", "password": BODY["password"]+" "}).status_code == 401
        # Short mistyped sign-in passwords yield the normal credential error.
        assert client.post("/api/v1/auth/login", headers=ORIGIN,
                           json={"username": "passenger", "password": "short"}).status_code == 401


def test_concurrent_recovery_consumes_grant_once_on_postgres(session):
    if session.bind.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock concurrency check")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with TestClient(app) as client:
        result, _ = register(client)
        token = grant_for(result["user"]["id"])
        barrier = Barrier(2)
        def attempt(_):
            barrier.wait(timeout=10)
            return redeem(client, token).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
        assert sorted(outcomes) == [200, 400]
