"""Checkpoint historical mail and persist exact, previewed itinerary repairs."""
from alembic import op
import sqlalchemy as sa

revision = "0024_controlled_flight_import"
down_revision = "0023_travel_name_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("gmail_history_states",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        *[sa.Column(name, sa.DateTime(timezone=True), nullable=True) for name in
          ("cursor_before", "window_start", "window_end", "next_attempt_at", "lease_until")],
        sa.Column("page_token", sa.Text(), nullable=True),
        sa.Column("next_page_token", sa.Text(), nullable=True),
        sa.Column("pending_message_ids", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(120), nullable=True),
        *[sa.Column(name, sa.DateTime(timezone=True), nullable=False) for name in ("created_at", "updated_at")],
        sa.UniqueConstraint("user_id", "provider", name="uq_gmail_history_user_provider"),
        sa.CheckConstraint("state IN ('pending','queued','running','complete','paused')", name="ck_gmail_history_state"))
    op.create_index("ix_gmail_history_states_user_id", "gmail_history_states", ["user_id"])
    op.create_index("ix_gmail_history_states_next_attempt_at", "gmail_history_states", ["next_attempt_at"])
    op.create_table("booking_repair_manifests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("base_fingerprint", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("preview_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "plan_hash", name="uq_booking_repair_user_plan"),
        sa.CheckConstraint("state IN ('previewed','applied')", name="ck_booking_repair_state"))
    op.create_index("ix_booking_repair_manifests_user_id", "booking_repair_manifests", ["user_id"])


def downgrade():
    op.drop_table("booking_repair_manifests")
    op.drop_table("gmail_history_states")
