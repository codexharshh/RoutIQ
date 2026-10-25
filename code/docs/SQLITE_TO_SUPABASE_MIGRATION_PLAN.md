# RoutIQ SQLite-to-Supabase Migration Readiness Plan

Audit date: 2026-10-19

## Status and safety boundary

This document records measured storage facts and unresolved decisions for a future owner-approved data transfer. Its Supabase baseline is the pre-migration Sprint 8 snapshot; the later schema migration attempt and current incident state are documented in [SPRINT9_MIGRATION_INCIDENT.md](SPRINT9_MIGRATION_INCIDENT.md). No SQLite database is designated authoritative, and no SQLite records have been transferred.

## Database topology

| Settings state / alias | Backend and file | Routed application data |
| --- | --- | --- |
| `DATABASE_URL` configured: `default` | PostgreSQL selected from the environment | Django core, built-in authentication, sessions/tokens, `potholes`, and `road_observations`. |
| `DATABASE_URL` blank or absent: `default` | SQLite at `backend/routiq.sqlite3` | Same core application data as the default PostgreSQL alias. |
| `government`, in either settings state | SQLite at `backend/routiq_government.sqlite3` | Models in the `government` app only. The router does not move this alias to PostgreSQL when `DATABASE_URL` is present. |

`DatabaseRouter` routes `government` app models to the `government` alias and all other models to `default`; cross-database ORM relations are denied. Production settings inherit the same database configuration. Therefore a successful Supabase connection does not mean that government records have moved to PostgreSQL. The current application can use PostgreSQL and a local government SQLite file at the same time.

## Source-candidate comparison

The storage audit opened local files read-only. It reports metadata, schemas, aggregate counts, migration labels, primary-key row comparisons, and foreign-key metadata only. It never prints stored record values. The prior database backup comparison now includes full column comparisons for rows sharing primary keys; file hashes remain separate evidence.

| Candidate | Measured evidence | Interpretation |
| --- | --- | --- |
| `backend/routiq.sqlite3` | 286,720 bytes; 22 tables; 43 migration rows; includes one built-in auth user, two damage instances, two damage observations, three assessments, two inspection sessions, and three outstanding-token rows. | This is the configured local core fallback and contains RoutIQ application data. That makes it an important candidate, not an owner-approved authority. |
| `backend/routiq_government.sqlite3` | 73,728 bytes; five tables; 43 migration rows; one `GovUser`; no road-segment rows. The government user-group and user-permission through tables refer to `auth_group` and `auth_permission` tables absent from this database. | Separate government store with a cross-database auth relationship risk. Preserve and review before consolidation. |
| `backend/db.sqlite3` | 311,296 bytes; 23 tables; 43 migration rows; no user or RoutIQ observation rows. It contains `road_observations_roadobservation`, a table absent from the configured `routiq.sqlite3` fallback and current observation model state. | Different schema/table inventory from the current core fallback; likely a historical schema artifact, but origin and intended role remain unresolved. |
| `backend/database2.sqlite3` | Zero bytes; no tables or migration history. | Empty file; purpose is unknown. Preserve. |
| `RoutIQ-database-backup-20261018-102204/db.sqlite3` | 311,296 bytes and a different SHA-256 from `backend/db.sqlite3`; same schema, table counts, and migration history. Read-only comparison found no row differences by primary key across the common tables. | Its database rows compare equal by primary key, but the distinct file remains a recovery artifact and must be preserved. The reason for the file-level hash difference is not established. |
| `RoutIQ-database-backup-20261018-102204/database2.sqlite3` | Zero bytes; same SHA-256 as the empty `backend/database2.sqlite3`. | Byte-identical empty artifact; retain pending owner confirmation. |
| Supabase PostgreSQL visible search path | Connection handshake succeeded. `pg_stat_user_tables` exposed no user tables; no visible `django_migrations` table or migration rows were found. The full Django migration plan reports all 44 graph migrations unapplied. | Consistent with an uninitialized Django schema in the visible search path. This does not prove that every schema in the Supabase project is empty. No schema change was made. |

The core SQLite candidates are not interchangeable: `routiq.sqlite3` has application rows absent from `db.sqlite3`, while `db.sqlite3` has a legacy table absent from `routiq.sqlite3`. Counts also differ for auth permissions/content types and token rows. Primary-key comparisons found records that exist only on each side and rows with the same key but different values. These findings rule out treating the files as duplicate copies. Exact file hashes and full inventory are in [SAFE_STORAGE_AUDIT.md](SAFE_STORAGE_AUDIT.md).

## Model ownership and relationship map

- **Built-in user/auth data:** `django.contrib.auth.User`, groups, permissions, password hashes, and their relation tables route through `default`. `accounts` currently defines no models and has no migrations. Do not invent an accounts migration for its current empty model state.
- **Sessions and tokens:** Django sessions, DRF/JWT-related token tables, and outstanding/blacklisted token tables route through `default`. Exclude sessions and active/revoked token material from a data transfer by default; users should authenticate again after cutover unless a separately reviewed requirement says otherwise.
- **Pothole and road-health records:** `Pothole`, `RoadHealth`, `ContractorMessage`, and `MessageSchedule` route through `default`. These legacy models do not provide a general owner FK. Image fields store paths to external files; migrate database rows and media files as separate, explicitly mapped work.
- **Modern road observations:** `InspectionSession.owner` points to the configured user model. `DamageObservation` points to its session and optionally a `DamageInstance`; `ObservationMatch` points to two observations; `DamageStatusAssessment` points to an instance and optionally an assessor; instances can reference a creator. Preserve user, session, instance, observation, assessment, and match keys/relationships in dependency order.
- **Private image evidence:** `InspectionSession.image_evidence` stores a storage path and `evidence_expires_at` stores retention metadata. The image bytes live in private storage outside PostgreSQL. Any approved migration must inventory and copy eligible files separately, retain owner access rules, preserve expiry, and omit already-expired evidence according to policy.
- **Government data:** `GovUser` is a separate `AbstractUser` model routed to `government`; `RoadSegment.created_by` points to that user. `GovUser.groups` and `GovUser.user_permissions` refer to built-in auth `Group` and `Permission`, which the router places on `default`. The government SQLite file has join tables but lacks the referenced auth tables. This cross-database relationship needs an explicit design before moving or migrating government data.

