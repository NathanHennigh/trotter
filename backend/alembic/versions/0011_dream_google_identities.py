"""Add Google Place identities without modifying saved content or existing resolution rows."""
from alembic import op
import sqlalchemy as sa

revision = "0011_dream_google_identities"
down_revision = "0010_dream_locations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dream_google_identities",
        sa.Column("location_id", sa.BigInteger(), sa.ForeignKey("dream_locations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("selected_place_id", sa.Text()),
        sa.Column("confirmed_place_id", sa.Text()),
        sa.Column("place_fingerprint", sa.String(64)),
        sa.Column("candidate_place_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("coordinates_expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_after", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_dream_google_identities_refresh_after", "dream_google_identities", ["refresh_after"])


def downgrade():
    raise RuntimeError("Refusing to delete saved Google Place identities or user choices. Restore a verified backup to roll back this migration.")
