# Milestone 3 — Verification Record (IN PROGRESS)

**This is a running record, not a finished report.** Milestone 3 is in progress. Phase 0,
Phase 1, Phase 2, Phase 3a+3b (persistence and ingestion) and Phase 4 (retrieval,
`POST /search`) have been touched. Persistence across a container restart — the remaining
M3 acceptance criterion — remains untested. Sections below are added as each phase is
verified; this document will change until the milestone is closed, and anything not yet in
it has not happened.

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

  > **SUPERSEDED BY PHASE 4 (§8), recorded here rather than rewritten.** The above was
  > true when Phase 1 was verified and is kept as written. As of §8, ingestion, semantic
  > search, reranking and collection isolation are **VERIFIED** against the live stack.
  > **Persistence across a container restart remains UNTESTED** — the one M3 criterion
  > still open, and explicitly not promoted. See §6.2.
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

   > **SUPERSEDED BY PHASE 4 (§8).** `POST /search` now exists and is verified end to end:
   > 62/62 tests, and a live search that ranked the right document first. See §8.2 and §8.4.

---

## 6. M3 acceptance criteria — status

| # | Criterion | Status |
|---|---|---|
| 1 | Ingestion of the corpus | **VERIFIED** — §6.1 |
| 2 | Semantic search returns relevant results | **VERIFIED** — §8.2 |
| 3 | Reranking applied | **VERIFIED** — §8.2 |
| 4 | Persistence across container restart | **UNTESTED** — see §6.2 |
| 5 | Collection isolation (canary pairs never cross) | **VERIFIED** — §8.4, §8.5 |

Two supporting infrastructure criteria were verified in Phase 2 and are recorded here so
the milestone's shape stays visible:

| # | Criterion | Status | Where |
|---|---|---|---|
| 6 | `GET /health/live` returns 200 | **VERIFIED** | §4.3 row 1 |
| 7 | `GET /health/ready` returns 200 with `database`, `embedder`, `reranker` all `ok` | **VERIFIED** | §4.3 row 2 |

### 6.1 Why row 1 moved from PARTIAL to VERIFIED

*(Updated by Phase 4. This subsection's original reasoning is retained below because the
change in verdict is itself the evidence: each bullet marked **NOW PROVEN** was on this
list as a gap one phase ago.)*

Ingestion was the first criterion with **some** evidence behind it, so it was worth being
precise about what that evidence did and did not reach.

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
- **NOW PROVEN (Phase 4, §8):** all 40 documents are reachable **through a search response a
  caller receives**, with the reranker applied and the collection predicate holding.

**What is NOT proven:**

- ~~**Reranking is untouched.** `POST /rerank` exists from Milestone 2 and this phase does
  not call it. Nothing here is evidence about it.~~ **NOW PROVEN — §8.2:** a live `/search`
  ranked `support-recycle-bin-file-recovery` first, 10 candidates in, 5 results out.
- ~~**`/search` does not exist.** There is no route a user can call to retrieve anything.
  Everything above was observed through the store or through `POST /documents`, never
  through a search response.~~ **NOW PROVEN — §8.2.** The route exists and is exercised over
  HTTP against the running container.
- ~~**Cross-collection isolation has been shown at store level only.** … the criterion as
  written is a claim about what a caller **sees in a search response**, and there is no such
  response to check.~~ **NOW PROVEN — §8.4, §8.5:** measured on the live corpus, the canary
  twin ranks **#2 overall** in an unscoped search and never appears in the scoped one, and
  the isolation test was mutation-proved to discriminate rather than merely to pass.
- **Persistence across a container restart is still untested** (row 4). It is untested in
  a way that matters more now than it did in Phase 2: the pool is now the thing being
  armed by `store.prepare_database`, and that arming has only ever been observed against a
  freshly started process. See §6.2.

### 6.2 Row 4 is NOT promoted, and here is why that is the honest call

**Persistence across a container restart remains UNTESTED.** Phase 4 did not test it and
Phase 4's evidence does not reach it.

The temptation is to read the rest of the table being green as momentum, and to promote
row 4 by association. That would be wrong for a specific reason rather than a general one:
`store.prepare_database`'s `engine.dispose()` is exactly the mechanism a restart exercises
and nothing else does. It exists because `db.startup()`'s `SELECT 1` ping leaves one pooled
connection permanently lacking the pgvector codec, and the dispose is what retires it
(§5.3). Every observation of that mechanism to date came from a **freshly started process** —
which is the easy direction. A restart has to prove the documents are still there, the
migrations have not been re-applied destructively, and the codec is armed again on a pool
whose *first* connection was created before startup finished. That is the untested direction.

