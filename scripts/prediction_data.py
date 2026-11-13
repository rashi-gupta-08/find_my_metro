"""Validate causal features and split whole journeys before loading ML libraries."""
import math
from datetime import datetime, timezone, timedelta

FIELDS=['segment_seconds','base_seconds','speed_mps','observation_age','trust','crowd_source','underground','remaining_segments','actual_remaining_seconds']


def stamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('History timestamps must include a timezone')
    return result.astimezone(timezone.utc)


def validate_history(rows,*,synthetic=False):
    valid=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('journey_id'),str) or not row['journey_id']:
            raise ValueError('Each observation needs a journey ID')
        observed=stamp(row['observed_at'])
        if any(isinstance(row.get(name),bool) or not isinstance(row.get(name),(int,float)) or not math.isfinite(row[name]) for name in FIELDS):
            raise ValueError('History features and outcomes must be finite numbers')
        if row['segment_seconds']<=0 or row['base_seconds']<=0 or row['actual_remaining_seconds']<0 or not 0<=row['trust']<=1 or row['observation_age']<0 or not 0<=row['speed_mps']<=45 or row['remaining_segments']<1:
            raise ValueError('History contains invalid feature ranges')
        if row['crowd_source'] not in {0,1} or row['underground'] not in {0,1}:
            raise ValueError('Source and context indicators must be binary')
        if not synthetic and not {'features_available_at','actual_arrival_at'}<=set(row):
            raise ValueError('Operator history requires feature availability and ground-truth arrival timestamps')
        available=stamp(row.get('features_available_at',row['observed_at']))
        if available>observed:raise ValueError('Features include evidence unavailable at prediction time')
        arrival=stamp(row['actual_arrival_at']) if 'actual_arrival_at' in row else observed+timedelta(seconds=row['actual_remaining_seconds'])
        if arrival<observed or abs((arrival-observed).total_seconds()-row['actual_remaining_seconds'])>1:
            raise ValueError('Ground-truth arrival does not match the remaining-time target')
        valid.append({**row,'observed_at':observed.isoformat(),'features_available_at':available.isoformat(),'actual_arrival_at':arrival.isoformat()})
    valid.sort(key=lambda row:row['observed_at'])
    return valid


def split_history(rows):
    journeys=list(dict.fromkeys(row['journey_id'] for row in rows))
    if len(journeys)<50:raise ValueError('At least 50 complete historical journeys are required')
    train_end=int(len(journeys)*.6);validation_end=int(len(journeys)*.8)
    groups=[set(journeys[:train_end]),set(journeys[train_end:validation_end]),set(journeys[validation_end:])]
    parts=[[row for row in rows if row['journey_id'] in group] for group in groups]
    for earlier,later in zip(parts,parts[1:]):
        if max(row['actual_arrival_at'] for row in earlier)>=min(row['observed_at'] for row in later):
            raise ValueError('Chronological split overlaps journey outcomes with later prediction features')
    return parts,groups
