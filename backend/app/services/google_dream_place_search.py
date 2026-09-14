"""Bounded Google Places (New) lookups with transient provider content.

The caller may retain place IDs and cache coordinates only within Google's
permitted lifetime. Names, addresses, types and attribution payloads returned
here must not be copied into permanent item metadata or history. This module
has no database, cache, dotenv, or legacy-provider dependency.

https://developers.google.com/maps/documentation/places/web-service/place-details
https://developers.google.com/maps/documentation/places/web-service/policies
"""

from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import quote, urlencode, urlparse

import httpx
from pydantic import BaseModel, Field, PrivateAttr

from .dream_place_search import (
    RetryableDreamPlaceLookupError,
    _CHAINS,
    _GENERIC,
    _VENUE_WORDS,
    _country,
    _locality,
    _name_score,
    _normal,
    _number,
    _same_admin,
    _text,
)


class GooglePlacesBlockedError(LookupError):
    """A configured service or credential needs attention; never contains a URL."""


class GoogleCandidate(BaseModel):
    id: str
    name: str
    address: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    google_maps_url: str
    provider: Literal["google_places"] = "google_places"
    city: str | None = None
    country: str | None = None
    score: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    attributions: list[dict[str, str]] = Field(default_factory=list)
    _types: set[str] = PrivateAttr(default_factory=set)
    _components: dict[str, set[str]] = PrivateAttr(default_factory=dict)
    _business_status: str = PrivateAttr(default="")


class GoogleSearchResult(BaseModel):
    status: Literal["resolved", "needs_review", "not_found", "blocked"]
    candidates: list[GoogleCandidate] = Field(default_factory=list, max_length=5)
    message: str | None = None
    provider: Literal["google_places"] = "google_places"


_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_DETAILS_URL = "https://places.googleapis.com/v1/places/"
_DETAIL_FIELDS = (
    "id,displayName,formattedAddress,addressComponents,location,types,"
    "businessStatus,pureServiceAreaBusiness,movedPlaceId,attributions"
)
_SEARCH_FIELDS = ",".join("places." + field for field in _DETAIL_FIELDS.split(","))
_TOTAL_TIMEOUT = 30
_LOCAL_TYPES = {"locality", "postal_town", "sublocality", "sublocality_level_1"}
_REGION_TYPES = {"neighborhood", "sublocality", "sublocality_level_1", "sublocality_level_2"}
_AREA_TYPES = {
    "country",
    "political",
    "locality",
    "postal_town",
    "postal_code",
    "route",
    "street_address",
}
_AUXILIARY_TYPES = {
    "parking",
    "public_bathroom",
    "bus_station",
    "bus_stop",
    "transit_station",
    "subway_station",
    "train_station",
    "taxi_stand",
    "gas_station",
}
_CATEGORY_TYPES = {
    "cafe": {"cafe", "coffee_shop", "tea_house"},
    "coffee": {"cafe", "coffee_shop"},
    "coffee shop": {"cafe", "coffee_shop"},
    "restaurant": {"restaurant", "meal_takeaway"},
    "food": {"restaurant", "cafe", "bakery", "meal_takeaway"},
    "bar": {"bar", "pub", "wine_bar", "bar_and_grill"},
    "hotel": {
        "lodging",
        "hotel",
        "resort_hotel",
        "motel",
        "hostel",
        "guest_house",
        "bed_and_breakfast",
        "inn",
    },
    "stay": {
        "lodging",
        "hotel",
        "resort_hotel",
        "motel",
        "hostel",
        "guest_house",
        "bed_and_breakfast",
        "inn",
    },
    "museum": {"museum"},
    "beach": {"beach"},
    "shopping": {"store", "shopping_mall", "market"},
    "attraction": {
        "tourist_attraction",
        "museum",
        "art_gallery",
        "historical_landmark",
        "cultural_landmark",
        "monument",
        "amusement_park",
        "zoo",
        "aquarium",
    },
    "activity": {
        "amusement_park",
        "aquarium",
        "zoo",
        "hiking_area",
        "sports_complex",
        "stadium",
        "spa",
        "swimming_pool",
        "park",
        "movie_theater",
        "bowling_alley",
    },
    "nature": {
        "park",
        "national_park",
        "natural_feature",
        "hiking_area",
        "garden",
        "botanical_garden",
        "wildlife_park",
        "beach",
    },
    "event": {
        "event_venue",
        "banquet_hall",
        "convention_center",
        "concert_hall",
        "performing_arts_theater",
    },
}


