"""Acceptance checks for the supplied Evaluation-2 software-only plan."""
import json
from datetime import timedelta
from sqlalchemy import func, select
from backend.app import surface_reports, journey_planner, phone_context
from backend.app.config import settings
from backend.app.db import iso
from backend.app.models import ContributionAward, Observation
from conftest import NOW
from test_journey_catalogue import catalogue, add_account, ingest_and_check, report_at


def agree(session, station="dmrc-sftn", kind="delayed", delay=300):
    for i in range(3):
        body=report_at(station,event=f"plan-{kind}-{i}",delay=delay)
        body["event_type"]=kind
        ingest_and_check(session,add_account(session,i),body)


def test_underground_reports_need_location_and_three_independent_accounts(session,catalogue):
    agree(session,"dmrc-rck")
    signals=surface_reports.signals(session,NOW)
    assert signals[0]["context"]=="underground" and signals[0]["status"]=="confirmed"
    live=journey_planner.journey_routes(session,"dmrc-rck","dmrc-sftn",NOW,NOW)
    assert live["routes"][0]["source_statuses"][0]["preferred_source"]=="static_and_phone"
    assert live["routes"][0]["delay_seconds"]==300


def test_reports_expire_exactly_at_30_seconds_despite_120_second_collection_window(session,catalogue):
    agree(session)
    assert surface_reports.signals(session,NOW+timedelta(seconds=29.999))[0]["status"]=="confirmed"
    assert surface_reports.signals(session,NOW+timedelta(seconds=30))==[]
    result=journey_planner.journey_routes(session,"dmrc-sftn","dmrc-necc",NOW+timedelta(seconds=30),NOW+timedelta(seconds=30))
    assert all(r["delay_seconds"]==0 for r in result["routes"])
    user=add_account(session,4)
    ingest_and_check(session,user,report_at(event="stale-plan-report",observed=NOW-timedelta(seconds=31)))
    assert session.get(Observation,"stale-plan-report").status=="historical"


def test_arrival_agreement_does_not_become_a_delay_or_named_train(session,catalogue):
    agree(session,kind="arrived",delay=0)
    signal=surface_reports.signals(session,NOW)[0]
    assert signal["event_type"]=="arrived" and signal["delay_seconds"] is None
    route=journey_planner.journey_routes(session,"dmrc-sftn","dmrc-necc",NOW,NOW)["routes"][0]
    assert route["delay_seconds"]==0 and route["source"]=="schedule"


def test_rewards_are_idempotent_survive_event_retention_and_enforce_cooldown(session,catalogue):
    agree(session)
    surface_reports.award_contributions(session,NOW)
    surface_reports.award_contributions(session,NOW)
    assert session.scalar(select(func.count()).select_from(ContributionAward))==3
    assert surface_reports.rewards(session,"account-0")["points"]==10
    for i in range(3):
        ingest_and_check(session,session.get(surface_reports.User,f"account-{i}"),report_at(event=f"repeat-plan-{i}"))
    surface_reports.award_contributions(session,NOW)
    assert session.scalar(select(func.count()).select_from(ContributionAward))==3
    assert surface_reports.rewards(session,"account-0")["badges"]==["First contribution"]


def test_aqua_bundle_has_21_stations_and_no_invented_cell_map(catalogue,monkeypatch):
    monkeypatch.setattr(settings,"cell_map_file","")
    bundle=phone_context.offline_bundle()
    assert len(bundle["stations"])==21 and len(bundle["lines"])==1
    assert bundle["cell_map"]["entries"]==[] and bundle["bundle_bytes"]<8*1024*1024
    assert not bundle["dated_departures_available"]
    assert phone_context.match_cells(["a"*64])["station_id"] is None


