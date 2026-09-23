import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import Base, DreamEnrichmentJob


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0012_dream_enrichment_jobs.py"
    spec = importlib.util.spec_from_file_location("dream_enrichment_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_all_original_tables_and_matches_model():
    engine = create_engine("sqlite://")
    tables = [table for table in Base.metadata.sorted_tables if table.name != "dream_enrichment_jobs"]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        connection.execute(Base.metadata.tables["users"].insert().values(id=1, email="fixture@example.invalid"))
        connection.execute(Base.metadata.tables["dreams"].insert().values(id=1, user_id=1, title="Original board"))
        connection.execute(Base.metadata.tables["dream_items"].insert().values(id=1, user_id=1, dream_id=1,
                           source_url="https://example.invalid/original", caption="Original caption"))
        before = {table.name: connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() for table in tables}
        schemas = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='table'").all())
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        assert before == {table.name: connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() for table in tables}
        after = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='table'").all())
        assert schemas == {key: after[key] for key in schemas}
        assert set(after) - set(schemas) == {"dream_enrichment_jobs"}
    assert {(column["name"], column["nullable"]) for column in inspect(engine).get_columns("dream_enrichment_jobs")} == {
        (column.name, column.nullable) for column in DreamEnrichmentJob.__table__.columns}


def test_postgresql_ddl_and_nondestructive_downgrade():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE dream_enrichment_jobs" in ddl and "ALTER TABLE" not in ddl
    assert "UNIQUE (item_id)" in ddl
    assert "TIMESTAMP WITH TIME ZONE" in str(CreateTable(DreamEnrichmentJob.__table__).compile(dialect=postgresql.dialect()))
    with Operations.context(context), pytest.raises(RuntimeError, match="Refusing to delete"):
        migration().downgrade()
    assert output.getvalue() == ddl
