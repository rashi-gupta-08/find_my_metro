"""Explicit software-only inputs. Never imported or enabled as an operator live feed."""
from datetime import timedelta
import math
import secrets
from sqlalchemy import select
from .db import iso, parse
from .models import Device, Runtime, Trip, User

SCENARIOS = {"normal":"Automatic journey", "underground":"Underground signals", "surface":"Surface reports",
             "transition":"Tunnel handover", "reverse-transition":"Surface to tunnel",
             "sensor-loss":"Sensor loss", "conflict":"Conflicting reports", "timeout":"Transition timeout", "delay":"Delayed train",
             "corroboration":"Matching phone and sensor evidence"}


def network_contract(now):
    stations, lines, checkpoints = [], [], []
    for offset, (operator, color) in enumerate([("dmrc","#e5ae30"),("nmrc","#249e9b")]):
        identifier = operator+"-software"
        names = ["Tunnel West", "Tunnel East", "Portal", "Surface Park", "Surface Terminal"]
        ids = [operator+f"-test-{index}" for index in range(5)]
        for index, (station, name) in enumerate(zip(ids,names)):
            stations.append({"id":station,"name":name,"area":"Software validation network",
                             "lat":28.6+offset*.025,"lng":77.2+index*.006,"x":80+index*160,"y":140+offset*180,
                             "zone": "underground" if index<2 else "transition" if index==2 else "surface"})
        segments = [{"metres":600,"seconds":30,"zone":["underground","transition","surface","surface"][index],
                     "geometry":[{"lat":28.6+offset*.025,"lng":77.2+index*.006},
                                 {"lat":28.6+offset*.025,"lng":77.2+(index+1)*.006}]} for index in range(4)]
        lines.append({"id":identifier,"operator_id":operator,"name":("Delhi" if operator=="dmrc" else "Noida")+" software test line",
                      "color":color,"station_ids":ids,"segments":segments,"dwell_seconds":6})
        for direction in ["inbound","outbound"]:
            checkpoints.extend({"id":f"{identifier}-{direction}-{index}","node_id":f"{identifier}_{direction}_{index}",
                                "line_id":identifier,"direction":direction,"position_m":index*100} for index in range(25))
    return {"schema_version":1,"provider":"Software validation feed — not real Delhi/Noida train tracking",
            "source_url":"https://example.invalid/findmymetro-software-validation","version":"software-network-v1","published_at":iso(now),
            "stations":stations,"lines":lines,"checkpoints":checkpoints,"transfer_seconds":60,
            "transfers":[{"from_station_id":f"dmrc-test-{index}","to_station_id":f"nmrc-test-{index}","seconds":8,"requires_exit":True} for index in [1,3]]}


def ensure(session, now):
    from .auth import digest
    from .config import settings
    from .network import CONFIG
    if settings.app_env != "software" or not CONFIG or CONFIG["version"] != "software-network-v1":
        raise RuntimeError("Software inputs require the dedicated software profile and network")
    control = session.get(Runtime,"software-control")
    if control is None:
        control=Runtime(key="software-control",value={"scenario":"normal","run":secrets.token_hex(5),"started_at":iso(now)})
        session.add(control)
    for index in range(3):
        identifier=f"software-contributor-{index}"
        if not session.get(User,identifier):
            # Internal input identities cannot sign in; passwords are never issued for them.
            session.add(User(id=identifier,username=f"software_input_{index}",display_name=f"Software contributor {index+1}",
                             password_hash="!no-interactive-login",role="passenger",disabled=False,verified_contributor=True,created_at=iso(now)))
    for cp in CONFIG["checkpoints"]:
        if not session.get(Device,cp["node_id"]):
            session.add(Device(node_id=cp["node_id"],key_hash=digest(settings.auth_secret+":"+cp["node_id"]),disabled=False,created_at=iso(now)))
    session.flush()
    return control


def control_status(session, now):
    control=session.get(Runtime,"software-control")
    return {"enabled":True,"synthetic":True,"scenario":control.value["scenario"] if control else "normal",
            "run":control.value["run"] if control else None,"started_at":control.value["started_at"] if control else None,
            "scenarios":[{"id":key,"label":value} for key,value in SCENARIOS.items()]}


def change_scenario(session, scenario, now):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown software input scenario")
    control=ensure(session,now)
    control.value={"scenario":scenario,"run":secrets.token_hex(5),"started_at":iso(now)}
    for trip in session.scalars(select(Trip).where(Trip.network_version=="software-network-v1", Trip.cancelled.is_(False))):
        trip.cancelled=True
        trip.timetable={**trip.timetable,"cancelled":True}
    return control_status(session,now)


