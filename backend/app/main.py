import asyncio
import hmac
import time
import threading
from datetime import timedelta
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse

from .acquisition import ingest
from .auth import authenticate_device, client_identity, identity, limit, router as auth_router
from .config import settings
from .contracts import BatchRequest, ScenarioRequest, SoftwareScenarioRequest
from .db import Session, engine, iso, parse, transaction, utcnow
from .models import Decision, Observation, Runtime, Trip
from .network import CONFIG, LINE_MAP, STATION_MAP, network_payload, project_position
from .operations import active_trips, router as operator_router
from .prediction import arrivals_for, effective_state
from .routing import routes
from .security import SecurityMiddleware
from .surface_reports import store_report, signals, report_history


@asynccontextmanager
async def lifespan(app):
    global snapshot_cache
    snapshot_cache = None
    journey_cache.clear()
    if settings.app_env == "test" and settings.simulation_enabled:
        from .simulator import seed
        with transaction() as session:
            seed(session, utcnow())
    yield
    engine.dispose()


app = FastAPI(title="FindMyMetro", version="1.0.0", lifespan=lifespan,
              docs_url=None if settings.app_env == "production" else "/docs",
              redoc_url=None, openapi_url=None if settings.app_env == "production" else "/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-CSRF-Token"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts.split(","))
app.add_middleware(SecurityMiddleware)
app.include_router(auth_router)
app.include_router(operator_router)


def require_key(value, expected):
    if not value or not expected or not hmac.compare_digest(value, expected):
        raise HTTPException(401, "Invalid credential")


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable. Please retry."}, headers={"Retry-After": "5"})


@app.get("/api/v1/network")
def network():
    return network_payload()


@app.get("/api/v1/health/live")
def liveness():
    return {"alive": True}


@app.get("/api/v1/health")
def health():
    with Session() as session:
        session.execute(text("SELECT 1"))
        heartbeat = session.get(Runtime, "worker")
        age = (utcnow()-parse(heartbeat.value["at"])).total_seconds() if heartbeat else None
        pending = session.scalar(select(func.count()).select_from(Observation).where(Observation.status == "queued"))
        return {"api": "ready", "database": engine.dialect.name, "worker": "ready" if age is not None and 0 <= age < 10 else "unavailable",
                "worker_age_seconds": age, "queued_events": pending, "simulated": settings.simulation_enabled,
                "network_configured": bool(STATION_MAP), "ready": age is not None and 0 <= age < 10}


@app.get("/api/v1/health/ready")
def readiness():
    status = health()
    return JSONResponse(status_code=200 if status["ready"] else 503, content={"ready": status["ready"]})


@app.post("/api/v1/sensor-events", status_code=202)
def sensor_events(payload: dict, request: Request, x_api_key: Annotated[str | None, Header()] = None):
    if settings.app_env != "test" and not settings.hardware_enabled:
        raise HTTPException(410, "Hardware acquisition is disabled in the software-only application")
    limit(client_identity(request), "sensor_ingestion", 600)
    with transaction() as session:
        if settings.app_env == "test" and x_api_key == settings.sensor_api_key:
            require_key(x_api_key, settings.sensor_api_key)
        else:
            authenticate_device(session, x_api_key, payload.get("node_id"))
        result = ingest(session, payload, "wsn")
    if result["status"] == "conflict":
        raise HTTPException(409, result)
    return result


