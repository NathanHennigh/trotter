"""Add immutable booking evidence and pre-mutation itinerary history.

Revision ID: 0008_booking_ledger
Revises: 0007_add_dreams
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_booking_ledger"
down_revision = "0007_add_dreams"
branch_labels = None
depends_on = None
pk_type = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def _base_columns():
    return [
        sa.Column("id", pk_type, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_key", sa.String(64), nullable=False),
    ]


def _constraints(unique_name):
    return [
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "evidence_key", name=unique_name),
    ]


def upgrade():
    op.add_column("users", sa.Column("travel_name_aliases", sa.JSON(), nullable=False, server_default="[]"))
    op.create_table(
        "booking_observations", *_base_columns(),
        sa.Column("source_message_id", sa.String(255), nullable=True),
        sa.Column("source_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pnr", sa.String(16), nullable=True),
        sa.Column("travel_date", sa.String(10), nullable=True),
        sa.Column("dep_airport", sa.String(8), nullable=True),
        sa.Column("arr_airport", sa.String(8), nullable=True),
        sa.Column("flight_number", sa.String(16), nullable=True),
        sa.Column("ownership", sa.String(16), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *_constraints("uq_booking_observation_evidence"),
    )
    op.create_table(
        "booking_cancellations", *_base_columns(),
        sa.Column("source_message_id", sa.String(255), nullable=True),
        sa.Column("source_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pnr", sa.String(16), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *_constraints("uq_booking_cancellation_evidence"),
    )
    op.create_table(
        "itinerary_history", *_base_columns(),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *_constraints("uq_itinerary_history_evidence"),
    )
    for table in ("booking_observations", "booking_cancellations", "itinerary_history"):
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
    for table in ("booking_observations", "booking_cancellations"):
        op.create_index(f"ix_{table}_pnr", table, ["pnr"])


def downgrade():
    # Reverting application code is safe with these additive tables left intact.
    # An automatic schema rollback must never erase original booking evidence.
    raise RuntimeError("Booking ledger downgrade is non-destructive: retain the additive evidence tables when reverting application code.")