Row 4 stays **UNTESTED**. It is the next task.

**No user-facing retrieval criterion is left unchecked.** Rows 2, 3 and 5 are verified in
§8 against the live stack. Rows 6 and 7 remain infrastructure the retrieval layer depends
on rather than evidence about it. Row 1's remaining caveat is row 4, above.

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
.venv/bin/python -m pytest --collect-only -q                      # Expected: 62 tests collected
cat .venv/lib/python3.14/site-packages/pgvector-0.5.1.dist-info/WHEEL   # Expected: Tag: py3-none-any
```

The claims that cannot — 62/62 passing, 40/40 ingested, the `psql` row counts, the
three-way codec measurement, and the live `/search` ranking in §8 — require the dev
database and the rebuilt API container, and were executed by the operator. Their provenance
is stated per row in §5 and §8 and is **not** an independent reproduction.

When the next phases land, add them as new numbered sections below rather than editing
rows 1–8 above. A verification record that gets rewritten is not a record.

---

## 8. Phase 4 — `POST /search`

**Status: VERIFIED — 62/62 tests passing, and a live search ranked correctly.**

Everything in this section was executed and reported by the **operator**, who ran the
commands against the real local PostgreSQL and the real llama.cpp inference workers. The
agent did not run these and is not claiming to. The one exception is the collection count
re-check below, which the CEO ran read-only.

### 8.1 Test suite

| # | Item | Result as reported | Executed by | Verdict |
|---|---|---|---|---|
| 1 | Full suite passes | **62/62** — real local PostgreSQL, real `embedder` and `reranker` containers, HTTP against the running API. No mocks, no in-process client. | **operator** (terminal output pasted) | **VERIFIED** |
| 2 | Suite size | `pytest --collect-only -q` → **62 tests collected** (35 before this phase; `test_search.py` adds 26 test functions, several parameterised). | **CEO** (command + output below) | **VERIFIED** |
| 3 | No `pytest.skip()` anywhere in `api/tests/` | AST walk over all four test modules finds **zero** calls to `pytest.skip`, `pytest.mark.skip` or `pytest.mark.skipif`. The four textual matches are the word appearing *inside docstrings that forbid it*. | **CEO** (command + output below) | **VERIFIED** |

```console
$ .venv/bin/python -m pytest --collect-only -q 2>&1 | tail -1
62 tests collected in 0.41s
```

### 8.2 A live search, ranked by the real cross-encoder

| # | Item | Result as reported | Executed by | Verdict |
|---|---|---|---|---|
| 1 | A relevant query returns the relevant document first | Query about recovering files from a user's Recycle Bin, scoped to `it-support`, ranked **`support-recycle-bin-file-recovery`** first. | **operator** (terminal output pasted) | **VERIFIED** |
| 2 | The funnel ran at its configured size | **10 candidates considered, 5 results returned.** | **operator** (terminal output pasted) | **VERIFIED** |
| 3 | Every result is in the searched collection | **All 5 in `it-support`.** No `infra-*` document appeared. | **operator** (terminal output pasted) | **VERIFIED** |
| 4 | `relevance_score` and metadata survive the round trip | Both present on every result; `distance` (stage 1) accompanies `relevance_score` (stage 2) so a result can explain why it was considered at all. | **operator** (terminal output pasted) | **VERIFIED** |

Nothing here was seeded by the test suite. The corpus is the one
`scripts/load_corpus.py` loaded, queried over HTTP, and ranked by the real
`bge-reranker-base` worker.

### 8.3 A transient failure, recorded because hiding it would make this record worthless

**A `connection reset` was observed once on `GET /health/live` during this run. It was not
reproduced. The full suite passed cleanly on rerun.**

The **operator's assessment** — and it is the operator's, not the agent's — is that this is
most consistent with the `api` container not yet listening immediately after
`docker compose up -d --build api`. The compose healthcheck's `start_period` is 30s, and a
probe issued before the process is accepting connections inside that window gets a reset
rather than a refusal.

Stated plainly so it cannot be quietly reinterpreted later: **if this recurs OUTSIDE a
restart window, it is a real defect and must be investigated — not dismissed.** A connection
reset on liveness in steady state is not a startup artefact; it would point at the
connection pool, the event loop, or something wedging and restarting the process. The
30-second-window explanation makes this occurrence unremarkable. It does not license
ignoring the next one.

The reason this is in the record at all: a verification record that hides a flake is worse
than one that has never seen one. Green that hides a known-unexplained failure teaches the
next reader that the log is complete when it is not.

### 8.4 The isolation control — the real proof, on real data

Collection filtering is claimed in `store.py`'s docstring and proved by a mutation test in
§8.5. This section is the *measurement*: what the claim looks like against the live 40-document
corpus, with the adversarial `isolation_canary` twin pairs as the probe.

| # | Measurement | Result as reported | Executed by | Verdict |
|---|---|---|---|---|
| 1 | Search scoped to `infrastructure` | **10 candidates, all 10 in `infrastructure`.** The `it-support` twin of the canary pair **never appears**. | **operator** (terminal output pasted) | **VERIFIED** |
| 2 | The same query as a **global** search, no collection predicate | The twin **`support-service-account-password-rotation` ranks #2 overall**, distance **0.3018**, behind only its infrastructure counterpart `infra-aws-iam-key-rotation` at **0.2071**. | **operator** (terminal output pasted) | **VERIFIED** |
| 3 | How much of the global top 10 belongs to the collection actually asked for | **Only 7 of the global top 10 are `infrastructure`.** Three are `it-support`. | **operator** (terminal output pasted) | **VERIFIED** |

**The conclusion, stated because it is the part that matters:** the `WHERE` clause is doing
**two jobs at once**, and a system that only believed it was doing one was still broken.

1. **It excludes the canary twin that would otherwise have been reranked into the top 5.**
   Row 2 is not an anecdote — the twin is the *second most relevant document in the entire
   corpus* for that query. A filter that leaked would surface it immediately, which is why
   this pair is a canary at all.
2. **It recovers three `infrastructure` documents a fetch-then-filter would have silently
   discarded.** Row 3: a global top-10 holds only 7 infrastructure documents, so
   global-top-10-then-filter-in-Python returns **7, not 10** — and the three it loses are not
   arbitrary; they are the three the *global* metric judged least similar, which is exactly
   the population a `collection = :collection` predicate never restricted in the first place.

That second job is the one that fails silently. A leaked filter is loud (a foreign document
in the response, caught by any isolation assertion). A starved filter is **silent**: correct
documents, correct collection, fewer of them, HTTP 200, and a retrieval system that gets
steadily worse as the corpus grows while every test asserting isolation stays green.

This is the recall-destruction argument, demonstrated on real data rather than asserted from
the shape of the SQL.

### 8.5 An isolation test that was found BLIND

**This is the most important thing this phase produced, and it is a record of a test that
was passing while testing nothing.**

The original `test_retrieve_returns_only_documents_from_the_asked_collection` used a query
vector seeded `_vector(1)` — **the same seed as the `alpha-0` fixture**. So `alpha-0` sat at
distance exactly `0.0000` from the query, and the global top-3 came back as `alpha-0`
(0.0000), `alpha-1` (0.1298), `alpha-2` (0.1747), with `beta-0` at the *same* 0.1747.

**All three of the global top 3 were collection A's.** A fetch-then-filter implementation
would therefore return all three and the test would **PASS against the broken code**. The
test was discriminating on a coin flip that happened to land the right way. It was not a
test of SQL filtering; it was a test of which three of eight deterministic vectors happened
to be numerically closest.

**Proven by mutation, not by argument.** `store.retrieve` was temporarily rewritten into
global-top-N-then-filter-in-Python, and the test was run against the mutated implementation:

| # | Run | Result | Executed by | Verdict |
|---|---|---|---|---|
| 1 | Old seed **+** post-filter mutation | **PASSED** — the test was blind to the defect it existed to catch. | **operator** (terminal output pasted) | **DEFECT CONFIRMED** |
| 2 | New seed (`_vector(104)`, one of B's own seeds) **+** post-filter mutation | **FAILED: `assert 2 == 3`** — the post-filter returned 2 where the `WHERE` clause returns 3. | **operator** (terminal output pasted) | **DEFECT CONFIRMED** |
| 3 | `api/app/store.py` restored | **Byte-identical** to its pre-mutation state. | **operator** (`git diff` empty) | **VERIFIED** |

Measured with the corpus loaded, after the seed change: the global top-3 is `beta-4`
(0.0000), `alpha-0` (0.2103), `alpha-1` (0.2380) — **two** A documents, so the post-filter
returns 2 and `len(from_a) == 3` fails.

**A control assertion now runs on every execution**, so the test proves itself armed rather
than relying on a reader having done the arithmetic:

```python
shortlist_a = [i for i, c in global_shortlist if c == FIXTURE_COLLECTION_A]
assert len(shortlist_a) < 3, "a fetch-then-filter could fill the limit entirely from
                              the right collection and len(from_a) == 3 would be
                              satisfied by the bug. This test no longer
                              discriminates."
