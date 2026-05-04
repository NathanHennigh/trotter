"""Aircraft enrichment provider chain.

The public app should read the normalized output in Segment.meta_json and stay
agnostic about whether it came from email parsing, AeroDataBox, FAA, or a later
premium provider.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from ..models import Segment

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = float(os.getenv("TROTTER_ENRICHMENT_HTTP_TIMEOUT", "8"))
AERODATABOX_ENABLED = os.getenv("AERODATABOX_ENABLED", "true").lower() not in {"0", "false", "no"}
AERODATABOX_NEGATIVE_CACHE_DAYS = int(os.getenv("AERODATABOX_NEGATIVE_CACHE_DAYS", "90"))
AERODATABOX_PROVIDER_ORDER = [
    provider.strip().lower()
    for provider in os.getenv("AERODATABOX_PROVIDER_ORDER", "rapidapi,apimarket").split(",")
    if provider.strip()
]

FAA_REGISTRY_URL = os.getenv(
    "FAA_REGISTRY_URL",
    "https://registry.faa.gov/database/ReleasableAircraft.zip",
)
FAA_REGISTRY_ENABLED = os.getenv("FAA_REGISTRY_ENABLED", "true").lower() not in {"0", "false", "no"}

_N_NUMBER_RE = re.compile(r"\bN[0-9]{1,5}[A-Z]{0,2}\b", re.IGNORECASE)
_ICAO24_RE = re.compile(r"\b[0-9A-F]{6}\b", re.IGNORECASE)
_EQUIPMENT_RE = re.compile(
    r"""
    \b(?:
        aircraft|equipment|equipment\s+type|aircraft\s+type|plane|operated\s+by
    )\b
    [:\s-]{0,12}
    (?P<value>
        (?:Airbus|Boeing|Embraer|Bombardier|De\s*Havilland|ATR|Cessna|CRJ|ERJ|A[0-9]{3}|B[0-9]{3}|7[0-9]{2})
        [A-Za-z0-9 .\-]{0,40}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_LAST_AERODATABOX_CALL_AT: dict[str, float] = {}


@dataclass(frozen=True)
class AeroDataBoxProvider:
    name: str
    base_url: str
    headers: dict[str, str]
    min_interval_seconds: float


@dataclass
class AircraftInfo:
    model: Optional[str] = None
    model_code: Optional[str] = None
    equipment_code: Optional[str] = None
    registration: Optional[str] = None
    icao24: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None
    source: str = "unknown"
    confidence: str = "low"
    looked_up_at: Optional[str] = None
    provider_payload: Optional[dict] = None

    def compact(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value not in (None, "", {})}


def enrich_aircraft(
    segment: Segment,
    existing: Optional[dict] = None,
    *,
    provider_flight: Optional[dict] = None,
    allow_provider_lookup: bool = True,
    allow_faa_lookup: bool = True,
) -> tuple[Optional[dict], bool]:
    """Run the provider chain and return normalized aircraft metadata."""
    current = dict(existing or {})
    result = _from_existing_meta(current)

    if not _has_useful_aircraft_data(result):
        if provider_flight:
            result = _aircraft_from_aerodatabox_flight(provider_flight) or result
        elif allow_provider_lookup:
            result = _from_aerodatabox(segment) or result

    if allow_faa_lookup and result and result.registration:
        faa = lookup_faa_registration(result.registration)
        if faa:
            result = _merge_aircraft(result, faa)

    if not result or not _has_useful_aircraft_data(result):
        return (current or None), False

    normalized = result.compact()
    changed = normalized != current
    return normalized, changed


def enrich_schedule(
    segment: Segment,
    existing: Optional[dict] = None,
    *,
    provider_flight: Optional[dict] = None,
    apply_to_segment: bool = True,
) -> tuple[Optional[dict], bool]:
    """Normalize provider schedule data and optionally repair weak segment times.

    Email parsing remains the primary source. Provider schedule data is applied
    only when the route matches and current times are missing, impossible, or
    clearly low-confidence.
    """
    current = dict(existing or {})
    if not provider_flight:
        return (current or None), False

    schedule = _schedule_from_aerodatabox_flight(segment, provider_flight)
    if not schedule:
        return (current or None), False

    changed = schedule != current
    applied = False
    dep_dt = _parse_provider_utc((schedule.get("departure") or {}).get("best_utc"))
    arr_dt = _parse_provider_utc((schedule.get("arrival") or {}).get("best_utc"))
    if apply_to_segment and dep_dt and arr_dt and _should_apply_provider_times(segment, dep_dt, arr_dt):
        schedule["previous_times"] = {
            "dep_time": _datetime_iso(segment.dep_time),
            "arr_time": _datetime_iso(segment.arr_time),
        }
        segment.dep_time = dep_dt
        segment.arr_time = arr_dt
        applied = True
        changed = True

    schedule["applied_to_segment"] = applied
    if schedule != current:
        changed = True
    return schedule, changed


def extract_email_aircraft_hint(text: str) -> Optional[dict]:
    """Best-effort generic extraction for aircraft hints in future parser paths."""
    if not text:
        return None
    registration_match = _N_NUMBER_RE.search(text)
    equipment_match = _EQUIPMENT_RE.search(text)
    icao24_match = _ICAO24_RE.search(text)
    if not any([registration_match, equipment_match, icao24_match]):
        return None

    info = AircraftInfo(
        registration=normalize_registration(registration_match.group(0)) if registration_match else None,
        equipment_code=_clean_equipment(equipment_match.group("value")) if equipment_match else None,
        icao24=icao24_match.group(0).upper() if icao24_match else None,
        source="email",
        confidence="medium",
        looked_up_at=_now_iso(),
    )
    if info.equipment_code and _looks_like_model(info.equipment_code):
        info.model = info.equipment_code
    return info.compact()


def lookup_faa_registration(registration: str) -> Optional[AircraftInfo]:
    """Resolve a U.S. N-number to FAA make/model data when available."""
    if not FAA_REGISTRY_ENABLED:
        return None
    n_number = normalize_registration(registration)
    if not n_number or not n_number.startswith("N"):
        return None
    rows = _load_faa_rows()
    if not rows:
        return None
    master, acft_ref = rows
    master_row = master.get(n_number[1:])
    if not master_row:
        return None
    model_code = _row_value(master_row, "MFR MDL CODE", "MFR_MDL_CODE", "MFR MDL")
    ref_row = acft_ref.get(model_code or "")
    manufacturer = _row_value(ref_row, "MFR", "MANUFACTURER") if ref_row else None
    model = _row_value(ref_row, "MODEL") if ref_row else None
    return AircraftInfo(
        model=_join_model(manufacturer, model),
        model_code=model_code,
        registration=n_number,
        manufacturer=manufacturer,
        serial_number=_row_value(master_row, "SERIAL NUMBER", "SERIAL_NUMBER"),
        source="faa_registry",
        confidence="high",
        looked_up_at=_now_iso(),
    )


def aerodatabox_lookup_key(segment: Segment) -> Optional[str]:
    flight_number = _normalize_flight_number(segment.flight_number or "", segment.airline)
    if not flight_number:
        return None
    return "|".join(
        [
            flight_number,
            segment.dep_time.date().isoformat(),
            segment.dep_airport.upper(),
            segment.arr_airport.upper(),
        ]
    )


def has_aerodatabox_credentials() -> bool:
    return bool(_aerodatabox_providers())


def should_lookup_provider_flight(segment: Segment, enrichment: Optional[dict]) -> bool:
    """Return True only when a paid/limited provider call can add missing data."""
    if not AERODATABOX_ENABLED or not has_aerodatabox_credentials() or not segment.flight_number:
        return False

    lookup_key = aerodatabox_lookup_key(segment)
    if not lookup_key:
        return False

    enrichment = enrichment or {}
    prior_lookup = enrichment.get("flight_detail_lookup") or {}
    if prior_lookup.get("lookup_key") == lookup_key and not _lookup_cache_expired(prior_lookup):
        if prior_lookup.get("found") is False:
            return False
        if _schedule_meta_is_complete(enrichment.get("schedule"), segment) or prior_lookup.get("found") is True:
            return False

    needs_schedule = (
        not _schedule_meta_is_complete(enrichment.get("schedule"), segment)
        and _segment_times_need_provider(segment)
    )
    needs_aircraft = not _aircraft_meta_is_useful(enrichment.get("aircraft"))
    return needs_schedule or needs_aircraft


def flight_detail_lookup_meta(segment: Segment, provider_flight: Optional[dict]) -> dict:
    return {
        "provider": "aerodatabox",
        "provider_route": provider_flight.get("_trotter_provider") if provider_flight else None,
        "lookup_key": aerodatabox_lookup_key(segment),
        "found": bool(provider_flight),
        "looked_up_at": _now_iso(),
        "negative_cache_days": AERODATABOX_NEGATIVE_CACHE_DAYS,
    }


def lookup_aerodatabox_flight(segment: Segment) -> Optional[dict]:
    if not AERODATABOX_ENABLED or not segment.flight_number:
        return None
    flight_number = _normalize_flight_number(segment.flight_number, segment.airline)
    if not flight_number:
        return None

    date_local = segment.dep_time.date().isoformat()
    params = {
        "dateLocalRole": "Both",
        "withAircraftImage": "false",
        "withLocation": "false",
        # AeroDataBox marks flight-plan data as a higher-cost add-on for this endpoint.
        "withFlightPlan": "false",
    }

    for provider in _aerodatabox_providers():
        url = f"{provider.base_url}/flights/number/{flight_number}/{date_local}"
        try:
            _rate_limit_provider(provider)
            with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, headers=provider.headers) as client:
                response = client.get(url, params=params)
                if response.status_code == 204:
                    return None
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("AeroDataBox %s lookup skipped for %s: %s", provider.name, flight_number, exc)
            continue

        flight = _select_aerodatabox_flight(payload, segment)
        if flight:
            selected = dict(flight)
            selected["_trotter_provider"] = provider.name
            return selected

    return None


