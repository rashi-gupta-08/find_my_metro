"""Operator-approved topology and dated timetable contracts; never generated trains."""
from typing import Literal
import math
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator, field_validator
from datetime import timezone


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GeoPoint(StrictModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Station(GeoPoint):
    id: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
    name: str = Field(min_length=1, max_length=100)
    area: str = Field(default="", max_length=100)
    x: float = Field(ge=0, le=850)
    y: float = Field(ge=0, le=500)
    zone: Literal["underground", "transition", "surface"]


class Segment(StrictModel):
    metres: float = Field(gt=0, le=20000)
    seconds: int = Field(gt=0, le=3600)
    zone: Literal["underground", "transition", "surface"]
    geometry: list[GeoPoint] = Field(min_length=2, max_length=1000)
    timing_source: str = Field(default="configured", max_length=100)
    distance_source: str = Field(default="configured", max_length=100)


class Line(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9-]{1,30}$")
    operator_id: Literal["dmrc", "nmrc"]
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    station_ids: list[str] = Field(min_length=2, max_length=200)
    segments: list[Segment] = Field(min_length=1, max_length=199)
    dwell_seconds: int = Field(ge=0, le=600)
    family_id: str | None = Field(default=None, max_length=30)


class Checkpoint(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    node_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    line_id: str
    direction: Literal["inbound", "outbound"]
    position_m: float = Field(ge=0, le=500000)


class TransferConnection(StrictModel):
    from_station_id: str
    to_station_id: str
    seconds: int = Field(gt=0, le=3600)
    requires_exit: bool
    walking_metres: float | None = Field(default=None, ge=0, le=10000)
    distance_estimated: bool = True
    source_url: str | None = Field(default=None, pattern=r"^https://", max_length=1000)


class NetworkImport(StrictModel):
    schema_version: Literal[1] = 1
    provider: str = Field(min_length=1, max_length=100)
    source_url: str = Field(pattern=r"^https://", max_length=1000)
    version: str = Field(min_length=1, max_length=80)
    published_at: AwareDatetime
    stations: list[Station] = Field(min_length=2, max_length=1000)
    lines: list[Line] = Field(min_length=1, max_length=30)
    checkpoints: list[Checkpoint] = Field(default_factory=list, max_length=10000)
    transfer_seconds: int = Field(ge=30, le=3600)
    transfers: list[TransferConnection] = Field(default_factory=list, max_length=200)
    journey_planning: bool = False
    sources: list[dict] = Field(default_factory=list, max_length=30)
    coverage_note: str = Field(default="", max_length=2000)
    transfer_walking_metres: int = Field(default=180, ge=0, le=2000)

    @model_validator(mode="after")
    def topology(self):
        stations = {s.id for s in self.stations}
        lines = {line.id: line for line in self.lines}
        if len(stations) != len(self.stations) or len(lines) != len(self.lines):
            raise ValueError("Station and line IDs must be unique")
        for line in self.lines:
            if len(set(line.station_ids)) != len(line.station_ids) or not set(line.station_ids) <= stations:
                raise ValueError("A line needs distinct known stations; represent branches as separate paths")
            if len(line.segments) != len(line.station_ids)-1:
                raise ValueError("One segment is required between each consecutive station")
            station_map = {station.id: station for station in self.stations}
            for index, segment in enumerate(line.segments):
                for point, identifier in [(segment.geometry[0], line.station_ids[index]), (segment.geometry[-1], line.station_ids[index+1])]:
                    station = station_map[identifier]
                    distance = math.hypot((point.lat-station.lat)*111195, (point.lng-station.lng)*111195*math.cos(math.radians(station.lat)))
                    if distance > 200:
                        raise ValueError("Track geometry endpoints must match their stations within 200 metres")
        if len({cp.id for cp in self.checkpoints}) != len(self.checkpoints):
            raise ValueError("Checkpoint IDs must be unique")
        for cp in self.checkpoints:
            if cp.line_id not in lines or cp.position_m > sum(s.metres for s in lines[cp.line_id].segments):
                raise ValueError("Checkpoint must lie on its configured line")
        for transfer in self.transfers:
            if transfer.from_station_id not in stations or transfer.to_station_id not in stations or transfer.from_station_id == transfer.to_station_id:
                raise ValueError("Walking connections require two distinct known stations")
        return self


class StopTime(StrictModel):
    station_id: str
    arrival_at: AwareDatetime
    departure_at: AwareDatetime
    platform: str | None = Field(default=None, max_length=30)

    @field_validator("arrival_at", "departure_at")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)


class OperatorTrip(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_:.-]{1,100}$")
    code: str = Field(min_length=1, max_length=30)
    line_id: str
    direction: Literal["inbound", "outbound"]
    cancelled: bool = False
    stops: list[StopTime] = Field(min_length=2, max_length=200)

    @model_validator(mode="after")
    def times(self):
        for index, stop in enumerate(self.stops):
            if stop.departure_at < stop.arrival_at or index and stop.arrival_at <= self.stops[index-1].departure_at:
                raise ValueError("Stop times must advance chronologically")
        return self


class TimetableImport(StrictModel):
    network_version: str
    trips: list[OperatorTrip] = Field(min_length=1, max_length=200)
