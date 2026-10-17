# Ch21 — The Five Acceptance Criteria, and the Evidence Behind Each

## What this chapter is for

A milestone is not "done". It is **done against a list**, and the list was written down
before the work started so that finishing could be recognised rather than declared. This
chapter takes Milestone 3's list item by item, shows exactly what was run, and — just as
importantly — shows what each piece of evidence **does not** cover.

Three tags are used throughout, and they are not decoration:

- **[VERIFIED]** — a named check was run and its result is recorded in
  `docs/verification-milestone-3.md`, with a citation.
- **[PARTIAL]** — something was measured, but the measurement does not reach as far as the
  claim it is being used to support. The boundary is stated every time.
- **[UNTESTED]** — never measured. No number exists.

If a claim carries no tag, treat it as **[UNTESTED]** — an untagged claim in a document
that uses tags is a gap in the writing, not a licence for the claim.

---

## 1. Where the criteria come from

The five criteria were set out in `verification-milestone-3.md` §6, alongside two supporting
infrastructure criteria:

| # | Criterion | Supporting criterion |
|---|---|---|
| 1 | Ingestion of the corpus | 6 — `GET /health/live` returns 200 |
| 2 | Semantic search returns relevant results | 7 — `GET /health/ready` returns 200 with `database`, `embedder`, `reranker` all `ok` |
| 3 | Reranking applied | |
| 4 | Persistence across container restart | |
| 5 | Collection isolation (canary pairs never cross) | |

**A word about history, because it is a teaching point and not housekeeping.** The §6 table
reads row 4 as **UNTESTED**, and §6.2 ends with *"Row 4 stays **UNTESTED**. It is the next
task."* Both were true when written and both are **still there, deliberately** (§6.3,
§6.2). The record is appended to, never rewritten. When the answer moved, a supersede banner
was added pointing at the current answer (§9.8, then §9.9, then §12.5). This is deliberate:
silently editing an `UNTESTED` into a `VERIFIED` would destroy the only trace that the
question was ever open, and a record where nothing was ever open teaches a reader that the
whole document is a list of confirmations.

The current table is **§12.5**, and it has two columns: local and **cloud**.

---

## 2. The headline result

**All five acceptance criteria are VERIFIED in the cloud environment, on a live `t3.small`
behind a public ALB, against RDS.** [VERIFIED §12.5]

The qualifier that matters as much: **six of the eight items in the "what is not verified"
list are still open** [VERIFIED §12.4]. A milestone can pass its acceptance criteria and
still be unmeasured in six important ways. Those are different statements and this chapter
keeps them apart.

---

## 3. The evidence set, row by row

This is the complete cloud acceptance evidence, reproduced from §12.1 and §12.1.1. **Every
row was executed and reported by the operator.** The agent that wrote the verification record
ran no AWS command and is not claiming to (§12, opening paragraph). That provenance statement
is load-bearing: a row recorded as if the agent had run it would be a fabricated claim wearing
a real one's clothes (§ opening note).

### 3.1 The twelve primary rows (§12.1)

| # | Item | Result as reported | Verdict |
|---|---|---|---|
| 1 | Instance size and identity after the resize | **`t3.small` running, and the EC2 instance ID is UNCHANGED** from before the resize | **VERIFIED** |
| 2 | Container health | **All three containers healthy** | **VERIFIED** |
| 3 | Reranker serving state | Reranker reports **`n_slots = 1`** | **VERIFIED** |
| 4 | Ingestion of the corpus on RDS | **40 of 40 documents ingested, zero failures** | **VERIFIED** |
| 5 | Cloud `POST /search` | **10 candidates returned, 5 results** | **VERIFIED** |
| 6 | Ranking, `infrastructure` | **Correct top documents** | **VERIFIED** |
| 7 | Ranking, `it-support` | **Correct top documents** | **VERIFIED** |
| 8 | Collection isolation on the response | **Isolation passes for both collections** | **VERIFIED** |
| 9 | Persistence across restart | **Search survived an API container restart** | **VERIFIED** — qualified, see §5.1 |
| 10 | No new OOM | **No new kernel OOM event within the verified search window** | **VERIFIED (bounded)** |
| 11 | Public ALB `GET /health/ready` | **HTTP 200** | **VERIFIED** |
| 12 | Public ALB `POST /search` | **HTTP 200 in 15.55 seconds** | **VERIFIED** — one sample only |

