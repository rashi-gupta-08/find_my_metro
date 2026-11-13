from datetime import timedelta
from sqlalchemy import select
from fastapi.testclient import TestClient

from backend.app.acquisition import ingest
from backend.app.db import Session, iso, parse, utcnow
from backend.app.engines import evaluate, process_observation
from backend.app.main import app
from backend.app.models import Decision, Evidence, Observation, Runtime, Trip
from backend.app.network import checkpoint, coords_at
from backend.app.prediction import MODEL_VERSION, arrivals_for
from backend.app.routing import routes
from backend.app.simulator import seed, set_scenario, ensure_trips
from conftest import NOW


def sensor(trip, index, stamp=NOW, **extra):
    cp = checkpoint(trip.line_id, trip.direction, index)
    return {"event_id": f"sensor-event-{index}-{stamp.timestamp()}", "trip_id": trip.id,
            "observed_at": iso(stamp), "direction": trip.direction,
            "node_id": cp["node_id"], "checkpoint_id": cp["id"], **extra}


def crowd(trip, contributor, position, stamp=NOW, **extra):
    lat, lng = coords_at(trip.line_id, trip.direction, position)
    return {"event_id": f"crowd-{contributor}-{stamp.timestamp()}", "trip_id": trip.id,
            "observed_at": iso(stamp), "direction": trip.direction, "kind": "sighting",
            "contributor_id": contributor, "position_m": position, "latitude": lat, "longitude": lng, **extra}


def deliver(session, payload, now=NOW):
    source = "crowd" if "contributor_id" in payload else "wsn"
    result = ingest(session, payload, source, contributor=payload.get("contributor_id"), now=now)
    row = session.get(Observation, result["event_id"])
    if row.status == "queued":
        process_observation(session, row, now)
        session.flush()
    return row


def transition(session, trip):
    deliver(session, sensor(trip, 4), NOW)
    deliver(session, sensor(trip, 6, NOW+timedelta(seconds=25)), NOW+timedelta(seconds=25))
    return NOW+timedelta(seconds=25)


def test_duplicate_delivery_has_one_effect(session, trip):
    payload = sensor(trip, 1)
    first = deliver(session, payload)
    version = trip.version
    result = ingest(session, payload, "wsn", now=NOW)
    assert result["status"] == "duplicate"
    assert trip.version == version
    assert len(session.scalars(select(Observation)).all()) == 1
    assert first.status == "accepted"


def test_event_id_cannot_be_reused_for_different_data(session, trip):
    payload = sensor(trip, 1)
    deliver(session, payload)
    result = ingest(session, {**payload, "healthy": False}, "wsn", now=NOW)
    assert result["status"] == "conflict"


def test_one_sensor_detection_does_not_prove_speed(session, trip):
    deliver(session, sensor(trip, 1))
    assert trip.state["speed_mps"] is None


def test_speed_uses_two_known_checkpoints(session, trip):
    deliver(session, sensor(trip, 1))
    deliver(session, sensor(trip, 2, NOW+timedelta(seconds=12.5)), NOW+timedelta(seconds=12.5))
    assert trip.state["speed_mps"] == 20


def test_station_dwell_requires_matching_arrival_and_departure(session, trip):
    deliver(session, sensor(trip, 0, kind="arrival", station_id="new-delhi"))
    deliver(session, sensor(trip, 0, NOW+timedelta(seconds=15), kind="departure", station_id="new-delhi"), NOW+timedelta(seconds=15))
    assert trip.state["dwell_seconds"] == 15


def test_unknown_trip_is_audited_without_assignment(session, trip):
    row = deliver(session, {**sensor(trip, 1), "trip_id": "unknown"})
    assert row.reason == "unknown_or_unassigned_trip"
    assert trip.version == 0


def test_wrong_direction_rejected(session, trip):
    assert deliver(session, {**sensor(trip, 1), "direction": "inbound"}).reason == "wrong_direction"


