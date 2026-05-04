"""Segment/trip builder: groups ParsedFlights into DB Trip and Segment records."""

from __future__ import annotations

import math
from collections import Counter
from datetime import timedelta, timezone
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
    if not flights:
        return 0

    sorted_flights = sorted(flights, key=lambda f: f.dep_time)
    trip_groups = _group_into_trips(sorted_flights)

    new_segments = 0
    for group in trip_groups:
        trip = _find_or_create_trip(db, user_id, group)
        for flight in group:
            if _upsert_segment(db, trip.id, user_id, flight):
                new_segments += 1

    rebuild_user_trips(db, user_id)
    return new_segments


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
        ordered = sorted(cluster, key=lambda segment: (segment.dep_time, segment.arr_time, segment.id))
        trip.start_ts = min(segment.dep_time for segment in ordered)
        trip.end_ts = max(segment.arr_time for segment in ordered)
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

def _cluster_saved_segments(segments: list[Segment], home_airport: Optional[str]) -> list[list[Segment]]:
    if not segments:
        return []

    ordered = sorted(segments, key=lambda segment: (segment.dep_time, segment.arr_time, segment.id))
    clusters: list[list[Segment]] = [[ordered[0]]]
    for segment in ordered[1:]:
        current = clusters[-1]
        previous = current[-1]
        gap = segment.dep_time - previous.arr_time
        if _belongs_to_current_trip(current, segment, gap, home_airport):
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
            (segment.dep_airport, segment.arr_airport, segment.dep_time, segment.flight_number),
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
                segment.flight_number,
                segment.pnr,
            ),
            [],
        ).append(segment)
    mark_duplicates(same_flight_groups)

    same_day_groups: dict[tuple[str, str, str, object], list[Segment]] = {}
    for segment in segments:
        same_day_groups.setdefault(
            (
                segment.dep_airport,
                segment.arr_airport,
                segment.airline or "",
                segment.dep_time.date(),
            ),
            [],
        ).append(segment)
    for key, group in same_day_groups.items():
        ordered = sorted(
            [segment for segment in group if segment.id not in delete_ids],
            key=lambda segment: segment.dep_time,
        )
        if len(ordered) <= 1:
            continue
        cluster: list[Segment] = [ordered[0]]
        for segment in ordered[1:]:
            if segment.dep_time - cluster[-1].dep_time <= timedelta(hours=8):
                cluster.append(segment)
                continue
            mark_duplicates({key: cluster})
            cluster = [segment]
        mark_duplicates({key: cluster})

    for segment in segments:
        if segment.id in delete_ids:
            db.delete(segment)
        elif segment.id not in keep_ids:
            keep_ids.add(segment.id)
    if delete_ids:
        db.flush()
    return [segment for segment in segments if segment.id in keep_ids]


def _best_duplicate_segment(duplicates: list[Segment], all_segments: list[Segment]) -> Segment:
    return max(
        duplicates,
        key=lambda segment: (
            _same_pnr_neighbor_count(segment, all_segments),
            bool(segment.meta_json and (segment.meta_json or {}).get("enrichment")),
            bool(segment.pnr),
            bool(segment.distance_km),
            segment.id,
        ),
    )


def _same_pnr_neighbor_count(segment: Segment, all_segments: list[Segment]) -> int:
    if not segment.pnr:
        return 0
    count = 0
    for other in all_segments:
        if other.id == segment.id or other.pnr != segment.pnr:
            continue
        if abs(other.dep_time - segment.dep_time) <= timedelta(days=7):
            count += 1
    return count


def _merge_duplicate_segment(keep: Segment, duplicate: Segment) -> None:
    if duplicate.pnr and not keep.pnr:
        keep.pnr = duplicate.pnr
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


