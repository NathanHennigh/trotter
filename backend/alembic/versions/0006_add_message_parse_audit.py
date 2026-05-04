"""Add parse audit fields to messages.

Revision ID: 0006
Revises: 0005_add_discovery_parser_version
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_add_message_parse_audit"
down_revision = "0005_add_discovery_parser_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("parse_error", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("parse_evidence", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "parse_evidence")
    op.drop_column("messages", "parse_error")
