"""Source-grounded AI query planning: synthetic provider responses only."""
import asyncio
import copy
import json

import httpx
import pytest

from app.services import dream_location_research as research


def query(name="Hiên Coffee", city=None, country="Vietnam", region=None, intent="place", **evidence):
    return dict(place_name=name, city=city, country=country, region_or_neighborhood=region,
                intent=intent, evidence={field: evidence.get(field) for field in research.EVIDENCE_FIELDS})


def validate(*queries, **saved):
    data = dict(source_caption="Visit Hiên Coffee in Ta Xua, Vietnam.", place_name="Hiên Coffee",
                city="Sa Pa", country="Vietnam", category="cafe")
    data.update(saved)
    return research.validate_location_proposals({"queries": list(queries)}, **data)


def test_drop_unsupported_city_preserves_name_country_and_auditable_evidence():
    plans = validate(query())
    assert len(plans) == 1
    plan = plans[0]
    assert plan.lookup_kwargs() == dict(place_name="Hiên Coffee", city=None, country="Vietnam",
                                      region_or_neighborhood=None, category="cafe")
    assert plan.dropped_fields == ("city",)
    assert plan.evidence["city"] == {"source": "removed", "quote": None}
    assert plan.evidence["place_name"] == {"source": "saved", "quote": "Hiên Coffee"}
    assert plan.region is None and plan.allow_area is False


def test_comparison_city_can_be_removed_with_exact_quote():
    caption = "While everyone flocks to Sa Pa, explore Ta Xua. Visit Hiên Coffee in Ta Xua."
    raw = query()
    raw["evidence"]["city"] = "While everyone flocks to Sa Pa"
    assert len(validate(raw, source_caption=caption)) == 1
    raw["evidence"]["city"] = None
    assert validate(raw, source_caption=caption) == []


def test_source_bound_new_city_and_missing_country_are_allowed():
    raw = query(city="Ta Xua", country="Vietnam")
    raw["evidence"].update(city="Hiên Coffee in Ta Xua, Vietnam", country="Hiên Coffee in Ta Xua, Vietnam")
    plan = validate(raw, country=None)[0]
    assert plan.city == "Ta Xua" and plan.country == "Vietnam"
    assert plan.evidence["city"]["source"] == "caption"


@pytest.mark.parametrize("caption,evidence", [
    ("Visit Hiên Coffee. Then see Dragon Bridge in Da Nang.", "Visit Hiên Coffee. Then see Dragon Bridge in Da Nang"),
    ("Hiên Coffee in Ta Xua; Dragon Bridge in Da Nang", "Hiên Coffee in Ta Xua; Dragon Bridge in Da Nang"),
    ("Hiên Coffee in Ta Xua and Dragon Bridge in Da Nang", "Hiên Coffee in Ta Xua and Dragon Bridge in Da Nang"),
    ("Hiên Coffee in Ta Xua. Dragon Bridge in Da Nang", "Dragon Bridge in Da Nang"),
    ("Hiên Coffee in Ta Xua. Dragon Bridge in Da Nang", "Hiên Coffee in Ta Xua. Dragon Bridge in Da Nang"),
    ("Hiên Coffee in Ta Xua, Dragon Bridge in Da Nang", "Hiên Coffee in Ta Xua, Dragon Bridge in Da Nang"),
    ("Hiên Coffee is wonderful, Da Nang has Dragon Bridge.", "Hiên Coffee is wonderful, Da Nang has Dragon Bridge."),
    ("Hiên Coffee is wonderful / Dragon Bridge in Da Nang.", "Hiên Coffee is wonderful / Dragon Bridge in Da Nang."),
    ("Hiên Coffee, Dragon Bridge in Da Nang.", "Hiên Coffee, Dragon Bridge in Da Nang."),
])
def test_cannot_attach_another_stops_geography(caption, evidence):
    raw = query(city="Da Nang")
    raw["evidence"]["city"] = evidence
    assert validate(raw, source_caption=caption) == []


