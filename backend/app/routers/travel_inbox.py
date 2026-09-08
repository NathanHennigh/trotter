"""Owner-only, read-only access to retained travel and its evidence pointers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import TravelInboxItem, User
from .auth import get_current_user

router = APIRouter(prefix="/travel-inbox", tags=["travel-inbox"])


def _serialize_item(db, user_id, item, *, include_evidence=False):
    from ..services.travel_inbox import serialize_item
    return serialize_item(db, user_id, item, include_evidence=include_evidence)


@router.get("")
def list_travel_inbox(
    limit: int = Query(50, ge=1, le=100),
    before_id: str | None = Query(None, min_length=1, max_length=36),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(TravelInboxItem).filter(TravelInboxItem.user_id == current_user.id)
    if before_id is not None:
        cursor = query.filter(TravelInboxItem.id == before_id).first()
        if cursor is None:
            raise HTTPException(404, "Travel inbox cursor not found")
        query = query.filter(or_(
            TravelInboxItem.created_at < cursor.created_at,
            and_(TravelInboxItem.created_at == cursor.created_at, TravelInboxItem.id < cursor.id),
        ))
    rows = query.order_by(TravelInboxItem.created_at.desc(), TravelInboxItem.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    return {
        "items": [_serialize_item(db, current_user.id, item) for item in page],
        "next_cursor": page[-1].id if len(rows) > limit else None,
    }


@router.get("/{item_id}")
def get_travel_inbox_item(
    item_id: str = Path(min_length=1, max_length=36),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    item = db.query(TravelInboxItem).filter(
        TravelInboxItem.user_id == current_user.id, TravelInboxItem.id == item_id,
    ).first()
    if item is None:
        raise HTTPException(404, "Travel inbox item not found")
    return _serialize_item(db, current_user.id, item, include_evidence=True)
