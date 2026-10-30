"""Private saved-place suggestions and explicit per-traveller future sharing."""
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, func, or_

from ..models import DreamGoogleIdentity, DreamItem, DreamLocation, DreamSourcePost
from ..planner_models import PlannerContribution, PlannerIdea, PlannerMember
from . import planner


def scope_value(country, city=None):
    if not country:
        return None
    country_label = country.title()
    city_label = city.title() if city else None
    return {"id": planner.digest(["geography-v1", country, city]), "country": country_label,
            "city": city_label, "label": f"{city_label}, {country_label}" if city_label else country_label}


def scope(trip):
    return scope_value(trip.match_country_key, trip.match_city_key)


def destination_rows(db, user_id):
    # A covering owner/geography index supports grouping without reading private payloads.
    return (db.query(DreamItem.planner_country_key, DreamItem.planner_city_key, func.count(DreamItem.id))
        .filter(DreamItem.user_id == user_id, DreamItem.planner_country_key.isnot(None), DreamItem.place_name.isnot(None))
        .group_by(DreamItem.planner_country_key, DreamItem.planner_city_key).all())


def destinations(db, user_id):
    countries, cities = {}, []
    for country, city, count in destination_rows(db, user_id):
        countries[country] = countries.get(country, 0) + count
        if city:
            cities.append({**scope_value(country, city), "count": count})
    choices = [{**scope_value(country), "count": count} for country, count in countries.items()] + cities
    return sorted(choices, key=lambda item: (item["country"], item["city"] or ""))


def resolve_scope(db, user_id, scope_id):
    if scope_id is None:
        return None, None
    for country, city, _count in destination_rows(db, user_id):
        if scope_value(country)["id"] == scope_id:
            return country, None
        if city and scope_value(country, city)["id"] == scope_id:
            return country, city
    raise HTTPException(422, "Choose a country or city from your categorized Dreams.")


def ensure_scope(trip, scope_id):
    current = scope(trip)
    if not current or current["id"] != scope_id:
        raise HTTPException(409, "This trip's matching destination changed. Review it before sharing.")


def pause_reason(trip, member):
    if member.removed_at:
        return "access_removed"
    if not trip.match_country_key:
        return "no_destination"
    if planner.now().astimezone(ZoneInfo(trip.timezone)).date() > date.fromisoformat(trip.end_date):
        return "trip_ended"
    return None


def sharing(trip, member):
    reason = pause_reason(trip, member)
    return {"enabled": bool(member.dream_auto_share), "active": bool(member.dream_auto_share and not reason),
            "paused_reason": reason, "consented_at": member.dream_consented_at}


def set_scope(db, trip, user_id, scope_id):
    current = scope(trip)
    if scope_id == (current["id"] if current else None):
        return
    country, city = resolve_scope(db, user_id, scope_id)
    trip.match_country_key, trip.match_city_key = country, city
    # A new scope is new permission. Never broaden someone else's prior consent.
    for member in db.query(PlannerMember).filter_by(trip_id=trip.id).all():
        disable(member)


def disable(member):
    member.dream_auto_share = False
    member.dream_consented_at = None
    member.dream_sync_item_id = None
    member.dream_last_synced_at = None


def set_sharing(trip, member, scope_id, enabled):
    ensure_scope(trip, scope_id)
    if not enabled:
        disable(member)
    elif not member.dream_auto_share:
        if pause_reason(trip, member):
            raise HTTPException(422, "This trip has ended. Update its dates before sharing future saves.")
        member.dream_auto_share = True
        member.dream_consented_at = planner.now()
        member.dream_sync_item_id = 0
        member.dream_last_synced_at = None


def matches_query(db, trip, user_id):
    query = db.query(DreamItem).filter(DreamItem.user_id == user_id,
        DreamItem.planner_country_key == trip.match_country_key, DreamItem.place_name.isnot(None), DreamItem.place_name != "")
    if not trip.match_country_key:
        query = query.filter(False)
    if trip.match_city_key:
        query = query.filter(DreamItem.planner_city_key == trip.match_city_key)
    return query


def new_suggestions_query(db, trip, user_id):
    contributed = db.query(PlannerContribution.id).filter(PlannerContribution.trip_id == trip.id,
        PlannerContribution.user_id == user_id, PlannerContribution.dream_item_id == DreamItem.id).exists()
    provider = db.query(func.coalesce(DreamGoogleIdentity.confirmed_place_id, DreamGoogleIdentity.selected_place_id)).join(
        DreamLocation, DreamLocation.id == DreamGoogleIdentity.location_id).filter(
        DreamLocation.item_id == DreamItem.id).correlate(DreamItem).scalar_subquery()
    provider = func.coalesce(provider, DreamItem.google_place_id)
    identity_matches = or_(and_(provider.isnot(None), PlannerIdea.google_place_id == provider),
        and_(PlannerIdea.dream_match_key == DreamItem.planner_place_key,
             or_(provider.is_(None), PlannerIdea.google_place_id.is_(None))))
    removed = db.query(PlannerIdea.id).filter(PlannerIdea.trip_id == trip.id, identity_matches,
        PlannerIdea.deleted_at.isnot(None), PlannerIdea.merged_into_id.is_(None)).exists()
    return matches_query(db, trip, user_id).filter(~contributed, ~removed)


