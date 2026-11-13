from datetime import timedelta
from sqlalchemy import select
from fastapi import APIRouter, HTTPException, Request
from .auth import identity, limit
from .config import settings
from .db import iso, parse, transaction, utcnow
from .engines import initial_state
from .models import SecurityAudit, Trip
from .network import CONFIG, LINE_MAP, context_at, path_for
from .provider_contracts import TimetableImport

router = APIRouter(prefix="/api/v1/operator", tags=["Operator integration"])


def active_trips(session, now):
    if settings.app_env == "test":
        from .simulator import current_trips
        return current_trips(session, now)
    if not CONFIG:
        return []
    rows = session.scalars(select(Trip).where(Trip.service_end >= iso(now-timedelta(seconds=30)),
                                             Trip.network_version == CONFIG["version"], Trip.cancelled.is_(False),
                                             Trip.scheduled_start <= iso(now+timedelta(hours=12))).order_by(Trip.scheduled_start)).all()
    return [trip for trip in rows if trip.line_id in LINE_MAP and trip.timetable.get("stops")]


def import_timetable(session, body, now):
    if not CONFIG or body.network_version != CONFIG["version"]:
        raise HTTPException(409, "Load the matching approved network configuration first")
    if len({trip.id for trip in body.trips}) != len(body.trips):
        raise HTTPException(422, "Trip IDs must be unique in a batch")
    for item in body.trips:
        if item.line_id not in LINE_MAP or [stop.station_id for stop in item.stops] != path_for(item.line_id, item.direction):
            raise HTTPException(422, "Trip stops must match the configured directional line path")
        if item.stops[0].arrival_at < now-timedelta(days=2) or item.stops[-1].departure_at > now+timedelta(days=7):
            raise HTTPException(422, "Import dated services within the supported seven-day horizon")
        existing = session.get(Trip, item.id)
        if existing and (existing.line_id != item.line_id or existing.direction != item.direction or existing.scheduled_start != iso(item.stops[0].arrival_at)):
            raise HTTPException(409, "A trip ID cannot be reassigned to a different journey")
    for item in body.trips:
        trip = session.get(Trip, item.id)
        if trip is None:
            state = initial_state()
            state["context"] = context_at(item.line_id, item.direction, 0)
            trip = Trip(id=item.id, code=item.code, line_id=item.line_id, direction=item.direction,
                        scheduled_start=iso(item.stops[0].arrival_at), state=state, version=0)
            session.add(trip)
        trip.timetable = {"network_version": body.network_version, "cancelled": item.cancelled,
                          "imported_at": iso(now), "stops": [stop.model_dump(mode="json") for stop in item.stops]}
        trip.service_end, trip.network_version, trip.cancelled = iso(item.stops[-1].departure_at), body.network_version, item.cancelled
        trip.version += 1
    return {"imported": len(body.trips), "network_version": body.network_version}


@router.post("/timetable")
def timetable(body: TimetableImport, request: Request):
    user = identity(request, mutation=True, admin=True)
    limit(user.id, "timetable_import", 20)
    with transaction() as session:
        result = import_timetable(session, body, utcnow())
        session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id, action="timetable_imported"))
    return result
