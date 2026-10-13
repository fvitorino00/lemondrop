# Milestone 3 — Verification Record (IN PROGRESS)

**This is a running record, not a finished report.** Milestone 3 is in progress. Phase 0,
Phase 1, Phase 2 and Phase 3a+3b (persistence and ingestion) have been touched. Semantic
search, reranking, and persistence across a container restart — the remaining M3 acceptance
criteria — remain untested. Sections below are added as each phase is verified; this
document will change until the milestone is closed, and anything not yet in it has not
happened.

The distinction that matters throughout: **VERIFIED** means a check was run and its result
is recorded below. **NOT YET VERIFIED** means the claim is untested or the risk is
understood but unmeasured. Nothing here is claimed without a named check and a result.

**Provenance is the point of this document.** Every row below states *who ran the check*:

- **Executed by: operator** — the operator ran the command and pasted the terminal output.
  The agent did not run it and cannot re-run it. These are transcribed from the operator's
  report, not reproduced from an independent session.
- **Executed by: CEO** — run by the agent using read-only commands, with the real command
  and its real output pasted below. Anyone can re-run these and get the same thing.

Where a row's raw terminal output is not pasted inline, it is because the operator
reported the result rather than supplying a transcript; the row says so. That
distinction is not decoration. An operator-executed check recorded here as if the agent
had run it would be a fabricated claim wearing a real one's clothes.

---

## 1. Phase 0 — Corpus

**Status: VERIFIED.**

**The corpus is synthetic, and this is the most important fact in this section.**
`data/corpus.json` was *generated for Milestone 3 by this project*. It was not supplied
by the operator, not sourced from a third party, and is not real-world documentation. A
full search of the repository found no `data/`, `datasets/`, `runbooks/` or `corpus/`
directory and no corpus file of any kind; the operator was told this and decided we
generate one instead. The file carries `"synthetic": true` and a `generation_note` saying
so, and `data/README.md` records the decision and how to replace it. Nothing downstream
depends on its contents — only its shape — so a real dataset can replace it without
touching code outside `data/`.

| # | Item | Command / check | Observed result | Executed by | Verdict |
|---|---|---|---|---|---|
| 1 | 20 documents in `infrastructure` | `grep -c '"collection": "infrastructure"' data/corpus.json` | `20` | **CEO** (command + output below) | **VERIFIED** |
| 2 | 20 documents in `it-support` | `grep -c '"collection": "it-support"' data/corpus.json` | `20` | **CEO** (command + output below) | **VERIFIED** |
| 3 | 10 documents flagged `isolation_canary` | `grep -c '"isolation_canary": true' data/corpus.json` | `10` | **CEO** (command + output below) | **VERIFIED** |
| 4 | Corpus is 40 documents total | Document count | 40 — consistent with rows 1 + 2 | **CEO** | **VERIFIED** |
| 5 | Corpus contains no real credentials, AWS account ids, hostnames or personal data | `grep -noE '\b[0-9]{12}\b'`; `grep -noE '[a-z0-9.-]+\.(rds\|elb)\.amazonaws\.com'`; `grep -noE 'arn:aws:[a-z0-9-]+\|ASIA[0-9A-Z]+\|@[a-z0-9.-]+\.(com\|net\|org\|io)'` | No matches. Placeholders only (`<INSTANCE_ID>`, `<VPC_ID>`, `<TG_ARN>`). | **CEO** | **VERIFIED** |
| 6 | The canaries form 5 cross-collection near-duplicate pairs | Ids of the ten canary documents | 5 `infra-*` / 5 `support-*` — `iam-key-rotation`/`service-account-password-rotation`, `rds-snapshot-restore`/`workstation-backup-and-restore`, `security-group-ingress`/`admin-console-access-grant`, `drain-unhealthy-target`/`departing-employee-access-removal`, `rds-master-password-rotation`/`mfa-reset-locked-out-user` | **CEO** | **VERIFIED** |

