"""Pre-specified synthetic ETA model experiment, separate from the passenger app.

This measures predictor components, not the paper's source-router ablations.
100 fictional user identities each make 5 chronological simulated journeys.
30 independent generator/training seeds; no real operator delay ground truth.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
MODELS=["schedule","historical","prophet","hybrid"]
NAMES={"schedule":"Schedule","historical":"Historical","prophet":"Prophet","hybrid":"Prophet + RF"}
PROTOCOL={"version":"100-user-eta-v1","data_kind":"synthetic","users":100,"journeys_per_user":5,
          "queries_per_journey":6,"seeds":list(range(3101,3131)),"nominal_segment_seconds":120,
          "dwell_seconds":25,"train_validation_test_journeys":[300,100,100],
          "forest":{"n_estimators":40,"max_depth":7,"min_samples_leaf":4,"n_jobs":2},
          "prophet":{"daily_seasonality":True,"weekly_seasonality":False,"yearly_seasonality":False},
          "bootstrap_replicates":5000,"bootstrap_unit":"whole seed / run","significance":"paired two-sided Wilcoxon over seeds with Holm correction for three comparisons",
          "scope":"Predictor-component evaluation; excludes feed/crowd source-router baselines and ablations; not deployed to the passenger app."}


def generate_history(seed):
    rng=random.Random(seed)
    rows=[]
    for journey in range(500):
        start=datetime(2026,9,1,tzinfo=timezone.utc)+timedelta(hours=journey)
        hour=start.hour+start.minute/60
        season=10*math.sin(2*math.pi*hour/24)+18*(math.exp(-((hour-8)/2)**2)+math.exp(-((hour-18)/2)**2))
        common=max(-12,min(65,rng.gauss(5,19)))
        # Current speed carries imperfect information about a journey-wide
        # condition; future stops/segment innovations are independently drawn.
        travel=[max(65,120+season+common+rng.gauss(0,12)) for _ in range(6)]
        holds=[rng.uniform(25,150) if rng.random()<.06 else 0 for _ in range(6)]
        dwells=[max(10,25+rng.gauss(0,6)) for _ in range(5)]
        arrival=start+timedelta(seconds=sum(travel)+sum(holds)+sum(dwells))
        elapsed=0
        for index in range(6):
            fraction=rng.uniform(.1,.5)
            observed=start+timedelta(seconds=elapsed+fraction*travel[index])
            remaining=6-index
            base=(1-fraction)*120+(remaining-1)*(120+25)
            speed=1800/travel[index]*max(.8,min(1.2,rng.gauss(1,.04)))
            # Completed prior segment timing was available at observation time.
            past=travel[index-1] if index else max(65,120+season+rng.gauss(0,12))
            rows.append({"journey_id":f"s{seed}-j{journey:04}","user_id":f"sim-user-{journey%100:03}",
                "observed_at":observed.isoformat(),"features_available_at":observed.isoformat(),"actual_arrival_at":arrival.isoformat(),
                "segment_seconds":past,"base_seconds":base,"speed_mps":speed,"observation_age":rng.uniform(0,5),
                "trust":rng.uniform(.65,.98),"crowd_source":float(index>=3),"underground":float(index<3),
                "remaining_segments":remaining,"actual_remaining_seconds":(arrival-observed).total_seconds()})
            elapsed+=travel[index]+holds[index]+(dwells[index] if index<5 else 0)
    return rows


def bootstrap(values, rng, replicates=5000):
    import numpy as np
    values=np.asarray(values)
    sampled=rng.choice(values,size=(replicates,len(values)),replace=True).mean(axis=1)
    return [float(np.quantile(sampled,.025)),float(np.quantile(sampled,.975))]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"artifacts/paper-100-users")
    parser.add_argument("--seeds",type=int,default=30)
    args=parser.parse_args()
    if not 1<=args.seeds<=30:raise ValueError("Use 1 to 30 pre-specified seeds")
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    # The ML environment is separate from the API environment. These imports
    # are pure validation and JSON tree traversal; no app configuration/DB import.
    from scripts.prediction_data import validate_history,split_history
    from backend.app.forest_inference import predict_forest
    import numpy as np
    import pandas as pd
    import prophet,sklearn,scipy
    from prophet import Prophet
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error,root_mean_squared_error
    from scipy.stats import wilcoxon
    import logging
    logging.getLogger('cmdstanpy').setLevel(logging.WARNING)
    logging.getLogger('prophet').setLevel(logging.WARNING)
    protocol={**PROTOCOL,"seeds":PROTOCOL["seeds"][:args.seeds],"libraries":{"prophet":prophet.__version__,"sklearn":sklearn.__version__,"numpy":np.__version__,"scipy":scipy.__version__},"python":sys.version.split()[0]}
    (output/"model-protocol.json").write_text(json.dumps(protocol,indent=2)+"\n",encoding="utf-8")
    started=time.monotonic();runs=[]
    predictions_file=output/"heldout-predictions.jsonl"
    with predictions_file.open("w",encoding="utf-8") as predictions_out:
        for seed in protocol["seeds"]:
            seed_started=time.monotonic()
            rows=validate_history(generate_history(seed),synthetic=True)
            (train,validation,test),groups=split_history(rows)
            assert [len(g) for g in groups]==[300,100,100]
            assert len({r['user_id'] for r in test})==100
            assert not groups[0]&groups[1] and not groups[1]&groups[2]
            assert all(len({r['actual_arrival_at'] for r in test if r['journey_id']==jid})==1 for jid in groups[2])
            data_hash=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
            if seed==protocol["seeds"][0]:
                (output/"example-history.jsonl").write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding="utf-8")
            history=pd.DataFrame(train).groupby('observed_at',as_index=False)['segment_seconds'].mean()
            history['ds']=pd.to_datetime(history['observed_at'],utc=True).dt.tz_localize(None)
            history['y']=history['segment_seconds']
            forecast_model=Prophet(**PROTOCOL['prophet'],uncertainty_samples=0)
            forecast_model.fit(history[['ds','y']],seed=seed)
            historical_ratio=float(np.median([r['actual_remaining_seconds']/r['base_seconds'] for r in train]))
            def prepare(part):
                dates=pd.to_datetime([r['observed_at'] for r in part],utc=True).tz_localize(None)
                season=forecast_model.predict(pd.DataFrame({'ds':dates}))['yhat'].to_numpy()
                base=np.array([r['base_seconds'] for r in part])*np.clip(season/120,.5,2)
                features=np.array([[b]+[r[k] for k in ['speed_mps','observation_age','trust','crowd_source','underground','remaining_segments']] for r,b in zip(part,base)])
                return features,base
            x_train,b_train=prepare(train)
            forest=RandomForestRegressor(**PROTOCOL['forest'],random_state=seed)
            forest.fit(x_train,np.array([r['actual_remaining_seconds'] for r in train])-b_train)
            def predict(part):
                x,base=prepare(part)
                raw=np.array([r['base_seconds'] for r in part])
                # Match the serving correction's safety range.
                hybrid=np.clip(base+forest.predict(x),0,raw*2+60)
                return {'schedule':raw,'historical':raw*historical_ratio,'prophet':base,'hybrid':hybrid},x
            def scores(part,values):
                actual=[r['actual_remaining_seconds'] for r in part]
                return {name:{'mae_seconds':float(mean_absolute_error(actual,pred)),
                              'rmse_seconds':float(root_mean_squared_error(actual,pred))} for name,pred in values.items()}
            val_predictions,_=predict(validation);val_scores=scores(validation,val_predictions)
            champion=min(MODELS[:3],key=lambda k:(val_scores[k]['mae_seconds'],val_scores[k]['rmse_seconds']))
            accepted=bool(val_scores['hybrid']['mae_seconds']<val_scores[champion]['mae_seconds'] and val_scores['hybrid']['rmse_seconds']<=val_scores[champion]['rmse_seconds'])
            held,x_test=predict(test);held_scores=scores(test,held)
            if seed==protocol["seeds"][0]:
                trees=[]
                for estimator in forest.estimators_:
                    tree=estimator.tree_
                    trees.append({'left':tree.children_left.tolist(),'right':tree.children_right.tolist(),'feature':tree.feature.tolist(),
                                  'threshold':tree.threshold.tolist(),'value':tree.value[:,0,0].tolist()})
                error=max(abs(predict_forest(trees,values)-expected) for values,expected in zip(x_test,forest.predict(x_test)))
                if error>1e-9:raise ValueError('Exported forest does not match serving inference')
                (output/"candidate-forest.json").write_text(json.dumps({'data_kind':'synthetic','do_not_deploy':True,'seed':seed,'accepted_on_validation':accepted,'forest':trees,'serialization_max_error':error}),encoding='utf-8')
            for index,row in enumerate(test):
                predictions_out.write(json.dumps({'seed':seed,'user_id':row['user_id'],'journey_id':row['journey_id'],
                    'observed_at':row['observed_at'],'actual_remaining_seconds':row['actual_remaining_seconds'],
                    'predictions':{key:float(values[index]) for key,values in held.items()}})+'\n')
            run={'seed':seed,'history_sha256':data_hash,'train_journeys':300,'validation_journeys':100,'test_journeys':100,
                 'test_users':100,'test_query_instants':len(test),'validation':val_scores,'validation_champion':champion,
                 'hybrid_qualified_on_validation':accepted,'test':held_scores,'elapsed_seconds':round(time.monotonic()-seed_started,3)}
            runs.append(run)
            print(json.dumps({'seed':seed,'test':held_scores,'qualified':accepted}),flush=True)
    rng=np.random.default_rng(90210)
    aggregate={}
    for model in MODELS:
        aggregate[model]={}
        for metric in ['mae_seconds','rmse_seconds']:
            values=[r['test'][model][metric] for r in runs]
            aggregate[model][metric]={'mean':float(np.mean(values)),'ci95':bootstrap(values,rng)}
    comparisons=[]
    if len(runs)>1:
        for baseline in MODELS[:3]:
            delta=np.array([r['test'][baseline]['mae_seconds']-r['test']['hybrid']['mae_seconds'] for r in runs])
            p=float(wilcoxon(delta,alternative='two-sided',method='auto').pvalue) if np.any(delta) else 1.
            comparisons.append({'baseline':baseline,'mean_mae_difference_seconds':float(delta.mean()),'ci95':bootstrap(delta,rng),'p_value':p})
        maximum=0
        for rank,item in enumerate(sorted(comparisons,key=lambda r:r['p_value'])):
            maximum=max(maximum,min(1,item['p_value']*(len(comparisons)-rank)))
            item['p_holm']=maximum
    result={'protocol':protocol,'runs':runs,'aggregate':aggregate,'comparisons':comparisons,
        'completed_at':datetime.now(timezone.utc).isoformat(),'total_wall_seconds':round(time.monotonic()-started,2),
        'distinct_simulated_user_ids':100,'total_heldout_journeys':100*len(runs),'heldout_prediction_instants':600*len(runs),
        'validation_acceptance_runs':sum(r['hybrid_qualified_on_validation'] for r in runs),
        'interpretation':'All metrics are measured on synthetic trajectories. Learned source selection, field accuracy, native GPS and the paper source-router ablations are not established.'}
    (output/"model-results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    # Grayscale, print-friendly replacement Figure 10; component comparison only.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Serif','font.size':10,'pdf.fonttype':42,'ps.fonttype':42})
    fig,ax=plt.subplots(figsize=(7.1,3.9),layout='constrained')
    positions=np.arange(4);width=.34
    for offset,metric,label,color,hatch in [(-width/2,'mae_seconds','MAE','0.30',''),(width/2,'rmse_seconds','RMSE','0.83','///')]:
        means=np.array([aggregate[k][metric]['mean'] for k in MODELS])
        errors=np.array([[v-aggregate[k][metric]['ci95'][0] for k,v in zip(MODELS,means)],
                         [aggregate[k][metric]['ci95'][1]-v for k,v in zip(MODELS,means)]])
        bars=ax.bar(positions+offset,means,width,label=label,color=color,edgecolor='black',linewidth=.7,hatch=hatch,yerr=errors,capsize=3,error_kw={'linewidth':.9})
        for bar,value in zip(bars,means):ax.annotate(f'{value:.1f}',(bar.get_x()+bar.get_width()/2,bar.get_height()),xytext=(0,9),textcoords='offset points',ha='center',fontsize=9)
    ax.set_xticks(positions,[NAMES[k] for k in MODELS]);ax.set_ylabel('ETA error (seconds)')
    ax.set_ylim(0,max(aggregate[k]['rmse_seconds']['ci95'][1] for k in MODELS)*1.25)
    ax.set_axisbelow(True);ax.grid(axis='y',color='.9',linewidth=.6);ax.spines[['top','right']].set_visible(False)
    ax.legend(frameon=False,ncols=2,loc='upper right')
    ax.set_title(f'Synthetic held-out prediction error\n100 simulated users per run; {len(runs)} independent seeds',fontsize=11,pad=13)
    for extension in ['png','pdf','svg']:
        fig.savefig(output/f'figure_10.{extension}',dpi=600,bbox_inches='tight')
    plt.close(fig)
    print(json.dumps({'aggregate':aggregate,'output':str(output),'accepted_runs':result['validation_acceptance_runs']},indent=2))


if __name__=='__main__':main()
