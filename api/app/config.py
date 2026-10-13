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

Everything else in here is either a named constant with a stated reason, a small
helper that exists to keep a credential out of a log line, or the retrieval
funnel — ``QUERY_PREFIX``, ``Funnel`` and ``funnel_from_environment`` — which is
the one piece of configuration that is about behaviour rather than about
connecting. The bge query prefix is the most dangerous string in this repository
and is defined here precisely so that there is exactly one of it: see the block
above ``QUERY_PREFIX``.
"""

from __future__ import annotations

import os
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