@pytest.mark.parametrize("quote", ["Hiên Coffee in Ta Xua, Vietnam", "Hiên Coffee is located in Ta Xua, Vietnam",
                                  "Hiên Coffee, Ta Xua, Vietnam", "Hiên Coffee — Ta Xua, Vietnam"])
def test_direct_locative_or_destination_label_keeps_valid_repairs(quote):
    raw = query(city="Ta Xua", country="Vietnam")
    raw["evidence"].update(city=quote, country=quote)
    assert len(validate(raw, source_caption=quote, city=None, country=None)) == 1


def test_cannot_substitute_a_sibling_venue_even_with_exact_source_quote():
    raw = query(name="Dragon Bridge")
    raw["evidence"]["place_name"] = "Dragon Bridge"
    assert validate(raw, source_caption="Visit Hiên Coffee. Visit Dragon Bridge.") == []


def test_cropped_quote_cannot_hide_comparison_context():
    raw = query(city="Hanoi")
    raw["evidence"]["city"] = "Hiên Coffee in Hanoi"
    assert validate(raw, source_caption="Not Hiên Coffee in Hanoi. Try something else.") == []


def test_literal_local_alias_is_allowed_without_reinterpreting_the_name():
    caption = "Visit Dolphin Rock (Mỏm Cá Heo) in Ta Xua, Vietnam."
    raw = query(name="Mỏm Cá Heo", city="Ta Xua", place_name="Mỏm Cá Heo")
    plan = validate(raw, source_caption=caption, place_name="Dolphin Rock", city="Ta Xua", category="nature")[0]
    assert plan.place_name == "Mỏm Cá Heo"
    assert plan.evidence["place_name"] == {"source": "caption", "quote": "Mỏm Cá Heo"}


def test_unattached_local_name_and_translated_alias_are_rejected():
    raw = query(name="Mỏm Cá Heo", place_name="Mỏm Cá Heo")
    assert validate(raw, source_caption="Dolphin Rock. Elsewhere Mỏm Cá Heo.", place_name="Dolphin Rock") == []
    raw = query(name="Hien Cafe", place_name="Hiên Coffee")
    assert validate(raw) == []


@pytest.mark.parametrize("field,value", [("country", None), ("country", "Thailand"), ("city", "Hanoi")])
def test_known_country_or_supported_city_cannot_be_changed(field, value):
    raw = query(city="Ta Xua")
    raw[field] = value
    raw["evidence"][field] = "Hiên Coffee in Ta Xua, Vietnam"
    assert validate(raw, city="Ta Xua") == []


@pytest.mark.parametrize("flags", [{"protected": True}, {"manual": True}, {"protected_fields": ("city",)}])
def test_protected_data_is_never_repaired(flags):
    assert validate(query(), **flags) == []


def test_protected_country_allows_unsupported_city_removal():
    assert len(validate(query(), protected_fields=("country",))) == 1


def test_accents_do_not_turn_saved_geography_into_new_guesses():
    raw = query(city="Tà Xùa")
    raw["region_or_neighborhood"] = None
    plan = validate(raw, city="Ta Xua", region_or_neighborhood="Old hint")[0]
    assert plan.city == "Ta Xua"
    assert plan.dropped_fields == ("region_or_neighborhood",)


def area_query(name, quote, *, city=None, country="Italy"):
    raw = query(name=name, city=city, country=country, intent="area")
    raw["evidence"].update(place_name=quote, intent=quote)
    return raw


