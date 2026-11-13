"""The worker's selected state reaches the passenger REST/WebSocket contract."""
from datetime import timedelta
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from backend.app import journey_planner, main, surface_reports
from backend.app.config import settings
from backend.app.db import iso
from backend.app.models import Runtime
from backend.app.software_feed import change_scenario
from backend.app.worker import tick
from conftest import NOW
from test_patent_software import software_network
from test_journey_catalogue import catalogue, add_account, ingest_and_check, report_at


@pytest.fixture
def connected_software(software_network, monkeypatch):
    value = software_network
    value["journey_planning"] = True
    for module in [journey_planner,surface_reports]:
        for name,data in {"CONFIG":value,"LINE_MAP":{line["id"]:line for line in value["lines"]},
                          "STATION_MAP":{s["id"]:s for s in value["stations"]},
                          "LINES":value["lines"],"STATIONS":value["stations"]}.items():
            if hasattr(module,name):monkeypatch.setattr(module,name,data)
    return value


@pytest.mark.parametrize("scenario,second,station,source,context",[
    ("normal",0,1,"wsn","underground"),
    ("normal",26,2,"estimate","transition"),
    ("normal",40,2,"crowd","transition"),
    ("normal",65,3,"crowd","surface"),
    ("timeout",6,2,"estimate","transition"),
    ("timeout",66,2,"schedule","transition"),
    ("corroboration",7,2,"fused","transition"),
])
def test_accepted_worker_state_reaches_real_journey_results(session,connected_software,scenario,second,station,source,context):
    change_scenario(session,scenario,NOW);session.commit()
    for at in range(second+1):tick(NOW+timedelta(seconds=at))
    now=NOW+timedelta(seconds=second)
    result=journey_planner.journey_routes(session,f"dmrc-test-{station}","dmrc-test-4",now,now)
    first=result["routes"][0]
    status=first["source_statuses"][0]
    assert status["source"]==source and status["train_context"]==context
    assert status["scope"]=="identified_train"
    assert status["next_arrival"]["model_version"]==status["model_version"]
    assert status["next_arrival"]["source"]==status["source"]
    assert sum(step["delay_seconds"] for step in first["steps"])==first["delay_seconds"]
    if source=="estimate":
        assert status["freshness_status"]=="estimated"
        assert status["valid_until"]==status["transition"]["deadline"]
        assert status["age_seconds"]>0
        assert status["last_observed_at"]==status["transition"]["observed_at"]
    if scenario=="timeout" and second==66:
        assert status["reason"]=="transition_deadline_fallback"
        assert status["trust_score"]==0 and first["source"]=="schedule"


def test_future_boarding_cannot_extend_transition_estimate(session,connected_software):
    change_scenario(session,"timeout",NOW);session.commit()
    for at in range(6):tick(NOW+timedelta(seconds=at))
    now=NOW+timedelta(seconds=5)
    future=now+timedelta(seconds=61)
    result=journey_planner.journey_routes(session,"dmrc-test-2","dmrc-test-4",future,now)
    assert all(s["source"]!="estimate" for route in result["routes"] for s in route["source_statuses"])
    assert all(route["delay_seconds"]==0 for route in result["routes"])


def test_reverse_handover_publishes_underground_source_for_approaching_terminal(session,connected_software):
    change_scenario(session,"reverse-transition",NOW);session.commit()
    for second in range(41):tick(NOW+timedelta(seconds=second))
    arrivals=journey_planner.accepted_arrivals(session,NOW+timedelta(seconds=40))
    status=arrivals[("dmrc-test-0","dmrc-software","inbound")][0]
    assert status["source"]=="wsn" and status["train_context"]=="underground"
    assert status["next_arrival"]["station_id"]=="dmrc-test-0"


def test_real_catalogue_static_status_and_community_overlay_remain_distinct(session,catalogue):
    baseline=journey_planner.journey_routes(session,"dmrc-sftn","dmrc-necc",NOW,NOW)["routes"][0]
    status=baseline["source_statuses"][0]
    assert status["scope"]=="static" and status["trust_score"] is None and status["next_arrival"] is None
    for i in range(3):ingest_and_check(session,add_account(session,i),report_at(event=f"independent-status-{i}"))
    result=journey_planner.journey_routes(session,"dmrc-sftn","dmrc-necc",NOW,NOW)["routes"][0]
    status=result["source_statuses"][0]
    assert status["scope"]=="station_service" and status["train_context"] is None
    assert status["next_arrival"] is None and status["confirmations"]==3
    assert result["duration_seconds"]==baseline["duration_seconds"]+300


def test_rest_and_websocket_share_versioned_routes(session,catalogue):
    with TestClient(main.app) as client,patch("backend.app.main.utcnow",return_value=NOW):
        response=client.get("/api/v1/routes",params={"origin":"dmrc-ndi","destination":"nmrc-17"})
        assert response.status_code==200
        with client.websocket_connect("/ws/journeys?origin=dmrc-ndi&destination=nmrc-17",headers={"Origin":"http://localhost:5173"}) as socket:
            message=socket.receive_json()
            assert message.pop("type")=="journey_snapshot"
            assert message==response.json()
            assert message["routes"][0]["source_statuses"]


@pytest.mark.parametrize("query,origin",[
    ("origin=unknown&destination=nmrc-17","http://localhost:5173"),
    ("origin=dmrc-ndi&destination=dmrc-ndi","http://localhost:5173"),
    ("origin=dmrc-ndi&destination=nmrc-17&preference=invalid","http://localhost:5173"),
    ("origin=dmrc-ndi&destination=nmrc-17","https://untrusted.example"),
])
def test_journey_socket_rejects_invalid_context(session,catalogue,query,origin):
    with TestClient(main.app) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws/journeys?"+query,headers={"Origin":origin}):pass
        assert rejected.value.code==1008


def test_journey_cache_never_extends_report_expiry(session,catalogue):
    for i in range(3):ingest_and_check(session,add_account(session,i),report_at(event=f"expiring-status-{i}"))
    session.commit()
    with TestClient(main.app) as client:
        with patch("backend.app.main.utcnow",return_value=NOW+timedelta(seconds=29)):
            before=client.get("/api/v1/routes?origin=dmrc-sftn&destination=dmrc-necc").json()
        with patch("backend.app.main.utcnow",return_value=NOW+timedelta(seconds=30)):
            after=client.get("/api/v1/routes?origin=dmrc-sftn&destination=dmrc-necc").json()
    assert before["routes"][0]["source"]=="live_and_schedule"
    assert after["routes"][0]["source"]=="schedule"
    assert after["snapshot_version"]>before["snapshot_version"]


def test_journey_socket_respects_shared_connection_limit(session,catalogue,monkeypatch):
    monkeypatch.setattr(settings,"max_ws_connections",0)
    with TestClient(main.app) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws/journeys?origin=dmrc-ndi&destination=nmrc-17"):pass
        assert rejected.value.code==1013


def test_closed_line_removes_its_journey_status(session,catalogue):
    session.add(Runtime(key="control",value={"closed_lines":["nmrc-aqua"]}));session.flush()
    # Use the catalogue identity rather than assuming a colour name.
    aqua=next(line["id"] for line in catalogue["lines"] if line["operator_id"]=="nmrc")
    session.get(Runtime,"control").value={"closed_lines":[aqua]};session.flush()
    result=journey_planner.journey_routes(session,"dmrc-ndi","nmrc-17",NOW,NOW)
    assert result["routes"]==[] and result["reason"]=="no_valid_route"
