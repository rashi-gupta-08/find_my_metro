"""Prevent unverified account creation from manufacturing independent agreement."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column("verified_contributor", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("users", "verified_contributor")