def _belongs_to_current_trip(
    current: list[Segment],
    segment: Segment,
    gap,
    home_airport: Optional[str],
) -> bool:
    if gap < timedelta(hours=-6):
        return False
    previous = current[-1]
    ended_at_home = bool(home_airport and previous.arr_airport == home_airport)
    starts_from_home = bool(home_airport and segment.dep_airport == home_airport)
    if ended_at_home and starts_from_home and gap > timedelta(hours=48):
        return False

    same_booking = bool(segment.pnr and segment.pnr in {item.pnr for item in current if item.pnr})
    if same_booking and gap <= timedelta(days=90):
        return True
    if previous.arr_airport == segment.dep_airport and gap <= _EXTRA_DESTINATION_STOPOVER:
        return True
    if _airports_are_near(previous.arr_airport, segment.dep_airport) and gap <= timedelta(days=21):
        return True
    if gap <= timedelta(hours=36):
        return True

    if len(current) > 1 and not ended_at_home and gap <= timedelta(days=21):
        return True
    return False


def _infer_home_airport(segments: list[Segment]) -> Optional[str]:
    counts: Counter[str] = Counter()
    for segment in segments:
        counts[segment.dep_airport] += 1
        counts[segment.arr_airport] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _select_reusable_trip_id(cluster: list[Segment], used_trip_ids: set[int]) -> Optional[int]:
    counts = Counter(segment.trip_id for segment in cluster if segment.trip_id not in used_trip_ids)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _trip_title_for_segments(segments: list[Segment], home_airport: Optional[str] = None) -> Optional[str]:
    if not segments:
        return None
    ordered = sorted(segments, key=lambda segment: (segment.dep_time, segment.arr_time, segment.id))
    origin = ordered[0].dep_airport
    final = ordered[-1].arr_airport
    title = _smart_trip_title(ordered, origin, final, home_airport=home_airport)
    if title:
        return title
    destination = _main_destination(segments, origin, final)
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
    main_destination = _main_destination(segments, origin, final)
    meaningful: list[str] = []
    ordered = sorted(segments, key=lambda segment: (segment.dep_time, segment.arr_time, segment.id))

    if home_airport and final == home_airport and origin != home_airport and len(ordered) == 1:
        return [origin]

    for index, segment in enumerate(ordered[:-1]):
        code = segment.arr_airport
        if code == origin:
            continue
        next_segment = ordered[index + 1]
        stopover = next_segment.dep_time - segment.arr_time
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
) -> Optional[str]:
    longest_stop_code: Optional[str] = None
    longest_stop = timedelta()
    ordered = sorted(segments, key=lambda segment: (segment.dep_time, segment.arr_time, segment.id))
    for previous, next_segment in zip(ordered, ordered[1:]):
        gap = next_segment.dep_time - previous.arr_time
        if gap > longest_stop and previous.arr_airport != origin:
            longest_stop = gap
            longest_stop_code = previous.arr_airport
    if longest_stop_code and longest_stop >= timedelta(hours=12):
        return longest_stop_code

    origin_coords = _AIRPORT_COORDS.get(origin)
    best_code: Optional[str] = None
    best_distance = -1.0
    endpoint_codes: list[str] = []
    for segment in segments:
        endpoint_codes.extend([segment.dep_airport, segment.arr_airport])

    if origin_coords:
        for code in endpoint_codes:
            if code == origin:
                continue
            coords = _AIRPORT_COORDS.get(code)
            if not coords:
                continue
            distance = _haversine_km(origin_coords[0], origin_coords[1], coords[0], coords[1])
            if distance > best_distance:
                best_code = code
                best_distance = distance
    if best_code and (origin == final or best_code != final):
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
        if f.pnr:
            pnr_groups.setdefault(f.pnr, []).append(f)
        else:
            no_pnr.append(f)

    return list(pnr_groups.values()) + _group_by_proximity(no_pnr)


def _group_by_proximity(flights: list) -> list[list]:
    """Cluster un-PNR'd flights where dep_time is within 48 h of the previous arr_time."""
    if not flights:
        return []
    groups: list[list] = [[flights[0]]]
    for f in flights[1:]:
        gap = f.dep_time - groups[-1][-1].arr_time
        if gap <= timedelta(hours=48):
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def _find_or_create_trip(db: Session, user_id: int, flights: list) -> Trip:
    """Return an existing Trip that spans the same time window or create one."""
    start_ts = min(f.dep_time for f in flights)
    end_ts = max(f.arr_time for f in flights)

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


