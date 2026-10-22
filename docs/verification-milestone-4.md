# Milestone 4 — Verification Record

> ## ⚠️ **MILESTONE 4 IS NOT CLOSED. The deployment path is verified; the acceptance criterion is not.**
>
> **§13 is the authority on the criterion, and it is UNTESTED.** The deploy tooling in this
> milestone was built, exercised live against a real EC2 host, and left behind a record that
> answers "what is running?" without help from a human. **Every operational result in this
> document was produced by the engineer who built the system. No second party has followed
> this runbook.** That single fact is what keeps the milestone open, and §13 states the
> ambiguity in the criterion's wording rather than resolving it by assumption.
>
> | Section | What it holds |
> |---|---|
> | **§1** | The classification table — every area, VERIFIED / PARTIAL / UNTESTED |
> | **§2** | Provenance — who ran what, and what can be re-run by a reader |
> | **§3** | CI run `38646911142` — nine jobs, all green |
> | **§4** | The three diagnostic suites, and the count that could be re-checked |
> | **§5** | The host: checkout, and the database head nobody could read from the record |
> | **§6** | The Docker engine compatibility probe — the check that had to pass first |
> | **§7** | Adoption: pre-adoption probe, adoption, post-adoption verification |
> | **§8** | The first live deploy — **and the redundant-deploy defect, UNFIXED** |
> | **§9** | The real rollback, the tags it left behind, and two different hash kinds |
> | **§10** | What §9's five green verdicts do **not** mean |
> | **§11** | PARTIAL — two things, neither of which should be rounded up |
> | **§12** | UNTESTED — six items, none of them softened |
> | **§13** | The M4 acceptance criteria, and why the criterion's wording matters |
> | **§14** | The eleven commits this milestone consists of |
> | **§16** | Post-remediation addendum — supersedes the §1 and §12 statuses **without erasing them** |
> | **§16.9** | Cross-reference: E5 fix deployed, no M4 status changed |
>
> **The headline verified facts, compactly.** CI run **`38646911142`** finished **SUCCESS with
> all nine jobs green**, including `pip-audit --strict` (**zero vulnerabilities**) and
> `terraform fmt`/`validate` on both stacks. The published image carries **immutable digests
> and OCI labels**. The diagnostic suites report **30 / 34 / 4 passed, 0 failed**. On the live
> host: the checkout is **`1eba3b6`**, the database head is **`0001`**, adoption of the
> legacy image **succeeded** (`f3a94a3f-…`, exit 0), post-adoption verification returned
> **`UNPINNED (LEGACY)`** with the recorded `IMAGE_ID` matching the running API, `ALEMBIC_HEAD=0001`,
> readiness **HTTP 200** and the known-good search **PASS** (`92810aaf-…`, exit 0). An older
> labelled release deployed and verified **AGREE**. A **real rollback** to `sha256:6036f724…`
> succeeded (`4450c9b0-…`). The final state is **digest AGREE, provenance AGREE, schema
> AGREE, readiness HTTP 200, semantic search PASS** (`97f3ed0e-…`, exit 0).
>
> **And what those facts do not mean, stated in the same breath so this header cannot be
> read as a blanket claim:**
>
> - **The acceptance criterion is UNTESTED.** One engineer deployed, rolled back, adopted and
>   verified. §13 explains why that does not close the criterion, and does not pretend the
>   criterion's wording is unambiguous when it is not.
> - **The legacy rollback branch of `rollback.sh` is known-defective and was never executed.**
>   `docs/deployment.md` §10 item 15 is the record. **Do not rehearse it.**
> - **PowerShell 5.1 was never executed and cannot be** — it does not exist on Linux. All
>   execution was PowerShell 7.4.6 on Linux (§4, §11).
> - **The mutating scripts have no automated tests.** `deploy.sh`, `rollback.sh`,
>   `verify-deployment.sh` and `deploy-lib.sh` control flow is unexercised by any suite, and
>   their first live use was this milestone (§12).
> - **There is a real, unfixed defect in `deploy.sh`**, found by this milestone's own
>   operator, in §8. It is recorded, not repaired.

---

## 1. Status at a glance

Every area in this milestone, classified. The definitions are strict on purpose: **VERIFIED**
means a check was run and its result is recorded below with an identifier; **PARTIAL** means
part of the claim was exercised and the rest is stated as unexercised; **UNTESTED** means no
check was run and none is implied.

| # | Area | Status | Evidence |
|---|---|---|---|
| 1 | CI on the release workflow — 9 jobs | **VERIFIED** | Run `38646911142`, conclusion `success` — §3 |
| 2 | Application test suites (T1 service-free, T2 disposable pgvector) | **VERIFIED** | §3, jobs 6 and 7 |
| 3 | Diagnostic tier classification (T0) | **VERIFIED** | §3, job 2 |
| 4 | Dependency audit — `pip-audit --strict`, `api/requirements-dev.txt` | **VERIFIED** | Zero vulnerabilities — §3, job 4 |
| 5 | Terraform `fmt` + `validate`, main and bootstrap stacks | **VERIFIED** | §3, job 5 |
| 6 | Docker image build, content gate, label assertion, GHCR publish | **VERIFIED** | §3, jobs 8 and 9 |
| 7 | `scripts/test-diagnose.sh` | **VERIFIED** | 30 passed / 0 failed — §4 |
| 8 | `scripts/test-diagnose.ps1` | **VERIFIED** | 34 passed / 0 failed — §4 |
| 9 | `scripts/test-diagnose-parity.sh` | **VERIFIED** | 4 passed / 0 failed — §4 |
| 10 | The EC2 checkout is `1eba3b6` | **VERIFIED** (operator-reported) | §5 |
| 11 | The live RDS Alembic revision is `0001` | **VERIFIED** (independently, by the operator) | §5 — TLS verify-full, `public.alembic_version`, exactly one row |
| 12 | Docker engine compatibility: container `.Image` vs image `.Id`, `RepoDigests`, live `image_repo_digests()` | **VERIFIED** | SSM `c071e162-3a03-4d9b-be7f-c7095a796591` — §6 |
| 13 | Pre-adoption probe | **VERIFIED** | SSM `ffd75853-8a77-4eab-9ddc-9eacff494b0a` — PASS, §7 |
| 14 | Legacy adoption (`--adopt-current 0001`) | **VERIFIED** | SSM `f3a94a3f-ca3c-498e-a40b-6eacb427e768`, Success, exit 0, record written — §7 |
| 15 | Post-adoption verification | **VERIFIED** | SSM `92810aaf-8df8-4f8a-99c1-12ad35196a4c`, Success, exit 0 — §7 |
| 16 | Bash diagnostic on the live host | **VERIFIED** | SSM `3aa89e7e-68da-4bce-bbd2-65ef944a7547`, Success, exit 0 — §7 |
| 17 | Deploy of an older labelled release, `sha256:45a04d20…` | **VERIFIED** | §8 |
| 18 | Verification after that deploy | **VERIFIED** | AGREE, HTTP 200, known-good search PASS — §8 |
| 19 | Real rollback to `sha256:6036f724…` | **VERIFIED** | SSM `4450c9b0-edd0-4d83-8632-3d64f9e72630`, SUCCESS — §9 |
| 20 | Final verification + diagnostics | **VERIFIED** | SSM `97f3ed0e-ed62-42a0-b273-b270d45db4ef`, SUCCESS, exit 0 — §9 |
| 21 | Final restored state | **VERIFIED** | digest AGREE, provenance AGREE, schema AGREE, HTTP 200, search PASS — §9 |
| 22 | Redundant-deploy guard in `deploy.sh` | **UNTESTED — and the guard does not exist** | §8.2, §10 item 3 |
| 23 | PowerShell 5.1 compatibility | **PARTIAL** | Written for 5.1, executed only on 7.4.6/Linux — §11.1 |
| 24 | Runbook freshness for the adoption command | **PARTIAL** | Corrected at `667e7ad` — §11.2 |
| 25 | Second-engineer acceptance criterion | **UNTESTED** | §13.1 |
| 26 | Legacy rollback branch | **UNTESTED, and known-defective** | `docs/deployment.md` §10 item 15; §12.2 |
| 27 | Automated tests for the mutating scripts | **UNTESTED — none exist** | §12.3 |
| 28 | The diagnostic report artifact from the live host | **UNTESTED as evidence** | Produced on the host, not retained — §12.4 |
| 29 | ALB idle timeout (60 s) vs worst-case `/search` (~240 s) | **UNTESTED / unresolved** | Out of M4 scope — §12.5 |
| 30 | `shellcheck` over `scripts/*.sh` | **UNTESTED — no such job exists** | §12.6 |

