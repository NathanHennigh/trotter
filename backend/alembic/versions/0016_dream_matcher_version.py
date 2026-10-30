"""Let unresolved named saves benefit once from a deliberate matcher upgrade."""
from alembic import op
import sqlalchemy as sa

revision = "0016_dream_matcher_version"
down_revision = "0015_dream_personal_notes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dream_locations", sa.Column("matcher_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("dream_locations", sa.Column("matcher_retry_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("dream_locations", sa.Column("matcher_generation", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_dream_locations_matcher_recovery", "dream_locations",
                    [sa.text("(CASE WHEN matcher_generation = generation THEN matcher_version ELSE 0 END)"), "id"],
                    postgresql_where=sa.text("status IN ('not_found', 'failed')"),
                    sqlite_where=sa.text("status IN ('not_found', 'failed')"))


def downgrade():
    raise RuntimeError("Refusing to discard matcher retry history. Keep this schema when rolling back application code.")
