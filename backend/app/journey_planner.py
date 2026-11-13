"""Passenger route alternatives over static topology with qualified live overlays."""
from datetime import timedelta
import hashlib
import itertools
import networkx as nx
from .db import iso, parse
from .network import CONFIG, LINES, STATIONS, STATION_MAP, LINE_MAP
from .models import Runtime
from .operations import active_trips
from .prediction import arrivals_for, effective_state
from .surface_reports import signals
from .config import settings


def accepted_arrivals(session, now):
    """Publish only the state selected by the patent engines, never raw events."""
    result = {}
    for trip in active_trips(session, now):
        state = effective_state(trip, now)
        source = state["source"]
        valid_until = None
        if source == "estimate" and state.get("transition"):
            valid_until = state["transition"]["deadline"]
        elif source in {"wsn", "crowd", "fused"} and state.get("last_observed_at"):
            age_limit = settings.sensor_max_age_seconds if source == "wsn" else settings.crowd_max_age_seconds
            valid_until = iso(parse(state["last_observed_at"])+timedelta(seconds=age_limit))
        for arrival in arrivals_for(trip, now):
            status = {"source": source, "scope": "identified_train", "train_context": state["context"],
                      "trust_score": arrival["trust_score"], "freshness_status": arrival["freshness_status"],
                      "last_observed_at": arrival["last_observation_at"], "valid_until": valid_until,
                      "reason": state.get("reason", "awaiting_evidence"), "scores": state.get("scores", {}),
                      "model_version": arrival["model_version"], "transition": state.get("transition"),
                      "arbitration": state.get("arbitration"), "next_arrival": arrival,
                      "delay_seconds": arrival["delay_seconds"] if source != "schedule" else 0}
            key = (arrival["station_id"], trip.line_id, trip.direction)
            result.setdefault(key, []).append(status)
    for items in result.values():
        items.sort(key=lambda value: value["next_arrival"]["arrival_at"])
    return result


def boarding_status(edge, station, ready_at, now, trains, community):
    context = edge["context"]
    status = {"source": "schedule", "scope": "static", "planned_context": context,
              "preferred_source": "static_and_phone" if context == "underground" else "crowd" if context == "surface" else "arbitration",
              "train_context": None, "trust_score": None, "freshness_status": "static_baseline",
              "last_observed_at": None, "valid_until": None, "reason": "awaiting_qualified_evidence",
              "scores": {}, "model_version": "operator-static-travel-time-v1", "transition": None,
              "arbitration": None, "next_arrival": None, "delay_seconds": 0}
    key = (station, edge["line_id"], edge["direction"])
    # A later, high-trust train must not replace the next boardable service.
    for candidate in trains.get(key, []):
        arrival = candidate["next_arrival"]
        if parse(arrival["arrival_at"]) < ready_at:
            continue
        if candidate["valid_until"] and ready_at >= parse(candidate["valid_until"]):
            continue
        status.update(candidate)
        break
    if status["source"] == "schedule":
        report = community.get(key)
        if report and ready_at < parse(report["expires_at"]):
            # This is station service evidence, not a phone-created train identity.
            status.update(source="crowd", scope="station_service", train_context=None,
                          trust_score=report["trust_score"], freshness_status="fresh",
                          last_observed_at=report["last_observed_at"], valid_until=report["expires_at"],
                          reason="independent_station_agreement", scores={"crowd": report["trust_score"]},
                          model_version="community-wait-overlay-v1", delay_seconds=report["delay_seconds"],
                          confirmations=report["confirmations"])
    if status["last_observed_at"]:
        status["age_seconds"] = max(0, round((now-parse(status["last_observed_at"])).total_seconds()))
    else:
        status["age_seconds"] = None
    return status