## 2. Provenance

This document follows the convention `docs/verification-milestone-3.md` sets. Every row states
*who ran the check*, because that distinction is not decoration:

- **Executed by: operator** — run on the EC2 host through SSM by the operator, with the
  result reported. **These were not re-run by the agent and cannot be.** The SSM command ID
  is given beside each one so the invocation itself can be looked up.
- **Executed by: CEO** — run by the agent in this repository, read-only, with the command and
  its result reproducible by anyone.
- **Reported by the operator, re-read independently by: CEO** — the operator ran the check;
  the agent independently re-read the result from an API that does not re-run it. Only §3 is
  in this class.

**Every row in §5 through §9 is operator-executed.** No `aws` call, no SSM `SendCommand`, no
Terraform apply, no deploy and no rollback was performed in the course of writing this
document. The two re-runs that did happen were `scripts/test-diagnose.sh` (§4) and a
read-only GitHub API query for the CI run (§3).

## 3. Continuous integration — run `38646911142`

**Reported by the operator, re-read independently by: CEO.** Read-only GitHub API query;
the agent did not re-run CI and cannot. Workflow **`release`**, event `push`, head commit
`1eba3b600f1551868318e401d9479a27298c8a35`, created `2026-10-14T22:20:05Z`, conclusion
**`success`**.

| # | Job | Conclusion | What it establishes |
|---|---|---|---|
| 1 | `state-leak gate` | `success` | Forbidden paths are not tracked; no secrets in tracked content |
| 2 | `T0 (tier classification)` | `success` | Every collected test is classified into exactly one tier; **both diagnostics run syntax + self-test, stubbed end-to-end, and heading parity** |
| 3 | `actionlint` | `success` | The workflows parse and lint |
| 4 | `dependency audit (pip-audit)` | `success` | **`pip-audit --strict --progress-spinner off --format json --requirement api/requirements-dev.txt`** (`hygiene.yml:726-727`) exited **0** — **zero vulnerabilities** |
| 5 | `terraform validate` | `success` | `fmt` + `init` + lockfile-drift + `validate` on **both** the main and the bootstrap stack |
| 6 | `T1 (service-free)` | `success` | `pip check`, tier-1 preconditions, and the service-free suite |
| 7 | `T2 (disposable pgvector)` | `success` | Containers initialised, **migrate** ran, the database-backed suite collected and passed, containers stopped |
| 8 | `build and inspect the image` | `success` | Image built into the local daemon; **`assert the built image carries its labels`**; **image content gate**; digest recorded; artifact uploaded |
| 9 | `publish to GHCR` | `success` | The **exact gated artifact** was loaded, **verified to be the inspected image**, then pushed with the `sha` and `main` tags; pushed digest recorded |

**All nine jobs are `success`.** Nothing was skipped, cancelled or neutral.

**What the nine green jobs establish about the M4 work specifically.** The published image is
**digest-addressed and labelled** (jobs 8 and 9), which is what makes a single-argument deploy
possible (§8). The dependency gate is **blocking**, not advisory (job 4). The diagnostics are
**tested in both languages with the heading-parity check** (job 2).

**What the nine green jobs do not establish.** Not one of them invokes `deploy.sh`,
`rollback.sh` or `verify-deployment.sh`. Job 2 runs the *diagnostics* and their tests; the
diagnostics are read-only and, by design, call none of the three mutating scripts. **A green
release run is evidence about the image and the test suites, not about the deployment path.**
The deployment path's evidence is §5 through §9, and §12.3 is the standing reminder that it
has no automated coverage at all.

## 4. The diagnostic suites

| Suite | Result | Executed by |
|---|---|---|
| `scripts/test-diagnose.sh` | **30 passed, 0 failed** | **CEO — re-run in this repository, reproducible** |
| `scripts/test-diagnose.ps1` | **34 passed, 0 failed** | Operator / CI (job 2) |
| `scripts/test-diagnose-parity.sh` | **4 passed, 0 failed** | Operator / CI (job 2) |

**Re-check the Bash half from the repository root:**

```
bash scripts/test-diagnose.sh
```

It reports `test-diagnose.sh: 30 passed, 0 failed`. The suite leaves no residue: `git status`
was clean immediately afterwards, apart from the two untracked `docs/` paths that are not this
milestone's.

**The PowerShell half was NOT re-run here, and the reason is worth stating plainly:**
**`pwsh` is not on `PATH` in the environment this record was written in.** Running
`scripts/test-diagnose-parity.sh` locally fails with `pwsh is not on PATH, so the PowerShell
half could not be compared.` **The 34 and 4 figures are carried from the operator and from CI
job 2. They are not re-checked by this document and no reader should infer that they are.**
This is the same 5.1-versus-7.x gap as §11.1, one level up: the tests ran, and they ran on
one PowerShell.

## 5. The host — checkout and database head

**The checkout is `1eba3b6`.** Reported by the operator. **A coincidence worth noting and not
over-reading:** the head commit of release run `38646911142` is
`1eba3b600f1551868318e401d9479a27298c8a35` (§3), so the commit that was released and the
commit on the host are the same commit. **That is consistent; it is not independent
confirmation of the host's working tree**, which nobody inspected with
`git rev-parse HEAD` on the host. What the host actually has checked out is operator-reported.

