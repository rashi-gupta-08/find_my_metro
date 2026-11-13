# Deploy the web app on Vercel

The repository contains a React web frontend, FastAPI API, long-running processing
worker and PostgreSQL database. Publishing just the frontend does not start the
backend, process reports or copy your local accounts/database to the internet.

## Deployment layout

```text
Browser -> Vercel: React frontend + /api/* reverse proxy
                       |
                       +-> HTTPS FastAPI service -> PostgreSQL
Browser -----------------> WSS FastAPI service
                                  ^
                           processing worker -> PostgreSQL
```

The same-origin REST proxy preserves HttpOnly session-cookie and CSRF behavior.
Public journey WebSockets connect directly to the backend's WSS endpoint. No
database password, account token or AUTH_SECRET belongs in the frontend build.
Vercel supports additional backend deployment options, but this configuration
keeps the existing Python API and continuously running worker together on a
container/server host; it does not convert the worker into a serverless function.

## 1. Start the hosted backend

### Render Blueprint for this repository

`render.yaml` uses the **free** compute plans requested by the project owner:
one 512 MB web service shares the API and worker, with a separate free PostgreSQL
database in Singapore. Public database connections are disabled. No paid worker,
paid database, persistent disk or autoscaling resource is defined. No service is
created by committing this file. Automatic deploys are off in this initial
configuration.

Free web services sleep after 15 idle minutes and cold starts can take about one
minute. The worker sleeps with the service. Free PostgreSQL expires after 30 days
and has no managed backups. This deployment is for evaluation/testing; these free
plans do not provide continuous production availability. No paid upgrades or
paid replacements are authorized.

Render generates an authentication seed and runtime database password in a
shared environment group. The launcher derives a stable 64-character signing
key from that seed. Both services receive the same signing key and use the
same DML-only database role. During startup the launcher creates the role, grants
table/sequence access and applies migrations with the schema-owner role. A
database advisory lock serializes this step if starts overlap. The launcher then
executes a fresh supervisor process with runtime-only credentials; that process
starts the API and worker. If either child fails it stops the other and exits, so
Render can restart a complete backend. SIGTERM is forwarded to both children.
The schema-owner connection is stored in Render's service configuration for
release/startup configuration; the launcher removes it and the raw generated
secrets from the environment passed to the running API and worker. Service
administrators still have access to that control-plane configuration.

Set the API's `CORS_ORIGINS` to the actual, authorized Vercel HTTPS frontend origin
when approving the Blueprint. Its worker inherits that exact same value.
The launcher adds Render's assigned API hostname and the frontend hostname to
the explicit allowed-host list. The `/api/v1/health/ready` check requires database
access and a current worker heartbeat before traffic is accepted. Also inspect
the full `/api/v1/health` result and verify report processing before publishing the
frontend.

The following generic hosting instructions describe the equivalent services when
not using the Blueprint launcher.

Use a host that runs containers or persistent Python services and supplies public
HTTPS/WSS. Build from the **repository root**, using `backend/Dockerfile`.
The image contains the backend, migrations and public operator catalogue.
Create PostgreSQL with backups, a schema-owner migration account and a separate
runtime account with only the required application-table privileges. Supply the
following using the host's private environment settings, not Git:

```dotenv
APP_ENV=production
AUTH_SECRET=<generate a new random secret of at least 48 characters>
DATABASE_URL=postgresql+psycopg://<runtime-user>:<password>@<db-host>:5432/<database>?sslmode=require
SECURE_COOKIES=true
CORS_ORIGINS=https://<your-project>.vercel.app
ALLOWED_HOSTS=<your-api-host>,<your-project>.vercel.app,localhost
NETWORK_FILE=/app/data/operator-network.json
HARDWARE_ENABLED=false
MQTT_ENABLED=false
SIMULATION_ENABLED=false
```

Replace every placeholder. URL-encode special characters in database credentials.
Use the same runtime environment for API and worker. Include each exact frontend
custom domain in `CORS_ORIGINS`; never use `*` for authenticated origins. A Vercel
preview URL needs its own explicit permitted origin before sign-in/reporting works.

