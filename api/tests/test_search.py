"""Tests for `POST /search`: the retrieval pipeline end to end, against real services.

What this file is: real PostgreSQL, real pgvector, real HTTP against the running
API, real llama.cpp workers behind it. No mocks, no in-process test client. The
same reason `test_documents.py` gives, and it applies more sharply to `/search`:
the thing under test is a FOUR-STAGE CHAIN — an embedder, a SQL filter, a
cross-encoder, and an index mapping that joins the two together. A mock at any
boundary agrees with the code by construction, and the failure that actually
matters here — every score attached to the wrong document, returning 200 with
plausible numbers — is one a mock would happily certify.

Preconditions, both of which must be true before pytest is invoked. From the
repository root:

    docker compose --profile devdb up -d --build postgres
    docker compose up -d --build api
    .venv/bin/python scripts/load_corpus.py
    set -a && . ./.env && set +a

**`docker compose up -d --build api` is mandatory for every test in sections 1-8.**
`/search` was added in this phase; an API image that predates it answers 404, and
`post_search` turns that into a failure naming the rebuild command. That is
correct behaviour rather than a broken test, and there is deliberately no
`pytest.skip()` in this file: a skipped test has stopped testing while still
reporting green, and green-that-means-nothing is worse than red, because red gets
read.

**No test in this file passes on a machine where nothing is running — all 26
require a database, including Section 0.** An earlier version of this docstring
claimed otherwise ("Section 0 ... needs no services at all and passes on a
machine where nothing is running"). That claim was false, and the fixture is
why. `_clean_probe_collection` is declared `@pytest.fixture(autouse=True)`, so
it empties this file's probe collection in the database before AND after
*every* test — it runs for Section 0's pure-configuration tests exactly as it
does for the live ones. With no database reachable it raises in SETUP, and the
test never reaches its own body.

Measured on this host, CPython 3.14.4 / pytest 9.1.1, exit status 1 both ways:

    env -u DATABASE_URL -u API_URL pytest api/tests/test_search.py
    → 26 errors in 2.16s

    DATABASE_URL=postgresql+asyncpg://...@127.0.0.1:<closed port>/lemondrop \
      API_URL=http://127.0.0.1:1 pytest api/tests/test_search.py
    → 26 errors in 8.84s

and the traceback for a Section 0 test — `test_a_coherent_funnel_is_accepted`,
whose body reads two environment variables and asserts on an `if` — lands at
`api/tests/test_search.py:245`, inside the fixture, not in the test.

This is why no test in this file is declared T1 in `.github/workflows/tests.yml`,
and why Section 0's five funnel tests are declared in T2 rather than T1: five
declarations that expand to 13 collected cases, all of them on the database side
of that line. The comment banner above Section 0 still says "No services
required", and it is wrong for the same reason; it has been left in place here
rather than fixed in a change scoped to this docstring.

What this file protects, in rough order of how much damage its absence causes:

* **The collection filter is real.** Asserted with an adversarial canary pair
  AND with an unfiltered control query, because "the other collection's twin did
  not appear" is satisfiable by a system that returned nothing at all.
* **Every score belongs to the document it was computed for.** The index-mapping
  trap, which fails silently and looks perfect.
* **The funnel is a bound, not a suggestion** — at most `RETRIEVAL_CANDIDATES`
  considered, at most `RERANK_TOP_K` returned, and a caller cannot widen either.
* **An empty collection does not reach the cross-encoder**, which on a `t3.micro`
  is the difference between one round trip and a wasted CPU inference.
* **Results are ordered, and the response says how many candidates were
  considered**, so a bad result set is explainable rather than mysterious.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

import pytest
import requests
from pgvector import Vector
from sqlalchemy import text

from app import config, db, store
from app.config import get_settings

# The API under test. Read from the environment with a localhost default,
# matching the convention in test_db.py, test_integration.py and
# test_documents.py.
BASE_URL = os.environ.get("API_URL", "http://localhost:8000")

START_DEVDB = "docker compose --profile devdb up -d --build postgres"
REBUILD_API = "docker compose up -d --build api"
LOAD_CORPUS = ".venv/bin/python scripts/load_corpus.py"

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "data" / "corpus.json"

INFRASTRUCTURE = "infrastructure"
IT_SUPPORT = "it-support"

# A collection the tests below WRITE to. Prefixed like test_documents.py's
# fixture collections, and for the same reason: a stray test run must not be able
# to collide with the real corpus, and a test's teardown must never be one typo
# away from deleting production data.
PROBE_COLLECTION = "search-probe-documents"

# A collection that exists in the schema and holds nothing. Not a typo: this name
# is queried, and "no rows" is the property under test. `/search` has no notion of
# a collection existing — see the empty-collection decision in main.search — so
# there is nothing to create; the name only has to be non-blank.
EMPTY_COLLECTION = "search-empty-probe"

# ── The funnel sizes these tests assert against ───────────────────────────────
#
# These are the CODE defaults, not a re-read of this process's environment, and
# the distinction is load-bearing. `docker-compose.yml`'s `api` service passes
# exactly two variables into the container — `DATABASE_URL` and `EMBEDDING_DIM` —
# so the container resolves `RETRIEVAL_CANDIDATES` and `RERANK_TOP_K` from
# `config.py`'s defaults no matter what this machine's `.env` says. A test that
# read the local environment would expect 50 (the stale value in this repo's
# `.env`) while the API correctly used 10, and would fail while reporting a
# configuration problem that does not exist.
#
# If `docker-compose.yml` ever gains these variables, this is the line to change,
# and the assertion in `test_the_api_runs_the_configured_funnel` says so out loud.
CONFIGURED_CANDIDATES = config.DEFAULT_RETRIEVAL_CANDIDATES
CONFIGURED_TOP_K = config.DEFAULT_RERANK_TOP_K

# Generous: /search embeds a query and then has the CPU-only cross-encoder score
# every candidate. On a t3.micro that is seconds, not milliseconds, and the
# reranker's own budget is INFERENCE_TIMEOUT_SECONDS (120).
SEARCH_TIMEOUT_SECONDS = 180


# ── Helpers ───────────────────────────────────────────────────────────────────
#
# `with_database`, `engine_of` and `database_settings` deliberately repeat the
# pair from test_documents.py rather than importing them, for the reason that
# file gives: the versions needed here are not the same, and a shared helper
# that grew a flag to serve a second file would couple two files that test
# different things and make both harder to read. There is no `prepare_codecs`
# switch here because no test in this file writes a vector — it only reads them.


def database_settings():
    """Build settings from the environment, failing with a usable message.

    Same wrapper as the other two files', including the same reason: the message
    has to survive `get_settings()`'s own long one, because the operator reading
    a failure needs the "is the devdb up?" line more than they need the DSN
    advice.
    """
    try:
        return get_settings()
    except RuntimeError as exc:
        pytest.fail(f"{exc}\n\nIf it is set but wrong, check the devdb is up:\n    {START_DEVDB}")


def with_database(action: Callable[[db.Database], Coroutine[Any, Any, Any]]) -> Any:
    """Run `action` against a started `Database` in ONE event loop, then dispose.

    The single `asyncio.run` is not stylistic: an `AsyncEngine` binds its pool to
    the loop running when it was created, so starting in one loop and closing in
    another is precisely the "attached to a different loop" failure `db.startup`
    warns about. A failing test must not leave a pool holding real connections,
    so the `finally` is not optional.

    `store.prepare_database` is called and there is deliberately NO switch to turn
    it off. The comment above that function in test_documents.py says a pool
    without the pgvector codec can be produced by not arming it — but it also says
    why arming is not optional, and that reason applies to a test that READS a
    vector exactly as much as to one that writes one: asyncpg's codec is per
    CONNECTION, so `store.retrieve` on an unarmed pool raises
    `DataError: invalid input for query argument $1 ... (expected str, got Vector)`
    — a message that reads like a driver bug and is really a missing
    registration. Measured, not assumed: that is the failure this file produced
    before `prepare_database` was added here.
    """

    async def _run() -> Any:
        database = await db.startup(database_settings())
        try:
            await store.prepare_database(database)
            return await action(database)
        finally:
            await db.close(database)

    return asyncio.run(_run())


def engine_of(database: db.Database):
    """The engine, asserted present — so the failure names the real cause."""
    engine = database.engine
    if engine is None:
        pytest.fail(f"no database engine: {database.problem}\n    {START_DEVDB}")
    return engine


def post_search(payload: dict[str, Any]) -> requests.Response:
    """POST to `/search`, turning "route not deployed" into a readable failure.

    A bare 404 is ambiguous — the path could be wrong in this test, or the
    running image predates the route — and the two have completely different
    fixes. Naming the rebuild command in the failure is what makes it diagnosable
    in one read. This is the same convention as `post_document` in
    test_documents.py, for the same reason.
    """
    response = requests.post(f"{BASE_URL}/search", json=payload, timeout=SEARCH_TIMEOUT_SECONDS)

    if response.status_code == 404:
        pytest.fail(
            "POST /search does not exist — the running API image predates this "
            f"phase.\nRebuild and restart it:\n    {REBUILD_API}\n"
            f"Then load the corpus if you have not already:\n    {LOAD_CORPUS}"
        )

    return response


def search(collection: str, query: str, **extra: Any) -> requests.Response:
    """A well-formed `/search` body, with overrides for the tests that need one."""
    payload: dict[str, Any] = {"collection": collection, "query": query}
    payload.update(extra)
    return post_search(payload)


def embed_text(text_to_embed: str) -> list[float]:
    """A vector from `/embed`, which forwards text BARE by definition.

    Used by the tests that need to reproduce a stage of the pipeline
    independently. Going through the public route — rather than the worker — is
    deliberate: this is the same call `main.search` makes, so a test that
    disagreed with the route about how to embed would be testing a fiction.
    """
    response = requests.post(f"{BASE_URL}/embed", json={"text": text_to_embed}, timeout=SEARCH_TIMEOUT_SECONDS)
    assert response.status_code == 200, f"/embed returned {response.status_code}: {response.text[:300]}"
    return [float(value) for value in response.json()["embedding"]]


def corpus_documents() -> dict[str, dict[str, Any]]:
    """The corpus file, keyed by id. Read here so the tests can name real documents."""
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return {document["id"]: document for document in corpus["documents"]}


def collection_counts() -> dict[str, int]:
    """How many documents the database actually holds per collection.

    Every count-based assertion below is downstream of this. A test that asserts
    "ten candidates were considered" is vacuous against an empty collection, and
    a test that asserts "no it-support document appeared" is satisfied by a
    system that stored nothing at all — the failure mode `store.retrieve`'s
    docstring is written about.
    """
    return with_database(lambda database: store.count_by_collection(engine_of(database)))


@pytest.fixture(autouse=True)
def _clean_probe_collection():
    """Empty this file's own write-target collection before and after every test.

    At setup as well as teardown, for the reason test_documents.py gives: a row
    left behind by a failed run would make the NEXT run's counts wrong, and a
    leftover document in `infrastructure` or `it-support` would silently change
    what the isolation and ordering tests are asserting about.
    """
    with_database(lambda database: store.delete_collection(engine_of(database), collection=PROBE_COLLECTION))
    yield
    with_database(lambda database: store.delete_collection(engine_of(database), collection=PROBE_COLLECTION))


# ── 0. The funnel's configuration rules. A DATABASE is required. ──────────────
#
# These tests are pure configuration logic: they read two environment variables
# and assert on an `if`. That is exactly why this banner used to say "No services
# required", and why it was wrong — it was corrected in e3e7d25 together with this
# module's docstring, and the correction is not confined to the docstring.
#
# They DO need a database. `_clean_probe_collection` above is declared
# `@pytest.fixture(autouse=True)` and empties this file's probe collection before
# AND after every test — these tests exactly as much as the live ones. With no
# database reachable the fixture raises in SETUP and the test never reaches its
# own body, so the purity of the body is irrelevant to whether the test can run.
#
# Measured on this host with a well-formed DSN pointed at a closed port: all 13
# collected cases of this section ERROR AT SETUP. e3e7d25 measured the whole file
# the same way and got 26 errors, because the fixture is autouse and the other 13
# tests fail at setup for the same reason. This is why no test in this file is
# declared T1 in `.github/workflows/tests.yml`, and why this section's five funnel
# tests are declared in T2 — five declarations expanding to 13 collected cases,
# all of them on the database side of that line.
#
# The distinction the old banner was reaching for, now stated accurately: no
# running API, no llama.cpp worker and no model are needed here. A database is.


@pytest.mark.parametrize(
    ("candidates", "top_k"),
    [
        (10, 5),  # the shipped configuration
        (50, 50),  # equal is legal: the last candidate may be returned
        (5, 1),
        (1, 1),  # the floor
        (1000, 3),
    ],
)
def test_a_coherent_funnel_is_accepted(monkeypatch: pytest.MonkeyPatch, candidates: int, top_k: int):
    monkeypatch.setenv(config.RETRIEVAL_CANDIDATES_ENV_VAR, str(candidates))
    monkeypatch.setenv(config.RERANK_TOP_K_ENV_VAR, str(top_k))

    funnel = config.funnel_from_environment()

    assert funnel.retrieval_candidates == candidates
    assert funnel.rerank_top_k == top_k


@pytest.mark.parametrize(
    ("candidates", "top_k", "must_mention"),
    [
        (10, 20, "RERANK_TOP_K"),
        (3, 4, "RERANK_TOP_K"),
        (0, 5, "RETRIEVAL_CANDIDATES"),
        (-1, 5, "RETRIEVAL_CANDIDATES"),
        (10, 0, "RERANK_TOP_K"),
    ],
)
def test_an_incoherent_funnel_is_refused_and_the_message_names_both_values(
    monkeypatch: pytest.MonkeyPatch, candidates: int, top_k: int, must_mention: str
):
    """A `top_k` above the candidate count is a configuration error, not a runtime surprise.

    ── WHY THIS MUST NOT BE CLAMPED ────────────────────────────────────────────
    A caller asking for a `top_k` above the server's maximum is asking for LESS
    work than the server is willing to do, and clamping is right there (see
    `Funnel.clamped`). A CONFIGURATION that says `RERANK_TOP_K=20` with
    `RETRIEVAL_CANDIDATES=10` is different: it is arithmetically unsatisfiable,
    and the honest response to an unsatisfiable configuration is to refuse to
    start rather than to serve a shorter list than the operator wrote down, on
    every query, with a 200 and nothing in the body saying the configured number
    was unreachable.

    Both numbers must appear in the message, because the fix is a comparison
    between them. A message naming only the offending one sends the operator to
    look up the other — the very thing they were about to get wrong.
    """
    monkeypatch.setenv(config.RETRIEVAL_CANDIDATES_ENV_VAR, str(candidates))
    monkeypatch.setenv(config.RERANK_TOP_K_ENV_VAR, str(top_k))

    with pytest.raises(ValueError) as caught:
        config.funnel_from_environment()

    message = str(caught.value)
    assert must_mention in message, f"the message does not name {must_mention}: {message}"
    assert config.RETRIEVAL_CANDIDATES_ENV_VAR in message, (
        f"the message does not name {config.RETRIEVAL_CANDIDATES_ENV_VAR}: {message}"
    )
    assert str(candidates) in message, f"the message does not print the candidate count: {message}"
    assert str(top_k) in message, f"the message does not print the top_k: {message}"


def test_a_non_numeric_funnel_value_is_refused_with_a_message_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
):
    """`.env` values are strings; a typo must say which variable and what it is."""
    monkeypatch.setenv(config.RETRIEVAL_CANDIDATES_ENV_VAR, "ten")
    monkeypatch.setenv(config.RERANK_TOP_K_ENV_VAR, "5")

    with pytest.raises(ValueError) as caught:
        config.funnel_from_environment()

    assert config.RETRIEVAL_CANDIDATES_ENV_VAR in str(caught.value)
    assert str(config.DEFAULT_RETRIEVAL_CANDIDATES) in str(caught.value), (
        "the message should say what the value is supposed to look like, not just "
        "that the variable is wrong"
    )


def test_settings_reports_the_funnel_and_refuses_an_incoherent_pair():
    """`Settings` carries both numbers, and validates them through the same rules.

    A separate check from the one above because `Settings` is a DIFFERENT object
    with its OWN copy of the two values: it is what a `repr(settings)` shows an
    operator, and a settings repr that described a database and an embedding
    width but not the size of a search would hide the one number needed to debug
    a slow search. The pair is validated by constructing the same `Funnel`, so
    there is one definition of "coherent" rather than two that could drift.
    """
    settings = get_settings()

    assert settings.retrieval_candidates >= 1
    assert settings.rerank_top_k >= 1
    assert settings.rerank_top_k <= settings.retrieval_candidates, (
        f"Settings accepted rerank_top_k={settings.rerank_top_k} with "
        f"retrieval_candidates={settings.retrieval_candidates}"
    )

    from pydantic import SecretStr, ValidationError

    with pytest.raises(ValidationError) as caught:
        type(settings)(
            database_url=SecretStr("postgresql+asyncpg://u:p@127.0.0.1:5432/d"),
            embedding_dim=384,
            retrieval_candidates=5,
            rerank_top_k=50,
        )

    assert "RERANK_TOP_K" in str(caught.value)


def test_a_caller_can_narrow_the_funnel_and_can_never_widen_it():
    """`Funnel.clamped` is the whole of the caller's authority, and it only subtracts.

    Three cases, all of them load-bearing:

    * nothing supplied → the CONFIGURED numbers, which is what makes the
      configuration the default rather than a suggestion;
    * less supplied → honoured, so a caller can ask for a cheap search;
    * more supplied → truncated to the configured maximum, so a caller cannot
      make this service spend more inference than its operator sized it for on a
      host whose memory headroom is already documented as tight.

    The last case is the one worth arguing for: a 422 would also be defensible,
    but it would mean a client has to know the server's configuration to be
    well-formed and would have to change its code when `.env` changes. Asking for
    more than the server will compute is not an error; it is a request the server
    satisfies as fully as it can.
    """
    funnel = config._build_funnel(10, 5)

    assert funnel.clamped(candidates=None, top_k=None) == (10, 5)
    assert funnel.clamped(candidates=3, top_k=2) == (3, 2)
    assert funnel.clamped(candidates=50, top_k=None) == (10, 5)
    assert funnel.clamped(candidates=None, top_k=99) == (10, 5)
    assert funnel.clamped(candidates=999, top_k=999) == (10, 5)
    # More results than candidates is arithmetically impossible, so it is capped
    # rather than reported: the reranker cannot produce 5 results from 2
    # documents, and a response claiming it could would be claiming an arithmetic.
    assert funnel.clamped(candidates=2, top_k=5) == (2, 2)


# ── The corpus and the canaries ──────────────────────────────────────────────


CANARY_PAIRS = [
    # (infrastructure id, it-support id) — near-duplicates by construction, so
    # a search that leaked across the filter would surface the twin.
    ("infra-aws-iam-key-rotation", "support-service-account-password-rotation"),
    ("infra-rds-snapshot-restore", "support-workstation-backup-and-restore"),
    ("infra-security-group-ingress", "support-admin-console-access-grant"),
    ("infra-drain-unhealthy-target", "support-departing-employee-access-removal"),
]


def test_the_corpus_is_loaded_enough_for_every_assertion_below_to_mean_something():
    """Both collections are really populated, at their documented sizes.

    First in the file for the reason `store.retrieve`'s docstring gives: a test
    that asserts "the other collection's document did not appear" is satisfied by
    a system that stored nothing at all, and a test that asserts "ten candidates
    were considered" is vacuous against an empty collection. Everything below is
    downstream of these counts, so they are asserted once, here, loudly.
    """
    counts = collection_counts()

    assert counts.get(INFRASTRUCTURE) == 20, (
        f"{INFRASTRUCTURE} holds {counts.get(INFRASTRUCTURE)} documents, expected 20. "
        f"Load the corpus:\n    {LOAD_CORPUS}\nEvery count-based assertion in this "
        "file is vacuous without it."
    )
    assert counts.get(IT_SUPPORT) == 20, (
        f"{IT_SUPPORT} holds {counts.get(IT_SUPPORT)} documents, expected 20. "
        f"Load the corpus:\n    {LOAD_CORPUS}"
    )


# ── 1. The full pipeline, end to end ─────────────────────────────────────────
#
# ── FROM HERE DOWN, EVERY TEST NEEDS THE REBUILT API IMAGE ───────────────────


def test_the_bge_query_prefix_is_the_default_and_is_not_a_per_request_setting():
    """The prefix is a constant of the MODEL, so it is one constant, not a field.

    Two things are asserted, and the second is the one that matters.

    The first is that the prefix this test process would apply is the default
    one. The second is that `SearchRequest` has no field through which a caller
    could change it, send a document's text through the query side, or omit it.

    Worth its own test because the failure it guards against is invisible: a
    prefix parameter would be a feature nobody would notice until recall quietly
    degraded, and "no `kind`, no parameterised prefix" is a decision `main.embed`
    records as considered and rejected — so the schema is where it has to be
    enforced.
    """
    assert config.QUERY_PREFIX == config.DEFAULT_QUERY_PREFIX
    assert config.QUERY_PREFIX.endswith(" "), (
        "the trailing space is part of bge's instruction string; the query is "
        "QUERY_PREFIX + text, with no separator added between them"
    )

    schema_response = requests.get(f"{BASE_URL}/openapi.json", timeout=30)
    assert schema_response.status_code == 200, (
        f"/openapi.json returned {schema_response.status_code}. If this is 404, the "
        f"running image predates /search:\n    {REBUILD_API}"
    )
    schema = schema_response.json()
    assert "/search" in schema["paths"], (
        f"the running image serves no /search route:\n    {REBUILD_API}"
    )
    search_body = schema["components"]["schemas"]["SearchRequest"]["properties"]
    assert set(search_body) == {"collection", "query", "candidates", "top_k"}, (
        f"SearchRequest's fields changed: {sorted(search_body)}. There is to be no "
        "`kind` and no `prefix` — see main.embed's docstring, where both were "
        "considered and rejected."
    )


def test_a_relevant_query_returns_the_relevant_document_first_in_the_right_collection():
    """Search the live corpus; the genuinely relevant runbook comes back first.

    Nothing is ingested, mocked or seeded: this is the corpus that
    `scripts/load_corpus.py` loaded, queried through HTTP, ranked by the real
    cross-encoder.

    The query is chosen to be unambiguous about WHICH document is correct
    (`support-recycle-bin-file-recovery`, the only corpus document about
    recovering deleted files from a Recycle Bin) and to share vocabulary with
    nothing else. A vague query would make this test a claim about the model's
    taste rather than about the pipeline.
    """
    query = "how do I recover files a user deleted from the Recycle Bin on their workstation"

    response = search(IT_SUPPORT, query)

    assert response.status_code == 200, f"{response.status_code}: {response.text[:500]}"
    body = response.json()

    assert body["results"], f"the search returned nothing: {body}"
    assert len(body["results"]) <= CONFIGURED_TOP_K

    best = body["results"][0]
    assert best["document_id"] == "support-recycle-bin-file-recovery", (
        f"the top result was {best['document_id']!r}, not the document that actually "
        f"answers the query. Ranked: {[r['document_id'] for r in body['results']]}"
    )
    assert best["collection"] == IT_SUPPORT
    assert "recycle bin" in best["content"].lower()
    # Every result carries the collection it was scoped to, and every result
    # echoes the collection that was searched — the provenance a caller needs to
    # believe the filter held.
    assert {result["collection"] for result in body["results"]} == {IT_SUPPORT}
    assert body["collection"] == IT_SUPPORT
    assert body["candidates_considered"] > 0
    assert body["model"], "the reranker alias is echoed so scores can be attributed"


# ── 2. The funnel is a bound ─────────────────────────────────────────────────


def test_the_api_runs_the_configured_funnel():
    """State the expected numbers out loud, and check the API against them.

    See the comment on `CONFIGURED_CANDIDATES`: `docker-compose.yml` passes only
    `DATABASE_URL` and `EMBEDDING_DIM` into the `api` container, so the funnel
    the API uses comes from `config.py`'s defaults. This test exists to make that
    assumption FALSIFIABLE — if compose ever gains the variables, this fails and
    says what to change, instead of the test above failing for a reason that
    looks like a search bug.
    """
    assert (CONFIGURED_CANDIDATES, CONFIGURED_TOP_K) == (10, 5), (
        "the funnel defaults changed. If docker-compose.yml still passes only "
        "DATABASE_URL and EMBEDDING_DIM to the api container, update "
        "CONFIGURED_CANDIDATES/CONFIGURED_TOP_K here and the counts asserted "
        "below."
    )

    response = search(INFRASTRUCTURE, "rotate a credential")
    assert response.status_code == 200, f"{response.status_code}: {response.text[:300]}"
    body = response.json()
    assert body["candidates_considered"] == CONFIGURED_CANDIDATES, (
        f"the API considered {body['candidates_considered']} candidates; the "
        f"configured maximum is {CONFIGURED_CANDIDATES}"
    )


def test_the_funnel_is_capped_and_a_caller_cannot_widen_it():
    """Ten considered, five returned, and a caller's larger number is truncated.

    ── WHY THE COUNT MATTERS MORE THAN THE LIST ────────────────────────────────
    `infrastructure` holds 20 documents and stage 1 is asked for 10. Asserting
    only "some results came back" would pass against a funnel that returned
    everything and let the reranker sort it — 20 candidates, 5 results, a 200,
    and no visible evidence that five times the cross-encoder work was done on a
    box with roughly 280Mi of headroom. `candidates_considered` is the number
    that makes the bound observable from outside.

    ── WHY THE CALLER CASES ARE IN THE SAME TEST ───────────────────────────────
    Because "the default is bounded" and "a caller cannot unbound it" are the same
    claim. A funnel that clamps its own default but honours a caller's larger
    number has no bound at all — the configured maximum would be a default
    rather than a limit, and the test above would keep passing.
    """
    counts = collection_counts()
    assert counts[INFRASTRUCTURE] > CONFIGURED_CANDIDATES, (
        "infrastructure holds fewer documents than the funnel's candidate limit, "
        "so 'the limit was enforced' and 'the collection ran out' are the same "
        "observation and this test cannot tell them apart"
    )

    default_response = search(INFRASTRUCTURE, "restore a database from a snapshot")
    assert default_response.status_code == 200, default_response.text[:300]
    default_body = default_response.json()

    assert default_body["candidates_considered"] == CONFIGURED_CANDIDATES == 10, (
        f"stage 1 considered {default_body['candidates_considered']} documents out of "
        f"{counts[INFRASTRUCTURE]} available; the configured limit is {CONFIGURED_CANDIDATES}"
    )
    assert len(default_body["results"]) == CONFIGURED_TOP_K == 5, (
        f"{len(default_body['results'])} results returned, expected {CONFIGURED_TOP_K}"
    )

    # A caller may ask for LESS.
    narrow = search(INFRASTRUCTURE, "restore a database from a snapshot", candidates=3, top_k=2)
    assert narrow.status_code == 200, narrow.text[:300]
    narrow_body = narrow.json()
    assert narrow_body["candidates_considered"] == 3, (
        f"asked for 3 candidates, the API considered {narrow_body['candidates_considered']}"
    )
    assert len(narrow_body["results"]) == 2

    # A caller may NOT ask for MORE. Truncated, not refused — see
    # `Funnel.clamped` for why.
    wide = search(INFRASTRUCTURE, "restore a database from a snapshot", candidates=999, top_k=999)
    assert wide.status_code == 200, wide.text[:300]
    wide_body = wide.json()
    assert wide_body["candidates_considered"] == CONFIGURED_CANDIDATES, (
        f"a caller asked for 999 candidates and the API considered "
        f"{wide_body['candidates_considered']}. The configured maximum is a LIMIT, "
        "not a default: honouring a larger number would let any client spend more "
        "cross-encoder time than the operator sized this host for."
    )
    assert len(wide_body["results"]) == CONFIGURED_TOP_K

    # And a caller asking for more results than candidates gets the candidates'
    # worth, not an impossible number.
    impossible = search(INFRASTRUCTURE, "restore a database from a snapshot", candidates=2, top_k=5)
    assert impossible.status_code == 200, impossible.text[:300]
    assert len(impossible.json()["results"]) == 2


# ── 3. Collection isolation, against the canary pairs ────────────────────────


def test_the_collection_filter_holds_against_the_adversarial_canary_pairs():
    """The twin never appears; and it WOULD have, without the filter.

    ── WHY THE SECOND HALF IS THE TEST ─────────────────────────────────────────
    "The it-support twin did not come back" is satisfied by a system that
    returned nothing, by a system that stored nothing, and by a system whose
    ranking is simply good. None of those is isolation.

    What makes it isolation is the CONTROL: the same query, run as ONE global
    vector search across every document with no collection predicate at all — the
    fetch-then-filter implementation `store.retrieve`'s docstring rejects —
    returns the twin inside the top 10. So the twin is genuinely competitive for
    this query, and its absence from the scoped search is the filter working
    rather than the query failing to match.

    The control is also what exposes the OTHER failure mode, the one that
    isolation-only tests cannot see: a global shortlist of 10 drawn from both
    collections contains few infrastructure documents at all, so a
    fetch-then-filter would not merely leak the twin — it would starve the
    collection the caller actually asked for. Both counts are asserted.
    """
    for infrastructure_id, twin_id in CANARY_PAIRS:
        infrastructure_doc = corpus_documents()[infrastructure_id]
        twin_doc = corpus_documents()[twin_id]

        # A query drawn from the shared concept of the pair — the wording both
        # documents use, which is the point of them being canaries.
        query = _concept_query(infrastructure_doc, twin_doc)

        response = search(INFRASTRUCTURE, query)
        assert response.status_code == 200, f"{response.status_code}: {response.text[:300]}"
        body = response.json()

        returned_ids = [result["document_id"] for result in body["results"]]

        assert twin_id not in returned_ids, (
            f"searching {INFRASTRUCTURE} returned {twin_id!r}, which lives in "
            f"{IT_SUPPORT}. Returned: {returned_ids}"
        )
        assert set(result["collection"] for result in body["results"]) <= {INFRASTRUCTURE}
        assert body["collection"] == INFRASTRUCTURE

        # ── THE CONTROL: the same query, with NO collection predicate ──────────
        # This is deliberately raw SQL rather than `store.retrieve`: retrieve()
        # takes the collection as a required parameter precisely because the
        # predicate belongs in SQL, so the unfiltered shortlist it describes
        # cannot be produced through it. This query IS that shortlist.
        query_embedding = embed_text(config.QUERY_PREFIX + query)
        unfiltered = with_database(
            lambda database: _global_shortlist(
                engine_of(database), query_embedding, limit=CONFIGURED_CANDIDATES
            )
        )
        unfiltered_ids = [identifier for identifier, _ in unfiltered]

        assert twin_id in unfiltered_ids, (
            f"{twin_id!r} is not in the global top {CONFIGURED_CANDIDATES} for this "
            f"query, so its absence from the scoped search proves nothing. Pick a "
            f"canary pair whose twins are genuinely competitive. Global: {unfiltered_ids}"
        )

        # And the starvation half: how much of the unfiltered shortlist belongs to
        # the collection the caller actually asked for.
        infrastructure_in_global = sum(
            1 for identifier, _ in unfiltered if identifier.startswith("infra-")
        )
        assert infrastructure_in_global < CONFIGURED_CANDIDATES, (
            f"{infrastructure_in_global} of the global top {CONFIGURED_CANDIDATES} "
            f"already belong to {INFRASTRUCTURE}, so a fetch-then-filter would have "
            "filled the whole candidate list from the right collection and this "
            "canary pair would prove nothing. Pick a more competitive query."
        )


def _concept_query(infrastructure_doc: dict[str, Any], twin_doc: dict[str, Any]) -> str:
    """A query naming the shared concept of a canary pair, in the caller's words.

    Taken from the two documents' own titles rather than written by hand, because
    a hand-written query that happens to match one document strongly would turn
    the control above into a tautology. The titles of the five canary pairs are
    deliberately parallel, so the shared noun is in both.
    """
    return f"{infrastructure_doc['metadata']['title']} / {twin_doc['metadata']['title']}"


async def _global_shortlist(engine: Any, query_embedding: list[float], limit: int) -> list[tuple[str, float]]:
    """The nearest documents across the WHOLE table, with no collection filter.

    This is the implementation `store.retrieve` refuses to be: a global top-N,
    which a later caller would filter in Python. Written here so the control has
    somewhere to run, and so its existence is a standing reminder that the two
    are different queries with different failure modes.

    Async, and awaited from inside `with_database`'s single event loop rather
    than given an `asyncio.run` of its own: an `AsyncEngine` is bound to the loop
    that built it, and a nested `asyncio.run` would raise "cannot be called from a
    running event loop" — which is at least a loud failure, but a confusing one.

    The query vector is passed as a `Vector`, exactly as `store.retrieve` passes
    it, because `with_database` arms this pool with the pgvector codec and a
    codec-registered connection DECODES a text representation as a malformed
    list: passing `Vector(...).to_text()` here raised
    `DataError: invalid input for query argument $1: '[-0.05...' (expected list or
    ndarray)`. Measured, not reasoned — the two representations are only
    interchangeable on an UNARMED pool.
    """
    statement = text(
        "SELECT id, (embedding <=> CAST(:query AS vector)) AS distance "
        "FROM documents ORDER BY distance LIMIT :limit"
    )
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                statement,
                {"query": Vector(query_embedding), "limit": limit},
            )
        ).all()
    return [(str(row.id), float(row.distance)) for row in rows]


# ── 4. Ordering ──────────────────────────────────────────────────────────────


def test_results_are_ordered_by_descending_relevance_score():
    """Scores must be monotonically non-increasing down the list.

    Walked as CONSECUTIVE PAIRS, the way
    `test_integration.py::test_rerank_results_are_sorted_best_first` walks them,
    because a pair-wise assertion is the one that cannot be satisfied by a list
    that is sorted somewhere in the middle.

    Ordering is also what makes truncation meaningful. If the list were in score
    order, `[:top_k]` is the best five. In any other order it is an arbitrary
    five, and the caller gets the same 200 either way.
    """
    response = search(
        INFRASTRUCTURE,
        "the load balancer target is unhealthy and needs to be drained",
    )
    assert response.status_code == 200, response.text[:300]
    results = response.json()["results"]

    assert len(results) >= 2, (
        f"only {len(results)} result(s); a monotonicity assertion over one element "
        "is vacuous. Pick a query that matches more of the corpus."
    )

    scores = [float(result["relevance_score"]) for result in results]
    for earlier, later in zip(scores, scores[1:]):
        assert earlier >= later, (
            f"results are not in descending score order: {scores}. A caller "
            "truncating this list to top_k would get an arbitrary subset."
        )

    # The same walk on the stage-1 numbers, which arrive in distance order (lower
    # is better) and are NOT expected to survive reranking in the same order —
    # which is the entire reason stage 2 exists. Asserting monotonicity there
    # would be asserting that reranking does nothing.
    distances = [float(result["distance"]) for result in results]
    assert all(distance == distance for distance in distances), (
        f"a NaN distance means a null vector survived into the results: {distances}"
    )


# ── 5. The empty collection ──────────────────────────────────────────────────


def test_an_empty_collection_returns_200_with_no_results_and_never_reaches_the_reranker():
    """Empty in, 200 out, zero candidates — and no cross-encoder call.

    ── WHY TWO INDEPENDENT PIECES OF EVIDENCE FOR "NO RERANKER CALL" ───────────
    The response's `candidates_considered == 0` is the structural claim: it is
    what the route reports, and it is the same number the route branches on. The
    timing is the behavioural one: an empty search does one embedding and one
    indexed `SELECT`, while a ten-document rerank is a cross-encoder running on
    a CPU-only box. If the reranker were being called, the empty search would be
    slower than the non-empty one — which is absurd on its face and therefore a
    good thing to assert.

    The timing bound is the reranker's own measured cost for the same number of
    documents, obtained in the same test rather than hardcoded, so it cannot rot
    when the host gets faster or slower.
    """
    empty = search(EMPTY_COLLECTION, "anything at all")
    assert empty.status_code == 200, f"{empty.status_code}: {empty.text[:300]}"
    empty_body = empty.json()

    assert empty_body["results"] == []
    assert empty_body["candidates_considered"] == 0
    assert empty_body["collection"] == EMPTY_COLLECTION, (
        "the collection must be echoed even for an empty result, or a typo'd "
        "collection name is invisible"
    )

    # ── THE TIMING CONTROL ─────────────────────────────────────────────────────
    # What a real ten-document rerank costs, measured now, on this host.
    candidates = with_database(
        lambda database: _shortlist_contents(engine_of(database), INFRASTRUCTURE, CONFIGURED_CANDIDATES)
    )
    baseline_start = time.monotonic()
    reranked = requests.post(
        f"{BASE_URL}/rerank",
        json={"query": "anything at all", "documents": candidates},
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    baseline_seconds = time.monotonic() - baseline_start
    assert reranked.status_code == 200, f"the baseline /rerank failed: {reranked.text[:300]}"
    assert len(reranked.json()["results"]) == CONFIGURED_CANDIDATES

    empty_start = time.monotonic()
    again = search(EMPTY_COLLECTION, "anything at all")
    empty_seconds = time.monotonic() - empty_start
    assert again.status_code == 200

    assert empty_seconds < baseline_seconds, (
        f"an empty search took {empty_seconds:.3f}s while scoring "
        f"{CONFIGURED_CANDIDATES} documents took {baseline_seconds:.3f}s. The empty "
        "path is doing at least as much work as the expensive path, which means "
        "the reranker is being called with an empty list."
    )


async def _shortlist_contents(engine: Any, collection: str, limit: int) -> list[str]:
    """The contents of `limit` documents in `collection`, for a rerank baseline.

    No vector work at all: this exists only to give the reranker a realistic
    payload of real corpus documents, so the timing baseline above is a
    cross-encoder measurement and not a measurement of how fast the API rejects
    nonsense.
    """
    statement = text("SELECT content FROM documents WHERE collection = :collection LIMIT :limit")
    async with engine.connect() as connection:
        rows = (await connection.execute(statement, {"collection": collection, "limit": limit})).all()
    return [str(row.content) for row in rows]


def test_a_collection_name_that_does_not_exist_is_an_empty_result_not_an_error():
    """The documented trade-off, asserted so it cannot change silently.

    `/search` has no notion of a collection existing, so a typo'd name returns
    200 with no results. That is a real trade-off — the caller cannot tell "no
    document matched" from "no such collection" — accepted in `main.search`'s
    docstring in exchange for one round trip, no TOCTOU race against a free-text
    partition key, and conventional semantics.

    This test exists so that the trade-off is a DECISION on the record rather
    than an accident: if someone adds a 404 here, this fails and says what the
    alternative would cost.
    """
    response = search("this-collection-was-never-created", "restore a database")

    assert response.status_code == 200, (
        f"a collection that does not exist returned {response.status_code}. Either "
        "this is the intended change (and the empty-collection decision in "
        "main.search's docstring needs rewriting) or it is a regression."
    )
    assert response.json()["results"] == []
    assert response.json()["candidates_considered"] == 0


# ── 6. Invalid input ─────────────────────────────────────────────────────────


def test_a_blank_query_or_collection_is_a_422_not_a_500():
    """Bad input is the CALLER's fault, so the status must say so.

    A 500 here would mean the blank value reached a layer that could not cope —
    almost certainly the embedder, spending a real inference call on an empty
    string. The caller would get a server error for their own bad input, which is
    both the wrong status code and the wrong blame.

    Every variant is checked in one test because they share one failure mode and
    one fix; splitting them would give several copies of the same assertion and
    several chances to forget a case. Whitespace-only is checked alongside empty
    because `NonBlankText` strips BEFORE `min_length`, and that ordering is what
    makes `"   "` invalid — `min_length` alone would accept it — and an ABSENT
    field is checked alongside both because "missing" and "blank" are different
    failures with the same right answer.
    """
    # `None` as a value means "leave this key OUT of the body", which is a
    # different case from an empty string: one is a field that is not there, the
    # other is a field that is there and says nothing. Writing them with the same
    # `""` would silently test only one of them.
    invalid_bodies: list[dict[str, Any]] = [
        {"collection": IT_SUPPORT, "query": "   "},
        {"collection": IT_SUPPORT, "query": ""},
        {"collection": "   ", "query": "restore a database"},
        {"collection": "", "query": "restore a database"},
        {"collection": None, "query": "restore a database"},  # no collection at all
        {"collection": IT_SUPPORT, "query": None},  # no query at all
    ]

    for overrides in invalid_bodies:
        payload: dict[str, Any] = {"collection": IT_SUPPORT, "query": "placeholder"}
        for key, value in overrides.items():
            if value is None:
                payload.pop(key)
            else:
                payload[key] = value

        response = post_search(payload)

        assert response.status_code == 422, (
            f"body {overrides!r} returned {response.status_code}, expected 422: "
            f"{response.text[:300]}"
        )

    # And a nonsense size is refused at the edge rather than clamped silently
    # from the wrong side: `candidates=0` is a caller mistake worth naming.
    for override in ({"candidates": 0}, {"top_k": 0}, {"candidates": -5}):
        response = search(INFRASTRUCTURE, "restore a database", **override)
        assert response.status_code == 422, (
            f"{override!r} returned {response.status_code}, expected 422: {response.text[:300]}"
        )


# ── 7. Every score belongs to its own document ───────────────────────────────


def test_every_result_carries_the_score_of_its_own_document():
    """The index-mapping trap: `document_id`, `content` and `relevance_score` must agree.

    ── THE FAILURE THIS CATCHES ────────────────────────────────────────────────
    The reranker returns `index` = the caller's position in the array the caller
    SENT. Send the contents in one order, slice or sort before mapping, and every
    score attaches to the wrong document — silently, with a 200 and entirely
    plausible-looking numbers. Nothing raises; the response is well-formed; users
    are shown the wrong snippet next to a real score.

    ── WHY IT IS CHECKED INDEPENDENTLY RATHER THAN BY INSECTION ────────────────
    This test re-runs the two stages itself — embed with the prefix, retrieve
    with the collection, rerank the returned contents — and then compares the
    API's `(document_id, relevance_score)` pairs against its own. A mis-mapped
    index shows up as a document carrying a score computed for a DIFFERENT
    document, which is a gross, unmistakable difference rather than a rounding
    artefact, so the comparison tolerates float noise and still fails on the bug
    it exists to catch.

    The query is deliberately vague ("rotate a credential") so that SEVERAL
    documents are plausible. With one obvious winner, a mis-mapped index could
    still leave the winner first by luck, because the ordering of a wrong
    permutation of an already-sorted list often coincides.
    """
    query = "rotate a credential"
    response = search(INFRASTRUCTURE, query)
    assert response.status_code == 200, response.text[:300]
    results = response.json()["results"]
    assert len(results) >= 3, (
        f"only {len(results)} results; with fewer, several documents are not "
        "plausible at once and a mis-mapped index may not be detectable"
    )

    # ── THE SAME PIPELINE, RUN INDEPENDENTLY ───────────────────────────────────
    query_embedding = embed_text(config.QUERY_PREFIX + query)
    candidates = with_database(
        lambda database: _retrieve(
            engine_of(database), collection=INFRASTRUCTURE, embedding=query_embedding, limit=CONFIGURED_CANDIDATES
        )
    )
    assert candidates, "the independent retrieval found nothing; the API found something"

    independent = requests.post(
        f"{BASE_URL}/rerank",
        json={"query": query, "documents": [candidate.content for candidate in candidates]},
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    assert independent.status_code == 200, independent.text[:300]

    # content → (document_id, score), joined the way main.search joins them: the
    # worker's `index` is a position in the array sent, which is `candidates`.
    expected: dict[str, tuple[str, float]] = {}
    for item in independent.json()["results"]:
        candidate = candidates[item["index"]]
        expected[candidate.content] = (candidate.document_id, float(item["relevance_score"]))

    for result in results:
        content = result["content"]
        assert content in expected, (
            f"the API returned content that was never scored: {result['document_id']!r}"
        )
        expected_id, expected_score = expected[content]

        assert result["document_id"] == expected_id, (
            f"document {result['document_id']!r} carries the score of {expected_id!r}: "
            "the reranker's index was mapped onto the wrong candidate. This is the "
            "silent failure — the response is well-formed and every number is real."
        )
        assert abs(float(result["relevance_score"]) - expected_score) < 1e-3, (
            f"{result['document_id']!r} scored {result['relevance_score']!r} here and "
            f"{expected_score!r} when scored independently, on identical text"
        )

    # And the stage-1 number must be the one belonging to THAT document — the
    # other half of "the scores travel with their documents".
    distances = {candidate.content: candidate.distance for candidate in candidates}
    for result in results:
        assert abs(float(result["distance"]) - distances[result["content"]]) < 1e-6, (
            f"{result['document_id']!r} reports distance "
            f"{result['distance']!r}, which is not the distance of its own content"
        )


async def _retrieve(engine: Any, *, collection: str, embedding: list[float], limit: int) -> list[store.Candidate]:
    """`store.retrieve` through this process's own pool.

    The point of using the store directly is that it is the same function the API
    calls, so the candidate list this test reconstructs is the API's candidate
    list — down to the ordering the reranker's indices refer to. Async, for the
    reason given on `_global_shortlist`.
    """
    return await store.retrieve(
        engine, collection=collection, query_embedding=embedding, limit=limit
    )


# ── 8. The pre-existing endpoints ────────────────────────────────────────────


def test_the_endpoints_that_existed_before_this_phase_are_unaffected():
    """`/health`, `/embed`, `/rerank` and `POST /documents` still behave as they did.

    A new route is not an additive change by default: a shared helper edited for
    it, a lifespan change, or a renamed import breaks the routes above it, and
    they are the ones compose's healthcheck, `scripts/boot.sh` and the Milestone 2
    ALB target group already depend on. `/search` reuses `embed()` and
    `rerank()` rather than reimplementing them, so this is the check that the
    reuse was behaviour-preserving.

    The `/documents` write uses this file's own prefixed collection and is
    cleaned up by the autouse fixture, so it cannot collide with the real corpus.
    """
    health = requests.get(f"{BASE_URL}/health", timeout=30)
    assert health.status_code == 200, f"/health returned {health.status_code}: {health.text[:200]}"
    assert health.json()["status"] == "ok"

    ready = requests.get(f"{BASE_URL}/health/ready", timeout=30)
    assert ready.status_code == 200, f"/health/ready returned {ready.status_code}: {ready.text[:200]}"
    assert ready.json()["database"] == "ok"

    live = requests.get(f"{BASE_URL}/health/live", timeout=30)
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}

    embedded = requests.post(f"{BASE_URL}/embed", json={"text": "a short probe"}, timeout=SEARCH_TIMEOUT_SECONDS)
    assert embedded.status_code == 200, f"/embed returned {embedded.status_code}"
    assert len(embedded.json()["embedding"]) == 384

    ranked = requests.post(
        f"{BASE_URL}/rerank",
        json={"query": "how do I reset my password", "documents": ["Click Forgot Password.", "The weather is mild."]},
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    assert ranked.status_code == 200, f"/rerank returned {ranked.status_code}"
    assert [item["index"] for item in ranked.json()["results"]] == [0, 1]

    # `/documents` still embeds bare and still reports the stored width. It does
    # not embed the prefixed text, and this assertion is here because a future
    # edit to share code between /documents and /search is exactly where that
    # would leak in.
    posted = requests.post(
        f"{BASE_URL}/documents",
        json={
            "document_id": "search-regression-probe",
            "collection": PROBE_COLLECTION,
            "content": "A probe document written by test_search.py to check /documents still works.",
            "metadata": {"source": "test_search"},
        },
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    assert posted.status_code == 201, f"POST /documents returned {posted.status_code}: {posted.text[:300]}"
    assert posted.json()["dimensions"] == 384

    # The row really is there, read back through a connection this test owns
    # rather than off the response body — the same argument
    # `test_a_posted_document_is_read_back_through_a_fresh_connection` makes.
    async def _read(database: db.Database) -> store.StoredDocument | None:
        return await store.fetch_document(engine_of(database), document_id="search-regression-probe")

    stored = with_database(_read)
    assert stored is not None
    assert stored.collection == PROBE_COLLECTION
    assert stored.dimensions == 384


# ── 9. The measured cost of the 10-vs-50 candidate decision ───────────────────
#
# NOTE ON STALENESS, because every other section in this file depends on a
# rebuilt image and this one deliberately does not: `/rerank` has existed since
# Milestone 1, so this measurement runs green against a stale API image. That is
# a feature here. The number it records is the justification for a decision in
# `config.DEFAULT_RETRIEVAL_CANDIDATES`, and a justification that can only be
# checked after a five-minute rebuild is a justification that goes unchecked.


RERANK_LATENCY_SAMPLES = 5
"""How many times the same call is made before anything is reported.

