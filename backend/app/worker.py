import logging
import os
import time
import signal
import threading
from datetime import timedelta
from sqlalchemy import select, delete, text

from .config import settings
from .db import iso, parse, transaction, utcnow
from .engines import evaluate, process_observation
from .models import Observation, Prediction, Runtime, Trip, AuthSession, PasswordReset, RateBucket, SecurityAudit, Decision, Evidence
from .operations import active_trips
from .prediction import arrivals_for
from .simulator import generate, seed

log = logging.getLogger(__name__)


def tick(now=None):
    now = now or utcnow()
    with transaction() as session:
        # A transaction-level lock gives a single processing leader across PostgreSQL workers.
        # Job effects and the heartbeat commit together; another worker can take over on failure.
        if session.bind.dialect.name == "postgresql" and not session.scalar(text("SELECT pg_try_advisory_xact_lock(64124501)")):
            return
        heartbeat = session.get(Runtime, "worker", with_for_update=True)
        if heartbeat is None:
            session.add(Runtime(key="worker", value={"at": iso(now), "pid": os.getpid()}))
        else:
            heartbeat.value = {"at": iso(now), "pid": os.getpid()}
        if settings.app_env == "software":
            from .software_feed import generate as software_generate
            software_generate(session, now)
        elif settings.simulation_enabled:
            seed(session, now)
            generate(session, now)
        jobs = session.scalars(select(Observation).where(Observation.status == "queued", Observation.available_at <= iso(now))
                               .order_by(Observation.received_at, Observation.event_id).limit(100)
                               .with_for_update(skip_locked=True)).all()
        for row in jobs:
            try:
                with session.begin_nested():
                    if row.source=="surface_crowd":
                        from .surface_reports import validate_report
                        validate_report(session,row,now)
                    else:
                        process_observation(session, row, now)
                    session.flush()
            except Exception as error:
                log.error("Event processing failed: %s (%s)", row.event_id, type(error).__name__)
                row.attempts += 1
                row.status = "dead_letter" if row.attempts >= 5 else "queued"
                row.reason = type(error).__name__
                row.available_at = iso(now+timedelta(seconds=min(30, 2**row.attempts)))
        from .surface_reports import award_contributions
        award_contributions(session, now)
        for trip in active_trips(session, now):
            previous = trip.version
            evaluate(session, trip, now)
            if previous != trip.version:
                for payload in arrivals_for(trip, now):
                    session.add(Prediction(trip_id=trip.id, station_id=payload["station_id"],
                                           generated_at=iso(now), payload=payload))
        housekeeping = session.get(Runtime, "housekeeping")
        if not housekeeping or (now-parse(housekeeping.value["at"])).total_seconds() >= 3600:
            cutoff = iso(now-timedelta(days=settings.retention_days))
            for model, column in ((Observation, Observation.received_at), (Prediction, Prediction.generated_at),
                                  (Decision, Decision.at), (Evidence, Evidence.observed_at), (SecurityAudit, SecurityAudit.at)):
                session.execute(delete(model).where(column < cutoff))
            session.execute(delete(AuthSession).where(AuthSession.expires_at < iso(now)))
            session.execute(delete(RateBucket).where(RateBucket.expires_at < iso(now)))
            session.execute(delete(PasswordReset).where(PasswordReset.expires_at < iso(now)))
            session.execute(delete(Trip).where(Trip.scheduled_start < cutoff))
            if housekeeping:
                housekeeping.value = {"at": iso(now)}
            else:
                session.add(Runtime(key="housekeeping", value={"at": iso(now)}))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("Processing worker started; simulation=%s", settings.simulation_enabled)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    try:
        while not stopped.is_set():
            started = time.monotonic()
            try:
                tick()
            except Exception as error:
                log.error("Worker tick failed; database transaction rolled back (%s)", type(error).__name__)
            stopped.wait(max(.1, 1-(time.monotonic()-started)))
    except KeyboardInterrupt:
        log.info("Worker stopped")


if __name__ == "__main__":
    main()
