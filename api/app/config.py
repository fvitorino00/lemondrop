"""lemondrop API — application settings, read from the environment.

This module answers one question: *what does this process need to know before it
can do anything?* Everything here is read once, at settings-construction time,
into a single frozen object, so that no later code has to reach back into
``os.environ`` and no two call sites can disagree about a value.

Four decisions in this file are load-bearing and all four are about the DSN:

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
4. WHERE THE DSN COMES FROM IS EXPLICIT, NEVER INFERRED. See
   ``DB_DSN_SOURCE_ENV_VAR`` and ``resolve_database_url``. A process that
   cannot find ``DATABASE_URL`` does NOT quietly fall back to AWS; it either
   reads the environment or it was told, by name, to read AWS.

Everything else in here is either a named constant with a stated reason, a small
helper that exists to keep a credential out of a log line, or the retrieval
funnel — ``QUERY_PREFIX``, ``Funnel`` and ``funnel_from_environment`` — which is
the one piece of configuration that is about behaviour rather than about
connecting. The bge query prefix is the most dangerous string in this repository
and is defined here precisely so that there is exactly one of it: see the block
above ``QUERY_PREFIX``.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)
from sqlalchemy.engine import URL, make_url

logger = logging.getLogger(__name__)

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

# ── Retrieval behaviour ───────────────────────────────────────────────────────
#
# Three values, and they belong together because getting one of them wrong
# produces the same failure: a funnel that quietly returns the wrong number of
# documents, with a 200 and a plausible-looking result list as the only evidence.

QUERY_PREFIX_ENV_VAR = "QUERY_PREFIX"
RETRIEVAL_CANDIDATES_ENV_VAR = "RETRIEVAL_CANDIDATES"
RERANK_TOP_K_ENV_VAR = "RERANK_TOP_K"

# bge-small-en-v1.5's instruction string, verbatim. The trailing space is part of
# it: the prefix is concatenated with `QUERY_PREFIX + text`, not with a separator
# added between them, so the space belongs to the constant.
DEFAULT_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Read once at import, like the model aliases in main.py, and for the same
# reason: it is a property of the EMBEDDING MODEL rather than a per-deployment
# tuning knob, so there is nothing for a caller to disagree about at request
# time. It is NOT a field on `Settings` — a field would invite per-request
# variation on a string whose only correct value is the one the model was
# trained with.
#
# It is also the single most dangerous string in this repository, so the comment
# above it is the invariant: prepended to the QUERY by /search, to NOTHING else.
# `/embed` and `/documents` both forward text bare, and a document stored with
# this string attached to it carries a permanently corrupted vector that no
# response ever reports.
QUERY_PREFIX = os.environ.get(QUERY_PREFIX_ENV_VAR, DEFAULT_QUERY_PREFIX)

# Stage 1 — how many candidates the vector store returns before reranking.
#
# WHY 10 AND NOT 50. `.env.example` documented 50 until this phase, and 50 was
# never exercised by anything: the value was read by no code. It is sized here
# rather than carried forward because the reranker is a CROSS-ENCODER: it scores
# every (query, passage) pair it is handed, on CPU, with no batch discount and
# no GPU to hide behind. 50 pairs is five times the inference work of 10.
#
# And the box is already documented as tight. Milestone 2 measured this host as a
# `t3.micro`: 913Mi total, with roughly 280Mi available at rest once the two
# llama.cpp models are resident. A five-fold increase in the slowest thing this
# service does is exactly the change that turns a documented constraint into an
# incident, on hardware whose memory headroom is already the subject of
# `config.py`'s pool-sizing comment.
#
# The floor is 1 and not 0: a zero candidate count would make /search return an
# empty result set for every query, for every collection, with a 200 — the one
# failure mode in this service that looks exactly like success.
DEFAULT_RETRIEVAL_CANDIDATES = 10

# Stage 2 — how many reranked results the caller receives. Five is a presentation
# choice rather than a resource one (the work was already done by the time this
# number applies), so it is not sized against the host.
DEFAULT_RERANK_TOP_K = 5


@dataclass(frozen=True)
class Funnel:
    """The two numbers that size /search, validated together.

    ── WHY THIS IS A SEPARATE OBJECT AND NOT TWO INT FIELDS ON `Settings` ──────
    `Settings` cannot be constructed without a `DATABASE_URL` (see
    `resolve_database_url_from_environment`), and `/search` needs these two
    numbers in order to work. Making the route build a whole `Settings` — whose
    only other content is a credential it does not need — would mean the route
    could not run on a host where the DSN is unconfigured, on a service whose
    documented policy is to keep serving `/health/live` and report 503 elsewhere.
    The funnel is the retrieval policy; it is not part of the connection
    configuration, and it is kept separately so it can be validated without one.

    `Settings` still carries both values, because the operator's `.env` is one
    file and both numbers come from it — but it validates them by constructing
    one of these, so there is exactly ONE definition of "a coherent funnel" in
    this module rather than two that could drift.
    """

    #: Stage 1: candidates drawn from the vector store before reranking.
    retrieval_candidates: int

    #: Stage 2: reranked results returned to the caller. Always <= the above.
    rerank_top_k: int

    def clamped(
        self,
        *,
        candidates: int | None,
        top_k: int | None,
    ) -> tuple[int, int]:
        """Resolve caller-supplied optional sizes against the configured maxima.

        Returns `(candidates, top_k)` ready to hand to `store.retrieve` and to
        the reranker.

        ── WHY A CALLER CAN ASK FOR LESS BUT NEVER FOR MORE ──────────────────────
        The defaults here are the CONFIGURATION, so a caller that says nothing
        gets exactly what the operator configured — this function is not a second
        place that decides the funnel. What a caller MAY do is ask for less, and
        `min()` is the whole mechanism: a value above the configured maximum is
        clamped DOWN to it, never honoured and never rejected.

        Clamping rather than rejecting is deliberate. A 422 here would be
        defensible, but it would also mean a client has to know the server's
        configuration to be well-formed, and would have to change its code when
        the operator changes `.env`. Asking for more than the server is willing
        to compute is not an error — it is a request the server satisfies as
        fully as it can, and the response says how many candidates it actually
        considered so the caller can see that.

        Clamping is ALSO what makes the funnel's cost bound real. Without it, a
        caller could set `candidates=10000` on a box that `config.py` sizes its
        PostgreSQL pool for 3 connections because the reranker is the bottleneck.
        The `RERANK_TOP_K <= RETRIEVAL_CANDIDATES` rule protects the pair from
        each other; this `min()` protects both of them from the caller.
        """
        resolved_candidates = min(
            DEFAULT_RETRIEVAL_CANDIDATES if candidates is None else candidates,
            self.retrieval_candidates,
        )
        resolved_top_k = min(
            DEFAULT_RERANK_TOP_K if top_k is None else top_k,
            self.rerank_top_k,
            # Never return more results than were considered. Without this the
            # truncation below would be a no-op for a caller who asked for
            # candidates=2, top_k=5, and the response would claim five results
            # out of two candidates — a claim that is arithmetic, and arithmetic
            # is not a creative choice.
            resolved_candidates,
        )
        # `max(1, ...)` is not defensive padding: both maxima are validated as
        # >= 1 below and both inputs are Field(ge=1), so the only way to reach 0
        # is to have edited one of those rules. The guard turns that edit into an
        # obviously wrong number rather than a `store.retrieve` ValueError at
        # request time.
        return max(1, resolved_candidates), max(1, resolved_top_k)


def funnel_from_environment() -> Funnel:
    """Read `RETRIEVAL_CANDIDATES` and `RERANK_TOP_K` and return them validated.

    The no-DSN counterpart to `get_settings`, for the reason on `Funnel`: the
    retrieval route needs these two numbers whether or not a database is
    configured, so that it can report a truthful 503 about the database rather
    than a configuration error about something it never used.

    Read at call time rather than import time, so a test can drive it with a
    patched environment and so that the values are never cached from a moment
    before `.env` was loaded.
    """
    try:
        retrieval_candidates = int(
            os.environ.get(RETRIEVAL_CANDIDATES_ENV_VAR, DEFAULT_RETRIEVAL_CANDIDATES)
        )
    except ValueError:
        raise ValueError(
            f"{RETRIEVAL_CANDIDATES_ENV_VAR} is not an integer. It is a COUNT of "
            f"documents to fetch from the vector store — {DEFAULT_RETRIEVAL_CANDIDATES} "
            "in the default configuration."
        ) from None

    try:
        rerank_top_k = int(os.environ.get(RERANK_TOP_K_ENV_VAR, DEFAULT_RERANK_TOP_K))
    except ValueError:
        raise ValueError(
            f"{RERANK_TOP_K_ENV_VAR} is not an integer. It is a COUNT of reranked "
            f"results to return — {DEFAULT_RERANK_TOP_K} in the default configuration."
        ) from None

    return _build_funnel(retrieval_candidates, rerank_top_k)


def _build_funnel(retrieval_candidates: int, rerank_top_k: int) -> Funnel:
    """Validate the pair and return it, or raise naming BOTH values.

    ── WHY THE PAIR IS VALIDATED TOGETHER, AND WHY A top_k ABOVE THE CANDIDATE
    COUNT IS A CONFIGURATION ERROR RATHER THAN A RUNTIME SURPRISE ──────────────
    A `rerank_top_k` larger than `retrieval_candidates` is arithmetically
    impossible to satisfy: stage 2 can only re-order the documents stage 1
    returned, so the most it could ever produce is `retrieval_candidates`
    results. Left unvalidated, that does not raise at startup. It produces a
    search that returns a SHORTER list than the operator configured, on every
    query, forever — with a 200 and nothing in the body saying the configured
    number was unreachable.

    That is the same failure shape this module already rejects everywhere else: a
    misconfiguration that starts successfully and serves wrong answers. A caller
    asking for `top_k` above the maximum is a different case and is handled
    differently — `Funnel.clamped` truncates it — because the caller's request
    is asking for less work, not expressing a broken belief about the server.

    The message names BOTH numbers because the fix is a comparison between them.
    A message naming only the offending one leaves the operator to go and look
    up the other, which is the thing they were about to get wrong.
    """
    if retrieval_candidates < 1:
        raise ValueError(
            f"{RETRIEVAL_CANDIDATES_ENV_VAR} is {retrieval_candidates}, which is not a "
            "usable funnel. It must be at least 1: a candidate count of 0 would make "
            f"/search return an empty result set for every query, with a 200 — the one "
            f"failure that looks exactly like success. (RERANK_TOP_K is {rerank_top_k}.)"
        )
    if rerank_top_k < 1:
        raise ValueError(
            f"{RERANK_TOP_K_ENV_VAR} is {rerank_top_k}, which is not a usable result "
            "count. It must be at least 1, or /search would return nothing after doing "
            f"all of the work. ({RETRIEVAL_CANDIDATES_ENV_VAR} is "
            f"{retrieval_candidates}.)"
        )
    if rerank_top_k > retrieval_candidates:
        raise ValueError(
            f"{RERANK_TOP_K_ENV_VAR} is {rerank_top_k} but "
            f"{RETRIEVAL_CANDIDATES_ENV_VAR} is only {retrieval_candidates}. "
            "The reranker can only re-order the documents the vector store returned, "
            "so it can never produce more results than there were candidates. "
            f"Raise {RETRIEVAL_CANDIDATES_ENV_VAR} to at least {rerank_top_k}, or lower "
            f"{RERANK_TOP_K_ENV_VAR} to at most {retrieval_candidates}."
        )
    return Funnel(retrieval_candidates=retrieval_candidates, rerank_top_k=rerank_top_k)


# ── The AWS credential path ───────────────────────────────────────────────────
#
# Milestone 3 added the second implementation of the `DatabaseUrlResolver` seam
# below: the one that reads the RDS master password out of Secrets Manager rather
# than out of the environment. Everything in this section exists to make that
# path behave under three pressures that the environment path never has to
# survive — it talks to the network, it costs money per call, and its input is a
# credential this process is not supposed to print.


# ── WHICH SOURCE IS READ. EXPLICIT, ALWAYS ────────────────────────────────────
#
# `DB_DSN_SOURCE` names the source. It has two documented values and a default:
#
#   environment (default)  read DATABASE_URL from the process environment.
#   aws                    read SSM Parameter Store + AWS Secrets Manager.
#
# ── WHY THERE IS NO "AUTODETECT" VALUE, AND WHY THIS MATTERS MORE THAN IT LOOKS ──
# The obvious design is "if DATABASE_URL is unset, try AWS". It is refused, and
# the reason is the exact failure this repository has already been bitten by
# twice elsewhere: a configuration mistake that does not fail where it was made.
#
# A forgotten `DATABASE_URL` in a container environment is a routine event — the
# variable is set in `docker-compose.yml` for local dev and in an `.env` on a
# laptop, and neither travels to EC2. Under an autodetect rule, that omission
# would not produce "no database". It would produce a successful connection to
# the PRODUCTION RDS instance, at production latency, with production data,
# because the local variable happened to be missing — and the symptom would be
# an authentication failure hours later if the secret were wrong, or nothing at
# all if it were right. Silently doing something dangerous is the failure mode;
# the loud stop is the fix. So the flag is required, and spelling it wrong is
# also a loud stop.
#
# The ORDER below is the other half of the rule and is the reverse of the
# natural one. `DATABASE_URL` is consulted FIRST and wins even when
# `DB_DSN_SOURCE=aws` is set, so local behaviour is byte-for-byte unchanged and a
# laptop can never reach AWS by accident — including in a shell that still has
# the flag exported from last week's experiment.
DB_DSN_SOURCE_ENV_VAR = "DB_DSN_SOURCE"

#: Read `DATABASE_URL` from the environment. The default, and the value every
#: local and container deployment uses today.
DB_DSN_SOURCE_ENVIRONMENT = "environment"

#: Read the host and port from SSM Parameter Store and the master credential
#: from Secrets Manager, through the EC2 instance role.
DB_DSN_SOURCE_AWS = "aws"

# Every accepted value of DB_DSN_SOURCE, for the message below. One tuple so the
# error and the accepted set cannot drift apart.
DB_DSN_SOURCE_VALUES = (DB_DSN_SOURCE_ENVIRONMENT, DB_DSN_SOURCE_AWS)


# ── WHERE THE THREE SSM PARAMETERS LIVE ──────────────────────────────────────
#
# These three paths mirror `aws_ssm_parameter.app_core`, `app_db_port` and
# `app_db_secret_arn` in `infra/iam.tf`, which build them from `var.project_name`
# and `var.environment`. The deployed values are, literally:
#
#     /lemondrop/dev/db/host
#     /lemondrop/dev/db/port
#     /lemondrop/dev/db/secret-arn
#
# iam.tf writes a long comment about how those names have already been
# mis-applied twice (once without the leading slash, once with a trailing one).
# Read it before touching anything below.
#
# The prefix is an environment variable with the deployed value as its default
# rather than a literal, for one reason: the "dev" in the path follows
# `var.environment`, and hardcoding it here would silently point a `prod`
# deployment at a parameter that does not exist — a wrong-database failure of the
# same family as the one this whole section exists to prevent. A caller who sets
# nothing gets exactly what is deployed today.
DB_SSM_PARAMETER_PREFIX_ENV_VAR = "DB_SSM_PARAMETER_PREFIX"
DEFAULT_DB_SSM_PARAMETER_PREFIX = "/lemondrop/dev/db"

# The three leaves. Named rather than concatenated inline so that every error
# message can name the exact parameter it failed on, and so the three strings
# appear once each in the whole codebase.
DB_SSM_HOST_LEAF = "host"
DB_SSM_PORT_LEAF = "port"
DB_SSM_SECRET_ARN_LEAF = "secret-arn"

# The database to connect to, which is NEITHER in SSM nor in the secret by this
# module's choice. See the long note on the secret's ignored fields below.
DB_NAME_ENV_VAR = "DB_NAME"
DEFAULT_DB_NAME = "lemondrop"


# ── REGION ────────────────────────────────────────────────────────────────────
#
# `AWS_REGION` then `AWS_DEFAULT_REGION`, in that order — the same order the AWS
# tooling itself uses, so a shell that sets either one behaves identically here
# and on the CLI.
#
# ── WHY THERE IS NO DEFAULT REGION ────────────────────────────────────────────
# The tempting default is the region this stack was deployed into. It is refused
# for the same reason every other default in this module is: a default here is
# not a fallback, it is a CLAIM. Resolving against `eu-west-1` when the instance
# actually lives elsewhere produces `InvalidSignatureException` or a DNS failure
# whose message names a region the operator never configured — a failure that
# reads like an IAM problem and sends them to look at the role instead of at the
# answer. Failing on the missing variable costs one line in the task definition;
# guessing costs an afternoon.
AWS_REGION_ENV_VAR = "AWS_REGION"
AWS_DEFAULT_REGION_ENV_VAR = "AWS_DEFAULT_REGION"

# The IAM actions each step needs, quoted into the error messages. Named here so
# that the operator's next move — "check the role's policy" — is spelled out in
# the one place that already knows the answer, and so a policy change is a change
# to a constant rather than to five f-strings.
AWS_SSM_GET_PARAMETER_ACTION = "ssm:GetParameter"
AWS_SECRETS_GET_SECRET_VALUE_ACTION = "secretsmanager:GetSecretValue"


# ── TIMEOUTS ──────────────────────────────────────────────────────────────────
#
# Named for what they bound, in the same spirit as `main.py`'s split between a
# probe budget and a work budget: these are three different questions and
# collapsing them into one number would hide which one had run out.
#
# TCP/TLS connect to the AWS API endpoint. An EC2 instance with no egress route
# blackholes this rather than refusing it, so without an explicit bound botocore
# sits in `connect()` until the OS gives up — which on Linux is minutes.
AWS_CONNECT_TIMEOUT_SECONDS = 3.0

# Waiting for a response to ONE AWS API call, after the connection is up.
# Secrets Manager and SSM are both a single round trip to a regional endpoint
# inside AWS; the normal answer is tens of milliseconds. Five seconds is an
# order of magnitude of headroom over that, which is what makes it a bound on
# the pathological case rather than on the ordinary one.
AWS_READ_TIMEOUT_SECONDS = 5.0

# botocore's retry ceiling per API call. 2 rather than botocore's default of 3:
# a retry after a throttling response is genuinely worth having, and a THIRD
# attempt against a `t3.micro` that is already the bottleneck is where a
# configuration problem becomes a startup problem. The worst case for one call
# is therefore `AWS_MAX_ATTEMPTS * (AWS_CONNECT_TIMEOUT_SECONDS +
# AWS_READ_TIMEOUT_SECONDS)` = 16s.
AWS_MAX_ATTEMPTS = 2

# ── THE OVERALL BUDGET, AND WHAT IT ACTUALLY GUARANTEES ───────────────────────
# This bounds the WHOLE resolution: three SSM reads, one secret read, and the
# parsing between them. It is enforced by `_Deadline`, which is consulted before
# every AWS call and which clamps each call's timeouts to the time still
# remaining.
#
# Stated honestly, because "bounded" is a claim: the deadline is checked BEFORE
# a call, not during one. So at most ONE call can begin with a full 16s of
# retry worst case; every call after it is clamped to whatever is left, and a
# call that would start with nothing left is refused without being made. The
# total is therefore bounded by this budget plus one call's worst case — not by
# this budget alone. Given that the ordinary case finishes in well under a
# second, and that this runs once per process, that is the right trade: a hard
# bound needs a watchdog thread, and a watchdog thread guarding four blocking
# calls that each have their own timeouts is more machinery than the failure it
# prevents.
AWS_RESOLVE_BUDGET_SECONDS = 15.0


# The driver the DSN is built for. Named rather than written into the URL twice,
# because `db.py` already assumes an asyncpg DSN and a scheme typo would produce
# a confusing driver error from a mile away.
POSTGRES_ASYNCPG_DRIVER = "postgresql+asyncpg"


class _Deadline:
    """A wall-clock budget for one resolution, consulted before every AWS call.

    `time.monotonic()` rather than `time.time()` on purpose: this is a
    DURATION, and a duration measured against the wall clock is wrong by exactly
    however long NTP stepped the clock during startup — including backwards, in
    which case a deadline would appear to have hours left and would never fire.

    Never raises on its own. `check` raises so the caller can name the step that
    ran out; `remaining` returns a number so the client can clamp its timeouts.
    """

    __slots__ = ("_expires_at",)

    def __init__(self, budget_seconds: float) -> None:
        self._expires_at = time.monotonic() + budget_seconds

    def remaining(self) -> float:
        """Seconds left. Zero once the budget is spent, never negative."""
        return max(0.0, self._expires_at - time.monotonic())

    def check(self, step: str) -> float:
        """Return the seconds left, or raise naming `step` if there are none.

        The step name is a constant written by the caller — never a value read
        from AWS — so nothing a remote service said can reach this message.
        """
        remaining = self.remaining()
        if remaining <= 0.0:
            raise RuntimeError(
                f"resolving the database DSN from AWS ran out of its "
                f"{AWS_RESOLVE_BUDGET_SECONDS:g}s budget before it could {step}. "
                "Something is making the AWS API very slow to answer from this "
                "host: an egress problem that blackholes rather than refuses, or a "
                "region endpoint that is not reachable from this subnet. This is "
                "reported as the database being unavailable rather than raised out "
                "of startup, so the process is up and /health/ready is answering "
                "503 while you look."
            )
        return remaining


def _boto3_client(service_name: str, *, region_name: str, config: Any) -> Any:
    """Construct one boto3 client. THE ONLY PLACE boto3 IS TOUCHED.

    ── WHY THIS EXISTS AS ITS OWN FUNCTION ─────────────────────────────────────
    Three reasons, in increasing order of how much they matter.

    1. It is the boundary. Everything above it in this section — source
       selection, JSON parsing, field validation, URL construction, every error
       message — is REAL logic that the test suite exercises directly. This one
       function is the entire surface the tests replace, which is what lets the
       tests prove the resolver works without a network, an AWS account, or a
       credential anywhere in sight.
    2. The import is LAZY, inside the function. boto3 is 16MB of botocore's JSON
       service models and pulling it in costs real import time on a path that a
       local developer takes every single day and that never touches AWS. So
       `import app.config` stays boto3-free, `db.py` stays boto3-free, and the
       dependency is paid only by the one deployment that asked for it.
    3. No credentials are passed. There is no `aws_access_key_id` argument here
       and there must never be one. Omitting them entirely puts boto3 on its
       default provider chain, which is the ONLY correct arrangement for this
       service: on EC2 that chain ends at the instance profile, whose temporary
       credentials rotate automatically and expire on their own. Building a
       credential object out of environment variables by hand — the alternative
       that looks tidier — is the pattern that leaks credentials into subprocesses
       (they inherit the environment), into crash reports (they read it), and
       into every log line that dumps `os.environ`.
    """
    import boto3  # noqa: PLC0415 — deliberately local; see point 2 above.

    return boto3.client(service_name, region_name=region_name, config=config)


def _aws_error_code(exc: BaseException) -> str:
    """The AWS error code for an exception, or its class name.

    botocore reports service errors as `ClientError`, whose `.response` carries
    `Error.Code` (`AccessDeniedException`, `ParameterNotFound`, …) and
    `Error.Message`. Only the CODE is read, never the message: the code is the
    stable, greppable thing an operator can search IAM's error docs for, and the
    message is free text that varies by service, by version and by SDK language.

    The class name is the fallback for everything else — connection errors,
    timeouts, DNS failures — for the same reason `main.py`'s `_probe` prefers
    `type(exc).__name__`: it is stable where the message is not.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            code = error.get("Code")
            if code:
                return str(code)
    return type(exc).__name__


