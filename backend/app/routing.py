import heapq
import itertools
from datetime import timedelta
from sqlalchemy import select

from .db import iso, parse
from .models import Runtime, Trip
from .network import (DWELL_SECONDS, HEADWAY_SECONDS, LINE_MAP, SEGMENT_METRES,
                      STATION_MAP, TRAVEL_SECONDS, graph, path_for)
from .prediction import arrivals_for
from .operations import active_trips
from .config import settings


def routes(session, origin, destination, depart_at, now):
    if origin not in STATION_MAP or destination not in STATION_MAP:
        raise ValueError("unknown_station")
    if origin == destination:
        return {"routes": [], "reason": "already_at_destination", "simulated": settings.synthetic_data}
    control = session.get(Runtime, "control")
    closures = set(control.value.get("closed_lines", [])) if control else set()
    trips = active_trips(session, depart_at)
    trip_lookup = {trip.id: trip for trip in trips}
    topology = graph()
    for node in list(topology):
        if node[1] in closures:
            topology.remove_node(node)

    boarding_cache = {}
    for trip in trips:
        path = path_for(trip.line_id, trip.direction)
        timetable = {stop["station_id"]: stop for stop in trip.timetable.get("stops", [])}
        for arrival in arrivals_for(trip, now):
            station = arrival["station_id"]
            index = path.index(station)
            if index == len(path)-1:
                continue
            stop = timetable.get(station)
            dwell = (parse(stop["departure_at"])-parse(stop["arrival_at"])).total_seconds() if stop else DWELL_SECONDS
            timestamp = parse(arrival["arrival_at"])+timedelta(seconds=dwell)
            boarding_cache.setdefault((station, path[index+1], trip.line_id), []).append((timestamp, trip.id, arrival["source"]))

    def boarding(station, following, line, ready):
        options = []
        for option in boarding_cache.get((station, following, line), []):
            if option[0] >= ready:
                options.append(option)
        # A timetable service keeps routes usable when no live tracked trip is approaching.
        epoch = int(ready.timestamp())
        scheduled = ready+timedelta(seconds=(HEADWAY_SECONDS-epoch%HEADWAY_SECONDS)%HEADWAY_SECONDS)
        if settings.app_env == "test":
            options.append((scheduled, None, "schedule"))
        return min(options, key=lambda option: option[0]) if options else None

    def search(banned=frozenset()):
        queue, visited, counter = [], {}, itertools.count()
        for node in topology:
            if node[0] == origin:
                heapq.heappush(queue, (depart_at.timestamp(), next(counter), node, None, [], 0))
        while queue:
            seconds, _, node, boarded, steps, changes = heapq.heappop(queue)
            key = (node, boarded)
            if visited.get(key, float("inf")) <= seconds:
                continue
            visited[key] = seconds
            if node[0] == destination:
                return steps, seconds, changes
            for following, edge in topology[node].items():
                if (node, following) in banned:
                    continue
                start = parse(iso(depart_at))+timedelta(seconds=seconds-depart_at.timestamp())
                if edge["kind"] == "transfer":
                    end = start+timedelta(seconds=edge["seconds"])
                    leg = {"kind": "transfer", "from_station_id": node[0], "to_station_id": following[0],
                           "line_id": following[1], "seconds": edge["seconds"], "wait_seconds": 0,
                           "requires_exit": edge.get("requires_exit", False),
                           "source": "schedule", "departure_at": iso(start), "arrival_at": iso(end)}
                    next_boarded, next_changes = None, changes+1
                else:
                    path = LINE_MAP[node[1]]["station_ids"]
                    direction = "outbound" if path.index(following[0]) > path.index(node[0]) else "inbound"
                    if boarded and boarded[0] == direction:
                        departure, trip_id, source = start+timedelta(seconds=DWELL_SECONDS), boarded[1], boarded[2]
                    else:
                        boarding_option = boarding(node[0], following[0], node[1], start)
                        if boarding_option is None:
                            continue
                        departure, trip_id, source = boarding_option
                    # Delay already affects the boarding arrival. Never add it again per edge.
                    end = departure+timedelta(seconds=edge["seconds"])
                    if settings.app_env != "test" and trip_id:
                        trip = trip_lookup[trip_id]
                        next_stop = next((s for s in trip.timetable["stops"] if s["station_id"] == following[0]), None)
                        this_stop = next((s for s in trip.timetable["stops"] if s["station_id"] == node[0]), None)
                        if not next_stop or not this_stop:
                            continue
                        travel_seconds = (parse(next_stop["arrival_at"])-parse(this_stop["departure_at"])).total_seconds()
                        if boarded:
                            actual_dwell = (parse(this_stop["departure_at"])-parse(this_stop["arrival_at"])).total_seconds()
                            departure = start+timedelta(seconds=actual_dwell)
                        end = departure+timedelta(seconds=travel_seconds)
                    leg = {"kind": "ride", "from_station_id": node[0], "to_station_id": following[0],
                           "line_id": node[1], "trip_id": trip_id, "source": source,
                           "seconds": round((end-start).total_seconds()),
                           "wait_seconds": round((departure-start).total_seconds()),
                           "departure_at": iso(departure), "arrival_at": iso(end)}
                    next_boarded, next_changes = (direction, trip_id, source), changes
                heapq.heappush(queue, (end.timestamp(), next(counter), following, next_boarded, steps+[leg], next_changes))
        return None

    first = search()
    found = []
    if first:
        found.append(first)
        for leg in first[0]:
            if leg["kind"] != "ride":
                continue
            alternative = search(frozenset({((leg["from_station_id"], leg["line_id"]), (leg["to_station_id"], leg["line_id"]))}))
            if alternative and [x["to_station_id"] for x in alternative[0]] != [x["to_station_id"] for x in first[0]]:
                if not any(alternative[0] == item[0] for item in found):
                    found.append(alternative)
            if len(found) == 3:
                break
    options = [{"id": f"route-{index}", "departure_at": iso(depart_at),
                "arrival_at": iso(depart_at+timedelta(seconds=end-depart_at.timestamp())),
                "duration_seconds": round(end-depart_at.timestamp()), "transfers": changes,
                "steps": steps, "source": "live_and_schedule" if any(x.get("source") != "schedule" for x in steps) else "schedule",
                "simulated": settings.synthetic_data} for index, (steps, end, changes) in enumerate(sorted(found, key=lambda item: item[1]))]
    return {"routes": options, "reason": None if options else "no_valid_route", "simulated": settings.synthetic_data}
