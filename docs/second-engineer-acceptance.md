# Second-Engineer Acceptance — Verification Protocol

> ## ⚠️ **NOT YET TESTED. NO REVIEWER HAS BEEN IDENTIFIED. NO PROCEDURE HAS BEEN RUN. NO EVIDENCE EXISTS.**
>
> This document is a **protocol and an empty evidence template**. It is not a result.
> **Nothing in it has been observed.** Every field that would hold an outcome — the
> reviewer's name, the revision under test, the digest, the command list, the
> questions asked, the verdict — is **blank, and is blank on purpose.** A blank field
> here is not an oversight to be filled in by the next reader; it is the state of the
> world.
>
> **Status: UNTESTED.** That is the classification, in the vocabulary this repository
> uses (`docs/verification-milestone-4.md:92`). It means no check was run and none is
> implied.
>
> | Fact | State |
> |---|---|
> | Protocol authored | 2026-10-15 |
> | Reviewer identified | **None. No person has been approached.** |
> | Variant selected | **Undecided — see §3. The decision is owed by the assessor, not by this document.** |
> | Procedure executed | **Never. Not in part, not on a throwaway host, not anywhere.** |
> | Evidence submitted | **None exists** |
> | Deployments performed for this test | **None** |
> | Rollbacks performed for this test | **None** |
> | Verdict | **NOT YET TESTED** |
>
> **Why this document exists.** `docs/verification-milestone-4.md` recorded every
> operational result in that milestone as produced by the engineer who built the
> system — `docs/verification-milestone-4.md:8-9`: *"No second party has followed this
> runbook."* The second-engineer acceptance criterion remained UNTESTED, and
> `docs/verification-milestone-4.md:571` is the record of why, including the
> observation that **the criterion's wording is genuinely ambiguous** and is recorded
> rather than resolved. This document is the protocol for closing that gap. **It closes
> nothing by existing.**
>
> **And what writing this document did and did not do.** No AWS call was made, no SSM
> `SendCommand` was issued, no deployment was performed, no rollback was performed, no
> test suite was run for this purpose, and nothing was pushed. The only repository
> operations were read-only inspections and this one new file.

---

## §0 — What this document is

**This document is the reviewer protocol, and it is self-contained.** The status
banner above and §1 through §12 are the whole of it — the brief, the procedure in §7,
the evidence forms, and the pass/fail criteria the work will be read against. **Nothing
a reviewer needs is outside it, and nothing has to be added to it before it is handed
over.** It is handed over whole.

**The evaluator's material is held separately, and is deliberately not in this
repository.** The answer key — what a correct answer looks like at each step of §7, the
warnings a reviewer should encounter, what a good result contains, and the operator's
own checklist for running the exercise — was extracted out of this file and now lives
outside the repository. **Its absence here is deliberate: a reviewer who can read the
answer key has not been measured.** If you are reading this document as a reviewer,
nothing is being withheld from you.

**The property this document must keep.** **No section below refers the reader to a
section outside this document for substance**, and **no section below contains a value
the reviewer is supposed to derive** — no commit SHA, no image digest, no CI run
identifier, no database revision, and no deploy, verify or rollback command line. If you
find yourself wanting to add a clarifying sentence before handing this over, that
sentence is almost certainly an answer, and the correct response is to leave it out and
let the question surface in §9.

---

## §1 — Status

**UNTESTED.** Stated once here and repeated wherever a reader could otherwise mistake
this document for a record.

| Element | State |
|---|---|
| A second person has followed the runbook | **No** |
| A second person has deployed anything | **No** |
| A procedure has been derived from the repository by an independent reader | **No** |
| A reviewer has been identified or contacted | **No** |
| Any question has been asked of a reviewer | **No — §9 is empty and cannot be otherwise** |
| Any documentation gap has been catalogued | **No — §10 is empty** |
| Any verdict exists | **No — §12 is NOT YET TESTED** |

**The distinction this document exists to preserve.** `docs/verification-milestone-4.md`
established a great deal about the deploy path — that it runs, that it records what it
found, that it rolls back, and that it keeps a manifest digest distinct from an image
config ID. **None of that was established by anyone other than the system's author.**
The status of the *criterion* is therefore not "partially met"; it is **untested**, and
it stays untested however much adjacent machinery is verified.

