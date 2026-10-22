# Milestone 5 — Verification Record

> ## ⚠️ **MILESTONE 5 IS IN PROGRESS. NO INCIDENT HAS BEEN RECORDED.**
>
> This is a running record, not a finished report. **One functional baseline has
> been observed and is recorded in §2. No incident has occurred and none is
> recorded.** Nothing in this document is invented: every value below was read
> from the evidence files named beside it, and where a value is unknown this
> document says so rather than filling it in.
>
> | Section | What it holds |
> |---|---|
> | **§1** | The two ledgers — functional observations here, incidents in `INCIDENTS.md` |
> | **§2** | M5-001 — the first functional baseline |
> | **§3** | The functional test ledger |
> | **§4** | The incident ledger index — **zero** records |
> | **§5** | The M5 deliverables tracker |
> | **§6** | The evidence-retention convention |
> | **§7** | The operator-driven learning contract |
>
> **The headline fact, compactly.** One black-box request — `POST /search` to the
> public ALB — returned **HTTP 200** in **15.234854 s**, with the correct document
> first (`support-recycle-bin-file-recovery`, collection `it-support`). It is
> **one observation**, not a latency distribution, and it is **evidence, not an
> incident** (§1). The three required incidents remain at **0 of 3** (§5).

---

## 1. Two ledgers

Milestone 5 keeps two separate records, and they are not interchangeable.

| Ledger | Where it lives | What belongs in it |
|---|---|---|
| **Functional / ordinary observations** | **this file** — `docs/verification-milestone-5.md` | Requests that were made, what they returned, and whether the result matched the operator's stated prediction. A working baseline is recorded here. |
| **Incidents** | `INCIDENTS.md` §5.1 / §5.2 / §5.3 | A fault: a broken state with a symptom, a testable hypothesis, evidence, a correction, and a verified recovery. |

**The rule that keeps the two apart, stated plainly:** a successful baseline
that works is **EVIDENCE, never an incident**. It shows the system doing what it
is meant to do; it has no broken state, no hypothesis to test and no recovery to
demonstrate. **A baseline must never be counted as one of the three required
incidents.** The three incident records this milestone asks for must each exhibit
the whole arc — broken, hypothesised, evidenced, corrected, recovered — and a
green request exhibits none of it.

---

## 2. M5-001 — the first functional baseline

| Field | Value |
|---|---|
| **id** | `M5-001` |
| **ledger** | functional-baseline — **NOT an incident** |
| **persona** | Tier-1 API end user (black-box) |
| **Timestamp (UTC)** | `2026-10-15T21:42:50Z` |
| **Route** | `POST /search` via the public ALB, from the operator workstation |
| **Request** | `collection=it-support`; a query about recovering a file deleted from the Recycle Bin |

**Observed.**

| Field | Value |
|---|---|
| HTTP status | **200** |
| Total latency | **15.234854 s** |
| Connect | **0.106971 s** |
| First byte | **15.230363 s** |
| `candidates_considered` | **10** |
| Results returned | **5** |
| Top result `document_id` | **`support-recycle-bin-file-recovery`** (collection `it-support`) |
| Reranker model | **`bge-reranker-base`** |

**Operator prediction, recorded before the request was executed.** HTTP 200;
latency between 10 and 30 seconds; the correct document first. **Outcome: the
prediction matched.** The prediction is recorded because it was written down
first — a prediction stated after the result is not a prediction.

**Classification:** VERIFIED baseline. It is a verified **baseline**, not a
verified **recovery** — nothing was broken, so nothing was recovered. See §1.

**Evidence path:** `~/lemondrop-m5-evidence/20261015T214250Z/` — `start.txt`,
`timing.txt`, `headers.txt`, `response.json`.

**Evidence-file checksums (sha256).** Computed in this pass with `sha256sum`:

| File | sha256 |
|---|---|
| `start.txt` | `b770fa8d5bb0eb9328f7043bddafc862bf7ed0600572284235c63d281887d72f` |
| `timing.txt` | `37d525097c240e746f077d3295c0eb0846aa3227e9f2cf409eb98da47d251dab` |
| `headers.txt` | `e2f71582519cc43ae86e0883d72bd650bc140a320dff55b76f3a9588b33cdaa2` |
| `response.json` | `0e561558c79f60edc44a94bb61c81acec1d8dc0696a2cee1cde599acf4c67a16` |

**Caveats, stated so this row is not over-read.**

- **15.234854 s is a single observation, not a distribution.** It is not a mean,
  a median, a p95, an SLO or a margin. One request was made.
- **The ALB 60 s idle-timeout versus the ~240 s worst-case `/search` remains
  unresolved.** It is the known configuration gap carried from
  `docs/verification-milestone-3.md` §10.8 and `docs/verification-milestone-4.md`
  §12.5. This baseline does not narrow it: 15.23 s is well inside the timeout, so
  the timeout was not exercised.
- **The raw evidence directory currently lives OUTSIDE Git** (see §6).

---

## 3. Functional test ledger

| id | route | status | verdict | evidence |
|---|---|---|---|---|
| `M5-001` | `POST /search` (public ALB) | HTTP 200 | **VERIFIED baseline** — prediction matched | `~/lemondrop-m5-evidence/20261015T214250Z/` (§2) |
| `M5-002` | multiple routes (public ALB) | mixed | **DEMONSTRATION** — no prediction recorded first; reachability and happy path confirmed; candidate faults E5/H2/A8/A14/E1-E2 observed | `~/lemondrop-investigation/CLIENT-PERSPECTIVE-EVIDENCE.md` (§8) |

`M5-001` remains the only predicted test. `M5-002` is a demonstration/observation
session; its findings are recorded in §8.

---

## 4. Incident ledger index

Genuine incidents do not live here. They live in `INCIDENTS.md`, one per category
section, following the five-stage template in `INCIDENTS.md` §4.

| Category section | Location | Recorded so far |
|---|---|---|
| Networking | `INCIDENTS.md` §5.1 | **ZERO** |
| Dependency | `INCIDENTS.md` §5.2 | **ZERO** |
| Application-correctness | `INCIDENTS.md` §5.3 | **ZERO** |

**Zero of the three required incidents are recorded.** §5 item (e) tracks this.

---

## 5. M5 deliverables tracker

