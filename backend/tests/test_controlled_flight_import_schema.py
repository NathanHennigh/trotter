"""Upgrade/rollback and private-data lifecycle for durable import state."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, delete, inspect, text
from sqlalchemy.orm import Session

from app.models import Base, BookingRepairManifest, GmailHistoryState, User


@pytest.fixture
def engine():
    value = create_engine("sqlite:///:memory:")
    with value.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.commit()
    yield value
    value.dispose()


def test_migration_adds_only_new_tables_and_downgrade_preserves_user(engine):
    User.__table__.create(engine)
    with Session(engine) as db:
        db.add(User(id=1, email="traveler@example.test", name="Example Traveler", travel_name_aliases=["Example Previousname"]))
        db.commit()
    path = Path(__file__).parents[1] / "alembic/versions/0024_controlled_flight_import.py"
    spec = importlib.util.spec_from_file_location("controlled_import_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        tables = inspect(connection).get_table_names()
        assert {"users", "gmail_history_states", "booking_repair_manifests"} == set(tables)
        for table in ("gmail_history_states", "booking_repair_manifests"):
            fk = inspect(connection).get_foreign_keys(table)[0]
            assert fk["referred_table"] == "users"
            assert fk["options"]["ondelete"] == "CASCADE"
        migration.downgrade()
        assert inspect(connection).get_table_names() == ["users"]
    with Session(engine) as db:
        assert db.get(User, 1).travel_name_aliases == ["Example Previousname"]


def test_history_and_repair_state_erased_only_with_their_owner(engine):
    Base.metadata.create_all(engine, tables=[User.__table__, GmailHistoryState.__table__, BookingRepairManifest.__table__])
    with Session(engine) as db:
        for user_id in (1, 2):
            db.add(User(id=user_id, email=f"traveler{user_id}@example.test", name="Example Traveler"))
        db.flush()
        for user_id in (1, 2):
            db.add(GmailHistoryState(user_id=user_id, pending_message_ids=[f"message-{user_id}"], state="queued"))
            db.add(BookingRepairManifest(user_id=user_id, base_fingerprint="a"*64, plan_hash="b"*64,
                manifest_json={"source_ids":[f"message-{user_id}"]}, preview_json={"added":1}))
        db.commit()
        db.execute(delete(User).where(User.id == 1))
        db.commit()
        assert [row.user_id for row in db.query(GmailHistoryState)] == [2]
        assert [row.user_id for row in db.query(BookingRepairManifest)] == [2]


def test_history_defaults_are_independent_per_account(engine):
    Base.metadata.create_all(engine, tables=[User.__table__, GmailHistoryState.__table__])
    with Session(engine) as db:
        db.add_all([User(id=n, email=f"p{n}@example.test") for n in (1,2)])
        db.flush()
        db.add_all([GmailHistoryState(user_id=n) for n in (1,2)])
        db.commit()
        rows = db.query(GmailHistoryState).order_by(GmailHistoryState.user_id).all()
        assert [(row.state, row.attempts, row.scanned_count, row.pending_message_ids) for row in rows] == [
            ("pending", 0, 0, []), ("pending", 0, 0, [])]
