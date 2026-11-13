import importlib
import json
from datetime import timedelta
from pathlib import Path
import pytest
from sqlalchemy import func, select
from backend.app.db import iso
from backend.app.models import Observation, Trip, User
from backend.app.provider_contracts import NetworkImport
from backend.app import journey_planner, surface_reports
from backend.tests.conftest import NOW


@pytest.fixture
def catalogue(monkeypatch):
    root=Path(__file__).resolve().parents[2]
    config=NetworkImport.model_validate_json((root/"data/operator-network.json").read_text(encoding="utf-8")).model_dump(mode="json")
    stations,lines=config["stations"],config["lines"]
    smap,lmap={s["id"]:s for s in stations},{l["id"]:l for l in lines}
    for name in ["network","operations","prediction","engines","main","journey_planner","surface_reports"]:
        module=importlib.import_module("backend.app."+name)
        for field,value in [("CONFIG",config),("STATIONS",stations),("LINES",lines),("STATION_MAP",smap),("LINE_MAP",lmap)]:
            if hasattr(module,field):monkeypatch.setattr(module,field,value)
    # Static planning does not require or manufacture an active dated train.
    monkeypatch.setattr(journey_planner,"active_trips",lambda session,now:[])
    return config


def test_catalogue_connected_and_operator_sourced(catalogue):
    import networkx as nx
    graph=journey_planner.planning_graph(set())
    assert nx.is_weakly_connected(graph)
    assert len(catalogue["stations"])>=265
    assert len([s for s in catalogue["stations"] if s["id"].startswith("nmrc-")])==21
    assert {segment["timing_source"] for line in catalogue["lines"] for segment in line["segments"]}=={"dmrc_indicative_journey_time","nmrc_indicative_journey_time"}
    assert {segment["zone"] for line in catalogue["lines"] for segment in line["segments"]}=={"underground","surface","transition"}
    assert not catalogue["checkpoints"]


@pytest.mark.parametrize("preference,key",[("fastest","duration_seconds"),("fewest_changes","transfers"),("least_walking","walking_metres"),("shortest_distance","distance_metres")])
def test_cross_network_route_preferences(session,catalogue,preference,key):
    result=journey_planner.journey_routes(session,"dmrc-ndi","nmrc-17",NOW,NOW,preference)
    assert 1<=len(result["routes"])<=8
    assert [r[key] for r in result["routes"]]==sorted(r[key] for r in result["routes"])
    assert session.scalar(select(func.count()).select_from(Trip))==0
    for route in result["routes"]:
        steps=route["steps"]
        assert steps[0]["from_station_id"]=="dmrc-ndi" and steps[-1]["to_station_id"]=="nmrc-17"
        assert any(s["requires_exit"] for s in steps if s["kind"]=="transfer")
        assert route["source"]=="schedule" and route["walking_estimated"]
        assert sum(s["seconds"] for s in steps)==route["duration_seconds"]
        assert all(a["to_station_id"]==b["from_station_id"] for a,b in zip(steps,steps[1:]))
    assert any(preference in r["recommendations"] for r in result["routes"])


def test_green_line_branch_does_not_skip_junction_or_add_change(session,catalogue):
    route=journey_planner.journey_routes(session,"dmrc-knr","dmrc-cipk",NOW,NOW)["routes"][0]
    assert route["transfers"]==0
    assert [step["to_station_id"] for step in route["steps"][:2]]==["dmrc-srsm","dmrc-apmn"]
    second=journey_planner.journey_routes(session,"dmrc-ilok","dmrc-cipk",NOW,NOW)["routes"][0]
    assert second["transfers"]==0 and second["steps"][0]["to_station_id"]=="dmrc-apmn"


def test_blue_line_continuation_does_not_create_a_walking_transfer(session,catalogue):
    route=journey_planner.journey_routes(session,"dmrc-vasi","dmrc-rck",NOW,NOW)["routes"][0]
    assert route["transfers"]==0 and route["walking_metres"]==0
    assert any(s["line_id"]=="dmrc-ln3" for s in route["steps"])
    assert any(s["line_id"]=="dmrc-ln4" for s in route["steps"])


def add_account(session,index):
    user=User(id=f"account-{index}",username=f"account_{index}",display_name="Passenger",password_hash="test",role="passenger",disabled=False,verified_contributor=False,created_at=iso(NOW))
    session.add(user);session.flush()
    return user


def report_at(station="dmrc-sftn",event="surface-event-1",delay=300,observed=NOW):
    s=surface_reports.STATION_MAP[station]
    return {"event_id":event,"station_id":station,"line_id":"dmrc-ln3","direction":"outbound","observed_at":iso(observed),
            "latitude":s["lat"],"longitude":s["lng"],"accuracy_m":10,"delay_seconds":delay,"note":"Extra wait"}


def ingest_and_check(session,user,body,now=NOW):
    ack=surface_reports.store_report(session,body,user.id,now)
    if ack["status"]=="queued":
        row=session.get(Observation,body["event_id"])
        surface_reports.validate_report(session,row,now)
        session.flush()
    return ack


