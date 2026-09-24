"""Keep one source post with independently editable saved places."""
from alembic import op
import sqlalchemy as sa

revision = "0013_dream_source_places"
down_revision = "0012_dream_enrichment_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dream_source_posts",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_platform", sa.String(32), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("raw_metadata_json", sa.JSON()),
        sa.Column("removed_place_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "source_url", name="uq_dream_source_user_url"),
    )
    op.create_index("ix_dream_source_posts_user_id", "dream_source_posts", ["user_id"])
    with op.batch_alter_table("dream_items") as batch:
        batch.add_column(sa.Column("source_post_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("source_place_key", sa.String(64), nullable=False, server_default="primary"))
        batch.add_column(sa.Column("source_place_index", sa.Integer(), nullable=False, server_default="0"))
        batch.create_foreign_key("fk_dream_item_source_post", "dream_source_posts", ["source_post_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_dream_items_source_post_id", ["source_post_id"])
        batch.drop_constraint("uq_dream_item_user_source_url", type_="unique")
        batch.create_unique_constraint("uq_dream_item_user_source_place", ["user_id", "source_url", "source_place_key"])
    op.add_column("dream_enrichment_jobs", sa.Column("source_generation", sa.Integer(), nullable=True))
    # Deliberately do not rewrite old saves, request providers, or start jobs here.
    # Source records are attached lazily; the explicit backfill uses saved parser data.


def downgrade():
    raise RuntimeError("Refusing to discard saved places. Keep this schema when rolling back application code.")
