"""lemondrop API — the orchestrator in front of the two inference workers.

Architecture in one paragraph: `embedder` and `reranker` are stateless llama.cpp
servers that are NOT published to the host. They are reachable only from other
containers on the compose network, by service name. This API is the single door
to the outside world, and its job is to stand in front of them.

Seven routes, in the order they were earned: ``GET /health`` reports the truth
about the two workers beneath it; ``POST /embed`` and ``POST /rerank`` are thin
proxies that actually call them; ``GET /health/live`` and ``GET /health/ready``
came with the database phase, which probes the database as well as the workers.
The sixth was ``POST /documents``, the first route that writes anything. It
embeds a document through the same worker proxy ``/embed`` uses and hands the
vector to ``app/store.py``. The seventh, ``POST /search``, is the first route that
reads one back: it embeds a query, filters by collection in SQL, reranks the
candidates through the existing ``/rerank`` machinery, and returns the top few.

A NOTE ON THE bge QUERY PREFIX, recorded here because it is the single most
misreadable decision in this file. bge-small-en-v1.5 was trained with the fixed
instruction string ``Represent this sentence for searching relevant passages: ``
attached to SEARCH QUERIES ONLY. Documents must never carry it — prefixing a
document corrupts that document's vector for every future retrieval. So
``/embed`` forwards its text BARE, deliberately; so does ``/documents``, which
embeds through ``/embed`` and therefore inherits the same invariant. The prefix
belongs on ``/search``, which now exists and applies it to the query and to
nothing else in that route.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from sqlalchemy.exc import SQLAlchemyError

from app import config, db, store
from app.config import QUERY_PREFIX, SCHEMA_EMBEDDING_DIM

# ── Downstream endpoints ──────────────────────────────────────────────────────
# Read from the environment with compose-network defaults, so the SAME image runs
# unmodified both inside compose (where the defaults resolve) and outside it
# (where EMBEDDER_URL/RERANKER_URL are set to whatever is reachable). Hardcoding
# the URLs in code would make the image unrunnable outside the compose network,
# for no benefit — an env var with a correct default is strictly more flexible
# and costs one line.
#
# These are the compose SERVICE NAMES, not localhost. Service names resolve
# through Docker's embedded DNS on the default network. There is no port
# publishing involved on this path at all: `embedder:8080` is reachable because
# the two containers share a network, not because anything was published to the
# host.
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://embedder:8080")
RERANKER_URL = os.environ.get("RERANKER_URL", "http://reranker:8080")

# Why a timeout, and why it must be short: without one, a probe against a
# container that is up but wedged (or a network that blackholes packets) waits
# forever. A /health endpoint that hangs is worse than one that fails — compose
# waits out its own healthcheck timeout, marks this container unhealthy, and
# restarts a perfectly good process. Five seconds is comfortably longer than a
# local HTTP round trip needs and comfortably shorter than anything a scheduler
# waits for.
PROBE_TIMEOUT_SECONDS = 5.0

# The value returned by a probe on success. A named constant so that the success
# check below is a comparison, never a magic string, and so "ok" cannot drift
# between the value written and the value compared.
_PROBE_OK = "ok"

# ── Model aliases ─────────────────────────────────────────────────────────────
# The workers register their models under an ALIAS, not under a filename. Asking
# llama.cpp for a model by alias is the only portable way to do this: the alias
# is what the server was started with, so a caller never has to know a .gguf
# path. Read from the environment with the value from .env.example as the
# default, mirroring how EMBEDDER_URL/RERANKER_URL are read above: if the env
# var is present it wins, and if the image is run somewhere that does not set it,
# the documented alias still works.
EMBEDDER_MODEL_ALIAS = os.environ.get("EMBEDDER_MODEL_ALIAS", "bge-small-en-v1.5")
RERANKER_MODEL_ALIAS = os.environ.get("RERANKER_MODEL_ALIAS", "bge-reranker-base")

# Why inference needs a MUCH longer budget than the 5s probe above, and why the
# two numbers must not be unified into one constant. They answer different
# questions.
#
# A readiness probe asks "is this thing up right now?" and wants a fast NO — it
# runs every few seconds, for the life of the container, and a probe that times
# out too eagerly reports a false negative on a busy machine, which is worse than
# useless because compose acts on it (marks the container unhealthy, restarts a
# process that was fine).
#
# An inference request asks "do this real piece of work" and its cost scales with
# the work: the reranker scores EVERY document the caller supplied, on a
# CPU-only box, with no GPU to hide behind. Cutting such a request short
# discards real work the worker already did, and the client has no way to tell
# that from the request having failed for no reason.
#
# So the split is deliberate and both numbers are named for what they measure:
# PROBE_TIMEOUT_SECONDS is a readiness budget, INFERENCE_TIMEOUT_SECONDS is a
# work budget.
INFERENCE_TIMEOUT_SECONDS = 120.0

# The largest input the API will forward to an inference worker, in characters.
#
# Derivation: llama.cpp runs with n_ctx_slot = 512 (confirmed in the worker's
# startup log: "n_slots = 4, n_ctx_slot = 512", docker-compose.yml:197-199), so
# any input above 512 tokens is REJECTED by the worker, not truncated. Real BPE
# prose runs about 4 chars/token, not the ~2 chars/token measured on repeated
# 'A' characters, so 512 tokens is about 2048 characters of real prose.
#
# 2048 chars = 512 tokens × 4 chars/token (realistic BPE prose density). It
# exceeds the corpus maximum of 1874 chars (data/corpus.json), so all 40
# verified-good documents remain acceptable
# (docs/verification-milestone-3.md §5.2: 40/40 ingested through POST /documents).
#
# This is a CHARACTER proxy for the worker's 512-TOKEN limit and cannot be
# exact: tokenisation is not a function of character count alone. At realistic
# prose density (~4 chars/token) 2048 chars ≈ 512 tokens and is the ceiling.
# Pathological low-density input — long unbroken character runs at ~2
# chars/token — can still exceed the worker's token limit below 2048 characters
# and will produce an upstream 502. That is a KNOWN residual, not a solved case.
# The n_ctx_slot = 512 evidence source is docker-compose.yml:197-199.
#
# Anything at or below this limit is accepted; anything above is refused at the
# edge with a 422 naming the field, instead of being forwarded to a worker that
# would answer with a permanent, non-retryable 500.
MAX_INFERENCE_INPUT_CHARS = 2048

# The largest search query /search will accept from a caller, in characters.
#
# /search forwards ``QUERY_PREFIX + query`` to the embedder, and
# MAX_INFERENCE_INPUT_CHARS is the cap on what is forwarded TO THE WORKER — the
# prefix is part of that forwarded string, so it consumes part of the caller's
# allowance. With the default 57-character prefix the caller's allowance is
# therefore 1991 characters, and the sum ``len(QUERY_PREFIX) +
# MAX_SEARCH_QUERY_CHARS`` equals the worker budget exactly.
#
# This is exact arithmetic on a known, service-side constant — NOT the "false
# precision over a character proxy" that the /rerank comment below warns about;
# that warning concerns two CALLER-supplied fields whose token interaction is
# unknown, whereas the prefix is a fixed constant this service adds.
MAX_SEARCH_QUERY_CHARS = MAX_INFERENCE_INPUT_CHARS - len(QUERY_PREFIX)
if MAX_SEARCH_QUERY_CHARS < 1:
    raise RuntimeError(
        f"QUERY_PREFIX ({len(QUERY_PREFIX)} chars) is longer than the entire "
        f"inference budget (MAX_INFERENCE_INPUT_CHARS={MAX_INFERENCE_INPUT_CHARS}); "
        "a search query would have no usable allowance"
    )

# Strings a caller must actually provide. Declared here, once, so that the
# rejection rule is written down in a single place and cannot drift between the
# two request bodies below.
#
# Pydantic does the rejecting, which is the point: FastAPI turns a failed
# validation into a 422 with a precise field-level error automatically. The
# hand-rolled alternative — `if not body.text: raise HTTPException(422, ...)` —
# is strictly worse: it produces a coarser error, it lives in the handler where
# it can be forgotten on the day someone adds a field, and it never appears in
# the OpenAPI schema, so /docs would still advertise the field as a plain string
# that accepts anything.
#
# strip_whitespace THEN min_length, in that order, is what makes "   " invalid:
# stripping first turns a whitespace-only string into "", which min_length then
# rejects. min_length alone would accept "   ", and an empty string is not
# something either worker can do anything useful with.
NonBlankText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_INFERENCE_INPUT_CHARS,
    ),
]

# The same rule as ``NonBlankText``, but with the smaller maximum that accounts
# for the bge query prefix that /search adds before forwarding to the worker.
# This type is what makes an over-long query a FastAPI 422 on the field, rather
# than a pydantic.ValidationError raised inside the handler after the prefix has
# been concatenated.
SearchQueryText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_SEARCH_QUERY_CHARS,
    ),
]

# Identifiers (document_id, collection) are never forwarded to an inference
# worker, so they have no worker-imposed token limit and must NOT carry
# max_length. strip_whitespace then min_length=1: a blank identifier is not a
# usable key, but a non-blank identifier of any length is accepted.
NonBlankIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
    ),
]

# The same rule for document entries, minus the stripping. Documents are not
# compared for equality against anything and a reranker scores whatever text it
# is given, so there is no reason to silently rewrite the caller's strings.
#
# A WHITESPACE-ONLY entry IS rejected: it is blank after stripping and would be
# scored as noise, producing a meaningless ranking. The validator below checks
# `not value.strip()` and raises a validation error, but returns the original
# string untouched otherwise — so "  padded  " is accepted verbatim, while "   "
# is refused. The entry is also capped at MAX_INFERENCE_INPUT_CHARS so a rerank
# call never forwards an input the worker would permanently reject.
def _reject_blank_after_strip(value: str) -> str:
    """Reject a string that is blank after stripping, without rewriting it.

    Returns the original value unchanged when it is non-blank. Raises a
    ValueError when `value.strip()` is empty, so whitespace-only entries are
    refused while non-blank caller strings are preserved exactly as given.
    """
    if not value.strip():
        raise ValueError("string must not be blank or whitespace-only")
    return value


NonBlankItem = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_INFERENCE_INPUT_CHARS),
    AfterValidator(_reject_blank_after_strip),
]

# Module logger. Exceptions are logged HERE, server-side, and never returned to
# the caller — see the docstring on _post_upstream.
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Own the database connection pool for exactly the life of the process.

    This is the only place the engine is created, and the reason is in
    ``db.startup``: an AsyncEngine binds its pool to the event loop that exists
    when it is built, so one built at import time is bound to the wrong loop and
    fails much later with "attached to a different loop" or "await wasn't used
    with an Future". Here, the loop that will serve requests is already running,
    and the pool is created inside it and disposed inside it.

    The `finally` is not optional bookkeeping. The shutdown half of a lifespan
    runs even when startup raised, so without it a partially-initialised
    process leaks its connections on the way down; and ``db.close`` is
    deliberately the last thing that happens, so no request is holding a
    connection from a pool that has already been disposed.

    `db.startup()` never raises. An unreachable or unconfigured database is
    logged, recorded on the returned object, and the process serves anyway —
    see that function's docstring for the operational reason. The consequence
    for this file is that ``/health/live`` answers 200 (the process is fine) and
    ``/health/ready`` answers 503 (a request needing the database must not be
    sent here). Both are true simultaneously, which is the point of having two
    endpoints rather than one overloaded one.
    """
    database = await db.startup()
    # On app.state rather than a module global: state is per-application, so two
    # apps in one process (which is what a test harness creates) cannot share a
    # pool bound to the wrong loop. See db.startup's docstring.
    application.state.database = database

    # Arms the pool for vector writes. This is not an optional extra: without it
    # every vector INSERT fails, intermittently, on whichever pooled connection
    # was created before this line ran. `store.prepare_database` explains the
    # mechanism, and `api/tests/test_documents.py` proves both directions.
    #
    # Called here rather than inside `db.startup` so that `db.py` keeps owning
    # only the engine's lifecycle and knows nothing about pgvector. It is
    # deliberately NOT in a `try/except`: a failure to register a codec means
    # the store layer cannot work, and a process that serves 200 from /health
    # while every write fails is worse than one that says so loudly at startup.
    await store.prepare_database(database)

    try:
        yield
    finally:
        await db.close(database)


