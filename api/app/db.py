"""lemondrop API — the engine, its lifecycle, and the health probe.

This module owns exactly three things: an ``AsyncEngine``, the two functions
that create and dispose it, and a ``ping()`` that reports whether the database
can be reached. There is no session layer, no declarative model and no query in
here — the store layer that will use this engine is a later phase, and
everything below is built so that phase can be added without touching it.

The two things this module is most careful about:

* **The engine is created inside the FastAPI lifespan, never at import.** See
  ``startup()``.
* **Nothing logged or raised out of this module can contain a credential.**
  See ``_redact`` — it is the single sanitisation helper, and every error path
  in this file goes through it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import DB_PING_TIMEOUT_SECONDS, DATABASE_URL_ENV_VAR, Settings, engine_kwargs, get_settings

logger = logging.getLogger(__name__)

# The string substituted for anything that looks like a credential.
# Chosen to be unmistakably not-a-value: a reader scanning a log can tell
# redaction happened rather than wondering whether the log is truncated.
REDACTED = "***REDACTED***"

# What `ping()` reports when the database answered. The SUCCESS vocabulary
# belongs to `main.py` (`_PROBE_OK`) and is deliberately not duplicated here —
# `PingResult.ok` is a bool, so `main.py` supplies the word. Two constants
# meaning "ok" in two modules is two constants that eventually disagree.
#
# Used only when the engine could not even be constructed, where there is no
# verdict to report and only a reason.
_UNCONFIGURED = "unconfigured"

# The longest a `PingResult.detail` may be.
#
# This string is serialised straight into the body of `GET /health/ready`, so it
# is read by whoever is calling the API — including a load balancer and anyone
# reading a response in a terminal. Without a cap, one verbose
# configuration error turns that field into a wall of prose: the unconfigured-
# database path alone produces several sentences, all of which are instructions
# meant for whoever is operating the service, not for a client reading a status.
#
# So the same division of labour `_post_upstream` uses in main.py applies here:
# the FULL text is written to the log by the caller that built it, and the
# client gets enough to act on. Collapsed to one line as well as capped, so a
# multi-line driver message cannot smuggle newlines into a JSON field someone
# will print.
_MAX_DETAIL_CHARS = 120


def _brief(detail: str) -> str:
    """Collapse a verdict to one short line, for the response body.

    The cap is applied HERE, at the point the verdict is constructed, rather
    than at the route that serialises it. That is deliberate: there is exactly
    one way to build a `PingResult`, so a future caller cannot forget the cap
    and ship a paragraph to a client. The full text has already been logged by
    the time this runs.
    """
    collapsed = " ".join(detail.split())
    if len(collapsed) > _MAX_DETAIL_CHARS:
        return collapsed[:_MAX_DETAIL_CHARS] + "..."
    return collapsed


def _password_of(dsn: str) -> str:
    """Return just the password component of a DSN, or "" if there is not one.

    Never raises: a malformed DSN is a problem for whoever needs to connect, and
    a logging helper must not be the thing that crashes. Uses SQLAlchemy's own
    parser rather than `urllib.parse`, because that is the parser the engine
    itself will use — so the component extracted here is the component that is
    actually going to be transmitted.
    """
    try:
        return make_url(dsn).password or ""
    except Exception:  # noqa: BLE001 — ArgumentError from a malformed DSN
        return ""


def _secrets_of(settings: Settings | None) -> tuple[str, ...]:
    """Every string in these settings that must never be logged or returned.

    The full DSN AND the bare password, because a driver error can quote either:
    some embed the URL, and a message can carry the password without the URL
    around it. Assembled in one function so a new secret cannot be added to the
    config without this noticing, which is the actual risk.

    Returns () for a missing settings object rather than raising — this is
    called on error paths, and a logging helper must never be the thing that
    crashes.
    """
    if settings is None:
        return ()
    dsn = settings.database_url.get_secret_value()
    return (dsn, _password_of(dsn))


def _redact(text_to_clean: str, secrets: tuple[str, ...]) -> str:
    """Remove every known credential substring from a string.

    Three substitutions, and all three are needed:

    1. The full DSN, because SQLAlchemy and asyncpg both embed the connection
       URL in some error paths and in their own diagnostics.
    2. The raw password, because a driver error can quote it without the
       surrounding URL.
    3. The PERCENT-ENCODED password, because a URL round-tripped through a
       parser or a query string encodes it, and `abc/def` does not appear
       verbatim in a message that contains `abc%2Fdef`.

    Percent-encoding is the one that is easy to miss and the one that actually
    bites: it means a naive "does the message contain the password" check can
    pass while the password is sitting in the log encoded.

    Nothing else is redacted. Over-redaction destroys the diagnostic value of a
    message, and the operator needs to be able to read a real Postgres error.

    This is THE sanitisation helper for this module. Every error path — the
    timeout branch, the SQLAlchemy branch, the catch-all branch, the dispose
    failure and the settings-construction failure — passes its text through it.
    """
    cleaned = text_to_clean
    for secret in secrets:
        if not secret:
            # An empty secret would match everywhere and turn the whole message
            # into REDACTED. Skipping is correct: "" carries no credential.
            continue
        cleaned = cleaned.replace(secret, REDACTED)
        encoded = quote(secret, safe="")
        if encoded != secret:
            # Only substitute the encoded form when it differs, so a
            # password of only unreserved characters is not processed twice.
            cleaned = cleaned.replace(encoded, REDACTED)
    return cleaned


def _describe(exc: BaseException, secrets: tuple[str, ...]) -> str:
    """Render an exception as a short, credential-free, single-line description.

    The exception CLASS name is included rather than relying on its message
    alone, for the same reason `main.py` does the same in `_probe`: driver
    messages vary between versions and are not a stable thing to parse, while
    the class name is. Whitespace is collapsed so a multi-line driver message
    cannot smuggle a wall of text into a JSON field a client will print.
    """
    return _redact(" ".join(f"{type(exc).__name__}: {exc}".split()), secrets)


@dataclass(frozen=True)
class PingResult:
    """The verdict of one `SELECT 1`.

    `ok` is a bool and `detail` is a short human-readable string, rather than
    `detail` being a magic value compared against a string. A bool cannot be
    misspelled at the call site, and `main.py` supplies the success word itself
    (its `_PROBE_OK`) rather than this module inventing a second one.
    """

    ok: bool
    # "ok" when ok is True; otherwise a short description of the failure. Always
    # sanitised before it gets here.
    detail: str


@dataclass
class Database:
    """A live engine, or the record of why there is not one.

    Holds `engine` even when it is None so that the lifespan and the readiness
    route have ONE object to carry around and no `if engine is None` branch at
    every call site. `ready` and `problem` are the honest account of the state:
    a `Database` with no engine is a valid value here, not an error.

    `settings` is None only in the one case where settings could not be
    constructed at all, so `ping()` reports the recorded `problem` rather than
    asking an object that does not exist for its host.
    """

    engine: AsyncEngine | None
    ready: bool
    # Why it is not ready. Sanitised, and safe to log.
    problem: str = _UNCONFIGURED
    settings: Settings | None = None

    def host(self) -> str:
        """The loggable identity of the target. The ONLY part of a DSN logged."""
        if self.settings is None:
            return "<unconfigured>"
        return self.settings.database_host

    def secrets(self) -> tuple[str, ...]:
        """Every string in this configuration that must never be logged."""
        return _secrets_of(self.settings)

    async def ping(self) -> PingResult:
        """Ask the database whether it is reachable. Never raises.

        A failed health check is a NORMAL, REPORTABLE outcome, not an exception
        to propagate. The route that calls this needs to answer 503 with a
        reason; an exception escaping here would become an unhandled 500 with a
        body that tells the operator nothing about which dependency is at fault.

        Two distinct failures, handled separately because they mean different
        things to whoever has to fix them:

        * no engine at all — the process is misconfigured, or the database was
          unreachable at startup. Nothing was even attempted;
        * an engine that could not connect or timed out — the path to the
          database is broken right now.
        """
        if self.engine is None:
            return PingResult(ok=False, detail=_brief(self.problem))

        secrets = self.secrets()

        try:
            # `SELECT 1` rather than a real query, on purpose: readiness asks
            # "is there a working connection", not "is the schema correct" or
            # "is the table empty". A readiness probe that touched `documents`
            # would report on the data too, and would start failing for reasons
            # that have nothing to do with whether this process can connect.
            #
            # Bounded by DB_PING_TIMEOUT_SECONDS via wait_for, in addition to
            # asyncpg's own connect timeout. Two independent bounds because they
            # protect different things: the connect timeout bounds the network
            # path, and wait_for bounds everything else — including the case
            # where a connection is checked out of the pool but the pool itself
            # is exhausted, which wait_for catches and command_timeout does not.
            await asyncio.wait_for(self._select_one(), timeout=DB_PING_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            # Deliberately distinct wording: "the database is slow" and "the
            # database is absent" have different causes and different fixes, and
            # collapsing them into one message costs an operator an hour.
            detail = f"timeout after {DB_PING_TIMEOUT_SECONDS}s"
            logger.warning("database ping timed out against %s", self.host())
            return PingResult(ok=False, detail=_brief(detail))
        except SQLAlchemyError as exc:
            # SQLAlchemy wraps driver errors here, and its messages can embed the
            # connection URL. Redacted through the one helper, and only the
            # CLASS name plus a sanitised message is logged — the original
            # exception is deliberately not interpolated, because an attached
            # traceback is readable by an operator with the process's memory
            # while a formatted message is copied into log aggregators and chat
            # transcripts.
            detail = _describe(exc, secrets)
            logger.warning("database ping failed against %s: %s", self.host(), detail)
            return PingResult(ok=False, detail=_brief(detail))
        except Exception as exc:  # noqa: BLE001 — a driver raising something exotic
            # asyncpg raises a few types outside SQLAlchemy's hierarchy for
            # conditions SQLAlchemy does not wrap. A health check must not have
            # a hole in it that produces a 500.
            detail = _describe(exc, secrets)
            logger.warning("database ping failed against %s: %s", self.host(), detail)
            return PingResult(ok=False, detail=_brief(detail))

        return PingResult(ok=True, detail="ok")

    async def _select_one(self) -> None:
        """Execute the probe query on its own connection, then release it.

        A `connect()` rather than a pooled checkout where possible: `connect()`
        is the cheapest thing that proves the path works, and it avoids making a
        readiness probe compete with real traffic for one of three connections.

        The `text()` wrapper rather than a driver-specific execute: this is
        Core, so the statement is dialect-neutral and portable to the RDS
        Postgres 16 this runs against in production without a change.
        """
        if self.engine is None:  # pragma: no cover — guarded by the caller
            return
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))


async def startup(settings: Settings | None = None) -> Database:
    """Create the engine, attempt one ping, and return the resulting `Database`.

    ── WHY THE ENGINE IS BUILT HERE AND NOT AT IMPORT TIME ────────────────────
    An ``AsyncEngine`` binds its pool — and therefore its connections — to the
    event loop that was running when it was created. Constructing one at module
    import means constructing it against whatever loop happened to exist at
    import time: the loop of the first ``asyncio.run()`` in a test, the
    ``uvloop`` instance uvicorn creates, or none at all. The engine then hands
    out connections attached to the wrong loop, and the failure surfaces much
    later, at shutdown, as either:

        RuntimeError: Task ... got Future ... attached to a different loop
        RuntimeError: await wasn't used with an Future

    Both messages describe a symptom several steps from the cause, and both are
    miserable to diagnose — the traceback points at library internals rather
    than at the line that created the engine. So the engine is created inside
    the lifespan startup, where the loop that will actually serve requests is
    already running, and disposed in the shutdown on that same loop.

    ── WHY THIS NEVER RAISES ──────────────────────────────────────────────────
    An unreachable or unconfigured database must NOT stop the process from
    serving. Two reasons, one operational and one architectural:

    * Operationally, this API is not only a database client. `/embed` and
      `/rerank` work without any database at all, and a database blip is a
      common, self-healing condition. Crashing the container turns a recoverable
      dependency failure into a restart, and a restart cycle during a brief
      outage extends the outage.
    * Architecturally, the `api` service in `docker-compose.yml` now sets
      `DATABASE_URL`, built by interpolation from `DEV_DB_USER` /
      `DEV_DB_PASSWORD` / `DEV_DB_NAME`. Those three are defined for the local
      devdb and are NOT in the environment on EC2, where they interpolate to
      empty strings and the container receives a DSN that cannot possibly
      authenticate. A startup that hard-failed on that would refuse to boot the
      image that the api healthcheck, `scripts/boot.sh` and the Milestone 2 ALB
      target group all depend on. So the correct behaviour is to serve, say
      clearly that the database is not configured, and report 503 on readiness —
      which is precisely what `ping()` returning a verdict instead of raising
      produces.

    So: log it loudly, record the reason on the `Database`, and let the process
    come up. Liveness stays 200 (the process is fine) and readiness goes 503
    (requests needing the database must not be sent here). Both claims are true
    at the same time, and saying so is the whole design.
    """
    try:
        resolved = settings if settings is not None else get_settings()
    except Exception as exc:  # noqa: BLE001 — any misconfiguration, incl. RuntimeError
        # No settings object exists yet, so the secrets come from the raw
        # environment value: the only credential that could have been involved.
        raw = os.environ.get(DATABASE_URL_ENV_VAR, "")
        secrets = (raw, _password_of(raw))
        detail = _describe(exc, secrets)
        logger.error("database is not configured, the API will serve without it: %s", detail)
        return Database(engine=None, ready=False, problem=detail)

    # create_async_engine itself does not CONNECT — it builds the pool lazily.
    # So a wrong host or a wrong password does not fail HERE; the first actual
    # connection failure happens on the ping below.
    #
    # But it is not exception-free: it PARSES the DSN, and a malformed one (a
    # missing `postgresql://` scheme, say — the single most common typo there
    # is) raises `ArgumentError` right here. Left unhandled, that exception
    # would escape `startup()` and out through the lifespan, which means a
    # one-character typo in `.env` would refuse to boot the container and take
    # the compose healthcheck, `scripts/boot.sh` and the ALB target group with
    # it. That directly contradicts the "never raises" contract this function
    # documents, so the parse is inside the same promise.
    #
    # Note the message: SQLAlchemy 2.0.54's is "Could not parse SQLAlchemy URL
    # from given URL string" and does NOT quote the URL — but that is a
    # property of this version, not a guarantee, and it is exactly the kind of
    # thing that changes between releases. The exception is still redacted
    # through the one helper, so a future SQLAlchemy that starts quoting the URL
    # cannot turn a typo into a credential leak.
    secrets = _secrets_of(resolved)
    try:
        engine = create_async_engine(
            resolved.database_url.get_secret_value(),
            **engine_kwargs(resolved),
        )
    except Exception as exc:  # noqa: BLE001 — ArgumentError from a malformed DSN
        detail = _describe(exc, secrets)
        logger.error("database engine could not be created, the API will serve without it: %s", detail)
        return Database(engine=None, ready=False, problem=detail, settings=resolved)

    database = Database(engine=engine, ready=False, settings=resolved)
    verdict = await database.ping()
    database.ready = verdict.ok
    if not verdict.ok:
        database.problem = verdict.detail
        # Deliberately a warning, not an exception: this is a degraded start,
        # not a fatal one. See the docstring above.
        logger.warning(
            "database pool created but the database is NOT ready (%s) at %s",
            verdict.detail,
            database.host(),
        )
    else:
        # Only ever the HOST — see `Settings.database_host` for why the full DSN
        # is not loggable.
        logger.info("database pool ready at %s", database.host())

    return database


async def ping(database: Database | None) -> PingResult:
    """Probe a `Database`, tolerating the absence of one.

    The module-level counterpart to `Database.ping`, so a caller holding
    `app.state.database` does not need an `if ... is None` branch of its own.
    The `None` case is real rather than defensive: an app driven without its
    lifespan (an ASGI test harness that does not run startup, a route imported
    standalone) has no database, and that must be reported as not-ready rather
    than raise an `AttributeError` into a 500.
    """
    if database is None:
        return PingResult(ok=False, detail=_brief("not started"))
    return await database.ping()


async def close(database: Database | None) -> None:
    """Dispose the engine and release every pooled connection.

    Called from the lifespan shutdown, and deliberately tolerant of `None`: the
    shutdown half of a lifespan runs even when startup failed part-way, and
    raising there would replace a useful error with an unhelpful one.

    `dispose()` closes all checked-in and idle connections. It does not kill
    connections currently checked out — those are returned and closed as their
    holders release them — which is why this belongs on the shutdown path of a
    process that is about to exit rather than being something to worry about
    mid-life.

    Never raises. A failure to close is worth a log line, not a shutdown that
    dies in a `finally` and masks whatever was actually being handled.
    """
    if database is None or database.engine is None:
        return

    try:
        await database.engine.dispose()
        logger.info("database pool disposed")
    except Exception as exc:  # noqa: BLE001 — shutdown must complete regardless
        # Redacted against the settings this object was built with, so a driver
        # error that quotes the DSN cannot reach the log on the way out.
        logger.warning("disposing the database pool failed: %s", _describe(exc, database.secrets()))
    finally:
        # Cleared so a second call to close() is a no-op and, more importantly,
        # so nothing can use the engine after it has been disposed.
        database.engine = None