### 3.2 The final independent pass (§12.1.1)

These are a **separate, later, read-only** set of checks, run independently of the twelve
above. They are recorded as their own rows because they close items §12.4 had carried as
open — Terraform reconciliation and the instance-role negative control in particular.

| # | Item | Result as reported | Verdict |
|---|---|---|---|
| 13 | RDS corpus counts, read-only | **`infrastructure` 20, `it-support` 20, total 40** | **PASS** |
| 14 | Adversarial canary count | **10 canaries** | **RECORDED** |
| 15 | pgvector version on RDS | **0.8.1** | **RECORDED** |
| 16 | Connection identity | Authenticated as **`lemondrop_app` — NOT the RDS master user** | **PASS** |
| 17 | RDS COUNTS overall | **PASS** | **PASS** |
| 18 | Instance-role access to the RDS-managed master secret | **DENIED** | **PASS** |
| 19 | Canaries through the public ALB | **10 of 10 passed, in BOTH directions** | **PASS** |
| 20 | Terraform state reconciliation | **No changes, exit 0** | **VERIFIED** |

Three of those rows need explaining before the table means anything, because the raw words
are ambiguous and the meanings are opposite.

**Row 18 — why `DENIED` is a control and not a lucky error code.** The operator recorded
three things, and all three are load-bearing:

| Aspect | What was recorded |
|---|---|
| How the secret was identified | The master-secret ARN was **read from `DBInstances[0].MasterUserSecret.SecretArn`** — **not hand-written** |
| What was returned | A genuine **`AccessDeniedException`** — **not** a `ResourceNotFoundException` |
| Credential hygiene | **stderr captured; stdout discarded**, so no credential could reach the transcript |

`AccessDeniedException` means *the IAM policy refused a caller who identified the secret
correctly*: the ARN resolved, the secret exists, policy said no. `ResourceNotFoundException`
would mean *the path never resolved* — wrong ARN, different visibility, or the call never got
far enough to be refused. **That would not have been a pass.** It would have been a check that
failed to run while wearing the costume of one. Ch22 is entirely about how to tell those two
apart; here it is enough to say the distinction is why the row exists in that form.

**Row 19 — "both directions" is a real claim.** Isolation was run scoped to
`infrastructure` (asserting no `support-*` twin appears) **and** scoped to `it-support`
(asserting no `infra-*` twin appears). One direction is a lucky accident of the corpus; both
directions is a property of the code.

**Row 20 — what was actually run.** A read-only `terraform plan -detailed-exitcode`.
`-detailed-exitcode` returns **0 for no changes** and **2 for changes present**, so the exit
status *is* the result and has to be quoted rather than eyeballed. The row records exit 0,
i.e. no changes. **No apply was run to satisfy this item, and none should be**
(§12.1.1 row 20 note).

### 3.3 How rows 13–18 reached RDS without a public database

These checks did not go over a public path. They came through an **SSM port-forward
tunnel** (`AWS-StartPortForwardingSessionToRemoteHost`), and the connection used a **split
`host` / `hostaddr`**:

| Parameter | Value | Why it is that |
|---|---|---|
| `host` | the **RDS endpoint** | the name the **TLS certificate is verified against** |
| `hostaddr` | **`127.0.0.1`**, `port=15432` | the **forwarded local socket** the traffic actually rides |
| `sslmode` | **`verify-full`** | full chain **and** hostname verification |

