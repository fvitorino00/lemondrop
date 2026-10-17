# Milestone 4 — Implementation Plan

**Status:** plan only. No code, workflow YAML, Terraform or scripts exist yet.
**Author:** RECOVERY · **Date:** 2026-10-13 · **Branch:** `main` @ `d9593cc`

---

## 0. Executive summary

Milestone 4 is not "add some CI." It is **"stop building the deployed artifact on the host that runs it."**
Everything else — the workflows, the registry, the tag strategy, the rollback script — exists to serve that
one change, because that change is what the acceptance criterion is actually about.

Three findings from reading the repo reframe the milestone:

1. **The test suite cannot go into CI as one job.** Of the 196 tests, 140 run with no services at
   all (T1); 44 of those are in `api/tests/test_db_credentials.py`. The rest require real
   PostgreSQL (T2) and/or the live stack (T3). Requirement 1 as written is underspecified; §3.1
- [REVISED 2026-10-17 — see 06-CATALOG-ERRATA.md §III: measured test-suite breakdown — T1=140 (service-free), T2=28 (disposable pgvector), T3=28 (live-stack), total 196; CI runs T1+T2=168 of 196, T3=28 excluded from PR CI. This supersedes any historical '146 total / 118 in CI' claim. Original text preserved.]
   proposes the split.
2. **`terraform init` in `infra/` cannot run in credential-less CI.** `infra/versions.tf:41` declares a
   real `backend "s3"` pointing at the live state bucket. §3.4 gives the one-flag workaround.
3. **The registry decision is not actually a fork, and it is being framed backwards.** This repo is
   **public**, and `docker-compose.yml:90` and `:164` already pull `ghcr.io/ggml-org/llama.cpp:server`.
   GHCR is not a new external dependency — it is a dependency the project already has. Choosing ECR would
   *add* one. §2 recommends GHCR.

The single highest-value fact carried forward from M3: `scripts/boot.sh:196` clones with `--depth 1`, and
`docs/verification-milestone-3.md` §11.2 correctly identifies that this makes `git fetch --unshallow`
**mandatory before any rollback — "without it there is no rollback path at all."** Deploying a prebuilt
image instead of a git checkout does not just improve rollback; it **deletes this landmine entirely.**

---

## 1. Gap analysis

### 1.1 Requirement 1 — GitHub Actions for application tests and dependency checks

| Sub-requirement | State | Evidence |
|---|---|---|
| Any CI at all | **Absent.** `.github/` does not exist. | `ls .github` → *No such file or directory* |
| Tests run in CI | **Absent** | — |
| Dependency checks | **Absent, and weaker than assumed.** | `api/requirements.txt` and `api/requirements-dev.txt` contain **0** `--hash` lines. Packages are pinned with `==` but not hashed. |

The "dependency checks" half of this requirement is the weaker one, and it is weak in a way worth naming:
the repo has **version pinning but no integrity verification**. A pinned-but-unhashed dependency can be
replaced upstream at the same version number and CI would install it without complaint. That is a supply
chain property, not a dependency-freshness property. See §3.3 for the decision.

**Where it is closer to done than it looks:** the test suite itself is genuinely good — 196 tests, real
services, no mocks, and explicit written refusal to `pytest.skip()`
(`api/tests/test_db.py:23-26`, `api/tests/test_search.py:25-28`). The *substrate* is unusually mature. What
is missing is only a place to run it. M4 is mostly plumbing, not test authoring.

### 1.2 Requirement 2 — Terraform formatting and validation

| Sub-requirement | State | Evidence |
|---|---|---|
| `terraform fmt` enforced | **Absent** | no CI exists |
| `terraform validate` enforced | **Absent** | no CI exists |
| Both stacks covered | **Two stacks exist**, not one: `infra/` (main, remote backend) and `infra/bootstrap/` (local backend) | `infra/versions.tf:41`, `infra/bootstrap/terraform.tf` (no `backend` block, by design) |

**Where it is closer to done than it looks:** the config is well-formed and heavily documented —
`infra/versions.tf` alone is 5,658 bytes of rationale for a 3-line backend block. `infra/bootstrap/main.tf:115`
even ships a `validation` block that fails loudly on an unfilled placeholder. The quality bar is high
because someone already cared. The risk is therefore not *authoring* friction; it is that **`terraform fmt
-check` may fail on day one** and someone must decide whether that is a CI failure or a first `terraform fmt`
commit. I could not verify which — see §9 open questions.

### 1.3 Requirement 3 — Docker image builds and publication of versioned images

| Sub-requirement | State | Evidence |
|---|---|---|
| A Docker build exists | **Yes.** | `api/Dockerfile` (63 lines, well-reasoned layering) |
| An image is built today | **Yes — but on the target host, at boot.** | `docker-compose.yml:311` `build: ./api`; `boot.sh:267` `docker compose up -d --remove-orphans` |
| A registry exists | **None.** No `ecr` resource in `infra/*.tf`. No `ecr:*` action in `infra/iam.tf`. | `grep -rn ecr infra/ --include=*.tf` → only false-positive substring matches (`reconcile`, `credentials`) |
| Versioned publication | **None.** | — |

**This is the central gap and it is bigger than "no registry."** The image named `lemondrop-api`
(`docker-compose.yml:314`) exists only in the Docker daemon of whichever machine last ran
`docker compose up --build`. It is not an artifact. It is a side effect. Nothing outside the EC2 host has
ever seen it.

**Where it is closer to done than it looks:** the `llama.cpp:server` workers are *already* pulled as
versioned third-party images (`docker-compose.yml:90`, `:164`). The missing piece is narrower than
"introduce containers" — it is "the one image we build ourselves."

### 1.4 Requirement 4 — Reproducible scripted deployment and documented rollback

| Sub-requirement | State | Evidence |
|---|---|---|
| Deployment is scripted | **Partially.** `scripts/boot.sh` (299 lines) is a thorough boot script — but it is **boot**, not deploy. | `boot.sh:1-3` |
| Deployment is reproducible | **No.** The deployed code is whatever `main` HEAD was at boot time. | `boot.sh:196` `git clone --depth 1 "$APP_URL"` — no ref, no SHA |
| Rollback is documented | **Yes, and it is excellent — and it is written about a mechanism M4 should replace.** | `docs/verification-milestone-3.md` §11.2 |
| Rollback is scripted | **No** | — |

**The specific defect, stated plainly:** `boot.sh:196` clones the *default branch*. There is no ref, no
SHA, no tag anywhere in the deploy path. So **the code running in production is not a version — it is
whatever the branch tip happened to be when the host last booted.** Nobody can state which commit is
running. Nobody can prove it was tested. A commit merged after the last boot is deployed *only* if
something triggers a reboot, and a commit merged before is deployed *without any test having run against
it*. The test suite and the deployed artifact have no causal relationship whatsoever.

### 1.5 Requirement 5 — Bash and PowerShell operational diagnostics

