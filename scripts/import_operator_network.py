"""Build an offline journey catalogue from public operator passenger information.

The DMRC website's own public API supplies station layout, geography, adjacency
and indicative adjacent-station journey times. No private endpoint or login is
used. NMRC supplies its station list and public journey planner. The historical
OTD mirror is used only for NMRC coordinates, with that limitation recorded.
This imports topology and travel baselines, never current train departures.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import zipfile
import csv
import networkx as nx

BASE = "https://backend.delhimetrorail.com/api/v2/en/"
NMRC = "https://www.nmrcnoida.com"
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".local/research"


def fetch(url, file, json_data=True):
    if file.exists():
        data = file.read_text(encoding="utf-8")
    else:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "FindMyMetro-local/1.0", "Referer": "https://www.delhimetrorail.com/"})
                data = urllib.request.urlopen(req, timeout=20).read(2_000_000).decode("utf-8-sig")
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(data, encoding="utf-8")
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
    return json.loads(data) if json_data else data


def metres(a, b):
    return math.hypot((a["lat"]-b["lat"])*111195, (a["lng"]-b["lng"])*111195*math.cos(math.radians(a["lat"])))


def build():
    CACHE.mkdir(parents=True, exist_ok=True)
    definitions = fetch(BASE+"line_list", CACHE/"en_line_list.json")
    definitions = [line for line in definitions if line["show_in_frontend"] and line["line_code"] != "LN11"]
    listed = {line["line_code"]: fetch(BASE+"station_by_line/"+line["line_code"], CACHE/(line["line_code"]+".json")) for line in definitions}
    codes = {s["station_code"] for group in listed.values() for s in group if s["status"] == "Station Open"}
    def station(code):
        return code, fetch(BASE+"station/"+code, CACHE/"stations"/(code+".json"))
    details = dict(ThreadPoolExecutor(3).map(station, sorted(codes)))
    stations = []
    for code, row in details.items():
        if not row.get("latitude") or not row.get("longitude"):
            raise ValueError("Operator station has no coordinates: "+code)
        stations.append({"id": "dmrc-"+code.lower(), "name": row["station_name"].title(), "area": "Delhi Metro",
                         "lat": float(row["latitude"]), "lng": float(row["longitude"]), "x": 0, "y": 0,
                         "zone": "underground" if row["station_type"] == "Underground" else "surface"})
    paths = []
    for line in definitions:
        graph = nx.Graph()
        for item in listed[line["line_code"]]:
            code = item["station_code"]
            if code not in codes:
                continue
            for entry in details[code]["prev_next_stations"]:
                for rows in entry.values():
                    for row in rows:
                        if row["line_id"] != line["id"]:
                            continue
                        for field in ["prev_station", "next_station"]:
                            other = row[field]
                            if isinstance(other, dict) and other["station_code"] in codes:
                                graph.add_edge(code, other["station_code"])
        ends = sorted(n for n in graph if graph.degree(n) == 1)
        # Each branch is represented as an ordered physical path. The journey
        # router collapses paths in the same line family, avoiding fake changes.
        if line["line_code"] == "LN5":
            # The public station-detail API omits this branch junction; the
            # operator map and the adjacent journey response confirm it.
            graph.add_edge("SRSM", "APMN")
            chosen = [nx.shortest_path(graph, "CIPK", "KNR"), nx.shortest_path(graph, "APMN", "ILOK")]
        elif len(ends) == 2 and nx.is_connected(graph) and max(dict(graph.degree()).values()) <= 2:
            chosen = [nx.shortest_path(graph, ends[0], ends[1])]
        else:
            raise ValueError(f"Review non-linear operator topology {line['line_code']}: {ends}")
        for index, path in enumerate(chosen):
            paths.append((line, path, index))
    timings = CACHE / "timings"
    timings.mkdir(exist_ok=True)
    pairs = sorted({tuple(sorted((a,b))) for _, path, _ in paths for a,b in zip(path,path[1:])})
    def timing(pair):
        a,b = pair
        # Fixed reference time makes updates reproducible; only path_time is
        # retained, never the API's next-train or inferred departure timestamp.
        url = BASE+f"station_route/{a}/{b}/least-distance/2026-10-08T12:00:00.000"
        row = fetch(url, timings/(a+"-"+b+".json"))
        legs = row.get("route", [])
        matching = [leg for leg in legs if leg.get("map-path") in [[a+"-"+b],[b+"-"+a]]]
        if len(legs) != 1 or len(matching) != 1:
            raise ValueError(f"Operator route does not confirm the adjacent edge {a}-{b}")
        h,m,s = map(int, matching[0]["path_time"].split(":"))
        seconds = h*3600+m*60+s
        if not 0 < seconds <= 3600:
            raise ValueError("Invalid operator travel time")
        return pair, seconds
    print(f"Reading {len(details)} stations and {len(pairs)} travel-time baselines", flush=True)
    seconds = dict(ThreadPoolExecutor(3).map(timing, pairs))
    smap = {s["id"]:s for s in stations}
    lines = []
    for line,path,index in paths:
        identifier = "dmrc-"+line["line_code"].lower()+(f"-branch-{index}" if index else "")
        ids = ["dmrc-"+c.lower() for c in path]
        segments = []
        for a,b in zip(path,path[1:]):
            first,last = smap["dmrc-"+a.lower()],smap["dmrc-"+b.lower()]
            segments.append({"metres": max(1,round(metres(first,last))), "seconds": seconds[tuple(sorted((a,b)))],
                             "zone": first["zone"] if first["zone"] == last["zone"] else "transition",
                             "geometry": [{"lat":s["lat"],"lng":s["lng"]} for s in [first,last]],
                             "timing_source": "dmrc_indicative_journey_time", "distance_source": "station_coordinate_estimate"})
        family="dmrc-ln3" if line["line_code"]=="LN4" else "dmrc-"+line["line_code"].lower()
        suffix=" · Inderlok branch" if index else " · Vaishali branch" if line["line_code"]=="LN4" else ""
        lines.append({"id":identifier,"operator_id":"dmrc","name":line["line_color"]+suffix,
                      "family_id":family,"color":line["primary_color_code"],"station_ids":ids,
                      "segments":segments,"dwell_seconds":0})
    # NMRC's planner confirms each adjacent segment; published first-train times
    # contain mid-line starts, so subtracting those would be incorrect.
    mirror = CACHE/"metro.zip"
    if not mirror.exists():
        mirror.write_bytes(urllib.request.urlopen("https://ethanc8.github.io/delhi-gtfs/metro.zip", timeout=30).read(20_000_000))
    with zipfile.ZipFile(mirror) as archive:
        aqua = [s for s in csv.DictReader(io.StringIO(archive.read("stops.txt").decode("utf-8-sig"))) if 500 <= int(s["stop_id"]) <= 520]
    aqua.sort(key=lambda s:int(s["stop_id"]))
    if len(aqua) != 21:
        raise ValueError("NMRC coordinate snapshot must contain 21 stations")
    station_list=fetch(NMRC+"/StationList",CACHE/"nmrc-station-list.html",False)
    names={int(number):html.unescape(re.sub("<[^>]+>","",name)).strip() for number,name in re.findall(r"<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>(.*?)</td>",station_list,re.S)}
    if not all(i in names for i in range(1,22)):
        raise ValueError("Review changed official NMRC station list")
    for i,row in enumerate(aqua):
        stations.append({"id":f"nmrc-{i+1}","name":names[i+1],"area":"Noida Metro · Aqua Line",
                         "lat":float(row["stop_lat"]),"lng":float(row["stop_lon"]),"x":0,"y":0,"zone":"surface"})
    def aqua_timing(i):
        file = timings/f"nmrc-{i}-{i+1}.html"
        if not file.exists():
            parameter = fetch(NMRC+"/Captcha/EncryptString?"+urllib.parse.urlencode({"EncryptString":f"{i}#{i+1}"}), timings/f"nmrc-param-{i}.json", False).strip('"')
            fetch(NMRC+"/Passenger-Information/Journey-Planner-and-Fares?"+urllib.parse.urlencode({"id":parameter}), file, False)
        text = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", file.read_text(encoding="utf-8"))))
        minute = re.search(r"Timing:\s*([\d.]+)\s*Min",text)
        distance = re.search(r"Distance:\s*([\d.]+)\s*KM",text)
        if not minute or not distance:
            raise ValueError("Missing official NMRC adjacent-station time")
        return {"seconds":round(float(minute[1])*60),"metres":max(1,round(float(distance[1])*1000)),"zone":"surface",
                "geometry":[{"lat":float(s["stop_lat"]),"lng":float(s["stop_lon"])} for s in [aqua[i-1],aqua[i]]],
                "timing_source":"nmrc_indicative_journey_time","distance_source":"nmrc_journey_planner"}
    aqua_segments = list(ThreadPoolExecutor(2).map(aqua_timing,range(1,21)))
    lines.append({"id":"nmrc-aqua","family_id":"nmrc-aqua","operator_id":"nmrc","name":"Aqua Line","color":"#009c9c",
                  "station_ids":[f"nmrc-{i}" for i in range(1,22)],"segments":aqua_segments,"dwell_seconds":0})
    # Scale coordinates for a schematic overview, not navigational walking paths.
    minlat,maxlat = min(s["lat"] for s in stations),max(s["lat"] for s in stations)
    minlng,maxlng = min(s["lng"] for s in stations),max(s["lng"] for s in stations)
    for s in stations:
        s["x"] = round(30+(s["lng"]-minlng)/(maxlng-minlng)*790,2)
        s["y"] = round(30+(maxlat-s["lat"])/(maxlat-minlat)*440,2)
    now = datetime.now(timezone.utc).isoformat()
    transfers = [{"from_station_id":"dmrc-nsf","to_station_id":"nmrc-1","seconds":480,"requires_exit":True,"walking_metres":350,"distance_estimated":True,"source_url":NMRC+"/Passenger-Information/Journey-Planner-and-Fares"}]
    # The operator's FOB is a pedestrian connection, never a fictitious rail line.
    if "dmrc-dkv" in smap and "dmrc-ddsc" in smap:
        transfers.append({"from_station_id":"dmrc-dkv","to_station_id":"dmrc-ddsc","seconds":600,"requires_exit":True,"walking_metres":1000,"distance_estimated":True,"source_url":"https://delhimetrorail.com/map"})
    config = {"schema_version":1,"provider":"DMRC & NMRC passenger information","source_url":"https://delhimetrorail.com/map",
              "version":"operator-catalogue-"+now[:10],"published_at":now,"stations":stations,"lines":lines,
              "checkpoints":[],"transfer_seconds":240,"transfer_walking_metres":180,"transfers":transfers,"journey_planning":True,
              "sources":[{"url":"https://delhimetrorail.com/map","retrieved_at":now,"scope":"DMRC station layouts, coordinates, open station adjacency and indicative journey times"},
                         {"url":NMRC+"/StationList","retrieved_at":now,"scope":"NMRC 21-station network"},
                         {"url":NMRC+"/Passenger-Information/Journey-Planner-and-Fares","retrieved_at":now,"scope":"NMRC indicative segment time and distance"},
                         {"url":"https://otd.delhi.gov.in/data/staticDMRC/","mirror_url":"https://ethanc8.github.io/delhi-gtfs/metro.zip","scope":"Historical NMRC coordinates only; feed expired 2025-12-31"}],
              "coverage_note":"Open stations in the retrieved DMRC passenger API and all 21 NMRC stations. Rapid Metro Gurugram is outside this Delhi/Noida catalogue. Journey times are indicative static estimates, not next-train departures. Walking distances are estimates; station access and security time are not measured. NMRC coordinates come from a historical OTD mirror; track geometry is a straight station-to-station approximation. Refresh and review operator changes before deployment."}
    # Discover the actual Sector 52 code rather than accepting a name-based guess.
    sector52 = next(s["id"] for s in stations if s["id"].startswith("dmrc-") and "52" in s["name"] and "Noida" in s["name"])
    config["transfers"][0]["from_station_id"] = sector52
    station_lookup={s["id"]:s for s in stations}
    for connection in config["transfers"]:
        # Approximate platform-centre access: never less than straight distance.
        estimate=round(metres(station_lookup[connection["from_station_id"]],station_lookup[connection["to_station_id"]])*1.25+80,-1)
        connection["walking_metres"]=estimate
        connection["seconds"]=max(connection["seconds"],round(estimate/1.2)+120)
    digest=hashlib.sha256(json.dumps({"stations":stations,"lines":lines,"transfers":config["transfers"]},sort_keys=True).encode()).hexdigest()[:10]
    config["version"]+="-"+digest
    from backend.app.provider_contracts import NetworkImport
    config = NetworkImport.model_validate(config).model_dump(mode="json")
    output = ROOT/"data/operator-network.json"
    output.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Saved {len(stations)} stations, {len(lines)} line paths to {output}",flush=True)


if __name__ == "__main__":
    build()