@app.post("/api/v1/crowd-reports/batch", status_code=202)
def crowd_reports(payload: BatchRequest, request: Request, authorization: Annotated[str | None, Header()] = None):
    token = authorization.removeprefix("Bearer ") if authorization else ""
    contributor = settings.contributors().get(token)
    if not contributor:
        contributor = identity(request, mutation=True).id
    limit(contributor, "crowd_batches", 10)
    results = []
    with transaction() as session:
        for index, raw in enumerate(payload.reports):
            report = dict(raw)
            if settings.app_env != "test":
                if "contributor_id" in report and report["contributor_id"] != contributor:
                    report["identity_mismatch"] = True
                report["contributor_id"] = contributor
                trip = session.get(Trip, report.get("trip_id")) if isinstance(report.get("trip_id"), str) else None
                if trip and trip.line_id in LINE_MAP:
                    try:
                        distance, position = project_position(trip.line_id, trip.direction, float(report["latitude"]), float(report["longitude"]))
                        report["position_m"] = position
                        if distance > 500 or float(report.get("accuracy_m", 500)) > 100:
                            report["unreliable_location"] = True
                    except (KeyError, ValueError, TypeError):
                        report["invalid_location"] = True
                else:
                    report["unassigned_trip"] = True
            result = ingest(session, report, "crowd", contributor)
            results.append({**result, "index": index, "client_event_id": raw.get("event_id")})
    return {"acknowledgements": results, "simulated": settings.synthetic_data}


@app.post("/api/v1/reports/batch", status_code=202)
@app.post("/api/v1/surface-reports/batch", status_code=202, deprecated=True)
def surface_reports(payload: BatchRequest, request: Request):
    user=identity(request,mutation=True)
    limit(user.id,"surface_reports",20)
    with transaction() as session:
        results=[{**store_report(session,raw,user.id,utcnow()),"index":i,"client_event_id":raw.get("event_id")}
                 for i,raw in enumerate(payload.reports)]
    return {"acknowledgements":results}


@app.get("/api/v1/service-status")
def service_status(request: Request):
    limit(client_identity(request),"service_status",120)
    now=utcnow()
    with Session() as session:
        return {"signals":signals(session,now),"generated_at":iso(now),"hardware_status":"disabled_software_only",
                "live_ttl_seconds":settings.service_report_max_age_seconds,"consensus_users":settings.service_consensus_users,
                "baseline":"operator_static" if CONFIG and CONFIG.get("journey_planning") else "unavailable"}


@app.get("/api/v1/reports/mine")
@app.get("/api/v1/surface-reports/mine", deprecated=True)
def my_surface_reports(request: Request, limit_count: int = Query(default=30,ge=1,le=100)):
    user=identity(request)
    limit(user.id,"report_history",60)
    now=utcnow()
    with Session() as session:
        return {"reports":report_history(session,user.id,now,limit_count),"generated_at":iso(now)}


@app.get("/api/v1/contributions/mine")
def my_contributions(request: Request):
    from .surface_reports import rewards
    user=identity(request)
    with Session() as session:
        return rewards(session,user.id)


@app.get("/api/v1/offline-bundle")
def get_offline_bundle(request: Request):
    from .phone_context import offline_bundle
    limit(client_identity(request),"offline_bundle",30)
    return offline_bundle()


@app.post("/api/v1/phone-context")
def phone_context(payload: dict, request: Request):
    from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, ValidationError
    from .phone_context import match_cells
    class PhoneContext(BaseModel):
        model_config=ConfigDict(extra="forbid")
        observed_at: AwareDatetime
        fingerprints: list[str] = Field(max_length=16)
        route_station_ids: list[str] = Field(max_length=300)
    user=identity(request,mutation=True)
    limit(user.id,"phone_context",30)
    try:
        body=PhoneContext.model_validate(payload)
    except ValidationError:
        raise HTTPException(422,"Invalid phone observation") from None
    age=(utcnow()-body.observed_at).total_seconds()
    if age<0 or age>=settings.service_report_max_age_seconds:
        raise HTTPException(422,"Phone observation is stale or future dated")
    return {**match_cells(body.fingerprints,body.route_station_ids),"observed_at":iso(body.observed_at),"age_seconds":round(age),
            "expires_at":iso(body.observed_at+timedelta(seconds=settings.service_report_max_age_seconds))}


snapshot_lock = threading.Lock()
snapshot_cache = None


