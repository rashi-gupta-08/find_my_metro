"""Create only the separate software-validation database and private configuration."""
from pathlib import Path
import secrets
from datetime import datetime, timezone
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[1]


def main():
    original=dotenv_values(ROOT/".env")
    runtime=make_url(original["DATABASE_URL"])
    owner=make_url(original["MIGRATION_DATABASE_URL"])
    if runtime.get_backend_name()!="postgresql":
        raise RuntimeError("Set up the application PostgreSQL installation before software validation.")
    admin=owner.set(username="metro_admin",password=original["POSTGRES_PASSWORD"],database="postgres")
    with create_engine(admin,isolation_level="AUTOCOMMIT").connect() as connection:
        exists=connection.scalar(text("SELECT 1 FROM pg_database WHERE datname='metro_software'"))
        if not exists: connection.execute(text('CREATE DATABASE metro_software OWNER metro_owner'))
    software_owner=owner.set(database="metro_software")
    with create_engine(software_owner).begin() as connection:
        connection.execute(text('REVOKE CREATE ON SCHEMA public FROM PUBLIC'))
        connection.execute(text('GRANT USAGE ON SCHEMA public TO metro'))
        connection.execute(text('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO metro'))
        connection.execute(text('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO metro'))
        connection.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO metro'))
        connection.execute(text('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO metro'))
    folder=ROOT/'.local/software'
    folder.mkdir(parents=True,exist_ok=True)
    from backend.app.software_feed import network_contract
    import json
    (folder/'network.json').write_text(json.dumps(network_contract(datetime.now(timezone.utc)),indent=2),encoding='utf-8')
    previous=dotenv_values(ROOT/'.local/software.env')
    values={"APP_ENV":"software","SIMULATION_ENABLED":"true","SECURE_COOKIES":"false",
            "AUTH_SECRET":previous.get("AUTH_SECRET") or secrets.token_urlsafe(64),
            "DATABASE_URL":runtime.set(database="metro_software").render_as_string(hide_password=False),
            "MIGRATION_DATABASE_URL":software_owner.render_as_string(hide_password=False),
            "NETWORK_FILE":".local/software/network.json","CORS_ORIGINS":"http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
            "ALLOWED_HOSTS":"localhost,127.0.0.1","PREDICTION_MODEL_FILE":".local/software/prediction-model.json"}
    (ROOT/'.local/software.env').write_text('\n'.join(f'{key}={value}' for key,value in values.items())+'\n',encoding='utf-8')
    print('Separate PostgreSQL software database and private configuration are ready. Original operator data was preserved.')


if __name__=='__main__':
    main()