def planning_graph(closed):
    graph=nx.DiGraph()
    serving={s["id"]:set() for s in STATIONS}
    for line in LINES:
        if line["id"] in closed:
            continue
        family=line.get("family_id") or line["id"]
        for station in line["station_ids"]:
            serving[station].add(family)
        for index,(a,b) in enumerate(zip(line["station_ids"],line["station_ids"][1:])):
            segment=line["segments"][index]
            for start,end,direction in [(a,b,"outbound"),(b,a,"inbound")]:
                graph.add_edge((start,family),(end,family),kind="ride",line_id=line["id"],family_id=family,direction=direction,
                               seconds=segment["seconds"],metres=segment["metres"],walking_metres=0,changes=0,context=segment["zone"],
                               timing_source=segment.get("timing_source","configured"),distance_estimated=segment.get("distance_source")!="nmrc_journey_planner")
    for station,families in serving.items():
        for a,b in itertools.permutations(families,2):
            # Clearly labelled estimates until measured platform/gate paths exist.
            walking=300 if STATION_MAP[station]["zone"]=="underground" else CONFIG.get("transfer_walking_metres",180)
            graph.add_edge((station,a),(station,b),kind="transfer",line_id=next(l["id"] for l in LINES if (l.get("family_id") or l["id"])==b),
                           seconds=max(CONFIG["transfer_seconds"],round(walking/1.2)+60),walking_metres=walking,metres=0,changes=1,
                           requires_exit=False,distance_estimated=True,context=STATION_MAP[station]["zone"])
    for connection in CONFIG.get("transfers",[]):
        for a,b in [(connection["from_station_id"],connection["to_station_id"]),(connection["to_station_id"],connection["from_station_id"])]:
            for x,y in itertools.product(serving[a],serving[b]):
                graph.add_edge((a,x),(b,y),kind="transfer",line_id=next(l["id"] for l in LINES if (l.get("family_id") or l["id"])==y),
                               seconds=connection["seconds"],walking_metres=connection.get("walking_metres") or 0,metres=0,changes=1,
                               requires_exit=connection["requires_exit"],distance_estimated=connection.get("distance_estimated",True),context="surface")
    return graph


