"""A reduced, simulated fixture. Names reference Delhi; geography and timings are demo data."""
import math
import networkx as nx

STATIONS = [
    {"id": "new-delhi", "name": "New Delhi", "area": "Paharganj", "lat": 28.643, "lng": 77.222, "x": 270, "y": 65, "zone": "underground"},
    {"id": "rajiv-chowk", "name": "Rajiv Chowk", "area": "Connaught Place", "lat": 28.633, "lng": 77.219, "x": 270, "y": 145, "zone": "underground"},
    {"id": "central-secretariat", "name": "Central Secretariat", "area": "Central Delhi", "lat": 28.615, "lng": 77.212, "x": 270, "y": 225, "zone": "transition"},
    {"id": "ina", "name": "INA", "area": "South Delhi", "lat": 28.575, "lng": 77.210, "x": 270, "y": 315, "zone": "surface"},
    {"id": "hauz-khas", "name": "Hauz Khas", "area": "South Delhi", "lat": 28.544, "lng": 77.206, "x": 270, "y": 415, "zone": "surface"},
    {"id": "mandi-house", "name": "Mandi House", "area": "Central Delhi", "lat": 28.625, "lng": 77.234, "x": 475, "y": 145, "zone": "surface"},
    {"id": "yamuna-bank", "name": "Yamuna Bank", "area": "East Delhi", "lat": 28.623, "lng": 77.267, "x": 660, "y": 145, "zone": "surface"},
    {"id": "lajpat-nagar", "name": "Lajpat Nagar", "area": "South Delhi", "lat": 28.570, "lng": 77.237, "x": 475, "y": 315, "zone": "surface"},
    {"id": "kalkaji-mandir", "name": "Kalkaji Mandir", "area": "South Delhi", "lat": 28.549, "lng": 77.259, "x": 660, "y": 415, "zone": "surface"},
]
LINES = [
    {"id": "yellow", "name": "Yellow Line", "color": "#d7a516", "station_ids": ["new-delhi", "rajiv-chowk", "central-secretariat", "ina", "hauz-khas"]},
    {"id": "blue", "name": "Blue Line", "color": "#377ee6", "station_ids": ["rajiv-chowk", "mandi-house", "yamuna-bank"]},
    {"id": "violet", "name": "Violet Line", "color": "#9160c5", "station_ids": ["central-secretariat", "mandi-house", "lajpat-nagar", "kalkaji-mandir"]},
    {"id": "pink", "name": "Pink Line", "color": "#dc70a0", "station_ids": ["ina", "lajpat-nagar"]},
    {"id": "magenta", "name": "Magenta Line", "color": "#b841b1", "station_ids": ["hauz-khas", "kalkaji-mandir"]},
]
STATION_MAP = {s["id"]: s for s in STATIONS}
LINE_MAP = {s["id"]: s for s in LINES}
SEGMENT_METRES = 1500
TRAVEL_SECONDS = 75
DWELL_SECONDS = 10
HEADWAY_SECONDS = 240
CHECKPOINT_INTERVAL = 250


def path_for(line_id, direction):
    stations = LINE_MAP[line_id]["station_ids"]
    return list(stations if direction == "outbound" else reversed(stations))


def context_at(line_id, direction, position):
    path = path_for(line_id, direction)
    index = min(len(path)-1, max(0, int(position // SEGMENT_METRES)))
    # The boundary is a configured segment, in either travel direction.
    current = STATION_MAP[path[index]]["zone"]
    if index < len(path)-1:
        following = STATION_MAP[path[index+1]]["zone"]
        if current == "transition" or following == "transition":
            return "transition"
    return current


def coords_at(line_id, direction, position):
    path = path_for(line_id, direction)
    index = min(len(path)-2, max(0, int(position // SEGMENT_METRES)))
    ratio = max(0, min(1, (position-index*SEGMENT_METRES)/SEGMENT_METRES))
    a, b = STATION_MAP[path[index]], STATION_MAP[path[index+1]]
    return a["lat"]+(b["lat"]-a["lat"])*ratio, a["lng"]+(b["lng"]-a["lng"])*ratio


def distance_metres(lat1, lng1, lat2, lng2):
    a1, a2 = math.radians(lat1), math.radians(lat2)
    da, dl = a2-a1, math.radians(lng2-lng1)
    return 6371000*2*math.asin(min(1, math.sqrt(math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2)))


def checkpoint(line_id, direction, index):
    position = index*CHECKPOINT_INTERVAL
    if line_id not in LINE_MAP or direction not in {"inbound", "outbound"} or index < 0 or position > (len(LINE_MAP[line_id]["station_ids"])-1)*SEGMENT_METRES:
        return None
    return {"id": f"{line_id}-{direction}-{index}", "node_id": f"node-{line_id}-{direction}-{index}", "position_m": position}


def network_payload():
    stations = [{**s, "line_ids": [line["id"] for line in LINES if s["id"] in line["station_ids"]]} for s in STATIONS]
    return {"simulated": True, "fixture": "Reduced Delhi-style demonstration; not an official metro feed",
            "stations": stations, "lines": LINES,
            "schedule": {"segment_seconds": TRAVEL_SECONDS, "dwell_seconds": DWELL_SECONDS, "headway_seconds": HEADWAY_SECONDS}}


def graph():
    result = nx.DiGraph()
    for line in LINES:
        stations = line["station_ids"]
        for a, b in zip(stations, stations[1:]):
            result.add_edge((a, line["id"]), (b, line["id"]), kind="ride", seconds=TRAVEL_SECONDS, line_id=line["id"])
            result.add_edge((b, line["id"]), (a, line["id"]), kind="ride", seconds=TRAVEL_SECONDS, line_id=line["id"])
    for station in STATIONS:
        serving = [line["id"] for line in LINES if station["id"] in line["station_ids"]]
        for a in serving:
            for b in serving:
                if a != b:
                    result.add_edge((station["id"], a), (station["id"], b), kind="transfer", seconds=90, line_id=b)
    return result
