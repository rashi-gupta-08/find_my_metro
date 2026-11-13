# FindMyMetro

The [software implementation update](docs/SOFTWARE_IMPLEMENTATION_2026-10-16.md), dated 16 October 2026, records the changes made against your synopsis and Evaluation-0/Evaluation-2 materials. The app now supports software-only station reporting, strict 30-second live evidence, contribution rewards, rerouting thresholds, Aqua offline routes and a redesigned Flutter passenger flow. Hardware ingestion is disabled by default. The earlier [redesign specification](docs/SOFTWARE_ONLY_REDESIGN.md) remains design history; its private onboard journey sessions are still a separate unfinished extension.

FindMyMetro runs the web passenger app, a Flutter/Dart client, FastAPI API, PostgreSQL database and durable processing worker on your local machine. The backend retains the earlier context, trust, switching and arbitration modules; the active passenger flow uses station-service evidence and static section timings. Private onboard passenger tracking remains a separate extension.

**The default running app is a passenger journey planner using a locally stored, operator-sourced Delhi/Noida station catalogue.** Search source and destination across both operators, compare shortest time, fewer interchanges, less walking and shortest distance, and expand every station and walking connection. The catalogue currently contains 265 stations and 14 ordered line paths. Travel times are static indicative estimates, not current train departures. Walking distances are explicitly approximate.

Station service reports use account authentication, one-time location proximity checks, original observation timestamps and three-account agreement. Qualified community delays can update route estimates at boarding for both surface and underground stations; every participating report must be less than 30 seconds old. Without qualified evidence, the operator segment baseline remains active. Typed arrival/departure/crowding reports remain separate from delay measurements. No phone report creates or moves an operator train. Direct Android cell assistance requires a reviewed station map; none has been supplied.

The original GitHub repository contained only a README and license. This local frontend was built using the published Lovable design as a reference; it is not an export of the hosted site's source. Nothing has been pushed or published. Earlier simulated data remains preserved in `data/metro.db` and is not used by the running app.

