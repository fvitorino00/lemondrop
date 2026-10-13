"""Alembic environment for lemondrop.

The one thing that makes this file not the stock template: **it is async**.

Our driver is asyncpg (see api/requirements.txt), which only speaks async.
Alembic's default env.py is synchronous and expects a blocking DBAPI dialect.
Copying it unchanged gets you one of two failures — either the async dialect
refuses to be used synchronously ("The asyncio extension requires an
asyncio-aware event loop"), or it silently opens a second, blocking connection
and you ship a migration path that behaves differently in production than it
did in review. So the online path here builds an AsyncEngine and drives it under
an explicit ``asyncio.run()``, and hands control to Alembic only once inside the
loop. That is the whole modification.

Two other deliberate choices, both about not embedding knowledge that goes
stale:

1. **No URL in this file and none in alembic.ini.** It comes from the
   ``ALEMBIC_DATABASE_URL`` environment variable. A hardcoded URL would put a
   password in a tracked file, and would also mean a developer pointing the tool
   at the devdb silently pointed production at it too, or vice versa.
2. **``target_metadata = None``.** Milestone 3 uses SQLAlchemy Core, not the ORM,
   so there are no declarative models to compare the database against; the
   migrations are hand-written SQL. Setting the metadata to an empty
   ``MetaData()`` instead would be worse than nothing: ``alembic revision
   --autogenerate`` would read "the database has a table my (empty) metadata
   does not" and helpfully generate a migration that DROPS ``documents``.
   ``None`` makes autogenerate refuse rather than propose destruction.

And a third, which is a safety rail rather than a style choice:

3. **The online path refuses a non-local host.** ``_assert_local_target`` stops
   before a connection is opened if the URL names anything but loopback or the
   compose service. Point 1 keeps the URL out of tracked files; this keeps an
   ordinary ``.env`` edit from turning ``alembic upgrade head`` into an
   unattended production migration. The offline path (``--sql``) is deliberately
   exempt — it emits DDL and connects to nothing, which is exactly the review
   step that makes a deliberate remote migration safe. See
   ``_assert_local_target`` and api/alembic/README.md.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

# Alembic populates `config` before executing this file; there is no import for
# it, and pyright/mypy both need the ignore.
config = context.config

if config.config_file_name is not None:
    # Routes alembic's own logging through the [loggers] block in alembic.ini.
    fileConfig(config.config_file_name)

# See module docstring, point 2.
target_metadata = None

# The env var carrying the connection URL. Distinct from whatever URL the
# application itself will use at runtime: migrations are a DBA concern with
# broader privileges (they CREATE EXTENSION and own the schema), and conflating
# the two is how a runtime role quietly acquires DDL rights it should never
# have had.
URL_ENV_VAR = "ALEMBIC_DATABASE_URL"


def _database_url() -> str:
    """Return the migration URL from the environment, or fail with an explanation.

    Deliberately raising rather than defaulting. The obvious "helpful" fallback
    — a hardcoded local dev URL — is the exact failure this project is avoiding:
    it would let `alembic upgrade head` succeed against the developer's laptop
    while the operator believed a migration had been applied to RDS. A loud stop
    is strictly better than a quiet wrong target.
    """
    url = os.environ.get(URL_ENV_VAR)
    if not url:
        raise RuntimeError(
            f"{URL_ENV_VAR} is not set, and there is deliberately no default.\n"
            "\n"
            "Alembic will not guess which database to migrate: a wrong guess here\n"
            "reports success while having changed nothing on the server that matters.\n"
            "\n"
            "For the local devdb container (see api/alembic/README.md):\n"
            "    set -a && . ./.env && set +a     # from the repo root\n"
            "    alembic upgrade head              # from api/\n"
            "\n"
            "The value must use the async driver:\n"
            "    postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>"
        )
    return url


# The hosts this project considers safe to migrate without asking. `postgres` is
# here because alembic may legitimately be run from inside the compose network
# (a one-shot container), where the database is a service name rather than an
# address. `::1` is IPv6 loopback, which a developer could reasonably type.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})

# The escape hatch. Exactly "1" or nothing — not "true", not "yes", not "0". A
# value that merely resembles consent is not consent; this variable decides
# whether DDL runs against a production database, and it should take one
# unambiguous keystroke to say yes and be hard to hit by accident.
ALLOW_REMOTE_ENV_VAR = "ALEMBIC_ALLOW_REMOTE_HOST"


def _assert_local_target(url: str) -> None:
    """Refuse to migrate a host that does not look like a local database.

    Why this exists. The rule is that nothing in this project touches
    infrastructure without explicit approval — and a migration is not a small
    thing: ``alembic upgrade head`` runs ``CREATE EXTENSION vector`` and
    ``CREATE TABLE documents`` against whatever host the URL names. Today the URL
    is localhost and ``.env`` names no RDS endpoint, but "today" is not a control.
    One later edit to ``.env`` would silently aim the same command at production,
    and it would run unattended and report success. Raising here converts a
    convention into an enforced one.

    Why an env var rather than editing this file: a deliberate production
    migration must stay possible, and the moment it requires a code change is the
    moment it stops being a decision and starts being an accident waiting for a
    hurried person.

    Credential safety. Only ``url.host`` ever reaches this message. The full URL
    is never printed, formatted or logged — not even in the malformed-URL branch
    — because ``make_url`` objects carry ``url.password`` and a URL embedded in
    an exception string is a URL pasted into a terminal, a log aggregator and a
    chat transcript. The host is the only part needed to identify the target and
    it is the only part that is safe to show.
    """
    try:
        host = make_url(url).host
    except Exception as exc:  # noqa: BLE001 — ArgumentError from a bad URL
        # The parse failed, so the target is unknown. Unknown is treated as
        # remote. The exception's own message can quote the offending string, so
        # it is summarised by type rather than reprinted.
        raise RuntimeError(
            f"{URL_ENV_VAR} could not be parsed as a database URL "
            f"({type(exc).__name__}), so alembic cannot tell which host it would "
            f"be migrating. Refusing to guess.\n"
            "\n"
            "The value must use the async driver:\n"
            "    postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>"
        ) from None

    if host in LOCAL_HOSTS:
        return

    if os.environ.get(ALLOW_REMOTE_ENV_VAR) == "1":
        return

    raise RuntimeError(
        f"Refusing to migrate: {URL_ENV_VAR} points at host {host!r}, which is "
        f"not one of the local targets {sorted(LOCAL_HOSTS)}.\n"
        "\n"
        "A migration is not a read: this would run CREATE EXTENSION and CREATE\n"
        "TABLE against that host, unattended, and report success. Infrastructure\n"
        "changes in this project require explicit approval, and the absence of a\n"
        "guard is not approval.\n"
        "\n"
        "To review the DDL WITHOUT connecting to anything, use the offline path\n"
        "— it emits SQL and touches no database:\n"
        "    alembic upgrade head --sql\n"
        "\n"
        "To migrate a remote database deliberately, having confirmed the target\n"
        "and that you want it changed, opt in for this single command:\n"
        f"    {ALLOW_REMOTE_ENV_VAR}=1 alembic upgrade head\n"
    )


def _configure(**kwargs: object) -> None:
    """Shared context.configure() call for the offline and online paths.

    Note there is no `sqlalchemy.url=` passed here. It is set on the config
    object below instead, which is what both paths read.
    """
    context.configure(
        target_metadata=target_metadata,
        # PostgreSQL is the only backend this project targets (RDS 16 in
        # production, pgvector/pgvector:pg16 locally), so there is no
        # cross-dialect batch mode to configure and no reason to pretend there
        # might be.
        compare_type=True,
        # Print the actual SQL rather than a progress bar. Migrations here are
        # reviewed as diffs before they run; being able to read the emitted DDL
        # in the terminal is worth more than the progress bar.
        echo=False,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to anything.

    Used by ``alembic upgrade head --sql`` to produce a script a DBA can review
    or run by hand — which is the normal path for a production RDS change, where
    the operator would rather paste reviewed SQL than trust an unattended
    migration.
    """
    _configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    """Run the migrations against an already-open async connection.

    Note the connection is *not* closed here. Alembic's context manager is not
    async-aware, so closing an AsyncConnection from inside a sync callback is
    what produces "await wasn't used with future" and
    "attached to a different loop" at shutdown. `engine.dispose()` in the
    finally-block of the caller handles it in the async context where it belongs.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Create the AsyncEngine, connect, and run the migrations inside the loop."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool, not the default QueuePool. A migration is a short,
        # one-shot process: pooling would buy nothing and risks leaving an idle
        # session held open against RDS long after `alembic` has exited, which
        # on a small instance consumes a connection slot that the application
        # needs. Disposing is strictly safer here.
        poolclass=NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Online path: build an async engine and drive it from asyncio.run().

    This is the modification that the stock synchronous template does not have.
    """
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    # No guard here, deliberately. The offline path (`alembic upgrade head --sql`)
    # renders DDL to stdout and opens no connection, so there is nothing remote
    # for it to touch. Blocking it would break the one workflow that exists to
    # make a remote migration safe: render, read the SQL, then decide.
    run_migrations_offline()
else:
    # The URL is injected into the config *here*, from the environment, for the
    # same reason it is absent from alembic.ini: no credential belongs in a
    # tracked file. This assignment is what `async_engine_from_config` reads via
    # `prefix="sqlalchemy."` above.
    url = _database_url()
    # Checked before the engine exists, so a wrong target fails without a single
    # packet having been sent.
    _assert_local_target(url)
    config.set_main_option("sqlalchemy.url", url)
    run_migrations_online()