Pointing `host` at `127.0.0.1` would make `verify-full` verify the certificate against
`127.0.0.1`, which either fails outright or — worse — gets "fixed" by loosening the check
until it passes. Splitting the two keeps **certificate verification meaningful through a
tunnel**: the bytes travel over the loopback forward, the name being verified stays the real
endpoint. Lab 5 in Ch27 walks this in detail.

---

## 4. Each criterion, and how it was proven

### Criterion 1 — Ingestion of the corpus

**Status: VERIFIED (local) and VERIFIED (cloud).** [VERIFIED §12.5 row 1]

- **Cloud:** 40 of 40 ingested against RDS, zero failures reported (§12.1 row 4).
- **Local:** the loader run reported **40/40 stored, 0 failed**, and PostgreSQL
  *independently* confirmed `infrastructure` = 20, `it-support` = 20 at `psql` (§5.2 rows 1–2).
- **Cloud, independently:** 20 / 20 / 40 read back through the tunnel (§12.1.1 row 13).

**Why the row counts are the interesting part.** "The loader ran and reported 40" is a claim
about a *script's own summary*. "20 infrastructure and 20 it-support read back at `psql`" is a
claim about the **database**, confirmed by something that is not the thing that wrote the
rows. The loader itself is verified to exit non-zero on any per-document failure
(`scripts/load_corpus.py` returns 1 and `sys.exit(main())` when `failures` is non-empty —
§5.2 row 3), so a cheerful summary cannot hide a dropped document — but the independent count
is what makes it a *number* rather than a *report*.

**The qualification that survives.** The **schema work itself** — the Alembic migration — was
applied to the local dev database, not to RDS: §2 row 8 recorded the migration target
resolving to `127.0.0.1:5432/lemondrop`, and §12.5 row 1 keeps that qualification visible.
§12.1 row 4 covers the RDS side by observing 40 documents present there. Migration execution
against RDS is not separately recorded as an executed check. **[PARTIAL]**

### Criterion 2 — Semantic search returns relevant results

**Status: VERIFIED (local) and VERIFIED (cloud).** [VERIFIED §12.5 row 2]

- **Cloud:** 10 candidates in, 5 results out; both collections return the correct top
  documents (§12.1 rows 5, 6, 7).
- **Local, and much more precisely:** a query about recovering files from a user's Recycle
  Bin, scoped to `it-support`, ranked **`support-recycle-bin-file-recovery` first**; 10
  candidates considered, 5 returned; all 5 in `it-support`; both `relevance_score` and
  `distance` present on every result (§8.2 rows 1–4).

**Read the note attached to the cloud rows.** The operator reported that the searches "return
the correct top documents". **The specific document ids ranked first on AWS were not
reported**, and the record does not invent them. §8.4 names ids for the *local* run; those are
local results and are **not restated as cloud results** (§12.1.1 closing note on rows 6–8).

That is an important asymmetry to hold in your head: the local evidence is *stronger and more
specific*; the cloud evidence is *confirmed but coarser*. The cloud rows are not a
reproduction of the local rows. They are a different body of evidence about the same criterion,
and §12.5 says exactly that — "The cloud rows and the local rows are different evidence about
the same five criteria, and this document now holds both."

### Criterion 3 — Reranking applied

**Status: VERIFIED (local) and VERIFIED (cloud).** [VERIFIED §12.5 row 3]

- **Cloud:** the funnel shape holds (10 → 5) and the reranker reports `n_slots = 1`
  (§12.1 rows 3, 5).
- **Local:** a real search over HTTP, against the real `bge-reranker-base` worker, with a
  named document ranked first (§8.2).

**The explicit boundary, stated by the record itself:** *"The cross-encoder scores themselves
were not reported and are not claimed."* [VERIFIED §12.5 row 3]

What this means precisely: the cloud run proves the reranker was reached, that it returned
the configured number of results, and that the worker came up with one inference slot. It does
**not** independently report a `relevance_score` value from the cloud run. The funnel shape is
carried by the count, and the count is carried by the code path — `main.search` cannot produce
five results without calling `rerank()` at `main.py:1459`.

