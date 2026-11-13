from datetime import timedelta
import pytest
from scripts.prediction_data import validate_history, split_history
from conftest import NOW


def history():
    return [{'journey_id':f'journey-{index}','observed_at':(NOW+timedelta(minutes=index*10)).isoformat(),
             'features_available_at':(NOW+timedelta(minutes=index*10)).isoformat(),
             'actual_arrival_at':(NOW+timedelta(minutes=index*10,seconds=70)).isoformat(),
             'segment_seconds':30.,'base_seconds':60.,'speed_mps':20.,'observation_age':1.,'trust':.9,
             'crowd_source':0.,'underground':1.,'remaining_segments':2.,'actual_remaining_seconds':70.}
            for index in range(50)]


def test_whole_journey_split_requires_causal_inputs_and_ground_truth():
    valid=validate_history(history())
    (train,validation,test),groups=split_history(valid)
    assert [len(part) for part in [train,validation,test]]==[30,10,10]
    assert not groups[0]&groups[1] and not groups[1]&groups[2]


@pytest.mark.parametrize('variation',['future_features','future_outcome','naive_time','nonfinite','missing_provenance','wrong_target'])
def test_invalid_training_history_is_rejected(variation):
    rows=history()
    if variation=='future_features':rows[0]['features_available_at']=(NOW+timedelta(seconds=1)).isoformat()
    if variation=='future_outcome':rows[29]['actual_remaining_seconds']=700;rows[29]['actual_arrival_at']=(NOW+timedelta(minutes=29*10,seconds=700)).isoformat()
    if variation=='naive_time':rows[0]['observed_at']=NOW.replace(tzinfo=None).isoformat()
    if variation=='nonfinite':rows[0]['trust']=float('nan')
    if variation=='missing_provenance':del rows[0]['features_available_at']
    if variation=='wrong_target':rows[0]['actual_remaining_seconds']=50.
    with pytest.raises(ValueError):split_history(validate_history(rows))


def test_synthetic_data_remains_explicitly_separate():
    rows=history()
    for row in rows:del row['features_available_at'];del row['actual_arrival_at']
    assert validate_history(rows,synthetic=True)
    with pytest.raises(ValueError):validate_history(rows)
