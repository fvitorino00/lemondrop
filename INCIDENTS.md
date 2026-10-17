# INCIDENTS — investigation records for the lemondrop stack

> ## ⚠️ NO INCIDENT HAS OCCURRED. NO INCIDENT HAS BEEN SOLVED.
>
> This file is a **template and an incident-readiness note**. Every incident
> section below is **EMPTY — NOT STARTED**. There is no ticket, no symptom, no
> hypothesis, no evidence and no recovery recorded anywhere in this document,
> and none has been invented to fill the shape.
>
> The milestone this file belongs to asks that we be *ready* to investigate and
> record an incident — not that we manufacture one. A filled-in example would be
> indistinguishable from a real claim, so there is none.

---

## 1. What this file is for

An incident record is evidence, and like every other artifact in this repository
it exists to make a claim **checkable**. The distinction the milestone turns on:

> **The acceptance is "demonstrate the recovery, not just the final working
> system."**

A record that shows only the working end state proves nothing about recovery.
To demonstrate recovery you must capture the **broken state**, state a
**testable hypothesis**, show the **evidence** that confirms or rejects it, make
the **smallest defensible correction**, and capture the **healthy state again** —
in that order, with the before and after both on file. The record has to exhibit
the whole arc, not its end.

This file lives at the repository root next to `RUNBOOK.md` and `COSTS.md`
because an incident record is a durable artifact retained **in Git**, not
infrastructure — see `RUNBOOK.md` §6.2 for why that distinction matters at
teardown.

---

## 2. How to use this file

1. **Do not edit an existing incident's conclusions after the fact.** Append.
   If a root cause was wrong, record the correction as a new dated entry that
   supersedes the old one. The history of the investigation is part of the
   evidence.
2. **Capture the baseline first.** Before changing anything, take the read-only
   measurements in §6.3. An incident record with no "before" is a story.
3. **One section per incident.** Copy the template in §4 into the right
   category section (§5.1 networking / §5.2 dependency / §5.3
   application-correctness). If a category has no incidents, leave it as it is.
4. **Ground every claim in a command and its output**, or mark it
   `NOT OBSERVED`. Never record a value you did not read.
5. **Respect the standing prohibitions** in §6.4. Some of them exist because
   acting on the obvious instinct would destroy evidence or make things worse.

---

## 3. Evidence before and after — the method

The recovery is demonstrated by **two snapshots and a diff**, not by a
narrative.

| | Before the correction | After the correction |
|---|---|---|
| Purpose | Show the broken state | Show the recovered state |
| How | Read-only tools only (§6.2) | The same read-only tools, same arguments |
| Output | A timestamped report per tool | A timestamped report per tool |
| Store | The report text, plus the command that produced it | The report text, plus the command |
| Then | — | Diff before vs. after; the difference **is** the recovery |

Rules that make the diff meaningful:

- **Same tools, same arguments, same vantage point** before and after. A
  before-shot from the host and an after-shot from the laptop compare two
  different things.
- **Timestamp and record the command**, not just the result. The command is what
  makes the result reproducible.
- **If a tool cannot run** (e.g. a report directory is unwritable), record *that*
  as the observation — `NOT OBSERVED` is a fact; silence is not.
- **Preserve the broken-state report.** It is the half of the pair that is
  usually lost, and without it "we recovered" is an assertion.

On the host, the read-only pair is `scripts/verify-deployment.sh` and
`scripts/diagnose.sh`; both write nothing except `diagnose.sh`'s timestamped
report under `/var/lib/lemondrop/diagnostics/` (§6.2). Copy the reports out
**before** any deploy overwrites them — see §6.2 and `docs/verification-milestone-4.md`
§12.4, which records a live-host report that was produced and **not retained**.

---

## 4. The investigation template

Copy the block below verbatim into the relevant category section and fill it in.
Leave a field as `NOT OBSERVED` / `NOT STARTED` rather than guessing.

