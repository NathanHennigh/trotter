import sqlalchemy as sa
from alembic import op

revision = "0004_add_message_parse_version"
down_revision = "0003_add_gmail_discovery_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("parse_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("messages", "parse_version")
