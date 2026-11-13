"""Independently recompute publication metrics from saved predictions/requests."""
from collections import Counter,defaultdict
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    directory=ROOT/'artifacts/paper-100-users'
    result=json.loads((directory/'model-results.json').read_text())
    errors=defaultdict(lambda:defaultdict(list));users=defaultdict(set);journeys=defaultdict(set)
    count=0
    for line in (directory/'heldout-predictions.jsonl').open(encoding='utf-8'):
        row=json.loads(line);count+=1
        users[row['seed']].add(row['user_id']);journeys[row['seed']].add(row['journey_id'])
        for name,prediction in row['predictions'].items():
            assert math.isfinite(prediction) and prediction>=0
            errors[row['seed']][name].append(prediction-row['actual_remaining_seconds'])
    assert len(errors)==30 and count==18000
    for run in result['runs']:
        assert len(users[run['seed']])==len(journeys[run['seed']])==100
        for name,values in errors[run['seed']].items():
            mae=sum(abs(v) for v in values)/len(values)
            rmse=math.sqrt(sum(v*v for v in values)/len(values))
            assert abs(mae-run['test'][name]['mae_seconds'])<1e-9
            assert abs(rmse-run['test'][name]['rmse_seconds'])<1e-9
    for name,metrics in result['aggregate'].items():
        for metric,value in metrics.items():
            mean=sum(run['test'][name][metric] for run in result['runs'])/30
            assert abs(mean-value['mean'])<1e-9
            assert value['ci95'][0]<=mean<=value['ci95'][1]
    load=json.loads((directory/'load-results.json').read_text())
    assert len(load['requests'])==500 and len(load['updates'])==500
    assert len({row['user'] for row in load['requests']})==100
    assert Counter(row['wave'] for row in load['requests'])==dict.fromkeys(range(1,6),100)
    assert all(r['status']==202 and r['ack']=='queued' for r in load['requests'])
    assert all(load['acceptance'].values())
    report={'prediction_rows_recomputed':count,'model_runs_recomputed':30,'distinct_users_per_run':100,
            'http_acknowledgements_checked':500,'websocket_updates_checked':500,
            'processing_matches_known_injected_faults':load['actual_processing']==load['expected_processing'],
            'all_checks_passed':True}
    (directory/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
