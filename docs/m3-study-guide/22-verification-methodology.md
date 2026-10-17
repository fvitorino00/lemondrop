# Ch22 — Verification Methodology: How "It Works" Becomes Evidence

## The problem this chapter solves

"It works" is not a fact. It is a **claim** — a sentence with no named check attached to it. In
Milestone 1 that sentence would have been true and useless: a table can be perfect and a
retrieval layer completely broken, and the two look identical from the outside.

This chapter is the method that converts the claim into something else: a named check, a named
actor, a recorded result, and — the part people skip — **a statement of what the result does
not reach**.

---

## 1. The discipline: never mutate AWS while verifying

**The rule: a verification pass is read-only. If a check changes the thing it is checking, it
is not a verification pass — it is a second change wearing a label.**

This is not a purity preference. It is structural:

- A check that mutates cannot be re-run. If it produces a surprising result, you cannot simply
  run it again to see whether the surprise was reproducible — the world it observed is gone.
- A check that mutates destroys the state that other evidence depends on. Confirming "the
  documents survived a container restart" after you have re-ingested the corpus is a claim
  about your re-ingestion, not about persistence.
- A check that mutates confuses *evidence* with *intervention*. Two rows in §12.1.1 say
  "**read-only**" and one says explicitly **"no apply was run to satisfy it, and none should
  be"** (§12.1.1 row 20 note). That sentence exists because the temptation to satisfy a
  reconciliation question with an apply is the exact failure the read-only rule prevents.

Concrete examples from this milestone, both in the same table:

| Check | Read-only? | What it would have destroyed if it had mutated |
|---|---|---|
| `terraform plan -detailed-exitcode` → no changes, exit 0 | **Yes** | An `apply` here would have *made* the state match and then claimed to have verified it. Circular. |
| RDS counts through an SSM port-forward | **Yes** | A write to establish "the counts are 20/20/40" would prove the writer works, not the reader. |

**The corollary, and it is the harder half: read-only does not mean harmless.** A read-only
check that prints a secret to your terminal has leaked it. The next section is about that.

---

## 2. Derive values from the system of record; never hand-write them

**The rule: an identifier your check depends on must be read from the authoritative source,
not typed by the person running the check.**

§12.1.1 row 18 records how the master secret was identified: the ARN was **read from
`DBInstances[0].MasterUserSecret.SecretArn`** — explicitly *"not hand-written"*, with the
reason spelled out: **a mistyped ARN would have produced a meaningless result.**

That is the whole argument in one line. Consider what hand-typing produces:

| Check | Result with a hand-typed ARN | What a reader concludes |
|---|---|---|
| "Can the instance role read the master secret?" | *No* — some error came back | "Least privilege is enforced." **Wrong.** |
| Same check, ARN read from `describe-db-instances` | *No* — `AccessDeniedException` | "The policy refused a caller who found the secret." **Right.** |

The two failures are indistinguishable unless you know which ARN was used. Deriving the value
makes the check self-describing.

**Where this pattern appears elsewhere in the repo, and why it generalises:**

- **SSM parameter names.** `config.py` builds `/lemondrop/dev/db/{host,port,secret-arn}` from
  `DB_SSM_PARAMETER_PREFIX` + a named leaf (`config.py:668-678`), and `infra/iam.tf` builds the
  same three paths from `var.project_name` / `var.environment`. `iam.tf` writes a long comment
  about how those names have already been mis-applied twice — once without the leading slash,
  once with a trailing one, the latter being a `ValidationException` at apply time. Two
  systems constructing the same string from the same variables is what makes that class of typo
  impossible rather than unlikely.
- **The model alias.** The workers register models under an alias; `main.py:84-85` reads
  `EMBEDDER_MODEL_ALIAS` / `RERANKER_MODEL_ALIAS` from the environment rather than hardcoding
  a `.gguf` filename. One name, read from configuration, used by both sides.
- **The corpus counts.** `store.count_by_collection` (`store.py:611-625`) exists so counts are
  *queried*, not remembered.
