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

## §0 — How this document is split, and how to build the reviewer packet

**This document holds two different audiences' material, because the reviewer must be
briefed precisely and the evaluator must hold answers. The two are fenced, and the
fence is at a section boundary so that extraction is mechanical rather than a
judgement call.**

| Sections | Audience | Hand to the reviewer? |
|---|---|---|
| **§0 – §12** | **Reviewer-facing.** The brief, the procedure, the evidence forms, the pass/fail criteria | **YES — extract these** |
| **§13 – §17** | **Evaluator-only.** The answer key: what a correct answer looks like at each step | **NO — never provide** |

**The rule for producing the reviewer packet:** extract §0 through §12, **whole**,
and stop at the fence line before §13. Do not select sections individually. Do not
hand over the file. Do not paste §13–§17 into a message "just in case".

**What makes a clean packet.** Every section in §0–§12 reads correctly on its own
terms. **No section in the packet refers the reader to a section outside the packet
for substance**, and **no section in the packet contains a value the reviewer is
supposed to derive** — no commit SHA, no image digest, no CI run identifier, no
database revision, and no deploy, verify or rollback command line. If you find yourself
wanting to add a clarifying sentence while extracting, that sentence is almost
certainly an answer, and the correct response is to leave it out and let the question
surface in §9.

**§0 is the only section that discusses the split.** Every other reviewer-facing
section is self-contained without it.

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
  the brief, the measurement is destroyed and the result is worthless. That is why §0
  fences the answer key and why §7 refuses to pre-fill any value.
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

# ═══ EVALUATOR-ONLY — DO NOT PROVIDE TO THE REVIEWER ═══

> ## ⚠️ **EVERYTHING BELOW THIS LINE IS EVALUATOR MATERIAL.**
>
> **§13 – §17 are the answer key.** They record what a correct answer looks like at
> each step of §7, the warnings a reviewer should encounter, and what a good result
> contains.
>
> **They must not be provided to the reviewer, in any form** — not extracted, not
> summarised, not paraphrased into a "few hints", not read aloud during the exercise,
> and not used to help a reviewer who has stalled. **A reviewer who is helped has not
> been measured**, and a result produced that way is not evidence and must not be
> recorded as such.
>
> **The reviewer packet is §0 – §12, whole, and it stops here.**

## §13 — EVALUATOR ONLY — the answer key, step by step

**What a correct answer looks like at each step of §7.** Use this to mark the reviewer's
written procedure. **A reviewer who arrives at a different but correct route has
passed** — the runbook is not the only valid path, and marking down a correct
alternative route is how this exercise produces a false negative.

### Step 1 — baseline

**Correct:** `sudo /opt/lemondrop/scripts/verify-deployment.sh` (`docs/deployment.md`
§4.2), then read the record at `/var/lib/lemondrop/deployed-revision.env` (§4.6).
**Parse the record with `grep`/`sed`, never `source` it** — a record that gets
`set -a; . record` can set any variable it likes, and §4.6 says so.

**The comparison verdict has three possible values, not two**, and recognising all three
is part of a correct answer:

| Verdict | Meaning |
|---|---|
| `AGREE` | The record and the running image name the same thing |
| `DIVERGENCE` | They were compared and they differ |
| `UNPINNED (LEGACY)` | **Nothing was compared** — the running image has no registry digest |

A reviewer who treats `UNPINNED (LEGACY)` as a failure has misread it; §4.6 explains why
it exists and why it is not an error.

**Parse, never source** is the detail that most often separates a careful procedure from
a confident one.

### Step 2 — revision and digest

**Correct source, in order:** the **`publish` job of `.github/workflows/release.yml`**
— first the job summary from the step named **`record the pushed digest`**, which
writes a `registry manifest digest (authoritative)` line, and second the job log's
`published digest:` line. See `docs/deployment.md` §3.3.

**Three traps, all of which produce a plausible wrong answer:**

