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
from .dream_place_aliases import source_place_aliases

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
    precision: Literal["place", "area"] = "place"
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
_SEARCH_FIELDS = ",".join("places." + field for field in _DETAIL_FIELDS.split(",")) + ",nextPageToken"
_TOTAL_TIMEOUT = 30
_LOCAL_TYPES = {"locality", "postal_town", "sublocality", "sublocality_level_1"}
_NEIGHBORHOOD_TYPES = {"neighborhood", "sublocality", "sublocality_level_1", "sublocality_level_2"}
_AREA_TYPES = {
    "country",
    "political",
    "locality",
    "postal_town",
    "postal_code",
    "route",
    "street_address",
}
_SUPPORTED_AREA_TYPES = {
    "country", "locality", "postal_town", "neighborhood", "sublocality",
    "colloquial_area", "archipelago", "natural_feature", "island", "lake",
    "river", "mountain_peak", "woods", "nature_preserve", "national_park",
    "state_park", "park", "beach",
    *(f"administrative_area_level_{level}" for level in range(1, 8)),
    *(f"sublocality_level_{level}" for level in range(1, 6)),
}
_AREA_AUXILIARY_TYPES = {"political", "geocode", "point_of_interest", "establishment", "tourist_attraction"}
_AREA_CATEGORIES = {
    "", "unknown", "area", "destination", "town", "city", "village", "region",
    "country", "lake", "island", "mountain", "nature", "attraction", "activity",
    "park", "beach",
}
_AREA_GENERIC_NAMES = {"area", "destination", "town", "city", "village", "region", "country", "lake", "river", "island", "mountain", "province", "district", "nature"}
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


def _candidate(place: object, *, expected_id: str | None = None, allow_area=False) -> GoogleCandidate | None:
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
    area = bool(types & _SUPPORTED_AREA_TYPES) and not types - (_SUPPORTED_AREA_TYPES | _AREA_AUXILIARY_TYPES)
    if allow_area and area:
        precision = "area"
    elif (
        not types
        or types & (_AREA_TYPES | _AUXILIARY_TYPES)
        or any(kind.startswith("administrative_area_level_") for kind in types)
    ):
        return None
    else:
        precision = "place"
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
        precision=precision,
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


def _brand_similarity(wanted: str, actual: str) -> float:
    """Compare distinctive brand windows after checking the venue's geography.

    Places can include extra descriptors or join/transliterate a saved brand's
    words. Verified geography and a known compatible category are required
    separately by the caller; a cafe/restaurant difference is compatible.
    Branch numbers are identity evidence, not optional descriptive text.
    """
    left, right = _brand_words(wanted), _brand_words(actual)
    core = "".join(left)
    # A short multiword brand can be exact while the full Google display name
    # adds venue descriptions. Do not fuzzy-match short names or discard an
    # arbitrary suffix: branch names and locations remain identity evidence.
    wanted_words, actual_words = _normal(wanted).split(), _normal(actual).split()
    descriptors = _VENUE_WORDS | {"and", "rooftop", "terrace", "lounge", "spa", "boutique", "lodging"}
    if (
        len(left) >= 2
        and len(core) >= 6
        and actual_words[:len(wanted_words)] == wanted_words
        and all(word in descriptors for word in actual_words[len(wanted_words):])
    ):
        return 1.0
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


def _region_conflicts(wanted: str, components: dict[str, set[str]]) -> bool:
    """Reject comparable region evidence, not missing/mixed-level geography."""
    if not wanted:
        return False
    groups = {kind: values for kind, values in components.items()
              if kind in _NEIGHBORHOOD_TYPES | _LOCAL_TYPES or kind.startswith("administrative_area_level_")}
    values = {value for group in groups.values() for value in group}
    if any(_normal(wanted) == _normal(value) or _same_admin(wanted, value) for value in values):
        return False
    # region_or_neighborhood is freeform. Local neighborhood evidence is
    # comparable to it; a state's name alone is not proof that an unspecified
    # neighborhood is wrong. Explicit district/state labels or short state
    # codes allow comparison at that administrative level as well.
    neighborhoods = {value for kind in _NEIGHBORHOOD_TYPES for value in groups.get(kind, set())}
    if neighborhoods and not _unverifiable_locality(wanted, neighborhoods):
        return True
    normalized = _normal(wanted)
    state_hint = bool(re.search(r"\b(state|province|region)\b", normalized)) or bool(re.fullmatch(r"[A-Z]{2}", wanted))
    district_hint = bool(re.search(r"\b(district|county)\b", normalized))
    for kind, hinted in (("administrative_area_level_1", state_hint), ("administrative_area_level_2", district_hint)):
        group = groups.get(kind, set())
        if hinted and group and not _unverifiable_locality(wanted, group):
            return True
    return False


