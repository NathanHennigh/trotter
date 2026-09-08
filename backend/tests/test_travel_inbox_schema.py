import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Base, BookingObservation, Message, Segment, TravelInboxEvidence, TravelInboxItem, Trip, User,
)


INBOX_TABLES = {"travel_inbox_items", "travel_inbox_evidence"}


def migration():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0009_travel_inbox.py"
    spec = importlib.util.spec_from_file_location("travel_inbox_migration_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def engine_with_foreign_keys():
    engine = create_engine("sqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    return engine


def observation(user_id, suffix="one"):
    return BookingObservation(
        user_id=user_id, evidence_key=suffix.ljust(64, "0"), source_message_id=f"source-{suffix}",
        pnr="ABC123", travel_date="2025-02-18", dep_airport="IAH", arr_airport="DCA",
        flight_number="UA1540", ownership="other",
        facts={"passenger_names": ["Rachel Smith"], "immutable_original": suffix},
    )


def inbox_item(user_id, *, record_key="a" * 64):
    return TravelInboxItem(
        user_id=user_id, record_key=record_key, flight_key="f" * 64,
        passenger_name="Rachel Smith", passenger_key="rachel smith", reason="other_traveler",
    )


def test_migration_is_additive_and_preserves_every_existing_table_row_and_schema():
    engine = engine_with_foreign_keys()
    old_tables = [table for table in Base.metadata.sorted_tables if table.name not in INBOX_TABLES]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as db:
        user = User(email="nathan@example.com", travel_name_aliases=["Nate"])
        db.add(user)
        db.flush()
        trip = Trip(user_id=user.id, title="Keep this original trip")
        db.add(trip)
        db.flush()
        db.add_all([
            observation(user.id),
            Message(user_id=user.id, provider_msg_id="original-message", parse_evidence={"unrecognized": "keep"}),
            Segment(trip_id=trip.id, mode="flight", dep_airport="IAH", arr_airport="DCA",
                    dep_time=datetime(2025, 2, 18, 12), arr_time=datetime(2025, 2, 18, 15),
                    pnr="ABC123", flight_number="UA1540", meta_json={"original": [1, 2, 3]}),
        ])
        db.commit()
    with engine.begin() as connection:
        before_rows = {table.name: connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() for table in old_tables}
        before_schema = {name: sql for name, sql in connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all()}
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        for table in old_tables:
            assert connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() == before_rows[table.name]
        after_schema = {name: sql for name, sql in connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all()}
        assert {name: after_schema[name] for name in before_schema} == before_schema
        assert set(after_schema) - set(before_schema) == INBOX_TABLES
    inspector = inspect(engine)
    assert {index["name"] for index in inspector.get_indexes("travel_inbox_items")} == {
        "ix_travel_inbox_items_user_id", "ix_travel_inbox_items_flight_key",
    }
    assert {index["name"] for index in inspector.get_indexes("travel_inbox_evidence")} == {
        "ix_travel_inbox_evidence_observation_id",
    }
    with Session(engine) as db:
        item = inbox_item(db.query(User).one().id)
        db.add(item)
        db.flush()
        assert UUID(item.id).version == 4
        assert item.created_at.utcoffset() == timezone.utc.utcoffset(item.created_at)
        db.add(TravelInboxEvidence(item_id=item.id, observation_id=db.query(BookingObservation).one().id))
        db.commit()
        assert db.query(TravelInboxEvidence).count() == 1
    engine.dispose()


def test_link_lifecycle_retains_immutable_observations_and_stable_item_identity():
    engine = engine_with_foreign_keys()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="nathan@example.com")
        db.add(user)
        db.flush()
        first, second = observation(user.id), observation(user.id, "two")
        item = inbox_item(user.id)
        db.add_all([first, second, item])
        db.flush()
        item_id, first_id, second_id = item.id, first.id, second.id
        db.add(TravelInboxEvidence(item_id=item_id, observation_id=first_id))
        db.commit()
        db.add(TravelInboxEvidence(item_id=item_id, observation_id=second_id))
        db.commit()
        assert db.query(TravelInboxItem).one().id == item_id
        assert db.query(TravelInboxEvidence).count() == 2
        with pytest.raises(IntegrityError):
            db.delete(db.get(BookingObservation, first_id))
            db.commit()
        db.rollback()
        assert db.get(BookingObservation, first_id).facts["immutable_original"] == "one"
        db.delete(db.get(TravelInboxItem, item_id))
        db.commit()
        assert db.query(TravelInboxEvidence).count() == 0
        assert {row.id for row in db.query(BookingObservation).all()} == {first_id, second_id}
    engine.dispose()


def test_owner_scoped_identity_and_evidence_links_reject_duplicates():
    engine = engine_with_foreign_keys()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first_user, second_user = User(email="one@example.com"), User(email="two@example.com")
        db.add_all([first_user, second_user])
        db.flush()
        first, other_owner = inbox_item(first_user.id), inbox_item(second_user.id)
        source = observation(first_user.id)
        db.add_all([first, other_owner, source])
        db.commit()
        assert first.id != other_owner.id
        with pytest.raises(IntegrityError):
            db.add(inbox_item(first_user.id))
            db.commit()
        db.rollback()
        db.add(TravelInboxEvidence(item_id=first.id, observation_id=source.id))
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(TravelInboxEvidence(item_id=first.id, observation_id=source.id))
            db.commit()
        db.rollback()
        assert db.query(TravelInboxItem).count() == 2
        assert db.query(TravelInboxEvidence).count() == 1
        with pytest.raises(IntegrityError):
            invalid = inbox_item(first_user.id, record_key="x" * 64)
            invalid.reason = "invite_sent"
            db.add(invalid)
            db.commit()
        db.rollback()
    engine.dispose()


def test_downgrade_cannot_drop_retained_ticket_evidence():
    with pytest.raises(RuntimeError, match="retain the additive inbox and evidence tables"):
        migration().downgrade()
