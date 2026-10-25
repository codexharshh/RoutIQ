"""Read-only storage audit tests using temporary SQLite databases."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from road_observations.storage_audit import (
    compare_sqlite_files,
    inspect_postgresql_connection,
    inspect_sqlite_file,
    render_postgresql_summary,
    render_sqlite_summary,
)


def create_database(path: Path, statements: tuple[str, ...]) -> None:
    with closing(sqlite3.connect(path)) as database:
        for statement in statements:
            database.execute(statement)
        database.commit()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StorageAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="routiq-storage-audit-")
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_empty_file_is_inspected_without_being_modified(self):
        path = self.root / "empty.sqlite3"
        path.touch()
        before = file_hash(path)

        result = inspect_sqlite_file(path)

        self.assertEqual(result["status"], "inspected")
        self.assertEqual(result["tables"], [])
        self.assertEqual(result["row_counts"], {})
        self.assertEqual(file_hash(path), before)

    def test_same_schema_with_different_records_is_detected_without_values(self):
        left_path, right_path = self.root / "left.sqlite3", self.root / "right.sqlite3"
        schema = ("CREATE TABLE reports (id INTEGER PRIMARY KEY, email TEXT)",)
        create_database(left_path, schema + ("INSERT INTO reports VALUES (1, 'private@example.invalid')",))
        create_database(right_path, schema + ("INSERT INTO reports VALUES (2, 'other@example.invalid')",))
        hashes_before = (file_hash(left_path), file_hash(right_path))

        comparison = compare_sqlite_files(
            inspect_sqlite_file(left_path), inspect_sqlite_file(right_path)
        )

        self.assertEqual(comparison["schema_differences"], [])
        self.assertEqual(comparison["row_count_differences"], {})
        self.assertEqual(
            comparison["rows_not_equal_by_key"]["reports"],
            {"left_only": 1, "right_only": 1, "same_primary_key_different_values": 0},
        )
        self.assertNotIn("private@example.invalid", str(comparison))
        self.assertNotIn("other@example.invalid", str(comparison))
        self.assertEqual((file_hash(left_path), file_hash(right_path)), hashes_before)

    def test_primary_key_collision_with_different_values_is_counted(self):
        left_path, right_path = self.root / "left.sqlite3", self.root / "right.sqlite3"
        schema = ("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)",)
        create_database(left_path, schema + ("INSERT INTO items VALUES (5, 'left-only-content')",))
        create_database(right_path, schema + ("INSERT INTO items VALUES (5, 'right-only-content')",))

        comparison = compare_sqlite_files(
            inspect_sqlite_file(left_path), inspect_sqlite_file(right_path)
        )

        self.assertEqual(
            comparison["rows_not_equal_by_key"]["items"],
            {"left_only": 0, "right_only": 0, "same_primary_key_different_values": 1},
        )
        self.assertNotIn("left-only-content", str(comparison))
        self.assertNotIn("right-only-content", str(comparison))

    def test_missing_tables_and_row_count_differences_are_reported(self):
        left_path, right_path = self.root / "left.sqlite3", self.root / "right.sqlite3"
        create_database(
            left_path,
            ("CREATE TABLE observations (id INTEGER PRIMARY KEY, label TEXT)",
             "INSERT INTO observations VALUES (1, 'one')",
             "INSERT INTO observations VALUES (2, 'two')"),
        )
        create_database(
            right_path,
            ("CREATE TABLE observations (id INTEGER PRIMARY KEY, label TEXT)",
             "CREATE TABLE unrelated (id INTEGER PRIMARY KEY)",
             "INSERT INTO observations VALUES (1, 'one')"),
        )

        comparison = compare_sqlite_files(
            inspect_sqlite_file(left_path), inspect_sqlite_file(right_path), compare_records=False
        )

        self.assertEqual(comparison["tables_only_left"], [])
        self.assertEqual(comparison["tables_only_right"], ["unrelated"])
        self.assertEqual(comparison["row_count_differences"]["observations"], (2, 1))
        self.assertEqual(comparison["record_comparison"], "skipped_by_option")

    def test_migration_history_is_reported_as_metadata(self):
        path = self.root / "migrations.sqlite3"
        create_database(
            path,
            ("CREATE TABLE django_migrations (app TEXT, name TEXT, applied TEXT)",
             "INSERT INTO django_migrations VALUES ('road_observations', '0002_test', 'timestamp')"),
        )

        result = inspect_sqlite_file(path)

        self.assertEqual(result["migration_history"], [("road_observations", "0002_test")])
        self.assertNotIn("timestamp", render_sqlite_summary(result))

    def test_foreign_key_violations_are_counted_without_row_identifiers(self):
        path = self.root / "foreign-key.sqlite3"
        create_database(
            path,
            ("CREATE TABLE parent (id INTEGER PRIMARY KEY)",
             "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))",
             "INSERT INTO child VALUES (37, 999)"),
        )

        result = inspect_sqlite_file(path)

        self.assertEqual(result["foreign_key_check"], "complete")
        self.assertEqual(result["foreign_key_violations"], {"child": 1})
        self.assertNotRegex(render_sqlite_summary(result), r"\b37\b")
        self.assertNotIn("999", render_sqlite_summary(result))

    def test_summary_never_contains_user_values_and_inspection_preserves_hash(self):
        path = self.root / "private-data.sqlite3"
        create_database(
            path,
            ("CREATE TABLE auth_user (id INTEGER PRIMARY KEY, email TEXT, password TEXT)",
             "INSERT INTO auth_user VALUES (1, 'private@example.invalid', 'private-token-value')"),
        )
        before = file_hash(path)

        summary = render_sqlite_summary(inspect_sqlite_file(path))

        self.assertNotIn("private@example.invalid", summary)
        self.assertNotIn("private-token-value", summary)
        self.assertEqual(file_hash(path), before)

    def test_postgresql_connection_failure_does_not_expose_connection_url(self):
        private_url = "postgresql://audit-user:private-password@db.example.invalid/audit"

        class FailingCursor:
            def __enter__(self) -> FailingCursor:
                return self

            def __exit__(self, *_args: Any) -> None:
                return None

            def execute(self, _query: str) -> None:
                raise RuntimeError(private_url)

        class FailingConnection:
            def cursor(self) -> FailingCursor:
                return FailingCursor()

        result = inspect_postgresql_connection(FailingConnection(), nullcontext)
        output = render_postgresql_summary(result)

        self.assertEqual(result["status"], "inconclusive")
        self.assertIn("RuntimeError", output)
        self.assertNotIn(private_url, output)
        self.assertNotIn("private-password", output)
if __name__ == "__main__":
    unittest.main()
