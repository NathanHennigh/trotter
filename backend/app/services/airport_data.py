"""Airport metadata backed by OurAirports, with airportsdata fallback.

The app already parses IATA codes well; this module gives those codes richer,
portable context for passport stats and later trip detail screens.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OURAIRPORTS_BASE_URL = os.getenv(
    "TROTTER_OURAIRPORTS_BASE_URL",
    "https://davidmegginson.github.io/ourairports-data",
).rstrip("/")
OURAIRPORTS_CACHE_DAYS = int(os.getenv("TROTTER_OURAIRPORTS_CACHE_DAYS", "30"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("TROTTER_ENRICHMENT_HTTP_TIMEOUT", "6"))


@dataclass(frozen=True)
class AirportInfo:
    iata_code: str
    icao_code: Optional[str]
    name: str
    city: str
    country_code: str
    country_name: str
    latitude: float
    longitude: float
    timezone: Optional[str]
    source: str

    def to_json(self) -> dict:
        return asdict(self)


_AIRPORTS: Optional[dict[str, AirportInfo]] = None


def get_airport(code: str | None) -> Optional[AirportInfo]:
    """Return metadata for an IATA airport code."""
    if not code:
        return None
    return _load_airports().get(code.strip().upper())


def get_airport_json(code: str | None) -> Optional[dict]:
    airport = get_airport(code)
    return airport.to_json() if airport else None


def _load_airports() -> dict[str, AirportInfo]:
    global _AIRPORTS
    if _AIRPORTS is not None:
        return _AIRPORTS

    airports = _load_ourairports()
    fallback = _load_airportsdata()

    # airportsdata includes timezone and often cleaner ICAO mappings; merge
    # those onto the public OurAirports rows while retaining OurAirports as the
    # canonical open dataset source.
    for code, fallback_info in fallback.items():
        if code not in airports:
            airports[code] = fallback_info
            continue
        current = airports[code]
        airports[code] = AirportInfo(
            iata_code=current.iata_code,
            icao_code=current.icao_code or fallback_info.icao_code,
            name=current.name or fallback_info.name,
            city=current.city or fallback_info.city,
            country_code=current.country_code or fallback_info.country_code,
            country_name=current.country_name or fallback_info.country_name,
            latitude=current.latitude,
            longitude=current.longitude,
            timezone=current.timezone or fallback_info.timezone,
            source="ourairports+airportsdata",
        )

    _AIRPORTS = airports or fallback
    return _AIRPORTS


def _load_ourairports() -> dict[str, AirportInfo]:
    try:
        airports_csv = _cached_download("airports.csv")
        countries_csv = _cached_download("countries.csv")
        country_names = {
            row["code"].strip().upper(): row["name"].strip()
            for row in csv.DictReader(io.StringIO(countries_csv))
            if row.get("code")
        }
        airports: dict[str, AirportInfo] = {}
        for row in csv.DictReader(io.StringIO(airports_csv)):
            iata = (row.get("iata_code") or "").strip().upper()
            if not iata:
                continue
            try:
                lat = float(row["latitude_deg"])
                lon = float(row["longitude_deg"])
            except (KeyError, TypeError, ValueError):
                continue
            country_code = (row.get("iso_country") or "").strip().upper()
            airports[iata] = AirportInfo(
                iata_code=iata,
                icao_code=(row.get("ident") or "").strip().upper() or None,
                name=(row.get("name") or "").strip(),
                city=(row.get("municipality") or "").strip(),
                country_code=country_code,
                country_name=country_names.get(country_code, country_code),
                latitude=lat,
                longitude=lon,
                timezone=None,
                source="ourairports",
            )
        return airports
    except Exception as exc:
        logger.warning("OurAirports metadata unavailable, falling back to airportsdata: %s", exc)
        return {}


def _load_airportsdata() -> dict[str, AirportInfo]:
    try:
        import airportsdata

        rows = airportsdata.load("IATA")
    except Exception as exc:
        logger.warning("airportsdata fallback unavailable: %s", exc)
        return {}

    airports: dict[str, AirportInfo] = {}
    for code, row in rows.items():
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        country_code = str(row.get("country") or "").strip().upper()
        airports[code.upper()] = AirportInfo(
            iata_code=code.upper(),
            icao_code=str(row.get("icao") or "").strip().upper() or None,
            name=str(row.get("name") or "").strip(),
            city=str(row.get("city") or "").strip(),
            country_code=country_code,
            country_name=country_code,
            latitude=lat,
            longitude=lon,
            timezone=str(row.get("tz") or "").strip() or None,
            source="airportsdata",
        )
    return airports


def _cached_download(filename: str) -> str:
    cache_dir = Path(os.getenv("TROTTER_DATA_CACHE", Path.cwd() / ".cache" / "trotter-data"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / filename
    if _cache_is_fresh(path):
        return path.read_text(encoding="utf-8")

    url = f"{OURAIRPORTS_BASE_URL}/{filename}"
    headers = {"User-Agent": "Trotter/1.0 airport-enrichment"}
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, headers=headers, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    path.write_text(response.text, encoding="utf-8")
    return response.text


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return datetime.now(timezone.utc) - updated_at < timedelta(days=OURAIRPORTS_CACHE_DAYS)
