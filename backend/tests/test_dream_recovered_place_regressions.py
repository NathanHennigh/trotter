"""Recovered caption patterns through source preparation and the real matcher.

HTTP results and coordinates are synthetic. No live service, caption archive,
personal database, or provider balance is needed to verify these regressions.
"""
import asyncio

import pytest

from app.services import dream_location_lookup as lookup
from app.services import google_dream_place_search as google
from test_google_dream_place_search import component, place, responses


MILOS = (
    "Everyone's obsessed with Santorini and Mykonos. Meet Milos, this little island. "
    "WHERE TO STAY: We based ourselves in Adamas port, the perfect spot to explore from. "
    "Or stay up in Plaka, the dreamy hilltop capital. "
    "BEST BEACH: Sarakiniko, hands down. Also loved Firiplaka and Papafragkas! "
    "WHERE TO EAT: Glaronisia in Tripiti village; Alevromilos Cucina Cicladica; "
    "Egoist (if you're looking for breakfast heaven); Aggeliki Gelato for dessert. "
    "DON'T SKIP: A boat tour to Kleftiko. The sea caves are beautiful."
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "synthetic-key")
    monkeypatch.setattr(google.httpx, "AsyncClient", lambda **_: pytest.fail("Unexpected HTTP request"))


def match(name, *, city=None, region=None, country="Greece", category="activity", caption=MILOS, expected_miss=False):
    async def planner(**_):
        if not expected_miss:
            pytest.fail("Source-grounded recognizable case should not need an extra AI call")
        return []
    return asyncio.run(lookup.lookup_dream_location(
        name, city, country, region, category, source_caption=caption, planner=planner,
    ))


def greek_place(name, *, kind="restaurant", region=None, **updates):
    return place(
        displayName={"text": name}, types=[kind],
        formattedAddress="Synthetic fixture address, Greece",
        location={"latitude": 36.72, "longitude": 24.45},
        addressComponents=[component("locality", "Adamantas"), component("country", "Greece", "GR"),
                           *([component("administrative_area_level_3", region)] if region else [])],
        **updates,
    )


@pytest.mark.parametrize("caption", [
    MILOS,
    MILOS.replace("Meet Milos", "meet Milos"),
    MILOS.replace("Meet Milos, this little island", "Milos island"),
])
def test_mixed_island_reel_dessert_name_and_missing_region_component_resolve_together(monkeypatch, caption):
    target = greek_place("Aggeliki ice cream shop", kind="ice_cream_shop")
    island = greek_place("Milos", kind="island", id="synthetic-milos",
                         viewport={"low": {"latitude": 36.6, "longitude": 24.3},
                                   "high": {"latitude": 36.9, "longitude": 24.6}})
    calls, _ = responses(monkeypatch, [
        {"places": [{"id": target["id"]}]}, target, {"places": [island]},
    ])
    result = match("Aggeliki Gelato", city="Milos", caption=caption)
    assert result["status"] == "resolved"
    candidate = result["candidates"][0]
    assert candidate["id"] == target["id"] and candidate["precision"] == "place"
    assert candidate["latitude"] == target["location"]["latitude"]
    assert calls[0]["json"]["textQuery"] == "Aggeliki Gelato, Milos, Greece"
    assert len(calls) == 3 and calls[-1]["json"]["textQuery"] == "Milos, Greece"
    corrected = result["_research"]["matched"]
    assert corrected["city"] is None and corrected["region_or_neighborhood"] == "Milos"
    assert corrected["category"] == "food"


def test_mixed_island_reel_beach_remains_area_with_local_type_prefix(monkeypatch):
    target = greek_place("Paralia Firiplaka", kind="beach", region="Milos")
    calls, _ = responses(monkeypatch, [{"places": [{"id": target["id"]}]}, target])
    result = match("Firiplaka", region="Milos")
    assert result["status"] == "resolved" and result["candidates"][0]["precision"] == "area"
    assert calls[0]["json"]["textQuery"] == "Firiplaka, Milos, Greece"
    assert len(calls) == 2


def test_hotel_descriptor_and_greek_city_alias_work_through_real_lookup(monkeypatch):
    target = greek_place("Panoptis Escape, an SLH Hotel", kind="hotel", region="Mikonos")
    calls, _ = responses(monkeypatch, [{"places": [{"id": target["id"]}]}, target])
    result = match("Panoptis Escape", city="Mykonos", category="hotel",
                   caption="Panoptis Escape, Mykonos. Back to the hotel after a beach day in Mykonos, Greece.")
    assert result["status"] == "resolved" and result["candidates"][0]["precision"] == "place"
    assert len(calls) == 2


def test_named_airbnb_keeps_real_hotel_pin_while_lake_moves_from_city_to_region(monkeypatch):
    target = place(displayName={"text": "Lakeview Lodge"}, types=["hotel"],
                   addressComponents=[component("locality", "Panajachel"),
                                      component("administrative_area_level_3", "Lake Atitlan"),
                                      component("country", "Guatemala", "GT")])
    calls, _ = responses(monkeypatch, [{"places": [{"id": target["id"]}]}, target])
    result = match("Lakeview Lodge", city="Lake Atitlan", country="Guatemala", category="hotel",
                   caption="Our Airbnb overlooked Lake Atitlan. Lakeview Lodge, Lake Atitlan, Guatemala.")
    assert result["status"] == "resolved" and result["candidates"][0]["precision"] == "place"
    assert result["_research"]["matched"]["city"] is None
    assert result["_research"]["matched"]["region_or_neighborhood"] == "Lake Atitlan"
    assert len(calls) == 2


@pytest.mark.parametrize("kind", ["natural_feature", "tourist_attraction"])
def test_unnamed_lakeside_airbnb_cannot_take_a_google_lake_pin(monkeypatch, kind):
    target = place(displayName={"text": "Lake Atitlan"}, types=[kind],
                   addressComponents=[component("country", "Guatemala", "GT")])
    calls, _ = responses(monkeypatch, [{"places": [{"id": target["id"]}]}, target])
    result = match("Lake Atitlan", country="Guatemala", category="hotel", expected_miss=True,
                   caption="Comment LINK and we'll send you this dreamy lakeside stay in Lake Atitlan, Guatemala! #airbnbpartner")
    assert result["status"] == "not_found" and result["candidates"] == []
    assert len(calls) <= 2


def test_recovered_greek_beach_pattern_still_rejects_wrong_country(monkeypatch):
    target = greek_place("Paralia Firiplaka", kind="beach", region="Milos")
    target["addressComponents"] = [component("country", "Italy", "IT")]
    calls, _ = responses(monkeypatch, [{"places": [{"id": target["id"]}]}, target])
    result = match("Firiplaka", region="Milos", expected_miss=True)
    assert result["status"] == "not_found" and result["candidates"] == []
    assert len(calls) == 2