def _upsert_segment(db: Session, trip_id: int, user_id: int, flight) -> bool:
    """Insert a Segment if one with the same key doesn't already exist for this user. Returns True if inserted."""
    from app.models import Trip
    dep_time = _db_datetime(flight.dep_time)
    arr_time = _db_datetime(flight.arr_time)

    q = db.query(Segment).join(Trip).filter(
        Trip.user_id == user_id,
        Segment.dep_time == dep_time,
        Segment.dep_airport == flight.dep_airport,
        Segment.arr_airport == flight.arr_airport,
    )
    if flight.airline is not None:
        q = q.filter(Segment.airline == flight.airline)
    else:
        q = q.filter(Segment.airline.is_(None))
    if flight.flight_number is not None:
        q = q.filter(Segment.flight_number == flight.flight_number)
    else:
        q = q.filter(Segment.flight_number.is_(None))

    existing = q.first()
    if existing:
        _refresh_existing_segment(existing, flight)
        return False

    # Compute geometry and distance when coordinates are available
    distance_km: Optional[float] = None
    geom = None
    dep_c = _AIRPORT_COORDS.get(flight.dep_airport)
    arr_c = _AIRPORT_COORDS.get(flight.arr_airport)
    
    if not dep_c:
        import logging
        logging.getLogger(__name__).warning("Missing backend coordinates for departure airport: %s", flight.dep_airport)
    if not arr_c:
        import logging
        logging.getLogger(__name__).warning("Missing backend coordinates for arrival airport: %s", flight.arr_airport)
    if dep_c and arr_c:
        distance_km = _haversine_km(dep_c[0], dep_c[1], arr_c[0], arr_c[1])
        wkt = _densified_linestring(dep_c[0], dep_c[1], arr_c[0], arr_c[1])
        geom = wkt
        if getattr(db.bind, 'dialect', None) and db.bind.dialect.name == 'postgresql':
            try:
                from geoalchemy2.elements import WKTElement
                geom = WKTElement(wkt, srid=4326)
            except Exception:
                pass

    seg = Segment(
        trip_id=trip_id,
        mode="flight",
        dep_airport=flight.dep_airport,
        arr_airport=flight.arr_airport,
        dep_time=dep_time,
        arr_time=arr_time,
        airline=flight.airline,
        flight_number=flight.flight_number,
        pnr=flight.pnr,
        distance_km=distance_km,
        geom=geom,
        meta_json=_segment_meta(flight),
    )
    enrich_segment(seg, include_weather=False)
    db.add(seg)
    db.flush()
    return True


def _refresh_existing_segment(segment: Segment, flight) -> None:
    if flight.pnr and not segment.pnr:
        segment.pnr = flight.pnr
    arr_time = _db_datetime(flight.arr_time)
    if arr_time and arr_time != segment.arr_time:
        segment.arr_time = arr_time
    if flight.airline and not segment.airline:
        segment.airline = flight.airline
    if flight.flight_number and not segment.flight_number:
        segment.flight_number = flight.flight_number
    meta = dict(segment.meta_json or {})
    if flight.source:
        meta["source"] = flight.source
    if getattr(flight, "confidence", None) is not None:
        meta["confidence"] = flight.confidence
    segment.meta_json = meta
    enrich_segment(segment, include_weather=False)


def _db_datetime(value):
    if value is not None and getattr(value, "tzinfo", None) is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _segment_meta(flight) -> dict:
    meta = {"source": flight.source}
    if getattr(flight, "confidence", None) is not None:
        meta["confidence"] = flight.confidence
    aircraft = getattr(flight, "aircraft", None)
    if aircraft:
        meta["enrichment"] = {"aircraft": aircraft}
    return meta