### Real output — Phase 0 counts (CEO)

Run from the repository root:

```console
$ grep -c '"collection": "infrastructure"' data/corpus.json
20
$ grep -c '"collection": "it-support"' data/corpus.json
20
$ grep -c '"isolation_canary": true' data/corpus.json
10
```

### Why the canaries matter

Ten of the forty documents are deliberate isolation canaries: five near-duplicate pairs
straddling the two collections, semantically adjacent and lexically overlapping. A search
scoped to one collection can therefore be tested against a document that *would* rank
first if the collection filter leaked. They are the hardest isolation probe available
here and they are load-bearing for that acceptance criterion. Note that this is a
statement about the *corpus*, not about retrieval: whether any system in this repo
actually honours the filter is not tested yet.

---

## 2. Phase 1 — Schema and migrations

**Status: VERIFIED by the operator.**

Everything in this section was executed and reported by the **operator**, who ran the
commands and pasted terminal output. The agent did not run these and is not claiming to.
The rows transcribe the operator's report; where the raw transcript is not reproduced
here it is because it was summarised rather than pasted verbatim, and the row is marked
as such.

| # | Item | Command / check | Result as reported | Executed by | Verdict |
|---|---|---|---|---|---|
| 1 | Migration applied | `alembic upgrade head` | Revision `0001` applied successfully. | **operator** (terminal output pasted) | **VERIFIED** |
| 2 | Table shape | `\d documents` | Columns: `id`, `collection`, `content`, `metadata` (JSONB), `embedding` (`vector(384)`), `created_at`, `updated_at`. | **operator** (terminal output pasted) | **VERIFIED** |
| 3 | Index present | `\d documents` | `documents_collection_idx` present. | **operator** (terminal output pasted) | **VERIFIED** |
| 4 | BOTH CHECK constraints present | `\d documents` | `documents_collection_not_blank` **and** `documents_metadata_is_object`. | **operator** (terminal output pasted) | **VERIFIED** |
| 5 | Trigger present | `\d documents` | `documents_set_updated_at`. | **operator** (terminal output pasted) | **VERIFIED** |
| 6 | pgvector version | `SELECT extversion FROM pg_extension WHERE extname = 'vector';` | `0.8.7` — the version in the **local container**. | **operator** (terminal output pasted) | **VERIFIED (local only)** |
| 7 | Remote-host guard rejects a non-local host | Migration run pointed at `db.example.invalid` | **REJECTED before opening any connection.** No connection attempted. | **operator** (terminal output pasted) | **VERIFIED** |
| 8 | Actual migration target was local, not RDS | Resolved `ALEMBIC_DATABASE_URL` target | `127.0.0.1:5432/lemondrop` — the local container. **Not** AWS RDS. | **operator** (terminal output pasted) | **VERIFIED** |

Row 8 matters for reading this document correctly: Phase 1 was proved against a local
dev database. Nothing in this section is evidence about the RDS instance.

---

## 3. Open limitations and known risks

Stated plainly, because each of these is a real caveat on everything above:

- **pgvector 0.8.7 is the LOCAL container's version.** The RDS instance ships whatever
  version AWS provides, and vector index capabilities differ between pgvector versions.
  No ANN index is in use — search is exact — so this is currently low risk. It is a real
  portability caveat regardless, and it **must be re-checked against RDS before any index
  work begins.**
- **The AWS-side credential path is not implemented or tested.** The intended chain —
  SSM parameter `/lemondrop/dev/db/{host,port,secret-arn}` → Secrets Manager → DSN —
  does not exist yet. The IAM changes live on the `feat/aws-infrastructure` branch and are
  **NOT applied**. Deployed permissions must be verified directly against the live
  instance before any AWS integration work. Do not assume they exist.