## §2 — Objective

**What this test is for.** To establish, with evidence, whether an engineer who has
**no prior involvement with this system** can carry out a deployment of a tested
revision, and a verification of it, and a rollback of it, using **only what this
repository contains** — plus the credentials and access any operator would have.

**What it measures, precisely.** One thing, and it is the thing the criterion's wording
turns on:

> **How much of the procedure is derivable from the repository, and how much of it
> exists only in the author's head?**

Every question the reviewer has to ask the author is a measurement. Every value the
reviewer has to reconstruct mentally is a measurement. The pass/fail criteria in §11
are built entirely on that one quantity.

**What this test is explicitly NOT for.** Stated up front, because each of these is a
plausible way to misuse this document:

- **It is not a test of the deploy tooling.** Whether the deploy tooling works is a
  separate
  question with a separate record. This test measures the *documentation and the
  procedure*, and a reviewer who succeeds has succeeded at reading, not at deploying.
- **It is not a performance review, and it is not a skills test.** A reviewer who
  cannot follow the runbook has found a fact about the runbook. That is the result, not
  a personal failing, and §11 says so in the terms that make it stick.
- **It is not a substitute for reading the runbook.** If the answer is handed over in
  the brief, the measurement is destroyed and the result is worthless. That is why the
  answer key is held outside this repository (§0) and why §7 refuses to pre-fill any
  value.
- **It does not resolve which sentence of the criterion governs.** §3 keeps that open
  deliberately.

## §3 — The two variants

**Read this section before running anything.** The acceptance criterion is phrased as a
capability, and the plan operationalises it as an event. Those are not the same test,
and this document will not pick one for you.

**The criterion, as written**, at `docs/m4-plan.md:452-453`:

> *"A second engineer must be able to deploy a tested revision without manually
> reconstructing the original environment."*

**The plan's operationalisation of it**, at `docs/m4-plan.md:668-675`, requires a
second person to actually do it:

> **Verified — this is the acceptance criterion, and it must be tested by someone other
> than the author.** A second engineer, given only the runbook and repo access, deploys
> a SHA-tagged revision **without asking a question**, then rolls back, then confirms
> `/health` and a `/search` that returns correct results. **If the author runs this test
> themselves, the criterion is not met** — it is the definition of "without manually
> reconstructing."
>
> **Done when:** the acceptance sentence is true, witnessed by someone else.

**And the plan had already flagged the mismatch**, at `docs/m4-plan.md:821-824`, before
any of this was attempted: *"**The acceptance criterion is therefore weaker than it
reads.**"* Its recommended restatement is at `docs/m4-plan.md:826-827`:

> *"A second engineer can deploy a tested revision to the running environment without
> manually reconstructing the original deployment steps."*

**The difference between those two sentences is not cosmetic.** "The original
deployment steps" excludes the walk-forward and `terraform apply` path — a path the
plan itself records has never been walked end to end from zero
(`docs/m4-plan.md:823`). "The original environment" does not exclude it.
`docs/verification-milestone-4.md:571` §13.1 records this tension and explicitly
declines to settle it.

### Variant A — cold-reader walkthrough

The reviewer receives the repository access listed in §4 and **nothing else that is not
in the repository**. They then work out, unaided, the complete procedure for deploying,
verifying and rolling back a tested revision, and **write it down**. No deployment is
performed. Nothing on the host is touched. No AWS call that mutates anything is made.

- **What it tests:** whether the information needed to operate this system is
  **self-sufficient in the repository** — which is the clause *"without manually
  reconstructing the original environment."*
- **What it costs:** one person's time, and no infrastructure change whatsoever.
- **What it proves:** that the repository can be *read* into an actionable procedure by
  an unbriefed reader.
- **What it does not prove, and this must be stated every time an A result is
  reported:** ❗ **that a second person executed a live deployment. Nothing was
  deployed. Variant A is not evidence of a deployment, of a rollback, or of a
  verification — it is evidence about a page.**