@pytest.mark.parametrize("name,city,caption,quote", [
    ("Tropea", None, "Explore Tropea, Italy.", "Explore Tropea, Italy"),
    ("Tropea", None, "Welcome to Tropea!", "Welcome to Tropea"),
    (None, "Tropea", "The beautiful beaches of Tropea, Italy.", "Tropea, Italy"),
    ("Lake Atitlan", None, "Lake Atitlan is breathtaking.", "Lake Atitlan is breathtaking"),
    ("Ta Xua", None, "Explore Ta Xua, a mountain region. Visit Hiên Coffee in Ta Xua.", "Explore Ta Xua, a mountain region"),
])
def test_broad_destination_sources_can_request_verified_area(name, city, caption, quote):
    raw = area_query(name or city, quote, city=city)
    plans = validate(raw, source_caption=caption, place_name=name, city=city, country="Italy", category="unknown")
    assert len(plans) == 1 and plans[0].allow_area
    assert research.source_area_intent(place_name=name, city=city, category="unknown", source_caption=caption)


@pytest.mark.parametrize("caption", [
    "Tropea should definitely be on your Italy bucket list. Perched above the turquoise waters of Calabria, Tropea combines dramatic coastal views, beautiful beaches, charming old streets. Save this post for your next trip to Italy!",
    "Perched above the turquoise waters of Calabria, Tropea combines dramatic coastal views, beautiful beaches, charming old streets.",
    "Plan your next trip to Tropea.",
    "Wander Tropea's charming old streets.",
])
def test_real_tropea_destination_prose_supports_area_without_generic_explore_heading(caption):
    quote = caption.split(".")[0]
    raw = area_query("Tropea", quote)
    assert research.source_area_intent(place_name="Tropea", source_caption=caption, category="attraction")
    assert len(validate(raw, source_caption=caption, place_name="Tropea", city=None,
                        country="Italy", category="attraction")) == 1


@pytest.mark.parametrize("name,caption", [
    ("Lake Atitlán", "San Marcos, Lake Atitlan is beautiful."),
    ("Lake Atitlan", "San Marcos, Lake Atitlán is beautiful."),
])
def test_lake_accent_variation_matches_identity_but_keeps_original_label(name, caption):
    raw = area_query(name, caption, country="Guatemala")
    assert research.source_area_intent(place_name=name, source_caption=caption, category="nature")
    plan = validate(raw, source_caption=caption, place_name=name, city=None, country="Guatemala", category="nature")[0]
    assert plan.place_name == name
    assert plan.evidence["intent"]["quote"] == caption


def test_accent_equivalent_identity_does_not_allow_rewritten_evidence_quote():
    raw = area_query("Lake Atitlán", "San Marcos, Lake Atitlán is beautiful", country="Guatemala")
    assert validate(raw, source_caption="San Marcos, Lake Atitlan is beautiful", place_name="Lake Atitlán", city=None,
                    country="Guatemala", category="nature") == []


def test_source_relationship_accepts_accent_equivalent_name_and_geography_with_literal_evidence():
    caption = "Hien Coffee in Ta Xua, Vietnam"
    raw = query(city="Tà Xùa")
    raw["evidence"]["city"] = caption
    plan = validate(raw, source_caption=caption, city=None)[0]
    assert plan.place_name == "Hiên Coffee" and plan.city == "Tà Xùa"
    assert plan.evidence["city"]["quote"] == caption


def test_accent_matching_keeps_comparison_clause_boundaries():
    caption = "Skip Hanoi\nHien Coffee in Ta Xua, Vietnam"
    raw = query(city="Tà Xùa")
    raw["evidence"]["city"] = "Hien Coffee in Ta Xua, Vietnam"
    assert len(validate(raw, source_caption=caption, city=None)) == 1


@pytest.mark.parametrize("name,caption", [
    ("Tropea", "This hotel in Tropea should definitely be on your Italy bucket list."),
    (None, "The best hotel! Tropea should definitely be on your Italy bucket list."),
    ("Lake Atitlán", "This Airbnb is beside Lake Atitlan."),
    (None, "The best Airbnb in Guatemala! Wake up beside Lake Atitlan."),
])
def test_new_destination_and_accent_support_preserves_business_exclusions(name, caption):
    city = "Lake Atitlán" if "Atitlan" in caption else "Tropea"
    assert not research.source_area_intent(place_name=name, city=city if name is None else None,
                                         source_caption=caption, category="unknown")


