"""Software report processing timestamps and idempotent contribution rewards."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None


def upgrade():
    op.add_column("observations", sa.Column("validated_at", sa.String(40), nullable=True))
    op.create_table("contribution_awards",
        sa.Column("event_id", sa.String(100), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("station_id", sa.String(60), nullable=False),
        sa.Column("line_id", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("awarded_at", sa.String(40), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False))
    op.create_index("ix_contribution_awards_user_id", "contribution_awards", ["user_id"])
    op.create_index("ix_contribution_awards_awarded_at", "contribution_awards", ["awarded_at"])


def downgrade():
    op.drop_table("contribution_awards")
    op.drop_column("observations", "validated_at")