| # | Deliverable | Status |
|---|---|---|
| a | Git repo with app / Terraform / Docker / tests / automation | **PRESENT/PASS.** The repository is present at the current `HEAD`; `api/`, `infra/`, `docker-compose.yml`, `scripts/` and `.github/workflows/` are committed. `models/` contains only the `.gitkeep` placeholder — the `*.gguf` weight files are gitignored and are not tracked. The E5 fix was introduced in `04ab05d` and the M5 record in `6cc54bc`; both are in `main` history. |
| b | Architecture diagram (networks, routing, ports, security groups, dependencies) | **PASS.** `docs/architecture.md` is present and committed; its content covers §1 network topology, §2 ports, §3 the security-group matrix, §4 request flow, §6 non-reachability/egress, and §7 service dependencies. The adequacy judgement remains the operator's gate. |
| c | Reproducible README | **PARTIAL.** `README.md` is committed and corrected. A static documentation audit now exists as a dated record at `/home/zaratustra0/lemondrop-investigation/README-RUNBOOK-AUDIT.md` (99 claim rows — 74 MATCH, 6 PARTIAL, 13 MISMATCH, 6 NOT-CHECKABLE-STATICALLY; all 13 mismatches corrected, including the T3-tier subset wording in `README.md`). That audit is a static text check, not a runtime proof. A **clean-host reproduction still does not exist** and remains the outstanding part. |
| d | Operational RUNBOOK | **PARTIAL.** A static documentation audit now exists at `/home/zaratustra0/lemondrop-investigation/README-RUNBOOK-AUDIT.md` (99 claim rows — 74 MATCH, 6 PARTIAL, 13 MISMATCH, 6 NOT-CHECKABLE-STATICALLY; all 13 mismatches corrected). The artefact establishes that every documented command's path, flags, variables, counts and citations in `README.md`, `RUNBOOK.md`, `COSTS.md` and `docs/end-to-end-demo.md` was checked statically against the repository at HEAD. It does **not** establish that any recovery command was executed, that any command works at runtime, or that the end-to-end command audit was performed — that remains outstanding. The `db_skip_final_snapshot` correction in `RUNBOOK.md` is in place and is not at risk. |
| e | Timestamped investigations in `INCIDENTS.md` | **UNTESTED, 0 of 3.** The three category sections in `INCIDENTS.md` exist and are EMPTY. No operator-driven fault exercise has been performed; no incident record has been written. `docs/maintenance-challenge.md` is unexecuted preparation for the operator's exercise. |
| f | `COSTS.md` — expected **and** observed | **PARTIAL.** AWS Cost Explorer was read for period 2026-10-01 to 2026-10-21 (end exclusive) and returned a near-zero estimated total; the record is `Estimated: true` and the period is open. The read does not explain why the EC2 t3.small running since 2026-10-13 does not appear as a compute charge, so a closed-period invoice is required. A derived list-price cross-check (198.5920 h × $0.0228 = ~$4.53) is kept separately and labelled `DERIVED-ESTIMATE-NOT-A-BILL`; it is not entered as observed. See `~/lemondrop-investigation/OBSERVED-COST-EVIDENCE.txt`. |
| g | End-to-end ALB → app → PostgreSQL → response walkthrough | **PARTIAL.** The 2026-10-22 post-release walkthrough captured: a prediction written before the first request; the known-good probe returning HTTP 200 with `support-recycle-bin-file-recovery` first, **5** results, **10** candidates, model `bge-reranker-base`, latency **14.615 s**; and host-side `api`/`embedder`/`reranker` logs over the same UTC window, with reranker task ids 1514–1523 independently confirming the 10 candidates. Source address `213.22.54.159` matched the allow-list. What it does **NOT** capture: the ALB access-log hop (logs are OFF); the database SQL-statement hop (exported PostgreSQL log holds only checkpoints); request-id propagation (the system has none, so correlation is by timestamp window only); and the operator's own predicted-before-execution test under the `M5-001` convention — the walkthrough prediction was the agent's, not the operator's. See §8 and `~/lemondrop-investigation/POST-RELEASE-WALKTHROUGH-EVIDENCE.txt`. |
| h | Verified teardown preserving Git evidence | **UNTESTED.** No teardown evidence of any kind exists. |

---

## 6. Evidence retention

Raw evidence is produced outside the repository and is **not committed while it
is raw**. After the record is reviewed:

- the **raw** evidence — verbatim responses, headers, logs, timing files — stays
  **outside Git until the record is reviewed**;
- once reviewed, **sanitized evidence, or stable references to where the raw
  evidence is retained**, are committed;
- **credentials are never committed** — no secrets, tokens, connection strings or
  private keys, sanitized or otherwise.

The M5-001 directory (§2) is currently in the raw, outside-Git state.

---

## 7. The operator-driven learning contract

Hands-on tests in this milestone follow one loop, and the operator drives every
step of it:

**PREDICT → EXECUTE → OBSERVE → EXPLAIN → REVIEW.**

| Step | What the operator does |
|---|---|
| **PREDICT** | Before running anything, write down what is expected: status, rough latency, correct result. Written first, on file. |
| **EXECUTE** | Run the request, black-box, from a real vantage point — the operator workstation, through the public ALB. |
| **OBSERVE** | Capture the raw result to files — status, timing, headers, body — before interpreting it. |
| **EXPLAIN** | Reconcile the observed result against the prediction, including the places where the prediction was wrong. |
| **REVIEW** | Read the record back: is the evidence checkable, is the claim supported, is the caveat stated. |

**The prediction is the point.** A result with a prediction recorded in advance
is a test; the same result without one is a demonstration. M5-001 (§2) is the
first test run under this contract.

---

## 8. M5-002 — 2026-10-21 client-perspective session

This session was a **demonstration, not a predicted test** — the operator's
predicted-before-execution contract was last honoured for `M5-001` on
2026-10-15. It was performed over the public ALB from the authorized workstation.

### Session header

| Field | Value |
|---|---|
| **id** | `M5-002` |
| **ledger** | functional-observation — **NOT an incident** |
| **date (UTC)** | 2026-10-21 |
| **UTC window** | 21:10 – 21:33 |
| **base URL** | `http://lemondrop-dev-alb-285677848.eu-west-1.elb.amazonaws.com` |
| **roles dispatched** | 1. Integration Observer + Happy Path Explorer (`moe-build`, 21:10)<br>2. Adversarial User (`moe-build`, 21:14 – 21:19)<br>3. Edge Case Hunter (`moe-wire`, 21:27 – 21:33) |