def _google_locality(value: str, country: str) -> str:
    normalized = _locality(value, country)
    # Verified alternate spellings in Google's English/address components.
    # Keep these scoped to the country; fuzzy city matching can select a
    # different branch, and removing spaces globally merges unrelated names.
    country_key = _country(country)
    if country_key in {"morocco", "ma"} and normalized == "marrakech":
        return "marrakesh"
    if country_key == "vn" and normalized == "ha noi":
        return "hanoi"
    return normalized


def _described_single_brand(wanted: str, actual: str, city: str, country: str) -> bool:
    """Recognize an exact brand decorated only with venue descriptors / its city.

    Google often labels a saved six-letter brand as e.g. "Restaurant BRAND
    Rooftop CITY". This is not fuzzy matching: short brands, extra branch names,
    numbers and unrelated words are retained as differences. The caller still
    requires compatible category and independently verified local geography.
    """
    brand = _normal(wanted)
    descriptors = _VENUE_WORDS | {"rooftop", "terrace", "lounge", "food", "cocktails", "and"}
    if (len(brand.split()) != 1 or len(brand) < 6 or not brand.isalpha() or brand in _GENERIC | descriptors
            or _google_locality(brand, country) == _google_locality(city, country) or _country(brand) == _country(country)):
        return False
    words = _normal(actual).split()
    # Only a trailing city label can be omitted, and only using the same scoped
    # locality aliases as the provider's verified address components.
    for length in range(min(5, len(words) - 1), 0, -1):
        if _google_locality(" ".join(words[-length:]), country) == _google_locality(city, country):
            words = words[:-length]
            break
    return words.count(brand) == 1 and all(word == brand or word in descriptors for word in words)


def _described_source_alias(wanted: str, actual: str, city: str, country: str) -> bool:
    """A source-stated local name can carry a city and venue labels in Google."""
    name = _normal(wanted).split()
    if len(name) < 2 or len("".join(name)) < 6:
        return False
    words = _normal(actual).split()
    # Preserve the full alias contiguously; never use a partial/fuzzy translation.
    found = [start for start in range(len(words) - len(name) + 1) if words[start:start + len(name)] == name]
    if len(found) != 1:
        return False
    start = found[0]
    remaining = words[:start] + words[start + len(name):]
    for length in range(min(5, len(remaining)), 0, -1):
        offsets = [index for index in range(len(remaining) - length + 1)
                   if _google_locality(" ".join(remaining[index:index + length]), country) == _google_locality(city, country)]
        if len(offsets) == 1:
            offset = offsets[0]
            remaining = remaining[:offset] + remaining[offset + length:]
            break
    descriptors = _VENUE_WORDS | {"rooftop", "terrace", "lounge", "homestay", "more", "and"}
    return all(word in descriptors for word in remaining)


def _same_transport_brand(wanted: str, actual: str, types: set[str]) -> bool:
    # A transport operator may append the literal service label "Train" to its
    # brand. Normalize that one label only for transport listings; arbitrary
    # prefix matches, route names and branch qualifiers are not exact identity.
    if not types & {"transportation_service", "travel_agency"}:
        return False
    def words(value: str) -> list[str]:
        parts = _normal(value).split()
        return parts[:-1] if parts and parts[-1] == "train" else parts
    left, right = words(wanted), words(actual)
    brand = [word for word in left if word not in _VENUE_WORDS]
    return left == right and len(brand) >= 2 and len("".join(brand)) >= 8


def _verified_region(region: str, components: dict[str, set[str]], country: str) -> bool:
    wanted = _google_locality(region, country)
    return bool(wanted and any(
        wanted == _google_locality(value, country) or _same_admin(wanted, _google_locality(value, country))
        for kind, values in components.items()
        if kind in _LOCAL_TYPES | _NEIGHBORHOOD_TYPES or kind.startswith("administrative_area_level_")
        for value in values
    ))


def _country_only_identity(name: str, actual: str) -> bool:
    """Without a city, neither fuzzy brands nor a lone chain result is enough."""
    wanted = _normal(name)
    if any(wanted == chain or wanted.startswith(chain + " ") for chain in _CHAINS):
        return False
    words = _brand_words(name)
    distinctive = (len(words) >= 2 and len("".join(words)) >= 8
                   or len(words) == 1 and len(wanted.split()) == 1 and len(words[0]) >= 6
                   and words[0] not in _GENERIC | _AREA_GENERIC_NAMES | {"rooftop", "terrace", "lounge", "garden"})
    return bool(distinctive and wanted == _normal(actual))


