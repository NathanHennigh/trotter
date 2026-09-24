import importlib.util
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models import Base


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0014_dream_area_precision.py"
    spec = importlib.util.spec_from_file_location("dream_area_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_area_migration_preserves_original_location_rows_and_every_other_table():
    engine = sa.create_engine("sqlite://")
    old = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(old)
    locations = old.tables["dream_locations"]
    locations._columns.remove(locations.c.coordinate_precision)
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(old.tables["users"].insert().values(id=1,email="owner@example.invalid"))
        conn.execute(old.tables["dreams"].insert().values(id=1,user_id=1,title="Original board"))
        conn.execute(old.tables["dream_items"].insert().values(id=1,user_id=1,dream_id=1,
            source_url="https://example.invalid/original",place_name="Original venue",caption="Original caption"))
        conn.execute(locations.insert().values(id=1,item_id=1,user_id=1,fingerprint="before",pin_fingerprint="pin",
            status="manual",latitude=4.1,longitude=2.3,message="Keep my manual pin"))
        before={table.name:conn.execute(sa.select(table)).all() for table in old.sorted_tables}
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        assert before == {table.name:conn.execute(sa.select(table)).all() for table in old.sorted_tables}
        assert conn.exec_driver_sql("SELECT coordinate_precision FROM dream_locations").scalar_one() is None
    assert {col['name'] for col in sa.inspect(engine).get_columns('dream_locations')} == set(Base.metadata.tables['dream_locations'].columns.keys())
    engine.dispose()


def test_area_migration_only_adds_column_and_refuses_destructive_downgrade():
    output=StringIO()
    context=MigrationContext.configure(dialect_name="postgresql",opts={"as_sql":True,"output_buffer":output})
    with Operations.context(context):
        migration().upgrade()
    assert output.getvalue().strip() == "ALTER TABLE dream_locations ADD COLUMN coordinate_precision VARCHAR(16);"
    with Operations.context(context),pytest.raises(RuntimeError,match="Refusing to discard"):
        migration().downgrade()
