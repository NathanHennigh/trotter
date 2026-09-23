"""Add durable Dreams enrichment work without rewriting existing saves."""
from alembic import op
import sqlalchemy as sa

revision = "0012_dream_enrichment_jobs"
down_revision = "0011_dream_google_identities"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dream_enrichment_jobs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("item_id", sa.BigInteger(), sa.ForeignKey("dream_items.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="ck_dream_enrichment_status"),
    )
    for column in ("user_id", "status", "next_attempt_at"):
        op.create_index(f"ix_dream_enrichment_jobs_{column}", "dream_enrichment_jobs", [column])


def downgrade():
    raise RuntimeError("Refusing to delete durable Dreams work. Keep this additive table when rolling back code.")
