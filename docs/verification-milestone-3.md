# Milestone 3 — Verification Record (IN PROGRESS)

**This is a running record, not a finished report.** Milestone 3 is in progress. Only
Phase 0, Phase 1 and Phase 2 have been touched. Ingestion, semantic search, reranking,
persistence across a container restart, and collection isolation — every M3 acceptance
criterion — remain untested. Sections below are added as each phase is verified; this
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

## 5. M3 acceptance criteria — status

| # | Criterion | Status |
|---|---|---|
| 1 | Ingestion of the corpus | **UNTESTED** |
| 2 | Semantic search returns relevant results | **UNTESTED** |
| 3 | Reranking applied | **UNTESTED** |
| 4 | Persistence across container restart | **UNTESTED** |
| 5 | Collection isolation (canary pairs never cross) | **UNTESTED** |

Two supporting infrastructure criteria were verified in Phase 2 and are recorded here so
the milestone's shape stays visible:

| # | Criterion | Status | Where |
|---|---|---|---|
| 6 | `GET /health/live` returns 200 | **VERIFIED** | §4.3 row 1 |
| 7 | `GET /health/ready` returns 200 with `database`, `embedder`, `reranker` all `ok` | **VERIFIED** | §4.3 row 2 |

**No retrieval criterion has been checked.** Rows 1–5 are every M3 acceptance criterion
that matters, and all five remain UNTESTED. Rows 6 and 7 are infrastructure the
retrieval layer depends on, not evidence about it: a container that reports itself ready
and a table that answers a `<=>` query are different claims, and only the first has been
made. This table exists so the gap is visible, not to imply progress.

---

## 6. Re-check this record

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

When the next phases land, add them as new numbered sections below rather than editing
rows 1–8 above. A verification record that gets rewritten is not a record.