app = FastAPI(
    title="lemondrop API",
    version="0.1.0",
    description="Orchestrates the embedder and reranker inference workers.",
    lifespan=lifespan,
)


class HealthResponse(BaseModel):
    """Body of GET /health.

    A Pydantic model rather than a bare dict so the response shape is declared
    once, is validated on the way out, and shows up in the generated OpenAPI
    schema that /docs serves.

    The fields are strings, not nested objects or booleans, on purpose. When the
    embedder is down, the caller needs to know WHY, and a boolean can only say
    "no". A short human-readable string — "unreachable: ConnectError" — is what
    makes this endpoint useful for debugging rather than merely boolean.
    """

    # "ok" only when BOTH dependencies answered successfully.
    # "degraded" when either one did not.
    status: str
    # Per-dependency verdict: "ok", or a short description of the failure.
    embedder: str
    reranker: str


async def _probe(url: str, client: httpx.AsyncClient) -> str:
    """Ask one inference service whether it is ready, and report the outcome.

    Returns the string "ok" if the service answered 2xx, otherwise a short
    description of what went wrong. It never raises: a failed probe is a normal,
    expected outcome that this endpoint reports, not an error to propagate. The
    reason for the distinction is that an unhandled exception here would produce
    a 500 with an unhelpful body and would tell the operator nothing about which
    dependency is actually at fault.

    The httpx.AsyncClient is passed in rather than constructed here so that the
    caller owns its lifecycle and both probes share one client — and therefore
    one connection pool.
    """
    try:
        response = await client.get(url)
        # raise_for_status turns a 503 into an exception, which is what we want.
        # The llama.cpp server answers 503 while the model is still loading into
        # memory, so a 503 here genuinely means "not ready yet" and must NOT be
        # reported as a success just because the connection worked.
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # The service answered, but not with success — e.g. 503 while loading.
        return f"unhealthy: HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        # Distinguished from the generic case because "it hung" and "it is not
        # there" have completely different causes and different fixes.
        return f"timeout after {PROBE_TIMEOUT_SECONDS}s"
    except httpx.HTTPError as exc:
        # Everything else: DNS failure, connection refused, network unreachable.
        # The exception CLASS name is included rather than its message because
        # httpx messages vary by version and are not a stable thing to read.
        return f"unreachable: {type(exc).__name__}"

    return _PROBE_OK


@app.get("/health", response_model=HealthResponse, summary="Readiness of the API and its dependencies")
async def health(response: Response) -> HealthResponse:
    """Report whether this API can actually do its job right now.

    Readiness, not liveness. The useful question is not "is the Python process
    running" — a process that is running but whose entire purpose depends on two
    other services cannot serve a single request — but "are both workers ready to
    be called". So this probes the real dependencies rather than returning a
    static OK.

    Returns HTTP 200 when both probes succeed and HTTP 503 when either fails.

    Why 503 and not 200-with-a-sad-body: a health check that returns 200 while
    its dependencies are down is a health check that has stopped working. Every
    consumer of this endpoint — compose's own healthcheck, an orchestrator, a
    load balancer, a person with curl — treats a non-200 as "not ready". 503
    Service Unavailable is precisely that claim, stated in the status line where
    generic tooling will actually look. A body claiming "degraded" behind a 200
    would be correct and completely invisible to anything that is not parsing
    JSON.
    """
    # One client, shared by both probes, closed when this block exits.
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        # Why async and why gather: a request handler in FastAPI runs on a single
        # event loop. If these two probes were issued sequentially with blocking
        # calls, the event loop would sit idle waiting on whichever service
        # happened to be first — the total wait being the SUM of both services'
        # response times. With httpx.AsyncClient under asyncio.gather, both
        # requests are in flight at once and the event loop is free to serve
        # other clients while we wait, so the total wait is the SLOWER of the
        # two. Worst-case probe latency is halved, and the API is not blocked
        # while it waits.
        #
        # gather() also does not fail fast by default: if the embedder probe
        # raises, gather still collects the reranker's result. That is what we
        # want, since we want a report on BOTH dependencies rather than only on
        # whichever one happened to break first. (Either way _probe swallows
        # exceptions, but relying on one guard is clearer than two.)
        embedder_state, reranker_state = await asyncio.gather(
            _probe(EMBEDDER_URL, client),
            _probe(RERANKER_URL, client),
        )

    # "ok" requires BOTH. One healthy dependency out of two is not a healthy
    # service — the funnel needs both stages to return a result.
    is_ok = embedder_state == _PROBE_OK and reranker_state == _PROBE_OK
    overall = _PROBE_OK if is_ok else "degraded"

    if not is_ok:
        # Set on the injected Response, which FastAPI uses as the status code for
        # the response it is about to serialise.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(status=overall, embedder=embedder_state, reranker=reranker_state)


# ── Liveness and readiness ────────────────────────────────────────────────────
# Two endpoints, and the reason there are two rather than one overloaded one is
# the difference between the questions they answer:
#
#   LIVENESS  "is this process irrecoverably broken?"     → the orchestrator's
#            restart decision.
#   READINESS "can this process serve a request right now?" → the load
#            balancer's routing decision.
#
# They point in OPPOSITE directions on dependencies, and that is not a subtlety
# — it is the entire reason the pair exists. Liveness deliberately ignores every
# external system; readiness depends on all of them.


class LivenessResponse(BaseModel):
    """Body of GET /health/live.

    A NEW model rather than a reuse of `HealthResponse`, and `HealthResponse`
    itself is untouched. Reusing it would have meant a liveness endpoint whose
    response claims to describe the embedder and the reranker while containing
    no information about either — a body that is actively misleading about what
    it measured, in the one endpoint whose whole contract is that it measures
    nothing. `HealthResponse`'s two dependency fields stay exactly as they were,
    because `/health` is referenced by the compose healthcheck, by
    `scripts/boot.sh` and by the Milestone 2 ALB target group, and its shape is
    a live production contract.
    """

    # Always the success word, on every call, unconditionally. A single field
    # because a body listing dependencies here would be a lie.
    status: str