1. **Do not take the digest from a file in this repository.** `docker-compose.yml` and
   `.env.example` both name a digest, and **both are stale by construction** — a new
   one is published on every merge to `main`. §3.2 and §10 item 8 both say this in
   terms. A reviewer who deploys a digest read out of the compose file has failed step
   2 even though the command succeeded.
2. **Do not deploy the `:<40-char-sha>` tag or `:main`.** The SHA tag is a naming
   convention with no immutability guarantee, and `:main` is a moving pointer. §3.1.
3. **Do not interchange the registry manifest digest with the local image-config ID.**
   These are two different hashes and confusing them is a correctness bug, not a
   cosmetic one. §3.3.

**Also correct and worth credit:** running §3.3's anonymous-pullability check on the
day. **Judge it by whether the command succeeded** — a `401` challenge is how a client
obtains a token, not a verdict on privacy, and reading it as "private" is a false
negative that a careful reviewer will not make.

### Step 3 — the live database revision

**Correct:** read it **out of band, from RDS, from the reviewer's workstation** —
against `public.alembic_version`, over a TLS-verified connection. The mechanics are in
`api/alembic/README.md` (*Against RDS, later*); the connection mechanics the reviewer
will most likely use are in `RUNBOOK.md` §3, with the master password fetched from AWS
Secrets Manager at the moment of use and the CA bundle from the RDS truststore.

**Why it must be read this way — and this is the point of the step.** The EC2 instance
role holds the **application** secret only, and the application database role has **no
DDL rights**. `docs/deployment.md` §7.1 states it directly:

> *"**The value must be read out of band, because this host cannot read it.** … `deploy.sh`,
> `rollback.sh` and `verify-deployment.sh` can all **compare against** `ALEMBIC_HEAD` and
> none of them can **confirm** it — nothing in this repository can."*

So the host **cannot** supply this value under any circumstances. A reviewer who tries
to obtain it from the host has misunderstood the architecture, and this is a good thing
to notice, not a fault — **it is the reason the step exists.**

**Two correct-but-wrong answers to watch for:**

- **Taking it from the git tree.** The checkout says what the code expects; the database
  says what the database is. These differ whenever a migration was applied out of band,
  which §7.1 says is the normal way this schema moves.
- ⚠️ **Taking the value written down in `docs/deployment.md` §7.1.** That value is
  printed in a table there, and §7.1 itself marks it as **an evidence record, not a
  cached belief**, instructing the reader to re-read it and stating that passing it
  because the document prints it is precisely the failure the code was written to
  eliminate. **A reviewer who copies that value has failed step 3** — and this is a
  genuine tension in the documentation worth recording in §10 if it is what happens.

### Step 4 — deploy

**Correct:** `sudo /opt/lemondrop/scripts/deploy.sh <digest> [<sha>]` (§4.3). One
argument suffices on a labelled image; the second cross-checks the label and enables
the early schema gate (§4.4). **Must be run as `sudo`** — the state directory, lock and
log are root-owned.

**What a correct answer demonstrates beyond the command line:** the reviewer knows the
deploy is ordered so that **nothing changes until every check that can be made without
changing something has passed** (§4.5), and can name roughly what they will see.

### Step 5 — verify

**Correct:** `sudo /opt/lemondrop/scripts/verify-deployment.sh` on the host against
`localhost` (§5.2), which covers readiness and the known-good search. §5.3 for ALB
reachability **as a separate check**.

**The contextual requirement is part of a correct answer.** §5.1 is emphatic that
readiness and the known-good search are run **on the host against localhost, not
through the ALB**, because the ALB's idle timeout is 60 s and the API's worst case is
~240 s — **the ALB times out before the API does**, and that mismatch is unfixed. A
reviewer who verifies through the public ALB will hit a timeout that says nothing about
the deployment, and a reviewer who explains *why* they are running it locally has
understood something the runbook is trying to teach.