def _key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not key or len(key) > 512 or any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise GooglePlacesBlockedError("Google place lookup is not configured correctly.")
    return key


def _identifier(value: object) -> str:
    value = _text(value)
    # IDs have no documented fixed length. Reject unreasonable or path-like
    # input rather than truncate or interpret it as an endpoint/resource path.
    return (
        value
        if value
        and len(value) <= 4096
        and all(char.isascii() and (char.isalnum() or char in "-_") for char in value)
        else ""
    )


async def _request(
    client, method: str, url: str, key: str, fields: str, *, body=None, allow_missing=False
):
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": fields,
        "Content-Type": "application/json",
    }
    try:
        response = await client.request(method, url, headers=headers, json=body)
    except httpx.RequestError:
        raise RetryableDreamPlaceLookupError(
            "Google place lookup is temporarily unavailable."
        ) from None
    if response.status_code in {408, 425, 429} or response.status_code >= 500:
        raise RetryableDreamPlaceLookupError("Google place lookup is temporarily unavailable.")
    if response.status_code == 404 and allow_missing:
        return None
    if response.status_code != 200:
        raise GooglePlacesBlockedError(
            "Google place lookup could not authorize or complete this request."
        )
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        raise RetryableDreamPlaceLookupError("Google returned an invalid place response.") from None
    if not isinstance(payload, dict):
        raise RetryableDreamPlaceLookupError("Google returned an invalid place response.")
    return payload


def _places(payload: dict) -> list[dict]:
    places = payload.get("places", [])
    if not isinstance(places, list) or any(
        not isinstance(place, dict) or not _identifier(place.get("id")) for place in places
    ):
        raise RetryableDreamPlaceLookupError("Google returned an invalid place response.")
    return places


def _components(values: object) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for component in values if isinstance(values, list) else []:
        if not isinstance(component, dict) or not isinstance(component.get("types"), list):
            continue
        names = {_text(component.get(field)) for field in ("longText", "shortText")} - {""}
        for kind in component["types"]:
            if isinstance(kind, str):
                result.setdefault(kind, set()).update(names)
    return result