| Sub-requirement | State | Evidence |
|---|---|---|
| Any diagnostic script | **None.** `scripts/` holds `boot.sh`, `fetch-models.sh`, `load_corpus.py`. | `ls scripts/` |
| Service status collection | Available ad hoc | `boot.sh:292` `docker compose ps` |
| HTTP health results | Available ad hoc | `boot.sh:282` `curl -fsS .../health` |
| Timestamped report | **None** | — |

**Where it is closer to done than it looks:** the *commands* already exist inside `boot.sh:279-295`
(the `/health` poll) and `boot.sh:268` (`docker compose ps`), and `boot.sh` logs to
`/var/log/lemondrop-boot.log` with UTC ISO-8601 timestamps (`boot.sh:40`). Requirement 5 is largely
**extraction of existing commands into a standalone, operator-invocable script.** That is a few hours, not
a project.

---

## 2. Registry decision

### 2.1 The facts that decide it

| Fact | Evidence |
|---|---|
| **The repository is PUBLIC** | `gh repo view --json isPrivate` → `{"isPrivate":false,"visibility":"PUBLIC"}` |
| **The project already depends on GHCR** | `docker-compose.yml:90`, `:164` → `ghcr.io/ggml-org/llama.cpp:server` |
| **The EC2 host already has proven public-internet egress** | `infra/README.md:135` — "a deployed instance booted successfully, pulled a 263MB container image, and downloaded 340MB of model weights over this route" |
| **There is no ECR and no `ecr:*` IAM action** | `infra/*.tf`, `infra/iam.tf` |
| **The instance role is deliberately narrow** | `infra/iam.tf` grants `ssm:*` (lines 127-149), `ssm:GetParameter(s)` (299-300), `secretsmanager:GetSecretValue` (537) — and nothing else |
| **OIDC is optional** | operator framing |
| **CI must not hold long-lived AWS keys** | that would be a security regression against M3's least-privilege posture |

### 2.2 Recommendation: **GHCR**

Not a menu — a decision. Publish to `ghcr.io/<owner>/lemondrop-api`.

**Why, concretely:**

1. **Zero AWS credentials in CI, which retires the OIDC question entirely.**
   This is the strongest structural argument. Publishing to ECR requires AWS credentials in GitHub
   Secrets. With OIDC deferred, the only options are long-lived access keys — a direct regression against
   `infra/iam.tf`'s deliberate least-privilege posture — or the deferred OIDC work. GHCR authenticates
   with the **built-in `GITHUB_TOKEN`**, which is minted per-run, scoped to this repository, and expires.
   **The right way to handle an optional security feature is to choose the architecture that does not need
   it.** OIDC stops being "deferred"; it becomes "unnecessary." That is the cheapest possible resolution of
   a decision the operator explicitly asked not to dominate the milestone.

2. **It is not a new dependency.** The host already pulls from `ghcr.io` twice, today, to run the
   application. `docker-compose.yml:90`. An engineer reading this repo already has to trust GHCR. Choosing
   ECR adds a *second* registry to a two-service stack.

3. **A public package means the host pulls with no stored credential at all.**
   The repository is public, so the package can be public. `docker pull ghcr.io/<owner>/lemondrop-api:<sha>`
   on EC2 needs **nothing** — no `docker login`, no `~/.docker/config.json`, no new IAM policy, no
   `terraform apply` to grant `ecr:GetAuthorizationToken`. Given the instruction not to touch AWS in M4,
   this is decisive: **GHCR requires zero AWS changes; ECR requires at minimum an IAM policy change and an
   apply.**

4. **Egress is proven.** `infra/README.md:135` documents that the host pulled a 263 MB image over the
   IGW route even with NAT disabled. Pulling a ~200 MB image from GHCR is the same class of operation that
   has already worked. This resolves the NAT-cost debate: **registry choice does not change the NAT
   decision either way**, so it is not a tiebreaker and should not be argued as one.

### 2.3 The strongest argument **against** GHCR — stated at full strength

**GHCR provides no tag immutability guarantee, and this milestone's entire rollback story depends on tags
being stable.** A tag like `lemondrop-api:<sha>` is, on GHCR, a **naming convention** — any actor with
`packages: write` on the repository can re-push that tag and silently replace the image behind it. ECR
supports `image_tag_mutability = IMMUTABLE`, which makes tag overwrite a **registry-enforced** error.

This matters more than it first appears, because M4's rollback design (§4) rests on the proposition that
"the previous tag still points at the previous bits." On GHCR that proposition is *believed*, not
*enforced*. Worse, for a **public** package, deletion and un-publish are also possible by anyone with
admin rights — so rollback could fail not because the tag moved but because the image is gone.

**Mitigation, which is why this is not disqualifying:** the deployed revision must be recorded by
**digest**, not by tag (§4.3). Rollback then names a digest that was captured at deploy time. A moved tag
cannot corrupt an already-recorded digest. The gap that remains — a *historical* digest that has since been
overwritten — is addressed by GitHub's own retention rather than by anything we build.

If the operator disagrees with public-package visibility, the answer flips: a **private** GHCR package
would require a `GITHUB_PAT` on EC2, which is a stored registry credential on the host — precisely the
problem ECR solves with the instance role. In that scenario ECR's advantage is real and OIDC stops being
optional. **Recommendation holds, conditioned on a public package.**

### 2.4 Is ECR wrong *now*?

**Yes, plainly.** ECR is the right answer for a project that already has OIDC, or that must not depend on
anything outside AWS, or whose images must not be public. None of those is true here: this is a single
public repository with an existing GHCR dependency and an explicit instruction to leave AWS alone.

**What would change the answer:**
- The repository is made private → GHCR needs a host credential → ECR's instance-role pull wins.
- The images must not be publicly readable → same trigger.
- OIDC is implemented anyway for other reasons → the AWS-credential objection to ECR evaporates.
- A second service or a teammate needs to pull without a `GITHUB_TOKEN` in a private-network context.

**Migration path, deliberately kept open:** a GHCR-published image is just an OCI artifact. Moving to ECR
later means changing the publish login step and the pull reference. Nothing in the deploy design (§4) binds
to a registry — it binds to a **digest**. That is the point of designing around digests.

---

## 3. CI job design

### 3.0 Workflow structure

| Workflow | Trigger | Purpose |
|---|---|---|
| `.github/workflows/hygiene.yml` | `push` to `main`, `pull_request` | Fast, AWS-free gates. The merge gate. |
| `.github/workflows/tests.yml` | `push` to `main`, `pull_request`, `workflow_dispatch` | Test tiers. |
| `.github/workflows/images.yml` | `push` to `main` **only after tests pass**, `workflow_dispatch` | Build + publish. Never on a PR — a PR must not publish. |

Three files, not one. `hygiene` is the gate that must be fast enough to never be bypassed (§7.4); splitting
it means a 30-second job is not queued behind a 12-minute test run.

**The single most important design constraint: in M4, no job may touch AWS.** Not because it is
impossible, but because it is the specific thing that turns a CI system into a deployment tool, and a
deployment tool is a much harder thing to reason about than a test runner. Concretely:

- **No AWS credentials in any repository secret.** If a credential exists in the repository, CI is wrong.
- No job runs `terraform plan`, `apply`, or `aws` against the account. `terraform validate` (see §3.4) does
  not need credentials and therefore does not need any.
- Publishing is the *only* privileged write, and its privilege is `GITHUB_TOKEN`'s `packages: write`,
  scoped to this repository. Blast radius: one repo's container namespace.
- Deployment is **never** a workflow. It is a script a human runs (§4). The person deciding to deploy is
  never a CI runner acting on a trigger nobody reviewed.

### 3.1 The test job — and the split the requirement is missing

This is where I most disagree with the requirement as written. "GitHub Actions for application tests"
implies one job. The suite is **three tiers** with different prerequisites, and only one of them belongs in
PR CI.

| Tier | Files | Needs | Runs in PR CI? |
|---|---|---|---|
| **T1 — unit** | `test_db_credentials.py` (44 tests) | Python + `requirements-dev.txt`. **Nothing else.** The boto3 client is stubbed at the boundary (`test_db_credentials.py:280`). No DB, no HTTP, no network. | **Yes, always** |
| **T2 — database** | the DB-config portions of `test_db.py`, `test_documents.py`, `test_search.py` | Real PostgreSQL + **pgvector** (`docker-compose.yml:564` `pgvector/pgvector:pg16`) | **Yes** — service container |
| **T3 — live stack** | `test_integration.py` (6), the HTTP portions of `test_db.py`, `test_documents.py`, `test_search.py` | T2 **plus** the API **plus** two llama.cpp workers **plus** ~325 MB of GGUF weights **plus** a loaded corpus via `scripts/load_corpus.py` (`test_search.py:16-18`) | **No** — see below |

**Why T3 must not be in PR CI.** The weights are gitignored (`.gitignore:3` `*.gguf`, `:9` `models/*`) and
fetched from HuggingFace by `scripts/fetch-models.sh`. `boot.sh:229-241` describes ~340 MB as *"the slow
step, every fresh instance."* Running T3 in CI means every PR either downloads 325 MB of weights or pays
for it in wall-clock. Worse — and this is the decisive point — `boot.sh:248-250` records that a `t3.micro`
is ~913 MiB with no swap and the two GGUFs are ~410 MB resident once loaded. **Running the full inference
stack in a GitHub runner is a memory-shaped problem with no comfortable margin**, and a flaky T3 that times
out on runner capacity trains engineers to ignore red. The repo's own philosophy (`test_db.py:23-26`:
*"a skipped test has stopped testing while still reporting green, and green-that-means-nothing is worse
than red, because red gets read"*) is the right standard — and it applies with equal force to *jobs*.

**The honest answer to "will the suite pass in CI?"** No, not as one invocation, and this is not a defect in
the tests. Selection is done by **node id**, not by `pytest.skip()`:

- T1: `pytest api/tests/test_db_credentials.py`
- T2: selected `::` node ids for DB-config tests
- T3: **not** in CI

**This must be surfaced as a named decision in the repo, not buried in a workflow file.** If T3 is not run in
CI, it must run *somewhere* on a schedule or a manual trigger, or it silently becomes the untested tier —
which is precisely how `verification-milestone-3.md` §6 row 4 became `UNTESTED` for an entire milestone.
Recommendation: T3 as a `workflow_dispatch`-only job in `tests.yml`, documented as "run before a release
deploy," never on PR.

**Invocation and the `sys.path` arrangement.** `api/tests/conftest.py:24-27` inserts `api/` onto
`sys.path` so `from app import db` resolves. There is no `pyproject.toml`, no `pytest.ini`, no
`setup.cfg` — verified absent. Consequences:

- pytest **must** be invoked with `api/tests` reachable, and `conftest.py` handles the rest. Running
  `pytest api/tests/...` from the repository root works and is the invocation the test docstrings already
  prescribe (`test_integration.py:14`, `test_search.py:18`).
- **Install `requirements-dev.txt`, not `requirements.txt`.** `requirements-dev.txt:27` is
  `-r requirements.txt` plus `alembic`, `pytest`, `requests`. Installing only the runtime file gives a
  runner with no pytest — a confusing failure.
- **Do not add a `pyproject.toml` in M4.** It would be a real improvement (`conftest.py:5-10` argues its own
  approach at length) but it changes the import mechanism for 196 tests and is not needed for CI. Out of
  scope; noted in §8 so it is a conscious omission.

**`DATABASE_URL` must be set explicitly for T2.** `test_db.py:137` names `docker compose --profile devdb
up -d --build postgres` as the fix when the DSN is wrong. In CI the equivalent is a service container plus
an explicit `DATABASE_URL` environment variable. **Do not rely on `.env`**: `.gitignore:28` ignores it, and
`docker-compose.yml:431` interpolates `${DEV_DATABASE_URL:-}` — empty by design locally
(`test_db.py:455-456` explains that an empty `.env` is why the API serves degraded). CI sets the variable
directly. This is also why the CI job is safe: no `.env` exists on a runner, so nothing can be inherited by
accident.

**Service container.** `pgvector/pgvector:pg16`, matching `docker-compose.yml:564` and PostgreSQL major
version, per `docker-compose.yml:572` (*"Matching the major version locally is deliberate"*). Matching the
image **and** the major version is the requirement; a plain `postgres:16` service would fail at
`CREATE EXTENSION vector`.

**Health-wait before pytest.** `docker-compose.yml:624` uses `pg_isready` as the service healthcheck. The
CI job needs an equivalent — otherwise T2 races the database's first-boot initdb and fails in a way that
looks like a test bug.

### 3.2 Test job — what it does NOT do

- Does not build or push any image (that is `images.yml`, §3.5).
- Does not fetch model weights (`fetch-models.sh` is a **boot-time** concern — `boot.sh:229-241`).
- Does not run `docker compose up` for the application stack.
- Does not touch AWS or RDS.
- Does not mutate `.env`.

### 3.3 Dependency checks — and the hashing decision

**Recommendation: in M4, do a *failure-notice* check. Do NOT introduce hashes.**

The instinct is to add `pip-compile --generate-hashes` and pin an integrity-verified lock. I am
recommending against it in M4, for a reason specific to this repo:

- Hashing converts `requirements.txt` into a generated artifact with a regeneration workflow. Every
  routine dependency bump becomes a two-file, tool-mediated change.
- The repo's stated rule is **"exact pins, no ranges, ever"** (`requirements-dev.txt:24-25`), enforced by
  hand and explained at length. The *stated* threat model is version drift, and it is already fully
  addressed by `==`.
- Hashing addresses a **different** threat — upstream republishing at the same version. That is real, but it
  is a supply-chain-hardening project, not a CI plumbing project. It does not belong in a milestone whose
  acceptance criterion is about deployment.

**What M4 does instead:** CI installs `requirements-dev.txt` **exactly as committed**, so a dependency that
has become unresolvable is caught on every push rather than on someone's laptop. And the repo gains one
line of documentation stating plainly that pinning is not integrity verification and that hashing is
deferred with its reason. **Naming a deferred decision prevents someone later assuming it was overlooked.**