- **`-detailed-exitcode`.** The exit status is the result. "No changes" is an inference from
  output text; exit 0 is a value a script can act on.

**The test for a value:** *if I typed this from memory and got it wrong, would the check
quietly pass?* If yes, derive it.

---

## 3. The stderr/stdout pattern: make it impossible for a secret to reach a transcript

The rule, as recorded: **stderr was captured; stdout was discarded, so no credential could
reach the transcript.** (§12.1.1 row 18)

This is a **structural** defence, and structural beats disciplined. A rule you must remember
fails once, at 2am, on the one host where it matters. A shape that makes the outcome impossible
does not need remembering.

**Why the AWS CLI needs this shape specifically.** `secretsmanager get-secret-value` prints the
credential on **stdout**. That is the command's designed behaviour. So:

- Discarding stdout removes the credential by construction — not by "being careful not to
  print it".
- Keeping stderr preserves the **error**, which is what the operator actually needs: the error
  code is on stderr, the secret is not.

### The same principle, applied everywhere in this codebase

Look at how consistently the codebase does this. It is worth learning as a *style*, because
each instance is a shape rather than a reminder:

| Mechanism | Where | What it prevents |
|---|---|---|
| `SecretStr` for the DSN | `config.py:1183` | `str()` renders `**********`; reading the real value needs an explicit `.get_secret_value()` call, so the places that do it are greppable and few |
| Redaction helper | `db.py:114-150` | Removes the DSN, the bare password, **and the percent-encoded password** — the last is the one that bites, because "does the message contain the password" can pass while `abc%2Fdef` sits in the log |
| `hide_parameters=True` | `config.py:1490` | Stops SQLAlchemy's DEBUG logging echoing bound parameters — which for this service means document text and query strings |
| Log the class and SQLSTATE, not the message | `main.py:1418-1423` | asyncpg's `DETAIL` lines carry the failing row. SQLSTATE is a code, not data, and cannot carry a document. |
| The only loggable DSN component | `config.py:1380-1414` | `database_host` returns the host, or `"<unparseable>"`. A redacted repr that says nothing at all is safe but useless; this is safe *and* useful. |
| `raise ... from None` everywhere in the AWS path | `config.py:747`, `:758`, `:800`, `:810`, `:824`, `:832`, `:859` | A chained botocore/json exception renders its own traceback, and json's `DecodeError` renders a fragment of what it failed on — which is the credential. |
| `psql` with the password in `PGPASSWORD` and SQL on stdin | `lemondrop_app_bootstrap.py` | The password never reaches `argv` (visible in `ps`) and never reaches `~/.psqlrc` |
| The one log line the AWS path produces | `config.py:962-966` | Logs region, host, and a cache marker. **No DSN, no password, no secret body, no ARN.** The host already says which database it is. |

**The design rule underneath all eight:** *the full text goes to the log; the client gets
enough to act on.* `main.py:_summarise` collapses whitespace and caps at 200 characters;
`db._brief` collapses and caps at 120. Division of labour, consistently applied.

**Note also what is deliberately absent.** `_boto3_client` (`config.py:590-619`) takes no
`aws_access_key_id` argument, and there must never be one. Omitting credentials entirely puts
boto3 on its **default provider chain**, which on EC2 ends at the instance profile — temporary
credentials that rotate and expire on their own. Building a credential object from environment
variables by hand is the pattern that leaks credentials into subprocesses (they inherit the
environment), into crash reports (they read it), and into every log line that dumps
`os.environ`.

---

## 4. Distinguishing an ambiguous result from a pass

**This is the most transferable idea in the chapter.** An error is not a result. Two AWS errors
mean **opposite things**:

| Error | Means | Is it a pass for "the role cannot read the secret"? |
|---|---|---|
| `AccessDeniedException` | The IAM policy refused a caller who **identified the secret correctly**. The ARN resolved, the secret is there, policy said no. | **Yes.** This is the control working. |
| `ResourceNotFoundException` | The path **never resolved**. Wrong ARN, different visibility, or the call never got far enough to be refused. | **No.** A check that failed to run while wearing the costume of one. |