def suggestions(db, trip, member, *, limit=20, cursor=None):
    query = new_suggestions_query(db, trip, member.user_id)
    total = query.count()
    if cursor is not None:
        query = query.filter(DreamItem.id > cursor)
    rows = query.order_by(DreamItem.id).limit(limit + 1).all()
    return {"scope": scope(trip), "sharing": sharing(trip, member), "total": total,
        "suggestions": [{"dream_item_id": str(item.id), "title": item.place_name, "category": item.category,
            "country": item.country, "city": item.city, "image_url": f"/dream-items/{item.id}/thumbnail"}
            for item in rows[:limit]], "next_cursor": str(rows[limit-1].id) if len(rows) > limit else None}


def import_suggestions(db, trip, user_id, scope_id, *, all_items=False, item_ids=None):
    ensure_scope(trip, scope_id)
    query = new_suggestions_query(db, trip, user_id)
    if not all_items:
        try:
            ids = set(int(i) for i in item_ids or [])
        except (ValueError, TypeError):
            raise HTTPException(422, "Choose saved places that have finished uploading.")
        # Already-contributed selections are harmless retries, but every ID must still be yours and in scope.
        if matches_query(db, trip, user_id).filter(DreamItem.id.in_(ids)).count() != len(ids):
            raise HTTPException(404, "A selected save is no longer available for this destination.")
        query = query.filter(DreamItem.id.in_(ids))
    rows = query.order_by(DreamItem.id).limit(planner.MAX_IDEAS + 1).all()
    if len(rows) > planner.MAX_IDEAS:
        raise HTTPException(422, "Choose up to 200 matching saves at a time.")
    for item in rows:
        # Bulk suggestions do not resurrect a group removal. Deliberate individual manual import still can.
        if not removed_match(db, trip, item):
            planner.import_dream_item(db, trip, user_id, item, explicit=False)


def removed_match(db, trip, item):
    key = item.planner_place_key
    if not key:
        return False
    _, place_id = planner.shared_identity(item)
    identity = PlannerIdea.dream_match_key == key
    if place_id:
        identity = or_(PlannerIdea.google_place_id == place_id,
            and_(PlannerIdea.google_place_id.is_(None), PlannerIdea.dream_match_key == key))
    return db.query(PlannerIdea.id).filter(PlannerIdea.trip_id == trip.id, identity,
        PlannerIdea.deleted_at.isnot(None), PlannerIdea.merged_into_id.is_(None)).first() is not None


def reconcile_matching(db, trip, *, user_id=None, limit=100):
    """Bounded pending anti-join, independent of update timestamps or commit order.

    Original source capture time distinguishes future saves from later-extracted
    siblings of old private reels. Every unshared match remains pending durably.
    """
    members = db.query(PlannerMember).filter_by(trip_id=trip.id, removed_at=None, dream_auto_share=True)
    if user_id is not None:
        members = members.filter_by(user_id=user_id)
    for member in members.all():
        member.dream_last_synced_at = planner.now()
        if pause_reason(trip, member) or not member.dream_consented_at:
            continue
        def future(query):
            return query.outerjoin(DreamSourcePost, DreamSourcePost.id == DreamItem.source_post_id).filter(
                func.coalesce(DreamSourcePost.created_at, DreamItem.created_at) >= member.dream_consented_at)
        query = future(new_suggestions_query(db, trip, member.user_id))
        rows = query.order_by(DreamItem.id).limit(limit).all()
        for item in rows:
            try:
                planner.import_dream_item(db, trip, member.user_id, item, explicit=False)
            except HTTPException as exc:
                if exc.status_code == 422:
                    # Capacity can be freed later; the anti-join keeps this pending.
                    break
                raise
        # Refresh late location resolution without a timestamp cursor: a delayed
        # commit is picked up on the next pass. Removed ideas remain tombstones.
        contributed = db.query(PlannerContribution.id).filter(PlannerContribution.trip_id == trip.id,
            PlannerContribution.user_id == member.user_id, PlannerContribution.dream_item_id == DreamItem.id).exists()
        refresh = future(matches_query(db, trip, member.user_id).filter(contributed))
        refresh = refresh.filter(DreamItem.id > (member.dream_sync_item_id or 0)).order_by(DreamItem.id).limit(limit).all()
        if not refresh:
            member.dream_sync_item_id = 0
        for item in refresh:
            planner.import_dream_item(db, trip, member.user_id, item, explicit=False)
            member.dream_sync_item_id = item.id