**Two further dependencies M4 must not silently accept:**

- `requirements-dev.txt` pulls `-r requirements.txt`, so CI installs FastAPI, uvicorn and httpx that the
  test process does not need. `requirements-dev.txt:17-22` argues this trade-off is accepted deliberately
  and correctly (a runtime dep missing from the image fails loudly at build time). **Do not "optimise" this
  away in M4.**
- The repo also contains `test_lemondrop_app_bootstrap.py` at the root (43 KB) and
  `lemondrop_app_bootstrap.py` (58 KB). I did not determine whether these are in scope for the CI test job —
  **open question, §9.** Including them is a scope decision, not a mechanical one.

### 3.4 Terraform validation — and the `init` safety problem

**Two stacks, both mandatory:**

| Stack | Backend | CI treatment |
|---|---|---|
| `infra/` | `backend "s3"` → live state bucket (`infra/versions.tf:41`) | `init -backend=false` |
| `infra/bootstrap/` | **none, by design** (`infra/bootstrap/terraform.tf` — chicken-and-egg) | plain `init` is safe |

**The hazard, stated plainly:** `terraform init` in `infra/` **will attempt to reach the real S3 state
bucket.** `infra/versions.tf:29-33` states the values are the live outputs of the applied bootstrap stack
and *"a typo here is only detectable by running `terraform init`."* In credential-less CI that command
fails — or, worse, in any environment where long-lived credentials happen to exist in the runner's ambient
environment, it **succeeds against production state**. `validate` does not read state, so it does not need
the backend.

**Correct invocation:**

```
terraform -chdir=infra        init -backend=false -input=false
terraform -chdir=infra        fmt -check -recursive
terraform -chdir=infra        validate

terraform -chdir=infra/bootstrap init -input=false
terraform -chdir=infra/bootstrap fmt -check -recursive
terraform -chdir=infra/bootstrap validate
```

`-backend=false` is the load-bearing flag. `-input=false` prevents a prompt from hanging a job until it
times out — the standard cause of a mysterious 6-minute red X. `fmt -check -recursive` covers both stacks
in one sweep if run from the repository root.

**Should CI also assert `.terraform.lock.hcl` is not modified?** Yes, cheaply, and deliberately:

`git diff --exit-code infra/.terraform.lock.hcl infra/bootstrap/.terraform.lock.hcl`

`.gitignore:60-66` is unusually explicit that the lock file is **deliberately not ignored**, because
"ignoring it would let plan/apply behaviour change underneath the operator with no diff anywhere to show
for it." CI should **enforce that decision**, not rebuild it. A drifting lock file is exactly the failure
that rule exists to prevent, and it is invisible without this check. Note the asymmetry: CI must not
*regenerate* the lock file, only *report* on it.

**`terraform plan` is deliberately excluded.** A `plan` needs the backend and real credentials — it would
make AWS unavoidable, which §3.0 forbids. It is also the least valuable check here: a plan against
production state from a PR is a change to AWS-shaped data on every push.

### 3.5 Image build and publication

**What is actually built: exactly one image — `api/Dockerfile`. Nothing else.**

- `docker-compose.yml:311-314` — `api` has `build: ./api`, `image: lemondrop-api`. This is the only
  `build:` in the file.
- `docker-compose.yml:90`, `:164` — the two workers use the **prebuilt** `ghcr.io/ggml-org/llama.cpp:server`.
  Nothing to build.
- `docker-compose.yml:564` — `pgvector/pgvector:pg16`, explicitly *"No `build:` — pgvector/pgvector is a
  published third-party artifact."*
