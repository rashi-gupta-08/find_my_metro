"""Render launcher: derive runtime configuration and keep owner credentials out of it.

Only the release command uses the database owner. API and worker connect with a
separate DML-only role; the same generated secrets are shared by both services.
"""
import hashlib
import os
import subprocess
import sys
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

RUNTIME_ROLE = "metro_app"


def prepare_environment(source):
    environment = dict(source)
    owner_value = environment.pop("RENDER_DATABASE_URL", "")
    password = environment.pop("RENDER_APP_PASSWORD", "")
    seed = environment.pop("RENDER_AUTH_SEED", "")
    if not owner_value or len(password) < 32 or len(seed) < 32:
        raise ValueError("Render database connection and generated secrets are required")
    owner = make_url(owner_value)
    if owner.get_backend_name() not in {"postgresql", "postgres"} or not owner.username or not owner.database:
        raise ValueError("Render requires a PostgreSQL owner connection")
    if owner.username == RUNTIME_ROLE:
        raise ValueError("Migration and runtime roles must be different")
    owner = owner.set(drivername="postgresql+psycopg")
    if "sslmode" not in owner.query:
        owner = owner.update_query_dict({"sslmode": "require"})
    runtime = owner.set(username=RUNTIME_ROLE, password=password)
    environment["DATABASE_URL"] = runtime.render_as_string(hide_password=False)
    # Render's generated 256-bit secret is base64 encoded (44 characters). Derive
    # a 64-character key without reducing its entropy, meeting the app's policy.
    environment["AUTH_SECRET"] = hashlib.sha256(seed.encode()).hexdigest()
    environment["APP_ENV"] = "production"
    environment["SECURE_COOKIES"] = "true"
    environment.pop("MIGRATION_DATABASE_URL", None)
    hosts = {value.strip() for value in environment.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if value.strip()}
    hostname = environment.get("RENDER_EXTERNAL_HOSTNAME")
    if hostname:
        hosts.add(hostname)
    origins = environment.get("CORS_ORIGINS", "").split(",")
    for origin in origins:
        parsed = urlsplit(origin.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Configure exact HTTPS frontend origins before deploying")
        hosts.add(parsed.hostname)
    environment["ALLOWED_HOSTS"] = ",".join(sorted(hosts))
    return environment, owner, password


def initialize_runtime_role(owner, password):
    # This runs only during the release phase, on the dedicated app database.
    dsn = owner.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname=%s", (RUNTIME_ROLE,))
            existing = cursor.fetchone()
            if existing and any(existing):
                raise ValueError("Refusing to reuse a privileged runtime role")
            operation = "ALTER" if existing else "CREATE"
            cursor.execute(sql.SQL(operation + " ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION").format(
                sql.Identifier(RUNTIME_ROLE), sql.Literal(password)))
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(owner.database), sql.Identifier(RUNTIME_ROLE)))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(RUNTIME_ROLE)))
            cursor.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(RUNTIME_ROLE)))
            cursor.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(RUNTIME_ROLE)))
            cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(
                sql.Identifier(owner.username), sql.Identifier(RUNTIME_ROLE)))
            cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}").format(
                sql.Identifier(owner.username), sql.Identifier(RUNTIME_ROLE)))


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode not in {"migrate", "api", "worker"}:
        raise ValueError("Use migrate, api or worker")
    environment, owner, password = prepare_environment(os.environ)
    if mode == "migrate":
        initialize_runtime_role(owner, password)
        environment["MIGRATION_DATABASE_URL"] = owner.render_as_string(hide_password=False)
        subprocess.run([sys.executable, "-m", "backend.app.bootstrap"], env=environment, check=True)
        return
    if mode == "worker":
        command = [sys.executable, "-m", "backend.app.worker"]
    else:
        port = int(environment.get("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid service port")
        command = [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", str(port),
                   "--no-proxy-headers", "--no-server-header", "--ws-max-size", "4096", "--limit-concurrency", "300"]
    # Replace the launcher so Uvicorn/worker receives SIGTERM directly. The
    # owner connection, raw auth seed and separate password variable are absent.
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Connection/config exceptions can contain credentials. Keep diagnostics
        # categorical; never print connection strings or generated secret values.
        print(f"Render setup failed ({type(error).__name__}); check deployment configuration and database permissions.", file=sys.stderr)
        sys.exit(1)