## Migration ordering and integrity risks

1. Review model/migration state and the complete graph before applying anything. The current cloud target shows all migrations pending; `road_observations.0001_initial` precedes the additive `0002_inspection_evidence`. The `government` and `potholes` migrations also require review against the intended final alias topology.
2. Decide whether `government` remains a separate SQLite system, becomes a separate PostgreSQL schema/alias, or is consolidated into the default database. Do not assume the existing router can enforce relationships after a topology change.
3. Resolve `GovUser` group/permission relationships. A single PostgreSQL database can host both model families, but that is an architecture and migration decision; do not create cross-database FKs or silently discard memberships.
4. Import the referenced built-in `auth_user` rows before owner-linked inspection sessions and user-attributed assessments. Import instances before observations that refer to them; observations before matches; road health before contractor messages/schedules; `GovUser` before road segments.
5. Do not merge both core candidates by copying primary keys blindly. The audit found overlapping primary keys with different row values in common tables. Create an explicit per-table key-preservation/remapping policy, preserve every FK under that mapping, and verify no orphan remains.
6. Resolve the legacy `road_observations_roadobservation` table in `db.sqlite3`. It is absent from current models and the configured fallback. Determine whether it has needed records or is stale before deciding to include or omit it.
7. Confirm ownership/provenance for legacy pothole rows, which do not have the modern owner relationship. Do not assign an owner based on inference.

## Backup, rehearsal, and rollback strategy

- Obtain owner approval for exactly one source file per database alias, and retain immutable copies of every source and recovery folder.
- Record source SHA-256, size, timestamp, schemas, migration history, table counts, primary-key comparison results, and FK violations. Verify a restored backup in isolation.
- Rehearse schema migrations and imports in a separate staging Supabase project/database. Never use production data or production schema for the first rehearsal.
- Before any approved target change, verify a provider-side backup/restore point and identify who can restore it. Preserve local SQLite files and media until validation and retention approval are complete.
- Define a write freeze or delta-capture process, explicit cutover criteria, rollback trigger, responsible operator, and tested restore steps before routing production traffic to the target.
- Keep schema migration, row transfer, private-image transfer, and frontend/API cutover as separate reviewed steps. A successful `DATABASE_URL` connection alone validates none of those steps.

## Pre-transfer and post-transfer validation

**Before transfer:**

- Run the read-only `routiq_storage_audit` command and preserve its output securely without credentials.
- Confirm source selection and per-alias topology; back up every selected file and verify hashes after backup.
- Review migration graph and SQL, router behavior, legacy tables, auth ownership, and government Group/Permission relationships.
- Compare per-table counts, PK overlap and divergent-row counts, null/duplicate keys, constraints, FK violations, media paths, evidence expiry, and available storage capacity.
- Approve which rows are in scope; default to excluding session and token tables and expired/private evidence unless separately authorized.

**After an approved staging import:**

- Compare exact row counts and key ranges by table, FK integrity and orphan counts, owner/user references, unique/idempotency constraints, and migration history.
- Verify selected records through application-level read paths and role/owner authorization tests without exposing record data in logs.
- Verify media/evidence hashes, path isolation, retention metadata, and owner-scoped retrieval independently of database row validation.
- Re-run `routiq_storage_audit`, Django system checks, and relevant tests. Confirm SQLite source hashes remain unchanged and document any intentional transformation.
- Obtain owner review of all discrepancies before a production cutover.

## Decisions requiring owner approval

1. Which core SQLite file, if any, is authoritative: `routiq.sqlite3`, `db.sqlite3`, or a separately approved reconstruction from multiple sources?
2. What is the intended final location for `government` data and its `GovUser` membership/permission relationships?
3. Which legacy and aggregate pothole rows, user rows, tokens/sessions, media, and private evidence are in scope for transfer and retention?
4. Should the unmodeled `road_observations_roadobservation` table be preserved, mapped, or excluded after its contents/provenance are reviewed?
5. Which staging target, backup/restore owner, import window, cutover criteria, and rollback procedure are approved?

## Evidence confidence

- **Confirmed:** Settings and router behavior; local SQLite file hashes, sizes, table schemas/counts, migration histories, and read-only FK metadata; exact record comparison by primary key for schema-compatible SQLite tables; successful PostgreSQL connection; no visible PostgreSQL user tables/migration rows; all 44 Django migration graph nodes pending on that visible target.
- **Likely explanation, not a decision:** `routiq.sqlite3` is the current local core data source because settings select it as the SQLite default and it contains modern application rows. This does not establish it as the authoritative migration source.
- **Unresolved:** Why `db.sqlite3` contains a different historical table and different data; whether the backup hash difference is due only to SQLite file layout/metadata; source ownership of legacy data; intended government topology; completeness of externally stored images/evidence; and whether schemas outside the configured PostgreSQL search path contain project data.

## Next safe action

The project owner should review this evidence and designate the authoritative source per alias, approve the government relationship/topology decision, and authorize an isolated staging rehearsal with a verified backup. Until those decisions are recorded, do not apply migrations, transfer records/files, or change database routing.