**The known-good search asserts rank-first, not top-N presence** (§5.2), and re-grounds
itself against the corpus on every run. A reviewer who knows it asserts rank-first has
read it carefully.

### Step 6 — roll back

**Correct:** `sudo /opt/lemondrop/scripts/rollback.sh`, **no arguments** (§6.1). The
target is chosen by the record, and any argument is refused. **Knowing that the target
comes from the record rather than from the operator is a load-bearing part of the
answer**, not a detail.

**Correct handling of §10 item 15 — this is the most important judgement in the
exercise.** A reviewer who reads §6.4 without reading §10 item 15 may believe the
legacy branch is a documented option to rehearse. **It is not.** §10 item 15 is
categorical: the branch **can start an image that is not the rollback target, and its
own checks will not notice**, because it re-tags a name compose never resolves, removes
the `API_IMAGE` key so compose falls back to a digest-pinned default, and then verifies
**content, not identity**. Its own identity check inspects the tag rather than the
running container, and on a record with no `IMAGE_ID` **that check is skipped
entirely**. It has never been executed and **must not be rehearsed**.

**A correct reviewer does not rehearse it, does not attempt it, and escalates if they
land on it.** `docs/deployment.md` §10 item 15 is the citation; §12.2 of the M4 record
is the shorter form.

**Note also** that the rollback **re-verifies** and **never deletes the record**, and
that after a rollback the `PREVIOUS_*` fields are emptied so a second rollback refuses
(§6.3). A reviewer who knows a rollback is finished when the restored image is
*serving correctly*, not when the container starts, has read §6.3 properly.

### Step 7 — recovery

**Correct:** §7 of the runbook, with §7.1 (record missing or malformed — and the
`--adopt-current` argument discipline, including the ordering trap that the `mv` must
come *last* or not at all), §7.2 (interrupted deploy — **the log is authoritative**),
§7.3 (lock held), §7.4 (failed verification), §7.5 (unknown state).

**The trap worth watching:** in §7.1 the bare `--adopt-current` refuses and demands the
database-verified revision. A reviewer who runs it without the argument, having already
moved the damaged record aside, has destroyed the evidence and recorded nothing —
strictly worse than the state they started in. §7.1 says so in terms.

### On steps the reviewer may legitimately find elsewhere

**`docs/deployment.md` Appendix A is a one-line command reference, and finding it is a
pass, not a shortcut.** It is part of the repository, and a reviewer who locates it has
demonstrated the self-sufficiency this test measures. **Note it in §10 as a usability
observation if they use it** — it is a genuine finding about where the information
lives, and it is not something to penalise.

## §14 — EVALUATOR ONLY — expected verdicts from each step

**What a healthy host produces, so you can tell a real result from an invented one.**

| Step | Expected observation | What a different observation means |
|---|---|---|
| Baseline (§4.2) | A comparison verdict of `AGREE` on a healthy digest-pinned host | `DIVERGENCE` is a real finding; `UNPINNED (LEGACY)` means the host is M3-era and changes step 3 |
| Digest pullability (§3.3) | The manifest resolves | A `401` alone is **not** a failure — it is the token challenge |
| Deploy (§4.3) | Exit 0 and the `DEPLOYED` banner | A non-zero exit is the refusal path; **a green exit is not proof the deploy was non-redundant** |
| Post-deploy verification (§5.2) | Readiness HTTP 200, and the known-good search reporting **PASS** with the expected document ranked first | A search that "returns results" but does not rank the expected document first has **failed** — the assertion is rank-first |
| Rollback (§6.1) | Exit 0, the rollback result printed, the record restored to the baseline revision | **An exit 0 here is not proof the right image was restored** — see §15 |
| Restored state | The record's digest matches the baseline digest, `PREVIOUS_*` are empty, verification agrees | Any divergence here is a **finding about the rollback**, not about the reviewer |