### Criterion 4 — Persistence across container restart

**Status: VERIFIED (cloud) — with the qualification below.** [VERIFIED §12.5 row 4]

- **Cloud:** search survived an API container restart (§12.1 row 9).
- **Local, and stronger:** the operator restarted the API **and** PostgreSQL **separately**,
  waiting for a healthy status at each step rather than tearing the stack down. Two
  independent restarts, so the API's restart could not have been what carried the database
  through. 40 documents present (20/20), a real `POST /search` afterwards returning 10 → 5,
  `support-recycle-bin-file-recovery` ranked first again, every result in `it-support`
  (§9.2 rows 1–4).

**The boundary — [PARTIAL]. This is the single most misreadable row in the table.**

> *"Verified via an API CONTAINER restart, not an EC2 reboot."* (§12.5 row 4)

A container restart re-creates the container's writable layer. It does **not** reboot the
host, re-run `user_data`, re-clone the repository, or re-download the model weights. An EC2
reboot *is* what would exercise the boot path, and §12.4 item 5 records that a clean
destroy/rebuild has never been exercised end to end. Neither the local test nor the cloud test
is an instance reboot, and the record says so in the table itself rather than in a footnote.

**What data survived, and why.** Data lives in the named `pgdata` volume — locally — and in
**RDS**, not in a container filesystem. The compose `down -v` path was **deliberately not
used**: `-v` removes named volumes, which would have destroyed the data along with the test and
measured volume deletion rather than persistence (§9.5). "We restarted and the data was still
there" is a very different claim depending on which of those two commands was run.

**A further gap, recorded because it is cheap to close.** Three of four schema facts —
the pgvector extension, `documents_collection_idx`, and the `documents_set_updated_at`
trigger — were verified *before* a restart and were **not re-confirmed after one** (§9.6).
The inference that named-volume semantics make them safe is sound, but it is **an argument,
not an observation**, and the record does not claim it as a check.

**And the mechanism was not established either.** The search succeeded on the first attempt
after the restart. §9.3 lists three explanations that all fit that observation — `pool_pre_ping`
discarding a stale connection, the pool simply holding no idle connection at that moment, or
plain timing — and records the **negative control that was not run**: disable `pool_pre_ping`,
restart the database, observe the difference. Until that runs, `pool_pre_ping` is the
*intended* mechanism and the test is *consistent with* it. Weaker, and the only one the
evidence carries.

### Criterion 5 — Collection isolation (canary pairs never cross)

**Status: VERIFIED (local) and VERIFIED (cloud).** [VERIFIED §12.5 row 5]

- **Cloud:** isolation passes for both collections, judged on what the caller receives
  (§12.1 row 8); 10 of 10 canaries passed through the public ALB, in **both directions**
  (§12.1.1 row 19).
- **Local, and this is where the real proof lives:** §8.4 measured it on the live corpus,
  §8.5 **proved the test discriminates by mutation**.

**The measurement (§8.4).** Scoped to `infrastructure`: **10 candidates, all 10 in
`infrastructure`**, and the `it-support` twin of the canary pair never appears. The same query
run **globally**, with no collection predicate: the twin **`support-service-account-password-rotation`
ranks #2 overall**, distance **0.3018**, behind only its infrastructure counterpart
`infra-aws-iam-key-rotation` at **0.2071**. And: **only 7 of the global top 10 are
`infrastructure`.**

**The mutation proof (§8.5).** The original isolation test used a query vector sharing a seed
with a fixture (`_vector(1)`, the same seed as `alpha-0`). All three of the global top-3 were
collection A's, so **a fetch-then-filter implementation returned all three and the test
PASSED against the broken code**. The implementation was rewritten into
global-top-N-then-filter-in-Python and the test was run against it:

| Run | Result |
|---|---|
| Old seed **+** post-filter mutation | **PASSED** — the test was blind to the defect it existed to catch |
| New seed (`_vector(104)`, one of B's own seeds) **+** post-filter mutation | **FAILED: `assert 2 == 3`** |
| `api/app/store.py` restored | **Byte-identical** to its pre-mutation state |

A control assertion now runs on **every execution**, so the test proves itself armed rather
than relying on a reader having done the arithmetic
(`api/tests/test_documents.py::test_retrieve_returns_only_documents_from_the_asked_collection`).

**Why "the `WHERE` clause is doing two jobs" is the most useful sentence in §8.4.** It is not
only excluding the twin that would otherwise be reranked into the top 5. It is also
**recovering three `infrastructure` documents a fetch-then-filter would have silently
discarded** — a global top-10 contains only 7 infrastructure rows, so post-filtering returns
7, not 10, and the three lost are the ones the *global* metric judged least similar.

That second job **fails silently**. A leaked filter is loud: a foreign document in the
response, caught by any isolation assertion. A **starved** filter is silent — correct
documents, correct collection, fewer of them, HTTP 200, and a retrieval system that gets
steadily worse as the corpus grows while every isolation test stays green.

**The boundary — [PARTIAL], and it is a split boundary.** On AWS, isolation is verified **at
the response level**: what the caller receives. The **SQL-level mechanism** underneath it —
that the predicate is in the `WHERE` clause, proven by mutating `store.retrieve` into
fetch-then-filter and watching the test fail — is a **local** result and is *not* restated as a
cloud result (§12.5 row 5, verbatim).

Both halves matter and they prove different things. The mutation proof shows the *mechanism*
is load-bearing. The cloud run shows the *behaviour* is correct in the deployed environment.
Neither substitutes for the other.

---

## 5. The boundaries, stated plainly

This section is the point of the chapter. A milestone that presents only its green rows is
worse than one that never ran.

### 5.1 Persistence: proven across a container restart, not an EC2 reboot — **[PARTIAL]**

Covered above in Criterion 4. The single sentence to remember: *a container restart re-creates
a writable layer; it does not re-run the boot path.* Persistence is proven for the container.
It is **[UNTESTED]** for the host.

### 5.2 Isolation: proven at the response boundary on AWS, at the SQL mechanism locally — **[PARTIAL]**

Covered above in Criterion 5. Response-level proof in the deployed environment; mechanism-level
proof by mutation in the local environment. Neither is restated as the other.

### 5.3 Latency: one observation, no distribution — **[PARTIAL]**

§12.1 row 12 records **15.55 seconds** for a `POST /search` through the ALB. §12.1.1 states
this in the only way it should be stated:

> *15.55s is a SINGLE OBSERVATION, not a latency distribution.* One request, one result, on a
> shared host that was not under concurrent load. It is not a mean, not a median, not a p95,
> not an SLO, and it must not be quoted as one.

§8.6's distribution (two runs of five samples: min 8.191s / median 11.409s / max 12.996s;
min 9.354s / median 12.466s / max 13.214s) is real evidence of a distribution — but it was
measured **on the developer's host, not on EC2**, and §8.7 says so three times. §12.1's single
sample is **not** a margin measurement; §12.4 item 4 answers that question with "not
answered", and **no 3-run latency distribution was measured on the cloud**.

For comparison: the one measured distribution is a **5-sample spread of 4.8s between min and
max** — larger than most of the gap between a fast run and a slow one. This is why the local
test asserts no latency bound at all and reports its distribution instead (§8.6 row 3). A tight
threshold on a shared host is a flaky test that teaches the team to ignore it.

### 5.4 The corpus is synthetic — **[UNTESTED] against real data**

`data/corpus.json` was **generated for Milestone 3 by this project**. It was not supplied by
the operator, not sourced from a third party, and is not real-world documentation. A full
search of the repository found no `data/`, `datasets/`, `runbooks/` or `corpus/` directory and
no corpus file of any kind; the operator was told this and decided we generate one instead
(§1). The file carries `"synthetic": true` and a `generation_note` saying so.