## Start and stop on this Windows machine

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
powershell -ExecutionPolicy Bypass -File scripts/stop.ps1
```

Open [the web app](http://localhost:5173) or [API documentation](http://localhost:8000/docs). Choose any source/destination in the catalogue, select a route preference and click **Find my route**. **Report** opens the station-update form after sign-in. Journey updates arrive over WebSocket, with REST retrieval after reconnect and a polling fallback. Saved journeys display their age while offline. Aqua Line routes can also be calculated for a new station pair from the saved catalogue, with live delays excluded.

**The software is ready for local crowdsourcing tests without hardware.** Signed-in passengers can view private report outcomes in **My reports** on Home or Alerts: processing, agreement, rejection, historical and expired. Offline uploads retry automatically while the app is open, retain original IDs/times and stay scoped to the signed-in account. The built app caches its public shell so it can reload offline; saved journeys remain labelled with age. API responses, login sessions and GPS reports are not placed in the service-worker cache. Opt-in browser notifications cover fresh delays on the selected journey while the app is open.

For this computer, run `& .\scripts\test-crowdsourcing.ps1` from the project folder. It launches three independent browser sessions, the actual API and worker on separate loopback ports, and a new isolated test database. It checks the normal report form, GPS rejection, three-account agreement, route updates, duplicate handling, automatic offline retry and offline reload. It uses explicit test GPS coordinates and never adds fake reports to the passenger database. Playwright and Chrome are required; the script detects this workstation's bundled Playwright. See `SOFTWARE_COMPLETE.md` for the checklist and commands.

Expanded journeys include a **Journey source status** panel for every boarding point. It connects the worker's accepted source and prediction output to the passenger route: static/phone evidence underground, validated crowd evidence at either station type, source freshness and any separately identified upcoming arrival. The train's current accepted context is separate from the route's planned sections. Station service reports are explicitly separate from identified train predictions; static data never creates a next-train arrival. Accepted delays are counted once at boarding. The static route duration still excludes the ordinary boarding wait, access and security; an identified next arrival is shown separately.

`GET /api/v1/routes` and `WS /ws/journeys?origin=...&destination=...&preference=fastest` share a versioned journey snapshot. The existing station ETA WebSocket, source-status API, authenticated ingestion, processing worker and decision history remain connected. Snapshot caching expires at the evidence or arbitration deadline and does not extend its freshness. Refresh requests reuse a bounded shared cache; each connection is covered by the existing WebSocket connection limit.

The default serves the web app. The optional Flutter client can be built/started with `-Mobile`; it now starts with the passenger journey planner, defaults to the 21-station Aqua scope, includes report/reward flows and computes Aqua static routes offline. `-Software` runs the isolated fictional validation network in a separate database. Its developer controls are available only at `/?developer=1`. See `SOFTWARE_RUN.md` for that separate test profile.

The startup script builds the web frontend, applies migrations and starts the API and worker. It serves compiled assets, records process IDs and exact start times, and stops only its own process trees. Stop first before restarting. Omitting `-Software` runs operator mode against the original database; omitting `-Mobile` runs only the web client.

This installation uses the existing PostgreSQL 16.15 binaries and a separate cluster at `D:/FindMyMetro-local-runtime/postgres-data`, listening only on `127.0.0.1:5433`. Other installed PostgreSQL databases are untouched. Private configuration is in the ignored `.env`; cluster location is in the ignored `.local/database.json`. Migration and runtime database accounts are separate. The runtime role cannot create tables or modify schema.

Python 3.12 and Node.js 24 are used here. The startup script reuses the parent directory's isolated Python environment. On another machine, configure PostgreSQL connection URLs in `.env` or use Compose. A SQLite fallback exists for local tooling and isolated tests; the production profile rejects SQLite.

## Accounts and reporting

Create your own account through Sign in / Create account. Passwords use Argon2id. Revocable sessions use HttpOnly cookies; production enables Secure cookies with the `__Host-` prefix. Mutations require a permitted Origin and a session-bound CSRF token. Accounts cannot choose administrator or verified contributor status during registration.

Sightings use an explicitly requested, one-time device location. Route distance and contributor identity are assigned by the server. Reports with imprecise location, wrong association, invalid timestamps or conflicting IDs cannot change train state. Browser queues are account-scoped, limited to 100 reports, retain original observation times and expire after 24 hours. Signing out clears that account's queued reports. Reports and locations on the server are retained for up to 30 days, with hourly expiry processing.

Identified train sightings require an operator-verified contributor before influencing train state. Separate station service-delay reports can establish an explicitly community-reported signal after three authenticated accounts agree; this does not establish an operator-confirmed delay or a train identity. Account-level agreement is not proof of three unique people; real public rollout needs independently verified enrollment and abuse monitoring. Password change revokes all sessions. Account deletion requires the current password and removes sessions and owned reports. Recovery is currently administrator-assisted; no email/SMS service is assumed.

From an operator-controlled terminal, after creating the account in the app:

```powershell
python -m backend.app.manage promote-admin YOUR_USERNAME
python -m backend.app.manage verify-contributor VERIFIED_USERNAME
python -m backend.app.manage reset-password YOUR_USERNAME
python -m backend.app.manage disable-user USERNAME
```

These changes are audited. Password recovery prompts for the new password without echoing it. Promotion revokes existing sessions; sign in again to use administrator features. Protect console access and `.env` as privileged operator access.

## Connect Delhi Metro and Noida Metro data

The included catalogue was assembled from the [DMRC passenger website](https://delhimetrorail.com/map), its public station and journey APIs, the [NMRC station list](https://www.nmrcnoida.com/StationList) and [NMRC journey planner](https://www.nmrcnoida.com/Passenger-Information/Journey-Planner-and-Fares). The official [Delhi OTD metro feed](https://otd.delhi.gov.in/data/staticDMRC/) exists separately from its bus feeds, but is dated. Only historical NMRC coordinates were taken from a documented mirror of that metro feed; its expired timetable is never presented as today's trains.

`data/operator-network.json` includes source attribution, scope, retrieval date and a content-dependent version. It covers open stations returned by the retrieved DMRC passenger API and all 21 NMRC stations, including the explicit Sector 52/Sector 51 walking connection. Rapid Metro Gurugram is outside this Delhi/Noida catalogue. Station-to-station geometry approximates track alignment; replace it and the walking measurements before field hardware/GPS train tracking.

To rebuild the catalogue from public passenger information:

```powershell
python -m scripts.import_operator_network
```

Responses are cached in `.local/research` to avoid unnecessary operator requests. For a fresh import, rename that research folder and rerun, then review the resulting topology and restart both processes. The importer checks adjacent journey responses and never silently inserts a guessed travel time. No authorized operator live tracking feed is connected.

Obtain an operator-approved topology and dated timetable, and transform them into the supplied contracts. JSON schemas are in `hardware/contracts/network.schema.json` and `hardware/contracts/timetable.schema.json`; the corresponding Pydantic contracts are in `backend/app/provider_contracts.py`.

```powershell
python -m backend.app.manage install-network path/to/approved-network.json
```

Set `NETWORK_FILE=.local/provider/network.json` in `.env`, then restart the API and worker. For containers set `CONTAINER_NETWORK_FILE=/app/provider/network.json`. Network installation is atomic; processes load one consistent network version at startup.

Each line has an explicit `operator_id` (`dmrc` or `nmrc`), ordered stations, per-segment geometry, track distances, durations, zone type and dwell time. Station coordinates and geometry endpoints must agree. Hardware checkpoints are explicitly registered. Represent branches as separate directional paths. External walking connections, including connections between different operators, require configured station IDs, walking time and an exit/re-entry flag; the app does not infer a connection or duration from proximity.

Import dated trips through the administrator account's timetable import control, the CSRF-protected `POST /api/v1/operator/timetable` endpoint, or:

```powershell
python -m backend.app.manage import-timetable path/to/dated-timetable.json
```

A timetable batch includes the matching network version, immutable trip IDs, line, direction and ordered stop arrival/departure times with timezone offsets. Times normalize to UTC. Existing trip IDs cannot be reassigned to another journey. Cancellation removes a service from arrivals and routing. No repeating headway service is generated when a timetable is missing. Current contracts require a complete directional path; express services with skipped stops, platform boarding restrictions and varying service calendars need an extended contract before use.

The public static journey catalogue adapter is implemented. An operator-specific live feed and current dated service calendar are not connected. Route estimates therefore exclude scheduled boarding waits, security and station access; current train departures are not fabricated.

## Hardware

Provision only nodes present in the approved network:

```powershell
python -m backend.app.manage provision-device NODE_ID
python -m backend.app.manage revoke-device NODE_ID
```

A provisioned device key is displayed once. Keep it in the device's secret storage, never frontend code. `POST /api/v1/sensor-events` checks that key against the claimed node. A checkpoint must belong to the trip's line and direction. Physical presence alone cannot establish train identity or speed: an approved gateway must associate actual observations with operator trip IDs, and successive known checkpoints are required to derive speed.

For MQTT, configure a TLS broker, CA/server certificates and distinct device credentials. `hardware/mosquitto.conf` and `hardware/acl` provide TLS-only settings, packet limits, device topic scoping and a read-only ingestion identity. The adapter is disabled until configured, and acknowledges messages only after durable storage. MQTT is not started by the default local stack; broker TLS and actual device drivers have not been field-tested.

`python -m hardware.publish_sensor ACTUAL_EVENT.json` forwards an actual recorded event. Supply `METRO_DEVICE_KEY` privately in the environment for HTTP, or TLS broker credentials for MQTT. This tool does not generate sightings, train identities or timestamps.

## Reliability and prediction

HTTP acknowledgement follows durable storage. Event IDs deduplicate delivery, per-trip locking protects state, failed jobs retry with backoff and reach a dead-letter state after five attempts. PostgreSQL advisory locking elects one processing leader. A replacement worker retains the original transition deadline. Source decisions, event outcomes and prediction history are retained for audit.

Switching uses context, source health, age, qualified independent agreement, hold time and confirmation margins. Transition estimates remain bounded by the next station and expire at their original deadline. Output freshness is enforced even when the worker stops. The API shares a two-second network snapshot among station clients so subscriptions do not multiply full-network calculations.

Prediction supports a Prophet historical baseline and a scikit-learn Random Forest correction, trained offline and served through validated JSON artifacts. The software profile currently uses a model trained on synthetic journeys with separate chronological training, validation and test groups. Missing, invalid, expired or unapproved models fall back to the deterministic baseline. Synthetic models are blocked in operator and production modes. Confidence remains heuristic trust; no field ETA accuracy is claimed.

Training checks feature availability and ground-truth outcome cutoffs, normalizes timezone offsets, and rejects overlapping journey partitions. A candidate must beat the strongest validation baseline among schedule, historical and Prophet estimates. Actual-history training requires timestamped provenance and the network's nominal segment duration; the synthetic fixture's 30-second segment duration is not assumed for Delhi/Noida.

## Containers and production profile

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Docker
```