### Reachability determination

| Field | Value |
|---|---|
| Measured egress IP | `213.22.54.159` |
| ALB allow-list entry | `213.22.54.159/32` |
| Comparison | **MATCH YES** (exact /32) |
| Verdict | **REACHABLE** |

Command:

```text
curl -sS --max-time 10 https://api.ipify.org
```

Output: `213.22.54.159`

### Health checks

All three health endpoints returned HTTP 200 from the public ALB:

- `GET /health` → `{"status":"ok","embedder":"ok","reranker":"ok"}`
- `GET /health/live` → `{"status":"ok"}`
- `GET /health/ready` → `{"status":"ok","embedder":"ok","reranker":"ok","database":"ok"}`

### Happy-path search

`POST /search` with the `client.md` §4 example returned HTTP 200 in ~14–15 s,
`candidates_considered=10`, five results, top result
`support-recycle-bin-file-recovery` in `it-support`, model `bge-reranker-base`.

### Established limits (Role 3)

| Route | Input | Boundary | At/below boundary | Above boundary |
|---|---|---|---|---|
| `/embed` | `text` | 2048 characters | 2048 chars → 200 | 2049 chars → 422 `string_too_long max_length=2048` |
| `/rerank` | `query` | 2048 characters | 2048 chars → 200 | 2049 chars → 422 `string_too_long max_length=2048` |
| `/rerank` | `documents[i]` | 2048 characters | 2048 chars → 200 | 3000 chars → 422 `string_too_long max_length=2048` |
| `/search` | `collection` | unbounded length | 1, 100 and 300 chars → 200 | only non-blankness enforced |
| `/rerank` | `top_n` | 1 to document count | 1 → 1 result; 2 → 2 results; omitted → all 3; 1000 → clamped to document count | N/A |
| `/rerank` | `documents[]` | min length 1 | empty → 422 `too_short min_length=1`; 1 entry → 200; 50 entries → 200, relevant doc at index 49 ranked first | N/A |
| `/rerank` | whitespace-only entry | N/A | 422 `value_error "string must not be blank or whitespace-only"` | N/A |
| `/search` | whitespace-only query | N/A | 422 `string_too_short` | N/A |
| `/embed` | 2048 guard | characters, not bytes | 2048 CJK chars forwarded to worker | 2049 CJK chars → 422 |
| `/search` | query length | at least 1 character | 1-char query, single emoji, lone combining mark → 200 | N/A |
| `/health` | `Accept: text/html` | header ignored | still `application/json` | N/A |
| `/health` | `HEAD` method | not allowed | 405 Method Not Allowed with `allow: GET` | N/A |

### Findings from this session

These are **observations and candidate faults**, not incident records. They are
recorded here so the acceptance picture is honest.

#### E5 — `POST /search` with a 2048-character query returns opaque HTTP 500

**Status (2026-10-22): FIXED AND DEPLOYED.** The root cause and symptom capture
below are kept exactly as they were recorded while E5 stood against the deployed
service. The regression test and the local fix record follow the original
capture. The fix is now live in production.

- **Severity:** CRITICAL (fixed and deployed; historical capture retained)
- **Deployed image:**
  `ghcr.io/fvitorino00/lemondrop-api@sha256:c2c1d81c5e743fb8b92b6b9e244179441c345d9441341e525d8d6865dfab39d4`
- **Source revision:** `6cc54bc4c09182e37575c5fedb2ad57c71dc7d58`
- **Release run:** GitHub Actions release run **39708332804**, 9/9 jobs green,
  published the image above
  (`~/lemondrop-investigation/RELEASE-PUBLISH-EVIDENCE.txt`).
- **Deploy:** SSM Run Command as root, command id
  **b402a174-72b3-4422-8100-e45033b08aa4**, exit code **0**
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt`).
- **Verify:** SSM Run Command as root, command id
  **4adcb66f-0b11-40f5-a638-33f35b7408b4**, exit code **0**, **PROBLEMS=0**,
  printing `VERDICT: everything above is consistent. Nothing to do.`, with
  `AGREE`, `PROVENANCE AGREE` and `SCHEMA AGREE`
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt`).
- **Exact command:**

  ```text
  BASE_URL="http://lemondrop-dev-alb-285677848.eu-west-1.elb.amazonaws.com" && jq -nc '{collection: "it-support", query: ([range(410)] | map("word ") | add | .[0:2048])}' | curl -sS -i "$BASE_URL/search" -H "Content-Type: application/json" --data-binary @-
  ```

- **Verbatim response:**

  ```http
  HTTP/1.1 500 Internal Server Error
  Date: Wed, 21 Oct 2026 21:29:37 GMT
  Content-Type: text/plain; charset=utf-8
  Content-Length: 21
  Connection: keep-alive
  server: uvicorn

  Internal Server Error
  ```

- **Expected behaviour per `client.md`:** Invalid or oversized input should be rejected with a 422
  naming the field.
- **Root cause — confirmed by source inspection:**
  - `api/app/main.py:1471` builds a **second** validated model inside the `/search` route:
    `embed(EmbedRequest(text=QUERY_PREFIX + body.query))`. The prefix is appended **after**
    the request-level validation.
  - `api/app/main.py:1206` declares `SearchRequest.query: NonBlankText`, whose constraint is
    `max_length=MAX_INFERENCE_INPUT_CHARS` (2048) with `strip_whitespace=True` (type definition
    at `:150-157`; constant at `:132`). A query of exactly 2048 characters therefore passes the
    edge guard.
  - `api/app/main.py:656-668` declares `EmbedRequest.text` as `NonBlankText`, so the prefixed
    string re-validates against the same 2048 cap. With the default prefix
    (`api/app/config.py:177`, `"Represent this sentence for searching relevant passages: "`,
    57 characters), a 2048-character query becomes a 2105-character string and raises a
    pydantic `ValidationError` inside the route handler.
  - No handler catches it: the route's only exception catches is the `SQLAlchemyError` catch
    (`:1501`) and the rerank index guard (`:1576`); there is no exception handler for
    `pydantic.ValidationError` in `main.py`. FastAPI converts only **request-parsing**
    validation errors into 422, so the error escapes to Starlette's error middleware and becomes
    an opaque HTTP 500 with `Content-Type: text/plain; charset=utf-8` and body
    `Internal Server Error` — matching the captured response byte for byte.
  - Why only `/search`: `/embed` maps a worker HTTP error to 502
    (`{"detail":"embedder returned HTTP 500"}`) at `main.py:599-631` and never re-wraps the
    input; `/rerank` never prefixes the query, so it is unaffected.
