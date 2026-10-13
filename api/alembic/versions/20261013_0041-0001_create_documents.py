"""create the documents table (pgvector, 384-dim)

Revision ID: 0001
Revises:
Create Date: 2026-10-13

The first and only schema migration so far: one table, holding an embedded
document. Every design choice below is commented, because the interesting part
of a schema is not what it stores but what it makes IMPOSSIBLE to store.

OPERATIONS, in order, deliberately kept as separate op.execute() calls rather
than one blob of DDL:

  1. CREATE EXTENSION vector
  2. CREATE TABLE documents
  3. ALTER TABLE ... ADD CONSTRAINT (the two CHECKs and the PK/constraints)
  4. CREATE INDEX on documents(collection)
  5. CREATE FUNCTION + TRIGGER for updated_at

They are separate because a failure should be attributable: when this migration
dies halfway we want to know which operation was the problem, and because a
reviewer reads a migration as a sequence of claims rather than as a wall. Note
that each op.execute() carries exactly ONE statement — this is not stylistic.
asyncpg refuses multiple statements in a single prepared statement, so batching
two CREATE statements into one string would fail at runtime with a protocol
error that has nothing to do with the SQL being wrong.

The statement style is raw SQL via op.execute() rather than op.create_table()
with sa.Column objects. pgvector's `vector` type is not part of SQLAlchemy's
built-in type registry: SQLAlchemy can only recognise it through the separate
`pgvector-python` package, which ships a `pgvector.sqlalchemy.VECTOR` type and
has manylinux wheels for CPython 3.12 — so it is available, and saying otherwise
would be wrong. It is still the wrong trade here. Adding that dependency purely
so a DDL helper can recognise one column would put a runtime dependency in the
production image that exists only to serve a migration file. Raw SQL keeps the
migration honest about what it does and adds nothing to the image.
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. The pgvector extension ─────────────────────────────────────────────
    # The `<=>` operator, the vector type and any future ANN index all come from
    # this extension; without it nothing else in this file resolves.
    #
    # IF NOT EXISTS so re-running is harmless — which matters because the
    # operator's local devdb is a long-lived volume that may already have it
    # from an earlier manual `CREATE EXTENSION`.
    #
    # ON RDS THIS REQUIRES THE MASTER USER, because only the rds_superuser role
    # may create extensions. Two consequences, both deliberate and neither
    # worked around here:
    #   * the migration cannot be run by the application's own database role, so
    #     that role is granted DML only and migrations run out of band, as a
    #     separate privileged step (see api/alembic/README.md);
    #   * the correct end state is a second, least-privilege role for the app —
    #     one that holds rds_superuser and therefore cannot be given to code
    #     that processes user text. Shipping the app on the master credential
    #     would mean an injection bug is a database-compromise bug. That
    #     separation is Phase 2's job; what matters here is that this migration
    #     is honest about needing privilege the runtime role will not have.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ── 2. The table ──────────────────────────────────────────────────────────
    # `id` is TEXT, not UUID/serial. Chosen because document ids are minted by
    # the ingestion path (an external id, a content hash, a source-system key),
    # not by the database; a generated column would mean a second identity in
    # the system and a mapping nobody would trust.
    #
    # `embedding vector(384)` is the load-bearing column. The dimension is fixed
    # in the type, not merely documented: pgvector enforces it at the database
    # boundary, so a 768-dim vector from a swapped model fails loudly at INSERT
    # instead of silently degrading every retrieval score. See the note after
    # the constraints.
    op.execute(
        """
        CREATE TABLE documents (
            id         TEXT        PRIMARY KEY,
            collection TEXT        NOT NULL,
            content    TEXT        NOT NULL,
            metadata   JSONB       NOT NULL DEFAULT '{}'::jsonb,
            embedding  vector(384) NOT NULL,
            created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """
    )

    # ── 3. Constraints ────────────────────────────────────────────────────────
    # A blank collection name must be impossible. `collection` is the partition
    # key that every retrieval query filters on, and the empty string is a
    # perfectly valid TEXT value that passes NOT NULL while being useless: an
    # empty collection is invisible in any UI that renders a collection list, and
    # it partitions documents away from every query that actually names a
    # collection. It is the kind of bad row that gets written by one buggy
    # client and then is invisible forever. btrim() rather than = '' so that
    # '   ' is rejected too — whitespace-only is the same bug wearing a hat.
    op.execute(
        "ALTER TABLE documents "
        "ADD CONSTRAINT documents_collection_not_blank "
        "CHECK (length(btrim(collection)) > 0);"
    )

    # `metadata` is a map in every consumer: .get("source"), ["tags"], item
    # access in JSON serialisation. jsonb accepts an array, a string, a number,
    # bool or null, so the column would happily store `[1,2,3]` and the failure
    # would surface as an AttributeError or TypeError in application code,
    # somewhere far from the INSERT that caused it. This constraint moves that
    # failure to the statement that produced it. Note it also rules out a
    # JSON null in that key's place — `jsonb_typeof('null'::jsonb)` is not
    # 'object' — which is intentional: absent metadata is `{}`, not `null`.
    op.execute(
        "ALTER TABLE documents "
        "ADD CONSTRAINT documents_metadata_is_object "
        "CHECK (jsonb_typeof(metadata) = 'object');"
    )

    # WHY THERE IS NO EXPLICIT CHECK ON THE EMBEDDING DIMENSION
    # There does not need to be one. `vector(384)` is itself the check: the type
    # carries the dimension and rejects any vector whose length differs at
    # INSERT. Adding `CHECK (vector_dims(embedding) = 384)` on top would be a
    # restatement of something the column type already guarantees — and the kind
    # of duplication that drifts: change the model, change the type, forget the
    # constraint, and now two definitions of "384" disagree. The dimension lives
    # in exactly one place.
    #
    # The practical consequence is the one worth having: swapping the embedder
    # for a model with a different dimensionality fails immediately and loudly,
    # on the first write, naming the column — instead of quietly writing vectors
    # whose distances are meaningless, which would show up only as "search got
    # worse" weeks later with nothing pointing at the cause.

    # ── 4. Indexes ────────────────────────────────────────────────────────────
    # The primary key on `id` is already implied by the column declaration and is
    # backed by a btree index automatically; there is nothing to add here.
    #
    # A plain btree on `collection`, and only on `collection`. Every retrieval
    # query MUST carry `WHERE collection = $1` — cross-collection search is not a
    # feature of this system — so this index is on the one predicate that is
    # always true of the query.
    #
    # It earns its place even at this size: it is what lets PostgreSQL narrow to
    # one partition before the vector comparison, rather than comparing every
    # row's embedding and then throwing most of them away.
    op.execute("CREATE INDEX documents_collection_idx ON documents (collection);")

    # WHY THERE IS NO HNSW OR IVFFLAT INDEX — DELIBERATELY, NOT FORGOTTEN
    # Vector search here is EXACT: `ORDER BY embedding <=> $query`, which returns
    # the true nearest neighbours. At the current corpus (~40 documents) that is
    # a sequential scan of 40 rows — microseconds — and an ANN index would be
    # pure overhead: build time, insert-time maintenance, extra disk, and an
    # approximate answer that is less accurate than what we already get for
    # free. pgvector's own guidance is that approximate indexes stop paying for
    # themselves somewhere in the low thousands of vectors.
    #
    # The operator deferred this deliberately. When the corpus grows past roughly
    # 10k rows, RE-MEASURE before indexing, and measure all three of:
    #   * the latency of the exact query with the collection filter applied, and
    #     whether it has become the dominant term in end-to-end search latency;
    #   * recall@k of exact search on a sampled query set — this is the number an
    #     ANN index is allowed to lose, and it must be recorded BEFORE the index
    #     exists so the comparison is honest rather than post-hoc;
    #   * index build and maintenance cost, which is paid on every INSERT and
    #     every UPDATE of the embedding.
    # HNSW (better recall, more build time and memory, no training step) and
    # IVFFlat (smaller and faster to build, but needs data loaded first to train
    # its lists, and degrades if the corpus grows after training) are different
    # trades — the choice is driven by that measurement, not by preference.

    # WHY `id` IS THE GLOBAL PRIMARY KEY RATHER THAN (collection, id)
    # Because a document id means one thing across the whole system: the
    # ingestion path mints it, and re-ingesting the same document into a
    # different collection must update the same row rather than create a second
    # one. A composite key would make "which document is this" ambiguous across
    # collections and would push id-uniqueness into application logic.
    #
    # WHAT THAT CHOICE FORBIDS, stated plainly so it is a decision rather than a
    # surprise later: the SAME id cannot exist in two collections. Moving a
    # document between collections is an UPDATE of its `collection` column, not
    # an INSERT. If per-collection id reuse is ever genuinely required, this
    # primary key is the thing that has to change, and changing it is a
    # migration affecting every query — not a config change.
    #
    # It also means the `documents_collection_idx` above is the only secondary
    # index, and that lookups by id (the common ingest/update path) hit the
    # primary key directly without touching it.

    # ── 5. updated_at — MAINTAINED BY A TRIGGER, NOT BY THE APPLICATION ───────
    # The decision: a BEFORE UPDATE trigger owns this column. The application
    # never sets it and never sends it.
    #
    # Application-managed was the alternative, and it is the default choice
    # because it is simpler and more explicit. It loses here for one reason: it
    # is correct only if EVERY writer remembers. Every UPDATE would need
    # `updated_at = now()` added to its SET list, and the failure mode is not an
    # error — it is a plausible, silently wrong timestamp. A future code path
    # that forgets produces rows whose updated_at is stale, which is worse than
    # having no updated_at at all, because something will eventually trust it.
    # The ON CONFLICT DO UPDATE path of an upsert is exactly such a place to
    # forget, and upsert is the natural write for ingestion.
    #
    # The trigger makes the invariant structural: the column cannot be wrong,
    # because nothing but the trigger can write it. That is consistent with the
    # rest of this migration, where the CHECK constraints and `vector(384)` are
    # likewise database-enforced — leaving updated_at as the one mutable
    # invariant enforced only in Python would be the odd one out.
    #
    # The cost is one trigger invocation per updated row, which is free at this
    # write volume (documents are written rarely, not per-request), plus one
    # function that has to be dropped on downgrade. Taken.
    #
    # The one consequence to know: because the trigger is unconditional, a test
    # cannot ask for a specific updated_at value. That is the correct behaviour
    # for a column meant to record when the row actually changed, and it should
    # be tested by asserting the timestamp MOVED, not by pinning it.

    # BEFORE, not AFTER: an AFTER trigger would let the UPDATE land first and
    # could only rewrite NEW values via a second UPDATE, doubling the write and
    # leaving a window where updated_at is stale. FOR EACH ROW because
    # multi-row statements are normal (bulk re-embed) and the trigger must fire
    # once per row, not once per statement.
    op.execute(
        """
        CREATE FUNCTION documents_set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE TRIGGER documents_set_updated_at
        BEFORE UPDATE ON documents
        FOR EACH ROW
        EXECUTE FUNCTION documents_set_updated_at()
        """
    )


def downgrade() -> None:
    # Reverse order of the operations that created state.
    #
    # Trigger first, then its function: dropping the table first would remove the
    # trigger along with it, leaving the function orphaned — and `CREATE OR
    # REPLACE`/DROP ordering on a function a live trigger depends on is the kind
    # of thing that fails on the next deploy rather than this one.
    op.execute("DROP TRIGGER IF EXISTS documents_set_updated_at ON documents;")
    op.execute("DROP FUNCTION IF EXISTS documents_set_updated_at();")

    # DROP TABLE, not DROP TABLE CASCADE. The constraints and the collection
    # index live on this table and are dropped with it automatically; if some
    # future object had come to depend on it, CASCADE would silently take that
    # object too. Failing loudly is the better default for a downgrade.
    op.execute("DROP TABLE IF EXISTS documents;")

    # WHY THE EXTENSION IS NOT DROPPED
    # Deliberately. `DROP EXTENSION vector` would remove the `<=>` operator, the
    # vector type and anything else built on the extension — for the whole
    # DATABASE, not just this table, including objects this migration has never
    # heard of. An extension is a shared, expensive-to-rebuild facility; the
    # reversible part of this migration is the table, and the extension is the
    # database's, not ours. If a database genuinely needs to shed it, that is a
    # deliberate manual operation, not a side effect of rolling back one table.