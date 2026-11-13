from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def utcnow():
    return datetime.now(timezone.utc)


def iso(value):
    return value.isoformat() if value else None


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class Base(DeclarativeBase):
    pass


if settings.database_url.startswith("sqlite:"):
    Path(settings.database_url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)

database_options = {"connect_args": {"check_same_thread": False, "timeout": 15}} if settings.database_url.startswith("sqlite:") else {
    "pool_size": 5, "max_overflow": 5, "pool_timeout": 10, "pool_recycle": 1800,
    "connect_args": {"connect_timeout": 10, "options": "-c statement_timeout=15000 -c lock_timeout=5000"},
}
engine = create_engine(settings.database_url, pool_pre_ping=True, **database_options)
if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def sqlite_settings(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")

Session = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction():
    with Session.begin() as session:
        yield session