- **Every M3 acceptance criterion is UNTESTED.** Ingestion, semantic search, reranking,
  persistence across a container restart, collection isolation — all still to come.
  **Phase 1 proved a schema exists and is correct. It proves nothing whatsoever about
  retrieval behaviour.** A perfect table and a broken retrieval layer look identical at
  this point in the milestone.
- **The corpus is synthetic.** No conclusion drawn from this corpus is a conclusion about
  real-world documentation quality. See §1.

---

## 4. Phase 2 — Database layer, lifecycle and configuration

**Status: VERIFIED — 19/19 tests passing.**

Everything in this section was executed and reported by the **operator**, who ran the
commands and pasted terminal output. The agent did not run these and is not claiming to.

### 4.1 Test suite

| Suite | Result |
|---|---|
| `api/tests/test_db.py` | **13 passed** |
| `api/tests/test_integration.py` | **6 passed** (no regression) |

### 4.2 The thirteen `test_db.py` cases, and what each protects

| # | Test | What it protects |
|---|---|---|
| 1 | `test_ping_reports_ok_against_the_configured_local_database` | The lifecycle genuinely connects. `SELECT 1` against the local devdb returns `ok=True`, so the pool, the driver and the credentials work together rather than merely constructing. |
| 2 | `test_a_wrong_password_never_reaches_an_exception_a_log_or_a_repr` | **Security property.** A wrong password reaches no exception message, no captured log record and no `repr`. Guards the end-to-end outcome across all three sinks. |
| 3 | `test_the_redactor_removes_a_dsn_that_a_driver_quotes` | **Security property.** The redactor removes a quoted DSN, a quoted bare password and a quoted percent-encoded password. It exists because test 2 alone was insufficient — see limitation 1. |
| 4 | `test_repr_of_settings_does_not_contain_the_password` | **Security property.** `repr(settings)` renders the DSN masked, asserted in both directions: the password is absent, and the mask is genuinely present. |
| 5 | `test_missing_database_url_raises_an_error_naming_the_key` | A missing `DATABASE_URL` is reported as a message that names the key, not as a silent default DSN. Also asserts the message carries no credential and no placeholder value. |
| 6 | `test_a_dsn_with_an_empty_password_is_rejected_and_leaks_nothing` | **Security property, DSN validation.** `postgresql+asyncpg://:password@host/db` is rejected at construction, and the error names `DATABASE_URL` while leaking nothing — including the non-secret parts, since a message that quotes the host today is one edit from quoting the password. |
| 7 | `test_a_dsn_with_an_empty_username_is_rejected` | **Security property, DSN validation.** The empty-username case, asserted separately because `if not url.password:` reads complete on its own and would leave the twin case unhandled. The error does not echo the distinctive marker in the DSN. |
| 8 | `test_a_malformed_dsn_is_rejected_without_leaking_the_parser_s_error` | **Security property, DSN validation.** A malformed DSN is rejected and SQLAlchemy's own parser error — which can quote the offending string — is suppressed rather than surfaced. |
| 9 | `test_a_fully_populated_dsn_still_constructs` | The happy path. The two validators must not reject a valid DSN, which is the failure mode a paranoid check introduces. |
| 10 | `test_embedding_dim_is_384_and_matches_the_column_definition` | The application's embedding width and the migrated column's `vector(384)` are asserted against each other, so a model swap fails at the boundary rather than silently destroying the distance metric. |
| 11 | `test_health_live_returns_200` | `/health/live` answers 200. It must probe nothing: a liveness check that depended on the database would restart a healthy container during a transient blip. |
| 12 | `test_health_ready_returns_200_when_the_database_and_both_workers_are_up` | `/health/ready` answers 200 with all three dependencies healthy, and reports each of `database`, `embedder` and `reranker`. |
| 13 | `test_health_is_unchanged_by_the_database_phase` | The pre-existing `/health` route is behaviourally untouched. It is referenced by the compose healthcheck, by `boot.sh`'s boot verification loop and by the live AWS ALB target group. |