def test_accent_equivalent_comparison_is_not_positive_destination_support():
    caption = "Skip Lake Atitlan. Visit somewhere else."
    assert not research.source_area_intent(place_name="Lake Atitlán", source_caption=caption, category="nature")


def test_actual_ta_xua_caption_with_comparison_prefix_and_comma_adjectives_is_an_area():
    caption = ("While everyone flocks to Sa Pa or Ha Giang, Ta Xua remains a peaceful, mist-covered mountain paradise hidden in Northern Vietnam.\n"
               "Visit Dinosaur Spine ridge and Hiên Coffee for the views.")
    quote = "Ta Xua remains a peaceful, mist-covered mountain paradise"
    assert research.source_area_intent(place_name="Ta Xua", source_caption=caption, category="attraction")
    raw = area_query("Ta Xua", quote, country="Vietnam")
    raw['region_or_neighborhood'] = 'Northern Vietnam'
    assert len(validate(raw, source_caption=caption, place_name="Ta Xua", city=None, country="Vietnam",
                        category="attraction", region_or_neighborhood="Northern Vietnam")) == 1


@pytest.mark.parametrize("name,city,category,caption", [
    (None, "Tropea", "unknown", "This unnamed hotel in Tropea has the best views."),
    (None, "Lake Atitlan", "unknown", "This Airbnb overlooking Lake Atitlan is a dream."),
    (None, "Lake Atitlan", "unknown", "The best Airbnb in Guatemala! Wake up beside Lake Atitlan."),
    (None, "Tropea", "unknown", "An incredible hotel. Wake up in Tropea."),
    (None, "Tropea", "unknown", "Visit Tropea. This restaurant is the best."),
    ("Lake Atitlan", None, "unknown", "Book this Airbnb on Lake Atitlan."),
    ("Tropea", None, "hotel", "Explore Tropea, Italy."),
    ("Amazing Airbnb", "Tropea", "unknown", "Explore Tropea, Italy. Amazing Airbnb is nearby."),
    ("Hiên Coffee", None, "cafe", "Explore Hiên Coffee, Vietnam."),
    (None, None, "unknown", "Explore Italy."),
])
def test_unknown_business_is_not_approximated_by_area(name, city, category, caption):
    anchor = name or city or "Italy"
    raw = area_query(anchor, anchor, city=city)
    assert validate(raw, source_caption=caption, place_name=name, city=city, country="Italy", category=category) == []
    assert not research.source_area_intent(place_name=name, city=city, category=category, source_caption=caption)


def test_nameless_destination_requires_area_not_exact_place_pin():
    assert validate(query(name="Tropea", city="Tropea", country="Italy", place_name="Tropea"),
                    source_caption="Explore Tropea, Italy", place_name=None, city="Tropea", country="Italy", category="unknown") == []


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.update(latitude=10),
    lambda raw: raw.update(place_name="https://example.com"),
    lambda raw: raw.update(city="1.234, 5.678"),
    lambda raw: raw.update(city=["Ta Xua"]),
    lambda raw: raw.update(intent="hotel"),
    lambda raw: raw.update(intent=[]),
    lambda raw: raw.update(evidence=None),
    lambda raw: raw["evidence"].update(city="invented quotation"),
    lambda raw: raw["evidence"].update(place_name=42),
])
def test_rejects_untrusted_malformed_or_invented_outputs(mutation):
    raw = query()
    mutation(raw)
    assert validate(raw) == []


def test_original_proper_name_can_survive_its_absence_from_caption_but_no_reinterpretation():
    plan = validate(query(), source_caption="Beautiful mornings in Vietnam.")[0]
    assert plan.place_name == "Hiên Coffee"


