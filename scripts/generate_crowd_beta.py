"""Create reviewable JSON/CSV beta fixtures without connecting to any database."""
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path

from backend.testing.crowd_beta import build_dataset

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/"data/beta/crowdsourcing"


def main():
    dataset=build_dataset(ROOT/"data/operator-network.json")
    TARGET.mkdir(parents=True,exist_ok=True)
    (TARGET/"dataset.json").write_text(json.dumps(dataset,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    headers=["scenario_id","participant_id","data_kind","received_at","received_offset_seconds","event_id","station_id","line_id","direction","event_type","observed_at","latitude","longitude","accuracy_m","cell_fingerprints","delay_seconds","note","expected_ack","expected_processing_status","expected_reason"]
    with (TARGET/"reports.csv").open("w",newline="",encoding="utf-8-sig") as file:
        writer=csv.DictWriter(file,fieldnames=headers);writer.writeheader()
        for case in dataset["scenarios"]:
            for delivery in case["deliveries"]:
                body={**delivery["report"]};body["cell_fingerprints"]=json.dumps(body.get("cell_fingerprints",[]))
                writer.writerow({**body,"scenario_id":case["id"],"participant_id":delivery["participant_id"],"data_kind":"synthetic",
                    "received_at":(datetime.fromisoformat(case["starts_at"])+timedelta(seconds=delivery["received_offset_seconds"])).isoformat(),
                    **{k:delivery[k] for k in ["received_offset_seconds","expected_ack","expected_processing_status","expected_reason"]}})
    with (TARGET/"participants.csv").open("w",newline="",encoding="utf-8-sig") as file:
        writer=csv.DictWriter(file,fieldnames=list(dataset["participants"][0]));writer.writeheader();writer.writerows(dataset["participants"])
    with (TARGET/"expected-checkpoints.csv").open("w",newline="",encoding="utf-8-sig") as file:
        fields=["scenario_id","title","offset_seconds","station_id","line_id","direction","event_type","expected_signal_status","expected_confirmations","expected_delay_seconds","expected_route_delay_seconds"]
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for case in dataset["scenarios"]:
            for check in case["checkpoints"]:
                signal=check["expected_signal"] or {}
                writer.writerow({"scenario_id":case["id"],"title":case["title"],"offset_seconds":check["offset_seconds"],**check["target"],
                    "expected_signal_status":signal.get("status","absent"),"expected_confirmations":signal.get("confirmations",0),
                    "expected_delay_seconds":signal.get("delay_seconds"),"expected_route_delay_seconds":check["expected_route_delay_seconds"]})
    manifest={k:v for k,v in dataset.items() if k not in {"scenarios","participants"}}
    manifest.update(scenarios=len(dataset["scenarios"]),participants=len(dataset["participants"]),
                    report_deliveries=sum(len(c["deliveries"]) for c in dataset["scenarios"]),
                    checkpoints=sum(len(c["checkpoints"]) for c in dataset["scenarios"]),
                    files=["dataset.json","reports.csv","participants.csv","expected-checkpoints.csv"])
    (TARGET/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(TARGET),**{k:manifest[k] for k in ["scenarios","participants","report_deliveries","checkpoints"]}},indent=2))


if __name__=="__main__":main()