Tests 2, 3, 4, 6, 7 and 8 are the security properties of this phase. Tests 6, 7 and 8
each assert both that the defective DSN is rejected and that the resulting error leaks
nothing.

### 4.3 Runtime verification

| # | Item | Result as reported | Executed by | Verdict |
|---|---|---|---|---|
| 1 | `GET /health/live` | **HTTP 200** | **operator** (terminal output pasted) | **VERIFIED** |
| 2 | `GET /health/ready` | **HTTP 200**, with `database`, `embedder` and `reranker` all reporting `ok` | **operator** (terminal output pasted) | **VERIFIED** |
| 3 | Container's database host | Resolves as **`postgres`** — not `127.0.0.1`. **Checked explicitly.** | **operator** (terminal output pasted) | **VERIFIED** |

Row 3 is load-bearing and was checked explicitly rather than inferred from the 200s. The
container must reach the database over the compose network **by service name**, because
`127.0.0.1` inside a container is *that container's own loopback* — nothing listens on
5432 there. A DSN copied verbatim from the host `.env` produces `connection refused`
from inside `api` while `psql` on the workstation connects perfectly, which reads as a
broken database and is actually a broken address. A passing readiness probe is
consistent with both the right and the wrong host, so it does not prove this on its own.

### 4.4 Known limitations

Stated plainly, without softening. Four of these are properties of the *evidence*, not
of the code.

**1. The credential-redaction test was initially inadequate, and measurement caught
it.** Neither asyncpg nor SQLAlchemy 2.0.54 actually quotes the credential in their
error messages on this host — asyncpg reports `password authentication failed for user
"lemondrop"` and SQLAlchemy reports `Could not parse SQLAlchemy URL from given URL
string`. The end-to-end leak test (`test_a_wrong_password_never_reaches_an_exception_a_
log_or_a_repr`) would therefore still have **passed with the redactor deleted and
replaced by `str()`**. It guards the **OUTCOME, not the MECHANISM**. Test 3 closes that
gap by constructing the message the drivers do not currently produce. This is a property
of the evidence — the redactor's behaviour is only tested against synthetic input —
and is **not** a strength of the code.

**2. Python version skew.** The local venv is **Python 3.14.4**; `api/Dockerfile` is
**`python:3.12-slim`**. `python3.12` is **not available on this host**. Every
`test_db.py` case imports application modules and therefore runs on 3.14.4, while
production runs on 3.12. A 3.12-only incompatibility would **not** be caught locally.
Not fixed; recorded.

**3. Least privilege is asserted, not demonstrated.** The local devdb role is a
**SUPERUSER**, so the split between the application credential (`DATABASE_URL`) and the
migration credential (`ALEMBIC_DATABASE_URL`) is enforced by variable naming and
documented intent only. Nothing local proves the application role lacks DDL rights.

**4. No AWS anything.** No SSM, no Secrets Manager, no boto3, no IAM. The
`DatabaseUrlResolver` seam is documented and deliberately unimplemented. The
`feat/aws-infrastructure` IAM changes are **NOT applied**, so deployed permissions
remain unverified and **must be checked directly against the live instance before any
cloud integration**.

**5. SQLAlchemy 2.0.54's asyncpg dialect has no `vector` colspec.** Measured:
`'vector' in d.colspecs → False`. This blocks the Phase 3 store layer until
pgvector-python is integrated — the approved decision for Phase 3.

---

## 5. Phase 3a + 3b — pgvector integration, document store and `POST /documents`

**Status: VERIFIED by the operator — 35/35 tests passing, 40/40 documents ingested.**

Everything in §5.1 to §5.4 marked **operator** was executed and reported by the
**operator**, who ran the commands against the local dev database and the running API
container and pasted terminal output. The agent did not run those and is not claiming to.
The rows marked **CEO** were run by the agent using read-only commands with the real
command and its real output pasted below; anyone can re-run them and get the same thing.

