"""Deterministic, fictional passenger reports. This module never imports the app DB."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
from statistics import median

SEED = 20261028
ANCHOR = datetime(2026, 10, 28, 2, 30, tzinfo=timezone.utc)
POLICY = {"service_report_max_age_seconds": 30, "service_consensus_window_seconds": 120,
          "service_consensus_users": 3, "delay_agreement_band_seconds": 60,
          "station_proximity_metres": 250, "maximum_gps_accuracy_metres": 100,
          "maximum_future_timestamp_seconds": 5}


def build_dataset(network_path):
    """Expected labels are outside the submitted body; no outcomes enter the API."""
    path = Path(network_path)
    network_bytes = path.read_bytes()
    network = json.loads(network_bytes)
    stations = {s["id"]: s for s in network["stations"]}
    rng = random.Random(SEED)
    cases = []
    participants = [{"id": f"beta-{i:03}", "username": f"beta_passenger_{i:03}",
                     "display_name": f"Fictional passenger {i:03}", "data_kind": "synthetic"}
                    for i in range(1, 49)]

    def case(identifier, title, explanation, station="dmrc-sftn", line="dmrc-ln3", direction="outbound", destination="dmrc-necc"):
        value = {"id": identifier, "title": title, "explanation": explanation,
                 "starts_at": (ANCHOR+timedelta(seconds=len(cases)*180)).isoformat(),
                 "target": {"station_id": station, "line_id": line, "direction": direction, "event_type": "delayed"},
                 "journey": {"origin": station, "destination": destination}, "deliveries": [], "checkpoints": []}
        cases.append(value)
        return value

    def report(c, actor, delay=300, observed=0, received=2, kind="delayed", change=None,
               status="validated", reason="awaiting_independent_agreement", ack="queued"):
        station = stations[c["target"]["station_id"]]
        body = {"event_id": f"beta:{c['id']}:{len(c['deliveries'])+1:03}",
                "station_id": station["id"], "line_id": c["target"]["line_id"],
                "direction": c["target"]["direction"],
                "observed_at": (datetime.fromisoformat(c["starts_at"])+timedelta(seconds=observed)).isoformat(),
                "event_type": kind, "latitude": round(station["lat"]+rng.uniform(-.00005,.00005),7),
                "longitude": round(station["lng"]+rng.uniform(-.00005,.00005),7),
                "accuracy_m": rng.randint(6,25), "delay_seconds": delay,
                "note": "SYNTHETIC BETA REPORT - fictional passenger and location reading"}
        if change:
            body.update(change)
        delivery = {"participant_id": f"beta-{actor:03}", "received_offset_seconds": received,
                    "report": body, "expected_ack": ack, "expected_processing_status": status,
                    "expected_reason": reason}
        c["deliveries"].append(delivery)
        return delivery

    def check(c, at=5, count=3, delay=300, route_delay=None, status=None, event_type=None, **extra):
        target = {**c["target"]}
        if event_type:
            target["event_type"] = event_type
        c["checkpoints"].append({"offset_seconds": at, "target": target,
              "expected_signal": None if count==0 else {"status": status or ("confirmed" if count>=3 else "awaiting_agreement"),
                    "confirmations": count, "delay_seconds": delay if count>=3 and target["event_type"]=="delayed" else None},
              "expected_route_delay_seconds": delay if route_delay is None and count>=3 else (route_delay or 0), **extra})

    c=case("surface-agreement","Surface: three passengers agree","Three fictional, independently authenticated accounts report a five-minute extra wait.")
    for i,d in enumerate([295,300,305],1): report(c,i,d)
    check(c,expected_awards=3)

    c=case("no-input","No reports: static baseline","No location or crowd evidence must produce the existing static journey estimate.")
    check(c,count=0,delay=0)

    c=case("sparse-crowd","Only two passengers","Two accounts do not meet the required three-account quorum.")
    for i in [1,2]:report(c,i)
    check(c,count=2,expected_awards=0)

    c=case("same-account","Repeated submissions from one account","Eight different events from one account still count as one account.")
    for i in range(8):report(c,1,observed=i,received=i+1)
    check(c,at=10,count=1,expected_awards=0)

    c=case("duplicate-delivery","Offline retry: same event ID","Replaying an identical event does not add confirmations or rewards.")
    first=report(c,1)
    for i in [2,3]:report(c,i)
    duplicate=deepcopy(first);duplicate.update(received_offset_seconds=4,expected_ack="duplicate")
    c["deliveries"].append(duplicate)
    check(c,expected_awards=3)

    c=case("id-conflict","Changed content under an existing ID","A retry with altered content is a conflict; the first event remains intact.")
    first=report(c,1)
    duplicate=deepcopy(first);duplicate["report"]["delay_seconds"]=900
    duplicate.update(received_offset_seconds=4,expected_ack="conflict")
    c["deliveries"].append(duplicate)
    check(c,count=1)

    c=case("cross-account-id","One event ID reused by another account","An event ID cannot be reassigned to another contributor.")
    first=report(c,1)
    duplicate=deepcopy(first);duplicate.update(participant_id="beta-002",received_offset_seconds=4,expected_ack="conflict")
    c["deliveries"].append(duplicate)
    check(c,count=1)

    c=case("conflicting-delays","Reports disagree on the delay","A 0/60/120-second chain cannot create a false three-account consensus.")
    for i,d in enumerate([0,60,120],1):report(c,i,d)
    check(c,count=2,expected_awards=0)

    c=case("honest-majority","Consistent group plus outliers","Three consistent reports can agree while two conflicting accounts are excluded.")
    for i,d in enumerate([295,300,305,0,900],1):report(c,i,d)
    check(c,expected_awards=3)

    c=case("late-upload","Offline upload retains its original time","Reports observed 45 seconds earlier are stored as historical, never refreshed by upload time.")
    for i in [1,2,3]:report(c,i,observed=-45,status="historical",reason="stale_surface_report")
    check(c,count=0,expected_awards=0)

    c=case("freshness-boundary","Freshness expires at exactly 30 seconds","The same quorum works at 29.999 seconds and disappears at 30 seconds without another event.")
    for i in [1,2,3]:report(c,i)
    check(c,at=29.999);check(c,at=30,count=0);check(c,at=60,count=0)

    c=case("partial-expiry","One expiring member breaks the quorum","Observation times of 0/10/20 seconds are still only two fresh accounts at second 30.")
    for i,t in enumerate([0,10,20],1):report(c,i,observed=t,received=t)
    check(c,at=29);check(c,at=30,count=2);check(c,at=50,count=0)

    c=case("off-station","GPS fix far from the selected station","A fictional fix about one kilometre away fails the 250-metre station check.")
    for i in [1,2,3]:report(c,i,change={"latitude":stations["dmrc-sftn"]["lat"]+.01},status="rejected",reason="outside_station_proximity")
    check(c,count=0)

    c=case("missing-location","Location permission unavailable","Station selection alone does not qualify a live crowd report.")
    for i in [1,2,3]:report(c,i,change={"latitude":None,"longitude":None,"accuracy_m":None},status="rejected",reason="location_evidence_required")
    check(c,count=0)

    c=case("inaccurate-gps","GPS accuracy outside the contract","Accuracy above 100 metres is rejected by the submitted report schema.")
    for i in [1,2,3]:report(c,i,change={"accuracy_m":101},status=None,reason="invalid_surface_report",ack="rejected")
    check(c,count=0)

    c=case("wrong-line","Station and line do not match","A Blue Line station cannot be submitted as an Aqua Line observation.")
    for i in [1,2,3]:report(c,i,change={"line_id":"nmrc-aqua"},status="rejected",reason="station_line_mismatch")
    check(c,count=0)

    c=case("future-clock","Phone clock ahead by ten seconds","Future timestamps beyond the five-second tolerance are rejected.")
    for i in [1,2,3]:report(c,i,observed=12,received=2,status="rejected",reason="future_timestamp")
    check(c,count=0)

    c=case("split-directions","Opposite directions stay separate","Two reports in each direction do not form a four-account quorum.")
    for i in [1,2]:report(c,i)
    for i in [3,4]:report(c,i,change={"direction":"inbound"})
    check(c,count=2)

    c=case("split-types","Arrival and delay votes stay separate","Two delay reports and one arrival report are not three delay confirmations.")
    report(c,1);report(c,2);report(c,3,delay=0,kind="arrived")
    check(c,count=2);check(c,count=1,event_type="arrived")

    for kind in ["arrived","departed","crowded"]:
        c=case("type-"+kind,"Three passengers: "+kind,"A confirmed typed report never becomes a fabricated live train or a delay measurement.")
        for i in [1,2,3]:report(c,i,delay=0,kind=kind)
        check(c,delay=0,event_type=kind)

    c=case("reverse-direction","Inbound travel","Inbound agreement applies only to a journey in the configured inbound direction.",station="dmrc-necc",destination="dmrc-sftn",direction="inbound")
    for i in [1,2,3]:report(c,i,delay=180)
    check(c,delay=180)

    c=case("underground-unmapped","Underground: unmapped cell readings","Invented cell hashes deliberately have no reviewed map, so the route keeps static timing.",station="dmrc-rck",line="dmrc-ln2",destination="dmrc-ndi",direction="inbound")
    for i in [1,2,3]:report(c,i,change={"latitude":None,"longitude":None,"accuracy_m":None,"cell_fingerprints":["a"*64,"b"*64]},status="rejected",reason="unverified_cell_location")
    check(c,count=0)

    c=case("mixed-corridor","Mixed underground and surface corridor","Injected station coordinates test the software's accepted-evidence path; they are not real underground GPS measurements.",station="dmrc-rck",destination="dmrc-necc")
    for i in [1,2,3]:report(c,i,delay=180)
    check(c,delay=180,required_route_contexts=["underground","surface","transition"])
    check(c,at=30,count=0,required_route_contexts=["underground","surface","transition"])

    c=case("aqua-delay","Aqua Line: no alternative metro corridor","Agreement changes the route wait; a single corridor may correctly have no faster alternative.",station="nmrc-1",line="nmrc-aqua",destination="nmrc-4")
    for i in [1,2,3]:report(c,i,delay=300)
    check(c,expected_rerouting="no_faster_alternative")

    c=case("later-boarding","Evidence expires before a later boarding","Aqua evidence that expires during the inter-operator walk must not be used when boarding later.",station="nmrc-1",line="nmrc-aqua",destination="nmrc-4")
    # Start one ride before the inter-operator walk, so this case isolates
    # later-boarding expiry rather than the planner's walk-first restriction.
    c["journey"]["origin"]="dmrc-stfn"
    for i in [1,2,3]:report(c,i)
    check(c,route_delay=0)

    # Varied but bounded traffic cohorts. Negative labels describe known injected
    # faults, not measured passenger honesty or real-world train ground truth.
    aqua=[s for s in network["lines"] if s["id"]=="nmrc-aqua"][0]["station_ids"]
    for number in range(1,21):
        start=(number-1)%17
        c=case(f"traffic-{number:02}",f"Traffic cohort {number:02}",
               "A seeded group with GPS jitter, plausible delay disagreement and four injected location/time faults.",
               station=aqua[start],line="nmrc-aqua",destination=aqua[start+3])
        actors=rng.sample(range(1,49),rng.randint(17,23))
        base_delay=rng.choice([60,120,180,240,300,420])
        delays=[]
        for index,actor in enumerate(actors[:-4]):
            delay=base_delay+rng.choice([-20,-10,0,10,20]);delays.append(delay)
            report(c,actor,delay=delay,observed=index/2,received=10+index/4)
        report(c,actors[-4],delay=base_delay,observed=-45,received=12,status="historical",reason="stale_surface_report")
        report(c,actors[-3],delay=base_delay,received=12,change={"latitude":stations[aqua[start]]["lat"]+.02},status="rejected",reason="outside_station_proximity")
        report(c,actors[-2],delay=base_delay,received=12,change={"latitude":None,"longitude":None,"accuracy_m":None},status="rejected",reason="location_evidence_required")
        report(c,actors[-1],delay=base_delay,observed=23,received=12,status="rejected",reason="future_timestamp")
        check(c,at=20,count=len(delays),delay=round(median(delays)))
        check(c,at=40,count=0)

    return {"schema_version":1,"dataset_id":"findmymetro-crowd-beta-v1","data_kind":"synthetic",
            "purpose":"Functional beta validation before a real passenger pilot; not ETA model training or field-performance evidence.",
            "seed":SEED,"reference_clock":ANCHOR.isoformat(),"network_version":network["version"],
            "network_sha256":hashlib.sha256(network_bytes).hexdigest(),"policy":POLICY,
            "location_notice":"Station references come from the existing catalogue. Every submitted position and account is fictional; underground fixes are controlled software inputs.",
            "participants":participants,"scenarios":cases}
