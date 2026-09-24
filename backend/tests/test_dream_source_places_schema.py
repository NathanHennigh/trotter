"""Exercise the multi-place migration against a pre-change schema and rows."""
import importlib.util
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import Base


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0013_dream_source_places.py"
    spec = importlib.util.spec_from_file_location("dream_source_places_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_original_columns_rows_and_supports_siblings():
    engine = sa.create_engine("sqlite://")
    old = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name != "dream_source_posts":
            table.to_metadata(old)
    items = old.tables["dream_items"]
    for constraint in list(items.constraints):
        if constraint.name == "uq_dream_item_user_source_place" or isinstance(constraint, sa.ForeignKeyConstraint) and "source_post_id" in constraint.columns:
            items.constraints.remove(constraint)
    for index in list(items.indexes):
        if index.name == "ix_dream_items_source_post_id":
            items.indexes.remove(index)
    for name in ("source_post_id", "source_place_key", "source_place_index"):
        column = items.c[name]
        for fk in list(column.foreign_keys):
            items.foreign_keys.discard(fk)
        items._columns.remove(column)
    items.append_constraint(sa.UniqueConstraint("user_id", "source_url", name="uq_dream_item_user_source_url"))
    jobs = old.tables["dream_enrichment_jobs"]
    jobs._columns.remove(jobs.c.source_generation)
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(old.tables["users"].insert().values(id=1, email="schema@example.invalid"))
        conn.execute(old.tables["dreams"].insert().values(id=1, user_id=1, title="Morocco"))
        conn.execute(items.insert().values(id=10, user_id=1, dream_id=1, source_url="https://instagram.com/reel/source",
                                         caption="Original private caption", place_name="El Fenn", summary="Keep my notes"))
        conn.execute(jobs.insert().values(id=1, item_id=10, user_id=1, fingerprint="x", status="completed"))
        before = {table.name: conn.execute(sa.select(table)).all() for table in old.sorted_tables}
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        assert before == {table.name: conn.execute(sa.select(table)).all() for table in old.sorted_tables}
        assert conn.exec_driver_sql("SELECT source_post_id,source_place_key,source_place_index FROM dream_items").one() == (None, "primary", 0)
        conn.exec_driver_sql("INSERT INTO dream_source_posts(id,user_id,source_url,source_platform) VALUES (1,1,'https://instagram.com/reel/source','instagram')")
        conn.exec_driver_sql("UPDATE dream_items SET source_post_id=1 WHERE id=10")
        conn.execute(Base.metadata.tables["dream_items"].insert().values(id=11, user_id=1, dream_id=1,
            source_url="https://instagram.com/reel/source", source_post_id=1, source_place_key="bacha", place_name="Bacha Coffee"))
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM dream_items").scalar_one() == 2
    inspected = sa.inspect(engine)
    for name in ("dream_items", "dream_source_posts", "dream_enrichment_jobs"):
        assert {(c["name"], c["nullable"]) for c in inspected.get_columns(name)} == {
            (c.name, c.nullable) for c in Base.metadata.tables[name].columns}


def test_postgresql_ddl_changes_unique_identity_without_losing_places():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE dream_source_posts" in ddl
    assert "DROP CONSTRAINT uq_dream_item_user_source_url" in ddl
    assert "UNIQUE (user_id, source_url, source_place_key)" in ddl
    assert "DELETE FROM" not in ddl and "DROP TABLE" not in ddl
    with Operations.context(context), pytest.raises(RuntimeError, match="Refusing to discard"):
        migration().downgrade()
