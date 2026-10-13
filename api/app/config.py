"""lemondrop API — application settings, read from the environment.

This module answers one question: *what does this process need to know before it
can do anything?* Everything here is read once, at settings-construction time,
into a single frozen object, so that no later code has to reach back into
``os.environ`` and no two call sites can disagree about a value.

Three decisions in this file are load-bearing and all three are about the DSN:

1. ``DATABASE_URL`` is a ``pydantic.SecretStr``, not a ``str``. See
   ``Settings.database_url``.
2. The application DSN and ``ALEMBIC_DATABASE_URL`` are DIFFERENT variables and
   must stay different. See ``DATABASE_URL_ENV_VAR``.
3. A DSN that parses but carries no username or no password is rejected HERE, at
   construction, rather than left for the driver to complain about. See
   ``Settings._must_carry_a_username_and_a_password``. This is the check that
   catches ``postgresql+asyncpg://:@postgres:5432/`` — what a ``${DEV_DB_*}``
   variable that was never defined interpolates to on a host without a ``.env``,
   which is otherwise set, non-blank, and completely useless.

Everything else in here is either a named constant with a stated reason or a
small helper that exists to keep a credential out of a log line.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, SecretStr, computed_field, field_validator
from sqlalchemy.engine import make_url

# ── Which environment variable carries the application DSN ────────────────────
#
# This is NOT `ALEMBIC_DATABASE_URL`, and the two must never be unified. Alembic
# runs migrations: `CREATE EXTENSION vector`, `CREATE TABLE`, `ALTER TABLE`. That
# requires a role with DDL rights and ownership of the schema. This application
# only ever runs `SELECT 1` and, once the store layer lands, one parameterised
# `SELECT` against `documents` — which needs DML on one table and nothing else.
#
# Pointing both at one variable is how a runtime role quietly acquires the DDL
# rights it was supposed to be denied: it is a single `.env` edit that is
# invisible at review time and completely effective at runtime, because the
# privilege is decided by *which credentials the URL carries*, not by which tool
# reads it. Keeping the variables separate means the application's credentials
# can be a genuinely least-privilege role in production, and that revoking DDL
# from it is a one-line change that cannot break migrations.
#
# Locally both point at the same devdb and the local devdb role happens to be a
# superuser — that is a property of the throwaway dev container, NOT evidence
# that the split works. The split is what makes a least-privilege production
# role possible; the local devdb cannot demonstrate it.
DATABASE_URL_ENV_VAR = "DATABASE_URL"

# ── Pool sizing ───────────────────────────────────────────────────────────────
#
# These are the numbers most likely to be "fixed" later by someone copying
# SQLAlchemy's defaults, so here is the measurement they are sized against.
#
# Milestone 2 measured this host as a `t3.micro`: 913Mi total RAM, with roughly
# 280Mi available at rest once the two llama.cpp models are resident. That is the
# whole budget, and the two models are the reason the API is worth running at
# all — they are not optional overhead that a larger pool could displace.
#
# The cost being sized is that **every PostgreSQL connection is a separate
# backend OS process**. PostgreSQL 16 shares one buffer pool between backends,
# so a connection is not a fresh slice of shared_buffers, but each backend still
# costs private process memory plus its own ``work_mem`` and sort/temp buffers
# while a query runs. Fifteen of them is fifteen processes on a box with ~280Mi
# of headroom and two resident models — which is a memory-exhaustion event, not
# a throughput problem.
#
# SQLAlchemy's defaults are `pool_size=5, max_overflow=10` — 15 concurrent
# connections. They are a reasonable generic default for a server whose job is
# serving connections. They are not a reasonable default for a `t3.micro` whose
# job is running two CPU inference models, and the defaults know nothing about
# either fact.
#
# The demand being sized against is also low, which is the other half of the
# argument. The retrieval path this pool exists for is a single parameterised
# `SELECT` with a `<=>` ordering — millisecond-scale on an indexed table. The
# API is not a high-throughput data service; it is an orchestrator whose
# genuinely slow calls are the 120-second inference requests, and those hold no
# database connection at all. Nothing in this service generates enough
# concurrent database work to need more than a handful of connections.
#
# So: 2 pooled, 1 overflow, 3 concurrent per API process. Overflow 1 rather
# than 0 so a brief burst queues for one connection instead of failing
# instantly; past that, `DB_POOL_TIMEOUT_SECONDS` applies backpressure — which
# is the correct behaviour, because a request queue bounded by a timeout is
# better than unbounded memory growth on a memory-constrained host.
DB_POOL_SIZE = 2
DB_MAX_OVERFLOW = 1

# How long a caller waits for a pooled connection before giving up. Deliberately
# LONGER than the connect timeout: waiting on a busy pool is a normal, transient
# condition and the waiter is queued behind real work, whereas a connect timeout
# means something is wrong with the path to the server. Failing the first fast
# and waiting on the second correctly reports the second as a timeout.
DB_POOL_TIMEOUT_SECONDS = 10.0

# asyncpg's connect timeout — how long to wait for the TCP connection and the
# authentication handshake. Short: on loopback (local devdb) this is
# milliseconds, and against RDS it is a single TCP round trip plus TLS. Ten
# seconds here would mean the network is blackholing, and there is nothing to be
# gained by waiting longer than the caller's own patience.
DB_CONNECT_TIMEOUT_SECONDS = 5.0

# asyncpg's per-statement timeout. This is NOT a query-complexity policy — it is
# the backstop that stops a wedged query from holding a pooled connection
# forever on a pool of three. Sized above the expected cost of the one query
# this service runs by a wide margin.
DB_COMMAND_TIMEOUT_SECONDS = 10.0

# The budget for `SELECT 1` in `db.ping()`. Shortest of all of these, on purpose:
# this runs on a readiness probe, which fires every few seconds for the life of
# the process and must produce a fast answer. A readiness probe that takes its
# own sweet time is a readiness probe that reports stale truth.
DB_PING_TIMEOUT_SECONDS = 2.0

# ── Embedding width ───────────────────────────────────────────────────────────
#
# The column is `embedding vector(384)`, created by migration 0001 and owned by
# the schema. This constant is the application's belief about the same fact, and
# the two are asserted against each other in `api/tests/test_db.py`.
#
# Why assert rather than trust: swapping `bge-small-en-v1.5` for a wider model
# does not fail anywhere on its own. The embedder returns a different number of
# floats, the API's `dimensions` field reports it faithfully, and the INSERT
# fails at the column — or, worse, succeeds against a `vector` column without a
# typmod constraint and quietly destroys the distance metric the index depends
# on. Checking at the boundary turns "retrieval quality mysteriously degraded
# weeks later" into an immediate, named failure.
EMBEDDING_DIM_ENV_VAR = "EMBEDDING_DIM"

# The width the migrated schema declares. Not a default that can be moved: this
# is what `documents.embedding` is, and a mismatch is a bug to fix rather than a
# setting to tune.
SCHEMA_EMBEDDING_DIM = 384


class DatabaseUrlResolver(Protocol):
    """The seam an alternative credential source plugs into.

    Defined now, implemented only by the environment reader below, so that the
    substitution point is a named, documented shape rather than something the
    next person has to invent inside `get_settings()`.

    ── WHY THIS EXISTS AND WHAT IS DELIBERATELY NOT HERE ──────────────────────
    The intended AWS credential path reads the host and port from SSM
    (`/lemondrop/dev/db/{host,port}`) and a secret ARN from the same prefix,
    fetches the password from Secrets Manager, assembles a DSN, and returns it —
    with the credential existing only in memory for the life of the process.

    None of that is written, because it is NOT this phase and it CANNOT BE
    verified in this phase: the `feat/aws-infrastructure` IAM changes are not
    applied, so the deployed permissions for SSM and Secrets Manager are
    unverified and assumed to be nothing. Writing code against unverified
    permissions produces code whose failure mode is unknown. boto3 is
    deliberately absent from `api/requirements.txt` for the same reason.

    What this seam guarantees is that adding it later touches ONE function:
    rebind `DATABASE_URL_RESOLVER` at import, or pass a different resolver into
    `get_settings()`. `db.py` never learns where the DSN came from, never
    fetches a credential, and never needs a boto3 import. If that ever stops
    being true, this seam has been bypassed and the next credential source will
    leak into the database layer.
    """

    def __call__(self) -> str: ...


def resolve_database_url_from_environment() -> str:
    """Return `DATABASE_URL` from the environment, or raise explaining its absence.

    Raising rather than defaulting is the whole point. A default here would be a
    DSN pointing *somewhere* — a plausible-looking localhost that may or may not
    be the database anyone meant — and the failure would not be that the app
    started, it would be that the app started WRONGLY and served traffic against
    a database nobody chose. A loud stop at startup costs one restart; a silent
    default costs an incident.

    Note this function returns the raw `str`. Redaction is not its job — it is
    `Settings`' job, and redacting here would mean the caller could never build a
    working URL at all.
    """
    raw = os.environ.get(DATABASE_URL_ENV_VAR)

    # Both the unset case and the blank case, and the distinction is worth
    # keeping: `DATABASE_URL=` in a `.env` file is *set*, so a bare
    # `if not raw` reads naturally but an explicit check makes the intent
    # obvious to the next reader. An empty DSN is exactly as unusable as a
    # missing one, and just as common — it is what you get from
    # `DATABASE_URL=$SOMETHING` when `$SOMETHING` is unset.
    if raw is None or not raw.strip():
        raise RuntimeError(
            f"{DATABASE_URL_ENV_VAR} is not set, and there is deliberately no default.\n"
            "\n"
            "This API will not guess which database to connect to: a wrong guess\n"
            "here starts successfully and then serves traffic against a database\n"
            "nobody chose, which is far worse than not starting.\n"
            "\n"
            "For the local devdb container:\n"
            f"    {DATABASE_URL_ENV_VAR}=postgresql+asyncpg://<user>:<password>@127.0.0.1:5432/<database>\n"
            "\n"
            "See .env.example. Note this is a DIFFERENT variable from\n"
            "ALEMBIC_DATABASE_URL on purpose — the application must not hold DDL\n"
            "rights, and sharing one URL is how it acquires them."
        )

    return raw.strip()


# The single, named place an alternative credential source would be bound.
# Today: the environment. Later: an SSM/Secrets Manager resolver. See
# `DatabaseUrlResolver` for why the substitution point is defined now and
# implemented then.
DATABASE_URL_RESOLVER: DatabaseUrlResolver = resolve_database_url_from_environment


class Settings(BaseModel):
    """Everything this process needs to know, validated once, at construction.

    A `pydantic.BaseModel` rather than a dataclass or a module of globals, for
    three reasons that are all load-bearing here:

    1. `SecretStr` is a pydantic type. It is what keeps the DSN out of every
       `repr()` below, and using a dataclass to avoid pydantic would mean
       reimplementing that redaction by hand.
    2. Validation happens at construction, once, so a misconfigured process
       fails at the boundary rather than at the first query that needs the value.
    3. `frozen=True` means the settings cannot change halfway through a request.
       A mutable settings object is a settings object two coroutines will
       eventually disagree about.
    """

    # Frozen: settings are read, never rewritten. See the class docstring.
    model_config = ConfigDict(frozen=True)

    # The DSN the application connects with, as a SecretStr.
    #
    # ── WHY SecretStr AND NOT str ─────────────────────────────────────────────
    # A plain `str` is not a safe container for a credential, because a `str`
    # has no idea what it is holding. It renders itself in full anywhere it is
    # interpolated: an f-string in a log line, the `locals()` dump in a
    # traceback, a dataclass repr in a debug print, a `pdb` session, a crash
    # report attached to a bug. None of those are mistakes in the sense of
    # being unusual — they are ordinary debugging.
    #
    # `SecretStr` renders as `**********` in `repr()` and `str()`, so all of
    # those become useless for reading the value while remaining completely
    # normal for everything else. Retrieval still requires an explicit
    # `.get_secret_value()` call, which is the point: reading the real DSN is
    # something you have to write down deliberately, so the places that do it
    # are greppable and few.
    #
    # Cost: zero. Pydantic is already a transitive dependency via FastAPI, and
    # `main.py` already imports from it.
    database_url: SecretStr

    # The width of the vectors the embedder produces. Validated against
    # `SCHEMA_EMBEDDING_DIM` below rather than merely read, so a model swap that
    # changes the width fails here — loudly, at the boundary — instead of
    # failing later at the column or, worse, not failing at all.
    embedding_dim: int

    @field_validator("database_url")
    @classmethod
    def _must_carry_a_username_and_a_password(cls, value: SecretStr) -> SecretStr:
        """Reject a DSN that parses but cannot possibly authenticate.

        ── THE DEFECT THIS EXISTS TO FIX ─────────────────────────────────────────
        `docker-compose.yml` builds the container's `DATABASE_URL` by
        interpolation::

            DATABASE_URL: "postgresql+asyncpg://${DEV_DB_USER}:${DEV_DB_PASSWORD}@postgres:5432/${DEV_DB_NAME}"

        On EC2 — where `DEV_DB_*` is defined for the local devdb and is NOT in
        that host's environment — Compose substitutes empty strings for the
        three unset variables, and the value the container receives is::

            postgresql+asyncpg://:@postgres:5432/

        That is NOT an empty string, so it sails straight past the only check
        the resolver performs (set and non-blank). It is non-blank and useless:
        a username of `""` and a password of `""`. The process builds a
        `Settings`, `db.startup` builds a pool, the engine reports itself ready
        to construct, and the failure arrives at the first real connection as an
        opaque driver-level complaint about a server refusing the credentials —
        several steps away from the shell variable that was never exported.

        Measured on this host's SQLAlchemy 2.0.54, that string parses cleanly
        into `username=''` and `password=''`, which is why the check below has
        to read those two components explicitly rather than rely on a parse
        error to announce the problem.

        ── WHY AN EMPTY PASSWORD IS REJECTED, STATED HONESTLY ───────────────────
        An empty password is not automatically a mistake in PostgreSQL. Peer
        authentication over a unix socket is a legitimate, widely-deployed mode
        that uses no password at all, and "this DSN has no password" is
        therefore NOT a universal truth about DSNs.

        **THIS CHECK FORBIDS THAT.** Peer, trust and socket authentication are
        not discouraged for this application — they are out of scope, the same
        way migration 0001 states plainly what its primary-key choice rules out.
        Naming the excluded thing is what stops the next reader from
        rediscovering the idea and assuming it was merely never considered.

        The justification is a property of THIS project, not of PostgreSQL: every
        credential this application ever uses is a password. Locally it is
        `DEV_DB_PASSWORD`; in production it comes from Secrets Manager through
        the `DatabaseUrlResolver` seam. The API connects over TCP to RDS — there
        is no unix socket to peer over, and no deployment in which peer auth is
        intended. So an empty username or an empty password can ONLY ever be an
        interpolation failure, a variable that was not defined; it can never be
        a deliberate configuration. Given that, accepting it would mean
        accepting a typo as though someone had meant it.

        ── WHY CONFIGURATION TIME AND NOT CONNECT TIME ───────────────────────────
        Same reason as every other check in this class: construction is the
        boundary where the environment becomes something the rest of the process
        is entitled to trust, and it is the last point at which the answer is
        still obviously about configuration.

        A connect-time check is strictly worse for this particular defect. By
        the time a connection is attempted the process has built a pool, logged
        "database pool ready", and answered liveness 200. The operator is then
        reading asyncpg internals to discover that they forgot to export a shell
        variable — and liveness has already told them the service is healthy.

        So on EC2 this check is the entire point: an opaque connection failure
        becomes a message that names the missing variable, at startup, before
        anything has claimed to be working.

        ── WHAT IS NOT QUOTED HERE, AND WHY ─────────────────────────────────────
        Not the DSN, not the username, not the host, and not SQLAlchemy's own
        parse error. Every one of those is a substring of a credential in this
        system, and an exception message is the one string guaranteed to be
        pasted into a bug report, a chat transcript and a log aggregator. The
        message names the PROBLEM and nothing else. An operator who needs the
        value can read it in the environment they set it in.
        """
        dsn = value.get_secret_value()

        try:
            url = make_url(dsn)
        except Exception:  # noqa: BLE001 — ArgumentError, or a bare ValueError
            # `except Exception`, not `except ArgumentError`, and deliberately
            # so: SQLAlchemy does not raise ArgumentError for every malformed
            # DSN. A DSN with a non-numeric port raises a bare
            # `ValueError: invalid literal for int()` out of the parser, whose
            # message quotes the offending port. Catching only ArgumentError
            # would let that fragment become MY error message, so the catch is
            # at the width of everything the parser can throw.
            #
            # `from None` rather than `from exc`, because the chained traceback
            # would render the underlying parser error — which quotes the DSN in
            # some versions — directly above this one. Same reasoning as
            # `database_host` below, for the same reason.
            raise ValueError(
                f"{DATABASE_URL_ENV_VAR} is set but is not a URL this application can "
                "parse, so there is nothing to connect to. It must look like "
                "postgresql+asyncpg://<user>:<password>@<host>:5432/<database>.\n"
                "The value itself is not repeated here because it is a credential."
            ) from None

        # Both components are checked before raising, so a DSN missing BOTH —
        # which is exactly what an undefined `DEV_DB_*` produces — names both in
        # a single message. Reporting only the first would send the operator to
        # fix one variable and then meet the identical failure again.
        #
        # `not <component>` rather than `<component> == ""`, because SQLAlchemy
        # reports an absent component as None and an empty one as "". The
        # unsigned `postgresql://` case also lands here with both None, which is
        # correct: it cannot authenticate either.
        missing = [
            component
            for component, present in (("username", url.username), ("password", url.password))
            if not present
        ]
        if missing:
            raise ValueError(
                f"{DATABASE_URL_ENV_VAR} has no {' and no '.join(missing)}, so it cannot "
                "authenticate against any PostgreSQL server.\n"
                "\n"
                "This is almost always an UNSET variable interpolated into the DSN. "
                "docker-compose.yml builds this value from DEV_DB_USER, "
                "DEV_DB_PASSWORD and DEV_DB_NAME; a host where those are not defined "
                "produces a DSN that is set and non-blank but empty exactly where the "
                "credentials go, and that is the case this check exists to catch.\n"
                "\n"
                "Define the variables the DSN is built from (see .env.example), or set "
                "the DSN directly. The value is not repeated here because it is a "
                "credential."
            )

        return value

    @field_validator("embedding_dim")
    @classmethod
    def _must_match_the_schema(cls, value: int) -> int:
        """Reject an embedding width the migrated schema cannot hold.

        `documents.embedding` is `vector(384)`. Any other width is either an
        INSERT that fails (loud, fine) or — against a column declared without a
        typmod — an INSERT that succeeds and silently breaks the index's
        distance metric (silent, and the expensive kind of bug: retrieval
        quality degrades over weeks with nothing pointing at the cause).
        Checking at construction makes it an import-time-ish failure with a name
        in the message.
        """
        if value != SCHEMA_EMBEDDING_DIM:
            raise ValueError(
                f"EMBEDDING_DIM is {value}, but the `documents.embedding` column "
                f"is vector({SCHEMA_EMBEDDING_DIM}). These must match: the column "
                "is defined by migration 0001 and the width is a property of the "
                "embedding model, not a setting. If the model changed width, the "
                "column needs a migration — see api/alembic/README.md."
            )
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_host(self) -> str:
        """ONLY the host part of the DSN, for logging.

        This is the single sanctioned way to say anything about the database in
        a log line. The host is the one component of a DSN that identifies the
        target without carrying the credential —
        `prod-db.abc123.us-east-1.rds.amazonaws.com` tells an operator which
        database is involved; the rest of the URL tells them the password.

        So the rule this property exists to enforce: **anything logged about the
        connection goes through this**. The full DSN is never logged, printed,
        formatted into an exception message, or returned to a client.

        It is a computed_field rather than a plain method for a reason that is
        about diagnosability: this puts the host into `repr(settings)` and into
        `model_dump()`, so a traceback's locals dump, a `pdb` session and a
        `logger.info("%r", settings)` all answer "which database is this?" —
        without the one component that would make the answer a credential leak.
        A redacted repr that says nothing at all is safe but useless; this is
        safe AND useful.

        Returns `"<unparseable>"` rather than raising on a malformed URL. Logging
        must not become a second way for a bad configuration to crash the
        process, and the detail of a malformed URL is exactly the kind of
        substring that carries the credential.
        """
        try:
            return make_url(self.database_url.get_secret_value()).host or "<unknown>"
        except Exception:  # noqa: BLE001 — ArgumentError from a malformed DSN
            # Summarised by condition, never by exception message: SQLAlchemy's
            # parse errors quote the offending string, and the offending string
            # is the credential.
            return "<unparseable>"


def get_settings(resolver: DatabaseUrlResolver | None = None) -> Settings:
    """Build the settings object, or raise a clear error naming what is missing.

    This is the one entry point. `db.py` takes a `Settings` rather than
    constructing one, so the database layer never reads the environment itself
    and can be exercised in a test with a deliberately wrong DSN.

    The optional `resolver` is the seam described on `DatabaseUrlResolver`. It
    defaults to the module-level `DATABASE_URL_RESOLVER` — read at CALL time,
    not at import time, so rebinding it works and so a test can pass a stub
    without mutating global state.
    """
    source = resolver if resolver is not None else DATABASE_URL_RESOLVER

    return Settings(
        # The one line in the codebase that reads a credential. Everything else
        # receives it already wrapped in a SecretStr.
        database_url=SecretStr(source()),
        # Defaulted rather than required: the width is a property of the model
        # the embedder runs, and the documented value is the correct one. But it
        # is still passed through the validator above, so an explicit wrong value
        # is rejected rather than quietly accepted.
        embedding_dim=int(os.environ.get(EMBEDDING_DIM_ENV_VAR, SCHEMA_EMBEDDING_DIM)),
    )


def engine_kwargs(settings: Settings) -> dict[str, Any]:
    """Return the `create_async_engine` keyword arguments, in one place.

    Assembling this in a function rather than inline in `db.create_engine` means
    every tunable above has exactly one consumer and one place to be read, and
    that a test can assert on the resulting configuration without constructing an
    engine — which matters, because constructing an engine binds it to the
    current event loop (see `db.py`).

    Note that no credential appears in this dict: `settings.database_url` is a
    `SecretStr`, and SQLAlchemy accepts it only via `create_engine(url=...)`
    which `db.py` passes separately. Nothing here needs the plaintext DSN.
    """
    return {
        # ── pool ──────────────────────────────────────────────────────────────
        "pool_size": DB_POOL_SIZE,
        "max_overflow": DB_MAX_OVERFLOW,
        "pool_timeout": DB_POOL_TIMEOUT_SECONDS,
        # The single most important line in db.py, justified there. Named here
        # only because it is a pool setting.
        "pool_pre_ping": True,
        # ── asyncpg ───────────────────────────────────────────────────────────
        "connect_args": {
            # Seconds to wait for connect + auth handshake. See the constant.
            "timeout": DB_CONNECT_TIMEOUT_SECONDS,
            # Per-statement backstop. See the constant.
            "command_timeout": DB_COMMAND_TIMEOUT_SECONDS,
            # Identifies this process in `pg_stat_activity`. Without it every
            # idle backend shows up as an anonymous connection, and "which of
            # these is ours" becomes a question nobody can answer on a box that
            # may have three API processes on it.
            "server_settings": {"application_name": "lemondrop-api"},
        },
        # ── logging ───────────────────────────────────────────────────────────
        # Suppresses bound parameters in SQLAlchemy's DEBUG logging. This is a
        # credential and privacy leak vector independent of the DSN: the
        # `hide_parameters=False` default writes the full parameter list of every
        # statement into the log, which for this service means user document text
        # and query strings. Off regardless of log level, because a log level
        # lowered for debugging is exactly when it starts.
        "hide_parameters": True,
    }