"""Confirm travel identities and recover retained bookings without mailbox replay."""
from alembic import op
import sqlalchemy as sa

revision = "0023_travel_name_recovery"
down_revision = "0022_ios_auth_identities"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("travel_names_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("travel_onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("travel_name_recoveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("names", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        *[sa.Column(name, sa.BigInteger(), nullable=False) for name in ("max_observation_id", "cursor")],
        *[sa.Column(name, sa.Integer(), nullable=False) for name in ("checked", "added", "existing", "needs_review", "attempts")],
        sa.Column("error", sa.Text(), nullable=True),
        *[sa.Column(name, sa.DateTime(timezone=True), nullable=False) for name in ("next_attempt_at", "created_at", "updated_at")])
    op.create_index("ix_travel_name_recoveries_user_id", "travel_name_recoveries", ["user_id"])
    op.create_index("ix_travel_name_recoveries_next_attempt_at", "travel_name_recoveries", ["next_attempt_at"])


def downgrade():
    op.drop_table("travel_name_recoveries")
    op.drop_column("users", "travel_onboarding_completed_at")
    op.drop_column("users", "travel_names_confirmed_at")