class ReadinessResponse(BaseModel):
    """Body of GET /health/ready.

    Deliberately the same SHAPE as `HealthResponse` — same field names, same
    string-valued verdicts, same 200/503 semantics — with one field added:
    `database`. Matching the existing shape means an operator who already reads
    `/health` reads this one without learning anything, and a scraper written
    against one works against the other. The two are separate models rather
    than one model with optional fields because the shapes differ in what they
    promise: `HealthResponse` promises to describe the workers and says nothing
    about the database, and a model with optional fields would let a future
    edit quietly turn that promise into a lie.
    """

    # "ok" only when the database AND both workers answered successfully.
    # "degraded" when any of them did not.
    status: str
    # Per-dependency verdict: "ok", or a short description of the failure. All
    # three are strings rather than booleans for the reason given on
    # `HealthResponse`: when a dependency is down, the caller needs to know WHY,
    # and a boolean can only say "no".
    embedder: str
    reranker: str
    # The database verdict. `db.PingResult.detail` is already short,
    # single-line and credential-free by construction — `db.ping()` redacts
    # before it builds the string, so there is nothing for this route to strip
    # and no way for this route to leak it by formatting it carelessly.
    database: str


@app.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness: is this process alive at all",
)
async def health_live() -> LivenessResponse:
    """Return 200 immediately, having checked nothing.

    ── WHY THIS PROBES NOTHING. READ THIS BEFORE "IMPROVING" IT ───────────────
    This looks like a bug. It returns a constant. It could be `return True`.
    It is not, and it is not an oversight — it is the most important endpoint on
    the service.

    Liveness exists to answer one question: *is this process so broken that
    restarting it is the only way forward?* Nothing else. And the answer to that
    question is structurally independent of every dependency, because a
    dependency cannot break the process. The embedder can be down. The database
    can be unreachable. The reranker can be loading a model. Every one of those
    is a perfectly healthy Python process that has nothing to say about them.

    So imagine "improving" this to also check the database and the workers. It
    works perfectly — for about forty seconds. Then Postgres has a brief
    connection blip, and /health/live returns 503. The orchestrator reads that
    as "irrecoverably broken" and kills a container that is fine. The new
    container starts, probes, finds the blip still present, and dies too. Now
    the restart loop is running, and the API is down — not because the database
    was briefly unreachable, but because the health check disagreed with the
    dependency. **The liveness check turned a five-second blip into a total
    outage, and it will keep killing every replacement that suffers the same
    blip.** Recovery is what a restart is for, and a restart that is triggered
    by the very condition it cannot fix is the opposite of recovery.

    That is why the answer here is a constant and why the function has no
    dependencies, no awaits, and no parameters: it is impossible for it to
    report a failure caused by something else, which is precisely the property
    that makes it safe to hand to a process supervisor that will act on it
    destructively.

    Everything this endpoint deliberately does NOT do lives in /health/ready,
    which checks all three dependencies and returns 503 when any is down — so
    the information is not lost, it is just consulted by something that can act
    on it correctly (take the instance out of rotation) rather than
    destructively (kill it).
    """
    return LivenessResponse(status=_PROBE_OK)


@app.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness: can this process serve a request right now",
)
async def health_ready(request: Request, response: Response) -> ReadinessResponse:
    """Report whether the database AND both inference workers are usable.

    This is the counterpart to /health/live and shares nothing with it but the
    `_PROBE_OK` vocabulary. It answers a different question with the opposite
    policy on dependencies: readiness SHOULD fail when a dependency is down,
    because the correct response to "I cannot serve requests right now" is
    "stop sending me requests", which is exactly what a load balancer or an
    orchestrator does with a 503 — take the instance out of rotation and put it
    back when it recovers. That is safe, self-limiting and automatic.

    Returns HTTP 200 when all three dependencies are ok, and HTTP 503 otherwise.
    503 and not 200-with-a-sad-body, for the reason written on /health: a
    non-2xx is what generic tooling actually reads.

    `/health` is unchanged and is still the workers-only readiness check that
    compose, scripts/boot.sh and the ALB already depend on. This route is
    additive; nothing that exists today routes through it yet.
    """
    # getattr rather than attribute access: an app driven without its lifespan
    # has no database on its state, and a 500 from a health endpoint is the
    # least useful thing a health endpoint can do. `db.ping(None)` reports
    # not-ready, which is the truthful answer for a process with no pool.
    database = getattr(request.app.state, "database", None)

    # One client for both worker probes, closed when this block exits, and one
    # concurrent probe of the database through its own pool. gather means the
    # total wait is the SLOWEST of the three, not the sum — so adding the
    # database to this route did not make the slowest case any slower.
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        embedder_state, reranker_state, database_verdict = await asyncio.gather(
            _probe(EMBEDDER_URL, client),
            _probe(RERANKER_URL, client),
            db.ping(database),
        )

    # The database contributes a bool plus a reason; the workers contribute a
    # reason that is already "ok" or a description. Normalising the database
    # through the same `_PROBE_OK` word keeps the response body uniform, and it
    # is safe to put in a client-visible response precisely because `db.ping()`
    # redacted it before building it — see `ReadinessResponse.database`.
    database_state = _PROBE_OK if database_verdict.ok else database_verdict.detail

    # "ok" requires ALL THREE. Two healthy dependencies out of three is not a
    # healthy service: a search that cannot reach the database serves nothing.
    is_ok = (
        embedder_state == _PROBE_OK
        and reranker_state == _PROBE_OK
        and database_verdict.ok
    )
    overall = _PROBE_OK if is_ok else "degraded"

    if not is_ok:
        # On the injected Response, which FastAPI uses as the status code for
        # the response it is about to serialise. Same mechanism as /health.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status=overall,
        embedder=embedder_state,
        reranker=reranker_state,
        database=database_state,
    )


# ── Inference proxies ─────────────────────────────────────────────────────────
# Everything below this line exists to hand a caller's request to a worker and
# hand the answer back. No storage, no retries, no caching, no queue: this API is
# a door, not a worker.


