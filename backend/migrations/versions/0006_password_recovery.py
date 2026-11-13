"""One-time operator-issued password recovery grants."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = depends_on = None


def upgrade():
    op.create_table("password_resets",
                    sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("expires_at", sa.String(40), nullable=False))
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])
    op.create_index("ix_password_resets_expires_at", "password_resets", ["expires_at"])


def downgrade():
    op.drop_table("password_resets")
