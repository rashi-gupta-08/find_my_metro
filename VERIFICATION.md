# Software-only application verification — 16 October 2026

Current implementation: [software change record](docs/SOFTWARE_IMPLEMENTATION_2026-10-16.md). Earlier records below describe the previous version and retain their original dates.

| Check | Result / evidence |
| --- | --- |
| Full backend regression suite | **145 passed** on isolated SQLite (`.local/software-final-sqlite-tests.log`). The full 144-case PostgreSQL run passed (`.local/software-postgres-full-tests.log`); after the final deadline change, all 29 focused PostgreSQL checks passed (`.local/software-final-postgres-tests.log`). Each PostgreSQL runner removed only its newly created test database. |
| Coverage after final changes | The final suite includes legacy report retry compatibility and rerouting expiry even when the delayed route falls outside the returned alternatives. All 145 tests pass in the final SQLite run; changed paths pass in the focused PostgreSQL run. |
| Actual passenger database | Schema at `0005`, runtime role can read the new contribution ledger, accounts retained, hardware disabled. Read-only records: `.local/software-runtime-verification.json` and `.local/software-postgres-verification.json`. Pre-migration archive: `.local/backups/before-software-0005.dump`. |
| Web build | TypeScript, Vite and offline shell pass. `.local/software-web-build.log`. |
| Web browser | **Nine checks**, no page exceptions: full catalogue, connected alternatives and walking, source snapshots, reconnection, account requirement, new offline Aqua journey, 390px layout and typed location report flow. `.local/journey-checks/results.json`. |
| Real crowdsourcing browser flow | **Ten checks**, no page exceptions. Three independently authenticated accounts in an isolated SQLite stack use the actual API/worker. Checks cover quorum, private outcomes, one reward, single-count route delay, duplicate handling, GPS rejection, historical uploads, offline retry/reload, reconnection and 30-second expiry. `.local/crowd-checks/aee5f2737b8c48e48d2cb4fe0520063c/results.json`. Notification delivery is stubbed; foreground permission/deduplication behavior is verified. |
| Flutter | **Five tests pass**: session/CSRF, rejected requests, all 420 ordered pairs of distinct Aqua stations offline, outside-coverage/missing-plugin behavior, and stale Android-channel sample rejection. `.local/flutter-verified-tests.log`. |
| Flutter analysis/build | Analyzer reports no issues; production web compilation succeeds. `.local/flutter-analyze-final.log`, `.local/flutter-software-build.log`. |
| Flutter browser | **Three checks**, no page exceptions: new Aqua planner reads backend route, complete station details expand, disconnected journey switches to bundled static timing. `.local/mobile-software-check/results.json`. |
| Client deadline logic | `node scripts/journey-freshness-check.mjs` verifies exact expiry, loss of connection, coherent adjusted times, preserved original evidence and all 420 Aqua station pairs in the web offline calculator. |

The combined regression coverage includes migration preservation, both station contexts, typed report separation, exact deadlines, independently agreed delays, reward idempotency/cooldown, cell-map route relevance, real alternative suggestions, no-alternative outcomes, and compatibility with pre-update report shapes.

No live operator departure/position feed, reviewed field cell map, real-world prediction accuracy, production load result, physical Android cell collection or signed release APK is established by these checks. The machine's Flutter doctor reports no Android SDK or connected Android phone. Android Kotlin source is implemented; device compilation and field behavior remain unverified. The existing Starlette/httpx warning concerns test tooling.

No push or deployment occurred. Test accounts and synthetic locations are confined to isolated test databases; the passenger database is not used for test fixtures.

---

# Local application verification — updated 10 October 2026

## Hardware-deferred software completion — 10 October 2026

