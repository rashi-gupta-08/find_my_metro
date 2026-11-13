import subprocess
import sys
import os
from .db import transaction, utcnow
from .simulator import seed
from .config import settings
from .models import Runtime


def main():
    environment = dict(os.environ)
    if settings.migration_database_url:
        environment["DATABASE_URL"] = settings.migration_database_url
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=environment)
    with transaction() as session:
        if settings.app_env == "software":
            from .software_feed import generate
            generate(session, utcnow())
        elif settings.simulation_enabled:
            seed(session, utcnow())
        if session.get(Runtime, "worker") is None:
            session.add(Runtime(key="worker", value={"at": "2000-01-01T00:00:00+00:00"}))


if __name__ == "__main__":
    main()
