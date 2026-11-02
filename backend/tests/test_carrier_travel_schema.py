"""The new evidence store must not rewrite existing account or flight data."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, CarrierTravelEvidence, Message, Segment, Trip, User


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0025_carrier_travel_evidence.py"
    spec = importlib.util.spec_from_file_location("carrier_evidence_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def database():
    engine = create_engine("sqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    return engine


def evidence(user_id):
    return CarrierTravelEvidence(user_id=user_id, evidence_key="e" * 64,
        source_message_id="original-carrier-message", source_sha256="s" * 64,
        evidence_version=1, received_at=datetime(2025, 3, 3, tzinfo=timezone.utc),
        kind="post_travel", carrier="AA", name="Alex", local_day="2025-03-01",
        dep_airport="SFO", arr_airport="JFK", facts={"ownership_authority": False})


def test_additive_migration_preserves_existing_schema_and_data_and_has_bounded_lookup_indexes():
    engine = database()
    prior_tables = [table for table in Base.metadata.sorted_tables if table.name != "carrier_travel_evidence"]
    Base.metadata.create_all(engine, tables=prior_tables)
    # Recreate the actual pre-migration schema: the date lookup index is new.
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_booking_observation_user_date")
    with Session(engine) as db:
        user = User(email="alex@example.test", name="Alex Rowan")
        db.add(user); db.flush()
        trip = Trip(user_id=user.id, title="Original title", visibility="private")
        db.add(trip); db.flush()
        db.add_all([
            Message(user_id=user.id, provider_msg_id="keep-original", parse_evidence={"original": True}),
            Segment(trip_id=trip.id, mode="flight", dep_airport="SFO", arr_airport="JFK",
                dep_time=datetime(2025, 3, 1, 10), arr_time=datetime(2025, 3, 1, 16),
                pnr="KEEP01", flight_number="AA101", meta_json={"original": [1, 2]}),
        ])
        db.commit()
    with engine.begin() as connection:
        before = {table.name: connection.execute(table.select()).all() for table in prior_tables}
        schema = dict(connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all())
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        assert all(connection.execute(table.select()).all() == before[table.name] for table in prior_tables)
        after_schema = dict(connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all())
        assert {name: after_schema[name] for name in schema} == schema
    indexes = inspect(engine).get_indexes("carrier_travel_evidence")
    assert any(index["name"] == "ix_booking_observation_user_date"
               and index["column_names"] == ["user_id", "travel_date"]
               for index in inspect(engine).get_indexes("booking_observations"))
    assert {tuple(index["column_names"]) for index in indexes} == {
        ("user_id", "carrier", "local_day"), ("user_id", "carrier", "pnr"), ("user_id", "source_message_id")}
    with Session(engine) as db:
        db.add(evidence(db.query(User).one().id)); db.commit()
        assert db.query(CarrierTravelEvidence).count() == 1
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration().downgrade()
        assert all(connection.execute(table.select()).all() == before[table.name] for table in prior_tables)
    assert all(index["name"] != "ix_booking_observation_user_date"
               for index in inspect(engine).get_indexes("booking_observations"))
    engine.dispose()


def test_evidence_is_account_scoped_unique_and_removed_only_with_its_account():
    engine = database(); Base.metadata.create_all(engine)
    with Session(engine) as db:
        first, second = User(email="first@example.test"), User(email="second@example.test")
        db.add_all([first, second]); db.flush()
        db.add_all([evidence(first.id), evidence(second.id)]); db.commit()
        with pytest.raises(IntegrityError):
            db.add(evidence(first.id)); db.commit()
        db.rollback()
        assert db.query(CarrierTravelEvidence).count() == 2
        db.delete(first); db.commit()
        assert db.query(CarrierTravelEvidence).one().user_id == second.id
    engine.dispose()