def eta_snapshot(station_id, line_id=None, direction=None):
    global snapshot_cache
    if station_id not in STATION_MAP:
        raise HTTPException(404, "Unknown station")
    if line_id is not None and line_id not in LINE_MAP or direction is not None and direction not in {"inbound", "outbound"}:
        raise HTTPException(422, "Unknown line or direction")
    # One bounded read per API process serves every connected station. Client count
    # must not multiply the full network prediction calculation or database reads.
    with snapshot_lock:
        current = utcnow()
        if not snapshot_cache or time.monotonic()-snapshot_cache["created"] >= 2 or snapshot_cache["expires_at"] and current >= snapshot_cache["expires_at"]:
            with Session() as session:
                now = utcnow()
                grouped = {}
                expires = []
                for trip in active_trips(session, now):
                    state = effective_state(trip, now)
                    if state["source"] == "estimate" and state.get("transition"):
                        expires.append(parse(state["transition"]["deadline"]))
                    elif state["source"] in {"wsn", "crowd", "fused"} and state.get("last_observed_at"):
                        age_limit = settings.sensor_max_age_seconds if state["source"] == "wsn" else settings.crowd_max_age_seconds
                        expires.append(parse(state["last_observed_at"])+timedelta(seconds=age_limit))
                    for arrival in arrivals_for(trip, now):
                        grouped.setdefault(arrival["station_id"], []).append(arrival)
                community=signals(session,now)
                expires.extend(parse(signal["expires_at"]) for signal in community)
                snapshot_cache = {"created": time.monotonic(), "now": now, "stations": grouped, "expires_at": min(expires, default=None),
                                  "community_signals":community}
        now = snapshot_cache["now"]
        arrivals = [item for item in snapshot_cache["stations"].get(station_id, [])
                    if (line_id is None or item["line_id"] == line_id) and (direction is None or item["direction"] == direction)]
        arrivals.sort(key=lambda arrival: arrival["remaining_seconds"])
        return {"station_id": station_id, "arrivals": arrivals[:20], "generated_at": iso(now),
                "schema_version": 1, "snapshot_version": int(now.timestamp()*1000), "simulated": settings.synthetic_data,
                "data_status": "available" if arrivals else "no_scheduled_service",
                "community_signals":[s for s in snapshot_cache["community_signals"] if s["station_id"]==station_id],
                "alerts": [{"id": "delay-"+arrival["trip_id"], "trip_id": arrival["trip_id"], "line_id": arrival["line_id"],
                            "title": f"{arrival['train_code']} delayed", "delay_seconds": arrival["delay_seconds"],
                            "source": arrival["source"], "freshness_status": arrival["freshness_status"]}
                           for arrival in arrivals if arrival["delay_seconds"] >= 60 and arrival["source"] != "schedule"]}


@app.get("/api/v1/eta/{station_id}")
def eta(station_id: str, request: Request, line_id: str | None = None, direction: str | None = None):
    limit(client_identity(request), "public_eta", 120)
    return eta_snapshot(station_id, line_id, direction)


@app.get("/api/v1/trips")
def trips():
    with Session() as session:
        return {"trips": [{"id": trip.id, "code": trip.code, "line_id": trip.line_id,
                            "direction": trip.direction, "state": effective_state(trip, utcnow()), "version": trip.version}
                           for trip in active_trips(session, utcnow())], "simulated": settings.synthetic_data}


@app.get("/api/v1/source-status/{trip_id}")
def source_status(trip_id: str):
    with Session() as session:
        trip = session.get(Trip, trip_id)
        if trip is None or trip.line_id not in LINE_MAP:
            raise HTTPException(404, "Unknown trip")
        decisions = session.scalars(select(Decision).where(Decision.trip_id == trip_id).order_by(Decision.id.desc()).limit(12)).all()
        return {"trip_id": trip_id, **effective_state(trip, utcnow()), "version": trip.version, "confidence_kind": "heuristic_trust",
                "simulated": settings.synthetic_data, "decisions": [{"at": d.at, "source": d.source, "reason": d.reason, "scores": d.scores} for d in decisions]}


