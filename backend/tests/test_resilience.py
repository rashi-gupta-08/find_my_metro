from datetime import timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app.acquisition import ingest
from backend.app.db import Session, iso
from backend.app.engines import evaluate
from backend.app.main import app
from backend.app.models import Observation, Runtime, Trip
from backend.app.prediction import arrivals_for, effective_state
from backend.app.worker import tick
from test_pipeline import crowd, deliver, sensor, transition
from conftest import NOW


def test_failure_rolls_back_effects_and_retries_durable_event(session, trip):
    payload = sensor(trip, 1)
    ingest(session, payload, "wsn", now=NOW)
    session.commit()

    def fail_after_modifying_state(work_session, row, now):
        work_trip = work_session.get(Trip, row.trip_id)
        work_trip.state = {**work_trip.state, "position_m": 999}
        row.status = "accepted"
        work_session.flush()
        raise RuntimeError("Injected processing fault")

    with patch('backend.app.worker.process_observation', side_effect=fail_after_modifying_state):
        tick(NOW)
    with Session() as inspect:
        row = inspect.get(Observation, payload["event_id"])
        assert row.status == "queued" and row.attempts == 1
        assert inspect.get(Trip, trip.id).state["position_m"] == 0
    tick(NOW+timedelta(seconds=3))
    with Session() as inspect:
        assert inspect.get(Observation, payload["event_id"]).status == "accepted"
        assert inspect.get(Trip, trip.id).state["position_m"] == 250


def test_poison_event_stops_retrying_after_five_failures(session, trip):
    payload = sensor(trip, 1)
    ingest(session, payload, "wsn", now=NOW)
    session.commit()
    with patch('backend.app.worker.process_observation', side_effect=RuntimeError("Injected fault")):
        for i in range(5):
            tick(NOW+timedelta(seconds=i*40))
    with Session() as inspect:
        row = inspect.get(Observation, payload["event_id"])
        assert row.status == "dead_letter" and row.attempts == 5


def test_database_failure_does_not_acknowledge_ingestion(session, trip):
    session.commit()
    with TestClient(app) as client:
        with patch('backend.app.main.ingest', side_effect=OperationalError('INSERT', {}, Exception('Unavailable'))):
            response = client.post('/api/v1/sensor-events', headers={'X-API-Key': 'local-sensor-demo'}, json=sensor(trip, 1))
        assert response.status_code == 503
        assert 'temporarily unavailable' in response.json()['detail']


def test_matching_transition_events_allow_fusion(session, trip):
    entered = transition(session, trip)
    stamp = entered+timedelta(seconds=13)
    deliver(session, sensor(trip, 7, stamp, kind="arrival", match_key="observed-event"), stamp)
    for person in ["alice", "bob"]:
        report = crowd(trip, person, 1750, stamp, kind="arrival", match_key="observed-event")
        deliver(session, report, stamp)
    assert trip.state['source'] == 'fused'
    assert trip.state['reason'] == 'matching_evidence_fused'


def test_conflict_does_not_automatically_award_sensor_victory(session, trip):
    entered = transition(session, trip)
    stamp = entered+timedelta(seconds=13)
    deliver(session, sensor(trip, 7, stamp), stamp)
    later = stamp+timedelta(seconds=18)
    for person in ["alice", "bob"]:
        deliver(session, crowd(trip, person, 1900, later), later)
    assert trip.state['source'] == 'crowd'
    assert trip.state['reason'] == 'conflict_resolved_by_trust'


def test_normal_switch_requires_margin_confirmation_and_hold(session, trip):
    deliver(session, sensor(trip, 20))
    # Continued detections keep WSN healthy while the original hold expires.
    stamp = NOW+timedelta(seconds=20)
    deliver(session, sensor(trip, 20, stamp), stamp)
    for person in ["alice", "bob", "carol"]:
        deliver(session, crowd(trip, person, 5000, NOW+timedelta(seconds=42)), NOW+timedelta(seconds=42))
    assert trip.state['source'] == 'wsn'
    evaluate(session, trip, NOW+timedelta(seconds=43))
    assert trip.state['source'] == 'wsn'
    evaluate(session, trip, NOW+timedelta(seconds=44))
    assert trip.state['source'] == 'crowd'


def test_output_expires_stale_sensor_data_without_worker_tick(session, trip):
    deliver(session, sensor(trip, 1))
    assert trip.state['source'] == 'wsn'
    projected = effective_state(trip, NOW+timedelta(seconds=31))
    assert projected['source'] == 'schedule' and projected['freshness'] == 'schedule_fallback'
    assert trip.state['source'] == 'wsn'  # Reading output never changes persisted audit state.
    assert all(arrival['source'] == 'schedule' for arrival in arrivals_for(trip, NOW+timedelta(seconds=31)))


def test_output_expires_transition_deadline_without_worker_tick(session, trip):
    entered = transition(session, trip)
    projected = effective_state(trip, entered+timedelta(seconds=60))
    assert projected['source'] == 'schedule' and projected['reason'] == 'transition_deadline_fallback'
    assert trip.state['source'] == 'estimate'