def test_bounded_unique_plans_and_unchanged_query_is_not_repeated():
    assert validate(query(city="Sa Pa")) == []
    assert len(validate(query(), query(), query(), query())) == 1


@pytest.fixture(autouse=True)
def prevent_network(monkeypatch):
    monkeypatch.setattr(research.httpx, "AsyncClient", lambda **kwargs: pytest.fail("Unmocked network"))


def provider(monkeypatch, body=None, *, error=None, delay=0, status=200):
    calls, options = [], []

    class Client:
        def __init__(self, **kwargs):
            options.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append({"url": url, **copy.deepcopy(kwargs)})
            assert len(calls) == 1, "One model request maximum"
            if delay:
                await asyncio.sleep(delay)
            if error:
                raise error
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(research.httpx, "AsyncClient", Client)
    return calls, options


def plan(**kwargs):
    args = dict(source_caption="Visit Hiên Coffee in Ta Xua, Vietnam", place_name="Hiên Coffee",
                city="Sa Pa", country="Vietnam", category="cafe", provider="venice", api_key="synthetic")
    args.update(kwargs)
    return asyncio.run(research.plan_location_queries(**args))


def test_one_async_venice_request_with_source_only_schema_and_hard_timeout_cap(monkeypatch):
    body = {"choices": [{"message": {"content": json.dumps({"queries": [query()]})}}]}
    calls, options = provider(monkeypatch, body)
    result = plan(timeout_seconds=60)
    assert len(result) == 1 and len(calls) == 1
    assert options[0] == {"timeout": 15.0, "follow_redirects": False}
    payload = calls[0]["json"]
    assert payload["store"] is False and payload["temperature"] == 0
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["venice_parameters"]["enable_web_search"] == "off"
    user = json.loads(payload["messages"][1]["content"])
    assert set(user) == {"saved_place", "source_caption", "literal_local_aliases", "source_area_name", "protected_fields", "query_intent"}
    assert user['query_intent'] == 'place'
    assert payload['response_format']['json_schema']['schema']['properties']['queries']['items']['properties']['intent']['enum'] == ['place']
    assert "coordinates" not in user and "google_results" not in user


def test_one_async_ollama_request(monkeypatch):
    calls, _ = provider(monkeypatch, {"message": {"content": json.dumps({"queries": [query()]})}})
    assert len(plan(provider="ollama")) == 1
    assert calls[0]["url"].endswith("/api/chat")
    assert calls[0]["json"]["stream"] is False


def test_known_source_area_intent_constrains_provider_schema(monkeypatch):
    calls, _ = provider(monkeypatch, {"message": {"content": '{"queries": []}'}})
    assert plan(provider='ollama', place_name='Ta Xua', city=None, category='attraction',
                source_caption='Ta Xua remains a peaceful, mist-covered mountain paradise hidden in Northern Vietnam.') == []
    payload = calls[0]['json']
    assert payload['format']['properties']['queries']['items']['properties']['intent']['enum'] == ['area']
    assert json.loads(payload['messages'][1]['content'])['query_intent'] == 'area'


@pytest.mark.parametrize("body", [None, [], "bad", {}, {"message": None}, {"message": "bad"}, {"message": []}, {"message": {"content": []}}])
def test_malformed_optional_provider_response_returns_no_plans(monkeypatch, body):
    calls, _ = provider(monkeypatch, body)
    assert plan(provider="ollama") == [] and len(calls) == 1


@pytest.mark.parametrize("body", [{}, {"choices": None}, {"choices": []}, {"choices": [{"message": None}]},
                                   {"choices": [{"message": {"content": "not JSON"}}]}])
def test_malformed_venice_is_nonfatal(monkeypatch, body):
    provider(monkeypatch, body)
    assert plan() == []