### Variant B — live deployment demonstration

The reviewer executes the deploy, verification and rollback procedure against the real
host, having derived it themselves as in Variant A. They deploy a tested revision,
confirm readiness and a correct search, roll back, and confirm the restored state.

- **What it tests:** executability by an unbriefed party — that the derived procedure
  actually runs, that the scripts behave as the runbook says, and that the record the
  tooling writes is readable and true.
- **What it costs:** **an actual deployment and an actual rollback on a live host.** It
  changes host state. It consumes deployment history. It carries real risk: the deploy
  path's destructive branches have thin verification (§7), and one documented defect
  (below) will be encountered on the way.
- **What it proves:** that an unbriefed second person carried out a deployment, a
  verification and a rollback.
- **What it does not prove:** that the walk-forward / rebuild-from-zero path works. The
  criterion sentence and the plan's restatement disagree about whether that path is
  even in scope.

### ⚠️ The separation is not a formality — it is the whole point

**A Variant A result may never be reported as a Variant B result, and the reverse is
also not implied.** Specifically:

> ❗ **Variant A is NOT proof that a second person executed a live deployment.
> Variant B is the only one of the two that is. Neither result may be reported as the
> other, and a Variant A pass must never be written up in language that a reader could
> mistake for a completed deployment.**

This is not a drafting preference; it is the third leg of the argument already made at
`docs/verification-milestone-4.md:613-617`:

> *"**A command-identification exercise would not close it either.** Even if a second
> party later reads the runbook and names the right commands, that is evidence they can
> *find* the commands. **The criterion is about executing a deployment**, and a correct
> command list produced by someone who was told what to look at is not a deployment.
> **Identifying the command is not performing the deploy.**"*

Note the clause that bears directly on how this brief is written: *"produced by someone
who was told what to look at."* **A brief that names the commands would produce exactly
that — a correct command list handed over rather than derived — and the result would not
be evidence of anything.** That is why §7 names runbook *sections* and not commands.

### The variant decision is the assessor's, and it is still open

**This document does not select a variant, and it does not recommend one.** Selecting
one is a judgement about what the milestone's acceptance sentence requires, and it is
owed by the assessor (Moe) as the owner of the criterion. The decision has not been
made.

What this document owes the assessor instead is the following, and only this:

1. Both variants are specified completely enough to run (§7 is written for both).
2. The two are kept strictly separate, so that whichever is chosen, its result cannot
   be inflated into the other's.
3. §11 states pass/fail criteria for Variant A, and states — **conditionally, without
   choosing** — what would additionally be required if Variant B is the one selected.
4. The consequence of each choice is stated plainly above, so the decision is made with
   its cost in view.

**If the criterion is restated** in the form the plan recommends
(`docs/m4-plan.md:826-827`), say so in §12 before the exercise is run, and note it —
because the restated criterion names *deployment steps*, which bears on which variant
can satisfy it. **Do not restate it after seeing a result.** Deciding what the criterion
means after you know how it came out is how an ambiguous criterion gets quietly
resolved in whichever direction the result happens to point.

## §4 — Required access

Everything the reviewer needs, listed concretely. **The operator provisions these; the
reviewer does not discover them, and the reviewer must not be given anything beyond
this list as a hint.**

| # | Access | Detail | Carries a secret? |
|---|---|---|---|
| 1 | **Repository access, read** | The GitHub repository, at a pinned revision (§5). Read on Actions logs and job summaries, which §7 requires. | No |
| 2 | **AWS CLI v2, authenticated** | A named profile and a region. The runbook's own values are in `docs/deployment.md` §1.1 — **let the reviewer read them there.** | **Yes — credentials** |
| 3 | **SSM access to the instance** | `ssm:StartSession`, `ssm:SendCommand`, `ssm:GetCommandInvocation` against the EC2 instance. The instance has no SSH key and no public IP. The full permission set is in `docs/deployment.md` §1.2. | No — but grants host control |
| 4 | **RDS master secret, workstation-side** | Credentials for the RDS master user, reachable from the reviewer's own machine. Needed because the host **cannot** read the live database revision — the reviewer must establish it from outside the host. See `docs/deployment.md` §7.1. | ⚠️ **YES — highest sensitivity. Master database credential.** |
| 5 | **Local tooling** | `psql`, `curl`, `jq`, `docker` with Compose v2. `jq` and `psql` on the operator machine are already named in `RUNBOOK.md:10`. | No |
| 6 | **Either SSH or SSM Session Manager** | There is no SSH key and no public IP; SSM Session Manager is the normal route. `RUNBOOK.md:92`. | No — but grants host control |