- `scripts/fetch-models.sh` — **not an image.** It downloads weights into `models/`, which `.gitignore:9`
  excludes. **Weight fetching must never enter CI** (325 MB, and `boot.sh:229` calls it *"the slow step,
  every fresh instance"*). It stays where it is: on the host, at boot.

So requirement 3's plural — *"versioned images"* — is misleading. There is one image. **Say so in the
README**, because a second engineer will otherwise assume a multi-image pipeline exists.

**Tag strategy — commit SHA, plus `main` as a moving pointer. Not semver.**

| Tag | Pushed? | Purpose |
|---|---|---|
| `ghcr.io/<owner>/lemondrop-api:<full-40-char-sha>` | **always** | The immutable deployable reference. §2.3 explains why *digest* is what actually gets recorded. |
| `ghcr.io/<owner>/lemondrop-api:main` | on merge to `main` | Human convenience. **Never deployable** — see below. |

**Why SHA and not semver:** semver requires someone to decide the version. That decision needs release
discipline this project does not have (M3 shipped as a sequence of merges; `git log --oneline` shows merge
commits, not version tags). More importantly, semver is a **human judgment about content**, while SHA is a
**fact about what was tested**. The acceptance criterion is *"deploy a tested revision"* — the tag must name
the thing CI tested, and only a SHA does that by construction.

**Why a moving `main` tag is published but never deployed:** it is genuinely useful for a second engineer
to pull and inspect what is current. But a `main` tag cannot be rolled back to (it has moved) and cannot be
proven tested. The deploy script should **refuse** a non-SHA tag. That refusal is worth writing explicitly,
because it is the guard that keeps "deploy whatever is current" — today's actual behaviour — from quietly
surviving the migration.

**Why not build on PR:** publishing from a fork or an untrusted PR is how registries get burned. Build
verification can happen on PR (build, do not push); **push only on `main`.**

**Why not `workflow_dispatch` publish of arbitrary refs:** it is how an unreviewed commit reaches a
deployable tag. Keep the input constrained to a SHA that passed `tests.yml`.

### 3.6 The state-leak gate — cheapest job, highest protection

**This is the first task. See §6.**

A single job that asserts no Terraform state, no `.env`, and no model weights are tracked in git:

```
git ls-files --error-unmatch <path>   → must fail for every match
```

scanning for `*.tfstate`, `*.tfstate.*`, `crash.log`, `crash.*.log`, `.env`, `*.gguf`, `models/*`.

**Why this is the highest-leverage job in the milestone.** It is the only M4 job whose failure would
indicate a **security incident rather than a bug**. `infra/.terraform/terraform.tfstate` and
`infra/bootstrap/terraform.tfstate` both exist on this machine right now — correctly ignored, and they are
exactly the files that must never be committed. `.gitignore:42-49` gives three reasons to ignore state,
one of which is that *"`infra/` will reference the RDS endpoint and the secret ARN."* A committed
`infra/` state file leaks the DB endpoint into permanent git history. `.env` leaks credentials
(`.gitignore:27`). `*.gguf` adds 130 MB per file to history permanently (`.gitignore:1-2`).

**It enforces M3's security work rather than duplicating it.** `.gitignore` already blocks all of these —
CI's job is to catch the case where someone uses `git add -f`. **Enforce the decision; do not rebuild it.**
Cost: seconds. Runs on every push and every PR. No dependencies, no AWS, no services.

---

## 4. Deployment strategy

> *"A second engineer must be able to deploy a tested revision without manually reconstructing the
> original environment."*

### 4.1 The defect, stated plainly

Today, deployment is: SSH-equivalent over SSM → clone `main` at HEAD → `docker compose up -d --build` →
the API image is **built on the host from whatever the branch tip was at that instant**.

Four consequences, in increasing severity:

1. **Nobody can name the running version.** `boot.sh:198` logs `git rev-parse --short HEAD` — of a
   `--depth 1` clone whose provenance is the branch tip at clone time. If someone later pushes to `main`,
   the log line becomes a lie about what is running.
2. **The test suite has no causal relationship to production.** Tests run against a locally built image;
   production runs an image built independently, on weaker hardware, from an unpinned ref. A test pass is
   evidence about a *different artifact*.
3. **The environment cannot be reconstructed** without the exact sequence of manual steps that produced
   it — which is the acceptance criterion's actual complaint.
4. **Rollback is a landmine.** `verification-milestone-3.md` §11.2: `boot.sh:196` uses `--depth 1`, so the
   clone holds no history, and *"`git fetch --unshallow` is MANDATORY before deploying. Without it there is
   **no rollback path at all** — not a slow one, none."*

**The image-based path below deletes consequence 4 entirely.** Rolling back becomes "start the previous
image," which requires no git history, no unshallow, and no network fetch of source.

### 4.2 The proposed path

```
  push to main
      │
      ├── tests.yml ──── 44 unit + DB-tier tests green?
      │                          │ yes
      ├── images.yml ──── build api/Dockerfile
      │                     push ghcr.io/<owner>/lemondrop-api:<sha>
      │                     + :main  (pointer only, never deployed)
      │
      └── DEPLOYMENT IS NOT AUTOMATED. A human runs scripts/deploy.sh <sha>.
              │
              ├── SSM send-command to the instance
              │     ├── verify <sha> exists in the registry (fail fast, before touching the host)
              │     ├── docker pull ghcr.io/<owner>/lemondrop-api:<sha>
              │     ├── record current revision  ← §4.3, BEFORE any change
              │     ├── docker compose up -d --no-build --force-recreate api
              │     ├── wait for /health  (generous; see below)
              │     └── on failure → automatic rollback to recorded revision
              └── write the new revision record  ← §4.3, AFTER success
```

**Is this the right minimum? Yes — and it is deliberately small.** The alternative designs and why they are
rejected are in §7. The cost of this design is one compose change plus one script, and it converts
deployment from *rebuild-on-host* to *pull-known-artifact*.

**Two details that make or break it:**

- **`--no-build` is mandatory.** `docker-compose.yml:311` has `build: ./api`. Without `--no-build`, compose
  rebuilds locally and **the whole strategy silently reverts to today's defect** — deploying a locally
  built image while the log claims a SHA. This flag is the difference between the M4 design and the status
  quo.
- **`image:` must become parameterised** — currently it is the hardcoded literal `lemondrop-api`
  (`docker-compose.yml:314`). Deploying by tag requires something like `${API_IMAGE:-lemondrop-api}`, with
  the tag supplied per-deploy. **This is the one small compose change M4 requires.** It is listed in §5,
  Stage 4, because Stage 4 cannot be verified without it.

**Why the health wait must be generous.** `boot.sh:270-278` waits up to **300 s** and *exits 0 on timeout*,
because *"model loading can exceed it."* That reasoning applies unchanged: only the `api` container is
recreated, but the workers' models stay warm, and `boot.sh:248-250` records the t3.micro memory margin.
Reusing boot's number rather than inventing a smaller one is the conservative choice.

**Recreating only `api` is a deliberate scope limit.** The workers keep running; model weights are untouched;
`scripts/fetch-models.sh` is not re-run. That keeps a code deploy fast and keeps the 325 MB download out of
the deploy path entirely.

### 4.3 Recording the running revision — non-negotiable

**If the deployed revision is not recorded, requirement 4 has not been met.** The acceptance criterion says
a second engineer must be able to act *without reconstructing*; the record is what makes "what is running?"
answerable in one command.

**Record both tag and digest.** Per §2.3, the digest is the trustworthy half.

Written to `/opt/lemondrop/DEPLOYED_REVISION` on the host (plain text, one line, `boot.sh`'s existing
`$APP_DIR`), containing:

- the full 40-char commit SHA requested,
- the **image digest** as reported by `docker inspect` (`RepoDigests`) — never a reconstructed tag,
- UTC ISO-8601 deploy timestamp,
- the acting principal (the SSM command invoker identity).

**Why on the host and not only in CI:** the host is where the running container is. A CI-side record can
drift from reality; a file written by the deploy itself cannot. `boot.sh:40` already establishes UTC
ISO-8601 timestamps as this repo's logging convention — the record should match it.

**Also record it as an image label at build time** (`org.opencontainers.image.revision`) so the running
container answers the question about itself via `docker inspect`, with no dependency on a neighbouring file.

### 4.4 Rollback — scripted, and building on M3's precedent

**M3's precedent, used rather than replaced.** §11.2 established the correct principles even though it
described a git-based mechanism M4 supersedes:

- *"build the new image under a unique tag"* → the SHA tag (§3.5).
- *"verify it → only then switch to it"* → deploy order in §4.2.
- *"The previous image must still exist under its own named tag so there is something to return to."*
- ***"A tag overwritten in place is not a rollback point — it is the same failure mode as having no rollback
  at all, only harder to notice."*** → **this is the reason for SHA-only tags**, and it should be quoted in
  the deploy script's own comments so the constraint survives.

**What M4 changes: the rollback mechanism.** M3's rollback was `git fetch --unshallow` + checkout + rebuild
on the host. M4's is `docker compose up -d --no-build` with the **previous tag or digest**. Faster, and it
cannot fail for the reason §11.2 warns about.

**Procedure:**

1. **Name the previous revision.** Read from the record file (§4.3) *before* any change is made. If the file
   is missing or unreadable, **abort** — a deploy that cannot record cannot roll back.
2. **Keep the previous image.** `docker compose up` must not prune it. The deploy script must not run
   `docker image prune`. Retention is the rollback guarantee.
3. **Rollback command sequence** (exact, for the runbook):

   ```
   # over SSM, as ssm-user, with sudo for docker:
   PREV=$(cut -d' ' -f2 /opt/lemondrop/DEPLOYED_REVISION)   # previous tag/digest
   test -n "$PREV" || exit 1                               # no record, no rollback — stop
   docker image inspect "$PREV" >/dev/null || exit 1        # confirm it still exists locally
   docker compose up -d --no-build --force-recreate api \
       with API_IMAGE="$PREV" exported in the deploy env
   # then verify /health, then rewrite DEPLOYED_REVISION to PREV
   ```

4. **Decision criteria for the operator** — state them in advance, because deciding mid-incident is how
   bad calls get made:

   | Signal | Action |
   |---|---|
   | `/health` fails within the wait window | **Automatic** rollback. No judgement call. |
   | `/health` ok but `/search` errors or returns wrong results | Roll back, then investigate. |
   | Latency regression on `/search` | Investigate **before** rolling back; do not roll back a correct deployment for a performance question. |
   | Database migration was applied | **Do not roll back the API alone** unless the migration is backward-compatible. See below. |

5. **The migration caveat is the one real hazard.** `verification-milestone-3.md` §11.3 states the
   `lemondrop_app` role has **no DDL** and the **master credential is for migrations only**. A deploy whose
   revision includes a new Alembic migration is **not** rollback-safe by image alone — rolling the API back
   against a newer schema may fail. **So: `scripts/deploy.sh` must print a warning if the target SHA
   contains changes under `api/alembic/`, and the runbook must state that such a deploy requires a
   deliberate schema decision.** This is the single most likely way M4's rollback promise turns out to be a
   lie, and it must be written down *before* the first migration-bearing deploy, not discovered during it.

### 4.5 What must NOT be automated yet

- **The deploy trigger.** No auto-deploy on merge. The operator decides. Automation here converts "we
  deployed" into "it deployed," and the first bad deploy becomes invisible.
- **Terraform apply.** Never in CI, never in a deploy script. `infra/` changes remain an operator action
  via `RUNBOOK.md` §2.
- **Model fetching.** Stays on the host (`boot.sh:229-241`). Never in CI, never in the deploy path.
- **Database migrations.** Not automated. Per §4.4 item 5.
- **Reboot / `user_data` re-run.** `infra/compute.tf:185` sets `user_data_replace_on_change = true`;
  §11.1 notes the trigger is armed for any Terraform change. A re-run re-clones and rebuilds. **Out of
  scope, and a hazard**: the record must survive it. Flagged for the runbook.

---

## 5. Staged acceptance checklist

Ordered **minimum-value-first**. Every stage leaves the repo in a good state if the operator stops, and every
stage is independently verifiable. No stage requires AWS access.

### Stage 1 — State-leak gate (`.github/workflows/hygiene.yml`, one job)

- **Built:** one job, `state-leak`, asserting no tracked `*.tfstate`, `*.tfstate.*`, `crash*.log`, `.env`,
  `*.gguf`, or `models/*`.
- **Verified:** push to a scratch branch; job runs and passes. Deliberately verify it **can fail**: add a
  dummy `.env` with `git add -f`, confirm red, then remove it.
- **Evidence:** the Actions run URL, plus the deliberate-red run.
- **Done when:** the gate is on `main` and has been observed failing on a forced add.
- **Value:** protects M3's security work permanently. Cost: seconds.

### Stage 2 — Terraform validation (second job in `hygiene.yml`)

- **Built:** `fmt -check -recursive` and `validate` across **both** stacks, `init -backend=false` for
  `infra/`, plain `init` for `infra/bootstrap/`, plus the `.terraform.lock.hcl` no-drift check (§3.4).
- **Verified:** job runs; **if `fmt -check` fails on first run, that is expected and not a failure of this
  stage** — run `terraform fmt`, review the diff, commit it separately as `style(infra): terraform fmt`, and
  land that **before** enabling the check. Never disable the check to get green.
- **Evidence:** Actions run URL; if a fmt commit was needed, the commit SHA and the reviewed diff.
- **Done when:** both stacks validate, `fmt -check` is green, and the lock file shows no drift.
- **Value:** requirement 2 complete.

### Stage 3 — Test CI (`.github/workflows/tests.yml`, T1 then T2)

- **Built, in this order:** T1 first (`test_db_credentials.py`, no services — proves the runner and the
  invocation). Then T2 with a `pgvector/pgvector:pg16` service container, `pg_isready` health-wait, and an
  explicit `DATABASE_URL`.
- **Verified:** T1 green with **no** service container — the check that the tier split is real and not
  accidental. Then T2 green. Confirm `DATABASE_URL` is set explicitly and no `.env` is present on the runner.
- **Evidence:** Actions run showing the test counts per tier; the deliberate check that T1 passes with
  services absent.
- **Done when:** T1 and T2 run on every PR in under ~5 minutes, and **the repo documents which tests are in
  CI and which are not, and why** (§3.1). That documentation is a deliverable, not a footnote — an
  undocumented test gap becomes an invisible one.
- **Value:** requirement 1 complete, for the tiers CI can honestly run.

### Stage 4 — Image build and publish (`.github/workflows/images.yml`)

- **Built:** `docker/build-push-action` on `main` only, publishing `:main` and `:<sha>` to GHCR via
  `GITHUB_TOKEN`. **Plus the small compose change**: parameterise `image:` at `docker-compose.yml:314`.
- **Verified:** the workflow log shows the digest. Then, **from a non-CI machine**, `docker pull
  ghcr.io/<owner>/lemondrop-api:<sha>` succeeds **without `docker login`** — this is the decisive test of
  the whole registry decision, and it must be observed, not assumed.
- **Evidence:** the published digest, recorded in the milestone doc; the successful unauthenticated pull.
- **Done when:** a second engineer can pull the image with no credentials and no AWS access.
- **Value:** requirement 3 complete.

### Stage 5 — Deploy and rollback (`scripts/deploy.sh` + runbook section)

- **Built:** the SSM-initiated deploy from §4.2, with record-before / record-after, `--no-build`, the
  non-SHA-tag refusal, the migration warning, and the rollback procedure from §4.4.
- **Verified — this is the acceptance criterion, and it must be tested by someone other than the author.**
  A second engineer, given only the runbook and repo access, deploys a SHA-tagged revision **without
  asking a question**, then rolls back, then confirms `/health` and a `/search` that returns correct results.
  **If the author runs this test themselves, the criterion is not met** — it is the definition of "without
  manually reconstructing."
- **Evidence:** the second engineer's session transcript; the before/after `DEPLOYED_REVISION`; the
  rollback result.
- **Done when:** the acceptance sentence is true, witnessed by someone else.
- **Value:** requirement 4 complete — and the only stage that closes the milestone.

### Stage 6 — Operational diagnostics (`scripts/diagnose.sh` + `scripts/diagnose.ps1`)

- **Built:** both scripts collect service status, HTTP health results, and write a timestamped report.
  Content is largely **extracted from existing commands** — `boot.sh:279-295` (`/health` polling),
  `boot.sh:268` (`docker compose ps`), `boot.sh:40` (UTC ISO-8601 timestamp convention).
- **Verified:** both scripts run; each produces a report file; reports from the same state are comparable.
  The PowerShell script's real justification is an **operator on Windows** — state that in the script
  header, or it reads as unmotivated duplication.
- **Evidence:** two sample reports.
- **Done when:** both exist and are documented.
- **Value:** requirement 5 complete. **Lowest value on the acceptance path — deliberately last.**

### Ordering rationale

Stages 1-3 are AWS-free, credential-free, and independently useful: any of them alone justifies the
milestone. Stages 4-5 carry the acceptance criterion and are the only ones that touch a running system.
Stage 6 is operator convenience and is last because **stopping after Stage 5 leaves the milestone
essentially complete** — which is the correct place for an operator to stop.

---

## 6. First proposed task

**Create `.github/workflows/hygiene.yml` containing exactly one job: `state-leak`.**

**Precisely:**

- **Path:** `.github/workflows/hygiene.yml` (the only file created; the directory does not exist yet).
- **Trigger:** `on: push` (branches `main`) and `pull_request`. Nothing else. No `workflow_dispatch` — this
  job has no manual mode, because a manual mode is a way to skip it.
- **Permissions:** `contents: read` at workflow level. **No `packages: write`, no AWS, no secrets.** The
  most restrictive set that works.
- **Steps:** checkout (the only action needed), then a scan step asserting **no** tracked path matches
  `*.tfstate`, `*.tfstate.*`, `crash.log`, `crash.*.log`, `.env`, `*.gguf`, or anything under `models/`.
  Implement with `git ls-files` — the tracked-file list, not the filesystem — because the question is
  *"what is committed,"* not *"what is on this disk."* A filesystem scan would pass on a machine with a
  local `infra/terraform.tfstate`, which is normal and correct.
- **Explicitly NOT in this task:** terraform, pytest, Docker, any AWS action, any other workflow. One job.
  Adding a second job is Stage 2 and is a separate, separately verifiable step.

**Why this first, of all the candidates:**

1. **Deliverable in one sitting.** No service containers, no image builds, no AWS, no credentials.
2. **It cannot fail for reasons unrelated to M4's own work.** `terraform fmt` might fail on day one (§5
   Stage 2) and pytest needs tiering (§5 Stage 3) — both are *decisions* before they are jobs. This one is
   a finished thing whose behaviour is fully predictable.