**The live RDS Alembic revision is `0001`.** This one *is* independently established, and it is
the most important single fact in this document, because §5's second half is what the whole
adoption path rests on:

- Verified by the **operator**, **independently** of the deploy tooling.
- Through an **SSM tunnel**, with **`verify-full`** — TLS certificate verification on, not
  disabled.
- Against **`public.alembic_version`**.
- Returning **exactly one row**: `0001`.

**Why this needed its own verification, stated so the reasoning is not lost.** The record on the
host could not be trusted to know its own schema head — that is the entire reason `--adopt-current`
requires the operator to supply it (`docs/deployment.md` §7.1; the runbook change is `667e7ad`,
§11.2). A tool cannot check its own migration state by asking itself what migration state it is
in; the check has to come from outside the tool. It came from the database, through a verified
TLS tunnel, and it returned one row.

**What this does not establish.** `0001` is the head **at the time of the check**. It is a
statement about one database at one moment, not a guarantee about any other host, which is why
`docs/deployment.md` §7.1 insists the argument is `<db-verified-alembic-revision>` and must be
re-read per host.

## 6. The Docker engine compatibility probe

**SSM `c071e162-3a03-4d9b-be7f-c7095a796591`.** This probe ran *before* adoption, and it is
the right order: every identity claim the tooling makes downstream depends on these three
answers, and finding out they were wrong after adoption would have meant un-adopting.

| # | Question | Result |
|---|---|---|
| **Q1** | Does the running container's `.Image` match the image's `.Id`? | **YES** — they match |
| **Q2** | Does the registry image expose `RepoDigests`? | **YES** |
| **Q3** | Does the real `image_repo_digests()` return the digest? | **YES** — returned the digest, **exit 0**, **non-empty stdout**, **empty stderr** |

**Q3 is the one that matters and it is the one that was actually exercised.** Q1 and Q2 could
have been answered by reading the Docker documentation. Q3 runs **the function the deploy path
will call** — `image_repo_digests()`, `deploy-lib.sh:497-501`, which is
`docker inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$image_id"` — against the
host's real daemon. **Non-empty stdout and empty stderr, both, is the whole claim**: a function
that returns nothing while exiting 0 is the failure mode that would have produced a record
with an empty digest and a green exit code. It did not.

**Why `RepoDigests` is load-bearing here.** `verify-deployment.sh` reads `RUNNING_DIGESTS` from
this function (`verify-deployment.sh:95`) and it is what decides between `AGREE` and
`DIVERGENCE`. Q2 and Q3 together establish that the decision has something to decide on.

## 7. Adoption — the legacy host enters the record

Adoption is how an M3-era host — an image built on the box, with no registry reference — is
given a record without pretending it was deployed by `deploy.sh`. Three checks, in order.

### 7.1 Pre-adoption probe

**SSM `ffd75853-8a77-4eab-9ddc-9eacff494b0a` — PASS.**

A probe that passes before anything mutates. Its value is that it is the *last* moment at
which "this host is in the state I think it is in" is a cheap claim.

### 7.2 Adoption

**SSM `f3a94a3f-ca3c-498e-a40b-6eacb427e768` — Success, exit 0, record written**, invoked as
`--adopt-current 0001`.

**The `0001` in that command is §5's fact and nothing else.** The argument is not a default, not
a fallback and not a guess: `docs/deployment.md` §7.1 records that the revision is **mandatory,
with no default**, precisely because a tool that guesses its own schema head is a tool that can
lie about it. Adoption recorded what the host was actually running under an identity the
digest-pinned path can reason about.

### 7.3 Post-adoption verification

**SSM `92810aaf-8df8-4f8a-99c1-12ad35196a4c` — Success, exit 0.** Every row below was
reported by the operator:

| Check | Result |
|---|---|
| Digest verdict | **`UNPINNED (LEGACY)`** |
| Recorded `IMAGE_ID` | **matches the running API** |
| `ALEMBIC_HEAD` | **`0001`** |
| Readiness | **HTTP 200** |
| Known-good search | **PASS** |

**`UNPINNED (LEGACY)` is a PASS-shaped string and must be read as what it says it is.**
`verify-deployment.sh:176` prints `UNPINNED (LEGACY) — neither agreement nor divergence.
NOTHING WAS COMPARED`, and `:183` is explicit: *"this line is NOT a pass — it is an admission
that the check could not run."* There is no registry digest on either side, so there was
nothing to compare.

**The row that carries the weight is the second one, not the first.** The legacy verdict
admitted that no digest comparison was possible; what kept it honest is that the record **does**
pin an `IMAGE_ID`, and that the `IMAGE_ID` **matches the running API**. That is a real
comparison (`verify-deployment.sh:175`) — the only one a digest-less record can support, and
the script says so at `:189-190`. **An adopted host is therefore not an unchecked host.** It is
a host checked by a different, weaker, and explicitly-stated means.

### 7.4 The Bash diagnostic on the live host

**SSM `3aa89e7e-68da-4bce-bbd2-65ef944a7547` — Success, exit 0.** Reported:

- **All three containers healthy.**
- **Database readiness OK.**
- **`/health/live` and `/health/ready` both HTTP 200.**
- **A timestamped report was written.**

This is the first time the Stage 6 diagnostic ran against real containers on a real host. §4
established that it runs at all, under stubs; this establishes that it runs against a Docker
daemon.

**The report itself is not evidence anyone can re-read.** It was written on the EC2 host and
**was not retained in this repository** — §12.4. What is recorded here is the operator's
summary of its contents, not the artifact. Those are different kinds of claim and the
distinction is preserved.

## 8. The first live deployment — and the defect it exposed

### 8.1 The deploy, and its verification

**Deployed release:** `sha256:45a04d20…` — an **older labelled release**, revision
`52b02f4…`, `org.lemondrop.alembic-head` = `0001`.

**Verification after that deploy:** **AGREE**, **HTTP 200**, **known-good search PASS**.

That verdict is `AGREE` rather than `UNPINNED (LEGACY)`, and the difference is the whole point
of the deploy: the host moved from "nothing was comparable" to "the record and the running
image were compared and they match". The revision and schema head on that deploy line were
read from the **image's own OCI labels**, which is what allows a one-argument deploy —
`docs/deployment.md` §4.4.

### 8.2 ⚠️ FINDING — a redundant deploy has no guard, and this is UNFIXED

**What happened.** During the **first** deployment sequence, `deploy.sh` was run **twice**, and
the second run **overwrote `PREVIOUS_IMAGE_DIGEST` with the digest it had just deployed.** The
record's rollback pointer now named the image that was currently running, so the rollback target
was the thing you had just replaced.

**Root cause, at `file:line`.** `deploy.sh:944` reads the previous digest:

```
    prev_digest="$(record_get IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"
```

read from the **pre-existing** record — and that value is then written back as
`PREVIOUS_IMAGE_DIGEST` (`deploy.sh:969`). **No code path anywhere compares the target against
the running image.** There is no idempotency check, no "already deployed" refusal, no
already-running guard. Running `deploy.sh` twice against the same digest is not detected,
because nothing in the script looks.

**Why this is a defect and not a curiosity — proven two independent ways.** The observation is
that a second run was needed to produce the bad state. That is established from both ends:

| # | Argument | Why it holds |
|---|---|---|
| **(a)** | **`PREVIOUS_IMAGE_DIGEST` naming the just-deployed digest is not producible by a single run.** | In one run, `prev_digest` (`:944`) is read from the record as it was **before** this run wrote it, and that record describes the image that was running **before** this deploy. For the field to name the digest this run installed, a record naming that digest must already have existed — which is the **second** run's state, not the first's. |
| **(b)** | **A rollback tag pointing at the image that run installed is impossible.** | `PREV_IMAGE_ID` is read at **`deploy.sh:293`** — `PREV_IMAGE_ID="$(running_image_id "$PREV_CONTAINER_ID")"` — from the container that exists **before** the switch. The switch is the `compose up` at **`deploy.sh:925`**. Reading precedes switching, so on any single run the tag can only ever name the pre-deploy image. A tag naming the newly installed image requires a prior run to have installed it. |

Two routes, one conclusion: **≥2 runs are required.** The second run is not an accident that
might not recur; it is the mechanism.

**Status: UNFIXED.** Nothing was changed in `deploy.sh` while writing this record, and fixing
it is deliberately out of scope for this milestone. It is recorded here, and §10 item 3 carries
it into the list of what the green verdicts do not mean — because a deploy path with no
redundant-run guard will be run twice by someone, and the record will be wrong in a way that
only surfaces at the moment a rollback is needed.

## 9. The real rollback, and what it left behind

**Rollback to `sha256:6036f724…` — SSM `4450c9b0-edd0-4d83-8632-3d64f9e72630`, SUCCESS.**

This is the digest-bearing branch of `rollback.sh` (`rollback.sh:163-190`), and it is the one
that works — `docs/deployment.md` §10 item 15 is the long-form statement. **A rollback that has
been executed once is worth more than a rollback that has only been read**, and this is the
first live execution of `rollback.sh` on this host.

### 9.1 Rollback tags observed

| Tag | Resolves to | What it is |
|---|---|---|
| `lemondrop-api:rollback-20261014T232428Z` | `sha256:f5f08cd5…` | **The original legacy image — INTACT.** The M3-era image built on the host survived every deploy and rollback, exactly as `docs/deployment.md` §6.4 says it must |
| `lemondrop-api:rollback-20261014T232546Z` | `sha256:34dfc69d…` | The **first published release** |

The first row is the load-bearing one. §6.4 warns that on a legacy host the rollback target is
a **local tag with no copy anywhere else**, so if it had been pruned the pre-publication state
would have been unrecoverable. **It was not pruned, and that is now an observation rather than
a hope.**

### 9.2 Manifest digest vs image config ID — two hash kinds, by design

**This is not a defect and it is recorded so nobody files it as one.**

| Value | Kind | How it is read | Where it lives |
|---|---|---|---|
| `sha256:6036f724…` | **Manifest digest** | The registry's content address for the artifact | `IMAGE_DIGEST` in the record |
| `sha256:34dfc69d…` | **Image config ID** | `docker inspect .Image` — the ID of the image object | Read back at runtime |

**They are different hash kinds for the same artifact,** and neither is a corrupted copy of the
other. A manifest digest covers the manifest — the index of layers; a config ID covers the
image configuration object. Seeing two different `sha256:` values where one was expected is the
system working as designed. **The record stores the manifest digest because that is the thing a
registry can be asked to reproduce** — it is what `image_repo_digests()` returns
(`deploy-lib.sh:497-501`), and that is what §6's Q3 proved is populated.

**The practical consequence, since it will confuse the next reader:** a record's `IMAGE_DIGEST`
and a `docker inspect .Image` value are **not** expected to be equal, and no check in this
repository compares them to each other. `verify-deployment.sh` compares the record's digest
against `RUNNING_DIGESTS` (`:172`), not against `.Image`. Both §6 and §9 exist partly so the
next person does not "fix" this.

### 9.3 Final verification

**SSM `97f3ed0e-ed62-42a0-b273-b270d45db4ef` — SUCCESS, exit 0.** The final restored state:

| Check | Result |
|---|---|
| Digest | **AGREE** |
| Provenance (revision label vs record) | **AGREE** |
| Schema (`ALEMBIC_HEAD`) | **AGREE** |
| Readiness | **HTTP 200** |
| Semantic search | **PASS** |

Three independent `AGREE` verdicts and two passing functional checks, on a host that had been
adopted, deployed, deployed again, rolled back and verified. **This is the strongest evidence in
this document**, and §12 is the list of what it does not mean.

## 10. What §9's five green verdicts do not mean

Stated immediately after the green rows, because separating them is how a verification record
starts lying.

1. **Every one of them was produced by the engineer who built the system.** The acceptance
   criterion is about someone else. §13.
2. **The legacy rollback branch was never executed** and is known-defective. §12.2.
3. **A `PREVIOUS_IMAGE_DIGEST` that names the running image was produced and not repaired.**
   §8.2. **The final `AGREE` on digest does not retroactively validate that field.**
4. **No test suite has ever invoked any of the three mutating scripts.** §12.3.
5. **`UNPINNED (LEGACY)` appeared on this host** and is a designed third verdict, not a pass.
   §7.3.

## 11. PARTIAL

Two items. Neither is rounded up.

### 11.1 PowerShell 5.1 compatibility

**`scripts/diagnose.ps1` targets 5.1 syntax and avoids `#requires 7.0`. That is the whole of the
positive claim.**

**Windows PowerShell 5.1 does not exist on Linux and WAS NEVER EXECUTED.** All execution and
all testing was on **PowerShell 7.4.6 on Linux**. Not one line of that script has been run by
the interpreter it targets.

**This is stated plainly and is not softened by the green test count.** The 34 passing tests
(§4) are 34 tests passing on 7.4.6. The file's own header says the same thing and says why it
matters — `diagnose.ps1:39-54`, *"EXECUTED: PowerShell 7.4.6 on Linux … WRITTEN FOR BUT NOT
EXECUTED: Windows PowerShell 5.1. It cannot run on Linux at all, so nothing in this file has
been proven to work on it"* — and then names the constructs that differ:

- **report encoding** — 5.1's `Out-File` defaults to UTF-16LE, so the report is written with
  `[System.IO.File]::WriteAllText` and an explicit `UTF8Encoding($false, no BOM)`; `Out-File` is
  never used;
