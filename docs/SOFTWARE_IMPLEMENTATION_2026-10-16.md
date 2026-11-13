# FindMyMetro: software implementation update

Updated 16 October 2026. This records application changes made against the supplied **FindMyMetro Synopsis Final v5**, **FindMyMetro Evaluation 2**, and **Evaluation-0 Project PPT final V2**. Numerical evaluation criteria are targets until independently measured. This update supersedes earlier hardware-dependent startup and reporting instructions.

## What runs locally

| Application | Address | Purpose |
| --- | --- | --- |
| React web app | http://localhost:5173 | Delhi/Noida station search, route comparisons, community updates, reports and contribution points |
| Flutter web client | http://localhost:5174 | New passenger journey interface, Aqua offline routing, account/report flow and phone-evidence availability |
| FastAPI documentation | http://localhost:8000/docs | Local API contracts |
| PostgreSQL and worker | Local services | Durable acknowledgement, validation, rewards and recoverable processing |

No remote repository changes, publishing or cloud deployment were performed. Existing passenger accounts and stored events were preserved. Before migration `0005`, the local PostgreSQL database was backed up to `.local/backups/before-software-0005.dump`. This is a local operational backup containing private data; do not publish it.

```powershell
# From the find_my_metro project folder:
.\scripts\start.ps1 -Mobile -SkipInstall
.\scripts\stop.ps1
```

Stop the current app before starting it again. `-SkipInstall` reuses an already prepared Python environment; omit it on first setup. The separate `-Software` profile remains an explicitly synthetic legacy test network and is not the passenger data source.

## Changes to the previous application

| Area | Current behavior |
| --- | --- |
| Hardware dependency | Sensor HTTP ingestion returns 410 outside tests while `HARDWARE_ENABLED=false`. No gateway, MQTT broker, controller, track sensor or hardware feed is required by the passenger app. Historical schemas and isolated sensor tests remain for recoverability. |
| Geographic context | Route segments retain their configured underground, transition and surface zones. Losing GPS alone does not classify a station as underground. |
| Underground | Operator segment timing remains the baseline. Accurately located, independently agreed station reports may add a short-lived service delay. The Android channel can supply cell fingerprints for a reviewed station map. No usable evidence means static timing. |
| Surface | Foreground location, station proximity and account-level agreement qualify community reports. A phone position does not create an operator train or live train identity. |
| Mixed journeys | Each boarding point uses its own zone and available evidence. A station extra wait is counted once at boarding, not on every following segment. Expired evidence returns to baseline. |
| Report types | `delayed`, `arrived`, `departed`, `crowded`. Types form separate agreement groups. Arrival, departure and crowding reports never become zero-delay measurements that overwrite reported extra waiting. |
| Freshness | Service reports must be less than 30 seconds old. The 120-second collection limit does not revive expired evidence. Existing identified-trip tests have a separate legacy policy. |
| Consensus | At least three distinct active accounts, same station, ordered line, direction and report type; accepted delay values must fit a 60-second agreement band. Repeat reports from one account add no independent confirmations. |
| Route changes | Return a switch suggestion when a validated delay is greater than 180 seconds and a feasible faster alternative saves at least 120 seconds. Otherwise return the reason, including no faster alternative. |
| Points | Ten points after independent account agreement. Unique event key prevents duplicate rewards; a five-minute station/line/direction cooldown limits repeat submissions. Badges at 1, 10 and 50 awarded contributions. This rewards community agreement, not operator-verified truth or unique-person identity. |
| Offline | The web app computes new Aqua routes from its saved catalogue. Flutter bundles all 21 Aqua stations and indicative segment times and computes static routes without contacting the backend. Expired or disconnected live delays are removed from displayed totals. |
| Mobile interface | Flutter starts with source/destination and four route preferences. Includes full station details, source/age information, typed reports, private outcomes, rewards and an optional phone-signal check. |

The full stored Delhi/Noida catalogue is retained: 265 station records and 14 ordered line paths. Aqua Line is a selectable Phase 1 scope. The connected catalogue is Phase 2 coverage for route comparison, not a claim that all current operator services or every possible detour are covered. Search returns a bounded set of loop-free alternatives. An Aqua-only corridor can legitimately have no alternative metro route.

## API additions and data handling

| Interface | Contract |
| --- | --- |
| `POST /api/v1/reports/batch` | Authenticated, CSRF-protected uploads; original UTC observation time, event ID, station, line, direction, type and location evidence. Existing `/surface-reports/batch` is a deprecated compatibility alias. |
| `GET /api/v1/reports/mine` | Private validation/rejection/agreement/expiry outcomes, receipt and validation times; no public coordinates. Old surface-history path remains an alias. |
| `GET /api/v1/contributions/mine` | Own points, awarded contribution count, badges and award policy. |
| `GET /api/v1/offline-bundle` | Versioned Aqua station graph and indicative segment timing, live lifetime and optional reviewed cell map. Does not manufacture dated departures or a GTFS timetable. |
| `POST /api/v1/phone-context` | Authenticated fresh cell fingerprints and relevant route station IDs; returns a qualified station hint or explicit unmapped/ambiguous status. It does not update train state. |
| `GET /api/v1/routes`, `WS /ws/journeys` | Shared snapshots now include rerouting reason, minimum saving and actual suggested-route identifier when qualified. |