3. **It is the only job whose failure means a security incident.** It directly protects M3's
   least-privilege work, and `infra/.terraform/terraform.tfstate` and `infra/bootstrap/terraform.tfstate`
   exist on this machine right now.
4. **It establishes the pattern** — a fast, dependency-free, AWS-free gate on every push — that Stage 2
   extends. Designing the first workflow's shape is the most consequential decision in the CI work, and
   this task makes it with the least at stake.

**Acceptance evidence (all four required):**

1. Push to a scratch branch; `state-leak` appears and passes on the Actions tab.
2. **Negative control:** create a throwaway `.env`, `git add -f .env`, push; the job **fails** and names the
   file. A gate never observed failing is not known to work.
3. Remove the file, push again; the job passes.
4. `git log` shows the workflow commit and **no other change** — confirming scope discipline.

---

## 7. Risks and rejected alternatives

### 7.1 ALB idle timeout — RECORDED, NOT FIXED

**This risk is carried forward untouched, and M4 must not touch it.**

- ALB `lb_idle_timeout` is **60 s** (`var.lb_idle_timeout` default `60`, `infra/variables.tf:890`;
  applied at `infra/load_balancer.tf:67`; validated range 1-4000 at `infra/variables.tf:907`).
- `/search` worst case is **~240 s**: `INFERENCE_TIMEOUT_SECONDS=120` is a **per-call** budget applied
  inside `_post_upstream`, and `/search` makes **two sequential** calls — embed, then rerank. So 120 + 120.
  `verification-milestone-3.md` §10.8; `main.py:106`, `:547`, `:1381`, `:1459`.
