"""Durable collaborative plans, independent of imported flight groupings."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, DateTime, Float,
                        ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint)

from .models import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class PlannerTrip(Base):
    __tablename__ = "planner_trips"
    __table_args__ = (UniqueConstraint("owner_id", "client_request_id", name="uq_planner_trip_request"),)
    id = Column(String(36), primary_key=True, default=uid)
    owner_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_request_id = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    destination = Column(String(255), nullable=False)
    match_country_key = Column(String(128), nullable=True)
    match_city_key = Column(String(128), nullable=True)
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    timezone = Column(String(64), nullable=False, default="UTC")
    pace = Column(String(16), nullable=False, default="balanced")
    transport = Column(String(16), nullable=False, default="walk")
    transport_modes = Column(JSON, nullable=False, default=lambda: ["walk"], server_default='["walk"]')
    version = Column(Integer, nullable=False, default=1)
    accepted_revision_id = Column(String(36), nullable=True)
    draft_revision_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)


class PlannerMember(Base):
    __tablename__ = "planner_members"
    __table_args__ = (CheckConstraint("role IN ('owner','editor','contributor')", name="ck_planner_member_role"),
                     Index("ix_planner_member_dream_sync", "dream_auto_share", "dream_last_synced_at"))
    trip_id = Column(String(36), ForeignKey("planner_trips.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(16), nullable=False)
    joined_at = Column(DateTime(timezone=True), nullable=False, default=now)
    removed_at = Column(DateTime(timezone=True), nullable=True)
    dream_auto_share = Column(Boolean, nullable=False, default=False, server_default="0")
    dream_consented_at = Column(DateTime(timezone=True), nullable=True)
    dream_sync_item_id = Column(BigInteger, nullable=True)
    dream_last_synced_at = Column(DateTime(timezone=True), nullable=True)


class PlannerIdea(Base):
    __tablename__ = "planner_ideas"
    __table_args__ = (UniqueConstraint("trip_id", "identity_key", name="uq_planner_idea_identity"),
                     Index("ix_planner_idea_dream_match", "trip_id", "dream_match_key"),
                     Index("ix_planner_idea_provider_match", "trip_id", "google_place_id"))
    id = Column(String(36), primary_key=True, default=uid)
    trip_id = Column(String(36), ForeignKey("planner_trips.id", ondelete="CASCADE"), nullable=False, index=True)
    identity_key = Column(String(64), nullable=False)
    dream_match_key = Column(String(64), nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    category = Column(String(32), nullable=False, default="place")
    city = Column(String(128), nullable=True)
    country = Column(String(128), nullable=True)
    region_or_neighborhood = Column(String(128), nullable=True)
    source_url = Column(Text, nullable=True)
    google_place_id = Column(String(255), nullable=True)
    # Only user-supplied/manual coordinates belong here. Google data stays transient.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=60)
    must_do = Column(Boolean, nullable=False, default=False)
    status = Column(String(24), nullable=False, default="ready")
    user_edited = Column(Boolean, nullable=False, default=False)
    merged_into_id = Column(String(36), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class PlannerContribution(Base):
    __tablename__ = "planner_contributions"
    __table_args__ = (UniqueConstraint("trip_id", "user_id", "identity_key", name="uq_planner_contribution_identity"),
                     Index("ix_planner_contribution_dream", "trip_id", "user_id", "dream_item_id"))
    id = Column(String(36), primary_key=True, default=uid)
    trip_id = Column(String(36), ForeignKey("planner_trips.id", ondelete="CASCADE"), nullable=False, index=True)
    idea_id = Column(String(36), ForeignKey("planner_ideas.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    identity_key = Column(String(255), nullable=False)
    dream_item_id = Column(BigInteger, ForeignKey("dream_items.id", ondelete="SET NULL"), nullable=True)
    source_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class PlannerVote(Base):
    __tablename__ = "planner_votes"
    __table_args__ = (CheckConstraint("value IN (-1,1)", name="ck_planner_vote_value"),)
    idea_id = Column(String(36), ForeignKey("planner_ideas.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    value = Column(Integer, nullable=False)


class PlannerInvite(Base):
    __tablename__ = "planner_invites"
    __table_args__ = (UniqueConstraint("trip_id", "client_request_id", name="uq_planner_invite_request"),)
    id = Column(String(36), primary_key=True, default=uid)
    trip_id = Column(String(36), ForeignKey("planner_trips.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    client_request_id = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    token_encrypted = Column(LargeBinary, nullable=False)
    role = Column(String(16), nullable=False)
    label = Column(String(100), nullable=True)
    recipient_email = Column(String(255), nullable=True)
    max_uses = Column(Integer, nullable=False, default=25)
    uses = Column(Integer, nullable=False, default=0)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class PlannerInviteAcceptance(Base):
    __tablename__ = "planner_invite_acceptances"
    invite_id = Column(String(36), ForeignKey("planner_invites.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    accepted_at = Column(DateTime(timezone=True), nullable=False, default=now)


class PlannerRevision(Base):
    __tablename__ = "planner_revisions"
    id = Column(String(36), primary_key=True, default=uid)
    trip_id = Column(String(36), ForeignKey("planner_trips.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    base_version = Column(Integer, nullable=False)
    plan = Column(JSON, nullable=False)
    source = Column(String(16), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class PlannerJob(Base):
    __tablename__ = "planner_jobs"
    __table_args__ = (UniqueConstraint("user_id", "client_request_id", name="uq_planner_job_request"),
                     CheckConstraint("status IN ('queued','running','completed','failed')", name="ck_planner_job_status"))
    id = Column(String(36), primary_key=True, default=uid)
    trip_id = Column(String(36), ForeignKey("planner_trips.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_request_id = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    base_version = Column(Integer, nullable=False)
    input_json = Column(JSON, nullable=False)
    use_ai = Column(Boolean, nullable=False)
    status = Column(String(16), nullable=False, default="queued", index=True)
    message = Column(String(255), nullable=True)
    revision_id = Column(String(36), ForeignKey("planner_revisions.id", ondelete="SET NULL"), nullable=True)
    usage_json = Column(JSON, nullable=False, default=dict)
    lease_token = Column(String(36), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class PlannerSourceShare(Base):
    __tablename__ = "planner_source_shares"
    __table_args__ = (UniqueConstraint("trip_id", "user_id", "source_key", name="uq_planner_source_share"),)
    id = Column(String(36), primary_key=True, default=uid)
    trip_id = Column(String(36), ForeignKey("planner_trips.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_key = Column(String(64), nullable=False)
    source_url = Column(Text, nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


# Either model module may be imported first; bind hooks only after all classes exist.
from .models import DreamItem as _DreamItem  # noqa: E402
from .services.planner_geography import register_model_events as _register_geography_events  # noqa: E402
_register_geography_events(_DreamItem, PlannerIdea)
