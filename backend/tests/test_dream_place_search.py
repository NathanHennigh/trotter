"""Provider contract tests: synthetic responses only, no credentials or network."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import dream_place_search as search


def feature(**updates):
    properties = {
        "place_id": "synthetic-cafe-1",
        "name": "Casa Toro",
        "city": "Oaxaca",
        "country": "Mexico",
        "country_code": "mx",
        "state": "Oaxaca",
        "formatted": "Casa Toro, 12 Example Street, Oaxaca, Mexico",
        "result_type": "amenity",
        "category": "catering.cafe",
        "rank": {"confidence": 1, "confidence_city_level": 1, "match_type": "full_match"},
    }
    properties.update(updates)
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {"type": "Point", "coordinates": [-96.7266, 17.0732]},
    }


@pytest.fixture(autouse=True)
def isolated_provider(monkeypatch):
    monkeypatch.setenv("GEOAPIFY_API_KEY", "synthetic-test-key-never-real")

    def forbidden(*args, **kwargs):
        raise AssertionError("Provider calls must be mocked")

    monkeypatch.setattr(search.httpx, "AsyncClient", forbidden)


def mock_response(monkeypatch, features=None, status=200, payload=None, error=None):
    captured = []

    class Client:
        def __init__(self, **kwargs):
            captured.append({"options": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params):
            captured.append({"url": url, "params": params})
            if error:
                raise error
            return httpx.Response(
                status, json=payload if payload is not None else {"features": features or []}
            )

    monkeypatch.setattr(search.httpx, "AsyncClient", Client)
    return captured


def lookup(**kwargs):
    values = dict(place_name="Casa Toro", city="Oaxaca", country="Mexico", category="cafe")
    values.update(kwargs)
    return asyncio.run(search.search_dream_place(**values))


def test_unique_strong_amenity_resolves_with_exact_coordinate_link(monkeypatch):
    captured = mock_response(monkeypatch, [feature()])
    result = lookup()
    assert result.status == "resolved"
    assert result.model_dump()["candidates"][0]["provider"] == "geoapify"
    candidate = result.candidates[0]
    assert (candidate.latitude, candidate.longitude) == (17.0732, -96.7266)
    assert parse_qs(urlparse(candidate.google_maps_url).query) == {
        "api": ["1"],
        "query": ["17.0732,-96.7266"],
    }
    params = captured[1]["params"]
    assert params["type"] == "amenity" and params["limit"] == 5
    assert (params["name"], params["city"], params["country"]) == ("Casa Toro", "Oaxaca", "Mexico")
    assert "text" not in params and params["bias"] == "countrycode:none"
    assert captured[0]["options"]["follow_redirects"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"place_name": None},
        {"city": ""},
        {"country": None},
        {"place_name": "Coffee shop"},
        {"place_name": "Hotel"},
        {"place_name": "x" * 301},
        {"city": "Oaxaca\nLondon"},
        {"city": "Unknown"},
        {"country": "N/A"},
        {"country": "Worldwide"},
        {"place_name": "Oaxaca"},
    ],
)
def test_missing_or_generic_context_does_not_query(change):
    assert lookup(**change).status == "needs_review"


def test_no_configured_key_blocks_without_using_existing_fallback(monkeypatch):
    monkeypatch.delenv("GEOAPIFY_API_KEY")
    assert lookup().status == "blocked"


@pytest.mark.parametrize(
    "updates",
    [
        {"name": "Completely Different", "rank": {"confidence": 1, "match_type": "full_match"}},
        {"city": "Mexico City", "state": "Mexico City"},
        {"country": "Spain", "country_code": "es"},
        {"country": None, "country_code": None},
        {"result_type": "city"},
        {"result_type": "street"},
        {"result_type": "postcode"},
        {"result_type": "building", "category": None},
        {"name": None},
        {"rank": {"confidence": 1, "match_type": "match_by_city_or_disrict"}},
        {"category": "accommodation.hotel"},
        {"place_id": None},
        {"formatted": None},
    ],
)
def test_high_confidence_cannot_override_wrong_or_imprecise_place(monkeypatch, updates):
    mock_response(monkeypatch, [feature(**updates)])
    result = lookup()
    assert result.status == "not_found" and not result.candidates


@pytest.mark.parametrize(
    "coordinates", [[float("nan"), 17], [-96, 91], [181, 17], [True, 17], [0], [None, 17]]
)
def test_invalid_coordinates_never_become_pins(monkeypatch, coordinates):
    data = feature()
    data["geometry"]["coordinates"] = coordinates

    # Deliberately malformed provider JSON may include NaN in decoded objects.
    class Response:
        status_code = 200

        def json(self):
            return {"features": [data]}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(search.httpx, "AsyncClient", Client)
    assert lookup().status == "not_found"


def test_two_real_branches_require_review_even_if_first_has_higher_rank(monkeypatch):
    other = feature(
        place_id="synthetic-cafe-2", formatted="Casa Toro, 34 Other Street, Oaxaca, Mexico"
    )
    other["geometry"]["coordinates"] = [-96.70, 17.09]
    other["properties"]["rank"]["confidence"] = 0.9
    mock_response(monkeypatch, [feature(), other])
    result = lookup()
    assert result.status == "needs_review" and len(result.candidates) == 2


def test_known_chain_single_result_does_not_claim_branch_certainty(monkeypatch):
    mock_response(monkeypatch, [feature(name="Starbucks")])
    assert lookup(place_name="Starbucks").status == "needs_review"


@pytest.mark.parametrize(
    "updates",
    [
        {"name": "Casa Torro"},
        {"rank": {"confidence": 0.5, "match_type": "full_match"}},
        {"rank": {"confidence": 1, "confidence_city_level": 0.3, "match_type": "full_match"}},
        {"rank": {"confidence": 1}},
        {"category": None},
        {"result_type": "building"},
    ],
)
def test_plausible_but_incomplete_matches_require_review(monkeypatch, updates):
    mock_response(monkeypatch, [feature(**updates)])
    result = lookup()
    assert result.status == "needs_review" and len(result.candidates) == 1


def test_same_provider_id_deduplicates_but_full_page_does_not_auto_resolve(monkeypatch):
    mock_response(monkeypatch, [feature(), feature()])
    assert lookup().status == "resolved"
    mock_response(monkeypatch, [feature() for _ in range(5)])
    assert lookup().status == "needs_review"


def test_accent_and_punctuation_are_not_fuzzy_country_or_branch_matches(monkeypatch):
    mock_response(monkeypatch, [feature(name="Cása-Toro")])
    assert lookup().status == "resolved"


def test_country_alias_uses_hard_country_filter_and_region_must_agree(monkeypatch):
    data = feature(
        country="United States", country_code="us", city="Austin", state="Texas", state_code="US-TX"
    )
    captured = mock_response(monkeypatch, [data])
    assert lookup(country="USA", city="Austin", region="TX").status == "resolved"
    assert captured[1]["params"]["filter"] == "countrycode:us"
    assert captured[1]["params"]["text"] == "Casa Toro, TX, Austin, USA"
    assert "state" not in captured[1]["params"]
    assert lookup(country="USA", city="Austin", region="California").status == "needs_review"


def test_missing_region_evidence_requires_review(monkeypatch):
    mock_response(monkeypatch, [feature(state=None)])
    assert lookup(region="Oaxaca").status == "needs_review"


def test_neighborhood_context_is_not_misused_as_state_filter(monkeypatch):
    data = feature(
        city="Lisbon", country="Portugal", country_code="pt", state="Lisbon", suburb="Chiado"
    )
    captured = mock_response(monkeypatch, [data])
    assert lookup(city="Lisbon", country="Portugal", region="Chiado").status == "resolved"
    params = captured[1]["params"]
    assert params["text"] == "Casa Toro, Chiado, Lisbon, Portugal"
    assert not ({"state", "name", "city", "country"} & params.keys())
    assert lookup(city="Lisbon", country="Portugal", region="Alfama").status == "needs_review"


def test_actual_british_museum_greater_london_shape(monkeypatch):
    data = feature(
        name="British Museum",
        city="Greater London",
        country="United Kingdom",
        country_code="gb",
        state="England",
        category="entertainment.museum",
        rank={"confidence": 0.9, "confidence_city_level": 0.9, "match_type": "full_match"},
    )
    mock_response(monkeypatch, [data])
    assert (
        lookup(
            place_name="British Museum", city="London", country="United Kingdom", category="museum"
        ).status
        == "resolved"
    )
    data["properties"].update(country="Canada", country_code="ca")
    assert (
        lookup(
            place_name="British Museum", city="London", country="Canada", category="museum"
        ).status
        == "not_found"
    )


def test_actual_hotel_and_same_name_parking_do_not_become_ambiguous(monkeypatch):
    hotel = feature(
        name="Marina Bay Sands",
        city="Singapore",
        country="Singapore",
        country_code="sg",
        category="accommodation.hotel",
    )
    parking = feature(
        place_id="parking-2",
        name="Marina Bay Sands",
        city="Singapore",
        country="Singapore",
        country_code="sg",
        category="parking.cars",
    )
    mock_response(monkeypatch, [parking, hotel])
    result = lookup(
        place_name="Marina Bay Sands", city="Singapore", country="Singapore", category="hotel"
    )
    assert result.status == "resolved" and len(result.candidates) == 1
    assert result.candidates[0].id == "synthetic-cafe-1"


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
def test_retryable_http_errors_are_safe(monkeypatch, status):
    mock_response(
        monkeypatch, status=status, payload={"error": "unsafe request URL and credential"}
    )
    with pytest.raises(search.RetryableDreamPlaceLookupError) as caught:
        lookup()
    assert str(caught.value) == "Place lookup is temporarily unavailable."


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404])
def test_configuration_errors_block_and_do_not_echo_provider_body(monkeypatch, status):
    mock_response(
        monkeypatch, status=status, payload={"error": "unsafe request URL and credential"}
    )
    result = lookup()
    assert result.status == "blocked"
    assert "unsafe" not in result.model_dump_json()


def test_network_exception_does_not_expose_request_url(monkeypatch):
    mock_response(monkeypatch, error=httpx.ConnectError("https://private.invalid/?apiKey=secret"))
    with pytest.raises(search.RetryableDreamPlaceLookupError) as caught:
        lookup()
    assert "secret" not in str(caught.value) and "http" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_httpx_info_logging_redacts_provider_key(caplog):
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info(
            "HTTP Request: GET %s",
            "https://api.geoapify.com/v1/geocode/search?apiKey=synthetic-secret&name=cafe",
        )
    assert "synthetic-secret" not in caplog.text
    assert "apiKey=[redacted]" in caplog.text


@pytest.mark.parametrize(
    "payload", [{}, {"features": None}, {"features": "invalid"}, ["wrong envelope"]]
)
def test_invalid_provider_response_is_retryable(monkeypatch, payload):
    mock_response(monkeypatch, payload=payload)
    with pytest.raises(search.RetryableDreamPlaceLookupError):
        lookup()


def test_malformed_features_do_not_crash_or_leak_raw_content(monkeypatch):
    mock_response(
        monkeypatch,
        features=[
            None,
            {},
            {"properties": []},
            {"properties": {"name": "ignored"}, "geometry": "invalid"},
        ],
    )
    assert lookup().status == "not_found"


def test_result_is_bounded_and_deterministic(monkeypatch):
    items = [feature(place_id=f"place-{i}") for i in reversed(range(5))]
    mock_response(monkeypatch, items)
    result = lookup()
    assert result.status == "needs_review"
    assert [item.id for item in result.candidates] == [f"place-{i}" for i in range(5)]
    assert "raw" not in result.model_dump()["candidates"][0]


def test_actual_krabi_district_cafe_is_reviewed_instead_of_rejected(monkeypatch):
    data = feature(name="Kuan Nom Cafe", city="Ban Khao Thong", county="Mueang Krabi District",
                   state=None, country="Thailand", country_code="th",
                   formatted="Kuan Nom Cafe, wievpoint, Ban Khao Thong, Thailand",
                   rank={"confidence":0.375,"confidence_city_level":0.5,"match_type":"full_match"})
    data["geometry"]["coordinates"] = [98.7781301,8.1662227]
    captured = mock_response(monkeypatch,[data])
    result = lookup(place_name="Kuan Nom Saow Cafe",city="Krabi",country="Thailand")
    assert result.status == "needs_review" and len(result.candidates) == 1
    assert result.candidates[0].city == "Ban Khao Thong"
    assert result.candidates[0].name == "Kuan Nom Cafe"
    assert result.candidates[0].latitude == 8.1662227
    assert len([call for call in captured if "url" in call]) == 1


@pytest.mark.parametrize("actual",["North Krabi District","Krabiville Province","Other Province",None])
def test_admin_match_requires_whole_place_name_not_substring(monkeypatch,actual):
    mock_response(monkeypatch,[feature(city="Another Town",state=None,county=actual)])
    assert lookup(city="Krabi").status == "not_found"


@pytest.mark.parametrize("field,value",[("county","Oaxaca"),("state","Oaxaca Province"),("municipality","Oaxaca Municipal Unit")])
def test_exact_name_with_broader_admin_context_never_auto_resolves(monkeypatch,field,value):
    data=feature(city="Village",state=None,**{field:value}) if field != "state" else feature(city="Village",state=value)
    mock_response(monkeypatch,[data])
    assert lookup().status == "needs_review"


def test_parser_cafe_label_can_review_a_restaurant_but_not_parking(monkeypatch):
    mock_response(monkeypatch,[feature(category="catering.restaurant")])
    assert lookup().status == "needs_review"
    mock_response(monkeypatch,[feature(category="parking.cars")])
    assert lookup().status == "not_found"


def sequence_response(monkeypatch,pages):
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self,*args):
            return False
        async def get(self,url,params):
            calls.append({"url":url,"params":params})
            assert len(calls) <= len(pages), "Lookup exceeded bounded request plan"
            page = pages[len(calls)-1]
            return httpx.Response(page, json={"error": "unsafe credential"}) if isinstance(page, int) else httpx.Response(200,json={"features":page})
    monkeypatch.setattr(search.httpx,"AsyncClient",Client)
    return calls


def area_feature(name="Oaxaca",kind="city",identity="area-city",**extra):
    return feature(**{"name":name,"result_type":kind,"place_id":identity,"category":"administrative",**extra})


def test_canonical_category_suffix_search_retains_original_name_validation(monkeypatch):
    calls=sequence_response(monkeypatch,[[],[feature(name="Casa Toro Restaurant")]])
    result=lookup(place_name="Casa Toro Restaurant",category="restaurant")
    assert result.status == "needs_review"
    assert calls[1]["params"]["text"] == "Casa Toro, Mexico"
    assert "city" not in calls[1]["params"]


def test_places_recovery_uses_verified_boundaries_and_never_fakes_geocoder_rank(monkeypatch):
    city=area_feature(county="Oaxaca Regional Unit")
    county=area_feature(name="Oaxaca Regional Unit",kind="county",identity="area-county",county="Oaxaca Regional Unit")
    poi=feature(city="Village",state=None,county="Oaxaca Regional Unit",rank=None,result_type=None,
                categories=["catering","catering.cafe"],category=None)
    calls=sequence_response(monkeypatch,[[],[],[city],[county],[poi],[poi]])
    result=lookup()
    assert len(calls) == 6
    assert result.status == "needs_review" and len(result.candidates) == 1
    assert calls[2]["params"]["type"] == "locality"
    assert calls[3]["params"]["text"] == "Oaxaca Regional Unit, Mexico"
    assert {call["params"]["filter"] for call in calls[4:]} == {"place:area-city","place:area-county"}
    assert all(call["params"]["categories"] == "catering" for call in calls[4:])
    assert result.candidates[0].latitude == 17.0732


@pytest.mark.parametrize("bad_area",[
    {"name":"Other County"}, {"country":"Spain","country_code":"es"},
    {"result_type":"country"}, {"place_id":None},
])
def test_unverified_area_never_triggers_places_search(monkeypatch,bad_area):
    data=area_feature(**bad_area) if "name" not in bad_area else area_feature(name="Other County")
    calls=sequence_response(monkeypatch,[[],[],[data]])
    assert lookup().status == "not_found"
    assert len(calls) == 3


def test_area_centroid_and_wrong_purpose_objects_never_become_candidates(monkeypatch):
    city=area_feature()
    centroid=area_feature(categories=["catering.cafe"],name="Casa Toro")
    parking=feature(result_type=None,category=None,categories=["parking.cars"])
    calls=sequence_response(monkeypatch,[[],[],[city],[centroid,parking]])
    result=lookup()
    assert result.status == "not_found" and result.candidates == []
    assert len(calls) == 4


def test_places_query_name_can_recover_variants_but_full_saved_name_still_filters(monkeypatch):
    city=area_feature()
    wrong=feature(name="Casa Elsewhere",result_type=None,categories=["catering.cafe"])
    right=feature(name="Casa Toro Garden",result_type=None,categories=["catering.cafe"])
    calls=sequence_response(monkeypatch,[[],[],[city],[wrong,right]])
    result=lookup(place_name="Casa Toro Garden Cafe")
    assert calls[-1]["params"]["name"] == "Casa Toro"
    assert result.status == "needs_review" and [candidate.name for candidate in result.candidates] == ["Casa Toro Garden"]


@pytest.mark.parametrize("field", ["place_name", "city", "country"])
@pytest.mark.parametrize("value", ["---", "???", "…"])
def test_normalized_empty_identity_never_requests_provider(monkeypatch, field, value):
    calls = sequence_response(monkeypatch, [])
    assert lookup(**{field: value}).status == "needs_review"
    assert calls == []


def test_missing_provider_context_cannot_match_empty_normalized_inputs():
    data = feature(city=None, country=None, country_code=None)
    assert search._candidate(data, "Casa Toro", "---", "???", "", "cafe") is None
    assert not search._same_country(data["properties"], "???")


@pytest.mark.parametrize("category", [None, "unknown", "unsupported"])
@pytest.mark.parametrize("purpose", ["parking.cars", "public_transport.platform", "service.toilet"])
def test_unknown_category_never_resolves_auxiliary_objects(monkeypatch, category, purpose):
    mock_response(monkeypatch, [feature(category=purpose)])
    result = lookup(category=category)
    assert result.status == "not_found" and result.candidates == []


@pytest.mark.parametrize("category", [None, "unknown", "unsupported"])
def test_unknown_category_precise_named_place_requires_confirmation(monkeypatch, category):
    mock_response(monkeypatch, [feature()])
    assert lookup(category=category).status == "needs_review"


@pytest.mark.parametrize("status", [400, 401, 403])
@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_secondary_configuration_failure_is_blocked_not_not_found(monkeypatch, status, stage):
    city = area_feature(county="Oaxaca Regional Unit")
    county = area_feature(name="Oaxaca Regional Unit", kind="county", identity="area-county")
    pages = [[], [], [city], [county], []]
    pages[stage] = status
    calls = sequence_response(monkeypatch, pages[:stage + 1])
    result = lookup()
    assert result.status == "blocked" and len(calls) == stage + 1
    assert "unsafe" not in result.model_dump_json()


def test_beach_places_query_uses_documented_category_only(monkeypatch):
    calls = sequence_response(monkeypatch, [[], [], [area_feature()], []])
    assert lookup(place_name="Playa Coral", category="beach").status == "not_found"
    assert calls[-1]["params"]["categories"] == "beach"


@pytest.mark.parametrize("kind", ["city", "county", "state", "district", "suburb", "country", "postcode", "street"])
def test_places_explicit_area_kinds_never_become_pois(monkeypatch, kind):
    calls = sequence_response(monkeypatch, [[], [], [area_feature()], [feature(result_type=kind, categories=["catering.cafe"])]])
    result = lookup()
    assert result.status == "not_found" and not result.candidates and len(calls) == 4
