"""Segment/trip builder: groups ParsedFlights into DB Trip and Segment records."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Segment, Trip
from .enrichment import enrich_segment

if TYPE_CHECKING:
    from .parser import ParsedFlight

# ──────────────────────── airport coordinate lookup ─────────────────────────
# Load from airportsdata (7,800+ IATA airports). Falls back to a small embedded
# dict if the package is somehow unavailable.

def _load_airport_coords() -> dict[str, tuple[float, float]]:
    try:
        import airportsdata
        db = airportsdata.load("IATA")
        return {code: (float(ap["lat"]), float(ap["lon"])) for code, ap in db.items()}
    except Exception:
        pass
    # Minimal fallback — should not be needed if airportsdata is installed
    return {
        "ATL": (33.6407, -84.4277), "LAX": (33.9416, -118.4085), "ORD": (41.9742, -87.9073),
        "DFW": (32.8998, -97.0403), "DEN": (39.8561, -104.6737), "JFK": (40.6413, -73.7781),
        "SFO": (37.6213, -122.3790), "SEA": (47.4502, -122.3088), "LHR": (51.4775, -0.4614),
        "CDG": (49.0097, 2.5479), "DXB": (25.2532, 55.3657), "SIN": (1.3644, 103.9915),
        "NRT": (35.7720, 140.3929), "SYD": (-33.9399, 151.1753), "GRU": (-23.4356, -46.4731),
        "EWR": (40.6895, -74.1745), "IAD": (38.9445, -77.4558), "MIA": (25.7959, -80.2870),
        "IAH": (29.9902, -95.3368), "BOS": (42.3656, -71.0096), "ADD": (8.9779, 38.7993),
        "HGA": (9.5182, 44.0888), "MGA": (12.1416, -86.1680), "KLO": (11.6811, 122.3758),
        "MNL": (14.5086, 121.0195), "FLL": (26.0742, -80.1506), "BWI": (39.1754, -76.6682),
    }

_AIRPORT_COORDS: dict[str, tuple[float, float]] = _load_airport_coords()


def _load_airport_details() -> dict[str, dict[str, str]]:
    try:
        import airportsdata
        db = airportsdata.load("IATA")
        return {
            code: {
                "city": str(ap.get("city") or "").strip(),
                "country": str(ap.get("country") or "").strip(),
                "name": str(ap.get("name") or "").strip(),
            }
            for code, ap in db.items()
        }
    except Exception:
        return {
            "ATL": {"city": "Atlanta", "country": "US", "name": "Hartsfield/Jackson Atlanta International Airport"},
            "DFW": {"city": "Dallas-Fort Worth", "country": "US", "name": "Dallas Fort Worth International Airport"},
            "FLL": {"city": "Fort Lauderdale", "country": "US", "name": "Fort Lauderdale-Hollywood International Airport"},
            "IAH": {"city": "Houston", "country": "US", "name": "George Bush Intercontinental Airport"},
            "MEX": {"city": "Mexico City", "country": "MX", "name": "Benito Juarez International Airport"},
            "MGA": {"city": "Managua", "country": "NI", "name": "Augusto C. Sandino International Airport"},
            "MCO": {"city": "Orlando", "country": "US", "name": "Orlando International Airport"},
            "SIN": {"city": "Singapore", "country": "SG", "name": "Singapore Changi Airport"},
            "TPE": {"city": "Taipei", "country": "TW", "name": "Taiwan Taoyuan International Airport"},
        }


_AIRPORT_DETAILS: dict[str, dict[str, str]] = _load_airport_details()

_COUNTRY_NAMES = {
    "AE": "United Arab Emirates",
    "AU": "Australia",
    "BS": "Bahamas",
    "CA": "Canada",
    "CH": "Switzerland",
    "CN": "China",
    "DE": "Germany",
    "DO": "Dominican Republic",
    "ES": "Spain",
    "ET": "Ethiopia",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "IS": "Iceland",
    "IT": "Italy",
    "JP": "Japan",
    "KE": "Kenya",
    "MA": "Morocco",
    "MX": "Mexico",
    "NI": "Nicaragua",
    "NL": "Netherlands",
    "PH": "Philippines",
    "PT": "Portugal",
    "SG": "Singapore",
    "SO": "Somalia",
    "TH": "Thailand",
    "TR": "Turkey",
    "TW": "Taiwan",
    "US": "United States",
}
_EXTRA_DESTINATION_STOPOVER = timedelta(hours=36)
_NEARBY_INTERNATIONAL_CITY_KM = 2500.0


@dataclass
class BuildSegmentsResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    deduped: int = 0
    trips: int = 0


# ──────────────────────────── geometry helpers ───────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    ph1, ph2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(ph1) * math.cos(ph2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _densified_linestring(
    lat1: float, lon1: float, lat2: float, lon2: float, n: int = 20
) -> str:
    """Return a WKT LINESTRING densified with n intermediate points along the great circle.

    Uses spherical linear interpolation (slerp) for accuracy on longer routes.
    """
    def _slerp(t: float) -> tuple[float, float]:
        # Convert to radians
        la1, lo1 = math.radians(lat1), math.radians(lon1)
        la2, lo2 = math.radians(lat2), math.radians(lon2)
        # Cartesian unit vectors
        x1 = math.cos(la1) * math.cos(lo1)
        y1 = math.cos(la1) * math.sin(lo1)
        z1 = math.sin(la1)
        x2 = math.cos(la2) * math.cos(lo2)
        y2 = math.cos(la2) * math.sin(lo2)
        z2 = math.sin(la2)
        dot = max(-1.0, min(1.0, x1 * x2 + y1 * y2 + z1 * z2))
        omega = math.acos(dot)
        if omega < 1e-9:
            return lat1, lon1
        xp = (math.sin((1 - t) * omega) * x1 + math.sin(t * omega) * x2) / math.sin(omega)
        yp = (math.sin((1 - t) * omega) * y1 + math.sin(t * omega) * y2) / math.sin(omega)
        zp = (math.sin((1 - t) * omega) * z1 + math.sin(t * omega) * z2) / math.sin(omega)
        lat_p = math.degrees(math.atan2(zp, math.sqrt(xp * xp + yp * yp)))
        lon_p = math.degrees(math.atan2(yp, xp))
        return lat_p, lon_p

    pts = []
    for i in range(n + 1):
        la, lo = _slerp(i / n)
        pts.append(f"{lo:.6f} {la:.6f}")
    return f"LINESTRING({', '.join(pts)})"


# ──────────────────────────── public interface ───────────────────────────────

def build_segments_and_trips(
    db: Session, user_id: int, flights: "list[ParsedFlight]"
) -> int:
    """Upsert Trips and Segments for a list of parsed flights. Returns new segment count."""
    return build_segments_and_trips_detailed(db, user_id, flights).inserted


def build_segments_and_trips_detailed(
    db: Session, user_id: int, flights: "list[ParsedFlight]"
) -> BuildSegmentsResult:
    """Upsert Trips and Segments for parsed flights and return insert/update counts."""
    result = BuildSegmentsResult()
    if not flights:
        return result

    sorted_flights = sorted(flights, key=lambda f: _db_datetime(f.dep_time))
    trip_groups = _group_into_trips(sorted_flights)

    for group in trip_groups:
        trip = _find_or_create_trip(db, user_id, group)
        for flight in group:
            action = _upsert_segment(db, trip.id, user_id, flight)
            if action == "inserted":
                result.inserted += 1
            elif action == "updated":
                result.updated += 1
            else:
                result.skipped += 1

    result.trips = rebuild_user_trips(db, user_id)
    resolve_booking_relationships(db, user_id)
    return result


def cancel_segments_for_pnr(db: Session, user_id: int, pnr: str, *, received_at=None) -> int:
    """Remove stored flight segments for a canceled booking code.

    When the cancellation has a source timestamp, preserve segments backed by a
    newer same-PNR confirmation so an old cancellation cannot erase a rebooking.
    """
    pnr = _normalize_pnr(pnr)
    if not pnr:
        return 0
    cancellation_time = _db_datetime(received_at)
    segments = (
        db.query(Segment)
        .join(Trip)
        .filter(Trip.user_id == user_id, Segment.pnr == pnr)
        .all()
    )
    removable = []
    affected = 0
    for segment in segments:
        source_time = _segment_source_received_at(segment)
        if cancellation_time and source_time and source_time > cancellation_time:
            continue
        alias = _first_active_pnr_alias(segment, pnr)
        if alias:
            segment.pnr = alias
            _add_pnr_alias(segment, pnr, reason="canceled_primary_pnr")
            _add_booking_relationship(
                segment,
                {
                    "type": "surviving_replacement_candidate",
                    "replaces_pnr": pnr,
                    "canceled_segment_id": segment.id,
                    "cancellation_received_at": cancellation_time.isoformat() if cancellation_time else None,
                },
            )
            affected += 1
            continue
        removable.append(segment)
    _mark_cancellation_replacements(db, user_id, pnr, removable, cancellation_time)
    count = affected + len(removable)
    for segment in removable:
        db.delete(segment)
    if count:
        db.flush()
        rebuild_user_trips(db, user_id)
        resolve_booking_relationships(db, user_id)
    return count


def resolve_booking_relationships(db: Session, user_id: int) -> None:
    """Annotate booking relationships without changing itinerary structure.

    The parser extracts flight facts; this lightweight resolver preserves
    evidence relationships that matter later: aliases, likely replacement
    bookings, and reused/credit-linked PNRs that appear on unrelated trips.
    """
    segments = (
        db.query(Segment)
        .join(Trip)
        .filter(Trip.user_id == user_id)
        .order_by(Segment.dep_time, Segment.arr_time, Segment.id)
        .all()
    )
    if not segments:
        return
    _mark_duplicate_route_aliases(segments)
    _mark_near_duplicate_booking_replacements(segments)
    _mark_reused_pnr_candidates(segments)
    db.flush()


def rebuild_user_trips(db: Session, user_id: int) -> int:
    """Re-cluster all saved flight segments into durable user trips.

    Imports often discover one leg at a time, or later parse a better copy of
    an itinerary. Rebuilding from the user's complete segment graph prevents
    stale one-email groupings from surviving after better data arrives.
    """
    segments = (
        db.query(Segment)
        .join(Trip)
        .filter(Trip.user_id == user_id)
        .order_by(Segment.dep_time, Segment.arr_time, Segment.id)
        .all()
    )
    if not segments:
        return 0

    segments = _prune_duplicate_segments(db, segments)
    old_trip_ids = {segment.trip_id for segment in segments}
    old_trips = {
        trip.id: trip
        for trip in db.query(Trip).filter(Trip.user_id == user_id, Trip.id.in_(old_trip_ids)).all()
    }
    home_airport = _infer_home_airport(segments)
    clusters = _cluster_saved_segments(segments, home_airport=home_airport)
    used_trip_ids: set[int] = set()

    for cluster in clusters:
        reusable_id = _select_reusable_trip_id(cluster, used_trip_ids)
        trip = old_trips.get(reusable_id) if reusable_id else None
        if trip is None:
            trip = Trip(user_id=user_id)
            db.add(trip)
            db.flush()
        used_trip_ids.add(trip.id)
        ordered = sorted(cluster, key=_segment_sort_key)
        trip.start_ts = min(_segment_dep_time(segment) for segment in ordered)
        trip.end_ts = max(_segment_arr_time(segment) for segment in ordered)
        trip.title = _trip_title_for_segments(ordered, home_airport=home_airport)
        for segment in ordered:
            segment.trip_id = trip.id

    db.flush()
    for trip in db.query(Trip).filter(Trip.user_id == user_id).all():
        segment_count = db.query(func.count(Segment.id)).filter(Segment.trip_id == trip.id).scalar()
        if trip.id not in used_trip_ids and segment_count == 0:
            db.delete(trip)
    db.flush()
    return len(clusters)


# ──────────────────────────── internal helpers ───────────────────────────────

def _segment_dep_time(segment: Segment) -> datetime:
    return _db_datetime(segment.dep_time)


def _segment_arr_time(segment: Segment) -> datetime:
    return _db_datetime(segment.arr_time)


def _segment_sort_key(segment: Segment) -> tuple[datetime, datetime, int]:
    return (_segment_dep_time(segment), _segment_arr_time(segment), segment.id or 0)


def _cluster_saved_segments(segments: list[Segment], home_airport: Optional[str]) -> list[list[Segment]]:
    if not segments:
        return []

    ordered = sorted(segments, key=_segment_sort_key)
    home_airports = _infer_home_airports(segments)
    clusters: list[list[Segment]] = [[ordered[0]]]
    for segment in ordered[1:]:
        current = clusters[-1]
        previous = current[-1]
        gap = _segment_dep_time(segment) - _segment_arr_time(previous)
        if _belongs_to_current_trip(current, segment, gap, home_airport, home_airports):
            current.append(segment)
        else:
            clusters.append([segment])
    return clusters


def _prune_duplicate_segments(db: Session, segments: list[Segment]) -> list[Segment]:
    keep_ids: set[int] = set()
    delete_ids: set[int] = set()

    def mark_duplicates(groups: dict[tuple, list[Segment]]) -> None:
        for duplicates in groups.values():
            active = [segment for segment in duplicates if segment.id not in delete_ids]
            if len(active) <= 1:
                continue
            keep = _best_duplicate_segment(active, segments)
            keep_ids.add(keep.id)
            for duplicate in active:
                if duplicate.id == keep.id:
                    continue
                _merge_duplicate_segment(keep, duplicate)
                delete_ids.add(duplicate.id)

    exact_groups: dict[tuple[str, str, object, Optional[str]], list[Segment]] = {}
    for segment in segments:
        exact_groups.setdefault(
            (segment.dep_airport, segment.arr_airport, _segment_dep_time(segment), _normalize_flight_number(segment.flight_number)),
            [],
        ).append(segment)
    mark_duplicates(exact_groups)

    same_flight_groups: dict[tuple[str, str, str, str, str], list[Segment]] = {}
    for segment in segments:
        if not segment.flight_number or not segment.pnr:
            continue
        same_flight_groups.setdefault(
            (
                segment.dep_airport,
                segment.arr_airport,
                segment.airline or "",
                _normalize_flight_number(segment.flight_number) or "",
                segment.pnr,
            ),
            [],
        ).append(segment)
    mark_duplicates(same_flight_groups)

    route_day_groups: dict[tuple[str, str, object], list[Segment]] = {}
    for segment in segments:
        route_day_groups.setdefault(
            (segment.dep_airport, segment.arr_airport, _segment_dep_time(segment).date()),
            [],
        ).append(segment)
    for key, group in route_day_groups.items():
        active = [segment for segment in group if segment.id not in delete_ids]
        if len(active) <= 1:
            continue
        ordered_active = sorted(active, key=_segment_sort_key)
        compatible: list[Segment] = [ordered_active[0]]
        for segment in ordered_active[1:]:
            if (
                _is_low_information_segment(segment)
                or any(_is_low_information_segment(other) for other in compatible)
                or any(_segments_can_dedupe(segment, other) for other in compatible)
            ):
                compatible.append(segment)
        if len(compatible) > 1:
            mark_duplicates({key: compatible})

    same_day_groups: dict[tuple[str, str, str, object], list[Segment]] = {}
    for segment in segments:
        same_day_groups.setdefault(
            (
                segment.dep_airport,
                segment.arr_airport,
                segment.airline or "",
                _segment_dep_time(segment).date(),
            ),
            [],
        ).append(segment)
    for key, group in same_day_groups.items():
        ordered = sorted(
            [segment for segment in group if segment.id not in delete_ids],
            key=_segment_sort_key,
        )
        if len(ordered) <= 1:
            continue
        cluster: list[Segment] = [ordered[0]]
        for segment in ordered[1:]:
            if (
                _segment_dep_time(segment) - _segment_dep_time(cluster[-1]) <= timedelta(hours=8)
                and (
                    _is_low_information_segment(segment)
                    or _is_low_information_segment(cluster[-1])
                    or _segments_can_dedupe(segment, cluster[-1])
                )
            ):
                cluster.append(segment)
                continue
            mark_duplicates({key: cluster})
            cluster = [segment]
        mark_duplicates({key: cluster})

    _restore_superseded_layover_rewrites(segments, delete_ids)
    _mark_newer_direct_segments_replacing_layover_chains(segments, delete_ids)
    _rewrite_implied_layover_destinations(segments, delete_ids)
    _mark_covered_through_segments(segments, delete_ids)
    _mark_no_pnr_same_route_replacements(segments, delete_ids)
    _mark_rebooked_same_route_replacements(segments, delete_ids)
    _mark_same_trip_flight_key_collisions(segments, delete_ids)

    for segment in segments:
        if segment.id in delete_ids:
            db.delete(segment)
        elif segment.id not in keep_ids:
            keep_ids.add(segment.id)
    if delete_ids:
        db.flush()
    return [segment for segment in segments if segment.id in keep_ids]


def _rewrite_implied_layover_destinations(segments: list[Segment], delete_ids: set[int]) -> None:
    """Correct an over-broad first leg when a following leg reveals the layover.

    Some OTA emails render a through destination beside the first operating
    flight, e.g. BR272 MNL -> IAH followed by BR52 TPE -> IAH. For globe arcs we
    want the operating legs, so rewrite the first row to MNL -> TPE when the
    following same-booking segment clearly starts at the implied layover.
    """
    active = [segment for segment in segments if segment.id not in delete_ids and segment.pnr]
    for direct in sorted(active, key=_segment_sort_key):
        if _segment_has_nonstop_evidence(direct):
            continue
        direct_pnrs = _segment_pnr_set(direct)
        if not direct_pnrs:
            continue
        direct_dep = _segment_dep_time(direct)
        direct_arr = _segment_arr_time(direct)
        if not direct_dep or not direct_arr or direct_arr <= direct_dep:
            continue
        candidates = [
            segment
            for segment in active
            if segment.id != direct.id
            and segment.id not in delete_ids
            and direct_pnrs & _segment_pnr_set(segment)
            and segment.arr_airport == direct.arr_airport
            and segment.dep_airport not in {direct.dep_airport, direct.arr_airport}
            and direct_dep <= _segment_dep_time(segment) <= direct_arr + timedelta(hours=36)
        ]
        if not candidates:
            continue
        next_leg = min(candidates, key=lambda segment: abs((_segment_dep_time(segment) - direct_arr).total_seconds()))
        layover_airport = next_leg.dep_airport
        if len(layover_airport or "") != 3 or layover_airport == direct.dep_airport:
            continue
        if _has_same_pnr_route_sibling(
            direct,
            active,
            dep_airport=direct.dep_airport,
            arr_airport=layover_airport,
        ):
            continue
        old_route = f"{direct.dep_airport}-{direct.arr_airport}"
        old_arrival = direct.arr_time
        direct.arr_airport = layover_airport
        next_dep = _segment_dep_time(next_leg)
        if next_dep and direct_arr >= next_dep:
            direct.arr_time = next_dep - timedelta(minutes=45)
        if not direct.arr_time or _segment_arr_time(direct) <= _segment_dep_time(direct):
            direct.arr_time = direct.dep_time + timedelta(hours=2)
        direct.distance_km = None
        direct.geom = None
        _add_booking_relationship(
            direct,
            {
                "type": "implied_layover_destination_rewrite",
                "old_route": old_route,
                "new_route": f"{direct.dep_airport}-{direct.arr_airport}",
                "following_route": f"{next_leg.dep_airport}-{next_leg.arr_airport}",
                "old_arrival": old_arrival.isoformat() if old_arrival else None,
                "reason": "following_leg_reveals_first_leg_layover",
            },
        )


def _restore_superseded_layover_rewrites(segments: list[Segment], delete_ids: set[int]) -> None:
    active = [segment for segment in segments if segment.id not in delete_ids and segment.pnr]
    by_id = {segment.id: segment for segment in active}
    for segment in sorted(active, key=_segment_sort_key):
        rewrite = _latest_layover_rewrite(segment)
        if not rewrite:
            continue
        old_route = rewrite.get("old_route")
        following_route = rewrite.get("following_route")
        old_dep, old_arr = _split_route(old_route)
        following_dep, following_arr = _split_route(following_route)
        if not old_dep or not old_arr or not following_dep or not following_arr:
            continue
        if segment.dep_airport != old_dep or segment.arr_airport != following_dep:
            continue

        same_route_sibling = _has_same_pnr_route_sibling(
            segment,
            active,
            dep_airport=segment.dep_airport,
            arr_airport=segment.arr_airport,
        )
        chain = _covering_layover_chain_for_route(
            dep_airport=old_dep,
            arr_airport=old_arr,
            dep_time=_segment_dep_time(segment),
            arr_time=_rewrite_old_arrival(segment, rewrite) or _segment_arr_time(segment),
            candidates=[other for other in active if other.id != segment.id],
            pnr_set=_segment_pnr_set(segment),
        )
        chain_is_older = bool(chain) and _segment_source_received_at(segment) and all(
            (chain_time := _segment_source_received_at(leg)) and chain_time < _segment_source_received_at(segment)
            for leg in chain
        )
        if not same_route_sibling and not chain_is_older:
            continue

        old_current_route = f"{segment.dep_airport}-{segment.arr_airport}"
        segment.dep_airport = old_dep
        segment.arr_airport = old_arr
        old_arrival = _rewrite_old_arrival(segment, rewrite)
        if old_arrival and old_arrival > _segment_dep_time(segment):
            segment.arr_time = old_arrival
        segment.distance_km = None
        segment.geom = None
        _add_booking_relationship(
            segment,
            {
                "type": "implied_layover_destination_rewrite_restored",
                "old_current_route": old_current_route,
                "restored_route": old_route,
                "reason": "newer_direct_or_specific_operating_leg_wins",
            },
        )


def _mark_newer_direct_segments_replacing_layover_chains(segments: list[Segment], delete_ids: set[int]) -> None:
    active = [segment for segment in segments if segment.id not in delete_ids and segment.pnr]
    for direct in sorted(active, key=_segment_sort_key):
        direct_time = _segment_source_received_at(direct)
        if not direct_time:
            continue
        chain = _covering_layover_chain(direct, [segment for segment in active if segment.id != direct.id])
        if len(chain) < 2:
            continue
        chain_times = [_segment_source_received_at(leg) for leg in chain]
        if not all(time and time < direct_time for time in chain_times):
            continue
        for leg in chain:
            if leg.id in delete_ids:
                continue
            _add_pnr_alias(direct, leg.pnr, reason="newer_direct_replaces_layover_chain")
            _add_booking_relationship(
                direct,
                {
                    "type": "older_layover_leg_removed",
                    "removed_segment_id": leg.id,
                    "removed_route": f"{leg.dep_airport}-{leg.arr_airport}",
                    "removed_flight_number": _normalize_flight_number(leg.flight_number),
                    "reason": "newer_change_email_replaced_layover_route",
                },
            )
            delete_ids.add(leg.id)


def _mark_covered_through_segments(segments: list[Segment], delete_ids: set[int]) -> None:
    active = [segment for segment in segments if segment.id not in delete_ids and segment.pnr]
    by_pnr: dict[str, list[Segment]] = {}
    for segment in active:
        normalized_pnr = _normalize_pnr(segment.pnr)
        if normalized_pnr:
            by_pnr.setdefault(normalized_pnr, []).append(segment)

    for group in by_pnr.values():
        ordered = sorted(group, key=_segment_sort_key)
        for direct in ordered:
            if direct.id in delete_ids or _segment_has_nonstop_evidence(direct):
                continue
            chain = _covering_layover_chain(direct, [segment for segment in ordered if segment.id != direct.id])
            if len(chain) < 2:
                continue
            delete_ids.add(direct.id)
            for leg in chain:
                _add_booking_relationship(
                    leg,
                    {
                        "type": "covered_through_segment_removed",
                        "removed_route": f"{direct.dep_airport}-{direct.arr_airport}",
                        "removed_flight_number": _normalize_flight_number(direct.flight_number),
                        "reason": "layover_legs_cover_direct_segment",
                    },
                )


def _mark_no_pnr_same_route_replacements(segments: list[Segment], delete_ids: set[int]) -> None:
    active = [segment for segment in segments if segment.id not in delete_ids]
    groups: dict[tuple[str, str, object, str], list[Segment]] = {}
    for segment in active:
        groups.setdefault(
            (
                segment.dep_airport,
                segment.arr_airport,
                _segment_dep_time(segment).date(),
                segment.airline or "",
            ),
            [],
        ).append(segment)

    for group in groups.values():
        if len(group) <= 1:
            continue
        for sparse in sorted(group, key=_segment_sort_key):
            if sparse.id in delete_ids or sparse.pnr:
                continue
            sparse_time = _segment_source_received_at(sparse)
            candidates = [
                segment
                for segment in group
                if segment.id != sparse.id
                and segment.id not in delete_ids
                and segment.pnr
                and abs(_segment_dep_time(segment) - _segment_dep_time(sparse)) <= timedelta(hours=4)
                and (not sparse_time or not _segment_source_received_at(segment) or _segment_source_received_at(segment) >= sparse_time)
            ]
            if not candidates:
                continue
            keep = _best_duplicate_segment(candidates, active)
            _merge_duplicate_segment(keep, sparse)
            _add_booking_relationship(
                keep,
                {
                    "type": "no_pnr_same_route_segment_removed",
                    "removed_segment_id": sparse.id,
                    "removed_flight_number": _normalize_flight_number(sparse.flight_number),
                    "reason": "richer_same_route_segment_exists",
                },
            )
            delete_ids.add(sparse.id)


def _mark_rebooked_same_route_replacements(segments: list[Segment], delete_ids: set[int]) -> None:
    active = [segment for segment in segments if segment.id not in delete_ids and segment.pnr]
    groups: dict[tuple[str, str, object, str], list[Segment]] = {}
    for segment in active:
        groups.setdefault(
            (
                segment.dep_airport,
                segment.arr_airport,
                _segment_dep_time(segment).date(),
                segment.airline or "",
            ),
            [],
        ).append(segment)

    for group in groups.values():
        if len(group) <= 1:
            continue
        ordered = sorted(group, key=_segment_sort_key)
        for older in ordered:
            if older.id in delete_ids:
                continue
            older_time = _segment_source_received_at(older)
            candidates = [
                segment
                for segment in ordered
                if segment.id != older.id
                and segment.id not in delete_ids
                and abs(_segment_dep_time(segment) - _segment_dep_time(older)) <= timedelta(hours=8)
                and _bookings_linked_in_trip(older, segment, active)
                and _source_is_newer(segment, older_time)
            ]
            if not candidates:
                continue
            keep = max(candidates, key=lambda segment: (_segment_source_received_at(segment) or _segment_dep_time(segment), _segment_quality_score(segment), segment.id or 0))
            _merge_duplicate_segment(keep, older)
            _add_booking_relationship(
                keep,
                {
                    "type": "rebooked_same_route_segment_removed",
                    "removed_segment_id": older.id,
                    "removed_pnr": older.pnr,
                    "removed_flight_number": _normalize_flight_number(older.flight_number),
                    "reason": "newer_linked_booking_replaced_same_route",
                },
            )
            delete_ids.add(older.id)


def _segment_pnr_set(segment: Segment) -> set[str]:
    values = {_normalize_pnr(segment.pnr)}
    meta = segment.meta_json or {}
    for alias in meta.get("pnr_aliases") or []:
        values.add(_normalize_pnr(alias))
    return {value for value in values if value}


def _latest_layover_rewrite(segment: Segment) -> Optional[dict]:
    relationships = (segment.meta_json or {}).get("booking_relationships") or []
    for relationship in reversed(relationships):
        if relationship.get("type") == "implied_layover_destination_rewrite":
            return relationship
    return None


def _split_route(route: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not route or "-" not in route:
        return None, None
    dep, arr = route.split("-", 1)
    dep = dep.strip().upper()
    arr = arr.strip().upper()
    if len(dep) != 3 or len(arr) != 3:
        return None, None
    return dep, arr


def _rewrite_old_arrival(segment: Segment, rewrite: dict):
    raw = rewrite.get("old_arrival")
    if not raw:
        return None
    try:
        return _db_datetime(datetime.fromisoformat(str(raw)))
    except ValueError:
        return None


def _has_same_pnr_route_sibling(
    segment: Segment,
    candidates: list[Segment],
    *,
    dep_airport: str,
    arr_airport: str,
) -> bool:
    pnr_set = _segment_pnr_set(segment)
    if not pnr_set:
        return False
    return any(
        other.id != segment.id
        and other.dep_airport == dep_airport
        and other.arr_airport == arr_airport
        and _segment_dep_time(other).date() == _segment_dep_time(segment).date()
        and bool(pnr_set & _segment_pnr_set(other))
        for other in candidates
    )


def _bookings_linked_in_trip(left: Segment, right: Segment, segments: list[Segment]) -> bool:
    left_pnrs = _segment_pnr_set(left)
    right_pnrs = _segment_pnr_set(right)
    if left_pnrs & right_pnrs:
        return True
    if not left_pnrs or not right_pnrs:
        return False
    for segment in segments:
        segment_pnrs = _segment_pnr_set(segment)
        if not (segment_pnrs & left_pnrs and segment_pnrs & right_pnrs):
            continue
        if (
            abs(_segment_dep_time(segment) - _segment_dep_time(left)) <= timedelta(days=14)
            or abs(_segment_dep_time(segment) - _segment_dep_time(right)) <= timedelta(days=14)
        ):
            return True
    return False


def _source_is_newer(segment: Segment, older_time) -> bool:
    segment_time = _segment_source_received_at(segment)
    if older_time and segment_time:
        return segment_time - older_time >= timedelta(hours=6)
    if not older_time and segment_time:
        return True
    return False


def _covering_layover_chain_for_route(
    *,
    dep_airport: str,
    arr_airport: str,
    dep_time,
    arr_time,
    candidates: list[Segment],
    pnr_set: set[str],
) -> list[Segment]:
    if not pnr_set:
        return []
    probe = SimpleNamespace(
        id=-1,
        dep_airport=dep_airport,
        arr_airport=arr_airport,
        dep_time=dep_time,
        arr_time=arr_time,
        pnr=next(iter(pnr_set)),
        meta_json={"pnr_aliases": sorted(pnr_set - {next(iter(pnr_set))})},
        flight_number=None,
        airline=None,
    )
    return _covering_layover_chain(
        probe, [segment for segment in candidates if pnr_set & _segment_pnr_set(segment)]
    )


def _mark_same_trip_flight_key_collisions(segments: list[Segment], delete_ids: set[int]) -> None:
    active = [segment for segment in segments if segment.id not in delete_ids]
    groups: dict[tuple[str, str, str, object], list[Segment]] = {}
    for segment in active:
        normalized_pnr = _normalize_pnr(segment.pnr)
        normalized_number = _normalize_flight_number(segment.flight_number)
        if not normalized_pnr or not segment.airline or not normalized_number:
            continue
        groups.setdefault(
            (
                normalized_pnr,
                segment.airline,
                normalized_number,
                _segment_dep_time(segment),
            ),
            [],
        ).append(segment)

    for group in groups.values():
        remaining = [segment for segment in group if segment.id not in delete_ids]
        if len(remaining) <= 1:
            continue
        keep = _best_same_trip_flight_key_segment(remaining, active)
        for duplicate in remaining:
            if duplicate.id == keep.id:
                continue
            _merge_duplicate_segment(keep, duplicate)
            _add_booking_relationship(
                keep,
                {
                    "type": "same_trip_flight_key_collision_removed",
                    "removed_segment_id": duplicate.id,
                    "removed_route": f"{duplicate.dep_airport}-{duplicate.arr_airport}",
                    "removed_flight_number": _normalize_flight_number(duplicate.flight_number),
                    "reason": "would_duplicate_trip_flight_departure_key",
                },
            )
            delete_ids.add(duplicate.id)


def _best_same_trip_flight_key_segment(duplicates: list[Segment], all_segments: list[Segment]) -> Segment:
    return max(duplicates, key=lambda segment: _same_trip_flight_key_score(segment, all_segments))


def _same_trip_flight_key_score(segment: Segment, all_segments: list[Segment]) -> tuple[int, int, int, int, float, int]:
    dep_time = _segment_dep_time(segment)
    arr_time = _segment_arr_time(segment)
    duration = max(0.0, (arr_time - dep_time).total_seconds()) if dep_time and arr_time else 0.0
    return (
        int(_segment_has_nonstop_evidence(segment)),
        int(_segment_has_following_connection(segment, all_segments)),
        int(_segment_has_previous_connection(segment, all_segments)),
        _segment_quality_score(segment),
        duration,
        segment.id or 0,
    )


def _segment_has_following_connection(segment: Segment, all_segments: list[Segment]) -> bool:
    arr_time = _segment_arr_time(segment)
    return any(
        other.id != segment.id
        and other.dep_airport == segment.arr_airport
        and timedelta(minutes=-30) <= _segment_dep_time(other) - arr_time <= timedelta(hours=36)
        for other in all_segments
    )


def _segment_has_previous_connection(segment: Segment, all_segments: list[Segment]) -> bool:
    dep_time = _segment_dep_time(segment)
    return any(
        other.id != segment.id
        and other.arr_airport == segment.dep_airport
        and timedelta(minutes=-30) <= dep_time - _segment_arr_time(other) <= timedelta(hours=36)
        for other in all_segments
    )


def _covering_layover_chain(direct: Segment, candidates: list[Segment]) -> list[Segment]:
    direct_dep = _segment_dep_time(direct)
    direct_arr = _segment_arr_time(direct)
    if not direct_dep or not direct_arr or direct_arr <= direct_dep:
        return []
    route_legs = [
        segment
        for segment in candidates
        if segment.dep_airport != segment.arr_airport
        and segment.dep_airport != direct.arr_airport
        and segment.arr_airport != direct.dep_airport
        and _segment_dep_time(segment) >= direct_dep - timedelta(hours=18)
        and _segment_arr_time(segment) <= direct_arr + timedelta(hours=36)
    ]
    starts = [
        segment
        for segment in route_legs
        if segment.dep_airport == direct.dep_airport
        and abs(_segment_dep_time(segment) - direct_dep) <= timedelta(hours=18)
    ]
    for start in sorted(starts, key=_segment_sort_key):
        chain = _walk_layover_chain(
            current=start,
            target_airport=direct.arr_airport,
            target_arrival=direct_arr,
            candidates=route_legs,
            used_ids={start.id},
        )
        if len(chain) >= 2:
            return chain
    return []


def _walk_layover_chain(
    *,
    current: Segment,
    target_airport: str,
    target_arrival,
    candidates: list[Segment],
    used_ids: set[int],
) -> list[Segment]:
    if current.arr_airport == target_airport and abs(_segment_arr_time(current) - target_arrival) <= timedelta(hours=36):
        return [current]
    if len(used_ids) >= 4:
        return []
    current_arr = _segment_arr_time(current)
    next_legs = [
        segment
        for segment in candidates
        if segment.id not in used_ids
        and segment.dep_airport == current.arr_airport
        and timedelta(minutes=-30) <= _segment_dep_time(segment) - current_arr <= timedelta(hours=36)
    ]
    for leg in sorted(next_legs, key=_segment_sort_key):
        chain = _walk_layover_chain(
            current=leg,
            target_airport=target_airport,
            target_arrival=target_arrival,
            candidates=candidates,
            used_ids={*used_ids, leg.id},
        )
        if chain:
            return [current, *chain]
    return []


def _segment_has_nonstop_evidence(segment: Segment) -> bool:
    meta = segment.meta_json or {}
    if meta.get("nonstop") is True or meta.get("direct_nonstop") is True:
        return True
    signals = meta.get("signals") or meta.get("evidence_signals") or []
    if isinstance(signals, str):
        signals = [signals]
    return any(str(signal).lower() in {"nonstop", "direct_nonstop", "explicit_nonstop"} for signal in signals)


def _best_duplicate_segment(duplicates: list[Segment], all_segments: list[Segment]) -> Segment:
    return max(
        duplicates,
        key=lambda segment: (
            _segment_quality_score(segment),
            _same_pnr_neighbor_count(segment, all_segments),
            bool(segment.meta_json and (segment.meta_json or {}).get("enrichment")),
            bool(segment.pnr),
            bool(segment.distance_km),
            segment.id,
        ),
    )


def _segment_quality_score(segment: Segment) -> int:
    meta = segment.meta_json or {}
    score = 0
    if segment.arr_time and segment.dep_time and _segment_arr_time(segment) > _segment_dep_time(segment):
        score += 8
    if meta.get("source") != "subject":
        score += 4
    if segment.flight_number:
        score += 3
        if any(ch.isalpha() for ch in segment.flight_number):
            score += 1
    if segment.airline:
        score += 2
    if segment.pnr:
        score += 2
    if meta.get("confidence"):
        score += min(3, int(meta["confidence"]) if isinstance(meta["confidence"], int) else 1)
    return score


def _is_low_information_segment(segment: Segment) -> bool:
    meta = segment.meta_json or {}
    return (
        meta.get("source") == "subject"
        or not segment.flight_number
        or not segment.airline
        or _segment_arr_time(segment) <= _segment_dep_time(segment)
    )


def _segments_can_dedupe(a: Segment, b: Segment) -> bool:
    a_number = _normalize_flight_number(a.flight_number)
    b_number = _normalize_flight_number(b.flight_number)
    if a_number and b_number and not _flight_numbers_compatible(a_number, b_number):
        return False
    if a.airline and b.airline and a.airline != b.airline and not _flight_numbers_compatible(a_number, b_number):
        return False
    if abs(_segment_dep_time(a) - _segment_dep_time(b)) > timedelta(hours=24):
        return False
    return True


def _flight_numbers_compatible(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return True
    if a == b:
        return True
    return _flight_number_numeric_part(a) == _flight_number_numeric_part(b)


def _flight_number_numeric_part(value: str) -> str:
    normalized = _normalize_flight_number(value) or value
    if len(normalized) >= 3 and normalized[:2].isalnum() and normalized[2:].isdigit():
        return normalized[2:].lstrip("0") or "0"
    return "".join(ch for ch in normalized if ch.isdigit()).lstrip("0") or normalized


def _same_pnr_neighbor_count(segment: Segment, all_segments: list[Segment]) -> int:
    if not segment.pnr:
        return 0
    count = 0
    for other in all_segments:
        if other.id == segment.id or other.pnr != segment.pnr:
            continue
        if abs(_segment_dep_time(other) - _segment_dep_time(segment)) <= timedelta(days=7):
            count += 1
    return count


def _merge_duplicate_segment(keep: Segment, duplicate: Segment) -> None:
    _add_pnr_alias(keep, duplicate.pnr, reason="duplicate_segment")
    _add_pnr_alias(duplicate, keep.pnr, reason="duplicate_segment")
    if duplicate.pnr and not keep.pnr:
        keep.pnr = duplicate.pnr
    if duplicate.airline and not keep.airline:
        keep.airline = duplicate.airline
    if duplicate.flight_number and (
        not keep.flight_number
        or (
            _flight_numbers_compatible(
                _normalize_flight_number(keep.flight_number),
                _normalize_flight_number(duplicate.flight_number),
            )
            and len(duplicate.flight_number) > len(keep.flight_number)
        )
    ):
        keep.flight_number = _normalize_flight_number(duplicate.flight_number)
    if duplicate.distance_km and not keep.distance_km:
        keep.distance_km = duplicate.distance_km
    if duplicate.geom and not keep.geom:
        keep.geom = duplicate.geom
    meta = dict(keep.meta_json or {})
    duplicate_meta = duplicate.meta_json or {}
    if duplicate_meta.get("source") and "source" not in meta:
        meta["source"] = duplicate_meta["source"]
    if duplicate_meta.get("enrichment") and "enrichment" not in meta:
        meta["enrichment"] = duplicate_meta["enrichment"]
    keep.meta_json = meta


def _mark_duplicate_route_aliases(segments: list[Segment]) -> None:
    route_day_groups: dict[tuple[str, str, object], list[Segment]] = {}
    for segment in segments:
        route_day_groups.setdefault(
            (segment.dep_airport, segment.arr_airport, _segment_dep_time(segment).date()),
            [],
        ).append(segment)
    for group in route_day_groups.values():
        if len(group) <= 1:
            continue
        for segment in group:
            for other in group:
                if segment.id == other.id:
                    continue
                if not _segments_can_dedupe(segment, other):
                    continue
                if segment.pnr and other.pnr and segment.pnr != other.pnr:
                    _add_pnr_alias(segment, other.pnr, reason="same_route_date")
                    _add_booking_relationship(
                        segment,
                        {
                            "type": "pnr_alias_same_trip",
                            "pnr": other.pnr,
                            "segment_id": other.id,
                            "reason": "same_route_date",
                        },
                    )


def _mark_near_duplicate_booking_replacements(segments: list[Segment]) -> None:
    by_pnr: dict[str, list[Segment]] = {}
    for segment in segments:
        if segment.pnr:
            by_pnr.setdefault(segment.pnr, []).append(segment)
    pnrs = sorted(by_pnr)
    for index, left_pnr in enumerate(pnrs):
        for right_pnr in pnrs[index + 1 :]:
            left = by_pnr[left_pnr]
            right = by_pnr[right_pnr]
            if _booking_similarity(left, right) < 0.75:
                continue
            left_time = _booking_first_source_time(left)
            right_time = _booking_first_source_time(right)
            if left_time and right_time and abs(left_time - right_time) > timedelta(hours=24):
                continue
            for segment in left:
                _add_booking_relationship(
                    segment,
                    {
                        "type": "similar_booking_candidate",
                        "pnr": right_pnr,
                        "reason": "same_dates_routes_near_source_time",
                    },
                )
            for segment in right:
                _add_booking_relationship(
                    segment,
                    {
                        "type": "similar_booking_candidate",
                        "pnr": left_pnr,
                        "reason": "same_dates_routes_near_source_time",
                    },
                )


def _mark_reused_pnr_candidates(segments: list[Segment]) -> None:
    by_pnr: dict[str, list[Segment]] = {}
    for segment in segments:
        if segment.pnr:
            by_pnr.setdefault(segment.pnr, []).append(segment)
    for pnr, group in by_pnr.items():
        trip_ids = {segment.trip_id for segment in group}
        if len(trip_ids) <= 1:
            continue
        ordered = sorted(group, key=_segment_sort_key)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.trip_id == current.trip_id:
                continue
            gap = _segment_dep_time(current) - _segment_arr_time(previous)
            if gap < timedelta(days=30):
                continue
            _add_booking_relationship(
                current,
                {
                    "type": "possible_reused_pnr_or_travel_credit",
                    "pnr": pnr,
                    "previous_segment_id": previous.id,
                    "previous_trip_id": previous.trip_id,
                    "gap_days": gap.days,
                },
            )


def _mark_cancellation_replacements(
    db: Session,
    user_id: int,
    canceled_pnr: str,
    canceled_segments: list[Segment],
    cancellation_time,
) -> None:
    if not canceled_segments:
        return
    candidates = (
        db.query(Segment)
        .join(Trip)
        .filter(Trip.user_id == user_id, Segment.pnr != canceled_pnr)
        .all()
    )
    for canceled in canceled_segments:
        for candidate in candidates:
            if not candidate.pnr or candidate.id == canceled.id:
                continue
            if not _segments_are_replacement_candidates(canceled, candidate):
                continue
            _add_booking_relationship(
                candidate,
                {
                    "type": "surviving_replacement_candidate",
                    "replaces_pnr": canceled_pnr,
                    "canceled_segment_id": canceled.id,
                    "cancellation_received_at": cancellation_time.isoformat() if cancellation_time else None,
                },
            )
            _add_pnr_alias(candidate, canceled_pnr, reason="canceled_similar_booking")


def _first_active_pnr_alias(segment: Segment, canceled_pnr: str) -> Optional[str]:
    aliases = (segment.meta_json or {}).get("pnr_aliases") or []
    for alias in aliases:
        normalized = _normalize_pnr(alias)
        if normalized and normalized != canceled_pnr:
            return normalized
    return None


def _segments_are_replacement_candidates(canceled: Segment, candidate: Segment) -> bool:
    if _segment_dep_time(canceled).date() != _segment_dep_time(candidate).date():
        return False
    if canceled.dep_airport != candidate.dep_airport or canceled.arr_airport != candidate.arr_airport:
        return False
    if abs(_segment_dep_time(canceled) - _segment_dep_time(candidate)) > timedelta(hours=4):
        return False
    canceled_number = _normalize_flight_number(canceled.flight_number)
    candidate_number = _normalize_flight_number(candidate.flight_number)
    return not canceled_number or not candidate_number or _flight_numbers_compatible(canceled_number, candidate_number)


def _booking_similarity(left: list[Segment], right: list[Segment]) -> float:
    if not left or not right:
        return 0.0
    left_keys = {_segment_similarity_key(segment) for segment in left}
    right_keys = {_segment_similarity_key(segment) for segment in right}
    overlap = len(left_keys & right_keys)
    if not overlap:
        # Same date/route with changed flight number is still a meaningful
        # replacement signal.
        left_route_keys = {_segment_route_day_key(segment) for segment in left}
        right_route_keys = {_segment_route_day_key(segment) for segment in right}
        overlap = len(left_route_keys & right_route_keys)
        denominator = max(len(left_route_keys), len(right_route_keys), 1)
    else:
        denominator = max(len(left_keys), len(right_keys), 1)
    return overlap / denominator


def _segment_similarity_key(segment: Segment) -> tuple[str, str, object, Optional[str]]:
    return (
        segment.dep_airport,
        segment.arr_airport,
        _segment_dep_time(segment).date(),
        _normalize_flight_number(segment.flight_number),
    )


def _segment_route_day_key(segment: Segment) -> tuple[str, str, object]:
    return (segment.dep_airport, segment.arr_airport, _segment_dep_time(segment).date())


def _booking_first_source_time(segments: list[Segment]):
    times = [time for segment in segments if (time := _segment_source_received_at(segment))]
    return min(times) if times else None


def _add_pnr_alias(segment: Segment, alias: Optional[str], *, reason: str) -> None:
    alias = _normalize_pnr(alias)
    if not alias or alias == _normalize_pnr(segment.pnr):
        return
    meta = dict(segment.meta_json or {})
    aliases = list(meta.get("pnr_aliases") or [])
    if alias not in aliases:
        aliases.append(alias)
    meta["pnr_aliases"] = aliases
    _add_booking_relationship_to_meta(meta, {"type": "pnr_alias", "pnr": alias, "reason": reason})
    segment.meta_json = meta


def _add_booking_relationship(segment: Segment, relationship: dict) -> None:
    meta = dict(segment.meta_json or {})
    _add_booking_relationship_to_meta(meta, relationship)
    segment.meta_json = meta


def _add_booking_relationship_to_meta(meta: dict, relationship: dict) -> None:
    cleaned = {key: value for key, value in relationship.items() if value is not None}
    relationships = list(meta.get("booking_relationships") or [])
    if cleaned not in relationships:
        relationships.append(cleaned)
    meta["booking_relationships"] = relationships


def _belongs_to_current_trip(
    current: list[Segment],
    segment: Segment,
    gap,
    home_airport: Optional[str],
    home_airports: set[str],
) -> bool:
    previous = current[-1]
    same_booking = bool(segment.pnr and segment.pnr in {item.pnr for item in current if item.pnr})
    ended_at_home = bool(home_airport and previous.arr_airport == home_airport)
    starts_from_home = bool(home_airport and segment.dep_airport == home_airport)
    ended_at_anchor = previous.arr_airport in home_airports
    starts_from_anchor = segment.dep_airport in home_airports or any(
        _airports_are_near(segment.dep_airport, anchor) for anchor in home_airports
    )

    if gap < timedelta():
        return same_booking and _segments_can_overlap_in_same_booking(current, segment)

    if ended_at_home and starts_from_home:
        return same_booking and gap <= timedelta(hours=48)
    if ended_at_anchor and starts_from_anchor and gap > timedelta(hours=6):
        return same_booking and gap <= timedelta(hours=48)

    if previous.arr_airport == segment.dep_airport and gap <= _EXTRA_DESTINATION_STOPOVER:
        return True
    if previous.arr_airport == segment.dep_airport and gap <= timedelta(days=45):
        return True
    if _airports_are_near(previous.arr_airport, segment.dep_airport) and gap <= timedelta(days=21):
        return True
    if same_booking and gap <= timedelta(days=21) and not ended_at_home:
        return True
    if gap <= timedelta(hours=36):
        return True

    return False


def _cluster_is_away_from_home(current: list[Segment], home_airport: Optional[str]) -> bool:
    if not current or not home_airport:
        return False
    return current[-1].arr_airport != home_airport and any(
        segment.dep_airport == home_airport or segment.arr_airport == home_airport for segment in current
    )


def _segments_can_overlap_in_same_booking(current: list[Segment], segment: Segment) -> bool:
    # Same-PNR emails can include old and new versions of the same trip. Keep
    # route/date overlaps out of one itinerary unless they are alternate copies
    # of essentially the same segment.
    return any(
        existing.dep_airport == segment.dep_airport
        and existing.arr_airport == segment.arr_airport
        and _segment_dep_time(existing).date() == _segment_dep_time(segment).date()
        for existing in current
    )


def _infer_home_airport(segments: list[Segment]) -> Optional[str]:
    if segments:
        ordered = sorted(segments, key=_segment_sort_key)
        if ordered[0].dep_airport == ordered[-1].arr_airport:
            return ordered[0].dep_airport
    counts: Counter[str] = Counter()
    for segment in segments:
        counts[segment.dep_airport] += 1
        counts[segment.arr_airport] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _infer_home_airports(segments: list[Segment]) -> set[str]:
    counts: Counter[str] = Counter()
    for segment in segments:
        counts[segment.dep_airport] += 1
        counts[segment.arr_airport] += 1
    if not counts:
        return set()
    top_count = counts.most_common(1)[0][1]
    threshold = max(6, math.ceil(top_count * 0.6))
    return {airport for airport, count in counts.items() if count >= threshold}


def _select_reusable_trip_id(cluster: list[Segment], used_trip_ids: set[int]) -> Optional[int]:
    counts = Counter(segment.trip_id for segment in cluster if segment.trip_id not in used_trip_ids)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _trip_title_for_segments(segments: list[Segment], home_airport: Optional[str] = None) -> Optional[str]:
    if not segments:
        return None
    ordered = sorted(segments, key=_segment_sort_key)
    origin = ordered[0].dep_airport
    final = ordered[-1].arr_airport
    title = _smart_trip_title(ordered, origin, final, home_airport=home_airport)
    if title:
        return title
    destination = _main_destination(segments, origin, final, home_airport=home_airport)
    if destination:
        return _airport_title(destination)
    if final and final != origin:
        return _airport_title(final)
    return f"{origin} -> {final}"


def _smart_trip_title(
    segments: list[Segment],
    origin: str,
    final: str,
    home_airport: Optional[str] = None,
) -> Optional[str]:
    meaningful_airports = _meaningful_destination_airports(segments, origin, final, home_airport=home_airport)
    if not meaningful_airports:
        return None

    home_reference = home_airport if home_airport in {origin, final} else origin
    home_country = _airport_country(home_reference) or _airport_country(origin)
    countries = _ordered_unique(
        country
        for code in meaningful_airports
        if (country := _airport_country(code))
    )
    foreign_countries = [country for country in countries if country != home_country]

    if not foreign_countries:
        return _airport_title(meaningful_airports[0])

    if len(foreign_countries) == 1:
        country = foreign_countries[0]
        if _should_use_city_title_for_country(
            country=country,
            destination_airports=meaningful_airports,
            home_airport=home_reference,
            home_country=home_country,
        ):
            return _airport_title(_first_airport_in_country(meaningful_airports, country))
        return _country_title(country)

    return _join_title_parts(_country_title(country) for country in foreign_countries)


def _meaningful_destination_airports(
    segments: list[Segment],
    origin: str,
    final: str,
    home_airport: Optional[str] = None,
) -> list[str]:
    main_destination = _main_destination(segments, origin, final, home_airport=home_airport)
    meaningful: list[str] = []
    ordered = sorted(segments, key=_segment_sort_key)

    if home_airport and final == home_airport and origin != home_airport and len(ordered) == 1:
        return [origin]

    for index, segment in enumerate(ordered[:-1]):
        code = segment.arr_airport
        if code == origin:
            continue
        next_segment = ordered[index + 1]
        stopover = _segment_dep_time(next_segment) - _segment_arr_time(segment)
        if code == main_destination or stopover >= _EXTRA_DESTINATION_STOPOVER:
            _append_unique(meaningful, code)

    if main_destination:
        _append_unique(meaningful, main_destination)

    if not meaningful and final and final != origin:
        meaningful.append(final)

    return meaningful


def _airport_country(code: str) -> Optional[str]:
    country = (_AIRPORT_DETAILS.get(code, {}).get("country") or "").strip().upper()
    return country or None


def _should_use_city_title_for_country(
    country: str,
    destination_airports: list[str],
    home_airport: str,
    home_country: Optional[str],
) -> bool:
    if country == home_country:
        return True

    home_coords = _AIRPORT_COORDS.get(home_airport)
    if not home_coords:
        return False

    for code in destination_airports:
        if _airport_country(code) != country:
            continue
        coords = _AIRPORT_COORDS.get(code)
        if not coords:
            continue
        distance = _haversine_km(home_coords[0], home_coords[1], coords[0], coords[1])
        if distance <= _NEARBY_INTERNATIONAL_CITY_KM:
            return True
    return False


def _country_title(code: str) -> str:
    return _COUNTRY_NAMES.get(code, code)


def _first_airport_in_country(codes: list[str], country: str) -> str:
    for code in codes:
        if _airport_country(code) == country:
            return code
    return codes[0]


def _ordered_unique(values) -> list:
    ordered = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return ordered


def _append_unique(values: list[str], value: Optional[str]) -> None:
    if value and value not in values:
        values.append(value)


def _join_title_parts(values) -> str:
    parts = [part for part in values if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _airport_title(code: str) -> str:
    details = _AIRPORT_DETAILS.get(code, {})
    city = (details.get("city") or "").strip()
    if city:
        return _clean_place_name(city)

    name = (details.get("name") or "").strip()
    if name:
        for suffix in (
            " International Airport",
            " Intl Airport",
            " Airport",
            " Airfield",
            " Aerodrome",
        ):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return _clean_place_name(name)

    return code


def _clean_place_name(value: str) -> str:
    return " ".join(value.replace("-", " ").split())


def _main_destination(
    segments: list[Segment],
    origin: str,
    final: str,
    home_airport: Optional[str] = None,
) -> Optional[str]:
    longest_stop_code: Optional[str] = None
    longest_stop = timedelta()
    ordered = sorted(segments, key=_segment_sort_key)
    for previous, next_segment in zip(ordered, ordered[1:]):
        gap = _segment_dep_time(next_segment) - _segment_arr_time(previous)
        if gap > longest_stop and previous.arr_airport != origin:
            longest_stop = gap
            longest_stop_code = previous.arr_airport
    if longest_stop_code and longest_stop >= timedelta(hours=12):
        return longest_stop_code

    if final and final != origin and final != home_airport:
        return final

    origin_coords = _AIRPORT_COORDS.get(origin)
    best_code: Optional[str] = None
    best_distance = -1.0
    endpoint_codes: list[str] = []
    for segment in segments:
        endpoint_codes.extend([segment.dep_airport, segment.arr_airport])

    if origin_coords:
        for code in endpoint_codes:
            if code == origin or (home_airport and code == home_airport):
                continue
            coords = _AIRPORT_COORDS.get(code)
            if not coords:
                continue
            distance = _haversine_km(origin_coords[0], origin_coords[1], coords[0], coords[1])
            if distance > best_distance:
                best_code = code
                best_distance = distance
    if best_code:
        return best_code

    for code in endpoint_codes[1:-1]:
        if code not in {origin, final}:
            return code
    return best_code


def _airports_are_near(a: str, b: str, max_km: float = 150.0) -> bool:
    if a == b:
        return True
    a_coords = _AIRPORT_COORDS.get(a)
    b_coords = _AIRPORT_COORDS.get(b)
    if not a_coords or not b_coords:
        return False
    return _haversine_km(a_coords[0], a_coords[1], b_coords[0], b_coords[1]) <= max_km


def _group_into_trips(flights: list) -> list[list]:
    """Group flights by PNR (preferred) or 48-hour departure proximity."""
    pnr_groups: dict[str, list] = {}
    no_pnr: list = []

    for f in flights:
        pnr = _normalize_pnr(f.pnr)
        if pnr:
            pnr_groups.setdefault(pnr, []).append(f)
        else:
            no_pnr.append(f)

    return list(pnr_groups.values()) + _group_by_proximity(no_pnr)


def _group_by_proximity(flights: list) -> list[list]:
    """Cluster un-PNR'd flights where dep_time is within 48 h of the previous arr_time."""
    if not flights:
        return []
    groups: list[list] = [[flights[0]]]
    for f in flights[1:]:
        gap = _db_datetime(f.dep_time) - _db_datetime(groups[-1][-1].arr_time)
        if gap <= timedelta(hours=48):
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def _find_or_create_trip(db: Session, user_id: int, flights: list) -> Trip:
    """Return an existing Trip that spans the same time window or create one."""
    start_ts = min(_db_datetime(f.dep_time) for f in flights)
    end_ts = max(_db_datetime(f.arr_time) for f in flights)

    existing = (
        db.query(Trip)
        .filter(Trip.user_id == user_id, Trip.start_ts == start_ts, Trip.end_ts == end_ts)
        .first()
    )
    if existing:
        return existing

    dep = flights[0].dep_airport if flights else ""
    arr = flights[-1].arr_airport if flights else ""
    title = f"{dep} → {arr}" if dep and arr else None

    trip = Trip(user_id=user_id, title=title, start_ts=start_ts, end_ts=end_ts)
    db.add(trip)
    db.flush()
    return trip


