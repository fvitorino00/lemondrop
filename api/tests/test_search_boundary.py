"""Service-free boundary tests for POST /search.

**NO SERVICES. NO DATABASE. NO WORKERS.** This module uses FastAPI's
``TestClient`` to exercise the /search route with every external collaborator
stubbed in memory. No container, socket, inference worker or PostgreSQL instance
is reached. The point is to pin the route-level guarantee that an over-long
query is refused at the edge with 422, while a query at the effective limit is
accepted and forwarded to the (stubbed) embedder with the bge query prefix
already attached.

The E5 fix changed how /search embeds its query: the prefix is added inside a
plain-string helper, and the edge validation is sized so the prefixed string
fits the worker budget. A service-free test is the only way to protect that
guarantee in the CI tier that actually runs (T1), because the live-stack tier
(T3) is deliberately not executed in CI.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db, store
from app.config import QUERY_PREFIX
from app.main import MAX_INFERENCE_INPUT_CHARS, app

# This constant was introduced by the E5 fix. Import it when it exists; compute
# the identical value from public constants when running against earlier code
# (for example in the discriminating scratch-copy experiment).
try:
    from app.main import MAX_SEARCH_QUERY_CHARS
except ImportError:  # pragma: no cover - pre-fix compatibility for the red test
    MAX_SEARCH_QUERY_CHARS = MAX_INFERENCE_INPUT_CHARS - len(QUERY_PREFIX)


class _StubEngine:
    """A database engine stand-in that satisfies the small surface used here.

    ``/search`` only checks that ``database.engine`` is truthy. ``db.close``
    calls ``engine.dispose()`` at shutdown, so the stub provides a no-op async
    dispose to keep teardown quiet.
    """

    async def dispose(self) -> None:
        pass


@pytest.fixture
def search_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient whose /search route sees only in-memory stubs.

    The lifespan is faked so it never creates a real engine or touches the
    vector-store codec registration. The returned client has ``app.state.database``
    set to a stub with an ``engine`` attribute, which is the state /search requires
    in order to proceed past its first dependency check.
    """

    engine = _StubEngine()

    async def fake_startup(settings: Any = None) -> db.Database:
        return db.Database(engine=engine, ready=True, problem="")

    async def fake_prepare_database(database: db.Database | None) -> bool:
        return True

    async def fake_retrieve(
        engine: Any,
        collection: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[store.Candidate]:
        # Return exactly one candidate so the rerank stage has something to score.
        # The content and distance values are arbitrary; the stubbed reranker
        # returns a fixed score and index below.
        return [
            store.Candidate(
                document_id="doc-1",
                collection=collection,
                content="candidate content",
                metadata={},
                distance=0.5,
            )
        ]

    monkeypatch.setattr("app.main.db.startup", fake_startup)
    monkeypatch.setattr("app.main.store.prepare_database", fake_prepare_database)
    monkeypatch.setattr("app.main.store.retrieve", fake_retrieve)

    with TestClient(app, raise_server_exceptions=False) as client:
        # The stubbed lifespan already set this, but restate it explicitly: the
        # test harness must show a database with an engine so the route proceeds.
        client.app.state.database = db.Database(
            engine=engine, ready=True, problem=""
        )
        yield client


def test_a_2048_character_search_query_is_a_422_not_a_500(
    search_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query above the search limit is refused at the edge and never reaches the handler."""
    calls: list[dict[str, Any]] = []

    async def fake_post_upstream(
        url: str, payload: dict[str, Any], worker: str
    ) -> dict[str, Any]:
        calls.append(payload)
        # The return value is irrelevant: an over-long query must fail before
        # the upstream is reached. Returning a valid shape keeps the test honest
        # if the contract ever changes.
        return {"data": [{"embedding": [0.0] * 384}]}

    monkeypatch.setattr("app.main._post_upstream", fake_post_upstream)

    response = search_client.post(
        "/search",
        json={"collection": "test-collection", "query": "x" * 2048},
    )

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/json"
    detail = response.json()["detail"]
    assert any(
        item["type"] == "string_too_long"
        and item["loc"] == ["body", "query"]
        and item.get("ctx", {}).get("max_length") == MAX_SEARCH_QUERY_CHARS
        for item in detail
    ), detail
    assert "Internal Server Error" not in response.text
    assert not calls, "an over-long query must not reach the upstream stub"


def test_a_query_at_the_search_limit_prefixes_the_embedder_input(
    search_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query of exactly MAX_SEARCH_QUERY_CHARS is accepted and prefixed before forwarding."""
    calls: list[dict[str, Any]] = []

    async def fake_post_upstream(
        url: str, payload: dict[str, Any], worker: str
    ) -> dict[str, Any]:
        calls.append(payload)
        if "input" in payload:
            # Embedder call: return a 384-dimensional embedding so the schema
            # width check in /search passes.
            return {"data": [{"embedding": [0.0] * 384}]}
        # Reranker call: score the single candidate at its original index.
        return {"results": [{"index": 0, "relevance_score": 1.0}]}

    monkeypatch.setattr("app.main._post_upstream", fake_post_upstream)

    query = "x" * MAX_SEARCH_QUERY_CHARS
    response = search_client.post(
        "/search",
        json={"collection": "test-collection", "query": query},
    )

    assert response.status_code == 200, response.text
    embed_payloads = [p for p in calls if "input" in p]
    assert len(embed_payloads) == 1, calls
    forwarded = embed_payloads[0]["input"][0]
    assert forwarded == QUERY_PREFIX + query
    assert len(forwarded) <= MAX_INFERENCE_INPUT_CHARS


def test_search_with_database_absent_returns_503(
    search_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no database on app.state the route returns 503, proving it reaches the handler."""
    calls: list[dict[str, Any]] = []

    async def fake_post_upstream(
        url: str, payload: dict[str, Any], worker: str
    ) -> dict[str, Any]:
        calls.append(payload)
        return {"data": [{"embedding": [0.0] * 384}]}

    monkeypatch.setattr("app.main._post_upstream", fake_post_upstream)

    # Remove the database from app.state, exactly as the control requires.
    del search_client.app.state.database

    response = search_client.post(
        "/search",
        json={"collection": "test-collection", "query": "x" * MAX_SEARCH_QUERY_CHARS},
    )

    assert response.status_code == 503, response.text
    assert "the database is not available" in response.text
    assert not calls, "a 503 must be returned before any upstream call"
