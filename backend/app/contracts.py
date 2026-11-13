from datetime import datetime
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TrainObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event_id: str = Field(pattern=r"^[A-Za-z0-9_:.-]{8,100}$")
    trip_id: str = Field(pattern=r"^[A-Za-z0-9_:.-]{1,100}$")
    direction: Literal["inbound", "outbound"]
    observed_at: AwareDatetime
    station_id: str | None = Field(default=None, max_length=60)
    match_key: str | None = Field(default=None, max_length=100)
    kind: Literal["passage", "arrival", "departure", "sighting", "delay"] = "passage"


class SensorEvent(TrainObservation):
    source: Literal["wsn"] = "wsn"
    node_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    checkpoint_id: str = Field(min_length=1, max_length=100)
    healthy: bool = True


class CrowdReport(TrainObservation):
    source: Literal["crowd"] = "crowd"
    kind: Literal["sighting", "arrival", "departure", "delay"] = "sighting"
    contributor_id: str = Field(min_length=1, max_length=100)
    position_m: float = Field(ge=0, le=500000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(default=30, ge=0, le=500)
    note: str = Field(default="", max_length=500)


class ScenarioRequest(BaseModel):
    scenario: Literal["normal", "underground", "transition", "surface", "sensor-loss", "conflict", "timeout", "delay", "reverse-transition"]


class SoftwareScenarioRequest(BaseModel):
    scenario: Literal["normal", "underground", "transition", "surface", "sensor-loss", "conflict", "timeout", "delay", "reverse-transition", "corroboration"]


class BatchRequest(BaseModel):
    reports: list[dict] = Field(min_length=1, max_length=100)
