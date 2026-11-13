"""Dated operator imports and genuine location projection, using an isolated test topology."""
from datetime import timedelta, timezone
import copy
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from backend.app import engines, main, network, operations, prediction, routing
from backend.app.config import settings
from backend.app.db import iso, utcnow
from backend.app.models import Observation, User
from backend.app.provider_contracts import NetworkImport, TimetableImport
from test_security import register


@pytest.fixture
def approved_network(monkeypatch):
    value = {"provider": "Isolated operator test", "source_url": "https://operator.example/test-data", "version": "test-network-v1",
             "published_at": iso(utcnow()), "transfer_seconds": 120,
             "stations": [{"id": "station-a", "name": "Station A", "lat": 28.600, "lng": 77.200, "x": 100, "y": 100, "zone": "surface"},
                          {"id": "station-b", "name": "Station B", "lat": 28.610, "lng": 77.200, "x": 400, "y": 100, "zone": "surface"}],
             "lines": [{"id": "dmrc-path", "operator_id": "dmrc", "name": "Operator test path", "color": "#008888",
                        "station_ids": ["station-a", "station-b"], "dwell_seconds": 10,
                        "segments": [{"metres": 1112, "seconds": 100, "zone": "surface", "geometry": [{"lat":28.600,"lng":77.200},{"lat":28.610,"lng":77.200}]}]}],
             "checkpoints": [{"id": "physical-checkpoint", "node_id": "physical-node", "line_id": "dmrc-path", "direction": "outbound", "position_m": 0}]}
    value = NetworkImport.model_validate(value).model_dump(mode="json")
    for module in [network, operations, engines, main, prediction, routing]:
        for name, data in {"CONFIG": value, "LINE_MAP": {line["id"]:line for line in value["lines"]},
                           "STATION_MAP": {station["id"]:station for station in value["stations"]},
                           "LINES":value["lines"], "STATIONS":value["stations"]}.items():
            if hasattr(module, name): monkeypatch.setattr(module, name, data)
    monkeypatch.setattr(settings, "app_env", "local")
    return value


def timetable(now):
    return {"network_version": "test-network-v1", "trips": [{"id": "actual-operator-trip", "code": "DM-123", "line_id": "dmrc-path", "direction": "outbound",
            "stops": [{"station_id":"station-a", "arrival_at":iso(now), "departure_at":iso(now+timedelta(seconds=10)), "platform":"A"},
                      {"station_id":"station-b", "arrival_at":iso(now+timedelta(seconds=110)), "departure_at":iso(now+timedelta(seconds=120)), "platform":"B"}]}]}


def test_real_timetable_import_drives_exact_schedule_and_routes(session, approved_network):
    now = utcnow()
    body = TimetableImport.model_validate(timetable(now))
    assert operations.import_timetable(session, body, now)["imported"] == 1
    session.flush()
    trip = operations.active_trips(session, now)[0]
    arrival = prediction.arrivals_for(trip, now)[1]
    assert arrival["arrival_at"] == iso(now+timedelta(seconds=110))
    assert arrival["platform"] == "B" and not arrival["simulated"]
    result = routing.routes(session, "station-a", "station-b", now, now)
    assert result["routes"][0]["duration_seconds"] == 110
    assert result["routes"][0]["steps"][0]["wait_seconds"] == 10


def test_no_timetable_never_manufactures_service(session, approved_network):
    assert not operations.active_trips(session, utcnow())
    assert routing.routes(session, "station-a", "station-b", utcnow(), utcnow())["reason"] == "no_valid_route"


def test_cancelled_trip_disappears(session, approved_network):
    now = utcnow(); data = timetable(now)
    operations.import_timetable(session, TimetableImport.model_validate(data), now); session.flush()
    data["trips"][0]["cancelled"] = True
    operations.import_timetable(session, TimetableImport.model_validate(data), now); session.flush()
    assert not operations.active_trips(session, now)