```

The CEO verified this arithmetic independently, by recomputing `_vector` in isolation rather
than trusting the comment: with the current seeds the global top-3 is `['beta-4', 'alpha-0',
'alpha-1']` — **2 of 3 are collection A**, so the assertion holds and a post-filter genuinely
under-fills. With the old seed `_vector(1)` the global top-3 is `['alpha-0', 'alpha-1',
'alpha-2']` — **3 of 3**, confirming the original test was blind.

The general lesson, and the reason it is recorded rather than quietly fixed: **a test whose
discrimination depends on incidental numeric properties of its fixtures must assert those
properties on every run.** A comment saying "this seed was chosen because…" is a claim
about arithmetic that silently rots the first time someone edits `_vector`.

### 8.6 Measured rerank latency

Ten real corpus documents, 15,468 characters total, two independent runs of five samples
each. This is the evidence behind `RETRIEVAL_CANDIDATES` 50 → 10.

```console
run A: min  8.191s  median 11.409s  max 12.996s
run B: min  9.354s  median 12.466s  max 13.214s
```

| # | Item | Result as reported | Executed by | Verdict |
|---|---|---|---|---|
| 1 | Cost of one stage-2 pass over 10 documents | **~11–12.5s median**, i.e. **~1.1–1.25s per candidate.** | **operator** (two runs, terminal output pasted) | **VERIFIED** |
| 2 | Extrapolation to 50 candidates | **~55–60s.** Linear, with no batch discount — the reranker is a cross-encoder scoring every (query, passage) pair on CPU. | **CEO** (arithmetic on row 1) | **VERIFIED** |
| 3 | Why no latency bound is asserted | The **4.8s spread** between min and max is larger than most of the gap between a fast and a slow run. A tight threshold on a shared host is a flaky test that teaches the team to ignore it. The test therefore **reports its distribution and asserts no bound**; the only assertions are that the call completed and that it scored all 10 documents with a stable index order across samples. | **CEO** (reading the test) | **VERIFIED** |

### 8.7 What this measurement is NOT — the limits, unsoftened

- **Measured on the developer's host, not EC2.** No EC2 instance, no `t3.micro`, no ALB in
  this measurement. The Milestone 2 hardware description (`t3.micro`, ~913Mi, ~280Mi
  available at rest) is what motivates the 50→10 decision; it is not what this number was
  taken on.
- **Service-to-service, not end-to-end.** This is the client-side cost of calling the API's
  reranker from inside the test process. It **excludes** the ALB hop, request queueing, and
  the client's own network — all of which a real latency SLO would have to contain.
- **This is not an SLO and must not be quoted as one.** It is an observation made after the
  fact, on one host, at one candidate count, with one model. An SLO is a commitment made in
  advance and held over time.

### 8.8 Known limitations of this phase

Stated plainly, not softened. Inherited items are marked as such.

1. **Python version skew.** Local venv is **Python 3.14.4**; `api/Dockerfile` is
   `python:3.12-slim`, and **`python3.12` is not available on this host**. A 3.12-only
   incompatibility would not be caught locally. Inherited from §4.4 item 2.
2. **Least privilege is asserted, not demonstrated.** The local devdb role is a
   **SUPERUSER**, so the `DATABASE_URL` / `ALEMBIC_DATABASE_URL` split is enforced by
   variable naming and documented intent only. Inherited from §4.4 item 3 / §5.5 item 1.
3. **No AWS anything.** No SSM, no Secrets Manager, no boto3, no IAM, no RDS. The
   SSM → Secrets Manager credential path is **still unimplemented** — the
   `DatabaseUrlResolver` seam is documented and deliberately left unwritten. The
   `feat/aws-infrastructure` IAM changes are **NOT applied**, so deployed permissions
   remain unverified. Inherited from §5.5 item 3.
4. **`RETRIEVAL_CANDIDATES`, `RERANK_TOP_K` and `QUERY_PREFIX` are read by the code but are
   NOT passed into the `api` container by compose.** `docker-compose.yml`'s `api` service
   supplies exactly two variables — `DATABASE_URL` and `EMBEDDING_DIM` — so all three
   resolve from `config.py`'s code defaults regardless of what a local `.env` says. The
   **asymmetry is real and worth naming**: an operator editing `.env` and seeing no change
   in the running service has found this, not a bug in the code reading. `test_search.py`
   asserts against the code defaults (`CONFIGURED_CANDIDATES = 10`, `CONFIGURED_TOP_K = 5`)
   rather than re-reading its own environment, precisely so it does not fail for this reason,
   and `README.md` now states it. It is nonetheless an asymmetry, and closing it (passing the
   three variables through compose) is a change nobody has made.
5. **The `.env` on the operator's machine still said `RETRIEVAL_CANDIDATES=50`** until this
   phase. `.env.example` said 50 too, so the operator's file was correct against the
   documentation — the documentation was wrong against the code. The operator has updated it.
   Because of item 4 above this had **no effect on the running service**, which is precisely
   why the bug could sit unnoticed: the code default and the documented value disagreed and
   nothing was reading either.
6. **Persistence across a container restart is still UNTESTED.** Row 4 of §6 remains
   **UNTESTED** and is **not** promoted by this phase. It is now more load-bearing than it
   was in Phase 2: `store.prepare_database`'s pool-dispose is the thing that arms vector
   writes, and that arming has only ever been observed against a freshly started process.
   See §6.2.

### 8.9 The Phase 4 code itself, read by the CEO

Sections 8.1–8.8 are all runtime evidence: something was executed and its output reported.
This subsection is a different kind of claim — a **static read of the diff**. The CEO read the
Phase 4 changes directly and reported five findings. No command output is quoted because no
command produced them; the artefact is the reading, and the references below are the exact
lines it was made against, re-checked against the tree as committed here.

| # | Finding | Reference | Executed by | Verdict |
|---|---|---|---|---|
| 1 | **`QUERY_PREFIX` is applied at exactly one site.** `embed(EmbedRequest(text=QUERY_PREFIX + body.query))`. The query is prefixed, documents are not, and there is no second application site anywhere in the tree. | `api/app/main.py:1381` (the only application site); `main.py:1255` is a **docstring example**, not code; the constant and its env var live at `api/app/config.py:160-181` | **CEO** (code read) | **VERIFIED** |
| 2 | **Index mapping is structurally safe.** The reranker returns an index into the array we sent, and the score is bound **inside the same tuple as its document** (`mapped.append((candidates[result.index], result))`), so the sort at `:1493` cannot physically detach a score from the document it was computed for. An out-of-range index is **logged and skipped**, not turned into a 500 on every search. Mapping happens **before** `mapped[:top_k]` truncation. | `api/app/main.py:1469-1483` (mapping), `:1476` (range check), `:1483` (tuple binding), `:1493` (sort), `:1505` (truncation) | **CEO** (code read) | **VERIFIED** |
| 3 | **The search path logs no user data.** No query text and no document content at INFO or above. Retrieval failures log the exception **class and SQLSTATE but deliberately not the message** — asyncpg `DETAIL` lines carry row contents, and this query's bound parameters include the caller's query vector. | `api/app/main.py:1418` (class + SQLSTATE, no message); `:1435` (collection only); `:1511` (collection, counts and funnel numbers only) | **CEO** (code read) | **VERIFIED** |
| 4 | **An empty collection short-circuits before stage 2**, so the reranker is never called with an empty list. | `api/app/main.py:1430` | **CEO** (code read) | **VERIFIED** |
| 5 | **`Funnel.clamped()` can only ever subtract.** Both bounds are resolved with `min()`, so a caller may narrow the funnel but never widen it. Defaults are `DEFAULT_RETRIEVAL_CANDIDATES = 10` and `DEFAULT_RERANK_TOP_K = 5`. | `api/app/config.py:235-272` (`clamped`), `:267` and `:271` (the two `min()` calls), `:201` (candidates = 10), `:206` (top_k = 5) | **CEO** (code read) | **VERIFIED** |

**Why this subsection exists at all, and what it is not.** §8.5's lesson is that a check
which passes is not the same as a check which *discriminates*. A code review has the same
blind spot from the other direction: it can only report what the author drew attention to,
and its agreement with §8.1–8.8 is **not** independent corroboration — it is the same
authorial intent inspected twice. What it does add is reach: findings 1–5 are properties of
the code that no runtime test in §8.1 would exercise. A test suite that passes 62/62 is
consistent with a second application site of `QUERY_PREFIX`; this reading is what says there
isn't one. Neither substitutes for the other, and neither is a substitute for the untested
row 4 in §6.2.