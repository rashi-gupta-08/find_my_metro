"""Run regression tests in a newly created PostgreSQL database, never the app DB."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import psycopg
from psycopg import sql
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[1]


def main():
    values=dotenv_values(ROOT/".env")
    owner=make_url(values["MIGRATION_DATABASE_URL"])
    runtime=make_url(values["DATABASE_URL"])
    if owner.get_backend_name()!="postgresql" or runtime.get_backend_name()!="postgresql":
        raise ValueError("Configure the local PostgreSQL installation first")
    database="metro_validation_"+uuid.uuid4().hex[:16]
    # The random database is created by this invocation and is the only cleanup target.
    assert database.startswith("metro_validation_") and database not in {owner.database,runtime.database,"postgres"}
    connection=psycopg.connect(host=owner.host,port=owner.port,user="metro_admin",password=values["POSTGRES_PASSWORD"],
                               dbname="postgres",autocommit=True,connect_timeout=10)
    created=False
    output=ROOT/".local/software-postgres-tests.log"
    try:
        connection.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(database),sql.Identifier(owner.username)))
        created=True
        environment={**os.environ,"TEST_DATABASE_URL":owner.set(database=database).render_as_string(hide_password=False)}
        with output.open("w",encoding="utf-8") as log:
            targets=sys.argv[1:] or ["backend/tests"]
            result=subprocess.run([sys.executable,"-u","-m","pytest",*targets,"-q","--tb=short"],cwd=ROOT,
                env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        print(output.read_text(encoding="utf-8"))
        if result.returncode:
            raise RuntimeError("PostgreSQL regression checks failed; inspect the recorded test log")
    finally:
        if created:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
        connection.close()
    # The application account can read the upgraded schema without DDL privileges.
    with psycopg.connect(host=runtime.host,port=runtime.port,user=runtime.username,password=runtime.password,
                          dbname=runtime.database,connect_timeout=10) as current:
        schema=current.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        accounts=current.execute("SELECT count(*) FROM users").fetchone()[0]
        current.execute("SELECT count(*) FROM contribution_awards").fetchone()
    (ROOT/".local/software-postgres-verification.json").write_text(json.dumps({"schema_version":schema,
        "existing_accounts_preserved":accounts,"runtime_can_read_awards":True,"isolated_test_database_removed":True},indent=2))
    print("PostgreSQL verification passed; the newly created test database was removed. Passenger data was not used for test fixtures.")


if __name__=="__main__":
    main()
