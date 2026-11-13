"""Empty ticket-reconciliation scopes never read unrelated account history."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.models import BookingObservation, FlightShare, Segment, Trip
from app.services import booking_ticket_lifecycle as lifecycle
from app.services import builder


def flight(*, airline="UA", ownership="self", pnr="TEST12", ticket=None):
    return SimpleNamespace(airline=airline, ownership=ownership, pnr=pnr, booking_ticket=ticket)


class NoDatabaseCalls:
    def __getattr__(self, name):
        raise AssertionError(f"Empty ticket scope attempted database operation: {name}")


@pytest.mark.parametrize("values", [
    [],
    [flight()],
    [flight(ownership="unknown")],
    [flight(airline="WN", ownership="other")],
    [flight(airline="WN", pnr=None)],
    [flight(airline="WN", ownership="unknown", pnr="  ")],
    [flight(airline="AS", pnr=None, ticket={"source": "typed_receipt"})],
    [flight(), flight(airline="B6"), flight(airline="NK"), flight(airline="F9", ownership="other")],
])
@pytest.mark.parametrize("use_generator", [False, True])
def test_empty_scope_returns_before_protection_queries(monkeypatch, values, use_generator):
    monkeypatch.setattr(lifecycle, "enabled", lambda user_id: True)
    monkeypatch.setattr(builder, "_protected_trip_ids", lambda *args, **kwargs: pytest.fail("Unused protection scan"))
    yielded = []

    def stream():
        for value in values:
            yielded.append(value)
            yield value

    before = deepcopy([vars(value) for value in values])
    assert lifecycle.reconcile_ticket_revisions(NoDatabaseCalls(), 17, stream() if use_generator else values) == (set(), 0, 0)
    assert [vars(value) for value in values] == before
    if use_generator:
        assert yielded == values


class QueryTrace:
    """No SQL engine: trace the actual ORM read boundaries without a database."""
    def __init__(self):
        self.reads = []
        self.flushes = 0

    def query(self, model):
        trace = self

        class Query:
            def join(self, *args): return self
            def filter(self, *args): return self
            def filter_by(self, **kwargs): return self
            def all(self):
                trace.reads.append(model)
                return []

        return Query()

    def flush(self):
        self.flushes += 1


@pytest.mark.parametrize("value", [
    flight(airline="WN"),
    flight(airline="WN", ownership="unknown"),
    flight(airline="AS", ticket={"source": "typed_receipt"}),
    flight(airline="UA", ownership="other", ticket={"source": "typed_receipt"}),
])
def test_nonempty_scope_retains_all_protection_reads(monkeypatch, value):
    monkeypatch.setattr(lifecycle, "enabled", lambda user_id: True)
    db = QueryTrace()
    before = deepcopy(vars(value))
    assert lifecycle.reconcile_ticket_revisions(db, 17, [value]) == (set(), 0, 0)
    assert db.reads == [Segment, Trip, BookingObservation, FlightShare, BookingObservation]
    # Existing competitor handling and final reconciliation each flush.
    assert db.flushes == 2
    assert vars(value) == before


def test_disabled_feature_still_does_not_consume_input_or_query(monkeypatch):
    monkeypatch.setattr(lifecycle, "enabled", lambda user_id: False)

    def unused():
        pytest.fail("Disabled reconciliation consumed input")
        yield flight(airline="WN")

    assert lifecycle.reconcile_ticket_revisions(NoDatabaseCalls(), 17, unused()) == (set(), 0, 0)
