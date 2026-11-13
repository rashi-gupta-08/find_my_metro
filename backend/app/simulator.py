"""Known trajectories are used only to generate observations and separate arrival labels."""
from datetime import timedelta
from sqlalchemy import select

from .acquisition import ingest
from .db import iso, parse
from .engines import initial_state
from .models import ActualArrival, Runtime, Trip
from .network import (CHECKPOINT_INTERVAL, DWELL_SECONDS, LINES, SEGMENT_METRES,
                      TRAVEL_SECONDS, checkpoint, context_at, coords_at, path_for)


def seed(session, now):
    if session.get(Runtime, "control") is None:
        session.add(Runtime(key="control", value={"scenario": "normal", "epoch": iso(now),
                                                 "scenario_started_at": iso(now), "generation": 0, "closed_lines": []}))
    if session.get(Runtime, "simulator") is None:
        session.add(Runtime(key="simulator", value={"last_tick": None}))
    session.flush()
    ensure_trips(session, now)


def ensure_trips(session, now):
    control = session.get(Runtime, "control")
    epoch = parse(control.value["epoch"])
    active = []
    for line_index, line in enumerate(LINES):
        for direction in ["outbound", "inbound"]:
            offset = 35 if line["id"] == "yellow" and direction == "outbound" else line_index*11+5
            if control.value["scenario"] == "delay" and line["id"] == "yellow" and direction == "outbound":
                offset += 120
            journey_seconds = (len(line["station_ids"])-1)*(TRAVEL_SECONDS+DWELL_SECONDS)
            cycle_seconds = journey_seconds+60
            cycle = max(0, int(((now-epoch).total_seconds()+offset)//cycle_seconds))
            started = epoch+timedelta(seconds=cycle*cycle_seconds-offset)
            trip_id = f"{line['id']}-{direction}-g{control.value.get('trip_generation', 0):04d}-{cycle:04d}"
            trip = session.get(Trip, trip_id)
            if trip is None:
                state = initial_state()
                state["context"] = context_at(line["id"], direction, 0)
                trip = Trip(id=trip_id, code=line["id"][:2].upper()+f"-{412+line_index*100}"+('R' if direction == 'inbound' else ''),
                            line_id=line["id"], direction=direction, scheduled_start=iso(started), state=state)
                session.add(trip)
                session.flush()
            active.append(trip)
    return active


def ground_position(trip, now, control):
    elapsed = max(0, (now-parse(trip.scheduled_start)).total_seconds())
    scenario = control["scenario"] if trip.line_id == "yellow" and trip.direction == ("inbound" if control["scenario"] == "reverse-transition" else "outbound") else "normal"
    since = max(0, (now-parse(control["scenario_started_at"])).total_seconds())
    positions = {"underground": 500, "transition": 1800, "surface": 4800,
                 "sensor-loss": 800, "conflict": 5200, "timeout": 2000, "delay": 600,
                 "reverse-transition": 1800}
    if scenario != "normal":
        position = positions[scenario]
        if scenario in {"transition", "reverse-transition"}:
            position += min(since, 80)*20
        return min(position, (len(path_for(trip.line_id, trip.direction))-1)*SEGMENT_METRES), scenario
    segment = int(elapsed//(TRAVEL_SECONDS+DWELL_SECONDS))
    within = elapsed%(TRAVEL_SECONDS+DWELL_SECONDS)
    position = segment*SEGMENT_METRES+min(1, within/TRAVEL_SECONDS)*SEGMENT_METRES
    return min(position, (len(path_for(trip.line_id, trip.direction))-1)*SEGMENT_METRES), scenario


def generate(session, now):
    control = session.get(Runtime, "control")
    tracker = session.get(Runtime, "simulator")
    tick = int(now.timestamp())//3
    if tracker.value.get("last_tick") == tick:
        return
    tracker.value = {"last_tick": tick}
    for trip in ensure_trips(session, now):
        position, scenario = ground_position(trip, now, control.value)
        context = context_at(trip.line_id, trip.direction, position)
        prefix = f"sim-{trip.id}-{control.value['generation']}-{tick}"
        common = {"trip_id": trip.id, "direction": trip.direction, "observed_at": iso(now),
                  "match_key": f"{trip.id}:checkpoint:{round(position/CHECKPOINT_INTERVAL)}"}
        if context in {"underground", "transition"} or scenario == "conflict":
            index = int(position//CHECKPOINT_INTERVAL)
            cp = checkpoint(trip.line_id, trip.direction, index)
            previous = trip.state.get("last_sensor_checkpoint")
            snapshot_only = scenario in {"transition", "timeout"} and previous is not None
            if not snapshot_only and (previous != index or scenario in {"sensor-loss", "conflict", "delay", "underground"}):
                ingest(session, {**common, "event_id": prefix+"-wsn", "node_id": cp["node_id"],
                                 "checkpoint_id": cp["id"], "healthy": scenario != "sensor-loss"}, "wsn", now=now)
                trip.state = {**trip.state, "last_sensor_checkpoint": index}
        if context in {"surface", "transition"} and scenario != "timeout":
            if scenario not in {"transition", "reverse-transition"} or (now-parse(control.value["scenario_started_at"])).total_seconds() > 7:
                for contributor_index, contributor in enumerate(["alice", "bob", "carol"]):
                    crowd_position = position+contributor_index*5
                    if scenario == "conflict":
                        crowd_position = max(0, position-800)+contributor_index*5
                    crowd_position = min(crowd_position, (len(path_for(trip.line_id, trip.direction))-1)*SEGMENT_METRES)
                    lat, lng = coords_at(trip.line_id, trip.direction, crowd_position)
                    ingest(session, {**common, "event_id": prefix+"-"+contributor, "kind": "sighting",
                                     "contributor_id": contributor, "position_m": crowd_position,
                                     "latitude": lat, "longitude": lng}, "crowd", contributor=contributor, now=now)
        # Save actual arrivals only after they happen. Prediction never reads this table.
        path = path_for(trip.line_id, trip.direction)
        if scenario == "normal":
            for index, station_id in enumerate(path):
                arrived = parse(trip.scheduled_start)+timedelta(seconds=index*TRAVEL_SECONDS+max(0, index-1)*DWELL_SECONDS)
                key = f"{trip.id}:{station_id}"
                if arrived <= now and session.get(ActualArrival, key) is None:
                    session.add(ActualArrival(id=key, trip_id=trip.id, station_id=station_id, arrived_at=iso(arrived)))


def set_scenario(session, scenario, now):
    control = session.get(Runtime, "control")
    control.value = {**control.value, "scenario": scenario, "scenario_started_at": iso(now),
                     "generation": control.value["generation"]+1}
    # Each scenario is a separate simulated journey, so earlier positions cannot contaminate it.
    control.value = {**control.value, "epoch": iso(now)}
    generation = control.value["generation"]
    # Prefix the new epoch's journeys with a generation to keep all previous events auditable.
    control.value = {**control.value, "trip_generation": generation}
    return control.value


def current_trips(session, now):
    control = session.get(Runtime, "control")
    if control is None:
        return session.scalars(select(Trip)).all()
    generation = control.value.get("trip_generation", 0)
    trips = session.scalars(select(Trip).where(Trip.id.contains(f"-g{generation:04d}-"))).all()
    latest = {}
    for trip in trips:
        key = (trip.line_id, trip.direction)
        if key not in latest or trip.scheduled_start > latest[key].scheduled_start:
            latest[key] = trip
    return list(latest.values())