⚠️ **The single most important row is the last one.** On a host where a redundant deploy
has already occurred, a rollback can exit 0, print success, and restore the image that
was already running — **reporting success while accomplishing nothing.** §10 item 16
gives the mechanism. **An evaluator who marks a Variant B run as a clean pass on the
strength of exit codes alone has been fooled by a documented defect**, and the
reviewer's own written record is what should reveal it.

## §15 — EVALUATOR ONLY — warnings a reviewer should encounter

**These are not failures of the reviewer. They are hazards in the system that this test
exists to observe them encountering.** Record what the reviewer did about each.

### ⚠️ 1. The redundant-deploy trap — the highest-consequence one

**Where:** `docs/deployment.md` §4.2.1, §10 item 16 (`docs/deployment.md:1440`), and
`docs/verification-milestone-4.md:314`.

**What it is:** running `deploy.sh` with the digest that is **already running** is not
a no-op. Nothing in the script compares the target against the running image. It tags a
rollback point on the running image, pulls it again, rewrites `.env`, recreates the
container, verifies — and **exits 0 with a green banner** — while writing the running
digest into the field that names the rollback target. **The rollback pointer is
destroyed and the record becomes self-referential.**

**This is not hypothetical: it happened on the live host during Milestone 4.**

**What a correct reviewer does:** runs the manual pre-flight check in §4.2.1 **before**
deploying, comparing their target digest against the record's `IMAGE_DIGEST`, and does
not deploy if they are equal.

⚠️ **The subtlety that catches people:** the pre-flight check is `verify-deployment.sh`,
and on a healthy host it returns **`AGREE`** — the *good* verdict. **On this path `AGREE`
is precisely the signal that the digest you just read out of the record is the one you
must not deploy.** A green verification is not permission to redeploy what it just told
you is running. A reviewer who deploys *because* verification was green has hit the
defect, and it should be recorded in §10.

**Also worth watching:** the `DEPLOYED` banner ends with a line offering rollback as the
undo, and **that line is not true of a redundant deploy**, because the record names no
usable target. A reviewer who trusts the banner has trusted a false promise.

### ⚠️ 2. The legacy rollback defect

**Where:** `docs/deployment.md` §10 item 15 (`docs/deployment.md:1401`), §6.4;
`docs/verification-milestone-4.md` §12.2.

**What it is:** the legacy branch re-tags the rollback target under a bare local name
that compose never resolves, then removes `API_IMAGE` from `.env` so compose falls back
to its digest-pinned default — which is **not** the rollback target. Its identity check
inspects the tag rather than the running container, and on a record with no `IMAGE_ID`
**the check is skipped entirely**. It can therefore start the wrong image and **still
pass readiness and the known-good search**, because those are content checks, not
identity checks.

**What a correct reviewer does:** does not rehearse it, does not attempt it, and knows
it is not covered by §6.5's rehearsal. **A reviewer who rehearses it is a serious
finding and requires an immediate stop.**

**The digest-bearing path is unaffected**, and that is the one the exercise should use —
provided `PREVIOUS_IMAGE_DIGEST` is non-empty, which is what a completed deploy writes.

### ⚠️ 3. Verification from the wrong network context

**Where:** `docs/deployment.md` §5.1.

The ALB's 60-second idle timeout against an API worst case of ~240 seconds is an
**unfixed** configuration defect. Verifying through the public ALB produces a failure
that is not about the deployment, and a slow-but-correct result is **a pass on
correctness and a warning on the ALB path** — not a failure, and not a full pass.

### ⚠️ 4. Stale digests in the repository

**Where:** `docs/deployment.md` §3.2, §10 item 8.

A digest read out of `docker-compose.yml` or `.env.example` is a **worked example and a
safe boot default**, not an approved revision. Both documents say so. A deploy built on
a repository-file digest is a finding.

### ⚠️ 5. A missing record is refused, not repaired

**Where:** `docs/deployment.md` §7.1.

`rollback.sh` refuses with exit 2 on a missing or malformed record and changes nothing.
**This refusal is correct behaviour, not a failure to run**, and a reviewer who
interprets it as the tool being broken has misread it.

