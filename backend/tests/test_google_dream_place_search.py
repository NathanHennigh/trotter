"""Google provider contract: synthetic HTTP only; no account, DB or credentials."""

import asyncio
import copy

import httpx
import pytest

from app.services import google_dream_place_search as search


def component(kind, name, short=None):
    return {"types": [kind], "longText": name, "shortText": short or name}


def place(**updates):
    result = {
        "id": "synthetic-place-1",
        "displayName": {"text": "Casa Toro"},
        "formattedAddress": "12 Example Road, Oaxaca, Mexico",
        "location": {"latitude": 17.0732, "longitude": -96.7266},
        "types": ["cafe", "food", "point_of_interest", "establishment"],
        "addressComponents": [
            component("locality", "Oaxaca"),
            component("country", "Mexico", "MX"),
            component("administrative_area_level_1", "Oaxaca"),
        ],
        "businessStatus": "OPERATIONAL",
        "attributions": [],
    }
    result.update(updates)
    return result


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "synthetic-google-key")
    monkeypatch.setenv("GEOAPIFY_API_KEY", "unrelated-key-never-used")
    monkeypatch.setattr(
        search.httpx, "AsyncClient", lambda **kwargs: pytest.fail("Unmocked provider client")
    )


def responses(monkeypatch, pages):
    calls, options = [], []

    class Client:
        def __init__(self, **kwargs):
            options.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **copy.deepcopy(kwargs)})
            assert len(calls) <= len(pages), "Lookup exceeded expected request budget"
            result = pages[len(calls) - 1]
            if isinstance(result, Exception):
                raise result
            if isinstance(result, int):
                return httpx.Response(
                    result, json={"error": {"message": "unsafe provider content secret"}}
                )
            if isinstance(result, httpx.Response):
                return result
            return httpx.Response(200, json=result)

    monkeypatch.setattr(search.httpx, "AsyncClient", Client)
    return calls, options


def lookup(**updates):
    values = dict(place_name="Casa Toro", city="Oaxaca", country="Mexico", category="cafe")
    values.update(updates)
    return asyncio.run(search.search_google_dream_place(**values))


def singleton(monkeypatch, detail=None):
    return responses(
        monkeypatch,
        [{"places": [{"id": "synthetic-place-1"}]}, detail if detail is not None else place()],
    )


def test_singleton_uses_ids_only_then_details_pro_and_verifies_identity(monkeypatch):
    calls, options = singleton(monkeypatch)
    result = lookup()
    assert result.status == "resolved" and result.provider == "google_places"
    assert result.candidates[0].provider == "google_places"
    assert (result.candidates[0].latitude, result.candidates[0].longitude) == (17.0732, -96.7266)
    assert calls[0]["headers"]["X-Goog-FieldMask"] == "places.id,nextPageToken"
    assert calls[0]["json"]["pageSize"] == 5
    assert calls[1]["method"] == "GET" and calls[1]["url"].endswith("/synthetic-place-1")
    assert "displayName" in calls[1]["headers"]["X-Goog-FieldMask"]
    assert "rating" not in calls[1]["headers"]["X-Goog-FieldMask"]
    assert all(
        call["headers"]["X-Goog-Api-Key"] == "synthetic-google-key"
        and "key" not in call["url"].lower()
        for call in calls
    )
    assert options == [{"timeout": 12, "follow_redirects": False, "trust_env": False}]
    dumped = result.model_dump()
    assert "_types" not in dumped["candidates"][0] and "_components" not in dumped["candidates"][0]
    assert "17.0732" not in result.candidates[0].google_maps_url
    assert "query_place_id=synthetic-place-1" in result.candidates[0].google_maps_url


@pytest.mark.parametrize("input_field", ["place_name", "city", "country"])
@pytest.mark.parametrize("value", [None, "", "---", "???", "Unknown", "N/A"])
def test_missing_identity_never_queries(input_field, value):
    assert lookup(**{input_field: value}).status == "needs_review"


