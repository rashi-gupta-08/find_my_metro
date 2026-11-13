from datetime import timedelta
from .config import settings
from .context_switching import router
from .ml_prediction import correct_remaining
from .db import iso, parse
from .network import DWELL_SECONDS, HEADWAY_SECONDS, SEGMENT_METRES, TRAVEL_SECONDS, path_for, station_positions, segment_index, segments_for, LINE_MAP

MODEL_VERSION = "deterministic-segment-baseline-v1"


def effective_state(trip, now):
    """Output freshness is enforced even when the worker is temporarily unavailable."""
    state = dict(trip.state)
    source = state["source"]
    observation = parse(state.get("last_observed_at"))
    transition = state.get("transition")
    expired = False
    if source == "estimate":
        expired = not transition or now >= parse(transition["deadline"])
        if not expired:
            estimate = router.transition.estimate(transition, now)
            state.update(position_m=estimate["position_m"], trust=estimate["trust"])
    elif source in {"wsn", "crowd", "fused"}:
        maximum_age = settings.sensor_max_age_seconds if source == "wsn" else settings.crowd_max_age_seconds
        expired = not observation or (now-observation).total_seconds() >= maximum_age
    if expired:
        state["source"], state["trust"], state["freshness"] = "schedule", 0.0, "schedule_fallback"
        state["reason"] = "transition_deadline_fallback" if source == "estimate" else "stale_evidence_fallback"
    return state


def arrivals_for(trip, now):
    state = effective_state(trip, now)
    path = path_for(trip.line_id, trip.direction)
    arrivals = []
    if settings.app_env != "test" and (not trip.timetable.get("stops") or trip.timetable.get("cancelled")):
        return arrivals
    positions = station_positions(trip.line_id, trip.direction)
    segments = segments_for(trip.line_id, trip.direction)
    dwell = LINE_MAP[trip.line_id].get("dwell_seconds", DWELL_SECONDS)
    schedule_start = parse(trip.scheduled_start)
    for index, station_id in enumerate(path):
        model_version = MODEL_VERSION
        stop = next((s for s in trip.timetable.get("stops", []) if s["station_id"] == station_id), None)
        scheduled = parse(stop["arrival_at"]) if stop else schedule_start+timedelta(seconds=index*TRAVEL_SECONDS+max(0, index-1)*DWELL_SECONDS)
        station_position = positions[index]
        if state["source"] == "schedule":
            # Known demonstration delay is not folded into the timetable fallback.
            arrival = scheduled
        else:
            if station_position < state["position_m"]-1:
                continue
            current_index = segment_index(trip.line_id, trip.direction, state["position_m"])
            travel = 0
            for segment_no in range(current_index, index):
                segment = segments[segment_no]
                remaining_distance = positions[segment_no+1]-max(positions[segment_no], state["position_m"])
                speed = state.get("speed_mps") if segment_no == current_index else None
                speed = speed or segment["metres"]/segment["seconds"]
                travel += remaining_distance/max(1, min(45, speed))
            intermediate_stops = max(0, index-current_index-1)
            arrival = now+timedelta(seconds=travel+intermediate_stops*dwell)
            if state.get("at_station") and state["at_station"] != station_id:
                arrival += timedelta(seconds=dwell)
            corrected, model_version = correct_remaining(max(0,(arrival-now).total_seconds()),state,now,index-current_index)
            arrival = now+timedelta(seconds=corrected)
        remaining = round((arrival-now).total_seconds())
        if remaining < -10:
            continue
        delay = max(0, round((arrival-scheduled).total_seconds()))
        arrivals.append({"id": f"{trip.id}:{station_id}", "trip_id": trip.id, "train_code": trip.code,
                         "station_id": station_id, "line_id": trip.line_id, "direction": trip.direction,
                         "towards": path[-1], "platform": stop.get("platform") if stop else None,
                         "arrival_at": iso(arrival), "scheduled_arrival_at": iso(scheduled),
                         "remaining_seconds": max(0, remaining), "delay_seconds": delay,
                         "source": state["source"], "context": state["context"], "trust_score": round(state["trust"], 3),
                         "confidence_kind": "heuristic_trust", "freshness_status": state["freshness"],
                         "last_observation_at": state.get("last_observed_at"), "generated_at": iso(now),
                         "model_version": model_version, "simulated": settings.synthetic_data, "version": trip.version})
    return arrivals
