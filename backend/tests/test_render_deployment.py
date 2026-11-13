"""Deployment configuration checks; no cloud credentials or network required."""
import hashlib

import pytest
from sqlalchemy.engine import make_url

from backend.app.render_entrypoint import prepare_environment


def render_environment():
    return {
        "RENDER_DATABASE_URL": "postgresql://schema_owner:owner_fixture@db.internal:5432/metro",
        "RENDER_APP_PASSWORD": "different-runtime-password-fixture" * 2,
        "RENDER_AUTH_SEED": "platform-generated-auth-seed-fixture" * 2,
        "RENDER_EXTERNAL_HOSTNAME": "metro-api.test",
        "CORS_ORIGINS": "https://metro-frontend.test",
        "ALLOWED_HOSTS": "localhost,127.0.0.1",
        "MIGRATION_DATABASE_URL": "must-not-reach-the-application",
    }


def test_runtime_uses_a_separate_role_and_strips_release_credentials():
    original = render_environment()
    environment, owner, password = prepare_environment(original)
    runtime = make_url(environment["DATABASE_URL"])
    assert runtime.username == "metro_app"
    assert runtime.password == password
    assert owner.username == "schema_owner"
    assert runtime.drivername == "postgresql+psycopg"
    assert runtime.query["sslmode"] == "require"
    assert owner.password not in environment["DATABASE_URL"]
    assert not {"RENDER_DATABASE_URL", "RENDER_APP_PASSWORD", "RENDER_AUTH_SEED", "MIGRATION_DATABASE_URL"} & environment.keys()
    assert "RENDER_DATABASE_URL" in original


def test_shared_seed_produces_a_stable_key_and_exact_hosts():
    source = render_environment()
    environment, _, _ = prepare_environment(source)
    assert environment["AUTH_SECRET"] == hashlib.sha256(source["RENDER_AUTH_SEED"].encode()).hexdigest()
    assert len(environment["AUTH_SECRET"]) == 64
    assert set(environment["ALLOWED_HOSTS"].split(",")) == {"localhost", "127.0.0.1", "metro-api.test", "metro-frontend.test"}
    assert environment["APP_ENV"] == "production"
    assert environment["SECURE_COOKIES"] == "true"


@pytest.mark.parametrize("key,value", [
    ("RENDER_DATABASE_URL", "sqlite:///local.db"),
    ("RENDER_DATABASE_URL", "postgresql://metro_app:fixture@db/metro"),
    ("RENDER_AUTH_SEED", ""),
    ("RENDER_APP_PASSWORD", "short"),
    ("CORS_ORIGINS", ""),
    ("CORS_ORIGINS", "http://metro-frontend.test"),
    ("CORS_ORIGINS", "https://metro-frontend.test/account"),
])
def test_missing_or_invalid_cloud_configuration_is_rejected(key, value):
    source = render_environment()
    source[key] = value
    with pytest.raises(ValueError):
        prepare_environment(source)
