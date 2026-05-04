# backend/app/models.py
"""
SQLAlchemy models for the application.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Text, LargeBinary, Boolean, ForeignKey, Float, JSON, Enum, UniqueConstraint
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
    
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=True)
    home_tz = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")
    trips = relationship("Trip", back_populates="user", cascade="all, delete-orphan")
    sync_jobs = relationship("SyncJob", back_populates="user", cascade="all, delete-orphan")
    gmail_discovery_states = relationship("GmailDiscoveryState", back_populates="user", cascade="all, delete-orphan")
    gmail_discovery_signals = relationship("GmailDiscoverySignal", back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False)  # "google"
    refresh_token_encrypted = Column(LargeBinary, nullable=False)
    scopes = Column(Text, nullable=False)  # Space-separated scopes
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="accounts")


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
    status = Column(Enum(MessageStatus), nullable=False, default=MessageStatus.PENDING)
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
