import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base, FlightShare, Trip, User


TABLES = {"flight_shares", "travel_inbox_assignments"}


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0017_flight_sharing.py"
    spec = importlib.util.spec_from_file_location("flight_sharing_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_migration_preserves_existing_rows_schema_and_matches_models():
    engine = create_engine("sqlite:///:memory:")
    old_tables = [table for table in Base.metadata.sorted_tables if table.name not in TABLES]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as db:
        user = User(email="owner@example.com")
        db.add(user)
        db.flush()
        db.add(Trip(user_id=user.id, title="Original trip"))
        db.commit()
    with engine.begin() as conn:
        rows = {table.name: conn.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() for table in old_tables}
        schema = dict(conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all())
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        after_schema = dict(conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all())
        assert {name: after_schema[name] for name in schema} == schema
        assert set(after_schema) - set(schema) == TABLES
        for table in old_tables:
            assert rows[table.name] == conn.exec_driver_sql(f'SELECT * FROM "{table.name}"').all()
    inspector = inspect(engine)
    for name in TABLES:
        assert {column["name"] for column in inspector.get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
    with Session(engine) as db:
        now = datetime.now(timezone.utc)
        share = FlightShare(sender_id=db.query(User).one().id, recipient_email="friend@example.com",
            passenger_name="Friend Person", client_request_id=str(uuid4()), request_hash="r" * 64,
            token_hash="t" * 64, token_encrypted=b"encrypted", item_ids=[], flights=[], status="pending",
            expires_at=now + timedelta(days=14), accepted_segment_ids=[])
        db.add(share)
        db.commit()
        assert db.query(FlightShare).count() == 1
        assert db.query(Trip).one().title == "Original trip"
    engine.dispose()


def test_migration_refuses_evidence_loss_on_downgrade():
    assert migration().down_revision == "0016_dream_matcher_version"
    with pytest.raises(RuntimeError, match="discard"):
        migration().downgrade()