def test_device_checkpoint_pair_is_validated(session, trip):
    assert deliver(session, {**sensor(trip, 1), "node_id": "invented-node"}).reason == "checkpoint_device_mismatch"


def test_late_upload_retains_original_time(session, trip):
    stamp = NOW-timedelta(minutes=6)
    row = deliver(session, crowd(trip, "alice", 250, stamp))
    assert row.status == "historical"
    assert row.observed_at == iso(stamp) and row.received_at == iso(NOW)


def test_out_of_order_cannot_move_trip_backwards(session, trip):
    deliver(session, sensor(trip, 2))
    row = deliver(session, sensor(trip, 1, NOW-timedelta(seconds=1)))
    assert row.reason == "out_of_order" and trip.state["position_m"] == 500


def test_future_timestamp_rejected(session, trip):
    assert deliver(session, sensor(trip, 1, NOW+timedelta(seconds=6))).reason == "future_timestamp"


def test_faraway_crowd_position_rejected(session, trip):
    assert deliver(session, crowd(trip, "alice", 250, latitude=0, longitude=0)).reason == "outside_line_proximity"


def test_identity_cannot_be_claimed_in_payload(session, trip):
    result = ingest(session, crowd(trip, "bob", 250), "crowd", contributor="alice", now=NOW)
    assert result["status"] == "rejected"


def test_repeated_contributor_does_not_create_consensus(session, trip):
    for i in range(3):
        stamp = NOW+timedelta(seconds=i)
        deliver(session, crowd(trip, "alice", 5000, stamp), stamp)
    assert trip.state["source"] == "schedule"
    assert len(session.scalars(select(Evidence)).all()) == 1


def test_surface_requires_three_independent_reports(session, trip):
    for person in ["alice", "bob"]:
        deliver(session, crowd(trip, person, 5000))
    assert trip.state["source"] == "schedule"
    deliver(session, crowd(trip, "carol", 5000))
    assert trip.state["source"] == "crowd" and trip.state["context"] == "surface"


def test_inconsistent_crowd_cluster_is_not_consensus(session, trip):
    for i, person in enumerate(["alice", "bob", "carol"]):
        deliver(session, crowd(trip, person, 4500+i*500))
    assert trip.state["source"] == "schedule"


def test_sensor_loss_bypasses_hold_and_falls_back(session, trip):
    deliver(session, sensor(trip, 1))
    assert trip.state["source"] == "wsn"
    deliver(session, sensor(trip, 1, NOW+timedelta(seconds=1), healthy=False), NOW+timedelta(seconds=1))
    assert trip.state["source"] == "schedule"


def test_sparse_crowd_is_not_used_after_sensor_loss(session, trip):
    deliver(session, sensor(trip, 1))
    deliver(session, crowd(trip, "alice", 250))
    evaluate(session, trip, NOW+timedelta(seconds=31))
    assert trip.state["source"] == "schedule"


def test_transition_timeout_without_incoming_events(session, trip):
    entered = transition(session, trip)
    assert trip.state["source"] == "estimate"
    stamp = trip.state["last_observed_at"]
    evaluate(session, trip, entered+timedelta(seconds=59))
    assert trip.state["source"] == "estimate" and trip.state["last_observed_at"] == stamp
    assert trip.state["position_m"] <= 3000
    evaluate(session, trip, entered+timedelta(seconds=60))
    assert trip.state["source"] == "schedule" and trip.state["reason"] == "transition_deadline_fallback"


def test_restart_preserves_original_deadline(session, trip):
    entered = transition(session, trip)
    deadline = trip.state["transition"]["deadline"]
    session.commit()
    with Session() as restarted:
        restored = restarted.get(Trip, trip.id)
        evaluate(restarted, restored, entered+timedelta(seconds=61))
        assert restored.state["transition"]["deadline"] == deadline
        assert restored.state["source"] == "schedule"


def test_transition_two_reports_can_take_over(session, trip):
    entered = transition(session, trip)
    stamp = entered+timedelta(seconds=10)
    for person in ["alice", "bob"]:
        deliver(session, crowd(trip, person, 1700, stamp), stamp)
    assert trip.state["source"] == "crowd"


