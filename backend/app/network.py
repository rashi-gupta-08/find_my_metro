"""Configured physical topology. Test fixtures are isolated from local and production apps."""
import json
import math
from pathlib import Path
import networkx as nx
from .config import settings
from .provider_contracts import NetworkImport

SEGMENT_METRES, TRAVEL_SECONDS, DWELL_SECONDS, HEADWAY_SECONDS, CHECKPOINT_INTERVAL = 1500, 75, 10, 240, 250
OPERATORS = [
    {"id": "dmrc", "name": "Delhi Metro", "website": "https://delhimetrorail.com/", "map_url": "https://delhimetrorail.com/network_map"},
    {"id": "nmrc", "name": "Noida Metro", "website": "https://www.nmrcnoida.com/", "map_url": "https://www.nmrcnoida.com/Passenger-Information/Journey-Planner-and-Fares"},
]
CONFIG = None
if settings.app_env == "test" and not settings.network_file:
    from backend.testing.network_fixture import STATIONS, LINES
elif settings.network_file:
    file = Path(settings.network_file)
    if not file.is_absolute():
        from .config import ROOT
        file = ROOT / file
    CONFIG = NetworkImport.model_validate_json(file.read_text(encoding="utf-8-sig")).model_dump(mode="json")
    STATIONS, LINES = CONFIG["stations"], CONFIG["lines"]
else:
    STATIONS, LINES = [], []
STATION_MAP = {s["id"]: s for s in STATIONS}
LINE_MAP = {line["id"]: line for line in LINES}


def path_for(line_id, direction):
    path = LINE_MAP[line_id]["station_ids"]
    return list(path if direction == "outbound" else reversed(path))


def segments_for(line_id, direction):
    segments = LINE_MAP[line_id].get("segments")
    if segments is None:
        return [{"metres": SEGMENT_METRES, "seconds": TRAVEL_SECONDS} for _ in range(len(LINE_MAP[line_id]["station_ids"])-1)]
    return list(segments if direction == "outbound" else reversed(segments))


def station_positions(line_id, direction):
    values = [0.0]
    for segment in segments_for(line_id, direction):
        values.append(values[-1]+segment["metres"])
    return values


def segment_index(line_id, direction, position):
    positions = station_positions(line_id, direction)
    return next((i for i in range(len(positions)-1) if position < positions[i+1]), len(positions)-2)


def context_at(line_id, direction, position):
    segments = segments_for(line_id, direction)
    index = segment_index(line_id, direction, position)
    if "zone" in segments[index]:
        return segments[index]["zone"]
    path = path_for(line_id, direction)
    current, following = STATION_MAP[path[index]]["zone"], STATION_MAP[path[index+1]]["zone"]
    return "transition" if "transition" in {current, following} else current


def distance_metres(lat1, lng1, lat2, lng2):
    a1, a2 = math.radians(lat1), math.radians(lat2)
    da, dl = a2-a1, math.radians(lng2-lng1)
    return 6371000*2*math.asin(min(1, math.sqrt(math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2)))


def geometry_for(line_id, direction, index):
    path = path_for(line_id, direction)
    segment = segments_for(line_id, direction)[index]
    if "geometry" in segment:
        return segment["geometry"] if direction == "outbound" else list(reversed(segment["geometry"]))
    return [STATION_MAP[path[index]], STATION_MAP[path[index+1]]]


def coords_at(line_id, direction, position):
    positions = station_positions(line_id, direction)
    index = segment_index(line_id, direction, position)
    points = geometry_for(line_id, direction, index)
    lengths = [distance_metres(a["lat"], a["lng"], b["lat"], b["lng"]) for a, b in zip(points, points[1:])]
    remaining = max(0, min(1, (position-positions[index])/(positions[index+1]-positions[index])))*sum(lengths)
    for i, length in enumerate(lengths):
        if remaining <= length or i == len(lengths)-1:
            ratio = min(1, remaining/max(length, .001))
            a, b = points[i], points[i+1]
            return a["lat"]+(b["lat"]-a["lat"])*ratio, a["lng"]+(b["lng"]-a["lng"])*ratio
        remaining -= length


