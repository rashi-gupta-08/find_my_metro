# FindMyMetro crowdsourcing beta dataset

**461 synthetic report deliveries · 48 fictional accounts · 47 scenarios · 73 checkpoints.**

This pack is for checking the software before recruiting real beta passengers. It is **not collected passenger data, measured metro delays, a reviewed cell map, an ML training dataset, or evidence of ETA accuracy**. Station references come from the existing Delhi/Noida catalogue. Every account and reported GPS fix is fictional. The catalogue remains the stored project version, not a fresh operator-data update.

## Open these files

| File | What it contains |
|---|---|
| `reports.csv` | All deliveries, original observation time, upload time, fictional contributor, station/line/direction, reported delay, location and expected handling. Open in Excel or a text editor. |
| `participants.csv` | Fictional account identifiers. No credentials or real people. |
| `expected-checkpoints.csv` | Expected agreement, delay and journey effect at each scenario checkpoint. |
| `dataset.json` | Complete machine-readable replay: report bodies, timing, scenarios, expected results and route requests. |
| `manifest.json` | Seed, catalogue digest, current rule settings and dataset counts. |

Only each delivery's `report` object is sent to the real report endpoint. Expected results, contributor labels and injected-fault descriptions are outside that body. Authentication supplies the contributor identity; the runner never trusts a contributor ID embedded by a report.

## Run it locally

From the repository folder:

```powershell
.\scripts\test-crowd-beta.ps1

# Investigate one case:
.\scripts\test-crowd-beta.ps1 -Scenario freshness-boundary
```

Use the existing application Python environment with the development requirements installed. If it is elsewhere, pass `-PythonPath`.

The command creates a new SQLite database under `.local/crowd-beta/<random-run-id>/`, applies the actual migrations and uses FastAPI's in-process HTTP client, real account sessions/CSRF checks, the actual report API, durable storage, worker validation, rewards and route planner. There is no live server URL argument. Passenger `.env`, database, accounts and app ports are not used. The test configuration disables sensors, MQTT, model artifacts and field cell maps. The DB remains local for inspection; no cleanup deletes unrelated files.

Registration and request limits stay active. Synthetic client addresses from documentation-only IP ranges let 48 fictional accounts be enrolled without exhausting a real user's single-IP sign-up limit. These are in-process client metadata, not external network traffic, physical phones or proof of unique people. Only accounts needed by selected scenarios are enrolled.

The output is:

- `artifacts/crowdsourcing-beta/latest-report.html`: searchable results page with expected-versus-observed validation details.
- `artifacts/crowdsourcing-beta/latest-results.json`: machine-readable scenario outcomes.
- The unique run folder: isolated database, migration log and a copy of the report/results.

The reference clock is **28 October 2026, 08:00 IST**. Each scenario starts three virtual minutes after the preceding one, so old evidence cannot leak into another scenario. The runner advances time deterministically rather than sleeping. Original observation timestamps are preserved. Snapshot caches are cleared between controlled actions so this pack measures pipeline decisions; it does not test cache performance, network latency or rendered browser updates. Do not upload these fixed historical timestamps into the passenger application.

## What the scenarios exercise

| Group | Examples and expected behavior |
|---|---|
| Normal / sparse crowd | Three agreeing accounts confirm; two accounts and no reports retain baseline timing. |
| Retries / abuse | One account posting eight times still counts once; identical IDs deduplicate; altered payloads or reused IDs conflict. |
| Conflicting evidence | A consistent majority can exclude outliers. A 0/60/120-second chain cannot bridge into a false quorum. |
| Time | Offline uploads stay historical; a signal expires at exactly 30 seconds; losing one member breaks a quorum. |
| Location | Far-away GPS, missing location, accuracy over 100 metres, wrong line and future phone clocks fail the relevant check. |
| Report semantics | Arrival, departure, crowding, inbound and outbound reports remain separate groups. They do not invent named trains. |
| Underground / mixed | Unmapped cell hashes retain static timing. Explicitly injected station locations exercise the underground and mixed-corridor accepted-evidence path; this is not a claim that GPS works underground. |
| Routes / rewards | Qualified extra wait is added once, not per station. Evidence expiring before a later boarding is ignored. Aqua can correctly have no alternate metro corridor. Duplicate delivery cannot award points twice. |
| Seeded traffic | Twenty varied Aqua cohorts add fictional location jitter and bounded delay variation, with stale/off-station/missing/future faults. |
| Privacy | Public community output has no report coordinates or contributor identity; private history belongs to its signed-in account. |

Current software rules: three accounts; live report age **under 30 seconds**; a 60-second delay-agreement band; a maximum 250-metre distance from the selected station; accuracy no worse than 100 metres. The 120-second collection setting cannot make a 30-second-old report fresh. The preserved older identified-train pipeline has different rules and is outside this dataset.

## Reproduce or change the data

```powershell
..\.venv\Scripts\python.exe -m scripts.generate_crowd_beta
```

The same seed (`20261028`) and catalogue produce identical records. Review changes to `backend/testing/crowd_beta.py` before regenerating; the exporter replaces only the generated pack files listed in the manifest. Replay refuses a changed catalogue digest until the pack is reviewed and regenerated. Expected labels are controlled specifications, not predictions copied back from the backend's answers.

## Move from synthetic testing to a real beta

Recruit consenting testers and collect actual submissions through their own accounts. On this computer, independent test accounts exercise account agreement but do not establish GPS/cell/device reliability. For a field pilot, cover surface, underground and mixed routes; preserve observation/upload times; record permission loss and offline behavior; and obtain separate actual arrival/departure observations. Keep real coordinates, consent records and pseudonym mapping in private local storage, outside this public fixture pack. Never reuse synthetic account credentials or label these sample delays as measured operator data.

Record real report acceptance, expiry and contradictory evidence separately from ETA error. Calculating ETA MAE/RMSE needs independently observed arrival outcomes; this fixture pack does not provide those measurements. Browser/WebSocket delivery can be checked separately with the existing `scripts/test-crowdsourcing.ps1` isolated browser test. A representative load/device pilot is a separate release gate.

## Separate route-planner finding

While preparing the transfer-expiry scenario, a journey starting at **DMRC Sector - 52 Noida** and ending at **NMRC Sector - 76** returned no baseline route. The current planner requires the first step to be a train ride and drops a route whose first step is the inter-operator walk to Sector - 51. This is a route-coverage gap to resolve before launch; passing crowd validation scenarios does not resolve it. The `later-boarding` scenario starts one ride earlier, at Sector - 34, to test evidence expiry at the later Aqua boarding without that separate restriction.
