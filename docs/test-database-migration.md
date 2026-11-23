# Guarded test-database migration

This procedure upgrades only the existing `nammaclean_test_db` database on
`localhost:5433`. It does not create, drop, reset, or recreate a database and
does not touch the development database.

The only permitted migration path is the forward Alembic upgrade from
`e5a19cb28df4` to `b7e4d2c9f1a8`. The upgrades add nullable user profile
columns and create muster-point and attendance tables. Do not run downgrades.

## Preconditions

- Review the migration revisions and this procedure before approving a run.
- Ensure the existing PostGIS service is available on host port `5433`.
- Ensure the project `.env` contains the credentials for that service. The
  migration script uses those credentials but fixes the target host, port, and
  database name itself; it never prints the connection URL or password.
- Do not run a generic `alembic upgrade` command for this procedure. The
  project Alembic environment normally obtains its URL from application
  settings, which may target the development database.

## Run

From the repository root in PowerShell, after explicit approval:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_test_db.py --confirm
```

The script refuses to proceed unless `--confirm` is present and the operator
types this exact phrase at the prompt:

```text
MIGRATE nammaclean_test_db FROM e5a19cb28df4 TO b7e4d2c9f1a8
```

Before prompting, it verifies the connection URL is exactly
`localhost:5433/nammaclean_test_db`, then checks the live database identity,
starting Alembic revision, and PostGIS extension. It repeats those checks
inside a transaction immediately before migration and locks the
`alembic_version` table to prevent concurrent migration attempts. The script
passes that same verified SQLAlchemy connection to Alembic; Alembic does not
open a second connection from `.env` or an inherited development URL.

The forward upgrade and post-migration checks run in the same transaction.
Any raised error aborts the transaction. The post-check verifies the database
identity, revision `b7e4d2c9f1a8`, PostGIS, the new user columns, and the
muster-point, attendance, and QR-token tables before the transaction commits.
No test records are deleted or rewritten by this procedure.

## After a successful migration

The normal regression-test guards require revision `b7e4d2c9f1a8` and continue
to fail closed on a different database, port, or schema revision. The QR
integration harness uses a separate database,
`nammaclean_qr_integration_db`; this procedure and the regression-test guard
updates do not change that database or its guard.

Do not run the migration script until the operator has reviewed this procedure
and explicitly approved the database-changing operation.
