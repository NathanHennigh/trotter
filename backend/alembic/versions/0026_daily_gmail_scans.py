"""Distinguish daily new-mail scans from historical and interactive jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0026_daily_gmail_scans"
down_revision = "0025_carrier_travel_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sync_jobs", sa.Column("kind", sa.String(16), nullable=True))
    op.create_index("ix_sync_jobs_user_kind_started", "sync_jobs", ["user_id", "kind", "started_at"])


def downgrade():
    op.drop_index("ix_sync_jobs_user_kind_started", table_name="sync_jobs")
    op.drop_column("sync_jobs", "kind")