Compose starts PostgreSQL with separate migration/runtime roles, a one-shot migrator, API, worker and a non-root nginx frontend. Services have restart policies, health checks, read-only application filesystems and dropped capabilities. Database ports stay private. Credentials must be installation-specific and supplied through private configuration. Containers were configuration-validated here; Docker Desktop's Linux engine was unavailable for runtime verification.

For deployment behind a configured HTTPS ingress, use `compose.production.yaml` with `PUBLIC_ORIGIN`, `PUBLIC_HOST`, strong secrets and the approved provider file. The production profile rejects simulation, insecure browser cookies, non-HTTPS origins, wildcard hosts and SQLite. API documentation is disabled. Do not expose the local HTTP ports directly as a public service.

`TRUSTED_PROXY_CIDRS` defaults to empty. Configure only the actual trusted last-hop proxy addresses; that hop must replace `X-Forwarded-For` with one verified client IP. Configure ingress real-IP handling and test it before release, otherwise users behind the same proxy share IP limits. Container log rotation is configured; establish infrastructure monitoring, and establish encrypted off-machine backups with a tested restore and incident owner.

## Database backups

```powershell
python -m scripts.backup_database backup .local/backups/metro-YYYY-MM-DD.dump
python -m scripts.backup_database restore-new-database .local/backups/metro-YYYY-MM-DD.dump --database EMPTY_RESTORE_DATABASE
```