def _aws_client_config(remaining: float) -> Any:
    """botocore `Config` for one call, with its timeouts clamped to `remaining`.

    Clamping rather than using the constants directly is what makes
    `AWS_RESOLVE_BUDGET_SECONDS` a bound on the resolution rather than a comment
    about it. Without the clamp, the fourth call in a slow resolution would still
    be allowed a full `AWS_READ_TIMEOUT_SECONDS` on top of whatever budget had
    already been spent, and the total would be the sum of four independent
    worst cases instead of something an operator can reason about.

    botocore is imported here rather than at module scope for the same reason
    `_boto3_client` does it there, and it is only reached when the AWS path is
    actually taken.
    """
    from botocore.config import Config  # noqa: PLC0415 — see `_boto3_client`.

    return Config(
        connect_timeout=min(AWS_CONNECT_TIMEOUT_SECONDS, remaining),
        read_timeout=min(AWS_READ_TIMEOUT_SECONDS, remaining),
        retries={"max_attempts": AWS_MAX_ATTEMPTS, "mode": "standard"},
    )


def _ssm_parameter_path(leaf: str) -> str:
    """The full SSM path for one leaf, from the configured prefix.

    Rstrip'd of a trailing slash because iam.tf records that a trailing slash is
    a `ValidationException` at apply time, and a path that cannot be deployed
    should not be readable by the process that depends on it either.
    """
    prefix = os.environ.get(
        DB_SSM_PARAMETER_PREFIX_ENV_VAR, DEFAULT_DB_SSM_PARAMETER_PREFIX
    ).strip()
    return f"{prefix.rstrip('/')}/{leaf}"