> ⚠️ **SECRET HANDLING — items 2 and 4 are operator-provisioned and are never written
> into any document, including this one.** The RDS master credential (item 4) is the
> single most sensitive item in this list. It is provisioned directly to the reviewer
> through whatever channel the operator already trusts for credentials; **it does not
> appear in the brief, in the packet, in a commit, or in a transcript.**
>
> **If the reviewer's §9 log ever contains a credential — pasted, echoed by an error
> message, or included in a command line — that is an incident, not a data point.**
> Rotate it, and record the rotation in §10 as a process finding. Do not transcribe it
> into the evidence table.
>
> Item 3 and item 6 grant **control of a live production host**. For Variant A they are
> not needed at all, because Variant A deploys nothing — **provisioning them for a
> Variant A run is unnecessary privilege**, and the operator should say plainly whether
> they are being provisioned.

## §5 — Repository revision under test

**To be completed by the reviewer or the operator before the exercise begins. This
document does not name a revision, deliberately — see the note below.**

| Field | Value |
|---|---|
| Repository | *(to be completed)* |
| Commit SHA under test | *(to be completed)* |
| Date pinned | *(to be completed)* |
| Pinned by | *(to be completed)* |

**How to record it, and how to check it later.** Record the **full 40-character SHA**,
not an abbreviation — abbreviated SHAs are ambiguous across a long history, and an
ambiguous identifier cannot settle a dispute about what was tested. Record the date and
who pinned it, so that a later reader can tell a deliberate pin from an accident of
timing.

**Why this document names no SHA.** `docs/verification-milestone-4.md` §14 carries the
same discipline for the milestone's commit list: *"Read `git rev-parse HEAD` on the day
you need the current one."* A SHA written into a protocol document is stale the moment
it is written, and a stale SHA that looks authoritative is worse than a blank field.

**How to verify the pin afterwards.** The revision actually exercised must match the
revision recorded here. If the reviewer's checkout drifted mid-exercise, the two
records must disagree visibly rather than silently — and in that case the result
describes a test of something other than what this section says it tests.

## §6 — Reviewer details

**Blank. To be completed by the operator, from the reviewer's own statement, before
the exercise runs.** This section is not decorative: the final field is the one that
determines whether the result means anything.

| Field | Value |
|---|---|
| Reviewer name | |
| Role / team | |
| Date of the exercise | |
| **Prior exposure to this system** | |
| Prior exposure to this repository | |
| Prior exposure to this stack's tooling | |
| Variant performed | |
| Assessed by | |

**On the prior-exposure fields — the only question that matters is the fourth row.** If
the reviewer has previously read `docs/deployment.md`, has previously deployed this
stack, or was told any part of the procedure before the exercise, **the measurement is
compromised** and the result must be recorded as compromised rather than as a clean
pass. `docs/m4-plan.md:671-672` is the standard being applied here:

> *"**If the author runs this test themselves, the criterion is not met** — it is the
> definition of 'without manually reconstructing.'"*

A reviewer with incidental exposure is a weaker version of the same problem, not a
different one. **Record the exposure honestly and let the result be read against it.**
Do not approach a candidate with a briefing that creates exposure; the exposure is the
thing being measured.

## §7 — Test procedure

**This is the material the reviewer executes. For Variant A, steps 1–4 plus step 7 are
the exercise: the deliverable is the written procedure. For Variant B, every step runs.**

**No value is pre-filled in this section.** The digest, the source revision, the live
database revision and every command are for the reviewer to derive from the repository.
That is not stylistic reluctance — it is the measurement (§2). **A brief that supplies
the commands produces a correct command list handed over rather than derived, which
`docs/verification-milestone-4.md:616-617` says explicitly is not a deployment and is not
evidence.**

