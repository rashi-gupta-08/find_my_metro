"""Replay fictional beta reports through the real API/worker in a new private DB.

No live server URL is accepted. A virtual clock makes expiry/reconnect tests
repeatable. This is functional validation, not load, radio or ETA-accuracy testing.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]


def isolated_environment(run):
    """No inherited passenger DB, credentials, field maps or sensor adapters."""
    run=run.resolve()
    allowed=(ROOT/".local/crowd-beta").resolve()
    if not run.is_relative_to(allowed) or run==allowed or (run/"beta.db").exists():
        raise ValueError("Beta replay requires a new run folder under .local/crowd-beta")
    env_file=run/"test.env"
    env_file.write_text("# Isolated beta configuration is provided by the runner.\n",encoding="utf-8")
    return {"APP_ENV":"test","METRO_ENV_FILE":str(env_file),"AUTH_SECRET":secrets.token_hex(32),
        "DATABASE_URL":"sqlite:///"+(run/"beta.db").as_posix(),"MIGRATION_DATABASE_URL":"",
        "NETWORK_FILE":str(ROOT/"data/operator-network.json"),"SIMULATION_ENABLED":"false",
        "HARDWARE_ENABLED":"false","MQTT_ENABLED":"false","PREDICTION_MODEL_FILE":"","CELL_MAP_FILE":"",
        "SECURE_COOKIES":"false","CORS_ORIGINS":"http://localhost:5180","ALLOWED_HOSTS":"testserver,localhost,127.0.0.1",
        "TRUSTED_PROXY_CIDRS":"","SENSOR_API_KEY":"","ADMIN_API_KEY":"","CROWD_TOKENS":"",
        "SERVICE_REPORT_MAX_AGE_SECONDS":"30","SERVICE_CONSENSUS_WINDOW_SECONDS":"120","SERVICE_CONSENSUS_USERS":"3",
        "PYTHONUTF8":"1","PYTHONDONTWRITEBYTECODE":"1"}


def write_report(result, path):
    escape=lambda value:html.escape(str(value))
    rows=[]
    for scenario in result["scenarios"]:
        issues="".join("<li>"+escape(issue)+"</li>" for issue in scenario["failures"])
        rows.append(f'''<article class="scenario" data-status="{scenario['status']}" data-search="{escape(scenario['title'].lower())}">
        <details><summary><span class="badge {scenario['status']}">{scenario['status'].upper()}</span><span><b>{escape(scenario['title'])}</b><small>{escape(scenario['id'])} · {len(scenario['deliveries'])} report deliveries · {len(scenario['checkpoints'])} checkpoints</small></span><span class="expand">+</span></summary>
        <div class="detail"><p>{escape(scenario['explanation'])}</p>{'<ul class="failures">'+issues+'</ul>' if issues else ''}
        <h3>Observed results</h3><div class="table-wrap"><table><thead><tr><th>Virtual second</th><th>Community status</th><th>Accounts agreeing</th><th>Reported extra wait</th><th>Added to journey</th></tr></thead><tbody>'''+"".join(
          f"<tr><td>{escape(c['offset_seconds'])}</td><td>{escape((c['actual_signal'] or {}).get('status','No fresh signal'))}</td><td>{escape((c['actual_signal'] or {}).get('confirmations',0))}</td><td>{escape((c['actual_signal'] or {}).get('delay_seconds','—'))}</td><td>{escape(c.get('actual_route_delay_seconds','—'))} s</td></tr>" for c in scenario["checkpoints"])+'''</tbody></table></div>
        <details class="raw"><summary>Report validation details</summary><pre>'''+escape(json.dumps(scenario["deliveries"],indent=2))+'''</pre></details></div></details></article>''')
    summary=result["summary"]
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FindMyMetro · Crowdsourcing beta results</title><style>
    *{box-sizing:border-box}body{margin:0;background:#edf5f5;color:#143b47;font:15px/1.55 'Segoe UI',sans-serif}main{max-width:1060px;margin:36px auto;padding:0 22px 44px}header{display:flex;justify-content:space-between;gap:20px;align-items:start}h1{font-size:clamp(26px,4vw,39px);line-height:1.2;letter-spacing:-1px;margin:10px 0}h2{font-size:20px;margin:28px 0 13px}h3{font-size:14px;margin:20px 0 10px}p{margin:8px 0;color:#536f7a}.eyebrow{font-size:12px;letter-spacing:2px;font-weight:700;color:#167e78}.synthetic{background:#fff1d1;color:#856426;border:1px solid #ead8a9;border-radius:9px;padding:8px 12px;white-space:nowrap;font-size:12px;font-weight:700}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.card{background:white;border:1px solid #d4e5e5;border-radius:15px;padding:19px}.card strong{display:block;font-size:30px;color:#127b70}.card span{font-size:12px;color:#5c7881}.notice{background:#f9fcfb;border:1px solid #d4e5e5;border-radius:14px;padding:17px 20px;font-size:13px}.notice strong{color:#174c51}.tools{display:flex;gap:10px;margin:18px 0}input,select{font:inherit;border:1px solid #c7dbdc;border-radius:9px;padding:10px 12px;background:white;color:#234853}input{flex:1;min-width:0}.scenario{background:white;border:1px solid #d4e5e5;border-radius:12px;margin:10px 0;overflow:hidden}summary{list-style:none;cursor:pointer;padding:17px;display:flex;align-items:center;gap:15px}summary::-webkit-details-marker{display:none}summary small{display:block;color:#6c818a;font-size:11px;margin-top:4px}summary b{font-size:14px}.badge{border-radius:6px;padding:5px 9px;font-weight:700;font-size:10px;letter-spacing:.7px}.passed{color:#146c50;background:#e1f4e9}.failed{color:#9a3928;background:#fbe6df}.expand{margin-left:auto;color:#6a9097}.detail{border-top:1px solid #e5eeee;padding:17px 20px;font-size:13px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;text-align:left;font-size:12px}th,td{padding:10px;border-bottom:1px solid #e7eeee;white-space:nowrap}th{color:#5b7880;font-size:11px}pre{overflow:auto;background:#f2f7f7;padding:14px;max-height:300px;border-radius:9px;font-size:11px}.raw summary{padding:12px 0;color:#147b7a;font-size:12px}.failures{color:#9a3928}footer{margin-top:28px;color:#6a828c;font-size:12px}.empty{display:none}button:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #35a39a;outline-offset:3px}@media(max-width:650px){main{margin-top:22px;padding:0 15px 30px}header{flex-direction:column}.cards{grid-template-columns:repeat(2,1fr)}.tools{flex-wrap:wrap}.tools input{flex-basis:100%}summary{padding:14px;gap:10px}}
    </style></head><body><main><header><div><span class="eyebrow">FINDMYMETRO / BETA LAB</span><h1>Crowdsourcing, put to the test.</h1><p>Repeatable sample reports through the actual software pipeline.</p></div><span class="synthetic">SYNTHETIC DATA ONLY</span></header><section class="cards">'''
    for value,label in [(f"{summary['passed_scenarios']}/{summary['scenario_count']}","scenarios passed"),(summary["report_deliveries"],"report deliveries"),(summary["participants"],"fictional accounts"),(summary["checkpoints"],"time checkpoints")]:
        page+=f'<div class="card"><strong>{escape(value)}</strong><span>{escape(label)}</span></div>'
    page+='''</section><div class="notice"><strong>What this proves:</strong> functional handling of agreement, location checks, original timestamps, duplicates, expiry and static fallback in these controlled scenarios. <strong>What remains:</strong> real passenger beta collection, actual arrival ground truth, device/cell coverage, browser delivery and representative load tests. Virtual-clock, in-process API execution does not measure network latency or prediction accuracy. The passenger database is never opened.</div><h2>Scenario results</h2><div class="tools"><input id="search" type="search" aria-label="Search scenarios" placeholder="Search a scenario…"><select id="filter" aria-label="Filter results"><option value="all">All results</option><option value="passed">Passed</option><option value="failed">Failed</option></select></div>'''
    page+=''.join(rows)+f'''<footer>Dataset {escape(result['dataset_id'])} · seed {escape(result['seed'])} · network {escape(result['network_version'])}<br>Actual test completion: {escape(result['completed_at'])}. Inputs and test accounts are fictional; station references use the existing catalogue.</footer></main><script>
    function filter(){{const text=document.getElementById('search').value.toLowerCase();const status=document.getElementById('filter').value;document.querySelectorAll('.scenario').forEach(row=>row.hidden=!row.dataset.search.includes(text)||(status!=='all'&&row.dataset.status!==status));}}document.getElementById('search').addEventListener('input',filter);document.getElementById('filter').addEventListener('change',filter);
    </script></body></html>'''
    path.write_text(page,encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,default=ROOT/"data/beta/crowdsourcing/dataset.json")
    parser.add_argument("--scenario",help="Replay one scenario ID for investigation")
    args=parser.parse_args()
    dataset=json.loads(args.dataset.read_text(encoding="utf-8"))
    if dataset.get("data_kind")!="synthetic" or dataset.get("schema_version")!=1:
        raise ValueError("Only the explicitly synthetic beta contract is accepted")
    digest=hashlib.sha256((ROOT/"data/operator-network.json").read_bytes()).hexdigest()
    if dataset["network_sha256"]!=digest:
        raise ValueError("Catalogue changed. Review and regenerate the beta dataset first.")
    cases=[c for c in dataset["scenarios"] if not args.scenario or c["id"]==args.scenario]
    if not cases:raise ValueError("Unknown scenario ID")
    if any(key.startswith("backend.app") for key in sys.modules):
        raise RuntimeError("Run in a fresh Python process so passenger DB configuration is never imported")
    run=ROOT/".local/crowd-beta"/uuid.uuid4().hex
    run.mkdir(parents=True)
    os.environ.update(isolated_environment(run))
    with (run/"migration.log").open("w",encoding="utf-8") as log:
        subprocess.run([sys.executable,"-m","backend.app.bootstrap"],cwd=ROOT,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=45)

    # Imports occur only after the fresh, workspace-contained DB is configured.
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from backend.app import auth, main as api, worker
    from backend.app.config import settings
    from backend.app.db import Session, engine, parse
    from backend.app.models import ContributionAward, Observation, Trip
    from backend.testing.crowd_beta import POLICY
    if settings.app_env!="test" or not str(engine.url).startswith("sqlite:///") or engine.url.database!=str(run/"beta.db").replace('\\','/'):
        raise RuntimeError("Isolated beta database guard failed")
    for key in ["service_report_max_age_seconds","service_consensus_window_seconds","service_consensus_users"]:
        if getattr(settings,key)!=dataset["policy"][key] or dataset["policy"][key]!=POLICY[key]:
            raise ValueError("Beta expectations do not match the active report policy")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    clock=[datetime.fromisoformat(dataset["reference_clock"])]
    clients={};users={};headers={};results=[]
    used={r["participant_id"] for c in cases for r in c["deliveries"]}
    began=time.monotonic()
    origin={"Origin":"http://localhost:5180"}
    def set_time(value):
        clock[0]=value
        # Deterministic pipeline evaluation, not a cache or WebSocket test.
        api.journey_cache.clear();api.snapshot_cache=None
    def total_awards():
        with Session() as session:return session.scalar(select(func.count()).select_from(ContributionAward))
    def route(client,case):
        response=client.get("/api/v1/routes",params=case["journey"])
        response.raise_for_status()
        return response.json()
    with ExitStack() as stack:
        for module in [auth,api]:stack.enter_context(patch.object(module,"utcnow",side_effect=lambda:clock[0]))
        observer=stack.enter_context(TestClient(api.app,client=("192.0.2.254",51000)))
        for index,participant in enumerate(dataset["participants"]):
            if participant["id"] not in used:continue
            client=stack.enter_context(TestClient(api.app,client=(f"198.51.100.{index+1}",51000+index)))
            response=client.post("/api/v1/auth/register",headers=origin,json={
                "username":participant["username"],"display_name":participant["display_name"],"password":secrets.token_urlsafe(24)})
            response.raise_for_status()
            account=response.json()
            clients[participant["id"]]=client;users[participant["id"]]=account["user"]["id"]
            headers[participant["id"]]={**origin,"X-CSRF-Token":account["csrf_token"]}
        for case in cases:
            start=datetime.fromisoformat(case["starts_at"]);set_time(start)
            out={"id":case["id"],"title":case["title"],"explanation":case["explanation"],
                 "failures":[],"deliveries":[],"checkpoints":[]}
            def compare(actual,expected,description):
                if actual!=expected:out["failures"].append(f"{description}: expected {expected!r}; got {actual!r}")
            baseline=route(observer,case)
            if not baseline["routes"]:
                out["failures"].append("Fixture journey has no baseline route; no report-driven ETA comparison is possible.")
                out["status"]="failed";results.append(out)
                print(f"FAILED  {case['id']} (no baseline route)",flush=True)
                continue
            baseline_route=baseline["routes"][0]
            awards_before=total_awards()
            actions=[(d["received_offset_seconds"],0,index,d) for index,d in enumerate(case["deliveries"])]
            actions.extend((c["offset_seconds"],1,index,c) for index,c in enumerate(case["checkpoints"]))
            for seconds,kind,index,item in sorted(actions,key=lambda x:x[:3]):
                set_time(start+timedelta(seconds=seconds))
                if kind==0:
                    participant=item["participant_id"]
                    response=clients[participant].post("/api/v1/reports/batch",headers=headers[participant],json={"reports":[item["report"]]})
                    response.raise_for_status();ack=response.json()["acknowledgements"][0]
                    compare(ack["status"],item["expected_ack"],f"delivery {index+1} acknowledgement")
                    worker.tick(clock[0])
                    with Session() as session:
                        row=session.get(Observation,item["report"]["event_id"])
                        processing=row.status if row else None;reason=row.reason if row else ack.get("reason")
                    compare(processing,item["expected_processing_status"],f"delivery {index+1} processing")
                    compare(reason,item["expected_reason"],f"delivery {index+1} reason")
                    out["deliveries"].append({"participant_id":participant,"event_id":item["report"]["event_id"],
                        "received_offset_seconds":seconds,"acknowledgement":ack["status"],"processing_status":processing,"reason":reason})
                else:
                    status=observer.get("/api/v1/service-status");status.raise_for_status()
                    signals=status.json()["signals"]
                    target=item["target"]
                    found=[signal for signal in signals if all(signal.get(k)==v for k,v in target.items())]
                    actual={k:found[0][k] for k in ["status","confirmations","delay_seconds"]} if found else None
                    compare(actual,item["expected_signal"],f"checkpoint {seconds}s community signal")
                    for signal in signals:
                        compare(bool(set(signal)&{"latitude","longitude","contributor_id","cell_fingerprints","event_ids"}),False,"public signal privacy")
                    current=route(observer,case)
                    matching=next((r for r in current["routes"] if r["id"]==baseline_route["id"]),None)
                    expected_delay=item["expected_route_delay_seconds"]
                    compare(matching is not None,True,f"checkpoint {seconds}s reference route remains available")
                    if matching:
                        compare(matching["delay_seconds"],expected_delay,f"checkpoint {seconds}s journey delay")
                        compare(matching["duration_seconds"]-baseline_route["duration_seconds"],expected_delay,"delay added exactly once")
                        compare(all(s.get("next_arrival") is None for s in matching["source_statuses"]),True,"no invented train identity")
                        compare(set(item.get("required_route_contexts",[])).issubset({s.get("context") for s in matching["steps"]}),True,"configured route contexts")
                    if item.get("expected_rerouting"):
                        compare(current["rerouting"]["status"],item["expected_rerouting"],"alternative route outcome")
                    if "expected_awards" in item:
                        compare(total_awards()-awards_before,item["expected_awards"],"new reward count")
                    out["checkpoints"].append({"offset_seconds":seconds,"expected_signal":item["expected_signal"],"actual_signal":actual,
                        "actual_route_delay_seconds":matching["delay_seconds"] if matching else None,
                        "reference_route_id":baseline_route["id"],"rerouting_status":current["rerouting"]["status"]})
            for participant in set(d["participant_id"] for d in case["deliveries"]):
                response=clients[participant].get("/api/v1/reports/mine",params={"limit_count":100});response.raise_for_status()
                history=response.json()["reports"]
                with Session() as session:
                    own=set(session.scalars(select(Observation.event_id).where(Observation.payload["contributor_id"].as_string()==users[participant])))
                compare(all(r["event_id"] in own and not set(r)&{"latitude","longitude","cell_fingerprints","contributor_id"} for r in history),True,"private report history ownership and location redaction")
            with Session() as session:
                compare(session.scalar(select(func.count()).select_from(Trip)),0,"no reports create named trains")
            out["status"]="failed" if out["failures"] else "passed"
            results.append(out)
            print(f"{out['status'].upper():6}  {case['id']} ({len(case['deliveries'])} deliveries)",flush=True)
        engine.dispose()
    completed=datetime.now(timezone.utc).isoformat()
    result={"dataset_id":dataset["dataset_id"],"data_kind":"synthetic","seed":dataset["seed"],"network_version":dataset["network_version"],
            "completed_at":completed,"execution_kind":"virtual-clock in-process HTTP API, real auth/SQLAlchemy/worker/routing; isolated SQLite",
            "passenger_database_opened":False,"hardware_used":False,"load_or_accuracy_measurement":False,
            "summary":{"scenario_count":len(results),"passed_scenarios":sum(r["status"]=="passed" for r in results),
                "report_deliveries":sum(len(c["deliveries"]) for c in cases),"participants":len(used),
                "checkpoints":sum(len(c["checkpoints"]) for c in cases),"runner_wall_seconds":round(time.monotonic()-began,2)},"scenarios":results}
    (run/"results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    write_report(result,run/"report.html")
    artifact=ROOT/"artifacts/crowdsourcing-beta";artifact.mkdir(parents=True,exist_ok=True)
    (artifact/"latest-results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    write_report(result,artifact/"latest-report.html")
    print(json.dumps({"summary":result["summary"],"report":str(artifact/"latest-report.html"),"run":str(run)},indent=2))
    return 1 if result["summary"]["passed_scenarios"]!=len(results) else 0


if __name__=="__main__":sys.exit(main())
