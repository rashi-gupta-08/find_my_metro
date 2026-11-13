import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

TEST_DB = Path(tempfile.mkdtemp(prefix="findmymetro-tests-")) / "test.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///"+TEST_DB.as_posix())
os.environ["SIMULATION_ENABLED"] = "false"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_SECRET"] = "isolated-test-secret-do-not-use-for-app" * 2
os.environ["ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["MIGRATION_DATABASE_URL"] = ""
os.environ["NETWORK_FILE"] = ""
os.environ["CROWD_TOKENS"] = "local-alice:alice,local-bob:bob,local-carol:carol"
os.environ["SENSOR_API_KEY"] = "local-sensor-demo"
os.environ["ADMIN_API_KEY"] = "local-admin-demo"

from backend.app.db import Base, Session, engine, iso
from backend.app.models import Trip
from backend.app.engines import initial_state

NOW = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def session():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as session:
        yield session
        session.rollback()


@pytest.fixture
def trip(session):
    row = Trip(id="yellow-outbound-g0000-0000", code="YL-412", line_id="yellow", direction="outbound",
               scheduled_start=iso(NOW), state=initial_state())
    session.add(row)
    session.flush()
    return row
