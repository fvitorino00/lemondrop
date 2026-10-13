"""lemondrop API — the orchestrator in front of the two inference workers.

Architecture in one paragraph: `embedder` and `reranker` are stateless llama.cpp
servers that are NOT published to the host. They are reachable only from other
containers on the compose network, by service name. This API is the single door
to the outside world, and its job is to stand in front of them.

Five routes, in the order they were earned: ``GET /health`` reports the truth
about the two workers beneath it; ``POST /embed`` and ``POST /rerank`` are thin
proxies that actually call them; ``GET /health/live`` and ``GET /health/ready``
came with the database phase, which probes the database as well as the workers.
The sixth arrived with this one: ``POST /documents``, the first route that
writes anything. It embeds a document through the same worker proxy ``/embed``
uses and hands the vector to ``app/store.py``.

What is still absent is retrieval: there is no ``/search``. The database now
holds embedded documents, and nothing reads them back through the API yet.

A NOTE ON THE bge QUERY PREFIX, recorded here because it is the single most
misreadable decision in this file. bge-small-en-v1.5 was trained with the fixed
instruction string ``Represent this sentence for searching relevant passages: ``
attached to SEARCH QUERIES ONLY. Documents must never carry it — prefixing a
document corrupts that document's vector for every future retrieval. So
``/embed`` forwards its text BARE, deliberately, and so does ``/documents``,
which embeds through ``/embed`` and therefore inherits the same invariant. The
prefix belongs on ``/search``, which does not exist yet, and nowhere else.
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
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.exc import SQLAlchemyError

from app import db, store
from app.config import SCHEMA_EMBEDDING_DIM

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

# How much of an upstream worker's error body may be echoed back to the client.
# See _summarise for why it is capped rather than passed through whole.
_MAX_UPSTREAM_DETAIL_CHARS = 200

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
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# The same rule for document entries, minus the stripping. Documents are not
# compared for equality against anything and a reranker scores whatever text it
# is given, so there is no reason to silently rewrite the caller's strings — only
# a reason to refuse an empty one, which would score as noise and, depending on
# the caller's mapping back to its own data, quietly corrupt a ranking.
NonBlankItem = Annotated[str, StringConstraints(min_length=1)]

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


def _summarise(text: str) -> str:
    """Reduce an upstream error body to one short, single-line description.

    Two things happen here that matter. Whitespace is collapsed, so a multi-line
    body cannot smuggle a wall of text into a JSON field the caller will print.
    And the result is capped at _MAX_UPSTREAM_DETAIL_CHARS, so what reaches the
    caller is a description rather than a dump — a worker's error body can be an
    entire page, and there is no reason for one client to receive it all.

    The FULL body is written to the server log by the caller of this function.
    That is the division of labour: the operator gets everything, the client gets
    enough to act on.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_UPSTREAM_DETAIL_CHARS:
        return collapsed[:_MAX_UPSTREAM_DETAIL_CHARS] + "..."
    return collapsed


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
        logger.warning("%s returned HTTP %s: %s", worker, exc.response.status_code, exc.response.text)
        summary = _summarise(exc.response.text)
        detail = f"{worker} returned HTTP {exc.response.status_code}"
        # A bare status code tells the caller nothing they can act on — HTTP 400
        # from the reranker could mean a typo in the model alias or an empty
        # document list, and those are different bugs. A capped, collapsed
        # excerpt distinguishes them. The cap is what keeps this a description
        # rather than a traceback pasted into a response body; the whole body,
        # including anything sensitive or enormous, went to the log line above.
        if summary:
            detail = f"{detail}: {summary}"
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

    One field, because this route does one thing. The moment /search exists it
    will need a batch and a `kind`, and that is the moment this model grows —
    not before. A field that no caller uses is a field every caller has to read
    past.
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
    # the prefix gets added to the query and to nothing else. It does not exist
    # yet. Until it does, the prefix appears in this file only in comments.
    #
    # The deliberate omissions, so that nobody re-litigates them later: no `kind`
    # field, no query/document variants of this route, no parameterised prefix.
    # Each was considered and rejected.
    """
    # The OpenAI-compatible request shape the embedder server accepts. "model" is
    # the alias registered at server start, not a filename and not a HF repo id.
    # "input" is a LIST even for a single string — that is the embeddings API's
    # shape, and sending a bare string is a shape it does not accept.
    payload = {
        "model": EMBEDDER_MODEL_ALIAS,
        # Bare. See the block above. Do not add the bge query prefix here.
        "input": [request.text],
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


@app.post(
    "/rerank",
    response_model=RerankResponse,
    summary="Score and rank documents against a query",
)
async def rerank(request: RerankRequest) -> RerankResponse:
    """Score every supplied document against the query, best first.

    Note what this does NOT do: it does not filter, and it does not truncate.
    Reranking is a re-ordering of the documents the caller already chose. Deciding
    which candidates are worth sending in the first place is retrieval's job, and
    doing it here would mean the reranker's opinion of a document it was never
    shown.

    Failure handling is identical to /embed's, and shares its helper rather than
    restating it: 504 on timeout, 502 on an unreachable worker or a non-2xx
    answer, the detail logged here and a short sentence returned. The reasons are
    the ones written on _post_upstream and they apply unchanged to this route.
    """
    payload: dict[str, Any] = {
        "model": RERANKER_MODEL_ALIAS,
        "query": request.query,
        # Forwarded in the caller's original order, unaltered. That order is what
        # the `index` values in the response refer to, so reordering here would
        # silently invalidate every index the worker sends back.
        "documents": request.documents,
    }

    if request.top_n is not None:
        # Added ONLY when the caller supplied one. See below for why the default
        # is absence rather than a number.
        payload["top_n"] = request.top_n
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

    # The caller's own identifier, and the upsert key. NonBlankText (strip, then
    # reject blank) for the same reason as everything else: a blank id is not a
    # usable primary key, and it is exactly the kind of bad row that is
    # invisible in a UI and permanent in the database.
    document_id: NonBlankText

    # The partition every retrieval query filters on. NonBlankText rather than
    # NonBlankItem: unlike a reranker document, a collection name is compared
    # for equality by the caller (they will pass the same string to /search
    # later), so silently rewriting it with `strip()` would create a collection
    # the caller cannot name. It is also belt-and-braces with the database's own
    # `documents_collection_not_blank` CHECK — validated here so the caller gets
    # a 422 naming the field instead of a constraint violation.
    collection: NonBlankText

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
    This route embeds `body.content` by calling the `/embed` handler directly,
    and `/embed` forwards its text BARE. See its docstring for the full
    reasoning; the one-line version is that bge-small-en-v1.5's instruction
    string was trained onto SEARCH QUERIES ONLY, and prefixing a document moves
    its vector off the manifold the other documents live on — permanently,
    invisibly, and with nothing in any response ever saying so.

    So the invariant, stated as an invariant: **the only string that reaches the
    embedder from this route is the caller's own `content`, unmodified.** There
    is no `kind` parameter here, no prefix constant, and no code path that could
    add one without rewriting this sentence and `main.embed`'s docstring
    together. The prefix belongs on `/search`, which does not exist yet.

    Calling `embed()` directly rather than reimplementing its body is
    deliberate. FastAPI's route decorators register a handler and return the
    function UNCHANGED, so `embed` is still an ordinary async function here —
    and calling it means this route inherits the worker's exact failure
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
    embedded = await embed(EmbedRequest(text=body.content))

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
