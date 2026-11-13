"""Deterministic validation, trust, switching and bounded arbitration engines."""
from datetime import timedelta
from statistics import median
from sqlalchemy import select

from .config import settings
from .context_switching import router
from .db import iso, parse
from .models import Decision, Evidence, Observation, Trip, User, Device
from .network import (CHECKPOINT_INTERVAL, SEGMENT_METRES, STATION_MAP, checkpoint,
                      context_at, coords_at, distance_metres, path_for, lookup_checkpoint, station_positions, LINE_MAP, CONFIG)


def initial_state():
    return {"context": "underground", "source": "schedule", "trust": 0.0,
            "position_m": 0.0, "accepted_position_m": 0.0, "speed_mps": None,
            "last_observed_at": None, "last_switched_at": None, "reason": "awaiting_evidence",
            "scores": {"wsn": 0.0, "crowd": 0.0}, "freshness": "schedule_fallback",
            "candidate": None, "candidate_count": 0, "transition": None}


def reject(row, reason, historical=False):
    row.status = "historical" if historical else "rejected"
    row.reason = reason


def process_observation(session, row, now):
    payload = dict(row.payload)
    trip = session.get(Trip, row.trip_id, with_for_update=True)
    if not trip or trip.timetable.get("cancelled"):
        return reject(row, "unknown_or_unassigned_trip")
    if trip.line_id not in LINE_MAP or settings.app_env != "test" and (not CONFIG or trip.timetable.get("network_version") != CONFIG["version"]):
        return reject(row, "network_version_unavailable")
    if row.source == "crowd" and settings.app_env != "test":
        user = session.get(User, payload.get("authenticated_contributor"))
        if not user or user.disabled or not user.verified_contributor:
            return reject(row, "contributor_verification_required", historical=True)
    state = dict(trip.state)
    if payload["direction"] != trip.direction:
        return reject(row, "wrong_direction")
    observed = parse(payload["observed_at"])
    age = (now-observed).total_seconds()
    if age < -5:
        return reject(row, "future_timestamp")
    maximum_age = settings.sensor_max_age_seconds if row.source == "wsn" else settings.crowd_max_age_seconds
    if age > maximum_age:
        return reject(row, "stale_observation", historical=True)
    if state.get("last_observed_at") and observed < parse(state["last_observed_at"]):
        return reject(row, "out_of_order", historical=True)
    path = path_for(trip.line_id, trip.direction)
    if payload.get("station_id") and payload["station_id"] not in path:
        return reject(row, "station_not_on_trip")
    if row.source == "wsn":
        cp = lookup_checkpoint(trip.line_id, trip.direction, payload["checkpoint_id"])
        if cp is None or cp["id"] != payload["checkpoint_id"] or cp["node_id"] != payload["node_id"]:
            return reject(row, "checkpoint_device_mismatch")
        payload["position_m"] = cp["position_m"]
        if not payload["healthy"]:
            row.status, row.reason = "rejected", "unhealthy_sensor"
            # Retain the unhealthy latest evidence so an old healthy value cannot mask device loss.
            put_evidence(session, trip, row, payload)
            return evaluate(session, trip, now)
    else:
        maximum_position = station_positions(trip.line_id, trip.direction)[-1]
        if payload["position_m"] > maximum_position:
            return reject(row, "position_outside_trip")
        latitude, longitude = coords_at(trip.line_id, trip.direction, payload["position_m"])
        if distance_metres(latitude, longitude, payload["latitude"], payload["longitude"]) > 500:
            return reject(row, "outside_line_proximity")
    if payload.get("station_id") and payload["kind"] in {"arrival", "departure"}:
        station_position = station_positions(trip.line_id, trip.direction)[path.index(payload["station_id"])]
        if abs(station_position-payload["position_m"]) > 100:
            return reject(row, "station_position_mismatch")
    if state.get("last_observed_at"):
        gap = max(0, (observed-parse(state["last_observed_at"])).total_seconds())
        delta = payload["position_m"]-state.get("accepted_position_m", 0)
        if delta < -200 or delta > max(350, 45*gap+200):
            return reject(row, "implausible_movement")
    contributor = payload.get("contributor_id", "wsn") if row.source == "crowd" else "wsn"
    previous = session.get(Evidence, f"{trip.id}:{row.source}:{contributor}")
    if previous and observed <= parse(previous.observed_at):
        return reject(row, "superseded_observation", historical=True)
    if row.source == "wsn" and previous:
        dt = (observed-parse(previous.observed_at)).total_seconds()
        distance = payload["position_m"]-previous.payload["position_m"]
        if 0 < dt <= 120 and 0 < distance/dt <= 45 and payload["checkpoint_id"] != previous.payload.get("checkpoint_id"):
            payload["speed_mps"] = distance/dt
        else:
            payload["speed_mps"] = previous.payload.get("speed_mps")
        if payload["kind"] == "departure" and previous.payload["kind"] == "arrival" and payload.get("station_id") == previous.payload.get("station_id"):
            payload["dwell_seconds"] = max(0, dt)
    put_evidence(session, trip, row, payload)
    row.status, row.reason = "validated", "awaiting_source_selection"
    session.flush()
    evaluate(session, trip, now)


