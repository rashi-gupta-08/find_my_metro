"""Beta fixture fidelity and isolation guards; no passenger database connection."""
import csv
from datetime import datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from backend.app.surface_reports import SurfaceReport
from backend.testing.crowd_beta import build_dataset
from scripts import run_crowd_beta

ROOT=Path(__file__).resolve().parents[2]
PACK=ROOT/"data/beta/crowdsourcing"


def test_published_beta_pack_is_reproducible_and_csv_matches_deliveries():
    generated=build_dataset(ROOT/"data/operator-network.json")
    published=json.loads((PACK/"dataset.json").read_text(encoding="utf-8"))
    assert generated==published
    with (PACK/"reports.csv").open(encoding="utf-8-sig",newline="") as file:
        rows=list(csv.DictReader(file))
    deliveries=[d for c in generated["scenarios"] for d in c["deliveries"]]
    assert len(rows)==len(deliveries)==461
    assert all(row["data_kind"]=="synthetic" for row in rows)
    assert {d["participant_id"] for d in deliveries}=={p["id"] for p in generated["participants"]}


def test_labels_stay_out_of_submitted_reports_and_bad_schema_is_deliberate():
    dataset=build_dataset(ROOT/"data/operator-network.json")
    invalid=[]
    for case in dataset["scenarios"]:
        for delivery in case["deliveries"]:
            body=delivery["report"]
            assert not set(body)&{"expected_ack","expected_reason","participant_id","contributor_id","ground_truth"}
            assert datetime.fromisoformat(body["observed_at"]).tzinfo is not None
            try:SurfaceReport.model_validate(body)
            except ValidationError:
                invalid.append(case["id"])
                assert delivery["expected_ack"]=="rejected"
                assert delivery["expected_processing_status"] is None
    assert invalid==["inaccurate-gps"]*3


def test_beta_runner_rejects_external_or_reused_database_targets(tmp_path,monkeypatch):
    monkeypatch.setattr(run_crowd_beta,"ROOT",tmp_path)
    with pytest.raises(ValueError,match="new run folder"):
        run_crowd_beta.isolated_environment(tmp_path/"passenger")
    root=tmp_path/".local/crowd-beta"
    used=root/"existing";used.mkdir(parents=True);(used/"beta.db").touch()
    with pytest.raises(ValueError,match="new run folder"):
        run_crowd_beta.isolated_environment(used)
    fresh=root/"new";fresh.mkdir()
    environment=run_crowd_beta.isolated_environment(fresh)
    assert environment["DATABASE_URL"]=="sqlite:///"+(fresh/"beta.db").as_posix()
    assert environment["APP_ENV"]=="test"
    assert environment["MIGRATION_DATABASE_URL"]==environment["CELL_MAP_FILE"]==""
    assert environment["HARDWARE_ENABLED"]==environment["MQTT_ENABLED"]=="false"
    assert environment["METRO_ENV_FILE"]!=str(tmp_path/".env")