def _aws_region() -> str:
    """The region to talk to, from the environment, or raise naming the variable.

    See the note on `AWS_REGION_ENV_VAR` for why there is no default. The error
    names BOTH variables because either one satisfies the read, and an operator
    told only about `AWS_DEFAULT_REGION` on a host that uses `AWS_REGION` would
    conclude the problem was the instance role.
    """
    for name in (AWS_REGION_ENV_VAR, AWS_DEFAULT_REGION_ENV_VAR):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    raise RuntimeError(
        f"{DB_DSN_SOURCE_ENV_VAR}={DB_DSN_SOURCE_AWS} was requested but neither "
        f"{AWS_REGION_ENV_VAR} nor {AWS_DEFAULT_REGION_ENV_VAR} is set.\n"
        "\n"
        "There is deliberately no default region. Guessing one does not fall back "
        "to a working configuration, it produces an AWS error naming a region "
        "this deployment never used — which reads like an IAM problem and sends "
        "you to check the instance role instead of the environment.\n"
        "\n"
        f"Set {AWS_REGION_ENV_VAR} to the region the RDS instance is in, or set "
        f"{DB_DSN_SOURCE_ENV_VAR} back to '{DB_DSN_SOURCE_ENVIRONMENT}' and supply "
        f"{DATABASE_URL_ENV_VAR} instead."
    )


