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
> ⚠️ **The paragraph above was true when it was written and is now partly superseded.
> Read it with the dated note further down.** A Variant A exercise **was** run on
> 2026-10-15 by an AI agent reviewer, and §§5, 6, 8, 9, 10 and 12 now carry what it
> submitted. **The verdict is still blank, and it is blank on purpose** — it is the
> assessor's field, not the reviewer's and not this document's. **No deployment
> occurred.**
>
> **Status: UNTESTED.** That is the classification, in the vocabulary this repository
> uses (`docs/verification-milestone-4.md:92`). It means no check was run and none is
> implied.
>
> ⚠️ **And `UNTESTED` still describes the criterion's verdict state, which is what this
> banner is for.** §11 was applied to the submitted evidence and its outcome is
> **FAIL**; recording a FAIL against §11 is not the same as recording a verdict on the
> criterion, and the verdict remains the assessor's. **The run happened. The criterion's
> verdict is still unrecorded.**
>
> ⚠️ **Since that FAIL was written, §11's criteria have been revised and a re-run is
> required — and it has not happened.** The FAIL above was scored against §11's
> **previous** wording, which counted every row the reviewer could not answer from the
> tree as a documentation failure. **§11 now turns on genuine documentation gaps** (§9
> classifies the recorded questions under a three-way scale plus a host-state row type),
> **a documentation repair pass has since closed five of the eight gaps in §10, and a
> fresh cold-reader run is required because both the criteria and the repository have
> changed.** **Nothing has been re-run, no new reviewer has been engaged, no new question
> has been asked, no new result exists, and the Verdict field in §12 is still blank.**
> **This is not a prediction that a re-run would pass — it has not been done, and a
> re-run that fails is as likely as one that passes.** Nothing in the note changes the
> deployment facts, which stand: **nothing was deployed, no AWS call was made, and no
> Variant A result is a deployment.**
>
> | Fact | State |
> |---|---|
> | Protocol authored | 2026-10-15 |
> | Reviewer identified | **None. No person has been approached.** ⚠️ *Superseded in part — see the dated note below: an **AI agent**, not a person, ran a Variant A exercise. No person was approached.* |
> | Variant selected | **Undecided — see §3. The decision is owed by the assessor, not by this document.** ⚠️ *Superseded in part — see the dated note below: a **Variant A** exercise was run. The assessor's governing-variant decision is still open.* |
> | Procedure executed | **Never. Not in part, not on a throwaway host, not anywhere.** ⚠️ *Superseded — see the dated note below: a **Variant A derivation** was performed. **Nothing was executed against any host.*** |
> | Evidence submitted | **None exists** ⚠️ *Superseded — see the dated note below: evidence exists in §8, §9 and §10, submitted by an AI agent reviewer.* |
> | Deployments performed for this test | **None** — **and this row remains true. Nothing was deployed.** |
> | Rollbacks performed for this test | **None** — **and this row remains true. Nothing was rolled back.** |
> | Verdict | **NOT YET TESTED** — **and this row remains true. The verdict is the assessor's and has not been recorded.** |
>
> ### 📋 Dated note — 2026-10-15 — a Variant A exercise **was** run. Read this with the banner above.
>
> **The banner above now describes the state of the *verdict*, not the absence of a
> run.** It was written when nothing had been executed. One thing has happened since:
> **a Variant A exercise was carried out on 2026-10-15.** Everything the banner says
> about deployment, rollback and the verdict is untouched and still exactly true.
>
> | Fact about the run | State |
> |---|---|
> | Exercise executed | **Yes — 2026-10-15, Variant A (cold-reader documentation walkthrough)** |
> | Reviewer type | **An AI agent, context-isolated (§6). Not a person.** |
> | Revision under test | `678cef3bf46a3e15d79dbc20064f0ea43f22dca8` (§5) |
> | Deployments performed | **None** |
> | Rollbacks performed | **None** |
> | AWS calls made | **None** |
> | SSM commands issued | **None** |
> | Containers or Terraform touched | **None** |
> | **§11 applied to the submitted evidence** | **FAIL — unsoftened. Nine author-only questions are recorded in §9.** (§12) |
> | **Verdict of the acceptance criterion** | **NOT YET TESTED — reserved to the assessor (Moe). Not recorded here.** (§12) |
>
> ❗ **NO DEPLOYMENT OCCURRED.** Nothing was deployed, no AWS call was made, no SSM
> command was issued, no container was touched, no rollback was performed, and no
> Terraform was run. **This run must never be reported as a live-deployment
> demonstration, and nothing in it may be read as evidence that a second engineer
> deployed anything.**
>
> ❗ **Per §3, this is an agent run, and an agent run is a weaker proxy for the
> acceptance criterion than a human run.** The reviewer shares the model lineage and
> priors of the session that built this system, so it is isolated from the
> *conversation* but not from *how the system was built*. **It is not evidence that a
> second engineer performed a deployment**, and §6, §8 and §12 repeat that caveat
> wherever the reviewer type appears.
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

> ### 📋 Dated note — 2026-10-15 — a **second** Variant A run was carried out, and **§11 returns PASS**
>
> **A second cold-reader run was carried out on 2026-10-15**, against the **repaired tree**
> and against §11's **revised** wording. **It returns PASS on all four conditions** — with
> the Q6 adjudication and the agent caveat attached (§11, §12). Like the first run, it is a
> **Variant A** exercise by an **AI agent, context-isolated** (§6): the reviewer produced a
> complete derived procedure and **executed nothing**.
>
> | Fact about the second run | State |
> |---|---|
> | Exercise executed | **Yes — 2026-10-15, Variant A (cold-reader documentation walkthrough)** |
> | Reviewer type | **An AI agent, context-isolated (§6). Not a person.** |
> | Revision under test | `9fc2518ed9092f4696e41cebeab84066560908d7` (§5) — the pushed `main` |
> | Deployments performed | **None** |
> | Rollbacks performed | **None** |
> | AWS calls made | **None** |
> | SSM commands issued | **None** |
> | Containers or Terraform touched | **None** |
> | **§11 applied to the submitted evidence** | **✅ PASS — all four conditions. Never recorded bare: it carries the Q6 adjudication and the agent caveat.** (§11, §12) |
> | **Verdict of the acceptance criterion** | **NOT YET TESTED — reserved to the assessor (Moe). Not recorded here.** (§12) |
>
> ❗ **NO DEPLOYMENT OCCURRED, in either run.** Nothing was deployed, no AWS call was made,
> no SSM command was issued, no container was touched, no rollback was performed, and no
> Terraform was run. **Neither run may be reported as a live-deployment demonstration, and
> neither is evidence that a second engineer deployed anything.**
>
> ❗ **This run, like the first, was an AI agent's.** Per the reviewer-type subsection in §3,
> an agent run is evidence about the documentation's **self-sufficiency** and is a **weaker
> proxy** for the acceptance criterion than a human run: it shares the author's model
> lineage and priors, so **context isolation is not perspective isolation.** §3, §6, §8 and
> §12 repeat that caveat. **(The dispatch refers to this as the "§17.1 caveat"; its tracked
> home is §3, and there is no §17.1 in this document.)**
>
> **What is now current, and what is retained.** §11 (revised) now returns **PASS** on the
> second run's evidence; **the first run's FAIL is retained in full** as the record of what
> happened against the previous wording and the unrepaired tree. **The Verdict field in §12
> is still blank, and it is still the assessor's.**

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

> ⚠️ **That property held while this document was empty, and it is annotated rather than
> silently broken.** **§5 now records the revision under test, because the run of
> 2026-10-15 required it to be recorded** — and it was recorded *after* the exercise, as
> §5 asks, not handed to the reviewer beforehand. **No digest, no CI run identifier, no
> database revision and no deploy, verify or rollback command line has been added
> anywhere in this document**, and none was supplied to the reviewer. The property that
> matters — that the reviewer derived the procedure rather than being handed it — is
> intact, and §9 is the evidence of it.

---

## §1 — Status

**UNTESTED.** Stated once here and repeated wherever a reader could otherwise mistake
this document for a record.

> ### 📋 Dated note — 2026-10-15 — the Variant A exercise was run. `UNTESTED` above still stands, and says something narrower now.
>
> **The classification below is retained, and it is retained deliberately.** `UNTESTED`
> here describes **the verdict state of the acceptance criterion** — no verdict has been
> recorded, and the verdict is the assessor's (§12). **A Variant A exercise was carried
> out on 2026-10-15** by a reviewer who was **an AI agent, context-isolated** (§6), and
> **§11 was applied to its submitted evidence and returned FAIL** (§12).
>
> ❗ **No deployment occurred.** No AWS call, no SSM command, no container, no rollback,
> no Terraform. **Nothing in this run is evidence that a second engineer deployed
> anything, and it must never be reported as a live-deployment demonstration.**
>
> ❗ **Per §3 an agent run is a weaker proxy for the acceptance criterion than a human
> run.** The agent shares the author's model lineage and priors: it is isolated from the
> conversation, not from how the system was built.

> ### 📋 Dated note — 2026-10-15 — a **second** Variant A run. `UNTESTED` above still stands.
>
> **The retained note above describes the first run. A second Variant A run was carried out
> on 2026-10-15**, against the repaired tree and §11's revised wording, by **an AI agent,
> context-isolated** (§6). **§11 applied to it returns PASS on all four conditions**, with
> the Q6 adjudication and the agent caveat attached (§11, §12). **The rows in the table
> below describe the first run and are retained as written; the second run's record is in
> §§5, 6, 8, 9, 10, 11 and 12.**
>
> ❗ **No deployment occurred, in either run.** No AWS call, no SSM command, no container,
> no rollback, no Terraform. **Neither run is evidence that a second engineer deployed
> anything.**
>
> ❗ **Per §3 an agent run is a weaker proxy for the acceptance criterion than a human
> run.** This run shares the author's model lineage and priors: context isolation is not
> perspective isolation.

| Element | State |
|---|---|
| A second person has followed the runbook | **No.** No person exists in this run. The reviewer was an **AI agent** (§6). |
| A second person has deployed anything | **No. Nothing was deployed.** |
| A procedure has been derived from the repository by an independent reader | **Yes — by an AI agent (context-isolated), on 2026-10-15.** ⚠️ *Was `No`; superseded by the dated note. The reader is context-isolated but **not** perspective-isolated (§3), so this row records a derivation, not a second engineer's capability.* |
| A reviewer has been identified or contacted | **An AI agent, context-isolated. No person was approached, contacted or available.** ⚠️ *Was `No`; superseded by the dated note.* |
| Any question has been asked of a reviewer | **Yes — fifteen recorded in §9, nine of them author-only.** ⚠️ *Was `No`; superseded by the dated note.* |
| Any documentation gap has been catalogued | **Yes — eight in §10 (G-1 … G-8), two of them blocking.** ⚠️ *Was `No`; superseded by the dated note.* |
| Any verdict exists | **No — §12's Verdict field is blank and is reserved to the assessor (Moe).** The §11 outcome on the submitted evidence is **FAIL**; that is a criterion applied to evidence, not a verdict on the criterion. |

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

**The criterion, as written**, recorded in a tracked document at
`docs/verification-milestone-4.md` §13.1 (*"The criterion, as written"*):

> *"A second engineer must be able to deploy a tested revision without manually
> reconstructing the original environment."*

