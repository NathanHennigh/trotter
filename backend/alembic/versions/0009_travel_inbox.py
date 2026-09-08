"""Add stable retained-travel identities linked to immutable booking evidence.

Revision ID: 0009_travel_inbox
Revises: 0008_booking_ledger
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_travel_inbox"
down_revision = "0008_booking_ledger"
branch_labels = None
depends_on = None
pk_type = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade():
    op.create_table(
        "travel_inbox_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("record_key", sa.String(64), nullable=False),
        sa.Column("flight_key", sa.String(64), nullable=False),
        sa.Column("passenger_name", sa.String(255), nullable=True),
        sa.Column("passenger_key", sa.String(255), nullable=True),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "record_key", name="uq_travel_inbox_item_record"),
        sa.CheckConstraint("reason IN ('other_traveler', 'companion', 'unassigned')", name="ck_travel_inbox_item_reason"),
    )
    op.create_index("ix_travel_inbox_items_user_id", "travel_inbox_items", ["user_id"])
    op.create_index("ix_travel_inbox_items_flight_key", "travel_inbox_items", ["flight_key"])
    op.create_table(
        "travel_inbox_evidence",
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("observation_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["travel_inbox_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["observation_id"], ["booking_observations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("item_id", "observation_id", name="uq_travel_inbox_evidence_observation"),
    )
    op.create_index("ix_travel_inbox_evidence_observation_id", "travel_inbox_evidence", ["observation_id"])


def downgrade():
    raise RuntimeError("Travel inbox downgrade is non-destructive: retain the additive inbox and evidence tables when reverting application code.")
