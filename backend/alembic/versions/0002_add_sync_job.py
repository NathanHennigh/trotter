import sqlalchemy as sa
from alembic import op

revision = "0002_add_sync_job"
down_revision = "0001_create_base_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("scanned_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parsed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("segment_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("page_token", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("sync_jobs")
