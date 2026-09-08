"""Pure retention policy; no account lookup or database mutation is involved."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.travel_inbox_identity import retained_passengers


OWNER = "Alex Avery"
OTHER = "Morgan Blake"
UNASSIGNED = {"passenger_name": None, "passenger_key": None, "reason": "unassigned"}


def user(name=OWNER, aliases=None):
    return SimpleNamespace(name=name, travel_name_aliases=aliases or [], email="unrelated@example.test")


def traveler(name, **overrides):
    return {"name": name, "role": "traveler", "applies": True, "complete": True, **overrides}


def observation(ownership="other", evidence=None, **facts):
    return SimpleNamespace(ownership=ownership, facts={"passenger_evidence": evidence or [], **facts})


def named(name, reason="other_traveler", key=None):
    return {"passenger_name": name, "passenger_key": key or name.casefold(), "reason": reason}


@pytest.mark.parametrize("names", [[OWNER, OTHER], [OTHER, OWNER]])
def test_shared_self_flight_retains_companion_regardless_of_order(names):
    assert retained_passengers(observation("self", [traveler(name) for name in names]), user()) == [named(OTHER, "companion")]


def test_other_flight_retains_all_non_owner_travelers():
    result = retained_passengers(observation("other", [traveler(OTHER), traveler("Morgan Lane"), traveler(OWNER)]), user())
    assert result == [named(OTHER), named("Morgan Lane")]


def test_owner_only_self_flight_does_not_enter_other_travel_inbox():
    assert retained_passengers(observation("self", [traveler(OWNER)]), user()) == []


@pytest.mark.parametrize("ownership", ["unknown", None, "unrecognized"])
def test_unknown_ownership_is_one_unassigned_record_even_with_names(ownership):
    assert retained_passengers(observation(ownership, [traveler(OWNER), traveler(OTHER)]), user()) == [UNASSIGNED]


@pytest.mark.parametrize("ownership", ["self", "other"])
def test_missing_or_legacy_names_stay_unassigned(ownership):
    expected = [] if ownership == "self" else [UNASSIGNED]
    assert retained_passengers(observation(ownership, passenger_name=OTHER, passenger_names=[OTHER]), user()) == expected


def test_verified_self_without_names_does_not_invent_a_companion():
    assert retained_passengers(observation("self"), user(name=None)) == []


def test_verified_self_with_explicit_unnamed_traveler_preserves_one_unassigned():
    assert retained_passengers(observation("self", [traveler(OWNER), traveler(None)]), user()) == [UNASSIGNED]


def test_payers_contacts_and_unrelated_booking_names_are_not_retained():
    evidence = [traveler(OWNER), traveler("Card Owner", role="payer"),
                traveler("Email Recipient", role="recipient"), traveler("Different Booking", applies=False)]
    assert retained_passengers(observation("self", evidence), user()) == []


def test_ambiguous_scope_never_produces_a_named_person():
    evidence = [traveler(OWNER), traveler(OTHER, scope_ambiguous=True, applies=False)]
    assert retained_passengers(observation("self", evidence), user()) == [UNASSIGNED]


@pytest.mark.parametrize("name", ["Alex", "Avery", "A Avery", "A. Avery", "AVERY/A", "M Blake", "Dr. M Blake", "A. Avery Jr", None, "", "Unknown", "A.J. Avery", "Passenger Name", "Not Provided"])
def test_initials_partial_and_missing_names_are_unassigned(name):
    assert retained_passengers(observation("other", [traveler(name)]), user()) == [UNASSIGNED]


def test_valid_other_name_and_ambiguous_person_are_both_retained():
    result = retained_passengers(observation("other", [traveler(OTHER), traveler("M Blake"), traveler(None)]), user())
    assert result == [named(OTHER), UNASSIGNED]


def test_approved_alias_is_excluded_as_owner_but_not_merged_with_others():
    result = retained_passengers(observation("self", [traveler("Al Avery"), traveler(OTHER)]), user(aliases=["Al Avery"]))
    assert result == [named(OTHER, "companion")]


def test_approved_initial_does_not_hide_a_different_full_name():
    result = retained_passengers(observation("self", [traveler("Adrian Avery")]), user(aliases=["A Avery"]))
    assert result == [UNASSIGNED]


def test_unapproved_additional_middle_name_is_ambiguous_not_silently_owner():
    assert retained_passengers(observation("self", [traveler("Alex Jordan Avery")]), user()) == [UNASSIGNED]
    assert retained_passengers(observation("self", [traveler("Alex Jordan Avery")]),
                               user(aliases=["Alex Jordan Avery"])) == []


def test_reordered_owner_name_can_be_excluded_without_grouping_other_people():
    assert retained_passengers(observation("self", [traveler("AVERY/ALEX")]), user()) == []


def test_ambiguous_compound_surname_is_not_declared_another_person():
    assert retained_passengers(observation("other", [traveler("de la Cruz")]), user(name="Maria de la Cruz")) == [UNASSIGNED]


def test_only_unicode_case_and_whitespace_normalize_the_key():
    evidence = [traveler("  Élise\u00a0  Blake  "), traveler("E\u0301LISE BLAKE"),
                traveler("Elise Blake"), traveler("Blake Élise"), traveler("Élise Taylor Blake")]
    result = retained_passengers(observation("other", evidence), user())
    assert result == [named("Élise Blake", key="élise blake"), named("Elise Blake"),
                      named("Blake Élise"), named("Élise Taylor Blake")]


def test_punctuation_titles_and_middle_names_do_not_merge_people():
    names = ["Morgan O'Neil", "Morgan O’Neil", "Morgan Oneil", "Dr. Morgan Oneil", "Morgan A Oneil"]
    result = retained_passengers(observation("other", [traveler(name) for name in names]), user())
    assert [item["passenger_key"] for item in result] == [name.casefold() for name in names]


def test_fuzzy_nickname_and_family_resemblance_do_not_merge_retained_people():
    names = ["Morgan Blake", "Morgan Taylor Blake", "Morgana Blake", "Morgan Avery", "Al Avery"]
    result = retained_passengers(observation("other", [traveler(name) for name in names]), user())
    assert [item["passenger_name"] for item in result] == names


def test_user_decision_observations_are_excluded_from_automatic_projection():
    obs = observation("other", [traveler(OTHER)], user_decision={"ownership": "other", "status": "active"})
    assert retained_passengers(obs, user()) == []


def test_other_with_only_owner_evidence_remains_an_unassigned_conflict():
    assert retained_passengers(observation("other", [traveler(OWNER)]), user()) == [UNASSIGNED]


@pytest.mark.parametrize("evidence", [None, "bad", [None, "bad"], {"name": OTHER}, [traveler(OTHER, applies="true")]])
def test_malformed_evidence_is_not_treated_as_confident_identity(evidence):
    obs = SimpleNamespace(ownership="other", facts={"passenger_evidence": evidence})
    assert retained_passengers(obs, user()) == [UNASSIGNED]


def test_valid_single_evidence_dictionary_is_supported():
    obs = SimpleNamespace(ownership="other", facts={"passenger_evidence": traveler(OTHER)})
    assert retained_passengers(obs, user()) == [named(OTHER)]


def test_missing_account_name_is_not_replaced_by_email_or_account_lookup():
    assert retained_passengers(observation("other", [traveler(OTHER)]), user(name=None)) == [UNASSIGNED]


def test_mapping_inputs_and_projection_do_not_mutate_source_facts():
    obs = {"ownership": "self", "facts": {"passenger_evidence": [traveler(OWNER), traveler(OTHER)]}}
    account = {"name": OWNER, "travel_name_aliases": []}
    original = deepcopy((obs, account))
    assert retained_passengers(obs, account) == [named(OTHER, "companion")]
    assert (obs, account) == original


@pytest.mark.parametrize("ownership", ["self", "other"])
@pytest.mark.parametrize("oversized_name", ["A" * 250 + " Family", "ß" * 130 + " Family"])
def test_oversized_name_or_casefolded_key_retains_unassigned_without_losing_evidence(ownership, oversized_name):
    obs = observation(ownership, [traveler(OTHER), traveler(oversized_name), traveler(oversized_name)])
    original = deepcopy(obs.facts)
    reason = "companion" if ownership == "self" else "other_traveler"

    assert retained_passengers(obs, user()) == [named(OTHER, reason), UNASSIGNED]
    assert obs.facts == original


def test_identity_fields_at_255_character_limit_remain_named():
    name = "A" * 248 + " Family"
    assert len(name) == len(name.casefold()) == 255
    assert retained_passengers(observation("other", [traveler(name)]), user()) == [named(name)]