def test_network_version_mismatch_rejected_atomically(session, approved_network):
    data = timetable(utcnow()); data["network_version"] = "another-network"
    with pytest.raises(HTTPException) as error:
        operations.import_timetable(session, TimetableImport.model_validate(data), utcnow())
    assert error.value.status_code == 409
    assert not operations.active_trips(session, utcnow())


def test_trip_identity_cannot_be_reassigned(session, approved_network):
    now = utcnow(); data = timetable(now)
    operations.import_timetable(session, TimetableImport.model_validate(data), now); session.flush()
    changed = timetable(now+timedelta(minutes=1))
    with pytest.raises(HTTPException) as error:
        operations.import_timetable(session, TimetableImport.model_validate(changed), now)
    assert error.value.status_code == 409


def test_wrong_order_and_unreferenced_topology_rejected(approved_network):
    data = timetable(utcnow()); data["trips"][0]["stops"][1]["arrival_at"] = data["trips"][0]["stops"][0]["arrival_at"]
    with pytest.raises(ValidationError): TimetableImport.model_validate(data)
    config = copy.deepcopy(approved_network); config["lines"][0]["station_ids"] = ["station-a", "invented-station"]
    with pytest.raises(ValidationError): NetworkImport.model_validate(config)


def test_gps_projection_and_configured_checkpoint(approved_network):
    distance, along = network.project_position("dmrc-path", "outbound", 28.605, 77.200)
    assert distance < 1 and abs(along-556) < 1
    distance, along = network.project_position("dmrc-path", "inbound", 28.6025, 77.200)
    assert abs(along-834) < 1
    assert network.lookup_checkpoint("dmrc-path", "outbound", "physical-checkpoint")["node_id"] == "physical-node"
    assert network.lookup_checkpoint("dmrc-path", "inbound", "physical-checkpoint") is None


def test_report_identity_and_distance_come_from_server(session, approved_network):
    now = utcnow()
    operations.import_timetable(session, TimetableImport.model_validate(timetable(now)), now); session.commit()
    with TestClient(main.app) as client:
        result, headers = register(client)
        report = {"event_id": str(uuid.uuid4()), "trip_id": "actual-operator-trip", "direction": "outbound", "observed_at": iso(now),
                  "latitude": 28.605, "longitude":77.200, "accuracy_m": 10, "position_m": 999999, "kind":"sighting"}
        response = client.post("/api/v1/crowd-reports/batch", headers=headers, json={"reports":[report]})
        assert response.status_code == 202
        row = session.get(Observation, report["event_id"])
        assert row.payload["contributor_id"] == result["user"]["id"]
        assert abs(row.payload["position_m"]-556) < 1
        engines.process_observation(session, row, now)
        assert row.reason == "contributor_verification_required"


def test_imprecise_or_spoofed_location_is_rejected(session, approved_network):
    now=utcnow();operations.import_timetable(session,TimetableImport.model_validate(timetable(now)),now);session.commit()
    with TestClient(main.app) as client:
        result, headers = register(client)
        report={"event_id":str(uuid.uuid4()),"trip_id":"actual-operator-trip","direction":"outbound","observed_at":iso(now),"latitude":28.605,"longitude":77.200,"accuracy_m":250,"kind":"sighting"}
        response=client.post("/api/v1/crowd-reports/batch",headers=headers,json={"reports":[report]})
        assert response.json()["acknowledgements"][0]["status"] == "rejected"
        report.update(event_id=str(uuid.uuid4()), accuracy_m=10, contributor_id="someone-else")
        response=client.post("/api/v1/crowd-reports/batch",headers=headers,json={"reports":[report]})
        assert response.json()["acknowledgements"][0]["status"] == "rejected"