### 5.1 Test suite

| Suite | Result |
|---|---|
| `api/tests/test_db.py` | **13 passed** (no regression) |
| `api/tests/test_integration.py` | **6 passed** (no regression) |
| `api/tests/test_documents.py` | **16 passed** (new this phase) |
| **Total** | **35 passed** |

The agent did not execute the suite — that requires the devdb and the rebuilt API
container, and this review ran without Docker. The **count** of 35 is independently
checkable without either, because pytest collection does not open a connection:

```console
$ .venv/bin/python -m pytest --collect-only -q
35 tests collected in 0.40s
```

Note what the total is made of: the *new* file contributes 16 of the 35. The other 19 are
the Phase 2 and Milestone 2 suites, so the 35 is not 35 new assertions — it is 16 new and
19 pre-existing, all green. A regression in the earlier phases would have shown up here.

### 5.2 Runtime verification

| # | Item | Command / check | Observed result | Executed by | Verdict |
|---|---|---|---|---|---|
| 1 | Corpus loader ingested the whole corpus | `.venv/bin/python scripts/load_corpus.py` | **40/40 stored, 0 failed.** Per-collection summary: `infrastructure` 20 sent / 0 failed, `it-support` 20 sent / 0 failed. | **operator** (terminal output pasted) | **VERIFIED** |
| 2 | PostgreSQL independently confirms the row counts | `SELECT collection, count(*) FROM documents GROUP BY collection;` | **`infrastructure` = 20, `it-support` = 20.** | **operator** (terminal output pasted) | **VERIFIED** |
| 3 | The loader exits non-zero on any per-document failure | `main()` returns 1 and `sys.exit(main())` when `failures` is non-empty | Confirmed by reading `scripts/load_corpus.py` — a partial run cannot print a success summary. | **CEO** (code read) | **VERIFIED** |
| 4 | Collection-filtered retrieval returns only the asked-for collection | `store.retrieve(collection=...)` against the loaded corpus | Passed; returned rows carry only the requested `collection`, and the **count** was asserted, not merely the absence of a foreign id. | **operator** (terminal output pasted) | **VERIFIED** |
| 5 | Documents are stored at 384 dimensions | `vector_dims(embedding)` read back from PostgreSQL | **384**, confirmed by the API tests against the loaded database. | **operator** (terminal output pasted) | **VERIFIED** |
| 6 | The store is exercised against a REAL database — no mocks | Read of `api/tests/test_documents.py` | **No mock, no in-process test client, no fake pool.** Real HTTP to the running API, real PostgreSQL, real `pgvector` extension. | **CEO** (code read) | **VERIFIED** |
| 7 | The corpus used is real ingested data, not fixtures | `load_corpus.py` run + row counts above | **40 rows written by the loader through `POST /documents`.** Test fixtures use separate `testdocs-*` collections, which are cleared in setup and teardown and never touch `infrastructure` / `it-support`. | **operator** (terminal output pasted) | **VERIFIED** |
| 8 | Corpus file still holds 20 + 20 | `grep -c '"collection": "infrastructure"' data/corpus.json` | `20` | **CEO** (command + output below) | **VERIFIED** |
| 9 | | `grep -c '"collection": "it-support"' data/corpus.json` | `20` | **CEO** (command + output below) | **VERIFIED** |

```console
$ grep -c '"collection": "infrastructure"' data/corpus.json
20
$ grep -c '"collection": "it-support"' data/corpus.json
20
```

**Row 7 is the row that matters most, and it is easy to state badly.** "The store is tested"
means nothing on its own — a store tested against a fixture database proves the code
compiles. What was proven is that **40 real documents were embedded by the real embedder
and written through the real route into the real PostgreSQL, and that reading them back
found 20 and 20.** That is an end-to-end path, not a unit test.

### 5.3 The pgvector codec discovery — the most valuable thing this phase produced

