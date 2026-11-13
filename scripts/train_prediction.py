"""Train/evaluate the patent prediction pipeline from JSONL journeys, or labelled software history."""
import argparse
import json
import math
from pathlib import Path
from datetime import datetime, timedelta, timezone
import random
import hashlib
from statistics import median
from .prediction_data import validate_history, split_history

FEATURES=["baseline_seconds","speed_mps","observation_age","trust","crowd_source","underground","remaining_segments"]


def software_history():
    randomizer=random.Random(1127)
    end=datetime(2026,10,1,12,tzinfo=timezone.utc)
    rows=[]
    for journey in range(420):
        at=end-timedelta(hours=(420-journey)*.4)
        seasonal=30+3*math.sin(at.hour/24*2*math.pi)
        speed=randomizer.choice([10.,12.,18.,20.])
        crowd=float(journey%2)
        for remaining in [1,2,3,4]:
            base=remaining*30.+(remaining-1)*6.
            baseline=base*seasonal/30
            correction=30*(speed<14)+5*crowd
            rows.append({"journey_id":f"software-history-{journey}","observed_at":at.isoformat(),
                         "segment_seconds":seasonal+randomizer.uniform(-.4,.4),"base_seconds":base,
                         "speed_mps":speed,"observation_age":randomizer.uniform(0,5),"trust":.9,"crowd_source":crowd,
                         "underground":1-crowd,"remaining_segments":remaining,
                         "actual_remaining_seconds":baseline+correction+randomizer.uniform(-1,1)})
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--software',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--nominal-segment-seconds',type=float)
    args=parser.parse_args()
    if bool(args.input)==bool(args.software): raise ValueError('Choose actual JSONL input or explicitly labelled software history')
    nominal=args.nominal_segment_seconds if args.nominal_segment_seconds is not None else (30 if args.software else None)
    if nominal is None or not 1<=nominal<=3600:raise ValueError('Specify the network nominal segment time between 1 and 3600 seconds')
    import pandas as pd
    from prophet import Prophet
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, root_mean_squared_error
    import sklearn,prophet
    rows=software_history() if args.software else [json.loads(line) for line in args.input.read_text(encoding='utf-8').splitlines() if line.strip()]
    rows=validate_history(rows,synthetic=args.software)
    (train,validation,test),(train_ids,validation_ids,test_ids)=split_history(rows)
    historical_ratio=median(row['actual_remaining_seconds']/row['base_seconds'] for row in train)
    history=pd.DataFrame(train).groupby('observed_at',as_index=False)['segment_seconds'].mean()
    history['ds']=pd.to_datetime(history['observed_at'],utc=True).dt.tz_localize(None)
    history['y']=history['segment_seconds']
    model=Prophet(daily_seasonality=True,weekly_seasonality=False,yearly_seasonality=False,uncertainty_samples=0)
    model.fit(history[['ds','y']],seed=1127)
    def prepare(values):
        dates=pd.to_datetime([row['observed_at'] for row in values],utc=True).tz_localize(None)
        forecasts=model.predict(pd.DataFrame({'ds':dates}))['yhat'].tolist()
        matrix=[];targets=[];baselines=[]
        for row,segment in zip(values,forecasts):
            baseline=row['base_seconds']*max(.5,min(2,max(1,segment)/nominal))
            matrix.append([baseline]+[row[name] for name in FEATURES[1:]])
            targets.append(row['actual_remaining_seconds']-baseline)
            baselines.append(baseline)
        return matrix,targets,baselines
    x,y,_=prepare(train)
    forest=RandomForestRegressor(n_estimators=40,max_depth=7,min_samples_leaf=4,random_state=1127,n_jobs=2)
    forest.fit(x,y)
    x_test,_,base_test=prepare(validation)
    actual=[row['actual_remaining_seconds'] for row in validation]
    predicted=[base+delta for base,delta in zip(base_test,forest.predict(x_test))]
    def baselines(values,prophet_predictions):
        return {'schedule':[row['base_seconds'] for row in values],
                'historical':[row['base_seconds']*historical_ratio for row in values],
                'prophet':prophet_predictions}
    def scores(actual,predictions):
        return {'mae_seconds':float(mean_absolute_error(actual,predictions)),
                'rmse_seconds':float(root_mean_squared_error(actual,predictions))}
    baseline_results={name:scores(actual,values) for name,values in baselines(validation,base_test).items()}
    champion=min(baseline_results,key=lambda name:(baseline_results[name]['mae_seconds'],baseline_results[name]['rmse_seconds']))
    baseline_mae=baseline_results[champion]['mae_seconds']
    mae=mean_absolute_error(actual,predicted)
    accepted=bool(mae<baseline_mae and root_mean_squared_error(actual,predicted)<=baseline_results[champion]['rmse_seconds'])
    x_held,_,base_held=prepare(test)
    actual_held=[row['actual_remaining_seconds'] for row in test]
    predicted_held=[base+delta for base,delta in zip(base_held,forest.predict(x_held))]
    now=datetime.now(timezone.utc)
    times=[now+timedelta(minutes=index*10) for index in range(-1,1009)]
    future=model.predict(pd.DataFrame({'ds':pd.to_datetime(times,utc=True).tz_localize(None)}))['yhat'].tolist()
    trees=[]
    for estimator in forest.estimators_:
        tree=estimator.tree_
        trees.append({'left':tree.children_left.tolist(),'right':tree.children_right.tolist(),'feature':tree.feature.tolist(),
                      'threshold':tree.threshold.tolist(),'value':tree.value[:,0,0].tolist()})
    from backend.app.forest_inference import predict_forest
    serialization_error=max(abs(predict_forest(trees,values)-expected) for values,expected in zip(x_test,forest.predict(x_test)))
    if serialization_error>1e-9: raise ValueError('JSON inference does not reproduce the trained forest')
    held_baselines={name:scores(actual_held,values) for name,values in baselines(test,base_held).items()}
    metrics={'baseline_mae_seconds':round(float(baseline_mae),3),'hybrid_mae_seconds':round(float(mae),3),
             'hybrid_rmse_seconds':round(float(root_mean_squared_error(actual,predicted)),3),
             'test_baseline_mae_seconds':round(held_baselines[champion]['mae_seconds'],3),
             'test_hybrid_mae_seconds':round(float(mean_absolute_error(actual_held,predicted_held)),3),
             'test_hybrid_rmse_seconds':round(float(root_mean_squared_error(actual_held,predicted_held)),3),
             'training_journeys':len(train_ids),'validation_journeys':len(validation_ids),'test_journeys':len(test_ids),'chronological_split':True,
             'strongest_baseline':champion,'validation_baselines':baseline_results,'test_baselines':held_baselines,
             'causal_features_checked':True,'outcome_cutoffs_checked':True,
             'data_kind':'synthetic_software_validation' if args.software else 'operator_supplied_history'}
    metrics['serialization_max_error']=float(serialization_error)
    history_hash=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    artifact={'schema_version':1,'version':'prophet-random-forest-v2-'+history_hash[:12],'synthetic':args.software,'accepted':accepted,
              'features':FEATURES,'nominal_segment_seconds':nominal,'trained_at':now.isoformat(),'history_sha256':history_hash,
              'libraries':{'prophet':prophet.__version__,'scikit_learn':sklearn.__version__},'validation':metrics,
              'forecast':[{'at':at.isoformat(),'segment_seconds':max(1,float(seconds))} for at,seconds in zip(times,future)],'forest':trees}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(artifact,separators=(',',':')),encoding='utf-8')
    temporary.replace(args.output)
    args.output.with_suffix('.evaluation.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    args.output.with_suffix('.history.jsonl').write_text('\n'.join(json.dumps(row) for row in rows)+'\n',encoding='utf-8')
    print(json.dumps({'accepted':accepted,**metrics},indent=2))


if __name__=='__main__':
    main()