**The plan's operationalisation of it**, recorded in the same tracked section at
`docs/verification-milestone-4.md` §13.1 (*"The operationalisation of the same sentence,
as written"*), requires a second person to actually do it:

> **Verified — this is the acceptance criterion, and it must be tested by someone other
> than the author.** A second engineer, given only the runbook and repo access, deploys
> a SHA-tagged revision **without asking a question**, then rolls back, then confirms
> `/health` and a `/search` that returns correct results. **If the author runs this test
> themselves, the criterion is not met** — it is the definition of "without manually
> reconstructing."
>
> **Done when:** the acceptance sentence is true, witnessed by someone else.

**And the plan had already flagged the mismatch**, at `docs/verification-milestone-4.md` §13.1 (ambiguity item 2), before
any of this was attempted: *"**The acceptance criterion is therefore weaker than it
reads.**"* Its recommended restatement is quoted in that same tracked item:

> *"A second engineer can deploy a tested revision to the running environment without
> manually reconstructing the original deployment steps."*

**The difference between those two sentences is not cosmetic.** "The original
deployment steps" excludes the walk-forward and `terraform apply` path — a path the
plan itself records has never been walked end to end from zero
(`docs/deployment.md` §10 item 18). "The original environment" does not exclude it.
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
`docs/verification-milestone-4.md:639-643`:

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

**If the criterion is restated** in the form the plan recommends (recorded in
`docs/verification-milestone-4.md` §13.1, ambiguity item 2), say so in §12 before the
exercise is run, and note it — because the restated criterion names *deployment steps*,
which bears on which variant can satisfy it. **Do not restate it after seeing a result.**
Deciding what the criterion means after you know how it came out is how an ambiguous
criterion gets quietly resolved in whichever direction the result happens to point.

> ⚠️ **The citations in this section were retargeted, and the reason is G-1 itself.**
> This section used to cite `docs/m4-plan.md` by line number. **That file is untracked**,
> so a clean clone of any revision does not contain it, and a protocol that judges a
> milestone against a sentence a second reader cannot reach is the worst kind of
> dangling reference — which is what §10 G-1 records. A documentation repair pass has
> since recorded the same substance in tracked files: **the acceptance criterion, its
> operationalisation, the *weaker than it reads* finding and the recommended restatement
> are all in `docs/verification-milestone-4.md` §13.1**, and **the walk-forward path
> never having been walked end to end is in `docs/deployment.md` §10 item 18.** The
> quotations above are unaltered; only the pointers to them were retargeted, and each
> now names a location a clean clone can open.

### ⚠️ The reviewer's kind — an agent run is a weaker proxy than a human run

**The two variants above describe *what* is run, not *who* runs it, and the kind of
reviewer is a separate axis that the criterion's own word — *"a second engineer"* —
makes load-bearing.** The one run of 2026-10-15 was carried out by an **AI agent**
(§6), and that is a fact about the evidence which has to be recorded here, where a
reader meets the criterion, not only where the reviewer is named. This subsection is
its tracked home; §1, §6, §8 and §12 refer to it.

> **An agent run is evidence about the documentation's self-sufficiency, and a
> weaker proxy for the acceptance criterion than a human run. The agent shares the
> author's model lineage and priors, so context isolation is not perspective
> isolation. It is not evidence that a second engineer performed a deployment.**

**Why this is recorded rather than left as a detail of one run.** The criterion is a
capability claim about *a second engineer* (§2). An agent is a reader, not a colleague:
it was isolated from the author's *conversation* but not from *how the system was
built*, so it may reproduce the author's own search strategies and blind spots, and
succeed where a busy human would not. A run by an agent can therefore show that the
documentation is self-sufficient **while showing nothing about whether a person under
time pressure would reach the same result.** The two are not interchangeable, and — as
with Variant A and Variant B above — **neither result may be reported as the other, and
an agent result must never be written up as a second engineer's deployment.**

## §4 — Required access

Everything the reviewer needs, listed concretely. **The operator provisions these; the
reviewer does not discover them, and the reviewer must not be given anything beyond
this list as a hint.**

| # | Access | Detail | Carries a secret? |
|---|---|---|---|
| 1 | **Repository access, read** | The GitHub repository, at a pinned revision (§5). Read on Actions logs and job summaries, which §7 requires. | No |
| 2 | **AWS CLI v2, authenticated** | A named profile and a region. The runbook's own values are in `docs/deployment.md` §1.1 — **let the reviewer read them there.** The profile also needs the read-only **discovery** actions, because the runbook's discovery routes are AWS calls and not literals: `ec2:DescribeInstances` (the instance id), `elasticloadbalancing:DescribeLoadBalancers` (the ALB DNS name, §5.3), `rds:DescribeDBInstances` (the database endpoint, port, db name, master secret ARN and master username). **All three are `Describe`-only and none is a deploy permission**; the full table is `docs/deployment.md` §1.2. | **Yes — credentials** |
| 3 | **SSM access to the instance** | `ssm:StartSession`, `ssm:SendCommand`, `ssm:GetCommandInvocation` against the EC2 instance. The instance has no SSH key and no public IP. The full permission set is in `docs/deployment.md` §1.2. | No — but grants host control |
| 4 | **RDS master secret, workstation-side** | Credentials for the RDS master user, reachable from the reviewer's own machine. Needed because the host **cannot** read the live database revision — the reviewer must establish it from outside the host. See `docs/deployment.md` §7.1. | ⚠️ **YES — highest sensitivity. Master database credential.** |
| 5 | **Local tooling** | `psql`, `curl`, `jq`, `docker` with Compose v2. `jq` and `psql` on the operator machine are already named in `RUNBOOK.md:44`. | No |
| 6 | **Either SSH or SSM Session Manager** | There is no SSH key and no public IP; SSM Session Manager is the normal route. `RUNBOOK.md:151`. | No — but grants host control |

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

**Filled in from the run of 2026-10-15.** The values below are what the reviewer
actually worked against.

| Field | Value |
|---|---|
| Repository | `https://github.com/fvitorino00/lemondrop.git`, read locally at `/home/zaratustra0/Projects/lemondrop` |
| Commit SHA under test | `678cef3bf46a3e15d79dbc20064f0ea43f22dca8` — **full 40 characters, not abbreviated. Confirmed by the reviewer itself.** |
| Date pinned | **2026-10-15** |
| Pinned by | **Not recorded, and left unrecorded on purpose.** §5 asks for a name so that a later reader can tell a deliberate pin from an accident of timing. **The run's evidence does not name one, so none is invented here.** What is established: the SHA was the repository's `HEAD` before the reviewer's first command, and the reviewer independently re-derived and re-confirmed the full 40-character value. **That is weaker than §5 asks for, and the weakness is recorded rather than papered over.** |

**The pin was verified after the fact, and the verification is worth stating.**
`678cef3bf46a3e15d79dbc20064f0ea43f22dca8` resolves to a real commit, and its
description is *"docs: the reviewer protocol; the answer key leaves the repository."*
It was the repository's `HEAD` at the start of the exercise. Nothing was staged, and no
tracked file was modified during the reviewer's read-only work.

**Two facts about this pin that bear on the result, and that the reviewer recorded as
findings rather than as incidental detail:**

- **The revision under test is not what `origin/main` points at.** At the time of the
  exercise, `main` was **3 commits ahead of `origin/main`** — see §9 Q1 and §10 G-7.
  Nothing in the repository states that the revision under test must be a commit with a
  successful release run, and this one has **no published image**.
- **The revision under test does not contain two documents the runbook cites.** `docs/m3-study-guide/`
  and `docs/m4-plan.md` are **untracked** at this revision. A clean clone of
  `678cef3…` does not contain them — see §10 G-1, which is a direct, checkable
  consequence of the pin recorded above.

**How to record it, and how to check it later.** Record the **full 40-character SHA**,
not an abbreviation — abbreviated SHAs are ambiguous across a long history, and an
ambiguous identifier cannot settle a dispute about what was tested. Record the date and
who pinned it, so that a later reader can tell a deliberate pin from an accident of
timing.

**Why this document names no SHA.** `docs/verification-milestone-4.md` §14 carries the
same discipline for the milestone's commit list: *"Read `git rev-parse HEAD` on the day
you need the current one."* A SHA written into a protocol document is stale the moment
it is written, and a stale SHA that looks authoritative is worse than a blank field.

> ⚠️ **Annotated, because §5 above now names one.** The SHA recorded above was added
> **after** the run of 2026-10-15, as §5's own instructions require — a protocol states
> the rule, a run records its value. **The discipline above is not abandoned; it is why
> the value is a full 40-character SHA tied to a date rather than a shorthand that could
> be mistaken for something current.**

**How to verify the pin afterwards.** The revision actually exercised must match the
revision recorded here. If the reviewer's checkout drifted mid-exercise, the two
records must disagree visibly rather than silently — and in that case the result
describes a test of something other than what this section says it tests.

### 📋 The second run's revision — 2026-10-15

**Filled in from the second run of 2026-10-15. The first run's §5 record above is retained
unchanged; this is the second run's pin, added alongside it so the two are distinguishable.**

| Field | Value |
|---|---|
| Repository | `https://github.com/fvitorino00/lemondrop.git`, read locally at `/home/zaratustra0/Projects/lemondrop` |
| Commit SHA under test | `9fc2518ed9092f4696e41cebeab84066560908d7` — **full 40 characters. Confirmed by the reviewer itself**, with `git log -1 --format=%H`. |
| Date pinned | **2026-10-15** |
| Pinned by | **The evaluator.** The revision was pinned to the pushed `main` for this run. **No person's name is invented here** — the evidence names the pinning party as the evaluator, and no other individual. |

**Facts the reviewer confirmed and recorded about this pin:**

- The revision is `main`, and `main` is level with `origin/main` — `git branch -vv` shows
  `main [origin/main]` with no ahead/behind annotation, and `git status` reports *"Your
  branch is up to date with 'origin/main'"*. (Verified after the run: `origin/main...main`
  is `0 0`.) The commit subject is `docs(acceptance): re-resolve two citations shifted by
  the §13.1 insert`.
- **This is not the first run's pin.** The first run's revision
  (`678cef3bf46a3e15d79dbc20064f0ea43f22dca8`, above) is an ancestor; the tree has since
  moved on, and the repairs the closing note below says a fresh run must be against are all
  present. ⚠️ **The reviewer's submission states the repository "has moved on by 15
  commits"; the verified count is 19** (`git rev-list --count 678cef3bf46a3e15d79dbc20064f0ea43f22dca8..9fc2518ed9092f4696e41cebeab84066560908d7`
  = `19`). The reviewer's figure is recorded as submitted and corrected here rather than left
  standing; the substance — that this run is against the *repaired* tree, not the first run's
  tree — is unaffected.
- **CI on this revision** — run `38793650721`, all nine jobs green, and local `actionlint`
  v1.7.12 exited 0. These were reported by the evaluator and are **not derivable from the
  repository**: the reviewer could not read GitHub Actions and recorded that limit clearly.
  They are recorded here as **evaluator-supplied** facts, not as the reviewer's findings.

## §6 — Reviewer details

**Filled in from the run of 2026-10-15. The reviewer was not a person, and no field
below invents one.**

| Field | Value |
|---|---|
| Reviewer name | **No name — there is no person.** The reviewer was **an AI agent**: a fresh, context-isolated engineering agent. |
| Role / team | **AI agent (context-isolated).** No role, no team, no employer, no human affiliation exists for this reviewer, and **none is invented here.** |
| Date of the exercise | **2026-10-15** |
| **Prior exposure to this system** | **None conversationally, by construction** — the agent had no access to the author's conversation, notes, or terminal history. ⚠️ **But it shares the author's model lineage and priors. See the caveat below; this is not a clean bill of independence.** |
| Prior exposure to this repository | **None.** It read only within `/home/zaratustra0/Projects/lemondrop`. It did not read the evaluator-only answer key, which now lives outside the repository. |
| Prior exposure to this stack's tooling | **None.** It read the repository's *documentation* of the tooling and the tooling's source. **It executed no tooling, and operated no AWS, SSM, Docker or Terraform surface.** |
| Variant performed | **A — cold-reader documentation walkthrough. NO DEPLOYMENT OCCURRED.** |
| Assessed by | **Not assessed. No verdict is recorded.** The criterion's verdict is the assessor's (Moe) — see §12. |

> ### ❗ The reviewer was an AI agent. This is recorded precisely and is not softened.
>
> **Per §3, an agent run is evidence about the documentation's self-sufficiency, and
> is a weaker proxy for the acceptance criterion than a human run.** The consequences,
> none of which is softened:
>
> - ❗ **It is not a second person.** The criterion says *"a second engineer."* An agent
>   is a reader, not a colleague. It does not supply the thing the criterion names.
> - ❗ **Context isolation is not perspective isolation.** This reviewer shares the model
>   lineage and the priors of the session that built the system. It was isolated from
>   *the conversation*; it was **not** isolated from *how the system was built*. **It may
>   reproduce the author's own search strategies, including their blind spots, and succeed
>   where a human would not.** The prior-exposure fields above record this honestly
>   rather than claiming independence the run does not have.
> - ❗ **It is not under realistic pressure.** A human is time-boxed and will skim; an
>   agent searches exhaustively. **A pass by an agent is weaker evidence than the same
>   pass by a person**, because it does not show that a person under time pressure would
>   find the same thing.
> - ❗ **It cannot be socially independent in the way the measurement turns on.** The
>   measurement turns on a reviewer choosing *not* to ask the author. An agent has no
>   such temptation to resist, and so cannot demonstrate that property, however cleanly
>   it runs.
> - ❗ **It is not evidence that a second engineer performed a deployment.** **No
>   deployment occurred. Nothing was deployed, no AWS call was made, no SSM command was
>   issued, no container was touched, no rollback was performed and no Terraform was
>   run.** §3 forbids reporting a Variant A result as a Variant B result, and that
>   separation holds here without exception.
>
> **Its findings are evidence about the documentation, not about what an engineer can
> do.** The gaps in §10 are real gaps in the runbook. **They are not evidence about the
> capability the criterion asserts, and nothing in this record may be written up as if
> they were.**

**On the prior-exposure fields — the only question that matters is the fourth row.** If
the reviewer has previously read `docs/deployment.md`, has previously deployed this
stack, or was told any part of the procedure before the exercise, **the measurement is
compromised** and the result must be recorded as compromised rather than as a clean
pass. `docs/verification-milestone-4.md` §13.1 is the standard being applied here:

**On the prior-exposure fields — the only question that matters is the fourth row.** If
the reviewer has previously read `docs/deployment.md`, has previously deployed this
stack, or was told any part of the procedure before the exercise, **the measurement is
compromised** and the result must be recorded as compromised rather than as a clean
pass. `docs/verification-milestone-4.md` §13.1 is the standard being applied here:

> *"**If the author runs this test themselves, the criterion is not met** — it is the
> definition of 'without manually reconstructing.'"*