@pytest.mark.parametrize(
    "updates",
    [
        {"place_name": "cafe"},
        {"place_name": "Oaxaca"},
        {"place_name": "a" * 301},
        {"city": "Oaxaca\nLondon"},
    ],
)
def test_generic_or_unsafe_inputs_require_review(updates):
    assert lookup(**updates).status == "needs_review"


def test_explicit_google_key_required_even_with_geoapify_or_legacy_configuration(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY")
    assert lookup().status == "blocked"
    with pytest.raises(search.GooglePlacesBlockedError):
        asyncio.run(search.fetch_google_place_details("synthetic-place-1"))


@pytest.mark.parametrize("key", ["bad\nkey", "x" * 513, "\u00e9"])
def test_malformed_credentials_block_without_request(monkeypatch, key):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", key)
    assert lookup().status == "blocked"


@pytest.mark.parametrize("payload", [{}, {"places": []}])
def test_empty_search_is_not_found_without_details(monkeypatch, payload):
    calls, _ = responses(monkeypatch, [payload])
    assert lookup().status == "not_found" and len(calls) == 1


def test_multiple_ids_use_one_pro_search_and_never_auto_choose_first(monkeypatch):
    first, second = place(), place(
        id="synthetic-place-2", formattedAddress="34 Other Road, Oaxaca, Mexico"
    )
    calls, _ = responses(
        monkeypatch,
        [{"places": [{"id": first["id"]}, {"id": second["id"]}]}, {"places": [second, first]}],
    )
    result = lookup()
    assert result.status == "needs_review" and len(result.candidates) == 2
    assert len(calls) == 2 and all(call["method"] == "POST" for call in calls)
    assert "places.displayName" in calls[1]["headers"]["X-Goog-FieldMask"]


def test_single_id_with_next_page_preserves_ambiguity(monkeypatch):
    calls, _ = responses(
        monkeypatch,
        [{"places": [{"id": "synthetic-place-1"}], "nextPageToken": "more"}, {"places": [place()]}],
    )
    assert lookup().status == "needs_review" and calls[1]["method"] == "POST"


def test_multiple_ids_cannot_become_automatic_after_other_results_filtered(monkeypatch):
    responses(
        monkeypatch,
        [
            {"places": [{"id": "synthetic-place-1"}, {"id": "synthetic-place-2"}]},
            {"places": [place(), place(id="synthetic-place-2", displayName={"text": "Unrelated"})]},
        ],
    )
    result = lookup()
    assert result.status == "needs_review" and len(result.candidates) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"displayName": {"text": "Completely Different"}},
        {"id": "different-id"},
        {"types": ["locality", "political", "point_of_interest"]},
        {"types": ["administrative_area_level_1", "cafe"]},
        {"types": ["street_address"]},
        {"types": ["premise", "point_of_interest"]},
        {"types": ["parking", "point_of_interest", "establishment"]},
        {"types": ["public_bathroom"]},
        {"types": ["hotel", "lodging"]},
        {"pureServiceAreaBusiness": True},
        {"businessStatus": "CLOSED_PERMANENTLY"},
        {"movedPlaceId": "replacement"},
        {"formattedAddress": ""},
        {"addressComponents": []},
        {"displayName": "invalid"},
        {"location": {"latitude": True, "longitude": 1}},
        {"location": {"latitude": 91, "longitude": 1}},
        {"location": {"latitude": 1, "longitude": -181}},
        {"location": {}},
        {"types": []},
        {"types": "cafe"},
    ],
)
def test_single_result_still_rejects_wrong_or_imprecise_place(monkeypatch, updates):
    singleton(monkeypatch, place(**updates))
    assert lookup().status == "not_found"


def test_country_must_match_google_country_components(monkeypatch):
    singleton(
        monkeypatch,
        place(
            addressComponents=[component("locality", "Oaxaca"), component("country", "Spain", "ES")]
        ),
    )
    assert lookup().status == "not_found"


def test_precise_name_in_wrong_city_is_rejected(monkeypatch):
    singleton(
        monkeypatch,
        place(
            addressComponents=[
                component("locality", "Mexico City"),
                component("country", "Mexico", "MX"),
            ]
        ),
    )
    assert lookup().status == "not_found"


