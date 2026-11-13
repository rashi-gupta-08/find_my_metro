from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass


class Observation(Base):
    __tablename__ = "observations"
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    trip_id: Mapped[str | None] = mapped_column(String(100), index=True)
    observed_at: Mapped[str | None] = mapped_column(String(40), index=True)
    received_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[str] = mapped_column(String(40), index=True)


class Trip(Base):
    __tablename__ = "trips"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    code: Mapped[str] = mapped_column(String(30))
    line_id: Mapped[str] = mapped_column(String(30), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    scheduled_start: Mapped[str] = mapped_column(String(40))
    scheduled_delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=0)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(20))
    contributor: Mapped[str] = mapped_column(String(100))
    event_id: Mapped[str] = mapped_column(String(100))
    observed_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String(100), index=True)
    at: Mapped[str] = mapped_column(String(40))
    context: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(80))
    scores: Mapped[dict] = mapped_column(JSON)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String(100), index=True)
    station_id: Mapped[str] = mapped_column(String(60), index=True)
    generated_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)


class Runtime(Base):
    __tablename__ = "runtime"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class ActualArrival(Base):
    __tablename__ = "actual_arrivals"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(100), index=True)
    station_id: Mapped[str] = mapped_column(String(60))
    arrived_at: Mapped[str] = mapped_column(String(40))