@app.get("/api/v1/routes")
def journey_routes(request: Request, origin: str, destination: str, departure_time: datetime | None = None,
                   preference: Literal["fastest","fewest_changes","least_walking","shortest_distance"]="fastest"):
    limit(client_identity(request), "route_search", 30)
    now = utcnow()
    if departure_time and departure_time.tzinfo is None:
        raise HTTPException(422, "Departure time must include a timezone")
    if departure_time and not -60 <= (departure_time-now).total_seconds() <= 7*86400:
        raise HTTPException(422, "Choose a departure within the next seven days")
    try:
        return journey_snapshot(origin,destination,preference,departure_time)
    except ValueError as error:
        raise HTTPException(404,str(error)) from error


journey_cache = {}
journey_lock = threading.Lock()


def journey_snapshot(origin, destination, preference="fastest", departure_time=None):
    """REST and WebSocket publish the same bounded, versioned journey snapshot."""
    key=(origin,destination,preference)
    with journey_lock:
        now=utcnow()
        cached=journey_cache.get(key) if departure_time is None else None
        if (cached and time.monotonic()-cached["created"]<2
            and 0<=(now-parse(cached["snapshot"]["generated_at"])).total_seconds()<2
            and (cached["expires_at"] is None or now<cached["expires_at"])):
            return cached["snapshot"]
        with Session() as session:
            if CONFIG and CONFIG.get("journey_planning"):
                from .journey_planner import journey_routes as plan_journey
                response=plan_journey(session,origin,destination,departure_time or now,now,preference)
            else:
                response=routes(session,origin,destination,departure_time or now,now)
        response.update(origin=origin,destination=destination,preference=preference,
                        generated_at=iso(now),schema_version=1,snapshot_version=int(now.timestamp()*1000))
        if departure_time is None:
            expires=[parse(status["valid_until"]) for route in response["routes"] for status in route.get("source_statuses",[])
                     if status.get("valid_until")]
            if response.get("rerouting",{}).get("valid_until"):
                expires.append(parse(response["rerouting"]["valid_until"]))
            if len(journey_cache)>=64:
                oldest=min(journey_cache,key=lambda item:journey_cache[item]["created"])
                del journey_cache[oldest]
            journey_cache[key]={"created":time.monotonic(),"expires_at":min(expires,default=None),"snapshot":response}
        return response


@app.get("/api/v1/events")
def events(request: Request, limit: int = Query(default=30, ge=1, le=100)):
    identity(request, admin=True)
    with Session() as session:
        return {"events": [{"event_id": row.event_id, "source": row.source, "trip_id": row.trip_id,
                             "observed_at": row.observed_at, "received_at": row.received_at,
                             "status": row.status, "reason": row.reason, "attempts": row.attempts}
                            for row in session.scalars(select(Observation).order_by(Observation.received_at.desc()).limit(limit)).all()]}


@app.get("/api/v1/events/{event_id}")
def event_status(event_id: str, request: Request):
    with Session() as session:
        row = session.get(Observation, event_id)
        if settings.app_env != "test":
            user = identity(request)
            owner=row.payload.get("contributor_id") if row and row.source=="surface_crowd" else row.payload.get("authenticated_contributor") if row else None
            if row is None or owner != user.id and user.role != "admin":
                raise HTTPException(404, "Unknown event")
        if row is None:
            raise HTTPException(404, "Unknown event")
        return {"event_id": row.event_id, "status": row.status, "reason": row.reason}


# Simulation routes do not exist in local or production applications.
if settings.app_env == "test":
    from .simulator import set_scenario

    @app.get("/api/v1/demo/status")
    def demo_status():
        with Session() as session:
            control = session.get(Runtime, "control")
            return {**control.value, "simulated": True} if control else {"scenario": "normal", "simulated": True}

    @app.post("/api/v1/demo/scenario")
    def demo_scenario(payload: ScenarioRequest, x_api_key: Annotated[str | None, Header()] = None):
        require_key(x_api_key, settings.admin_api_key)
        if not settings.simulation_enabled:
            raise HTTPException(403, "Simulator disabled")
        with transaction() as session:
            return set_scenario(session, payload.scenario, utcnow())