### Step 1 — Establish a read-only baseline

Establish what is currently running **before** anything else, using a method that
mutates nothing. The runbook's read-only baseline procedure is `docs/deployment.md`
**§4.2**, and the record it reads is described in **§4.6**.

- Record the deployed revision, the image digest, the alembic head and the rollback
  pointer as the baseline, **before** any change.
- **Record the rollback target explicitly and separately.** You will need it in step 6,
  and a redundant step in between can overwrite it — see the warning in step 4.
- Note the exit status of the baseline check. A non-zero exit is a **finding**, not a
  blocker: record it and continue, because a host that is already divergent is a
  legitimate thing for a second engineer to encounter.

### Step 2 — Determine the revision under test, and its digest, from repository and CI evidence

Determine which revision is being deployed and **what its registry manifest digest is**,
deriving both from evidence in the repository and its CI record. The runbook's
procedure for obtaining the digest for a given commit is `docs/deployment.md` **§3.3**,
and the surrounding sections **§3.1** and **§3.2** state the rules and the traps.

- **Establish it; do not copy it.** Values written down in this repository are recorded
  there as *worked examples and safe defaults*, and `docs/deployment.md` **§3.2** and
  **§10 item 8** both say in terms that a digest taken from a file in this repository is
  not an approved revision. If you deploy a digest you read out of a file rather than
  out of the release evidence, you have not done this step.
- **Confirm the digest is pullable on the day**, by the check in **§3.3**. Package
  visibility is a setting someone can change at any time; §3.3's check is the answer for
  a given day, and no document in this repository is.
- Note the two different hash kinds you will encounter and do not interchange them
  (**§3.3**). They are a recurring source of false conclusions.

### Step 3 — Determine the live database revision, independently

Establish the alembic revision the **database** is at, independently of the deploy
tooling and independently of the repository's git tree. The runbook's procedure is
`docs/deployment.md` **§7.1**; the underlying connection and migration mechanics are in
`api/alembic/README.md`.

- **The value must come from the database, not from the checkout.** The checkout answers
  "what schema does this code expect"; this step answers "what schema is the database
  at". Those differ whenever a migration was applied out of band, which is the normal
  way this schema moves.
- **You are reading it from outside the host, deliberately.** The host has no credential
  and no rights that would let it confirm its own schema head. §7.1 says so directly.
- ⚠️ **The runbook writes a value down at §7.1, and it is marked as an evidence record
  rather than a current fact.** **Re-read it from the database. Do not pass the
  runbook's value because the runbook prints it.** That instruction is in §7.1 itself —
  read it before you act on it, not after.

### Step 4 — Deploy

Deploy the revision and its digest established in step 2. The procedure is
`docs/deployment.md` **§4.3**, with **§4.4** for the arguments and what they buy you,
and **§4.5** for the ordered sequence of what the script does and what you will see.

> ⚠️ **Before you deploy anything: read `docs/deployment.md` §4.2.1.** There is a known,
> **unfixed** defect on this path. Deploying the digest that is **already running** is
> not a no-op: nothing in the script stops it, it runs to completion, it prints a green
> success banner and exits 0 — and it **destroys the rollback pointer** by writing the
> running digest into the field that names what to roll back to. The check is manual,
> because nothing performs it. **The green banner is not evidence that this did not
> happen.**
>
> This is a live hazard on this exact path, not a theoretical one — it occurred in
> practice during Milestone 4 and is recorded at `docs/verification-milestone-4.md:314`
> and `docs/deployment.md:1440` (§10 item 16). **For a Variant B run, the operator decides
> before the exercise whether to accept this risk; that decision belongs to the
> operator, not to the reviewer, and it is made here in advance rather than in the
> middle of the exercise.**

### Step 5 — Verify

Confirm the deployment is serving correctly. The procedure is `docs/deployment.md`
**§5**, with **§5.2** for the on-host checks against localhost and **§5.3** for ALB
reachability.