def _upsert_segment(db: Session, trip_id: int, user_id: int, flight) -> str:
    """Insert/update a Segment and return inserted, updated, or skipped."""
    from app.models import Trip
    dep_time = _db_datetime(flight.dep_time)
    arr_time = _db_datetime(flight.arr_time)
    flight_number = _normalize_flight_number(flight.flight_number)
    airline = _normalize_airline(flight.airline, flight_number)
    pnr = _normalize_pnr(flight.pnr)

    if arr_time and dep_time and arr_time <= dep_time:
        return "skipped"

    existing = _find_supersedable_segment(db, user_id, flight)
    if existing:
        allow_overwrite = _incoming_is_newer_or_equal(existing, flight)
        if allow_overwrite and _incoming_is_contained_partial_segment(existing, flight):
            if existing.dep_airport == flight.dep_airport and existing.arr_airport != flight.arr_airport:
                existing = None
            else:
                allow_overwrite = False
        if existing:
            _refresh_existing_segment(db, existing, flight, allow_overwrite=allow_overwrite)
            return "updated"

    q = db.query(Segment).join(Trip).filter(
        Trip.user_id == user_id,
        Segment.dep_time == dep_time,
        Segment.dep_airport == flight.dep_airport,
        Segment.arr_airport == flight.arr_airport,
    )
    if airline is not None:
        q = q.filter(Segment.airline == airline)
    else:
        q = q.filter(Segment.airline.is_(None))
    if flight_number is not None:
        q = q.filter(Segment.flight_number == flight_number)
    else:
        q = q.filter(Segment.flight_number.is_(None))

    existing = q.first()
    if existing:
        _refresh_existing_segment(db, existing, flight)
        return "updated"

    existing = _find_unique_trip_flight_segment(
        db,
        trip_id=trip_id,
        dep_time=dep_time,
        airline=airline,
        flight_number=flight_number,
    )
    if existing:
        _refresh_existing_segment(
            db,
            existing,
            flight,
            allow_overwrite=not _segment_has_nonstop_evidence(existing),
        )
        return "updated"

    distance_km, geom = _segment_geometry(db, flight.dep_airport, flight.arr_airport)

    seg = Segment(
        trip_id=trip_id,
        mode="flight",
        dep_airport=flight.dep_airport,
        arr_airport=flight.arr_airport,
        dep_time=dep_time,
        arr_time=arr_time,
        airline=airline,
        flight_number=flight_number,
        pnr=pnr,
        distance_km=distance_km,
        geom=geom,
        meta_json=_segment_meta(flight),
    )
    enrich_segment(seg, include_weather=False)
    db.add(seg)
    db.flush()
    return "inserted"