def _match_area(candidate: GoogleCandidate, name: str, city: str, country: str, region: str, category: str):
    """A named area is its own result, never the location of a nearby business."""
    if candidate.precision != "area" or _normal(category) not in _AREA_CATEGORIES:
        return None
    components = candidate._components
    if _country(country) not in {_country(value) for value in components.get("country", set())}:
        return None
    wanted, actual = _google_locality(name, country), _google_locality(candidate.name, country)
    if not wanted or re.findall(r"\d+", wanted) != re.findall(r"\d+", actual):
        return None
    admin_area = any(kind.startswith("administrative_area_level_") for kind in candidate._types)
    if wanted != actual and not (admin_area and _same_admin(wanted, actual)):
        return None
    kind = _normal(category)
    if kind in {"city", "town", "village"} and not candidate._types & {"locality", "postal_town", "sublocality"}:
        return None
    if kind == "region" and not (admin_area or candidate._types & {"colloquial_area", "natural_feature"}):
        return None
    if kind == "lake" and not candidate._types & {"lake", "natural_feature"}:
        return None
    if city and _google_locality(city, country) not in {wanted, actual} and not _verified_region(city, components, country):
        return None
    if region and not _verified_region(region, components, country):
        return None
    candidate.score = 1.0
    return candidate


def _match(
    candidate: GoogleCandidate, name: str, city: str, country: str, region: str, category: str,
    *, source_alias=False,
):
    components = candidate._components
    countries = {_country(value) for value in components.get("country", set())} - {""}
    if not _country(country) or _country(country) not in countries:
        return None
    if candidate.precision != "place":
        return None
    # Branch numbers are identity evidence on every matching path, including a
    # high whole-name score that bypasses the transliteration comparison.
    if re.findall(r"\d+", _normal(name)) != re.findall(r"\d+", _normal(candidate.name)):
        return None
    if _region_conflicts(region, components):
        return None
    score = _name_score(name, candidate.name)
    wanted_city = _google_locality(city, country)
    city_values = {value for kind in _LOCAL_TYPES for value in components.get(kind, set())}
    city_exact = bool(
        wanted_city and any(_google_locality(value, country) == wanted_city for value in city_values)
    )
    admin_values = {
        value
        for kind, values in components.items()
        if kind.startswith("administrative_area_level_")
        for value in values
    }
    administrative = any(_same_admin(wanted_city, _google_locality(value, country)) for value in admin_values)
    allowed, category_exact = _category_match(category, candidate._types)
    if not city:
        if not allowed or not _country_only_identity(name, candidate.name):
            return None
        if _verified_region(name, components, country):
            return None
        if region and not _verified_region(region, components, country):
            return None
        candidate.score = 1.0
        return candidate
    geography_verified = city_exact or administrative
    brand_score = max(_brand_similarity(name, candidate.name),
                      1.0 if (_described_single_brand(name, candidate.name, city, country)
                              or source_alias and _described_source_alias(name, candidate.name, city, country)) else 0.0)
    distinctive_exact = (
        _normal(name) == _normal(candidate.name)
        and len(_brand_words(name)) >= 2
        and len("".join(_brand_words(name))) >= 8
    )
    # The saved category is inferred from a caption and may be wrong. It helps
    # disambiguate fuzzy/partial names, but cannot veto a distinctive exact
    # identity with verified geography. This never changes the saved category.
    strong_identity = distinctive_exact or _same_transport_brand(name, candidate.name, candidate._types)
    if not allowed and not (geography_verified and strong_identity):
        return None
    local_script_match = (
        not geography_verified
        and distinctive_exact
        and category_exact
        and _unverifiable_locality(city, city_values)
    )
    variant_brand_match = (
        geography_verified
        and _normal(category) in _CATEGORY_TYPES
        and allowed
        and score < 0.70
        and brand_score >= 0.86
    )
    if not geography_verified and not local_script_match:
        return None
    if score < 0.70 and not variant_brand_match:
        return None
    candidate.score = round(max(score, brand_score if variant_brand_match else 0), 4)
    return candidate


async def _details(client, key: str, place_id: str, *, allow_area=False) -> GoogleCandidate | None:
    payload = await _request(
        client,
        "GET",
        _DETAILS_URL + quote(place_id, safe=""),
        key,
        _DETAIL_FIELDS,
        allow_missing=True,
    )
    return _candidate(payload, expected_id=place_id, allow_area=allow_area) if payload is not None else None