def put_evidence(session, trip, row, payload):
    contributor = payload.get("contributor_id", "wsn") if row.source == "crowd" else "wsn"
    key = f"{trip.id}:{row.source}:{contributor}"
    evidence = session.get(Evidence, key)
    if evidence is None:
        evidence = Evidence(id=key, trip_id=trip.id, source=row.source, contributor=contributor)
        session.add(evidence)
    evidence.event_id, evidence.observed_at, evidence.payload = row.event_id, payload["observed_at"], payload


def candidates_for(session, trip, state, now):
    evidence = session.scalars(select(Evidence).where(Evidence.trip_id == trip.id)).all()
    candidates, scores = {}, {"wsn": 0.0, "crowd": 0.0}
    live = [e for e in evidence if -5 <= (now-parse(e.observed_at)).total_seconds()
            and (not state.get("last_observed_at") or parse(e.observed_at) >= parse(state["last_observed_at"]))]
    if settings.app_env != "test":
        qualified = []
        for item in live:
            if item.source == "crowd":
                user = session.get(User, item.contributor)
                usable = user and not user.disabled and user.verified_contributor
            else:
                device = session.get(Device, item.payload.get("node_id"))
                usable = device and not device.disabled
            if usable:
                qualified.append(item)
        live = qualified
    sensor = next((e for e in live if e.source == "wsn"), None)
    if sensor and sensor.payload.get("healthy") and (now-parse(sensor.observed_at)).total_seconds() < settings.sensor_max_age_seconds:
        age = max(0, (now-parse(sensor.observed_at)).total_seconds())
        scores["wsn"] = router.trust.score("wsn", state["context"], age)
        candidates["wsn"] = {**sensor.payload, "observed_at": sensor.observed_at, "event_ids": [sensor.event_id]}
    reports = [e for e in live if e.source == "crowd" and (now-parse(e.observed_at)).total_seconds() < settings.crowd_max_age_seconds]
    threshold = 2 if state["context"] == "transition" else 3
    # Cluster around one matching event, not arbitrary reports across an entire train journey.
    clusters = []
    for report in reports:
        cluster = [e for e in reports if abs((parse(e.observed_at)-parse(report.observed_at)).total_seconds()) <= 45
                   and abs(e.payload["position_m"]-report.payload["position_m"]) <= 200
                   and e.payload.get("match_key") == report.payload.get("match_key")
                   and e.payload["kind"] == report.payload["kind"]]
        if len(cluster) >= threshold:
            clusters.append(cluster)
    if clusters:
        cluster = max(clusters, key=lambda items: max(item.observed_at for item in items))
        stamp = max(e.observed_at for e in cluster)
        age = max(0, (now-parse(stamp)).total_seconds())
        scores["crowd"] = router.trust.score("crowd", state["context"], age)
        newest = max(cluster, key=lambda e: e.observed_at)
        candidates["crowd"] = {**newest.payload, "position_m": median(e.payload["position_m"] for e in cluster),
                               "observed_at": stamp, "event_ids": [e.event_id for e in cluster], "independent_count": len(cluster)}
    candidates = {key: value for key, value in candidates.items() if scores[key] >= settings.min_source_trust}
    return candidates, scores


