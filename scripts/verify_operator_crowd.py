"""Independently recompute evidence checks from exported files, without a server."""
import csv
import hashlib
import json
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/operator-crowd-100-users'


def verify(out=OUT):
    def read(name):
        with (out/name).open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))
    result=json.loads((out/'combined-results.json').read_text())
    audit=json.loads((out/'operator-provenance-audit.json').read_text())
    network=json.loads((out/'operator-network-snapshot.json').read_text())
    lines={l['id']:l for l in network['lines']}
    source=read('operator-baseline-segments.csv')
    reports=[json.loads(line) for line in (out/'crowd-reports.jsonl').read_text().splitlines()]
    views=read('journey-context-results.csv');acks=read('http-acknowledgements.csv')
    snapshots=[json.loads(line) for line in (out/'journey-snapshots.jsonl').read_text().splitlines()]
    baseline_errors=[]
    for item in snapshots:
        candidates=[r for r in item['snapshot']['routes'] if r['steps'] and all(s['kind']=='ride' and s['line_id'] in {'dmrc-ln3','nmrc-aqua'} for s in r['steps'])]
        # All four fixtures use one ordered line without an interchange.
        route=min(candidates,key=lambda r:r['duration_seconds'])
        total=0
        for s in route['steps']:
            line=lines[s['line_id']];a=line['station_ids'].index(s['from_station_id']);b=line['station_ids'].index(s['to_station_id'])
            assert abs(a-b)==1
            total+=line['segments'][min(a,b)]['seconds']
        matches=[r for r in views if r['phase']==item['phase'] and r['participant']==str(item['participant'])]
        if len(matches)!=1 or int(matches[0]['baseline_seconds'])!=total or int(matches[0]['actual_journey_seconds'])!=route['duration_seconds']:
            baseline_errors.append((item['phase'],item['cohort']))
    def p95(values):
        vals=sorted(values);i=(len(vals)-1)*.95;a=int(i);b=min(a+1,len(vals)-1)
        return round(vals[a]+(vals[b]-vals[a])*(i-a),2)
    observed=[float(r['observed_to_matching_ws_ms']) for r in views if r['observed_to_matching_ws_ms']]
    checks={
        'all_281_source_rows_match':len(source)==281 and all(r['matches_archived_source']=='True' for r in source),
        'source_hashes_intact':all(hashlib.sha256((out/r['source_archive']).read_bytes()).hexdigest()==r['source_sha256'] for r in source),
        'network_hash_intact':hashlib.sha256((out/'operator-network-snapshot.json').read_bytes()).hexdigest()==audit['network_sha256'],
        '100_distinct_synthetic_accounts':len({r['participant'] for r in reports})==100 and all(r['data_kind']=='synthetic' for r in reports),
        '400_unique_report_ids':len(reports)==len({r['report']['event_id'] for r in reports})==400,
        'all_actual_worker_labels_match':all(r['actual_processing']==r['expected_processing'] for r in reports),
        '400_acknowledgements':len(acks)==400 and all(r['http_status']=='202' and r['ack']=='queued' for r in acks),
        '500_journey_records':len(views)==500 and len({(r['phase'],r['participant']) for r in views})==500,
        '20_representative_snapshots':len(snapshots)==20 and not baseline_errors,
        'source_and_context_match_expectations':all(r['actual_source']==r['expected_source'] and r['actual_context']==r['expected_context'] for r in views),
        'journey_adds_delay_once':all(int(r['actual_journey_seconds'])==int(r['baseline_seconds'])+int(r['expected_delay_seconds']) for r in views),
        '100_expiry_fallback_records':sum(r['phase']=='evidence_expired' and r['actual_source']=='schedule' for r in views)==100,
        'ws_p95_recomputed':p95(observed)==result['observation_to_matching_journey_ws_latency']['p95_ms'],
        'ack_p95_recomputed':p95([float(r['elapsed_ms']) for r in acks])==result['http_ack_latency']['p95_ms'],
        'no_next_train_fabricated':all(r['next_train_claimed']=='False' for r in views),
        'test_database_removed':result['own_test_database_removed'],
        'recorded_acceptance_all_pass':all(result['acceptance'].values())}
    verification={'verified_at':datetime.now().astimezone().isoformat(),'checks':checks,'all_checks_passed':all(checks.values()),
        'note':'Recomputation of saved evidence; a reproducibility run uses test_operator_crowd_100.py and fresh timestamps.'}
    (out/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps(verification,indent=2))
    return verification


if __name__=='__main__':raise SystemExit(0 if verify()['all_checks_passed'] else 1)