def test_network_failure_no_retry(monkeypatch):
    calls, _ = provider(monkeypatch, error=httpx.ConnectError("offline"))
    with pytest.raises(research.LocationResearchUnavailable, match="timeout_or_network"):
        plan()
    assert len(calls) == 1


@pytest.mark.parametrize("status,reason", [(402, "billing"), (429, "rate_limited"), (503, "provider")])
def test_http_failure_no_retry(monkeypatch, status, reason):
    calls, _ = provider(monkeypatch, status=status, body={"error": "private provider details"})
    with pytest.raises(research.LocationResearchUnavailable, match=reason) as error:
        plan()
    assert "private" not in str(error.value) and len(calls) == 1


def test_real_async_timeout_cancels_without_waiting_for_thread_shutdown(monkeypatch):
    calls, _ = provider(monkeypatch, delay=1)
    with pytest.raises(research.LocationResearchUnavailable, match="timeout_or_network"):
        plan(timeout_seconds=0.001)
    assert len(calls) == 1


@pytest.mark.parametrize("name,category,caption", [
    ("Adamas port", "hotel", "WHERE TO STAY: We based ourselves in Adamas port, the perfect spot to explore from."),
    ("Plaka", "hotel", "WHERE TO STAY: Stay up in Plaka, the dreamy hilltop capital."),
    ("Sarakiniko", "activity", "WHERE TO STAY: A small hotel. BEST BEACH: Sarakiniko, hands down. WHERE TO EAT: Cafe Blue."),
    ("Firiplaka", "activity", "BEST BEACH: Sarakiniko, hands down. Also loved Firiplaka and Papafragkas! WHERE TO EAT: Cafe Blue."),
    ("Myrtos Beach", "attraction", "Don't miss: • Myrtos Beach (go early or stay for sunset) • Cafe Blue"),
    ("Kleftiko", "activity", "DON’T SKIP: A boat tour to Kleftiko. The sea caves are beautiful."),
    ("Elafonissi", "attraction", "Elafonissi ha sabbia rosa e davanti c’è un isolotto con altre spiagge."),
])
def test_target_specific_area_evidence_survives_mixed_lists_and_inferred_category(name, category, caption):
    assert research.source_area_intent(place_name=name, category=category, source_caption=caption)


@pytest.mark.parametrize("name,caption", [
    ("Lake Atitlan", "This unnamed hotel overlooks Lake Atitlan."),
    ("Beach House", "This Airbnb is called Beach House."),
    ("Beach House", "Stay at Beach House. BEST BEACH: White Beach."),
    ("Plaka", "WHERE TO STAY: The best hotel in Plaka."),
    ("Kleftiko", "Skip Kleftiko. Visit somewhere else."),
])
def test_target_repairs_do_not_create_area_pins_for_accommodation_or_negative_mentions(name, caption):
    assert not research.source_area_intent(place_name=name, category="hotel", source_caption=caption)


def test_shared_island_is_region_and_eating_section_repairs_activity_only():
    caption = "Meet Milos, this little island is wonderful. WHERE TO EAT: Egoist (if you’re looking for breakfast heaven). WHERE TO STAY: Blue House."
    fields, proof, dropped, area = research.source_search_context(place_name="Egoist", city="Milos", country="Greece", category="activity", source_caption=caption)
    assert fields["city"] is None and fields["region_or_neighborhood"] == "Milos"
    assert fields["category"] == "food" and not area and dropped == ["city"]
    assert proof["region_or_neighborhood"] == {"source": "caption", "quote": "Meet Milos"}
    fields, *_ = research.source_search_context(place_name="Blue House", country="Greece", category="hotel", source_caption=caption)
    assert fields["category"] == "hotel"


def test_comparison_islands_do_not_supply_shared_region():
    caption = "Skip Santorini and Mykonos. WHERE TO EAT: Egoist."
    fields, *_ = research.source_search_context(place_name="Egoist", country="Greece", category="activity", source_caption=caption)
    assert fields["region_or_neighborhood"] is None