def project_position(line_id, direction, latitude, longitude):
    """Project a real phone location onto the route; callers cannot invent route distance."""
    candidates = []
    positions = station_positions(line_id, direction)
    scale = math.cos(math.radians(latitude))
    for index in range(len(positions)-1):
        points = geometry_for(line_id, direction, index)
        lengths = [distance_metres(a["lat"], a["lng"], b["lat"], b["lng"]) for a, b in zip(points, points[1:])]
        elapsed, total = 0, sum(lengths)
        for (a, b), length in zip(zip(points, points[1:]), lengths):
            dx, dy = (b["lng"]-a["lng"])*scale, b["lat"]-a["lat"]
            px, py = (longitude-a["lng"])*scale, latitude-a["lat"]
            ratio = max(0, min(1, (px*dx+py*dy)/max(dx*dx+dy*dy, 1e-15)))
            lat, lng = a["lat"]+ratio*dy, a["lng"]+ratio*(b["lng"]-a["lng"])
            along = positions[index]+(elapsed+ratio*length)/max(total, .001)*(positions[index+1]-positions[index])
            candidates.append((distance_metres(latitude, longitude, lat, lng), along))
            elapsed += length
    return min(candidates)


def checkpoint(line_id, direction, index):
    identifier = f"{line_id}-{direction}-{index}"
    if CONFIG:
        return next((cp for cp in CONFIG["checkpoints"] if cp["id"] == identifier and cp["line_id"] == line_id and cp["direction"] == direction), None)
    if settings.app_env != "test" or line_id not in LINE_MAP or direction not in {"inbound", "outbound"} or index < 0 or index*CHECKPOINT_INTERVAL > station_positions(line_id, direction)[-1]:
        return None
    return {"id": identifier, "node_id": "node-"+identifier, "position_m": index*CHECKPOINT_INTERVAL}


def lookup_checkpoint(line_id, direction, identifier):
    if CONFIG:
        return next((cp for cp in CONFIG["checkpoints"] if cp["id"] == identifier and cp["line_id"] == line_id and cp["direction"] == direction), None)
    try:
        return checkpoint(line_id, direction, int(identifier.rsplit("-", 1)[1]))
    except (ValueError, IndexError):
        return None


def network_payload():
    stations = [{**s, "line_ids": [line["id"] for line in LINES if s["id"] in line["station_ids"]]} for s in STATIONS]
    return {"simulated": settings.synthetic_data, "configured": CONFIG is not None or settings.app_env == "test",
            "version": CONFIG["version"] if CONFIG else "unconfigured", "provider": CONFIG["provider"] if CONFIG else None,
            "source_url": CONFIG["source_url"] if CONFIG else None, "operators": OPERATORS,
            "stations": stations, "lines": LINES,"journey_planning":bool(CONFIG and CONFIG.get("journey_planning")),
            "published_at":CONFIG["published_at"] if CONFIG else None,"sources":CONFIG.get("sources",[]) if CONFIG else [],
            "coverage_note":CONFIG.get("coverage_note","") if CONFIG else ""}


def graph():
    result = nx.DiGraph()
    for line in LINES:
        path = line["station_ids"]
        for index, (a, b) in enumerate(zip(path, path[1:])):
            seconds = segments_for(line["id"], "outbound")[index]["seconds"]
            for start, end in [(a,b), (b,a)]:
                result.add_edge((start, line["id"]), (end, line["id"]), kind="ride", seconds=seconds, line_id=line["id"])
    for station in STATIONS:
        serving = [line["id"] for line in LINES if station["id"] in line["station_ids"]]
        for a in serving:
            for b in serving:
                if a != b:
                    result.add_edge((station["id"], a), (station["id"], b), kind="transfer", seconds=CONFIG["transfer_seconds"] if CONFIG else 90, line_id=b)
    for connection in CONFIG.get("transfers", []) if CONFIG else []:
        for start, end in [(connection["from_station_id"], connection["to_station_id"]), (connection["to_station_id"], connection["from_station_id"])]:
            for source in [line["id"] for line in LINES if start in line["station_ids"]]:
                for destination in [line["id"] for line in LINES if end in line["station_ids"]]:
                    result.add_edge((start, source), (end, destination), kind="transfer", seconds=connection["seconds"], line_id=destination, requires_exit=connection["requires_exit"])
    return result