- **Run the checks from the context the runbook specifies, and understand why it
  specifies that context.** §5.1 is emphatic about it, and the reason is a real
  configuration mismatch in this stack that is **unfixed**. Verifying through the wrong
  path produces a failure that says nothing about the deployment, or a success that
  proves less than it appears to.
- **Do not treat a passing check as more than it is.** `docs/deployment.md` **§10** tells
  you what the checks are and are not; read it rather than inferring.

### Step 6 — Roll back

Roll back to the state recorded in step 1. The procedure is `docs/deployment.md` **§6**,
with **§6.1** for the invocation, **§6.2** for how the target is chosen, and **§6.3**
for what it does in order.

- **Record what the rollback selected and why**, before you run it. The target comes
  from the record, not from you.
- ⚠️ **There is a known, unsafe branch in the rollback script.**
  `docs/deployment.md:1401` (**§10 item 15**) is the record: the legacy branch **can
  start an image that is not the rollback target, and its own checks will not notice.**
  It has never been executed and **must not be rehearsed.** §10 item 15 and §6.4 say
  what to do instead. **If your rollback lands on that branch, stop and escalate — do
  not attempt to correct it in place, and do not re-run it.**
- Confirm the restored state afterwards, and confirm the record was not consumed — §6.3
  states what the rollback does and does not do to the record.

### Step 7 — The recovery path

Read and be able to state what to do when the procedure goes wrong. `docs/deployment.md`
**§7** is the recovery section; §7.1 through §7.5 cover the record being missing or
malformed, an interrupted deploy, a held lock, a failed verification, and an unknown
state.

**For Variant A**, step 7 is part of the written deliverable: a procedure that cannot
say what to do when a deploy half-fails is not a complete procedure. **For Variant B**,
read it before step 4, not after something breaks.

### Step 8 — Submit

Submit §6, §8, §9 and §10, filled in. **Submit the questions you asked, including the
ones you worked out yourself without asking** — a question you nearly had to ask is a
near-miss on the same measurement, and it is more valuable to the runbook's author than
a question you did ask.

**Submit a written record of the procedure you derived** (Variant A) or executed
(Variant B), in your own words and in your own order. **Do not tidy it afterwards, and
do not re-check it against a worked answer.** The gaps and the dead ends are the data.

## §8 — Evidence collection

**Empty. No evidence has been collected.** For each command or action the reviewer
performs, record one row. **Record the command as issued**, including the substitution —
a command redacted to hide a value cannot later be shown to have produced what it
produced.

| # | Command or action, as issued | Exit status | Verdict observed | Diagnostic report path |
|---|---|---|---|---|
| | *(no rows — nothing has been run)* | | | |

**Conventions for this table.**

- **Exit status** is the process exit code, not a description. If a command was not
  run, record why in the gaps section instead of leaving the cell blank.
- **Verdict observed** is what the tool printed, quoted or closely paraphrased — for
  example the comparison verdict the verification script emits. **If you cannot tell
  what verdict a command produced, that is the finding.**
- **Diagnostic report path** is the path of any report file the run wrote. The
  diagnostics write timestamped reports on the host; where they went is part of the
  evidence, and a diagnostic that was produced and then lost is a finding about the
  evidence trail, not a detail.
- **Nothing may be entered into this table by anyone other than the reviewer or the
  operator transcribing the reviewer's own record.** No row may be reconstructed,
  inferred, or filled in afterwards from memory.

## §9 — Questions asked

**Empty. No questions have been asked, because no reviewer has begun.** This table is
the primary measurement this document exists to take, and it is deliberately the one
with no rows.

| Question, verbatim | Who could answer it | Answerable from the repository alone? |
|---|---|---|
| *(no rows — the exercise has not been run)* | | |

**Record the question verbatim**, in the reviewer's own words, before it is answered
and before it is paraphrased into something tidier. A question that has been
reformulated by the time it is written down is no longer evidence of what the reviewer
could not find.

**The third column is the measurement, and it has exactly two answers:**

| Answer | Meaning |
|---|---|
| **Yes** | The repository contains the answer. The reviewer had to work, and the work was the test. **This is a PASS contribution.** |
| **No** | The answer existed only in the author's head, in an unrecorded terminal session, or in an unwritten habit. **This is a FINDING against the runbook** — see §11. |

