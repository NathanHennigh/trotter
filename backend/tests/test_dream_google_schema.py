import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import Base, DreamGoogleIdentity


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0011_dream_google_identities.py"
    spec = importlib.util.spec_from_file_location("google_identity_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_google_identity_migration_preserves_all_original_tables():
    engine = create_engine("sqlite://")
    tables = [table for table in Base.metadata.sorted_tables if table.name != "dream_google_identities"]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO users (id,email) VALUES (1,'fixture@example.invalid')")
        before = {table.name: connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() for table in tables}
        schemas = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='table'").all())
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        assert before == {table.name: connection.exec_driver_sql(f'SELECT * FROM "{table.name}"').all() for table in tables}
        after = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='table'").all())
        assert schemas == {key: after[key] for key in schemas}
    assert {(column['name'],column['nullable']) for column in inspect(engine).get_columns('dream_google_identities')} == {(column.name,column.nullable) for column in DreamGoogleIdentity.__table__.columns}


def test_google_identity_postgresql_ddl_and_nondestructive_downgrade():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql":True,"output_buffer":output})
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE dream_google_identities" in ddl and "ALTER TABLE" not in ddl
    assert "latitude" not in ddl and "address" not in ddl and "payload" not in ddl
    assert "TIMESTAMP WITH TIME ZONE" in str(CreateTable(DreamGoogleIdentity.__table__).compile(dialect=postgresql.dialect()))
    with Operations.context(context), pytest.raises(RuntimeError, match="Refusing to delete"):
        migration().downgrade()
    assert output.getvalue() == ddl