def test_admin_geography_recovers_krabi_cafe_as_review_only(monkeypatch):
    data = place(
        displayName={"text": "Kuan Nom Cafe"},
        addressComponents=[
            component("locality", "Ban Khao Thong"),
            component("administrative_area_level_2", "Mueang Krabi District"),
            component("country", "Thailand", "TH"),
        ],
    )
    singleton(monkeypatch, data)
    result = lookup(place_name="Kuan Nom Saow Cafe", city="Krabi", country="Thailand")
    assert result.status == "needs_review" and result.candidates[0].city == "Ban Khao Thong"


@pytest.mark.parametrize("locality", [None, "Δοκιμή"])
def test_exact_distinctive_venue_with_missing_or_local_script_city_is_review_only(
    monkeypatch, locality
):
    components = [component("country", "Greece", "GR")]
    if locality:
        components.append(component("locality", locality))
    calls, _ = singleton(
        monkeypatch,
        place(
            displayName={"text": "Harbor Lighthouse Restaurant"},
            types=["restaurant", "food", "point_of_interest", "establishment"],
            addressComponents=components,
        ),
    )
    result = lookup(
        place_name="Harbor Lighthouse Restaurant",
        city="Example Island",
        country="Greece",
        category="restaurant",
    )
    assert result.status == "needs_review" and len(result.candidates) == 1
    assert len(calls) == 2


@pytest.mark.parametrize(
    "name,category",
    [
        ("Harbor Lighthouse", "restaurant"),
        ("Harbor Lighthouse Restaurant", "unknown"),
        ("Harbor Lighthouse Restaurant", "cafe"),
    ],
)
def test_unverifiable_city_never_combines_with_weak_identity_or_category(
    monkeypatch, name, category
):
    singleton(
        monkeypatch,
        place(
            displayName={"text": "Harbor Lighthouse Restaurant"},
            types=["restaurant"],
            addressComponents=[
                component("locality", "Δοκιμή"),
                component("country", "Greece", "GR"),
            ],
        ),
    )
    assert (
        lookup(place_name=name, city="Example Island", country="Greece", category=category).status
        == "not_found"
    )


def test_readable_contradictory_city_is_not_recovered_by_exact_name(monkeypatch):
    singleton(
        monkeypatch,
        place(
            displayName={"text": "Harbor Lighthouse Restaurant"},
            types=["restaurant"],
            addressComponents=[
                component("locality", "Other Island"),
                component("country", "Greece", "GR"),
            ],
        ),
    )
    assert (
        lookup(
            place_name="Harbor Lighthouse Restaurant",
            city="Example Island",
            country="Greece",
            category="restaurant",
        ).status
        == "not_found"
    )


@pytest.mark.parametrize(
    "provider_name",
    [
        "Lookout HarbourGreen Scenic View",
        "Scenic Harbour Green Lookout",
        "Lookout HarborGreen Coastal Cafe",
    ],
)
def test_compounded_or_romanized_brand_with_extra_descriptors_is_review_only(
    monkeypatch, provider_name
):
    assert search._name_score("Harbor Green Cafe", provider_name) < 0.70
    calls, _ = singleton(monkeypatch, place(displayName={"text": provider_name}))
    result = lookup(place_name="Harbor Green Cafe")
    assert result.status == "needs_review" and len(result.candidates) == 1
    assert len(calls) == 2


@pytest.mark.parametrize(
    "updates",
    [
        {"category": "hotel"},
        {"city": "Another City"},
        {"country": "Another Country"},
        {"category": "unknown"},
    ],
)
def test_variant_brand_requires_verified_geography_and_exact_category(monkeypatch, updates):
    singleton(monkeypatch, place(displayName={"text": "Lookout HarbourGreen Scenic View"}))
    assert lookup(place_name="Harbor Green Cafe", **updates).status == "not_found"