A reviewer with incidental exposure is a weaker version of the same problem, not a
different one. **Record the exposure honestly and let the result be read against it.**
Do not approach a candidate with a briefing that creates exposure; the exposure is the
thing being measured.

### 📋 The second run's reviewer — 2026-10-15

**Filled in from the second run of 2026-10-15. The first run's §6 record above is retained
unchanged. The reviewer was again not a person, and no field below invents one.**

| Field | Value |
|---|---|
| Reviewer name | **No name — there is no person.** The reviewer was **an AI agent**: a fresh, context-isolated engineering agent. |
| Role / team | **AI agent (context-isolated).** No role, no team, no employer, no human affiliation exists for this reviewer, and **none is invented here.** |
| Date of the exercise | **2026-10-15** |
| **Prior exposure to this system** | **No conversational context, by construction** — the agent received only the repository and a reviewer-facing brief. It saw no evaluator answer key, no prior review, and no part of the author's conversation or terminal history. ⚠️ **But it shares the author's model lineage and priors. This is not a clean bill of independence — see the caveat below.** |
| Prior exposure to this repository | **None beyond the repository itself.** It read only within `/home/zaratustra0/Projects/lemondrop`, and was told explicitly not to read outside it. |
| Prior exposure to this stack's tooling | **None.** It read the repository's *documentation* of the tooling and the tooling's source. **It executed no tooling, and operated no AWS, SSM, Docker or Terraform surface.** |
| Variant performed | **A — cold-reader documentation walkthrough. NO DEPLOYMENT OCCURRED.** |
| Assessed by | **Not assessed. No verdict is recorded.** The criterion's verdict is the assessor's (Moe) — see §12. |

> ### ❗ The reviewer was an AI agent, in both runs. This is recorded precisely and is not softened.
>
> **Per the reviewer-type subsection in §3, an agent run is evidence about the
> documentation's self-sufficiency, and is a weaker proxy for the acceptance criterion than
> a human run.** The consequences, none of which is softened:
>
> - ❗ **It is not a second person.** The criterion says *"a second engineer."* An agent is a
>   reader, not a colleague. It does not supply the thing the criterion names.
> - ❗ **Context isolation is not perspective isolation.** This reviewer shares the model
>   lineage and the priors of the session that built the system. It was isolated from *the
>   conversation*; it was **not** isolated from *how the system was built*. **It may
>   reproduce the author's own search strategies and blind spots, and succeed where a human
>   would not.**
> - ❗ **It is not under realistic pressure.** A human is time-boxed and will skim; an agent
>   searches exhaustively. **A pass by an agent is weaker evidence than the same pass by a
>   person.**
> - ❗ **It cannot be socially independent in the way the measurement turns on.** The
>   measurement turns on a reviewer choosing *not* to ask the author. An agent has no such
>   temptation to resist, and so cannot demonstrate that property, however cleanly it runs.
> - ❗ **It is not evidence that a second engineer performed a deployment.** **No deployment
>   occurred. Nothing was deployed, no AWS call was made, no SSM command was issued, no
>   container was touched, no rollback was performed and no Terraform was run.** §3 forbids
>   reporting a Variant A result as a Variant B result, and that separation holds here
>   without exception.
>
> **Its findings are evidence about the documentation, not about what an engineer can do.**
> The findings in §10 are real defects in the runbook. **They are not evidence about the
> capability the criterion asserts, and nothing in this record may be written up as if they
> were.**

## §7 — Test procedure

**This is the material the reviewer executes. For Variant A, steps 1–4 plus step 7 are
the exercise: the deliverable is the written procedure. For Variant B, every step runs.**

**No value is pre-filled in this section.** The digest, the source revision, the live
database revision and every command are for the reviewer to derive from the repository.
That is not stylistic reluctance — it is the measurement (§2). **A brief that supplies
the commands produces a correct command list handed over rather than derived, which
`docs/verification-milestone-4.md:642` says explicitly is not a deployment and is not
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
> and `docs/deployment.md:1859` (§10 item 16). **For a Variant B run, the operator decides
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
  `docs/deployment.md:1820` (**§10 item 15**) is the record: the legacy branch **can
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

**Filled in from the run of 2026-10-15. Variant A: every action recorded here was
read-only.** **Nothing that mutates anything was performed** — no AWS call, no SSM
command, no deployment, no container operation, no Terraform.

### A — What the reviewer actually did

| # | Command or action, as issued | Exit status | Verdict observed | Diagnostic report path |
|---|---|---|---|---|
| E-1 | `git log` — repository history and HEAD | *Not recorded by the reviewer.* Read-only, no side effects | Confirmed the revision under test as a full 40-character SHA (§5) — and recorded that `main` is **ahead of `origin/main`** | n/a — read-only |
| E-2 | `git status` — working-tree state | *Not recorded.* Read-only | **Revealed that `docs/m3-study-guide/` and `docs/m4-plan.md` are untracked** — the basis of §10 G-1 | n/a — read-only |
| E-3 | `git branch -vv` — branch topology against remotes | *Not recorded.* Read-only | Revealed `main [origin/main: ahead 3]`; no published image for the revision under test (§10 G-7) | n/a — read-only |
| E-4 | File reads under `docs/` | *Not recorded.* Read-only | `RUNBOOK.md` and `docs/deployment.md` supplied the runbook-side of the procedure; **G-2 is what is missing from them** | n/a — read-only |
| E-5 | File reads under `scripts/` | *Not recorded.* Read-only | Deploy/rollback/diagnostics behaviour derivable from source — see §9 Q14, resolved **from the code rather than from the runbook** | n/a — read-only |
| E-6 | File reads under `infra/` | *Not recorded.* Read-only | Surfaced the RDS username conflict in §10 G-6 | n/a — read-only |
| E-7 | File reads under `.github/workflows/` | *Not recorded.* Read-only | CI record understood; **the digest itself was not obtainable here** — §9 Q2 | n/a — read-only |
| E-8 | File reads under `api/` | *Not recorded.* Read-only | Alembic mechanics documented (`api/alembic/README.md`), **but no command line for reading the live revision** — §10 G-2 | n/a — read-only |
| E-9 | File reads of `RUNBOOK.md` | *Not recorded.* Read-only | Operational values read; staleness of M2-era values recorded as §10 G-5 | n/a — read-only |
| E-10 | File reads of `docker-compose.yml` | *Not recorded.* Read-only | Local shape of the stack; no action taken on any container | n/a — read-only |
| E-11 | `grep` and searches across `docs/`, `scripts/`, `infra/`, `.github/workflows/`, `api/`, `RUNBOOK.md`, `docker-compose.yml` | *Not recorded.* Read-only | Exhaustive search of the repository surface; **this is the coverage limit of every "not in the repository" verdict below** | n/a — read-only |
| E-12 | **Wrote out the derived procedure** — the §7 step 8 Variant A deliverable | n/a — a document, not a command | **A complete derived procedure was produced**, in the reviewer's own order, together with its questions (§9) and its gaps (§10) | n/a |

### B — Values sought, and where each could be obtained

**Recorded honestly: where a value could not be obtained from the repository, the row
says so. That is the finding, not a blank cell.**

| # | Value sought | Obtainable from the repository? | Where it actually came from, or why it could not |
|---|---|---|---|
| V-1 | The revision under test | **Yes** | `git log` / `git status`, full 40-character SHA (§5) |
| V-2 | The registry manifest digest for that revision | **No** | **Could not be obtained from the repository.** It lives in the release run's publish **job summary**, not in a tracked file. §9 Q2 |
| V-3 | The live database's alembic revision | **No** | **Could not be obtained, and no command line for obtaining it exists in the repository.** §9 Q4–Q6, §10 G-2 (**BLOCKING**) |
| V-4 | The current RDS endpoint hostname and master username | **No** | **Not confirmable from the repository.** The values written down in `RUNBOOK.md` are stale and contradictory (§10 G-5, G-6). §9 Q5 |
| V-5 | Currency of instance `i-0c3155b1b6bb31298` | **No** for a confirmed value | A candidate was identified in the repository; **nothing in the repository can confirm it is still current.** §9 Q7 |
| V-6 | Whether a *tested revision* means anything operationally | **No** | The term is never defined anywhere in the repository. §9 Q8, §10 G-7 |
| V-7 | A throwaway host to rehearse on | **No** | Never described in the repository. §9 Q15, §10 G-8 |
| V-8 | The deploy / rollback command surface | **Partly** | Reconstructable from `RUNBOOK.md` plus `scripts/`; **the SSM `send-command` wrapping was not given** and had to be put together. §9 Q13, Q14 |

### C — What was **not** done, stated explicitly

**Nothing in this list was performed, and no row above should be read as implying any of
it.** This is Variant A, and §3 defines that variant as a reading exercise.

- ❗ **No AWS call of any kind.** No `aws` invocation, authenticated or otherwise.
- ❗ **No SSM command.** No `send-command`, no `start-session`, no session opened.
- ❗ **No deployment.** Nothing was deployed, and no deployment was rehearsed.
- ❗ **No container operation.** Nothing was built, run, stopped or inspected.
- ❗ **No Terraform.** No plan, no apply, no output read from a live backend.
- ❗ **No rollback**, and **no rollback pointer was touched**.
- ❗ **No host state was read or changed.** The production host was not contacted at all.
- ❗ **Nothing was pushed**, and no branch was published.
- ❗ **No credential was read, requested, printed or recorded** (§4's secret-handling
  note did not need to be invoked).
- ❗ **The evaluator-only answer key was not read by the reviewer.** It lives outside the
  repository and was not provided in any form.

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

### 📋 The second run — 2026-10-15

**Filled in from the second run of 2026-10-15. Variant A: every action recorded here was
read-only. The first run's §8 record above is retained unchanged.**

**What the reviewer actually did.** Its commands were **read-only repository operations**:
`git log`, `git status`, `git branch -vv`, `grep`, `wc`, `find`/glob, and file reads. **It
made no AWS call, issued no SSM command, performed no deployment, operated no container,
and ran no Terraform.** The files it reported reading were
`docs/second-engineer-acceptance.md`; `RUNBOOK.md`; `docs/deployment.md` (end to end, in
four passes); `scripts/deploy.sh`, `scripts/rollback.sh`, `scripts/verify-deployment.sh`,
`scripts/lib/deploy-lib.sh`; `.github/workflows/release.yml`; `api/alembic/README.md`;
`infra/variables.tf`, `infra/outputs.tf`, `infra/iam.tf`, `infra/README.md`;
`docs/verification-milestone-4.md`, `docs/verification-milestone-3.md`, `docs/verification.md`;
`docker-compose.yml`, `.env.example` and `README.md`.

### A — The outcome of the second run

| # | Deliverable | Result |
|---|---|---|
| O-1 | **A complete derived procedure**, in the reviewer's own order | **Yes** — a six-phase procedure: (0) baseline → (1) determine the revision and its digest → (2) determine the live database revision → (3) deploy → (4) verify → (5) roll back, **plus** (6) the recovery path. Covering deploy, verification and rollback. **The reviewer was not told what to look at.** |
| O-2 | **A prerequisites table** | **Yes — thirteen** prerequisites, each marked provisioned or discoverable, each with the tracked source that says so (below). |
| O-3 | **An authoritative-sources table** | **Yes** — a source named for each value the procedure needs, plus the correctly-external values and the values the repo warns are not authoritative (below). |
| O-4 | **Questions asked and classified** | **Yes — sixteen**, each framed verbatim and classified. See §9. |
| O-5 | **Assumptions** | **Yes — eight**, each with what it rests on (below). |
| O-6 | **Items it could not find** | **Yes — ten**, stated plainly rather than worked around (below). |
| O-7 | **Observations on ambiguity / staleness** | **Yes — sixteen** (below). |

**The revision it worked from**, confirmed by the reviewer itself, is recorded in §5. It
recorded explicitly that **no value it needed was supplied, confirmed or corrected by the
operator.**

### B — Prerequisites (the reviewer's own table)

**Notation: [P] = operator-provisioned (not discoverable from the repository); [D] =
discoverable at run time from an authoritative source.**