def test_reverse_transition_enters_same_bounded_window(session, trip):
    trip.direction = "inbound"
    trip.state = {**trip.state, "context": "surface"}
    deliver(session, sensor(trip, 6))
    assert trip.state["context"] == "transition" and trip.state["source"] == "estimate"


def test_dead_reckoning_does_not_depart_an_unobserved_station(session, trip):
    deliver(session, sensor(trip, 6, kind="arrival", station_id="rajiv-chowk"))
    evaluate(session, trip, NOW+timedelta(seconds=20))
    assert trip.state["position_m"] == 1500 and trip.state["last_observed_at"] == iso(NOW)


def test_expired_sensor_data_is_not_live(session, trip):
    deliver(session, sensor(trip, 1))
    evaluate(session, trip, NOW+timedelta(seconds=30))
    assert trip.state["source"] == "schedule"


def test_small_score_changes_do_not_cause_switching(session, trip):
    deliver(session, sensor(trip, 1))
    for i in range(3):
        stamp = NOW+timedelta(seconds=i+1)
        for person in ["alice", "bob", "carol"]:
            deliver(session, crowd(trip, person, 250, stamp), stamp)
        assert trip.state["source"] == "wsn"
    switches = session.scalars(select(Decision).where(Decision.source == "crowd")).all()
    assert not switches


def test_schedule_model_is_deterministic_and_labelled(session, trip):
    arrival = arrivals_for(trip, NOW)[1]
    assert arrival["source"] == "schedule" and arrival["freshness_status"] == "schedule_fallback"
    assert arrival["model_version"] == MODEL_VERSION
    assert arrival["remaining_seconds"] == 75


def test_routes_include_waits_transfers_and_genuine_alternatives(session, trip):
    options = routes(session, "rajiv-chowk", "kalkaji-mandir", NOW, NOW)["routes"]
    assert len(options) >= 2
    for route in options:
        assert sum(step["seconds"] for step in route["steps"]) == route["duration_seconds"]
    signatures = [tuple((s["kind"], s["from_station_id"], s["to_station_id"], s["line_id"]) for s in route["steps"]) for route in options]
    assert len(set(signatures)) == len(signatures)


def test_unavailable_route_is_explicit(session, trip):
    session.add(Runtime(key="control", value={"closed_lines": ["yellow", "blue", "violet", "pink", "magenta"]}))
    result = routes(session, "new-delhi", "hauz-khas", NOW, NOW)
    assert result["reason"] == "no_valid_route" and not result["routes"]


def test_scenario_generations_preserve_previous_trip_identity(session, trip):
    seed(session, NOW)
    set_scenario(session, "surface", NOW+timedelta(seconds=1))
    active = ensure_trips(session, NOW+timedelta(seconds=1))
    assert all("-g0001-" in row.id for row in active)
    assert session.get(Trip, trip.id) is not None


def test_http_auth_and_durable_batch_acknowledgement(session, trip):
    session.commit()
    with TestClient(app) as client:
        assert client.post("/api/v1/sensor-events", json=sensor(trip, 1)).status_code == 401
        response = client.post("/api/v1/crowd-reports/batch", headers={"Authorization": "Bearer local-alice"}, json={"reports": [crowd(trip, "alice", 5000, stamp=utcnow())]})
        assert response.status_code == 202
        event_id = response.json()["acknowledgements"][0]["event_id"]
        assert client.get(f"/api/v1/events/{event_id}").json()["status"] == "queued"
        assert client.post("/api/v1/demo/scenario", json={"scenario": "surface"}).status_code == 401


def test_websocket_reconnect_always_receives_new_snapshot(session, trip):
    session.commit()
    with TestClient(app) as client:
        for _ in range(2):
            with client.websocket_connect("/ws/eta/rajiv-chowk") as socket:
                message = socket.receive_json()
                assert message["type"] == "snapshot" and message["schema_version"] == 1
                assert message["station_id"] == "rajiv-chowk"
