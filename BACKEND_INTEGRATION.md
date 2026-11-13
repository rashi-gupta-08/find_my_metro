# Backend integration in the passenger web app

> **Current scope — 16 October 2026:** See [the software implementation update](docs/SOFTWARE_IMPLEMENTATION_2026-10-16.md) for the current software-only application. Service reports now cover surface and underground stations, expire after 30 seconds and support typed updates/rewards. Flutter uses the new passenger planner. Hardware/WSN integration below describes the preserved earlier version, not a dependency or release requirement of the current app.

The pasted backend plan is connected to the local React journey planner. It uses the existing FastAPI API, PostgreSQL event store and processing worker. Changes remain local.

## Data flow

`HTTP/MQTT WSN events or authenticated trip reports → acquisition → durable observations → worker validation → trip state → context/trust/switching/arbitration → prediction → journey/ETA snapshots → web app`

GPS station delay reports also enter the durable worker. They establish a short-lived station service signal after agreement; they never manufacture an identified train. The planner adds qualified service delay once at boarding and displays its source separately from train predictions.

## Plan-to-code mapping

| Plan component | Implementation | Passenger integration |
|---|---|---|
| API gateway and acquisition | `backend/app/main.py`, `auth.py`, `security.py`, `acquisition.py`, `mqtt.py` | Same-origin API, authenticated reporting, device credentials, validation and durable acknowledgements |
| Context and dynamic trust | `context_switching.py`, `engines.py` | Selected train context, source scores and heuristic trust feed journey status |
| Stable switching and arbitration | `context_switching.py`, `worker.py` | Underground/surface selection, bounded transition estimate, decay and deadline fallback |
| Prediction | `prediction.py`, `ml_prediction.py`, `forest_inference.py` | Accepted-state next arrivals and model version; deterministic fallback when a model is missing/unusable |
| Storage and audit | `models.py`, `db.py`, Alembic migrations | Event history, processing retries, trip state, deadlines and decision history |
| Journey alternatives | `journey_planner.py`, `routing.py`, `surface_reports.py` | Four route preferences, walking/interchange detail and fresh delay counted once |
| Output and reconnection | `main.py`, `frontend/src/useJourney.ts`, `JourneyLiveStatus.tsx` | REST snapshot, WebSocket updates, complete refresh after reconnect, saved journey age |

The app shows planned route geography separately from the approaching train's accepted context. A train approaching a surface station may still be underground; its source is selected by its accepted position, not by the passenger's destination.

## Journey interface

- `GET /api/v1/routes?origin=<station>&destination=<station>&preference=fastest`
- `WS /ws/journeys?origin=<station>&destination=<station>&preference=fastest`

Both return the same journey snapshot with `schema_version`, `snapshot_version`, `generated_at`, routes and boarding `source_statuses`. A status includes source, evidence scope, planned/train context, trust, freshness, observation age, expiry, decision reason, model version, arbitration/deadline and an identified next arrival when available.

The next service follows predicted arrival order. A later high-trust train cannot displace the nearest service merely because it has a larger score. Estimate/observation expiry is checked before applying it to a boarding point. Snapshot caching cannot extend an evidence deadline; advancing or reversing the wall clock invalidates an unsuitable cached snapshot.

The existing network, sensor, trip crowd-report, station ETA, source-status, health and station ETA WebSocket interfaces remain available. Journey sockets share the station sockets' connection limit. The local frontend proxy and container nginx configuration support journey WebSocket upgrades.

## Current inputs and limits

The passenger database contains the operator station catalogue and indicative travel-time baseline. It has no connected live operator trip feed or commissioned WSN gateway. Therefore the passenger app does not invent next arrivals or live positions. Accepted surface service reports can affect current journey estimates. Imported identified services and qualified trip events use the full patent pipeline.

The static route duration excludes ordinary boarding wait, station access and security. Walking distances are estimates. An identified upcoming arrival is displayed separately. Route search returns up to eight useful alternatives, rather than enumerating every possible detour.

Prophet/Random Forest candidate training and JSON inference are implemented. Synthetic training artifacts remain restricted to isolated software validation; an operator model requires independent validation before enabling it. Confidence is heuristic, not a calibrated probability. MQTT configuration, Firebase notification configuration, physical hardware commissioning and field model accuracy remain separate integration work. Kafka and Redis remain the later expansion from the supplied plan.

## Local use

Run `scripts/start.ps1`, open <http://localhost:5173/>, select stations and choose **Find my route**. Expand a journey to inspect **Journey source status**. **Report** requires sign-in and captures GPS once. The Tracking page retains detailed trip decisions when an identified service exists.

Hardware interfaces and schemas remain in `hardware/`. The separate software profile and its replay scenarios remain available through `scripts/start.ps1 -Software`; generated observations never enter the passenger profile. Backend tests use isolated SQLite/PostgreSQL databases. Browser tests use read-only passenger requests and intercepted report responses.

The hardware-deferred software completion adds private report history (`GET /api/v1/surface-reports/mine`), automatic account-scoped upload retry, offline app-shell reload, session recovery and opt-in foreground journey notifications. `scripts/test-crowdsourcing.ps1` exercises actual registration/ingestion/worker/WebSocket processing in a new isolated test stack on this computer, using three browser sessions and explicit test GPS. No generated report reaches the passenger database. See `SOFTWARE_COMPLETE.md` for the finished local software checklist and remaining data-dependent integrations.
