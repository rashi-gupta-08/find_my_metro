"""Accounts, revocable sessions, scoped devices, abuse limits and real timetables."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    op.add_column("trips", sa.Column("timetable", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("username", sa.String(32), nullable=False, unique=True),
                    sa.Column("display_name", sa.String(64), nullable=False),
                    sa.Column("password_hash", sa.String(256), nullable=False),
                    sa.Column("role", sa.String(20), nullable=False),
                    sa.Column("disabled", sa.Boolean(), nullable=False),
                    sa.Column("created_at", sa.String(40), nullable=False))
    op.create_table("auth_sessions", sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("expires_at", sa.String(40), nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table("devices", sa.Column("node_id", sa.String(100), primary_key=True),
                    sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
                    sa.Column("disabled", sa.Boolean(), nullable=False),
                    sa.Column("created_at", sa.String(40), nullable=False))
    op.create_table("rate_buckets", sa.Column("key", sa.String(64), primary_key=True),
                    sa.Column("count", sa.Integer(), nullable=False), sa.Column("expires_at", sa.String(40), nullable=False))
    op.create_index("ix_rate_buckets_expires_at", "rate_buckets", ["expires_at"])
    op.create_table("security_audit", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("at", sa.String(40), nullable=False), sa.Column("actor_id", sa.String(100)),
                    sa.Column("action", sa.String(60), nullable=False))
    op.create_index("ix_security_audit_at", "security_audit", ["at"])


def downgrade():
    for table in ("security_audit", "rate_buckets", "devices", "auth_sessions", "users"):
        op.drop_table(table)
    op.drop_column("trips", "timetable")