async def _post_upstream(url: str, payload: dict[str, Any], worker: str) -> Any:
    """POST one JSON payload to an inference worker and return its parsed body.

    Shared by /embed and /rerank because the two proxies are identical up to the
    URL and the payload: same client, same timeout policy, same three failure
    modes, same status codes. Only the route-specific part — what to send, and how
    to read the answer — is left to each caller. Extracting it here is what keeps
    the two routes' failure semantics from drifting apart, which is the failure
    mode that actually costs something: a client that gets 504 from /rerank and
    500 from /embed has been taught nothing about what went wrong.

    Raises HTTPException on every failure. It never returns an error as an
    ordinary value, because "the body happened to be a dict" and "the body was an
    error" would then be the same shape to the caller and could not be told apart
    downstream.

    Why the detail is short and the log is not: an HTTPException's detail is
    serialised straight into the response body and read by whoever is calling the
    API. A Python traceback contains file paths, library versions and local
    variable values — none of which helps the caller and all of which the caller
    did not earn. So the exception is logged here, in full, with its traceback,
    and the caller receives a sentence. If a failure is ever worth diagnosing, it
    is diagnosed from the log, where the operator is already looking.
    """
    try:
        # One client per request, constructed and closed inside an `async with` —
        # the same lifecycle /health uses. There is no pool worth keeping warm
        # here: each of these requests is a single call to a worker that is busy
        # doing inference, and nothing is carried between callers.
        async with httpx.AsyncClient(timeout=INFERENCE_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            # raise_for_status turns a worker's 4xx/5xx into an exception here, so
            # the status check and the body read cannot drift apart.
            response.raise_for_status()
            # Raises ValueError on a non-JSON body — handled below, because a
            # worker answering 200 with something that is not JSON is an upstream
            # failure, not a success with an odd payload.
            return response.json()
    except httpx.TimeoutException:
        # 504, distinct from the 502 below, and the distinction is the useful
        # part: "too slow" and "not there" have different causes and different
        # fixes. A timeout means the worker is alive and busy — probably scoring
        # a long document list on a CPU-only box — and the fix is a smaller
        # request or more time. A connection error means DNS, routing or a dead
        # process, and the fix is infrastructure. Reporting both as 502 would
        # leave the caller unable to tell which problem they have.
        logger.exception("%s timed out at %s after %ss", worker, url, INFERENCE_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"{worker} timed out after {INFERENCE_TIMEOUT_SECONDS:g}s",
        ) from None
    except httpx.HTTPStatusError as exc:
        # 502, and specifically NOT 503. The distinction is the whole reason this
        # proxy has more than one error code: /health returns 503 to mean "the
        # API's own dependencies are down" — a fact about THIS service's
        # readiness, which is what a scheduler needs to hear. Here the API itself
        # is fine and reachable; it is a DEPENDENCY that failed while serving
        # one request. That is a bad gateway, and a client that retries a 502
        # (optionally with backoff) is behaving correctly in a way it should not
        # be doing for a 503.
        #
        # The FULL upstream body is logged above (logger.warning) for the
        # operator. It is deliberately NOT echoed into the client-facing detail:
        # a worker's error body can expose internal configuration (for example
        # "current batch size: 512") that a caller must not see and cannot act
        # on, and some 502s (an oversized input) are permanent and must not be
        # retried. The client gets a status code and a plain sentence; the
        # operator gets the body in the server log.
        logger.warning("%s returned HTTP %s: %s", worker, exc.response.status_code, exc.response.text)
        detail = f"{worker} returned HTTP {exc.response.status_code}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from None
    except httpx.HTTPError as exc:
        # Connection refused, DNS failure, network unreachable, TLS error —
        # everything that never got an HTTP response at all.
        # The exception CLASS name, not its message: httpx messages vary between
        # versions and are not a stable thing to parse, while the class name is.
        # Same reasoning as in _probe above, deliberately: the two places that
        # talk about a worker being unreachable should say the same thing.
        logger.exception("%s unreachable at %s", worker, url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{worker} is unreachable ({type(exc).__name__})",
        ) from None
    except ValueError:
        # Reached only from response.json(). The worker answered 2xx with a body
        # that is not JSON, which means it is not behaving like the OpenAI-
        # compatible server this proxy is written against. The client is not in a
        # position to interpret that, so neither is this API.
        logger.exception("%s returned a non-JSON body at %s", worker, url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{worker} returned a response that is not JSON",
        ) from None


class EmbedRequest(BaseModel):
    """Body of POST /embed — exactly one piece of text.

    One field, because this route does one thing. `/search` now exists and it
    embeds its query through the same internal helper this route uses, so the
    temptation to add a `kind` field or a batch here is real — and it is refused
    for the reason in this route's docstring: a prefix applied here cannot tell
    documents from queries, and it is the document case that is expensive to get
    wrong.
    """

    # Required, and must contain something. See NonBlankText for why this is
    # validated by Pydantic rather than by a check in the handler.
    text: NonBlankText


class EmbedResponse(BaseModel):
    """Body of a successful POST /embed."""

    # The vector itself, exactly as the worker produced it.
    embedding: list[float]

    # The width of the vector, as a number, alongside the vector.
    #
    # Why this is here when a caller could obviously count the floats: because
    # counting them by hand is precisely what nobody does, and a client that
    # silently accepts any array length will happily store a 1024-dim vector
    # produced by a model swap and only discover it when retrieval quality
    # mysteriously drops weeks later. bge-small-en-v1.5 returns exactly 384.
    # Reporting the number turns that from a slow mystery into an immediate,
    # visible mismatch.
    dimensions: int

    # The alias that produced the vector. Echoed so a caller can attribute a
    # stored vector to the model that made it — without it, a collection filled
    # over time by two different models is indistinguishable from one filled by
    # a single model.
    model: str


async def _embed_text(text: str) -> EmbedResponse:
    """Turn one plain string into one ``EmbedResponse`` by calling the embedder.

    This is the internal implementation shared by ``POST /embed``,
    ``POST /documents`` and ``POST /search``. It takes a plain ``str`` instead of
    an ``EmbedRequest`` because ``EmbedRequest`` is the EDGE contract: building
    one from an already-validated internal string re-applies the public
    ``NonBlankText`` limit and allowed a prefixed query to overflow that limit
    after ``SearchRequest.query`` had already been accepted. Receiving a plain
    string makes that second validation structurally impossible.

    The text is forwarded BARE — no bge query prefix is added here. See
    ``embed``'s docstring for why prefixing at this layer would corrupt stored
    document vectors, and why the prefix belongs only in ``POST /search``.
    """
    # The OpenAI-compatible request shape the embedder server accepts. "model" is
    # the alias registered at server start, not a filename and not a HF repo id.
    # "input" is a LIST even for a single string — that is the embeddings API's
    # shape, and sending a bare string is a shape it does not accept.
    payload = {
        "model": EMBEDDER_MODEL_ALIAS,
        # Bare. See the block above. Do not add the bge query prefix here.
        "input": [text],
    }

    body = await _post_upstream(f"{EMBEDDER_URL}/v1/embeddings", payload, "embedder")

    try:
        # The OpenAI-compatible envelope: {"data": [{"embedding": [...], ...}]}.
        # "data" is a list because the endpoint accepts a batch; this route asks
        # for one item, so it takes element zero and nothing else. Every lookup
        # below is inside the try, so a worker that answered 200 with a body of
        # an entirely different shape raises here rather than producing a
        # KeyError-turned-500 further down.
        raw = body["data"][0]["embedding"]
        # float() per element is not paranoia about the worker — it is what makes
        # the response model below incapable of raising a validation error: by the
        # time EmbedResponse is constructed, every element is already a float or
        # has already failed.
        vector = [float(value) for value in raw]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        # Pydantic's ValidationError subclasses ValueError, so it is in this
        # tuple too — which means the single guard below covers a malformed
        # envelope AND a malformed element AND a non-numeric float, and all
        # three are reported the same truthful way: the UPSTREAM broke its
        # contract, so it is a 502, not a 500. A 500 would blame this service,
        # and the fix would be looked for in the wrong file.
        logger.exception("embedder returned an unexpected body: %r", body)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="embedder returned an unexpected response shape",
        ) from exc

    if not vector:
        # A zero-length vector is not a valid embedding and passing it on as a
        # success would put an unusable row into whatever the caller stores.
        logger.error("embedder returned an empty vector")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="embedder returned an empty vector",
        )

    return EmbedResponse(embedding=vector, dimensions=len(vector), model=EMBEDDER_MODEL_ALIAS)


@app.post("/embed", response_model=EmbedResponse, summary="Embed a single piece of text")
async def embed(request: EmbedRequest) -> EmbedResponse:
    """Turn one piece of text into one vector, by asking the embedder.

    ── WHY THERE IS NO bge QUERY PREFIX HERE. READ THIS BEFORE "FIXING" IT ──
    #
    # bge-small-en-v1.5 was trained with a fixed instruction string prepended to
    # the text of a SEARCH QUERY:
    #
    #     Represent this sentence for searching relevant passages:
    #
    # That prefix is for QUERIES ONLY. Documents must never carry it. The two
    # are encoded by the same model into the same vector space, but only the
    # document vectors are stored and retrieved: append the prefix to a document
    # and its stored vector moves off the manifold the documents live on, so it
    # becomes much harder to match against a prefixed query later. The damage is
    # silent and permanent — it is written into whatever database holds it, and
    # nothing in the response says it happened.
    #
    # So /embed forwards `text` BARE, exactly as given. This is a decision, not
    # an oversight, and not a missing feature. It is also the correct default
    # for this endpoint in a way that is easy to miss: /embed does not know
    # whether its text will be a query or a document, and a document is the case
    # that is expensive to get wrong. Prefixing here would corrupt stored
    # vectors; not prefixing can at worst cost a little query accuracy, and only
    # once /search exists to do it properly.
    #
    # WHERE THE PREFIX BELONGS: /search. That route is the one that knows, by
    # construction, which side of the retrieval pair it is on, and it is where
    # the prefix gets added to the query and to nothing else. It arrived after
    # this docstring was written; the argument above is unchanged by that, and
    # the fact that /search applies the prefix to its query is exactly the
    # reason this route must not apply it to anything.
    #
    # The deliberate omissions, so that nobody re-litigates them later: no `kind`
    # field, no query/document variants of this route, no parameterised prefix.
    # Each was considered and rejected.
    """
    return await _embed_text(request.text)


# ── /rerank is a PER-PAIR constraint ──────────────────────────────────────────
# /rerank scores (query, passage) PAIRS; the worker's 512-token ceiling applies
# to the COMBINED pair, not to either field in isolation. The per-field
# character limit (MAX_INFERENCE_INPUT_CHARS) therefore cannot guarantee a pair
# fits: two individually in-limit fields can still exceed the ceiling together.
# That is a known, accepted residual — a joint-length validator is NOT the
# smallest defensible change, and deliberately attempting to enforce a combined
# limit here would be false precision over a character proxy for a token limit.
# A comment stating the residual is the honest position.


class RerankRequest(BaseModel):
    """Body of POST /rerank — one query scored against one list of documents."""

    # Same non-blank rule as EmbedRequest.text. A query made of whitespace
    # cannot be ranked against anything, and forwarding it would spend a real
    # inference call to produce a meaningless ordering.
    query: NonBlankText

    # At least one document. An empty list has no scores to return, so the only
    # possible answer is an empty result set that looks like a successful
    # ranking of nothing — and a caller cannot tell that apart from "everything
    # scored terribly". Rejecting it turns a silent no-op into a clear 422.
    documents: list[NonBlankItem] = Field(..., min_length=1)

    # Optional. See the comment at its use below for why the default is "not
    # sent" rather than a number.
    top_n: int | None = Field(default=None, ge=1)


