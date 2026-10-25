# Private Evidence Migration Readiness

Migration `0002_inspection_evidence` adds a blankable evidence file field and a nullable expiry timestamp to inspection sessions. Existing sessions remain valid without image evidence. The migration was not applied to either persistent RoutIQ database during this sprint.

Before activation, confirm the intended deployment environment and database target through the approved secret-management workflow without printing connection credentials. Take and verify a database backup, confirm the private evidence directory is outside public media and static roots, and ensure the application identity has restrictive filesystem permissions.

Run the following preflight from PowerShell with the deployment environment already configured:

```powershell
Set-Location D:\RoutIQ\code\backend
$env:DJANGO_SETTINGS_MODULE = "routiq_config.production_settings"
.\.venv\Scripts\python.exe manage.py check --deploy
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py showmigrations road_observations
.\.venv\Scripts\python.exe manage.py migrate --plan
```

Review the output and confirm the intended database and migration plan with the deployment owner. Only then apply the additive migration to the approved default database:

```powershell
.\.venv\Scripts\python.exe manage.py migrate road_observations 0002_inspection_evidence --database default
```

Do not run the apply command against a production or persistent local database without explicit database-owner approval. The test suite applies migrations only to Django's transient in-memory test database.