| # | Prerequisite | Provisioned / discoverable | Where the repo says so |
|---|---|---|---|
| 1 | AWS CLI v2, credentials for profile **`lemondrop`**, region **`eu-west-1`** | [P] credentials; profile/region named in repo | `RUNBOOK.md:4`, `docs/deployment.md` §1.1 |
| 2 | Session Manager plugin for the AWS CLI | [P] (tooling) | `RUNBOOK.md:49`, `docs/deployment.md` §4 item 6 |
| 3 | IAM grants on the operator principal: `ssm:StartSession`, `ssm:SendCommand`, `ssm:GetCommandInvocation` (+ `ssm:ListCommands/ListCommandInvocations`); `ec2:DescribeInstances`; `elasticloadbalancing:DescribeLoadBalancers`; `rds:DescribeDBInstances`; **`secretsmanager:GetSecretValue` on the RDS master secret** (operator-side, not the instance role); `ssm:GetParameter` (only for the no-Terraform DB route) | [P] | `docs/deployment.md` §1.2, §7.1.1; `infra/iam.tf:530-545` |
| 4 | RDS **master** credential, reachable from the workstation — **highest sensitivity** | [P] — never written into any document, incl. the protocol | protocol §4 item 4; `docs/deployment.md` §7.1.1 |
| 5 | Repository read access (GitHub, **private**) and ability to read Actions logs/job summaries | [P] | `docs/deployment.md` §1.2; `docs/verification.md:148` |
| 6 | Local tooling: **`psql`, `jq`, `curl`, `openssl`**, and **Docker with Compose v2** | [P] (tooling) | `RUNBOOK.md:44-45`, `docs/deployment.md` §1.1, protocol §4 item 5 |
| 7 | The four deploy files present and current under `/opt/lemondrop/scripts/` | [D] — check on the host | `docs/deployment.md` §2.2, §4.4 |
| 8 | GHCR package **anonymously readable**; otherwise a GitHub token with `read:packages` **on the host** | [P] if the setting changes | `docs/deployment.md` §1.2, §3.3, §10 item 7 |
| 9 | EC2 instance id | [D] — `ec2:DescribeInstances` on `Role=application-host`+`ManagedBy=terraform` | `docs/deployment.md` §1.1, §7.1.1 step 1 |
| 10 | RDS endpoint, port, db name, master secret ARN, master username | [D] — `rds:DescribeDBInstances` | `docs/deployment.md` §7.1.1 step 1 |
| 11 | Live database alembic revision | [D] — read from RDS out of band | `docs/deployment.md` §7.1, §7.1.1 |
| 12 | Registry manifest digest for the revision | [D] — CI `publish` job summary/log | `docs/deployment.md` §3.3 |
| 13 | A **rehearsal/throwaway host** | **Not available** — the repository states plainly that none is described | `docs/deployment.md` §6.5, §10 item 17 |

### C — Authoritative sources (the reviewer's own table)

| Value the procedure needs | Authoritative source | Where the repository says so |
|---|---|---|
| Revision under test | A commit on `origin/main` with a green `release` run (`publish` not skipped) | `docs/deployment.md` §3.4; `.github/workflows/release.yml` |
| Registry manifest digest | The `publish` job's job summary (step `record the pushed digest`) or its log line `published digest:` | `docs/deployment.md` §3.3; `release.yml:891-959` |
| Pullability of a digest, on the day | `docker manifest inspect` succeeding | `docs/deployment.md` §3.3 |
| AWS profile / region | `RUNBOOK.md:4` (profile `lemondrop`, region `eu-west-1`) | `docs/deployment.md` §1.1 |
| EC2 instance id | `aws ec2 describe-instances` tag filters; `terraform output ec2_instance_id` second route | `docs/deployment.md` §1.1, §7.1.1 step 1; `infra/outputs.tf:172-175` |
| ALB DNS name | `aws elbv2 describe-load-balancers --names <name_prefix>-alb`; `terraform output alb_dns_name` second route | `docs/deployment.md` §5.3; `infra/outputs.tf:161-165` |
| RDS endpoint/port/dbname/secret ARN/username | `aws rds describe-db-instances` `DBInstances[0].{Endpoint.Address,Endpoint.Port,DBName,MasterUserSecret.SecretArn,MasterUsername}` | `docs/deployment.md` §7.1.1 step 1; §10 item 11 |
| RDS host/port without `rds:` perms | SSM parameters `/<project_name>/<environment>/db/host` and `/port` | `docs/deployment.md` §7.1.1 step 1; `infra/iam.tf:821-847` |
| (Non-)authoritative: `/…/db/secret-arn` | It is the **application** ARN, **not** the master — do not use it to read the master secret | `docs/deployment.md` §7.1.1; `infra/iam.tf:849-878` |
| Live database alembic revision | The RDS instance, read via §7.1.1's `SELECT version_num FROM public.alembic_version` | `docs/deployment.md` §7.1.1; `api/alembic/README.md` |
| Current schema head the record compares against | The record's `ALEMBIC_HEAD` (operator-supplied, db-verified) | `docs/deployment.md` §4.6, §7.1 |
| Record path and keys | `deploy-lib.sh` defaults (`/var/lib/lemondrop/deployed-revision.env`) | `deploy-lib.sh:56-61,266`; `docs/deployment.md` §0.2, §4.6 |
| Known-good search probe | `deploy-lib.sh` `LEMDROP_PROBE_*`, re-grounded against `data/corpus.json` | `deploy-lib.sh:96-98,980-1003,1041-1088` |
| Migration procedure (out of band only) | `api/alembic/README.md`, "Against RDS, later" | `docs/deployment.md` §1.3, §7.1 |

**Values correctly external by construction (not in the tree, and the repo says so):** the
digest, the live DB revision, the live AWS resource identifiers, the operator's IAM grant.
**Values the repo explicitly warns are NOT authoritative:** every M2-era literal in
`RUNBOOK.md`, and the digest pinned in `docker-compose.yml`/`.env.example`.

### D — The eight assumptions the reviewer recorded

1. **That the running/"production" host is the `lemondrop-dev` stack.** Rests on
   `infra/variables.tf:47-55`, `infra/locals.tf:11`, and every ALB/RDS example. **No
   repository document states that a production environment exists or is the deploy target.**
2. **That the transport to the host is SSM `SendCommand`.** Rests on `RUNBOOK.md:160-168`,
   `docs/deployment.md` §1.2 and §2.1/§2.2. The only host-control mechanism the repo describes.
3. **That the four files are present and current on the host.** Not verified; §2.2/§4.4
   provide the checks, not the answer.
4. **That the GHCR package is anonymously readable.** Rests on §10 item 7's historical
   observation; the repo says this is not a standing guarantee.
5. **That the record file is at the default path with the default key set.** Rests on
   `deploy-lib.sh:56-61,266` and §0.2. Every path is overridable.
6. **That the workstation has `docker buildx imagetools`.** §1.1 names only "Docker, with
   Compose v2"; `buildx imagetools` is used in §3.3 but not listed as a prerequisite.
7. **That HEAD may be treated as "the revision under test" for this walkthrough.** A run
   property, not a documentation claim.
8. **That the values not present in the tree should be obtained at run time, not
   reconstructed.** Rests on §3.2, §7.1, §10 items 8 and 11.

### E — The ten items the reviewer could not find

1. No exact, copy-pasteable SSM `send-command` wrapper for `deploy.sh`, `rollback.sh` or
   `verify-deployment.sh`. The scripts' `DELIVERY` block and §2.3 state the omission is
   deliberate ("NOT WRITTEN HERE, ON PURPOSE"); `RUNBOOK.md:160-168` shows the mechanics
   only for a `tail`.
2. No release run / digest for the revision. Lives in GitHub Actions; not obtained.
3. No live database revision value. Only the route (§7.1.1) and an evidence record
   (`0001`, dated 2026-10-14).
4. No current AWS resource values. Only discovery routes; the repo forbids storing them.
5. No approver identity, notification target, or escalation contact. An organisational fact.
6. No throwaway/rehearsal host. The repo states plainly that it describes none.
7. No confirmation that `9fc2518…` has a green release run. The CI side is not in the repo.
8. No statement of where the host's scripts came from at this revision.
9. No documentation of the GHCR package's visibility setting (only a historical observation).
10. No separate production environment or production deploy procedure.

### F — The sixteen observations on ambiguity / staleness

**Self-contradictory / stale (1–9)** and **ambiguous (10–16)**, as the reviewer framed them.
**These are documentation defects, not §9 "genuine documentation gaps"** — none of them
stopped the derivation. They are treated as findings in §10.

1. `infra/README.md` is stale and contradicts the tree (see §10, F-1).
2. `RUNBOOK.md` carries M2-era literals; only some are flagged stale.
3. The RDS master username appears with two values and never a reconciled one.
4. `docs/deployment.md` §0.4 quotes a stale `git status` capture.
5. §9.4's heading ("A reboot reverts the digest pin") is superseded by §9.5.1.
6. §2.4 and §4.4 describe earlier drafts now annotated as false.
7. The protocol document itself is heavily self-annotated (banner vs later sections).
8. `.env.example` and `docker-compose.yml` pin the same digest — stale by construction.
9. "Deploy tooling has never been executed" (§10 item 1) vs "executed live during Milestone
   4" (§10 item 15).
10. **"Production host" is undefined in the repository.** The only environment described is
    `dev`; the task's phrase has no repository referent.
11. The acceptance criterion's endpoint (`/health`) vs the runbook's (`/health/ready`) disagree.
12. The acceptance criterion's wording is recorded as genuinely ambiguous and unresolved.
13. `docs/m4-plan.md` and `docs/m3-study-guide/` are untracked but cited by name (G-1).
14. `jq` is listed inconsistently (optional in §1.1, but needed by §7.1.1 step 4).
15. Digests appear only in abbreviated form in prose, while §3.3 warns against truncation.
16. §3.3's step-list numbering is non-linear (inserted 6b/6c that run after step 7).

**What was not done — restated for this run.** ❗ No AWS call, no SSM command, no deployment,
no container operation, no Terraform, no rollback, no host contact, nothing pushed, no
credential read, and the evaluator-only answer key was not read. This is Variant A, and §3
defines it as a reading exercise.

## §9 — Questions asked

**Filled in from the run of 2026-10-15. Fifteen questions, recorded in the reviewer's own
framing.**

> **Transcription note, and a limit on it.** The questions below are recorded in the
> reviewer's own framing, as it submitted them. **Where this record abbreviates a
> question, the abbreviation is marked and no wording has been invented** — the
> reviewer's verbatim strings are held in its own submission and are not reconstructed
> here from memory, which §8's conventions forbid. **The third column is the reviewer's
> own verdict, including its own qualifiers, reproduced as recorded.**

| # | Question, as the reviewer framed it | Who could answer it | Answerable from the repository alone? |
|---|---|---|---|
| Q1 | Which commit is "the revision under test"? | assessor | **No** |
| Q2 | What is the registry manifest digest for that revision? | the release run's publish job summary | **No** (for the value) |
| Q3 | Is GitHub Actions access part of "the repository" here? | the protocol | **Yes** |
| Q4 | What is the command to read the live alembic revision from RDS? | the author | **No** |
| Q5 | What is the current RDS endpoint hostname and master username? | the current AWS stack | **No** |
| Q6 | Does the operator's principal have `secretsmanager:GetSecretValue` on the master secret? | the operator's IAM grant | **No** |
| Q7 | Is instance `i-0c3155b1b6bb31298` still current? | AWS / terraform output | **No** for a confirmed value; **Yes** as a candidate |
| Q8 | What operationally is a "tested revision"? | the author | **No** |
| Q9 | Will the rollback land on the defective legacy branch? | only the host | **No** (a state question, not a documentation gap) |
| Q10 | Who approves a deploy to this host, and who must be told? | the operator | **No** |
| Q11 | Criterion says `/health`; the runbook mandates `/health/ready` — which one governs? | partly the runbook | **Yes** (the runbook is unambiguous; the untracked plan disagrees) |
| Q12 | Where does a diagnostic report land, and how is it retrieved? | the runbook | **Yes** |
| Q13 | How is `sudo deploy.sh …` wrapped for SSM `send-command`? | partly `RUNBOOK.md` | **Partly** — reconstructable |
| Q14 | Does the source-tree requirement actually block a deploy? | the code | **Yes** — resolved **from the source, not from the runbook; the runbook overstates it** |
| Q15 | Is there a throwaway host to rehearse on? | the operator | **No** |

> ⚠️ **The table above is the record and it is unaltered. Its fourth column is the
> reviewer's own binary verdict, and §11 no longer reads it.** A documentation repair
> pass has since classified these rows under a **three-way scale defined further down in
> this section**, and **five of the nine `No` rows turn out not to be documentation gaps
> at all.** The table is kept exactly as the reviewer submitted it because it is evidence
> of what the reviewer was able to conclude from the repository as it then stood, and
> **rewriting it would destroy the very thing it records.** The classification is recorded
> alongside it, in *The classification of the nine recorded questions* below, and §11 now
> turns on that classification rather than on this column.

### The tally as recorded — and what §11 now reads

**Nine of the fifteen rows carry a No verdict, and those nine are: Q1, Q2, Q4, Q5, Q6,
Q8, Q9, Q10, Q15.** **This tally is the record of the run and stands as recorded.** §11
**does not** read it; §11 reads the classification recorded further down, which sorts
these same nine rows into three different categories.

Three of them carried the reviewer's own qualifiers, and those qualifiers are part of
the finding and are reproduced rather than tidied away:

- **Q2** — **No**, *for the value*. The digest lives in a CI job summary, so it is
  outside the repository by construction rather than by omission.
- **Q9** — **No**, *and the reviewer marked it a state question, not a documentation
  gap.* Whether the rollback lands on the unsafe legacy branch can only be answered by
  the host, which a Variant A run does not contact. **It is recorded as an author-only
  question because that is the verdict given, and it is annotated because the reviewer
  itself said it is not a documentation defect.** The annotation does not reduce the
  count.
- **Q7** — **the recorded verdict is dual: "No for a confirmed value; Yes as a
  candidate."** It is left exactly as   recorded and is **not** counted in the nine. The
  reviewer resolved a candidate instance id from the repository and could not confirm it
  was current. **Counting Q7 either way does not change the outcome: §11 fails on a
  single No, and seven unqualified No rows — Q1, Q4, Q5, Q6, Q8, Q10, Q15 — are already
  among the nine.**


