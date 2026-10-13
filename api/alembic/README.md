# Alembic — running migrations

Schema migrations for the `api` service's database. `alembic.ini` lives one
directory up, in `api/`, because the migrations belong to that service and
nobody else in this repo has a schema.

**Run every command from the `api/` directory.** The `.env` file used below
lives one level up at the repo root, which is why the paths are explicit.

```bash
cd api
```

## The URL is never in a file

`api/alembic.ini` contains no `sqlalchemy.url`, and that is deliberate: a URL
carries a password, and a password in a tracked file is a password in git
history. `env.py` reads `ALEMBIC_DATABASE_URL` and **raises** if it is unset —
it will not fall back to a guessed local URL, because a silent fallback is how
you migrate the wrong database and never find out.

Load it from the repo root `.env` first. The `set -a` / `set +a` sandwich exports
everything the file defines; the quotes in `QUERY_PREFIX` survive it:

```bash
cd api
set -a && . ../.env && set +a
```

## The guard against migrating a remote database by accident

`env.py` refuses to run the **online** path against a host that is not one of
`localhost`, `127.0.0.1`, `::1` or `postgres` (the compose service name — alembic
is allowed to be run from inside the compose network, where the database is
reached by service name rather than by address).

**Why it exists.** `alembic upgrade head` is not a read. It runs
`CREATE EXTENSION vector` and `CREATE TABLE documents`. The standing rule in this
project is that nothing touches infrastructure without explicit approval — and a
migration aimed at production would run unattended and report success while
doing it. Today `ALEMBIC_DATABASE_URL` names `127.0.0.1` and `.env` mentions no
RDS endpoint, but "today" is not a control: one later edit to `.env` would point
the same command at production. The guard turns that convention into something
the tooling enforces. It runs **before** the engine is created, so a wrong target
fails without a single packet having been sent.

The error names the host and nothing else — never the URL, never the password.

**What it does NOT block: the offline path.** `alembic upgrade head --sql` emits
the DDL and connects to nothing, so it is exempt by design. Rendering and reading
the SQL is exactly the review step that makes a deliberate remote migration safe;
blocking it would remove the safety and keep the risk.

### Migrating a remote database on purpose

Once you have confirmed the target, and confirmed that you *want* it changed,
opt in for that one command:

```bash
export ALEMBIC_ALLOW_REMOTE_HOST=1 alembic upgrade head
unset ALEMBIC_DATABASE_URL
```

> ⚠️ **This changes a real remote database.** `CREATE EXTENSION vector` and
> `CREATE TABLE documents` will be applied to whatever host the URL names, with
> a role that holds `rds_superuser`. There is no dry run and no prompt. Prefer
> rendering the DDL first (`alembic upgrade head --sql`), reading it, and only
> then setting the override for the command that executes it.

The override must be exactly `1` — `true`, `yes` and `0` are all refused. It is
scoped to the command it prefixes, so it is not a standing permission: the next
plain `alembic upgrade head` is guarded again. A deliberate production migration
that required editing a source file would stop being a decision and become an
accident waiting for a hurried person.

## Locally, against the devdb container

The dev database is **profile-gated**, so it is never started by a plain
`docker compose up`. Start it with the profile named:

```bash
# from the repo root
docker compose --profile devdb up -d postgres
docker compose --profile devdb ps          # wait for 'healthy'
```

Then, from `api/`:

```bash
set -a && . ../.env && set +a

alembic current                 # (nothing) — confirms the URL resolved
alembic upgrade head            # apply
alembic downgrade base          # roll all the way back
```

A first run on a brand new volume prints the usual sequence:

1. `CREATE EXTENSION IF NOT EXISTS vector` — supplied by `pgvector/pgvector:pg16`.
2. `documents` and its two CHECK constraints.
3. The `documents(collection)` index.
4. The `updated_at` trigger.

Verify without a client:

```bash
psql "postgresql://$DEV_DB_USER:$DEV_DB_PASSWORD@127.0.0.1:$DEV_DB_HOST_PORT/$DEV_DB_NAME" \
  -c "\d documents"
```

The port is bound to `127.0.0.1` only, so this works from the host and from
nowhere else.

### Writing a new migration

```bash
alembic revision -m "add documents.source"
```

Hand-write the `upgrade()` / `downgrade()` bodies. `--autogenerate` is
deliberately unavailable: `env.py` sets `target_metadata = None` because this
project uses SQLAlchemy Core and has no declarative models to compare against.
Given an empty model set, autogenerate would read the live `documents` table as
unwanted and cheerfully generate a migration to drop it.

Keep each `op.execute()` to **one statement**. asyncpg rejects multiple
statements in a single prepared statement, so batching two `CREATE`s into one
string fails at runtime with a protocol error unrelated to the SQL.

## Against RDS, later

The mechanics do not change — only the URL. What changes is **who** runs it:

- `CREATE EXTENSION vector` requires the RDS **master** user (it holds
  `rds_superuser`). The application's runtime role will not have it, and will
  not need it: the extension is created once, by a migration.
- The master password lives in AWS Secrets Manager and is never in `.env`.
  Fetch it into the environment at the moment you run the migration, and do not
  write it into a file, a shell history entry, or this README:

  ```bash
  export ALEMBIC_ALLOW_REMOTE_HOST=1
  export ALEMBIC_DATABASE_URL="postgresql+asyncpg://<master_user>:<password>@<rds-endpoint>:5432/lemondrop"
  alembic upgrade head
  unset ALEMBIC_DATABASE_URL
  unset ALEMBIC_ALLOW_REMOTE_HOST
  ```

  `ALEMBIC_ALLOW_REMOTE_HOST=1` is required — see *The guard against migrating a
  remote database by accident* above. It is not ceremony: without it the command
  stops before connecting.

- Because the app will connect as a **separate, least-privilege role** (DML
  only, no `rds_superuser`), that role must be granted table privileges after
  the first migration. That is Phase 2.
- Prefer `alembic upgrade head --sql` to render the DDL without connecting,
  review it, then apply it — an unattended migration against a live instance is
  not something to leave to a bot.

> RDS 16 and `pgvector/pgvector:pg16` are deliberately the same major version.
> Planner behaviour and pgvector semantics are version-sensitive, so a local
> PostgreSQL 15 would let a migration pass here and fail there.