class RankedDocument(BaseModel):
    """One scored document, as the reranker returned it."""

    # The caller's ORIGINAL position in the array it sent — NOT the rank.
    #
    # This distinction is the whole reason the field is passed through untouched.
    # The worker returns documents already sorted best-first, so `results[0]` is
    # the winner; if `index` were re-derived from that position, position 0 would
    # claim to be the caller's document 0, which may be the one that scored
    # worst. A caller that trusted that would map every score back onto the wrong
    # document and would have no way to notice. Preserving the worker's value is
    # what lets the caller join the scores onto its own array and know which of
    # its own documents survived the cut.
    index: int

    # Higher is more relevant. Logits from the reranker's cross-encoder, so the
    # values are comparable to each other within one response and meaningless
    # across models or across versions of one.
    relevance_score: float


class RerankResponse(BaseModel):
    """Body of a successful POST /rerank."""

    # In the worker's order: best match first.
    results: list[RankedDocument]

    # The alias that produced the scores, echoed for the same reason EmbedResponse
    # echoes it — scores from two different rerankers are not comparable, and
    # without this the comparison cannot even be noticed.
    model: str


async def _rerank_texts(
    query: str, documents: list[str], top_n: int | None
) -> RerankResponse:
    """Score every supplied document against the query, best first.

    This is the internal implementation shared by ``POST /rerank`` and
    ``POST /search``. It takes plain values instead of a ``RerankRequest``
    because ``RerankRequest`` is the EDGE contract: building one from already-
    validated internal strings would re-apply the public length limit and is the
    same pattern that produced the E5 overflow bug in the embed path. Receiving
    plain strings makes that second validation structurally impossible.

    Note what this does NOT do: it does not filter, and it does not truncate.
    Reranking is a re-ordering of the documents the caller already chose. Deciding
    which candidates are worth sending in the first place is retrieval's job, and
    doing it here would mean the reranker's opinion of a document it was never
    shown.

    Failure handling is identical to ``_embed_text``'s, and shares its helper
    rather than restating it: 504 on timeout, 502 on an unreachable worker or a
    non-2xx answer, the detail logged here and a short sentence returned. The
    reasons are the ones written on ``_post_upstream`` and they apply unchanged
    to this route.
    """
    payload: dict[str, Any] = {
        "model": RERANKER_MODEL_ALIAS,
        "query": query,
        # Forwarded in the caller's original order, unaltered. That order is what
        # the `index` values in the response refer to, so reordering here would
        # silently invalidate every index the worker sends back.
        "documents": documents,
    }

    if top_n is not None:
        # Added ONLY when the caller supplied one. See below for why the default
        # is absence rather than a number.
        payload["top_n"] = top_n
    # Otherwise the key is not sent at all, and the worker applies its own default.
    #
    # Why: this API has no standing opinion about how many results a caller
    # wants. Hardcoding a funnel size here — "top 5" is the tempting choice —
    # would not fail loudly. It would quietly change retrieval behaviour for
    # EVERY caller that did not ask, dropping documents some of them needed,
    # with a 200 and a short result list as the only evidence. A knob that
    # defaults to "whatever the component below me decides" cannot have that
    # failure mode, and it means this API does not need to be redeployed when the
    # worker's default changes.

    body = await _post_upstream(f"{RERANKER_URL}/v1/rerank", payload, "reranker")

    try:
        # Re-validated into our own model on the way through rather than passed
        # through as a raw dict. It costs a few microseconds and buys two things:
        # the OpenAPI schema at /docs is generated from this model, so the
        # response shape is documented instead of being folklore; and a worker
        # that changes its answer is caught HERE, as a 502, instead of becoming a
        # KeyError in some future refactor. Same guard set as /embed, for the
        # same reason: pydantic's ValidationError is a ValueError, so a missing
        # key, a wrong type and a malformed item are all the same upstream
        # contract break and all get the same honest status code.
        return RerankResponse(results=body["results"], model=RERANKER_MODEL_ALIAS)
    except (KeyError, TypeError, ValueError) as exc:
        logger.exception("reranker returned an unexpected body: %r", body)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="reranker returned an unexpected response shape",
        ) from exc


@app.post(
    "/rerank",
    response_model=RerankResponse,
    summary="Score and rank documents against a query",
)
async def rerank(request: RerankRequest) -> RerankResponse:
    """Score every supplied document against the query, best first.

    This route is the edge contract: it validates the caller's body through
    ``RerankRequest`` and delegates the actual scoring to ``_rerank_texts``.
    Keeping validation and execution separate means no internal call site ever
    needs to construct a request model; that is the same invariant the embed path
    keeps via ``_embed_text``.
    """
    return await _rerank_texts(request.query, request.documents, request.top_n)


# ── Ingestion ─────────────────────────────────────────────────────────────────
#
# `POST /documents` is the first route in this file that MUTATES anything, and
# that changes what has to be defended. Everything above is a proxy: it can be
# wrong about a worker's shape or a worker's availability, and the worst outcome
# is a wrong answer to one request. This route writes a row that outlives the
# request, and a wrong vector written here is wrong permanently — there is no
# response that can tell the caller their stored document is subtly off, which
# is why the invariants below are stated as invariants rather than as features.


class DocumentRequest(BaseModel):
    """Body of POST /documents — one document, its collection, and its metadata.

    ── WHY THESE FOUR FIELDS AND NO MORE ───────────────────────────────────────
    The caller supplies an EXTERNAL identity (`document_id`), the partition it
    belongs in (`collection`), the text itself (`content`), and whatever
    arbitrary JSON they want to keep alongside it (`metadata`).

    Notably absent: the embedding. A caller cannot hand one in, and cannot
    supply an `id` for the database to generate. Both exclusions are load-
    bearing. Accepting a caller-supplied vector would let a document be stored
    that this service never embedded, which is precisely the class of row the
    retrieval path cannot detect — it would simply be unmatchable, forever,
    with no error. And a generated id would introduce a second identity for a
    document, which is the thing migration 0001 explicitly refused when it chose
    `id TEXT PRIMARY KEY` over a generated column.
    """

    # The caller's own identifier, and the upsert key. NonBlankIdentifier
    # (strip, then reject blank) — an identifier is never forwarded to an
    # inference worker, so it carries NO max_length: only non-blankness matters.
    document_id: NonBlankIdentifier

    # The partition every retrieval query filters on. NonBlankIdentifier rather
    # than NonBlankText: a collection name is compared for equality by the
    # caller (they will pass the same string to /search later), so silently
    # rewriting it would matter — but crucially it is NEVER sent to a worker,
    # so it carries NO max_length either. It is also belt-and-braces with the
    # database's own `documents_collection_not_blank` CHECK — validated here so
    # the caller gets a 422 naming the field instead of a constraint violation.
    collection: NonBlankIdentifier

    # The text to embed and store. NonBlankText: stripping is safe here because
    # the caller's intent is "this document", not "this exact byte sequence", and
    # the vector is computed from whatever is finally stored, so they agree.
    content: NonBlankText

    # Optional, defaults to `{}` — NOT to `None`. The migration's column is
    # `JSONB NOT NULL DEFAULT '{}'` with a CHECK of
    # `jsonb_typeof(metadata) = 'object'`, and it deliberately rules out a JSON
    # null: absent metadata is an empty object, never a null. A `None` default
    # would put `null` on the wire and be rejected by the database on a write
    # the caller had no reason to think was malformed.
    #
    # ── WHY THE TYPE IS `dict` AND NOT `Any` ──────────────────────────────────
    # The database already enforces that metadata is a JSON OBJECT; this is that
    # rule enforced at the EDGE instead, one layer earlier, where the caller can
    # still do something about it. `dict[str, Any]` makes FastAPI reject
    # `"metadata": [1, 2, 3]` — or a string, or a number — with a 422 that NAMES
    # the field, instead of letting it travel all the way to an
    # `IntegrityError` on a CHECK constraint. That matters for the same reason
    # the comment on `RerankRequest.documents` matters: the database constraint
    # turns a silent corruption into a loud failure, but a loud failure at INSERT
    # is only half the job — the other half is telling the caller WHICH field of
    # THEIR request was wrong. A `dict` type buys the second half for free, in
    # the generated OpenAPI schema as well as in the response.
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentResponse(BaseModel):
    """Body of a successful POST /documents.

    Reports what HAPPENED, not just what was asked for. Three fields, and each
    one exists because its absence would leave a real failure invisible:

    * `document_id` and `collection` echo the row as the DATABASE now holds it.
      Echoing the request instead would report what the caller asked for, which
      is not the same claim, and `collection` in particular can differ from what
      was sent when the id already existed in another collection — see
      `store.upsert_document`.
    * `dimensions` is `vector_dims(embedding)` — the width PostgreSQL ACCEPTED.
      Not the width the embedder claimed. Those are two systems answering two
      different questions, and this is the one that describes the stored bytes.
      If a model swap ever changes the width, the mismatch appears in this field
      on the very first write that could not store it, instead of weeks later as
      retrieval that has quietly stopped working.
    * `outcome` is `"inserted"` or `"updated"`, so an upsert's second arm is
      visible to the caller instead of being a silent overwrite.
    """

    document_id: str
    collection: str
    #: The width actually stored, as the database reports it.
    dimensions: int
    #: `"inserted"` for a new row, `"updated"` when the id already existed.
    outcome: str