**The middle column exists so that a finding can be routed.** "Only the author could
answer it" is a specific, fixable defect: it names the gap. "Nobody could answer it"
is a different and more serious defect — it names a missing piece of knowledge, and it
means the procedure is not merely undocumented but possibly wrong.

**Record questions the reviewer resolved without asking, in a separate note beneath the
table.** The distinction between *asked* and *almost asked* is the difference between a
clean pass and a runbook that is technically complete and practically hostile.

> ⚠️ **A question the operator answers is not a question the repository failed to
> answer — it is a question the repository failed to answer.** Record it in this table
> regardless of how quickly it was answered or how obvious the answer seemed.

## §10 — Documentation gaps found

**Empty. No gaps have been catalogued, because no reviewer has looked.**

**Convention for recording a gap.** One entry per gap, each with:

| Field | Content |
|---|---|
| **Gap** | What is missing or wrong, stated as an absence or a defect — not as a feeling |
| **Where the reviewer hit it** | The step in §7, and the question in §9 if there was one |
| **Severity** | **Blocking** — the procedure could not be completed without it · **Recoverable** — completed with difficulty, or with information from outside the repository |
| **Proposed fix** | What would have to be added to the repository, specifically enough to be actionable |

**Separate gaps from questions.** A question in §9 is something the reviewer asked. A
gap here is something **wrong or absent in the documentation that a question would
have exposed.** Many questions have no corresponding gap — the answer was in the
repository and simply took work to find — and recording those as gaps would inflate the
finding rate and make the real ones harder to see.

**A gap that is not documentation is still recorded here**, with a note that it is a
code defect rather than a documentation one. Some of the most important things a
reviewer will encounter on this path are **unfixed defects in the tooling**, not gaps in
the writing. §7's warnings name two of them. If a reviewer hits one, that is a finding
about the system and it belongs in this record.

## §11 — Pass / fail criteria

**Stated here, before any result exists, so that no criterion can be shaped after the
fact.** The pass/fail decision is made against this section as written, or not at all.

### The criterion under test

> *"A second engineer must be able to deploy a tested revision without manually
> reconstructing the original environment."* — `docs/m4-plan.md:452-453`

### PASS — all four must hold

1. **The reviewer produced the complete procedure from repository information alone** —
   deploy, verification and rollback, in an order they determined, without being told
   what to look at.
2. **Every required value was derivable from the repository and its CI record** — the
   revision under test, its digest, the live database revision, the recovery path. No
   value was supplied, confirmed, or corrected by the operator.
3. **Zero author-only questions.** §9 contains no row answered **No** in the third
   column.
4. **The reviewer's written record is complete enough to execute** — another competent
   engineer could follow it without reconstructing anything.

### FAIL — any one of these

1. **Any author-only question.** One is enough. See below.
2. **Any required value that could not be derived** from the repository and CI evidence —
   including the live database revision, which must be read from the database and not
   taken from the runbook's written-down value.
3. **The procedure is incomplete**, or could not be executed without information the
   reviewer did not have.
4. **The reviewer's result depends on prior exposure** (§6) that was not declared. A
   compromised run is not a pass; it is an unmeasured run, and it is recorded as such.

### ⚠️ A single author-only question disqualifies the pass

**One question answerable only by the author fails the exercise, regardless of how
confident the reviewer was, how much they managed, or how reasonable their workaround
was.** The reasoning is the criterion's own: *"without manually reconstructing the
original environment."* A procedure that required one question from the author is a
procedure that required reconstruction from a person, and the confidence surrounding the
other steps is not evidence about that one.

**And an author-only question is a finding about the runbook, not a complaint about the
reviewer.** It means a competent engineer following this documentation could not get
this far. That is a defect in the documentation, it is exactly what this test exists to
surface, and **it is worth more than a clean pass would have been.** A test that can
only fail the documentation when the documentation is genuinely incomplete is not
measuring anything.

