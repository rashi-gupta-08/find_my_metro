"""100 simulated accounts, actual loopback HTTP/WebSockets and worker; isolated DB.

No browser rendering, physical phones, external users or passenger data are used.
Account provisioning is fixture setup outside the measured reporting workload.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
HOST='127.0.0.1'
PORT=8020
ORIGIN='http://localhost:5181'


def summary(values):
    values=sorted(values)
    if not values:return {'samples':0,'p50_ms':None,'p95_ms':None,'max_ms':None}
    def quantile(q):
        i=(len(values)-1)*q;lo=int(i);hi=min(len(values)-1,lo+1)
        return values[lo]*(hi-i)+values[hi]*(i-lo) if hi!=lo else values[lo]
    return {'samples':len(values),'p50_ms':round(quantile(.5),2),'p95_ms':round(quantile(.95),2),'max_ms':round(max(values),2)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/paper-100-users')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    with socket.socket() as probe:
        if probe.connect_ex((HOST,PORT))==0:raise RuntimeError('Test port 8020 is in use; existing services will not be stopped')
    run=ROOT/'.local/paper-100-users'/uuid.uuid4().hex
    run.mkdir(parents=True)
    if any(k.startswith('backend.app') for k in sys.modules):raise RuntimeError('Use a fresh Python process')
    (run/'test.env').write_text('# Private isolated workload environment\n',encoding='utf-8')
    environment={**os.environ,'METRO_ENV_FILE':str(run/'test.env'),'APP_ENV':'test',
        'DATABASE_URL':'sqlite:///'+(run/'workload.db').as_posix(),'MIGRATION_DATABASE_URL':'',
        'NETWORK_FILE':str(ROOT/'data/operator-network.json'),'AUTH_SECRET':secrets.token_hex(32),
        'SIMULATION_ENABLED':'false','HARDWARE_ENABLED':'false','MQTT_ENABLED':'false',
        'CELL_MAP_FILE':'','PREDICTION_MODEL_FILE':'','SENSOR_API_KEY':'','ADMIN_API_KEY':'','CROWD_TOKENS':'',
        'CORS_ORIGINS':ORIGIN,'ALLOWED_HOSTS':'127.0.0.1,localhost','TRUSTED_PROXY_CIDRS':'',
        'SECURE_COOKIES':'false','SERVICE_REPORT_MAX_AGE_SECONDS':'30','SERVICE_CONSENSUS_USERS':'3',
        'SERVICE_CONSENSUS_WINDOW_SECONDS':'120','MAX_WS_CONNECTIONS':'200',
        'PYTHONUTF8':'1','PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1'}
    os.environ.update(environment)
    with (run/'migration.log').open('w',encoding='utf-8') as log:
        subprocess.run([sys.executable,'-m','backend.app.bootstrap'],cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
    from backend.app.auth import COOKIE,hash_password,issue_session
    from backend.app.db import Session,engine,iso,parse,transaction,utcnow
    from backend.app.models import ContributionAward,Observation,User
    from fastapi import Response
    from sqlalchemy import func,select
    import httpx
    import websockets
    if engine.url.database!=(run/'workload.db').as_posix():raise RuntimeError('Wrong database')
    accounts=[]
    # Login/registration throughput is deliberately outside this workload.
    # Each fixture gets a revocable session through the actual session issuer.
    password_hash=hash_password(secrets.token_urlsafe(32))
    with transaction() as session:
        for index in range(100):
            user=User(id=str(uuid.uuid4()),username=f'paper_user_{index:03}',display_name=f'Simulated user {index+1}',
                password_hash=password_hash,role='passenger',disabled=False,verified_contributor=False,created_at=iso(utcnow()))
            session.add(user);session.flush();response=Response()
            auth=issue_session(session,user,response)
            token=response.headers['set-cookie'].split(';')[0].split('=',1)[1]
            accounts.append({'index':index,'id':user.id,'cookie':token,'csrf':auth['csrf_token']})
    engine.dispose()
    processes=[];logs=[]
    try:
        for name,command in [('api',[sys.executable,'-m','uvicorn','backend.app.main:app','--host',HOST,'--port',str(PORT),'--no-proxy-headers','--no-access-log']),
                             ('worker',[sys.executable,'-m','backend.app.worker'])]:
            log=(run/(name+'.log')).open('w',encoding='utf-8');logs.append(log)
            processes.append(subprocess.Popen(command,cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        base=f'http://{HOST}:{PORT}'
        with httpx.Client(timeout=2) as client:
            for _ in range(40):
                try:
                    if client.get(base+'/api/v1/health').json()['ready']:break
                except (httpx.HTTPError,KeyError,ValueError):pass
                if any(p.poll() is not None for p in processes):raise RuntimeError('Test service stopped; inspect isolated logs')
                time.sleep(.5)
            else:raise RuntimeError('Test services did not become ready')
        catalogue=json.loads((ROOT/'data/operator-network.json').read_text(encoding='utf-8'))
        smap={s['id']:s for s in catalogue['stations']}
        line=next(l for l in catalogue['lines'] if l['id']=='nmrc-aqua')
        stations=[smap[sid] for sid in line['station_ids'][:20]]
        started=time.monotonic()
        async def workload():
            clients=[httpx.AsyncClient(base_url=base,timeout=45,cookies={COOKIE:a['cookie']},headers={'Origin':ORIGIN,'X-CSRF-Token':a['csrf']}) for a in accounts]
            sockets=[];payloads=[];requests=[];updates=[];rounds=[];failures=[]
            ready_at=time.monotonic()
            try:
                sockets=list(await asyncio.gather(*[websockets.connect(f'ws://{HOST}:{PORT}/ws/eta/{stations[i//5]["id"]}',origin=ORIGIN,open_timeout=45,max_size=2**20) for i in range(100)]))
                initial=await asyncio.gather(*[asyncio.wait_for(ws.recv(),45) for ws in sockets])
                if any(json.loads(frame)['type']!='snapshot' for frame in initial):raise RuntimeError('Missing initial snapshot')
                connection_ms=(time.monotonic()-ready_at)*1000
                with (output/'load-submitted-reports.jsonl').open('w',encoding='utf-8') as raw:
                    for wave in range(5):
                        stamp=utcnow();deadline=time.monotonic()+45
                        target_delay=180+wave*120
                        event_prefix=f'load-{wave}-'
                        bodies=[]
                        for i in range(100):
                            station=stations[i//5];slot=i%5
                            observed=stamp-timedelta(seconds=45 if slot==3 else 0)
                            report={'event_id':event_prefix+str(i).zfill(3),'station_id':station['id'],'line_id':'nmrc-aqua','direction':'outbound',
                                'observed_at':iso(observed),'event_type':'delayed','latitude':station['lat']+(.02 if slot==4 else 0),
                                'longitude':station['lng'],'accuracy_m':10,'delay_seconds':target_delay+([-15,0,15,0,0][slot]),
                                'note':'SYNTHETIC 100-user load experiment; no passenger observation'}
                            bodies.append(report)
                            raw.write(json.dumps({'wave':wave+1,'simulated_user':i+1,'expected_processing_status':'historical' if slot==3 else 'rejected' if slot==4 else 'validated','report':report})+'\n')
                        gate=asyncio.Event()
                        async def submit(i):
                            await gate.wait();before=time.monotonic()
                            try:
                                response=await clients[i].post('/api/v1/reports/batch',json={'reports':[bodies[i]]})
                                elapsed=(time.monotonic()-before)*1000
                                ack=response.json().get('acknowledgements',[{}])[0]
                                return {'wave':wave+1,'user':i+1,'event_id':bodies[i]['event_id'],'status':response.status_code,'ack':ack.get('status'),'elapsed_ms':round(elapsed,3)}
                            except Exception as error:
                                return {'wave':wave+1,'user':i+1,'event_id':bodies[i]['event_id'],'status':None,'error':type(error).__name__,'elapsed_ms':round((time.monotonic()-before)*1000,3)}
                        async def receive(i):
                            while time.monotonic()<deadline:
                                frame=json.loads(await asyncio.wait_for(sockets[i].recv(),max(.1,deadline-time.monotonic())))
                                signal=next((s for s in frame.get('community_signals',[]) if s['station_id']==stations[i//5]['id'] and s['status']=='confirmed' and s.get('delay_seconds')==target_delay and parse(s['last_observed_at'])>=stamp),None)
                                if signal:
                                    return {'wave':wave+1,'client':i+1,'observation_to_ws_receipt_ms':round((utcnow()-stamp).total_seconds()*1000,3),
                                            'quorum_to_ws_receipt_ms':round((utcnow()-parse(signal['quorum_available_at'])).total_seconds()*1000,3),
                                            'confirmations':signal['confirmations']}
                            raise TimeoutError('No fresh confirmed signal')
                        tasks=[asyncio.create_task(submit(i)) for i in range(100)]
                        reads=[asyncio.create_task(receive(i)) for i in range(100)]
                        wave_started=time.monotonic();gate.set()
                        sent=await asyncio.gather(*tasks);requests.extend(sent)
                        incoming=await asyncio.gather(*reads,return_exceptions=True)
                        for i,item in enumerate(incoming):
                            if isinstance(item,Exception):failures.append({'wave':wave+1,'client':i+1,'reason':type(item).__name__})
                            else:updates.append(item)
                        rounds.append({'wave':wave+1,'released_clients':100,'acknowledged':sum(r.get('status')==202 and r.get('ack')=='queued' for r in sent),
                            'ws_confirmations_received':sum(not isinstance(i,Exception) for i in incoming),'wall_seconds':round(time.monotonic()-wave_started,3)})
                        print(json.dumps(rounds[-1]),flush=True)
                        last_stamp=stamp
                # A few deliberate retries test durable event IDs without
                # increasing the advertised 500 unique observations.
                duplicate=[]
                for i in range(3):
                    response=await clients[i].post('/api/v1/reports/batch',json={'reports':[bodies[i]]})
                    duplicate.append(response.json()['acknowledgements'][0]['status'])
                expiry_wait=max(0,(last_stamp+timedelta(seconds=31)-utcnow()).total_seconds())
                if expiry_wait:await asyncio.sleep(expiry_wait)
                expiry=await clients[0].get('/api/v1/service-status')
                remaining=[s for s in expiry.json()['signals'] if s['line_id']=='nmrc-aqua']
                return {'requests':requests,'updates':updates,'rounds':rounds,'failures':failures,'duplicates':duplicate,
                    'signals_after_expiry':len(remaining),'ws_connections':len(sockets),'connect_all_clients_ms':round(connection_ms,2)}
            finally:
                await asyncio.gather(*[ws.close() for ws in sockets],return_exceptions=True)
                await asyncio.gather(*[c.aclose() for c in clients],return_exceptions=True)
        measured=asyncio.run(workload())
        with Session() as session:
            rows=session.scalars(select(Observation).where(Observation.source=='surface_crowd')).all()
            outcomes=Counter(r.status for r in rows)
            processing=[(parse(r.validated_at)-parse(r.received_at)).total_seconds()*1000 for r in rows if r.validated_at]
            awards=session.scalar(select(func.count()).select_from(ContributionAward))
        result={'data_kind':'synthetic','simulated_accounts':100,'concurrent_http_clients_per_wave':100,'concurrent_websocket_clients':100,
            'waves':5,'unique_reports':len(rows),'expected_processing':{'validated':300,'historical':100,'rejected':100},'actual_processing':dict(outcomes),
            'successful_acknowledgements':sum(r.get('status')==202 and r.get('ack')=='queued' for r in measured['requests']),
            'http_errors':sum(r.get('status')!=202 for r in measured['requests']),
            'http_ack_latency':summary([r['elapsed_ms'] for r in measured['requests'] if r.get('status')==202]),
            'receipt_to_validation_latency':summary(processing),
            'observation_to_websocket_latency':summary([u['observation_to_ws_receipt_ms'] for u in measured['updates']]),
            'quorum_to_websocket_latency':summary([u['quorum_to_ws_receipt_ms'] for u in measured['updates']]),
            'contribution_awards':awards,'limits':{'service_report_ttl_seconds':30,'consensus_accounts':3,'public_api_limits_unchanged':True},
            'backend_database':'isolated SQLite WAL','execution':'actual TCP loopback API and worker subprocesses; asynchronous Python clients',
            'physical_users':0,'browser_render_latency_measured':False,'login_and_registration_load_tested':False,'model_used_in_api':'static timing plus community delay overlay',
            'passenger_database_opened':False,'completed_at':datetime.now(timezone.utc).isoformat(),'wall_seconds':round(time.monotonic()-started,2),
            'machine':{'os':platform.platform(),'python':platform.python_version(),'logical_cpus':os.cpu_count()},
            **measured}
        result['acceptance']={'processing_matches_injected_labels':dict(outcomes)==result['expected_processing'],
            'all_reports_acknowledged':result['successful_acknowledgements']==500,
            'all_updates_received':len(measured['updates'])==500 and not measured['failures'],
            'duplicate_retries_idempotent':measured['duplicates']==['duplicate']*3,
            'evidence_expires':measured['signals_after_expiry']==0}
        (output/'load-results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in {'requests','updates','rounds'}},indent=2),flush=True)
        return 0 if all(result['acceptance'].values()) else 1
    finally:
        for proc in processes:
            if proc.poll() is None:proc.terminate()
        for proc in processes:
            try:proc.wait(timeout=12)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        for log in logs:log.close()
        engine.dispose()


if __name__=='__main__':sys.exit(main())
