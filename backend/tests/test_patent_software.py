"""Patent handover behavior and the software feed through the actual durable worker."""
from datetime import timedelta
import json
import pytest
from sqlalchemy import select
from backend.app import engines, main, network, operations, prediction, routing, ml_prediction
from backend.app.config import settings
from backend.app.context_switching import TransitionArbitrationEngine
from backend.app.db import iso
from backend.app.models import Trip, Observation
from backend.app.provider_contracts import NetworkImport
from backend.app.software_feed import network_contract, change_scenario
from backend.app.worker import tick
from fastapi.testclient import TestClient
from conftest import NOW
from test_pipeline import transition, deliver, crowd


def test_incoming_reports_wait_until_trust_exceeds_decaying_estimate(session, trip):
    entered=transition(session,trip)
    deadline=trip.state['transition']['deadline']
    stamp=entered+timedelta(seconds=1)
    for person in ['alice','bob']:
        deliver(session,crowd(trip,person,1700,stamp),stamp)
    assert trip.state['source']=='estimate'
    assert trip.state['reason']=='incoming_below_estimate_trust'
    assert trip.state['arbitration']['estimated_trust']>trip.state['scores']['crowd']
    engines.evaluate(session,trip,entered+timedelta(seconds=10))
    assert trip.state['source']=='crowd'
    assert trip.state['transition']['deadline']==deadline
    assert trip.state['last_observed_at']==iso(stamp)


def test_matching_evidence_fuses_but_unmatched_events_do_not():
    engine=TransitionArbitrationEngine()
    snapshot={'observed_at':iso(NOW),'started_at':iso(NOW),'deadline':iso(NOW+timedelta(seconds=60)),
              'position_m':100,'speed_mps':20,'next_station_position_m':600,'trust':.9}
    evidence={'observed_at':iso(NOW+timedelta(seconds=10)),'position_m':300,'kind':'arrival','match_key':'trip:station:arrival'}
    candidates={'wsn':{**evidence,'event_ids':['node-1']},'crowd':{**evidence,'event_ids':['phone-a','phone-b']}}
    result=engine.arbitrate(snapshot,candidates,{'wsn':.90,'crowd':.88},NOW+timedelta(seconds=10))
    assert result.winner=='fused' and result.reason=='matching_evidence_fused'
    candidates['crowd']['match_key']='another:station:arrival'
    result=engine.arbitrate(snapshot,candidates,{'wsn':.90,'crowd':.88},NOW+timedelta(seconds=10))
    assert 'fused' not in result.candidates and result.reason=='conflict_resolved_by_trust'
    assert engine.estimate(snapshot,NOW+timedelta(seconds=59))['position_m']==600


def test_zone_from_new_sensor_is_not_masked_by_old_surface_reports(session,software_network):
    from backend.app.software_feed import generate
    from backend.app.acquisition import ingest
    change_scenario(session,'reverse-transition',NOW)
    generate(session,NOW)
    for row in session.scalars(select(Observation).where(Observation.status=='queued')):
        engines.process_observation(session,row,NOW)
        session.flush()
    trip=session.scalars(select(Trip).where(Trip.line_id=='dmrc-software',Trip.scheduled_start==iso(NOW))).one()
    assert trip.state['source']=='crowd' and trip.state['context']=='surface'
    stamp=NOW+timedelta(seconds=20)
    cp=network.lookup_checkpoint(trip.line_id,'inbound','dmrc-software-inbound-19')
    result=ingest(session,{'event_id':'independent-tunnel-checkpoint','trip_id':trip.id,'direction':'inbound','observed_at':iso(stamp),
                          'node_id':cp['node_id'],'checkpoint_id':cp['id']},'wsn',now=stamp)
    engines.process_observation(session,session.get(Observation,result['event_id']),stamp)
    assert trip.state['context']=='underground' and trip.state['source']=='wsn'
    assert trip.state['scores']['crowd']<settings.min_source_trust


def test_route_http_endpoint_returns_alternatives_and_clear_unavailable_result(session,software_network):
    change_scenario(session,'normal',NOW)
    session.commit()
    tick(NOW)
    with TestClient(main.app) as client:
        from unittest.mock import patch
        with patch('backend.app.main.utcnow',return_value=NOW):
            response=client.get('/api/v1/routes?origin=dmrc-test-1&destination=dmrc-test-4')
            assert response.status_code==200
            options=response.json()['routes']
            assert len(options)>=2
            assert all(sum(step['seconds'] for step in option['steps'])==option['duration_seconds'] for option in options)
        with patch('backend.app.main.utcnow',return_value=NOW+timedelta(days=1)):
            response=client.get('/api/v1/routes?origin=dmrc-test-1&destination=dmrc-test-4')
            assert response.status_code==200 and response.json()['reason']=='no_valid_route'