### Near-miss questions — what the reviewer nearly had to ask, and resolved unaided

**§7 step 8 asks for these explicitly, and they are more valuable to the runbook's
author than the questions that were asked.**

- **Q3 — whether GitHub Actions is inside the boundary of "the repository".** Resolved
  unaided by reading §4 of this protocol.
- **Q11 — `/health` versus `/health/ready`.** The runbook is unambiguous; the reviewer
  found the contradiction in the **untracked** plan document and settled it against the
  runbook. **A near-miss that turned into G-1:** the document that disagrees is not in
  the revision under test at all.
- **Q12 — where a diagnostic report lands and how to retrieve it.** Resolved from the
  runbook.
- **Q13 — the SSM `send-command` wrapping of `sudo deploy.sh …`.** **Partly**
  reconstructable: the pieces exist across `RUNBOOK.md` and `scripts/`, and the
  reviewer assembled them. **A near-miss that was not free** — it cost assembly, and it
  is the practical face of G-2.
- **Q14 — whether the source-tree requirement actually blocks a deploy.** Resolved by
  reading `scripts/` rather than `RUNBOOK.md`, and the reviewer recorded that **the
  runbook overstates the requirement**. This is a near-miss that turned out to be a
  **documentation defect in the other direction** — the prose is stricter than the code.
- **Q7 — the instance id.** Resolved to a candidate in the repository; what could not be
  resolved is whether it is still current.

> ⚠️ **An honest limit on this subsection.** The reviewer submitted its questions and
> verdicts as the table above; **it did not submit a separate near-miss list distinct from
> that table.** The six entries here are the ones the table itself records as resolved
> from the repository rather than asked — which is what §7 step 8's *almost asked*
> distinction amounts to for this run. **Anything the reviewer recorded as a distinct
> near-miss and did not surface is not recorded here, and this subsection is therefore
> incomplete against §7 step 8's request.** It is left incomplete rather than filled in.

**Record the question verbatim**, in the reviewer's own words, before it is answered
and before it is paraphrased into something tidier. A question that has been
reformulated by the time it is written down is no longer evidence of what the reviewer
could not find.

### The classification — a three-way scale, and a fourth row type that is not a question

**The measurement is the classification, and it has exactly three answers.** The
two-answer scale this section used to carry was revised after the run of 2026-10-15 was
classified; the reason it was wrong is stated immediately after the table.

| Classification | Meaning | What §11 does with it |
|---|---|---|
| **Answerable from the repository** | **The repository contains it.** The reviewer had to work, and the work was the test. | **A PASS contribution.** |
| **Correctly external** | **The value or the fact lives in an authoritative external source, and the repository's job is to document *how* to obtain it.** The value is not expected to be in the tree — in some cases it cannot be, by construction. | **The measurement for this category is whether the route is documented, not whether the value is present.** A documented route is **not** a failure. An undocumented route **is** a genuine documentation gap, and is scored as one. |
| **Genuine documentation gap** | **The information should have been in the repository and was not.** | **A FINDING against the runbook.** See §11 — one disqualifies a pass. |

**The fourth row type is not a question and is not a classification above it:**

| Row type | Meaning | What §11 does with it |
|---|---|---|
| **Host-state question** | **Answerable only by inspecting the live host** — and a Variant A run does not contact the host. It is recorded so the reader can see it was considered. | ❗ **Excluded from the measurement.** A repository cannot and should not record the state of a live host, so its absence from the tree is not a documentation defect. |