Consequence: **every retrieval measurement in this milestone is a measurement on a corpus of
known shape**, not on anything a real user would search. §1 makes one further point worth
keeping — *nothing downstream depends on its contents, only its shape*, so a real dataset can
replace it without touching code outside `data/`. `data/README.md` §"Replacing this with an
official dataset" gives the four-step procedure and says, bluntly: *if the official dataset has
no isolation canaries, either drop the canary tests or add equivalent cross-collection
near-duplicates deliberately. Do not remove the test and silently lose the isolation
guarantee.*

### 5.5 The rest of the open list, in one place

| Item | Status | Where |
|---|---|---|
| Sustained and concurrent load | **STILL OUTSTANDING** — no load profile, no concurrency measurement, no soak | §12.4 item 2 |
| CPU credit exhaustion on `t3` | **STILL OUTSTANDING — unmeasured at any size** | §12.4 item 3 |
| ALB headroom / the timeout mismatch | **STILL OUTSTANDING — a known configuration defect** | §12.4 item 4 |
| Clean destroy/rebuild reproducibility | **STILL OUTSTANDING** — carried forward from Milestone 2 | §12.4 item 5 |
| The corpus is synthetic | **STILL OUTSTANDING** | §12.4 item 6 |
| Python version skew (3.14.4 local vs 3.12 image) | **STILL OUTSTANDING** | §12.4 item 8 |
| Terraform state reconciliation | **RESOLVED** — no changes, exit 0 | §12.1 row 20 |
| The §11.4 instance-role negative control | **RESOLVED — DEMONSTRATED** | §12.1 rows 16, 18 |

Two of those deserve a sentence each.

**CPU credits.** `t3` is burstable; sustained cross-encoder scoring is a sustained load. The
failure mode when credits deplete is throttling or degraded rerank latency, which looks like
*"search got slow"* rather than *"search is broken"* — a harder failure to diagnose later. The
record's summary is worth quoting: **`t3.small` should make retrieval WORK; it does not make
the architecture right.** (§12.4 item 3)

**The ALB timeout defect — the most urgent open item.** `INFERENCE_TIMEOUT_SECONDS = 120.0`
(`main.py:106`) is a **per-call** budget applied inside `_post_upstream` (`main.py:547`).
`/search` calls that helper **twice, sequentially** — embed at `main.py:1381`, then rerank at
`main.py:1459`. So the **worst-case request time is ~240s** (120 + 120) against an ALB
`lb_idle_timeout` of **60s** (`infra/variables.tf:890-891`, applied at
`infra/load_balancer.tf:67`). **The ALB times out before the API does.**

The per-call framing is why the arithmetic is invisible from the constant alone: `120.0` reads
like a request budget and is not one. Two sequential calls each get the full 120s. §10.8 calls
this *deliberately deferred* — raising `lb_idle_timeout` without a latency measurement would be
tuning against a guess. §12.4 item 4 keeps it open, and calls it an **unaddressed known
configuration defect**. Ch30 takes this up as the most urgent thing in the backlog.

### 5.6 What the open list is not

The open items are **not** defects in what was built. They are questions that were never asked,
recorded as open so nobody has to guess whether they were considered. §12.4's own framing is
worth repeating as a habit: *nothing was deleted to make this list look shorter — a reader needs
to see what was open, what closed it, and when, or the list is worthless.*

---

## 6. A worked example: reading one row carefully

Row 18 reads **"DENIED"**. Here is the difference between a reader who has learned to read
evidence and a reader who has learned to read words.

| Reader | Conclusion | Why it is right or wrong |
|---|---|---|
| Reads the word | "The instance role can't read the master secret. Least privilege works." | **Right conclusion, unsupported reasoning.** The same word would appear if the ARN were mistyped and the call returned "not found". |
| Reads the row | "The ARN was read from `DBInstances[0].MasterUserSecret.SecretArn`, so the caller identified the right secret. The refusal was `AccessDeniedException`, meaning the policy — not the path — said no. stdout was discarded, so no credential reached the transcript." | **A demonstration.** Every step that could have failed silently is named and shown to have worked. |

