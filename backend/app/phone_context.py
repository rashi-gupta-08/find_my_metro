"""Reviewed cell fingerprints are optional hints, never a train identifier.

Raw cell IDs, subscriber IDs and phone numbers are neither required nor stored.
An empty map deliberately produces no location claim.
"""
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from .config import ROOT, settings
from . import network


class Fingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    station_id: str
    accuracy_m: float = Field(gt=0, le=250)


class CellMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=80)
    reviewed_by: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=300)
    entries: list[Fingerprint] = Field(max_length=30000)


def cell_map():
    if not settings.cell_map_file:
        return {"version": "unmapped", "entries": [], "source": None}
    path = Path(settings.cell_map_file)
    if not path.is_absolute():
        path = ROOT / path
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Cell map exceeds the 8 MiB offline budget")
    value = CellMap.model_validate_json(path.read_text(encoding="utf-8")).model_dump()
    identifiers = [entry["fingerprint"] for entry in value["entries"]]
    if len(set(identifiers)) != len(identifiers) or any(e["station_id"] not in network.STATION_MAP for e in value["entries"]):
        raise ValueError("Cell map contains ambiguous fingerprints or unknown stations")
    return value


def match_cells(fingerprints, route_station_ids=None):
    """Require two separately mapped radios; route restriction prevents teleporting."""
    mapping = cell_map()
    allowed = set(route_station_ids) if route_station_ids is not None else set(network.STATION_MAP)
    entries = [e for e in mapping["entries"] if e["fingerprint"] in set(fingerprints) and e["station_id"] in allowed]
    stations = {e["station_id"] for e in entries}
    if len(entries) < 2 or len(stations) != 1:
        return {"status": "unmapped" if not entries else "ambiguous", "station_id": None, "map_version": mapping["version"]}
    station = next(iter(stations))
    return {"status": "matched", "station_id": station, "context": network.STATION_MAP[station]["zone"],
            "accuracy_m": max(e["accuracy_m"] for e in entries), "map_version": mapping["version"],
            "evidence_kind": "reviewed_cell_fingerprint_hint", "train_identity": None}


def offline_bundle():
    lines = [line for line in network.LINES if line.get("operator_id") == "nmrc"]
    ids = {station for line in lines for station in line["station_ids"]}
    mapping = cell_map()
    result = {"schema_version": 1, "network_version": network.CONFIG["version"] if network.CONFIG else "unconfigured",
              "scope": "nmrc_aqua_phase_1", "stations": [s for s in network.STATIONS if s["id"] in ids],
              "lines": lines, "cell_map": {**mapping, "entries": [e for e in mapping["entries"] if e["station_id"] in ids]},
              "live_ttl_seconds": settings.service_report_max_age_seconds, "cell_map_budget_bytes": 8 * 1024 * 1024,
              "timing_kind": "operator_indicative_segment_times", "dated_departures_available": False,
              "notice": "Offline journey estimates exclude ordinary boarding wait. Cell coverage requires a reviewed field map; live evidence expires after 30 seconds."}
    result["bundle_bytes"] = len(json.dumps(result, separators=(",", ":")).encode())
    return result
