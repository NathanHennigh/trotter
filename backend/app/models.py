# backend/app/models.py
"""
SQLAlchemy models for the application.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Text, LargeBinary, Boolean, ForeignKey, Float, JSON, Enum, UniqueConstraint, CheckConstraint, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
import enum

Base = declarative_base()


class MessageStatus(enum.Enum):
    PENDING = "pending"
    REVIEW_REQUIRED = "review_required"
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_email_lower", text("lower(email)")),)
    
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=True)
    travel_name_aliases = Column(JSON, nullable=False, default=list, server_default="[]")
    travel_names_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    travel_onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    home_tz = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")
    trips = relationship("Trip", back_populates="user", cascade="all, delete-orphan")
    sync_jobs = relationship("SyncJob", back_populates="user", cascade="all, delete-orphan")
    gmail_discovery_states = relationship("GmailDiscoveryState", back_populates="user", cascade="all, delete-orphan")
    gmail_discovery_signals = relationship("GmailDiscoverySignal", back_populates="user", cascade="all, delete-orphan")
    dreams = relationship("Dream", back_populates="user", cascade="all, delete-orphan")
    dream_items = relationship("DreamItem", back_populates="user", cascade="all, delete-orphan")


class TravelNameRecovery(Base):
    """Durable, resumable projection of retained evidence after name confirmation."""
    __tablename__ = "travel_name_recoveries"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    state = Column(String(16), nullable=False, default="queued")
    names = Column(JSON, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    max_observation_id = Column(BigInteger, nullable=False, default=0)
    cursor = Column(BigInteger, nullable=False, default=0)
    checked = Column(Integer, nullable=False, default=0)
    added = Column(Integer, nullable=False, default=0)
    existing = Column(Integer, nullable=False, default=0)
    needs_review = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False)  # "google"
    refresh_token_encrypted = Column(LargeBinary, nullable=False)
    scopes = Column(Text, nullable=False)  # Space-separated scopes
    gmail_connection_status = Column(String(24), nullable=True)  # NULL: derive legacy consent
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="accounts")


class AuthIdentity(Base):
    """Provider subjects identify accounts; contact email never silently merges users."""
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_auth_identity_subject"),
        UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
        CheckConstraint("provider IN ('google','apple')", name="ck_auth_identity_provider"),
        Index("ix_auth_identity_email_lower", text("lower(email)")),
    )
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(16), nullable=False)
    subject = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    refresh_token_encrypted = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AppleAuthChallenge(Base):
    __tablename__ = "apple_auth_challenges"
    __table_args__ = (CheckConstraint("purpose IN ('signin','link','reauth')", name="ck_apple_challenge_purpose"),)
    id = Column(String(36), primary_key=True)
    nonce_hash = Column(String(64), nullable=False)
    purpose = Column(String(16), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)


class AccountErasureCleanup(Base):
    """Retry filesystem cleanup after account deletion, without retaining identity."""
    __tablename__ = "account_erasure_cleanup"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    thumbnail_item_ids = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_swept_at = Column(DateTime(timezone=True), nullable=True)


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    state = Column(String(16), nullable=False, default="pending")  # pending, running, completed, failed
    scanned_count = Column(Integer, nullable=False, default=0)
    parsed_count = Column(Integer, nullable=False, default=0)
    segment_count = Column(Integer, nullable=False, default=0)
    page_token = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="sync_jobs")


class GmailDiscoveryState(Base):
    __tablename__ = "gmail_discovery_states"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_gmail_discovery_user_provider"),
    )

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False, default="google")
    last_incremental_scan_at = Column(DateTime(timezone=True), nullable=True)
    backfill_cursor_before = Column(DateTime(timezone=True), nullable=True)
    backfill_complete = Column(Boolean, nullable=False, default=False)
    parser_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="gmail_discovery_states")


class GmailHistoryState(Base):
    """Checkpointed history discovery, independent of the recent-mail watermark."""
    __tablename__ = "gmail_history_states"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_gmail_history_user_provider"),
        CheckConstraint("state IN ('pending','queued','running','complete','paused')", name="ck_gmail_history_state"),
    )

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(32), nullable=False, default="google")
    state = Column(String(16), nullable=False, default="pending")
    cursor_before = Column(DateTime(timezone=True), nullable=True)
    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=True)
    page_token = Column(Text, nullable=True)
    next_page_token = Column(Text, nullable=True)
    pending_message_ids = Column(JSON, nullable=False, default=list)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    scanned_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class BookingRepairManifest(Base):
    """Exact account-scoped repair plans; retain decisions and hashes, not raw mail."""
    __tablename__ = "booking_repair_manifests"
    __table_args__ = (
        UniqueConstraint("user_id", "plan_hash", name="uq_booking_repair_user_plan"),
        CheckConstraint("state IN ('previewed','applied')", name="ck_booking_repair_state"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(Integer, nullable=False, default=1)
    state = Column(String(16), nullable=False, default="previewed")
    base_fingerprint = Column(String(64), nullable=False)
    plan_hash = Column(String(64), nullable=False)
    manifest_json = Column(JSON, nullable=False)
    preview_json = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    applied_at = Column(DateTime(timezone=True), nullable=True)


class GmailDiscoverySignal(Base):
    __tablename__ = "gmail_discovery_signals"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "signal_type", "signal_value", name="uq_gmail_discovery_signal"),
    )

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False, default="google")
    signal_type = Column(String(32), nullable=False)
    signal_value = Column(String(255), nullable=False)
    hit_count = Column(Integer, nullable=False, default=1)
    first_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="gmail_discovery_signals")


class Message(Base):
    __tablename__ = "messages"
    
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider_msg_id = Column(String(255), nullable=False)  # Gmail message ID
    internal_ts = Column(DateTime(timezone=True), nullable=True)
    from_domain_hash = Column(String(64), nullable=True)
    from_email = Column(String(320), nullable=True)
    subject = Column(Text, nullable=True)
    snippet_sha256 = Column(String(64), nullable=True)
    status = Column(
        Enum(
            MessageStatus,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            name="message_status",
        ),
        nullable=False,
        default=MessageStatus.PENDING,
    )
    parse_version = Column(Integer, nullable=False, default=0)
    parse_error = Column(Text, nullable=True)
    parse_evidence = Column(JSON, nullable=True)
    ignored = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="messages")


class Trip(Base):
    __tablename__ = "trips"
    
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=True)
    start_ts = Column(DateTime(timezone=True), nullable=True)
    end_ts = Column(DateTime(timezone=True), nullable=True)
    visibility = Column(String(16), nullable=False, default="private")
    
    # Relationships
    user = relationship("User", back_populates="trips")
    segments = relationship("Segment", back_populates="trip", cascade="all, delete-orphan")


class Segment(Base):
    __tablename__ = "segments"
    
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    trip_id = Column(BigInteger, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    mode = Column(String(16), nullable=False)  # "flight"
    dep_airport = Column(String(8), nullable=False)  # IATA code
    arr_airport = Column(String(8), nullable=False)  # IATA code
    dep_time = Column(DateTime(timezone=True), nullable=False)
    arr_time = Column(DateTime(timezone=True), nullable=False)
    airline = Column(String(8), nullable=True)  # IATA code
    flight_number = Column(String(16), nullable=True)
    pnr = Column(String(16), nullable=True)  # Passenger Name Record
    distance_km = Column(Float, nullable=True)
    geom = Column(String().with_variant(Geography(geometry_type="LINESTRING", srid=4326), 'postgresql'), nullable=True)
    meta_json = Column(JSON, nullable=True)  # Additional metadata
    
    # Relationships
    trip = relationship("Trip", back_populates="segments")


class BookingObservation(Base):
    """Immutable extracted facts, including facts held outside the active itinerary."""
    __tablename__ = "booking_observations"
    __table_args__ = (UniqueConstraint("user_id", "evidence_key", name="uq_booking_observation_evidence"),)

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_key = Column(String(64), nullable=False)
    source_message_id = Column(String(255), nullable=True)
    source_event_at = Column(DateTime(timezone=True), nullable=True)
    pnr = Column(String(16), nullable=True, index=True)
    travel_date = Column(String(10), nullable=True)
    dep_airport = Column(String(8), nullable=True)
    arr_airport = Column(String(8), nullable=True)
    flight_number = Column(String(16), nullable=True)
    ownership = Column(String(16), nullable=False)
    facts = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class BookingCancellation(Base):
    """Durable cancellation evidence scoped to a booking's dated flight legs."""
    __tablename__ = "booking_cancellations"
    __table_args__ = (UniqueConstraint("user_id", "evidence_key", name="uq_booking_cancellation_evidence"),)

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_key = Column(String(64), nullable=False)
    source_message_id = Column(String(255), nullable=True)
    source_event_at = Column(DateTime(timezone=True), nullable=True)
    pnr = Column(String(16), nullable=False, index=True)
    scopes = Column(JSON, nullable=False)
    facts = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class ItineraryHistory(Base):
    """Complete pre-mutation snapshots; source IDs intentionally have no cascading FK."""
    __tablename__ = "itinerary_history"
    __table_args__ = (UniqueConstraint("user_id", "evidence_key", name="uq_itinerary_history_evidence"),)

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_key = Column(String(64), nullable=False)
    entity_type = Column(String(16), nullable=False)
    entity_id = Column(BigInteger, nullable=False)
    reason = Column(String(80), nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class TravelInboxItem(Base):
    """An owner's retained traveler/booking identity, backed by immutable evidence."""
    __tablename__ = "travel_inbox_items"
    __table_args__ = (
        UniqueConstraint("user_id", "record_key", name="uq_travel_inbox_item_record"),
        CheckConstraint("reason IN ('other_traveler', 'companion', 'unassigned')", name="ck_travel_inbox_item_reason"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    record_key = Column(String(64), nullable=False)
    flight_key = Column(String(64), nullable=False, index=True)
    passenger_name = Column(String(255), nullable=True)
    passenger_key = Column(String(255), nullable=True)
    reason = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class TravelInboxEvidence(Base):
    """Retained flight facts stay in the ledger; linking never copies or deletes them."""
    __tablename__ = "travel_inbox_evidence"
    __table_args__ = (
        UniqueConstraint("item_id", "observation_id", name="uq_travel_inbox_evidence_observation"),
    )

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    item_id = Column(String(36), ForeignKey("travel_inbox_items.id", ondelete="CASCADE"), nullable=False)
    observation_id = Column(BigInteger, ForeignKey("booking_observations.id", ondelete="RESTRICT"), nullable=False, index=True)


class TravelInboxAssignment(Base):
    """Owner annotation; extracted passenger evidence remains immutable."""
    __tablename__ = "travel_inbox_assignments"

    item_id = Column(String(36), ForeignKey("travel_inbox_items.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    passenger_name = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class FlightShare(Base):
    """Explicit, email-bound invitation with a passenger-safe immutable snapshot."""
    __tablename__ = "flight_shares"
    __table_args__ = (
        UniqueConstraint("sender_id", "client_request_id", name="uq_flight_share_request"),
        CheckConstraint("status IN ('pending', 'accepted', 'declined', 'revoked')", name="ck_flight_share_status"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sender_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_email = Column(String(255), nullable=False, index=True)
    recipient_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    passenger_name = Column(String(255), nullable=False)
    client_request_id = Column(String(36), nullable=False)
    request_hash = Column(String(64), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    token_encrypted = Column(LargeBinary, nullable=False)
    item_ids = Column(JSON, nullable=False)
    flights = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    added_flights = Column(Integer, nullable=False, default=0)
    existing_flights = Column(Integer, nullable=False, default=0)
    accepted_segment_ids = Column(JSON, nullable=False, default=list)


class Dream(Base):
    __tablename__ = "dreams"
    __table_args__ = (
        UniqueConstraint("user_id", "title", "country", "city", "region", name="uq_dream_user_location"),
    )

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    country = Column(String(128), nullable=True)
    city = Column(String(128), nullable=True)
    region = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="dreams")
    items = relationship("DreamItem", back_populates="dream", cascade="all, delete-orphan")


class DreamSourcePost(Base):
    """One saved source; its independently editable places remain DreamItems."""
    __tablename__ = "dream_source_posts"
    __table_args__ = (UniqueConstraint("user_id", "source_url", name="uq_dream_source_user_url"),)
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_url = Column(Text, nullable=False)
    source_platform = Column(String(32), nullable=False, default="instagram")
    caption = Column(Text, nullable=True)
    raw_metadata_json = Column(JSON, nullable=True)
    removed_place_keys = Column(JSON, nullable=False, default=list, server_default="[]")
    generation = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    items = relationship("DreamItem", back_populates="source_post", passive_deletes=True)


class DreamItem(Base):
    __tablename__ = "dream_items"
    __table_args__ = (
        UniqueConstraint("user_id", "source_url", "source_place_key", name="uq_dream_item_user_source_place"),
        Index("ix_dream_planner_geography", "user_id", "planner_country_key", "planner_city_key", "id"),
    )

    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dream_id = Column(BigInteger, ForeignKey("dreams.id", ondelete="CASCADE"), nullable=False)
    source_platform = Column(String(32), nullable=False, default="instagram")
    source_url = Column(Text, nullable=False)
    source_post_id = Column(BigInteger, ForeignKey("dream_source_posts.id", ondelete="SET NULL"), nullable=True, index=True)
    source_place_key = Column(String(64), nullable=False, default="primary", server_default="primary")
    source_place_index = Column(Integer, nullable=False, default=0, server_default="0")
    caption = Column(Text, nullable=True)
    raw_metadata_json = Column(JSON, nullable=True)
    category = Column(String(32), nullable=False, default="unknown")
    place_name = Column(String(255), nullable=True)
    city = Column(String(128), nullable=True)
    country = Column(String(128), nullable=True)
    region_or_neighborhood = Column(String(128), nullable=True)
    planner_country_key = Column(String(128), nullable=True)
    planner_city_key = Column(String(128), nullable=True)
    planner_place_key = Column(String(64), nullable=True)
    summary = Column(Text, nullable=False, default="Saved from Instagram")
    personal_note = Column(Text, nullable=True)
    tags_json = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=True)
    needs_google_places_lookup = Column(Boolean, nullable=False, default=False)
    google_place_id = Column(String(255), nullable=True)
    google_maps_url = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="needs_review")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="dream_items")
    dream = relationship("Dream", back_populates="items")
    source_post = relationship("DreamSourcePost", back_populates="items")
    location = relationship("DreamLocation", uselist=False, back_populates="item", cascade="all, delete-orphan")
    enrichment = relationship("DreamEnrichmentJob", uselist=False, back_populates="item", cascade="all, delete-orphan")


class DreamEnrichmentJob(Base):
    """Durable caption work. Provider calls run after the claiming transaction closes."""
    __tablename__ = "dream_enrichment_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="ck_dream_enrichment_status"),
    )
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    item_id = Column(BigInteger, ForeignKey("dream_items.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    source_generation = Column(Integer, nullable=True)
    generation = Column(Integer, nullable=False, default=1, server_default="1")
    status = Column(String(32), nullable=False, default="queued", server_default="queued", index=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    item = relationship("DreamItem", back_populates="enrichment")


class DreamLocation(Base):
    """Durable, owner-scoped location work; original saved content stays on DreamItem."""
    __tablename__ = "dream_locations"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'resolved', 'needs_review', 'not_found', 'failed', 'blocked', 'manual')", name="ck_dream_location_status"),
        Index("ix_dream_locations_matcher_recovery",
              text("(CASE WHEN matcher_generation = generation THEN matcher_version ELSE 0 END)"), "id",
              postgresql_where=text("status IN ('not_found', 'failed')"),
              sqlite_where=text("status IN ('not_found', 'failed')")),
    )
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    item_id = Column(BigInteger, ForeignKey("dream_items.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    pin_fingerprint = Column(String(64), nullable=False)
    generation = Column(Integer, nullable=False, default=1, server_default="1")
    matcher_version = Column(Integer, nullable=False, default=0, server_default="0")
    matcher_retry_version = Column(Integer, nullable=False, default=0, server_default="0")
    matcher_generation = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(32), nullable=False, default="queued", server_default="queued", index=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    provider = Column(String(32), nullable=True)
    coordinate_precision = Column(String(16), nullable=True)
    address = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    google_maps_url = Column(Text, nullable=True)
    candidates = Column(JSON, nullable=False, default=list, server_default="[]")
    history = Column(JSON, nullable=False, default=list, server_default="[]")
    message = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    item = relationship("DreamItem", back_populates="location")
    google_identity = relationship("DreamGoogleIdentity", uselist=False, back_populates="location", cascade="all, delete-orphan")


class DreamGoogleIdentity(Base):
    """Persistable Google IDs and user choices only; provider content is never stored here."""
    __tablename__ = "dream_google_identities"
    location_id = Column(BigInteger, ForeignKey("dream_locations.id", ondelete="CASCADE"), primary_key=True)
    selected_place_id = Column(Text, nullable=True)
    confirmed_place_id = Column(Text, nullable=True)
    place_fingerprint = Column(String(64), nullable=True)
    candidate_place_ids = Column(JSON, nullable=False, default=list, server_default="[]")
    coordinates_expires_at = Column(DateTime(timezone=True), nullable=True)
    refresh_after = Column(DateTime(timezone=True), nullable=True, index=True)
    location = relationship("DreamLocation", back_populates="google_identity")


# Register the additive planner tables for Alembic and metadata.create_all.
from . import planner_models as _planner_models  # noqa: E402,F401