def _from_existing_meta(meta: dict) -> Optional[AircraftInfo]:
    if not meta:
        return None
    equipment = meta.get("equipment_code")
    return AircraftInfo(
        model=meta.get("model") or (equipment if equipment and _looks_like_model(equipment) else None),
        model_code=meta.get("model_code"),
        equipment_code=equipment,
        registration=normalize_registration(meta.get("registration")),
        icao24=(meta.get("icao24") or "").upper() or None,
        manufacturer=meta.get("manufacturer"),
        serial_number=meta.get("serial_number"),
        source=meta.get("source") or "existing",
        confidence=meta.get("confidence") or "low",
        looked_up_at=meta.get("looked_up_at"),
        provider_payload=meta.get("provider_payload"),
    )


def _from_aerodatabox(segment: Segment) -> Optional[AircraftInfo]:
    flight = lookup_aerodatabox_flight(segment)
    return _aircraft_from_aerodatabox_flight(flight) if flight else None


def _aircraft_from_aerodatabox_flight(flight: dict) -> Optional[AircraftInfo]:
    aircraft = flight.get("aircraft") or {}
    if not aircraft:
        return None
    return AircraftInfo(
        model=aircraft.get("model") or aircraft.get("typeName"),
        model_code=aircraft.get("modelCode") or aircraft.get("icaoCode"),
        equipment_code=aircraft.get("iataCodeShort") or aircraft.get("iataType") or aircraft.get("icaoCode"),
        registration=normalize_registration(aircraft.get("reg")),
        icao24=(aircraft.get("hexIcao") or "").upper() or None,
        manufacturer=None,
        source="aerodatabox",
        confidence="medium",
        looked_up_at=_now_iso(),
        provider_payload=_summarize_aerodatabox_payload(flight),
    )


