"""GPS-checked community service observations, separate from identified trains.

An unassigned phone location never creates a train or moves a trip. Independent
reports can establish a short-lived, explicitly community-reported station delay.
Identified train sightings still use the existing trip acquisition pipeline.
"""
import hashlib
import json
from datetime import timedelta, timezone
from collections import deque
from statistics import median
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import iso, parse
from .models import ContributionAward, Observation, User
from .config import settings
from .network import CONFIG, LINE_MAP, STATION_MAP, distance_metres


class SurfaceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event_id: str = Field(pattern=r"^[A-Za-z0-9_:.-]{8,100}$")
    station_id: str = Field(max_length=60)
    line_id: str = Field(max_length=30)
    direction: Literal["inbound", "outbound"]
    observed_at: AwareDatetime
    event_type: Literal["delayed", "arrived", "departed", "crowded"] = "delayed"
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100)
    cell_fingerprints: list[str] = Field(default_factory=list, max_length=16)
    delay_seconds: int = Field(ge=0, le=3600)
    note: str = Field(default="", max_length=500)


def same_report(existing, payload, fingerprint):
    if existing.fingerprint == fingerprint:
        return True
    # Old queued reports omitted fields introduced by the software-only schema.
    # Normalizing only those defaults preserves their event-ID idempotency.
    previous = {**existing.payload}
    previous.setdefault("event_type", "delayed")
    previous.setdefault("cell_fingerprints", [])
    return previous == payload


def store_report(session, raw, user_id, now):
    try:
        report = SurfaceReport.model_validate(raw)
    except ValidationError:
        return {"event_id": raw.get("event_id"), "status": "rejected", "reason": "invalid_surface_report"}
    payload = report.model_dump(mode="json")
    payload.update(observed_at=iso(report.observed_at.astimezone(timezone.utc)), contributor_id=user_id,network_version=CONFIG["version"] if CONFIG else None)
    fingerprint = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    existing = session.get(Observation,report.event_id)
    if existing:
        return {"event_id":report.event_id,"status":"duplicate" if same_report(existing,payload,fingerprint) else "conflict"}
    row = Observation(event_id=report.event_id,source="surface_crowd",trip_id=None,observed_at=payload["observed_at"],
                      received_at=iso(now),payload=payload,fingerprint=fingerprint,status="queued",available_at=iso(now))
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        existing=session.get(Observation,report.event_id)
        if existing is None:
            raise
        return {"event_id":report.event_id,"status":"duplicate" if same_report(existing,payload,fingerprint) else "conflict"}
    return {"event_id":report.event_id,"status":"queued"}


def validate_report(session,row,now):
    p=row.payload
    user=session.get(User,p["contributor_id"])
    station=STATION_MAP.get(p["station_id"])
    line=LINE_MAP.get(p["line_id"])
    reason=None
    if not user or user.disabled:
        reason="inactive_contributor"
    elif not station or not line or station["id"] not in line["station_ids"]:
        reason="station_line_mismatch"
    else:
        gps = all(p.get(k) is not None for k in ("latitude", "longitude", "accuracy_m"))
        if gps:
            if distance_metres(station["lat"],station["lng"],p["latitude"],p["longitude"]) > 250:
                reason="outside_station_proximity"
        elif p.get("cell_fingerprints"):
            from .phone_context import match_cells
            match = match_cells(p["cell_fingerprints"], line["station_ids"])
            if match["station_id"] != station["id"] or match.get("accuracy_m", 251) > 100:
                reason="unverified_cell_location"
        else:
            reason="location_evidence_required"
    age=(now-parse(row.observed_at)).total_seconds()
    if age < -5:
        reason="future_timestamp"
    if reason:
        row.status,row.reason="rejected",reason
    elif age >= settings.service_report_max_age_seconds:
        row.status,row.reason="historical","stale_surface_report"
    else:
        row.status,row.reason="validated","awaiting_independent_agreement"
    row.validated_at=iso(now)


