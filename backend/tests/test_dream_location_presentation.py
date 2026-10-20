"""Map presentation never reinterprets missing source data as a provider error."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.dream_location_presentation import location_presentation


def item(**changes):
    return SimpleNamespace(**dict(
        {"place_name": None, "city": None, "country": "Greece", "category": "hotel",
         "region_or_neighborhood": None, "caption": "A seaside Greek island stay.",
         "summary": "A beautiful stay", "source_url": "https://www.instagram.com/reel/example/"},
        **changes,
    ))


@pytest.mark.parametrize("precision,state", [("place", "place"), ("area", "area"), (None, "place")])
def test_current_pin_wins_over_failed_refresh(precision, state):
    result = location_presentation(item(), has_pin=True, coordinate_precision=precision,
                                   location_status="failed", enrichment_status="failed")
    assert result["location_state"] == state
    assert result["location_reason"] == "resolved_" + state


@pytest.mark.parametrize("kwargs", [
    {"location_status": "queued"}, {"location_status": "running"},
    {"sorting_state": "queued"}, {"sorting_state": "running"},
    {"enrichment_status": "queued"}, {"enrichment_status": "running"},
])
def test_active_work_is_not_reported_as_missing_source(kwargs):
    assert location_presentation(item(caption="Comment LINK for the location."), **kwargs)["location_state"] == "processing"


@pytest.mark.parametrize("kwargs,reason", [
    ({"location_status": "failed"}, "processing_failed"),
    ({"location_status": "blocked"}, "provider_unavailable"),
    ({"sorting_state": "failed"}, "processing_failed"),
    ({"enrichment_status": "failed", "sorting_state": "sorted"}, "processing_failed"),
])
def test_processing_failure_is_never_blame_on_post(kwargs, reason):
    result = location_presentation(item(caption="Comment LINK for the location."), **kwargs)
    assert result["location_state"] == "unavailable"
    assert result["location_reason"] == reason


@pytest.mark.parametrize("status", ["resolved", "manual"])
def test_resolved_without_current_coordinates_does_not_claim_a_pin(status):
    assert location_presentation(item(), location_status=status)["location_reason"] == "location_unavailable"


def test_ambiguous_candidate_is_not_an_unnamed_post():
    assert location_presentation(item(place_name="Mô-Mô"), location_status="needs_review")["location_reason"] == "ambiguous_match"


@pytest.mark.parametrize("name,caption", [
    ("Seaweed Studio", "Seaweed studio on Airbnb"),
    ("Beautiful Life Rooms", "Beautiful Life Rooms in Milos"),
    ("Lakeview Lodge", "Lakeview Lodge is on Airbnb. Comment LINK for the location."),
    ("Serenya", "Serenya in Marrakech. Comment LINK for details."),
    ("Hotel Genessis", ""),
])
def test_named_business_miss_never_becomes_source_omission(name, caption):
    result = location_presentation(item(place_name=name, country=None, caption=caption), location_status="not_found")
    assert result["location_reason"] == "named_unresolved"


@pytest.mark.parametrize("caption", [
    "Comment ‘link’ for the info! I saw this property on @airbnb in Costa Rica.",
    "comment LINK and we’ll send you the link to this dreamy lakeside stay in Lake Atitlan, Guatemala!",
    "📍comment [ DUNE ] for location #travel #hotel",
    "Comment HOTEL and make sure to follow to receive the list of the island’s most beautiful hotels",
    "Follow + comment \"Taghazout\" and I’ll send the link to this unique stay.",
    "Comment “SERIFOS” and I will send you the link 🔗 Greece",
    "DM me for the address of this hotel.",
    "Message me to get the booking link.",
])
def test_explicit_creator_location_offers_have_clear_nonerror_hint(caption):
    result = location_presentation(item(caption=caption), location_status="not_found")
    assert result["location_state"] == "source_details"
    assert result["location_reason"] == "creator_link_required"
    assert "Open the post" in result["location_hint"]


@pytest.mark.parametrize("caption", [
    "Comment your favorite hotel in Greece!",
    "Comment below. The location is amazing.",
    "Like and follow for more stays!",
    "No need to comment for the link; the name is in the video.",
])
def test_engagement_without_offer_does_not_claim_creator_link_required(caption):
    result = location_presentation(item(caption=caption), location_status="not_found")
    assert result["location_reason"] != "creator_link_required"


def test_unnamed_lake_airbnb_does_not_become_a_named_area():
    saved = item(place_name="Lake Atitlan", country="Guatemala",
                 caption="Comment LINK and we'll send you the link to this dreamy lakeside stay in Lake Atitlan, Guatemala! #airbnbpartner")
    result = location_presentation(saved, location_status="not_found")
    assert result["location_reason"] == "creator_link_required"


def test_actual_named_lake_remains_recoverable_geographic_miss():
    saved = item(place_name="Lake Atitlan", country="Guatemala", category="nature",
                 caption="Visit Lake Atitlan in Guatemala.")
    assert location_presentation(saved, location_status="not_found")["location_reason"] == "named_unresolved"


@pytest.mark.parametrize("name,caption", [
    ("Coffee shops in Mexico City #coffee #cdmx #cafe", "Coffee shops in Mexico City #coffee #cdmx #cafe"),
    ("Deluxe room with view", "Deluxe room with view #fyp"),
    ("My favorite place on earth", "My favorite place on earth"),
    (None, "Morocco together? A dream hotel in the Moroccan desert."),
])
def test_generic_legacy_names_are_saved_inspiration(name, caption):
    assert location_presentation(item(place_name=name, caption=caption), location_status="not_found")["location_reason"] == "identity_not_shared"


@pytest.mark.parametrize("caption", [None, "", "   ", "https://www.instagram.com/reel/abc/"])
def test_missing_caption_has_its_own_state(caption):
    result = location_presentation(item(caption=caption), sorting_state="unavailable", enrichment_status="failed")
    assert result["location_reason"] == "caption_missing"


@pytest.mark.parametrize("caption", [
    "The perfect itinerary if you have 14 days and fly into Essaouira or Marrakesh.",
    "7 places to visit in October in Europe. Comment LINK for free travel guides.",
])
def test_broad_guides_do_not_get_one_fake_location(caption):
    result = location_presentation(item(caption=caption), location_status="not_found")
    assert result["location_reason"] == "broad_guide"


def test_named_stop_in_itinerary_does_not_become_broad_guide():
    saved = item(place_name="Cadejo Brewery", caption="El Salvador itinerary: visit Cadejo Brewery, then El Tunco.")
    assert location_presentation(saved, location_status="not_found")["location_reason"] == "named_unresolved"


@pytest.mark.parametrize("country", ["Greece", None])
def test_presentation_never_changes_item_or_guesses_country(country):
    saved = item(country=country, caption="This dream Airbnb. Comment LINK for the address.")
    before = deepcopy(vars(saved))
    location_presentation(saved, location_status="not_found")
    assert vars(saved) == before


def test_ignores_untrusted_provider_error_content():
    saved = item(raw_metadata_json={"error": "secret api key or arbitrary HTML"})
    result = location_presentation(saved, location_status="failed")
    assert "secret" not in str(result)
    assert "HTML" not in str(result)


@pytest.mark.parametrize("kwargs", [
    {"recovery_waiting": True, "enrichment_status": "queued"},
    {"recovery_waiting": True, "location_status": "blocked"},
    {"sorting_state": "retry_wait"},
])
def test_deferred_retry_is_quiet_and_does_not_blame_the_source(kwargs):
    result = location_presentation(item(caption="Comment LINK for the location."), **kwargs)
    assert result["location_state"] == "unavailable"
    assert result["location_reason"] == "provider_unavailable"
    assert "automatically" in result["location_hint"]


def test_existing_pin_remains_available_during_deferred_retry():
    result = location_presentation(item(), has_pin=True, coordinate_precision="place", recovery_waiting=True)
    assert result["location_state"] == "place"


def test_emoji_caption_is_uninformative_but_not_missing():
    assert location_presentation(item(caption="🏜️"))["location_reason"] == "identity_not_shared"


def test_untyped_failure_does_not_promise_retries_or_claim_provider_outage():
    result = location_presentation(item(), enrichment_status="failed")
    assert result["location_reason"] == "processing_failed"
    assert "automatically" not in result["location_hint"]
    assert "temporarily unavailable" not in result["location_hint"]