## §16 — EVALUATOR ONLY — what a good result contains

**Use this to judge the quality of the submission, after the pass/fail judgement of §11
has been made on its own terms.** These are not additional pass conditions; they are
what distinguishes a result that will improve this system from one that will not.

| Quality | What it looks like |
|---|---|
| **Excellent** | Complete procedure; **zero** author-only questions; correct handling of the pre-flight check and the legacy-branch refusal; correct separation of the two hash kinds; understands *why* verification runs on localhost; recorded honestly any point where they nearly asked something |
| **Good** | Complete procedure, zero author-only questions, correct values derived — but treats the warnings as obstacles rather than as findings, and records little of the reasoning |
| **Passing** | Everything §11 requires, and nothing more. **Note in §12 what was thin** — a pass on a thin procedure is a pass, and the thinness is the next thing to work on |
| **Failing** | Any author-only question, or any underivable value. **This is a finding about the runbook.** Fix it, and re-run with a fresh reviewer |
| **Compromised** | Prior exposure that was not declared, or operator help given during the exercise. **Not a pass and not a fail — an unmeasured run.** Record it as that |

**Two things to weight heavily, because they are hard to fake:**

1. **The questions section is where the value is.** A run with a handful of
   author-only questions is worth more to this system than a clean pass, because each
   one is a specific, located, fixable defect. **Do not report a finding-heavy run as a
   disappointing result.** Report it as the measurement succeeding.
2. **A reviewer who says "I got stuck here and did not know what to do" is better
   evidence than one who improvised.** Improvisation means the documentation failed and
   the reviewer covered for it. The exercise wants the first one.

**Never**: reconstruct a missing answer, fill a blank the reviewer left, or help them
past a gap and then record the result as clean. **The blanks are the data.**

## §17 — EVALUATOR ONLY — running the exercise

**The operator's checklist, in order. None of it has been done.**

1. **Decide the variant.** §3. This is yours and it is still open. Record the decision,
   and the reasoning, **before** the exercise — not after a result is in hand.
2. **Decide whether to restate the criterion.** If the restatement at
   `docs/m4-plan.md:826-827` is adopted, record it before the run. **Restating after
   seeing a result is how an ambiguous criterion gets resolved by the answer.**
3. **Identify a reviewer who has no prior exposure** (§6). Someone who has read the
   runbook already is not a cold reader, and the difference is the measurement.
4. **Provision access per §4** — and for a Variant A run, **do not provision host
   control**, which is unnecessary privilege. Provision secrets through the channel you
   already trust for credentials, and never into a document.
5. **Decide whether to accept the redundant-deploy risk** for a Variant B run (§7 step 4).
   This is an operator risk decision, made in advance.
6. **Extract the packet: §0 – §12, whole.** Check it before sending — confirm it
   contains no SHA, no digest, no CI run identifier, no database revision, and no
   deploy/verify/rollback command. **§7 must still contain no values after extraction.**
7. **Brief the reviewer on the task, not the answers.** State the objective (§2), the
   variant (§3), and that questions are to be recorded rather than suppressed (§9).
   **Do not preview the warnings.** Finding them is part of the test.
8. **Do not help.** Not with a value, not with a section number beyond what §7 already
   gives, not with a reassuring word. If they stall, let them stall and record it.
9. **Transcribe their submission into §6, §8, §9, §10** as given. Do not tidy it.
10. **Apply §11 as written** to reach a verdict, then record the verdict in §12 **with
    the variant named**, and with §12's constraint on wording observed: **a Variant A
    verdict may not state or imply that a deployment occurred.**
11. **If any author-only question occurred:** fix the runbook, and re-run with a
    reviewer who has not seen the first run.

**Record the run in `docs/verification-milestone-4.md`** once a verdict exists — §13.1 is
where the criterion's status is held, and §13.1 is explicit that closing it requires
**a decision from the operator about which sentence governs, followed by the execution
that sentence demands.** This document is the protocol for that execution. It is not
the execution.

