import importlib.util
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models import Base


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0016_dream_matcher_version.py"
    spec = importlib.util.spec_from_file_location("dream_matcher_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_version_and_partial_index_preserve_all_original_rows_and_notes():
    engine = sa.create_engine("sqlite://")
    old = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(old)
    locations = old.tables["dream_locations"]
    locations.indexes = {index for index in locations.indexes if index.name != "ix_dream_locations_matcher_recovery"}
    locations._columns.remove(locations.c.matcher_version)
    locations._columns.remove(locations.c.matcher_retry_version)
    locations._columns.remove(locations.c.matcher_generation)
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(old.tables["users"].insert().values(id=1, email="owner@example.invalid"))
        conn.execute(old.tables["dreams"].insert().values(id=1, user_id=1, title="Original board"))
        for number, status in enumerate(("not_found", "manual", "resolved", "failed"), 1):
            conn.execute(old.tables["dream_items"].insert().values(id=number, user_id=1, dream_id=1,
                source_url=f"https://example.invalid/{number}", caption="Original caption", personal_note="Keep my private note"))
            conn.execute(locations.insert().values(id=number, item_id=number, user_id=1, fingerprint="source", pin_fingerprint="pin",
                status=status, generation=3, attempts=5, history=[{"reason": "original evidence"}]))
        before = {table.name: conn.execute(sa.select(table)).all() for table in old.sorted_tables}
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        assert before == {table.name: conn.execute(sa.select(table)).all() for table in old.sorted_tables}
        assert conn.exec_driver_sql("SELECT matcher_version FROM dream_locations").all() == [(0,)] * 4
        assert conn.exec_driver_sql("SELECT matcher_retry_version FROM dream_locations").all() == [(0,)] * 4
        assert conn.exec_driver_sql("SELECT matcher_generation FROM dream_locations").all() == [(0,)] * 4
        sql = conn.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='ix_dream_locations_matcher_recovery'").scalar_one()
        assert "WHERE status IN ('not_found', 'failed')" in sql
    assert set(Base.metadata.tables["dream_locations"].columns.keys()) == {col["name"] for col in sa.inspect(engine).get_columns("dream_locations")}


def test_postgres_upgrade_only_adds_version_index_and_downgrade_keeps_history():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "ADD COLUMN matcher_version INTEGER DEFAULT '0' NOT NULL" in ddl
    assert "ADD COLUMN matcher_retry_version INTEGER DEFAULT '0' NOT NULL" in ddl
    assert "ADD COLUMN matcher_generation INTEGER DEFAULT '0' NOT NULL" in ddl
    assert "CASE WHEN matcher_generation = generation THEN matcher_version ELSE 0 END" in ddl
    assert "WHERE status IN ('not_found', 'failed')" in ddl
    assert "UPDATE " not in ddl and "DELETE " not in ddl and "DROP " not in ddl
    with Operations.context(context), pytest.raises(RuntimeError, match="Refusing to discard"):
        migration().downgrade()