The first reader cannot tell a control from a typo. The second can, because the record was
written so that they could. That is a property of the *record*, not of the reader — and it is
the whole argument of Ch22.

---

## 7. Three things to carry forward

1. **Two columns, not one.** §12.5 holds local *and* cloud verdicts side by side, because they
   are different evidence. The cloud rows are coarser; the local rows name specific documents.
   Neither replaces the other.
2. **A bounded claim is still a claim.** Row 10's verdict is **"VERIFIED (bounded)"** — no new
   OOM **within the verified search window**, and **the length of that window was not
   reported**. The word doing the work is *window*. It bounds the claim to the searches that
   were actually run; it is not a claim that the memory problem is closed.
3. **A supersede note is a feature.** When §9.8's "nothing verified on AWS" row became wrong,
   it was left in place with a banner rather than edited. Ch30 explains why this matters when
   you inherit the repository: the sections that have been superseded are usually the ones a
   hurried reader lands on first.

---

**Key terms:** acceptance criteria · provenance (operator-executed vs agent-executed) ·
supersede banner · isolation canary · fetch-then-filter · cross-encoder · `n_slots` ·
least-privilege negative control · `AccessDeniedException` · SSM port-forward tunnel ·
`host`/`hostaddr` split · load balancer idle timeout · cgroup OOM kill · blame-free supersession

**Recall questions** (answers below — cover the answer column and say it out loud before
checking):

1. **Why does §6 still read `UNTESTED` for criterion 4 when §12.5 reads VERIFIED?**
   *Because the record is appended to, never rewritten. §6.3 and §6.2 are preserved exactly
   as written and a supersede banner points at §9.8 and then §12.5. The change in verdict is
   itself the finding; editing the old row would destroy the only trace that the question was
   ever open.*

2. **A search through the ALB returns 200 in 15.55 seconds. What does that establish, and
   what does it not?**
   *That one request succeeded in 15.55s on an unloaded host. It is a single observation, not
   a distribution — not a mean, median, p95 or SLO — and not a margin measurement against the
   60s ALB idle timeout. No multi-run latency distribution has been taken on the cloud.*

3. **Why is cloud isolation evidence [PARTIAL] rather than VERIFIED outright?**
   *Because the two halves were measured in different places. On AWS, isolation is verified at
   the RESPONSE level — what the caller receives. The SQL-level mechanism underneath it, proven
   by mutating `store.retrieve` into fetch-then-filter and watching the test fail with
   `assert 2 == 3`, is a LOCAL result and is not restated as a cloud one.*

4. **What made the original isolation test blind, and what fixed it?**
   *Its query vector shared seed `_vector(1)` with a fixture, so all three of the global top-3
   were collection A's and a fetch-then-filter returned all three — passing against the broken
   code. The seed changed to `_vector(104)`, and a control assertion now runs on every
   execution proving the global shortlist does not over-fill from the right collection.*

5. **Why does the `WHERE` clause do two jobs, and which one is more dangerous?**
   *It excludes the canary twin that would otherwise be reranked into the top 5 — loud, caught
   by any isolation assertion. And it recovers three `infrastructure` documents that
   global-top-10-then-filter would discard, because only 7 of the global top 10 are
   infrastructure. That second job is silent: correct documents, correct collection, fewer of
   them, HTTP 200, and retrieval that gets steadily worse as the corpus grows.*

6. **Persistence on AWS was proven by restarting the API container. What was that not a test
   of?**
   *An EC2 reboot — and therefore the whole boot path: `user_data`, the repository clone, the
   model download, the compose bring-up. A container restart re-creates a writable layer and
   touches none of that. Clean destroy/rebuild reproducibility remains outstanding, carried
   forward from Milestone 2.*
