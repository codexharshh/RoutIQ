"""Read-only audit of configured databases and known RoutIQ SQLite candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connections, transaction
from django.db.migrations.loader import MigrationLoader

from road_observations.storage_audit import (
    compare_sqlite_files,
    inspect_postgresql_connection,
    inspect_sqlite_file,
    render_postgresql_summary,
    render_sqlite_summary,
)


SQLITE_FILENAMES = (
    "db.sqlite3",
    "database2.sqlite3",
    "routiq.sqlite3",
    "routiq_government.sqlite3",
)


def sqlite_candidate_paths(base_dir: Path, databases: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Return configured and known candidate paths without scanning generated trees."""
    candidates: dict[str, str] = {}

    def add(path: Path, label: str) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path.absolute())
        candidates.setdefault(resolved, label)

    for alias, config in databases.items():
        if config.get("ENGINE", "").endswith("sqlite3"):
            name = config.get("NAME")
            if name and str(name) != ":memory:":
                path = Path(name)
                if not path.is_absolute():
                    path = base_dir / path
                add(path, f"configured alias {alias}")

    for filename in SQLITE_FILENAMES:
        add(base_dir / filename, "known local candidate")

    repository_root = base_dir.parent.parent
    try:
        backup_dirs = sorted(
            path for path in repository_root.glob("RoutIQ-database-backup-*")
            if path.is_dir()
        )
    except OSError:
        backup_dirs = []
    for backup_dir in backup_dirs:
        for filename in SQLITE_FILENAMES:
            add(backup_dir / filename, "database-backup candidate")

    return candidates


def _migration_state(history: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    graph_nodes = set(loader.graph.nodes)
    applied = set(history)
    return (
        sorted(f"{app}.{name}" for app, name in applied if (app, name) in graph_nodes),
        sorted(f"{app}.{name}" for app, name in graph_nodes - applied),
    )


class Command(BaseCommand):
    help = "Inspect RoutIQ database metadata and candidate SQLite files without writing data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema-only",
            action="store_true",
            help="Skip row-by-row comparison between compatible SQLite candidates.",
        )

    def handle(self, *args, **options):
        compare_records = not options["schema_only"]
        self.stdout.write("RoutIQ storage audit (read-only)")
        self.stdout.write("Configured Django database aliases:")

        postgres_reports: dict[str, dict[str, Any]] = {}
        for alias, config in settings.DATABASES.items():
            engine = config.get("ENGINE", "")
            connection = connections[alias]
            if engine.endswith("sqlite3"):
                name = config.get("NAME")
                path = Path(name) if name and str(name) != ":memory:" else None
                if path and not path.is_absolute():
                    path = Path(settings.BASE_DIR) / path
                self.stdout.write(
                    f"- {alias}: vendor=sqlite; configured_file="
                    f"{path if path else 'in-memory or unavailable'}"
                )
            elif engine == "django.db.backends.postgresql":
                self.stdout.write(f"- {alias}: vendor=postgresql; connection URL suppressed")
                report = inspect_postgresql_connection(
                    connection,
                    lambda selected_alias=alias: transaction.atomic(using=selected_alias),
                )
                postgres_reports[alias] = report
                self.stdout.write("  " + render_postgresql_summary(report))
                if report["status"] == "inspected":
                    applied, pending = _migration_state(report["migration_history"])
                    self.stdout.write(
                        f"  Migration state: applied={len(applied)}; pending={len(pending)}."
                    )
                    if pending:
                        self.stdout.write("  Pending Django migrations: " + ", ".join(pending))
            else:
                self.stdout.write(f"- {alias}: vendor=unsupported; inspection skipped")

        candidates = sqlite_candidate_paths(Path(settings.BASE_DIR), settings.DATABASES)
        snapshots: dict[str, dict[str, Any]] = {}
        self.stdout.write("SQLite candidate files:")
        for path_text, label in candidates.items():
            snapshot = inspect_sqlite_file(Path(path_text))
            snapshot["candidate_label"] = label
            snapshots[path_text] = snapshot
            self.stdout.write(f"- {label}: {render_sqlite_summary(snapshot)}")
            if snapshot.get("status") == "inspected":
                if snapshot["foreign_key_violations"]:
                    counts = ", ".join(
                        f"{table}={count}"
                        for table, count in sorted(snapshot["foreign_key_violations"].items())
                    )
                    self.stdout.write(f"  [REVIEW] Foreign-key violations by table: {counts}.")
                if snapshot["missing_foreign_key_targets"]:
                    targets = ", ".join(snapshot["missing_foreign_key_targets"])
                    self.stdout.write(f"  [REVIEW] Foreign keys reference missing tables: {targets}.")
                applied, pending = _migration_state(snapshot["migration_history"])
                self.stdout.write(
                    f"  Migration state: applied={len(applied)}; pending={len(pending)}."
                )
                if pending:
                    self.stdout.write("  Pending Django migrations: " + ", ".join(pending))

        valid = [item for item in snapshots.values() if item.get("status") == "inspected"]

        def display_path(path_text: str) -> str:
            path = Path(path_text)
            try:
                return path.relative_to(Path(settings.BASE_DIR).parent.parent).as_posix()
            except ValueError:
                return path.name

        self.stdout.write("SQLite candidate comparisons:")
        for index, left in enumerate(valid):
            for right in valid[index + 1:]:
                result = compare_sqlite_files(left, right, compare_records=compare_records)
                if result["status"] != "inspected":
                    self.stdout.write(
                        f"- {display_path(result['left'])} vs {display_path(result['right'])}: "
                        f"[INCONCLUSIVE] {result.get('error_type', result.get('record_comparison', 'comparison unavailable'))}."
                    )
                    continue
                self.stdout.write(
                    f"- {display_path(result['left'])} vs {display_path(result['right'])}: "
                    f"tables only left={result['tables_only_left'] or 'none'}; "
                    f"only right={result['tables_only_right'] or 'none'}; "
                    f"schema differences={result['schema_differences'] or 'none'}; "
                    f"row-count differences={result['row_count_differences'] or 'none'}; "
                    f"rows not equal by primary key={result['rows_not_equal_by_key'] or 'none'}; "
                    f"unkeyed tables={result.get('unkeyed_tables', []) or 'none'}; "
                    f"record comparison={result.get('record_comparison', 'not run')}."
                )

        for alias, report in postgres_reports.items():
            if report.get("status") != "inspected":
                continue
            for candidate in valid:
                common = set(report["approximate_row_counts"]) & set(candidate["row_counts"])
                differences = {
                    table: (
                        report["approximate_row_counts"][table],
                        candidate["row_counts"][table],
                    )
                    for table in common
                    if report["approximate_row_counts"][table] != candidate["row_counts"][table]
                }
                if differences:
                    self.stdout.write(
                        f"[REVIEW] {alias} approximate PostgreSQL counts differ from "
                        f"{display_path(candidate['path'])} exact SQLite counts in {len(differences)} tables; "
                        "this is not a row-level equivalence check."
                    )

        self.stdout.write(
            "Manual review required: confirm the source database, user ownership mappings, "
            "cross-database government auth relations, media/evidence files, and primary-key policy."
        )
        if not compare_records:
            self.stdout.write("Record comparison was skipped by --schema-only.")