def _find_unique_trip_flight_segment(
    db: Session,
    *,
    trip_id: int,
    dep_time,
    airline: Optional[str],
    flight_number: Optional[str],
) -> Optional[Segment]:
    if not dep_time:
        return None
    q = db.query(Segment).filter(Segment.trip_id == trip_id, Segment.dep_time == dep_time)
    if airline is not None:
        q = q.filter(Segment.airline == airline)
    else:
        q = q.filter(Segment.airline.is_(None))
    if flight_number is not None:
        q = q.filter(Segment.flight_number == flight_number)
    else:
        q = q.filter(Segment.flight_number.is_(None))
    return q.first()


def _find_supersedable_segment(db: Session, user_id: int, flight) -> Optional[Segment]:
    pnr = _normalize_pnr(flight.pnr)
    if not pnr:
        return None
    from app.models import Trip

    q = db.query(Segment).join(Trip).filter(Trip.user_id == user_id, Segment.pnr == pnr)
    candidates = q.all()
    if not candidates:
        return None

    flight_number = _normalize_flight_number(flight.flight_number)
    if flight_number:
        for segment in candidates:
            if _normalize_flight_number(segment.flight_number) == flight_number:
                return segment

    route_matches = [
        segment
        for segment in candidates
        if segment.dep_airport == flight.dep_airport and segment.arr_airport == flight.arr_airport
    ]
    if route_matches:
        incoming_dep = _db_datetime(flight.dep_time)
        return min(route_matches, key=lambda segment: abs(_db_datetime(segment.dep_time) - incoming_dep))

    return None