@app.post(
    "/documents",
    response_model=DocumentResponse,
    summary="Embed a document and store it",
    status_code=status.HTTP_201_CREATED,
)
async def create_document(request: Request, body: DocumentRequest) -> DocumentResponse:
    """Embed one document and write it to `documents`, upserting by id.

    ── UPSERT SEMANTICS, STATED PLAINLY ────────────────────────────────────────
    Re-posting a `document_id` that already exists UPDATES that row — content,
    metadata, embedding, and collection — rather than creating a second one.
    There is no 409 and no "already exists": ingestion is idempotent by id, so
    re-running the corpus loader is safe, and a caller correcting a document
    re-posts it the same way. The response's `outcome` field says which arm ran.

    A consequence worth knowing before relying on it: because `id` is the GLOBAL
    primary key, re-posting under a different `collection` MOVES the document
    rather than copying it. That is the only behaviour the schema permits, and
    `store.upsert_document` explains why.

    ── THE bge QUERY PREFIX IS NOT APPLIED HERE. THIS IS THE POINT. ────────────
    This route embeds `body.content` through the same internal helper that
    `/embed` uses, and that helper forwards its text BARE. See `/embed`'s
    docstring for the full reasoning; the one-line version is that
    bge-small-en-v1.5's instruction string was trained onto SEARCH QUERIES ONLY,
    and prefixing a document moves its vector off the manifold the other
    documents live on — permanently, invisibly, and with nothing in any response
    ever saying so.

    So the invariant, stated as an invariant: **the only string that reaches the
    embedder from this route is the caller's own `content`, unmodified.** There
    is no `kind` parameter here, no prefix constant, and no code path that could
    add one without rewriting this sentence and `main.embed`'s docstring
    together. `/search` applies the prefix to its QUERY and to nothing else,
    including nothing that came through this route.

    Calling `_embed_text` rather than reimplementing the embedder call is
    deliberate: it means this route inherits the worker's exact failure
    semantics (504 on timeout, 502 on unreachable or on an unexpected body shape)
    and its exact bfloat16-to-float conversion, by construction. A second copy of
    that code would be free to drift from the first, and the drift would be
    invisible until the two routes disagreed about what a bad worker looks like.
    """
    database: db.Database | None = getattr(request.app.state, "database", None)
    engine = getattr(database, "engine", None)
    if engine is None:
        # Same policy as /health/ready, same reason: a request that cannot be
        # served must say so in the status line, not with a 200 and a sad body.
        # `db.startup` never raises, so this is a reachable state on a host where
        # the database is unconfigured or down — not a defensive branch.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the database is not available",
        )

    # BARE. See the invariant above. Do not add the bge query prefix here.
    embedded = await _embed_text(body.content)

    # The model's answer checked against the schema's, BEFORE the write. This is
    # the cheap half of "surface a mismatch immediately": it produces a 502 that
    # names both numbers, on the request that caused it, instead of a constraint
    # violation naming a column. The expensive half — the width the database
    # ACTUALLY stored — comes back in the response as `dimensions`, and the test
    # suite asserts against the stored value rather than this one.
    if embedded.dimensions != SCHEMA_EMBEDDING_DIM:
        logger.error(
            "embedder returned %d dimensions but documents.embedding is vector(%d)",
            embedded.dimensions,
            SCHEMA_EMBEDDING_DIM,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"embedder returned {embedded.dimensions} dimensions, but the "
                f"documents table stores vector({SCHEMA_EMBEDDING_DIM}). The model "
                "and the schema disagree; changing the embedding width is a "
                "migration, not a configuration change."
            ),
        )

    try:
        written = await store.upsert_document(
            engine,
            document_id=body.document_id,
            collection=body.collection,
            content=body.content,
            metadata=body.metadata,
            embedding=embedded.embedding,
        )
    except SQLAlchemyError as exc:
        # ── WHAT IS LOGGED, AND WHY SO LITTLE ─────────────────────────────────
        # The exception CLASS and its SQLSTATE. Not the message, and not the
        # traceback, and this is deliberate rather than terse: asyncpg's
        # CheckViolationError carries a DETAIL line containing THE FAILING ROW,
        # and the failing row is `id, collection, content, metadata`. Measured on
        # pgvector/asyncpg 0.32.0 + PostgreSQL 16.15, a rejected metadata write
        # produces:
        #
        #     DETAIL:  Failing row contains (metaarr, probe, <the content>, [1, ...
        #
        # So `logger.exception(...)` — which is the reflex, and which this route
        # would otherwise be expected to do — writes the caller's document body
        # into the server log. `hide_parameters=True` in `config.engine_kwargs`
        # already stops the OTHER half of that leak (SQLAlchemy's bound-parameter
        # echo); this line is what stops the remaining half.
        #
        # SQLSTATE is enough to diagnose: 23505 unique violation, 23514 check
        # violation, 23502 not-null, 08xxx connection. It is a code, not data,
        # and it cannot carry a document.
        logger.error(
            "storing document %r failed: %s (SQLSTATE %s)",
            body.document_id,
            type(exc).__name__,
            getattr(getattr(exc, "orig", None), "sqlstate", "<unknown>"),
        )
        # No `from exc`: the chained traceback would render that DETAIL line
        # above into whatever renders it — an error handler, a log aggregator, a
        # bug report. The response detail is a fixed sentence for the same
        # reason: it names the failure without quoting data back to a caller who
        # sent it.
        #
        # The 502 here is DELIBERATE and is documented in client.md §5: "the
        # document could not be stored" is a bad-gateway for a write that did not
        # complete, while `POST /search` returns 503 for the same SQLAlchemyError
        # class ("the document store could not be searched"). The divergence is
        # intentional — the API itself is fine in both cases; the status code
        # tells the client which dependency failed (the document store for a
        # write vs. a read) and what the client should do next. Do not unify
        # these codes without updating client.md §5 and both handlers together.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="the document could not be stored",
        ) from None

    # The document_id and collection are logged. The CONTENT is not, and never
    # will be: `hide_parameters=True` in `config.engine_kwargs` stops SQLAlchemy
    # echoing bound parameters, and this line is the other half of that. A
    # document body is the user's data, it can be arbitrarily large, and nothing
    # about diagnosing a write failure needs it.
    logger.info(
        "stored document %r in collection %r at %d dimensions (%s)",
        written.document_id,
        written.collection,
        written.dimensions,
        "inserted" if written.inserted else "updated",
    )

    return DocumentResponse(
        document_id=written.document_id,
        collection=written.collection,
        # From `vector_dims(embedding)` — the stored width, not the model's claim.
        dimensions=written.dimensions,
        outcome="inserted" if written.inserted else "updated",
    )


# ── Retrieval ─────────────────────────────────────────────────────────────────
#
# `POST /search` is the first route that reads a row back out of the database
# through the API, and it is the first route that composes the two workers. The
# stages below run in a fixed order and each one is deliberately boring:
#
#   1. validate           — Pydantic, so a bad request never reaches the embedder
#   2. embed the QUERY    — /embed, WITH the bge query prefix
#   3. retrieve           — store.retrieve, collection filter IN SQL
#   4. (zero candidates)  — return empty, WITHOUT calling the reranker
#   5. rerank             — /rerank, over the candidate CONTENTS, in stage-1 order
#   6. map + truncate     — attach each score to the document it belongs to
#
# The two properties this route exists to hold — the query is prefixed and the
# documents are not, and every score belongs to the document it was computed for
# — are easy to state and easy to break silently, so each is marked at the line
# that enforces it.


class SearchRequest(BaseModel):
    """Body of POST /search — a collection to search, a query, and optional sizes.

    Two required fields and two optional ones. Neither optional field has a
    default number in THIS model: `candidates` and `top_k` default to `None`,
    which is not the same as defaulting to a count. `None` means "use the
    server's configuration" and is resolved by `config.Funnel.clamped`, so the
    funnel lives in one place — `.env` — instead of being restated in a Pydantic
    default that a later configuration change would silently contradict.
    """

    # Which partition to search. NonBlankIdentifier, exactly as on
    # `DocumentRequest`: the same string will be compared for equality by the
    # caller when they post a document, and an identifier is never forwarded to
    # an inference worker so it carries NO max_length.
    collection: NonBlankIdentifier

    # The query. SearchQueryText (same non-blank rule as NonBlankText, but with
    # the smaller maximum that leaves room for QUERY_PREFIX), and this is a QUERY
    # by construction — it is the one field in this service that is guaranteed to
    # be on the retrieval pair's query side, which is what earns this route the
    # right to prefix it.
    query: SearchQueryText

    # Stage-1 candidate count. `ge=1` because a 0 is a mistake, and a mistake the
    # caller should hear about rather than a funnel they have silently emptied.
    # The configured maximum still applies — `clamped` truncates rather than
    # honouring a larger number, so a caller cannot make this service spend more
    # inference than its operator sized it for.
    candidates: int | None = Field(default=None, ge=1)

    # Stage-2 result count, bounded the same way and additionally capped at the
    # resolved candidate count: the reranker cannot produce more results than
    # there were documents to rerank.
    top_k: int | None = Field(default=None, ge=1)


