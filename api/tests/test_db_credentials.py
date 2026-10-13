"""Tests for the credential RESOLVER — which source, and what it builds.

**Why this is a new file and not part of `test_db.py`.** That file's own module
docstring states its contract: "half of it talks to the REAL local devdb over a
REAL socket with no mocking whatsoever, and half of it talks to the REAL running
API over real HTTP. Nothing here substitutes a fake engine or an in-process test
client." Every test in it assumes the compose stack is up.

These tests do not. The AWS credential path has no local dependency to stand up —
there is no local Secrets Manager, and standing up a fake AWS would be testing the
fake — so it is exercised as a pure unit with the boto3 CLIENT calls replaced and
everything above them real. Adding them to `test_db.py` would mean either
breaking that file's stated contract or making a `no mocking whatsoever` claim
that is no longer true. Separate file, separate contract, separate preconditions:
this one runs on any machine, including one where the devdb has never started.

**What is real and what is stubbed, and why that line is where it is.**

* REAL: source selection, the `DB_DSN_SOURCE` policy, region resolution, SSM
  parameter naming, the JSON parse, the missing-field and non-JSON handling, the
  `URL.create` assembly, the caching, and every error message. All of it runs on
  every test below, and none of it is mocked.
* STUBBED: `_boto3_client` — the single function that constructs a boto3 client,
  which is the boundary where this module stops and AWS begins. Substituting the
  whole resolver instead would be a test that asserts the resolver equals the
  resolver.

The AWS exceptions raised by the stubs are REAL `botocore.exceptions.ClientError`
objects, built the way botocore builds them, because the production code branches
on `response["Error"]["Code"]` and a fake exception with a `.code` attribute would
not exercise the branch that actually runs.

**The security test at the bottom is the reason the rest of this file exists.** A
credential resolver is the one function in this service whose input IS the secret,
and every test above deliberately puts a distinctive, unmistakably fake password
into it so that "the password appears in no message, no log and no repr" is a
claim that can actually fail.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.engine import make_url

from app import config, db
from app.config import (
    AWS_RESOLVE_BUDGET_SECONDS,
    AWS_SECRETS_GET_SECRET_VALUE_ACTION,
    AWS_SSM_GET_PARAMETER_ACTION,
    DB_DSN_SOURCE_AWS,
    DB_DSN_SOURCE_ENVIRONMENT,
    DB_DSN_SOURCE_ENV_VAR,
    DB_SSM_HOST_LEAF,
    DB_SSM_PARAMETER_PREFIX_ENV_VAR,
    DB_SSM_PORT_LEAF,
    DB_SSM_SECRET_ARN_LEAF,
    DATABASE_URL_ENV_VAR,
    POSTGRES_ASYNCPG_DRIVER,
    SCHEMA_EMBEDDING_DIM,
    Settings,
    get_settings,
)

# The three SSM paths, spelled out as literals rather than built from the module's
# own constants. If the constants changed and the test built its expectation from
# them too, the test would follow the bug and prove nothing — this asserts the
# strings that are DEPLOYED, as recorded in infra/iam.tf.
DEPLOYED_PREFIX = "/lemondrop/dev/db"
HOST_PARAMETER = f"{DEPLOYED_PREFIX}/{DB_SSM_HOST_LEAF}"
PORT_PARAMETER = f"{DEPLOYED_PREFIX}/{DB_SSM_PORT_LEAF}"
SECRET_ARN_PARAMETER = f"{DEPLOYED_PREFIX}/{DB_SSM_SECRET_ARN_LEAF}"

RDS_HOST = "lemondrop-db.abc123xyz.eu-west-1.rds.amazonaws.com"
RDS_PORT = 5432
RDS_SECRET_ARN = (
    "arn:aws:secretsmanager:eu-west-1:123456789012:secret:lemondrop-dev-db-AbCdEf"
)
RDS_MASTER_USERNAME = "lemondrop_admin"

# ── Distinctive markers, for the same reason test_db.py has two ───────────────
#
# Long, improbable, and absent from every English word in every message these
# functions can produce. A marker as short or as ordinary as "password" or "db"
# would make the leak assertions vacuous: such a string is absent from almost any
# message BY ACCIDENT, so the absence would prove nothing.
#
# The second one exists for a sharper reason. It is a password containing every
# character that matters to URL parsing — `@ : / ? % #` — because a benign
# password cannot detect the failure this module's biggest correctness requirement
# is about. See `test_a_hostile_password_round_trips_through_the_assembled_dsn`.
HOSTILE_PASSWORD = "p@ss:w/o?rd%of#the[net]5e1"
ORDINARY_PASSWORD = "RDS-managed-4f2a9c-marker-only-not-a-real-password"

# Every environment variable this module reads. Listed once so the autouse
# fixture below can neutralise all of them without a test having to know the
# full set, and so a variable added later cannot start leaking in from the
# developer's shell.
READ_ENV_VARS = (
    DATABASE_URL_ENV_VAR,
    DB_DSN_SOURCE_ENV_VAR,
    DB_SSM_PARAMETER_PREFIX_ENV_VAR,
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "DB_NAME",
)


# ── The AWS doubles ───────────────────────────────────────────────────────────


class FakeSSM:
    """An SSM client that answers by parameter NAME.

    Realistic in the two ways that matter. It dispatches on `Name` rather than
    returning one canned value for every call, so a test can deny ONE of the
    three parameters and prove the resulting message names that one — a stub that
    ignored the name could not tell the operator which policy statement to look
    at, and neither can this test. And it asserts `WithDecryption` is passed
    explicitly as False, because that is a stated property of the call.
    """

    def __init__(
        self,
        values: dict[str, str],
        *,
        denied: tuple[str, ...] = (),
        absent: tuple[str, ...] = (),
        malformed: tuple[str, ...] = (),
    ) -> None:
        self.values = values
        self.denied = denied
        self.absent = absent
        self.malformed = malformed
        self.calls: list[str] = []

    def get_parameter(self, *, Name: str, WithDecryption: bool) -> dict[str, Any]:
        self.calls.append(Name)
        assert WithDecryption is False, (
            "these three parameters are type String and must be read with "
            "WithDecryption=False stated explicitly, not left to the default"
        )
        if Name in self.denied:
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException",
                           "Message": "User is not authorized to perform this operation"}},
                "GetParameter",
            )
        if Name in self.absent:
            raise ClientError(
                {"Error": {"Code": "ParameterNotFound",
                           "Message": f"Parameter {Name} not found."}},
                "GetParameter",
            )
        if Name in self.malformed:
            return {"Parameter": {"Name": Name, "Type": "String"}}
        if Name not in self.values:
            raise AssertionError(f"the resolver asked for an unconfigured parameter: {Name}")
        return {"Parameter": {"Name": Name, "Type": "String", "Value": self.values[Name]}}


class FakeSecretsManager:
    """A Secrets Manager client that answers with one canned `SecretString`."""

    def __init__(
        self,
        secret_string: str | None,
        *,
        denied: bool = False,
        binary_only: bool = False,
    ) -> None:
        self.secret_string = secret_string
        self.denied = denied
        self.binary_only = binary_only
        self.calls: list[str] = []

    def get_secret_value(self, *, SecretId: str) -> dict[str, Any]:
        self.calls.append(SecretId)
        if self.denied:
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException",
                           "Message": "User is not authorized to perform this operation"}},
                "GetSecretValue",
            )
        if self.binary_only:
            return {"SecretBinary": b"\x00\x01"}
        return {"SecretString": self.secret_string}


class AwsStub:
    """Replaces `config._boto3_client` — the boundary — and records what crossed it.

    `calls` is the assertion surface for "the AWS path was never touched" and for
    "this was fetched exactly once". Without it, test 1 could only assert the
    happy path, and the caching test could not distinguish a cached resolution
    from two real ones.
    """

    def __init__(self, ssm: FakeSSM, secrets: FakeSecretsManager) -> None:
        self.ssm = ssm
        self.secrets = secrets
        self.calls: list[dict[str, Any]] = []

    def __call__(self, service_name: str, *, region_name: str, config: Any) -> Any:
        self.calls.append({"service": service_name, "region": region_name, "config": config})
        return self.ssm if service_name == "ssm" else self.secrets


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise every variable this module reads, and empty the process cache.

    Two separate jobs, both required for these tests to mean anything.

    The environment: without this, a developer who has `DATABASE_URL` exported in
    their shell — which is every developer on this project, per `.env` — would
    make every AWS test in this file pass by taking branch 1 of `resolve_database_url`
    and never reach the code under test at all. A test suite that cannot fail
    because of the machine it runs on is not a test suite.

    The cache: `_resolve_database_url_from_aws_once` is `lru_cache(maxsize=1)` and
    that caching is a REQUIREMENT, so without a `cache_clear` the second test in
    the file would get the first test's resolved DSN out of the cache and every
    assertion about its own stub would be meaningless.
    """
    for name in READ_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    config._resolve_database_url_from_aws_once.cache_clear()
    yield
    config._resolve_database_url_from_aws_once.cache_clear()


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Install a working AWS double and return a factory for it.

    Returned as a FACTORY rather than a single object because almost every test
    needs different SSM values or a different malformed secret, and a fixture that
    had to be parameterised per-test to do that would put the interesting content
    in the test signature instead of in the test body.
    """
    def _install(
        *,
        password: str = ORDINARY_PASSWORD,
        username: str = RDS_MASTER_USERNAME,
        host: str = RDS_HOST,
        port: str | int = RDS_PORT,
        denied_parameters: tuple[str, ...] = (),
        absent_parameters: tuple[str, ...] = (),
        malformed_parameters: tuple[str, ...] = (),
        secret_string: str | None = None,
        secret_denied: bool = False,
        secret_binary_only: bool = False,
    ) -> AwsStub:
        ssm = FakeSSM(
            {
                HOST_PARAMETER: host,
                PORT_PARAMETER: str(port),
                SECRET_ARN_PARAMETER: RDS_SECRET_ARN,
            },
            denied=denied_parameters,
            absent=absent_parameters,
            malformed=malformed_parameters,
        )
        secrets = FakeSecretsManager(
            secret_string or json.dumps({"username": username, "password": password}),
            denied=secret_denied,
            binary_only=secret_binary_only,
        )
        stub = AwsStub(ssm, secrets)
        monkeypatch.setattr(config, "_boto3_client", stub)
        monkeypatch.setenv(DB_DSN_SOURCE_ENV_VAR, DB_DSN_SOURCE_AWS)
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        config._resolve_database_url_from_aws_once.cache_clear()
        return stub

    return _install


# ── 1. DATABASE_URL wins, and the AWS path is never entered ───────────────────


def test_database_url_is_used_verbatim_and_no_aws_client_is_constructed(monkeypatch):
    """A set `DATABASE_URL` short-circuits everything, even with the flag set.

    This is the local-development guarantee, and it is deliberately stronger
    than "DATABASE_URL takes precedence". It is asserted with
    `DB_DSN_SOURCE=aws` EXPLICITLY SET, because that is the case that would
    otherwise be debatable: a shell where someone exported the flag during an
    experiment and forgot about it must still never reach AWS from a laptop.

    The stub raises if it is called at all rather than merely recording the call.
    "The AWS path was not taken" should be a failure of the test, not a fact
    asserted after the fact.
    """
    dsn = "postgresql+asyncpg://lemondrop:correct-horse@127.0.0.1:5432/lemondrop"

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a boto3 client was constructed on the DATABASE_URL path")

    monkeypatch.setattr(config, "_boto3_client", _explode)
    monkeypatch.setenv(DATABASE_URL_ENV_VAR, dsn)
    monkeypatch.setenv(DB_DSN_SOURCE_ENV_VAR, DB_DSN_SOURCE_AWS)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    settings = get_settings()

    # Verbatim. `resolve_database_url` strips surrounding whitespace and nothing
    # else, so a DSN with no padding survives character for character.
    assert settings.database_url.get_secret_value() == dsn
    assert settings.database_host == "127.0.0.1"


def test_a_developer_on_a_laptop_cannot_reach_aws_by_accident(aws):
    """Nothing in this repository's local configuration turns the AWS path on.

    The resolver's guarantees above are only worth something if the *deployment*
    files agree with them. `docker-compose.yml` and `.env.example` are what a
    developer actually uses, and if either of them ever grows a
    `DB_DSN_SOURCE=aws`, every one of these guarantees becomes a guard around a
    door that is standing open — on a machine with no instance role, so every
    resolution would fail with an opaque credential error, or worse, succeed
    against the real production database.

    So this reads the two files rather than trusting the module. It is the only
    test in either file that inspects deployment configuration, and it earns its
    place by being the only one that can catch this specific mistake.
    """
    repo_root = Path(__file__).resolve().parents[2]
    for relative in ("docker-compose.yml", ".env.example"):
        text = (repo_root / relative).read_text(encoding="utf-8")
        assert f"{DB_DSN_SOURCE_ENV_VAR}={DB_DSN_SOURCE_AWS}" not in text, (
            f"{relative} sets {DB_DSN_SOURCE_ENV_VAR}={DB_DSN_SOURCE_AWS}; the local "
            "stack must never select the AWS credential path"
        )


# ── 2. Neither source set ────────────────────────────────────────────────────


def test_neither_source_set_names_the_missing_key(monkeypatch):
    """No `DATABASE_URL` and no flag must produce the EXISTING error, unchanged.

    Asserted on the variable name because "there is deliberately no default" is
    only actionable if the reader is told which variable to set, and this is the
    message that has told them since the database phase — the AWS path must not
    have replaced it with something vaguer, and it must not have replaced it with
    an error about SSM, which would send an operator looking at a role when their
    problem is a missing `.env`.
    """
    with pytest.raises(RuntimeError) as excinfo:
        get_settings()

    message = str(excinfo.value)

    assert DATABASE_URL_ENV_VAR in message, f"the error must name the missing key, got: {message}"
    assert DB_SSM_HOST_LEAF not in message, (
        "an unconfigured local process must not be told about SSM; it was never "
        f"asked for the AWS source: {message}"
    )


def test_an_unrecognised_source_is_an_error_not_a_fallback(monkeypatch):
    """`DB_DSN_SOURCE=awsy` must fail loudly rather than quietly doing something.

    Falling back on an unrecognised value would make a typo indistinguishable from
    "not configured", and those two have nothing in common when the operator is
    reading the message three steps later.
    """
    monkeypatch.setenv(DB_DSN_SOURCE_ENV_VAR, "awsy")

    with pytest.raises(RuntimeError) as excinfo:
        get_settings()

    message = str(excinfo.value)

    assert DB_DSN_SOURCE_ENV_VAR in message
    assert DB_DSN_SOURCE_AWS in message and DB_DSN_SOURCE_ENVIRONMENT in message


def test_the_default_source_is_the_environment_not_a_fallback_guess(monkeypatch):
    """An explicit `DB_DSN_SOURCE=environment` and an UNSET one behave identically.

    Worth a test on its own because it is what stops the default from being a
    second, divergent behaviour: if `resolve_database_url` ever handled "unset"
    separately from "environment", this test would catch the two drifting.
    """
    monkeypatch.setenv(DATABASE_URL_ENV_VAR, "postgresql+asyncpg://u:p@127.0.0.1:5432/d")

    implicit = get_settings().database_url.get_secret_value()

    monkeypatch.setenv(DB_DSN_SOURCE_ENV_VAR, DB_DSN_SOURCE_ENVIRONMENT)
    explicit = get_settings().database_url.get_secret_value()

    assert implicit == explicit


# ── 3. The AWS path builds the right DSN ──────────────────────────────────────


def test_the_aws_source_builds_the_dsn_from_ssm_and_the_secret(aws):
    """Three SSM values plus a JSON secret produce one correct DSN.

    Every component is asserted separately through `make_url` rather than by
    string-matching the DSN, because a DSN that happens to contain the right
    characters in the wrong order is not the same claim as a DSN that parses back
    to the values that went in.
    """
    stub = aws()

    started = time.perf_counter()
    dsn = config.resolve_database_url()
    elapsed = time.perf_counter() - started

    url = make_url(dsn)
    assert url.drivername == POSTGRES_ASYNCPG_DRIVER
    assert url.username == RDS_MASTER_USERNAME
    assert url.password == ORDINARY_PASSWORD
    assert url.host == RDS_HOST
    assert url.port == RDS_PORT
    assert url.database == "lemondrop"

    # The exact deployed paths, fetched, in order. This is the assertion that
    # ties the code to infra/iam.tf: if a prefix default drifted, these fail.
    assert stub.ssm.calls == [HOST_PARAMETER, PORT_PARAMETER, SECRET_ARN_PARAMETER]
    assert stub.secrets.calls == [RDS_SECRET_ARN]

    # One client per service, in the region asked for. Region propagation is
    # asserted because a default of "the region boto3 happens to know" is the
    # thing `AWS_REGION` exists to prevent.
    assert [call["service"] for call in stub.calls] == ["ssm", "ssm", "ssm", "secretsmanager"]
    assert {call["region"] for call in stub.calls} == {"eu-west-1"}

    # Every call carries explicit, bounded timeouts. Asserted rather than assumed
    # because the default botocore timeout is 60s, and 60 seconds of startup per
    # hung call is exactly the failure the constants exist to prevent.
    for call in stub.calls:
        assert call["config"].connect_timeout <= config.AWS_CONNECT_TIMEOUT_SECONDS
        assert call["config"].read_timeout <= config.AWS_READ_TIMEOUT_SECONDS
        assert call["config"].retries["max_attempts"] == config.AWS_MAX_ATTEMPTS

    # And the whole resolution finished inside the budget it declares. A stub
    # answers in microseconds, so this is NOT a measurement of AWS's latency and
    # proves nothing about it — it is a guard against a future change that puts
    # blocking work inside the resolution (a sleep, an unbounded retry, a second
    # round of fetches), which would break the budget without breaking a single
    # other assertion in this file.
    assert elapsed < AWS_RESOLVE_BUDGET_SECONDS, (
        f"the resolution took {elapsed:.3f}s against a "
        f"{AWS_RESOLVE_BUDGET_SECONDS:g}s budget"
    )


def test_the_whole_resolution_produces_a_settings_object_the_database_layer_accepts(aws):
    """End to end, through `get_settings`, the AWS path yields a usable `Settings`.

    The unit above proves the DSN is right. This proves the rest of the chain
    accepts it: the `Settings` validators run, and they reject a DSN with an
    empty username or password. The RDS-managed secret supplies the master
    username, so `db.py` can use what comes back with no further wiring — this is
    the test that says so.
    """
    aws()

    settings = get_settings()

    assert isinstance(settings, Settings)
    assert settings.embedding_dim == SCHEMA_EMBEDDING_DIM
    assert settings.database_host == RDS_HOST
    assert "***" in repr(settings) or "**********" in repr(settings), (
        "the DSN from AWS must be redacted in a repr exactly like any other"
    )


def test_the_secret_is_fetched_exactly_once_for_the_life_of_the_process(aws):
    """Two calls into the resolver, one round of AWS calls.

    The caching is a REQUIREMENT with two documented reasons — it is a per-call
    billing line item, and it is tens of milliseconds on every request otherwise —
    so it is asserted directly rather than inferred from the code.

    Counting `stub.ssm.calls` across two `get_settings()` calls is the assertion
    that would fail if someone "helpfully" made the resolver refresh the secret
    periodically: the second `get_settings()` would hit AWS again.
    """
    stub = aws()

    first = get_settings().database_url.get_secret_value()
    second = get_settings().database_url.get_secret_value()

    assert first == second
    assert stub.secrets.calls == [RDS_SECRET_ARN], (
        "the secret must be read once for the life of the process, not once per "
        "resolution"
    )
    assert stub.ssm.calls == [HOST_PARAMETER, PORT_PARAMETER, SECRET_ARN_PARAMETER]


# ── 4. A hostile password survives URL construction ───────────────────────────


def test_a_hostile_password_round_trips_through_the_assembled_dsn(aws):
    """A password full of URL metacharacters must come back out UNCHANGED.

    ── WHY THIS TEST IS THE ONE THAT MATTERS MOST ──────────────────────────────
    RDS generates the master password from a password policy that does not
    restrict punctuation, so `@ : / ? % # [ ]` are all genuinely possible. With
    naive string concatenation the result is not a slightly ugly DSN — it is a
    DSN that connects to the WRONG THING:

    * a password containing `@` makes SQLAlchemy read everything after the LAST
      `@` as the host, so the DSN points at a host name taken from the middle of
      the password;
    * a password containing `/` ends the authority early, so the rest of it
      becomes a QUERY STRING — which, with `?` also present, may not parse at
      all;
    * a password containing `%` starts an invalid percent-escape, which the
      parser rejects.

    The symptom of every one of those is an authentication error HOURS later,
    pointing at the RDS user rather than at this function. So this test asserts
    the round trip, and then asserts that the naive alternative really would have
    failed — without that second half the test would still pass if the code built
    a URL that happened to work for a benign password, which is the bug.
    """
    aws(password=HOSTILE_PASSWORD)

    dsn = config.resolve_database_url()

    url = make_url(dsn)

    # Every character of the password survives, and so does everything else —
    # a DSN that corrupts the password by mangling the host instead would still
    # produce a `url` here, just a wrong one.
    assert url.password == HOSTILE_PASSWORD
    assert url.host == RDS_HOST
    assert url.port == RDS_PORT
    assert url.username == RDS_MASTER_USERNAME
    assert url.database == "lemondrop"

    # The control: prove the test is not vacuous by building the naive DSN and
    # showing it does NOT round-trip. It may fail to parse at all, or it may parse
    # to the wrong components — either is the bug this requirement exists to stop,
    # and both are acceptable outcomes here because the point is only that they
    # differ from the correct answer.
    naive = (
        f"{POSTGRES_ASYNCPG_DRIVER}://{RDS_MASTER_USERNAME}:{HOSTILE_PASSWORD}"
        f"@{RDS_HOST}:{RDS_PORT}/lemondrop"
    )
    try:
        naive_url = make_url(naive)
    except Exception:  # noqa: BLE001 — "fails to parse" is a valid outcome
        naive_wrong = True
    else:
        naive_wrong = (
            naive_url.password != HOSTILE_PASSWORD
            or naive_url.host != RDS_HOST
            or naive_url.port != RDS_PORT
        )
    assert naive_wrong, (
        "naive concatenation unexpectedly produced a correct DSN for this "
        "password — the hostile password may no longer be hostile, and this test "
        "would then be asserting nothing"
    )


def test_the_hostile_password_also_survives_the_settings_validator(aws):
    """The DSN from above must pass `Settings` unchanged.

    Separate from the round trip because it is a DIFFERENT parser's opinion.
    `make_url` is SQLAlchemy's general URL parser; the validator in `config.py`
    runs it over the DSN specifically to decide whether the credential is usable,
    and a rendered DSN that one parser accepts can still surprise the next.
    """
    aws(password=HOSTILE_PASSWORD)

    settings = get_settings()

    assert make_url(settings.database_url.get_secret_value()).password == HOSTILE_PASSWORD
    assert settings.database_host == RDS_HOST


# ── 5. A secret that is missing a field ──────────────────────────────────────


@pytest.mark.parametrize("field", ["username", "password"])
def test_a_secret_missing_a_field_names_that_field(aws, field):
    """A secret without a usable field must fail naming WHICH field is missing.

    "the secret is malformed" sends the operator to look at a secret they cannot
    see. "the secret has no usable `password` field" sends them to
    `manage_master_user_password`, which is where the answer is.

    Parametrised over both fields because they are checked by the same comparison
    and a half-fix that handles `password` and forgets `username` is exactly the
    plausible mistake — the two must be asserted separately or the second is
    untested.
    """
    payload = {"username": RDS_MASTER_USERNAME, "password": ORDINARY_PASSWORD}
    del payload[field]
    aws(secret_string=json.dumps(payload))

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert f"`{field}`" in message, f"the error must name the field, got: {message}"
    # The OTHER field's name appearing would be fine; the field's own value
    # appearing would not. The surviving value is asserted absent so the check is
    # not satisfied by a message that quotes the whole secret.
    assert ORDINARY_PASSWORD not in message


@pytest.mark.parametrize("bad_value", [None, 42, "", "   "])
def test_a_secret_with_an_unusable_field_value_is_rejected(aws, bad_value):
    """A field that is present but not a usable string is a missing field.

    `null`, a number, an empty string and a whitespace-only string are all as
    unusable as an absent key, and they all have the same fix — look at how the
    secret was created. Distinguishing them in the message would be guessing.

    The whitespace-only case is the interesting one: it is truthy, so an
    `if not payload.get(field)` check would accept it and hand a blank
    credential to the driver.
    """
    aws(secret_string=json.dumps({"username": RDS_MASTER_USERNAME, "password": bad_value}))

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    assert "`password`" in str(excinfo.value)


# ── 6. A secret that is not JSON ─────────────────────────────────────────────


def test_a_secret_that_is_not_json_is_rejected_without_echoing_it(aws):
    """A non-JSON secret fails clearly, and its body never appears in the error.

    The secret body is the credential, so this is really a statement about the
    message rather than about the parse. The message must be specific enough to
    act on — it names the ARN, says what the shape should have been, and says why
    the value is not reproduced — while containing nothing of the value itself.

    `api/tests/test_db.py`'s redactor tests cover the same principle for driver
    messages; this is the module's own equivalent for a message this module
    writes.
    """
    body = f"not json at all — the password is {ORDINARY_PASSWORD} and here is more"
    aws(secret_string=body)

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert "JSON" in message, f"the error must say what was wrong, got: {message}"
    assert RDS_SECRET_ARN in message, "the error must name which secret failed"
    assert ORDINARY_PASSWORD not in message, "the secret body must not be echoed"
    assert body not in message


def test_json_that_is_not_an_object_is_rejected(aws):
    """A secret holding a JSON list or string fails, rather than indexing it.

    The obvious implementation is `json.loads(...)["password"]`, which raises a
    `TypeError` on a list and a `KeyError` on a string — an exception whose text
    is about Python, not about which secret is wrong.
    """
    aws(secret_string=json.dumps(["username", "password"]))

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    assert "not an object" in str(excinfo.value)


def test_a_secret_with_only_secret_binary_is_rejected(aws):
    """A `SecretBinary`-only secret fails with a message that says why.

    Reachable in practice: `aws secretsmanager put-secret-value` can write a
    binary secret to the same ARN, and RDS's managed secret is the JSON string
    shape. The failure would otherwise be a `KeyError: 'SecretString'` whose text
    names a Python dictionary and nothing an operator can act on.
    """
    aws(secret_binary_only=True)

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert RDS_SECRET_ARN in message
    assert "SecretString" in message
    assert "manage_master_user_password" in message


# ── 7. Access denied ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("parameter", [HOST_PARAMETER, PORT_PARAMETER, SECRET_ARN_PARAMETER])
def test_access_denied_names_the_parameter_it_failed_on(aws, parameter):
    """A denied read must name BOTH the parameter and the IAM action.

    The operator's next move after any of these is "check the role's policy", and
    the first question they have to answer is "which of the three statements?".
    A message that said only "AccessDeniedException" would send them to the IAM
    console with nothing to search for — and the IAM changes this path depends on
    are documented as NOT YET APPLIED, which makes this the single most likely
    first failure anyone actually sees.

    Parametrised over all three parameters so the stub is proven to dispatch on
    the name: a stub that ignored `Name` could not produce three distinct
    messages, and neither could a resolver that reported a generic failure.
    """
    aws(denied_parameters=(parameter,))

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert parameter in message, f"the error must name the parameter, got: {message}"
    assert AWS_SSM_GET_PARAMETER_ACTION in message
    assert "AccessDeniedException" in message


def test_access_denied_on_the_secret_names_the_secret_action(aws):
    """A denied `GetSecretValue` names `secretsmanager:GetSecretValue`, not SSM.

    A separate test because the two denials have different causes and different
    fixes, and a message that named the wrong action would send the operator to
    the wrong statement in the policy. The IAM policy in `infra/iam.tf` grants
    them separately.
    """
    aws(secret_denied=True)

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert AWS_SECRETS_GET_SECRET_VALUE_ACTION in message
    assert RDS_SECRET_ARN in message, "the error must name the secret it could not read"
    assert AWS_SSM_GET_PARAMETER_ACTION not in message, (
        "the three SSM reads succeeded — naming their action here would point the "
        f"operator at the wrong policy statement: {message}"
    )


def test_a_missing_parameter_is_not_reported_as_a_permission_problem(aws):
    """`ParameterNotFound` gets its own message, because it is not an IAM problem.

    Sending an operator to check their role policy when the parameter was never
    deployed sends them to the wrong console entirely — and the real cause
    (`var.enable_managed_database` false, or the SSM resources simply never
    applied) is one `terraform apply` away.
    """
    aws(absent_parameters=(PORT_PARAMETER,))

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert PORT_PARAMETER in message
    assert "ParameterNotFound" in message
    assert AWS_SSM_GET_PARAMETER_ACTION not in message, (
        f"a parameter that does not exist is not a permissions problem: {message}"
    )


def test_a_parameter_with_no_value_is_reported_as_a_shape_problem(aws):
    """A parameter read successfully but carrying no `Value` says so.

    Distinct from every other failure because the policy is FINE — the role could
    read it — and telling the operator to check their permissions would be a
    wrong answer to a question they did not ask.
    """
    aws(malformed_parameters=(SECRET_ARN_PARAMETER,))

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert SECRET_ARN_PARAMETER in message
    assert AWS_SSM_GET_PARAMETER_ACTION not in message


def test_a_port_that_is_not_a_number_is_reported_with_its_value(aws):
    """A non-numeric port fails with the value quoted.

    The port is not a credential — it is published in `infra/iam.tf` as
    `tostring(local.db_port)` — so quoting it is safe, and quoting it is the
    whole value of the message: the operator's next action is to look at what
    that parameter actually contains, and they cannot do that from "not a port
    number".
    """
    aws(port="not-a-port")

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert "not-a-port" in message
    assert PORT_PARAMETER in message


# ── Region ───────────────────────────────────────────────────────────────────


def test_a_missing_region_names_the_variable_rather_than_defaulting(aws):
    """No region means no client, and an error naming BOTH accepted variables.

    Both, because either one satisfies the read and an operator told only about
    `AWS_DEFAULT_REGION` on a host that uses `AWS_REGION` would conclude the
    problem is the instance role.

    The stub passed in is never called — asserted by the call list being empty —
    because the region is resolved before any client is constructed. That ordering
    is the point: there is no state in which the process has begun talking to AWS
    in the wrong region.
    """
    stub = aws()
    os.environ.pop("AWS_REGION", None)
    config._resolve_database_url_from_aws_once.cache_clear()

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert "AWS_REGION" in message and "AWS_DEFAULT_REGION" in message
    assert stub.calls == [], "no client may be constructed without a region"


# ── 8. The credential leak test ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("scenario", "kwargs"),
    [
        ("ssm denied", {"denied_parameters": (HOST_PARAMETER,)}),
        ("parameter absent", {"absent_parameters": (PORT_PARAMETER,)}),
        ("parameter without a value", {"malformed_parameters": (SECRET_ARN_PARAMETER,)}),
        ("port not a number", {"port": "not-a-port"}),
        ("secret denied", {"secret_denied": True}),
        ("secret not JSON", {"secret_string": f"plain text {HOSTILE_PASSWORD}"}),
        ("secret missing username", {"secret_string": json.dumps({"password": HOSTILE_PASSWORD})}),
        ("secret missing password", {"secret_string": json.dumps({"username": "u"})}),
        ("secret json not an object", {"secret_string": json.dumps(HOSTILE_PASSWORD)}),
        ("secret field unusable", {"secret_string": json.dumps({"username": "u", "password": 7})}),
    ],
)
def test_no_failure_path_leaks_the_password(aws, scenario, kwargs, caplog):
    """Across every way this can fail, the password reaches nothing.

    The same claim as `test_db.py`'s end-to-end redaction test, for a different
    set of failure modes: those are DRIVER messages, and these are messages this
    module writes itself. Driver redaction is proven in `db.py`; this proves that
    a future edit to an f-string in `config.py` cannot reintroduce the leak on a
    path `db.py`'s redactor never sees — and it cannot, because the redactor only
    knows about the DSN, which does not exist yet when these messages are built.

    Checked in four places, for the same four reasons as the test in `test_db.py`:

      1. the exception message, which is what ends up in a bug report;
      2. every log record, at DEBUG and above, including the one INFO line this
         path emits — `getMessage()` and `args` both, because a secret passed as
         a logging argument is the common case and is not in `record.msg`;
      3. the password must not be sitting in the exception's `__cause__` or
         `__context__` chain, which a traceback renders above the message;
      4. `repr()` of anything the module produced on the way out.

    `HOSTILE_PASSWORD` is the marker rather than `ORDINARY_PASSWORD` because it
    also contains the URL metacharacters, so this catches the encoded forms too:
    a message carrying `p%40ss%3A...` rather than `p@ss:w` is still a leak, and a
    plain substring check would not see it.
    """
    aws(password=HOSTILE_PASSWORD, **kwargs)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(RuntimeError) as excinfo:
        get_settings()

    exc = excinfo.value
    message = str(exc)

    assert HOSTILE_PASSWORD not in message, f"{scenario}: the password is in the message"
    assert f"%40" not in message.replace("p@ss", ""), (
        f"{scenario}: a percent-encoded password fragment reached the message"
    )

    # The chained exception is checked because `raise ... from None` is a
    # DISCIPLINE, not a guarantee: an added `except` branch that forgets it, or a
    # future refactor that drops it, would attach the botocore or json traceback
    # above this message and render the secret right there.
    for linked in (exc.__cause__, exc.__context__):
        assert linked is None or HOSTILE_PASSWORD not in f"{linked!r}{linked}"

    for record in caplog.records:
        rendered = record.getMessage()
        assert HOSTILE_PASSWORD not in rendered, (
            f"{scenario}: the password is in a log record from {record.name}: {rendered}"
        )
        assert HOSTILE_PASSWORD not in repr(record.args), (
            f"{scenario}: the password is in the log args from {record.name}"
        )

    # 4. The DSN itself — which contains the password percent-encoded — must not
    #    be in anything either, and this is the check that covers the case where
    #    resolution SUCCEEDED and something later rendered it.
    encoded_dsn_fragment = "p%40ss%3Aw%2Fo%3Frd%25"
    for record in caplog.records:
        assert encoded_dsn_fragment not in record.getMessage()


def test_the_successful_path_logs_the_host_and_nothing_else(aws, caplog):
    """The one INFO line this path emits is audited by a test, not by a promise.

    A logger line is the easiest place in this codebase to leak a credential and
    the hardest to notice, because it is written once, works, and is never read
    again. Asserted positively rather than negatively: the message must name the
    region and the host — which is what `Settings.database_host` exists to permit
    — and must contain none of the DSN, the username, the secret ARN or the
    password.
    """
    aws(password=HOSTILE_PASSWORD)
    caplog.set_level(logging.DEBUG)

    config.resolve_database_url()

    messages = [record.getMessage() for record in caplog.records]
    assert messages, "the resolver emitted no log record at all, so nothing was audited"

    for message in messages:
        assert RDS_HOST in message, f"the log must say which database, got: {message}"
        assert HOSTILE_PASSWORD not in message
        assert RDS_MASTER_USERNAME not in message, (
            "the username is part of the connection string and has no business in "
            f"a log line: {message}"
        )
        assert RDS_SECRET_ARN not in message, (
            "the ARN is an identifier rather than a credential, but the host "
            f"already says which database this is: {message}"
        )
        assert "postgresql+asyncpg://" not in message, (
            f"no DSN may reach a log line: {message}"
        )


# ── 9. The never-raises contract survives the AWS path ───────────────────────


def test_a_failed_aws_resolution_leaves_the_database_not_ready_rather_than_crashing(aws):
    """`db.startup()` must return a not-ready `Database`, never raise.

    This is the whole reason `db.startup` catches everything it does. A resolver
    that raised out of startup would take down a container that can still serve
    `/health/live`, `/embed` and `/rerank` — a database blip would become a
    restart loop, which is the outcome `db.startup`'s docstring says it exists to
    prevent.

    And `db.startup` cannot redact its way out of the AWS path the way it does for
    the environment path: its redactor knows the DSN from `DATABASE_URL`, which on
    this path does not exist. The guarantee therefore has to be that these
    messages contain no credential to begin with, which is what the leak test
    above checks and what is asserted here by looking at what actually reached
    the log.
    """
    import logging as _logging

    records: list[str] = []

    class _Capture(_logging.Handler):
        def emit(self, record: Any) -> None:
            records.append(record.getMessage())

    handler = _Capture()
    config.logger.addHandler(handler)
    try:
        database = asyncio.run(db.startup())
    finally:
        config.logger.removeHandler(handler)

    assert database.engine is None
    assert database.ready is False
    assert database.problem, "a failed resolution must leave a reason on the Database"
    assert HOSTILE_PASSWORD not in database.problem

    for message in records:
        assert HOSTILE_PASSWORD not in message


# ── 10. Regression protection for the local path ──────────────────────────────


def test_the_local_database_url_path_is_byte_for_byte_unchanged(monkeypatch):
    """The 62 existing tests all build their DSN through this branch.

    Not a restatement of `test_db.py`'s `test_a_fully_populated_dsn_still_constructs`:
    that one proves `Settings` accepts a DSN it was HANDED. This one proves the
    SELECTOR hands over exactly what the environment holds — the branch every
    local and compose deployment takes, and the one that was working before any of
    this file existed. If the selector ever trimmed, re-encoded, normalised or
    re-ordered the components of a DSN, that would break local development while
    every AWS test in this file still passed.
    """
    dsn = "postgresql+asyncpg://lemondrop:correct-horse-battery-staple@127.0.0.1:5432/lemondrop"
    monkeypatch.setenv(DATABASE_URL_ENV_VAR, dsn)

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the local path constructed a boto3 client")

    monkeypatch.setattr(config, "_boto3_client", _explode)

    assert config.resolve_database_url() == dsn
    assert get_settings().database_url.get_secret_value() == dsn
    assert get_settings().database_host == "127.0.0.1"


# ── 11. The region reaches the CONTAINER (deployment files) ───────────────────
#
# Everything above this line tests the resolver. The resolver is correct and was
# left untouched: it reads AWS_REGION, then AWS_DEFAULT_REGION, and raises naming
# both when neither is set, and the tests above prove it does. What was missing was
# one level UP — the region never got INTO the container, because a Docker
# container does not inherit the host's environment and neither docker-compose.yml
# nor .env.example mentioned either variable. The failure looked like a resolver
# bug and was a wiring bug, which is the kind that survives a careful reading of
# the module that is raising.
#
# So these tests read the deployment files instead of the module. No network, no
# live AWS, no container: the unit under test is the text of the two files.


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"

# The pass-through form as it is deployed. Used in assertion messages rather than
# as a whole-string comparison, so that a test failure shows both what is there and
# what was required without the check itself depending on incidental quoting.
PASS_THROUGH_FORM = '${AWS_REGION:-}'


def _api_environment_block() -> str:
    """Return the `environment:` block of the `api` service, as text.

    Parsed by locating the block rather than by loading the file with PyYAML, and
    that is a deliberate trade. `yaml` is available in this venv today, but it is
    not something `api/` declares anywhere — there is no requirements file entry
    for it and no test in this suite imports it — so asserting on `yaml.safe_load`
    would mean a green suite that turns red the moment someone runs the tests in
    an environment built from the image's declared dependencies.

    The block is located structurally rather than by a bare substring search,
    because `DB_DSN_SOURCE` and `DATABASE_URL` appear in several other services'
    blocks and in the comments above them. Substring search over the whole file
    would find the wrong line and pass for the wrong reason, which is worse than
    not testing this at all.

    Indentation is the discriminator: the `api` service's `environment:` key sits
    at four spaces under `  api:`, and its entries at six. Any future edit that
    reformats that service's block breaks this helper loudly, which is the correct
    failure — a silent miss is what this test exists to prevent.
    """
    lines = COMPOSE_FILE.read_text(encoding="utf-8").splitlines()

    service_start = next(
        (i for i, line in enumerate(lines) if line.rstrip() == "  api:"),
        None,
    )
    assert service_start is not None, "docker-compose.yml has no `  api:` service"

    environment_start = next(
        (
            i
            for i in range(service_start, len(lines))
            if lines[i].rstrip() == "    environment:"
        ),
        None,
    )
    assert environment_start is not None, "the api service has no `environment:` block"

    block = [lines[environment_start]]
    for line in lines[environment_start + 1:]:
        # An entry is `      KEY: value`; a comment inside the block is indented
        # at the same six. The block ends at the first line that is neither —
        # which is a blank line, or the next key at a shallower indent.
        if not line.strip():
            break
        if not line.startswith("      ") or line.startswith("       "):
            break
        block.append(line)

    return "\n".join(block)


# One interpolation, matched rather than split by eye: `${NAME}`, `${NAME:-default}`
# or `${NAME-default}`. The two groups are the variable and the default, and the
# distinction that matters here is between group 2 being None — no `:-` at all, so
# there is no default expressed and the host's own shell decides — and it being
# the empty string, which is the explicit empty default this fix relies on. A
# plain string split on `:-` cannot tell those apart, which is why this is a
# regex.
INTERPOLATION = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-?([^}]*))?\}$")


def _api_environment_value(name: str) -> str:
    """The `api` service's declared value for `name`, unquoted.

    Unquoted because compose treats `"${X:-}"` and `${X:-}` as the same value, and
    the quoting is a YAML detail — asserting on it would fail a correct edit that
    added or removed quotes for readability.
    """
    block = _api_environment_block()
    prefix = f"{name}:"
    entries = [
        line.strip() for line in block.splitlines() if line.strip().startswith(prefix)
    ]

    assert len(entries) == 1, (
        f"expected exactly one {name} entry in the api service's environment "
        f"block, found {len(entries)}: {entries!r}\nBlock was:\n{block}"
    )

    return entries[0][len(prefix):].strip().strip("\"'")


def test_the_compose_file_passes_the_region_into_the_api_container():
    """`api` must RECEIVE `AWS_REGION`, in the pass-through form, with no default.

    Three claims, and the third is the one that matters most:

      1. the key exists in the `api` service's `environment:` block, so the
         container receives the host's value at all. A container does not inherit
         the host environment, so a key that is only in `.env` reaches nothing;
      2. its value is an interpolation of AWS_REGION — the pass-through — rather
         than a literal this file invented;
      3. the default after `:-` is EMPTY. Not `:-eu-west-1`, not
         `${AWS_REGION:-us-east-1}` — empty.

    Claim 3 is asserted on the PARSED fallback rather than by comparing the whole
    string, because that is the claim which survives a plausible edit: someone who
    "helpfully" fills in a region keeps the pass-through syntax and changes only
    that one substring. Naming it separately is what makes "no hardcoded region
    here" an enforced property rather than a convention.

    What this test deliberately does NOT claim is that the interpolation reads the
    right variable — the test below owns that, so that neither is a restatement of
    the other and a failure names the specific mistake.

    The empty default is the local-development case, and it is load-bearing in the
    same way the empty DATABASE_URL above is. This stack never builds an AWS
    client, so an empty region here is inert. A hardcoded one would be worse than
    inert: on the deployed host a wrong region does not fail as a configuration
    error, it fails as an AWS error naming a region that deployment never used,
    which reads like an IAM problem and sends the operator to audit the instance
    role.
    """
    block = _api_environment_block()

    assert "AWS_REGION:" in block, (
        "the api service's environment block declares no AWS_REGION, so the "
        "container cannot receive the host's region and _aws_region() raises "
        f"before boto3 is ever constructed. Block was:\n{block}"
    )

    value = _api_environment_value("AWS_REGION")

    parsed = INTERPOLATION.match(value)
    assert parsed is not None, (
        f"AWS_REGION must be the pass-through {PASS_THROUGH_FORM}, not a value "
        f"this file composed: {value!r}"
    )

    fallback = parsed.group(2)
    assert fallback == "", (
        "AWS_REGION must be the empty-default pass-through "
        f"{PASS_THROUGH_FORM}: no `:-` at all, or a `:-` followed by a hardcoded "
        f"region. Got a default of {fallback!r}. A hardcoded region here fails as "
        "an AWS error naming a region this deployment never used, which reads "
        "like an IAM problem, and the operator audits the instance role instead "
        "of this file"
    )


def test_the_compose_file_does_not_compose_the_region_out_of_other_variables():
    """The compose block hands the region over; it does not build one.

    The counterpart to the empty-default check above, and non-redundant with it:
    a substituted variable (`${AWS_DEFAULT_REGION:-}`, wrong name, empty default)
    passes that check and fails this one, while a hardcoded region fails both.

    Asserted as: the interpolation references exactly one variable, named
    AWS_REGION, and its default is free of any further reference. The regex is
    deliberately closed — no nesting, no `$` inside — so a composed expression such
    as `${AWS_REGION:-${AWS_DEFAULT_REGION:-}}` cannot match it by being clever,
    and a bare literal region matches nothing at all.
    """
    value = _api_environment_value("AWS_REGION")

    parsed = INTERPOLATION.match(value)
    assert parsed is not None, (
        f"AWS_REGION is not a single-variable interpolation, it is composed: {value!r}"
    )

    variable, fallback = parsed.groups()

    assert variable == "AWS_REGION", (
        f"the interpolation must read AWS_REGION itself, got: {variable!r}"
    )
    assert "$" not in (fallback or ""), (
        "the pass-through composes nothing from another variable; "
        f"got: {value!r}"
    )


def test_the_env_example_defines_the_region_and_leaves_it_empty():
    """`.env.example` must NAME the key and ship it with NO value.

    Both halves. The key has to be there, because `scripts/boot.sh` copies this
    template over `.env` on the EC2 host: a key the template never mentions is a
    key the operator has to discover from a stack trace. And the value has to be
    empty, because this file is committed — a region in it would be a region that
    nobody chose, that every clone inherits, and that quietly becomes the answer
    on a host where the real region is something else. Same reasoning as
    DEV_DATABASE_URL above, applied to a value that happens not to be a secret.

    The literal `AWS_REGION=` with nothing after it is the assertion. Matching it
    on the KEY alone would pass for `AWS_REGION=eu-west-1`, which is exactly the
    mistake this test is for.
    """
    text = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")
    assignments = [
        line for line in text.splitlines() if line.startswith("AWS_REGION=")
    ]

    assert assignments, (
        ".env.example does not define AWS_REGION at all; boot.sh copies this "
        "template over .env on EC2, so the key must exist for the operator to fill in"
    )

    assert assignments == ["AWS_REGION="], (
        "AWS_REGION must be declared exactly once in .env.example and with an "
        f"EMPTY value — a committed template must not ship a working "
        f"configuration. Got: {assignments!r}"
    )


def test_the_resolver_still_refuses_to_guess_a_region(aws, monkeypatch):
    """With BOTH variables absent it must still raise, naming both — no fallback.

    This is the assertion that the deployment fix does not become a resolver fix.
    Softening `_aws_region` to default to some region would make the tests above
    pass on a host that never set one, and it would do it by producing an AWS
    error that names a region the deployment never used — a failure mode that
    looks like IAM and is not, and that the operator pays for by auditing a role
    that was fine.

    So the guarantee is pinned on BEHAVIOUR, with both variables removed by this
    test itself rather than trusting the autouse fixture: a fixture that forgot a
    variable would silently turn "no region" into "whatever this machine exports",
    and the test would keep passing while testing nothing. `delenv` on both names
    is the construction of the situation, not an assumption about it.

    Both names appear in the message, for the reason `_aws_region` gives: either
    one satisfies the read, so an operator told only about AWS_DEFAULT_REGION on a
    host that sets AWS_REGION would go looking at the instance role.

    And no client is constructed — asserted by the stub's call list, which the
    resolver cannot reach without a region. That ordering is the property that
    makes the guarantee worth having: there is no state in which the process has
    begun talking to AWS somewhere unintended.
    """
    stub = aws()

    # Removed here, in the test, rather than left to the autouse fixture: this is
    # the construction of the situation, and a fixture that forgot one of the two
    # names would otherwise turn "no region" into "whatever this machine exports"
    # and the test would keep passing while testing nothing. `monkeypatch.delenv`
    # rather than `os.environ.pop` because it restores the developer's own value
    # at teardown, so a machine that exports AWS_REGION is left as it was found.
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(name, raising=False)
    config._resolve_database_url_from_aws_once.cache_clear()

    with pytest.raises(RuntimeError) as excinfo:
        config.resolve_database_url()

    message = str(excinfo.value)

    assert "AWS_REGION" in message, f"the error must name AWS_REGION, got: {message}"
    assert "AWS_DEFAULT_REGION" in message, (
        f"the error must name AWS_DEFAULT_REGION as well — either satisfies the "
        f"read. Got: {message}"
    )
    assert stub.calls == [], "no client may be constructed without a region"