And the record's own words: *Recording which error came back is the only thing that separates
the two, so it is preserved here.* (§12.1.1 row 18 note)

### The generalisation: an error is a third outcome, not a pass

Any check can return three things, and most people only prepare for two:

```
PASS  — the thing is true
FAIL  — the thing is false
????  — the check did not run, or did not run properly
```

`ResourceNotFoundException` is `????`. So is a DNS failure, a timeout, a permission error on
the *wrong* resource, and an empty response. **A check that cannot distinguish `????` from
`PASS` is not a check.**

The design rule: **before you run, write down what a passing result looks like AND what an
ambiguous result looks like, and make sure your acceptance condition rejects the second.**
This is the same discipline as deciding in advance what observation would change your mind —
the subject of Ch23's *Evidence* stage.

### Two more instances of the same confusion in this record

**`ParameterNotFound` is separated from the rest — deliberately.** `config.py:733-744`
branches on the error code, because `ParameterNotFound` is not an IAM problem at all:

> *The parameter does not exist. Check whether it was deployed — `terraform apply` in
> infra/ creates it only when `var.enable_managed_database` is true.*

Versus the IAM hint for everything else: *The instance role needs `ssm:GetParameter` on this
parameter… unapplied policies are the most likely cause here.* Telling an operator to check a
policy when the parameter was never deployed sends them to the wrong console entirely.

**One observation cannot distinguish three mechanisms either.** §9.3 is the same shape applied
to a *pass*: the search succeeded on the first attempt after a database restart, and the
obvious reading is "`pool_pre_ping` rescued it." The record lists three explanations that all
fit — pre-ping discarded a stale connection; the pool held no checked-in connection at that
moment so the first checkout was already new; or plain timing — and names the **negative
control that was not run**: disable `pool_pre_ping`, restart, observe the difference. Until it
runs, the flag is the *intended* mechanism and the test is *consistent with* it. **Weaker, and
the only thing the evidence carries.**

---

## 5. Count what should be there; do not just check that nothing errored

**"No errors" is the weakest possible assertion.** It is satisfied by a system that did
nothing at all.

The pattern that fixes it: **assert a count, not an absence.** From this milestone:

| Weak assertion | Strong assertion, and what it rules out |
|---|---|
| "Search of collection A returned no document from collection B" | **"Collection A holds 20 documents and collection B holds 20."** A loader that silently dropped a collection now fails the check. `store.count_by_collection`'s docstring says exactly this: *"A NUMBER rather than a boolean assertion, and that distinction is the point."* (`store.py:611-625`) |
| "All 40 documents were sent" | **"40 of 40 stored, 0 failed, plus `infrastructure`=20 and `it-support`=20 confirmed independently at `psql`."** Per-collection counts, not one total — "40 sent" and "20/20" answer different questions (§5.2). |
| "10 canaries exist" | **"10 of 10 canaries passed through the ALB, in BOTH directions."** Rows 14 and 19 in §12.1.1: the first records that the canaries exist, the second that they behave. Recording a count is not the same as exercising it, and the record keeps them as separate rows. |
| "Terraform looks reconciled" | **"No changes, exit 0"** — a quoted exit status from `-detailed-exitcode`, not an eyeballed diff. |
| "`candidates_considered: 5`" | The response reports **what stage 1 actually returned**, `len(candidates)`, not the requested `candidate_limit` (`main.py:1523-1527`). A collection with three documents and a limit of ten yields 3; reporting 10 would claim work that never happened. |

**Counting both sides is the point.** "20 infrastructure and 20 it-support" forces
verification of BOTH sides. "No it-support rows came back" forces verification of one and is
satisfied by an empty table.

---

## 6. Why a test that cannot fail is not a test

Forward-reference: the full method is Ch18. What belongs here is the specific shape the
problem takes in this codebase, because it is the most instructive bug class in the milestone.

### The blind isolation test, in full