- **The ALB times out before the API does.**
- It has not bitten because a search currently completes in **~15.55 s** — a **single observation**, not a
  distribution, and explicitly **not a margin measurement** (§12.1 row 12, §12.4 item 4).

**Status: DELIBERATELY DEFERRED** (§10.8) — the operator approved a config change; it was not made,
pending the EC2 latency measurement in §10.7.

**M4 does not fix it, does not investigate it, and does not touch AWS.** One specific M4 interaction to
note: **M4's deploy health check will hit `/health`, not `/search`.** `/health` does not exercise the
two-call inference chain, so **the deploy gate will not catch this defect** — it is out of scope for a
deploy check, and the plan records it rather than quietly relying on the health check to cover it. Line
note: `verification-milestone-3.md` §10.8 cites `infra/variables.tf:665-671` for the default; in the current
file the variable is at `infra/variables.tf:890`. The cited line numbers have drifted — the **value (60)
is correct**, only the reference is stale.

### 7.2 OIDC deferred — and, under this plan, unnecessary

Deferred per the operator. Under the GHCR recommendation (§2), **no AWS credential is needed in CI at all**,
so the OIDC question does not arise. This is the outcome the instruction was reaching for: *avoid
unnecessary complexity* rather than *defer a complexity*. OIDC should be re-opened **only** if §2.4's
triggers occur.

Residual risk: if a future requirement introduces a second private service or a second engineer needing AWS
access from CI, OIDC returns and should then be implemented properly rather than papered over with
long-lived keys.

### 7.3 CI cost

Public repositories get **unlimited free** GitHub Actions minutes; `fvitorino00/lemondrop` is **public**
(verified). So T1/T2 and the hygiene gates cost **$0**. The only cost is the image build, which benefits from
the layering already in `api/Dockerfile:13-28` — dependencies install before source, so an app-code change
reuses the cached pip layer and only rebuilds the thin source layer.

**Honest caveat:** this reasoning depends on the repository staying public. If it is made private, minutes
become billable and the cost model in `COSTS.md` (which tracks AWS only) becomes incomplete.

### 7.4 CI too slow to be used, and therefore bypassed

**This is the risk most likely to make M4 worthless, and it is a design constraint, not a consequence.**

- The repo has refused `pytest.skip()` on principle (`test_db.py:23-26`) and T3 needs ~325 MB of weights plus
  two inference workers on hardware with a documented memory squeeze (`boot.sh:248-250`). Shipping T3 into
  PR CI would produce a job that is slow, memory-fragile, and occasionally red for reasons unrelated to
  the change under review.
- **An engineer who learns that CI is unreliable will deploy without it** — and would be *rational*: the
  current deploy path does not check CI anyway (§4.1), so bypassing it costs nothing today.

Mitigations, all of which are in the plan: T3 is excluded from PR CI and is `workflow_dispatch`-only (§3.1);
the `hygiene` workflow is a **separate file** so its seconds-long jobs never queue behind a test run (§3.0);
Stage 1 is seconds. **The ordering of the stages is itself the mitigation** — the fast gate lands first and
builds the habit before the slow job exists.

**Residual risk, stated honestly:** excluding T3 from CI means the suite that best protects production
correctness runs least often. This is a genuine loss, traded for a reliable gate. It is only defensible
because T3 is **documented as not-in-CI** (§5 Stage 3 deliverable) and remains runnable on demand — an
undocumented exclusion would be strictly worse than either extreme.

### 7.5 "Reproducible deployment" is requested on an unverified foundation

**The most important risk in this plan.**

`verification-milestone-3.md` §12.4 item 5 records that **clean destroy/rebuild reproducibility remains
untested** — carried forward from M2 and never verified. The acceptance criterion for M4 asks for
**reproducible deployment** on a stack whose reproducibility from scratch has never been demonstrated.

**The distinction matters and must not be blurred.** M4 delivers **repeatable *deployment*** — deploying a
known artifact to a *running* host. It does **not** deliver **reproducible *provisioning*** — building the
host from nothing. Those are different claims, and M4 satisfies only the first.