def evaluate(session, trip, now):
    before = dict(trip.state)
    state = dict(before)
    candidates, scores = candidates_for(session, trip, state, now)
    if candidates:
        latest_source=max(candidates,key=lambda key:(candidates[key]["observed_at"],key=="wsn"))
        latest=candidates[latest_source]
        if not state.get("context_observed_at") or parse(latest["observed_at"])>=parse(state["context_observed_at"]):
            state["detected_context"]=router.context.determine(trip.line_id,trip.direction,latest["position_m"])
            state["context_observed_at"]=latest["observed_at"]
        detected=state.get("detected_context",state["context"])
        for source,candidate in candidates.items():
            age=max(0,(now-parse(candidate["observed_at"])).total_seconds())
            scores[source]=router.trust.score(source,detected,age)
            candidate_zone=router.context.determine(trip.line_id,trip.direction,candidate["position_m"])
            if candidate_zone!=detected and parse(candidate["observed_at"])<parse(state["context_observed_at"]):
                scores[source]=round(scores[source]*.5,3)
        candidates={source:value for source,value in candidates.items() if scores[source]>=settings.min_source_trust}
    state["scores"] = scores
    winner, reason, preferred, candidates = router.select(state, candidates, scores, now)
    transition = state.get("transition")
    source = state["source"]
    if state["context"] == "transition" and transition and not winner:
        source = "schedule" if now >= parse(transition["deadline"]) else "estimate"
        if source == "schedule":
            state["trust"] = 0.0
    if winner:
        candidate = candidates[winner]
        if not state.get("last_observed_at") or parse(candidate["observed_at"]) >= parse(state["last_observed_at"]):
            old_context = state["context"]
            state["accepted_position_m"] = max(state.get("accepted_position_m", 0), candidate["position_m"])
            state["position_m"] = state["accepted_position_m"]
            state["last_observed_at"] = candidate["observed_at"]
            state["speed_mps"] = candidate.get("speed_mps", state.get("speed_mps"))
            if candidate["kind"] == "arrival":
                state["speed_mps"] = 0
                state["at_station"] = candidate.get("station_id")
                if state.get("transition"):
                    state["transition"] = {**state["transition"],"next_station_position_m":state["position_m"]}
            if candidate["kind"] == "departure":
                state["at_station"] = None
            state["dwell_seconds"] = candidate.get("dwell_seconds", state.get("dwell_seconds"))
            state["context"] = router.context.determine(trip.line_id, trip.direction, state["position_m"])
            source = winner
            state["trust"], state["freshness"] = scores[winner], "live"
            if old_context != "transition" and state["context"] == "transition":
                position = state["position_m"]
                positions = station_positions(trip.line_id, trip.direction)
                next_station = next((p for p in positions if p > position), positions[-1])
                state["transition"] = {"position_m": position, "speed_mps": state["speed_mps"],
                    "observed_at": candidate["observed_at"], "direction": trip.direction,
                    "trust": scores[winner], "started_at": iso(now), "deadline": iso(now+timedelta(seconds=settings.transition_seconds)),
                    "next_station_position_m": position if state.get("at_station") else next_station}
                source, reason = "estimate", "transition_snapshot_saved"
                state["freshness"] = "estimated"
            elif state["context"] != "transition":
                state["transition"] = None
            if reason == "no_qualified_evidence":
                reason = "qualified_preferred_source" if winner == preferred else "qualified_alternative"
            for event_id in candidate["event_ids"]:
                observation = session.get(Observation, event_id)
                if observation and observation.status == "validated":
                    observation.status, observation.reason = "accepted", reason
    elif not (state["context"] == "transition" and transition and now < parse(transition["deadline"])):
        source = "schedule"
        state["trust"], state["freshness"] = 0.0, "schedule_fallback"
    if before.get("source") != source:
        state["last_switched_at"] = iso(now)
    state["source"], state["reason"] = source, reason
    state["backend_mode"] = {"wsn":"wsn", "crowd":"crowd", "fused":"fused", "estimate":"arbitration", "schedule":"schedule"}[source]
    if state != before:
        trip.state, trip.version = state, trip.version+1
        if before.get("source") != source or before.get("reason") != reason:
            session.add(Decision(trip_id=trip.id, at=iso(now), context=state["context"],
                                 source=source, reason=reason, scores=dict(scores)))
    return state
