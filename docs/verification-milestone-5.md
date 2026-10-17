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

One row. It is the only functional test executed and recorded so far; no other
request has been made and none is implied.

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
| a | Git repo with app / Terraform / Docker / tests / automation | **PRESENT.** The working directory is a Git repository; `api/`, `infra/`, `docker-compose.yml`, `scripts/`, `models/` and `.github/workflows/` are all present. |
| b | Architecture diagram (networks, routing, ports, security groups, dependencies) | **EXISTS — `docs/architecture.md`; appears to satisfy the requirement.** It carries §1 network topology (a mermaid diagram of subnets, route tables, NAT/IGW), §2 ports, §3 the security-group matrix, §4 request flow, §6 egress, and §7 service dependencies, each grounded in a `file:line`. **Note:** the file is currently **untracked** (`?? docs/architecture.md`). |
| c | Reproducible README | **EXISTS — `README.md`; AUDIT PENDING.** Present, and currently **modified in the working tree**. Its reproducibility has not been audited against a clean host. |
| d | Operational RUNBOOK | **EXISTS — `RUNBOOK.md`; AUDIT PENDING.** Present, and currently **modified in the working tree**. Not audited end to end. |
| e | Timestamped investigations in `INCIDENTS.md` | **0 of 3.** The three category sections exist and are EMPTY. |
| f | `COSTS.md` — expected **and** observed | **Expected: PRESENT. Observed: EMPTY.** The expected table is populated; the Observed column reads `NOT YET OBSERVED` on every line — no bill has been read. |
| g | End-to-end ALB → app → PostgreSQL → response walkthrough | **PLANNED, NOT RECORDED.** `docs/end-to-end-demo.md` exists as a *plan* — it states what will be captured and which sources need enabling — but the walkthrough itself has not been recorded. |
| h | Verified teardown preserving Git evidence | **NOT DONE.** No teardown has been performed or verified in this milestone. |

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
