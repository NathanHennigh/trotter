"""Stable provider identities and single-use native Apple challenges."""
from alembic import op
import sqlalchemy as sa

revision = "0022_ios_auth_identities"
down_revision = "0021_optional_gmail_connection"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")])
    op.create_table("auth_identities",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "subject", name="uq_auth_identity_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
        sa.CheckConstraint("provider IN ('google','apple')", name="ck_auth_identity_provider"))
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])
    op.create_index("ix_auth_identity_email_lower", "auth_identities", [sa.text("lower(email)")])
    op.create_table("apple_auth_challenges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("nonce_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('signin','link','reauth')", name="ck_apple_challenge_purpose"))
    op.create_index("ix_apple_auth_challenges_expires_at", "apple_auth_challenges", ["expires_at"])
    op.create_table("account_erasure_cleanup",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("thumbnail_item_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_swept_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM auth_identities WHERE provider='apple' LIMIT 1")).first():
        raise RuntimeError("Cannot drop Apple identities while accounts depend on Apple sign-in.")
    op.drop_table("apple_auth_challenges")
    op.drop_table("auth_identities")
    op.drop_table("account_erasure_cleanup")
    op.drop_index("ix_users_email_lower", table_name="users")