def _incoming_is_newer_or_equal(segment: Segment, flight) -> bool:
    incoming = _db_datetime(getattr(flight, "source_received_at", None))
    current = _segment_source_received_at(segment)
    if not incoming or not current:
        return True
    return incoming >= current


def _incoming_is_contained_partial_segment(segment: Segment, flight) -> bool:
    """Preserve a richer through-flight when a newer email only shows a stopover leg."""
    if _normalize_flight_number(segment.flight_number) != _normalize_flight_number(flight.flight_number):
        return False
    if _normalize_pnr(segment.pnr) != _normalize_pnr(flight.pnr):
        return False

    incoming_dep = _db_datetime(flight.dep_time)
    incoming_arr = _db_datetime(flight.arr_time)
    if not incoming_dep or not incoming_arr:
        return False
    segment_dep = _db_datetime(segment.dep_time)
    segment_arr = _db_datetime(segment.arr_time)
    existing_duration = segment_arr - segment_dep
    incoming_duration = incoming_arr - incoming_dep
    if incoming_duration >= existing_duration:
        return False

    shares_arrival = segment.arr_airport == flight.arr_airport
    shares_departure = segment.dep_airport == flight.dep_airport
    route_changed = (
        segment.dep_airport != flight.dep_airport
        or segment.arr_airport != flight.arr_airport
    )
    if not route_changed or not (shares_arrival or shares_departure):
        return False

    if incoming_dep >= segment_dep and incoming_arr <= segment_arr:
        return True
    if shares_arrival and incoming_dep > segment_dep + timedelta(hours=2):
        return True
    if shares_departure and incoming_arr < segment_arr - timedelta(hours=2):
        return True
    return False


