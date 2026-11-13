"""Combined frozen operator timings + 100 simulated crowd accounts over TCP.

Creates and removes its own PostgreSQL database. Never opens passenger tables.
Four scripted journey queries represent progress; no physical train is tracked.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOST, PORT, ORIGIN = '127.0.0.1', 8021, 'http://localhost:5182'
COHORTS = ['DMRC underground to surface', 'DMRC surface to underground', 'NMRC outbound', 'NMRC inbound']
# (origin, destination, ordered line, direction, expected geographic context)
INITIAL = [('dmrc-rck','dmrc-yb','dmrc-ln3','outbound','underground'),
           ('dmrc-idpt','dmrc-rck','dmrc-ln3','inbound','surface'),
           ('nmrc-1','nmrc-4','nmrc-aqua','outbound','surface'),
           ('nmrc-4','nmrc-1','nmrc-aqua','inbound','surface')]
BOUNDARY = [('dmrc-mdhs','dmrc-yb','dmrc-ln3','outbound','transition'),
            ('dmrc-ptmd','dmrc-rck','dmrc-ln3','inbound','transition'), *INITIAL[2:]]
AFTER = [('dmrc-ptmd','dmrc-yb','dmrc-ln3','outbound','surface'),
         ('dmrc-brkr','dmrc-rck','dmrc-ln3','inbound','underground'), *INITIAL[2:]]
PHASES = [dict(name='initial_static', routes=INITIAL, delay=0, qualified=[False]*4),
          dict(name='boundary_agreement', routes=BOUNDARY, delay=360, qualified=[True]*4),
          dict(name='surface_and_underground', routes=AFTER, delay=480, qualified=[True,False,True,True]),
          dict(name='evidence_expired', routes=AFTER, delay=0, qualified=[False]*4, no_submission=True),
          dict(name='fresh_evidence_recovery', routes=AFTER, delay=600, qualified=[True,False,True,True])]


def csv_write(path, rows):
    from audit_operator_baseline import write_csv
    write_csv(path, rows)


def percentile(values):
    values = sorted(values)
    def q(f):
        if not values: return None
        index = (len(values)-1)*f
        lo, hi = int(index), min(int(index)+1, len(values)-1)
        return round(values[lo] + (values[hi]-values[lo])*(index-lo), 2)
    return {'n':len(values), 'p50_ms':q(.5), 'p95_ms':q(.95), 'max_ms':round(max(values),2) if values else None}


def port_open(port):
    with socket.socket() as probe:
        probe.settimeout(.5)
        return probe.connect_ex((HOST, port)) == 0


def run(output):
    import psycopg
    from psycopg import sql
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url
    from audit_operator_baseline import audit
    output.mkdir(parents=True, exist_ok=True)
    provenance = audit(output)
    if provenance['source_mismatches']: raise RuntimeError('Operator source mismatch')
    if port_open(PORT): raise RuntimeError('Test port 8021 is occupied; no existing service will be stopped')
    run_dir = ROOT / '.local/operator-crowd-100' / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    pg = json.loads((ROOT/'.local/database.json').read_text())
    if not port_open(pg['port']):
        with (run_dir/'postgres-start.log').open('w') as log:
            subprocess.run([str(Path(pg['bin'])/'pg_ctl.exe'), '-D', pg['data'], '-l', str(run_dir/'postgres.log'),
                '-o', f'-p {int(pg["port"])} -h 127.0.0.1', '-w', '-t', '20', 'start'], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=25,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    private = dotenv_values(ROOT/'.env')
    owner, passenger = make_url(private['MIGRATION_DATABASE_URL']), make_url(private['DATABASE_URL'])
    database = 'metro_experiment_'+uuid.uuid4().hex[:16]
    assert database.startswith('metro_experiment_') and database not in {owner.database, passenger.database, 'postgres'}
    admin = psycopg.connect(host=owner.host, port=owner.port, user='metro_admin', password=private['POSTGRES_PASSWORD'],
                           dbname='postgres', autocommit=True, connect_timeout=10)
    processes, logs, created = [], [], False
    engine = None
    result = None
    try:
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database), sql.Identifier(owner.username)))
        created = True
        (run_dir/'test.env').write_text('# Private isolated experiment\n', encoding='utf-8')
        env = {**os.environ, 'METRO_ENV_FILE':str(run_dir/'test.env'), 'APP_ENV':'test',
            'DATABASE_URL':owner.set(database=database).render_as_string(hide_password=False), 'MIGRATION_DATABASE_URL':'',
            'NETWORK_FILE':str(ROOT/'data/operator-network.json'), 'AUTH_SECRET':secrets.token_hex(32),
            'SIMULATION_ENABLED':'false', 'HARDWARE_ENABLED':'false', 'MQTT_ENABLED':'false',
            'CELL_MAP_FILE':'', 'PREDICTION_MODEL_FILE':'', 'SENSOR_API_KEY':'', 'ADMIN_API_KEY':'', 'CROWD_TOKENS':'',
            'CORS_ORIGINS':ORIGIN, 'ALLOWED_HOSTS':'localhost,127.0.0.1', 'TRUSTED_PROXY_CIDRS':'',
            'SECURE_COOKIES':'false', 'SERVICE_REPORT_MAX_AGE_SECONDS':'30', 'SERVICE_CONSENSUS_USERS':'3',
            'SERVICE_CONSENSUS_WINDOW_SECONDS':'120', 'MAX_WS_CONNECTIONS':'200',
            'PYTHONUTF8':'1', 'PYTHONUNBUFFERED':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
        os.environ.update(env)
        with (run_dir/'migration.log').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable,'-m','backend.app.bootstrap'], cwd=ROOT, env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=45)
        from backend.app.auth import COOKIE, hash_password, issue_session
        from backend.app.db import Session, engine, iso, parse, transaction, utcnow
        from backend.app.models import Observation, Trip, User
        from fastapi import Response
        from sqlalchemy import func, select
        import httpx
        import websockets
        if engine.url.database != database: raise RuntimeError('Isolation check failed')
        catalogue = json.loads((ROOT/'data/operator-network.json').read_text())
        smap = {s['id']:s for s in catalogue['stations']}
        lmap = {l['id']:l for l in catalogue['lines']}
        accounts = []
        password_hash = hash_password(secrets.token_urlsafe(32))
        with transaction() as session:
            for index in range(100):
                user = User(id=str(uuid.uuid4()), username=f'operator_test_{index:03}', display_name=f'Simulated participant {index+1}',
                    password_hash=password_hash, role='passenger', disabled=False, verified_contributor=False, created_at=iso(utcnow()))
                session.add(user); session.flush()
                response = Response(); auth = issue_session(session, user, response)
                accounts.append({'index':index, 'id':user.id, 'cohort':index//25, 'slot':index%5,
                    'cookie':response.headers['set-cookie'].split(';')[0].split('=',1)[1], 'csrf':auth['csrf_token']})
        csv_write(output/'simulated-participants.csv', [{'participant':i+1,'cohort':COHORTS[i//25],
            'report_role': ['nearby_agreement_low','nearby_agreement_median','nearby_agreement_high','stale_upload','outside_station'][i%5],
            'data_kind':'synthetic','physical_person_recruited':False} for i in range(100)])
        engine.dispose()
        for name, command in [('api',[sys.executable,'-m','uvicorn','backend.app.main:app','--host',HOST,'--port',str(PORT),'--no-proxy-headers','--no-access-log']),
                              ('worker',[sys.executable,'-m','backend.app.worker'])]:
            log = (run_dir/(name+'.log')).open('w', encoding='utf-8'); logs.append(log)
            processes.append(subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        base = f'http://{HOST}:{PORT}'
        with httpx.Client(timeout=3) as client:
            for _ in range(60):
                try:
                    if client.get(base+'/api/v1/health').json()['ready']: break
                except (httpx.HTTPError,ValueError,KeyError): pass
                if any(p.poll() is not None for p in processes): raise RuntimeError('Test child stopped; see private run logs')
                time.sleep(.5)
            else: raise RuntimeError('Test services not ready')
        started = time.monotonic()

        def reference(frame, spec):
            matches = [r for r in frame['routes'] if r['steps'] and all(s['kind']=='ride' and s['line_id']==spec[2] for s in r['steps'])]
            return min(matches, key=lambda r:r['duration_seconds']) if matches else None

        def independent_baseline(route):
            total = 0
            for step in route['steps']:
                line = lmap[step['line_id']]
                a, b = line['station_ids'].index(step['from_station_id']), line['station_ids'].index(step['to_station_id'])
                if abs(a-b)!=1: raise RuntimeError('Non-adjacent ride')
                total += line['segments'][min(a,b)]['seconds']
            return total

        async def workload():
            clients = [httpx.AsyncClient(base_url=base,timeout=45,cookies={COOKIE:a['cookie']},
                headers={'Origin':ORIGIN,'X-CSRF-Token':a['csrf']}) for a in accounts]
            sockets, submissions, acks, observations, frames, failures, phase_summaries = [], [], [], [], [], [], []
            last_payloads, last_stamp, last_phase = None, None, None
            duplicate_checks = []
            try:
                for number, phase in enumerate(PHASES):
                    spec_list = phase['routes']
                    if number in [0,1,2]:
                        if sockets:
                            await asyncio.gather(*[ws.close() for ws in sockets], return_exceptions=True)
                        # Warm only four public routes; do not relax the shared-IP GET limit.
                        for spec in spec_list:
                            warm = await clients[0].get('/api/v1/routes', params={'origin':spec[0], 'destination':spec[1]})
                            if warm.status_code != 200 or not reference(warm.json(), spec):
                                raise RuntimeError('Fixture route unavailable')
                        sockets = list(await asyncio.gather(*[websockets.connect(
                            f'ws://{HOST}:{PORT}/ws/journeys?origin={spec_list[i//25][0]}&destination={spec_list[i//25][1]}',
                            origin=ORIGIN,open_timeout=45,max_size=4*2**20) for i in range(100)]))
                        await asyncio.gather(*[asyncio.wait_for(ws.recv(),45) for ws in sockets])
                    if phase.get('no_submission'):
                        # A real wall-clock expiry test; no patched clock, cache purge or injected tick.
                        wait = max(0, (last_stamp+timedelta(seconds=31)-utcnow()).total_seconds())
                        if wait: await asyncio.sleep(wait)
                        stamp = utcnow(); released = time.monotonic()
                    else:
                        stamp = utcnow(); gate = asyncio.Event(); bodies = []
                        for i, account in enumerate(accounts):
                            cohort, slot = account['cohort'], account['slot']
                            spec = spec_list[cohort]; station = smap[spec[0]]
                            qualified = phase['qualified'][cohort]
                            report = {'event_id':f'combined-{number}-{i:03}', 'station_id':spec[0], 'line_id':spec[2],
                                'direction':spec[3], 'event_type':'delayed',
                                'observed_at':iso(stamp-timedelta(seconds=45 if qualified and slot==3 else 0)),
                                'delay_seconds':max(0,phase['delay']+[-15,0,15,0,0][slot]),
                                'note':'SYNTHETIC combined operator-baseline experiment; not a passenger observation'}
                            if qualified:
                                report.update(latitude=station['lat']+(.02 if slot==4 else 0), longitude=station['lng'], accuracy_m=10)
                            label = 'rejected' if not qualified or slot==4 else 'historical' if slot==3 else 'validated'
                            submissions.append({'phase':phase['name'], 'phase_index':number, 'participant':i+1,
                                'expected_processing':label, 'cohort':COHORTS[cohort], 'data_kind':'synthetic', 'report':report})
                            bodies.append(report)
                        async def submit(i):
                            await gate.wait(); before = time.monotonic()
                            transport_errors=[]
                            # Retry transport failures with the SAME durable event
                            # ID. Keep all attempts; do not retry HTTP errors.
                            for attempt in range(1,4):
                                try:
                                    response = await clients[i].post('/api/v1/reports/batch', json={'reports':[bodies[i]]})
                                    ack = response.json().get('acknowledgements',[{}])[0]
                                    return {'phase':phase['name'],'participant':i+1,'event_id':bodies[i]['event_id'],
                                        'http_status':response.status_code,'ack':ack.get('status'),'attempts':attempt,
                                        'transport_errors':transport_errors,'elapsed_ms':round((time.monotonic()-before)*1000,3)}
                                except httpx.TransportError as error:
                                    transport_errors.append(type(error).__name__)
                                    if attempt<3:await asyncio.sleep(.2*attempt)
                            return {'phase':phase['name'],'participant':i+1,'event_id':bodies[i]['event_id'],
                                'http_status':None,'ack':transport_errors[-1],'attempts':3,'transport_errors':transport_errors,
                                'elapsed_ms':round((time.monotonic()-before)*1000,3)}
                        tasks = [asyncio.create_task(submit(i)) for i in range(100)]
                        released = time.monotonic(); gate.set()
                        sent = await asyncio.gather(*tasks); acks.extend(sent)
                        last_payloads, last_stamp, last_phase = bodies, stamp, number
                        # Missing-location phases must actually finish validation;
                        # otherwise a static snapshot alone would be a trivial pass.
                        deadline = time.monotonic()+35
                        while time.monotonic()<deadline:
                            with Session() as session:
                                pending = session.scalar(select(func.count()).select_from(Observation).where(
                                    Observation.event_id.in_([r['event_id'] for r in bodies]), Observation.status=='queued'))
                                count = session.scalar(select(func.count()).select_from(Observation).where(
                                    Observation.event_id.in_([r['event_id'] for r in bodies])))
                            if pending == 0 and count==100: break
                            await asyncio.sleep(.15)
                        else: failures.append({'phase':phase['name'],'reason':'worker_processing_timeout'})
                    deadline = time.monotonic()+30
                    async def receive(i):
                        spec = spec_list[i//25]; expected_source = 'crowd' if phase['qualified'][i//25] else 'schedule'
                        expected_delay = phase['delay'] if expected_source=='crowd' else 0
                        last_reason = 'no_snapshot'
                        while time.monotonic()<deadline:
                            frame = json.loads(await asyncio.wait_for(sockets[i].recv(), max(.1,deadline-time.monotonic())))
                            route = reference(frame,spec)
                            if not route: last_reason='missing_reference_route'; continue
                            status = route['source_statuses'][0]
                            # Discard buffered frames from before this phase and earlier quorums.
                            if parse(frame['generated_at']) < stamp: continue
                            if status['source']!=expected_source or route['delay_seconds']!=expected_delay:
                                last_reason=f'source_or_delay_{status["source"]}_{route["delay_seconds"]}'; continue
                            if expected_source=='crowd' and (not status['last_observed_at'] or parse(status['last_observed_at'])<stamp): continue
                            baseline = independent_baseline(route)
                            record = {'phase':phase['name'],'phase_index':number,'participant':i+1,'cohort':COHORTS[i//25],
                                'origin':spec[0],'destination':spec[1],'line_id':spec[2],'direction':spec[3],
                                'expected_context':spec[4],'actual_context':status['planned_context'],
                                'expected_source':expected_source,'actual_source':status['source'],'scope':status['scope'],
                                'baseline_seconds':baseline,'expected_delay_seconds':expected_delay,'actual_delay_seconds':route['delay_seconds'],
                                'expected_journey_seconds':baseline+expected_delay,'actual_journey_seconds':route['duration_seconds'],
                                'confirmations':status.get('confirmations',0), 'model_version':status['model_version'],
                                'snapshot_version':frame['snapshot_version'],'snapshot_at':frame['generated_at'],'received_at':iso(utcnow()),
                                'phase_to_matching_ws_ms':round((time.monotonic()-released)*1000,3),
                                'observed_to_matching_ws_ms':round((utcnow()-stamp).total_seconds()*1000,3) if expected_source=='crowd' else None,
                                'next_train_claimed':status['next_arrival'] is not None,
                                'passed':status['planned_context']==spec[4] and route['duration_seconds']==baseline+expected_delay and
                                    status['scope']==('station_service' if expected_source=='crowd' else 'static') and status['next_arrival'] is None}
                            return record, {'phase':phase['name'],'cohort':COHORTS[i//25],'participant':i+1,'snapshot':frame}
                        raise TimeoutError(last_reason)
                    incoming = await asyncio.gather(*[receive(i) for i in range(100)], return_exceptions=True)
                    for i, value in enumerate(incoming):
                        if isinstance(value,BaseException): failures.append({'phase':phase['name'],'participant':i+1,'reason':str(value) or type(value).__name__})
                        else:
                            observations.append(value[0])
                            if i%25==0: frames.append(value[1])
                    phase_summaries.append({'phase':phase['name'],'released_clients':100,
                        'matching_journey_updates':sum(not isinstance(v,BaseException) for v in incoming),
                        'wall_seconds':round(time.monotonic()-released,3)})
                    print(json.dumps(phase_summaries[-1]),flush=True)
                for i in range(3):
                    response = await clients[i].post('/api/v1/reports/batch',json={'reports':[last_payloads[i]]})
                    duplicate_checks.append(response.json()['acknowledgements'][0]['status'])
                # Read REST once for each route after WS; check identical route content
                # at a common version, permitting newer generated timestamps.
                rest_checks = []
                for spec in AFTER:
                    response = await clients[0].get('/api/v1/routes',params={'origin':spec[0],'destination':spec[1]})
                    r = reference(response.json(),spec) if response.status_code==200 else None
                    rest_checks.append(bool(r and r['duration_seconds']==independent_baseline(r)+r['delay_seconds']))
                return dict(submissions=submissions,acks=acks,observations=observations,frames=frames,failures=failures,
                    phase_summaries=phase_summaries,duplicate_checks=duplicate_checks,rest_checks=rest_checks)
            finally:
                await asyncio.gather(*[ws.close() for ws in sockets],return_exceptions=True)
                await asyncio.gather(*[c.aclose() for c in clients],return_exceptions=True)
        measured = asyncio.run(workload())
        with Session() as session:
            stored = session.scalars(select(Observation).where(Observation.source=='surface_crowd')).all()
            processing = {r.event_id:r for r in stored}
            outcomes = Counter(r.status for r in stored)
            train_rows = session.scalar(select(func.count()).select_from(Trip))
            for item in measured['submissions']:
                row = processing.get(item['report']['event_id'])
                item.update(actual_processing=row.status if row else 'missing', reason=row.reason if row else 'missing',
                    received_at=row.received_at if row else None, validated_at=row.validated_at if row else None)
        raw = measured.pop('submissions'); frames = measured.pop('frames')
        with (output/'crowd-reports.jsonl').open('w',encoding='utf-8') as f:
            for item in raw: f.write(json.dumps(item)+'\n')
        csv_write(output/'crowd-reports.csv',[{**{k:v for k,v in item.items() if k!='report'},**item['report']} for item in raw])
        csv_write(output/'journey-context-results.csv', measured['observations'])
        csv_write(output/'http-acknowledgements.csv', measured['acks'])
        with (output/'journey-snapshots.jsonl').open('w',encoding='utf-8') as f:
            for frame in frames: f.write(json.dumps(frame)+'\n')
        observation_latencies = [r['observed_to_matching_ws_ms'] for r in measured['observations'] if r['observed_to_matching_ws_ms'] is not None]
        result = {'completed_at':iso(utcnow()),'data_kind':'frozen_operator_baseline_with_synthetic_crowd_evidence',
            'physical_users':0,'simulated_accounts':100,'concurrent_http_clients_per_wave':100,'concurrent_journey_ws_clients':100,
            'unique_report_deliveries':len(raw),'http_requests_including_duplicate_retries':sum(r['attempts'] for r in measured['acks'])+3,
            'transport_errors_before_retry':sum(len(r['transport_errors']) for r in measured['acks']),
            'report_retry_policy':'At most 3 attempts after transport errors only, same event ID, 0.2/0.4 second backoff; no retry of HTTP errors.',
            'processing_outcomes':dict(outcomes),'expected_processing_outcomes':dict(Counter(r['expected_processing'] for r in raw)),
            'distinct_cohort_phase_conditions':20,'journey_updates_checked':len(measured['observations']),
            'expected_journey_updates':500,'passed_journey_updates':sum(r['passed'] for r in measured['observations']),
            'static_updates':sum(r['actual_source']=='schedule' for r in measured['observations']),
            'crowd_updates':sum(r['actual_source']=='crowd' for r in measured['observations']),
            'http_ack_latency':percentile([r['elapsed_ms'] for r in measured['acks'] if r['http_status']==202]),
            'receipt_to_processing_latency':percentile([(parse(r.validated_at)-parse(r.received_at)).total_seconds()*1000 for r in stored if r.validated_at]),
            'observation_to_matching_journey_ws_latency':percentile(observation_latencies),
            'oracle_journey_arithmetic_max_absolute_error_seconds':max((abs(r['actual_journey_seconds']-r['expected_journey_seconds']) for r in measured['observations']),default=None),
            'database':'fresh isolated PostgreSQL 16 database; migrations and application owner account',
            'passenger_database_opened':False,'own_test_database_removed':False,
            'rate_limits_unchanged':True,'report_ttl_seconds':30,'minimum_independent_accounts':3,
            'field_train_ground_truth_available':False,'individual_train_tracking_tested':False,'prophet_random_forest_used':False,
            'context_progression':'Scripted origin changes across configured Blue Line segments in both directions; NMRC remains surface.',
            'underground_policy':'Use static timing when no verified phone location evidence is available; valid crowd evidence is permitted by existing code in any zone.',
            'transition_policy':'Geographic boundary source preference and qualified station-delay overlay; no identified-train handover or dead reckoning exercised.',
            'fixture_provisioning':'100 accounts and revocable sessions issued before load; registration/login throughput excluded.',
            'latency_scope':'Client read timestamps include a per-wave worker-completion barrier; not browser render or mobile radio latency.',
            'machine':{'os':platform.platform(),'logical_cpus':os.cpu_count(),'python':platform.python_version()},
            'wall_seconds':round(time.monotonic()-started,2),'operator_audit':{k:provenance[k] for k in ['catalogue_version','network_sha256','segment_records','verified_against_archived_source']},
            **measured}
        result['acceptance'] = {
            'all_archived_operator_timings_match':provenance['verified_against_archived_source']==281,
            'all_100_accounts_submitted':len({r['participant'] for r in raw})==100,
            'all_400_reports_acknowledged':len(measured['acks'])==400 and all(r['http_status']==202 and r['ack']=='queued' for r in measured['acks']),
            'all_processing_matches_injected_labels':len(stored)==400 and all(r['actual_processing']==r['expected_processing'] for r in raw),
            'all_500_context_and_journey_checks_pass':len(measured['observations'])==500 and all(r['passed'] for r in measured['observations']) and not measured['failures'],
            'duplicates_do_not_create_observations':measured['duplicate_checks']==['duplicate']*3 and len(stored)==400,
            'both_geographic_boundary_directions_covered':all(any(r['cohort']==c and r['actual_context']=='transition' and r['actual_source']=='crowd' for r in measured['observations']) for c in COHORTS[:2]),
            'expiry_returns_all_100_clients_to_static':sum(r['phase']=='evidence_expired' and r['actual_source']=='schedule' for r in measured['observations'])==100,
            'no_phone_created_train':train_rows==0 and all(not r['next_train_claimed'] for r in measured['observations']),
            'rest_route_arithmetic_consistent':all(measured['rest_checks']),
            'connected_crowd_updates_within_30s':len(observation_latencies)==250 and max(observation_latencies)<30000}
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=12)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
        for log in logs:log.close()
        if engine is not None:engine.dispose()
        if created:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        admin.close()
        if result is not None:result['own_test_database_removed']=True
    (output/'combined-results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'acks','observations','failures'}},indent=2),flush=True)
    return 0 if all(result['acceptance'].values()) else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/operator-crowd-100-users')
    raise SystemExit(run(parser.parse_args().output.resolve()))