- **Hypotheses (not confirmed by direct observation):**
  - The production `QUERY_PREFIX` value is environment-overridable (`api/app/config.py:170-191`)
    and was **not observed** in any witness file.
  - The threshold window (roughly 1992–2048 characters, given a 57-character default prefix) is
    an arithmetic consequence of the confirmed mechanism, not a measured boundary.
  - The 2049-character `/search` boundary was never probed — the session stopped that line of
    attack after the first 5xx.
  - The 2048-character observation was a single un-repeated request.
- **Consequence for acceptance:** The defect was a per-request unhandled exception, not a
  process crash. The fix is now deployed; the consequence text above is historical only.

##### Deployment proof (2026-10-22)

The fix was proven against the **deployed** service through the public ALB.

- **Health routes** (all HTTP 200):
  - `GET /health` → `{"status":"ok","embedder":"ok","reranker":"ok"}`
  - `GET /health/live` → `{"status":"ok"}`
  - `GET /health/ready` → `{"status":"ok","embedder":"ok","reranker":"ok","database":"ok"}`
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §ALB_HEALTH).

- **Three-way boundary proof against the deployed service**
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §BOUNDARY_PROOF):

  | Query length | Result | Meaning |
  |---|---|---|
  | 2048 characters | HTTP **422**, body names `"body","query"`, `ctx.max_length` = **1991** | Edge rejects; no opaque 500 |
  | 1992 characters | HTTP **422**, same `max_length: 1991` | The threshold is at most 1991 |
  | 1991 characters | Accepted at the edge, then HTTP **502** `{"detail":"reranker returned HTTP 500"}` | Edge passes it; failure is the pre-existing worker-token residual (`api/app/main.py:124-126`), not E5 |

  The triple 422 / not-422 / 422 brackets the effective limit at exactly **1991**.

- **Post-release walkthrough**
  (`~/lemondrop-investigation/POST-RELEASE-WALKTHROUGH-EVIDENCE.txt`):
  - A prediction was written **before** the first request was sent.
  - The project's own known-good probe returned HTTP **200**, top document
    `support-recycle-bin-file-recovery` (collection `it-support`), **5** results,
    **10** candidates considered, model `bge-reranker-base`, latency **14.615 s**.
  - Host-side `api`, `embedder` and `reranker` container logs were captured over the
    same UTC window (2026-10-22T02:35:21Z .. 02:35:36Z); reranker task ids 1514–1523
    independently confirm 10 sequential candidates.
  - Source address measured as `213.22.54.159`, matching the ALB allow-list entry
    `213.22.54.159/32`.

- **Hops NOT observed**, recorded as such
  (`~/lemondrop-investigation/POST-RELEASE-WALKTHROUGH-EVIDENCE.txt` §NOT OBSERVED):
  - **ALB access-log hop** — access logs are off (`access_logs.s3.enabled=false`);
    enabling them is an unauthorised infrastructure change.
  - **Database SQL-statement hop** — the exported PostgreSQL log holds only periodic
    checkpoints over the window; no SQL statement is recorded.
  - **Request-id propagation** — the system has none; correlation is by timestamp
    window only.

- **Rollback:** the single remaining rollback target is the previously deployed image
  `ghcr.io/fvitorino00/lemondrop-api@sha256:8cf759f688daad5c5fbcc8a4efb6101de1de0f8efdf18c70e6aa7a8cd99f6110`
  (source revision `6b37a780e293003ba952c3e9062e8c5d126639e9`). The rollback is
  **one-way**: `rollback.sh` empties `PREVIOUS_*` on success, so exactly one rollback
  remains and no second.

- **Operator prediction:** the operator's own pre-committed prediction remains
  **outstanding** under the strict learning contract. The walkthrough prediction was
  the agent's, written before execution; it is not a substitute for the operator's.