def generate(session, now):
    from .acquisition import ingest
    from .engines import initial_state
    from .network import LINE_MAP, CONFIG, context_at, coords_at, path_for
    from .provider_contracts import TimetableImport
    from .operations import import_timetable
    control=ensure(session,now)
    scenario=control.value["scenario"]
    started=parse(control.value["started_at"])
    elapsed=max(0,(now-started).total_seconds())
    cycle=int(elapsed//180)
    age=elapsed%180
    for line_no, line in enumerate(LINE_MAP.values()):
        direction="inbound" if scenario=="reverse-transition" else "outbound"
        for service_cycle in [cycle,cycle+1]:
            service_id=f"software-{control.value['run']}-{service_cycle}-{line['id']}"
            departure=started+timedelta(seconds=service_cycle*180)
            if session.get(Trip,service_id) is None:
                stops=[]
                for index,station in enumerate(path_for(line["id"],direction)):
                    arrival=departure+timedelta(seconds=index*36)
                    stops.append({"station_id":station,"arrival_at":iso(arrival),"departure_at":iso(arrival+timedelta(seconds=6)),"platform":"Software"})
                import_timetable(session,TimetableImport.model_validate({"network_version":CONFIG["version"],"trips":[{
                    "id":service_id,"code":f"SW-{line_no+1:02d}","line_id":line["id"],"direction":direction,"stops":stops}]}),now)
                session.flush()
        identifier=f"software-{control.value['run']}-{cycle}-{line['id']}"
        trip=session.get(Trip,identifier)
        if age>140:
            continue
        start=1300 if scenario=="surface" else 500 if scenario in {"transition","timeout","conflict","corroboration"} else 1100 if scenario=="reverse-transition" else 100
        speed=12 if scenario=="delay" and line_no==0 else 20
        position=min(2400,start+speed*age)
        corroborating=scenario=="corroboration" and age>=6
        if scenario=="corroboration": position=min(600,position)
        if scenario in {"underground","sensor-loss"}:
            position=min(500,position)
        context=context_at(trip.line_id,direction,position)
        index=min(24,int(position//100))
        stamp=iso(now)
        sensor_on = context=="underground" or context=="transition" and scenario in {"conflict","reverse-transition"} or scenario=="conflict"
        # Emit the boundary node even when entering a connectivity gap.
        boundary_index=6 if direction=="outbound" else 12
        crossed=index>=boundary_index
        marker=session.get(Runtime,"software-mark:"+identifier)
        marked=dict(marker.value) if marker else {"checkpoint":-1,"boundary":False,"crowd_second":-1}
        if crossed and not marked["boundary"] and scenario!="surface":
            sensor_on=True
            index=boundary_index
            marked["boundary"]=True
        unhealthy=scenario=="sensor-loss" and age>=8
        if corroborating and not marked.get("arrival"): sensor_on=True
        if sensor_on and (index!=marked["checkpoint"] or unhealthy and not marked.get("unhealthy") or corroborating and not marked.get("arrival")):
            cp=next(cp for cp in CONFIG["checkpoints"] if cp["line_id"]==trip.line_id and cp["direction"]==direction and cp["position_m"]==index*100)
            ingest(session,{"event_id":f"{identifier}:wsn:{index}:{int(age)}","trip_id":identifier,"direction":direction,"observed_at":stamp,
                            "node_id":cp["node_id"],"checkpoint_id":cp["id"],"healthy":not unhealthy,
                            **({"kind":"arrival","station_id":path_for(trip.line_id,direction)[1],"match_key":identifier+":portal:arrival"} if corroborating else {})},"wsn",now=now)
            marked["checkpoint"],marked["unhealthy"]=index,unhealthy
            if corroborating: marked["arrival"]=True
        crowd_on=context in {"transition","surface"} and scenario not in {"timeout","underground","sensor-loss"}
        if scenario=="reverse-transition":
            crowd_on=context in {"surface","transition"}
        if scenario=="transition" and age<10:
            crowd_on=False
        if scenario=="corroboration": crowd_on=corroborating
        second=int(age//3)
        if crowd_on and marked["crowd_second"]!=second:
            reported=min(2400,position+(300 if scenario=="conflict" else 0))
            lat,lng=coords_at(trip.line_id,direction,reported)
            for contributor in range(3):
                owner=f"software-contributor-{contributor}"
                ingest(session,{"event_id":f"{identifier}:crowd:{contributor}:{second}","trip_id":identifier,"direction":direction,
                                "observed_at":stamp,"kind":"sighting","contributor_id":owner,"position_m":reported,
                                "latitude":lat,"longitude":lng,"accuracy_m":10,"note":"Explicit software-generated validation input",
                                **({"kind":"arrival","station_id":path_for(trip.line_id,direction)[1],"match_key":identifier+":portal:arrival"} if corroborating else {})},"crowd",contributor=owner,now=now)
            marked["crowd_second"]=second
        if marker: marker.value=marked
        else: session.add(Runtime(key="software-mark:"+identifier,value=marked))