This is recorded at length because it is the one finding whose failure mode is **invisible
to the kind of test people actually write**, and because the wrong version of it looks
completely like the right one.

asyncpg type codecs are registered **per connection** — not per engine, not per pool, not
per process. `register_vector(conn)` issues a `set_type_codec('vector', ...)` on one wire
protocol connection, and that codec exists on that connection and on no other.

The pool created by `create_async_engine` is **empty at startup and grows lazily**. At the
moment a vector query runs it may hold one connection, two, or three — and only the ones
that happened to have the registration applied can carry a vector. Registering on "the
connection I happened to acquire" registers it on one. A vector write that lands on any
other fails with:

```
asyncpg.exceptions.DataError: invalid input for query argument $N: Vector([...]) (expected str, got Vector)
```

— **intermittently, and only under real concurrency**, because which pooled connection
serves a request is a scheduling detail. A single-query test cannot see this: one INSERT
sees one connection and passes.

**And it is worse than that, in a way that was measured rather than assumed.**
`db.startup()` **pings the database before returning.** That ping checks a connection out
of the pool, runs `SELECT 1`, and checks it back in. So by the time the lifespan can attach
a listener, the pool **already holds one live connection that was created before any
registration existed**, and it is permanently unregistered. Attaching the listener covers
every connection created *afterwards* and leaves that first one broken forever.

| Configuration | Vector writes accepted across 3 pooled backends |
|---|---|
| listener **+** `await engine.dispose()` | **3 / 3** |
| listener **without** dispose | **1 of 3 FAILS** — the recycled ping connection; the 2 fresh ones pass |
| no registration at all | **0 / 3** |

**The middle case is the dangerous one, and it is the reason this is written down.** It is
a **1-in-3 intermittent failure that only appears under concurrency.** It passes every
single-connection test, it passes in a smoke test, and it fails in production roughly a
third of the time. The obvious "fix" — reasoning that the listener alone is sufficient
because it is attached to the pool — reintroduces precisely this bug while looking correct.

`await engine.dispose()` is therefore **load-bearing**, and a regression test asserts the
exact numbers `2 succeeded, 1 failed` so it cannot be quietly removed:

`api/tests/test_documents.py::test_attaching_the_listener_without_disposing_leaves_the_ping_connection_broken`

The middle row is the assertion. Deleting the `await engine.dispose()` from
`store.prepare_database` makes that test fail. That is the whole point of it.

Two further facts about the registration, both load-bearing and both verified rather than
trusted:

- The listener is attached to **`engine.sync_engine`**, not the async engine. SQLAlchemy
  rejects pool events on an `AsyncEngine` outright —
  `NotImplementedError: asynchronous events are not implemented at this time` — so the
  claim is not a style preference, it is the only thing that works.
- The raw driver connection is reached as **`dbapi_connection._connection`**, which is
  exactly what SQLAlchemy's own asyncpg dialect does in
  `setup_asyncpg_jsonb_codec` (`sqlalchemy/dialects/postgresql/asyncpg.py`:
  `asyncpg_connection = conn._connection` followed by `set_type_codec`).

### 5.4 Dependency facts

| # | Item | Result | Executed by | Verdict |
|---|---|---|---|---|
| 1 | `pgvector==0.5.1` is **pure Python** (`py3-none-any`) | `Root-Is-Purelib: true`, `Tag: py3-none-any` in the installed `WHEEL` | **CEO** (command + output below) | **VERIFIED** |
| 2 | The Dockerfile's no-compiler constraint is therefore satisfied | One wheel serves the image's CPython 3.12 and the host venv's CPython 3.14 alike; `pip install` never invokes a compiler. | **CEO** (reading + output below) | **VERIFIED** |
| 3 | SQLAlchemy 2.0.54's asyncpg dialect still has no `vector` colspec | `'vector' in d.colspecs → False`. Confirms `store.py`'s raw-SQL decision still holds. | **CEO** (command + output below) | **VERIFIED** |