**When an author-only question occurs:** record it (§9, §10), **fix the runbook so the
question has an answer in the repository, and re-run the exercise.** The re-run must be
with a reviewer who has not been exposed to the original run, since a reviewer who has
been told the answer once will not ask again — and the second run would then pass for
the wrong reason. **A pass obtained after the reviewer was helped is not a pass; it is
an unrecorded assistance.**

### If Variant B is the one selected — additional requirements, conditional only

⚠️ **This paragraph does not choose a variant.** It states what would additionally be
required **if** the assessor decides Variant B is the reading that governs, so that the
decision can be made with its consequences in view.

In addition to all four PASS conditions above, a Variant B pass additionally requires
that the deployment, the verification and the rollback **were actually executed**, that
the results are recorded in §8 with exit statuses, that the restored state was
confirmed, and that the host was returned to a known state.

**And it requires stating the thing Variant A cannot state:** that a second person
deployed, verified and rolled back. **Variant B is the only variant that can support
that sentence, and §12 must not contain it unless Variant B was run.**

## §12 — Final verdict

> ## ⚠️ **NOT YET TESTED**
>
> **No verdict may be recorded in this section until the exercise has actually been run
> by a real, identified reviewer.**
>
> This section is completed by the **assessor (Moe)**, not by the reviewer. It is
> included in the reviewer packet so that the reviewer can see exactly what is being
> measured and what standard their work will be read against — **but a reviewer may
> not fill it in, and a verdict entered by anyone who did not witness the exercise is
> not a verdict.**

| Field | Value |
|---|---|
| **Status** | **NOT YET TESTED** |
| Variant exercised | *(blank — undecided, §3)* |
| Reviewer | *(blank — none identified, §6)* |
| Date of exercise | *(blank)* |
| Revision under test | *(blank, §5)* |
| Author-only questions | *(blank, §9)* |
| Procedure derivation | *(blank)* |
| Deploy / verify / rollback executed | *(blank)* |
| Documentation gaps found | *(blank, §10)* |
| **Verdict** | *(blank — NOT YET TESTED)* |

**Before any verdict is recorded, these three things must be true. If any is false,
there is no verdict to record:**

1. **A named reviewer actually performed the exercise**, and §6 records their prior
   exposure honestly.
2. **§8 and §9 contain what that reviewer submitted**, transcribed rather than
   reconstructed.
3. **The assessor has stated which variant they are treating as governing** — or has
   stated that the criterion is being recorded as untested *despite* a variant having
   been run, because a demonstrated capability and a satisfied criterion are not the
   same claim and the record must say which one was produced.

**On the wording of any future verdict.** A verdict must name **the variant that was
run** and must not claim what that variant does not establish. Specifically:

> ❗ **If Variant A was run, the verdict may not state or imply that a deployment
> occurred.** It may state that a complete procedure was derivable from the repository
> by an unbriefed second party, and that is all it may state.

**The criterion's status after the exercise is the assessor's to record, and this
document's position on it does not change:** a capability claim about a person is
demonstrated by that person exercising it, and the criterion sentence and the plan's
operationalisation of it do not agree on whether that is required
(`docs/verification-milestone-4.md:571` §13.1). **Whichever variant is run, the
ambiguity is recorded rather than resolved, and the record says which reading the
verdict rests on.**

---

> ## Closing status, restated so it cannot be missed
>
> **This document is a protocol for a test that has not been run.**
>
> - **Status: UNTESTED.** No reviewer identified, no procedure run, no evidence
>   collected, no deployment performed, no rollback performed, no verdict.
> - **The criterion's ambiguity is recorded, not resolved** — see
>   `docs/verification-milestone-4.md:571` §13.1.
> - **Variant A is not proof that a second person deployed anything. Variant B is the
>   only one of the two that is.** Neither result may be reported as the other.
> - **Two known defects sit on this path**, both recorded and neither repaired: the
>   redundant-deploy guard that does not exist (`docs/deployment.md:1440`), and
>   the legacy rollback branch that can start the wrong image (`docs/deployment.md:1401`).
> - **Writing this document executed nothing.** No AWS call, no SSM command, no
>   deployment, no rollback, no test run for this purpose.