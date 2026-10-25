# RoutIQ Sprint 9 Supabase Migration Incident

**Status reviewed:** 2026-10-19
**Scope:** Read-only diagnosis during Sprint 10. No cloud data, migration records, permissions, schema, or local database files were changed during this review.

## Summary

The Supabase `default` database has the RoutIQ schema and all 44 migrations in the current Django graph are marked applied. Its `django_migrations` table contains 48 rows but only 44 distinct `(app, name)` keys. Four keys in `token_blacklist` each have one extra row. The failed Sprint 9 command raised a unique-key error while Django's `post_migrate` receiver was creating an `auth_permission` row. Current read-only checks show the permission set is unique and complete by the measured default-permission counts, but the failed command must still be treated as an incident.

No exact cause has been established. Concurrent migration execution is plausible; the available evidence does not prove it.

## Read-only findings

### Target and routing

- Django selects PostgreSQL for `default`, database name `postgres`, current schema `public`; connection credentials and host are intentionally omitted.
- The visible schema contains 21 application model tables plus `django_migrations` (22 tables total). No `government` model tables are present in PostgreSQL.
- The `government` alias remains SQLite at `backend/routiq_government.sqlite3`. Its file hash remained unchanged during Sprint 10.
- The router excludes government models from `default`. Both government migration files generate no SQL on `default`; their migration names are nevertheless recorded in the PostgreSQL migration history.

### Migration history

- `django_migrations`: 48 rows, 44 distinct migration keys.
- Four duplicate key groups, all in `token_blacklist`; each has two records: `0010_fix_migrate_to_bigautofield`, `0011_linearizes_history`, `0012_alter_outstandingtoken_user`, and `0013_alter_blacklistedtoken_options_and_more`.
- The migration table has only its primary-key uniqueness constraint; it has no unique constraint on `(app, name)`. The recorder model also declares no such constraint. Duplicate history rows can therefore exist without a database uniqueness violation.
- `showmigrations --database default` marks all 44 current graph nodes applied. This checks membership, not duplicate-history integrity.

### Permissions and schema

- `auth_permission` contains 84 rows; there are no duplicate `(content_type_id, codename)` keys. The permission for content type `admin.logentry` and codename `add_logentry` exists exactly once.
- `django_content_type` contains 21 rows and no duplicate `(app_label, model)` keys. Each present content type currently has four permission rows.
- Read-only model introspection found all 21 expected model tables and columns. The only extra table is Django's `django_migrations` recorder table. All 22 model foreign-key specifications were present, declared model index/constraint names were present, and PostgreSQL reported zero unvalidated foreign keys.
- These checks establish structural agreement with current models and migrations. They do not certify application behavior or a data transfer; the Supabase tables were initially empty and remain without imported RoutIQ records.

## Failure and cause assessment

The exact command failure was:

```text
django.db.utils.IntegrityError: duplicate key value violates unique constraint
"auth_permission_content_type_id_codename_01ab375a_uniq"
Key (content_type_id, codename)=(1, add_logentry) already exists.
```

The error occurred in Django's `post_migrate` permission creation after migration execution, not in a reported table-creation operation. The permission exists once now, and the database contains no duplicate permission keys. That state is consistent with a competing permission insert, but does not establish which process or event caused it.

The four duplicate token migration rows are evidence of repeated writes to migration history. Their timestamps are only seconds apart. The migration recorder does not enforce uniqueness for `(app, name)`, so duplicate rows alone cannot identify whether they came from overlapping migration processes, a prior manual/history operation, or another cause. During Sprint 9, a migration command yielded while its process status was not captured; another invocation was subsequently started. This creates a plausible overlap in this session, but it is not sufficient proof that overlap caused the database state.

## Risk and remediation proposal

Do not run another migration or permission-writing command until the database owner reviews the state and confirms no migration process is active. The smallest proposed correction is a reviewed, transactional data cleanup of exactly one redundant `django_migrations` row for each of the four duplicate keys, retaining one record per key. Do not alter `auth_permission`: current read-only inspection found no duplicate permission key and exactly one `add_logentry` row.

Before that write, the owner/operator should:

1. Take and verify a Supabase provider backup or restore point.
2. Confirm all application instances and deployment jobs that could run migrations are stopped.
3. Re-run aggregate duplicate and permission checks in a read-only transaction and confirm the four expected duplicate groups and no others.
4. Approve the one-row-per-key cleanup explicitly. Do not delete migration records outside those four identified groups and do not use `--fake`.
5. Re-run read-only duplicate, permission, model-table, column, index, and foreign-key checks. Confirm 44 distinct graph keys with no duplicate records, all 84 permissions unique, and the protected SQLite source hashes unchanged.

If permission creation still fails after the history cleanup and quiescence review, stop. Have the database owner inspect the active Django processes and `post_migrate` receivers before authorizing any permission repair. Do not add SQL workarounds or alter migrations to suppress the error.

No corrective cloud write was made in Sprint 10. The owner-approved next action is to review and approve or reject the proposed cleanup before any operator changes Supabase.