- **135 backend tests passed against isolated PostgreSQL** in `metro_checks`, including new report ownership/outcome, strict consensus-span, timezone-normalization, first-member expiry, future-boarding and ML provenance/cutoff checks. Fifteen initial new checks also passed against SQLite; later expiry checks are included in the final PostgreSQL run. The existing Starlette/httpx test-tool deprecation warning remains.
- TypeScript, Vite and the generated offline shell build passed. API and GPS requests are excluded from service-worker caching. Offline private history is not persisted in the shell.
- **Eight end-to-end crowdsourcing browser checks passed with zero runtime page exceptions** against an actual API, worker and isolated SQLite database. Three accounts were registered through the normal UI, captured explicit test GPS fixes and submitted through the normal report form. Evidence reached confirmed private outcomes and the live journey WebSocket; route delay was counted once and no train identity was created.
- Browser checks cover GPS rejection, historical uploads, deduplication, private history, closed-dialog automatic retry with original timestamps, offline full-page reload, saved journey age, reconnect/session recovery, notification permission denial and notification deduplication. Native notification delivery was stubbed; no OS notification was sent. The final fixture accounts/reports are confined to `.local/crowd-checks/bee44b2b5fab407fab23b7456e559af6/`; the repeatable command is `& .\scripts\test-crowdsourcing.ps1`.
- Prophet/RF training completed with 252 training, 84 validation and 84 held-out **synthetic** journeys. It checked causal features and disjoint outcome cutoffs, compared schedule/historical/Prophet baselines, and beat the historical validation baseline. Held-out synthetic MAE: hybrid 0.617 s, historical 14.997 s; synthetic RMSE: hybrid 0.728 s, historical 18.019 s. These deliberately simple generated-data results are software pipeline checks, not real metro performance.
- The validated synthetic JSON artifact is installed only in `.local/software/prediction-model.json`; its previous version was preserved. Passenger mode leaves ML unconfigured and blocks synthetic artifacts. Hardware, field feeds, actual GPS/ETA accuracy and public deployment are not established by these checks. No Git push or publishing occurred.
- Final passenger restart passed with PostgreSQL, API and worker ready; 265 stations/14 paths, software inputs and simulation disabled. Eight additional read-only/intercepted passenger browser checks passed with zero runtime page exceptions, including route search/preferences, streamed statuses, offline/reconnect behavior and a 390-pixel viewport. Results are in `.local/journey-checks/`. The final software-model loader check reported the accepted `prophet-random-forest-v2-ed2d6215a7ee` artifact active only under the isolated software configuration.

## Verified results

- **83 backend checks passed** against isolated SQLite and PostgreSQL databases. Added tests use the actual worker for automatic software journeys, reverse handover, matching evidence, loss and timeout. Tests also verify incoming trust against the decaying estimate, fresh tunnel evidence versus old surface reports, model rejection/fallback, JSON forest inference, route HTTP responses, event deduplication, associations, consensus, switching and recovery.
- Account/security tests cover Argon2id storage, hashed sessions, permitted Origins, CSRF, privilege escalation rejection, bounded password hashing concurrency, shared rate limits, device scoping/revocation, report ownership, password change and account deletion.
- Operator integration tests cover validated topology, projected phone locations, verification gates, exact dated timetable arrivals, cancellation, immutable trip IDs, UTC offset normalization, route waits and configured walking connections across DMRC/NMRC identities. Test data is fictional and remains isolated from passenger data.
- Upgrade tests confirm existing accounts/timetables survive migrations and indexed service windows are backfilled. Repeating the upgrade is safe. The running PostgreSQL database is at schema **0004**.
- Earlier authentication/browser verification covered data-unavailable behavior, operator links, sessions, CSRF/admin denial, password change and account deletion. Its temporary account was deleted. Signup/font/layout changes from a subsequent repair turn were rolled back at the user's request; those repair results do not describe the current code. Current software-profile browser checks use no registration and preserve original account data.
- TypeScript validation and the compiled frontend build passed. The app serves static compiled assets and rejects development-module URLs.
- Native start, process-tree stop and restart passed with the separate PostgreSQL cluster and restricted runtime role. Both IPv4 and IPv6 frontend listeners bind only to loopback. Worker and database health are ready.
- A PostgreSQL archive created by the runtime role restored into a separate empty database using the migration role. Schema 0004 and account tables were checked. Runtime schema creation was denied, as intended. The reusable backup tool refuses archive overwrites, application-database restore targets and non-empty targets.
- npm audit reported **zero known vulnerabilities** across frontend dependencies. pip-audit reported **zero known vulnerabilities** across the 31 pinned backend runtime dependencies. The isolated environment's pip was updated to resolve its reported vulnerabilities. These scans do not prove absence of unknown vulnerabilities.
- Both local and production Docker Compose configurations passed validation. Docker Desktop's Linux engine was unavailable, so the container build/runtime and TLS MQTT broker are not verified.

## Limited local responsiveness check

100 health requests through the built frontend proxy at concurrency 10 completed successfully. Measured p95 was **166.6 ms**, with maximum **184.7 ms**. A Windows IPv6-to-IPv4 connection delay was found and fixed by providing an IPv6 loopback frontend listener.

This check uses the currently unconfigured network. It does **not** establish ETA processing capacity, WebSocket capacity under representative metro data, field handover continuity, calibrated confidence or prediction accuracy.

