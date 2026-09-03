"""Copy a Trotter SQLite database into an empty migrated PostgreSQL database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy import Engine, Enum as SqlEnum, MetaData, create_engine, func, inspect, select, text

from app.models import Base


def copy_database(source: Engine, target: Engine, *, truncate: bool = False) -> dict[str, int]:
    source_tables = set(inspect(source).get_table_names())
    target_tables = set(inspect(target).get_table_names())
    model_tables = [table for table in Base.metadata.sorted_tables if table.name in source_tables]
    source_metadata = MetaData()
    source_metadata.reflect(bind=source, only=[table.name for table in model_tables])

    missing_targets = [table.name for table in model_tables if table.name not in target_tables]
    if missing_targets:
        raise RuntimeError(f"Target database is missing migrated tables: {', '.join(missing_targets)}")

    copied: dict[str, int] = {}
    with source.connect() as source_connection, target.begin() as target_connection:
        populated = {
            table.name: target_connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in model_tables
        }
        nonempty = {name: count for name, count in populated.items() if count}
        if nonempty and not truncate:
            names = ", ".join(f"{name}={count}" for name, count in nonempty.items())
            raise RuntimeError(f"Target database is not empty ({names}); use --truncate to replace it")

        if truncate and model_tables:
            quoted = ", ".join(f'"{table.name}"' for table in reversed(model_tables))
            target_connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))

        for table in model_tables:
            source_table = source_metadata.tables[table.name]
            rows = [
                _normalize_row(dict(row._mapping), table)
                for row in source_connection.execute(select(source_table))
            ]
            if rows:
                target_connection.execute(table.insert(), rows)
            copied[table.name] = len(rows)

        if target.dialect.name == "postgresql":
            _reset_postgres_sequences(target_connection, model_tables)

    return copied


def _normalize_row(row: dict, target_table) -> dict:
    for column in target_table.columns:
        value = row.get(column.name)
        if value is None or not isinstance(column.type, SqlEnum) or not isinstance(value, str):
            continue
        enum_class = column.type.enum_class
        if enum_class is not None and value in enum_class.__members__:
            row[column.name] = enum_class.__members__[value]
    return row


def _reset_postgres_sequences(connection, tables) -> None:
    for table in tables:
        if len(table.primary_key.columns) != 1:
            continue
        column = next(iter(table.primary_key.columns))
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table.name, "column_name": column.name},
        ).scalar_one_or_none()
        if not sequence:
            continue
        maximum = connection.execute(select(func.max(column))).scalar_one_or_none()
        if maximum is None:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), 1, false)"),
                {"sequence": sequence},
            )
        else:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                {"sequence": sequence, "value": maximum},
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="SQLite URL or path")
    parser.add_argument("--target", default=os.getenv("DATABASE_URL"), help="Target PostgreSQL URL")
    parser.add_argument("--truncate", action="store_true", help="Replace existing target rows")
    args = parser.parse_args()

    source_value = args.source
    if "://" not in source_value:
        source_path = Path(source_value).resolve()
        if not source_path.is_file():
            raise SystemExit(f"SQLite source was not found: {source_path}")
        source_value = f"sqlite:///{source_path.as_posix()}"
    if not args.target:
        raise SystemExit("DATABASE_URL or --target is required")
    if not args.target.startswith(("postgresql://", "postgresql+psycopg://")):
        raise SystemExit("Target must be PostgreSQL")

    copied = copy_database(create_engine(source_value), create_engine(args.target), truncate=args.truncate)
    print("SQLite migration complete:")
    for table_name, row_count in copied.items():
        print(f"  {table_name}: {row_count}")


if __name__ == "__main__":
    main()