```markdown
### INCIDENT-YYYYMMDD-NN — <one-line title>

| Field | Value |
|---|---|
| Timestamp detected (UTC, start) | |
| Detected by / from where | |
| Severity | SEV-1 (down) · SEV-2 (degraded) · SEV-3 (correctness, availability intact) |
| Affected component | (name the component: ALB / api / embedder / reranker / PostgreSQL / host / networking) |
| Route or path affected | (e.g. POST /search, or EC2→RDS :5432) |

**1. Observed symptom — what was SEEN, not what it means.**
Describe the raw observation: the status code, the message, the report line, the
blocked hop. No interpretation in this stage. "curl returned 503" is a symptom;
"the database is down" is a conclusion, and it belongs in Root cause.

- Observed behaviour:
- How the problem was discovered: (whose check, which tool, at what time)
- Affected component:
- Client impact: (who is affected and how; or NONE OBSERVED)

**2. Hypothesis (testable) — recorded BEFORE any test is run.**
State at least one specific theory that a command could **confirm or reject**. A
hypothesis written after the evidence is not a hypothesis; it is a retelling.
State both outcomes in advance:

- Hypothesis:
  - Confirms if:
  - Rejects if:

**Hypotheses are preserved even when the evidence disproves them.** A rejected
hypothesis stays in the record, marked `REJECTED`, with the evidence that
rejected it. Do not delete a hypothesis once it is answered — the history of the
investigation is part of the evidence.

**3. Evidence — two tables, split by what it does to the hypothesis.**
Exact commands, exit codes, relevant logs, HTTP responses, timings and
observations — nothing paraphrased to fit the conclusion.

*Evidence SUPPORTING the hypothesis.*

| # | Command run | Exit code | Output (verbatim or summarised) | Where the full output is recorded |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

*Evidence REJECTING the hypothesis.*

| # | Command run | Exit code | Output (verbatim or summarised) | Where the full output is recorded |
|---|---|---|---|---|
| 1 | | | | |

If one table has no rows, write `NONE` beneath it rather than leaving it blank.

**4. Correction — the smallest defensible change.**
The minimum change that addresses the established root cause — not the largest
change that might also help.

- The change, and what it touches and leaves alone:
- Why this change was chosen over the alternatives:
- Risks it introduces:
- Operator approval (name, UTC date):
- Rollback or recovery plan:

**5. Verified recovery and prevention.**
Prove that the **specific failure** was resolved — not merely that the service
returned HTTP 200. An intermittent fault is not verified by one green response;
say what distinguishes recovered from not-looking.

- Before / after results, and the diff between them (§3):
- Root cause (established), or `NOT YET ESTABLISHED`:
- Lessons learned:
- Suggested safeguards:
- Monitoring improvements:
- Regression tests:

**Status.** NOT STARTED · INVESTIGATING · CORRECTED · RECOVERED · CLOSED
```

**Evidence files live outside Git until the record is reviewed;** after review,
the sanitized evidence — or a stable reference to where it is retained — is
committed. Never commit credentials.

---

## 5. Incident records

### 5.1 Networking incident

**EMPTY — NOT STARTED.**

*(A networking incident is one where the path between components is affected:
the ALB not reaching the host, the host not reaching RDS, a security-group or
route change, DNS, or a source-address change locking the operator out. See
`docs/architecture.md` for the paths an incident here would traverse and §6 of
that file for the egress caveat.)*

---

### 5.2 Dependency incident

**EMPTY — NOT STARTED.**

*(A dependency incident is one where a component the caller depends on is
unavailable or unready: the embedder or reranker failing its healthcheck so the
API never becomes healthy, PostgreSQL unreachable so `/health/ready` returns 503
while `/health/live` stays 200, or a `depends_on: service_healthy` gate that
never fires. See `docs/architecture.md` §7 for the declared dependency graph.)*

---

### 5.3 Application-correctness incident

**EMPTY — NOT STARTED.**