@pytest.fixture
def software_network(monkeypatch):
    value=NetworkImport.model_validate(network_contract(NOW)).model_dump(mode='json')
    for module in [network,operations,engines,main,prediction,routing]:
        for name,data in {'CONFIG':value,'LINE_MAP':{line['id']:line for line in value['lines']},
                          'STATION_MAP':{station['id']:station for station in value['stations']},
                          'LINES':value['lines'],'STATIONS':value['stations']}.items():
            if hasattr(module,name): monkeypatch.setattr(module,name,data)
    monkeypatch.setattr(settings,'app_env','software')
    monkeypatch.setattr(settings,'simulation_enabled',True)
    return value


@pytest.mark.parametrize('scenario,states',[
    ('normal',[(0,'underground','wsn'),(25,'transition','estimate'),(40,'transition','crowd'),(65,'surface','crowd')]),
    ('reverse-transition',[(0,'surface','crowd'),(8,'transition',None),(40,'underground','wsn')]),
    ('timeout',[(0,'underground','wsn'),(5,'transition','estimate'),(66,'transition','schedule')]),
    ('sensor-loss',[(0,'underground','wsn'),(10,'underground','schedule')]),
    ('corroboration',[(0,'underground','wsn'),(5,'transition','estimate'),(7,'transition','fused'),(67,'transition','crowd')]),
])
def test_software_journeys_use_real_worker_and_preserve_event_history(session,software_network,scenario,states):
    change_scenario(session,scenario,NOW)
    session.commit()
    for second in range(states[-1][0]+1):
        tick(NOW+timedelta(seconds=second))
        if any(at==second for at,_,_ in states):
            session.expire_all()
            trip=session.scalars(select(Trip).where(Trip.line_id=='dmrc-software',Trip.cancelled.is_(False),Trip.scheduled_start==iso(NOW))).one()
            _,context,source=next(item for item in states if item[0]==second)
            assert trip.state['context']==context
            if source: assert trip.state['source']==source
            if scenario=='corroboration' and second>=7: assert trip.state['position_m']==600
    rows=session.scalars(select(Observation)).all()
    assert rows and all(row.attempts==0 and row.status!='queued' for row in rows)
    previous_ids={row.event_id for row in rows}
    change_scenario(session,'surface',NOW+timedelta(seconds=100))
    session.commit()
    tick(NOW+timedelta(seconds=100))
    session.expire_all()
    assert previous_ids.issubset({row.event_id for row in session.scalars(select(Observation))})


@pytest.fixture
def model_file(tmp_path,monkeypatch):
    value={'schema_version':1,'version':'checked-json-forest','features':ml_prediction.FEATURES,'accepted':True,'synthetic':True,
           'nominal_segment_seconds':30,'validation':{},
           'forecast':[{'at':iso(NOW-timedelta(hours=1)),'segment_seconds':30},{'at':iso(NOW+timedelta(hours=1)),'segment_seconds':30}],
           'forest':[{'left':[-1],'right':[-1],'feature':[-2],'threshold':[-2],'value':[3]}]}
    path=tmp_path/'model.json';path.write_text(json.dumps(value),encoding='utf-8')
    monkeypatch.setattr(settings,'prediction_model_file',str(path))
    monkeypatch.setattr(ml_prediction,'cache',{'path':None,'mtime':None,'model':None,'error':'not_configured'})
    return path


def test_model_json_serves_and_schedule_remains_deterministic(model_file):
    state={'source':'wsn','context':'underground','trust':.9,'speed_mps':20,'last_observed_at':iso(NOW)}
    assert ml_prediction.correct_remaining(120,state,NOW,4)==(123,'checked-json-forest')
    state['source']='schedule'
    assert ml_prediction.correct_remaining(120,state,NOW,4)==(120,'deterministic-segment-baseline-v1')


def test_synthetic_model_is_blocked_outside_software_even_after_cache_load(model_file,monkeypatch):
    assert ml_prediction.load_model()
    monkeypatch.setattr(settings,'app_env','local')
    assert ml_prediction.load_model() is None


def test_invalid_or_expired_model_falls_back(model_file):
    state={'source':'crowd','context':'surface','trust':.9,'last_observed_at':iso(NOW)}
    assert ml_prediction.correct_remaining(100,state,NOW+timedelta(hours=2),2)==(100,'deterministic-segment-baseline-v1')
    model_file.write_text('{invalid-json',encoding='utf-8')
    assert ml_prediction.correct_remaining(100,state,NOW,2)==(100,'deterministic-segment-baseline-v1')


def test_exported_forest_matches_float32_split_semantics():
    from backend.app.forest_inference import predict_forest
    tree={'left':[1,-1,-1],'right':[2,-1,-1],'feature':[0,-2,-2],
          'threshold':[1.00000003,-2,-2],'value':[0,10,20]}
    assert predict_forest([tree],[1.00000004])==10
    assert predict_forest([tree],[1.000001])==20