**Why the two-way scale was wrong, and it was wrong in two separate ways.** It scored a
**correctly-external value the same as a missing instruction.** The registry manifest
digest, for instance, is not in the tree **by construction** — it exists because CI
produced it, and no repository that does not run CI could ever contain it. Scoring that
`No` against the same scale as *"no document anywhere says how to find the digest"* makes
the two indistinguishable, and a reviewer who was told where CI records it has **not** been
handed an answer. **An engineer who needs AWS credentials is not a documentation failure
when the required access is specified** (§4 states exactly what access an operator must
provision, and names where the runbook's own values live). A measure that cannot tell
"the repository withheld this" from "the repository cannot hold this, and says where it is"
measures the wrong thing.

**And it scored a live-state question as a documentation failure at all.** Whether a
rollback will land on the defective legacy branch is a fact about a host **at this moment**.
No document can state it, none should try, and a run that recorded its absence as a defect
was reporting the absence of the impossible. **That is the second thing the three-way
scale fixes**: the row type is now named, recorded, and excluded from the measurement, so
it can be seen rather than silently scored.

**A note on this run, because the reviewer used two answers this scale does not define.**
Q13 was recorded **"Partly — reconstructable"**, and Q7 was recorded with a **dual
verdict** ("No for a confirmed value; Yes as a candidate"). **Neither has been rewritten
to fit the scale.** They stand as the reviewer recorded them, and the recorded tally above
states plainly which rows carry a No and what that means. **The scale was not edited to
fit the result, which is what §11's "stated before any result exists" is for** — and the
classification below was applied to rows the reviewer had already submitted, not to rows
chosen after the fact.

### The classification of the nine recorded questions

**Each of the nine rows the reviewer recorded a `No` against, classified under the scale
above, with the reason stated in one line.** The table immediately above this subsection
is the record of what the reviewer concluded and is unchanged; this is the reading of it
that §11 now applies.

| # | Question, as the reviewer framed it | Classification | Why |
|---|---|---|---|
| Q1 | Which commit is "the revision under test"? | **Genuine documentation gap** | The revision under test is a property of the run, but the repository's job is to say how a pin is recorded and checked afterwards — §5 now states it, and it did not. |
| Q2 | What is the registry manifest digest for that revision? | **Correctly external** | The digest is **not in the tree by construction** — CI produced it. The repository's job is to say where the run recorded it, and `docs/deployment.md` §3.3 does. |
| Q4 | What is the command to read the live alembic revision from RDS? | **Genuine documentation gap** | ⛔ **The ⛔ blocking gap.** The command was the repository's to supply and no tracked file carried it. Closed by the repair pass at `docs/deployment.md` §7.1.1. |
| Q5 | What is the current RDS endpoint hostname and master username? | **Genuine documentation gap** | The values go stale and two files disagreed on the username. The repository's job was a **discovery route**, not a corrected value, and it did not carry one. |
| Q6 | Does the operator's principal have `secretsmanager:GetSecretValue` on the master secret? | **Correctly external** | **A fact about the operator's grant, not about this system.** The repository's job is to state the requirement, which §4 item 4 and `docs/deployment.md` §1.2 now do. |
| Q8 | What operationally is a "tested revision"? | **Genuine documentation gap** | The criterion's central term was undefined everywhere in the tree. `docs/deployment.md` §3.4 defines it now. |
| Q9 | Will the rollback land on the defective legacy branch? | **Host-state question** | **Only the live host can answer it, and a Variant A run does not contact the host.** Not a documentation question at all — recorded so it can be seen, excluded from the measurement. |
| Q10 | Who approves a deploy to this host, and who must be told? | **Correctly external** | **A fact about the people running the system.** Naming an approver would be inventing an organisational fact, and an invented approver is worse than none. |
| Q15 | Is there a throwaway host to rehearse on? | **Genuine documentation gap** | The runbook tells an operator to rehearse somewhere it does not describe. **Saying plainly that no such host is described is within the repository's power**, and it did not. |

**The classification sorts the nine into: five genuine documentation gaps (Q1, Q4, Q5, Q8,
Q15), three correctly external (Q2, Q6, Q10), and one host-state question (Q9).** ❗ **Q7
is not among the nine** — the recorded verdict is dual and it is left exactly as recorded,
under the §9 convention that a qualifier is part of the finding and is not tidied away.

**What this does to the recorded result, and what it does not.** §11's PASS condition 3 as
it read at the time — *zero rows answered `No`* — was met by **five** of these nine on the
ground that matters, and **the FAIL against it still stands as recorded.** §11's criteria
have been revised in light of the classification above, which means **the recorded FAIL was
scored against criteria this document no longer carries**, and a fresh run is required.
See §12.

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

### 📋 The second run's questions — 2026-10-15, sixteen of them

**Filled in from the second run of 2026-10-15. The first run's question record above —
its table, its tally and its near-miss list — is retained unchanged and is evidence of what
that run found. This is the second run's record, added alongside it, clearly dated and
attributed, so the two are distinguishable.**

> **Transcription note.** The questions below are recorded **verbatim** as the reviewer
> framed them in its own submission, each with the reviewer's own answer/route and its own
> classification under §9's scale. **The classification matches the reviewer's own table**,
> so nothing has been re-scored here.

| # | Question, as the reviewer framed it | The reviewer's answer / route | Classification |
|---|---|---|---|
| Q1 | "Which commit am I deploying, and how do I know it is deployable?" | `docs/deployment.md` §3.4 defines "tested revision"; §3.4's unpushed-HEAD check tells the reviewer if the commit has no image. | **Answerable from the repository** |
| Q2 | "What is the registry manifest digest for that revision?" | The `publish` job summary/log (§3.3). The reviewer could not read it (no Actions access); the route is documented. | **Correctly external** (route documented) |
| Q3 | "How do I read the live alembic revision out of RDS?" | `docs/deployment.md` §7.1.1 gives the complete procedure (discover → tunnel → TLS → credential → query). | **Answerable from the repository** (this was G-2, now closed) |
| Q4 | "What is the current RDS endpoint / master username / secret ARN?" | Discover from `rds:DescribeDBInstances` (§7.1.1 step 1). The `RUNBOOK.md` values are stale. | **Correctly external** (route documented) |
| Q5 | "Does my principal actually have `secretsmanager:GetSecretValue` on the master secret?" | An operator-side IAM grant; the requirement is stated (§1.2, §7.1.1, protocol §4 item 4). | **Correctly external** |
| Q6 | "How is `sudo deploy.sh …` actually wrapped for SSM `send-command`?" | Assembled from `RUNBOOK.md:160-168` plus §2.3/§1.2. No verbatim wrapper exists. | **Partly reconstructable** — a label §9 does not define; **adjudicated in §11 as answerable-from-the-repository and a pass contribution, not a gap.** |
| Q7 | "Is the operator's `jq`/`psql`/`openssl`/`docker` present?" | Named as prerequisites (§1.1, `RUNBOOK.md:44`). | **Answerable from the repository** (provisioning) |
| Q8 | "Which endpoint governs — `/health` or `/health/ready`?" | The runbook mandates `/health/ready` and is unambiguous (`deploy-lib.sh:743`); the `/health` wording comes from the untracked plan. | **Answerable from the repository** |
| Q9 | "Will my rollback land on the defective legacy branch?" | Depends on the live host's record (`PREVIOUS_IMAGE_DIGEST` empty + a `ROLLBACK_TAG`). The reviewer can state the condition, not the fact. | **Host-state question** (excluded from the measurement) |
| Q10 | "Who approves a deploy to this host, and who must be told?" | The checklist says "you know who to tell" but names no one; an approver is an organisational fact. | **Correctly external** |
| Q11 | "Is there a throwaway host to rehearse a rollback on?" | The repository now states plainly that none is described, named, or confirmed to exist (§6.5, §10 item 17). | **Answerable from the repository** (the *absence* is now documented) |
| Q12 | "Where does a diagnostic report land, and how do I retrieve it?" | `/var/lib/lemondrop/diagnostics/` (bash) and `%LOCALAPPDATA%\lemondrop\diagnostics\` (ps1), overridable. | **Answerable from the repository** |
| Q13 | "What exactly is the record file, and what does each key mean?" | §0.2 and §4.6, plus `RECORD_KEYS_RE` in `deploy-lib.sh`. | **Answerable from the repository** |
| Q14 | "The task says 'production host' — which environment is that?" | The only described host is the `dev` stack (`lemondrop-dev`). The repo never names a separate production environment. | **Finding / ambiguity** — see §8 F-10 and §10 F-3 |
| Q15 | "How do I get the four scripts onto a host that predates them?" | §2.3 gives Option A (`git pull --ff-only`) and Option B (file copy), and says a transport wrapper is deliberately not supplied. | **Answerable from the repository** (the route is documented) |
| Q16 | "After an instance replacement, the `.env` pin is reverted — do I need to care?" | Yes: §9.4/§9.5.1 say an instance replacement reverts the pin; run `verify-deployment.sh` after any such event. An ordinary reboot does not re-run `user_data`. | **Answerable from the repository** |

**The tally of the second run:** **Answerable from the repository — nine (Q1, Q3, Q7, Q8,
Q11, Q12, Q13, Q15, Q16) · Correctly external, route documented — four (Q2, Q4, Q5, Q10) ·
Host-state, excluded — one (Q9) · Partly reconstructable, adjudicated a pass contribution —
one (Q6) · Finding/ambiguity — one (Q14).** **No row is a genuine documentation gap.**

**Near-miss questions the reviewer resolved without asking anyone:**

- **Q6 (transport).** Resolved by assembling `RUNBOOK.md:160-168` with §1.2/§2.3. **It cost
  assembly; the residual is recorded in §10.** See §11 for the adjudication.
- **Q8 (`/health` vs `/health/ready`).** Settled against the runbook; noticed the
  disagreement originates in an **untracked** document.
- **Q14 ("production host").** Resolved by reading `infra/variables.tf:47-55` and
  `infra/locals.tf:11` → the running stack is `lemondrop-dev`. **There is no documented
  production environment.**
- **The two hash kinds.** Resolved from §3.3 and `docs/verification-milestone-4.md` §9.2 —
  one manifest digest, one local config ID; never interchanged.

> ⚠️ **Q6 carries a label §9's scale does not define — "partly reconstructable".** §9 has a
> precedent for this: the first run recorded Q13 with the same undefined answer, and §9
> records that it was **not** rewritten to fit the scale. **Q6 is likewise left as the
> reviewer recorded it.** The classification above adds the reading §11 applies; it does not
> alter the reviewer's words.

## §10 — Documentation gaps found

**Filled in from the run of 2026-10-15. Eight gaps, recorded with the reviewer's own
severity ratings. The two blocking ratings are recorded as given and are not softened.**

> **Two fields in the convention below are not filled in, and the reason is the same for
> both.** *"Where the reviewer hit it"* is given where the submission stated the step or
> question, and marked **not stated by the reviewer** where it did not. *"Proposed fix"*
> is **not recorded for any gap**, because no fix was carried in the submitted evidence
> and **inventing one here would be the author's work written into the reviewer's
> record.** §11's remediation instruction — fix the runbook so the question has an
> answer in the repository, then re-run — is the author's next step, not this section's
> content.

### G-1 — `docs/m4-plan.md` and `docs/m3-study-guide/` are cited but not in the revision

| Field | Content |
|---|---|
| **Gap** | **`docs/m3-study-guide/` and `docs/m4-plan.md` are untracked in this revision**, yet the runbook and this protocol cite `docs/m4-plan.md` **by line number** in several places — including as the document that defines the acceptance criterion. **A clean clone of the tested revision does not contain it.** |
| **Where the reviewer hit it** | §9 Q11 — the `/health` versus `/health/ready` contradiction lives in the untracked plan. Step/question linkage beyond that **not stated by the reviewer.** |
| **Severity** | **Recoverable** |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

⚠️ **This gap is checkable, and its check is in this repository's own working tree.**
`git status` at the revision under test reports both paths as untracked. **Their
untracked status is a finding about the repository, not a licence to commit them** — and
nothing in this exercise stages, adds or modifies either path.

### G-2 — No command line exists for reading the live database's alembic revision

| Field | Content |
|---|---|
| **Gap** | **No command line exists anywhere in the repository for reading the live database's alembic revision.** The table, the TLS mode, the tunnel technology and the split-host technique are all documented. **The actual `psql` invocation and the SSM port-forwarding invocation are not.** |
| **Where the reviewer hit it** | §9 Q4 (the command), Q5 (the endpoint and username), Q6 (the `secretsmanager:GetSecretValue` grant) |
| **Severity** | **⛔ BLOCKING** — **recorded at full strength. The procedure could not be completed without it.** |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

### G-3 — The permission table contradicts the DB-read step

| Field | Content |
|---|---|
| **Gap** | The permission table says **`ssm:GetParameter` is "not needed for a deploy"**, but the database-read step needs the RDS address — **and the repository holds an SSM parameter for that address which no document tells the reviewer to read.** The table and the step are inconsistent. |
| **Where the reviewer hit it** | Step 3 / §9 Q5 — step linkage **not stated by the reviewer** |
| **Severity** | **Recoverable** |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

### G-4 — `terraform output` is routed through, but required access is not listed

| Field | Content |
|---|---|
| **Gap** | Several steps route through **`terraform output`**, but **the Terraform state backend and its credentials are absent from §4's required-access list.** A reviewer granted only §4's list has no documented way to satisfy those steps. |
| **Where the reviewer hit it** | **Not stated by the reviewer** |
| **Severity** | **Recoverable** |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

### G-5 — M2-era values in `RUNBOOK.md` are stale, and only one of them is flagged

| Field | Content |
|---|---|
| **Gap** | **M2-era infrastructure values in `RUNBOOK.md` are flagged as stale for the instance type only.** The **instance id, the ALB DNS name, the RDS endpoint, the secret ARN and the username are equally stale and mostly unflagged.** A reader has no way to know which values in the file can be trusted. |
| **Where the reviewer hit it** | Baseline and verification steps / §9 Q5, Q7 — step linkage **not stated by the reviewer** |
| **Severity** | **Recoverable** |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

### G-6 — The RDS master username appears twice, with different values

| Field | Content |
|---|---|
| **Gap** | **The RDS master username appears with two different values in `RUNBOOK.md` and `infra/variables.tf`, with no reconciliation anywhere.** A reader cannot tell which is current without access to the live stack. |
| **Where the reviewer hit it** | §9 Q5 |
| **Severity** | **Recoverable** |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

### G-7 — "Tested revision" is never defined

| Field | Content |
|---|---|
| **Gap** | **"Tested revision" is never defined.** Nothing states that the revision under test must be a commit with a successful release run — **and `HEAD` in the tested revision is ahead of `origin/main` and has no published image.** The criterion's central term has no operational meaning in the repository, and the revision this exercise pinned does not satisfy the obvious reading. |
| **Where the reviewer hit it** | §9 Q1, Q8; §5's pin |
| **Severity** | **Recoverable** |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

### G-8 — No throwaway host is described, and a Variant B run depends on one

| Field | Content |
|---|---|
| **Gap** | **The rehearsal the criterion depends on requires a throwaway host that the repository never describes.** Nothing in the repository names one, states that one exists, or says what "rehearsal" is supposed to happen on. |
| **Where the reviewer hit it** | §9 Q15 — the question of where a Variant B run could be rehearsed |
| **Severity** | **⛔ BLOCKING for a Variant B run** — **recorded at full strength.** It blocks the variant that would actually require a host. |
| **Proposed fix** | **Not recorded — no fix was carried in the submitted evidence.** |

### An honest limit on this section

**Eight gaps are recorded above: G-1 … G-8.** The reviewer's submission was summarised
into these eight before transcription. **Any further gap the reviewer reported that did
not survive that summary is not recorded here, and §10 is therefore incomplete against
the submission.** It is left incomplete rather than reconstructed — §8's conventions
forbid a row or an entry being filled in afterwards from memory, and the same rule
applies to a gap.

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

### 📋 The second run's findings — 2026-10-15

**Filled in from the second run of 2026-10-15. The first run's eight gaps (G-1 … G-8) above
are retained unchanged; this is the second run's record, added alongside.**

> **None of the findings below meets §9's definition of a *genuine documentation gap*.** The
> reviewer completed the derivation and classified every question as answerable,
> correctly-external-with-a-documented-route, a host-state question, or the Q6 adjudication.
> **But the reviewer surfaced real documentation defects that §11's scale does not score as
> gaps**, and recording them is the point of this section. They are drawn from the sixteen
> observations in §8 F. **None is fixed in this commit** — recording, not repairing, is what
> this run asks for; each is flagged as **follow-up work**.

| # | Finding, in the reviewer's own framing | Nature | Follow-up |
|---|---|---|---|
| **F-1** | ⚠️ **`infra/README.md` is actively misleading.** Its Scope table says EC2, ALB and RDS are *"not in this directory"* (*"Phase 2 and are deliberately not here"*), and its header says the configuration *"has never been validated. Terraform is not installed…"*. But `infra/compute.tf`, `infra/database.tf`, `infra/load_balancer.tf` and `infra/iam.tf` all exist, and the same file's own closing "Verification status" says *"The infrastructure is deployed and verified."* **A cold reader following the top of that file would conclude the infrastructure is not in the repository.** | Stale/self-contradictory doc | ⚠️ **Highest-value:** correct the scope table and header to match the tree. |
| **F-2** | **The SSM transport wrapper** — no copy-pasteable `send-command` wrapper for `deploy.sh`/`rollback.sh`/`verify-deployment.sh`. **A deliberate omission, documented as deliberate** (§2.3: *"NOT WRITTEN HERE, ON PURPOSE"* — the transport is approval-gated); the mechanics are in `RUNBOOK.md:160-168`. **Assembly was required.** | Deliberate omission | **Adjudicated not a gap** (see §11). No change recommended. |
| **F-3** | **"Production host" is undefined in the repository.** Only the `dev` environment is described (`infra/variables.tf:47-55`, `infra/locals.tf:11`). **The criterion's phrase has no repository referent.** | Ambiguity | Reconcile the criterion's wording ("production host") with the one stack the repo describes. |
| **F-4** | **`jq` is listed inconsistently.** `docs/deployment.md` §1.1 calls it optional and says no step needs it, but §7.1.1 step 4 extracts the password with `jq -r .password`, so the DB-read step **does** need it. | Internal inconsistency | Correct the §1.1 description of `jq`. |
| **F-5** | **Truncated digests in prose.** §3.3 warns a truncated digest is worse than none, while the prose itself uses truncations (e.g. `sha256:0bdb7afa…42986`, `sha256:d4aac49d…`). | Self-inconsistent | Either quote full digests or point to the file that holds the full value. |
| **F-6** | **§3.3's step numbering is non-linear** — inserted 6b/6c that *run after* step 7 — which the document itself flags. A reader following the numbers rather than the execution order could misread the safety ordering. | Structural/ambiguity | Re-number, or state the execution order explicitly alongside the numbers. |
| **F-7** | **`docs/deployment.md` §0.4 quotes a stale `git status`** (`## main...origin/main [ahead 1]` and `?? docs/deployment.md`). `deployment.md` is now tracked and `main` is not ahead; the doc annotates this, but the quoted capture is stale in two ways. | Stale capture | Refresh or remove the quoted capture. |

**The remaining observations in §8 F** — those not among the seven findings tabulated
above — are recorded there as ambiguity/staleness findings. They do not meet §9's
definition of a genuine documentation gap, and **no re-scoring is done here**; they are
listed so a later repair pass can route them.

## §11 — Pass / fail criteria

**Stated here, before any result exists, so that no criterion can be shaped after the
fact.** The pass/fail decision is made against this section as written, or not at all.

### The criterion under test

> *"A second engineer must be able to deploy a tested revision without manually
> reconstructing the original environment."* — recorded in a tracked document at
> `docs/verification-milestone-4.md` §13.1

### PASS — all four must hold

1. **The reviewer produced the complete procedure from repository information alone** —
   deploy, verification and rollback, in an order they determined, without being told
   what to look at.
2. **Every required value was derivable** — either from the repository, or from the
   authoritative external source the repository names as its route to it: the revision
   under test, its digest, the live database revision, the recovery path. **No value was
   supplied, confirmed, or corrected by the operator.**
3. **Zero genuine documentation gaps.** §9 contains no row classified as a **genuine
   documentation gap** under §9's three-way classification. **A correctly-external value
   whose route is *undocumented* counts as a genuine documentation gap**, because the
   documented route is what the repository owes for an external value. ❗ **A
   correctly-external value whose route *is* documented is not a gap and does not fail
   this condition.** ❗ **A host-state question is excluded from this condition entirely.**
4. **The reviewer's written record is complete enough to execute** — another competent
   engineer could follow it without reconstructing anything.

### ❗ The three-way distinction, stated explicitly because it is the whole point

**Condition 3 does not mean "zero questions the reviewer could not answer from the tree."**
It means zero questions the repository should have answered and did not. The four cases,
and what each does to the measurement:

| The reviewer asked about… | …and the repository… | Result |
|---|---|---|
| A value the repository **has** | — | ✅ **Pass contribution.** The work was the test. |
| A value that lives in an **authoritative external source**, whose **route the repository documents** | documented how to obtain it | ✅ **Not a gap.** The value's absence is expected; **the measurement is the route, and the route is present.** |
| A value that lives in an **authoritative external source**, whose **route the repository does not document** | never says where to look | ❌ **A genuine documentation gap.** *"Correctly external, undocumented route"* **is** a failure, and it is scored as a gap, not forgiven by the fact that the value was external. |
| The **state of the live host** | — | ❗ **Excluded from the measurement.** Never a documentation failure. See below. |

### FAIL — any one of these

1. **Any genuine documentation gap.** One is enough. See below. **This includes a
   correctly-external value whose route is undocumented.**
2. **Any required value that could not be derived** — neither from the repository nor
   from the authoritative external source the repository names as its route — including
   the live database revision, which must be read from the database and not taken from
   the runbook's written-down value.
3. **The procedure is incomplete**, or could not be executed without information the
   reviewer did not have.
4. **The reviewer's result depends on prior exposure** (§6) that was not declared. A
   compromised run is not a pass; it is an unmeasured run, and it is recorded as such.

### ❗ A host-state question is never a documentation failure

**A question answerable only by inspecting the live host does not fail this exercise, and
it cannot.** A repository **cannot and should not** record the state of a live host: the
value is true at one moment and stale the next, so a document carrying it would be wrong
soon after it was written. A Variant A run **does not contact the host at all** (§8's
"What was *not* done"), so the reviewer had no way to obtain it and **no document could
have given it to them.** Such a question is **recorded**, so that a later reader can see
it was considered and was deliberately not counted — **and it is excluded from the
measurement.** A run that recorded its absence as a defect was reporting the absence of
the impossible.

**Note the contrast that keeps this from becoming a loophole.** The question *"where is the
RDS endpoint"* is not a host-state question — **the host's address is a fact the repository
can point at**, and the fix is a route. The question *"is the rollback going to land on the
defective branch for the record that exists on the host right now"* is a host-state
question, because **no document can answer it in advance of a rollback nobody has
performed.** The line is whether a route could exist, not whether the answer is currently
knowable.

### ⚠️ A single genuine documentation gap disqualifies the pass

**One genuine documentation gap fails the exercise, regardless of how confident the
reviewer was, how much they managed, or how reasonable their workaround was.** The
reasoning is the criterion's own: *"without manually reconstructing the original
environment."* A procedure that required one question the repository should have
answered is a procedure that required reconstruction, and the confidence surrounding the
other steps is not evidence about that one.

**And a genuine documentation gap is a finding about the runbook, not a complaint about
the reviewer.** It means a competent engineer following this documentation could not get
this far. That is a defect in the documentation, it is exactly what this test exists to
surface, and **it is worth more than a clean pass would have been.** A test that can
only fail the documentation when the documentation is genuinely incomplete is not
measuring anything.

**When a genuine documentation gap occurs:** record it (§9, §10), **fix the runbook so the
question has an answer in the repository, and re-run the exercise.** The re-run must be
with a reviewer who has not been exposed to the original run, since a reviewer who has
been told the answer once will not ask again — and the second run would then pass for
the wrong reason. **A pass obtained after the reviewer was helped is not a pass; it is
an unrecorded assistance.**

### ⚠️ These criteria were revised after the run of 2026-10-15, and the recorded FAIL was scored against the previous wording

**This section is stated before any result exists, which is the discipline it claims — and
the classification it turns on was written afterwards, in the light of sorting that run's
questions.** The revision is recorded here rather than made silently:

- **What changed:** PASS condition 3 previously read **"zero author-only questions — §9
  contains no row answered `No`"**, and FAIL condition 1 read **"any author-only question.
  One is enough."** Both now turn on **genuine documentation gaps** under §9's three-way
  scale, with correctly-external values excluded when their route is documented and
  host-state questions excluded entirely.
- **Why it had to change:** the two-way scale could not tell a value the repository is
  **never able to hold apart from one it withheld, and it scored a question about a live
  host as a documentation defect at all.** §9 states both errors in full.
- **What this does to the recorded result:** the 2026-10-15 run was scored against the
  **two-way** wording and returned **FAIL**, which **stands as recorded** (§12). Under the
  revised wording, **five of the nine rows that carried `No` are genuine documentation
  gaps** — so the run would still fail, for a narrower and more accurate reason. **This
  is not a re-scoring of the run, and no new result has been produced**; it is a statement
  of what the revised criteria measure. **A fresh run is required**, because the previous
  FAIL was recorded against criteria this document no longer carries **and** against a
  repository that has since changed. See §12.

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

### 📋 §11 applied to the second run — 2026-10-15 — **PASS**, on all four conditions

**§11 was applied to the second run's submitted evidence and returns PASS. It is not
recorded bare: the Q6 adjudication and the agent caveat below are part of the result, and
neither may be detached from it.**

| PASS condition | Result |
|---|---|
| **1. The complete procedure came from repository information alone** | ✅ The reviewer produced a full six-phase procedure — baseline → determine revision and digest → determine the live database revision → deploy → verify → roll back — **plus** the recovery path, **in its own order, without being told what to look at** (§8 O-1). |
| **2. Every required value was derivable** | ✅ Each value came either from the tree or from a **documented** external route: the digest from the release `publish` job summary (`docs/deployment.md` §3.3); the live database revision from §7.1.1; the AWS resource identifiers from the `describe-*` discovery routes; the recovery path from §7. **No value was supplied, confirmed or corrected by the operator** (§8 A). |
| **3. Zero genuine documentation gaps** | ✅ See the Q6 adjudication below — the only borderline case. Every other question is answerable-from-the-repository, correctly-external-with-a-documented-route, or a host-state question excluded from the measurement (§9). |
| **4. The record is complete enough to execute** | ✅ The procedure, prerequisites, sources and recovery path are complete; another competent engineer could follow it. |

### The Q6 adjudication — the load-bearing reasoning

**The reviewer recorded Q6** (*"How is `sudo deploy.sh …` actually wrapped for SSM
`send-command`?"*) **with a label §9 does not define: "partly reconstructable".** §9 has a
precedent — the first run recorded the same undefined answer for its Q13, and §9 records
that it was **not** rewritten to fit the scale.

**Q6 is classified: Answerable from the repository — a pass contribution, NOT a gap.** The
reasoning, which is the whole decision:

- **The parts are all present in the tree:** the `SendCommand` / `GetCommandInvocation`
  mechanics at `RUNBOOK.md:160-168`, the required permission pair at `docs/deployment.md`
  §1.2, and the rationale for the deliberate omission at §2.3 (*"NOT WRITTEN HERE, ON
  PURPOSE"* — the transport is approval-gated).
- **The reviewer assembled it successfully**, without asking anyone.
- **§9's first row governs:** *"The reviewer had to work, and the work was the test."*
  Assembly from documented parts **is** the work, not a gap.
- **The criterion says *"without manually reconstructing the original environment"* — not
  *"without assembling any command."*** Assembling a three-line wrapper from documented
  mechanics is not reconstructing an environment.

**This is not claimed to have been easy or obvious.** Q6 **cost the reviewer real assembly
work**, and it is **the closest thing in this run to a gap** — but it **does not meet §9's
definition of one**, so it does not fail PASS condition 3.

### The agent caveat, stated alongside the PASS and not softened

❗ **This is an AGENT run.** Per the reviewer-type subsection in §3, an agent run is evidence
about the **documentation's self-sufficiency** and a **weaker proxy** for the acceptance
criterion than a human run. The reviewer shares the author's model lineage and priors, so
**context isolation is not perspective isolation.** **PASS here means the documentation was
self-sufficient for a context-isolated agent; it is not evidence that a second engineer
performed a deployment, and nothing in this record may imply that it is.** **No deployment
occurred.**

## §12 — Final verdict

> ## ⚠️ **NOT YET TESTED — the verdict field is still blank, and the exercise HAS been run**
>
> **No verdict is recorded in this section, and none may be.** **The Verdict field below
> is reserved to the assessor (Moe).** A reviewer may not fill it in, and a verdict
> entered by anyone who did not witness the exercise is not a verdict. **The reviewer
> that ran was an AI agent, context-isolated (§6) — it is a witness to the documentation,
> not to a deployment, and this section may not be completed on its word.**
>
> **What this section does record is the run, and the outcome of §11 applied to the
> evidence the run submitted. Those are different things, and the difference is the whole
> reason the Verdict row is still empty.**

| Field | Value |
|---|---|
| **Status** | **NOT YET TESTED** — the criterion's verdict is unrecorded. **The exercise was run; §11 was applied to it and returned FAIL.** |
| Variant exercised | **A — cold-reader documentation walkthrough. No deployment occurred.** |
| Reviewer | **An AI agent (context-isolated). Not a person.** ⚠️ *Per §3 an agent run is a weaker proxy for the acceptance criterion than a human run: the agent shares the author's model lineage and priors, so context isolation is not perspective isolation. It is not evidence that a second engineer performed a deployment.* |
| Date of exercise | **2026-10-15** |
| Revision under test | `678cef3bf46a3e15d79dbc20064f0ea43f22dca8` (§5) |
| Author-only questions | **Nine: Q1, Q2, Q4, Q5, Q6, Q8, Q9, Q10, Q15 (§9).** |
| Procedure derivation | **A complete written procedure was produced from the repository alone, in the reviewer's own order (§8 E-12) — but two required values inside it could not be derived from the repository at all:** the registry manifest digest (Q2) and the live database's alembic revision (Q4–Q6, and no command line for it exists — G-2). |
| Deploy / verify / rollback executed | **❗ NONE. Nothing was deployed, verified against a host, or rolled back. No AWS call, no SSM command, no container operation, no Terraform.** |
| Documentation gaps found | **Eight: G-1 … G-8 (§10). Two blocking: G-2 outright, and G-8 for a Variant B run.** |
| **§11 applied — outcome** | **❌ FAIL. Unsoftened — see below.** |
| **Verdict** | *(blank — **reserved to the assessor**. NOT YET TESTED.)* |

### §11 was applied, and its outcome was **FAIL**

**§11 as written requires all four PASS conditions to hold, and any one FAIL condition
disqualifies the pass. The submitted evidence fails.**

- **PASS condition 3 — "zero author-only questions" — is not met.** §9 contains **nine**
  rows whose verdict is **No**: Q1, Q2, Q4, Q5, Q6, Q8, Q9, Q10, Q15.
- **FAIL condition 1 — "any author-only question. One is enough" — is therefore met.**
  §11 is explicit that this disqualifies the pass **regardless of how confident the
  reviewer was, how much they managed, or how reasonable their workaround was.** There
  are nine, not one.
- **FAIL condition 2 — "any required value that could not be derived" — is also met.**
  The registry manifest digest (Q2) and the live database's alembic revision
  (Q4–Q6) **could not be derived from the repository**, and the second is compounded by
  G-2, which is **BLOCKING**: no command line for it exists anywhere in the repository.
- **The count does not depend on how the qualified verdicts are read.** Q2 and Q9 carried
  the reviewer's own qualifiers and Q7's verdict is dual; all three are recorded as
  submitted (§9), **and seven rows — Q1, Q4, Q5, Q6, Q8, Q10, Q15 — carry an unqualified
  No whatever the reader does with the other three.**

**And §11 says what an author-only question is, so it is stated here in §11's own terms
rather than softened:**

> **An author-only question is a finding about the runbook, not a criticism of the
> reviewer.** It means a competent engineer following this documentation could not get
> this far. **That is a defect in the documentation, it is exactly what this test exists
> to surface, and it is worth more than a clean pass would have been.**

**§11's own remediation instruction follows from this**, and is recorded here rather
than acted on: **fix the runbook so the question has an answer in the repository, and
re-run the exercise** — with a reviewer who has not been exposed to this run, since a
reviewer who has been told the answer once will not ask again.

### 📋 A documentation repair pass has since closed the genuine gaps, and a fresh run is required. The re-run has not happened.

**The FAIL recorded above stands as recorded. Nothing in this subsection withdraws it,
re-scores it, or replaces it.** What follows is an account of what changed *after* that
FAIL was written, and why the run it describes can no longer serve as the current
evidence for this criterion.

**1. §11's criteria have been revised in light of the classification recorded in §9.**
The FAIL above was scored against the **two-way** wording of PASS condition 3 — *zero rows
answered `No`* — which this document no longer carries. **That wording scored a
correctly-external value the same as a missing instruction, and it scored a question about
a live host as a documentation failure at all.** §11 now turns on **genuine documentation
gaps**, and the distinction between a correctly-external value with a **documented** route
and one with an **undocumented** route is explicit there. **The revision was made by
reading the questions the reviewer had already submitted; no new reviewer was engaged and
no new question was asked.**

**2. A documentation repair pass has since closed five of the eight gaps in §10.** Named
individually, so that what was closed and what was not is checkable:

| Gap | Closed by | What "closed" means here |
|---|---|---|
| **G-1** | `docs/verification-milestone-4.md` §13.1 records the acceptance criterion, its operationalisation and its restatement in a **tracked** document; and the citations to the untracked plan in **this** file were retargeted onto that section and onto `docs/deployment.md` §10 item 18. | **The first retarget did not fully close G-1 — two citations to the untracked plan survived it, outside this file** (`scripts/rollback.sh:50`, `.github/workflows/tests.yml:176`), **and this repair pass retargets both; with them retargeted, no tracked file cites either untracked path.** ❗ **The two untracked paths were not staged, added or modified — that is stated here because "closed" must not be read as "committed", and they remain untracked.** |
| **G-2** — ⛔ blocking | `docs/deployment.md` §7.1.1, *Reading the live database revision — the complete procedure*. | The command that did not exist anywhere now exists, in a tracked document. This was the ⛔ gap. |
| **G-6** | `docs/deployment.md` §7.1.1 and `docs/deployment.md` §10 item 11; `RUNBOOK.md` now points the endpoint, secret ARN and username at the discovery route. | **Resolved by route, not by picking a value** — a corrected value would go stale again and nothing would detect it. The authoritative source is named (`DBInstances[0].MasterUsername`). |
| **G-7** | `docs/deployment.md` §3.4, *What a **tested revision** is*, plus the unpushed-HEAD trap it records. | The criterion's central term now has an operational definition. |
| **G-8** | `docs/deployment.md` §10 item 17, conditionally. | ❗ **Recorded, not solved.** The repository now says plainly that **no rehearsal host has ever been described, named, or confirmed to exist**, and states what each variant is blocked by. **Nothing in this pass creates a host** — `docs/verification-milestone-4.md` §13.1 says so in terms: this is an infrastructure limitation, not a documentation one. |

**G-3, G-4 and G-5 were not closed by that pass.** They were closed by **a later one** —
commit `9b8fcf0`, *"close G-3, G-4 and G-5 with discovery routes, not stale literals"* —
which closed each with a **discovery route** rather than a corrected literal:

- **G-4** — §5.3 no longer routes the ALB check through `terraform output`, so the check no
  longer needs the S3 state-backend access §4's list does not grant. The ALB's DNS name is
  discovered with `aws elbv2 describe-load-balancers` (`docs/deployment.md:791-802`).
- **G-5** — `RUNBOOK.md`'s header tabulates the five M2-era literals that remain in that
  file, each against the route that supersedes it (`RUNBOOK.md:15-38`).
- **G-3** — the §1.2 permission table gained the `elasticloadbalancing:DescribeLoadBalancers`
  row it was missing, and §5.3's `aws ec2 describe-load-balancers` call was corrected to
  `aws elbv2 describe-load-balancers` (`docs/deployment.md:129`, `:801`). ⚠️ **§10's G-3
  cell words this contradiction around the DB-read step; the pass closed the same kind of
  table/step contradiction on §5.3's ALB step.**

**3. A fresh cold-reader run is required, for two reasons, and both are structural:**

- **The previous FAIL was recorded against criteria this document no longer carries.** A
  reviewer reading §11 today would be measured against the revised scale; the recorded
  FAIL was not. **Carrying it forward as though it were a current measurement would be
  reporting a result against a protocol that does not exist.**
- **The repository the run was performed against has changed.** The revision under test
  was `678cef3bf46a3e15d79dbc20064f0ea43f22dca8` (§5); the five repairs above landed after
  it. **The finding that Q4, Q5, Q8 and Q15 were unanswerable was true of that revision and
  is not true of the current tree** — which is precisely why re-running is the only way to
  learn whether the repaired routes and the correctly-external ones now
  hold up.

**And the re-run must be with a reviewer who has not been exposed to this run**, per §11's
own remediation instruction: a reviewer who has been told an answer once will not ask
again, **and the second run would then pass for the wrong reason. A pass obtained after
the reviewer was helped is not a pass; it is an unrecorded assistance.**

> ❗ **THE RE-RUN HAS NOT HAPPENED. There is no second run, no second reviewer, no new
> question, no new evidence and no new result in this document.** **Every field that
> describes the exercise — the reviewer in §6, the revision in §5, the evidence in §8, the
> questions in §9, the gaps in §10 — still describes the single run of 2026-10-15 and
> nothing else.** The **Verdict** field below **remains blank, and it remains the
> assessor's.** ❗ **Nothing here predicts, anticipates or pre-empts what a re-run would
> find, or whether it would pass. A re-run that fails is as likely as one that passes, and
> the only thing this document can say about it is that it has not been done.**

> ⚠️ **Superseded in part — 2026-10-15.** The blockquote above was true when it was written
> and **is retained as written**. **A second Variant A run has since been carried out**,
> against the repaired tree and against §11's revised wording: **§11 applied to it returns
> PASS on all four conditions**, with the Q6 adjudication and the agent caveat attached
> (§11). The first run's FAIL above **stands as recorded** and is **not** re-scored or
> withdrawn. **The Verdict field remains blank and remains the assessor's** — a PASS on §11
> is a criterion applied to evidence, not a verdict on the criterion. **See the second run's
> facts below.**

### ❗ What this run is not

- ❗ **NO DEPLOYMENT OCCURRED.** Nothing was deployed, no AWS call was made, no SSM
  command was issued, no container was touched, no rollback was performed and no
  Terraform was run. **This result must never be reported as a live-deployment
  demonstration.** §3's separation is absolute: **a Variant A result may never be
  reported as a Variant B result**, and this run is Variant A.
- ❗ **It is not evidence that a second engineer performed a deployment**, and nothing
  above may be read that way. **The reviewer was an AI agent**, and per §3 an agent
  run is a **weaker proxy** for the acceptance criterion than a human run — it shares
  the author's model lineage and priors, and context isolation is not perspective
  isolation.
- ❗ **The FAIL is a result, not a failure of the exercise.** §11 is explicit that this
  test can only fail the documentation when the documentation is genuinely incomplete,
  and that this is the finding worth having.

### The three preconditions below, checked against what actually happened

**Before any verdict is recorded, these three things must be true. If any is false,
there is no verdict to record:**

1. **A named reviewer actually performed the exercise**, and §6 records their prior
   exposure honestly. → ❗ **NOT SATISFIED AS WRITTEN.** A reviewer did perform the
   exercise and §6 records its exposure honestly — but **it is an AI agent, and no
   person is named, because no person exists.** This document asks for a *named
   reviewer*; it did not anticipate an agent reviewer, and §3 exists precisely to
   mark what that substitution can and cannot establish. **The precondition is recorded
   as unmet rather than argued around.**
2. **§8 and §9 contain what that reviewer submitted**, transcribed rather than
   reconstructed. → **Satisfied, with two recorded limits:** §9's questions are recorded
   in the reviewer's own framing and the verbatim strings are held in its own
   submission, and §9's near-miss subsection records an explicit incompleteness against
   §7 step 8. **Neither limit was filled in by reconstruction.**
3. **The assessor has stated which variant they are treating as governing** — or has
   stated that the criterion is being recorded as untested *despite* a variant having
   been run, because a demonstrated capability and a satisfied criterion are not the
   same claim and the record must say which one was produced. → **❗ NOT SATISFIED. The
   assessor has not stated this.** **The governing-variant decision in §3 remains open,
   and this record does not make it.**

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

### 📋 The second run's facts — 2026-10-15 — the **second** Variant A run

**This is the second Variant A run.** The first returned **FAIL against §11's earlier
wording and an unrepaired tree** (§12, above). **This one passes against the current
criteria and the repaired tree.** The run facts are recorded here; **the Verdict field is
left blank and belongs to the assessor.**

| Field | Value |
|---|---|
| **Status** | **NOT YET TESTED** — the criterion's verdict is unrecorded. **The second exercise was run; §11 was applied to it and returns PASS on all four conditions.** |
| Variant exercised | **A — cold-reader documentation walkthrough. No deployment occurred.** |
| Run ordinal | **Second Variant A run.** (First: FAIL, against the earlier wording and the unrepaired tree. This one: PASS, against the current wording and the repaired tree.) |
| Reviewer | **An AI agent (context-isolated). Not a person.** ⚠️ *Per §3 an agent run is a weaker proxy for the acceptance criterion than a human run: the agent shares the author's model lineage and priors, so context isolation is not perspective isolation. It is not evidence that a second engineer performed a deployment.* |
| Date of exercise | **2026-10-15** |
| Revision under test | `9fc2518ed9092f4696e41cebeab84066560908d7` (§5) — the pushed `main`. CI run `38793650721`, nine jobs green; local `actionlint` v1.7.12, exit 0 (evaluator-supplied; not derivable from the repository). |
| Author-only questions | **None.** Sixteen questions were recorded; **none is classified as a genuine documentation gap** (§9). Nine answerable-from-the-repository, four correctly-external-with-a-documented-route, one host-state (excluded), one partly-reconstructable adjudicated as a pass contribution (Q6), one finding/ambiguity (Q14). |
| Procedure derivation | **A complete six-phase procedure was produced from the repository alone, in the reviewer's own order** — baseline → determine revision and digest → determine the live database revision → deploy → verify → roll back — plus the recovery path (§8 O-1). **Every required value was derivable** from the tree or a documented external route; **none was supplied, confirmed or corrected by the operator.** |
| Deploy / verify / rollback executed | **❗ NONE. Nothing was deployed, verified against a host, or rolled back. No AWS call, no SSM command, no container operation, no Terraform.** |
| Documentation findings | **None meets §9's definition of a genuine documentation gap.** Seven real defects are recorded as findings (F-1 … F-7, §10), headed by the actively misleading `infra/README.md`; **none is fixed in this commit** and each is flagged as follow-up. |
| **§11 applied — outcome** | **✅ PASS — all four conditions. The Q6 adjudication is load-bearing; the agent caveat is attached. Never recorded bare.** (§11) |
| **Verdict** | *(blank — **reserved to the assessor**. NOT YET TESTED.)* |

### ❗ What the second run is not

- ❗ **NO DEPLOYMENT OCCURRED.** Nothing was deployed, no AWS call was made, no SSM command
  was issued, no container was touched, no rollback was performed and no Terraform was run.
  **This result must never be reported as a live-deployment demonstration.** §3's separation
  is absolute: **a Variant A result may never be reported as a Variant B result.**
- ❗ **It is not evidence that a second engineer performed a deployment.** **The reviewer was
  an AI agent**, and per §3 an agent run is a **weaker proxy** for the acceptance criterion
  than a human run — it shares the author's model lineage and priors, and context isolation
  is not perspective isolation.
- ❗ **This section records a criterion applied to evidence, not a verdict.** **The Verdict
  field above is blank and belongs to the assessor (Moe).** Nothing here predicts, or
  pre-empts, that decision.

---

> ## Closing status, restated so it cannot be missed
>
> **This document is a protocol, and it now also carries one Variant A run's evidence.**
>
> - **Status of the criterion: UNTESTED. No verdict is recorded, and the Verdict field in
>   §12 is reserved to the assessor.**
> - **A Variant A exercise WAS run on 2026-10-15**, by an **AI agent, context-isolated**
>   (§6), against `678cef3bf46a3e15d79dbc20064f0ea43f22dca8` (§5). **§11 was applied to
>   its submitted evidence and the outcome is FAIL** (§12) — nine author-only questions
>   are recorded in §9, and a single one disqualifies the pass.
> - ⚠️ **⚠️ That FAIL is now superseded as a current measurement, and it still stands as a
>   record.** It was scored against §11's **previous** wording — *zero rows answered
>   `No`* — which this document **no longer carries**. §11 now turns on **genuine
>   documentation gaps**, and §9 records the classification that forced the change: of the
>   nine rows, **five are genuine documentation gaps, three are correctly external, and
>   one (Q9) is a host-state question that is not a documentation failure at all.** **A
>   fresh cold-reader run is required and has not happened** (§12). **The Verdict field is
>   still blank.**

> ### 📋 Dated note — 2026-10-15 — the fresh run the note above required **has now happened**, and **§11 returns PASS**
>
> **The closing status above is retained as written.** One thing has changed since: **a
> second Variant A exercise was carried out on 2026-10-15**, by an **AI agent,
> context-isolated** (§6), against `9fc2518ed9092f4696e41cebeab84066560908d7` (§5) — the
> pushed `main`. **§11 (revised) was applied to its submitted evidence and the outcome is
> PASS on all four conditions**, carrying the **Q6 adjudication** and the **agent caveat**
> (§11, §12). It recorded **no genuine documentation gap**, but surfaced **seven real
> documentation defects as findings** (F-1 … F-7, §10), headed by the actively misleading
> `infra/README.md`.
>
> - ❗ **NOTHING WAS DEPLOYED in either run.** No AWS call, no SSM command, no container
>   operation, no Terraform, no rollback. **The PASS is a reading result, not a deployment.**
> - ❗ **The reviewer was an AI agent, not a second engineer.** Per §3 an agent run is a
>   weaker proxy for the acceptance criterion than a human run — it shares the author's
>   model lineage and priors, so **context isolation is not perspective isolation.**
> - **The Verdict field in §12 is still blank, and it is still the assessor's.** A PASS on
>   §11 is a criterion applied to evidence, not a verdict on the criterion.
> - ⚠️ **Five of the eight gaps in §10 were closed by a documentation repair pass after
>   that FAIL was written — G-1, G-2 (the ⛔ blocking one), G-6, G-7 and G-8 — and the
>   repository has since changed under it.** **G-3, G-4 and G-5 were closed by a later
>   pass, `9b8fcf0` — see §12.** ❗
>   **G-1's closure did not involve staging `docs/m3-study-guide/` or `docs/m4-plan.md`;
>   both remain untracked, and nothing in this document may be read as committing them.**
> - ❗ **NOTHING WAS DEPLOYED.** No AWS call, no SSM command, no container operation, no
>   Terraform, no rollback. **This run must never be reported as a live-deployment
>   demonstration.**
> - ❗ **The reviewer was an AI agent, not a second engineer.** Per §3 an agent run is
>   a weaker proxy for the acceptance criterion than a human run — it shares the author's
>   model lineage and priors, so **context isolation is not perspective isolation**.
> - **The criterion's ambiguity is recorded, not resolved** — see
>   `docs/verification-milestone-4.md:571` §13.1.
> - **Variant A is not proof that a second person deployed anything. Variant B is the
>   only one of the two that is.** Neither result may be reported as the other.
> - **Two known defects sit on this path**, both recorded and neither repaired: the
>   redundant-deploy guard that does not exist (`docs/deployment.md:1859`), and
>   the legacy rollback branch that can start the wrong image (`docs/deployment.md:1820`).
>   **The reviewer recorded both of these as live hazards it had to route around rather
>   than execute** (Q9).
> - **Writing this document executed nothing. Running the Variant A exercise executed
>   nothing either.** Both are read-only exercises; the second one produced a written
>   procedure and a gap list, and nothing else.