def test_timezone_offsets_normalize_to_one_trip_identity(session, approved_network):
    now = utcnow(); data = timetable(now)
    operations.import_timetable(session, TimetableImport.model_validate(data), now); session.flush()
    for stop in data["trips"][0]["stops"]:
        for key in ["arrival_at", "departure_at"]:
            from backend.app.db import parse
            stop[key] = parse(stop[key]).astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
    operations.import_timetable(session, TimetableImport.model_validate(data), now); session.flush()
    trip = operations.active_trips(session, now)[0]
    assert trip.scheduled_start == iso(now)
    assert trip.service_end == iso(now+timedelta(seconds=120))


def test_snapshot_calculation_is_shared_across_stations(session, approved_network, monkeypatch):
    from unittest.mock import patch
    now = utcnow()
    operations.import_timetable(session, TimetableImport.model_validate(timetable(now)), now);session.commit()
    monkeypatch.setattr(main, "snapshot_cache", None)
    with patch("backend.app.main.active_trips", wraps=operations.active_trips) as calculation:
        assert main.eta_snapshot("station-a")["arrivals"]
        assert main.eta_snapshot("station-b")["arrivals"]
        assert calculation.call_count == 1


def test_external_walk_connects_operators_without_invented_service(session, approved_network):
    config = approved_network
    config["stations"] += [{"id":"station-c","name":"Station C","lat":28.611,"lng":77.200,"x":430,"y":100,"zone":"surface"},
                           {"id":"station-d","name":"Station D","lat":28.621,"lng":77.200,"x":700,"y":100,"zone":"surface"}]
    config["lines"].append({"id":"nmrc-path","operator_id":"nmrc","name":"NMRC test path","color":"#00AAAA","station_ids":["station-c","station-d"],"dwell_seconds":10,
                            "segments":[{"metres":1112,"seconds":90,"zone":"surface","geometry":[{"lat":28.611,"lng":77.200},{"lat":28.621,"lng":77.200}]}]})
    config["transfers"]=[{"from_station_id":"station-b","to_station_id":"station-c","seconds":60,"requires_exit":True}]
    for module in [network, operations, engines, main, prediction, routing]:
        if hasattr(module,"STATION_MAP"): module.STATION_MAP.update({s["id"]:s for s in config["stations"]})
        if hasattr(module,"LINE_MAP"): module.LINE_MAP.update({line["id"]:line for line in config["lines"]})
    now=utcnow(); data=timetable(now)
    data["trips"].append({"id":"noida-operator-trip","code":"NM-11","line_id":"nmrc-path","direction":"outbound","stops":[
        {"station_id":"station-c","arrival_at":iso(now+timedelta(seconds=180)),"departure_at":iso(now+timedelta(seconds=190))},
        {"station_id":"station-d","arrival_at":iso(now+timedelta(seconds=280)),"departure_at":iso(now+timedelta(seconds=290))}]})
    operations.import_timetable(session,TimetableImport.model_validate(data),now);session.flush()
    result=routing.routes(session,"station-a","station-d",now,now)
    option=result["routes"][0]
    assert option["duration_seconds"]==280 and option["transfers"]==1
    assert option["steps"][1]["requires_exit"] and option["steps"][1]["seconds"]==60


def test_snapshot_does_not_cross_evidence_expiry(session, approved_network, monkeypatch):
    from unittest.mock import patch
    now = utcnow()
    operations.import_timetable(session, TimetableImport.model_validate(timetable(now)), now);session.flush()
    trip = operations.active_trips(session, now)[0]
    trip.state = {**trip.state, "source":"wsn", "trust":.9, "last_observed_at":iso(now-timedelta(seconds=29)), "freshness":"live"}
    session.commit()
    monkeypatch.setattr(main, "snapshot_cache", None)
    with patch("backend.app.main.utcnow", return_value=now):
        assert main.eta_snapshot("station-b")["arrivals"][0]["source"] == "wsn"
    with patch("backend.app.main.utcnow", return_value=now+timedelta(seconds=1)):
        assert main.eta_snapshot("station-b")["arrivals"][0]["source"] == "schedule"
