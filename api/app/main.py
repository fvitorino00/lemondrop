"""lemondrop API — the orchestrator in front of the two inference workers.

Architecture in one paragraph: `embedder` and `reranker` are stateless llama.cpp
servers that are NOT published to the host. They are reachable only from other
containers on the compose network, by service name. This API is the single door
to the outside world, and its job is to stand in front of them.

This phase deliberately delivers ONE route: ``GET /health``. There is no
database, no vector store and no /embed or /rerank here yet. A health endpoint
that reports the truth about its dependencies is the thing worth proving first —
if the API cannot tell you honestly whether the funnel is up, then nothing built
on top of it can be trusted either.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import FastAPI, Response, status
from pydantic import BaseModel

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

app = FastAPI(
    title="lemondrop API",
    version="0.1.0",
    description="Orchestrates the embedder and reranker inference workers.",
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
