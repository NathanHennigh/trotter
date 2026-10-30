"""Private traveler annotations and recipient-bound flight invitations."""
from alembic import op
import sqlalchemy as sa

revision = "0017_flight_sharing"
down_revision = "0016_dream_matcher_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("travel_inbox_assignments",
        sa.Column("item_id", sa.String(36), sa.ForeignKey("travel_inbox_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("passenger_name", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_travel_inbox_assignments_user_id", "travel_inbox_assignments", ["user_id"])
    op.create_table("flight_shares",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sender_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("recipient_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("passenger_name", sa.String(255), nullable=False),
        sa.Column("client_request_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=False),
        sa.Column("flights", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_flights", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("existing_flights", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_segment_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("sender_id", "client_request_id", name="uq_flight_share_request"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'declined', 'revoked')", name="ck_flight_share_status"))
    op.create_index("ix_flight_shares_sender_id", "flight_shares", ["sender_id"])
    op.create_index("ix_flight_shares_recipient_email", "flight_shares", ["recipient_email"])


def downgrade():
    raise RuntimeError("Refusing to discard shared-flight evidence. Roll back application code with these additive tables retained.")