def _schedule_from_aerodatabox_flight(segment: Segment, flight: dict) -> Optional[dict]:
    departure = flight.get("departure") or {}
    arrival = flight.get("arrival") or {}
    dep_code = _airport_code(departure)
    arr_code = _airport_code(arrival)
    segment_dep = segment.dep_airport.upper()
    segment_arr = segment.arr_airport.upper()
    dep_matches = not dep_code or dep_code == segment_dep
    arr_matches = not arr_code or arr_code == segment_arr
    if not dep_matches or not arr_matches:
        return None

    dep_times = _section_times(departure)
    arr_times = _section_times(arrival)
    if not dep_times.get("best_utc") and not arr_times.get("best_utc"):
        return None

    route_confidence = "high" if dep_code == segment_dep and arr_code == segment_arr else "medium"
    schedule = {
        "source": "aerodatabox",
        "confidence": route_confidence,
        "looked_up_at": _now_iso(),
        "status": flight.get("status"),
        "departure": {
            "airport": dep_code or segment_dep,
            **dep_times,
        },
        "arrival": {
            "airport": arr_code or segment_arr,
            **arr_times,
        },
        "provider_payload": _summarize_schedule_payload(flight),
    }
    return _compact_nested(schedule)


def _section_times(section: dict) -> dict:
    values = {
        "scheduled_utc": _provider_time(section, "scheduledTime"),
        "revised_utc": _provider_time(section, "revisedTime"),
        "predicted_utc": _provider_time(section, "predictedTime"),
        "actual_utc": _provider_time(section, "actualTime"),
        "runway_utc": _provider_time(section, "runwayTime"),
    }
    for key in ("actual_utc", "runway_utc", "revised_utc", "predicted_utc", "scheduled_utc"):
        if values.get(key):
            values["best_utc"] = values[key]
            values["best_kind"] = key.removesuffix("_utc")
            break
    return {key: value for key, value in values.items() if value}