def test_variant_brand_cannot_hide_a_conflicting_branch_number(monkeypatch):
    singleton(monkeypatch, place(displayName={"text": "Lookout HarbourGreen3 Scenic View"}))
    assert lookup(place_name="Harbor Green 2 Cafe").status == "not_found"


def test_variant_brand_with_known_catering_type_difference_remains_review_only(monkeypatch):
    singleton(
        monkeypatch,
        place(
            displayName={"text": "Lookout HarbourGreen Scenic View"},
            types=["restaurant", "food", "establishment", "point_of_interest"],
        ),
    )
    result = lookup(place_name="Harbor Green Cafe", category="cafe")
    assert result.status == "needs_review" and len(result.candidates) == 1


def test_short_single_word_brand_is_not_matched_to_a_long_descriptor(monkeypatch):
    singleton(monkeypatch, place(displayName={"text": "Lookout Garden Scenic View"}))
    assert lookup(place_name="Garden Cafe").status == "not_found"


@pytest.mark.parametrize("county", ["North Krabi District", "Krabiville", "Other"])
def test_admin_matching_is_not_a_substring(monkeypatch, county):
    singleton(
        monkeypatch,
        place(
            addressComponents=[
                component("locality", "Ban Khao Thong"),
                component("administrative_area_level_2", county),
                component("country", "Thailand", "TH"),
            ]
        ),
    )
    assert lookup(city="Krabi", country="Thailand").status == "not_found"


def test_country_alias_region_and_accent_match(monkeypatch):
    singleton(
        monkeypatch,
        place(
            displayName={"text": "Cása-Toro"},
            addressComponents=[
                component("locality", "Austin"),
                component("country", "United States", "US"),
                component("administrative_area_level_1", "Texas", "TX"),
            ],
        ),
    )
    assert lookup(city="Austin", country="USA", region="TX").status == "resolved"


@pytest.mark.parametrize(
    "updates", [{"region": "Another Neighborhood"}, {"category": "unknown"}, {"category": None}]
)
def test_unverified_region_or_category_requires_confirmation(monkeypatch, updates):
    singleton(monkeypatch)
    assert lookup(**updates).status == "needs_review"


@pytest.mark.parametrize("name", ["Starbucks", "Starbucks Reserve", "Hilton Garden Inn"])
def test_known_chain_is_never_chosen_automatically(monkeypatch, name):
    singleton(monkeypatch, place(displayName={"text": name}))
    assert lookup(place_name=name).status == "needs_review"


def test_catering_type_variation_is_reviewable(monkeypatch):
    singleton(
        monkeypatch,
        place(
            types=["greek_restaurant", "restaurant", "food", "point_of_interest", "establishment"]
        ),
    )
    assert lookup(category="cafe").status == "needs_review"
    singleton(
        monkeypatch,
        place(
            types=["greek_restaurant", "restaurant", "food", "point_of_interest", "establishment"]
        ),
    )
    assert lookup(category="restaurant").status == "resolved"


@pytest.mark.parametrize("status", ["CLOSED_TEMPORARILY", "FUTURE_OPENING"])
def test_non_operational_business_requires_review(monkeypatch, status):
    singleton(monkeypatch, place(businessStatus=status))
    assert lookup().status == "needs_review"


def test_attributions_are_preserved_without_provider_raw_payload(monkeypatch):
    singleton(
        monkeypatch,
        place(
            attributions=[{"provider": "Example Data", "providerUri": "https://example.org/credit"}]
        ),
    )
    candidate = lookup().candidates[0]
    assert candidate.attributions == [
        {"display_name": "Example Data", "uri": "https://example.org/credit"}
    ]
    assert "raw" not in candidate.model_dump()


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "https://user:secret@example.org",
        "file:///tmp/x",
        "https://[invalid-ipv6/",
    ],
)
def test_unsafe_attribution_links_are_not_returned(monkeypatch, uri):
    singleton(monkeypatch, place(attributions=[{"provider": "Example", "providerUri": uri}]))
    assert lookup().status == "not_found"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 301])