The original `test_retrieve_returns_only_documents_from_the_asked_collection` used a query
vector seeded `_vector(1)` — **the same seed as the `alpha-0` fixture**. So `alpha-0` sat at
distance exactly `0.0000` from the query, and the global top-3 came back as:

| Document | Distance | Collection |
|---|---|---|
| `alpha-0` | 0.0000 | A |
| `alpha-1` | 0.1298 | A |
| `alpha-2` | 0.1747 | A |
| (`beta-0`) | (0.1747) | B |

**All three of the global top-3 were collection A's.** A fetch-then-filter implementation would
return all three, `len(from_a) == 3` would hold, and **the test would PASS against the broken
code**. The test was discriminating on a coin flip that happened to land the right way. It was
not a test of SQL filtering; it was a test of which three of eight deterministic vectors
happened to be numerically closest.

### How it was caught: mutation, not argument

`store.retrieve` was temporarily rewritten into global-top-N-then-filter-in-Python and the test
run against the mutated implementation:

| Run | Result | Verdict |
|---|---|---|
| Old seed **+** post-filter mutation | **PASSED** | **DEFECT CONFIRMED** — the test was blind |
| New seed (`_vector(104)`, one of B's own seeds) **+** post-filter mutation | **FAILED: `assert 2 == 3`** | **DEFECT CONFIRMED** — and the new seed discriminates |
| `store.py` restored | **Byte-identical** to its pre-mutation state (`git diff` empty) | **VERIFIED** |

Measured with the corpus loaded after the seed change, the global top-3 is `beta-4` (0.0000),
`alpha-0` (0.2103), `alpha-1` (0.2380) — **two** A documents, so a post-filter returns 2 where
the `WHERE` clause returns 3.

### The durable fix: assert the discriminating property on every run

The test no longer relies on a comment. It computes the global shortlist and asserts:

```python
shortlist_a = [i for i, c in global_shortlist if c == FIXTURE_COLLECTION_A]
assert len(shortlist_a) < 3, "a fetch-then-filter could fill the limit entirely from
                              the right collection and len(from_a) == 3 would be
                              satisfied by the bug. This test no longer
                              discriminates."
```

> *A test whose discrimination depends on incidental numeric properties of its fixtures must
> assert those properties on every run. A comment saying "this seed was chosen because…" is a
> claim about arithmetic that silently rots the first time someone edits `_vector`.* (§8.5)

The same control exists at the corpus level, and it is stronger: a canary pair only proves
isolation if the twin is genuinely competitive. `test_search.py::test_the_collection_filter_holds_against_the_adversarial_canary_pairs`
asserts **both** directions of the control in the same test:

- the twin **must be** in the global unfiltered top-10 — *"so its absence from the scoped
  search proves nothing. Pick a canary pair whose twins are genuinely competitive."*
- the collection asked for must hold **fewer than the limit** of the global shortlist — *"so a
  fetch-then-filter would have filled the whole candidate list from the right collection and
  this canary pair would prove nothing."*

The second assertion catches the **starvation** failure as well as the **leak** failure. Most
isolation tests catch only the leak.

### The same bug class appears in the failure history

§12.3 names the `OOMKilled=false` misclassification alongside the blind test for exactly this
reason: *"a check that passed, or a check that read cleanly, while the thing it claimed to
cover was broken."*

The OOM case is subtler and worth holding onto: the reading **was not wrong and was not
fabricated — it was taken against the wrong object.** It described the *restarted* container
rather than the one that died. `RestartCount = 2` was the corroborating evidence and was
under-weighted in favour of a single flag answering a question about the wrong subject. The
record's framing is the sharpest available:

> *A diagnostic read from a restarted process describes the new process.* … a bad measurement
> invites distrust of the number, while **a well-formed reading of the wrong object invites
> full trust**.

---

## 7. How to design a check that is capable of returning a bad result

The recipe. Work through it before you run anything.

### Step 1 — Write the claim as a sentence with a subject and a predicate

Not "test isolation". **"A search scoped to `infrastructure` returns documents only from
`infrastructure`."** The subject and the predicate are what you will have to observe.

### Step 2 — Write the failing case *first*, and make it concrete

"If the filter leaked, the response would contain `support-…`, because that twin ranks #2
globally at distance 0.3018." Now you have a **named** value to look for, not a vibe.

### Step 3 — Ask: what does a broken implementation actually produce?

This is the step everyone skips, and it is the whole trick. A fetch-then-filter does not
produce "wrong documents" — it produces **fewer, correct documents**. So an assertion on
*presence of a foreign document* passes against the broken code, and an assertion on
*count* fails. You have to know the shape of the failure before you can write the assertion
that catches it.

### Step 4 — Establish that the input makes the failure possible

Either by arithmetic (seed `_vector(104)` so the global shortlist under-fills) or by a **control
assertion that runs every time**. "Is the twin competitive?" is not a comment; it is a query
against the unfiltered shortlist, asserted.

### Step 5 — Prove the check can fail, by breaking the thing

Mutation. Temporarily replace the correct implementation with the broken one, run the check,
watch it go red, restore, and **verify the restore** (`git diff` empty).

> **Never skip step 5 for a check that guards a claim you care about.** A test that has never
> been seen to fail is a hypothesis about a test.

### Step 6 — Bound the claim to the observation

Say what window, how many samples, which environment. "No new OOM **within the verified search
window**" — with the window's length noted as unreported — is an honest bounded claim. "No
OOM" is not.

### A worked table, from this milestone

| Claim | Naive check | Does it discriminate? | The fix |
|---|---|---|---|
| The app uses the least-privilege credential | `/health/ready` returns `database: ok` | **No** — `ok` is consistent with master and app | Read the connection identity; assert `lemondrop_app` and not master (§12.1 row 16) |
| The role cannot read the master secret | "some error came back" | **No** — `ResourceNotFound` looks identical | Read the ARN from the API; assert `AccessDeniedException` specifically |
| The corpus is complete | "the loader exited 0" | **No** — a loader that dropped a collection can still exit 0 | Query the database: 20 / 20 / 40 |
| Results are isolated | "no foreign id in the response" | **No** — passes against fetch-then-filter | Assert the count *and* the control (the global shortlist under-fills) |
| The container was not OOM-killed | `OOMKilled == false` | **No** — read after restart, describes another container | Check `RestartCount` and the cgroup/kernel OOM log, not one flag |
| Persistence works | "it came back up" | **No** — a `down -v` destroys data and still comes back up | Restart without `-v`; count rows; run a real search |
| Terraform matches reality | "the plan looks clean" | **No** — looks are eyeballed | Quote `terraform plan -detailed-exitcode` **exit status** |

---

## 8. Provenance: who ran it

The verification record distinguishes, on every row:

- **Executed by: operator** — the operator ran the command and pasted terminal output. The
  agent did not run it and cannot re-run it. Transcribed from the operator's report.
- **Executed by: CEO** — run by the agent using read-only commands, with the real command and
  its real output pasted, so anyone can re-run it and get the same thing.

> *An operator-executed check recorded here as if the agent had run it would be a fabricated
> claim wearing a real one's clothes.*

**All twenty rows of §12.1 and §12.1.1 are operator-executed.** Ch21's table is a record of
somebody else's observations. That is not a weakness in the evidence — the operator had
credentials, a live instance and a terminal, and the agent had none of those. It is a
**labelling** discipline: so a reader knows exactly what kind of thing each row is.

**What can be re-checked from the document alone**, and what cannot (§7):

```bash
grep -c '"collection": "infrastructure"' data/corpus.json   # Expected: 20
grep -c '"collection": "it-support"' data/corpus.json       # Expected: 20
grep -c '"isolation_canary": true' data/corpus.json         # Expected: 10
.venv/bin/python -m pytest --collect-only -q                 # Expected: 62 tests collected
```

The Phase 1 schema claims, 40/40 ingested, the three-way codec measurement, and the live
`/search` rankings **cannot** be re-checked from the document alone — they need the dev database
and the rebuilt API container, and were operator-executed.

---

## 9. What this chapter is not

It is not a licence to skip things. The M3 failure history is a record of things that were
built, broken, and then fixed:

1. `RuntimeError` from the credential resolver — `config.py` reads a region from
   `AWS_REGION`/`AWS_DEFAULT_REGION` and compose passed neither. Established by checking
   botocore's actual resolution order rather than arguing (§12.3).
2. `IMDSv2` hop limit of 1, too strict for a container — corrected to 2, with `http_tokens`
   **still `required`**. Two different settings; only one was traded.
3. Three kernel OOM kills of `llama-server` — the arithmetic in Ch24's stages.
4. `--parallel 1` — a correction that **did not fix the OOM**, and that is why it was
   informative. `self.pool_pre_ping` was never tested against a negative control; §9.3 says so.

**None of those is a verification failure.** They are engineering. Verification is the
discipline applied *after* the engineering, to decide which of them are actually fixed — and
the reason three of the five criteria could be VERIFIED in the cloud at all is that four
earlier local criteria had been verified properly enough to build on.

---

**Key terms:** provenance · read-only verification · system of record · derived vs hand-typed
identifier · structural secret hygiene · `stderr` capture / `stdout` discard · `AccessDeniedException`
vs `ResourceNotFoundException` · count-not-absence · negative control · mutation testing ·
control assertion · bounding a claim to a window · supersede banner

**Recall questions:**

1. **Why did the record require the master-secret ARN to be read from
   `DBInstances[0].MasterUserSecret.SecretArn` rather than typed?**
   *Because a mistyped ARN produces a meaningless result. Hand-typing it and reading a name
   back from the API produce the same "denied" word, but only the second proves the caller
   identified the secret correctly before being refused. Deriving the value makes the check
   self-describing.*

2. **Why capture stderr and discard stdout when probing Secrets Manager?**
   *Because `get-secret-value` prints the credential on stdout by design, and errors on stderr.
   Discarding stdout removes the secret structurally rather than by discipline; keeping stderr
   keeps the one thing the operator needs — the error code. A rule you must remember fails at
   2am; a shape that makes the outcome impossible does not need remembering.*

3. **What is the difference between `AccessDeniedException` and `ResourceNotFoundException`
   in the least-privilege check?**
   *`AccessDeniedException` is the policy refusing a caller who found the secret — a pass,
   because the control worked. `ResourceNotFoundException` means the path never resolved: the
   check failed to run while wearing the costume of one, and is not a pass. Recording which
   error came back is the only thing that separates them.*

4. **Why does "no errors occurred" make a weak assertion?**
   *Because it is satisfied by a system that did nothing. Assert counts instead — and both
   sides of them. "20 infrastructure and 20 it-support" forces verification of both; "no
   it-support rows came back" is satisfied by an empty table. `store.count_by_collection`
   exists for exactly this reason.*

5. **What did the blind isolation test get wrong, and how was it proved?**
   *Its query vector shared a seed with a fixture, so all three of the global top-3 were
   collection A's — and a fetch-then-filter returned all three, passing against the broken
   code. It was proved by mutation: rewrite `store.retrieve` into fetch-then-filter, watch the
   old test pass (`DEFECT CONFIRMED`) and the new seed fail (`assert 2 == 3`), restore, and
   confirm `git diff` is empty.*

6. **What is a negative control, and which one was never run?**
   *A check that removes the thing you believe is helping, to see whether the result changes.
   `pool_pre_ping=True` is the intended reason the first post-restart search succeeded — and the
   negative control (disable it, restart the database, observe) was never run. So the test is
   *consistent with* the mechanism, which is weaker than establishing it.*

7. **Give the six-step recipe for designing a check that can fail.**
   *Write the claim as subject + predicate; write the concrete failing case first; work out
   what a broken implementation actually produces; establish that the input makes that failure
   possible (arithmetic or a control assertion that runs every time); prove the check can fail
   by mutating the implementation; and bound the claim to the observation you actually made.*