def test_multiple_island_introductions_do_not_supply_shared_region():
    caption = "Meet Alpha, this island is beautiful. Meet Beta, this island is great. WHERE TO EAT: Blue Cafe."
    fields, *_ = research.source_search_context(place_name="Blue Cafe", country="Greece", category="cafe", source_caption=caption)
    assert fields["region_or_neighborhood"] is None


@pytest.mark.parametrize("city,caption", [
    ("Athens", "Meet Milos, this island is beautiful. WHERE TO EAT: Blue Cafe in Athens."),
    (None, "Meet Milos, this island is beautiful. Next stop: Athens. WHERE TO EAT: Blue Cafe."),
])
def test_island_context_does_not_cross_itinerary_or_saved_city(city, caption):
    fields, *_ = research.source_search_context(place_name="Blue Cafe", city=city, country="Greece", category="cafe", source_caption=caption)
    assert fields["region_or_neighborhood"] is None


def test_valley_or_lake_context_is_not_a_street_address_city():
    fields, *_ = research.source_search_context(place_name="Eden Boutique Hotel", city="Dades Valley", country="Morocco", region_or_neighborhood="Dades Valley", category="hotel", source_caption="Eden Boutique Hotel in Dades Valley, Morocco.")
    assert fields["city"] is None and fields["region_or_neighborhood"] == "Dades Valley"


def test_substring_of_venue_name_is_not_independent_city_evidence():
    fields, *_ = research.source_search_context(place_name="Sipadan Kapalai Dive Resort", city="Sipadan Kapalai", country="Malaysia", category="hotel", source_caption="Sipadan Kapalai Dive Resort in Sabah, Malaysia.")
    assert fields["city"] is None
    fields, *_ = research.source_search_context(place_name="Bath Spa Hotel", city="Bath", country="UK", category="hotel", source_caption="Bath Spa Hotel in Bath, UK.")
    assert fields["city"] == "Bath"


@pytest.mark.parametrize("category", ["hotel", "unknown", "activity"])
def test_unnamed_lakeside_rental_does_not_become_lake_pin(category):
    caption = ("comment LINK and we’ll send you the link to this dreamy lakeside stay in Lake Atitlan, Guatemala! "
               "(and other properties with the same view) #airbnbpartner What we loved about our stay: "
               "- private lake access for swimming - room is spacious yet cozy perfect for couples "
               "- accommodation is private w/ only one neighbor stay @airbnb #lakeatitlan #guatemala")
    assert not research.source_area_intent(place_name="Lake Atitlan", category=category, source_caption=caption)
    fields, _, _, area = research.source_search_context(place_name="Lake Atitlan", category=category, country="Guatemala", source_caption=caption)
    assert not area and fields["category"] == category


@pytest.mark.parametrize("name,city,category,caption", [
    (None, None, "activity", "Comment link for info! This property on @airbnb is a treehouse in Costa Rica."),
    ("Lake Atitlan", None, "hotel", "What a beautiful stay! Lake Atitlan is breathtaking. #AirbnbPartner"),
    (None, None, "unknown", "Deluxe room with view #fyp"),
    ("Seaweed Studio", None, "activity", "Seaweed studio on airbnb"),
    (None, "Mallorca", "hotel", "Comment HOTEL to receive the island’s most beautiful hotels."),
    (None, "Essaouira", "hotel", "The perfect itinerary, fly into Essaouira or Marrakesh!"),
    (None, "Taghazout", "hotel", "A beautiful hideaway. Comment Taghazout for the link to this unique stay."),
    ("Serifos", "Serifos", "hotel", "This stay had been on my bucket list. Comment SERIFOS and I will send the link. Greece | Greek Islands"),
    (None, None, "hotel", "a seaside greek island dream #waterfronthomes #airbnbfinds #beachvilla"),
])
def test_low_information_rental_sources_remain_unpinned(name, city, category, caption):
    assert not research.source_area_intent(place_name=name, city=city, category=category, source_caption=caption)