A single sample is not a measurement. It is one observation, and on a shared
`t3.micro` it is as likely as not to catch the neighbour's cron job. Five is
enough for the spread to be visible — the max matters more than the mean,
because the max is what a user waits through — and few enough that the test does
not spend its own runtime making the host slower for whatever runs next.
"""


def _real_corpus_documents(count: int) -> list[str]:
    """`count` documents' contents, taken from the corpus and verified in the database.

    "Realistic" is the operative word and it is doing real work in this
    measurement. The reranker's cost is a function of how much text it is asked
    to read: a list of ten short lorem-ipsum strings would be scored in a
    fraction of the time real runbooks take, and the number that produced would
    justify the candidate decision for a system this is not.

    So the text comes from `data/corpus.json` — the same file
    `scripts/load_corpus.py` loaded — and is then read back out of the DATABASE,
    with the file and the stored content compared. Two reasons for the round trip
    rather than reading the file and stopping:

    * it is the ingested corpus that is being measured, not the file on disk. If
      the loader had stored something different, this would score what the
      reranker will actually be handed;
    * the equality check makes "realistic" an assertion rather than an intention.
      A corpus regeneration that emptied the documents, or a loader that truncated
      them, fails here instead of silently producing a fast-looking measurement.

    Ordered by the corpus file's own order, not shuffled: determinism matters
    because this number is meant to be comparable to a future run of this test.
    """
    wanted = [document["id"] for document in corpus_documents().values() if document["collection"] == INFRASTRUCTURE][
        :count
    ]
    assert len(wanted) == count, f"the corpus has fewer than {count} {INFRASTRUCTURE} documents to measure"

    from_file = corpus_documents()

    async def _read(engine: Any) -> dict[str, str]:
        statement = text("SELECT id, content FROM documents WHERE id = ANY(:ids)")
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    statement, {"ids": list(wanted)}
                )
            ).all()
        return {str(row.id): str(row.content) for row in rows}

    stored = with_database(lambda database: _read(engine_of(database)))

    contents = []
    for document_id in wanted:
        assert document_id in stored, (
            f"{document_id!r} is in the corpus file but not in the database, so the "
            f"latency below would be measured against something this host is not "
            f"actually serving.\nLoad the corpus:\n    {LOAD_CORPUS}"
        )
        assert stored[document_id] == from_file[document_id]["content"], (
            f"the stored content of {document_id!r} differs from the corpus file. "
            "Something rewrote it between loading and now, and a latency measured "
            "on it would not describe the corpus."
        )
        assert len(stored[document_id].strip()) > 500, (
            f"{document_id!r} is {len(stored[document_id])} characters. Short filler "
            "text would make the reranker look far cheaper than it is on real "
            "runbooks, which is the one thing this measurement must not do."
        )
        contents.append(stored[document_id])
    return contents


def test_scoring_ten_real_documents_costs_what_it_costs_measured_not_assumed():
    """MEASURE the reranker's wall-clock cost for one stage-2 pass, and print it.

    ── WHY THIS TEST EXISTS ────────────────────────────────────────────────────
    `config.DEFAULT_RETRIEVAL_CANDIDATES` changed from 50 to 10 in this phase. The
    reasoning written on that constant is sound — the reranker is a
    cross-encoder, it scores EVERY candidate on CPU with no batch discount, and
    Milestone 2 measured this host as a `t3.micro` with roughly 280Mi of headroom
    at rest — but none of it is a NUMBER. It is an argument from the shape of the
    work. This test supplies the missing measurement so the decision rests on
    evidence as well as on reasoning, and so that a future reader can see what
    "ten candidates" actually costs rather than having to infer it.

    ── A WORK LATENCY, NOT A PROBE LATENCY. WHY THE DISTINCTION MATTERS HERE ────
    `main.py` already splits these two numbers deliberately
    (`PROBE_TIMEOUT_SECONDS` vs `INFERENCE_TIMEOUT_SECONDS`) and the reason applies
    here unchanged. A readiness probe asks "is this thing up right now?" and wants
    a fast NO; it runs every few seconds and compose ACTS on a timeout by marking
    the container unhealthy, so a probe tuned too eagerly is worse than useless.
    An inference request asks "do this real piece of work", and its cost scales
    with the work: a cross-encoder scoring ten passages cannot be answered faster
    by wanting it to.

    So this is unambiguously the SECOND kind. It is timed around a call that
    scores ten real documents, and it is allowed to be seconds long. It is NOT
    timed like a probe and it must NOT be given a probe's budget: a five-second
    cap on a ten-document rerank would be a statement about readiness that nobody
    asked for, expressed in the wrong unit.

    ── WHAT THIS NUMBER DOES AND DOES NOT JUSTIFY ───────────────────────────────
    It DOES justify `DEFAULT_RETRIEVAL_CANDIDATES = 10`. The cost of stage 2 is
    linear in the candidate count with no discount, so this measurement plus its
    error bar is the evidence behind the 10-vs-50 choice, and a reader who wants
    to revisit that choice has a measured cost per candidate to reason from
    instead of an intuition.

    It is NOT an SLO, and must not be quoted as one. Three reasons, and they are
    the reason the assertions below are as loose as they are:

    * this host is a shared, CPU-only `t3.micro`. The number moves when a
      neighbour is scheduled, and a latency bound asserted here would fail on a
      busy machine while telling the truth about the code;
    * it is a SERVICE-TO-SERVICE cost from one specific caller, not an end-to-end
      user latency — it excludes the queueing, the ALB hop and the client's own
      network, all of which a real SLO would have to contain;
    * it is measured at one candidate count on one day with one model. An SLO is
      a commitment made in advance and held over time; this is an observation made
      after the fact.

    ── WHY NOTHING TIGHT IS ASSERTED ────────────────────────────────────────────
    A hard bound here would be a flaky test that teaches the team to ignore it,
    which is strictly worse than no test at all. The assertions below are the
    ones that mean something on a loaded box — the call completed, and it
    completed correctly, scoring every document it was sent. The measurement
    itself is printed rather than asserted, so it is recorded without being able
    to fail. Run with `-s` to watch it.
    """
    documents = _real_corpus_documents(CONFIGURED_CANDIDATES)
    assert len(documents) == CONFIGURED_CANDIDATES == 10

    # A query drawn from the corpus's own vocabulary, so the reranker does the
    # work it would do for a real caller rather than scoring everything as
    # equally irrelevant.
    query = "restore the PostgreSQL database from an automated snapshot"

    samples: list[float] = []
    scored_indices: list[list[int]] = []

    for sample_number in range(RERANK_LATENCY_SAMPLES):
        started = time.monotonic()
        response = requests.post(
            f"{BASE_URL}/rerank",
            json={"query": query, "documents": documents},
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
        elapsed = time.monotonic() - started

        assert response.status_code == 200, (
            f"sample {sample_number + 1} returned {response.status_code}: "
            f"{response.text[:300]}"
        )
        body = response.json()
        indices = [int(item["index"]) for item in body["results"]]

        # ── THE LOOSE, MEANINGFUL ASSERTIONS ──────────────────────────────────
        # "It finished, and it finished correctly" is a real property of the
        # route and it holds on a busy machine. How long it took is not.
        assert len(body["results"]) == CONFIGURED_CANDIDATES, (
            f"sample {sample_number + 1} scored {len(body['results'])} of "
            f"{CONFIGURED_CANDIDATES} documents"
        )
        assert sorted(indices) == list(range(CONFIGURED_CANDIDATES)), (
            f"sample {sample_number + 1} did not return every index exactly once: "
            f"{sorted(indices)}. Every document sent must come back scored — a "
            "truncation here would change what the latency below means."
        )
        assert body["model"], "the reranker alias is echoed so these scores can be attributed"

        samples.append(elapsed)
        scored_indices.append(indices)

    # Identical results across samples: the same ten documents and the same query
    # must score identically, so a run-to-run difference in TIME cannot be
    # explained by a run-to-run difference in WORK. This is what makes it fair to
    # read the spread below as host noise rather than as the measurement drifting.
    assert all(indices == scored_indices[0] for indices in scored_indices), (
        "the same query against the same documents produced different index "
        f"orders across samples: {scored_indices}"
    )

    minimum, median, maximum = min(samples), statistics.median(samples), max(samples)

    # ── THE MEASUREMENT. Printed, never asserted. ──────────────────────────────
    print(
        "\n"
        "  ══ MEASURED: POST /rerank, "
        f"{len(documents)} real corpus documents ({sum(len(d) for d in documents):,} chars) "
        f"× {RERANK_LATENCY_SAMPLES} samples ══\n"
        f"     min    {minimum:7.3f} s\n"
        f"     median {median:7.3f} s\n"
        f"     max    {maximum:7.3f} s\n"
        f"     spread {maximum - minimum:7.3f} s\n"
        f"     per candidate: {median / len(documents):.3f} s\n"
        "     Evidence for DEFAULT_RETRIEVAL_CANDIDATES=10. NOT an SLO.\n"
        "     (Run pytest -s to see this.)"
    )

    # The only property of the measurement itself that is asserted: it is a
    # number. A zero or negative elapsed time would mean the clock, not the
    # reranker, is broken — and a latency of zero flowing silently into the
    # comment above would be worse than no measurement at all.
    assert all(0.0 < sample <= SEARCH_TIMEOUT_SECONDS for sample in samples), (
        f"implausible sample timings: {samples}. `time.monotonic()` cannot go "
        "backwards and no sample should approach the request timeout; if one does, "
        "the numbers above are not a measurement of the reranker."
    )