def _read_ssm_parameter(client: Any, parameter_name: str) -> str:
    """Read one SSM String parameter, or raise naming the parameter and the action.

    `WithDecryption=False` explicitly rather than left off: these three
    parameters hold a hostname, a port and an ARN, none of which are SecureString,
    and saying so in the call means the request cannot decrypt something by
    accident if the parameter is ever retyped.

    Every failure message names the FAILING PARAMETER and the IAM ACTION, because
    the operator's next move after any of them is "check the role's policy" and
    "which parameter?" is the first question they have to answer. A message that
    said only "AccessDeniedException" would send them to the IAM console with no
    idea which of three statements to look at.

    `from None` on every branch, for the reason this module already does it
    everywhere else: a chained botocore exception renders its own traceback, and
    botocore exception text is not something this module controls.
    """
    try:
        response = client.get_parameter(Name=parameter_name, WithDecryption=False)
    except Exception as exc:  # noqa: BLE001 — every botocore failure mode
        code = _aws_error_code(exc)
        # ParameterNotFound is separated from the rest because it is not an IAM
        # problem at all, and telling an operator to check their policy when the
        # parameter was never deployed sends them to the wrong console entirely.
        hint = (
            "The parameter does not exist. Check whether it was deployed — "
            "`terraform apply` in infra/ creates it only when "
            "var.enable_managed_database is true."
            if code == "ParameterNotFound"
            else (
                f"The instance role needs {AWS_SSM_GET_PARAMETER_ACTION} on this "
                "parameter. Check the role's inline policy in infra/iam.tf and, if "
                "it has not been applied, whether the IAM changes are deployed at "
                "all — unapplied policies are the most likely cause here."
            )
        )
        raise RuntimeError(
            f"reading the SSM parameter {parameter_name} failed: {code}.\n{hint}"
        ) from None

    try:
        value = response["Parameter"]["Value"]
    except (KeyError, TypeError, IndexError):
        raise RuntimeError(
            f"the SSM parameter {parameter_name} was read but the response carried "
            "no Parameter.Value. The parameter exists and this role can read it, so "
            "the problem is the parameter's TYPE or the shape of the response — not "
            "the policy. The three parameters this application reads must all be "
            "type String."
        ) from None

    return str(value)