def test_exact_account_handle_supports_spaced_name_context_but_not_fuzzy_brand():
    fields, _, dropped, _ = research.source_search_context(place_name="Eden Boutique Hotel and Spa", city="Dades Valley",
        country="Morocco", region_or_neighborhood="Dades Valley", category="hotel",
        source_caption="Add @edenboutiquehotelandspa in the Dades Valley to your list.")
    assert fields["city"] is None and fields["region_or_neighborhood"] == "Dades Valley" and dropped == ["city"]
    fields, *_ = research.source_search_context(place_name="Hotel Genesis", city="Dades Valley", country="Morocco",
        category="hotel", source_caption="@hotelgenessis is in Dades Valley.")
    assert fields["city"] == "Dades Valley"


def test_direct_town_declaration_repairs_inferred_hotel_category_without_inventing_hotel_pin():
    caption = "ALTEA – ONE OF THE MOST BEAUTIFUL TOWNS IN SPAIN! Whitewashed houses and beautiful restaurants. Altea, Alicante."
    assert research.source_area_intent(place_name="Altea", category="hotel", source_caption=caption)
    assert not research.source_area_intent(place_name="Altea", category="hotel", source_caption="An unnamed hotel! " + caption)


@pytest.mark.parametrize("category,caption", [
    ("restaurant", "This unnamed restaurant in Altea has the best sunset views. Altea - one of the most beautiful towns in Spain!"),
    ("cafe", "This hidden cafe in Altea is our favorite. Altea is a beautiful town in Spain."),
    ("unknown", "This secret coffee shop overlooking Altea is lovely. Altea is a charming town in Spain."),
    ("unknown", "This hidden cafe in Altea is our favorite. Altea is a town in Spain. Explore Altea!"),
])
def test_town_declaration_does_not_approximate_unknown_food_business(category, caption):
    assert not research.source_area_intent(place_name="Altea", category=category, source_caption=caption)


@pytest.mark.parametrize("category", ["restaurant", "cafe", "hotel", "unknown"])
def test_town_guide_with_incidental_plural_restaurants_remains_area(category):
    caption = "ALTEA – ONE OF THE MOST BEAUTIFUL TOWNS IN SPAIN! Whitewashed houses and some beautiful restaurants. Altea, Alicante."
    assert research.source_area_intent(place_name="Altea", category=category, source_caption=caption)


@pytest.mark.parametrize("name", ["El Tunco", "Volcan Santa Ana", "El Zonte"])
def test_specific_natural_list_entries_are_areas_among_unrelated_hotels(name):
    caption = ("🍻 Cadejo Brewery - beer and views! 🌞 Sunsets in El Tunco - the sunsets are amazing. "
               "🌋 Volcan Santa Ana - a day hike to the tallest volcano in the country! "
               "🛖 Day pass at Atami Resort - ocean pools. 🌊 Sea caves - both El Zonte and El Tunco have some huge sea caves to explore.")
    assert research.source_area_intent(place_name=name, category="activity", source_caption=caption)


def test_emoji_inside_rental_caption_does_not_crop_lodging_evidence_into_area_pin():
    caption = "This dreamy lakeside stay 🌅 Lake Atitlan 🌴 with private rooms 🏡 @airbnb"
    assert not research.source_area_intent(place_name="Lake Atitlan", category="hotel", source_caption=caption)


@pytest.mark.parametrize("kwargs", [{"protected": True}, {"manual": True}, {"source_caption": ""},
    {"place_name": "hotel"}, {"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
    {"timeout_seconds": float("inf")}, {"protected_fields": "city"}])
def test_invalid_or_protected_inputs_skip_provider(kwargs):
    assert plan(**kwargs) == []


def test_external_budget_cancellation_is_not_swallowed(monkeypatch):
    provider(monkeypatch, error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        plan()
