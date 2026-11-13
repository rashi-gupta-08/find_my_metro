"""Chronological split, user identity count and trajectory consistency checks."""
from collections import defaultdict
from datetime import datetime

from scripts.paper_model_experiment import generate_history
from scripts.prediction_data import validate_history,split_history
from scripts.paper_user_load import summary


def test_hundred_user_history_has_causal_disjoint_journey_partitions():
    rows=validate_history(generate_history(3101),synthetic=True)
    partitions,groups=split_history(rows)
    assert [len(group) for group in groups]==[300,100,100]
    assert [len(part) for part in partitions]==[1800,600,600]
    assert len({row['user_id'] for row in partitions[2]})==100
    assert not groups[0]&groups[1] and not groups[1]&groups[2] and not groups[0]&groups[2]
    targets=defaultdict(set)
    for row in rows:
        targets[row['journey_id']].add(row['actual_arrival_at'])
        observed=datetime.fromisoformat(row['observed_at'])
        arrival=datetime.fromisoformat(row['actual_arrival_at'])
        assert observed<arrival
        assert abs((arrival-observed).total_seconds()-row['actual_remaining_seconds'])<1e-6
    assert all(len(stamps)==1 for stamps in targets.values())


def test_generator_repeats_seed_and_changes_independent_run():
    assert generate_history(3101)==generate_history(3101)
    assert generate_history(3101)!=generate_history(3102)


def test_latency_quantiles_include_tail_and_empty_outcomes():
    assert summary([])['p95_ms'] is None
    assert summary([100])=={'samples':1,'p50_ms':100,'p95_ms':100,'max_ms':100}
    assert summary([0,10,20,30,1000])['p95_ms']==806