- **2026-10-21 fix record — applied in the local tree only (historical).**
  Authorised by the operator's instruction of 2026-10-21 (the original
  authorisation is retained locally at `.workflows/2026-10-21-lemondrop-acceptance.md`,
  which is gitignored and not part of the published repository). At the time this
  record was written the fix existed only in `api/app/main.py` in the working
  tree; the deployed image (`sha256:8cf759f6…`, source revision `6b37a78…`) still
  carried the defect. The 2026-10-22 release and deployment superseded this
  state. The parts of this record:
  - **Root cause (recorded above, unchanged):** `/search` validated `SearchRequest.query` against
    the 2048-character cap, then built `EmbedRequest(text=QUERY_PREFIX + body.query)` — the
    57-character bge prefix was appended after validation and re-validated against the same 2048
    cap, so a 2048-character query produced a 2105-character string and raised a
    `pydantic.ValidationError` that FastAPI does not convert (it converts only request-parsing
    errors) and Starlette rendered as the opaque 500. The crash window was queries of 1992 to
    2048 characters.
  - **The fix (four elements):**
    1. `MAX_SEARCH_QUERY_CHARS = MAX_INFERENCE_INPUT_CHARS - len(QUERY_PREFIX)` = 2048 − 57 =
       1991, so the prefix consumes part of the caller's allowance and the forwarded string never
       exceeds the 2048-character worker budget. A fail-fast `RuntimeError` guards a prefix that
       would consume the whole budget.
    2. `SearchRequest.query` now uses a dedicated `SearchQueryText` type whose `max_length` is
       1991, so FastAPI's own request validation produces the 422 naming the field and the
       effective limit.
    3. The embedder call body was extracted into an internal `_embed_text(text: str)` taking a
       plain string; `/embed`, `/documents` and `/search` all call it, and no internal call site
       constructs a request model. The `/rerank` body was likewise extracted into
       `_rerank_texts(query, documents, top_n)`, so `/search` constructs no model there either.
       After this, **no internal call site anywhere in `api/app/main.py` constructs a request
       model** — the pattern that produced E5 is gone, not merely patched (see the dated §8
       entry on the class closure below).
    4. The prefix concatenation lives in one named helper, `_search_embedding_text(query)`.
  - **Client-visible contract change (recorded prominently):** a search query is now limited to
    **1991 characters**, not 2048. A client that today sends a query of 1992 to 2048 characters
    receives a **422** naming the field and the effective limit where it previously received an
    opaque 500 — on the local tree and any image built from it. `client.md` and `README.md` have
    been updated to state 1991. The limits of `/embed`, `/documents` and `/rerank` are **UNCHANGED
    at 2048**.
  - **Verification evidence (all local, all observed):**
    - **RED baseline demonstrated before the fix:** in a scratch copy under `/tmp/opencode/red-scratch`
      (pre-fix `api/app/main.py` from `04ab05d^` plus the current test files), the model-level
      probe failed with `DID NOT RAISE ValidationError` and the ASGI-level boundary test failed
      with `AssertionError: Internal Server Error; assert 500 == 422`. The verbatim output is
      captured in `/home/zaratustra0/lemondrop-investigation/POST-FIX-FULL-SUITE-EVIDENCE.txt`
      Capture 2 (the evidence corpus lives outside the repository by project convention).
    - **Red/green discrimination experiment:** with the boundary loosened back to 2048 while the
      constant stayed, the two boundary tests went red. The OLD suite
      (`api/tests/test_request_models.py` at `04ab05d^`) passed **50/50** against the unfixed
      code (`api/app/main.py` at `04ab05d^`), measured in a scratch copy under `/tmp/opencode`
      and captured in `/home/zaratustra0/lemondrop-investigation/POST-FIX-FULL-SUITE-EVIDENCE.txt`
      Capture 4 (the evidence corpus lives outside the repository by project convention), which
      proves the old suite could not have caught this bug.
    - **New service-free ASGI-level test module** `api/tests/test_search_boundary.py` (3 tests,
      embedder and store stubbed): (i) a 2048-character query yields 422 with `application/json`,
      `type == "string_too_long"`, `loc == ["body","query"]`, `ctx["max_length"] ==
      MAX_SEARCH_QUERY_CHARS`, and a body containing no `Internal Server Error`; (ii) a query at
      exactly the effective limit reaches the embedder with `payload["input"][0] == QUERY_PREFIX
      + query` and `len(...) <= MAX_INFERENCE_INPUT_CHARS`; (iii) with the database absent the
      request yields 503 "the database is not available", proving the harness flows through the
      handler. Proven RED against the pre-fix code (`AssertionError: Internal Server Error;
      assert 500 == 422`) and GREEN after.
    - **Per-tier results of the final local run** against a container built from the working
      tree, with the container's `main.py` SHA-256 proven equal to the working tree's: T1
      **149 passed**, T2 **28 passed**, T3 **31 passed**, full suite **208 passed** (plus
      9 subtests). The T2, T3 and full-suite counts, the image-hash proof and the localhost proof
      are in `/home/zaratustra0/lemondrop-investigation/POST-FIX-FULL-SUITE-EVIDENCE.txt` Capture 1
      (the evidence corpus lives outside the repository by project convention). The T1 count and
      the CI tier-classification drift gate are in
      `/home/zaratustra0/lemondrop-investigation/POST-FIX-TEST-EVIDENCE.txt` (the evidence corpus
      lives outside the repository by project convention): T1 = `149 passed`
      (`POST-FIX-TEST-EVIDENCE.txt:340`, `============== 149 passed, 1 warning, 9 subtests passed in 0.92s ===============`);
      the drift-gate line is `inventory=208 T1=149 T2=28 T3=31 classified=208`
      (`POST-FIX-TEST-EVIDENCE.txt:111`, `tier-classification: PASS (0 problem(s))`).
    - **Strip-order analysis:** the boundary safety of the E5 fix was verified by measurement
      (`/home/zaratustra0/lemondrop-investigation/POST-FIX-FULL-SUITE-EVIDENCE.txt` Capture 3; the
      evidence corpus lives outside the repository by project convention): pydantic 2.14.1 strips
      before the length check, and under either strip ordering the forwarded string stays within
      the worker budget.
      The independent review that reported `PASS_WITH_FINDINGS` is referenced in the record, but
      its transcript is not a retained artefact in the published repository.
  - **Deployment facts, stated plainly (2026-10-21):** at the time this fix record was
    written, the deployed image (`sha256:8cf759f6…`, source revision `6b37a78…`) was unchanged
    and still carried E5. The 2026-10-22 release and deployment recorded below carried the
    fix to production.

#### 2026-10-21 — E5 fixed in the local tree; the search-query contract is 1991 in the tree, 2048 on the deployed service

- **What changed:** The E5 root cause was fixed in `api/app/main.py` in this
  working tree, under a post-workflow continuation authorised by the operator on
  2026-10-21 (the authorisation file is `.workflows/2026-10-21-lemondrop-acceptance.md`,
  a local, gitignored working record).
- **Client-visible contract change:** the effective search-query limit in the TREE is now
  **1991 characters** (2048 minus the 57-character bge prefix); the fixes reject a longer query
  at the edge with a **422** naming the field and the effective limit. `client.md` and
  `README.md` were updated to state 1991. The limits of `/embed`, `/documents` and `/rerank`
  are **UNCHANGED at 2048**.
- **Contract state, side by side (state on 2026-10-21, now historical):**

  | Surface | Tree contract (post-fix) | Deployed service on 2026-10-21 (image `8cf759f6…`) |
  |---|---|---|
  | `/search` `query` | **1991 characters**, oversized → 422 | **2048 characters** on the request model; 1992–2048 → opaque 500 (E5) |
  | `/embed` `text`, `/documents`, `/rerank` fields | 2048 characters — unchanged | 2048 characters — unchanged |

- **Defect-class closure (F5):** with `_embed_text`/`_rerank_texts` extracted, **no internal
  call site anywhere in `api/app/main.py` constructs a request model**. The pattern that
  produced E5 — appending to a validated string and re-wrapping it in a second validating
  model — no longer exists anywhere in the module: the defect CLASS is closed locally, not just
  this instance. A8 remains an open MINOR defect against the deployed service.

#### 2026-10-22 — E5 fix published and deployed

- **What changed:** The E5 fix was released, deployed and verified in production.
- **Published image:**
  `ghcr.io/fvitorino00/lemondrop-api@sha256:c2c1d81c5e743fb8b92b6b9e244179441c345d9441341e525d8d6865dfab39d4`
