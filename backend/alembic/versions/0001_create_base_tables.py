from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography


revision = "0001_create_base_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"users",
		sa.Column("id", sa.BigInteger, primary_key=True),
		sa.Column("email", sa.String(255), nullable=False, unique=True),
		sa.Column("name", sa.String(255), nullable=True),
		sa.Column("home_tz", sa.String(64), nullable=True),
		sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
	)

	op.create_table(
		"accounts",
		sa.Column("id", sa.BigInteger, primary_key=True),
		sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
		sa.Column("provider", sa.String(32), nullable=False),
		sa.Column("refresh_token_encrypted", sa.LargeBinary, nullable=False),
		sa.Column("scopes", sa.Text, nullable=False),
		sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
	)

	op.create_table(
		"messages",
		sa.Column("id", sa.BigInteger, primary_key=True),
		sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
		sa.Column("provider_msg_id", sa.String(255), nullable=False),
		sa.Column("internal_ts", sa.DateTime(timezone=True), nullable=True),
		sa.Column("from_domain_hash", sa.String(64), nullable=True),
		sa.Column("from_email", sa.String(320), nullable=True),
		sa.Column("subject", sa.Text, nullable=True),
		sa.Column("snippet_sha256", sa.String(64), nullable=True),
		sa.Column("status", sa.Enum("pending", "review_required", "accepted", "ignored", name="message_status"), nullable=False, server_default="pending"),
		sa.Column("ignored", sa.Boolean, nullable=False, server_default=sa.text("false")),
		sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
	)
	op.create_unique_constraint("uq_messages_user_provider", "messages", ["user_id", "provider_msg_id"])

	op.create_table(
		"trips",
		sa.Column("id", sa.BigInteger, primary_key=True),
		sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
		sa.Column("title", sa.String(255), nullable=True),
		sa.Column("start_ts", sa.DateTime(timezone=True), nullable=True),
		sa.Column("end_ts", sa.DateTime(timezone=True), nullable=True),
		sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
	)

	op.create_table(
		"segments",
		sa.Column("id", sa.BigInteger, primary_key=True),
		sa.Column("trip_id", sa.BigInteger, sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
		sa.Column("mode", sa.String(16), nullable=False),
		sa.Column("dep_airport", sa.String(8), nullable=False),
		sa.Column("arr_airport", sa.String(8), nullable=False),
		sa.Column("dep_time", sa.DateTime(timezone=True), nullable=False),
		sa.Column("arr_time", sa.DateTime(timezone=True), nullable=False),
		sa.Column("airline", sa.String(8), nullable=True),
		sa.Column("flight_number", sa.String(16), nullable=True),
		sa.Column("pnr", sa.String(16), nullable=True),
		sa.Column("distance_km", sa.Float, nullable=True),
		sa.Column("geom", Geography(geometry_type="LINESTRING", srid=4326), nullable=True),
		sa.Column("meta_json", sa.JSON, nullable=True),
	)
	op.create_unique_constraint("uq_segments_trip_flight", "segments", ["trip_id", "airline", "flight_number", "dep_time"])