def test_reviewed_cell_matches_require_two_fingerprints_and_route_relevance(session,catalogue,tmp_path,monkeypatch):
    mapping={"version":"test-map","reviewed_by":"Test fixture","source":"Synthetic fixture, not field mapping", "entries":[
        {"fingerprint":code*64,"station_id":"dmrc-rck","accuracy_m":80} for code in ["a","b"]]}
    path=tmp_path/"cells.json";path.write_text(json.dumps(mapping))
    monkeypatch.setattr(settings,"cell_map_file",str(path))
    assert phone_context.match_cells(["a"*64])["station_id"] is None
    assert phone_context.match_cells(["a"*64,"b"*64],["dmrc-sftn"])["station_id"] is None
    match=phone_context.match_cells(["a"*64,"b"*64],["dmrc-rck"])
    assert match["station_id"]=="dmrc-rck" and match["train_identity"] is None
    user=add_account(session,0)
    body=report_at("dmrc-rck")
    for field in ["latitude","longitude","accuracy_m"]:body.pop(field)
    body["cell_fingerprints"]=["a"*64,"b"*64]
    ingest_and_check(session,user,body)
    assert session.get(Observation,body["event_id"]).status=="validated"


def test_no_faster_alternative_is_explicit_on_a_single_corridor(session,catalogue):
    for i in range(3):
        station=surface_reports.STATION_MAP["nmrc-1"]
        body={**report_at(event=f"aqua-delay-{i}"),"station_id":station["id"],"line_id":"nmrc-aqua",
              "latitude":station["lat"],"longitude":station["lng"]}
        ingest_and_check(session,add_account(session,i),body)
    result=journey_planner.journey_routes(session,"nmrc-1","nmrc-17",NOW,NOW)
    assert result["rerouting"]["status"]=="no_faster_alternative"
    assert result["rerouting"]["suggested_route_id"] is None


def test_processing_times_are_recorded_without_public_coordinates(session,catalogue):
    agree(session)
    signal=surface_reports.signals(session,NOW)[0]
    assert signal["quorum_available_at"]==iso(NOW) and signal["predicted_at"]==iso(NOW)
    history=surface_reports.report_history(session,"account-0",NOW)[0]
    assert history["validated_at"]==iso(NOW)
    assert "latitude" not in history and "contributor_id" not in signal


def test_qualified_delay_can_suggest_a_real_alternative_with_savings(session,catalogue):
    agree(session,"dmrc-rck",delay=3600)
    result=journey_planner.journey_routes(session,"dmrc-rck","nmrc-17",NOW,NOW)
    rerouting=result["rerouting"]
    assert rerouting["status"]=="alternative_suggested"
    assert rerouting["saving_seconds"]>=120
    assert rerouting["suggested_route_id"]!=rerouting["baseline_route_id"]
    assert rerouting["suggested_route_id"] in {r["id"] for r in result["routes"]}
    assert rerouting["valid_until"]==iso(NOW+timedelta(seconds=30))


def test_old_event_shape_remains_idempotent_after_software_schema_change(session,catalogue):
    import hashlib
    user=add_account(session,0)
    body=report_at(event="pre-software-event")
    ingest_and_check(session,user,body)
    row=session.get(Observation,body["event_id"])
    original={k:v for k,v in row.payload.items() if k not in {"event_type","cell_fingerprints"}}
    row.payload=original
    row.fingerprint=hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()
    session.flush()
    assert surface_reports.store_report(session,body,user.id,NOW)["status"]=="duplicate"
    assert surface_reports.store_report(session,{**body,"delay_seconds":600},user.id,NOW)["status"]=="conflict"


def test_cache_expires_rerouting_even_when_delayed_route_is_not_returned(session,catalogue,monkeypatch):
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from backend.app import main
    calls=[]
    def route(*args):
        calls.append(True)
        return {"routes":[],"reason":"fixture","rerouting":{"valid_until":iso(NOW+timedelta(seconds=30))}}
    monkeypatch.setattr(journey_planner,"journey_routes",route)
    with TestClient(main.app) as client:
        for second in [29,30]:
            with patch("backend.app.main.utcnow",return_value=NOW+timedelta(seconds=second)):
                assert client.get("/api/v1/routes?origin=dmrc-rck&destination=nmrc-17").status_code==200
    assert len(calls)==2
