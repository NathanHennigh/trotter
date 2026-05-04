import sqlalchemy as sa
from alembic import op

pk_type = sa.BigInteger().with_variant(sa.Integer, "sqlite")

revision = "0003_add_gmail_discovery_state"
down_revision = "0002_add_sync_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_discovery_states",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="google"),
        sa.Column("last_incremental_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfill_cursor_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfill_complete", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "provider", name="uq_gmail_discovery_user_provider"),
    )
    op.create_table(
        "gmail_discovery_signals",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="google"),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("signal_value", sa.String(255), nullable=False),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "signal_type",
            "signal_value",
            name="uq_gmail_discovery_signal",
        ),
    )


def downgrade() -> None:
    op.drop_table("gmail_discovery_signals")
    op.drop_table("gmail_discovery_states")