- **Source revision:** `6cc54bc4c09182e37575c5fedb2ad57c71dc7d58`
- **Release:** GitHub Actions run **39708332804**, 9/9 jobs green, published the digest above
  (`~/lemondrop-investigation/RELEASE-PUBLISH-EVIDENCE.txt`).
- **Deploy:** SSM Run Command as root, command id
  **b402a174-72b3-4422-8100-e45033b08aa4**, exit code **0**
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §DEPLOY).
- **Verify:** SSM Run Command as root, command id
  **4adcb66f-0b11-40f5-a638-33f35b7408b4**, exit code **0**, **PROBLEMS=0**
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §VERIFY).
- **Behavioural proof against the deployed service:** a 2048-character `POST /search` query
  returns HTTP **422** naming `query` with `max_length: 1991`; a 1992-character query returns
  HTTP **422** with the same limit; a 1991-character query is accepted at the edge and then
  the worker answers HTTP **502** (`{"detail":"reranker returned HTTP 500"}`) — the pre-existing,
  documented worker-token residual (`api/app/main.py:124-126`), not the defect under repair
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §BOUNDARY_PROOF).
- **Health routes:** `GET /health`, `GET /health/live` and `GET /health/ready` all returned
  HTTP **200**; `/health/ready` reported `embedder`, `reranker` and `database` all `ok`
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §ALB_HEALTH).
- **Post-release walkthrough:** a prediction was written before the first request; the
  known-good probe returned HTTP **200** with `support-recycle-bin-file-recovery` first,
  **5** results, **10** candidates, model `bge-reranker-base`, latency **14.615 s**. Host-side
  `api`, `embedder` and `reranker` logs were captured over the same UTC window; reranker task
  ids 1514–1523 independently confirm the 10 candidates. Source address measured as
  `213.22.54.159` (`~/lemondrop-investigation/POST-RELEASE-WALKTHROUGH-EVIDENCE.txt`).
- **What remains open / NOT observed:**
  - The operator's own pre-committed prediction remains **outstanding**; the walkthrough
    prediction was the agent's, written before execution.
  - **ALB access-log hop** — not observed; access logs are off.
  - **Database SQL-statement hop** — not observed; the exported PostgreSQL log holds only
    periodic checkpoints over the window.
  - **Request-id propagation** — none; correlation is by timestamp window only.
  - The **DEP** finding (`pydantic` imported directly but not pinned) stays open; see below.

#### H2 — `POST /search` collection with trailing whitespace echoes the wrong collection

