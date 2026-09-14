"""Conservative, asynchronous resolution of a saved place; no database writes.

Geoapify data can be cached and used on Leaflet/OSM. Show OpenStreetMap
attribution wherever this data is displayed, plus Geoapify attribution on the
free plan; retain any additional datasource attribution required by the plan.
https://www.geoapify.com/terms-and-conditions/
https://apidocs.geoapify.com/docs/geocoding/

Only GEOAPIFY_API_KEY from the server environment is used. Google Maps URLs
point to our resolved coordinates, not to Google Places content or a guaranteed
Google business listing. Never log provider request URLs (they contain a key).
"""

from __future__ import annotations

import math
import logging
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field


class Candidate(BaseModel):
    id: str
    name: str
    address: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    google_maps_url: str
    provider: Literal["geoapify"] = "geoapify"
    city: str | None = None
    country: str | None = None
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class SearchResult(BaseModel):
    status: Literal["resolved", "needs_review", "not_found", "blocked"]
    candidates: list[Candidate] = Field(default_factory=list, max_length=5)
    message: str | None = None


class RetryableDreamPlaceLookupError(LookupError):
    """Temporary provider failure; the durable job may retry with backoff."""


_URL = "https://api.geoapify.com/v1/geocode/search"


class _GeoapifyKeyFilter(logging.Filter):
    """httpx INFO logs include query URLs even when our own errors are safe."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "api.geoapify.com/" in message:
            record.msg = re.sub(r"(?i)([?&]apiKey=)[^&\s\"']+", r"\1[redacted]", message)
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_GeoapifyKeyFilter())
_GENERIC = {
    "cafe",
    "coffee",
    "coffee shop",
    "restaurant",
    "restaurants",
    "hotel",
    "hotels",
    "bar",
    "beach",
    "museum",
    "park",
    "place",
    "unknown",
    "not specified",
    "n a",
}
# A single search result does not establish the intended branch of these names.
_CHAINS = {
    "starbucks",
    "mcdonalds",
    "mcdonald s",
    "hilton",
    "marriott",
    "hyatt",
    "sheraton",
    "holiday inn",
    "four seasons",
    "ritz carlton",
    "the ritz carlton",
    "dunkin",
    "subway",
    "burger king",
    "kfc",
    "pret a manger",
    "costa coffee",
    "blue bottle coffee",
    "% arabica",
    "arabica",
}
_COUNTRY_ALIASES = {
    "usa": "us",
    "united states": "us",
    "united states of america": "us",
    "uk": "gb",
    "great britain": "gb",
    "united kingdom": "gb",
    "united arab emirates": "ae",
    "uae": "ae",
    "south korea": "kr",
    "republic of korea": "kr",
    "turkey": "tr",
    "turkiye": "tr",
    "czech republic": "cz",
    "czechia": "cz",
    "vietnam": "vn",
    "viet nam": "vn",
    "taiwan": "tw",
    "taiwan province of china": "tw",
    "russia": "ru",
    "russian federation": "ru",
    "laos": "la",
    "lao peoples democratic republic": "la",
}
_CATEGORY_PREFIXES = {
    "cafe": ("catering.cafe",),
    "coffee": ("catering.cafe",),
    "coffee shop": ("catering.cafe",),
    "restaurant": ("catering.restaurant",),
    "food": ("catering",),
    "bar": ("catering.bar", "catering.pub"),
    "hotel": ("accommodation",),
    "stay": ("accommodation",),
    "museum": ("entertainment.museum",),
    "beach": ("beach", "natural.beach"),
    "shopping": ("commercial",),
    "attraction": ("tourism", "heritage", "entertainment"),
    "activity": ("activity", "entertainment", "sport", "leisure"),
    "nature": ("natural", "national_park", "leisure"),
    "event": ("activity.events_venue", "entertainment"),
}
_AREA_MATCHES = {
    "match_by_street",
    "match_by_postcode",
    "match_by_city_or_disrict",
    "match_by_city_or_district",
    "match_by_country_or_state",
}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normal(value: object) -> str:
    text = unicodedata.normalize("NFKD", _text(value).casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).split())


def _country(value: object) -> str:
    normalized = _normal(value)
    return _COUNTRY_ALIASES.get(normalized, normalized)


def _locality(value: object, country: str) -> str:
    normalized = _normal(value)
    # Verified provider naming. Do not strip 'Greater' globally or merge
    # cities in other countries simply because their names contain London.
    if _country(country) == "gb" and normalized == "greater london":
        return "london"
    return normalized


def _name_score(wanted: str, actual: str) -> float:
    a, b = _normal(wanted), _normal(actual)
    if not a or not b:
        return 0
    if a == b:
        return 1
    left, right = set(a.split()), set(b.split())
    overlap = len(left & right) / max(len(left | right), 1)
    return 0.6 * SequenceMatcher(None, a, b).ratio() + 0.4 * overlap


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _candidate(
    feature: object, name: str, city: str, country: str, region: str, category: str
) -> tuple[Candidate, bool] | None:
    if not isinstance(feature, dict):
        return None
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, dict) or not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    if (
        geometry.get("type") != "Point"
        or not isinstance(coordinates, list)
        or len(coordinates) != 2
    ):
        return None
    lon, lat = (_number(value) for value in coordinates)
    if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    # Reject both explicit low precision and a building with no named POI data.
    kind = properties.get("result_type")
    categories = properties.get("categories", [properties.get("category")])
    categories = (
        [item for item in categories if isinstance(item, str)]
        if isinstance(categories, list)
        else []
    )
    if kind != "amenity" and not (kind == "building" and categories):
        return None
    actual_name = _text(properties.get("name"))
    name_score = _name_score(name, actual_name)
    if not actual_name or name_score < 0.70:
        return None
    actual_country = _text(properties.get("country"))
    if _country(country) not in {
        _country(actual_country),
        _country(properties.get("country_code")),
    }:
        return None
    # A county, province or supplied query is not evidence of the requested city.
    localities = {
        _locality(properties.get(key), country)
        for key in ("city", "town", "village", "municipality")
    }
    if _locality(city, country) not in localities:
        return None
    actual_city = next(
        (
            _text(properties.get(key))
            for key in ("city", "town", "village", "municipality")
            if _locality(properties.get(key), country) == _locality(city, country)
        ),
        "",
    )
    actual_regions = {
        _normal(properties.get(key))
        for key in (
            "state",
            "state_code",
            "region",
            "suburb",
            "quarter",
            "district",
            "neighbourhood",
            "neighborhood",
            "borough",
        )
    }
    state_code = _text(properties.get("state_code"))
    if "-" in state_code:
        actual_regions.add(_normal(state_code.rsplit("-", 1)[-1]))
    known_regions = actual_regions - {""}
    # The saved field is 'region OR neighborhood'. A different state is not
    # evidence that a supplied neighborhood is wrong. Unverified context
    # stays a review candidate and cannot auto-resolve.
    prefixes = _CATEGORY_PREFIXES.get(_normal(category))
    category_agrees = not prefixes or any(
        value == prefix or value.startswith(prefix + ".")
        for value in categories
        for prefix in prefixes
    )
    if prefixes and categories and not category_agrees:
        return None
    rank = properties.get("rank") if isinstance(properties.get("rank"), dict) else {}
    match_type = rank.get("match_type")
    if match_type in _AREA_MATCHES:
        return None
    confidence = _number(rank.get("confidence"))
    confidence = min(1, max(0, confidence)) if confidence is not None else 0
    city_confidence = _number(rank.get("confidence_city_level"))
    address = _text(properties.get("formatted")) or _text(properties.get("address_line2"))
    identity = _text(properties.get("place_id"))
    if not identity or len(identity) > 512 or not address:
        return None
    result = Candidate(
        id=identity,
        name=actual_name,
        address=address,
        latitude=lat,
        longitude=lon,
        google_maps_url="https://www.google.com/maps/search/?"
        + urlencode({"api": "1", "query": f"{lat},{lon}"}),
        city=actual_city,
        country=actual_country or country,
        score=round(name_score * 0.75 + confidence * 0.25, 4),
    )
    strong = (
        kind == "amenity"
        and name_score >= 0.96
        and confidence >= 0.85
        and (city_confidence is None or city_confidence >= 0.85)
        and match_type == "full_match"
        and category_agrees
        and (not region or _normal(region) in known_regions)
        and _normal(name) not in _CHAINS
    )
    return result, strong


async def search_dream_place(
    place_name: str | None,
    city: str | None,
    country: str | None,
    region: str | None = None,
    category: str | None = None,
) -> SearchResult:
    """Resolve only a unique strong POI; uncertainty never becomes a saved pin."""
    name, city, country, region, category = map(
        _text, (place_name, city, country, region, category)
    )
    if (
        not name
        or not city
        or not country
        or _normal(name) in _GENERIC
        or _normal(city) in {"unknown", "not specified", "n a", "anywhere", "worldwide"}
        or _normal(country) in {"unknown", "not specified", "n a", "anywhere", "worldwide"}
        or _normal(name) in {_normal(city), _normal(country)}
    ):
        return SearchResult(
            status="needs_review",
            message="Add a specific place name, city and country to find its location.",
        )
    if any(
        len(value) > 300 or any(ord(char) < 32 for char in value)
        for value in (name, city, country, region, category)
    ):
        return SearchResult(
            status="needs_review",
            message="Check the place name and location before searching again.",
        )
    key = os.environ.get("GEOAPIFY_API_KEY", "").strip()
    if not key:
        return SearchResult(status="blocked", message="Place lookup is not configured.")
    params = {
        "name": name,
        "city": city,
        "country": country,
        "type": "amenity",
        "limit": 5,
        "lang": "en",
        "bias": "countrycode:none",
        "apiKey": key,
    }
    if region:
        # Do not send a neighborhood such as Chiado as an administrative state.
        # Free-form mode preserves that context without mixing input modes.
        for field in ("name", "city", "country"):
            params.pop(field)
        params["text"] = ", ".join((name, region, city, country))
    code = _country(country)
    if len(code) == 2 and code.isascii() and code.isalpha():
        params["filter"] = "countrycode:" + code
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False) as client:
            response = await client.get(_URL, params=params)
    except httpx.RequestError:
        raise RetryableDreamPlaceLookupError("Place lookup is temporarily unavailable.") from None
    if response.status_code in (408, 425, 429) or response.status_code >= 500:
        raise RetryableDreamPlaceLookupError("Place lookup is temporarily unavailable.")
    if response.status_code != 200:
        return SearchResult(
            status="blocked",
            message="The location provider could not authorize or complete this lookup.",
        )
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        raise RetryableDreamPlaceLookupError(
            "The location provider returned an invalid response."
        ) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise RetryableDreamPlaceLookupError("The location provider returned an invalid response.")
    matches: dict[str, tuple[Candidate, bool]] = {}
    for feature in payload["features"][:5]:
        match = _candidate(feature, name, city, country, region, category)
        if match:
            # Same provider ID may be repeated; distinct IDs remain ambiguous.
            previous = matches.get(match[0].id)
            if previous is None or match[0].score > previous[0].score:
                matches[match[0].id] = match
    ordered = sorted(matches.values(), key=lambda item: (-item[0].score, item[0].id))
    if not ordered:
        return SearchResult(
            status="not_found",
            message="No matching place was found in that city. You can add a pin manually.",
        )
    candidates = [item[0] for item in ordered]
    if len(ordered) == 1 and ordered[0][1] and len(payload["features"]) < 5:
        return SearchResult(status="resolved", candidates=candidates)
    return SearchResult(
        status="needs_review",
        candidates=candidates,
        message="Check the location before adding it to your map.",
    )
