"""Explicit old/new schedule cells stay inside their dated flight card."""
from datetime import datetime, timezone

import pytest

from app.services.parser import parse_email


CARD = """Passenger(s):
TAYLOR/ALEX MORGAN
Aeromexico Confirmation Code:
TEST12
Expedia Confirmation Code:
AGENT1
Aeromexico Changed Your Flight Details
Your itinerary is updated. See changes in red below.
Sunday, Mar 14, 2027
Flight Change Details
Aeromexico
Flight Number
: AM901
From
: Managua (MGA-Airport)
To
: Mexico City (MEX-Airport)
Status
: CONFIRMED
Depart
:
1:49 PM
2:19 PM
(change)
Arrive
:
4:45 PM
5:10 PM
(change)
Class
: Coach
"""


def parse(text, *, html=False):
    return parse_email(html="<p>" + text.replace("\n", "</p><p>") + "</p>" if html else "",
        plain_text="" if html else text, attachments=[], subject="Your changed flight details",
        user_name="Alex Taylor", aliases=[], received_at=datetime(2027, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("html", [False, True])
def test_explicit_changed_clock_supersedes_old_value_in_same_field(html):
    flight, = parse(CARD, html=html).flights
    assert (flight.flight_number, flight.pnr, flight.pnr_aliases, flight.ownership) == ("AM901", "TEST12", ["AGENT1"], "self")
    assert not getattr(flight, "force_review", False)
    assert flight.time_provenance["departure"]["local"] == "2027-03-14T14:19:00"
    assert flight.time_provenance["arrival"]["local"] == "2027-03-14T17:10:00"
    proof = flight.time_provenance["date_evidence"]["clock_evidence"]
    assert proof["departure"]["selected"] == "2:19 PM"
    assert proof["departure"]["other_printed_clocks"] == ["1:49 PM"]
    assert proof["arrival"]["selected"] == "5:10 PM"


@pytest.mark.parametrize("departure", ["2:19 PM (change)\n1:49 PM", "1:49 PM\n2:19 PM (change)"])
def test_marker_controls_selection_independently_of_clock_order(departure):
    flight, = parse(CARD.replace("1:49 PM\n2:19 PM\n(change)", departure)).flights
    assert flight.time_provenance["departure"]["local"].endswith("14:19:00")


@pytest.mark.parametrize("departure", [
    "1:49 PM\n2:19 PM", "1:49 PM\n2:19 PM\nnote\n(change)",
    "1:49 PM (change)\n2:19 PM (change)", "1:49 PM\n2:19 PM\n3:19 PM\n(change)",
    "(change)\n1:49 PM\n2:19 PM", "1:49 PM (change)\n(change)",
])
def test_conflicting_or_unbound_clocks_cannot_activate_first_or_last_value(departure):
    result = parse(CARD.replace("1:49 PM\n2:19 PM\n(change)", departure))
    assert not any(not getattr(f, "force_review", False) for f in result.flights)


def test_change_marker_in_other_field_cannot_resolve_ambiguous_departure():
    result = parse(CARD.replace("2:19 PM\n(change)", "2:19 PM"))
    assert not any(not getattr(f, "force_review", False) for f in result.flights)


def test_marked_new_clock_does_not_override_unresolved_arrival_day():
    flight, = parse(CARD.replace("5:10 PM", "1:10 PM")).flights
    assert flight.force_review
    assert flight.time_provenance["date_evidence"]["status"] == "needs_review"
    assert flight.time_provenance["date_evidence"]["clock_evidence"]["arrival"]["selected"] == "1:10 PM"


def test_unmodified_single_clocks_keep_prior_metadata_contract():
    flight, = parse(CARD.replace("1:49 PM\n2:19 PM\n(change)", "2:19 PM")
        .replace("4:45 PM\n5:10 PM\n(change)", "5:10 PM")).flights
    assert not getattr(flight, "force_review", False)
    assert "clock_evidence" not in flight.time_provenance.get("date_evidence", {})
