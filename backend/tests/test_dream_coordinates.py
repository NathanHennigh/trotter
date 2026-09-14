"""Coordinates must come from saved evidence, never from a display camera or city guess."""
from types import SimpleNamespace

import pytest

from app.routers.dreams import dream_item_coordinates


def saved(*, url=None, raw=None):
    return SimpleNamespace(google_maps_url=url, raw_metadata_json=raw)


@pytest.mark.parametrize("url, expected", [
    ("https://www.google.com/maps/search/?api=1&query=38.711%2C-9.13", (38.711, -9.13, "place")),
    ("https://www.google.com/maps/place/Cafe/data=!3d38.711!4d-9.13", (38.711, -9.13, "place")),
    ("https://www.google.com/maps/?q=0,0", (0.0, 0.0, "place")),
    ("https://www.google.com/maps/@38.711,-9.13,14z", (None, None, None)),
    ("https://www.google.com/maps/search/?query=Lisbon", (None, None, None)),
    ("https://www.google.com/maps/search/?query=200,300", (None, None, None)),
    ("javascript:alert(1)", (None, None, None)),
])
def test_explicit_pin_urls_only(url, expected):
    assert dream_item_coordinates(saved(url=url)) == expected


@pytest.mark.parametrize("result_type, precision", [("amenity", "place"), ("building", "place"), ("street", "area"), ("district", "area"), ("city", None), ("country", None), (None, None)])
def test_existing_geoapify_match_distinguishes_places_areas_and_city_centres(result_type, precision):
    raw = {"place_match": {"raw": {"properties": {"result_type": result_type}, "geometry": {"type": "Point", "coordinates": [-9.13, 38.711]}}}}
    assert dream_item_coordinates(saved(raw=raw)) == ((38.711, -9.13, precision) if precision else (None, None, None))


def test_unversioned_google_location_is_hidden_and_separate_manual_pin_wins():
    raw = {"place_match": {"raw": {"location": {"latitude": 38.711, "longitude": -9.13}}}}
    assert dream_item_coordinates(saved(raw=raw)) == (None, None, None)
    assert dream_item_coordinates(saved(raw=raw, url="https://www.google.com/maps/?q=38.711,-9.13")) == (None, None, None)
    assert dream_item_coordinates(saved(raw=raw, url="https://www.google.com/maps/?q=41.15,-8.6")) == (41.15, -8.6, "place")


@pytest.mark.parametrize("raw", [{}, [], {"place_match": []}, {"place_match": {"raw": {"location": {"latitude": float("nan"), "longitude": 1}}}}, {"place_match": {"raw": {"location": {"latitude": True, "longitude": 1}}}}])
def test_malformed_or_nonfinite_match_is_not_a_pin(raw):
    assert dream_item_coordinates(saved(raw=raw)) == (None, None, None)