def _candidate(place: object, *, expected_id: str | None = None) -> GoogleCandidate | None:
    if not isinstance(place, dict):
        return None
    identity = _identifier(place.get("id"))
    display = place.get("displayName")
    name = _text(display.get("text")) if isinstance(display, dict) else ""
    address = _text(place.get("formattedAddress"))
    location = place.get("location")
    types = place.get("types")
    if (
        not identity
        or (expected_id and identity != expected_id)
        or not name
        or not address
        or not isinstance(location, dict)
        or not isinstance(types, list)
    ):
        return None
    types = {kind for kind in types if isinstance(kind, str)}
    if (
        not types
        or types & (_AREA_TYPES | _AUXILIARY_TYPES)
        or any(kind.startswith("administrative_area_level_") for kind in types)
    ):
        return None
    # A named premise/address is not sufficient evidence of a visitable POI.
    meaningful = types - {
        "establishment",
        "point_of_interest",
        "premise",
        "subpremise",
        "geocode",
        "food",
    }
    if not meaningful or place.get("pureServiceAreaBusiness") is True:
        return None
    status = _text(place.get("businessStatus"))
    if status == "CLOSED_PERMANENTLY" or _text(place.get("movedPlaceId")):
        return None
    latitude, longitude = _number(location.get("latitude")), _number(location.get("longitude"))
    if (
        latitude is None
        or longitude is None
        or not (-90 <= latitude <= 90 and -180 <= longitude <= 180)
    ):
        return None
    components = _components(place.get("addressComponents"))
    countries = components.get("country", set())
    if not countries:
        return None
    attributions = []
    raw_attributions = place.get("attributions", [])
    if not isinstance(raw_attributions, list):
        return None
    for attribution in raw_attributions:
        if not isinstance(attribution, dict):
            return None
        provider, uri = _text(attribution.get("provider")), _text(attribution.get("providerUri"))
        try:
            parsed = urlparse(uri)
        except ValueError:
            return None
        if (
            not provider
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            return None
        attributions.append({"display_name": provider, "uri": uri})
    candidate = GoogleCandidate(
        id=identity,
        name=name,
        address=address,
        latitude=latitude,
        longitude=longitude,
        # Both values derive only from the persistable ID, not cached name/coords.
        google_maps_url="https://www.google.com/maps/search/?"
        + urlencode({"api": "1", "query": identity, "query_place_id": identity}),
        city=next(
            (
                sorted(components[kind], key=lambda text: (-len(text), text))[0]
                for kind in ("locality", "postal_town", "sublocality")
                if components.get(kind)
            ),
            None,
        ),
        country=sorted(countries, key=lambda text: (-len(text), text))[0],
        attributions=attributions,
    )
    candidate._types, candidate._components, candidate._business_status = types, components, status
    return candidate


def _category_match(category: str, types: set[str]) -> tuple[bool, bool]:
    expected = _CATEGORY_TYPES.get(_normal(category))
    if not expected:
        return True, False
    actual = set(types)
    if any(kind.endswith("_restaurant") for kind in types):
        actual.add("restaurant")
    if any(kind.endswith("_store") for kind in types):
        actual.add("store")
    agrees = bool(expected & actual)
    catering = {
        "restaurant",
        "cafe",
        "coffee_shop",
        "tea_house",
        "bakery",
        "bar",
        "pub",
        "wine_bar",
        "bar_and_grill",
        "meal_takeaway",
    }
    compatible = bool(expected & catering and actual & catering)
    return agrees or compatible, agrees


def _brand_words(name: str) -> list[str]:
    return [word for word in _normal(name).split() if word not in _VENUE_WORDS]


def _review_brand_similarity(wanted: str, actual: str) -> float:
    """Compare distinctive brand windows, never use this score for auto-pinning.

    Places can include extra descriptors or join/transliterate a saved brand's
    words. Verified geography and a known compatible category are required
    separately by the caller; a cafe/restaurant difference remains review-only.
    Branch numbers are identity evidence, not optional descriptive text.
    """
    left, right = _brand_words(wanted), _brand_words(actual)
    core = "".join(left)
    if len(left) < 2 or len(core) < 8 or not right:
        return 0
    if re.findall(r"\d+", _normal(wanted)) != re.findall(r"\d+", _normal(actual)):
        return 0
    score = 0.0
    for start in range(len(right)):
        for length in range(1, min(len(left) + 1, len(right) - start) + 1):
            window = "".join(right[start : start + length])
            if 0.75 <= len(window) / len(core) <= 1.33:
                score = max(score, SequenceMatcher(None, core, window).ratio())
    return score


def _letter_scripts(value: str) -> set[str]:
    return {
        unicodedata.name(char, "").split(" ", 1)[0]
        for char in _normal(value)
        if char.isalpha() and unicodedata.name(char, "")
    }


def _unverifiable_locality(wanted: str, values: set[str]) -> bool:
    # Google may supply local-script address components even for an English
    # request. An absent/non-comparable locality is not a known city mismatch.
    scripts = _letter_scripts(wanted)
    return bool(
        scripts and (not values or all(not scripts & _letter_scripts(value) for value in values))
    )


def _match(
    candidate: GoogleCandidate, name: str, city: str, country: str, region: str, category: str
):
    components = candidate._components
    countries = {_country(value) for value in components.get("country", set())} - {""}
    if not _country(country) or _country(country) not in countries:
        return None
    score = _name_score(name, candidate.name)
    wanted_city = _locality(city, country)
    city_values = {value for kind in _LOCAL_TYPES for value in components.get(kind, set())}
    city_exact = bool(
        wanted_city and any(_locality(value, country) == wanted_city for value in city_values)
    )
    admin_values = {
        value
        for kind, values in components.items()
        if kind.startswith("administrative_area_level_")
        for value in values
    }
    administrative = any(_same_admin(city, value) for value in admin_values)
    allowed, category_exact = _category_match(category, candidate._types)
    if not allowed:
        return None
    geography_verified = city_exact or administrative
    brand_score = _review_brand_similarity(name, candidate.name)
    distinctive_exact = (
        _normal(name) == _normal(candidate.name)
        and len(_brand_words(name)) >= 2
        and len("".join(_brand_words(name))) >= 8
    )
    locality_review = (
        not geography_verified
        and distinctive_exact
        and category_exact
        and _unverifiable_locality(city, city_values)
    )
    brand_review = (
        geography_verified
        and _normal(category) in _CATEGORY_TYPES
        and allowed
        and score < 0.70
        and brand_score >= 0.86
    )
    if not geography_verified and not locality_review:
        return None
    if score < 0.70 and not brand_review:
        return None
    region_values = admin_values | {
        value for kind in _REGION_TYPES for value in components.get(kind, set())
    }
    region_exact = not region or _normal(region) in {_normal(value) for value in region_values}
    candidate.score = round(score, 4)
    normalized_name = _normal(name)
    chain = any(
        normalized_name == _normal(value) or normalized_name.startswith(_normal(value) + " ")
        for value in _CHAINS
    )
    strong = (
        not (locality_review or brand_review)
        and city_exact
        and score >= 0.96
        and category_exact
        and region_exact
        and not chain
        and candidate._business_status in {"", "OPERATIONAL"}
    )
    return candidate, strong


async def _details(client, key: str, place_id: str) -> GoogleCandidate | None:
    payload = await _request(
        client,
        "GET",
        _DETAILS_URL + quote(place_id, safe=""),
        key,
        _DETAIL_FIELDS,
        allow_missing=True,
    )
    return _candidate(payload, expected_id=place_id) if payload is not None else None


async def fetch_google_place_details(place_id: str) -> GoogleCandidate | None:
    """Fresh same-ID POI for display/confirmation; never follows a moved place."""
    identity = _identifier(place_id)
    if not identity:
        return None
    key = _key()
    try:
        async with asyncio.timeout(_TOTAL_TIMEOUT):
            async with httpx.AsyncClient(
                timeout=12, follow_redirects=False, trust_env=False
            ) as client:
                return await _details(client, key, identity)
    except TimeoutError:
        raise RetryableDreamPlaceLookupError(
            "Google place lookup is temporarily unavailable."
        ) from None


async def search_google_dream_place(
    place_name: str | None,
    city: str | None,
    country: str | None,
    region: str | None = None,
    category: str | None = None,
) -> GoogleSearchResult:
    """At most two requests; multi-result or contextual ambiguity stays reviewable."""
    name, city, country, region, category = map(
        _text, (place_name, city, country, region, category)
    )
    if (
        any(not _normal(value) for value in (name, city, country))
        or _normal(name) in _GENERIC
        or _normal(name) in {_normal(city), _normal(country)}
        or any(
            _normal(value) in {"unknown", "not specified", "n a", "anywhere", "worldwide"}
            for value in (city, country)
        )
    ):
        return GoogleSearchResult(
            status="needs_review",
            message="Add a specific place name, city and country to find its location.",
        )
    if any(
        len(value) > 300 or any(ord(char) < 32 for char in value)
        for value in (name, city, country, region, category)
    ):
        return GoogleSearchResult(
            status="needs_review",
            message="Check the place name and location before searching again.",
        )
    query = {
        "textQuery": ", ".join(value for value in (name, region, city, country) if value),
        "pageSize": 5,
        "languageCode": "en",
    }
    matches = []
    singleton = False
    try:
        key = _key()
        async with asyncio.timeout(_TOTAL_TIMEOUT):
            async with httpx.AsyncClient(
                timeout=12, follow_redirects=False, trust_env=False
            ) as client:
                initial = await _request(
                    client, "POST", _SEARCH_URL, key, "places.id,nextPageToken", body=query
                )
                ids = _places(initial)
                if not ids:
                    return GoogleSearchResult(
                        status="not_found", message="No reliable Google place match was found."
                    )
                singleton = len(ids) == 1 and not initial.get("nextPageToken")
                if singleton:
                    candidate = await _details(client, key, ids[0]["id"])
                    candidates = [candidate] if candidate else []
                else:
                    full = await _request(
                        client, "POST", _SEARCH_URL, key, _SEARCH_FIELDS, body=query
                    )
                    candidates = [
                        candidate
                        for place in _places(full)[:5]
                        if (candidate := _candidate(place)) is not None
                    ]
                for candidate in candidates:
                    match = _match(candidate, name, city, country, region, category)
                    if match:
                        matches.append(match)
    except GooglePlacesBlockedError:
        return GoogleSearchResult(
            status="blocked",
            message="Google place lookup is not configured or could not authorize this request.",
        )
    except TimeoutError:
        raise RetryableDreamPlaceLookupError(
            "Google place lookup is temporarily unavailable."
        ) from None
    unique = {candidate.id: (candidate, strong) for candidate, strong in matches}
    ordered = sorted(unique.values(), key=lambda item: (-item[0].score, item[0].id))
    if not ordered:
        return GoogleSearchResult(
            status="not_found", message="No reliable Google place match was found."
        )
    status = "resolved" if singleton and len(ordered) == 1 and ordered[0][1] else "needs_review"
    return GoogleSearchResult(
        status=status,
        candidates=[item[0] for item in ordered[:5]],
        message=(
            None
            if status == "resolved"
            else "Check the place name and address before adding it to your map."
        ),
    )