Run migrations once as a release job, with the owner's connection supplied only
to that job as `MIGRATION_DATABASE_URL`:

```text
python -m backend.app.bootstrap
```

Run two separate long-lived services from the same image:

| Service | Start command |
| --- | --- |
| API | `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-server-header --ws-max-size 4096 --limit-concurrency 300` |
| Worker | `python -m backend.app.worker` |

Route the host's HTTPS/WSS ingress to the API's port **8000**, or override the
command's port if the provider requires its `PORT` value. The worker has no public
port. Restrict database access to the backend services. Do not start an API worker
inside a Vercel build command, a request handler or browser code.

Before deploying Vercel, open:

```text
https://<your-api-host>/api/v1/health
```

Require `ready: true`, database `postgresql` and worker `ready`. Check
`/api/v1/network` returns the intended operator catalogue. An API that starts but
has no worker cannot complete crowdsourced-report processing. With
`--no-proxy-headers`, rate limits use the immediate peer by default; configure a
trusted ingress that sanitizes the client IP and exact `TRUSTED_PROXY_CIDRS` before
relying on per-client limits at public load. Do not trust arbitrary forwarded IPs.

## 2. Import the repository into Vercel

Create a Vercel project from `rashi-gupta-08/find_my_metro`. Select the Git branch
containing the application and the deployment changes; the current local branch
is `codex/local-backend-integration`. If those changes are later merged, select
that branch instead.

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Framework Preset | **Other** (custom Build Output API configuration) |
| Install Command | `npm ci` |
| Build Command | `npm run build:vercel` |
| Output Directory | Leave the override **off**; the build writes `.vercel/output` |
| Node.js | `22.x` |
| Environment variable | `BACKEND_URL=https://<your-api-host>` |

`frontend/vercel.json` supplies the build settings. Set `BACKEND_URL` for each
Vercel environment being deployed. It is the API's **origin only**: no `/api`,
username, password or trailing path. Do not use `localhost` or your Vercel frontend
URL. The build fails clearly if this setting is missing or points at a placeholder.

The build compiles TypeScript/Vite, generates the offline shell, copies only `dist`
into the deployable static directory and writes Vercel's version-3 routing config.
REST stays at `/api/*` on the frontend domain; its upstream is generated from
`BACKEND_URL`. Live sockets use that origin with `wss:`. Security headers allow
only this additional WebSocket origin, and API responses use `no-store`.

Deploy after the API and worker are healthy. If you change the backend origin,
change `BACKEND_URL` and redeploy: this value configures the build. Existing local
startup is unchanged and continues to use the local same-origin proxy.

## 3. Verify the deployed app

1. Open the Vercel HTTPS URL. Confirm the station list/map loads.
2. Open `/api/v1/health` on the **Vercel URL** and confirm all services are ready.
3. Plan a Delhi-to-Noida journey and try the alternative route preferences.
4. Check the browser Network panel: REST goes to the Vercel domain; the journey
   socket goes to the hosted API over WSS and connects successfully.
5. Create a dedicated test account. Reload and confirm the session survives. Test
   sign-out, rejected credentials and CSRF-protected reporting. No local account
   is automatically copied to the hosted database.
6. With consenting test accounts and actual permitted location evidence, check
   three-account agreement, original observation times, duplicate protection and
   automatic fallback after the 30-second live-evidence lifetime. Use a separate
   staging database for simulated GPS/replay tests.
7. Disconnect and reconnect. Saved information must remain labelled with its age;
   private API responses and reports must remain outside the service-worker cache.

## Verification scope and remaining setup

The adapter can be checked locally with `node scripts/vercel-config-check.mjs`.
An actual Vercel deployment, public TLS/WSS, forwarded cookies, hosted database
permissions and hosted report processing must be verified after a backend host
and Vercel project are connected. No cloud resources are provisioned by these files.

References: [Vercel Build Output API](https://vercel.com/docs/build-output-api),
[output routing](https://vercel.com/docs/build-output-api/configuration),
[external rewrites](https://vercel.com/docs/routing/rewrites).
