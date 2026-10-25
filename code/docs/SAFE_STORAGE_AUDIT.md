# RoutIQ Safe Storage Audit

Audit date: 2026-10-19

This audit used read-only SQLite connections, file metadata and SHA-256 hashes, Django migration inspection, and a PostgreSQL connection handshake. It did not display application row values, inspect `.env` contents, modify databases, or apply migrations. Database connection strings and credentials are intentionally omitted.

**Historical status:** This report records the pre-migration Sprint 8 snapshot. Supabase has since received the owner-approved schema migration attempt; its current migration and permission state is documented in [SPRINT9_MIGRATION_INCIDENT.md](SPRINT9_MIGRATION_INCIDENT.md). The local SQLite inventory remains a preservation record, not a source-of-truth decision.

## Active project and working tree

- The Git repository root is `D:\RoutIQ`; the active RoutIQ application is `D:\RoutIQ\code`.
- The current branch is `routiq-independent-rebuild`.
- The working tree already contains many modified, deleted, and untracked application files and recovery folders. Those changes were preserved. This audit changed only this report and the database configuration helper/tests in the active application tree.
- The Django settings are in `code/backend/routiq_config/settings.py`. When a nonblank `DATABASE_URL` is loaded, Django selects PostgreSQL for `default`; the `government` alias remains SQLite. Without that variable, `default` falls back to `code/backend/routiq.sqlite3` and `government` to `code/backend/routiq_government.sqlite3`.

## SQLite inventory

All table names, schemas, counts, and migration rows below were inspected without reading application records. The `db.sqlite3` backup comparison was performed by schema, foreign keys, row counts, and migration metadata only; equal counts do not prove equal record values.

| File | Size | SHA-256 | Tables / nonzero counts | Finding |
| --- | ---: | --- | --- | --- |
| `code/backend/db.sqlite3` | 311,296 bytes | `1736c0d1cc810305c9dbc588d4263cb67ab416486611b6628f59952b60f5cf1a` | 23 tables; 88 permissions, 22 content types, 43 migration rows; other table counts zero | Not selected by current settings. Preserve. |
| `code/backend/database2.sqlite3` | 0 bytes | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | No schema or tables | Empty artifact; preserve until its origin and intended use are confirmed. |
| `code/backend/routiq.sqlite3` | 286,720 bytes | `26e44d191429115d27b4f2a3853795c3710c47521e5b8ed188c1169a66778439` | 22 tables; includes one auth user, two damage instances, two damage observations, three assessments, two sessions, and three outstanding tokens | Configured local fallback with application data. Preserve. |
| `code/backend/routiq_government.sqlite3` | 73,728 bytes | `f03faaa07b1765aae152e250b8cd9dbd53f875e5461de4112b0bb494715be945` | Five tables; includes one government user and 43 migration rows | Configured government database. Preserve. |
| `RoutIQ-database-backup-20261018-102204/db.sqlite3` | 311,296 bytes | `ddd92205d521f92d50c077daa437b889e45b1d838111f946b5b00b9d83ff80f1` | Same 23 table names, schemas, foreign keys, row counts, and migration history as `code/backend/db.sqlite3`; full-column comparison found equal rows by primary key across common tables | Hash differs from the active-named counterpart for an unresolved file-level reason; preserve as a backup. |
| `RoutIQ-database-backup-20261018-102204/database2.sqlite3` | 0 bytes | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | No schema or tables | Byte-identical to the empty `code/backend/database2.sqlite3`; preserve both pending confirmation. |

`code/backend/db.sqlite3` and `database2.sqlite3` are different files and are not byte-identical. The former contains Django’s standard schema and migration history but no user or RoutIQ observation rows; the latter is empty. The two configured SQLite fallback databases are separate files and contain data. None of these files was removed, renamed, merged, or written.

## Backup and recovery inventory

The listed backup folders have no nested Git metadata. Generated dependency/build directories were excluded from inventory. Logs were inspected only by filename, size, and timestamp, not opened.