def test_independent_gps_reports_add_delay_once_then_expire(session,catalogue):
    users=[add_account(session,i) for i in range(3)]
    base=journey_planner.journey_routes(session,"dmrc-sftn","dmrc-necc",NOW,NOW)["routes"][0]
    first=report_at()
    assert ingest_and_check(session,users[0],first)["status"]=="queued"
    assert ingest_and_check(session,users[0],first)["status"]=="duplicate"
    assert surface_reports.signals(session,NOW)[0]["confirmations"]==1
    assert surface_reports.signals(session,NOW)[0]["status"]=="awaiting_agreement"
    for i,user in enumerate(users[1:],1):ingest_and_check(session,user,report_at(event=f"surface-event-{i+1}"))
    accepted=surface_reports.signals(session,NOW)[0]
    assert accepted["status"]=="confirmed" and accepted["delay_seconds"]==300
    live=journey_planner.journey_routes(session,"dmrc-sftn","dmrc-necc",NOW,NOW)["routes"][0]
    assert live["duration_seconds"]==base["duration_seconds"]+300
    assert sum(s["delay_seconds"] for s in live["steps"])==300
    assert live["source"]=="live_and_schedule"
    assert surface_reports.signals(session,NOW+timedelta(seconds=300))==[]
    assert session.scalar(select(func.count()).select_from(Trip))==0


@pytest.mark.parametrize("variation,reason",[("off_station","outside_station_proximity"),("future","future_timestamp"),("stale","stale_surface_report"),("wrong_line","station_line_mismatch")])
def test_invalid_surface_report_cannot_change_live_state(session,catalogue,variation,reason):
    user=add_account(session,1)
    body=report_at()
    if variation=="off_station":body["latitude"]+=.02
    if variation=="underground":body=report_at("dmrc-rck")
    if variation=="future":body["observed_at"]=iso(NOW+timedelta(seconds=6))
    if variation=="stale":body["observed_at"]=iso(NOW-timedelta(seconds=300))
    if variation=="wrong_line":body["line_id"]="nmrc-aqua"
    ingest_and_check(session,user,body)
    row=session.get(Observation,body["event_id"])
    assert row.status in {"rejected","historical"} and row.reason==reason
    assert surface_reports.signals(session,NOW)==[]


def test_conflicting_or_disabled_contributors_do_not_establish_agreement(session,catalogue):
    for i,delay in enumerate([0,300,600]):ingest_and_check(session,add_account(session,i),report_at(event=f"surface-report-{i}",delay=delay))
    assert surface_reports.signals(session,NOW)[0]["status"]=="awaiting_agreement"
    user=session.get(User,"account-0");user.disabled=True;session.flush()
    assert all(s["confirmations"]<3 for s in surface_reports.signals(session,NOW))


def test_future_departure_does_not_reuse_current_delay(session,catalogue):
    for i in range(3):ingest_and_check(session,add_account(session,i),report_at(event=f"surface-report-{i}"))
    future=journey_planner.journey_routes(session,"dmrc-sftn","dmrc-necc",NOW+timedelta(hours=1),NOW)
    assert all(r["source"]=="schedule" and r["delay_seconds"]==0 for r in future["routes"])


def test_surface_endpoint_authentication_worker_processing_and_account_erasure(session,catalogue):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.worker import tick
    from unittest.mock import patch
    from test_security import register, BODY
    body=report_at()
    with TestClient(app) as client:
        assert client.post("/api/v1/surface-reports/batch",json={"reports":[body]}).status_code==401
        user,headers=register(client)
        assert client.post("/api/v1/surface-reports/batch",json={"reports":[body]},headers={"Origin":"http://localhost:5173"}).status_code==403
        with patch("backend.app.main.utcnow",return_value=NOW):
            result=client.post("/api/v1/surface-reports/batch",json={"reports":[body]},headers=headers)
        assert result.status_code==202 and result.json()["acknowledgements"][0]["status"]=="queued"
        tick(NOW)
        session.expire_all()
        assert session.get(Observation,body["event_id"]).status=="validated"
        assert surface_reports.signals(session,NOW)[0]["status"]=="awaiting_agreement"
        response=client.post("/api/v1/auth/account/delete",json={"current_password":BODY["password"]},headers=headers)
        assert response.status_code==200
        session.expire_all()
        assert session.get(Observation,body["event_id"]) is None


def test_out_of_order_surface_report_cannot_rewind_latest_account_evidence(session,catalogue):
    user=add_account(session,1)
    ingest_and_check(session,user,report_at(event="new-surface-report",delay=300))
    ingest_and_check(session,user,report_at(event="old-surface-report",delay=0,observed=NOW-timedelta(seconds=40)))
    signal=surface_reports.signals(session,NOW)[0]
    assert signal["confirmations"]==1 and signal["last_observed_at"]==iso(NOW)
