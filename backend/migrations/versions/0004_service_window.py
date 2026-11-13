"""Index active dated services without loading historical journeys."""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def upgrade():
    op.add_column("trips", sa.Column("service_end", sa.String(40)))
    op.add_column("trips", sa.Column("network_version", sa.String(80)))
    op.add_column("trips", sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_trips_service_end", "trips", ["service_end"])
    op.create_index("ix_trips_network_version", "trips", ["network_version"])
    trips = sa.table("trips", sa.column("id", sa.String()), sa.column("timetable", sa.JSON()),
                     sa.column("scheduled_start", sa.String()), sa.column("service_end", sa.String()),
                     sa.column("network_version", sa.String()), sa.column("cancelled", sa.Boolean()))
    connection = op.get_bind()
    for row in connection.execute(sa.select(trips.c.id, trips.c.timetable)).mappings():
        data = row["timetable"] or {}
        stops = data.get("stops", [])
        if stops and data.get("network_version"):
            start = datetime.fromisoformat(stops[0]["arrival_at"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            end = datetime.fromisoformat(stops[-1]["departure_at"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            connection.execute(trips.update().where(trips.c.id == row["id"]).values(
                scheduled_start=start, service_end=end, network_version=data["network_version"], cancelled=data.get("cancelled", False)))


def downgrade():
    op.drop_index("ix_trips_network_version", table_name="trips")
    op.drop_index("ix_trips_service_end", table_name="trips")
    for column in ["cancelled", "network_version", "service_end"]:
        op.drop_column("trips", column)
