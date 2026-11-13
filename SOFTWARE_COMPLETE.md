# Local software completion — 10 October 2026

> **Current scope — 16 October 2026:** See [the software implementation update](docs/SOFTWARE_IMPLEMENTATION_2026-10-16.md) for the current software-only application. Service reports now cover surface and underground stations, expire after 30 seconds and support typed updates/rewards. Flutter uses the new passenger planner. Hardware/WSN integration below describes the preserved earlier version, not a dependency or release requirement of the current app.

The current product is the web journey app connected to FastAPI, a durable PostgreSQL worker and the patent's context-aware source pipeline. Hardware commissioning is deferred. The default passenger database contains the Delhi/Noida station catalogue and preserves existing accounts. It does not receive generated trains, fake GPS reports or the synthetic prediction model.

| Software flow | Implemented behavior |
|---|---|
| Journey planning | 265 catalogue stations, 14 ordered line paths; shortest time, fewer interchanges, less walking and shortest distance; bounded alternatives with full stations and explicit walking/re-entry connections |
| Accounts | Registration, sign-in, account-scoped queues, private processing history, session/CSRF checks, password change, deletion and administrator-assisted recovery |
| Surface observations | One-time foreground GPS; station proximity and accuracy checks; original UTC observation and receipt times; durable acknowledgement; worker validation; three-account agreement; disagreement and stale report outcomes |
| Surface delay output | Community service evidence affects boarding delay once, without inventing train identity; evidence expiry includes the first ageing member of the selected agreement |
| Identified train pipeline | Acquisition → context → trust → stable switching → arbitration → prediction; underground, surface and both handover directions; bounded motion estimate, confidence decay and persisted 60-second deadline |
| Software failures | Duplicates, conflicts, out-of-order uploads, missing sources, queued retry/dead letter, worker restart, model failure and deterministic fallback |
| Passenger updates | Versioned REST/WebSocket snapshots; reconnection refresh; observation age, source and heuristic trust; in-app delay alerts |
| Offline web app | Public shell and compiled assets cached; last network/journey saved with age; account/GPS API responses excluded from service-worker caching; account-scoped report retry while app is open |
| Browser notifications | Explicit opt-in; fresh selected-journey delays; duplicate suppression; denial/failure leaves in-app alerts available; requires the app to remain open |
| ML lifecycle | Offline Prophet/RF training, chronological whole-journey splits, causal feature/outcome checks, strongest-baseline validation, versioned JSON inference and fallback; synthetic artifacts restricted to test/software profiles |

## Run the passenger web app

```powershell
& .\scripts\start.ps1
```

Open http://localhost:5173. API documentation is http://localhost:8000/docs. Before restarting use `& .\scripts\stop.ps1`; stored accounts and reports remain intact. These commands run on loopback only. Nothing is pushed or published.

To send a real surface report, sign in, select **Report**, choose the surface station/line/direction, enter observed extra wait and allow location when submitting. **My reports** shows the worker outcome. Three accounts must agree within a 45-second observation span and a 60-second delay-value span; account agreement is not proof of independently enrolled people. The app does not continuously track a passenger in the background.

## Test crowdsourcing on this computer

```powershell
& .\scripts\test-crowdsourcing.ps1
```

The script needs the application Python environment, a built frontend, Node, Playwright and Chrome. It detects the Python environment and this workstation's bundled Playwright; other installations can pass `-PythonPath`, `-NodePath` and `-PlaywrightModules`. Set `METRO_CHROME_PATH` if Chrome is installed elsewhere. Build with `cd frontend; npm.cmd run build` after frontend changes.

It creates a new SQLite database beneath `.local/crowd-checks/<run>/`, starts the actual API/worker on 8010 and frontend on 5180, and registers three normal accounts through the web UI. Three browser contexts capture test GPS coordinates near Noida Sector 52 and submit through the normal form. The test waits for worker confirmation and checks the live journey, private history, duplicates, bad GPS, old uploads, closed-dialog retry, offline reload and reconnection. Notification delivery is stubbed to avoid a native prompt or notification; the consent/denial and deduplication flow still runs. The script always stops its own process trees, restores its process environment and preserves results/screenshots for review. It does not stop or alter the running passenger app. Never run generated reports against the passenger database.

Backend tests run with `& .\scripts\test.ps1`. PostgreSQL tests require an explicitly isolated `TEST_DATABASE_URL`; fixtures recreate test tables. The final verified PostgreSQL run and browser evidence are recorded in `VERIFICATION.md`.

## Check the context-switching software without hardware

```powershell
& .\scripts\stop.ps1
& .\scripts\start.ps1 -Software
```

Open http://localhost:5173/?developer=1. This deliberately switches to the separate fictional network/database `metro_software`, with visible software-validation labels. Replay normal and reverse journeys, lost sensors, conflicting reports, matched evidence, delay and transition timeout. Controls change incoming observations; the actual worker decides the source. Use **Tracking** for source scores and decision history. See `SOFTWARE_RUN.md` for details. Stop and restart without `-Software` to return to the passenger catalogue.

## Data-dependent integrations

Physical WSN/MQTT commissioning, authorized operator tracking/timetables, field-trained prediction accuracy, independently verified public contributor enrollment, a public HTTPS deployment and closed-app background push remain integration/release work. Current operator travel times and walking geometry are labelled indicative estimates. The local software tests establish implemented behavior, not real Delhi/Noida ETA accuracy or completed public deployment.
