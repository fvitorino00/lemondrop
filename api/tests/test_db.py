"""Tests for the database layer: connection lifecycle, configuration, probes.

What this file is: half of it talks to the REAL local devdb over a REAL socket
with no mocking whatsoever, and half of it talks to the REAL running API over
real HTTP. Nothing here substitutes a fake engine or an in-process test client.
That is a deliberate departure from what is usually considered good practice for
a "unit" test file, and the reason is that the things this file protects are not
logic — they are wiring. A mocked pool would pass every assertion in this file
while the application failed to connect in production, because the mock agrees
with the code by construction and the database does not.

Preconditions, both of which must be true before pytest is invoked. From the
repository root:

    docker compose --profile devdb up -d --build postgres
    docker compose up -d --build api
    set -a && . ./.env && set +a

If the database is not running, the ping and dimension tests fail. If the API is
not running the updated image, the /health tests fail. **That is correct
behaviour, not a broken test.** A connection error means the dependency is down,
and the assertions here have no meaning without a live service behind them. So
there is no `pytest.skip()` anywhere in this file and there will not be one: a
skipped test is a test that has stopped testing while still reporting green, and
green-that-means-nothing is worse than red, because red gets read.

What this file protects, in order of how much damage it prevents:

* **Credentials never reaching a log, an exception or a repr.** One test. It is
  the most important test in the file and the only reason the rest of this file
  exists.
* The database being reachable and `ping()` reporting it truthfully.
* `EMBEDDING_DIM` agreeing with the `vector(384)` column the schema actually has.
* Liveness answering 200 without consulting anything, and readiness answering
  503 when a dependency is down.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Coroutine
from urllib.parse import quote

import pytest
import requests
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import ArgumentError

from app import db
from app.config import (
    DATABASE_URL_ENV_VAR,
    EMBEDDING_DIM_ENV_VAR,
    SCHEMA_EMBEDDING_DIM,
    Settings,
    get_settings,
)

# The API under test. Read from the environment with a localhost default,
# matching the convention in test_integration.py, so the suite can be pointed at
# another host without editing this file.
BASE_URL = os.environ.get("API_URL", "http://localhost:8000")

# The exact command that brings the precondition up. Named once and interpolated
# into every failure message below, so the operator's next step is printed by
# the test that failed rather than having to be remembered.
START_DEVDB = "docker compose --profile devdb up -d --build postgres"

# Deliberately wrong, and deliberately shaped so it CANNOT be a valid password
# for anything: a wrong credential must be wrong, not merely unusual. It is also
# long and distinctive so that finding it in a string is unambiguous — a test that
# searched for a two-character password could pass by accident.
WRONG_PASSWORD = "definitely-not-the-password-4f2a9c"

# A second distinctive marker, for the DSN-validation tests below. Same property
# as `WRONG_PASSWORD` and for the same reason — long and unmistakable, so that
# asserting it is ABSENT from a string is a real check. That is the whole point
# of having two: the redaction tests want a credential that is genuinely wrong,
# and these want one that is unmistakably a marker. Asserting the absence of a
# short or ordinary word ("password", "db", "user") proves nothing, because such
# a string is absent from almost any message by accident — and, worse, "user" is
# a substring of "username", which the error legitimately contains.
DISTINCTIVE_MARKER = "marker-only-7b31c9-not-a-real-password"


# ── Helpers ───────────────────────────────────────────────────────────────────


def with_database(
    action: Callable[[db.Database], Coroutine[Any, Any, Any]],
    settings: Settings | None = None,
) -> Any:
    """Run `action` against a started `Database`, then dispose it — in ONE loop.

    ── WHY THIS HELPER EXISTS ─────────────────────────────────────────────────
    An `AsyncEngine` is bound to the event loop that was running when it was
    created. Two separate `asyncio.run()` calls create two loops, so starting
    the engine in one and closing it in the other is exactly the "attached to a
    different loop" bug that `db.startup`'s docstring warns about — reproduced
    here in the test suite, where it would produce a failure that has nothing to
    do with the code under test and would be very easy to misread as a bug in
    `db.py`.

    So the entire lifecycle — startup, the action, and the close in a `finally`
    — happens inside a single `asyncio.run`. This also mirrors what the FastAPI
    lifespan does, so the test exercises the same shape the application uses.

    The `finally` matters for the same reason the lifespan's does: a test that
    fails must not leave a pool holding real connections to a real database.
    """

    async def _run() -> Any:
        database = await db.startup(settings)
        try:
            return await action(database)
        finally:
            await db.close(database)

    return asyncio.run(_run())


def configured_settings() -> Settings:
    """Build settings from the environment, failing with a usable message.

    `get_settings()` raises when `DATABASE_URL` is unset, and its message says
    how to set it. This wrapper adds the one thing it cannot know — that the
    value must match the devdb that `START_DEVDB` starts — so a first-time
    failure reads as instructions rather than as a stack trace.
    """
    try:
        return get_settings()
    except RuntimeError as exc:
        pytest.fail(
            f"{exc}\n\n"
            f"If {DATABASE_URL_ENV_VAR} is set but wrong, check the devdb is up:\n"
            f"    {START_DEVDB}"
        )


def assert_no_secret(needle: str, haystack: str, where: str) -> None:
    """Fail if `needle` appears anywhere in `haystack`.

    Extracted so every assertion below reads as the same shape and so the
    failure message names the place the leak was found — "the password appears
    in the log" is actionable, a bare `assert needle not in haystack` is not.
    """
    assert needle not in haystack, f"credential leak: the password appears in {where}"


# ── The database is reachable ─────────────────────────────────────────────────


def test_ping_reports_ok_against_the_configured_local_database():
    """`ping()` must succeed against the real devdb, using the configured DSN.

    This is the assertion that the whole local path works end to end: the DSN in
    `.env` parses, the async engine is built, the driver authenticates, `SELECT
    1` executes, and the verdict comes back ok. Every other test in this file
    that touches the database assumes this one passed — a suite where the ping
    test fails loudly and the dimension test fails for the same reason is a
    diagnosable outage, whereas one where the ping fails and the rest quietly
    work on a different assumption is not.

    The `finally` on the error path is what makes the failure message useful: it
    names the exact command that starts the database, because "the pool is not
    ready: timeout after 2.0s" on its own is a riddle.
    """
    settings = configured_settings()

    def _ping(database: db.Database) -> Coroutine[Any, Any, Any]:
        return database.ping()

    verdict = with_database(_ping, settings)

    if not verdict.ok:
        pytest.fail(
            f"ping() reported the database as not ready: {verdict.detail}\n"
            f"DSN host was {settings.database_host!r}.\n"
            f"If the host is wrong, check {DATABASE_URL_ENV_VAR} in .env.\n"
            f"If the database is simply not running:\n"
            f"    {START_DEVDB}"
        )

    assert verdict.ok is True
    assert verdict.detail == "ok"


# ── Credentials ───────────────────────────────────────────────────────────────


def test_a_wrong_password_never_reaches_an_exception_a_log_or_a_repr(caplog):
    """A failed authentication must leak the password NOWHERE.

    This is the most important test in the file, and it is the only thing
    standing between a credentials-in-logs bug and production. Everything else
    here is a regression guard against a nuisance; this one is a security
    control.

    Why the risk is real rather than theoretical: SQLAlchemy and asyncpg both
    put the connection URL into their error paths in some versions, and a
    connection failure is precisely the moment a developer adds a `print(exc)`
    or a `logger.exception` to find out what happened. So the two changes that
    make a credential leak — a driver that quotes its own URL, and a debugging
    line added on the day it first appeared — are the SAME day. The mitigation
    has to be in place before the bad day.

    So: a deliberately wrong password is configured, the connection is genuinely
    attempted and genuinely fails, and then FOUR separate places are checked for
    the secret string:

      1. the verdict returned to the caller, which is what reaches a client;
      2. every log record emitted during the attempt, at DEBUG and above, so
         SQLAlchemy's own engine logging is covered and not just this module's;
      3. `repr()` of the settings object, which is what an uncaught traceback's
         locals dump and a `pdb` session both show;
      4. every serialisation of the settings object — `model_dump()` and
         `model_dump_json()` — because "the repr is safe" is not the same claim
         as "the object is safe", and a future logger that dumps the model rather
         than its repr would defeat only the first.

    The connection is asserted to have FAILED as well. A test that passes
    because nothing was attempted protects nothing: this is why there is no
    `pytest.skip()` for an unreachable database here.

    And because `ok is False` is ALSO what a refused socket reports, "it
    failed" is asserted twice over: the endpoint is first proved reachable with
    the real credential (a precondition, not an assertion about the outcome),
    and the failure that follows is then required to be
    `asyncpg.InvalidPasswordError` — SQLSTATE 28P01, and a class name rather
    than a message, because `db._describe`'s docstring records that driver
    messages vary between versions. Together those two are what make this a
    test of the authentication path instead of a test of the string
    "no password in this message", which a closed port satisfies too.
    """
    good = configured_settings()
    good_dsn = good.database_url.get_secret_value()

    # ── PRECONDITION: the endpoint must be REACHABLE and accept this credential ─
    # `PingResult.ok` is False for EVERY failure mode — a wrong password, a
    # refused socket, a name that does not resolve, a timeout. So the step-0
    # assertion below is satisfied just as well by a closed port as by a server
    # that rejected the password, and every "the password is not in this
    # message" assertion after it then passes without the authentication path
    # ever being executed. Measured on this host: pointed at a closed port, this
    # test used to pass in 0.47s having asked nothing of any server.
    #
    # So the endpoint is proved ALIVE with the REAL credential first, before the
    # wrong one is configured. After this, a `ok is False` can only mean the
    # server saw the credential and said no — which is the entire claim.
    def _ping_good(database: db.Database) -> Coroutine[Any, Any, Any]:
        return database.ping()

    reachable = with_database(_ping_good, good)

    assert reachable.ok is True, (
        f"the configured database did not answer a ping with the REAL credential, so "
        f"this test cannot exercise an authentication failure: {reachable.detail}\n"
        f"DSN host was {good.database_host!r}.\n"
        f"If the host is wrong, check {DATABASE_URL_ENV_VAR} in .env.\n"
        f"If the database is simply not running:\n"
        f"    {START_DEVDB}\n"
        f"Without this, a refusal to connect would sail through every redaction "
        f"assertion below and be reported as if the password had been checked."
    )

    # Replace the real password component rather than the whole authority
    # string, so this keeps working if the username or host ever contains a
    # colon or an at-sign.
    bad_dsn = good_dsn.replace(db._password_of(good_dsn), WRONG_PASSWORD)

    # Assert the replacement actually happened, so a future change to the DSN's
    # shape cannot silently turn this into a test that configures the REAL
    # password and then asserts it does not leak.
    assert WRONG_PASSWORD in bad_dsn
    assert good_dsn not in bad_dsn

    bad_settings = Settings(database_url=SecretStr(bad_dsn), embedding_dim=SCHEMA_EMBEDDING_DIM)

    # DEBUG, so SQLAlchemy's engine logger — which is where a connection URL
    # would most plausibly end up — is captured and not just this module's
    # deliberate warning line.
    caplog.set_level(logging.DEBUG)

    def _ping(database: db.Database) -> Coroutine[Any, Any, Any]:
        return database.ping()

    verdict = with_database(_ping, bad_settings)

    # 0. The failure must be real. Without this the whole test is vacuous.
    assert verdict.ok is False, "a wrong password was accepted — the test proves nothing"

    # 0b. It must be the AUTHENTICATION failure specifically, not merely some
    #     failure. `ok is False` alone cannot tell "the server rejected this
    #     password" from "nothing was listening", and a transport error would
    #     reach the four redaction assertions below having proved nothing about
    #     credentials — which is exactly the vacuous pass this precondition and
    #     this assertion exist to end.
    #
    #     Asserted on the exception CLASS NAME, never on message text:
    #     `db._describe`'s own docstring records that driver messages vary
    #     between versions and are not a stable thing to parse, while the class
    #     name is. `asyncpg.InvalidPasswordError` is SQLSTATE 28P01 and is
    #     stable. `_describe` puts the class name FIRST in the string and
    #     `_brief` truncates at 120 characters, so the cap cannot hide it.
    assert "InvalidPasswordError" in verdict.detail, (
        f"the connection failed for a reason other than a rejected password, so the "
        f"redaction assertions below are being applied to a transport failure: "
        f"{verdict.detail!r}"
    )

    # 1. The verdict. This string is put straight into the /health/ready
    #    response body, so it is the one most likely to reach an unauthenticated
    #    caller.
    assert_no_secret(WRONG_PASSWORD, verdict.detail, "the ping verdict returned to the caller")

    # 2. Every log record. `record.getMessage()` formats the args, which is what
    #    the handler will actually write — checking `record.msg` alone would miss
    #    a secret passed as a logging argument, which is the common case and
    #    exactly the one `%s`-style logging invites.
    for record in caplog.records:
        assert_no_secret(WRONG_PASSWORD, record.getMessage(), f"the log record from {record.name}")
        assert_no_secret(WRONG_PASSWORD, repr(record.args), f"the log args from {record.name}")

    # 3. repr(). What an uncaught traceback's locals, a `pdb` session, a crash
    #    report and a careless `logger.info("%r", settings)` all show.
    assert_no_secret(WRONG_PASSWORD, repr(bad_settings), "repr() of the Settings object")

    # 4. Every serialisation. See the docstring: a model dump is not a repr, and
    #    a future change to how this object is logged would defeat only the
    #    repr assertion.
    assert_no_secret(WRONG_PASSWORD, repr(bad_settings.model_dump()), "Settings.model_dump()")
    assert_no_secret(WRONG_PASSWORD, bad_settings.model_dump_json(), "Settings.model_dump_json()")


def test_the_redactor_removes_a_dsn_that_a_driver_quotes():
    """Prove the redactor works on a message that DOES contain the credential.

    ── WHY THIS TEST EXISTS ALONGSIDE THE END-TO-END ONE ──────────────────────
    The test above configures a genuinely wrong password and asserts the secret
    appears nowhere. It is the important test. But it can only prove as much as
    this stack's drivers actually do — and measured on this host:

      * asyncpg's `InvalidPasswordError` message is "password authentication
        failed for user ..." and contains no password at all;
      * SQLAlchemy 2.0.54's unparseable-URL `ArgumentError` is "Could not parse
        SQLAlchemy URL from given URL string" and quotes no URL either.

    So the end-to-end test PASSES RIGHT NOW EVEN IF THE REDACTOR WERE DELETED
    AND REPLACED BY `str()`. It is guarding the outcome, not the mechanism. That
    is not a useless test — the outcome is what matters and it is what the
    standard library versions actually produce — but it is a test that would
    keep passing right up to the day a dependency upgrade starts embedding URLs
    in its diagnostics, which is precisely when it would stop being reassuring.

    This test closes that gap by constructing the failure the drivers do not
    currently produce: a message that genuinely contains the DSN. If the
    redactor is removed, this fails immediately. It is the mechanism's own test,
    independent of what any particular library version happens to do.

    Three cases, because there are three ways the secret can appear:

      1. the whole DSN, which is how SQLAlchemy has historically quoted URLs;
      2. the bare password on its own, which is how a driver error that reports
         only the credential would look;
      3. the PERCENT-ENCODED password — the case that is easy to miss and the
         one that actually bites, because `abc/def` does not appear verbatim in
         a message containing `abc%2Fdef`, so a naive substring check passes
         while the credential sits in the log encoded.
    """
    dsn = f"postgresql+asyncpg://lemondrop:{WRONG_PASSWORD}/x@127.0.0.1:5432/lemondrop"
    secrets = (dsn, WRONG_PASSWORD)

    # 1. The whole DSN quoted by the driver.
    quoted_dsn = db._redact(f"connection to {dsn} failed: InvalidPasswordError", secrets)
    assert_no_secret(WRONG_PASSWORD, quoted_dsn, "a message quoting the whole DSN")
    assert db.REDACTED in quoted_dsn, "the redaction marker must be visible, not silent truncation"

    # 2. The bare password, with no URL around it.
    quoted_password = db._redact(f"authentication failed using {WRONG_PASSWORD}", secrets)
    assert_no_secret(WRONG_PASSWORD, quoted_password, "a message quoting the bare password")

    # 3. The percent-encoded form. A password containing a slash is used
    #    deliberately: every character in WRONG_PASSWORD is URL-unreserved, so a
    #    password that could not possibly encode would make case 3 vacuous.
    encodable = "sl/ash+and=equals"
    encoded = quote(encodable, safe="")
    assert encoded != encodable, "this password must actually require encoding"
    dsn_with_encodable = f"postgresql+asyncpg://lemondrop:{encodable}@127.0.0.1:5432/lemondrop"
    leaked_encoded = db._redact(
        f"driver echoed: {encoded}",
        (dsn_with_encodable, encodable),
    )
    assert_no_secret(encodable, leaked_encoded, "a message quoting the percent-encoded password")
    assert_no_secret(encoded, leaked_encoded, "a message quoting the percent-encoded password")

    # An empty secret must not redact everything. "" appears in every string, so
    # a redactor that did not skip it would turn every message into the marker
    # and destroy all diagnostic value — a bug that would pass every
    # "is the secret absent" assertion above.
    assert db._redact("OperationalError: timeout", ("",)) == "OperationalError: timeout"


def test_repr_of_settings_does_not_contain_the_password():
    """`repr()` of the settings object must not contain the password.

    Separate from the test above on purpose, even though that one covers it too.
    That test is a large integration test with several moving parts and will be
    the one that gets skipped-by-accident, deleted during a refactor, or blamed
    on the database being down. This one needs nothing but the DSN — it does not
    connect to anything — so it keeps testing the redaction guarantee even on a
    machine where the devdb has never been started.

    It asserts both directions. The password is absent, which is the guarantee.
    And something is PRESENT in its place, because the failure mode of an
    over-eager redactor is to drop the field entirely: a `repr()` that quietly
    omits the DSN would pass an `not in` assertion while telling an operator
    nothing at all when they ask which database this process is talking to.
    """
    settings = configured_settings()
    password = db._password_of(settings.database_url.get_secret_value())

    assert password, "the configured DSN has no password component"
    rendered = repr(settings)

    assert_no_secret(password, rendered, "repr() of the Settings object")

    # Asserted in BOTH directions, because each catches a different failure.
    #
    # The mask is present: an over-eager redactor that dropped the field
    # entirely would pass a bare "not in" assertion while leaving an operator
    # with nothing when they ask what this process is configured to talk to.
    # The exact mask string is asserted rather than any non-empty value, because
    # "**********" is a deliberate, recognisable convention — an operator
    # scanning a log can tell at a glance that a value was withheld on purpose.
    assert "**********" in rendered, f"expected a masked secret in {rendered!r}"

    # The host is present too, and it is the one component safe to show. This is
    # what makes the repr diagnostic rather than merely safe.
    assert settings.database_host in rendered, (
        f"the repr should show which host is configured; got {rendered!r}"
    )


def test_missing_database_url_raises_an_error_naming_the_key(monkeypatch):
    """No `DATABASE_URL` must fail loudly, name the key, and leak nothing.

    The requirement is that the error NAMES `DATABASE_URL`, because "there is
    deliberately no default" is only useful if the reader is told which variable
    to set. An error that merely says "database URL missing" makes the reader
    guess between the application URL and the Alembic one — and guessing wrong
    here means pointing production at a migration credential, which is the exact
    mistake the two-variable split exists to prevent.

    Asserted alongside: that the message does not contain any credential (a
    misconfiguration error is still an error path, and this one runs on a
    machine that may well have a working URL in a sibling variable), and that
    the message does not mention the Alembic variable as the thing to set.

    `monkeypatch.delenv` with `raising=False`, because the point is to test the
    case where the key is absent, and it may or may not be present in the shell
    that invoked pytest.
    """
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        get_settings()

    message = str(excinfo.value)

    assert DATABASE_URL_ENV_VAR in message, f"the error must name the missing key, got: {message}"
    assert "CHANGE_ME" not in message, "the error must not contain a credential or a placeholder value"

    # The Alembic key must NOT be offered as the answer. It is a different
    # credential with different privileges, and pointing somebody at it is the
    # mistake this separation exists to prevent.
    assert "ALEMBIC_DATABASE_URL=postgresql" not in message


# ── A DSN that is set, non-blank, and useless ─────────────────────────────────
#
# The four tests below share a subject: `Settings` must reject a DSN that
# `resolve_database_url_from_environment` is happy to hand back.
#
# None of them touch a database, a socket or the running API. They construct
# `Settings` directly and expect it to fail, so they need no devdb container and
# pass on any machine — which is deliberate. The defect they protect is one that
# fires on a host where the local development database is *not* what is being
# configured, so a suite that only exercised these cases with devdb up would
# leave the EC2-shaped failure untested exactly where it happens.


def settings_from(dsn: str) -> Settings:
    """Build a `Settings` from an arbitrary DSN string.

    Constructs `Settings` directly rather than going through `get_settings()`,
    because the thing under test is the DSN VALIDATION on the model — not the
    environment reader, which has its own test above. Using `get_settings()`
    would also make these tests depend on whatever `DATABASE_URL` the shell
    happened to export, which is the opposite of the isolation being asked for.
    """
    return Settings(database_url=SecretStr(dsn), embedding_dim=SCHEMA_EMBEDDING_DIM)


def test_a_dsn_with_an_empty_password_is_rejected_and_leaks_nothing():
    """`postgresql+asyncpg://user@127.0.0.1:5432/db` must fail at construction.

    ── WHAT BREAKS WITHOUT THIS TEST ──────────────────────────────────────────
    `docker-compose.yml` PASSES THROUGH the container's DSN rather than
    composing it: the `api` service declares `DATABASE_URL: "${DEV_DATABASE_URL:-}"`,
    so whatever the host's `.env` puts in `DEV_DATABASE_URL` is what the container
    receives. `.env.example` ships that key EMPTY, so a production host whose
    `.env` came from the template hands `api` an empty `DATABASE_URL` and the
    resolver in `api/app/config.py` falls through to the SSM + Secrets Manager
    path.

    This test guards the branch of that contract on the near side of the
    fall-through. A DSN that arrives with nothing where the password belongs is
    exactly what the empty-value discipline is NOT meant to produce: an empty
    `DATABASE_URL` is treated as unset (`raw is None or not raw.strip()`) and
    never reaches `Settings` at all, whereas a malformed-but-non-blank DSN does.
    If such a value were ever constructed again — by an interpolation that
    substitutes empty strings rather than one that substitutes nothing — it is
    NOT blank, so `resolve_database_url_from_environment` returns it,
    `get_settings()` succeeds, `db.startup` builds a pool, and the failure
    arrives at the first real connection as an opaque driver error about a server
    refusing credentials. The operator ends up reading asyncpg internals to
    discover that a variable was never filled in.

    This test is the regression guard for that: it is the assertion that a DSN
    with nothing where the password belongs cannot reach a live connection.

    The two secondary assertions are the reason this test is not just
    `pytest.raises`:

      * the error must NAME `DATABASE_URL`. "no password" alone leaves the
        reader to choose between the application URL and the Alembic one, and
        choosing the Alembic one hands the runtime process the migration
        credential — the exact mistake the two-variable split prevents.
      * the error must carry NO credential material. This is a configuration
        error, and configuration errors are the ones that get pasted into a bug
        report and a log aggregator. The DSN itself, and every part of it, are
        asserted absent — including the non-secret parts, because a message that
        quotes the host today is one edit away from quoting the password.
    """
    dsn = "postgresql+asyncpg://user@127.0.0.1:5432/db"

    with pytest.raises(ValueError) as excinfo:
        settings_from(dsn)

    message = str(excinfo.value)

    assert DATABASE_URL_ENV_VAR in message, f"the error must name the variable, got: {message}"
    assert "no password" in message, f"the error must name what is missing, got: {message}"

    # Nothing from the DSN reaches the message. The whole string is checked
    # because it is the shape any echo would take, and the host additionally,
    # because it is the component a careless author would be most tempted to
    # include ("which database?") — and a message that quotes the host today is
    # one edit away from quoting the password. See the docstring.
    assert_no_secret(dsn, message, "the error raised for an empty-password DSN")
    assert_no_secret("127.0.0.1", message, "the host component of the rejected DSN")


def test_a_dsn_with_an_empty_username_is_rejected():
    """`postgresql+asyncpg://:password@host/db` must fail at construction too.

    The same interpolation failure as the previous test, one component over. It
    is a separate test because the two are checked by two separate comparisons,
    and a fix that handles the password and forgets the username is a very
    plausible half-fix — `if not url.password:` reads complete on its own and is
    the obvious thing to write first.

    The username is checked FIRST when both are missing, so a DSN with neither
    reports the username. That ordering is asserted here too, because the
    combined message is what an operator on the affected host actually sees and
    it should say both rather than making them fix one variable, restart, and
    meet the identical failure again.
    """
    with pytest.raises(ValueError) as excinfo:
        settings_from(f"postgresql+asyncpg://:{DISTINCTIVE_MARKER}@127.0.0.1:5432/db")

    message = str(excinfo.value)

    assert DATABASE_URL_ENV_VAR in message, f"the error must name the variable, got: {message}"
    assert "no username" in message, f"the error must name what is missing, got: {message}"

    # This DSN DOES carry a password, so this is the case where a leak would
    # actually be a leak — the marker is distinct from any real credential and
    # from every English word in the message, so its absence proves something.
    # (A marker as short as "password" would not: it appears nowhere by accident
    # and its absence would prove nothing.)
    assert_no_secret(DISTINCTIVE_MARKER, message, "the password of a DSN rejected for its username")

    # Both-empty: the exact EC2 string. Asserted separately from the two
    # single-component cases above because it is the shape that actually ships,
    # and a message that named only the first missing component would still be a
    # misconfiguration failure with an unhelpful fix.
    with pytest.raises(ValueError) as combined:
        settings_from("postgresql+asyncpg://:@postgres:5432/")

    combined_message = str(combined.value)
    assert "no username" in combined_message and "no password" in combined_message, (
        f"a DSN missing both must name both, got: {combined_message}"
    )


def test_a_malformed_dsn_is_rejected_without_leaking_the_parser_s_error():
    """A DSN SQLAlchemy cannot parse must be rejected cleanly, and quietly.

    ── WHAT BREAKS WITHOUT THIS TEST ──────────────────────────────────────────
    `db.startup`'s docstring already records that `create_async_engine` PARSES
    the DSN and raises on a malformed one, and it wraps that in a try/except
    precisely so a one-character typo cannot refuse to boot the container. That
    defence sits in `db.py`. This check sits EARLIER, at configuration time, and
    it is the one that decides what the message says.

    Two things are protected, and the second is the one that is easy to get
    wrong:

      1. It is not a bare `ArgumentError`. `make_url` does not raise
         `ArgumentError` for every malformed DSN — a DSN with a non-numeric port
         raises a plain `ValueError: invalid literal for int() with base 10:
         'notaport'` from inside the parser. Catching only `ArgumentError`
         would let that raw parser error become this validation's own message,
         and pydantic would faithfully wrap it. Asserted twice: the exception is
         not an `ArgumentError`, and the message is not the parser's.
      2. NO part of the DSN appears. `WRONG_PASSWORD` is embedded in this DSN
         deliberately, and the assertion is that it does not appear in the error.
         A test whose DSN had no secret in it could not detect an echo at all.

    Nothing here needs a database, so this test runs on any host.
    """
    # A non-numeric port: measured on SQLAlchemy 2.0.54 this raises
    # ValueError("invalid literal for int() with base 10: 'notaport'") rather
    # than ArgumentError, and that message quotes the offending port.
    dsn = f"postgresql+asyncpg://lemondrop:{WRONG_PASSWORD}@127.0.0.1:notaport/lemondrop"

    with pytest.raises(ValueError) as excinfo:
        settings_from(dsn)

    # A bare ArgumentError escaping here would mean this validation passed the
    # DSN through and let SQLAlchemy's own exception be the answer — the failure
    # mode this test exists to rule out.
    assert not isinstance(excinfo.value, ArgumentError), (
        f"SQLAlchemy's own error escaped the validation: {excinfo.value}"
    )

    message = str(excinfo.value)

    assert DATABASE_URL_ENV_VAR in message, f"the error must name the variable, got: {message}"

    # The parser's message must be REPLACED, not wrapped or appended to. Both
    # halves of the leak this guards against: the password, and the DSN fragment
    # (`notaport`) that a raw parser error would quote.
    assert "invalid literal for int()" not in message, (
        f"the parser's own error leaked into the message: {message}"
    )
    assert_no_secret(WRONG_PASSWORD, message, "the error raised for a malformed DSN")
    assert_no_secret(dsn, message, "the error raised for a malformed DSN")
    assert_no_secret("notaport", message, "the DSN fragment quoted by the parser")


def test_a_fully_populated_dsn_still_constructs():
    """The working local DSN must be ACCEPTED — the regression guard.

    Every other test in this section asserts that a DSN is refused. A test suite
    can therefore be made entirely green by a validator that refuses everything,
    which is a real and destructive failure mode: it would look like four passing
    tests while breaking local development and production simultaneously, and it
    would only be discovered by trying to run the service.

    So the positive case is asserted as a test, not assumed. This is the DSN
    shape from `.env`: user, password, host, port and database, all present. It
    must construct, and the resulting object must still be useful — the two
    assertions below are what "constructs" has to mean in practice, because a
    `Settings` that validates but has lost its value protects nothing.
    """
    dsn = "postgresql+asyncpg://lemondrop:correct-horse-battery-staple@127.0.0.1:5432/lemondrop"

    settings = settings_from(dsn)

    assert settings.database_url.get_secret_value() == dsn, (
        "a valid DSN must survive validation unchanged"
    )
    # The redaction guarantee is unaffected by the new check: the DSN is still a
    # SecretStr, still masked in a repr, and still exposes only the host as a
    # loggable component. A validator that unwrapped the SecretStr to inspect it
    # would break all three, and nothing else in this file would notice.
    assert "correct-horse-battery-staple" not in repr(settings), (
        f"the password must not appear in repr(settings): {repr(settings)!r}"
    )
    assert settings.database_host == "127.0.0.1"


# ── The embedding width ───────────────────────────────────────────────────────


def test_embedding_dim_is_384_and_matches_the_column_definition():
    """The configured embedding width must equal the width the column actually has.

    `EMBEDDING_DIM` (what the application believes) is compared against
    `documents.embedding`'s real `atttypmod` (what the migrated schema is). Not
    against a constant — against the database. A constant would only prove the
    code agrees with itself, which is precisely the failure this needs to catch.

    Why it matters, concretely. Swapping `bge-small-en-v1.5` for a wider model
    changes the embedding width, and nothing on that path fails loudly on its
    own: `/embed` returns a longer vector, the API's `dimensions` field reports
    the new number faithfully, and the mismatch surfaces later — either as an
    INSERT error against `vector(384)`, or, against a column declared without a
    typmod constraint, as an INSERT that SUCCEEDS while quietly destroying the
    distance metric the vector index depends on. The second one is the expensive
    case: retrieval quality degrades over weeks, every query still returns 200,
    and nothing points at the cause.

    So the check belongs at the boundary, comparing configuration to reality, and
    it must FAIL rather than skip. A test that passes when it cannot reach the
    database is worse than no test, because it converts an unknown into a
    recorded success.
    """

    def _check(database: db.Database) -> Coroutine[Any, Any, Any]:
        async def _run() -> tuple[int, int]:
            async with database.engine.connect() as connection:  # type: ignore[union-attr]
                # atttypmod on a `vector(n)` column IS the n. This is how
                # pgvector stores its dimension, and it is read from
                # pg_attribute rather than information_schema because
                # information_schema reports the type as USER-DEFINED and does
                # not surface the typmod.
                result = await connection.execute(
                    text(
                        "SELECT a.atttypmod FROM pg_attribute a "
                        "WHERE a.attrelid = 'documents'::regclass "
                        "AND a.attname = 'embedding' "
                        "AND NOT a.attisdropped"
                    )
                )
                row = result.fetchone()
                result.close()
                if row is None:
                    pytest.fail(
                        "the documents table has no `embedding` column.\n"
                        "The schema has not been migrated. Apply it with:\n"
                        "    set -a && . ./.env && set +a\n"
                        "    cd api && alembic upgrade head"
                    )
                configured = int(os.environ.get(EMBEDDING_DIM_ENV_VAR, SCHEMA_EMBEDDING_DIM))
                return int(row[0]), configured

        return _run()

    column_dim, settings_dim = with_database(_check, configured_settings())

    assert settings_dim == SCHEMA_EMBEDDING_DIM == 384, (
        f"EMBEDDING_DIM is {settings_dim}, which is not {SCHEMA_EMBEDDING_DIM}"
    )
    assert column_dim == settings_dim, (
        f"EMBEDDING_DIM is {settings_dim} but documents.embedding is vector({column_dim}). "
        "A model swap that changes the embedding width must change the column via a "
        "migration, not be discovered at INSERT time."
    )


# ── Liveness and readiness ────────────────────────────────────────────────────


def test_health_live_returns_200():
    """`/health/live` must answer 200 even if every dependency is broken.

    That property is the endpoint's entire reason for existing, and it is the
    thing most likely to be "fixed" by a future contributor who sees a health
    endpoint that checks nothing and adds a dependency to it. Such a change
    passes this test on a healthy stack and then turns the first transient
    database blip into a container restart loop — turning a five-second outage
    into a total one. So the assertion is made here, on the live service, where
    the stack is genuinely up and genuinely healthy, and it is paired with the
    reasoning in `main.health_live`'s docstring.

    Only the status code is asserted. The body has exactly one field; a
    regression that added dependency fields to it would be caught by
    `test_health` below, which asserts `/health`'s shape is unchanged.
    """
    response = requests.get(f"{BASE_URL}/health/live", timeout=10)

    assert response.status_code == 200, (
        f"/health/live returned {response.status_code}. If the compose stack is "
        f"not running the updated image, rebuild it with:\n"
        f"    docker compose up -d --build api"
    )
    assert response.json()["status"] == "ok"


def test_health_ready_returns_200_when_the_database_and_both_workers_are_up():
    """`/health/ready` must answer 200 only when ALL THREE dependencies are ok.

    All three, not "some": a search that cannot reach the database serves
    nothing, so a partially-healthy instance is not a usable one, and a
    readiness endpoint that reported 200 with the database down would route
    traffic to an instance guaranteed to fail every request it accepted.

    This test requires the compose stack running the UPDATED image. With the old
    image the route does not exist and this fails with a 404 — correctly, rather
    than skipping, because a skip here would report the readiness contract as
    verified on a build that has never implemented it.
    """
    response = requests.get(f"{BASE_URL}/health/ready", timeout=15)

    if response.status_code == 404:
        pytest.fail(
            "/health/ready does not exist — the running API image predates this "
            "phase. Rebuild and restart it:\n"
            "    docker compose up -d --build api"
        )

    assert response.status_code == 200, (
        f"/health/ready returned {response.status_code}: {response.text}\n"
        "All three of database, embedder and reranker must be reachable.\n"
        f"If the database is not running:\n    {START_DEVDB}"
    )

    body = response.json()
    assert body["status"] == "ok"
    assert body["embedder"] == "ok"
    assert body["reranker"] == "ok"
    # Asserted explicitly rather than implied by the status code, for the same
    # reason test_integration.py asserts both `dimensions` and `len(embedding)`:
    # the claim and the data are separate things, and only checking the claim
    # lets a bug through where the API reports "ok" while sending something else.
    assert body["database"] == "ok"


def test_health_is_unchanged_by_the_database_phase():
    """`/health` must still report the workers and nothing else.

    `/health` is a LIVE production contract: the compose api healthcheck reads
    it, `scripts/boot.sh`'s 300-second boot loop polls it, and the Milestone 2
    ALB target group health-checks against it. Adding a `database` field to it,
    or making it 503 because the database is down, would break all three at
    once — and the ALB would take a working instance out of rotation over a
    dependency the old image never had.

    So this test exists to make the decision explicit and enforceable: `/health`
    gained nothing from the database phase, and `/health/ready` is the additive
    route that carries the database verdict instead.
    """
    response = requests.get(f"{BASE_URL}/health", timeout=10)

    assert response.status_code == 200

    body = response.json()
    # Exact key set, not a subset. Asserting the two expected fields are present
    # would pass alongside a third one that a future edit had added.
    assert set(body) == {"status", "embedder", "reranker"}, (
        f"/health's response shape changed to {sorted(body)}; it is a live "
        "contract for the compose healthcheck, scripts/boot.sh and the ALB"
    )
    assert body["status"] == "ok"