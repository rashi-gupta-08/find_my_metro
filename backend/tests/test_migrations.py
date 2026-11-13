import json
import os
import sqlite3
import subprocess
import sys


def test_upgrade_preserves_accounts_and_backfills_service_window(tmp_path):
    database = tmp_path / "migration.db"
    environment = {**os.environ, "APP_ENV":"test", "DATABASE_URL":"sqlite:///"+database.as_posix(), "MIGRATION_DATABASE_URL":"", "NETWORK_FILE":""}
    command = [sys.executable, "-m", "alembic", "upgrade"]
    subprocess.run(command+["0003"], env=environment, check=True, capture_output=True, timeout=30)
    timetable = {"network_version":"verified-v1", "cancelled":True, "stops":[
        {"station_id":"a", "arrival_at":"2026-10-08T10:00:00+05:30", "departure_at":"2026-10-08T10:00:10+05:30"},
        {"station_id":"b", "arrival_at":"2026-10-08T10:02:00+05:30", "departure_at":"2026-10-08T10:02:10+05:30"}]}
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO trips (id,code,line_id,direction,scheduled_start,scheduled_delay_seconds,state,version,timetable) VALUES (?,?,?,?,?,?,?,?,?)",
                           ("operator-trip","DM-11","line","outbound","2026-10-08T10:00:00+05:30",0,"{}",1,json.dumps(timetable)))
        connection.execute("INSERT INTO users (id,username,display_name,password_hash,role,disabled,created_at,verified_contributor) VALUES (?,?,?,?,?,?,?,?)",
                           ("preserved-user","passenger","Passenger","hash","passenger",0,"2026-10-08T00:00:00+00:00",0))
    subprocess.run(command+["head"], env=environment, check=True, capture_output=True, timeout=30)
    subprocess.run(command+["head"], env=environment, check=True, capture_output=True, timeout=30)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        result = connection.execute("SELECT scheduled_start,service_end,network_version,cancelled FROM trips").fetchone()
        assert result == ("2026-10-08T04:30:00+00:00","2026-10-08T04:32:10+00:00","verified-v1",1)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006"
        assert connection.execute("SELECT count(*) FROM password_resets").fetchone()[0] == 0
