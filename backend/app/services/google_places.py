"""Place matching helpers for Dream items."""

from __future__ import annotations

import os
from difflib import SequenceMatcher
from urllib.parse import urlencode
from typing import Any, Optional

import httpx
from pydantic import BaseModel

DEFAULT_GEOAPIFY_API_KEY = "5922125ee4e24171a175763098adcd0b"


class GooglePlaceMatch(BaseModel):
    place_id: str
    display_name: str
    formatted_address: Optional[str] = None
    google_maps_url: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    raw: dict[str, Any]


class GooglePlacesError(RuntimeError):
    pass


class GeoapifyError(RuntimeError):
    pass


def normalize_place_name(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in value).split())


def place_name_score(expected: Optional[str], actual: Optional[str]) -> float:
    expected_normalized = normalize_place_name(expected)
    actual_normalized = normalize_place_name(actual)
    if not expected_normalized or not actual_normalized:
        return 0
    if expected_normalized in actual_normalized or actual_normalized in expected_normalized:
        return 1
    expected_tokens = set(expected_normalized.split())
    actual_tokens = set(actual_normalized.split())
    token_overlap = len(expected_tokens & actual_tokens) / len(expected_tokens | actual_tokens)
    ratio = SequenceMatcher(None, expected_normalized, actual_normalized).ratio()
    if token_overlap >= 0.75 or ratio >= 0.88:
        return max(token_overlap, ratio)
    return min(token_overlap, ratio)


def build_place_query(
    place_name: Optional[str],
    city: Optional[str],
    country: Optional[str],
    region: Optional[str] = None,
) -> Optional[str]:
    if not place_name:
        return None
    return " ".join(part for part in [place_name, city, region, country] if part)


def build_google_maps_search_url(
    place_name: Optional[str],
    city: Optional[str],
    country: Optional[str],
    region: Optional[str] = None,
) -> Optional[str]:
    query = build_place_query(place_name, city, country, region)
    if not query:
        return None
    return f"https://www.google.com/maps/search/?{urlencode({'api': '1', 'query': query})}"


def search_google_place(
    place_name: Optional[str],
    city: Optional[str],
    country: Optional[str],
    region: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    timeout_seconds: float = 10,
) -> Optional[GooglePlaceMatch]:
    key = api_key or os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    query = build_place_query(place_name, city, country, region)
    if not key or not query:
        return None

    payload = {
        "textQuery": query,
        "languageCode": "en",
        "maxResultCount": 1,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": ",".join(
            [
                "places.id",
                "places.displayName",
                "places.formattedAddress",
                "places.googleMapsUri",
                "places.addressComponents",
            ]
        ),
    }
    try:
        response = httpx.post(
            "https://places.googleapis.com/v1/places:searchText",
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise GooglePlacesError(f"Google Places lookup failed: {exc}") from exc

    body = response.json()
    places = body.get("places") if isinstance(body, dict) else None
    if not places:
        return None

    place = places[0]
    components = place.get("addressComponents") or []
    parsed_components = parse_address_components(components)
    display_name = place.get("displayName", {}).get("text") or place_name or query
    return GooglePlaceMatch(
        place_id=place.get("id"),
        display_name=display_name,
        formatted_address=place.get("formattedAddress"),
        google_maps_url=place.get("googleMapsUri"),
        city=parsed_components.get("city"),
        region=parsed_components.get("region"),
        country=parsed_components.get("country"),
        raw=place,
    )


def search_geoapify_place(
    place_name: Optional[str],
    city: Optional[str],
    country: Optional[str],
    region: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    timeout_seconds: float = 10,
) -> Optional[GooglePlaceMatch]:
    key = api_key or os.getenv("GEOAPIFY_API_KEY") or DEFAULT_GEOAPIFY_API_KEY
    query = build_place_query(place_name, city, country, region)
    if not key or not query:
        return None

    params = {
        "text": query,
        "limit": 5,
        "bias": "countrycode:none",
        "apiKey": key,
    }
    try:
        response = httpx.get(
            "https://api.geoapify.com/v1/geocode/search",
            params=params,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise GeoapifyError(f"Geoapify lookup failed: {exc}") from exc

    body = response.json()
    features = body.get("features") if isinstance(body, dict) else None
    if not features:
        return None

    scored_features = []
    for feature in features:
        properties = feature.get("properties") or {}
        raw_name = properties.get("name") or properties.get("formatted") or ""
        rank = properties.get("rank") or {}
        confidence = float(rank.get("confidence") or 0)
        name_score = place_name_score(place_name, str(raw_name))
        scored_features.append((name_score, confidence, feature))

    scored_features.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    best_name_score, best_confidence, feature = scored_features[0]
    properties = feature.get("properties") or {}
    if place_name and best_name_score < 0.72 and best_confidence < 0.7:
        return None
    place_id = properties.get("place_id") or properties.get("osm_id") or properties.get("datasource", {}).get("raw", {}).get("osm_id")
    return GooglePlaceMatch(
        place_id=str(place_id) if place_id else f"geoapify:{query}",
        display_name=properties.get("name") or properties.get("formatted") or place_name or query,
        formatted_address=properties.get("formatted"),
        google_maps_url=build_google_maps_search_url(place_name, properties.get("city") or city, properties.get("country") or country, properties.get("state") or region),
        city=properties.get("city") or properties.get("town") or properties.get("village"),
        region=properties.get("state"),
        country=properties.get("country"),
        raw=feature,
    )


def parse_address_components(components: list[dict[str, Any]]) -> dict[str, Optional[str]]:
    city = None
    region = None
    country = None
    for component in components:
        types = set(component.get("types") or [])
        name = component.get("longText") or component.get("shortText")
        if not name:
            continue
        if "locality" in types or "postal_town" in types:
            city = city or name
        elif "administrative_area_level_1" in types:
            region = region or name
        elif "country" in types:
            country = country or name
    return {"city": city, "region": region, "country": country}