def journey_routes(session,origin,destination,depart_at,now,preference="fastest"):
    if origin not in STATION_MAP or destination not in STATION_MAP:
        raise ValueError("unknown_station")
    if origin==destination:
        return {"routes":[],"reason":"already_at_destination","simulated":False}
    control=session.get(Runtime,"control")
    closed=set(control.value.get("closed_lines",[])) if control else set()
    graph=planning_graph(closed)
    overlays={}
    # Station observations affect waiting at the boarding point once. They are
    # not evidence that a particular train is late along its entire route.
    for signal in signals(session,now):
        if signal["status"]=="confirmed" and signal.get("event_type","delayed")=="delayed":
            overlays[(signal["station_id"],signal["line_id"],signal["direction"])]=signal
    trains=accepted_arrivals(session,now)
    start,end=("__origin__",""),("__destination__","")
    for node in list(graph):
        if node[0]==origin:graph.add_edge(start,node,kind="access",seconds=0,metres=0,walking_metres=0,changes=0)
        if node[0]==destination:graph.add_edge(node,end,kind="access",seconds=0,metres=0,walking_metres=0,changes=0)
    if start not in graph or end not in graph:
        return {"routes":[],"reason":"no_valid_route","simulated":False}
    # Small station graph with strictly non-negative weights. Each objective
    # has a bounded Yen search, rather than enumerating unhelpful detour cycles.
    candidates={}
    for objective in ["fastest","fewest_changes","least_walking","shortest_distance","live_origin_wait"]:
        def weight(a,b,edge):
            # Generate topology alternatives on the baseline, then rank them
            # using boarding-specific live overlays. A station delay is never
            # charged repeatedly on every following ride edge.
            seconds=edge["seconds"]
            if objective=="live_origin_wait" and edge.get("kind")=="ride" and a[0]==origin:
                report=overlays.get((origin,edge["line_id"],edge["direction"]))
                if report and depart_at<parse(report["expires_at"]):
                    seconds+=report["delay_seconds"]
            if objective=="fewest_changes":return edge["changes"]*100_000_000+seconds
            if objective=="least_walking":return edge["walking_metres"]*1_000_000+seconds
            if objective=="shortest_distance":return edge["metres"]*1000+edge["walking_metres"]*1000+seconds
            return seconds
        try:
            for path in itertools.islice(nx.shortest_simple_paths(graph,start,end,weight=weight),12):
                route_nodes=path[1:-1]
                sequence=[node[0] for i,node in enumerate(route_nodes) if not i or node[0]!=route_nodes[i-1][0]]
                if len(sequence)!=len(set(sequence)):
                    continue
                signature=tuple(route_nodes)
                candidates.setdefault(signature,route_nodes)
        except nx.NetworkXNoPath:
            pass
    options=[]
    for nodes in candidates.values():
        steps=[]
        source_statuses=[]
        seconds,walking,distance,changes=0,0,0,0
        boarding=True
        for a,b in zip(nodes,nodes[1:]):
            edge=graph[a][b]
            status=boarding_status(edge,a[0],depart_at+timedelta(seconds=seconds),now,trains,overlays) if boarding and edge["kind"]=="ride" else None
            delay=status["delay_seconds"] if status else 0
            if status:
                source_statuses.append({**status,"boarding_station_id":a[0],"line_id":edge["line_id"],"direction":edge["direction"]})
            step={**edge,"from_station_id":a[0],"to_station_id":b[0],"source":status["source"] if status else "schedule",
                  "delay_seconds":delay,"seconds":edge["seconds"]+delay,"wait_seconds":delay,
                  "last_observed_at":status.get("last_observed_at") if status else None,"source_status":status,
                  "departure_at":iso(depart_at+timedelta(seconds=seconds)),"arrival_at":iso(depart_at+timedelta(seconds=seconds+edge["seconds"]+delay))}
            seconds+=step["seconds"];walking+=edge["walking_metres"];distance+=edge["metres"];changes+=edge["changes"]
            steps.append(step)
            boarding=edge["kind"]=="transfer"
        if not steps or steps[0]["kind"]!="ride" or steps[-1]["kind"]!="ride":
            continue
        identifier=hashlib.sha256(json_repr([(s["from_station_id"],s["to_station_id"],s.get("family_id"),s["kind"]) for s in steps]).encode()).hexdigest()[:12]
        options.append({"id":identifier,"steps":steps,"duration_seconds":seconds,"transfers":changes,"walking_metres":round(walking),
                        "distance_metres":round(distance),"station_count":len({s["from_station_id"] for s in steps}|{s["to_station_id"] for s in steps}),
                        "walking_estimated":True,"departure_at":iso(depart_at),"arrival_at":iso(depart_at+timedelta(seconds=seconds)),
                        "source":"live_and_schedule" if any(s["source"]!="schedule" for s in steps) else "schedule",
                        "delay_seconds":sum(s["delay_seconds"] for s in steps),"simulated":False,"recommendations":[],"source_statuses":source_statuses})
    # Deduplicate equivalent physical routes represented by different branch IDs.
    unique={}
    for option in options:
        key=tuple((s["from_station_id"],s["to_station_id"],s.get("family_id"),s["kind"]) for s in option["steps"])
        unique.setdefault(key,option)
    options=list(unique.values())
    orders={"fastest":lambda r:(r["duration_seconds"],r["transfers"],r["walking_metres"]),
            "fewest_changes":lambda r:(r["transfers"],r["duration_seconds"]),
            "least_walking":lambda r:(r["walking_metres"],r["duration_seconds"]),
            "shortest_distance":lambda r:(r["distance_metres"],r["duration_seconds"])}
    for kind,order in orders.items():
        if options:min(options,key=order)["recommendations"].append(kind)
    selected=sorted(options,key=orders[preference])
    # Always retain the best suggestion for every requested objective.
    recommended=[r for r in selected if r["recommendations"]]
    selected=sorted((recommended+[r for r in selected if r not in recommended])[:8],key=orders[preference])
    rerouting={"status":"no_qualifying_delay","delay_trigger_seconds":settings.reroute_delay_seconds,
               "minimum_saving_seconds":settings.reroute_min_saving_seconds,"saving_seconds":0,"valid_until":None}
    if options:
        baseline=min(options,key=lambda r:(r["duration_seconds"]-r["delay_seconds"],r["transfers"]))
        fastest=min(options,key=orders["fastest"])
        rerouting.update(baseline_route_id=baseline["id"],suggested_route_id=None)
        if baseline["delay_seconds"]>settings.reroute_delay_seconds:
            deadlines=[status["valid_until"] for status in baseline["source_statuses"] if status.get("valid_until") and status["delay_seconds"]>0]
            rerouting["valid_until"]=min(deadlines,default=None)
            saving=baseline["duration_seconds"]-fastest["duration_seconds"]
            rerouting.update(saving_seconds=saving,status="no_faster_alternative" if fastest["id"]==baseline["id"] else "saving_below_threshold")
            if saving>=settings.reroute_min_saving_seconds:
                rerouting.update(status="alternative_suggested",suggested_route_id=fastest["id"])
    return {"routes":selected,"reason":None if selected else "no_valid_route","simulated":False,"preference":preference,"rerouting":rerouting,
            "generated_at":iso(now),"network_version":CONFIG["version"],"search_scope":"bounded_loop_free_alternatives",
            "timing_note":"Indicative running and transfer time. Boarding wait, security and station access are not included; confirmed community delay is added at boarding once.",
            "coverage_note":CONFIG.get("coverage_note","")}


def json_repr(value):
    import json
    return json.dumps(value,separators=(",",":"))