- **Severity:** **WITHDRAWN-AS-RECORDED** (was BLOCKING)
- **Original capture (kept visible):** Searching with collection `"it-support "` (one trailing
  space) appeared to return the same five documents as `"it-support"`, while the response's
  top-level `collection` field appeared to echo `"it-support "` and every `results[*].collection`
  read `"it-support"`. The original command and response were:

  ```text
  jq -nc '{collection: "it-support ", query: "how do I recover files a user deleted from the Recycle Bin on their workstation"}' | curl -sS -i "$BASE_URL/search" -H "Content-Type: application/json" --data-binary @-
  ```

  ```http
  HTTP/1.1 200 OK ; Content-Length: 8603
  ```

  (body as originally read: the same five documents returned for `"it-support"`, with top-level
  `collection` `"it-support "` and each result's `collection` `"it-support"`.)

- **2026-10-21 revision — controlled A/B reproduction refutes the original reading.** Two
  requests were issued against the deployed service, differing only by the trailing 0x20 byte in
  the collection value:

  | | Request A | Request B |
  |---|---|---|
  | Collection value | `"it-support "` (one trailing space) | `"it-support"` (no trailing space) |
  | Body size on the wire | 119 bytes | 118 bytes |
  | UTC timestamp | 2026-10-21T22:09:39Z | 2026-10-21T22:09:57Z |

  Both responses were:

  - HTTP/1.1 200 OK, `Content-Length: 8603`;
  - body sha256 `3cdc9f4dccc243745ca7588ac1294999e825f07d12bb80361ac50d6873b2f4fe`
    for **both** requests;
  - top-level `collection` exactly `"it-support"` in both bodies;
  - every `results[*].collection` exactly `"it-support"` in both bodies;
  - `grep -o 'it-support '` matched **zero** occurrences in either body;
  - the measured body length agreed with the `Content-Length` header for both requests.

  **Conclusion:** the two responses are byte-for-byte identical despite a one-byte request
  difference. The trailing space is stripped consistently for both the lookup and the echo. The
  original capture misread the **request** body's collection value as the **response** echo. H2
  is **WITHDRAWN AS RECORDED**.
- **Reproduced behaviour:** The trailing space is stripped before lookup and before echo, which
  matches `client.md` §3 ("Leading and trailing whitespace is stripped first, then an empty
  result is rejected"). No mismatch between searched and echoed collection occurs.
- **Consequence for acceptance:** None. The behaviour is consistent and is correctly documented
  in `client.md` §3.

#### A8 — NUL byte and control characters reach a 503 path

- **Severity:** MINOR
- **What happened:** A `collection` value containing a NUL byte and control characters returned
  HTTP 503 `{"detail":"the document store could not be searched"}`.
- **Exact command:**

  ```text
  curl -sS -i --max-time 20 -w '\nELAPSED:%{time_total}\n' -X POST 'http://lemondrop-dev-alb-285677848.eu-west-1.elb.amazonaws.com/search' -H 'Content-Type: application/json' -d '{"collection":"x\u0000y\u0001\u0002\u0007","query":"reset password"}'
  ```

- **Verbatim response:**

  ```http
  HTTP/1.1 503 Service Unavailable
  Date: Wed, 21 Oct 2026 21:16:57 GMT
  Content-Type: application/json
  Content-Length: 53
  Connection: keep-alive
  server: uvicorn

  {"detail":"the document store could not be searched"}
  ```

- **Expected behaviour per `client.md`:** `503` is documented only for a genuine database failure;
  client-controlled bytes should be rejected with 422/400 or treated as opaque data.
- **Consequence for acceptance:** Client-controlled bytes reach an infrastructure-fault path.
  Single observation only; no multi-request availability impact was tested.

#### A14 — 990 KB `/embed` body echoed back in the 422 response

- **Severity:** COSMETIC
- **What happened:** A 990,000-character body to `/embed` returned 422 naming the 2048-character
  limit but echoed the entire 990,000-character input back, producing a 990,149-byte response.
- **Exact command:**

  ```text
  date -u +%Y-%m-%dT%H:%M:%SZ; jq -nc '{text: ("a" * 990000)}' | curl -sS -i --max-time 20 -X POST 'http://lemondrop-dev-alb-285677848.eu-west-1.elb.amazonaws.com/embed' -H 'Content-Type: application/json' --data-binary @- -w '\nELAPSED:%{time_total}\n'
  ```

- **Verbatim response (summary):**

  ```http
  HTTP/1.1 422 Unprocessable Entity
  Date: Wed, 21 Oct 2026 21:18:56 GMT
  Content-Type: application/json
  Content-Length: 990149
  Connection: keep-alive
  server: uvicorn

  {"detail":[{"type":"string_too_long","loc":["body","text"],"msg":"String should have at most 2048 characters","input":"aaaa…[990,000 'a' characters, verbatim in capture]…aaaa","ctx":{"max_length":2048}}]}
  ```

- **Expected behaviour per `client.md` §3:** 422 naming the field and limit is expected; the full
  input echo is not.
- **Consequence for acceptance:** The error handler acts as a reflection amplifier (~1:1 response
  amplification).

#### E1/E2 — `/embed` 502 on low-density 2047/2048-character input

- **Severity:** MINOR
- **What happened:** `/embed` with 2047 or 2048 low-density characters (`'a' * 2048`) returned
  502 `{"detail":"embedder returned HTTP 500"}`; the same length in realistic prose returned 200.
- **Expected behaviour per `client.md`:** Valid length requests should succeed.
- **Consequence for acceptance:** This is the **documented residual** observed live. The
  2048-character guard is a character-count proxy for the worker's 512-token ceiling, not a hard
  invariant, and `client.md` §3 already describes this residual. It is recorded here as a
  confirmation, not a new defect.

#### A11 — Unknown request fields are silently ignored

- **What happened:** Extra fields (`admin`, `role`, `__proto__`) in a `POST /search` body were
  silently ignored; no privilege effect was observable.
- **This is NOT booked as a defect.** It was already investigated and classified as standard
  behaviour: Pydantic v2 defaults to `extra='ignore'`
  (`~/lemondrop-investigation/CONSOLIDATED-INVESTIGATION.md` FP-02, lines 152–153). It is recorded
  here as an observation consistent with that adjudication.

#### DEP — `pydantic` is imported directly but not pinned in `api/requirements.txt`

- **Severity:** OBSERVATION — not a runtime defect, a dependency-hygiene gap.
- **What was found:** `api/app/main.py` imports `pydantic` directly (`from pydantic import
  AfterValidator, BaseModel, Field, StringConstraints` at `:40`, and uses `StringConstraints`
  at `:150-157`), but `api/requirements.txt` does not list `pydantic`. It arrives transitively
  via `fastapi==0.143.0`. That contradicts `api/requirements.txt`'s own rule: "Exact pins, no ranges"
  and "Every dependency below — and every transitive dependency they pull — ships a prebuilt
  wheel..." A direct import of a package that is not explicitly pinned means a future FastAPI
  version could change the transitive pydantic version without this file recording the intent.
- **Why this is NOT fixed in this pass:** Changing the dependency set would desynchronise the
  repository from the deployed image's provenance. The image deployed before this release
  (`sha256:8cf759f6…`) was built from the current `api/requirements.txt`, and adding or pinning
  `pydantic` here would make the source record diverge from that image. A dependency change
  requires a release decision, a new image build, and a new deployment record — all out of scope
  for this documentation-only correction pass.
- **Operational note:** the AWS `[default]` login session expired on 2026-10-17 and is
  unrecoverable without an interactive `aws login`. Every AWS call in this release used
  `AWS_PROFILE=lemondrop` (static-key profile); that profile works
  (`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §AWS_ACCESS).
- **Consequence for acceptance:** Recorded as a finding for the next release cycle. No acceptance
  verdict is changed by this observation.
- **2026-10-21 addition — pydantic strip-order analysis (from the independent review of the E5
  fix, verdict PASS_WITH_FINDINGS).** The review transcript is not a retained artefact in the
  published repository; the strip-order property is grounded in the measurement captured in
  `/home/zaratustra0/lemondrop-investigation/POST-FIX-FULL-SUITE-EVIDENCE.txt` Capture 3
  (pydantic 2.14.1; the evidence corpus lives outside the repository by project convention).
  The boundary safety of the E5 fix does not depend on pydantic's strip ordering: an accepted
  input cannot exceed the worker 2048-character budget under either ordering. Measured
  behaviour of the installed pydantic: it **strips BEFORE the length checks** — a raw
  **1992**-character input of which **1** character is trailing whitespace is accepted, stored
  as 1991, and forwarded as `QUERY_PREFIX + 1991` = 2048, which is exactly inside the worker
  budget (`/home/zaratustra0/lemondrop-investigation/POST-FIX-FULL-SUITE-EVIDENCE.txt` Capture 3,
  `trailing-whitespace N+1`). Under the opposite ordering (length check on the
  unstripped string) the behaviour would be stricter, not looser; under NEITHER ordering can an
  accepted input exceed the worker budget. The old code path was byte-identical in what it
  forwarded: constructing the old `EmbedRequest` re-stripped an already-stripped string, a no-op.
  **This analysis narrows the E5 fix's residual risk but does NOT close this finding:** the DEP
  finding stays OPEN — the pydantic version remains unpinned in `api/requirements.txt` while
  `main.py` imports it directly, against that file's own "Exact pins, no ranges" rule. Pinning is
  a RELEASE decision that changes the dependency set relative to the deployed image's provenance,
  so it is carried to the operator, not applied here.

### What was NOT captured

The 2026-10-21 session explicitly did not capture the per-hop evidence that would
turn the `/search` demonstration into a full end-to-end walkthrough. The
2026-10-22 post-release walkthrough captured the host-side `api`, `embedder` and
`reranker` container logs over the same UTC window; the following remain
unrecorded:

- A read of the RDS `postgresql` log for the request window — the exported log
  held only periodic checkpoints.
- ALB access logs — they are OFF by design and were not enabled.
- A second predicted-before-execution test under the `M5-001` convention by the
  operator (the operator's own prediction remains outstanding).
- Evidence retained in a checksummed directory per the `M5-001` convention.

### Evidence source

- `~/lemondrop-investigation/CLIENT-PERSPECTIVE-EVIDENCE.md` (2026-10-21 session).
- `~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` (2026-10-22 deploy and
  boundary proof).
- `~/lemondrop-investigation/POST-RELEASE-WALKTHROUGH-EVIDENCE.txt`
  (2026-10-22 walkthrough and per-hop correlation).

### Static documentation audit — 2026-10-21

A parallel static documentation audit was completed on 2026-10-21. Its artefact
is `/home/zaratustra0/lemondrop-investigation/README-RUNBOOK-AUDIT.md`.

**Scope and counts.** The audit checked `README.md`, `RUNBOOK.md`, `COSTS.md` and
`docs/end-to-end-demo.md` claim by claim against the repository at HEAD
(`3e298f83906fa1c17e3e19f778f11fd2868c93c1`) and against the evidence corpus in
`/home/zaratustra0/lemondrop-investigation/`.

| Result | Count |
|---|---|
| MATCH | 74 |
| PARTIAL | 6 |
| MISMATCH | 13 |
| NOT-CHECKABLE-STATICALLY | 6 |
| **Total** | **99** |

All 13 mismatches were corrected:

| ID | Document | Original claim | Correction |
|---|---|---|---|
| A19 (D6) | `README.md` | "These are the live-stack (T3) tests" | Reworded to "six of the live-stack (T3) tests … subset of the 28-test T3 tier". |
| C03 (D7a) | `COSTS.md` | `infra/variables.tf:259-262` for `app_instance_type` | `:259-262` |
| C04 (D7b) | `COSTS.md` | `infra/variables.tf:522-525` for `app_root_volume_size` | `:522-525` |
| C11 (D7c) | `COSTS.md` | `infra/variables.tf:781-784` for `db_skip_final_snapshot` | `:781-784` |
| C14 (D7d) | `COSTS.md` | `infra/variables.tf:751-754` for `db_deletion_protection` | `:751-754` |
| C15 (D7e) | `COSTS.md` | `infra/variables.tf:873-876` for `lb_enable_deletion_protection` | `:873-876` |
| B17 (D8a) | `RUNBOOK.md` | `infra/variables.tf:781` for `db_skip_final_snapshot` | `:781` |
| B22 (D8b) | `RUNBOOK.md` | `infra/variables.tf:751-754` for `db_deletion_protection` | `:751-754` |
| B23 (D8c) | `RUNBOOK.md` | `infra/variables.tf:873-876` for `lb_enable_deletion_protection` | `:873-876` |
| D07 (D9) | `docs/end-to-end-demo.md` | `infra/variables.tf:912-915` for `lb_access_logs_enabled` | `:912-915` |
| C17 (D11) | `COSTS.md` | "roughly 1.6 months" of credit coverage | "roughly 1.5 months" |
| B08 (new) | `RUNBOOK.md` | S3 backend argument `use_locking = true` | `use_lockfile = true` (`infra/versions.tf:50`) |
| D05 (new) | `docs/end-to-end-demo.md` | `docker-compose.yml:152-158` for `json-file` rotation | `:161-167` |

The `variables.tf` citations above are the committed-file line numbers; the
operator's uncommitted tester-access proposal adds 48 lines in the working tree,
so the same variables appear 48 lines lower there.

**The three limits of this audit**, reproduced from the artefact:

1. "This is a STATIC audit of documentation against the repository." It checks
   what the documents say against what the files contain.
2. "It is NOT a clean-host reproduction of the README." No clean machine was
   provisioned, no `.env` was created, no image was pulled, no service was
   started.
3. "It is NOT an end-to-end execution of any command." `docker`,
   `docker compose`, `terraform`, `aws`, `psql`, `ssh`, `curl`, the test harness
   and `pytest` were all left unrun. A command that is documented and
   syntactically sound is recorded as such; it is not recorded as working.

**Claims that remain unverified by this method**, and why:

- Docker Desktop/WSL and Compose-version host facts (`README.md` A12) — host
  facts; no version pin or host probe in the repository.
- "Models take roughly 30–60 seconds to load" (`README.md` A15) — runtime
  timing; no retained measurement in the corpus.
- `python3 -m venv` / `ensurepip` behaviour (`README.md` A20) —
  distribution-dependent OS behaviour.
- Per-resource dollar estimates and the `~$82/mo` total (`COSTS.md` C02) — no
  bill has been read; the observed column is empty.
- `$120` credit and April 4 2027 expiry (`COSTS.md` C06) — external billing
  fact; no billing artefact in the corpus.
- AWS stop/destroy billing semantics (`COSTS.md` C09) — AWS-engine behaviour,
  not repository state.
- The `lemondrop` AWS CLI profile (`RUNBOOK.md` B01) — operator host
  configuration.
- SSM / AWS command effects (`RUNBOOK.md` B12, B13, B20) — syntax checked;
  effects require AWS, which this audit did not call.
- The deployed corpus path `/opt/lemondrop/data/corpus.json`
  (`docs/end-to-end-demo.md` D02) — the repository holds `data/corpus.json`;
  the host path was not inspected.
- The future hop-by-hop recording plan (`docs/end-to-end-demo.md` D04) — a
  plan, not an executed recording.
- The README "all passing against the running stack" claim (`README.md` A19) —
  corroborated by `LOCAL-VERIFICATION-REPORT.md:18` (T3 28/28), but not
  re-executed here.

This audit does **not** establish that the stack runs, that the README quick
start succeeds on a fresh host, that the RUNBOOK's recovery commands recover
anything, or that any documented command was executed.

### Open item — `infra/variables.tf` llama.cpp truncation note

The operator's uncommitted working copy of `infra/variables.tf` (lines 442–449)
rewrites the `--ctx-size` note from "llama.cpp TRUNCATES over-long input" to
"does NOT silently truncate over-long input: it rejects it". The committed HEAD
version (line 394) still says TRUNCATES, which disagrees with
`api/app/main.py:112` ("any input above 512 tokens is REJECTED by the worker,
not truncated"). This is a remediation correction riding in the operator's file,
not operator work; it is the operator's decision whether to commit their file or
have the correction re-applied to the committed state.