| Folder | Relevant inventory and comparison | Recommendation |
| --- | --- | --- |
| `RoutIQ-database-backup-20261018-102204` (folder timestamp 2026-10-18 10:23 local) | Contains `db.sqlite3` (311,296 bytes; timestamp 10:22; hash differs from `code/backend/db.sqlite3`), empty `database2.sqlite3`, and an 8,813-byte `settings.py` (timestamp 12:38) with no byte-identical active counterpart. The database has matching schema/counts and equal rows by primary key across common tables; the file hash still differs. | **Preserve.** It is a recovery point; its hash difference and settings-file provenance are unresolved. |
| `RoutIQ-one-shot-recovery-20261018-145838` (folder timestamp 2026-10-18 14:58 local) | Contains `frontend-build.log` (1,434 bytes; 14:58), `recovery.log` (1,884 bytes; 14:59), a 17,040-byte `RoadDamageConsole.tsx.before` (08:54), and three startup scripts (411, 407, and 101 bytes; 14:58). The startup scripts and historical console source have no byte-identical active counterparts. Log contents were not read. | **Preserve.** Recovery and diagnostic evidence may be unique. |
| `RoutIQ-v0-ui-backup-20261018-194500` (folder timestamp 2026-10-18 19:45 local) | Contains `rollback-manifest.json` (946 bytes; 19:45) and historical `original/src/App.tsx` (5,952 bytes; 08:54); neither is byte-identical to its active counterpart. | **Preserve.** This is unique historical UI and rollback information. |

The root `images` directory contains three large image assets (`Main.png`, `Mainv2.png`, `web_up3.png`). Their contents were not opened. Preserve them as unverified project assets. `RoutIQ-Phase1-Modernize.ps1` and the untracked `.vscode` folder are also existing user files and were left untouched.

No backup is recommended for deletion. The empty duplicate `database2.sqlite3` is the only exact duplicate found, and its purpose is unknown. The differing backup database hashes prevent treating the database backup as redundant even though its schema and counts match.

## Sprint 8 read-only storage audit

- The configured aliases were inspected: `default` selected PostgreSQL from the environment-loaded `DATABASE_URL`; `government` selected `code/backend/routiq_government.sqlite3`. The URL was not printed.
- PostgreSQL catalog inspection ran in a read-only transaction. The visible search path had no user tables or `django_migrations` rows; Django reports all 44 migration graph nodes pending. This does not establish that all schemas in the Supabase project are empty.
- The government SQLite file has no reported row-level SQLite foreign-key violations, but its group and permission join-table definitions reference `auth_group` and `auth_permission`, absent from that database. This cross-database relationship needs a reviewed design.
- The full audit compared records by primary key and all columns without emitting values. It confirmed equal common-table rows between `backend/db.sqlite3` and the backup `db.sqlite3`; it confirmed material row-count and row-content differences between `backend/db.sqlite3` and configured `backend/routiq.sqlite3`. Neither core candidate is declared authoritative.
- Automated tests covered empty databases, schema/count differences, distinct rows sharing a key, migration metadata, foreign-key violations, output sanitization, and file-hash preservation. No database was modified.

## Supabase and migration state (Sprint 8 snapshot)

- Django selected the PostgreSQL backend from the configured environment without displaying the connection URL. A non-destructive connection handshake succeeded; Django reported vendor `postgresql`.
- `DATABASE_URL` configuration is parsed by `dj_database_url`; PostgreSQL uses SSL (`sslmode=require`), a 10-second connection timeout, a 60-second connection age, and connection health checks. The PostgreSQL driver is installed in the project virtual environment.
- The full `showmigrations --plan` output showed every listed migration as unapplied on the selected database. The focused dependency plan included `contenttypes.0001_initial`, `auth.0001_initial`, `road_observations.0001_initial`, and `road_observations.0002_inspection_evidence`. No migrations were applied.
- `accounts` has an empty `models.py` and only an empty migration package initializer; `showmigrations accounts` reports “no migrations.” It currently uses Django’s built-in user model rather than defining its own database models. This appears intentional for the current model state. Reassess and create reviewed migrations only if application-owned account models are introduced.
- The evidence migration is additive and depends on `road_observations.0001_initial`. It remains unapplied on Supabase. Application code must not enable evidence persistence until the migration is reviewed and deliberately activated.
- A successful connection proves only that the selected endpoint accepts a connection. It does not transfer SQLite records, prove the target is empty, or validate application-level permissions/data.