**The consequence:** a second engineer can deploy a tested revision to the **existing** instance, but if
that instance is gone, `RUNBOOK.md` §2a-2b and the `terraform apply` path are the only reconstruction — and
that path has never been walked end to end from zero. **The acceptance criterion is therefore weaker than
it reads.** I recommend restating it as:

> *"A second engineer can deploy a tested revision to the running environment without manually
> reconstructing the original deployment steps."*

That is achievable, verifiable in Stage 5, and honest. The stronger claim is not.

**Recommendation:** add a **Stage 7** — one full `terraform destroy` + re-apply + deploy + verify, on a
schedule or a scratch account — and only then claim reproducible provisioning. **Out of scope for M4**
(§8), named here so it is a decision rather than an oversight.

### 7.6 Rejected alternatives

| Alternative | Why rejected |
|---|---|
| **ECR** | Requires AWS credentials in CI. With OIDC deferred that means **long-lived access keys in GitHub Secrets — a security regression against `infra/iam.tf`'s deliberate least-privilege posture.** Also needs an IAM policy change plus an apply, which conflicts with "do not touch AWS." Its real advantage (instance-role pull, no stored host credential) is real but unnecessary for a public GHCR package. **Not wrong forever — wrong now** (§2.4). |
| **Deploy on merge to `main`, automatically** | Converts "we deployed" into "it deployed." The first bad deploy becomes invisible. The operator's decision to deploy is the control that makes the acceptance criterion meaningful. |
| **Deploy by git SHA (`git checkout <sha>` + rebuild on host)** | Keeps M3's `--depth 1` landmine (§11.2) and keeps building on the target host. It fixes *versioning* but not the central defect. Strictly worse than image-pull. |
| **Run T3 (full stack) in PR CI** | 325 MB weights + two inference workers per PR, on hardware with a documented memory margin (`boot.sh:248-250`). Produces a slow, flaky gate — and a flaky gate gets bypassed (§7.4). |
| **Auto-run `terraform plan` in CI** | Needs the real backend and real AWS credentials, making AWS unavoidable in CI (§3.0) for little value. A plan against production state on every PR is a change to AWS-shaped data. |
| **`pip-compile --generate-hashes` in M4** | Right hardening, wrong milestone. Converts `requirements.txt` into a generated artifact with a regeneration workflow, for a threat (upstream republish) the repo's `==` rule does not already address. **Deferred with its reason documented** (§3.3). |
| **Bake a Golden AMI with the app baked in** | Named as an alternative in `RUNBOOK.md:146`. Genuinely viable, but it makes the artifact untestable-per-commit and couples code release to AMI build. The image-pull approach gets the same reproducibility with per-commit granularity. |
| **Add `pyproject.toml` and install the app as a package** | An improvement `conftest.py:5-10` argues for at length, but it changes the import mechanism for 100 passing tests and is not needed for CI. Out of scope (§8). |
| **Fix the ALB timeout in M4** | Explicitly forbidden and explicitly not attempted. See §7.1. |

---

## 8. Out of scope for M4

Stated so it cannot creep in. Each item is deliberately deferred, with the reason.

1. **The ALB `lb_idle_timeout` defect** (§7.1). Record, do not fix, do not touch AWS.
2. **OIDC / short-lived AWS credentials in CI.** Unnecessary under the GHCR recommendation (§7.2).
3. **Any AWS mutation.** No ECR, no IAM change, no `terraform apply`, no RDS change, no `terraform plan`.
   **No M4 job holds an AWS credential.**
4. **Automated deployment.** No deploy-on-merge, no webhook trigger (§4.5).
5. **Model weights in CI.** `scripts/fetch-models.sh` stays on the host, at boot (§3.5).
6. **`pyproject.toml` / packaging the app** (§7.6).
7. **Dependency hash pinning** (§3.3).
8. **Clean destroy/rebuild verification** — named as Stage 7 in §7.5, explicitly **not** M4.
9. **T3 (live-stack) tests in PR CI** (§3.1, §7.4).
10. **Database migration automation**, and any deploy that applies a migration without a deliberate schema
    decision (§4.4 item 5, §4.5).
11. **Non-root container user.** `api/Dockerfile:59-62` defers this *"on purpose rather than forgotten"* and
    ties it to the first commit that adds a volume, secret, or user-supplied code. **M4 does not add any of
    those to the image** — the image is still `requirements.txt` + `app/` — so this stays deferred, and the
    plan must not claim otherwise.
12. **Load/concurrency testing, CPU-credit measurement, latency distribution.** Carried forward in
    `verification-milestone-3.md` §12.4 items 2, 3, 7. Untouched.
13. **A second registry, or multi-image publishing.** There is exactly one image to publish (§3.5).
14. **Rewriting `boot.sh`.** It stays as the boot path. M4 adds a *deploy* path alongside it. **The 16,384-byte
    `user_data` ceiling applies** (`boot.sh:5-6`, measured at 15,068) — a future change that touches
    `boot.sh` must be measured against that budget, which is a reason not to touch it in M4.

---

## 9. Open questions

Claims I could **not** verify from the repo. Each is a question, not an assumption.

1. **Does `terraform fmt -check -recursive` currently pass?** I did not run Terraform, per instruction. If
   it fails, Stage 2 requires a `terraform fmt` commit landing **before** the check is enabled (§5 Stage 2).
   **This is the most likely first surprise in the milestone.**
2. **`test_lemondrop_app_bootstrap.py` (43 KB, repo root) and `lemondrop_app_bootstrap.py` (58 KB) — in
   scope for the CI test job?** They sit outside `api/tests/` and outside the operator's count of 100. I did
   not determine whether they are maintained, generated, or vestigial. **A scope decision, not a mechanical
   one.** Excluding them silently would be the wrong default.
3. **The measured total is 196 tests**, which includes `test_integration.py` (6 tests,
   `test_integration.py:36-152`) as T3 and the repository-root `test_lemondrop_app_bootstrap.py`
   (40 tests) as T1. Confirm the intended total.
4. **Is the GHCR package to be public or private?** The §2.3 mitigation assumes public (§2.4 states the
   flip condition). Public follows from the repo being public, but package visibility is set independently
   and should be confirmed.
5. **Is `test_search.py`'s 26 vs. 18 test functions discrepancy** (mine: 18 functions; operator: 26 tests)
   purely `@pytest.mark.parametrize`? I did not run collection. Affects only the Stage 3 counts in evidence.
6. **Does the second engineer have AWS/SSM access?** The acceptance criterion presumes someone who can run
   SSM `send-command` (`RUNBOOK.md:98`). That is a human IAM grant outside the repo and **cannot be delivered
   by any M4 work.** If it is not in place, Stage 5 cannot be witnessed and the criterion cannot be met.
   **This is a genuine dependency on the operator and is the likeliest reason Stage 5 stalls.**
7. **`boot.sh:198` logs `rev-parse --short HEAD`** — whether that log line is currently relied on by
   anything (an alert, a runbook step) that would break when deploys stop cloning. Not determined.