"""Add durable Dreams location resolution without changing existing saved records."""
from alembic import op
import sqlalchemy as sa

revision = "0010_dream_locations"
down_revision = "0009_travel_inbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dream_locations",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True),
        sa.Column("item_id", sa.BigInteger(), sa.ForeignKey("dream_items.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("pin_fingerprint", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("provider", sa.String(32)), sa.Column("address", sa.Text()),
        sa.Column("latitude", sa.Float()), sa.Column("longitude", sa.Float()),
        sa.Column("google_maps_url", sa.Text()),
        sa.Column("candidates", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("history", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("message", sa.Text()), sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'resolved', 'needs_review', 'not_found', 'failed', 'blocked', 'manual')", name="ck_dream_location_status"),
    )
    for column in ("user_id", "status", "next_attempt_at"):
        op.create_index(f"ix_dream_locations_{column}", "dream_locations", [column])


def downgrade():
    raise RuntimeError("Refusing to delete saved Dreams location evidence. Restore a verified backup to roll back this migration.")
