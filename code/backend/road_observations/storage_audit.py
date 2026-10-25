"""Read-only database inspection helpers for migration readiness."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any, Callable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def inspect_sqlite_file(path: Path) -> dict[str, Any]:
    """Inspect a SQLite file through a read-only URI and return metadata only."""
    path = Path(path)
    result: dict[str, Any] = {
        "path": str(path),
        "backend": "sqlite",
        "status": "inconclusive",
        "exists": path.is_file(),
        "tables": [],
        "row_counts": {},
        "schema": {},
        "migration_history": [],
        "foreign_key_violations": {},
        "missing_foreign_key_targets": [],
    }
    if not result["exists"]:
        result["status"] = "missing"
        return result

    try:
        result["size_bytes"] = path.stat().st_size
        result["sha256"] = _sha256(path)
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as database:
            database.execute("PRAGMA query_only=ON")
            tables = [
                row[0]
                for row in database.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            table_set = set(tables)
            result["tables"] = tables

            for table in tables:
                quoted = _quote_identifier(table)
                columns = [
                    {
                        "name": row[1],
                        "type": row[2],
                        "not_null": bool(row[3]),
                        "primary_key_order": row[5],
                    }
                    for row in database.execute(f"PRAGMA table_info({quoted})")
                ]
                foreign_keys = [
                    {
                        "target_table": row[2],
                        "source_column": row[3],
                        "target_column": row[4],
                        "on_update": row[5],
                        "on_delete": row[6],
                    }
                    for row in database.execute(f"PRAGMA foreign_key_list({quoted})")
                ]
                indexes = []
                for index in database.execute(f"PRAGMA index_list({quoted})"):
                    index_name = index[1]
                    index_quoted = _quote_identifier(index_name)
                    indexes.append(
                        {
                            "unique": bool(index[2]),
                            "origin": index[3],
                            "partial": bool(index[4]) if len(index) > 4 else False,
                            "columns": [
                                row[2]
                                for row in database.execute(
                                    f"PRAGMA index_info({index_quoted})"
                                )
                            ],
                        }
                    )
                result["schema"][table] = {
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                    "indexes": sorted(indexes, key=lambda item: (item["origin"], item["columns"])),
                }
                result["row_counts"][table] = database.execute(
                    f"SELECT COUNT(*) FROM {quoted}"
                ).fetchone()[0]
                for foreign_key in foreign_keys:
                    if foreign_key["target_table"] not in table_set:
                        result["missing_foreign_key_targets"].append(
                            f"{table}.{foreign_key['source_column']} -> "
                            f"{foreign_key['target_table']}.{foreign_key['target_column']}"
                        )

            if "django_migrations" in table_set:
                result["migration_history"] = [
                    (row[0], row[1])
                    for row in database.execute(
                        "SELECT app, name FROM django_migrations ORDER BY app, name"
                    )
                ]

            try:
                violations: Counter[str] = Counter()
                for row in database.execute("PRAGMA foreign_key_check"):
                    # Do not retain or display row identifiers from violations.
                    violations[row[0]] += 1
                result["foreign_key_violations"] = dict(sorted(violations.items()))
                result["foreign_key_check"] = "complete"
            except sqlite3.DatabaseError as error:
                result["foreign_key_check"] = "inconclusive"
                result["foreign_key_error_type"] = type(error).__name__

        result["status"] = "inspected"
    except (OSError, sqlite3.DatabaseError, ValueError) as error:
        # SQLite errors may include a URI; keep diagnostic output sanitized.
        result["error_type"] = type(error).__name__
    return result


def compare_sqlite_files(
    left: dict[str, Any], right: dict[str, Any], *, compare_records: bool = True
) -> dict[str, Any]:
    """Compare schemas, aggregate counts, and primary-key rows without returning data."""
    comparison: dict[str, Any] = {
        "left": left.get("path", "left"),
        "right": right.get("path", "right"),
        "status": "inconclusive",
        "tables_only_left": [],
        "tables_only_right": [],
        "schema_differences": [],
        "row_count_differences": {},
        "rows_not_equal_by_key": {},
    }
    if left.get("status") != "inspected" or right.get("status") != "inspected":
        return comparison

    left_tables = set(left["tables"])
    right_tables = set(right["tables"])
    common = sorted(left_tables & right_tables)
    comparison["tables_only_left"] = sorted(left_tables - right_tables)
    comparison["tables_only_right"] = sorted(right_tables - left_tables)
    comparison["row_count_differences"] = {
        table: (left["row_counts"][table], right["row_counts"][table])
        for table in common
        if left["row_counts"][table] != right["row_counts"][table]
    }
    comparison["schema_differences"] = [
        table for table in common if left["schema"][table] != right["schema"][table]
    ]
    if not compare_records:
        comparison["record_comparison"] = "skipped_by_option"
        comparison["status"] = "inspected"
        return comparison

    left_path, right_path = Path(left["path"]), Path(right["path"])
    try:
        uri = left_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as database:
            database.execute("PRAGMA query_only=ON")
            database.execute("ATTACH DATABASE ? AS peer", (right_path.resolve().as_uri() + "?mode=ro",))
            row_differences: dict[str, dict[str, int]] = {}
            unkeyed_tables: list[str] = []
            for table in common:
                if table in comparison["schema_differences"]:
                    continue
                columns = [column["name"] for column in left["schema"][table]["columns"]]
                primary_keys = [
                    column["name"]
                    for column in sorted(
                        left["schema"][table]["columns"],
                        key=lambda column: column["primary_key_order"] or 999999,
                    )
                    if column["primary_key_order"]
                ]
                left_table = f"main.{_quote_identifier(table)}"
                right_table = f"peer.{_quote_identifier(table)}"
                if primary_keys:
                    join = " AND ".join(
                        f"source.{_quote_identifier(key)} = target.{_quote_identifier(key)}"
                        for key in primary_keys
                    )
                    key_missing = " OR ".join(
                        f"target.{_quote_identifier(key)} IS NULL" for key in primary_keys
                    )
                    values_equal = " AND ".join(
                        f"source.{_quote_identifier(column)} IS target.{_quote_identifier(column)}"
                        for column in columns
                    ) or "1"

                    def count_missing(source: str, target: str) -> int:
                        sql = (
                            f"SELECT COUNT(*) FROM {source} AS source "
                            f"LEFT JOIN {target} AS target ON {join} "
                            f"WHERE {key_missing}"
                        )
                        return database.execute(sql).fetchone()[0]

                    def count_changed_values(source: str, target: str) -> int:
                        sql = (
                            f"SELECT COUNT(*) FROM {source} AS source "
                            f"INNER JOIN {target} AS target ON {join} "
                            f"WHERE NOT ({values_equal})"
                        )
                        return database.execute(sql).fetchone()[0]

                    differences = {
                        "left_only": count_missing(left_table, right_table),
                        "right_only": count_missing(right_table, left_table),
                        "same_primary_key_different_values": count_changed_values(
                            left_table, right_table
                        ),
                    }
                elif columns:
                    unkeyed_tables.append(table)
                    selected = ", ".join(_quote_identifier(column) for column in columns)
                    left_difference = database.execute(
                        f"SELECT COUNT(*) FROM (SELECT {selected} FROM {left_table} "
                        f"EXCEPT SELECT {selected} FROM {right_table})"
                    ).fetchone()[0]
                    right_difference = database.execute(
                        f"SELECT COUNT(*) FROM (SELECT {selected} FROM {right_table} "
                        f"EXCEPT SELECT {selected} FROM {left_table})"
                    ).fetchone()[0]
                    differences = {
                        "left_distinct_tuples_only": left_difference,
                        "right_distinct_tuples_only": right_difference,
                    }
                else:
                    continue
                if any(differences.values()):
                    row_differences[table] = differences
            comparison["rows_not_equal_by_key"] = row_differences
            comparison["unkeyed_tables"] = unkeyed_tables
            comparison["record_comparison"] = (
                "inconclusive_for_tables_without_primary_keys" if unkeyed_tables else "complete"
            )
            comparison["status"] = "inspected"
    except (OSError, sqlite3.DatabaseError, ValueError) as error:
        comparison["record_comparison"] = "inconclusive"
        comparison["error_type"] = type(error).__name__
    return comparison


def inspect_postgresql_connection(
    connection: Any, read_only_transaction: Callable[[], Any]
) -> dict[str, Any]:
    """Read PostgreSQL catalog/statistics in a read-only transaction."""
    result: dict[str, Any] = {
        "backend": "postgresql",
        "status": "inconclusive",
        "tables": [],
        "approximate_row_counts": {},
        "migration_history": [],
        "unvalidated_foreign_key_constraints": None,
    }
    try:
        with read_only_transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT schemaname, relname, n_live_tup "
                    "FROM pg_stat_user_tables "
                    "WHERE schemaname = ANY(current_schemas(false)) "
                    "ORDER BY schemaname, relname"
                )
                rows = cursor.fetchall()
                result["tables"] = [row[1] for row in rows]
                result["approximate_row_counts"] = {
                    row[1]: max(0, int(row[2] or 0)) for row in rows
                }
                cursor.execute("SELECT to_regclass('django_migrations')")
                if cursor.fetchone()[0] is not None:
                    cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
                    result["migration_history"] = cursor.fetchall()
                cursor.execute(
                    "SELECT COUNT(*) FROM pg_constraint "
                    "WHERE contype = 'f' AND NOT convalidated"
                )
                result["unvalidated_foreign_key_constraints"] = int(cursor.fetchone()[0])
        result["status"] = "inspected"
        result["foreign_key_check"] = "validated_constraint_metadata_only"
    except Exception as error:  # Driver exceptions may embed the full connection URL.
        result["error_type"] = type(error).__name__
    return result


def render_sqlite_summary(snapshot: dict[str, Any]) -> str:
    """Format aggregate-only SQLite results; never include row values."""
    if snapshot.get("status") != "inspected":
        return (
            f"[INCONCLUSIVE] SQLite file {snapshot.get('path', '<unknown>')}: "
            f"{snapshot.get('error_type', snapshot.get('status', 'unknown'))}."
        )
    counts = ", ".join(
        f"{table}={count}" for table, count in sorted(snapshot["row_counts"].items())
    ) or "none"
    return (
        f"[PASS] SQLite file {snapshot['path']}: {snapshot['size_bytes']} bytes; "
        f"SHA-256 {snapshot['sha256']}; tables={len(snapshot['tables'])}; "
        f"migration rows={len(snapshot['migration_history'])}; row counts: {counts}; "
        f"foreign-key check={snapshot.get('foreign_key_check', 'not available')}."
    )


def render_postgresql_summary(report: dict[str, Any]) -> str:
    """Format PostgreSQL audit status without exposing driver exception text."""
    if report.get("status") != "inspected":
        return (
            "[INCONCLUSIVE] PostgreSQL inspection failed safely "
            f"({report.get('error_type', 'unknown error')}); URL and error details suppressed."
        )
    estimates = ", ".join(
        f"{table}~{count}"
        for table, count in sorted(report["approximate_row_counts"].items())
    ) or "none"
    return (
        f"[PASS] PostgreSQL catalog read; approximate table rows: {estimates}; "
        f"migration rows={len(report['migration_history'])}; "
        f"unvalidated foreign keys={report['unvalidated_foreign_key_constraints']}."
    )
