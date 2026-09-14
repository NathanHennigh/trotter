import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.models import Base, Dream, DreamItem, DreamLocation, User


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0010_dream_locations.py"
    spec = importlib.util.spec_from_file_location("dream_locations_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_every_old_table_schema_and_raw_row():
    engine = create_engine("sqlite://")
    old_tables = [table for table in Base.metadata.sorted_tables if table.name != "dream_locations"]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as db:
        db.add(User(id=1, email="fixture@example.invalid"))
        db.add(Dream(id=1, user_id=1, title="My original board"))
        db.flush()
        db.add(DreamItem(id=1, user_id=1, dream_id=1, source_url="https://example.invalid/original",
                         caption="Original caption", summary="Private notes", place_name="A named place",
                         needs_google_places_lookup=False, raw_metadata_json={"legacy": ["untouched"]}))
        db.commit()
    with engine.begin() as connection:
        before_rows = {table.name: connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() for table in old_tables}
        before_schema = dict(connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all())
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        for table in old_tables:
            assert connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() == before_rows[table.name]
        after_schema = dict(connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all())
        assert {name: after_schema[name] for name in before_schema} == before_schema
        assert set(after_schema) - set(before_schema) == {"dream_locations"}
    columns = inspect(engine).get_columns("dream_locations")
    assert {(column["name"], column["nullable"]) for column in columns} == {
        (column.name, column.nullable) for column in DreamLocation.__table__.columns}
    engine.dispose()


def test_postgresql_migration_and_model_ddl_compile_and_downgrade_preserves_evidence():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE dream_locations" in ddl
    assert "ALTER TABLE" not in ddl and "DELETE" not in ddl.replace("ON DELETE CASCADE", "")
    assert "UNIQUE (item_id)" in ddl
    model_ddl = str(CreateTable(DreamLocation.__table__).compile(dialect=postgresql.dialect()))
    assert "TIMESTAMP WITH TIME ZONE" in model_ddl
    before = output.getvalue()
    with Operations.context(context), pytest.raises(RuntimeError, match="Refusing to delete"):
        migration().downgrade()
    assert output.getvalue() == before
