"""lemondrop API — the document store: the only module in this service that writes SQL.

Three responsibilities, and nothing else:

1. **Making `vector` usable at all.** See `prepare_database` — this is not a
   convenience, it is the difference between every vector write succeeding and
   every vector write failing intermittently.
2. **Writing documents** (`upsert_document`).
3. **Reading them back for retrieval** (`retrieve`, `fetch_document`,
   `count_by_collection`).

── WHY RAW `sqlalchemy.text()` AND NOT THE ORM ────────────────────────────────
Migration 0001 wrote the schema in raw SQL and the phase before this one made
the same call for the engine. It is the same reasoning here. The only query in
this file is

    SELECT ... FROM documents WHERE collection = $1 ORDER BY <op> $2 LIMIT $3

and the ORM's contribution to it would be a declarative class, a session
lifecycle and an identity map that buy nothing for one parameterised query —
while costing a second, independently-editable definition of the table shape
that could disagree with migration 0001 without anything noticing.

Measured on SQLAlchemy 2.0.54 (see `api/tests/test_documents.py`):
`'vector' in d.colspecs` is `False` for the asyncpg dialect. So `pgvector`'s
`VECTOR` type cannot be used as a column type through this dialect at all, and
`text()` is not a workaround for that — it is the same conclusion reached from
the other direction. What `text()` *does* buy, and what matters, is that every
value in this file reaches PostgreSQL as a bound parameter. See the audit note
on each statement below.

── THE ONE RULE EVERY FUNCTION HERE FOLLOWS ───────────────────────────────────
**No caller-supplied value is ever formatted into a SQL string.** Every id,
collection, content, metadata, embedding, limit and document count is a `:name`
bind parameter. This is not a style preference; it is the only reason the
`collection` value can be arbitrary caller input at all. There is no f-string,
no `%`, no `.format()` and no string concatenation anywhere in this file's SQL.
The operator selection in `retrieve` looks like an exception and is not: it is a
dict lookup into statements that were written out by hand at import time, so
there is still no code path that could splice a caller's string into SQL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pgvector import Vector
from pgvector.asyncpg import register_vector
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import db

logger = logging.getLogger(__name__)


# ── Making `vector` work at all ───────────────────────────────────────────────
#
# ── THE TRAP, AND WHY IT IS WRITTEN DOWN AT LENGTH ─────────────────────────────
# asyncpg type codecs are registered PER CONNECTION, not per engine, not per
# pool and not per process. `register_vector(conn)` issues a
# `set_type_codec('vector', ...)` on one wire protocol connection, and that
# codec exists on that connection and on no other.
#
# `create_async_engine` builds a POOL. The pool is empty at startup and grows
# lazily: the first query creates connection #1, and each concurrent query
# beyond `pool_size` creates another. So at the moment a vector query runs, the
# pool may hold one connection, two, or three — and only the ones that happened
# to have the registration applied to them can carry a vector.
#
# Register on "the connection I happened to get" and you have registered it on
# one. Every other connection in the pool is unregistered, and a vector query
# that lands on one of them fails with
#
#     asyncpg.exceptions.DataError: invalid input for query argument $N:
#     Vector([...]) (expected str, got Vector)
#
# — intermittently, and only under real concurrency, because which pooled
# connection serves a request is a scheduling detail. A single-query test
# cannot see this. A test that runs one vector INSERT sees one connection and
# passes; production sees three and fails roughly one time in three. This is
# the single most dangerous bug shape in this file, and
# `api/tests/test_documents.py::test_every_pooled_connection_has_the_vector_codec`
# exists specifically to make it visible.


def _register_vector_on_connect(
    dbapi_connection: Any,
    connection_record: Any,  # noqa: ANN401 — SQLAlchemy's pool record, unused
) -> None:
    """Register the pgvector codecs on one freshly-created pooled connection.

    ── WHY AN EVENT LISTENER AND NOT SOMETHING ELSE ────────────────────────────
    Two candidate mechanisms were rejected, and both rejections are about
    COVERAGE rather than about taste:

    * **Register on the connection you acquired.** This is the trap described
      above, in miniature: it makes one connection work and leaves the rest of
      the pool broken. It cannot be made correct, because at the moment you hold
      a connection you do not know whether it was created before or after any
      registration you performed, and you do not control which connection the
      next request receives.

    * **Register on every checkout** (`event.listen(engine, "checkout", ...)`).
      This does reach every connection, eventually, because every checkout is
      preceded by one. It is rejected for two reasons. First, it re-registers
      on every single checkout — three `set_type_codec` round trips per request
      on a pool that exists because the host is a `t3.micro`. Second, and worse,
      it interleaves with `pool_pre_ping=True` (set in `config.engine_kwargs`):
      the ping runs before the checkout hook on a recycled connection, so
      ordering between the two has to be reasoned about rather than observed.
      "Before any statement is prepared" is exactly the property the `connect`
      event gives for free, with no ordering question to get wrong.

    So: **`event.listen(engine.sync_engine, "connect")`**, which fires from
    `Pool._ConnectionRecord.__connect` for EVERY connection the pool creates —
    at creation, before the pool can hand it to any caller, before any statement
    is prepared on it. It cannot miss a connection, because there is no path by
    which a pooled connection exists without having passed through it.

    ── WHY `sync_engine` AND NOT THE ASYNC ENGINE ──────────────────────────────
    The event is dispatched from the *synchronous* pool that an `AsyncEngine`
    wraps. `event.listen(async_engine, "connect", ...)` is accepted by
    SQLAlchemy and would attach to the async engine's own dispatch, which does
    not carry the pool's `connect` event. The `sync_engine` attribute is the
    documented handle on the pool for exactly this, and pgvector's own README
    uses the same shape for the Psycopg async case.

    ── WHY `dbapi_connection.await_(...)` AND NOT `async def` ──────────────────
    This is a synchronous listener. It cannot be `async def`, because SQLAlchemy
    calls it synchronously from inside the greenlet that `greenlet_spawn`
    created for this connection. `.await_()` (which is `await_only`) suspends
    that greenlet, hands the coroutine to the event loop, and resumes the
    listener when it is done — which is exactly what SQLAlchemy's own asyncpg
    dialect does for its JSON and JSONB codecs in `PGDialect_asyncpg.on_connect`.
    This is a library-blessed pattern, not a workaround.

    Note on the API shape, since it is easy to get wrong and the failure is
    cryptic: on SQLAlchemy 2.0.54 `.await_()` takes a coroutine OBJECT, not a
    function. `.await_(register_vector)` raises `TypeError: 'function' object
    can't be awaited`. The connection argument is bound here, first.

    ── WHY `dbapi_connection._connection` ──────────────────────────────────────
    `register_vector` needs the raw `asyncpg.Connection`. The object the pool
    hands to a listener is SQLAlchemy's `AsyncAdapt_asyncpg_connection` adapter,
    which does not expose the driver's `set_type_codec`. The raw connection is
    reachable as `._connection`, and that underscore is not a guess: it is
    precisely what SQLAlchemy's own `on_connect` reaches for
    (`conn._connection.set_type_codec(...)` in
    `dialect/postgresql/asyncpg.py`). There is no public accessor for it on the
    adapter — `dialect.get_driver_connection()` takes a different object — so
    this is the supported-by-precedent route, and it is isolated to this one
    function so that a future SQLAlchemy rename is a one-line fix with one
    obvious place to look.
    """
    raw_connection = dbapi_connection._connection
    dbapi_connection.await_(register_vector(raw_connection))


async def prepare_database(database: db.Database | None) -> bool:
    """Arm the engine for vector writes. Returns whether an engine was found.

    ── WHY THIS DISPOSES THE POOL, AND WHY THAT IS THE WHOLE POINT ─────────────
    `db.startup()` PINGS the database before returning (`db.Database.ping`).
    That ping checks a connection out of the pool, runs `SELECT 1` on it, and
    checks it back in. By the time this function can run, there is already one
    live pooled connection — and it was created BEFORE any codec registration
    existed, so it is permanently unregistered. Attaching the listener at that
    point covers every connection created from now on and leaves that first one
    broken forever.

    This was measured, not assumed. `api/tests/test_documents.py` runs the same
    scenario both ways: with the dispose, all three pooled connections carry the
    codec and all three vector writes succeed; without it, the recycled
    connection from the ping fails and the two fresh ones succeed — the exact
    intermittent, concurrency-only, single-query-test-invisible failure this
    whole function exists to prevent.

    `AsyncEngine.dispose()` closes every checked-in and idle connection, so the
    unregistered one is terminated before it can ever be handed out again. Every
    subsequent connection is created under the listener. `dispose()` keeps the
    pool object and the engine-level event registry intact, so the listener
    survives it — also verified by that test rather than trusted.

    ── WHY NOT "REGISTER ON THE EXISTING CONNECTIONS TOO" ─────────────────────
    The other repair would be to reach into `pool._pool`, iterate the idle
    connections and await a registration on each. It is rejected: `pool._pool`
    is private and its shape is an implementation detail, it cannot see
    connections that are checked out at that instant, and it introduces a window
    where a request could be served by an unregistered connection. Disposing is
    one public call with no window: after it returns, no unregistered connection
    exists.

    Idempotent. Calling it twice is safe and is a no-op beyond a second dispose
    (the cost of which is one fresh TCP connection on the next query).
    """
    engine = getattr(database, "engine", None) if database is not None else None
    if engine is None:
        # Not an error. `db.startup` never raises by design (see its docstring):
        # an unconfigured or unreachable database leaves the process serving, and
        # `/health/ready` reports 503. A route that needs the database reports
        # its own 503 for the same reason. Logged, never fatal.
        logger.warning("no database engine: vector writes are not available")
        return False

    sync_engine = engine.sync_engine
    if not event.contains(sync_engine, "connect", _register_vector_on_connect):
        event.listen(sync_engine, "connect", _register_vector_on_connect)
        logger.info("pgvector codecs registered for every pooled connection")

    await engine.dispose()
    return True


# ── Statements ────────────────────────────────────────────────────────────────
#
# Named module constants, one per metric, looked up by a symbolic key. This is
# how the vector similarity operator is selected WITHOUT interpolating anything
# into SQL — see `retrieve` for why a bound parameter cannot express it at all,
# and for why this lookup is the right answer instead.
#
# pgvector 0.8.7 exposes four distance operators, and WHICH ONE IS USED IS THE
# DISTANCE METRIC — the same embeddings ranked by `<=>` and by `<->` produce
# genuinely different orderings, so this is a retrieval-quality decision and not
# a formatting one. `<+>` is worth reading twice: it is the NEGATIVE inner
# product, so `ORDER BY embedding <+> $q` ascending puts the LARGEST inner
# product first, which is the max-inner-product ranking.


_RETRIEVE_SQL: dict[str, Any] = {
    # `<=>` — L2 (Euclidean) distance. The default, and the operator the
    # migration's own note about a future `vector_l2_ops` index assumes.
    "l2": text(
        "SELECT id, collection, content, metadata, "
        "embedding <=> CAST(:query AS vector) AS distance "
        "FROM documents "
        "WHERE collection = :collection "
        "ORDER BY distance "
        "LIMIT :limit"
    ),
    # `<+>` — negative inner product; largest inner product ranks first.
    "max_inner_product": text(
        "SELECT id, collection, content, metadata, "
        "embedding <+> CAST(:query AS vector) AS distance "
        "FROM documents "
        "WHERE collection = :collection "
        "ORDER BY distance "
        "LIMIT :limit"
    ),
    # `<->` — cosine distance. Ranking matches on direction, ignoring magnitude.
    "cosine": text(
        "SELECT id, collection, content, metadata, "
        "embedding <-> CAST(:query AS vector) AS distance "
        "FROM documents "
        "WHERE collection = :collection "
        "ORDER BY distance "
        "LIMIT :limit"
    ),
}

#: The metric used when a caller does not name one.
DEFAULT_METRIC = "l2"


def _retrieve_sql(metric: str) -> Any:
    """Return the pre-written statement for `metric`, or raise.

    The lookup is the safety mechanism. There is no code path that puts an
    arbitrary string into SQL: the caller supplies a KEY, not SQL, and an
    unrecognised key is an error rather than a fallback. A `.get(metric, DEFAULT)`
    would quietly substitute a different metric for a typo and change every
    ranking in the system, so the `KeyError` is converted into a `ValueError`
    that names what was asked for and what was available.

    The exception message quotes the requested key. That is safe because the key
    is an operator name from a closed set chosen by this module and not passed
    through to SQL — but it is logged as a bare metric name and never returned to
    an HTTP client by any route in this service.
    """
    try:
        return _RETRIEVE_SQL[metric]
    except KeyError:
        raise ValueError(
            f"unknown distance metric {metric!r}; expected one of "
            f"{sorted(_RETRIEVE_SQL)}"
        ) from None


_UPSERT_SQL = text(
    "INSERT INTO documents (id, collection, content, metadata, embedding) "
    "VALUES (:document_id, :collection, :content, CAST(:metadata AS jsonb), CAST(:embedding AS vector)) "
    "ON CONFLICT (id) DO UPDATE SET "
    "collection = EXCLUDED.collection, "
    "content = EXCLUDED.content, "
    "metadata = EXCLUDED.metadata, "
    "embedding = EXCLUDED.embedding "
    "RETURNING (xmax = 0) AS inserted, vector_dims(embedding) AS dimensions, updated_at"
)

# ── WHY `updated_at` IS NOT IN THE STATEMENT ABOVE. READ THIS BEFORE ADDING IT.
#
# Migration 0001 installs a `BEFORE UPDATE ... FOR EACH ROW` trigger
# (`documents_set_updated_at`) that owns this column. Nothing else writes it.
#
# Setting it here would defeat the entire reason the trigger exists. The
# trigger's value is not "it saves a line of SQL"; it is that the invariant is
# STRUCTURAL — `updated_at` cannot be stale, because there is no code path that
# can make it stale. Application-managed `updated_at` is correct only if EVERY
# writer remembers, and the failure when one forgets is not an error: it is a
# plausible, silently wrong timestamp on a column something will eventually
# trust. The `ON CONFLICT DO UPDATE` arm of an upsert is exactly the sort of
# place to forget, which is why the migration names it.
#
# `RETURNING updated_at` below is a READ of the column, not a write. The test
# asserts it MOVED after an update; it deliberately never asserts a specific
# value, because the trigger owns that and it is unpinnable by design.

_FETCH_SQL = text(
    "SELECT id, collection, content, metadata, "
    "vector_dims(embedding) AS dimensions, created_at, updated_at "
    "FROM documents "
    "WHERE id = :document_id"
)

_COUNT_BY_COLLECTION_SQL = text(
    "SELECT collection, count(*) AS document_count FROM documents GROUP BY collection ORDER BY collection"
)

_DELETE_COLLECTION_SQL = text("DELETE FROM documents WHERE collection = :collection")


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UpsertResult:
    """What actually happened to one document, read back from the database.

    `inserted` distinguishes the two arms of `ON CONFLICT`. `dimensions` is
    `vector_dims(embedding)` — the width the DATABASE accepted, not the width
    the model claimed to produce. Those are different numbers from different
    systems, and the whole point of reporting the database's is that a mismatch
    surfaces on the write that caused it instead of weeks later as mysteriously
    bad retrieval.
    """

    document_id: str
    collection: str
    #: `True` if the row was created, `False` if the id already existed and its
    #: columns (including `collection`) were updated in place.
    inserted: bool
    #: The width actually stored, as `vector_dims()` reported it.
    dimensions: int
    updated_at: Any


@dataclass(frozen=True)
class Candidate:
    """One stage-1 candidate, with the distance that put it where it is.

    `content` is carried so the rerank stage has something to score without a
    second round trip. `distance` is returned rather than discarded because a
    retrieval system that cannot show its scores is a retrieval system that
    cannot be debugged: when results are bad, the first question is always
    "what did stage 1 actually think", and a candidate list without distances
    cannot answer it.

    Distance is ascending and lower-is-better for all three metrics — including
    `<+>`, because pgvector defines it as the NEGATIVE inner product.
    """

    document_id: str
    collection: str
    content: str
    metadata: dict[str, Any]
    distance: float


@dataclass(frozen=True)
class StoredDocument:
    """One document as it exists in the database right now."""

    document_id: str
    collection: str
    content: str
    metadata: dict[str, Any]
    dimensions: int
    created_at: Any
    updated_at: Any


# ── Writing ───────────────────────────────────────────────────────────────────


async def upsert_document(
    engine: AsyncEngine,
    *,
    document_id: str,
    collection: str,
    content: str,
    metadata: dict[str, Any],
    embedding: list[float],
) -> UpsertResult:
    """Insert a document, or update it in place when the id already exists.

    ── WHAT IT GUARANTEES ──────────────────────────────────────────────────────
    Exactly one row exists for `document_id` afterwards, whichever arm of the
    `ON CONFLICT` ran. Re-posting the same id is therefore safe and idempotent:
    it updates, it never duplicates, and it never leaves the caller guessing
    which of the two happened — `UpsertResult.inserted` says.

    ── WHY MOVING COLLECTIONS IS AN UPDATE AND NOT A SECOND ROW ────────────────
    Because `id` is the GLOBAL PRIMARY KEY of `documents`, not `(collection, id)`.
    Migration 0001 states that choice and states its consequence: the same id
    cannot exist in two collections. So a caller that re-ingests a document under
    a different collection gets an `UPDATE` of the `collection` column on the one
    row that already exists — which is why `collection = EXCLUDED.collection` is
    in the `DO UPDATE SET` list above. Dropping it would leave a document filed
    under its original collection while its content and embedding changed
    underneath it: the worst outcome available, since the document would be
    findable only in a collection the caller has stopped using. If per-collection
    id reuse is ever genuinely wanted, the primary key is what has to change, and
    that is a migration affecting every query — not a decision for this function.

    ── WHY THE METADATA IS JSON-SERIALISED HERE AND CAST IN SQL ────────────────
    `metadata` is a Python `dict`, and the column is `JSONB`. SQLAlchemy's
    `text()` carries no type information for a `:name` bind, so the dict would
    reach asyncpg as an opaque Python object with no codec bound to JSONB's OID.
    `json.dumps` plus `CAST(:metadata AS jsonb)` gives the driver a plain string
    and lets PostgreSQL do the parse. It stays a bound parameter — the CAST is
    SQL syntax around a bind, not a value spliced into a string — and it lets the
    database's own CHECK constraint do the validating, which is where the
    `jsonb_typeof(metadata) = 'object'` rule actually lives.

    ── WHAT BREAKS IF THE ENGINE WAS NEVER PREPARED ────────────────────────────
    This raises `asyncpg.DataError: invalid input for query argument ...`. That
    is not a bug here; it is `prepare_database` not having been called. The
    engine is taken as an argument precisely so that no route can accidentally
    build its own.
    """
    # `engine.begin()` owns the transaction: it checks a connection out, opens
    # one, and COMMITS on a clean exit / ROLLS BACK on an exception. That is why
    # the caller cannot forget the commit — the ownership is here, not in the
    # route, where forgetting it would return 201 for a write that was then
    # thrown away.
    async with engine.begin() as connection:
        row = (
            await connection.execute(
                _UPSERT_SQL,
                {
                    "document_id": document_id,
                    "collection": collection,
                    "content": content,
                    "metadata": json.dumps(metadata),
                    "embedding": Vector(embedding),
                },
            )
        ).one()

    # `inserted` via `xmax = 0`: on an INSERT the row's system `xmax` column is
    # zero, and on an UPDATE it holds the updating transaction's id. This is the
    # standard PostgreSQL idiom for distinguishing the arms of an upsert without
    # a second query and without a race between "check" and "insert". It is a
    # heuristic by PostgreSQL's own standards — a row locked by a concurrent
    # transaction can also read as inserted — which is why nothing load-bearing
    # is decided from it here. It is a REPORTING field: the caller is told what
    # happened, and if it is ever wrong the data is still correct.
    return UpsertResult(
        document_id=document_id,
        collection=collection,
        inserted=bool(row.inserted),
        # The database's own answer, not len(embedding). See the class docstring.
        dimensions=int(row.dimensions),
        updated_at=row.updated_at,
    )


# ── Reading ───────────────────────────────────────────────────────────────────


async def retrieve(
    engine: AsyncEngine,
    *,
    collection: str,
    query_embedding: list[float],
    limit: int,
    metric: str = DEFAULT_METRIC,
) -> list[Candidate]:
    """Return the `limit` documents in `collection` nearest to `query_embedding`.

    ── THE COLLECTION FILTER IS IN THE `WHERE` CLAUSE. IT MUST STAY THERE. ─────
    This is the requirement in this file most likely to be "fixed" wrongly, so
    the reason is stated rather than left to be rediscovered:

    A fetch-then-filter implementation — `SELECT ... ORDER BY distance LIMIT 10`
    over the whole table, followed by `[c for c in rows if c.collection == X]` —
    **passes a response-level isolation test.** A test that searches collection A
    and asserts "no document from collection B came back" is GREEN. And the
    system is broken.

    The reason is that the `limit` candidates have already been chosen by the
    time the filter runs, and they were chosen from the WRONG POPULATION. If
    collection A holds 3 documents and collection B holds 37, a global top-10 is
    almost entirely B; filtering that to A returns 3 rows at best and usually
    far fewer — and worse, the ones it does return are A's best out of a global
    shortlist that excluded A's best outright. Recall is destroyed silently, in
    a way that gets WORSE as the corpus grows and BETTER as other collections
    shrink. No error is raised. Retrieval simply gets quietly worse, and the
    regression is invisible to every test that only checks isolation.

    So: the predicate is in SQL, where the planner can use
    `documents_collection_idx` to narrow to one collection BEFORE the vector
    comparison, and the `limit` is applied to the right population. A response
    shape test is not evidence that this is correct — the funnel is, which is
    why `count_by_collection` exists and why the tests assert against real
    counts rather than against the absence of a foreign id.

    ── WHY THE OPERATOR IS NOT A BOUND PARAMETER ───────────────────────────────
    Because PostgreSQL cannot express it as one. A bind parameter stands for a
    VALUE, and `a $1 b` is not a legal expression — the position of an operator
    is part of the grammar, not an operand. There is no `OPERATOR(...)` form that
    takes a parameter either; the operator name there is still a bare token.

    So the choice is between "interpolate a string" and "do not interpolate a
    string", and this module does the latter: the four statements in
    `_RETRIEVE_SQL` are written out in full, one per metric, and the caller
    supplies a KEY. There is no code path in this file that can put a caller's
    string into SQL, which is a stronger guarantee than a whitelist around an
    f-string would be — a whitelist can be widened by accident on a bad day; a
    dict of literal statements cannot be widened without someone deliberately
    editing SQL.

    Why it matters beyond hygiene: which operator is used IS the distance metric.
    `<=>`, `<+>` and `<->` rank the same embeddings differently, so silently
    substituting one for another changes every ranking in the system. A typo must
    fail loudly (`ValueError` from `_retrieve_sql`), which it does.

    ── WHY `CAST(:query AS vector)` ────────────────────────────────────────────
    Same reason as `metadata` in `upsert_document`, plus one more: `text()`
    carries no type for the bind, so without the CAST PostgreSQL cannot pin the
    parameter's type and asyncpg cannot encode it. It is a bound parameter with
    an explicit type, not a spliced value.

    ── WHY `ORDER BY distance` (THE OUTPUT ALIAS) ──────────────────────────────
    Because the vector appears exactly ONCE in the statement. Using the same
    `:query` bind in both the SELECT list and the ORDER BY collapses into one
    wire parameter used in two places, and asyncpg then reports
    `AmbiguousParameterError: inconsistent types deduced for parameter $1:
    vector versus text` — the SELECT-list occurrence is inferred as the
    statement's OUTPUT type (text-ish) while the ORDER BY occurrence is inferred
    from the operator signature (vector). Naming the distance once in the SELECT
    list and ordering by its alias sidesteps that entirely, and reads better.
    """
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")

    statement = _retrieve_sql(metric)

    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                statement,
                {
                    "collection": collection,
                    "query": Vector(query_embedding),
                    "limit": limit,
                },
            )
        ).all()

    return [
        Candidate(
            document_id=row.id,
            collection=row.collection,
            content=row.content,
            metadata=dict(row.metadata),
            distance=float(row.distance),
        )
        for row in rows
    ]


async def fetch_document(engine: AsyncEngine, *, document_id: str) -> StoredDocument | None:
    """Read one document back by id, or `None` if there is no such document.

    Exists mainly so a caller can verify a WRITE with a READ that is not the
    write's own connection — which is the only kind of read that proves anything.
    A value echoed back from the connection that just inserted it proves the
    arguments survived the call, not that PostgreSQL stored them.
    """
    async with engine.connect() as connection:
        row = (await connection.execute(_FETCH_SQL, {"document_id": document_id})).first()

    if row is None:
        return None

    return StoredDocument(
        document_id=row.id,
        collection=row.collection,
        content=row.content,
        metadata=dict(row.metadata),
        dimensions=int(row.dimensions),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def count_by_collection(engine: AsyncEngine) -> dict[str, int]:
    """Return `{collection: document_count}` for every collection that has rows.

    A NUMBER rather than a boolean assertion, and that distinction is the point.
    "Search for collection A returned no document from collection B" can be
    satisfied by a system that stored nothing at all, and by one whose filter
    works. "Collection A holds 20 documents and collection B holds 20" cannot: it
    forces a verification of BOTH sides, so a loader that silently dropped a
    collection fails the check rather than quietly shrinking the corpus the next
    search will draw from.
    """
    async with engine.connect() as connection:
        rows = (await connection.execute(_COUNT_BY_COLLECTION_SQL)).all()

    return {row.collection: int(row.document_count) for row in rows}


async def delete_collection(engine: AsyncEngine, *, collection: str) -> int:
    """Delete every document in `collection`. Returns how many rows went.

    NOT part of the product. It exists for two reasons and neither of them is a
    feature: the tests need to seed and clean up a collection without stepping on
    the real corpus, and an operator who loads the wrong corpus needs an escape
    hatch that is not `psql`. It is deliberately collection-scoped and
    parameterised — a delete that took a table name or a raw predicate would be
    the most dangerous function in this file, and there is no reason for it to be.

    There is deliberately no "delete by document id" either: ingestion is an
    upsert, so re-posting is the intended way to correct a single document, and a
    delete path per document is one more way to lose data by accident.
    """
    async with engine.begin() as connection:
        result = await connection.execute(_DELETE_COLLECTION_SQL, {"collection": collection})

    deleted = int(result.rowcount or 0)
    logger.info("deleted %d document(s) from collection %r", deleted, collection)
    return deleted