ws_connections = 0


@app.websocket("/ws/journeys")
async def websocket_journey(socket: WebSocket):
    global ws_connections
    origin=socket.query_params.get("origin","")
    destination=socket.query_params.get("destination","")
    preference=socket.query_params.get("preference","fastest")
    browser_origin=socket.headers.get("origin")
    if (origin not in STATION_MAP or destination not in STATION_MAP or origin==destination
        or preference not in {"fastest","fewest_changes","least_walking","shortest_distance"}
        or browser_origin and browser_origin not in settings.cors_origins.split(",")):
        await socket.close(code=1008)
        return
    if ws_connections>=settings.max_ws_connections:
        await socket.close(code=1013)
        return
    ws_connections+=1
    try:
        await socket.accept()
        while True:
            snapshot=await asyncio.to_thread(journey_snapshot,origin,destination,preference)
            await socket.send_json({"type":"journey_snapshot",**snapshot})
            try:
                incoming=await asyncio.wait_for(socket.receive_text(),timeout=2)
                if len(incoming)>1024:
                    await socket.close(code=1009)
                    break
            except asyncio.TimeoutError:
                pass
            else:
                await asyncio.sleep(2)
    except (WebSocketDisconnect,RuntimeError):
        pass
    except (SQLAlchemyError,ValueError):
        await socket.close(code=1013,reason="Journey updates temporarily unavailable")
    finally:
        ws_connections-=1


@app.websocket("/ws/eta/{station_id}")
async def websocket_eta(socket: WebSocket, station_id: str):
    global ws_connections
    origin = socket.headers.get("origin")
    if station_id not in STATION_MAP or origin and origin not in settings.cors_origins.split(","):
        await socket.close(code=1008)
        return
    if ws_connections >= settings.max_ws_connections:
        await socket.close(code=1013)
        return
    ws_connections += 1
    try:
        await socket.accept()
        while True:
            await socket.send_json({"type": "snapshot", **await asyncio.to_thread(eta_snapshot, station_id)})
            try:
                incoming = await asyncio.wait_for(socket.receive_text(), timeout=2)
                if len(incoming) > 1024:
                    await socket.close(code=1009)
                    break
            except asyncio.TimeoutError:
                pass
            else:
                await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except SQLAlchemyError:
        await socket.close(code=1013, reason="Service temporarily unavailable")
    finally:
        ws_connections -= 1


@app.get("/api/v1/system")
def system_status():
    from .ml_prediction import model_status
    return {"architecture":"context-aware-source-router", "software_inputs":True,
            "hardware_enabled":settings.hardware_enabled,"live_report_ttl_seconds":settings.service_report_max_age_seconds,
            "phone_inputs":["foreground_location","reviewed_android_cell_fingerprints"],
            "synthetic":settings.synthetic_data, "engines":[
                {"reference":106,"name":"Context-Aware Data Source Router"},
                {"reference":108,"name":"Context Determination Engine"},
                {"reference":110,"name":"Dynamic Trust Engine"},
                {"reference":112,"name":"Backend Switching Engine"},
                {"reference":114,"name":"Transition Arbitration Engine"},
                {"reference":116,"name":"Prediction Engine"},
                {"reference":118,"name":"Output Interface"},
                {"reference":120,"name":"Data Acquisition Interface"}],
            "transition_seconds":settings.transition_seconds,"prediction":model_status()}


if settings.app_env == "software":
    @app.get("/api/v1/software/status")
    def software_status():
        from .software_feed import control_status
        with Session() as session:
            return control_status(session,utcnow())

    @app.post("/api/v1/software/scenario")
    def software_scenario(body: SoftwareScenarioRequest, request: Request):
        from .auth import origin_check
        from .software_feed import change_scenario
        origin_check(request)
        if request.client.host not in {"127.0.0.1","::1"}:
            raise HTTPException(403,"Software controls are local-only")
        limit(client_identity(request),"software_controls",30)
        with transaction() as session:
            return change_scenario(session,body.scenario,utcnow())
