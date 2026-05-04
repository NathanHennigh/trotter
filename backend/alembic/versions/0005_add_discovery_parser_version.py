"""Add parser version to Gmail discovery state.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_add_discovery_parser_version"
down_revision = "0004_add_message_parse_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gmail_discovery_states",
        sa.Column("parser_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("gmail_discovery_states", "parser_version")