def _provider_time(section: dict, key: str) -> Optional[str]:
    value = section.get(key)
    if isinstance(value, dict):
        raw = value.get("utc") or value.get("local")
    else:
        raw = value
    parsed = _parse_provider_utc(raw)
    return parsed.replace(tzinfo=timezone.utc).isoformat() if parsed else None


def _airport_code(section: dict) -> Optional[str]:
    airport = section.get("airport") or {}
    value = (
        airport.get("iata")
        or airport.get("iataCode")
        or section.get("iata")
        or section.get("iataCode")
    )
    return str(value).upper() if value else None


def _should_apply_provider_times(segment: Segment, dep_time: datetime, arr_time: datetime) -> bool:
    provider_duration = arr_time - dep_time
    if provider_duration < timedelta(minutes=20) or provider_duration > timedelta(hours=26):
        return False

    current_dep = _as_utc_naive(segment.dep_time)
    current_arr = _as_utc_naive(segment.arr_time)
    if not current_dep or not current_arr:
        return True

    current_duration = current_arr - current_dep
    if current_duration <= timedelta(minutes=0) or current_duration > timedelta(hours=30):
        return True
    if current_duration < timedelta(minutes=20):
        return True

    meta = segment.meta_json or {}
    confidence = meta.get("confidence")
    try:
        confidence_value = int(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_value = None

    dep_delta = abs(dep_time - current_dep)
    arr_delta = abs(arr_time - current_arr)
    duration_delta = abs(provider_duration - current_duration)
    low_confidence = confidence_value is not None and confidence_value <= 45
    medium_confidence = confidence_value is not None and confidence_value <= 70
    if low_confidence and (dep_delta > timedelta(minutes=15) or arr_delta > timedelta(minutes=15)):
        return True
    if medium_confidence and duration_delta > timedelta(hours=2):
        return True
    return False


def _segment_times_need_provider(segment: Segment) -> bool:
    current_dep = _as_utc_naive(segment.dep_time)
    current_arr = _as_utc_naive(segment.arr_time)
    if not current_dep or not current_arr:
        return True
    current_duration = current_arr - current_dep
    if current_duration <= timedelta(minutes=0):
        return True
    if current_duration < timedelta(minutes=20) or current_duration > timedelta(hours=30):
        return True
    meta = segment.meta_json or {}
    try:
        confidence = int(meta.get("confidence")) if meta.get("confidence") is not None else None
    except (TypeError, ValueError):
        confidence = None
    return confidence is not None and confidence <= 45


def _aircraft_meta_is_useful(meta: Optional[dict]) -> bool:
    return bool(
        meta
        and (
            meta.get("model")
            or meta.get("equipment_code")
            or meta.get("registration")
            or meta.get("icao24")
        )
    )


def _schedule_meta_is_complete(meta: Optional[dict], segment: Segment) -> bool:
    if not meta:
        return False
    departure = meta.get("departure") or {}
    arrival = meta.get("arrival") or {}
    dep_airport = (departure.get("airport") or "").upper()
    arr_airport = (arrival.get("airport") or "").upper()
    if dep_airport and dep_airport != segment.dep_airport.upper():
        return False
    if arr_airport and arr_airport != segment.arr_airport.upper():
        return False
    return bool(departure.get("best_utc") and arrival.get("best_utc"))


def _lookup_cache_expired(meta: dict) -> bool:
    looked_up_at = _parse_provider_utc(meta.get("looked_up_at"))
    if not looked_up_at:
        return True
    if meta.get("found") is True:
        return False
    ttl_days = meta.get("negative_cache_days") or AERODATABOX_NEGATIVE_CACHE_DAYS
    try:
        ttl = int(ttl_days)
    except (TypeError, ValueError):
        ttl = AERODATABOX_NEGATIVE_CACHE_DAYS
    return datetime.now(timezone.utc).replace(tzinfo=None) - looked_up_at > timedelta(days=ttl)


def _select_aerodatabox_flight(payload, segment: Segment) -> Optional[dict]:
    flights = payload if isinstance(payload, list) else [payload]
    candidates = [flight for flight in flights if isinstance(flight, dict)]
    if not candidates:
        return None
    dep = segment.dep_airport.upper()
    arr = segment.arr_airport.upper()

    def score(flight: dict) -> int:
        departure = ((flight.get("departure") or {}).get("airport") or {})
        arrival = ((flight.get("arrival") or {}).get("airport") or {})
        departure_code = (departure.get("iata") or "").upper()
        arrival_code = (arrival.get("iata") or "").upper()
        return int(departure_code == dep) + int(arrival_code == arr)

    return max(candidates, key=score)


def _aerodatabox_providers() -> list[AeroDataBoxProvider]:
    providers = {
        "rapidapi": _rapidapi_provider,
        "apimarket": _apimarket_provider,
    }
    configured: list[AeroDataBoxProvider] = []
    for name in AERODATABOX_PROVIDER_ORDER:
        factory = providers.get(name)
        if not factory:
            continue
        provider = factory()
        if provider:
            configured.append(provider)
    return configured


def _rapidapi_provider() -> Optional[AeroDataBoxProvider]:
    api_key = os.getenv("AERODATABOX_RAPIDAPI_KEY") or os.getenv("AERODATABOX_API_KEY")
    if not api_key:
        return None
    host = os.getenv("AERODATABOX_RAPIDAPI_HOST", "aerodatabox.p.rapidapi.com")
    headers = {
        "Accept": "application/json",
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": host,
    }
    return AeroDataBoxProvider(
        name="rapidapi",
        base_url=os.getenv("AERODATABOX_RAPIDAPI_BASE_URL", "https://aerodatabox.p.rapidapi.com").rstrip("/"),
        headers=headers,
        min_interval_seconds=float(os.getenv("AERODATABOX_RAPIDAPI_MIN_INTERVAL_SECONDS", "0.25")),
    )


def _apimarket_provider() -> Optional[AeroDataBoxProvider]:
    api_key = os.getenv("AERODATABOX_APIMARKET_KEY")
    if not api_key:
        return None
    auth_header = os.getenv("AERODATABOX_APIMARKET_AUTH_HEADER", "x-magicapi-key")
    headers = {
        "Accept": "application/json",
        auth_header: api_key,
    }
    if auth_header != "x-api-market-key":
        headers["x-api-market-key"] = api_key
    return AeroDataBoxProvider(
        name="apimarket",
        base_url=os.getenv(
            "AERODATABOX_APIMARKET_BASE_URL",
            "https://prod.api.market/api/v1/aedbx/aerodatabox",
        ).rstrip("/"),
        headers=headers,
        min_interval_seconds=float(os.getenv("AERODATABOX_APIMARKET_MIN_INTERVAL_SECONDS", "1.05")),
    )


def _rate_limit_provider(provider: AeroDataBoxProvider) -> None:
    interval = max(0.0, provider.min_interval_seconds)
    if interval <= 0:
        return
    now = time.monotonic()
    last = _LAST_AERODATABOX_CALL_AT.get(provider.name)
    if last is not None:
        wait_for = interval - (now - last)
        if wait_for > 0:
            time.sleep(wait_for)
    _LAST_AERODATABOX_CALL_AT[provider.name] = time.monotonic()


def _summarize_aerodatabox_payload(flight: dict) -> dict:
    aircraft = flight.get("aircraft") or {}
    return {
        "number": (flight.get("number") or flight.get("callSign")),
        "status": flight.get("status"),
        "aircraft": {
            key: aircraft.get(key)
            for key in ("reg", "hexIcao", "model", "modelCode", "iataType", "iataCodeShort", "icaoCode")
            if aircraft.get(key)
        },
    }


def _summarize_schedule_payload(flight: dict) -> dict:
    return {
        key: value
        for key, value in {
            "number": flight.get("number") or flight.get("callSign"),
            "status": flight.get("status"),
            "codeshareStatus": flight.get("codeshareStatus"),
        }.items()
        if value
    }


def _merge_aircraft(primary: AircraftInfo, secondary: AircraftInfo) -> AircraftInfo:
    return AircraftInfo(
        model=primary.model or secondary.model,
        model_code=primary.model_code or secondary.model_code,
        equipment_code=primary.equipment_code or secondary.equipment_code,
        registration=primary.registration or secondary.registration,
        icao24=primary.icao24 or secondary.icao24,
        manufacturer=primary.manufacturer or secondary.manufacturer,
        serial_number=primary.serial_number or secondary.serial_number,
        source=f"{primary.source}+{secondary.source}",
        confidence="high" if secondary.source == "faa_registry" else primary.confidence,
        looked_up_at=_now_iso(),
        provider_payload=primary.provider_payload,
    )


def _has_useful_aircraft_data(info: Optional[AircraftInfo]) -> bool:
    return bool(info and (info.model or info.equipment_code or info.registration or info.icao24))


def _normalize_flight_number(flight_number: str, airline: Optional[str]) -> str:
    value = re.sub(r"\s+", "", flight_number or "").upper()
    if value and re.match(r"^[A-Z0-9]{2,3}\d", value):
        return value
    if airline and value and value[0].isdigit():
        return f"{airline.upper()}{value}"
    return value


def _parse_provider_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _datetime_iso(value: Optional[datetime]) -> Optional[str]:
    normalized = _as_utc_naive(value)
    if not normalized:
        return None
    return normalized.replace(tzinfo=timezone.utc).isoformat()


def _compact_nested(value):
    if isinstance(value, dict):
        compact = {}
        for key, item in value.items():
            nested = _compact_nested(item)
            if nested not in (None, "", {}, []):
                compact[key] = nested
        return compact
    if isinstance(value, list):
        return [_compact_nested(item) for item in value if _compact_nested(item) not in (None, "", {}, [])]
    return value


def normalize_registration(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return normalized or None


def _clean_equipment(value: str) -> str:
    return " ".join(value.strip(" .:-").split())


def _looks_like_model(value: str) -> bool:
    return bool(re.search(r"\b(?:Airbus|Boeing|Embraer|Bombardier|ATR|A\d{3}|B\d{3}|7\d{2})\b", value, re.I))


def _load_faa_rows() -> Optional[tuple[dict[str, dict], dict[str, dict]]]:
    path = _faa_zip_path()
    try:
        if not path.exists():
            _download_faa_registry(path)
        with zipfile.ZipFile(path) as archive:
            master = _read_faa_table(archive, "MASTER.txt", key_field="N-NUMBER")
            acft_ref = _read_faa_table(archive, "ACFTREF.txt", key_field="CODE")
        return master, acft_ref
    except Exception as exc:
        logger.info("FAA registry lookup unavailable: %s", exc)
        return None


def _download_faa_registry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Trotter/1.0 aircraft-enrichment"}
    with httpx.Client(timeout=45, headers=headers, follow_redirects=True) as client:
        response = client.get(FAA_REGISTRY_URL)
        response.raise_for_status()
    path.write_bytes(response.content)


def _faa_zip_path() -> Path:
    cache_dir = Path(os.getenv("TROTTER_DATA_CACHE", Path.cwd() / ".cache" / "trotter-data"))
    return cache_dir / "faa-releasable-aircraft.zip"


def _read_faa_table(archive: zipfile.ZipFile, filename: str, *, key_field: str) -> dict[str, dict]:
    member = next((name for name in archive.namelist() if name.upper().endswith(filename.upper())), filename)
    raw = archive.read(member).decode("latin-1", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    rows: dict[str, dict] = {}
    for row in reader:
        normalized = {_normalize_header(key): (value or "").strip() for key, value in row.items() if key}
        key = normalized.get(_normalize_header(key_field), "")
        if key:
            rows[key] = normalized
    return rows


def _row_value(row: Optional[dict], *fields: str) -> Optional[str]:
    if not row:
        return None
    for field in fields:
        value = row.get(_normalize_header(field))
        if value:
            return value.strip()
    return None


def _normalize_header(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def _join_model(manufacturer: Optional[str], model: Optional[str]) -> Optional[str]:
    parts = [part.strip() for part in (manufacturer, model) if part and part.strip()]
    return " ".join(parts) if parts else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
