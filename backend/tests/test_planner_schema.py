import importlib.util
from pathlib import Path
import subprocess
import sys

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base, Trip, User
from app.planner_models import PlannerTrip


@pytest.mark.parametrize("first", ["app.models", "app.planner_models", "app.services.planner_geography"])
def test_model_and_pure_geography_import_orders_register_matching_hooks(first):
    script = f"""
import {first}
from app.models import DreamItem
from app.planner_models import PlannerIdea
from app.services.planner_geography import geography, maintain_geography, maintain_idea_match_key
from sqlalchemy import event
assert geography('MA', 'Marrakech') == ('morocco', 'marrakesh')
assert event.contains(DreamItem, 'before_insert', maintain_geography)
assert event.contains(PlannerIdea, 'before_update', maintain_idea_match_key)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def migration(filename="0018_collaborative_planner.py"):
    path = Path(__file__).parents[1] / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location("planner_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATCHING_COLUMNS = {"dream_items": {"planner_country_key", "planner_city_key", "planner_place_key"},
    "planner_trips": {"match_country_key", "match_city_key"},
    "planner_members": {"dream_auto_share", "dream_consented_at", "dream_last_synced_at", "dream_sync_item_id"},
    "planner_ideas": {"dream_match_key", "region_or_neighborhood"}}


def matching_migration():
    return migration("0019_planner_dream_matching.py")


def transport_migration():
    return migration("0020_planner_transport_modes.py")


def test_frozen_additive_schema_matches_models_preserves_rows_and_downgrades_only_empty():
    engine = create_engine("sqlite:///:memory:")
    old_tables = [t for t in Base.metadata.sorted_tables if not t.name.startswith("planner_")]
    Base.metadata.create_all(engine, tables=old_tables)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP INDEX ix_dream_planner_geography')
        for column in MATCHING_COLUMNS["dream_items"]:
            conn.exec_driver_sql(f'ALTER TABLE dream_items DROP COLUMN {column}')
    with Session(engine) as db:
        user = User(email="owner@example.com")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(Trip(user_id=user.id, title="Original trip"))
        db.commit()
    with engine.begin() as conn:
        old_rows = {t.name: conn.exec_driver_sql(f'SELECT * FROM "{t.name}"').all() for t in old_tables}
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        for name, rows in old_rows.items():
            assert conn.exec_driver_sql(f'SELECT * FROM "{name}"').all() == rows
    names = [t.name for t in Base.metadata.sorted_tables if t.name.startswith("planner_")]
    assert len(names) == 10
    for name in names:
        later = MATCHING_COLUMNS.get(name, set()) | ({"transport_modes"} if name == "planner_trips" else set())
        assert {c["name"] for c in inspect(engine).get_columns(name)} == set(Base.metadata.tables[name].columns.keys()) - later
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration().downgrade()
            migration().upgrade()
            matching_migration().upgrade()
            matching_migration().downgrade()
            matching_migration().upgrade()
            transport_migration().upgrade()
    for name in names + ["dream_items"]:
        assert {c["name"] for c in inspect(engine).get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
    with Session(engine) as db:
        db.add(PlannerTrip(owner_id=user_id, client_request_id="test-request", request_hash="x"*64,
            title="Shared trip", destination="Morocco", start_date="2026-11-12", end_date="2026-11-14"))
        db.commit()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="discard"):
                migration().downgrade()
    assert migration().down_revision == "0017_flight_sharing"
    engine.dispose()


def test_transport_migration_preserves_every_existing_value_and_backfills_each_primary_mode():
    from app.planner_models import PlannerMember, PlannerRevision
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="transport-migration@example.com")
        db.add(user)
        db.flush()
        for mode in ("walk", "drive", "transit"):
            trip = PlannerTrip(owner_id=user.id, client_request_id=f"transport-{mode}", request_hash="x"*64,
                title=f"By {mode}", destination="Morocco", transport=mode,
                start_date="2026-11-12", end_date="2026-11-14", version=7)
            db.add(trip)
            db.flush()
            db.add(PlannerMember(trip_id=trip.id, user_id=user.id, role="owner"))
            revision = PlannerRevision(trip_id=trip.id, created_by=user.id, base_version=6, source="manual",
                plan={"days": [], "warnings": [], "unplaced_idea_ids": [], "private_test": "preserve as-is"})
            db.add(revision)
            db.flush()
            trip.accepted_revision_id = revision.id
        db.commit()
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE planner_trips DROP COLUMN transport_modes")
        original = {}
        for table in Base.metadata.tables:
            columns = [c["name"] for c in inspect(conn).get_columns(table)]
            original[table] = (columns, conn.exec_driver_sql(f'SELECT * FROM "{table}"').all())
        with Operations.context(MigrationContext.configure(conn)):
            transport_migration().upgrade()
        for table, (columns, rows) in original.items():
            projection = ','.join(f'"{c}"' for c in columns)
            assert conn.exec_driver_sql(f'SELECT {projection} FROM "{table}"').all() == rows
        import json
        for primary, modes in conn.exec_driver_sql("SELECT transport,transport_modes FROM planner_trips"):
            assert json.loads(modes) == [primary]
        assert next(c for c in inspect(conn).get_columns("planner_trips") if c["name"] == "transport_modes")["nullable"] is False
        with Operations.context(MigrationContext.configure(conn)):
            transport_migration().downgrade()
            transport_migration().upgrade()
        conn.exec_driver_sql("UPDATE planner_trips SET transport_modes='[\"walk\",\"transit\"]' WHERE transport='walk'")
        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="discard"):
                transport_migration().downgrade()
    assert transport_migration().down_revision == "0019_planner_dream_matching"
    engine.dispose()


def test_matching_migration_backfills_only_derived_fields_preserves_personal_and_shared_content():
    from app.models import Dream, DreamItem
    from app.planner_models import PlannerIdea, PlannerMember
    from app.services.planner_geography import place_match_key
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="migration@example.com")
        db.add(user)
        db.flush()
        dream = Dream(user_id=user.id, title="Private", country="MA")
        trip = PlannerTrip(owner_id=user.id, client_request_id="matching-migration", request_hash="x"*64,
            title="Shared", destination="Morocco", start_date="2026-11-12", end_date="2026-11-14")
        db.add_all([dream, trip])
        db.flush()
        db.add_all([DreamItem(user_id=user.id, dream_id=dream.id, source_url="https://example.com/reel",
            place_name="Café", country="MA", city="Marrakech", personal_note="private", caption="private caption"),
            PlannerMember(trip_id=trip.id, user_id=user.id, role="owner"),
            PlannerIdea(trip_id=trip.id, identity_key="x"*64, title="Café", country="MA", city="Marrakech")])
        db.commit()
    with engine.begin() as conn:
        for name in ("ix_dream_planner_geography", "ix_planner_member_dream_sync", "ix_planner_idea_dream_match", "ix_planner_idea_provider_match", "ix_planner_contribution_dream"):
            conn.exec_driver_sql(f'DROP INDEX {name}')
        for table, columns in MATCHING_COLUMNS.items():
            for column in columns:
                conn.exec_driver_sql(f'ALTER TABLE {table} DROP COLUMN {column}')
        original = {}
        for table in Base.metadata.tables:
            columns = [c["name"] for c in inspect(conn).get_columns(table)]
            original[table] = (columns, conn.exec_driver_sql(f'SELECT * FROM "{table}"').all())
        with Operations.context(MigrationContext.configure(conn)):
            matching_migration().upgrade()
        for table, (columns, rows) in original.items():
            projection = ','.join(f'"{c}"' for c in columns)
            assert conn.exec_driver_sql(f'SELECT {projection} FROM "{table}"').all() == rows
        key = place_match_key("Café", "MA", "Marrakech")
        assert conn.exec_driver_sql('SELECT planner_country_key,planner_city_key,planner_place_key FROM dream_items').one() == ("morocco", "marrakesh", key)
        assert conn.exec_driver_sql('SELECT dream_match_key FROM planner_ideas').scalar() == key
        conn.exec_driver_sql("UPDATE planner_trips SET match_country_key='morocco'")
        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="discard"):
                matching_migration().downgrade()
    assert matching_migration().down_revision == "0018_collaborative_planner"
    engine.dispose()
