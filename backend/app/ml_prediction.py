"""Safe JSON inference for a trained Prophet forecast plus Random Forest correction.

Training uses Prophet/scikit-learn offline. Serving never loads pickle or executable model files.
"""
import json
import math
from bisect import bisect_left
from pathlib import Path
from .config import ROOT, settings
from .db import parse
from .forest_inference import predict_forest

FEATURES=["baseline_seconds","speed_mps","observation_age","trust","crowd_source","underground","remaining_segments"]
cache={"path":None,"mtime":None,"model":None,"error":"not_configured"}


def load_model():
    if not settings.prediction_model_file:
        cache.update(model=None,error="not_configured")
        return None
    path=Path(settings.prediction_model_file)
    if not path.is_absolute(): path=ROOT/path
    try:
        stat=path.stat()
        if cache["path"]==str(path) and cache["mtime"]==stat.st_mtime_ns and cache.get("size")==stat.st_size:
            if cache["model"] and cache["model"]["synthetic"] and not settings.synthetic_data:
                return None
            return cache["model"]
        if stat.st_size>8*1024*1024: raise ValueError("oversized_model")
        model=json.loads(path.read_text(encoding="utf-8"))
        if model["schema_version"]!=1 or model["features"]!=FEATURES or not model["accepted"]:
            raise ValueError("unapproved_model")
        if model["synthetic"] and not settings.synthetic_data:
            raise ValueError("synthetic_model_not_allowed")
        forest=model["forest"]
        if not 1<=len(forest)<=128: raise ValueError("invalid_forest")
        for tree in forest:
            size=len(tree["left"])
            if not 1<=size<=8191 or any(len(tree[key])!=size for key in ["right","feature","threshold","value"]):
                raise ValueError("invalid_tree")
            for index in range(size):
                left,right=tree["left"][index],tree["right"][index]
                if left!=-1 and (not index<left<size or not index<right<size or not 0<=tree["feature"][index]<len(FEATURES)):
                    raise ValueError("invalid_tree_indices")
                if not all(math.isfinite(tree[key][index]) for key in ["threshold","value"]):
                    raise ValueError("invalid_tree_number")
        forecast=model["forecast"]
        if not 2<=len(forecast)<=20000 or any(not math.isfinite(item["segment_seconds"]) or not 1<=item["segment_seconds"]<=3600 for item in forecast):
            raise ValueError("invalid_forecast")
        times=[parse(item["at"]) for item in forecast]
        if any(a>=b for a,b in zip(times,times[1:])): raise ValueError("unordered_forecast")
        if not math.isfinite(model["nominal_segment_seconds"]) or model["nominal_segment_seconds"]<=0:
            raise ValueError("invalid_nominal_segment_time")
        if not isinstance(model["version"],str) or not isinstance(model["validation"],dict):
            raise ValueError("invalid_model_metadata")
        model["forecast_times"]=times
        cache.update(path=str(path),mtime=stat.st_mtime_ns,size=stat.st_size,model=model,error=None)
        return model
    except (OSError,ValueError,KeyError,TypeError,OverflowError):
        cache.update(model=None,error="model_unavailable_or_invalid")
        return None


def model_status():
    model=load_model()
    return {"active":bool(model),"version":model["version"] if model else "deterministic-segment-baseline-v1",
            "kind":"Prophet baseline + Random Forest correction" if model else "Timetable/segment baseline",
            "training_data":"synthetic_software_validation" if model and model["synthetic"] else "operator_history" if model else None,
            "validation":model["validation"] if model else None,"fallback_reason":cache["error"] if not model else None}


def correct_remaining(base, state, now, remaining_segments):
    model=load_model()
    if not model or state["source"]=="schedule" or base<=0:
        return base,"deterministic-segment-baseline-v1"
    forecast=model["forecast"]
    times=model["forecast_times"]
    if not times[0]<=now<=times[-1]:
        return base,"deterministic-segment-baseline-v1"
    index=bisect_left(times,now)
    if index and (now-times[index-1]).total_seconds() < (times[index]-now).total_seconds(): index-=1
    row=forecast[index]
    ratio=max(.5,min(2,row["segment_seconds"]/model["nominal_segment_seconds"]))
    baseline=base*ratio
    age=max(0,(now-parse(state["last_observed_at"])).total_seconds()) if state.get("last_observed_at") else 300
    values=[baseline,state.get("speed_mps") or 0,age,state["trust"],float(state["source"] in {"crowd","fused"}),float(state["context"]=="underground"),remaining_segments]
    try:
        result=baseline+predict_forest(model['forest'],values)
        if not math.isfinite(result): raise ValueError("invalid_prediction")
        return max(0,min(base*2+60,result)),model["version"]
    except (ValueError,KeyError,TypeError,IndexError,ZeroDivisionError,OverflowError):
        return base,"deterministic-segment-baseline-v1"