PostgreSQL migration `0005` adds a nullable `validated_at` on observations and a contribution ledger with user-deletion cascade. Existing tables, accounts and observations are retained. Durable event acknowledgement and worker retries remain transactional. Failed events stay auditable. Points are awarded in the processing leader's transaction and survive raw-event retention.

Validation records `received_at` and `validated_at`; qualified service output includes `quorum_available_at` and `predicted_at`. A full correlated client-render latency report is still an evaluation task: these timestamps alone do not establish the presentation's under-30-second performance result.

## Android cell support: implementation and limits

Flutter calls a Kotlin method channel on a foreground action. The Android collector requires precise-location permission, requests available GSM/WCDMA/LTE/NR information and rejects cached samples aged 30 seconds or more. It hashes radio identifiers on the phone; it never returns IMSI, IMEI, a phone number or subscriber ID. Hashes remain location-derived data and are treated as private report evidence.

The backend requires two separately mapped fingerprints agreeing on one relevant station, a reviewed map with provenance, and suitable accuracy. A generic cell reading is not proof of a station, train or passenger journey. It is possible for a phone to expose too few cells or no fresh cells. The normal fallback is static timing.

No field cell map was supplied. The bundled map is intentionally empty and reports **unmapped**. The 8 MiB value is a budget, not the size of an existing station fingerprint dataset. The bundle currently occupies only a few kilobytes because it contains the station graph and no invented map.

This computer has Flutter and Java but **no Android SDK or connected Android device**, according to the local Flutter toolchain check. Dart analysis/tests and Flutter web build are verified; the Kotlin channel has not been APK-compiled or field-tested. After installing Android SDK components and connecting a test phone, run:

```powershell
.\scripts\build-android.ps1 -AndroidSdk 'PATH_TO_YOUR_ANDROID_SDK'
# With adb available and a USB-authorized phone:
adb reverse tcp:5173 tcp:5173
```

The script builds a debug APK that connects to this computer over USB forwarding. Release signing, HTTPS server access and Play Store delivery are separate steps. A debug APK has not been built on this machine.

## Requirements and remaining gates

| Requirement from the supplied deck | Implementation / remaining verification |
| --- | --- |
| FR1 capture and FR2 validation | Typed schema, location checks, freshness, distinct accounts, duplicate/conflict handling, durable validation and private history implemented. |
| FR3 Prophet + Random Forest ETA | Existing candidate training and safe JSON inference remain available for isolated identified-trip evaluation. Default passenger routes use indicative timing plus qualified service delays. No independently labelled field history, validated production hybrid artifact or real ETA RMSE result exists. |
| FR4 distribution and FR7 freshness | REST/WebSocket, original timestamps, strict evidence expiry, offline source labels and opt-in foreground browser notifications implemented. FCM closed-app push and full rendered-latency evaluation remain unconfigured. |
| FR5 rerouting | Thresholds, bounded alternatives, single-count delay and explicit no-alternative outcome implemented. The 20% delay-impact improvement is a measurement target, not a demonstrated general result. |
| FR6 offline | Static Aqua routes work for all 21 stations in both directions in both web and Flutter clients. The bundle is not a dated GTFS feed. Cell coverage and actual airplane-mode device tests await a reviewed map and phone. |
| FR8 rewards | Transactional event ledger, cooldown, personal points and badges implemented. Peak-hour engagement targets are unmeasured. |
| NFRs | Authentication, CSRF/Origin checks, rate limits and private broadcasts are in place. Public TLS configuration, representative 100-client load results, independent contributor enrollment and a ten-person usability pilot remain release/evaluation gates. |

The local runtime uses PostgreSQL, a durable processing worker and an in-process deadline-aware snapshot cache. Redis, TimescaleDB, Kafka and MLflow are not active dependencies of this installation. The deck explicitly allows Kafka to be introduced when pipeline complexity warrants it. F1 is appropriate only for a defined delay-classification task; ETA regression uses MAE/RMSE. No 85% F1, RMSE under two minutes, 90% usability or public production-readiness claim is made from local software checks.

Private passenger journey sessions and continuous consented onboard progress from the earlier redesign document are not implemented by this update. The active product is a route planner with qualified station-service evidence; its context labels describe configured route sections and evidence sources. The older identified-trip arbitration engine remains isolated from unassigned phone positions. This distinction prevents a phone observation from silently becoming a claimed live train track.

## Verification commands and evidence

```powershell
# Isolated backend checks (never run TEST_DATABASE_URL against the passenger DB):
..\.venv\Scripts\python.exe -m pytest backend/tests -q

# Three independent accounts, actual API + worker, isolated test database:
.\scripts\test-crowdsourcing.ps1

# Android prerequisites checked by the build script; Flutter tests use the configured SDK:
cd mobile
flutter analyze
flutter test
```

The final backend suite reports **145 passing checks** on isolated SQLite. A 144-case full PostgreSQL run passed, followed by 29 focused PostgreSQL checks after the final deadline change, including account-preserving migration, both underground and surface reporting, exact expiry, reward idempotency, cell-map relevance and feasible/no-alternative route outcomes. Flutter reports **five passing tests**, including all **420 distinct ordered Aqua station pairs**, account/CSRF behavior and stale cell-sample handling. These are software tests, not measurements of real metro prediction accuracy. Browser evidence and final verification details are recorded in `VERIFICATION.md` and the ignored `.local` logs.