def _search_embedding_text(query: str) -> str:
    """Return the exact string /search forwards to the embedder for ``query``.

    This is ``QUERY_PREFIX + query`` with no separator. Keeping the concatenation
    in one named helper makes the budget arithmetic testable and prevents the
    route from inlining a subtle + that could drift from ``SearchQueryText``'s
    maximum. Because ``SearchRequest.query`` is validated against
    ``MAX_SEARCH_QUERY_CHARS``, the returned string is guaranteed to be at most
    ``MAX_INFERENCE_INPUT_CHARS`` characters long.
    """
    return QUERY_PREFIX + query


# Keys that are internal test-scaffolding / audit evidence and must never be
# returned to an external client. They remain in storage: store.retrieve copies
# `dict(row.metadata)` verbatim (store.py:579) because these keys are
# load-bearing audit evidence for collection isolation —
# docs/verification-milestone-3.md §12.3 records
# `grep -c '"isolation_canary": true' data/corpus.json` = 10, and the corpus
# canary pairs are exercised by api/tests/test_search.py §3.
#
# Filtering happens here, at the API RESPONSE layer, when building
# SearchResultDocument.metadata. The set is explicit and narrow: only internal
# scaffolding keys are excluded, never arbitrary caller metadata. Currently the
# only such key is `isolation_canary`.
INTERNAL_METADATA_KEYS = frozenset({"isolation_canary"})


def _strip_internal_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return `metadata` with internal scaffolding keys removed.

    Internal audit keys (see INTERNAL_METADATA_KEYS) must not reach external
    clients through a search response, but they must remain in storage for the
    collection-isolation evidence. Ordinary caller keys are preserved verbatim.
    """
    return {
        key: value
        for key, value in metadata.items()
        if key not in INTERNAL_METADATA_KEYS
    }


class SearchResultDocument(BaseModel):
    """One search result: a stored document, with both stages' opinion of it."""

    # The caller's own external identity, unchanged from ingestion. Echoing the
    # stored value rather than anything computed here means a caller can join
    # results back onto their own index without a second lookup.
    document_id: str

    # The partition this result came from. It is redundant — every result in one
    # response shares the searched collection — and it is here anyway, because a
    # result whose provenance is inferred rather than stated cannot be checked,
    # and "why did this come back from a search I scoped elsewhere" is the
    # question an operator asks first when a filter is suspected.
    collection: str

    # The stored text, verbatim. Returned whole rather than as a snippet because
    # the caller supplied it, this service did not write it, and truncating it
    # here would save nothing they cannot save themselves.
    content: str

    # The caller's metadata from ingestion. Returned because a search result that
    # omits the fields a caller attached is not actionable: they would have to
    # fetch every hit individually to filter, sort or display it.
    metadata: dict[str, Any]

    # ── STAGE 2 — THE SCORE TO TRUST ───────────────────────────────────────────
    # The cross-encoder's logit. Higher is more relevant, and the values are
    # comparable to each other WITHIN one response. They are not percentages, not
    # probabilities, and not comparable across models or across versions of one —
    # a reranker swap silently changes what "good" means, which is why the model
    # alias is echoed at the top level too.
    relevance_score: float

    # ── STAGE 1 — THE SCORE THAT DECIDED WHO WAS CONSIDERED AT ALL ─────────────
    # The vector distance that put this document in the candidate set, lower is
    # better.
    #
    # WHY BOTH SCORES ARE RETURNED, since `relevance_score` is the meaningful one
    # and this could be dropped:
    #
    # The two numbers answer different questions and are only interpretable
    # together. `distance` is what stage 1 thought, and it is the answer to "why
    # was this document considered at all" — a result with a good
    # `relevance_score` and an awful `distance` means stage 1 had to reach deep
    # to find it, which is exactly the signal that the candidate count is too
    # small for this corpus. Conversely a result with a wonderful `distance` and a
    # poor `relevance_score` means the vector space and the cross-encoder
    # disagree about that document, which is a model or a chunking problem.
    #
    # A retrieval system that returns only one score cannot be debugged at all:
    # it cannot distinguish "the reranker got it wrong" from "stage 1 never gave
    # it a chance", and those two have completely different fixes. Returning both
    # costs one float per result and makes bad answers explainable.
    distance: float


class SearchResponse(BaseModel):
    """Body of a successful POST /search."""

    # The results, best first. Truncated to the resolved `top_k`. An empty list is
    # a SUCCESSFUL response meaning "nothing in this collection matched" — see
    # the empty-collection decision in the route's docstring.
    results: list[SearchResultDocument]

    # The collection that was searched, echoed from what was ASKED for rather than
    # derived from the results. On an empty response these are the only two facts
    # a caller has, and "I searched the wrong collection" is the first thing to
    # rule out when a search returns nothing.
    collection: str

    # How many candidates stage 1 actually returned and stage 2 actually scored.
    # This is the number that makes an empty result set explainable: 0 means the
    # collection held nothing (or nothing matched), and 5 with 0 results means
    # the funnel was cut somewhere else entirely. Without it, "no results" is a
    # shrug; with it, it is a fact about a specific stage.
    candidates_considered: int

    # The reranker alias, echoed for the same reason `EmbedResponse.model` and
    # `RerankResponse.model` echo theirs: scores from two different rerankers are
    # not comparable, and without the alias the substitution is invisible.
    model: str


