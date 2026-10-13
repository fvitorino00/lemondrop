"""Tests for the document store and `POST /documents`: ingestion, upsert, isolation.

What this file is: real PostgreSQL, real pgvector, real HTTP against the running
API. No mocks, no in-process test client, no fake pool — for the same reasons
`test_db.py` gives, and more sharply here. The thing under test is a chain that
crosses four boundaries: Pydantic, HTTP, a connection POOL, and a PostgreSQL
column with a type constraint. A mock at any of those boundaries agrees with the
code by construction, which means it cannot catch the failure that actually
matters: a vector written through a connection whose codec was never registered.

That specific failure is the reason the first three tests below exist, in the
order they exist. Read `test_without_the_registration_a_vector_write_fails`
first: it is the negative control that proves the positive one is measuring
something.

Preconditions, both of which must be true before pytest is invoked. From the
repository root:

    docker compose --profile devdb up -d --build postgres
    docker compose up -d --build api
    set -a && . ./.env && set +a

If the API container is running an image that predates this phase, the
`POST /documents` tests fail with a message naming `docker compose up -d --build
api`. **That is correct behaviour, not a broken test**, and there is no
`pytest.skip()` anywhere in this file: a skipped test is a test that has stopped
testing while still reporting green, and green-that-means-nothing is worse than
red, because red gets read.

What this file protects, in rough order of how much damage its absence causes:

* **Every pooled connection carries the pgvector codec.** Without it, vector
  writes fail intermittently, under load only, and never in a single-query test.
* **`documents.embedding` really is `vector(384)`** — asserted by making the
  database REJECT a 768-dimension vector, not by reading the schema.
* **Retrieval cannot leak across collections** — asserted with counts, not with
  the absence of a foreign id.
* **Documents are embedded BARE**, with the bge query prefix nowhere near them.
* Ingestion round-trips, upserts update in place, and `updated_at` moves.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable, Coroutine

import pytest
import requests
from pgvector import Vector
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import db, store
from app.config import SCHEMA_EMBEDDING_DIM, get_settings

# The API under test. Read from the environment with a localhost default,
# matching the convention in test_db.py and test_integration.py.
BASE_URL = os.environ.get("API_URL", "http://localhost:8000")

START_DEVDB = "docker compose --profile devdb up -d --build postgres"
REBUILD_API = "docker compose up -d --build api"

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "data" / "corpus.json"

# A vector that is not the zero vector and not a unit vector, so L2 distances
# between different documents are distinct and the ORDER BY is actually
# exercised. Deterministic (no randomness) so a failure is reproducible.
def _vector(seed: int) -> list[float]:
    """A deterministic 384-dimension vector derived from `seed`.

    Deterministic because a test that seeds randomness cannot be re-run to see
    the same ordering twice, and this file's ordering assertions are about the
    WHERE clause, not about ranking quality — the vector does not need to be a
    real embedding for that. It only needs to be distinguishable from the others.
    """
    return [((seed * (i + 1)) % 97) / 97.0 for i in range(SCHEMA_EMBEDDING_DIM)]


# Collections reserved for this file's fixtures. Prefixed so a stray run of the
# test suite cannot collide with the real corpus's `infrastructure` /
# `it-support`, and so `delete_collection` in teardown can never be pointed at
# production data by a typo in a test name.
FIXTURE_COLLECTION_A = "testdocs-alpha"
FIXTURE_COLLECTION_B = "testdocs-beta"


# ── Helpers ───────────────────────────────────────────────────────────────────
#
# `with_database` and `database_settings` deliberately repeat the pair from
# test_db.py rather than importing them. The import would work (pytest puts this
# directory on sys.path), but the versions needed here are not the same: this
# file's helper must optionally ARM the pool with the vector codec, and arming it
# is the entire subject of the next section. A shared helper that gained a
# `prepare_codecs=True` flag would be a test_db.py edit to serve a test_db.py
# that does not need it, and coupling two files that test different things makes
# both harder to read.


def database_settings():
    """Build settings from the environment, failing with a usable message.

    Same wrapper as test_db.py's, including the same reason: `get_settings()`
    raises a long, helpful message when `DATABASE_URL` is unset but cannot know
    which devdb the value should point at, and the operator needs to be told
    that in the failure rather than having to remember it.
    """
    try:
        return get_settings()
    except RuntimeError as exc:
        pytest.fail(f"{exc}\n\nIf it is set but wrong, check the devdb is up:\n    {START_DEVDB}")


def with_database(
    action: Callable[[db.Database], Coroutine[Any, Any, Any]],
    *,
    prepare_codecs: bool = True,
) -> Any:
    """Run `action` against a started `Database` in ONE event loop, then dispose.

    The single `asyncio.run` is not stylistic: an `AsyncEngine` binds its pool to
    the loop running when it was created, so starting in one loop and closing in
    another is precisely the "attached to a different loop" bug `db.startup`
    warns about. Same reasoning, and the same `finally`, as test_db.py's helper —
    a failing test must not leave a pool holding real connections.

    `prepare_codecs=False` is the negative-control switch. It produces a pool
    that behaves exactly as SQLAlchemy builds it: connections created, `SELECT 1`
    runs, everything healthy — and no `vector` codec on any of them. That is the
    configuration the first test below needs, and it cannot be produced by
    breaking the registration helper, because a broken helper that still
    registers the codec would prove nothing.
    """

    async def _run() -> Any:
        database = await db.startup(database_settings())
        try:
            if prepare_codecs:
                await store.prepare_database(database)
            return await action(database)
        finally:
            await db.close(database)

    return asyncio.run(_run())


def engine_of(database: db.Database):
    """The engine, asserted present.

    A test that reaches an `Optional` and passes it on produces an
    `AttributeError: 'NoneType'` two frames from the real cause. `prepare_codecs`
    returned False — meaning `db.startup` found no usable database — and the
    message says so.
    """
    engine = database.engine
    if engine is None:
        pytest.fail(f"no database engine: {database.problem}\n    {START_DEVDB}")
    return engine


async def _clear_fixtures(database: db.Database) -> None:
    """Remove both fixture collections. Runs in teardown; failures are not fatal.

    A leftover row from a failed test would make the NEXT run's counts wrong, so
    the fixture is cleared at setup as well as at teardown.
    """
    engine = engine_of(database)
    for collection in (FIXTURE_COLLECTION_A, FIXTURE_COLLECTION_B):
        await store.delete_collection(engine, collection=collection)


@pytest.fixture(autouse=True)
def _clean_fixture_collections():
    """Empty both fixture collections before and after every test in this file."""
    with_database(lambda database: _clear_fixtures(database))
    yield
    with_database(lambda database: _clear_fixtures(database))


def post_document(payload: dict[str, Any]) -> requests.Response:
    """POST to `/documents`, turning "route not deployed" into a readable failure.

    A bare 404 here is ambiguous — it could mean the path is wrong in this test,
    or that the running image predates the route — and the two have completely
    different fixes. Naming the rebuild command in the failure is what makes it
    diagnosable in one read.

    The timeout is generous (the API's own inference budget is 120 seconds and
    each of these embeds real text on a CPU-only worker) but not infinite: a
    request that hangs forever is a bug worth failing on.
    """
    response = requests.post(f"{BASE_URL}/documents", json=payload, timeout=180)

    if response.status_code == 404:
        pytest.fail(
            "POST /documents does not exist — the running API image predates this "
            f"phase.\nRebuild and restart it:\n    {REBUILD_API}"
        )

    return response


def document_payload(document_id: str, collection: str, content: str, **extra: Any) -> dict[str, Any]:
    """A well-formed ingestion body, with overrides for the tests that need one."""
    payload = {
        "document_id": document_id,
        "collection": collection,
        "content": content,
        "metadata": {"source": "test"},
    }
    payload.update(extra)
    return payload


# ── 1. Is the codec on EVERY pooled connection? ───────────────────────────────


def test_every_pooled_connection_has_the_vector_codec():
    """POSITIVE CONTROL. Three distinct pooled connections, three vector writes.

    ── WHAT BREAKS WITHOUT THIS TEST ───────────────────────────────────────────
    asyncpg type codecs are per CONNECTION. `create_async_engine` builds a pool
    of up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` = 3 connections, created lazily,
    so the number of connections that exist at any moment depends on how many
    requests arrived at once.

    Register the codec on the connection you happen to be holding and only that
    connection can carry a vector. The others raise
    `asyncpg.DataError: invalid input for query argument $N: Vector([...])
    (expected str, got Vector)` — intermittently, only under concurrency,
    because which pooled connection serves a request is a scheduling detail. A
    test that writes one vector sees one connection and passes; production sees
    three and fails about a third of the time.

    So this test forces the pool to grow: `pool_size=2, max_overflow=1` means
    three simultaneously-held connections are exactly three DISTINCT backends,
    and `pg_backend_pid()` is the proof. Those three pids are asserted to be
    three different values, because "opened three connections" and "used three
    connections" are only the same claim if the pool actually made three.
    """
    del_pids: list[int] = []
    inserted_pids: list[int] = []

    async def _run(database: db.Database) -> tuple[list[int], list[int]]:
        engine = engine_of(database)

        # All three held open at the same time, so none of them can be returned
        # and reused: these are three genuinely concurrent checkouts.
        connections = [await engine.connect() for _ in range(3)]
        try:
            for connection in connections:
                del_pids.append(int(await connection.scalar(text("SELECT pg_backend_pid()"))))

                # A vector write, on THIS connection. If the codec were missing
                # here, this statement raises and the test fails — which is the
                # behaviour the negative control below proves is real.
                await connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(id, collection, content, metadata, embedding) "
                        "VALUES (:id, :collection, :content, CAST(:metadata AS jsonb), :embedding)"
                    ),
                    {
                        "id": f"codec-probe-{len(inserted_pids)}",
                        "collection": FIXTURE_COLLECTION_A,
                        "content": "codec coverage probe",
                        "metadata": "{}",
                        "embedding": Vector(_vector(len(inserted_pids))),
                    },
                )
                await connection.commit()
                inserted_pids.append(int(await connection.scalar(text("SELECT pg_backend_pid()"))))
        finally:
            for connection in connections:
                await connection.close()

        return del_pids, inserted_pids

    pids, write_pids = with_database(_run)

    assert len(set(pids)) == 3, (
        f"the pool handed out {len(set(pids))} distinct connections, not 3: {pids}. "
        "If the pool is not growing, this test is measuring one connection three "
        "times and cannot see the bug it exists to catch."
    )
    # The vector INSERT succeeded on every one of them — that is the assertion,
    # and it is only meaningful because the negative control below fails.
    assert sorted(write_pids) == sorted(pids), "a vector write and its pid check landed on different connections"


def test_without_the_registration_a_vector_write_fails():
    """NEGATIVE CONTROL. The identical write, with the codec deliberately absent.

    ── WHY THIS TEST IS THE ONE THAT MATTERS ───────────────────────────────────
    A positive control proves nothing on its own. `test_every_pooled_connection_
    has_the_vector_codec` would pass against a `prepare_database` that does
    nothing, if the pool happened to reuse one already-registered connection, if
    pgvector's codec were installed by some other route, if the column accepted
    text vectors on some path this test does not exercise — all of which are
    plausible and none of which are checked.

    So the same write is run against a pool built EXACTLY as SQLAlchemy builds
    it, with `prepare_codecs=False`. If that write SUCCEEDS, the positive test
    above is not measuring registration at all, and the honest response is to fix
    the test — not to claim a pass. So the assertion is that it fails, and the
    assertion is on the failure's TYPE as well as its existence: an
    `asyncpg.DataError` about the parameter. A test that merely asserted "some
    exception" would be satisfied by a connection refusal, which would mean the
    suite was measuring the database's availability, not the codec.
    """

    async def _run(database: db.Database) -> list[Exception]:
        engine = engine_of(database)
        failures: list[Exception] = []

        connections = [await engine.connect() for _ in range(3)]
        try:
            for index, connection in enumerate(connections):
                try:
                    await connection.execute(
                        text(
                            "INSERT INTO documents "
                            "(id, collection, content, metadata, embedding) "
                            "VALUES (:id, :collection, :content, CAST(:metadata AS jsonb), :embedding)"
                        ),
                        {
                            "id": f"codec-negcontrol-{index}",
                            "collection": FIXTURE_COLLECTION_A,
                            "content": "negative control",
                            "metadata": "{}",
                            "embedding": Vector(_vector(index)),
                        },
                    )
                    await connection.commit()
                except DBAPIError as exc:
                    failures.append(exc)
        finally:
            for connection in connections:
                await connection.close()

        return failures

    failures = with_database(_run, prepare_codecs=False)

    assert len(failures) == 3, (
        f"expected all 3 unregistered connections to refuse a vector write, got "
        f"{len(failures)} failures.\n"
        "If this is 0, the positive control above is NOT measuring codec "
        "registration — something else is making vector writes work, and that "
        "test is measuring the wrong thing."
    )

    # ── WHY THIS ASSERTS ON THE MESSAGE AND NOT THE EXCEPTION CLASS ────────────
    # Measured on SQLAlchemy 2.0.54 + asyncpg 0.32.0: the dialect does NOT
    # preserve the driver's exception class. `type(exc.orig).__name__` is
    # `"Error"` and `type(exc.orig).__module__` is
    # `sqlalchemy.dialects.postgresql.asyncpg` for EVERY driver error, including
    # DataError, CheckViolationError and unique violations alike. The asyncpg
    # class name survives only in the rendered message, as
    # `<class 'asyncpg.exceptions.DataError'>: ...`. So the message is what
    # identifies the failure, and asserting on `type(exc.orig).__name__` would
    # assert nothing at all.
    for exc in failures:
        rendered = str(exc.orig)
        assert "asyncpg.exceptions.DataError" in rendered, (
            f"expected asyncpg's DataError for a missing vector codec, got: {rendered}"
        )
        assert "invalid input for query argument" in rendered, (
            f"expected the missing-codec error text, got: {rendered}"
        )


def test_attaching_the_listener_without_disposing_leaves_the_ping_connection_broken():
    """The intermediate case, asserted, so the `dispose()` in `prepare_database` stays.

    This is the subtle half of the bug and it is the half a reviewer would not
    think of.

    `db.startup()` PINGS the database before returning: it checks a connection
    out, runs `SELECT 1`, and checks it back in. So by the time anything could
    attach a listener, the pool already holds one live connection that was
    created before the listener existed. Attaching the listener covers every
    connection created AFTERWARDS and leaves that first one permanently
    unregistered.

    This test reproduces exactly that: attach, do not dispose, open three
    connections. The assertion is that the RECYCLED one fails while the two
    genuinely fresh ones succeed — one failure, not three. If a future edit drops
    the `await engine.dispose()` from `prepare_database` on the grounds that the
    listener alone looks sufficient, this test is what catches it.

    This state is a test-only construction. The application never sits in it:
    `prepare_database` is called once, immediately after startup, before any
    route can reach the engine.
    """
    engine_state: dict[str, Any] = {}

    async def _run(database: db.Database) -> None:
        engine = engine_of(database)

        from sqlalchemy import event

        event.listen(engine.sync_engine, "connect", store._register_vector_on_connect)
        # Deliberately NO dispose — that is the state under test.

        connections = [await engine.connect() for _ in range(3)]
        try:
            for index, connection in enumerate(connections):
                pid = int(await connection.scalar(text("SELECT pg_backend_pid()")))
                try:
                    await connection.execute(
                        text(
                            "INSERT INTO documents "
                            "(id, collection, content, metadata, embedding) "
                            "VALUES (:id, :collection, :content, CAST(:metadata AS jsonb), :embedding)"
                        ),
                        {
                            "id": f"codec-nodispose-{index}",
                            "collection": FIXTURE_COLLECTION_A,
                            "content": "no-dispose probe",
                            "metadata": "{}",
                            "embedding": Vector(_vector(index)),
                        },
                    )
                    await connection.commit()
                except DBAPIError:
                    engine_state.setdefault("failed", []).append(pid)
                else:
                    engine_state.setdefault("succeeded", []).append(pid)
        finally:
            for connection in connections:
                await connection.close()

    # `prepare_codecs=False`: this test constructs the no-dispose state itself,
    # so the helper must NOT have already disposed the ping connection away.
    with_database(_run, prepare_codecs=False)

    succeeded = engine_state.get("succeeded", [])
    failed = engine_state.get("failed", [])

    # Three connections, two codecs — one of them the recycled ping connection.
    assert len(succeeded) == 2, f"expected 2 fresh connections to succeed, got {succeeded}"
    assert len(failed) == 1, (
        f"expected exactly ONE unregistered connection (the one db.startup's ping "
        f"checked back in), got {len(failed)}: {failed}"
    )


def test_sqlalchemy_has_no_vector_colspec_so_raw_sql_is_the_only_route():
    """The measured constraint that decides `text()` over a typed column.

    Measured on SQLAlchemy 2.0.54's asyncpg dialect: `'vector' in d.colspecs` is
    `False`. pgvector-python ships a `sqlalchemy.VECTOR` type, and it cannot be
    used as a column type with this dialect at all — so the alternative to
    `store`'s raw SQL is not "cleaner typed SQL", it is "unavailable".

    Asserted rather than assumed because it is a property of a pinned dependency
    version, and a future SQLAlchemy that ADDS the colspec would change the
    shape of this decision. Whoever notices this test go quiet should read it as
    "the option opened up, go look at store again", not as "delete the test".
    """
    from sqlalchemy.dialects.postgresql import asyncpg as asyncpg_dialect

    colspecs = asyncpg_dialect.dialect.colspecs
    assert "vector" not in colspecs, (
        "the asyncpg dialect now HAS a vector colspec — pgvector's VECTOR type "
        "may now be usable as a column type, and store.py's raw-SQL decision is "
        "worth revisiting"
    )


# ── 2. The store's own write path ─────────────────────────────────────────────
#
# `store.upsert_document` is reached in production only through
# `POST /documents`, so the API tests below would be its only coverage — and
# those cannot run until the container image is rebuilt. This test exercises the
# function directly against a real database so the write path is verified on a
# machine where the API image is stale.


def test_upsert_document_reports_which_arm_ran_and_what_width_was_stored():
    """Insert then update, through `store.upsert_document` itself.

    ── WHY THIS IS NOT COVERED BY THE API TESTS ALONE ──────────────────────────
    `upsert_document` is called from exactly one place — the `/documents` route —
    so an API-level test suite covers it. But those tests cannot run until
    `docker compose up -d --build api` has been run, and until then the one
    function that writes rows would have zero executed coverage on a machine
    where a reviewer is checking the diff. This test does not need the API at
    all: it drives the store against the same PostgreSQL the API would use.

    What it pins down:

    * both arms of `ON CONFLICT` are distinguishable through `UpsertResult`, so
      the route's `outcome` field reports something true rather than always
      saying "inserted";
    * `dimensions` comes back as 384 — read from `vector_dims(embedding)` by the
      DATABASE, so this also proves the round trip through
      `CAST(:embedding AS vector)` and the binary codec preserves the width;
    * a collection change is an UPDATE, not a second row;
    * `updated_at` moves and `created_at` does not.
    """

    async def _run(database: db.Database) -> tuple[store.UpsertResult, store.UpsertResult, int]:
        engine = engine_of(database)
        first = await store.upsert_document(
            engine,
            document_id="store-upsert",
            collection=FIXTURE_COLLECTION_A,
            content="first",
            metadata={"n": 1},
            embedding=_vector(7),
        )
        second = await store.upsert_document(
            engine,
            document_id="store-upsert",
            collection=FIXTURE_COLLECTION_B,
            content="second",
            metadata={"n": 2},
            embedding=_vector(8),
        )
        async with engine.connect() as connection:
            total = int(
                await connection.scalar(
                    text("SELECT count(*) FROM documents WHERE id = :document_id"),
                    {"document_id": "store-upsert"},
                )
            )
        return first, second, total

    first, second, total = with_database(_run)

    assert total == 1, f"{total} rows for one id; an upsert must leave exactly one"
    assert first.inserted is True, "the first write took the UPDATE arm, which is impossible — xmax reporting is wrong"
    assert second.inserted is False, "the second write of an existing id reported 'inserted'"
    assert first.dimensions == SCHEMA_EMBEDDING_DIM
    assert second.dimensions == SCHEMA_EMBEDDING_DIM

    async def _read(database: db.Database) -> store.StoredDocument | None:
        return await store.fetch_document(engine_of(database), document_id="store-upsert")

    stored = with_database(_read)

    assert stored is not None
    assert stored.content == "second"
    assert stored.collection == FIXTURE_COLLECTION_B, "the collection move did not happen as an UPDATE"
    assert stored.metadata == {"n": 2}
    assert stored.updated_at > first.updated_at, "updated_at did not move on the update arm"
    assert stored.created_at == first.updated_at, (
        "created_at changed on update — it belongs to the original insert and "
        "records when the document entered the corpus"
    )


# ── 3. The database enforces its own invariants ───────────────────────────────


def test_a_768_dimension_vector_is_rejected_by_the_database():
    """`vector(384)` must be a real boundary, not documentation.

    ── WHY THIS TEST, GIVEN A CHECK CONSTRAINT WOULD BE SIMPLER ────────────────
    Migration 0001 deliberately has no `CHECK (vector_dims(embedding) = 384)`: the
    column's typmod IS the check, and restating it would create two definitions
    of "384" that can drift. The consequence is that the guarantee is only
    visible through the type, so the test has to go through the type.

    The write bypasses the API entirely (raw SQL through a store connection) on
    purpose. An API-level test could only observe a 502, which would pass whether
    the rejection came from this route's own width check, from the column, or
    from the network — three different causes, one indistinguishable outcome.

    AND IT MUST FAIL FOR THE RIGHT REASON, which is why the message is asserted
    and not just the exception: pgvector says `expected 384 dimensions, not 768`
    and asyncpg raises `DataError`. If the message were about the codec
    (`invalid input for query argument`), the rejection would be an accident of
    the connection this test happened to use rather than proof of the column, and
    the test would pass on a database with no dimension constraint at all.
    """
    engine_state: dict[str, Any] = {}

    async def _run(database: db.Database) -> None:
        engine = engine_of(database)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(id, collection, content, metadata, embedding) "
                        "VALUES (:id, :collection, :content, CAST(:metadata AS jsonb), :embedding)"
                    ),
                    {
                        "id": "wrong-dimension",
                        "collection": FIXTURE_COLLECTION_A,
                        "content": "768 dimensions",
                        "metadata": "{}",
                        "embedding": Vector([0.01] * 768),
                    },
                )
        except DBAPIError as exc:
            engine_state["exception"] = exc
        else:
            engine_state["exception"] = None

    with_database(_run)

    exc = engine_state["exception"]
    assert exc is not None, (
        "the database ACCEPTED a 768-dimension vector into a vector(384) column. "
        "Either the column lost its typmod or the write went somewhere else — "
        "both mean the dimension is documentation rather than a constraint."
    )

    message = str(exc.orig)
    assert "expected 384 dimensions, not 768" in message, (
        f"the rejection must be about the DIMENSION, got: {exc.orig}. A codec error "
        "here would mean the dimension check was never reached and the test would "
        "pass on a database with no typmod at all."
    )
    # And the converse, asserted explicitly rather than assumed: this pool HAS
    # the vector codec (`with_database` defaults to `prepare_codecs=True`), and
    # the assertion below is what proves it. Without a codec, asyncpg cannot even
    # ENCODE the 768-float vector, so it fails earlier with
    # `invalid input for query argument` — the exact message the negative
    # control above asserts on — and the column is never asked to do anything.
    # The two tests are the same write with one input variable changed, and this
    # assertion is what keeps them distinguishable.
    assert "invalid input for query argument" not in message, (
        f"this write failed for lack of a codec, not for its dimension: {exc.orig}. "
        "The pool running this test must be prepared — see with_database."
    )
    assert "asyncpg.exceptions.DataError" in message, (
        f"expected asyncpg's DataError from pgvector's dimension check, got: {exc.orig}"
    )


def test_metadata_that_is_not_a_json_object_is_rejected_by_the_database():
    """The CHECK constraint must fire on an array.

    The API validates this at the edge (see `test_a_json_array_as_metadata_is_a_422`
    below), so this test writes raw SQL — bypassing that validation — to prove the
    DATABASE also refuses it. Both are needed: the edge check is what gives the
    caller a useful 422, and this one is what guarantees the invariant even for a
    writer that skipped the API entirely (a migration, a psql session, a future
    service).

    Asserted on the CONSTRAINT NAME, not merely on "it raised", because the
    interesting failure is a rejection for some other reason — a NOT NULL
    violation, a type error — which would leave the actual guarantee untested
    while the suite stayed green.
    """

    async def _run(database: db.Database) -> None:
        engine = engine_of(database)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(id, collection, content, metadata, embedding) "
                        "VALUES (:id, :collection, :content, CAST(:metadata AS jsonb), :embedding)"
                    ),
                    {
                        "id": "metadata-as-array",
                        "collection": FIXTURE_COLLECTION_A,
                        "content": "metadata is an array",
                        "metadata": json.dumps([1, 2, 3]),
                        "embedding": Vector(_vector(1)),
                    },
                )
        except DBAPIError as exc:
            return exc

        return None

    exc = with_database(_run)

    assert exc is not None, "the database accepted a JSON array in a column whose CHECK requires an object"
    assert "documents_metadata_is_object" in str(exc.orig), (
        f"expected the metadata CHECK constraint by name, got: {exc.orig}"
    )


# ── 4. Retrieval is scoped by collection, and the counts prove it ──────────────


def test_retrieve_returns_only_documents_from_the_asked_collection():
    """The collection filter is in SQL, and the counts prove it rather than assume it.

    ── WHY A NUMBER AND NOT AN ABSENCE ─────────────────────────────────────────
    "No document from collection B came back" is satisfiable by a system that
    stored nothing at all. `count_by_collection` is asserted FIRST so that the
    isolation assertion is downstream of proof that both collections are really
    populated — otherwise this test could pass with an empty database and an
    empty result.

    The shape is chosen so the failure mode described in `store.retrieve`'s
    docstring is caught: collection A holds 3 documents and collection B holds
    5, and the limit is 3. A correct `WHERE collection = $1 ORDER BY distance
    LIMIT 3` returns three documents, all from A. A fetch-then-filter
    implementation — global top 3, then discard anything not in A — returns AT
    MOST three and usually ZERO, because the global shortlist is drawn from all
    eight and B's five outrank A's three. The isolation assertion alone cannot
    tell those apart: both return no B rows. Asserting the COUNT is what
    distinguishes them.

    A `pytest.skip()` would have been the tempting shortcut here ("only run when
    the corpus is loaded"), and it is exactly the shortcut this project forbids:
    the whole corpus may not be loaded, and the test must still prove isolation
    against fixtures it controls.
    """

    async def _seed(database: db.Database) -> None:
        engine = engine_of(database)
        async with engine.begin() as connection:
            for index in range(3):
                await connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(id, collection, content, metadata, embedding) "
                        "VALUES (:id, :collection, :content, CAST(:metadata AS jsonb), :embedding)"
                    ),
                    {
                        "id": f"alpha-{index}",
                        "collection": FIXTURE_COLLECTION_A,
                        # Canary text: a distinctive token per document, so the
                        # assertion can check identity and not just membership.
                        "content": f"CANARY-ALPHA-{index} {FIXTURE_COLLECTION_A}",
                        "metadata": json.dumps({"canary": f"alpha-{index}"}),
                        "embedding": Vector(_vector(index + 1)),
                    },
                )
            # More documents in B than the limit. This is the load-bearing
            # asymmetry: with a correct WHERE, A's limit is filled from A; with a
            # post-filter, B eats the shortlist.
            for index in range(5):
                await connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(id, collection, content, metadata, embedding) "
                        "VALUES (:id, :collection, :content, CAST(:metadata AS jsonb), :embedding)"
                    ),
                    {
                        "id": f"beta-{index}",
                        "collection": FIXTURE_COLLECTION_B,
                        "content": f"CANARY-BETA-{index} {FIXTURE_COLLECTION_B}",
                        "metadata": json.dumps({"canary": f"beta-{index}"}),
                        "embedding": Vector(_vector(index + 100)),
                    },
                )

    with_database(_seed)

    async def _check(database: db.Database) -> tuple[dict[str, int], list[store.Candidate], list[store.Candidate]]:
        engine = engine_of(database)
        counts = await store.count_by_collection(engine)
        from_a = await store.retrieve(
            engine, collection=FIXTURE_COLLECTION_A, query_embedding=_vector(1), limit=3
        )
        from_b = await store.retrieve(
            engine, collection=FIXTURE_COLLECTION_B, query_embedding=_vector(1), limit=10
        )
        return counts, from_a, from_b

    counts, from_a, from_b = with_database(_check)

    # 1. Both collections are really populated. Without this, everything below
    #    is vacuous.
    assert counts == {FIXTURE_COLLECTION_A: 3, FIXTURE_COLLECTION_B: 5}, (
        f"fixture seeding did not produce the expected counts, got {counts}. "
        "Every assertion below is downstream of these numbers."
    )

    # 2. The exact vector, and the requested count of it.
    assert len(from_a) == 3, (
        f"asked for 3 documents from {FIXTURE_COLLECTION_A!r} and got {len(from_a)}. "
        "A number below 3 is the signature of a post-filter: the limit was spent "
        "on the other collection's documents before the filter ran."
    )
    assert {candidate.collection for candidate in from_a} == {FIXTURE_COLLECTION_A}
    assert all("CANARY-ALPHA" in candidate.content for candidate in from_a)

    # 3. The other collection is unaffected and complete — asked for 10, got all
    #    5, so the same code path is not simply returning a short list.
    assert len(from_b) == 5
    assert {candidate.collection for candidate in from_b} == {FIXTURE_COLLECTION_B}
    assert all("CANARY-BETA" in candidate.content for candidate in from_b)

    # 4. Content and metadata survive the round trip alongside the id, because
    #    stage 2 (rerank) reads `content` and a Candidate that silently carried
    #    empty strings would be invisible to the isolation assertions above.
    for candidate in from_a:
        assert candidate.content.startswith("CANARY-ALPHA-")
        assert candidate.metadata["canary"].startswith("alpha-")

    # 5. Distances are present, finite and ascending — the caller can see the
    #    funnel working. Not a ranking-quality claim; a "did the ORDER BY and the
    #    distance projection both happen" claim.
    distances = [candidate.distance for candidate in from_a]
    assert distances == sorted(distances), f"candidates are not ordered by distance: {distances}"
    assert all(distance == distance for distance in distances), "a NaN distance means the vector was null"


def test_retrieve_selects_the_distance_metric_by_name_and_rejects_an_unknown_one():
    """The operator is chosen by a KEY into pre-written SQL, never interpolated.

    pgvector offers `<=>` (L2), `<+>` (negative inner product) and `<->`
    (cosine), and which one is used IS the distance metric — the same embeddings
    rank differently under each. So an unrecognised metric must FAIL, not
    silently fall back to a default: a fallback would change every ranking in the
    system because of a typo, with no error anywhere.

    This is also the test that keeps the "no interpolation" rule honest. The
    only way `retrieve` can be made to interpolate a caller-supplied string into
    SQL is if someone replaces `_RETRIEVE_SQL` with a format call — and the
    ValueError contract below is what that edit would break.
    """
    error_state: dict[str, Exception | None] = {}

    async def _run(database: db.Database) -> None:
        engine = engine_of(database)
        # The valid names all resolve.
        for metric in ("l2", "max_inner_product", "cosine"):
            try:
                await store.retrieve(
                    engine, collection=FIXTURE_COLLECTION_A, query_embedding=_vector(1), limit=1, metric=metric
                )
            except Exception as exc:  # noqa: BLE001
                error_state[metric] = exc
            else:
                error_state[metric] = None

        try:
            await store.retrieve(
                engine,
                collection=FIXTURE_COLLECTION_A,
                query_embedding=_vector(1),
                limit=1,
                metric="embedding; DROP TABLE documents; --",
            )
        except ValueError as exc:
            error_state["injection"] = exc
        else:
            error_state["injection"] = None

        # And a limit of zero is rejected before any SQL runs.
        try:
            await store.retrieve(engine, collection=FIXTURE_COLLECTION_A, query_embedding=_vector(1), limit=0)
        except ValueError as exc:
            error_state["limit"] = exc
        else:
            error_state["limit"] = None

    with_database(_run)

    for metric in ("l2", "max_inner_product", "cosine"):
        assert error_state[metric] is None, f"metric {metric!r} should be accepted, got {error_state[metric]!r}"

    assert error_state["injection"] is not None, (
        "an unrecognised metric was accepted. retrieve() must fail on an unknown "
        "metric rather than fall back, or a typo silently changes every ranking."
    )
    assert "unknown distance metric" in str(error_state["injection"])

    assert error_state["limit"] is not None, "limit=0 must be rejected"
    assert "limit must be at least 1" in str(error_state["limit"])


# ── 5. The API route ──────────────────────────────────────────────────────────
#
# Everything below needs a running API image that contains this phase's route.
# A 404 here means the image is stale, and the tests say so in the failure.


def test_a_posted_document_is_read_back_through_a_fresh_connection():
    """Ingestion round-trip, verified on a DIFFERENT connection than the one that wrote it.

    ── WHY THE FRESH READ, HARD ────────────────────────────────────────────────
    The API writes through its own pool, in its own process, from a POST body.
    Reading the value back off the same connection that took it — or off the
    response body — would prove that a function call returned its own arguments.
    This test reads with a SEPARATE engine, built by this test process, against
    the same PostgreSQL. That is the only read that establishes the real
    postcondition: the bytes are in the table, in the column, at the width the
    column declares.

    The dimension assertion is `vector_dims(embedding)` from the database rather
    than `len()` of the API's reported number, for the reason already written on
    the response model: those are two systems answering two different questions,
    and only one of them describes what was stored.
    """
    document_id = "roundtrip-document"

    response = post_document(
        document_payload(
            document_id,
            FIXTURE_COLLECTION_A,
            "How to roll back a bad migration: stop the writers, then revert.",
        )
    )

    assert response.status_code == 201, f"expected 201, got {response.status_code}: {response.text}"
    body = response.json()
    assert body["document_id"] == document_id
    assert body["collection"] == FIXTURE_COLLECTION_A
    assert body["outcome"] == "inserted"

    async def _read(database: db.Database) -> store.StoredDocument | None:
        return await store.fetch_document(engine_of(database), document_id=document_id)

    stored = with_database(_read)

    assert stored is not None, "the document was not in the database at all"
    assert stored.collection == FIXTURE_COLLECTION_A
    assert stored.content == "How to roll back a bad migration: stop the writers, then revert."
    assert stored.metadata == {"source": "test"}
    # The database's answer, not the response body's.
    assert stored.dimensions == SCHEMA_EMBEDDING_DIM == 384, (
        f"stored width is {stored.dimensions}, expected {SCHEMA_EMBEDDING_DIM}"
    )
    # And the response's claim agrees with the database's. Asserted separately
    # from the width above for the same reason test_db.py asserts both
    # `dimensions` and `len(embedding)`: the claim and the data are separate
    # things.
    assert body["dimensions"] == stored.dimensions


def test_posting_the_same_document_id_updates_it_in_place():
    """Re-posting an id UPDATES the row: one row, new content, new collection, moved `updated_at`.

    ── WHY `updated_at` IS ASSERTED AS "MOVED", NEVER PINNED ───────────────────
    Migration 0001 puts a `BEFORE UPDATE` trigger on this column and states that
    nothing but the trigger may write it. A test that asserted a specific
    timestamp would be testing something the design deliberately forbids — and
    would fail every time it ran, since `now()` is the transaction time.

    So the assertion is a strict `>`: the stored timestamp moved forward. That
    catches both regressions that matter — an upsert arm that silently creates a
    second row (in which case the old row's `updated_at` never moves), and an
    upsert that updates content but not the rest.

    The collection move is asserted separately and deliberately, because it is
    the behaviour most likely to be "fixed": `id` is the GLOBAL primary key, so
    a document re-posted under a different collection is MOVED. Dropping
    `collection = EXCLUDED.collection` from the `DO UPDATE SET` would leave a
    document whose content and embedding had changed while it was filed under the
    old collection — findable only in a collection the caller has stopped using.
    """
    document_id = "upsert-document"

    first = post_document(document_payload(document_id, FIXTURE_COLLECTION_A, "The original content."))
    assert first.status_code == 201, f"{first.status_code}: {first.text}"
    assert first.json()["outcome"] == "inserted"

    async def _read(database: db.Database) -> store.StoredDocument | None:
        return await store.fetch_document(engine_of(database), document_id=document_id)

    before = with_database(_read)
    assert before is not None
    assert before.collection == FIXTURE_COLLECTION_A
    assert before.content == "The original content."

    second = post_document(
        document_payload(
            document_id,
            FIXTURE_COLLECTION_B,
            "The replacement content, in a different collection.",
            metadata={"source": "test", "revision": 2},
        )
    )
    assert second.status_code == 201, f"{second.status_code}: {second.text}"
    assert second.json()["outcome"] == "updated", "the second POST took the INSERT arm, not the UPDATE arm"
    assert second.json()["collection"] == FIXTURE_COLLECTION_B

    async def _count_and_read(database: db.Database) -> tuple[int, store.StoredDocument | None]:
        engine = engine_of(database)
        async with engine.connect() as connection:
            total = int(
                await connection.scalar(
                    text("SELECT count(*) FROM documents WHERE id = :document_id"),
                    {"document_id": document_id},
                )
            )
        return total, await store.fetch_document(engine, document_id=document_id)

    total, after = with_database(_count_and_read)

    assert total == 1, (
        f"{total} rows exist for {document_id!r}; an upsert must leave exactly one. "
        "More than one means the primary key is not doing its job."
    )
    assert after is not None
    assert after.content == "The replacement content, in a different collection."
    assert after.collection == FIXTURE_COLLECTION_B, "the document was not MOVED to the new collection"
    assert after.metadata == {"source": "test", "revision": 2}

    # MOVED, not pinned. See the docstring.
    assert after.updated_at > before.updated_at, (
        f"updated_at did not move: {before.updated_at} -> {after.updated_at}. The "
        "BEFORE UPDATE trigger should have fired on the upsert's UPDATE arm."
    )
    # `created_at` must NOT move — it belongs to the original insert, and an
    # upsert that reset it would destroy the only record of when a document
    # entered the corpus.
    assert after.created_at == before.created_at


def test_a_document_is_embedded_bare_and_stores_384_dimensions():
    """The query-prefix invariant, made explicit for the ingestion path.

    ── THE INVARIANT ───────────────────────────────────────────────────────────
    bge-small-en-v1.5 was trained with `Represent this sentence for searching
    relevant passages: ` prepended to SEARCH QUERIES ONLY. A document must never
    carry it: prefixing one moves its vector off the manifold the other documents
    live on, permanently, in whatever database holds it, and nothing in any
    response ever says so.

    So what this test can assert TODAY is what it can honestly assert: that
    ingestion succeeds, that the text is stored verbatim, and that the stored
    vector is exactly 384 dimensions — i.e. that the document took the same
    path as `/embed`, which forwards its text bare.

    ── WHAT IT DELIBERATELY CANNOT ASSERT YET, AND WHY ─────────────────────────
    It cannot assert that the stored vector equals the embedding of the BARE
    text, because that comparison needs the embedder, and — more to the point —
    it needs a QUERY-side embedding to compare against, and the query-side
    prefix belongs on `/search`, which does not exist yet. Writing that
    assertion now would mean embedding the same text through `/embed` and
    comparing floats, which passes whether or not a prefix was ever added: both
    sides would be prefixed identically. A test that cannot fail is decoration.

    ── WHERE THE QUERY-PREFIX ASSERTION GOES WHEN `/search` LANDS ──────────────
    The test to add there, and to add HERE at the same time, is the pair:

        1. store a document D, and assert the stored vector equals
           `/embed(D.content)`  ← the document is bare, and it is CHECKABLE,
           because `/embed` is the bare path by definition;
        2. search for D's text through `/search` and assert the embedding used
           was built from PREFIX + text, not from text  ← the query is prefixed.

    Assertion (1) is the one that catches the corruption, and it becomes possible
    the moment this route's embedding is captured rather than discarded. This
    marked block is where it goes.
    """
    document_id = "prefix-invariant-document"
    content = "A document whose vector must never have carried the bge query prefix."

    response = post_document(document_payload(document_id, FIXTURE_COLLECTION_A, content))
    assert response.status_code == 201, f"{response.status_code}: {response.text}"
    assert response.json()["dimensions"] == SCHEMA_EMBEDDING_DIM

    async def _read(database: db.Database) -> store.StoredDocument | None:
        return await store.fetch_document(engine_of(database), document_id=document_id)

    stored = with_database(_read)

    assert stored is not None
    assert stored.dimensions == SCHEMA_EMBEDDING_DIM
    # The content is stored EXACTLY as submitted, with nothing prepended to the
    # stored text. This is not the prefix assertion (a prefix would be added
    # before embedding, not stored), but it is the half that is checkable
    # today, and it catches the cruder version of the bug where somebody
    # "helpfully" normalises the document on its way in.
    assert stored.content == content
    assert not stored.content.startswith("Represent this sentence")


def test_a_json_array_as_metadata_is_a_422_naming_the_field():
    """A non-object `metadata` is rejected at the EDGE, with a 422 naming it.

    The database also rejects it (`test_metadata_that_is_not_a_json_object_is_rejected_by_the_database`),
    and both checks are wanted for different reasons. The database's CHECK turns
    a silent type corruption into a loud failure; it does NOT tell the caller
    which field of THEIR request was wrong, because by then the request has
    already been embedded — an inference call spent to produce a row that will
    be refused.

    Validating at the edge means the caller learns about it in microseconds,
    before paying for an embedding, and gets a body that names `metadata`. The
    field name is asserted because "the request was bad" is much less useful to
    a client than "the request was bad HERE".
    """
    response = post_document(
        document_payload("bad-metadata-document", FIXTURE_COLLECTION_A, "content", metadata=[1, 2, 3])
    )

    assert response.status_code == 422, (
        f"a JSON array as metadata returned {response.status_code}, expected 422. "
        f"Body: {response.text[:300]}"
    )
    errors = response.json()["detail"]
    locations = {tuple(error["loc"]) for error in errors}
    assert any("metadata" in location for location in locations), (
        f"the 422 does not name the offending field; locations were {sorted(locations)}"
    )


def test_a_blank_collection_or_content_is_a_422_not_a_500():
    """Whitespace-only input must be refused by validation, before anything expensive happens.

    A 500 here would mean the blank value reached a layer that could not cope —
    almost certainly the embedder, which would either error on empty input or
    return a zero-length vector that then fails at the column. Either way the
    caller gets a server error for what is their own bad input, which is both a
    wrong status code and a wrong blame.

    Every invalid variant is checked in one test rather than several, because they
    share one failure mode and one fix; splitting them would produce four copies
    of the same assertion and four chances to forget a case. Whitespace-only is
    checked alongside empty because `NonBlankText` strips BEFORE min_length, and
    that ordering is what makes `"   "` invalid — `min_length` alone would accept
    it.
    """
    invalid_bodies = [
        {"collection": "   ", "content": "some content", "metadata": {}},
        {"collection": "", "content": "some content", "metadata": {}},
        {"collection": FIXTURE_COLLECTION_A, "content": "   ", "metadata": {}},
        {"collection": FIXTURE_COLLECTION_A, "content": "", "metadata": {}},
        {"collection": FIXTURE_COLLECTION_A, "content": "some content", "document_id": "  "},
    ]

    for overrides in invalid_bodies:
        payload = document_payload("blank-input-document", FIXTURE_COLLECTION_A, "placeholder")
        payload.update(overrides)
        # A blank field is most cleanly expressed by omitting it when empty, but
        # both spellings are worth checking: `""` must fail on length, and a
        # whitespace string must fail because it strips to nothing.
        if "document_id" in overrides and overrides["document_id"] == "":
            del payload["document_id"]

        response = post_document(payload)

        assert response.status_code == 422, (
            f"body {overrides!r} returned {response.status_code}, expected 422: {response.text[:300]}"
        )


# ── 6. The real corpus, read but not required to be loaded ────────────────────


def test_the_corpus_file_is_shaped_the_way_the_loader_expects():
    """`scripts/load_corpus.py` and this file both read the same file; this checks it.

    Not a test of the loader (which needs a running API) but of the CONTRACT
    between the corpus and the two things that read it: the fields the loader
    posts and the collections it summarises. A corpus that gained a field or lost
    a required one would otherwise fail inside the loader as a 422 forty times
    over, which reads as an API bug and is not one.

    Deliberately tolerant about whether the corpus has been LOADED. This file
    must pass on a machine that has never run the loader, and the assertion that
    actually needs loaded documents is
    `test_retrieve_returns_only_documents_from_the_asked_collection`, which seeds
    its own.
    """
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    documents = corpus["documents"]

    assert len(documents) == corpus["document_count"], (
        f"document_count says {corpus['document_count']} but there are {len(documents)}"
    )

    ids = [document["id"] for document in documents]
    assert len(set(ids)) == len(ids), "the corpus has duplicate document ids — upsert would silently merge them"

    for document in documents:
        assert set(document) >= {"id", "collection", "content"}, (
            f"{document.get('id')!r} is missing a field the loader posts"
        )
        assert document["collection"] in corpus["collections"], (
            f"{document['id']!r} names collection {document['collection']!r}, which the "
            "corpus header does not list"
        )
        assert document["content"].strip(), f"{document['id']!r} has blank content, which the API would refuse"


def test_both_corpus_collections_are_distinct_enough_to_be_a_canary():
    """The corpus's two collections must not share ids or be trivially separable by id.

    `data/corpus.json` is the canary for manual verification of collection
    isolation: an operator loads it, searches one collection, and must not see
    the other. That check is only meaningful if the ids visibly belong to one
    collection or the other — which is what this asserts. If a future regeneration
    produced ids that no longer carry their collection's prefix, a human reading
    search results could no longer tell at a glance whether isolation held, and
    the manual check would degrade into trusting the output.

    No documents need to be loaded for this, which is the point: the property is
    about the corpus file.
    """
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    documents = corpus["documents"]

    prefixes: dict[str, set[str]] = {}
    for document in documents:
        prefixes.setdefault(document["collection"], set()).add(document["id"])

    assert len(prefixes) >= 2, f"the corpus has {len(prefixes)} collection(s); isolation cannot be checked"

    # Each collection's ids must be distinguishable from another collection's by
    # their leading token.
    for collection, collection_ids in prefixes.items():
        leading = {document_id.split("-")[0] for document_id in collection_ids}
        others = set().union(*(ids for name, ids in prefixes.items() if name != collection))
        foreign_leading = {document_id.split("-")[0] for document_id in others}
        assert not (leading & foreign_leading), (
            f"collections {collection!r} and another share the id prefix(es) "
            f"{sorted(leading & foreign_leading)}; a reader could no longer tell "
            "which collection a search result came from"
        )