- **non-2xx handling** — 5.1's `Invoke-WebRequest` **throws** on a 503, which for a diagnostic
  is the normal case and a finding rather than a crash, so the status code is read out of the
  caught exception's `Response`;
- **`-UseBasicParsing`** everywhere a 5.1 parse of HTML could matter.

**The 503 path is the sharp end of this and it is covered by a test** (`test-diagnose.ps1`,
per the header) — **on 7.4.6**. A 5.1-specific parser refusing the script outright is not
hypothetical; it is the ordinary failure mode of writing for an interpreter you cannot run.

**Two further limits, both from §4 and both the same shape:** `pwsh` is not installed in the
environment this record was written in, so the PowerShell half could not be re-run here at
all; and `scripts/test-diagnose-parity.sh` — whose entire job is cross-language parity —
**executed the Bash half and skipped the PowerShell half** when run locally.

**What would close this item:** one execution of `scripts/diagnose.ps1` and
`scripts/test-diagnose.ps1` on a real Windows host under Windows PowerShell 5.1. **That has not
happened.**

### 11.2 Runbook freshness — corrected at `667e7ad`

**PARTIAL, and only just.** The adoption command in `docs/deployment.md` now **requires the
operator-verified database head** (§7.1, Appendix A) rather than carrying a default. That
correction landed in **`667e7ad`**, *"docs(deployment): the adoption command refuses without a
database head"*, and it is the change that makes §7.2's `--adopt-current 0001` legitimate
rather than convenient.

**Why it is PARTIAL and not VERIFIED.** The correction is **verified as committed and
self-consistent**; it is **not verified as sufficient**. Two things stand between it and
`VERIFIED`, and neither is closed:

- **It was not verified against a host whose head differs from `0001`.** The command was used
  exactly once, with `0001`, which §5 independently confirmed — so the refusal behaviour was
  never exercised. **The guard that matters most is the one that has never fired.**
- **The rest of the runbook's freshness is not claimed.** §7.1 addresses the adoption argument.
  Whether every command in `docs/deployment.md` reflects the current state of every script is a
  larger question, and §12.6's neighbour problem (no shellcheck over the scripts) is part of it.

## 12. UNTESTED — unsoftened

Six items. None of them has a mitigating "though".

### 12.1 The second-engineer acceptance criterion

**UNTESTED. This is the item the milestone turns on, and §13 treats it at length.**

Every operational result in §5 through §9 was produced by **the engineer who built the system**.
**No second party has followed the runbook. No second engineer's session transcript exists.**
Read §13 before treating any of this as closing the criterion.

### 12.2 The legacy rollback branch

**Never executed. Known-defective.** `docs/deployment.md` §10 item 15 is the full statement;
the short form is that the branch re-tags the rollback target as `lemondrop-api`
(`rollback.sh:238`) and then **removes** `API_IMAGE` from `.env` (`rollback.sh:265-281`), on a
rationale at `rollback.sh:229-233` that compose will "resolve the `lemondrop-api` name again"
— which was true when the compose default *was* that name and is false now that the default is
a digest pin (`docker-compose.yml:436`). The branch's identity check inspects **the tag**
(`rollback.sh:246`), never the container compose started, and on a record with no `IMAGE_ID`
that check is **skipped entirely** (`rollback.sh:248`).

**It can start an image that is not the rollback target and still pass readiness and the
known-good search, because `verify_stack()` (`deploy-lib.sh:1093-1104`) is content, not
identity.**

**Do not rehearse it until it is fixed.** Fixing it is out of scope for this milestone.

### 12.3 The mutating scripts have no automated tests

**`deploy.sh`, `rollback.sh`, `verify-deployment.sh` and `deploy-lib.sh` control flow is
unexercised by any test suite.** No file under `scripts/` **invokes** any of them and no
workflow runs them. Their **first live use was this milestone.**

**One qualification, and it is the one `docs/deployment.md` §10 item 1 already makes
precisely:** `scripts/diagnose.sh` **sources** `deploy-lib.sh` — the same three lines
`verify-deployment.sh` uses — so its `LEMDROP_*` defaults, its `readonly EX_*` constants and
the `log`/`say`/`die` definitions **load** on every pull request, and the three functions the
diagnostic actually calls execute. **Sourcing a file defines functions; it does not run them.**
No function body that touches Docker, the lock, the record or the network has been called by
anything: not `known_good_search`, `verify_stack`, `wait_for_ready`, `restore_previous`,
`env_restore`, `api_container_id` or `record_is_valid`. **`verify_stack()` is the function
`deploy.sh:931` and `rollback.sh:376` both call, and it has never run in CI.**

This is stated as a live risk, not a technical footnote. It means §5 through §9 are the
**entire** evidence base for the deploy path, that evidence is one engineer's, and that a
regression in any of these scripts would reach a running host before any CI job noticed.
`docs/deployment.md` §10 item 1 carries the same fact from the other direction; its item 15
note narrows the "never executed" claim to what is still true.

### 12.4 The diagnostic report artifact

**The live-host report was produced and not retained.** §7.4: written on the EC2 host by
`scripts/diagnose.sh`, containing the three-container health check, database readiness, and the
`/health/live` and `/health/ready` results.

**It is not in this repository and no reader can re-read it.** What §7.4 records is the
**operator's summary of its contents**. If that report is wanted as evidence, it must be
copied off the host before the next deploy overwrites it — **and it was not.** The evidence
here is a report about a report.

### 12.5 ALB idle timeout (60 s) vs worst-case `/search` (~240 s)

**Unresolved. Outside M4's scope, and M4 did not change it.**

The API's `INFERENCE_TIMEOUT_SECONDS = 120` is a **per-inference-call** budget, and `/search`
makes **two sequential calls** — embed, then rerank — so worst-case request time is roughly
**240 s** against a **60 s** ALB idle timeout. **The ALB gives up first.**

**Carried forward unchanged** from `docs/verification-milestone-3.md` §10.8 and §12.4 item 4,
and restated at `docs/deployment.md` §10 item 4, where it remains open. **No latency
distribution was measured in this milestone**, so nothing here narrows it. **It is a known
configuration defect that is still a known configuration defect.**

### 12.6 No `shellcheck` job over `scripts/*.sh`

**There is no such job.** `actionlint` (CI job 3) covers the **workflows**, and it covers the
`run:` blocks inside them — `.github/workflows/hygiene.yml:584`. **It does not read a single
line of `scripts/*.sh`.**

So the shell scripts that this milestone's entire deploy path runs on have **no static
analysis whatsoever**, which is a large part of why §12.3 has to be stated as a live risk
rather than a historical one. The diagnostics are syntax-checked as part of job 2's *"syntax and
self-test"* step; `deploy.sh`, `rollback.sh`, `verify-deployment.sh` and `deploy-lib.sh` are
not, and no equivalent exists for them.