@pytest.mark.parametrize("stage", [0, 1])
def test_authorization_and_other_client_failures_are_sanitized(monkeypatch, status, stage):
    pages = [status] if stage == 0 else [{"places": [{"id": "synthetic-place-1"}]}, status]
    responses(monkeypatch, pages)
    result = lookup()
    assert result.status == ("not_found" if stage == 1 and status == 404 else "blocked")
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
def test_transient_http_failure_is_retryable(monkeypatch, status):
    responses(monkeypatch, [status])
    with pytest.raises(search.RetryableDreamPlaceLookupError, match="temporarily unavailable"):
        lookup()


def test_network_errors_do_not_expose_credentials_or_request_content(monkeypatch):
    responses(monkeypatch, [httpx.ConnectError("unsafe URL and secret")])
    with pytest.raises(search.RetryableDreamPlaceLookupError) as error:
        lookup()
    assert "secret" not in str(error.value) and error.value.__suppress_context__


@pytest.mark.parametrize(
    "payload",
    [
        {"places": None},
        {"places": [None]},
        {"places": [{}]},
        {"places": [{"id": "../bad"}]},
        ["invalid"],
    ],
)
def test_malformed_search_envelopes_are_retryable(monkeypatch, payload):
    responses(monkeypatch, [payload])
    with pytest.raises(search.RetryableDreamPlaceLookupError):
        lookup()


def test_invalid_json_is_retryable(monkeypatch):
    responses(monkeypatch, [httpx.Response(200, content=b"invalid JSON")])
    with pytest.raises(search.RetryableDreamPlaceLookupError):
        lookup()


def test_total_request_budget_is_hard_bounded(monkeypatch):
    calls, _ = responses(
        monkeypatch,
        [
            {"places": [{"id": f"place-{i}"} for i in range(10)]},
            {"places": [place(id=f"place-{i}") for i in range(10)]},
        ],
    )
    result = lookup()
    assert len(calls) == 2 and len(result.candidates) == 5 and result.status == "needs_review"


def test_fresh_details_confirms_same_id_without_rebinding(monkeypatch):
    calls, _ = responses(monkeypatch, [place()])
    candidate = asyncio.run(search.fetch_google_place_details("synthetic-place-1"))
    assert candidate.id == "synthetic-place-1" and len(calls) == 1
    assert candidate.name == "Casa Toro"


@pytest.mark.parametrize(
    "payload",
    [
        404,
        place(id="different"),
        place(movedPlaceId="new-id"),
        place(types=["locality", "political"]),
    ],
)
def test_obsolete_or_imprecise_details_never_rebind(monkeypatch, payload):
    calls, _ = responses(monkeypatch, [payload])
    assert asyncio.run(search.fetch_google_place_details("synthetic-place-1")) is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "identity", ["", "../place", "places/example", "https://private.invalid", "a" * 4097]
)
def test_invalid_place_id_never_becomes_an_endpoint(identity):
    assert asyncio.run(search.fetch_google_place_details(identity)) is None


def test_long_google_id_is_not_truncated(monkeypatch):
    identity = "a" * 500
    responses(monkeypatch, [place(id=identity)])
    assert asyncio.run(search.fetch_google_place_details(identity)).id == identity


def test_fresh_details_reports_configuration_errors(monkeypatch):
    responses(monkeypatch, [403])
    with pytest.raises(search.GooglePlacesBlockedError) as error:
        asyncio.run(search.fetch_google_place_details("synthetic-place-1"))
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("details_only", [False, True])
def test_overall_deadline_is_retryable_without_response_details(monkeypatch, details_only):
    class SlowClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, *args, **kwargs):
            await asyncio.sleep(1)
            raise AssertionError("The overall deadline should have cancelled this request")

    monkeypatch.setattr(search.httpx, "AsyncClient", SlowClient)
    monkeypatch.setattr(search, "_TOTAL_TIMEOUT", 0.01)
    with pytest.raises(
        search.RetryableDreamPlaceLookupError, match="temporarily unavailable"
    ) as error:
        if details_only:
            asyncio.run(search.fetch_google_place_details("synthetic-place-1"))
        else:
            lookup()
    assert error.value.__suppress_context__
