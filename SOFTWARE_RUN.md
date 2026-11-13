> This document describes the separate fictional validation profile. The default app now runs the real-station passenger journey planner described in README.md. Open `/?developer=1` only when running `-Software` to display replay controls.

> **Current scope — 16 October 2026:** See [the software implementation update](docs/SOFTWARE_IMPLEMENTATION_2026-10-16.md) for the current software-only application. Service reports now cover surface and underground stations, expire after 30 seconds and support typed updates/rewards. Flutter uses the new passenger planner. Hardware/WSN integration below describes the preserved earlier version, not a dependency or release requirement of the current app.

# Running the patent's software components locally

From the repository folder in PowerShell:

```powershell
& .\scripts\stop.ps1
& .\scripts\start.ps1 -Software -Mobile
```

Open the web frontend at http://localhost:5173 and the Flutter client at http://localhost:5174. API documentation is at http://localhost:8000/docs. The original frontend source was not present in the supplied GitHub repository; the integrated web implementation preserves the published Lovable design as its reference. It is not an exported copy of that source.

The web **Run journey** control changes inputs, rather than forcing a source or context. Normal journeys cross underground, transition and surface sections automatically. Other conditions exercise reverse handover, matching sensor/phone evidence, conflicting reports, sensor loss, timeout and delays. Tracking shows selected source, source trust, the decaying estimate, original deadline and decision history. Choose Surface Terminal to watch arrivals through most of a journey. The next dated software journey is also available as an explicit timetable fallback, so routes can wait for a valid future service.

## Component mapping

| Patent component | Implementation |
|---|---|
| Client 102 | `frontend/src/` and `mobile/lib/` |
| API gateway 104 | `backend/app/main.py`, `auth.py`, `security.py` |
| Acquisition 120 | `backend/app/acquisition.py`, `mqtt.py` |
| Router 106 | `ContextAwareDataSourceRouter` in `context_switching.py` |
| Context 108 | `ContextDeterminationEngine`; configured segment zone map |
| Trust 110 | `DynamicTrustEngine`; source qualification in `engines.py` |
| Switching 112 | `BackendSwitchingEngine`; hold, margin and confirmations |
| Arbitration 114 | `TransitionArbitrationEngine`; bounded position, trust comparison and deadline |
| Prediction 116 | `prediction.py`, `ml_prediction.py`, `scripts/train_prediction.py` |
| Output 118 | `/ws/eta/{station_id}`, ETA REST snapshots and delay alerts |
| Storage | PostgreSQL durable observations, trip state, jobs, scores and decisions |
| Routes | `routing.py`; NetworkX topology with predicted boarding waits and travel times |

Health is `/api/v1/health`; `/api/v1/system` reports the active prediction model and training-data kind. Input timestamps and receipt timestamps are separate. Derived positions do not become independent evidence. Arrivals cap motion at a station until observed departure. Arbitration timeout uses schedule fallback when qualified fresh evidence is absent.

The software feed uses database **metro_software**, private configuration `.local/software.env`, and `.local/software/network.json`. Internal contributors cannot sign in. Existing operator accounts and events in database **metro** remain separate. Local software controls are absent from operator and production applications. Synthetic prediction artifacts cannot serve those applications.

## Training

This machine's offline training environment is on D: and is recorded in the ignored `.local/ml-runtime.json`. Rebuild the labelled synthetic model with:

```powershell
& .\scripts\train-prediction.ps1 -Software
```

On another machine, prepare a Python 3.12 environment with `backend/requirements-ml.lock.txt` and pass its Python path through `-PythonPath`. For actual history, use `-InputFile journey-history.jsonl -OutputFile model.json -NominalSegmentSeconds <network-baseline-seconds>`. Each JSONL row needs `journey_id`, timezone-aware `observed_at`, `features_available_at` and independently measured `actual_arrival_at`; finite numeric `segment_seconds`, `base_seconds`, `speed_mps`, `observation_age`, `trust`, `crowd_source`, `underground`, `remaining_segments`, and `actual_remaining_seconds`. Source/context indicators are 0 or 1. Features must be available at prediction time, and remaining time must match the measured arrival. Training rejects overlapping outcome cutoffs between partitions. The 30-second nominal segment default is restricted to the explicitly synthetic fixture.

Whole journeys are split chronologically 60/20/20. Prophet and Random Forest fit only training journeys. Validation compares schedule, training-only historical and Prophet baselines; activation requires improved MAE and no worse RMSE than the strongest validation baseline. The final test partition reports unseen results against that preselected baseline. Synthetic history uses a fixed seed and fixed historical dates; the rows are saved beside the artifact in `.history.jsonl`. Artifacts include a history digest and version. Forecast coverage is seven days; outside coverage inference uses the deterministic fallback. Metrics in `.local/software/prediction-model.evaluation.json` are synthetic results, not measured metro performance. Real deployment still requires representative operator data, calibration and independent review.

## Flutter client

Flutter 3.47.6 and Dart 3.13.5 are installed under `D:/FindMyMetro-local-runtime/flutter`. The compiled client is under `D:/FindMyMetro-local-runtime/mobile-web`. Dependency and build caches also use D: because C: is nearly full. The private runtime record is `.local/mobile-runtime.json`.

After mobile source changes, build with:

```powershell
& .\scripts\build-mobile.ps1
```

On another machine, pass `-FlutterPath` and `-OutputPath` or install Flutter on PATH. The script builds in release mode with optimization level 2 to fit this workstation's available memory; `-OptimizationLevel 4` selects maximum optimization. Start with `-Mobile` to serve the built client. Web builds use their own origin for requests. Native builds accept `--dart-define=API_BASE=YOUR_API_URL` and `--dart-define=API_ORIGIN=YOUR_ALLOWED_ORIGIN`. Native sessions remain in memory; passwords are never cached. HTTP is allowed only in the Android debug manifest; a release connection requires HTTPS.

The client includes station/operator selection, ETAs, route queries, source tracking, account sign-in/registration, one-time location reporting, account-scoped offline queues, snapshot age and in-app delay alerts. Queues preserve event IDs and original observation times and clear on sign-out. Android manifests include Internet and foreground location permissions. Android APK/emulator execution is not verified on this machine because an Android SDK/device is not configured.

Firebase background notifications require a Firebase project, service credentials, device enrollment and consent. These are not configured; current alerts arrive while connected through WebSocket snapshots. Redis and Kafka are not needed for the single-machine processing architecture. Hardware commissioning and authorized Delhi/Noida tracking remain later integrations.

## Verification

`backend/tests/` covers automatic software journeys using the actual worker, trust comparison, corroboration, both handover directions, loss, timeout, restart recovery, invalid models and the original security/operator tests. `mobile/test/api_test.dart` covers session/CSRF handling and preserving an offline observation. `scripts/software-browser-check.cjs` checks only the software profile and does not register accounts or consume the original database's signup allowance. Screenshots are in `.local/software/checks/`.

No push, deployment or hardware connection is performed by these scripts.