async def fetch_google_place_details(place_id: str, *, allow_area=False) -> GoogleCandidate | None:
    """Fresh same-ID place, or same-ID area when explicitly refreshing an area."""
    identity = _identifier(place_id)
    if not identity:
        return None
    key = _key()
    try:
        async with asyncio.timeout(_TOTAL_TIMEOUT):
            async with httpx.AsyncClient(
                timeout=12, follow_redirects=False, trust_env=False
            ) as client:
                candidate = await _details(client, key, identity, allow_area=allow_area)
                if allow_area and candidate and candidate.precision != "area":
                    return None
                return candidate
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
    *,
    source_caption: str | None = None,
    allow_area: bool = False,
) -> GoogleSearchResult:
    """Resolve a named venue, or explicitly request a named area with allow_area.

    Google ranks its text results for the complete name and location query. Keep
    that order after rejecting mismatched countries, cities, names and venue
    types; sorting opaque place IDs must never decide which branch is pinned.
    At most two ordinary provider requests are made, including fresh details.
    If needed, up to two extra searches use local names explicitly attached to
    this place in the original caption. All attempts share one timeout budget.
    Country-only venues require an exact distinctive name and one unambiguous
    result. Area mode returns only verified named areas; it cannot substitute a
    region's center for a hotel's location.
    """
    name, city, country, region, category = map(
        _text, (place_name, city, country, region, category)
    )
    if (
        any(not _normal(value) for value in (name, country))
        or _normal(name) in _GENERIC
        or allow_area and _normal(name) in _AREA_GENERIC_NAMES
        or not allow_area and _normal(name) in {_normal(city), _normal(country)}
        or allow_area and _normal(category) not in _AREA_CATEGORIES
        or any(
            _normal(value) in {"unknown", "not specified", "n a", "anywhere", "worldwide"}
            for value in (city, country)
        )
    ):
        return GoogleSearchResult(
            status="not_found",
            message="Add a specific place name and country to find its location.",
        )
    if any(
        len(value) > 300 or any(ord(char) < 32 for char in value)
        for value in (name, city, country, region, category)
    ):
        return GoogleSearchResult(
            status="not_found",
            message="Check the place name and location before searching again.",
        )
    if not _normal(city):
        city = ""
    query = {
        "textQuery": ", ".join(value for value in (name, region, city, country) if value),
        "pageSize": 5,
        "languageCode": "en",
    }
    matches = []
    singleton = False
    truncated = False
    matcher = _match_area if allow_area else _match
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
                truncated = bool(initial.get("nextPageToken")) or len(ids) > 5
                singleton = len(ids) == 1 and not initial.get("nextPageToken")
                if singleton:
                    candidate = await _details(client, key, ids[0]["id"], allow_area=allow_area)
                    candidates = [candidate] if candidate else []
                elif ids:
                    full = await _request(
                        client, "POST", _SEARCH_URL, key, _SEARCH_FIELDS, body=query
                    )
                    candidates = [
                        candidate
                        for place in _places(full)[:5]
                        if (candidate := _candidate(place, allow_area=allow_area)) is not None
                    ]
                    truncated = truncated or bool(full.get("nextPageToken")) or len(_places(full)) > 5
                else:
                    candidates = []
                for candidate in candidates:
                    match = matcher(candidate, name, city, country, region, category)
                    if match:
                        matches.append(match)
                if not matches:
                    for alias in source_place_aliases(name, source_caption):
                        if (_normal(alias) in _GENERIC
                                or not allow_area and (_google_locality(alias, country) == _google_locality(city, country)
                                                       or _country(alias) == _country(country))):
                            continue
                        alias_query = {**query, "textQuery": ", ".join(value for value in (alias, region, city, country) if value)}
                        page = await _request(client, "POST", _SEARCH_URL, key, _SEARCH_FIELDS, body=alias_query)
                        alias_truncated = bool(page.get("nextPageToken")) or len(_places(page)) > 5
                        for raw in _places(page)[:5]:
                            candidate = _candidate(raw, allow_area=allow_area)
                            match = candidate and matcher(candidate, alias, city, country, region, category,
                                                          **({} if allow_area else {"source_alias": True}))
                            if match:
                                matches.append(match)
                        if matches:
                            truncated = alias_truncated
                            break
    except GooglePlacesBlockedError:
        return GoogleSearchResult(
            status="blocked",
            message="Google place lookup is not configured or could not authorize this request.",
        )
    except TimeoutError:
        raise RetryableDreamPlaceLookupError(
            "Google place lookup is temporarily unavailable."
        ) from None
    if not matches:
        return GoogleSearchResult(
            status="not_found", message="No reliable Google place match was found."
        )
    matches = list({candidate.id: candidate for candidate in matches}.values())
    if (not city or allow_area) and (len(matches) != 1 or truncated):
        return GoogleSearchResult(status="not_found", message="More location detail is needed to distinguish these places.")
    return GoogleSearchResult(
        status="resolved",
        candidates=[matches[0]],
        message="Location found on Google Maps.",
    )