```console
$ cat .venv/lib/python3.14/site-packages/pgvector-0.5.1.dist-info/WHEEL
Wheel-Version: 1.0
Generator: setuptools (84.0.0)
Root-Is-Purelib: true
Tag: py3-none-any

$ .venv/bin/python -c "from sqlalchemy.dialects.postgresql import asyncpg as d; \
    print('vector in colspecs:', 'vector' in d.dialect.colspecs)"
vector in colspecs: False

$ .venv/bin/python -c "import sqlalchemy, asyncpg, sys; \
    print(sqlalchemy.__version__, asyncpg.__version__, sys.version)"
2.0.54 0.32.0 3.14.4 (main, Aug 20 2026, 10:41:58) [GCC 15.2.0]
```

**Row 1 corrects an assumption made earlier in this milestone.** `pgvector` was initially
expected to require a **compiled wheel**, on the assumption that a database-extension
client library would ship a native extension. It does not: it is pure Python, so the
Dockerfile installs it with no toolchain and no per-interpreter builds. Worth recording
because the assumption was reasonable, was acted on conservatively, and was wrong — and a
verification record that only records confirmations is not a verification record.

### 5.5 Known limitations of this phase

Stated plainly, not softened.

1. **Least privilege is asserted, not demonstrated.** The local devdb role is a
   **SUPERUSER**, so the `DATABASE_URL` / `ALEMBIC_DATABASE_URL` split is enforced by
   variable naming and documented intent only. Nothing local proves the application role
   lacks DDL rights. This is inherited from Phase 2 (§4.4 item 3) and is **unchanged**.
2. **Python version skew.** The local venv is **Python 3.14.4**; `api/Dockerfile` is
   **`python:3.12-slim`**, and `python3.12` is **not available on this host**. Every
   `test_documents.py` case that imports application modules runs on 3.14.4 while
   production runs on 3.12. A 3.12-only incompatibility would **not** be caught locally.
   Inherited from §4.4 item 2.
3. **No AWS anything.** No SSM, no Secrets Manager, no boto3, no IAM, no RDS. Everything
   in this section ran against the **local dev database**. The `DatabaseUrlResolver` seam
   is still documented and deliberately unimplemented. The `feat/aws-infrastructure` IAM
   changes are **NOT applied**, so deployed permissions remain unverified.
4. **pgvector 0.8.7 is still the LOCAL container's version**, and §3's re-check-before-index
   caveat still stands. No ANN index is in use; search is exact.
5. **The store is verified; retrieval is not.** `store.retrieve` is exercised, and its
   collection scoping is proven. **No user-facing search exists** — there is no `/search`
   route, so none of this has been observed through an API response a caller could receive.
   See §6.

---

## 6. M3 acceptance criteria — status

| # | Criterion | Status |
|---|---|---|
| 1 | Ingestion of the corpus | **PARTIAL** — see below |
| 2 | Semantic search returns relevant results | **UNTESTED** |
| 3 | Reranking applied | **UNTESTED** |
| 4 | Persistence across container restart | **UNTESTED** |
| 5 | Collection isolation (canary pairs never cross) | **UNTESTED** — store level only; see below |

Two supporting infrastructure criteria were verified in Phase 2 and are recorded here so
the milestone's shape stays visible:

| # | Criterion | Status | Where |
|---|---|---|---|
| 6 | `GET /health/live` returns 200 | **VERIFIED** | §4.3 row 1 |
| 7 | `GET /health/ready` returns 200 with `database`, `embedder`, `reranker` all `ok` | **VERIFIED** | §4.3 row 2 |

### 6.1 Why row 1 is PARTIAL and not VERIFIED

Ingestion is the first criterion with **some** evidence behind it, so it is worth being
precise about what that evidence does and does not reach.

**What IS proven** (all of it operator-executed, all of it against the real local
database — §5.2):

