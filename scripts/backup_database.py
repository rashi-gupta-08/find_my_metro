"""Create or restore a PostgreSQL archive without passing passwords on the command line."""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from sqlalchemy.engine import make_url
from backend.app.config import ROOT, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore-new-database"])
    parser.add_argument("archive")
    parser.add_argument("--database", help="A separately created restore target database")
    parser.add_argument("--bin", help="Directory containing pg_dump/pg_restore")
    args = parser.parse_args()
    if not settings.database_url.startswith("postgresql"):
        raise ValueError("This operational backup tool requires PostgreSQL")
    runtime = make_url(settings.database_url)
    bin_dir = args.bin
    record = ROOT / ".local" / "database.json"
    if not bin_dir and record.exists():
        bin_dir = json.loads(record.read_text(encoding="utf-8-sig"))["bin"]
    executable = "pg_dump" if args.action == "backup" else "pg_restore"
    binary = str(Path(bin_dir) / (executable+(".exe" if os.name == "nt" else ""))) if bin_dir else shutil.which(executable)
    if not binary:
        raise ValueError("Install PostgreSQL client tools or specify --bin")
    archive = Path(args.archive).resolve()
    if args.action == "backup":
        if archive.exists():
            raise ValueError("Use a new archive filename; existing backups are never overwritten")
        archive.parent.mkdir(parents=True, exist_ok=True)
        url = runtime
        command = [binary, "--format=custom", "--file", str(archive)]
    else:
        if not args.database or args.database == runtime.database:
            raise ValueError("Restore only into a separate, empty, pre-created database")
        url = make_url(settings.migration_database_url or settings.database_url).set(database=args.database)
        import psycopg
        with psycopg.connect(host=url.host, port=url.port, user=url.username, password=url.password,
                            dbname=url.database, connect_timeout=10) as connection:
            tables = connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
            if tables:
                raise ValueError("Restore target is not empty; existing tables will not be replaced")
        command = [binary, "--exit-on-error", "--no-owner", "--no-acl"]
    command += ["--host", url.host, "--port", str(url.port or 5432), "--username", url.username, "--dbname", url.database]
    if args.action == "restore-new-database":
        command.append(str(archive))
    subprocess.run(command, env={**os.environ, "PGPASSWORD": url.password}, check=True, timeout=300)
    print("Database "+args.action+" completed. Archive: "+str(archive))


if __name__ == "__main__":
    main()
