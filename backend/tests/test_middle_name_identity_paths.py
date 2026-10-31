"""The same known traveler must resolve consistently across import and recovery."""
from copy import deepcopy

import pytest

from app.models import BookingObservation, MessageStatus, Segment, TravelInboxItem
from app.services.booking_reconciliation import matches
from app.services.parser import check_identity
from app.services.passenger_identity import identity_candidates
from app.services.travel_inbox import serialize_item
from app.services.travel_name_recovery import matching_evidence
from test_travel_name_recovery import api, confirm, receipt, run  # noqa: F401


@pytest.mark.parametrize("printed,owned", [
    ("Alex Avery", True),
    ("Alex Jordan Avery", True),
    ("AVERY/ALEXJORDAN", True),
    ("AlexJordan Avery", True),
    ("Alex Casey Avery", False),
    ("Alexandra Avery", False),
    ("Alex Jordan Avery Jr", False),
])
def test_import_and_recovery_share_full_name_precedence(api, printed, owned):
    api.user.name = "Alex Avery"
    api.user.travel_name_aliases = ["Alex Jordan Avery"]
    api.db.commit()
    names = [api.user.name, *api.user.travel_name_aliases]
    _, row = receipt(api, name=printed)
    original = deepcopy(row.facts)

    assert check_identity(printed, names[0], names[1:]) == (
        MessageStatus.ACCEPTED if owned else MessageStatus.REVIEW_REQUIRED)
    assert bool(matching_evidence(row, names)) is owned
    assert bool(matches(row, names)) is owned

    job = run(api, confirm(api, names[1:]))
    assert job.added == int(owned)
    assert api.db.query(Segment).count() == int(owned)
    assert api.db.get(BookingObservation, row.id).facts == original
    for item in api.db.query(TravelInboxItem):
        status = serialize_item(api.db, api.user.id, item)["status"]
        if not owned:
            assert status != "belongs_to_you"
        elif item.passenger_name:
            assert status == "belongs_to_you"


def test_explicit_alternative_middle_names_are_both_usable(api):
    api.user.name = "Alex Avery"
    api.db.commit()
    receipt(api, name="Alex Jordan Avery", day=9)
    receipt(api, name="Alex Casey Avery", day=11)
    job = run(api, confirm(api, ["Alex Jordan Avery", "Alex Casey Avery"]))
    assert job.added == 2
    assert api.db.query(Segment).count() == 2


def test_saved_full_name_does_not_promote_billing_contact(api):
    api.user.name = "Alex Avery"
    api.db.commit()
    receipt(api, name="Alex Jordan Avery", evidence=[{
        "name": "Alex Jordan Avery", "role": "payer", "applies": True,
        "complete": True,
    }])
    job = run(api, confirm(api, ["Alex Jordan Avery"]))
    assert job.added == 0
    assert api.db.query(Segment).count() == 0


@pytest.mark.parametrize("primary,aliases,own,other", [
    ("Alex Avery", ["AVERY/ALEX JORDAN"], "AVERY/ALEXJORDAN", "Alex Casey Avery"),
    ("Alex Avery", ["Avery, Alex Jordan"], "AlexJordan Avery", "Alex Casey Avery"),
    ("AVERY/ALEX", ["Alex Jordan Avery"], "Alex Avery", "Alex Casey Avery"),
    ("Alex Avery Jr", ["Alex Jordan Avery Jr"], "AVERY JR/ALEX", "Alex Casey Avery Jr"),
    ("Alex Avery Jr", ["AVERY JR/ALEX JORDAN"], "AlexJordan Avery Jr", "Alex Casey Avery Jr"),
    ("Alex Avery", ["Alex J Avery", "Alex Jordan Avery"], "Alex Avery", "Alex James Avery"),
])
def test_confirmed_name_precedence_handles_printed_formats(primary, aliases, own, other):
    assert check_identity(own, primary, aliases) == MessageStatus.ACCEPTED
    assert check_identity(other, primary, aliases) == MessageStatus.REVIEW_REQUIRED


def test_pruning_does_not_change_stored_aliases_or_drop_distinct_explicit_names():
    aliases = ["Alex Jordan Avery", "Alex Casey Avery", "Alex Blake", "Alex Avery Jr"]
    original = list(aliases)
    assert identity_candidates("Alex Avery", aliases) == aliases
    assert aliases == original


def test_compound_family_names_are_not_inferred_to_be_middle_names():
    assert identity_candidates("Maria Cruz", ["Maria de la Cruz"]) == ["Maria Cruz", "Maria de la Cruz"]
