"""Track optional Gmail authorization without changing stored credentials."""
from alembic import op
import sqlalchemy as sa

revision = "0021_optional_gmail_connection"
down_revision = "0020_planner_transport_modes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("gmail_connection_status", sa.String(24), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM accounts WHERE gmail_connection_status='needs_reconnect' LIMIT 1")).first():
        raise RuntimeError("Reconnect or remove revoked Gmail connections before dropping their authorization state.")
    op.drop_column("accounts", "gmail_connection_status")
