"""Exercise SQL String limits that SQLite itself does not enforce."""
import ast
from pathlib import Path

from sqlalchemy import String, func, select

from app import models
from app.models import Base, ItineraryHistory
from test_booking_lifecycle_hardening import db_user
from test_booking_ticket_lifecycle import enable_ticket_reconciliation, ingest


def test_ticket_exchange_persisted_values_fit_declared_sql_lengths(db_user):
    db, user = db_user
    ingest(db, user, "old")
    ingest(db, user, "new")
    ingest(db, user, "reminder")
    db.flush()
    assert ItineraryHistory.__table__.c.entity_type.type.length == 16
    assert db.query(ItineraryHistory).filter_by(entity_type="ticket_exchange").count() == 2
    violations = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, String) and column.type.length:
                excessive = db.execute(select(column).where(func.length(column.cast(String)) > column.type.length)).scalars().all()
                if excessive:
                    violations.append((table.name, column.name, column.type.length, excessive))
    assert not violations


def test_model_constructor_literals_and_history_reasons_fit_sql_columns():
    """Catch new oversized labels before a dialect with real VARCHAR limits."""
    model_columns = {name: {column.name: column.type.length for column in value.__table__.columns
        if isinstance(column.type, String) and column.type.length}
        for name, value in vars(models).items() if isinstance(value, type) and hasattr(value, "__table__")}
    violations = []
    for path in (Path(__file__).parents[1] / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            limits = model_columns.get(node.func.id, {})
            if node.func.id == "snapshot_user_itinerary":
                limits = {"reason": ItineraryHistory.__table__.c.reason.type.length}
            for keyword in node.keywords:
                if (keyword.arg in limits and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str) and len(keyword.value.value) > limits[keyword.arg]):
                    violations.append((str(path), node.lineno, node.func.id, keyword.arg,
                                       keyword.value.value, limits[keyword.arg]))
    assert not violations