The tool refuses to overwrite an existing archive or restore over the application's database or a non-empty target. Copy archives to encrypted off-machine storage; this local script does not provide an off-site backup service.

## Verification

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test.ps1
```

The browser check is `scripts/production-browser-check.cjs` and needs Playwright plus Chrome. It creates and deletes only its own verification account. PostgreSQL test runs use an isolated database supplied by `TEST_DATABASE_URL`; never set this to the application database because test fixtures recreate tables.

See `VERIFICATION.md` for measured results and `IMPLEMENTATION_STATUS.md` for the remaining release gates. No push, public deployment or external account integration has been performed.

## Crowdsourcing beta dataset

The [synthetic beta pack](data/beta/crowdsourcing/README.md) contains 461 report deliveries from 48 fictional accounts, with 47 scenarios and 73 expected time checkpoints. CSV files are readable in Excel; JSON drives repeatable replay. This is controlled software-test data, not collected passenger data or measured metro arrival outcomes.

```powershell
.\scripts\test-crowd-beta.ps1
```

Replay uses a newly created isolated database, the actual API/worker and a virtual clock. It never opens the passenger database or sends synthetic reports to the running app. Review `artifacts/crowdsourcing-beta/latest-report.html` afterward. See the pack README for coverage, replay limits and the separate walk-first inter-operator route gap identified during preparation.