**One thing to be aware of that is not a result.** `docs/deployment.md:774` cites the
plan's acceptance-test block as `docs/m4-plan.md:670-673`; the block is at
`docs/m4-plan.md:668-675`. **This is a pre-existing citation drift in another
document, not something this exercise found, and it must not be entered in §10 as an
exercise finding.** If the reviewer independently raises it, record it — but note where
it came from.

### §17.1 — Choosing who runs it: an independent engineer, or an independent agent

**This section sits below the fence on purpose.** It concerns how the evaluator conducts
and reads the run. It is not handed to the reviewer, and **it does not tell the reviewer
which sort of reviewer they are** — that is briefed separately, per §17 step 7.

**Reviewer type is a different axis from variant, and the two must not be conflated.**
§3 decides *what the reviewer does* — derive the procedure only, or derive it and then
deploy, verify and roll back. **This section decides *who reads the repository*.** Either
reviewer type can be run under either variant, including a Variant B run performed by an
agent, which would change host state exactly as §3 describes. **The two fields answer
different questions and neither substitutes for the other**: the variant records *what
happened to the environment*, and the reviewer type records *who perceived it*. Both are
recorded in §6.

> **A naming collision to be careful with on this page.** §3's **Variant A** and
> **Variant B** are the *exercise* variants — cold-reader walkthrough, and live
> deployment. The **A** and **B** used in the headings and table below are *reviewer
> types*. **The same two letters mean different things in different parts of this
> document.** Read "Variant B" as the live-deployment variant and "B" as the agent
> reviewer, and never write one where the other is meant.

#### The two reviewer types are not two runs of one test

They yield different evidence. The difference is not a matter of degree, and an agent run
is not a cheap approximation of a human one — it is a **narrower question**, asked
cleanly.

| | **A — a human engineer who has never seen this system** | **B — a fresh, context-isolated engineering agent** |
|---|---|---|
| Independence | Social and real | Real from the conversation; questionable from the build |
| Availability | On request, on someone's schedule | Immediate, reproducible, resettable, cheap |
| How it reads | Under time pressure — skims, assumes, misses sections | Exhaustively — no deadline, no skim |
| Can it resist asking the author? | Yes, and whether it does **is** the measurement | No such temptation exists |
| What it establishes | The strongest evidence available for this criterion | Whether the procedure is **derivable** from the repository |

#### A — a human engineer with no prior exposure

**What it establishes.** The strongest form of the evidence this criterion admits. A
distinct person, no prior exposure to the system or the repository, working from the
repository alone and nothing else — **which is the closest available realisation of the
criterion's own words.** Where a human run passes, the argument that the information is
self-sufficient is as strong as it can be made without the author in the room.

**What it cannot establish, stated plainly:**

- **Availability and scheduling.** It requires a person who is willing to spend real time
  on a procedure that may be long, and whose time is not yours to spend. This is a
  genuine operational constraint, and **it is the reason an agent-run protocol is worth
  having at all** — an agent reviewer is answerable at once, when no person is.
- **Access parity is not free.** The reviewer may not hold the same infrastructure access
  you do. **Provisioning it changes the environment under test**, and therefore changes
  what the exercise measures. Provision for the reviewer as §4 requires, no more; and for
  a Variant A run, no host control at all.
- **Social interest biases the result, and the bias runs in two opposite directions.**
  Some reviewers suppress a question they should have asked, because asking would look
  like not understanding. Others ask the author things the repository could have answered,
  because the author is present and available. **These two failures look similar from the
  outside and you cannot tell them apart without reading §9 carefully** — §9's *asked* /
  *almost asked* distinction and its third column are precisely what separates a genuine
  finding from a socially awkward silence.
- **A human reads the way a human reads.** Under time pressure, people skim, assume, and
  miss a section that an exhaustive search would find. **Their failures are the most
  informative failures available**, and that cuts both ways: a missed section is a real
  finding about the runbook, and a suppressed question is a real finding about how
  hostile the runbook is to use.

