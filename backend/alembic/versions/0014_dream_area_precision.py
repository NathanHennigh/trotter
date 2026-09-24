"""Distinguish an area marker from a precise saved venue."""
from alembic import op
import sqlalchemy as sa

revision = "0014_dream_area_precision"
down_revision = "0013_dream_source_places"
branch_labels = None
depends_on = None


def upgrade():
    # Application display state only: no provider content, requests or rewrites.
    op.add_column("dream_locations", sa.Column("coordinate_precision", sa.String(16), nullable=True))


def downgrade():
    raise RuntimeError("Refusing to discard location precision. Keep this schema when rolling back application code.")
