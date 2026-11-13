# Application and release status

Updated 16 October 2026. The active local application is software-only. This status supersedes the earlier hardware-deferred implementation notes.

The [full implementation update](docs/SOFTWARE_IMPLEMENTATION_2026-10-16.md) maps the supplied synopsis and Evaluation-0/Evaluation-2 requirements to code and remaining gates.

## Running locally

- React web app: http://localhost:5173. Full stored Delhi/Noida catalogue, Aqua Phase 1 filter, four route preferences and station details.
- Flutter web client: http://localhost:5174. New passenger planner, all 21 Aqua stations bundled for offline routing, typed reports, private outcomes, rewards and phone-evidence availability.
- FastAPI, PostgreSQL and durable worker. Migration 0005 preserves accounts and historical observations. A pre-migration backup is kept privately in `.local/backups`.
- Hardware acquisition disabled by default; no sensor or gateway is required. Historical hardware code/tests remain preserved.

## Implemented software changes

- Surface and underground station-service reports with location validation, original UTC timestamps and three-account agreement. Four report types do not overwrite each other.
- Thirty-second live lifetime; the 120-second collection limit never revives stale evidence. Delayed offline uploads remain historical.
- Validated delay greater than three minutes can trigger a faster alternative suggestion if it saves at least two minutes. Explicit no-faster-alternative result on a single corridor. Delay counted once at boarding.
- Idempotent contribution points, badges and a five-minute repeat-submission cooldown.
- Deadline-aware REST/WebSocket snapshots, explicit static fallback and removal of stale/disconnected delay from displayed route totals.
- Android Kotlin method-channel source for foreground cell readings; reviewed fingerprint-map contract with no invented station map. This is a location hint, not a train identity.

## Verified

- Backend: 145 checks pass on SQLite; the 144-case PostgreSQL suite passed, followed by 29 focused PostgreSQL checks after the final deadline change, including account-preserving migration and source-evidence boundaries.
- Flutter: five tests pass, including all 420 ordered pairs of distinct Aqua stations, CSRF/session behavior and stale cell rejection.
- Flutter analysis and web build pass; React production build passes.
- Browser checks and evidence are listed in `VERIFICATION.md`; no software check establishes real-world ETA accuracy.

## Remaining gates

1. Android SDK installation, debug APK compilation and physical-phone checks. No Android SDK or Android phone is currently detected on this computer.
2. A reviewed field cell map, actual dated service data if next-arrival predictions are required, and independently labelled real journey records. Static indicative timing is not a dated GTFS schedule.
3. Field-trained Prophet/Random Forest validation against schedule and historical baselines. No production hybrid prediction artifact or measured field accuracy is active.
4. Correlated client-render latency evaluation, representative 100-client load test and proposed usability pilot. Deck numbers remain targets.
5. Public TLS, independent contributor enrollment/abuse controls, release signing, operational monitoring and configured closed-app push notifications.
6. Private onboard passenger journey sessions and continuous progress from the earlier redesign proposal. Route context and station-service evidence are implemented; they do not establish a live train track.

The active local stack uses PostgreSQL, a processing worker and a deadline-aware in-process cache. Redis, Kafka, TimescaleDB and MLflow are not active services here. Nothing has been pushed or published.