def _read_secret_credentials(client: Any, secret_arn: str) -> tuple[str, str]:
    """Return `(username, password)` from an RDS-managed secret, or raise safely.

    ── THE SHAPE ───────────────────────────────────────────────────────────────
    A secret created by RDS `manage_master_user_password` holds a JSON object
    with (among others) `username` and `password`. That is where the master
    password LIVES: with `manage_master_user_password = true` on `aws_db_instance`
    (see infra/database.tf) the password never appears in Terraform at all, not
    even in state, and the only copy is in Secrets Manager.

    The `username` it carries is the RDS MASTER username — which is the account
    this application connects as, and which `Settings` then refuses to accept if
    it is empty. That is the intended coupling: one account, one credential, no
    second variable that could disagree with the secret about who the user is.

    ── WHAT IS NEVER DONE HERE, AND WHY ────────────────────────────────────────
    The response is never logged, never `%r`-formatted, never attached to an
    exception, and the password is never passed to `str()`, `repr()` or an f-string.
    A `logger.debug("secret: %s", body)` is the single line that turns this
    function into a credential leak, and it is a line that reads as helpful while
    debugging a parse failure. So every message below is written from constants —
    field names, the ARN, a shape description — and `from None` keeps botocore's
    and json's own tracebacks from rendering underneath.

    A non-string or empty field is reported as a MISSING FIELD, naming which one.
    That is what the operator needs: "the secret has no `password`" points at
    `manage_master_user_password`, "malformed secret" points at nothing.
    """
    try:
        response = client.get_secret_value(SecretId=secret_arn)
    except Exception as exc:  # noqa: BLE001 — every botocore failure mode
        raise RuntimeError(
            f"reading the secret {secret_arn} failed: {_aws_error_code(exc)}.\n"
            f"The instance role needs {AWS_SECRETS_GET_SECRET_VALUE_ACTION} on this "
            "secret. Check the role's policy in infra/iam.tf and, if it has not been "
            "applied, whether the IAM changes are deployed at all — unapplied "
            "policies are the most likely cause here."
        ) from None

    try:
        secret_string = response["SecretString"]
    except (KeyError, TypeError):
        raise RuntimeError(
            f"the secret {secret_arn} was read but the response carried no "
            "SecretString. A secret with only SecretBinary cannot be read by this "
            "application; the RDS-managed secret this one should be created with "
            "manage_master_user_password stores the credential as a JSON string."
        ) from None

    try:
        payload = json.loads(secret_string)
    except (TypeError, ValueError):
        # Deliberately NOT `from exc`. json's own DecodeError renders a fragment
        # of what it failed on, and what it failed on here is a credential.
        raise RuntimeError(
            f"the secret {secret_arn} did not contain JSON this application can "
            "read. A secret created by RDS manage_master_user_password is a JSON "
            "object carrying `username` and `password`; anything else means either "
            "the wrong secret was published to this parameter or something else "
            "wrote to it. The value is not reproduced here because it is a "
            "credential."
        ) from None

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"the secret {secret_arn} contained JSON that is not an object (it is "
            f"a {type(payload).__name__}). This application expects a JSON object "
            "with `username` and `password`. The value is not reproduced here "
            "because it is a credential."
        ) from None

    # The field the operator has to go and fix, named. Checked as "absent, not a
    # string, or blank" in one pass because all three produce the same next move
    # and distinguishing them would be guessing: a field that is `null`, a number,
    # or `""` is as unusable as one that was never written, and the fix is the
    # same — look at how the secret was created.
    #
    # The blank test is `.strip()` and not `not value`, and that is the whole
    # point of it. A whitespace-only password is TRUTHY, so an `if not value`
    # check accepts it and hands a blank credential to the driver — which then
    # produces a `fe_sendauth: no password supplied` error at connection time,
    # several steps from the secret that was wrong. Same rule as `main.py`'s
    # `NonBlankText`, applied for the same reason. The value is NOT stripped:
    # only its emptiness is tested, because a real password may legitimately
    # begin or end with a space and rewriting it would break a working
    # credential.
    resolved: dict[str, str] = {}
    for field in ("username", "password"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(
                f"the secret {secret_arn} has no usable `{field}` field. An RDS "
                "secret created by manage_master_user_password always carries both "
                "`username` and `password` as non-empty strings, so this means the "
                "secret is not the one this parameter points at, or it has been "
                "rewritten. No part of the secret is reproduced here."
            )
        resolved[field] = value

    return resolved["username"], resolved["password"]


@functools.lru_cache(maxsize=1)
def _resolve_database_url_from_aws_once() -> str:
    """Resolve the DSN from AWS, once per process. Cached; see the caller.

    `functools.lru_cache` rather than a module global so that "has this already
    been fetched" is a property of a named object that a test can clear with
    `_resolve_database_url_from_aws_once.cache_clear()`, instead of a variable
    that has to be reassigned from the outside.

    The arguments are none, which is why the cache is `maxsize=1` rather than a
    cache keyed by anything: within one process the environment is read once and
    the answer is the answer.
    """
    region = _aws_region()
    deadline = _Deadline(AWS_RESOLVE_BUDGET_SECONDS)
    host_parameter = _ssm_parameter_path(DB_SSM_HOST_LEAF)
    port_parameter = _ssm_parameter_path(DB_SSM_PORT_LEAF)
    secret_parameter = _ssm_parameter_path(DB_SSM_SECRET_ARN_LEAF)

    def _client(service_name: str, step: str) -> Any:
        """Build one client for `step`, refusing if the budget is already gone."""
        remaining = deadline.check(step)
        return _boto3_client(
            service_name,
            region_name=region,
            config=_aws_client_config(remaining),
        )

    # ── Three SSM reads ───────────────────────────────────────────────────────
    # `ssm` and `secretsmanager` are constructed once and reused for their calls,
    # but the TIME OUTS are clamped per fetch: constructing a client is local work
    # and costs no AWS calls, while a stale read timeout on the last fetch is
    # exactly the case the overall budget exists to prevent.
    ssm = _client("ssm", "read the first SSM parameter")
    host = _read_ssm_parameter(ssm, host_parameter).strip()

    ssm = _client("ssm", "read the second SSM parameter")
    port_text = _read_ssm_parameter(ssm, port_parameter).strip()

    ssm = _client("ssm", "read the third SSM parameter")
    secret_arn = _read_ssm_parameter(ssm, secret_parameter).strip()

    # ── One Secrets Manager read ──────────────────────────────────────────────
    secrets = _client("secretsmanager", "read the database secret")
    username, password = _read_secret_credentials(secrets, secret_arn)

    try:
        port = int(port_text)
    except ValueError:
        # The port is not a credential, so quoting it is safe — and quoting it is
        # the whole value of the message, because the operator's next action is to
        # look at what that parameter actually contains.
        raise RuntimeError(
            f"the SSM parameter {port_parameter} contains {port_text!r}, which is not "
            "a port number. It is published by infra/iam.tf as tostring(local.db_port) "
            "and must be type String; check the parameter's value and type."
        ) from None

    if not host:
        raise RuntimeError(
            f"the SSM parameter {host_parameter} is set but empty, so there is no "
            "host to connect to. Check what that parameter actually contains."
        )

    # ── Assemble the DSN ──────────────────────────────────────────────────────
    # `URL.create()`, NEVER string concatenation. This is a correctness
    # requirement, not a style preference, and the reason is that an RDS master
    # password is machine-generated from a password policy that does not restrict
    # punctuation — so it can contain any of `@ : / ? # [ ] % & =` and more.
    #
    # Measured on this stack's SQLAlchemy 2.0.54, concatenating a password
    # containing `@ : / ? %` does not merely produce an ugly DSN: it produces one
    # that no longer parses at all (`ValueError: invalid literal for int() with
    # base 10: 'w'` from the port parser, because `user:pass@ss` left the host
    # reading as `ss`). And a password containing only `@` parses happily into
    # the WRONG HOST — a DSN that connects somewhere, fails to authenticate, and
    # produces an authentication error hours later that points at the RDS user
    # rather than at this line. `URL.create` percent-encodes every component, so
    # the rendered string round-trips back to the original characters.
    url = URL.create(
        POSTGRES_ASYNCPG_DRIVER,
        username=username,
        password=password,
        host=host,
        port=port,
        database=os.environ.get(DB_NAME_ENV_VAR, DEFAULT_DB_NAME).strip()
        or DEFAULT_DB_NAME,
    )
    dsn = url.render_as_string(hide_password=False)

    # The one log line this path produces. The host is the sanctioned loggable
    # component (see `Settings.database_host` for why it is the only one), and the
    # count is here so an operator reading a log can tell a cached resolution from
    # a repeated one without counting lines themselves. No DSN, no password, no
    # secret body, no ARN: the ARN is an identifier rather than a credential, but
    # the host already says which database this is, and there is no second job
    # this line has to do.
    logger.info(
        "database DSN resolved from AWS (region %s, host %s, secret #1)",
        region,
        host,
    )
    return dsn


def resolve_database_url_from_aws() -> str:
    """Return the DSN built from SSM + Secrets Manager. Cached for the process.

    ── WHY THE RESULT IS CACHED, EXACTLY ONCE, FOR THE LIFE OF THE PROCESS ─────
    Two reasons, both of them real numbers rather than tidiness.

    * COST. Secrets Manager charges per API call: $0.05 per 10,000 calls in
      eu-west-1, and the same per-call rate elsewhere. One fetch per process is
      one call. Fetching per REQUEST turns a read-only search service into a
      metered API line item: at even 20 requests/second sustained, one process
      would make 1.728 million calls a day and cost about $86 a month. The same
      service fetching once at startup costs $0.00. The SSM reads are free, but
      they have the same round-trip cost and the same shape, so they are cached
      with them rather than being left as an inconsistency.

    * LATENCY. A Secrets Manager round trip is tens of milliseconds from inside
      the same region. Doing that on the request path adds it to EVERY search,
      which is the one thing this service is supposed to be fast at. The engine's
      connection pool is the natural lifetime for this: the pool is built in the
      FastAPI lifespan and disposed in its shutdown (see `db.startup`), so the
      credential and the pool are created and destroyed together, and there is no
      cache to invalidate and no rotation that this code silently misses.

    Called from `resolve_database_url`, which is called from `get_settings`,
    which `db.startup` calls exactly once. The cache is a belt-and-braces
    guarantee on top of that, and it is what makes "exactly once" a property of
    this function rather than a property of a call graph nobody is holding still.

    CACHE CLEARING IS A TEST CONCERN ONLY. There is deliberately no refresh, no
    TTL and no rotation handling: a rotated secret is picked up the next time the
    process starts, which is the correct behaviour for a long-lived pool and is
    the one thing that does not need a reaper.
    """
    return _resolve_database_url_from_aws_once()


def resolve_database_url() -> str:
    """Return the DSN, from the source `DB_DSN_SOURCE` NAMES. Never infers.

    Three branches, in this order, and the order is the policy:

    1. `DATABASE_URL` set and non-blank → return it, unchanged, and do not
       construct a boto3 client, do not read a region and do not touch the
       network. This is what makes local development byte-for-byte identical to
       what it was before this function existed, and it is why a laptop can never
       reach AWS even by accident — even with `DB_DSN_SOURCE=aws` still exported
       in the shell from an earlier experiment.
    2. Otherwise, `DB_DSN_SOURCE` says `aws` → resolve from AWS.
    3. Otherwise → the environment reader's existing error, unchanged, which
       names `DATABASE_URL` and explains that there is deliberately no default.

    A `DB_DSN_SOURCE` set to anything else is an ERROR rather than a fallback.
    Falling back would make a typo indistinguishable from "not configured", and
    the operator's diagnosis of the first is completely different from the
    second.

    `resolve_database_url_from_environment` is still called on branch 3 rather
    than its error being re-typed here, so the missing-`DATABASE_URL` message has
    exactly one home and cannot drift between the two paths.
    """
    raw = os.environ.get(DATABASE_URL_ENV_VAR)
    if raw is not None and raw.strip():
        return raw.strip()

    requested = os.environ.get(DB_DSN_SOURCE_ENV_VAR, DB_DSN_SOURCE_ENVIRONMENT)
    requested = requested.strip().lower()

    if requested == DB_DSN_SOURCE_ENVIRONMENT:
        # Not a tautology. It is the branch that guarantees an UNSET
        # DB_DSN_SOURCE and an explicit `DB_DSN_SOURCE=environment` take the same
        # path, so the default is not a separate behaviour that can diverge from
        # the named one.
        return resolve_database_url_from_environment()

    if requested == DB_DSN_SOURCE_AWS:
        return resolve_database_url_from_aws()

    raise RuntimeError(
        f"{DB_DSN_SOURCE_ENV_VAR} is {requested!r}, which is not a source this "
        f"application knows. It must be one of {', '.join(DB_DSN_SOURCE_VALUES)}.\n"
        "\n"
        "There is no fallback, because a fallback here would make a typo look "
        "exactly like a missing configuration — and those two have nothing in "
        "common when the operator is reading the message.\n"
        "\n"
        f"Use {DB_DSN_SOURCE_ENVIRONMENT!r} for the local devdb (with "
        f"{DATABASE_URL_ENV_VAR} set), or {DB_DSN_SOURCE_AWS!r} on the EC2 host."
    )


class DatabaseUrlResolver(Protocol):
    """The seam each credential source plugs into.

    One shape, two implementations: `resolve_database_url_from_environment` (the
    local and container path, unchanged since the database phase) and
    `resolve_database_url_from_aws` (SSM Parameter Store plus Secrets Manager,
    through the EC2 instance role). `resolve_database_url` chooses between them
    on an explicitly named flag and binds to `DATABASE_URL_RESOLVER`.

    ── WHY THIS EXISTS AND WHAT IS DELIBERATELY NOT HERE ──────────────────────
    The AWS path reads the host and port from SSM
    (`/lemondrop/dev/db/{host,port}`), a secret ARN from the same prefix, the
    master credential from Secrets Manager, assembles a DSN, and returns it —
    with the credential existing only in memory for the life of the process.

    What the seam guarantees is that this touches ONE function:
    `DATABASE_URL_RESOLVER`. `db.py` never learns where the DSN came from, never
    fetches a credential, and never imports boto3. If that ever stops being true,
    this seam has been bypassed and the next credential source will leak into the
    database layer.

    ── WHAT IS STILL UNVERIFIED, AND IS NOT FIXED BY THE SEAM ──────────────────
    The `feat/aws-infrastructure` IAM changes are NOT applied, so the deployed
    permissions for SSM and for Secrets Manager are unverified and assumed to be
    nothing. Writing the path was still the right call — the alternative is that
    the first thing anyone learns about the instance role is an AccessDenied at
    3am — but every error message below is written to NAME the action that was
    denied, precisely because the first real run may well fail here and the
    message has to be the useful one.
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


# The single, named place a credential source is bound. Today it is the SELECTOR
# `resolve_database_url`, not one of the two resolvers: `get_settings` takes a
# `DatabaseUrlResolver` and must not have to know that there is more than one,
# and the choice between them is a configuration decision (`DB_DSN_SOURCE`), not
# a fact about the interface. Rebinding this to `resolve_database_url_from_aws`
# unconditionally — in a test, or in a future single-target deployment — is still
# a one-line change and is exactly what the seam exists to allow.
DATABASE_URL_RESOLVER: DatabaseUrlResolver = resolve_database_url


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

    # ── The retrieval funnel ───────────────────────────────────────────────────
    # Stage 1 candidate count and stage 2 result count.
    #
    # Both carry the documented default as their FIELD default, and both are still
    # passed explicitly by `get_settings()`, which is what reads the environment.
    # The field default is not redundant — it is what lets a caller construct a
    # `Settings` with only the values it cares about, which is how
    # `api/tests/test_db.py` exercises the DSN validators without standing up a
    # retrieval configuration to do it. A field with no default would make every
    # such construction fail for a reason that has nothing to do with the DSN,
    # and the fix would have been to edit a test about the database.
    #
    # They are validated by constructing a `Funnel` rather than by re-stating the
    # rules: one definition of "a coherent funnel", in `Funnel`/`_build_funnel`,
    # reached from both places that need it. Two hand-written copies of the same
    # three comparisons would be free to disagree, and the disagreement would
    # only show up as a search that returns a different number of results than
    # the configuration claims.
    retrieval_candidates: int = DEFAULT_RETRIEVAL_CANDIDATES
    rerank_top_k: int = DEFAULT_RERANK_TOP_K

    @model_validator(mode="after")
    def _funnel_must_be_coherent(self) -> Settings:
        """Run the funnel's own validation over this instance's two numbers.

        `_build_funnel` raises naming both values, which is the message the
        operator needs, and it is deliberately the SAME function
        `funnel_from_environment` calls — so a `.env` that is rejected at
        startup is rejected with the words that explain it, not a pydantic
        field error that names only `rerank_top_k`.
        """
        _build_funnel(self.retrieval_candidates, self.rerank_top_k)
        return self

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
    funnel = funnel_from_environment()

    return Settings(
        # The one line in the codebase that reads a credential. Everything else
        # receives it already wrapped in a SecretStr.
        database_url=SecretStr(source()),
        # Defaulted rather than required: the width is a property of the model
        # the embedder runs, and the documented value is the correct one. But it
        # is still passed through the validator above, so an explicit wrong value
        # is rejected rather than quietly accepted.
        embedding_dim=int(os.environ.get(EMBEDDING_DIM_ENV_VAR, SCHEMA_EMBEDDING_DIM)),
        # Validated as a pair by `Settings._funnel_must_be_coherent`. The values
        # come from `funnel_from_environment()` rather than from two more
        # `os.environ.get` calls here, so the defaults live in one place and a
        # test that patches one variable exercises the same read the route does.
        retrieval_candidates=funnel.retrieval_candidates,
        rerank_top_k=funnel.rerank_top_k,
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