def _segment_source_received_at(segment: Segment):
    value = (segment.meta_json or {}).get("source_received_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _refresh_existing_segment(db: Session, segment: Segment, flight, *, allow_overwrite: bool = False) -> None:
    incoming_pnr = _normalize_pnr(flight.pnr)
    if incoming_pnr and not segment.pnr:
        segment.pnr = incoming_pnr
    elif incoming_pnr and segment.pnr and incoming_pnr != _normalize_pnr(segment.pnr):
        _add_pnr_alias(segment, incoming_pnr, reason="matched_existing_segment")
    for alias in getattr(flight, "pnr_aliases", []) or []:
        _add_pnr_alias(segment, alias, reason="source_message_alias")
    incoming_flight_number = _normalize_flight_number(flight.flight_number)
    incoming_airline = _normalize_airline(flight.airline, incoming_flight_number)
    dep_time = _db_datetime(flight.dep_time)
    arr_time = _db_datetime(flight.arr_time)
    route_changed = False
    if allow_overwrite and flight.dep_airport and flight.dep_airport != segment.dep_airport:
        segment.dep_airport = flight.dep_airport
        route_changed = True
    if allow_overwrite and flight.arr_airport and flight.arr_airport != segment.arr_airport:
        segment.arr_airport = flight.arr_airport
        route_changed = True
    segment_dep = _db_datetime(segment.dep_time)
    segment_arr = _db_datetime(segment.arr_time)
    if allow_overwrite and dep_time and dep_time != segment_dep:
        segment.dep_time = dep_time
    if (
        arr_time
        and arr_time != segment_arr
        and (
            allow_overwrite
            or not segment_arr
            or (segment_arr <= segment_dep and arr_time > dep_time)
        )
    ):
        segment.arr_time = arr_time
    if incoming_airline and (allow_overwrite or not segment.airline):
        segment.airline = incoming_airline
    if incoming_flight_number and (allow_overwrite or not segment.flight_number):
        segment.flight_number = incoming_flight_number
    if route_changed:
        segment.distance_km, segment.geom = _segment_geometry(db, segment.dep_airport, segment.arr_airport)
    meta = dict(segment.meta_json or {})
    if flight.source:
        meta["source"] = flight.source
    if getattr(flight, "confidence", None) is not None:
        meta["confidence"] = flight.confidence
    if getattr(flight, "source_received_at", None) is not None:
        meta["source_received_at"] = flight.source_received_at.isoformat()
    if getattr(flight, "nonstop", False):
        meta["nonstop"] = True
    segment.meta_json = meta
    for alias in getattr(flight, "pnr_aliases", []) or []:
        _add_pnr_alias(segment, alias, reason="source_message_alias")
    enrich_segment(segment, include_weather=False)


def _db_datetime(value):
    if value is not None and getattr(value, "tzinfo", None) is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _normalize_flight_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = "".join(str(value).upper().split())
    if len(normalized) < 3:
        return normalized
    prefix = normalized[:2]
    suffix = normalized[2:]
    if prefix.isalpha() and suffix:
        trimmed = suffix.lstrip("0") or "0"
        return f"{prefix}{trimmed}"
    return normalized


_INVALID_PNR_VALUES = {
    "ABOUT",
    "AGENT",
    "BOARDING",
    "BOOKING",
    "CHECKIN",
    "DETAILS",
    "FLIGHT",
    "FORYOUR",
    "MANAGED",
    "ONLINE",
    "PASSENGER",
    "PRINT",
    "RECEIPT",
    "RESERVATION",
    "TICKET",
    "TRAVEL",
    "WITHIN",
}


def _normalize_pnr(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = "".join(str(value).upper().split())
    if normalized in _INVALID_PNR_VALUES:
        return None
    if not (5 <= len(normalized) <= 8):
        return None
    if normalized.isalpha() and len(normalized) > 6:
        return None
    return normalized


def _normalize_airline(value: Optional[str], flight_number: Optional[str] = None) -> Optional[str]:
    if value:
        return str(value).upper().strip()
    if flight_number and len(flight_number) >= 2 and flight_number[:2].isalpha():
        return flight_number[:2]
    return None


def _segment_geometry(db: Optional[Session], dep_airport: str, arr_airport: str) -> tuple[Optional[float], object]:
    distance_km: Optional[float] = None
    geom = None
    dep_c = _AIRPORT_COORDS.get(dep_airport)
    arr_c = _AIRPORT_COORDS.get(arr_airport)

    if not dep_c:
        import logging
        logging.getLogger(__name__).warning("Missing backend coordinates for departure airport: %s", dep_airport)
    if not arr_c:
        import logging
        logging.getLogger(__name__).warning("Missing backend coordinates for arrival airport: %s", arr_airport)
    if dep_c and arr_c:
        distance_km = _haversine_km(dep_c[0], dep_c[1], arr_c[0], arr_c[1])
        wkt = _densified_linestring(dep_c[0], dep_c[1], arr_c[0], arr_c[1])
        geom = wkt
        if db is not None and getattr(db.bind, 'dialect', None) and db.bind.dialect.name == 'postgresql':
            try:
                from geoalchemy2.elements import WKTElement
                geom = WKTElement(wkt, srid=4326)
            except Exception:
                pass
    return distance_km, geom


def _segment_meta(flight) -> dict:
    meta = {"source": flight.source}
    if getattr(flight, "confidence", None) is not None:
        meta["confidence"] = flight.confidence
    aircraft = getattr(flight, "aircraft", None)
    if aircraft:
        meta["enrichment"] = {"aircraft": aircraft}
    if getattr(flight, "source_received_at", None) is not None:
        meta["source_received_at"] = flight.source_received_at.isoformat()
    if getattr(flight, "nonstop", False):
        meta["nonstop"] = True
    aliases = []
    for alias in getattr(flight, "pnr_aliases", []) or []:
        normalized = _normalize_pnr(alias)
        if normalized and normalized != _normalize_pnr(getattr(flight, "pnr", None)) and normalized not in aliases:
            aliases.append(normalized)
    if aliases:
        meta["pnr_aliases"] = aliases
        for alias in aliases:
            _add_booking_relationship_to_meta(
                meta,
                {"type": "pnr_alias", "pnr": alias, "reason": "source_message_alias"},
            )
    return meta