## Ignore and credential-file review

- The root ignore rules exclude `code/backend/.env`, the backend virtual environment, SQLite files and sidecar files, media, `node_modules`, and frontend build output. `code/.gitignore` also ignores `.env` and its specified local SQLite file pattern; `code/backend/.gitignore` ignores private evidence storage and virtual environments.
- Git reports no tracked entries for the audited SQLite files. The ignore rules were inspected but not changed; existing ignore changes were preserved.
- `code/backend/.env.example` has a blank `DATABASE_URL` placeholder and blank secret placeholders. No environment file contents were read. Keep the real environment file untracked and credentials out of reports and source control.

## Safe SQLite-to-Supabase migration plan

Do not transfer data until the authoritative SQLite source and a reviewed mapping plan are approved.

1. **Identify the source.** Confirm the intended source file with the project owner. Compare all candidate SQLite files and backup hashes; do not select one based only on its filename or settings fallback. Keep an untouched copy and record its hash, size, timestamp, schema, and row counts.
2. **Back up and rehearse.** Create and verify a separate backup of the chosen source and a recovery plan for the cloud target. Rehearse in an isolated Supabase project/database before touching the intended target. Confirm backup restoration rather than relying on file presence alone.
3. **Review schema and migration ordering.** Review the complete Django migration graph and model state first. Back up the target, apply the reviewed schema migrations in dependency order, and verify each migration state. In particular, assess `accounts` (currently model-less) and `road_observations.0002_inspection_evidence`; do not create or apply either migration speculatively.
4. **Map relationships before copying.** Define table/model mappings, primary-key behavior, foreign keys, and owner/user relationships. Preserve user IDs and authentication-related references only under an approved plan; never migrate password/token/session data by default. Resolve legacy observations without owner foreign keys and government records separately. Check for orphaned references before import.
5. **Transfer in a controlled rehearsal.** Use a reviewed, repeatable export/import process with transactions or staging tables and explicit conflict handling. Preserve timestamps, coordinates, provenance, source identifiers, and image references; do not copy local filesystem paths that do not exist in cloud storage. Record source and target counts by table without exporting secrets to logs.
6. **Validate before cutover.** Compare table counts, key ranges, nulls, duplicate/idempotency keys, foreign-key integrity, owner-scoped access, representative application queries, and required assets. Re-run migration-state checks. Do not use a successful database connection as proof of transfer completeness.
7. **Cut over and retain rollback.** Schedule an approved write freeze or delta-capture strategy, retain the source and verified backup, and define a rollback trigger and procedure before directing production traffic to the target. Do not delete the source until stakeholders approve validation and retention requirements.

## Commands and next safe actions

Read-only checks used from `code/backend`:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py showmigrations accounts
.\.venv\Scripts\python.exe manage.py showmigrations --plan accounts road_observations
.\.venv\Scripts\python.exe manage.py routiq_preflight --skip-service-checks
```

The existing `routiq_preflight` command is the project’s storage/configuration preflight; no duplicate command was added. Use `--skip-service-checks` when the goal is to inspect local configuration and migration state without calling FastAPI. Migration-state inspection still connects to the currently selected database and reads Django’s migration metadata.

The observed `routiq_preflight --skip-service-checks` result was PASS=5, WARNING=2, BLOCKED=0, NOT VERIFIED=2. Warnings were pending road-observation migrations and missing optional dashcam dependencies; FastAPI health/readiness were not verified because service checks were intentionally skipped. `manage.py check` also passed with `DATABASE_URL` blank, confirming that the local system-check run used the SQLite fallback.

The next safe action is owner review to designate the authoritative SQLite source and approve a staging database and transfer plan. Until then, keep Supabase schema migrations and data transfer separate from this read-only audit, and preserve every listed database and recovery folder.