#### B — a fresh, context-isolated engineering agent

**What it establishes.** Whether the procedure is **derivable** from the repository by an
independent reader with no access to the author's conversation, notes, or terminal
history. Nothing more, and that is a genuinely useful thing to know: it is available
immediately, reproducible, resettable, and cheap. **Those are real advantages, and they
are the reason it is worth doing even when a human reviewer is available** — a gap found
by an agent is a gap found before anyone has spent an afternoon on the exercise.

**What it cannot establish. None of these are softened here, and none should be:**

- ❗ **It is not a second person.** The criterion says *"a second engineer."* An agent is
  a reader, not a colleague. Whatever else it does, it does not supply the thing the
  criterion names.
- ❗ **Context isolation is not the same as independence.** A fresh agent spawned from the
  same session, running the same model, carrying the same priors, is isolated from *the
  conversation* but not from *how the system was built*. **It may reproduce the author's
  own search strategies, including their blind spots, and succeed where a human would
  not.** Isolation of context is not isolation of perspective.
- ❗ **It is not under realistic pressure.** A human is time-boxed and will skim; an agent
  will search exhaustively and keep going. **A pass by an agent is therefore weaker
  evidence than the same pass by a person**, because it does not demonstrate that a person
  under time pressure would find the same thing — and finding it under time pressure is
  the entire practical content of the criterion.
- ❗ **It cannot be socially independent in the way that matters.** The measurement turns
  on a reviewer choosing *not* to ask the author. An agent has no such temptation to
  resist, and therefore cannot demonstrate the property the criterion is really about,
  however cleanly it runs.
- **Its findings are evidence about the documentation, not about what an engineer can do.**
  A gap an agent finds is a real gap in the runbook. It is not evidence about the
  capability the criterion asserts, and it must not be written up as if it were.

#### What each one establishes, stated without softening either

**Neither reviewer type, on its own, proves that a second person executed a live
deployment. Only Variant B, with a person, does that** — §3 and §12, which are the two
places this is stated and both of which this section does not weaken.

- **An agent run is evidence about the documentation's self-sufficiency** — whether the
  procedure can be derived at all — **and a weaker proxy for the criterion than a human
  run.** A clean agent run is not a clean result under §11; it is a narrower observation
  that constrains what the runbook can be shown to contain.
- **A human run is the stronger evidence**, and where it is available it supersedes the
  agent run for the purposes of this criterion.
- **If the human surfaces a question the agent did not, that question is real and the
  agent pass does not cover it.** An agent pass is not a prior that excuses a later
  finding; it is one observation, and a better-informed reader can always find more.

#### A recommendation, and what it leaves open

**If no human reviewer is available, run the agent reviewer first.** It costs nothing,
it touches nothing, and it will surface documentation gaps cheaply and early — which is
the failure mode that actually matters (§11's disqualifier). **A human run supersedes it
when one becomes available**, and **any gap the agent missed but the human hits is a
genuine finding**, recorded as such.

**Record which type was used in §6.** That section is blank and waits for this; the
reviewer fields were written for a person, so for an agent run say plainly what kind of
reviewer it was. **Do not record an agent run as a human run** — in the same way, and for
the same reason, **a Variant A result may not be recorded as a Variant B result** (§3).

**One thing to keep straight.** **The variant decision (§3) and the decision about what
the criterion requires both belong to the assessor, and this section says nothing about
which variant governs or how the criterion should be read.** Choosing *who* runs the
exercise is an operator decision — a scheduling and capability decision, not a judgement
about the system. Choosing *what the criterion demands* is not an operator decision, and
nothing in this section should be cited toward it.

**Nothing in this section has been run.** Both reviewer types are described from
protocol. **No reviewer of either type has been identified, neither variant has been run,
and §6, §9, §10 and §12 remain exactly as blank as they were before this section was
written.**

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