*(An application-correctness incident affects **correctness rather than
availability**: the stack is up and answering, and the answers are wrong. The
deploy log and the readiness checks will all be green — which is exactly why
this class needs its own section and its own evidence. The known candidate for
this class is a retrieval or reranking correctness fault, e.g. a query prefix
wrongly applied, a wrong embedding width, or a stale candidate set. See
`README.md` [Design notes](README.md#design-notes) for the invariants a
correctness incident would be measured against.)*

---

## 6. Incident readiness

This section is the preamble an investigator reads **before touching a ticket**.
It lives here — with the records it feeds — rather than in `RUNBOOK.md`, because
`RUNBOOK.md` is about operating the stack (deploy, verify, restart, tear down)
while this is about investigating a fault without destroying the evidence the
record needs. The two overlap at the read-only tools; both name the same scripts.

### 6.1 The last VERIFIED healthy baseline

| Field | Value |
|---|---|
| Record | `docs/verification-milestone-4.md` §9.3 (SSM `97f3ed0e-ed62-42a0-b273-b270d45db4ef`, SUCCESS, exit 0) |
| Digest verdict | **AGREE** |
| Provenance verdict (revision label vs record) | **AGREE** |
| Schema verdict (`ALEMBIC_HEAD`) | **AGREE** |
| Readiness | **HTTP 200** |
| Semantic search | **PASS** |
| Host checkout | **`1eba3b6`** (`docs/verification-milestone-4.md` §5) |
| Live database revision | **`0001`** (§5, verified independently through a TLS `verify-full` tunnel) |
| Date | The M4 session, 2026-10-14/15; the record's own last commit is `8d9edc8` (2026-10-15) |

**Read the baseline for what it is, and no more.** It is a **VERIFIED healthy
state** — the strongest evidence in `docs/verification-milestone-4.md` — but
**Milestone 4 is not closed**, and that document says so in its own header.
Every result behind this baseline was produced by **the engineer who built the
system**; **no second party has followed the runbook**
(`docs/verification-milestone-4.md` §13.1). So this is a baseline verified by the
author, not an independently witnessed one. Do not present it as a second-party
baseline, and do not treat "the last deployed digest" here as current without
re-running §6.2's read-only tools — the committed digests go stale on every merge
(`docs/deployment.md` §10 item 8).

### 6.2 Inventory of diagnostic tools

What exists today, and — the part that matters — what each one does **not** tell
you.

| Tool | What it tells you | What it does **not** tell you |
|---|---|---|
| `scripts/verify-deployment.sh` | The record vs. the **running image**: `AGREE` / `DIVERGENCE` / `UNPINNED (LEGACY)`; the provenance and schema blocks. Read-only; takes no lock, writes nothing. | Does **not** check health, does **not** call `/search`, does **not** touch the database. It answers "what is this host running?", not "is it well?". |
| `scripts/diagnose.sh` | Container health for all three services, database readiness, and the status codes of `/health/live` and `/health/ready`; writes a timestamped report under `/var/lib/lemondrop/diagnostics/`. Read-only; emits no verdict strings, composes no credentials. | Does **not** run the known-good search (that probe is `verify_stack()`'s, and over the ALB it meets the 60s-idle-timeout vs ~240s-search mismatch, `docs/deployment.md` §10 item 4). Does **not** compare the record to the running image. |
| `scripts/diagnose.ps1` | The same report from a Windows workstation. | **Written for Windows PowerShell 5.1 but executed only on 7.4.6/Linux.** 5.1 was never executed and cannot run on Linux (`docs/verification-milestone-4.md` §11.1). |
| `/var/log/lemondrop-deploy.log` | The `deploy.sh` / `rollback.sh` log (`deploy-lib.sh:60`). | Only what those scripts logged; nothing about what the live system did after the deploy. |
| `/var/log/lemondrop-boot.log`, `/var/log/cloud-init-output.log` | The boot script's own log and cloud-init's. Terminal verdict line at the end. | Only the boot. An ordinary reboot does **not** re-run `user_data` (`docs/deployment.md` §9.5.1), so a stale boot log is expected, not a fault. |
| `docker compose logs` (on the host) | Per-service container logs. Bounded by `json-file` rotation at `10m` × 3 files per service (`docker-compose.yml:152-158`). | Only the last ~30MB per service; older lines are gone. The API records upstream detail server-side while the caller gets a short sentence (`README.md` [Upstream failures](README.md#upstream-failures)). |
| `/var/lib/lemondrop/diagnostics/` | Timestamped on-host diagnostic reports. | **Not** an off-host artifact. `docs/verification-milestone-4.md` §12.4 records a live report produced and **not retained** — copy reports out before the next deploy. |
| **CloudWatch / ALB** | **RDS** exports `postgresql` and `upgrade` logs to CloudWatch (`infra/database.tf:280`). ALB publishes CloudWatch metrics by default. | **ALB access logs are OFF** (`lb_access_logs_enabled` defaults to `false`, `infra/load_balancer.tf:81-115`). There is **no CloudWatch alarm and no dashboard** anywhere in `infra/*.tf` — a `grep` for `aws_cloudwatch_metric_alarm` returns nothing. Nothing pages anyone; monitoring is pull-based. |

### 6.3 Prerequisites for safely investigating a ticket

- **Access.** There is no SSH by default. Reach the host through SSM Session
  Manager, discovering the instance id from the `Role=application-host` tag the
  config sets (`infra/compute.tf:589-592`); the runbook's route is
  `docs/deployment.md` §7.1.1 step 1. The `RUNBOOK.md` header lists the
  AWS-access mechanics this depends on.
- **The read-only baseline habit.** Run the read-only tools **first**, before
  changing anything: `scripts/verify-deployment.sh` then `scripts/diagnose.sh`.
  Both are safe on a host that is on fire, mid-deploy, or never deployed to
  (`scripts/verify-deployment.sh:12-22`). Copy `diagnose.sh`'s report off the
  host before proceeding — the next deploy can overwrite it.
- **One vantage point per comparison.** The same tool the same way before and
  after (§3). Do not compare a host-side report to a laptop-side curl.

### 6.4 Standing prohibitions — do not do these while investigating

These are not style notes; each one destroys evidence or makes a record wrong.

1. **Do not hand-edit the revision record** (`/var/lib/lemondrop/deployed-revision.env`).
   It is the only thing that makes "what is running?" answerable, and hand-edits
   make it lie. A deploy or rollback rewrites it; nothing else should.
2. **Do not deploy a digest that is already running.** `deploy.sh` has no
   redundant-deploy guard: a second deploy of the running digest overwrites
   `PREVIOUS_IMAGE_DIGEST` with that digest, so the rollback pointer names the
   image that is running and the intended previous image is orphaned. It was
   **executed** on the live host during M4. Status **UNFIXED**.
   `docs/deployment.md` §10 item 16; `docs/verification-milestone-4.md` §8.2.
3. **Do not rehearse the legacy rollback branch** of `rollback.sh`. It can start
   an image that is not the rollback target and its own checks will not notice.
   It is **UNSAFE and UNVERIFIED**; do not construct the state that selects it.
   `docs/deployment.md` §10 item 15; `docs/verification-milestone-4.md` §12.2.
4. **Do not try to run a migration from the host.** The EC2 instance role can
   read only the application database secret, never the RDS master, so the
   `lemondrop_app` role has no DDL rights and a migration cannot run there.
   `deploy-lib.sh`'s own header states this; migrations are out-of-band.
5. **Do not roll the API back on its own** if a migration was applied out of
   band and is not known to be backward-compatible — check the recorded head
   first (`scripts/rollback.sh`, header block `── WHEN TO USE THIS, DECIDED IN
   ADVANCE ──`; `docs/deployment.md` §4.1).

### 6.5 The evidence-before-and-after procedure, concretely

```
BEFORE  (broken state — capture it, do not fix it yet)
  1. sudo /opt/lemondrop/scripts/verify-deployment.sh   | tee /root/inc-<id>-before-verify.txt
  2. sudo /opt/lemondrop/scripts/diagnose.sh            # writes /var/lib/lemondrop/diagnostics/<stamp>.txt
  3. Copy BOTH out of the host, and note the command, the time (UTC), and the vantage point.
  4. Record the observed symptom (§4) from THAT output, not from memory.

CHANGE
  5. Make the smallest defensible correction (§4). One change where possible.

AFTER   (recovered state — same tools, same arguments, same vantage point)
  6. sudo /opt/lemondrop/scripts/verify-deployment.sh   | tee /root/inc-<id>-after-verify.txt
  7. sudo /opt/lemondrop/scripts/diagnose.sh            # a second timestamped report
  8. Copy both out of the host.

DIFF
  9. diff /root/inc-<id>-before-verify.txt /root/inc-<id>-after-verify.txt
 10. The difference between the two is the recovery. Record it verbatim in stage 5's
     "Verified recovery and prevention" field, alongside where the two reports are kept.
```

The reports above are the read-only pair and say nothing about `/search`; if the
incident is in retrieval, add the recorded search probe from
`docs/verification-milestone-3.md` §8.2 as a third measurement, from a single
consistent vantage point, and note the ALB timeout caveat (§6.2).