@app.post(
    "/search",
    response_model=SearchResponse,
    summary="Retrieve, rerank and return the best documents in a collection",
)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """Find the documents most relevant to a query, within one collection.

    ── STAGE 2: THE QUERY IS PREFIXED. THE DOCUMENTS ARE NOT. ───────────────────
    This is the line the entire route exists to get right, so it is stated once
    more here where the code is:

        embed(QUERY_PREFIX + body.query)   ← the QUERY, prefixed
        embed(D.content)                   ← every document, BARE, forever

    bge-small-en-v1.5 was trained with that instruction string attached to search
    QUERIES only, and only the DOCUMENT vectors are stored. See `embed`'s
    docstring for the full argument. The short version: prefixing a document
    moves its vector off the manifold the other documents live on, so it becomes
    much harder to match, permanently, in whatever database holds it, and no
    response ever says it happened.

    Note what this route does NOT do with the prefix: it does not re-embed the
    candidates. Stage 1 returned rows whose embeddings were computed at ingestion
    and are sitting in the column. Re-embedding them here — even "just to be
    consistent" — would write a different vector than the one that was stored,
    and would do it with the same silent permanence. The documents are read, and
    the prefix is applied to exactly one string in this function.

    There is deliberately no `kind` parameter and no parameterised prefix here
    either. Both were considered when `/embed` was written and both rejected; see
    `embed`'s docstring. This route does not know the difference between a query
    and a document because it is never given a document to embed.

    ── THE INDEX MAPPING. THIS IS THE CORRECTNESS TRAP. ────────────────────────
    The reranker returns `index` = the caller's position in the array THE
    CALLER SENT. This route sends `[candidate.content for candidate in
    candidates]`, in stage-1 distance order. Two rules follow from that, and
    breaking either attaches every score to the wrong document — silently, with a
    200 and entirely plausible-looking numbers:

    * The list SENT and the list MAPPED must be the same list, in the same
      order. Re-sorting between sending and mapping (e.g. "sorted by distance,
      nicer to read") moves every index by an unknown amount. That is why the
      comprehension below builds `sent_contents` ONCE and both the request
      payload and the mapping index into that one list, and why nothing between
      the send and the mapping is allowed to reorder or filter it.
    * The results must be MAPPED before they are TRUNCATED. `results[:top_k]`
      is a list of reranker positions in reranker score order; slicing it and
      only then looking up each `index` works, but slicing AFTER mapping is the
      same operation with the failure impossible to see. The mapping below
      happens first and the truncation second, so the number of scores that are
      looked up is the number that will be returned.

    `api/tests/test_integration.py::test_rerank_preserves_original_document_indices`
    (Milestone 1) guards the same property at the `/rerank` layer: the worker's
    `index` is passed through untouched rather than re-derived from the sorted
    position. This route consumes that value rather than re-deriving it, which is
    the whole reason it is worth preserving there.

    ── AN EMPTY COLLECTION RETURNS 200 WITH AN EMPTY LIST. THIS IS A CHOICE. ────
    Searching a collection that holds no documents returns HTTP 200 and
    `results: []`, `candidates_considered: 0`.

    The alternative was 404 "collection not found", and it was rejected for three
    reasons, in descending order of how much they matter:

    1. It requires an existence query before the search — a second round trip
       against the database, on the one request in this service whose whole job
       is to be fast, to answer a question the search itself can answer for free
       by returning nothing.
    2. It introduces a TOCTOU race. Collections are not a table here; they are a
       value in a column, and a document can be ingested into a collection
       between the existence check and the search. Under 404 the correct answer
       ("it exists") would then be reported for a request that found it empty,
       and vice versa. The check cannot be made atomic against a free-text
       partition key, so it can only be made less wrong.
    3. 404-on-search is not what any HTTP client expects. Generic clients treat
       404 as "wrong URL", and a search endpoint is exactly the place where an
       empty result is a completely normal outcome — the query was bad, the
       corpus is small, the document has not been ingested yet. Overwhelming a
       legitimate answer with an error status makes the distinction harder to
       express than it needs to be, and a caller who wants the distinction can
       already compute it: `results == [] and candidates_considered == 0` says
       "the collection produced no candidates", which is the fact.

    STATED PLAINLY, because it is a real trade-off and not an oversight: a
    TYPO'D collection name returns an empty result set rather than an error. A
    caller who misspells `infrastrucure` gets 200 and no documents, and if they
    do not check `candidates_considered` they may read that as "nothing matched"
    when the truth is "nothing was searched". That is accepted here in exchange
    for one round trip, no race, and conventional semantics. The mitigations are
    the echoed `collection` (a typo is visible in the response) and
    `candidates_considered` (zero is visible and distinguishable from "the funnel
    found things and none were relevant"). Callers who need strict existence
    should add an explicit `require_collection` flag; that is a product decision
    for a milestone that has a caller asking for it, not something to guess at
    here.

    ── ZERO CANDIDATES DOES NOT REACH THE RERANKER ────────────────────────────
    An empty candidate list goes back to `/rerank` as a 422 — it has no scores to
    return, and the only answer it could produce is an empty result set that looks
    like a successful ranking of nothing. So `/search` checks first and returns
    its own empty result. That is not politeness: the reranker is a cross-encoder
    on a CPU-only box, and calling it with an empty list would spend a real HTTP
    round trip to a worker doing real inference work, on every search of an empty
    collection, to produce a rejection.

    ── FAILURE HANDLING ────────────────────────────────────────────────────────
    * Database unavailable or erroring → 503, the same meaning `/health/ready`
      gives the same word: this process cannot serve this request now.
    * Embedder or reranker unreachable → 502; either of them slower than
      `INFERENCE_TIMEOUT_SECONDS` → 504. Both inherited from `_post_upstream` by
      calling `_embed_text()` and `_rerank_texts()` as ordinary functions rather
      than reimplementing either, which is the same reasoning `create_document`
      gives for calling `_embed_text()`.
    """
    database: db.Database | None = getattr(request.app.state, "database", None)
    engine = getattr(database, "engine", None)
    if engine is None:
        # Same policy as /health/ready and /documents, same reason: the
        # database is a real dependency of this route, and a request that cannot
        # be served must say so in the status line rather than return 200 with an
        # empty result that the caller cannot distinguish from a real one.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the database is not available",
        )

    # Resolved once, here, so every number this route uses comes from the same
    # read of the same configuration. `clamped` applies the configured maxima;
    # its docstring covers why a caller may ask for less but never for more.
    funnel = config.funnel_from_environment()
    candidate_limit, top_k = funnel.clamped(
        candidates=body.candidates, top_k=body.top_k
    )

    # ── THE PREFIX. ON THE QUERY. HERE. AND NOWHERE ELSE IN THIS FUNCTION. ─────
    embedded = await _embed_text(_search_embedding_text(body.query))

    # Checked against the schema's width for the same reason /documents checks
    # it, and the failure it prevents is worse here: a wrong-width query vector
    # reaches `CAST(:query AS vector)` in the store layer, where the mismatch
    # surfaces as a driver-level complaint about a query argument — a message
    # that blames the database for a model swap that happened in a worker.
    if embedded.dimensions != SCHEMA_EMBEDDING_DIM:
        logger.error(
            "embedder returned %d dimensions for a search query but documents.embedding is vector(%d)",
            embedded.dimensions,
            SCHEMA_EMBEDDING_DIM,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"embedder returned {embedded.dimensions} dimensions, but the "
                f"documents table stores vector({SCHEMA_EMBEDDING_DIM}). Documents "
                "already in the table were embedded at the schema's width, so this "
                "model cannot be compared against them."
            ),
        )

    try:
        candidates = await store.retrieve(
            engine,
            collection=body.collection,
            query_embedding=embedded.embedding,
            limit=candidate_limit,
        )
    except SQLAlchemyError as exc:
        # 503, and specifically not 502. The API is fine and reachable; the
        # DATABASE is what failed while serving one request, and `/health/ready`
        # means exactly this by 503. The log line carries the class and the
        # SQLSTATE for the reasons spelled out in `create_document`: the message
        # is not logged because asyncpg's DETAIL lines carry row contents, and
        # the query parameters here include the caller's query vector.
        #
        # The 503 here is DELIBERATE and is documented in client.md §5: "the
        # document store could not be searched" is a service-unavailable for a
        # read that could not complete, while `POST /documents` returns 502 for
        # the same SQLAlchemyError class ("the document could not be stored").
        # The divergence is intentional — the API itself is fine in both cases;
        # the status code tells the client which dependency failed (a read vs. a
        # write to the document store) and what the client should do next. Do
        # not unify these codes without updating client.md §5 and both handlers
        # together.
        logger.error(
            "retrieval for collection %r failed: %s (SQLSTATE %s)",
            body.collection,
            type(exc).__name__,
            getattr(getattr(exc, "orig", None), "sqlstate", "<unknown>"),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the document store could not be searched",
        ) from None

    # ── NO CANDIDATES → EMPTY RESULT, NO RERANKER CALL. See the docstring. ─────
    if not candidates:
        # The collection is echoed and NOT logged at INFO with the query: a
        # search query is user data, exactly as document content is, and the same
        # rule that keeps `/documents` from logging content keeps this from
        # logging the thing it was searching for.
        logger.info(
            "search returned 0 results: collection %r has no candidates for this query",
            body.collection,
        )
        return SearchResponse(
            results=[],
            collection=body.collection,
            candidates_considered=0,
            model=RERANKER_MODEL_ALIAS,
        )

    # ── STAGE 2 ────────────────────────────────────────────────────────────────
    # Built ONCE, in stage-1 distance order, and used for both the payload and the
    # mapping below. Do not sort, slice or otherwise disturb this list between
    # those two uses — see "THE INDEX MAPPING" in the docstring. Every failure
    # that costs real debugging time on this route starts with a second,
    # differently-ordered list appearing here.
    sent_contents = [candidate.content for candidate in candidates]

    # `_rerank_texts()` is called rather than `_post_upstream` being reimplemented,
    # for the same reason `create_document` calls `_embed_text()`: it inherits the
    # worker's exact failure semantics (502/504) and its response validation by
    # construction, and a second copy of that code would be free to drift from
    # the first.
    ranked = await _rerank_texts(body.query, sent_contents, None)

    # ── MAP FIRST, TRUNCATE SECOND. See the docstring for why the order matters. ─
    # Each result's `index` is a position in `sent_contents`, which is the same
    # list `candidates` was built from in the same order — so the lookup below is
    # into the stage-1 list by the reranker's own index. `relevance_score` is
    # read from the SAME result object that supplied the index, so a score can
    # never be detached from the document it was computed for.
    mapped: list[tuple[store.Candidate, RankedDocument]] = []
    for result in ranked.results:
        # An out-of-range index would raise IndexError here and become a 500.
        # It cannot happen with a well-behaved worker, but the consequence of it
        # happening would be a crash on the one code path every search goes
        # through, so it is skipped with a loud log rather than allowed to
        # propagate: a missing result is visible, a 500 on every search is not.
        if not 0 <= result.index < len(candidates):
            logger.error(
                "reranker returned index %d for a request carrying %d document(s)",
                result.index,
                len(candidates),
            )
            continue
        mapped.append((candidates[result.index], result))

    # Re-sorted here rather than trusted from the worker, and the comment above
    # says why that is not redundant: `RerankResponse.results` is documented as
    # "in the worker's order", which is a property of the worker, not a contract
    # this route may rely on — a worker that changed its sort, or a proxy that
    # reordered a JSON array, would silently change what this API promises its
    # callers. Sorting AFTER mapping is safe in a way sorting the response list
    # would not be: the score travels inside `pair`, so nothing that moves can
    # become detached from the document it was computed for.
    mapped.sort(key=lambda pair: pair[1].relevance_score, reverse=True)
    results = [
        SearchResultDocument(
            document_id=candidate.document_id,
            collection=candidate.collection,
            content=candidate.content,
            metadata=_strip_internal_metadata(candidate.metadata),
            relevance_score=result.relevance_score,
            # Stage 1's opinion, carried from the candidate. Both scores, because
            # a result showing only stage 2 cannot explain why it was considered.
            distance=candidate.distance,
        )
        for candidate, result in mapped[:top_k]
    ]

    # Metadata only: the collection, the two funnel numbers and the counts. NOT
    # the query, NOT the document contents, NOT the scores. See the log note
    # above — a search query is user data and is handled like document content.
    logger.info(
        "searched collection %r: %d candidate(s) considered, %d returned (funnel %d/%d)",
        body.collection,
        len(candidates),
        len(results),
        funnel.retrieval_candidates,
        funnel.rerank_top_k,
    )

    return SearchResponse(
        results=results,
        collection=body.collection,
        # What stage 1 ACTUALLY returned, not `candidate_limit`. A collection
        # holding three documents with a limit of ten yields 3, and reporting 10
        # would claim work that never happened and make the empty-result case
        # indistinguishable from the truncated one.
        candidates_considered=len(candidates),
        model=RERANKER_MODEL_ALIAS,
    )
