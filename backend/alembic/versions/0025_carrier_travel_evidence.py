"""Retain indexed carrier assertions separately from passenger manifests."""
from alembic import op
import sqlalchemy as sa

revision = "0025_carrier_travel_evidence"
down_revision = "0024_controlled_flight_import"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_booking_observation_user_date", "booking_observations", ["user_id", "travel_date"])
    op.create_table("carrier_travel_evidence",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_key", sa.String(64), nullable=False),
        sa.Column("source_message_id", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_version", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("carrier", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("local_day", sa.String(10), nullable=True),
        sa.Column("dep_airport", sa.String(8), nullable=True),
        sa.Column("arr_airport", sa.String(8), nullable=True),
        sa.Column("pnr", sa.String(16), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "evidence_key", name="uq_carrier_travel_evidence"))
    for name, columns in (
        ("date", ["user_id", "carrier", "local_day"]),
        ("booking", ["user_id", "carrier", "pnr"]),
        ("source", ["user_id", "source_message_id"]),
    ):
        op.create_index("ix_carrier_evidence_user_" + name, "carrier_travel_evidence", columns)


def downgrade():
    op.drop_table("carrier_travel_evidence")
    op.drop_index("ix_booking_observation_user_date", table_name="booking_observations")