- **Real ingestion.** 40 of 40 documents went through `POST /documents` and were written
  to PostgreSQL, and the row counts were independently confirmed at `psql` as
  **`infrastructure` = 20 and `it-support` = 20**. Not fixtures, not a mocked store.
- **Correct 384-dimension storage.** `vector_dims(embedding)` read back from the database
  reports **384**, and a 768-dimension vector is actively **rejected** by the column —
  asserted on the rejection *message*, so the test cannot pass for the wrong reason.
- **Metadata round-trip.** JSONB metadata survives the write and reads back as an object,
  and a non-object is refused both at the API edge (422 naming the field) and by the
  database's own CHECK constraint.
- **Upsert.** Re-posting a `document_id` updates the one row in place — content, metadata,
  embedding and collection — with `updated_at` moving and `created_at` **not** moving.
- **Collection-filtered retrieval.** `store.retrieve` scopes to the requested collection,
  and the test asserts the **returned count**, not merely the absence of a foreign id.

**What is NOT proven:**

- **Reranking is untouched.** `POST /rerank` exists from Milestone 2 and this phase does
  not call it. Nothing here is evidence about it.
- **`/search` does not exist.** There is no route a user can call to retrieve anything.
  Everything above was observed through the store or through `POST /documents`, never
  through a search response.
- **Cross-collection isolation has been shown at store level only.** The `WHERE` clause
  is proven to hold, and the funnel is proven to be applied to the right population. But
  the criterion as written — *"canary pairs never cross"* — is a claim about what a caller
  **sees in a search response**, and there is no such response to check. Proving it at the
  store is real progress and is **not** the same claim.
- **Persistence across a container restart is still untested** (row 4), and is untested in
  a way that matters more now than it did in Phase 2: the pool is now the thing being
  armed by `store.prepare_database`, and that arming has only ever been observed against a
  freshly started process.

**Why row 5 is left UNTESTED rather than moved to PARTIAL.** The temptation is to promote
it, because collection scoping *is* demonstrated. The criterion is specifically about the
ten `isolation_canary` near-duplicate pairs never crossing in a result set, and that is a
statement about a response. Until `/search` exists there is no response, so the criterion
has no subject. **PARTIAL** would read as "checked, found mostly fine", which is a
different and stronger claim than "not yet checkable".

**No user-facing retrieval criterion has been checked.** Rows 2, 3 and 5 remain UNTESTED
because there is no search route to test them against. Rows 6 and 7 are infrastructure the
retrieval layer depends on, not evidence about it: a container that reports itself ready
and a table that answers a `<=>` query are different claims, and only the first has been
made. This table exists so the gap is visible, not to imply progress.

---

## 7. Re-check this record

The Phase 0 claims can be re-verified by anyone:

```bash
grep -c '"collection": "infrastructure"' data/corpus.json   # Expected: 20
grep -c '"collection": "it-support"' data/corpus.json       # Expected: 20
grep -c '"isolation_canary": true' data/corpus.json         # Expected: 10
```

The Phase 1 claims (§2) **cannot** be re-checked from this document alone — they were
executed by the operator against a local database. Re-running them requires the dev
database up (`docker compose --profile devdb up -d postgres`) and
`cd api && alembic upgrade head`.

The Phase 3a+3b claims that **can** be re-checked without Docker:

```bash
.venv/bin/python -m pytest --collect-only -q                      # Expected: 35 tests collected
cat .venv/lib/python3.14/site-packages/pgvector-0.5.1.dist-info/WHEEL   # Expected: Tag: py3-none-any
```

The claims that cannot — 35/35 passing, 40/40 ingested, the `psql` row counts, and the
three-way codec measurement — require the dev database and the rebuilt API container, and
were executed by the operator. Their provenance is stated per row in §5 and is **not** an
independent reproduction.

When the next phases land, add them as new numbered sections below rather than editing
rows 1–8 above. A verification record that gets rewritten is not a record.