## Evidence and remaining limits

Test source is in `backend/tests/` and `scripts/production-browser-check.cjs`. Ignored browser screenshots, structured checks and local timing results are in `test-results/`; private audit results and database archives are in `.local/`.

One test-tooling deprecation warning remains: Starlette's TestClient currently warns that its httpx adapter is deprecated. All checks pass; httpx is confined to development requirements and is not included in the production runtime image.

The Flutter analyzer, two API tests and compiled web build pass. The synthetic Prophet/RF run uses 252 training, 84 validation and 84 test journeys, with test MAE 0.617 seconds and RMSE 0.728 seconds on the deliberately simple generated dataset. Exported JSON forest output differs from scikit-learn by at most 1.43e-14 seconds. These values verify that pipeline execution works; they do not establish field accuracy. API serving loads bounded JSON models and deterministic fallback without training libraries.

Current software-profile browser verification confirms automatic WSN → bounded estimate → qualified crowd handover, ETA cards, route alternatives, the web phone layout, Flutter connection, cache-age labels and reconnection. No test account was registered during these checks. Screenshots are under `.local/software/checks/`.

There is no connected authorized DMRC/NMRC live feed or commissioned hardware. Real model evaluation/calibration, Android device execution, Firebase background notifications, representative load, HTTPS ingress and off-machine backup operations remain integration gates in `IMPLEMENTATION_STATUS.md`.

No GitHub push or Lovable deployment was performed.


## Passenger journey planner — 8 October 2026

- Final PostgreSQL run: **100 tests passed** in the isolated `metro_checks` database. The new catalogue/report tests also passed under SQLite. Test accounts and report mutations never touched passenger accounts.
- Compiled React frontend: TypeScript and Vite build passed.
- Live local readiness: API, PostgreSQL and worker ready; simulation disabled; the network endpoint returned 265 stations and 14 ordered paths.
- Read-only browser checks passed for station search across operators, Delhi-to-Noida routing, external transfer/re-entry details, multiple route suggestions, preference selection and anonymous report access.
- Phone viewport 390×844: no horizontal overflow. One-time GPS report flow tested with browser-intercepted session/report responses; no real user account was created and no fake report was sent to the running app.
- PostgreSQL tests exercise actual durable surface-report ingestion, worker validation, three-account agreement, duplicates/conflicts, out-of-order uploads, stale/future timestamps, GPS proximity, underground rejection, delayed-route expiry and account erasure.
- Green and Blue branch tests prevent skipped junctions and fictitious walking changes. Routes do not create dated trains from static data; station reports never create train identities.
- Screenshots and browser results: `.local/journey-checks/`. Runtime page exceptions: zero.

The catalogue's public operator travel times are indicative; walking and track geometry are estimates. Current train departure times, physical WSN commissioning, public-deployment abuse resistance and field GPS/ETA accuracy are not verified by these tests. The original externally loaded font can produce a CSP console warning; the app uses its system-font fallback. The default web product is updated; Flutter retains its earlier UI.

## Backend-to-journey integration — 8 October 2026

- **118 tests passed against isolated PostgreSQL**. The 18 additional integration checks passed under SQLite as well. Real worker replay feeds the journey contract with WSN, crowd, fused, bounded estimates and deadline fallback; reverse handover reaches the terminal arrival output. Synthetic fixtures remain outside the passenger database.
- REST and journey WebSockets return the same versioned snapshot. Tests cover invalid stations/preferences/Origins, shared connection limits, closures, community-versus-train evidence, future boarding, exact expiry and cache invalidation after a clock change.
- Final TypeScript and compiled Vite frontend build passed. The original test-tooling deprecation warning remains.
- Eight local browser checks passed with zero runtime page exceptions: station search, journey alternatives, streamed source/freshness statuses, preference-specific frames, offline saved labels, fresh reconnect snapshots, authenticated report access, mobile layout and intercepted foreground GPS reports.
- Source status screenshot: `.local/journey-checks/backend-journey-status.png`. Other screenshots/results remain in that directory. Browser report mutations were intercepted; no fake passenger reports/accounts were created.
- Restart completed with PostgreSQL, API and worker ready, simulation disabled. The live route response included eight alternatives and three explicitly static boarding statuses for New Delhi to Pari Chowk, consistent with the lack of connected train evidence.

The plan's software integration is connected; this does not establish field accuracy or commission operator feeds/hardware. Operator ML artifacts remain disabled until independently validated. Ordinary boarding waits, access and security remain outside static route durations; identified next arrivals are shown separately. Nothing was pushed or published.

