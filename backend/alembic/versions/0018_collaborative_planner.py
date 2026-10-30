"""Stable shared trips, invitations, revisions and bounded generation jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0018_collaborative_planner"
down_revision = "0017_flight_sharing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('planner_trips',
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('owner_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_request_id', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('destination', sa.String(length=255), nullable=False),
        sa.Column('start_date', sa.String(length=10), nullable=False),
        sa.Column('end_date', sa.String(length=10), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False),
        sa.Column('pace', sa.String(length=16), nullable=False),
        sa.Column('transport', sa.String(length=16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('accepted_revision_id', sa.String(length=36), nullable=True),
        sa.Column('draft_revision_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'client_request_id', name='uq_planner_trip_request'))
    op.create_index('ix_planner_trips_owner_id', 'planner_trips', ['owner_id'], unique=False)

    op.create_table('planner_ideas',
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('planner_trips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('identity_key', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('city', sa.String(length=128), nullable=True),
        sa.Column('country', sa.String(length=128), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('google_place_id', sa.String(length=255), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('must_do', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('user_edited', sa.Boolean(), nullable=False),
        sa.Column('merged_into_id', sa.String(length=36), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('trip_id', 'identity_key', name='uq_planner_idea_identity'))
    op.create_index('ix_planner_ideas_trip_id', 'planner_ideas', ['trip_id'], unique=False)

    op.create_table('planner_invites',
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('planner_trips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('client_request_id', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('token_encrypted', sa.LargeBinary(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=True),
        sa.Column('recipient_email', sa.String(length=255), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=False),
        sa.Column('uses', sa.Integer(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('token_hash', name=None),
        sa.UniqueConstraint('trip_id', 'client_request_id', name='uq_planner_invite_request'))
    op.create_index('ix_planner_invites_trip_id', 'planner_invites', ['trip_id'], unique=False)

    op.create_table('planner_members',
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('planner_trips.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('owner','editor','contributor')", name='ck_planner_member_role'))

    op.create_table('planner_revisions',
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('planner_trips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('base_version', sa.Integer(), nullable=False),
        sa.Column('plan', sa.JSON(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_planner_revisions_trip_id', 'planner_revisions', ['trip_id'], unique=False)

    op.create_table('planner_source_shares',
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('planner_trips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_key', sa.String(length=64), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('trip_id', 'user_id', 'source_key', name='uq_planner_source_share'))
    op.create_index('ix_planner_source_shares_trip_id', 'planner_source_shares', ['trip_id'], unique=False)
    op.create_index('ix_planner_source_shares_last_synced_at', 'planner_source_shares', ['last_synced_at'], unique=False)

    op.create_table('planner_contributions',
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('planner_trips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('idea_id', sa.String(length=36), sa.ForeignKey('planner_ideas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('identity_key', sa.String(length=255), nullable=False),
        sa.Column('dream_item_id', sa.BigInteger(), sa.ForeignKey('dream_items.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('trip_id', 'user_id', 'identity_key', name='uq_planner_contribution_identity'))
    op.create_index('ix_planner_contributions_idea_id', 'planner_contributions', ['idea_id'], unique=False)
    op.create_index('ix_planner_contributions_trip_id', 'planner_contributions', ['trip_id'], unique=False)

    op.create_table('planner_invite_acceptances',
        sa.Column('invite_id', sa.String(length=36), sa.ForeignKey('planner_invites.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False))

    op.create_table('planner_jobs',
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('planner_trips.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_request_id', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('base_version', sa.Integer(), nullable=False),
        sa.Column('input_json', sa.JSON(), nullable=False),
        sa.Column('use_ai', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('message', sa.String(length=255), nullable=True),
        sa.Column('revision_id', sa.String(length=36), sa.ForeignKey('planner_revisions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('usage_json', sa.JSON(), nullable=False),
        sa.Column('lease_token', sa.String(length=36), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued','running','completed','failed')", name='ck_planner_job_status'),
        sa.UniqueConstraint('user_id', 'client_request_id', name='uq_planner_job_request'))
    op.create_index('ix_planner_jobs_status', 'planner_jobs', ['status'], unique=False)
    op.create_index('ix_planner_jobs_trip_id', 'planner_jobs', ['trip_id'], unique=False)
    op.create_index('ix_planner_jobs_user_id', 'planner_jobs', ['user_id'], unique=False)

    op.create_table('planner_votes',
        sa.Column('idea_id', sa.String(length=36), sa.ForeignKey('planner_ideas.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('value', sa.Integer(), nullable=False),
        sa.CheckConstraint('value IN (-1,1)', name='ck_planner_vote_value'))


def downgrade():
    tables = ["planner_jobs", "planner_invite_acceptances", "planner_contributions", "planner_votes",
              "planner_source_shares", "planner_revisions", "planner_members", "planner_invites", "planner_ideas", "planner_trips"]
    bind = op.get_bind()
    if any(bind.execute(sa.text(f'SELECT 1 FROM "{name}" LIMIT 1')).first() for name in tables):
        raise RuntimeError("Refusing to discard shared plans and membership history. Roll back code while retaining these additive tables.")
    for name in tables:
        op.drop_table(name)
