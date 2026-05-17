"""Add Dreams and Dream items.

Revision ID: 0007_add_dreams
Revises: 0006_add_message_parse_audit
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa

pk_type = sa.BigInteger().with_variant(sa.Integer, "sqlite")


revision = "0007_add_dreams"
down_revision = "0006_add_message_parse_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dreams",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "title", "country", "city", "region", name="uq_dream_user_location"),
    )
    op.create_table(
        "dream_items",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("dream_id", sa.BigInteger(), nullable=False),
        sa.Column("source_platform", sa.String(length=32), nullable=False, server_default="instagram"),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("raw_metadata_json", sa.JSON(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("place_name", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("region_or_neighborhood", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default="Saved from Instagram"),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("needs_google_places_lookup", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("google_place_id", sa.String(length=255), nullable=True),
        sa.Column("google_maps_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="needs_review"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dream_id"], ["dreams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "source_url", name="uq_dream_item_user_source_url"),
    )


def downgrade() -> None:
    op.drop_table("dream_items")
    op.drop_table("dreams")