def signals(session,now,*,include_event_ids=False):
    # Newest evidence per account; repeated delivery never adds confirmations.
    rows=session.scalars(select(Observation).where(Observation.source=="surface_crowd",Observation.status=="validated",
                    Observation.observed_at>iso(now-timedelta(seconds=settings.service_report_max_age_seconds)),Observation.observed_at<=iso(now+timedelta(seconds=5)))
                    .order_by(Observation.observed_at.desc()).limit(1000)).all()
    contributors={row.payload["contributor_id"] for row in rows}
    users=set(session.scalars(select(User.id).where(User.id.in_(contributors),User.disabled.is_(False)))) if rows else set()
    groups={}
    for row in rows:
        p=row.payload
        line=LINE_MAP.get(p["line_id"])
        station=STATION_MAP.get(p["station_id"])
        if p["contributor_id"] not in users or not line or not station or p.get("network_version")!=(CONFIG["version"] if CONFIG else None):
            continue
        # Direction belongs to the ordered line path, not a colour family.
        key=(p["station_id"],line["id"],p["direction"],p.get("event_type", "delayed"))
        groups.setdefault(key,{}).setdefault(p["contributor_id"],row)
    result=[]
    for (station,line_id,direction,event_type),contributions in groups.items():
        rows=list(contributions.values())
        # The entire group must fit the limits: a middle report must not bridge
        # two otherwise conflicting reports 90 seconds or 120 delay-seconds apart.
        stamped=sorted(((parse(row.observed_at).timestamp(),row) for row in rows),key=lambda item:item[0])
        cluster=[]
        best_key=(0,"")
        for start,(timestamp,_) in enumerate(stamped):
            window=[]
            for stamp,row in stamped[start:]:
                if stamp-timestamp>settings.service_consensus_window_seconds:break
                window.append(row)
            window.sort(key=lambda row:row.payload["delay_seconds"])
            left=0
            latest=deque()
            for right,row in enumerate(window):
                while row.payload["delay_seconds"]-window[left].payload["delay_seconds"]>60:left+=1
                while latest and latest[0]<left:latest.popleft()
                while latest and window[latest[-1]].observed_at<=row.observed_at:latest.pop()
                latest.append(right)
                key=(right-left+1,window[latest[0]].observed_at)
                if key>best_key:
                    cluster=window[left:right+1]
                    best_key=key
        accepted=len(cluster)>=settings.service_consensus_users
        stamp=max(r.observed_at for r in cluster)
        age=max(0,(now-parse(stamp)).total_seconds())
        result.append({"station_id":station,"line_id":line_id,"family_id":LINE_MAP[line_id].get("family_id") or line_id,"direction":direction,
                       "source":"crowd" if accepted else "unconfirmed","status":"confirmed" if accepted else "awaiting_agreement",
                       "event_type":event_type,"confirmations":len(cluster),"required_confirmations":settings.service_consensus_users,"delay_seconds":round(median(r.payload["delay_seconds"] for r in cluster)) if accepted and event_type=="delayed" else None,
                       "last_observed_at":stamp,"age_seconds":round(age),"trust_score":round(.9-.25*age/settings.service_report_max_age_seconds,3) if accepted else 0,
                       "quorum_available_at":max(r.validated_at or r.received_at for r in cluster) if accepted else None,
                       "predicted_at":iso(now),
                       # A future boarding or cached snapshot cannot assume an
                       # ageing contributor remains part of this agreement.
                       "confidence_kind":"heuristic_community_agreement","context":STATION_MAP[station]["zone"],
                       "expires_at":iso(min(parse(row.observed_at) for row in cluster)+timedelta(seconds=settings.service_report_max_age_seconds))})
        if include_event_ids:
            result[-1]["event_ids"]=[row.event_id for row in cluster]
    return result


def report_history(session,user_id,now,limit=30):
    """Private worker outcomes without exposing coordinates or other accounts."""
    rows=session.scalars(select(Observation).where(Observation.source=="surface_crowd",
            Observation.payload["contributor_id"].as_string()==user_id)
            .order_by(Observation.received_at.desc(),Observation.event_id).limit(limit)).all()
    current=signals(session,now,include_event_ids=True)
    membership={event:signal for signal in current for event in signal["event_ids"]}
    result=[]
    for row in rows:
        payload=row.payload
        age=max(0,round((now-parse(row.observed_at)).total_seconds()))
        signal=membership.get(row.event_id)
        outcome=row.status
        if row.status=="validated":
            outcome="expired" if age>=settings.service_report_max_age_seconds else "confirmed" if signal and signal["status"]=="confirmed" else "awaiting_agreement" if signal else "not_in_current_agreement"
        result.append({"event_id":row.event_id,"station_id":payload["station_id"],"line_id":payload["line_id"],
                "direction":payload["direction"],"delay_seconds":payload["delay_seconds"],"observed_at":row.observed_at,
                "received_at":row.received_at,"validated_at":row.validated_at,"event_type":payload.get("event_type","delayed"),"age_seconds":age,"processing_status":row.status,"outcome":outcome,
                "live_ttl_seconds":settings.service_report_max_age_seconds,
                "reason":row.reason,"confirmations":signal["confirmations"] if signal else 0,"required_confirmations":settings.service_consensus_users})
    return result


def award_contributions(session, now):
    """One award per accepted event; repeat reports at one place have a cooldown.

    The worker's transaction-level leader lock serializes award processing.
    Database event keys also make replay and restart idempotent.
    """
    for signal in signals(session, now, include_event_ids=True):
        if signal["status"] != "confirmed":
            continue
        for event_id in signal["event_ids"]:
            if session.get(ContributionAward, event_id):
                continue
            row=session.get(Observation, event_id)
            user_id=row.payload["contributor_id"]
            recent=session.scalar(select(ContributionAward.event_id).where(
                ContributionAward.user_id==user_id, ContributionAward.station_id==signal["station_id"],
                ContributionAward.line_id==signal["line_id"], ContributionAward.direction==signal["direction"],
                ContributionAward.awarded_at>iso(now-timedelta(minutes=5))).limit(1))
            if recent:
                continue
            session.add(ContributionAward(event_id=event_id, user_id=user_id, station_id=signal["station_id"],
                line_id=signal["line_id"], direction=signal["direction"], awarded_at=iso(now), points=10))
            session.flush()


def rewards(session, user_id):
    from sqlalchemy import func
    count, points=session.execute(select(func.count(),func.coalesce(func.sum(ContributionAward.points),0))
        .where(ContributionAward.user_id==user_id)).one()
    return {"validated_contributions":count,"points":points,
            "badges":[name for threshold,name in [(1,"First contribution"),(10,"Community helper"),(50,"Metro contributor")] if count>=threshold],
            "award_policy":"10 points for an independently confirmed report; one award per station, line and direction every five minutes. Agreement is not independent operator verification."}
