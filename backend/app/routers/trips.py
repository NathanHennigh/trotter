"""
backend/app/routers/trips.py
Endpoints to read back processed trips and flight segments.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Segment, Trip, User
from .auth import get_current_user

router = APIRouter(prefix="/trips", tags=["trips"])


# ── Response schemas ─────────────────────────────────────────────────────────

class SegmentOut(BaseModel):
    id: int
    trip_id: int
    mode: str
    dep_airport: str
    arr_airport: str
    dep_time: datetime
    arr_time: datetime
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    pnr: Optional[str] = None
    distance_km: Optional[float] = None
    meta_json: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class TripOut(BaseModel):
    id: int
    title: Optional[str] = None
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    segments: List[SegmentOut] = []

    class Config:
        from_attributes = True


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=List[TripOut])
def list_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[TripOut]:
    """Return all trips for the current user, newest first, each with nested segments."""
    trips = (
        db.query(Trip)
        .options(joinedload(Trip.segments))
        .filter(Trip.user_id == current_user.id)
        .order_by(Trip.start_ts.desc().nullslast())
        .all()
    )
    for trip in trips:
        trip.segments.sort(key=lambda segment: (segment.dep_time, segment.arr_time, segment.id))
    return trips


@router.get("/segments", response_model=List[SegmentOut])
def list_segments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SegmentOut]:
    """
    Return a flat list of all flight segments for the current user,
    ordered by departure time. This is the primary feed for map rendering.
    """
    segments = (
        db.query(Segment)
        .join(Trip, Segment.trip_id == Trip.id)
        .filter(Trip.user_id == current_user.id)
        .order_by(Segment.dep_time.asc())
        .all()
    )
    return segments


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(
    trip_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TripOut:
    """Return a single trip with its segments."""
    from fastapi import HTTPException, status
    trip = (
        db.query(Trip)
        .options(joinedload(Trip.segments))
        .filter(Trip.id == trip_id, Trip.user_id == current_user.id)
        .first()
    )
    if not trip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    trip.segments.sort(key=lambda segment: (segment.dep_time, segment.arr_time, segment.id))
    return trip
