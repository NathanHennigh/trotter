"""Tests for Google Places matching wrapper."""

from __future__ import annotations

import httpx

from app.services import google_places


def test_google_places_text_search_maps_address_components(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "places": [
                    {
                        "id": "places/abc",
                        "displayName": {"text": "Onera"},
                        "formattedAddress": "Wimberley, TX, USA",
                        "googleMapsUri": "https://maps.google.com/?cid=123",
                        "addressComponents": [
                            {"longText": "Wimberley", "types": ["locality"]},
                            {"longText": "Texas", "types": ["administrative_area_level_1"]},
                            {"longText": "United States", "types": ["country"]},
                        ],
                    }
                ]
            },
        )

    monkeypatch.setattr(google_places.httpx, "post", fake_post)

    match = google_places.search_google_place("Onera", "Wimberley", "United States", api_key="key")

    assert captured["url"] == "https://places.googleapis.com/v1/places:searchText"
    assert captured["json"]["textQuery"] == "Onera Wimberley United States"
    assert "places.googleMapsUri" in captured["headers"]["X-Goog-FieldMask"]
    assert match is not None
    assert match.google_maps_url == "https://maps.google.com/?cid=123"
    assert match.region == "Texas"


def test_google_maps_search_url_is_free_fallback():
    assert (
        google_places.build_google_maps_search_url("Casa Toro", "Puerto Escondido", "Mexico")
        == "https://www.google.com/maps/search/?api=1&query=Casa+Toro+Puerto+Escondido+Mexico"
    )


def test_geoapify_uses_dev_default_key(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"features": []},
        )

    monkeypatch.delenv("GEOAPIFY_API_KEY", raising=False)
    monkeypatch.setattr(google_places.httpx, "get", fake_get)

    google_places.search_geoapify_place("Onera", "Wimberley", "United States")

    assert captured["params"]["apiKey"] == google_places.DEFAULT_GEOAPIFY_API_KEY


def test_geoapify_search_maps_result(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "features": [
                    {
                        "properties": {
                            "place_id": "geo-1",
                            "name": "Casa Toro",
                            "formatted": "Casa Toro, Puerto Escondido, Mexico",
                            "city": "Puerto Escondido",
                            "state": "Oaxaca",
                            "country": "Mexico",
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(google_places.httpx, "get", fake_get)

    match = google_places.search_geoapify_place("Casa Toro", "Puerto Escondido", "Mexico", api_key="key")

    assert captured["url"] == "https://api.geoapify.com/v1/geocode/search"
    assert captured["params"]["text"] == "Casa Toro Puerto Escondido Mexico"
    assert captured["params"]["bias"] == "countrycode:none"
    assert captured["params"]["limit"] == 5
    assert match is not None
    assert match.place_id == "geo-1"
    assert match.region == "Oaxaca"
    assert match.google_maps_url is not None


def test_geoapify_rejects_low_confidence_name_mismatch(monkeypatch):
    def fake_get(url, params, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "features": [
                    {
                        "properties": {
                            "place_id": "geo-1",
                            "name": "Casa Vieja",
                            "formatted": "Casa Vieja, Puerto Escondido, Mexico",
                            "city": "Puerto Escondido",
                            "country": "Mexico",
                            "rank": {"confidence": 0},
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(google_places.httpx, "get", fake_get)

    assert google_places.search_geoapify_place("Casa Toro", "Puerto Escondido", "Mexico", api_key="key") is None


def test_geoapify_rejects_similar_wrong_name(monkeypatch):
    def fake_get(url, params, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "features": [
                    {
                        "properties": {
                            "place_id": "geo-1",
                            "name": "Casa Tortuga",
                            "city": "Puerto Escondido",
                            "country": "Mexico",
                            "rank": {"confidence": 0},
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(google_places.httpx, "get", fake_get)

    assert google_places.search_geoapify_place("Casa Toro", "Puerto Escondido", "Mexico", api_key="key") is None


def test_geoapify_chooses_best_name_candidate(monkeypatch):
    def fake_get(url, params, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "features": [
                    {
                        "properties": {
                            "place_id": "wrong",
                            "name": "Casa Vieja",
                            "city": "Puerto Escondido",
                            "country": "Mexico",
                            "rank": {"confidence": 0.2},
                        }
                    },
                    {
                        "properties": {
                            "place_id": "right",
                            "name": "Casa Toro",
                            "city": "Puerto Escondido",
                            "country": "Mexico",
                            "rank": {"confidence": 0.1},
                        }
                    },
                ]
            },
        )

    monkeypatch.setattr(google_places.httpx, "get", fake_get)

    match = google_places.search_geoapify_place("Casa Toro", "Puerto Escondido", "Mexico", api_key="key")

    assert match is not None
    assert match.place_id == "right"
