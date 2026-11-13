"""Software reporting outcomes, privacy and agreement boundaries."""
from datetime import timedelta, timezone
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import main, surface_reports
from backend.app.config import settings
from backend.app.models import Observation
from backend.app.db import iso
from conftest import NOW
from test_journey_catalogue import catalogue, add_account, ingest_and_check, report_at
from test_security import register, BODY


def test_surface_timestamps_are_normalized_before_deduplication(session,catalogue):
    user=add_account(session,1)
    body=report_at(observed=NOW.astimezone(timezone(timedelta(hours=5,minutes=30))))
    assert ingest_and_check(session,user,body)["status"]=="queued"
    row=session.get(Observation,body["event_id"])
    assert row.observed_at==iso(NOW)
    body["observed_at"]=iso(NOW)
    assert ingest_and_check(session,user,body)["status"]=="duplicate"


def test_collection_window_cannot_revive_expired_reports(session,catalogue):
    for index,seconds in enumerate([0,20,40]):
        stamp=NOW+timedelta(seconds=seconds)
        ingest_and_check(session,add_account(session,index),report_at(event=f"time-boundary-{index}",observed=stamp),stamp)
    signal=surface_reports.signals(session,NOW+timedelta(seconds=40))[0]
    assert signal["confirmations"]==2 and signal["status"]=="awaiting_agreement"


def test_middle_delay_cannot_bridge_conflicting_delay_values(session,catalogue):
    for index,delay in enumerate([0,60,120]):
        ingest_and_check(session,add_account(session,index),report_at(event=f"delay-boundary-{index}",delay=delay))
    assert surface_reports.signals(session,NOW)[0]["confirmations"]==2


def test_exact_time_and_delay_boundaries_are_accepted(session,catalogue):
    for index,(seconds,delay) in enumerate([(0,300),(10,330),(20,360)]):
        stamp=NOW+timedelta(seconds=seconds)
        ingest_and_check(session,add_account(session,index),report_at(event=f"exact-boundary-{index}",observed=stamp,delay=delay),stamp)
    signal=surface_reports.signals(session,NOW+timedelta(seconds=20))[0]
    assert signal["status"]=="confirmed" and signal["delay_seconds"]==330
    assert "event_ids" not in signal


def test_agreement_expiry_uses_first_expiring_contributor(session,catalogue):
    for index,seconds in enumerate([0,10,20]):
        stamp=NOW+timedelta(seconds=seconds)
        ingest_and_check(session,add_account(session,index),report_at(event=f"expiry-member-{index}",observed=stamp),stamp)
    signal=surface_reports.signals(session,NOW+timedelta(seconds=29))[0]
    assert signal["status"]=="confirmed"
    assert signal["expires_at"]==iso(NOW+timedelta(seconds=30))
    assert surface_reports.signals(session,NOW+timedelta(seconds=30))[0]["status"]=="awaiting_agreement"


def test_future_boarding_cannot_use_partially_expired_agreement(session,catalogue):
    from backend.app.journey_planner import journey_routes
    for index,seconds in enumerate([0,10,20]):
        stamp=NOW+timedelta(seconds=seconds)
        ingest_and_check(session,add_account(session,index),report_at(event=f"boarding-expiry-{index}",observed=stamp),stamp)
    now=NOW+timedelta(seconds=29)
    current=journey_routes(session,"dmrc-sftn","dmrc-necc",now,now)["routes"][0]
    future=journey_routes(session,"dmrc-sftn","dmrc-necc",NOW+timedelta(seconds=30),now)["routes"][0]
    assert current["delay_seconds"]==300
    assert future["delay_seconds"]==0


def test_private_history_distinguishes_queued_rejected_confirmed_and_expired(session,catalogue):
    user=add_account(session,0)
    body=report_at(event="private-history-event")
    surface_reports.store_report(session,body,user.id,NOW);session.flush()
    assert surface_reports.report_history(session,user.id,NOW)[0]["outcome"]=="queued"
    surface_reports.validate_report(session,session.get(Observation,body["event_id"]),NOW);session.flush()
    assert surface_reports.report_history(session,user.id,NOW)[0]["outcome"]=="awaiting_agreement"
    for index in [1,2]:ingest_and_check(session,add_account(session,index),report_at(event=f"private-history-{index}"))
    history=surface_reports.report_history(session,user.id,NOW)
    assert len(history)==1 and history[0]["outcome"]=="confirmed"
    assert history[0]["confirmations"]==3
    assert not {"latitude","longitude","note","contributor_id","event_ids"}&set(history[0])
    assert surface_reports.report_history(session,user.id,NOW+timedelta(seconds=30))[0]["outcome"]=="expired"
    rejected=report_at(event="rejected-history-event");rejected["latitude"]+=.1
    ingest_and_check(session,user,rejected)
    assert next(row for row in surface_reports.report_history(session,user.id,NOW) if row["event_id"]==rejected["event_id"])["outcome"]=="rejected"


def test_disagreeing_account_does_not_see_confirmed_outcome(session,catalogue):
    for index,delay in enumerate([300,300,300,600]):
        ingest_and_check(session,add_account(session,index),report_at(event=f"disagree-status-{index}",delay=delay))
    assert surface_reports.report_history(session,"account-0",NOW)[0]["outcome"]=="confirmed"
    assert surface_reports.report_history(session,"account-3",NOW)[0]["outcome"]=="not_in_current_agreement"
    assert surface_reports.report_history(session,"account-3",NOW)[0]["confirmations"]==0


def test_report_history_and_event_status_are_owned_and_authenticated(session,catalogue,monkeypatch):
    # Test the real profile's ownership path, rather than the isolated legacy API bypass.
    monkeypatch.setattr(settings,"app_env","local")
    with TestClient(main.app) as first,TestClient(main.app) as second:
        assert first.get("/api/v1/surface-reports/mine").status_code==401
        user,headers=register(first)
        response=second.post('/api/v1/auth/register',json={**BODY,'username':'another_passenger'},headers={'Origin':'http://localhost:5173'})
        assert response.status_code==201
        body=report_at(event="owner-surface-event")
        with patch("backend.app.main.utcnow",return_value=NOW):
            assert first.post("/api/v1/surface-reports/batch",json={"reports":[body]},headers=headers).status_code==202
            own=first.get("/api/v1/surface-reports/mine").json()
            other=second.get("/api/v1/surface-reports/mine").json()
        assert own["reports"][0]["event_id"]==body["event_id"] and other["reports"]==[]
        assert first.get("/api/v1/events/"+body["event_id"]).status_code==200
        assert second.get("/api/v1/events/"+body["event_id"]).status_code==404
        assert "latitude" not in json.dumps(own)
        assert first.get("/api/v1/surface-reports/mine?limit_count=101").status_code==422