## 13. The M4 acceptance criteria

### 13.1 The second-engineer criterion — UNTESTED, and the wording is genuinely ambiguous

**The criterion, as written.**

> *"A second engineer must be able to deploy a tested revision without manually reconstructing
> the original environment."*

**That text is recorded here because the document it was written in is now tracked in
this repository.** `docs/m4-plan.md` is **tracked** — `git ls-files docs/m4-plan.md`
lists it, and it was committed in `0e2761c` ("docs: preserve the M4 and M5 acceptance
records") on 2026-10-17 — so a clean clone of this repository contains it. Every
tracked file that cited it by line number, **including this one**, now resolves to a file
a second reader can reach. **So the sentence is recorded here, in a tracked document,
and this section is its home.** `docs/deployment.md` §6.5 cites this section rather than
a file that is not there.

**The operationalisation of the same sentence, as written:**

> **Verified — this is the acceptance criterion, and it must be tested by someone other than the
> author.** A second engineer, given only the runbook and repo access, deploys a SHA-tagged
> revision **without asking a question**, then rolls back, then confirms `/health` and a
> `/search` that returns correct results. **If the author runs this test themselves, the
> criterion is not met** — it is the definition of "without manually reconstructing."
>
> **Done when:** the acceptance sentence is true, witnessed by someone else.

Quoted rather than paraphrased for the same reason, and because *"without asking a
question"* and *"if the author runs this test themselves"* are the operative words: they
are what make the test a test.

**What actually happened, stated without softening.** **No second party has followed this
runbook.** There is no second engineer's session transcript, because there was no second
engineer. Every result in §5 through §9 — adoption, deploy, verification, rollback, re-verification
— was produced by **the engineer who built the system**, which is the one thing the
operationalisation above names as failing the test: *"if the author runs this test themselves,
the criterion is not met."* **By that test's own terms, the criterion is NOT MET.**

**One term in it was undefined until this revision, and that is a documentation finding of
its own.** *"a tested revision"* had no operational meaning anywhere in this repository.
`docs/deployment.md` **§3.4 now defines it**, as three things that must hold together: a
commit that reached `main` and produced a successful release run; the registry manifest
digest that run's `publish` job published, obtained from the run's evidence (§3.3 there); and
the source revision and validated schema label the image itself carries. **§3.4 also records
an observed trap** — a local commit that has not been pushed has **no published image at
all**, which is exactly the state the revision under test for the cold-reader walkthrough was
in. The criterion's central term is now defined, and it was not defined when the walkthrough
was run against it.

**The ambiguity, stated rather than resolved.** Three things are in tension and this record does
not pick a winner:

1. **The criterion sentence is about a capability, not about an event.** Read literally, *"a
   second engineer **can** deploy"* is a claim about what the runbook and tooling make
   possible. **Nothing in §5 through §9 demonstrates that capability**, because a capability
   claim about a person requires that person to exercise it. Whether the milestone demands the
   capability be *demonstrated* or merely *documented* is exactly what the restatement in item 2
   settles and the original sentence does not.
2. **The criterion was already flagged as weaker than it reads** — before any of this happened,
    by the same untracked plan (**2026-10-22 correction — SUPERSEDED:** `docs/m4-plan.md` was
    committed in `0e2761c` on 2026-10-17 and is now tracked; "untracked" is false as written),
    which is where the quoted text below comes from: *"The acceptance criterion is therefore
    weaker than it reads"*, with a recommended restatement as *"A second engineer can deploy a
    tested revision to the running environment without manually reconstructing the original
    deployment steps."* **The ambiguity is pre-identified there, not manufactured here.** Note
    what the restatement changes: **"the original deployment steps"**
    rather than **"the original environment."** Under the restated criterion, the walk-forward
    path — `terraform apply` and a from-zero rebuild — is excluded, and **`docs/deployment.md`
    §10 item 18 records, in a tracked document, that this path has never been walked end to end
    from zero.** That fact existed only in the untracked plan (**2026-10-22 correction —
    SUPERSEDED:** `docs/m4-plan.md` was committed in `0e2761c` on 2026-10-17 and is now tracked;
    "untracked" is false as written); it is now recorded where a reader can reach it.
3. **A command-identification exercise would not close it either.** Even if a second party
   later reads the runbook and names the right commands, that is evidence they can *find* the
   commands. **The criterion is about executing a deployment**, and a correct command list
   produced by someone who was told what to look at is not a deployment. **Identifying the
   command is not performing the deploy.**

**What this record will not do.** It will not resolve the ambiguity by picking the reading
under which the milestone passes, and it will not resolve it by picking the reading under which
it fails. **The status is UNTESTED and the ambiguity is recorded alongside it**, and closing
the criterion requires a decision from the operator about which sentence governs, followed by
the execution that sentence demands.

**What would close it, under the operationalisation quoted above:** a second engineer, given
only the runbook and repository access, deploying a SHA-tagged revision without asking a
question, rolling back, and confirming `/health` and a correct `/search` — with their session
transcript, the before/after `DEPLOYED_REVISION`, and the rollback result. **None of those
three artifacts exists.**

**One precondition on that, which this record did not previously state.** `docs/second-engineer-acceptance.md`
§3 specifies two variants and **does not choose between them** — the decision is the assessor's
and it is open. Under a **live deployment demonstration** the test ends in a rollback, and
`docs/deployment.md` §6.5 instructs the operator to rehearse rollbacks **on a throwaway host
that this repository never describes**. That gap is now recorded conditionally, as
`docs/deployment.md` §10 item 17: it does not block a read-only walkthrough, and it blocks a
live one. **It is a precondition on closing this criterion, and it is not a documentation
problem any more — it is an infrastructure one, and nothing in this pass creates a host.**

### 13.2 Requirement coverage

| Area | Criterion status |
|---|---|
| CI, tests, dependency audit, Terraform, image publish | **VERIFIED** — §3 |
| Diagnostics, both languages | **VERIFIED** — §4 |
| Host checkout and verified database head | **VERIFIED** — §5 |
| Engine compatibility for the identity claims | **VERIFIED** — §6 |
| Adoption of the legacy host | **VERIFIED** — §7 |
| Digest-pinned deploy and verification | **VERIFIED** — §8.1 |
| Real rollback by digest | **VERIFIED** — §9 |
| **Redundant-deploy guard** | **UNTESTED — the guard does not exist** — §8.2 |
| **Legacy rollback branch** | **UNTESTED, known-defective** — §12.2 |
| **Second-engineer acceptance criterion** | **UNTESTED** — §13.1. **The criterion text is recorded in this section, because the document it came from is untracked.** *(2026-10-22 correction — SUPERSEDED: `docs/m4-plan.md` was committed in `0e2761c` on 2026-10-17 and is now tracked; "is untracked" is false as written.)* |
| **What "a tested revision" is** | **DEFINED, after the walkthrough found it undefined** — `docs/deployment.md` §3.4 |
| **A throwaway host to rehearse a rollback on** | **NONE DESCRIBED** — `docs/deployment.md` §10 item 17, conditional on the variant |
| **Provisioning the stack from zero** | **NEVER WALKED END TO END** — `docs/deployment.md` §10 item 18 |

## 14. Repository commits

The commits this milestone consists of, oldest first. **Read `git rev-parse HEAD` on the day you
need the current one** — `docs/deployment.md` §10 item 9 explains why no SHA is named there,
and the same reasoning applies to the list below.

| Commit | Subject |
|---|---|
| `84c0c36` | `fix(compose): stop the api from being silently built, and pin what it runs` |
| `05d37bb` | `ci: label the published image with its revision and its alembic head` |
| `d2007b2` | `fix(ci): remove a literal empty expression that broke workflow compilation` |
| `952c5ba` | `ci: lint the workflows, and make hygiene a three-job gate` |
| `bad5e38` | `fix(ci): actionlint args reach docker as argv, so the quotes were literal` |
| `25e072f` | `feat(deploy): scripted deployment and rollback by registry digest` |
| `52b02f4` | `docs(deployment): answer the GHCR visibility question with the evidence` |
| `09cf02d` | `fix(deploy): three false claims about the running image, and one blocker` |
| `667e7ad` | `docs(deployment): the adoption command refuses without a database head` |
| `35bada8` | `ci(gate): pip-audit as a blocking dependency gate` |
| `1eba3b6` | `feat(diag): two read-only cross-platform diagnostics, and the tests that hold the boundary` |

**`1eba3b6` is the milestone's head and the host's checkout (§5), and it is the head commit of
release run `38646911142` (§3).**

`52b02f4` is also the revision label of the deployed release in §8.1, which is a second thing it
is: the plan commit that closed the GHCR visibility question is also the code that shipped in
the image this milestone deployed and rolled back.

## 15. Re-check this record

**What a reader can re-check from this repository, today:**

```
gh run view 38646911142 --json conclusion,headSha,jobs
bash scripts/test-diagnose.sh
git log --oneline 84c0c36^..1eba3b6
```

The first two were both run while writing this record (§3, §4). The third is exactly §14's
eleven commits — **bounded at both ends**, so it does not drift as this document and the
documentation commits after it land.

**What a reader cannot re-check, and must take on trust or go to AWS for:** everything in §5
through §9. Those results live in SSM command invocations — `c071e162-…`, `ffd75853-…`,
`f3a94a3f-…`, `92810aaf-…`, `3aa89e7e-…`, `4450c9b0-…`, `97f3ed0e-…` — and each is named so it
can be looked up with `aws ssm get-command-invocation`. **That is a lookup into history, not a
re-run**: re-running any of them would mutate a live host, which is exactly what this document
must not ask a reader to do casually.

**And the last thing a reader should take from this document.** The deploy tooling works: it was
run against a real host, it recorded what it actually found, it rolled back, and it kept a
manifest digest and an image config ID distinct without mistaking one for a corrupted copy of
the other (§9.2). **What has not happened is anyone else using it.** §13.

---

## 16. Post-remediation addendum — 2026-10-21

This section records the state of the M4 deliverables after the remediation work described in
`~/lemondrop-investigation/REMEDIATION-AND-VERIFICATION-REPORT.md` and
`~/lemondrop-investigation/LOCAL-VERIFICATION-REPORT.md`, and after the production deploy/rollback
rehearsal captured in `~/lemondrop-investigation/PHASE-A-DEPLOY-EVIDENCE.txt` and
`~/lemondrop-investigation/PHASE-B-ROLLBACK-EVIDENCE.txt`. It supersedes the earlier statuses below
**without erasing** the original sections, which were true when written.

### 16.1 Redundant-deploy guard

The redundant-deploy guard is now implemented in `scripts/deploy.sh` and is regression-tested by
the stubbed harness `scripts/test-deploy-rollback.sh` (section `[2]`). The guard compares the
target digest to the recorded `IMAGE_DIGEST` and refuses with `EX_REFUSED` before any tag, pull,
`.env` write, or service recreation. It was **not rehearsed against a real host**; the evidence is
the stubbed harness only.

Witness: `scripts/test-deploy-rollback.sh` lines 152–173;
`~/lemondrop-investigation/REMEDIATION-AND-VERIFICATION-REPORT.md` §3.2 and §8.

### 16.2 Legacy rollback branch refusal

The legacy M3-era rollback branch in `scripts/rollback.sh` now refuses at the top with
`EX_REFUSED` before any mutation. The stubbed harness asserts that the branch cannot silently
resolve to the digest-pinned compose default and that `.env` is not stripped. It was **deliberately
not run live**.

Witness: `scripts/test-deploy-rollback.sh` lines 184–200;
`~/lemondrop-investigation/REMEDIATION-AND-VERIFICATION-REPORT.md` §3.3 and §8.

### 16.3 Deploy/rollback test coverage and assertion count

The deploy/rollback/verify regression suite is `scripts/test-deploy-rollback.sh`. The script's
count is **environment-dependent** because of a conditional shellcheck block:

- 19 functional assertions (`check`, `has`, `hasnt`) in sections `[2]`–`[5]`;
- 4 `bash -n` syntax assertions in section `[1]`;
- a conditional shellcheck block that contributes **4 assertions** when `shellcheck` is installed,
  or **1 skip assertion** when it is not.

Therefore:

- In an environment **without** shellcheck, the script reports **24 passed**.
- In the CI environment that pins **shellcheck 0.11.0**, the script reports **27 passed**.

`~/lemondrop-investigation/LOCAL-VERIFICATION-REPORT.md` §6 and
`~/lemondrop-investigation/REMEDIATION-AND-VERIFICATION-REPORT.md` §3.5/§5 record the **24 passed**
run and explicitly note that shellcheck was not installed locally. That is accurate for the
environment in which they ran.

`~/lemondrop-investigation/HANDOFF-20261021.md` §3 states "27 assertions" without noting the
environment dependency. That figure is correct only when shellcheck is present. Because the
repository's CI workflow installs shellcheck 0.11.0 immediately before running the script
(`.github/workflows/tests.yml` lines 590–605), 27 is the expected count in CI. A captured CI run
record for this job **does exist**: `~/lemondrop-investigation/SHELLCHECK-REPRODUCTION.txt` §5 cites
CI run **39031189284** and reports counts of **23 passed, 4 failed**, exactly matching the local
reproduction with shellcheck 0.11.0. The record is a captured reproduction artefact, not a retained
CI job-log download, so it establishes that the job ran and what its counts were, not that the full
CI log is retained. This discrepancy is recorded here rather than promoted to a green claim.

Method: manual line-by-line count of every `check`, `has`, `hasnt`, `ok`, and `bad` call in
`scripts/test-deploy-rollback.sh`, treating the `for` loops as one call per iteration.

### 16.4 ShellCheck in CI

ShellCheck is pinned to **0.11.0** in the CI workflow (`.github/workflows/tests.yml` lines
590–600). The same job runs `scripts/test-deploy-rollback.sh`, whose conditional shellcheck block
exercises all four deploy/rollback scripts (`deploy.sh`, `rollback.sh`, `verify-deployment.sh`,
`lib/deploy-lib.sh`) when shellcheck is present. A captured CI run record **does exist**:
`~/lemondrop-investigation/SHELLCHECK-REPRODUCTION.txt` §5 cites CI run **39031189284** with counts
**23 passed, 4 failed**, matching the local shellcheck 0.11.0 reproduction. The record is a captured
reproduction artefact, not a retained CI job-log download; it is evidence the job ran with those
counts, not that the full CI log is retained.

### 16.5 Production deployment

The deployed image as of the 2026-10-22 release is:

| Field | Value | Source |
|---|---|---|
| Image digest | `sha256:c2c1d81c5e743fb8b92b6b9e244179441c345d9441341e525d8d6865dfab39d4` | `~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §VERIFY (revision record) |
| Source revision | `6cc54bc4c09182e37575c5fedb2ad57c71dc7d58` | image OCI label; `~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §VERIFY (labels on the image) |
| Alembic head | `0001` | image OCI label; `~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §VERIFY (labels on the image) |
| `verify-deployment.sh` | exit 0, verdict AGREE/PROVENANCE AGREE/SCHEMA AGREE | `~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §VERIFY (AGREE verdicts) |

Witness: `~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §DEPLOY and §VERIFY (the
2026-10-22 deploy command, the image it pulled, and the post-deploy verification record).
`~/lemondrop-investigation/HANDOFF-20261021.md` §2 and the PHASE-A/PHASE-B artefacts in the
same corpus record the earlier M4-cycle image (`sha256:8cf759f6…` / `6b37a78…`) and are not
the witness for the 2026-10-22 image in the table above.

### 16.6 Rollback rehearsal

A real rollback was rehearsed on 2026-10-17 and the old image was proven to have run.

- Rollback target: `sha256:6036f7247fbb1f4bb7af8b6d88d80345df2c133c7005edba0dcfcd003d73dbc1`
  (SSM Step 7, command `8af4b275-b721-4a06-b7d8-21342ef5bdde`, exit 0).
- The old image came up healthy: `/health`, `/health/live`, `/health/ready` all HTTP 200, and
  `POST /search` returned `support-recycle-bin-file-recovery` first (SSM Step 8,
  `b6eee8d2-a29a-451a-8eb9-cf4125ab7c51`, exit 0).
- **Decisive behaviour flip:** on the old image, a 2049-character `POST /embed` request returned
  HTTP **502** with the worker-internal detail
  `"input (1026 tokens) is too large to process... current batch size: 512"`. The repaired image
  returns HTTP **422** for input over 2048 characters and does not echo worker internals.
  This flip proves the old image actually ran during the rehearsal.
- Step 8 retry: the first attempt to print the OCI labels failed with
  `template parsing error: template: :1: bad character U+0024 '$'`; a separate Step 8 retry
  (`843420d7-bb2e-4fc4-adba-e398956d1d37`) successfully captured the old image revision label
  `1eba3b600f1551868318e401d9479a27298c8a35` and Alembic head `0001`.
- The repaired image was redeployed (SSM Step 9, `424a2391-2beb-45f3-ba7c-fbfe1a85a83b`, exit 0)
  and final verification passed (SSM Step 10, `ad370083-40be-4313-bd0f-1675c7462f0d`, exit 0).

Witness: `~/lemondrop-investigation/PHASE-B-ROLLBACK-EVIDENCE.txt` §2–§7;
`~/lemondrop-investigation/HANDOFF-20261021.md` §2.

### 16.7 Limitations preserved

Both limitations that keep M4 open are unchanged by this addendum:

1. **Second-engineer criterion — UNTESTED and NOT MET.** No independent second-engineer transcript
   exists. The operator-directed, agent-executed rehearsal recorded here does not satisfy the
   criterion as operationalised in §13.1.
2. **Public-ALB health check from the authorized workstation was NOT performed by the agent during
   the M4 cycle.** That check was performed on **2026-10-21** during the client-perspective phase
   and is recorded in `docs/verification-milestone-5.md`, not as M4 evidence.

### 16.8 Evidence index

This addendum draws on the following witness files:

- `~/lemondrop-investigation/HANDOFF-20261021.md`
- `~/lemondrop-investigation/PHASE-A-DEPLOY-EVIDENCE.txt`
- `~/lemondrop-investigation/PHASE-B-ROLLBACK-EVIDENCE.txt`
- `~/lemondrop-investigation/REMEDIATION-AND-VERIFICATION-REPORT.md`
- `~/lemondrop-investigation/LOCAL-VERIFICATION-REPORT.md`
- `scripts/test-deploy-rollback.sh`
- `.github/workflows/tests.yml`

### 16.9 Cross-reference added after the M4 cycle — 2026-10-21, updated 2026-10-22

**This note adds a cross-reference only; it does not alter any M4 status, any
witness above, or the two limitations preserved in §16.7.**

The image that was current immediately before the 2026-10-22 release — digest
`sha256:8cf759f688daad5c5fbcc8a4efb6101de1de0f8efdf18c70e6aa7a8cd99f6110`, source
revision `6b37a780e293003ba952c3e9062e8c5d126639e9`
(`~/lemondrop-investigation/RELEASE-DEPLOY-EVIDENCE.txt` §VERIFY,
`PREVIOUS_IMAGE_DIGEST` / `PREVIOUS_REVISION`) — was found, **after the M4 cycle**,
to carry a **CRITICAL defect in `/search`**: a `POST /search` request with a query of
exactly 2048 characters returned an opaque HTTP 500 (`Internal Server Error`,
`text/plain`). The fix for this defect (candidate fault **E5**, root cause confirmed)
was released and deployed on 2026-10-22 as image
`ghcr.io/fvitorino00/lemondrop-api@sha256:c2c1d81c5e743fb8b92b6b9e244179441c345d9441341e525d8d6865dfab39d4`
(source revision `6cc54bc4c09182e37575c5fedb2ad57c71dc7d58`) by GitHub Actions run
39708332804, with deploy command `b402a174-72b3-4422-8100-e45033b08aa4` and verify
command `4adcb66f-0b11-40f5-a638-33f35b7408b4`, both exit 0. The deployed service now
refuses a 1992-to-2048-character query at the edge with HTTP 422 naming `query` and
`max_length: 1991`. The full symptom capture, fix record, deployment evidence and
post-release walkthrough are in `docs/verification-milestone-5.md` §8. **No M4 status
above is changed by this defect or its remediation; M4 remains subject to the
limitations in §16.7 exactly as recorded.**