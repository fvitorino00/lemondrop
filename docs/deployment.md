# LemonDrop — Deployment and Rollback Runbook

**Audience:** an engineer who has never seen this project and has no shared context with anyone who has.
**Scope:** deploying a published, tested API image to the running EC2 host; verifying it; rolling it back; recovering when something goes wrong.

Every claim in this document is either (a) read directly out of a file in this repository, with the file and line cited, (b) read out of `docs/verification-milestone-3.md`, or (c) explicitly marked as unverified. Section 10 lists the things that are **not** verified and must not be treated as verified. If this document and the repository ever disagree, the repository is right and this document is a bug.

**A note on citations, because a stale citation is worse than none.** Line numbers are given only for files that are effectively frozen — chiefly `infra/compute.tf` (§9.2 declares any edit to it replaces the instance), plus `infra/iam.tf`, `infra/variables.tf`, `infra/outputs.tf`, `api/app/main.py` and `RUNBOOK.md`. For `scripts/**` this document cites **a function name and, where it matters, the quoted words**, never a line number. The reason is empirical, not stylistic: those four scripts grew by roughly 300 lines between the draft of this document and the commit that landed them, and every line number in the first draft silently stopped resolving while still *looking* correct. A `grep -c` on a function name cannot rot that way. If you find a citation here that looks like a line number under `scripts/`, treat it as a bug in this document.

---

## 0. Read this first

### 0.1 What the deploy tooling is

Three bash scripts, plus one shared library, plus the two Stage 6 diagnostic scripts:

| File | Role |
|---|---|
| `scripts/deploy.sh` | Deploys a digest-pinned image. Recreates only the `api` service. |
| `scripts/rollback.sh` | Returns the host to the previously recorded deployment. Takes no arguments. |
| `scripts/verify-deployment.sh` | Read-only. Reports what is running and whether it matches the record. |
| `scripts/lib/deploy-lib.sh` | Sourced by all three. Image-reference validation, the record format, the HTTP probes, the lock. |
| `scripts/diagnose.sh` | **Read-only diagnostic (Linux/WSL).** Service status from Docker, HTTP health, timestamped report. |
| `scripts/diagnose.ps1` | **Read-only diagnostic (Windows).** HTTP health only — deliberately no Docker — timestamped report. |
| `scripts/test-diagnose.sh`, `scripts/test-diagnose.ps1`, `scripts/test-diagnose-parity.sh` | The diagnostics' own tests. No framework, no services, no network. |

The scripts run **on the EC2 host**, not in CI. That is deliberate: `scripts/deploy.sh`, in the block headed `── WHY THIS SCRIPT RUNS ON THE HOST AND NOT IN CI ──` — "because a deployment is a decision, and CI turning 'we deployed' into 'it deployed' makes the first bad deploy invisible." A human runs it, having looked at what is being deployed.

The two `diagnose` scripts are the exception to "runs on the host", and each runs where its operator is: `diagnose.sh` on the host (it needs `docker`), `diagnose.ps1` on a Windows workstation (it has no Docker there and reports the application's own view instead). Both are also executed by the `tier-classification` job in `tests.yml`, against stubs — §10 item 1 records exactly what that does and does not prove.

### 0.2 The paths that matter

Defaults from `scripts/lib/deploy-lib.sh`, the `readonly LEMDROP_*` defaults at the top of the file. Every one is overridable by an environment variable of the same name; the defaults are the production values.

| Thing | Path / value |
|---|---|
| Application checkout | `/opt/lemondrop` |
| State directory | `/var/lib/lemondrop` |
| Revision record | `/var/lib/lemondrop/deployed-revision.env` |
| **Diagnostic reports (Bash)** | `/var/lib/lemondrop/diagnostics/` — override with `--report-dir` |
| **Diagnostic reports (PowerShell)** | `%LOCALAPPDATA%\lemondrop\diagnostics\` — override with `-ReportDir` |
| Deployment lock | `/var/lock/lemondrop-deploy.lock` |
| Deploy log | `/var/log/lemondrop-deploy.log` |
| Boot log | `/var/log/lemondrop-boot.log` |
| cloud-init log | `/var/log/cloud-init-output.log` |
| Corpus (probe grounding) | `/opt/lemondrop/data/corpus.json` |
| Compose project name | `lemondrop` |
| Readiness timeout | 300 s |
| Search timeout | 300 s |
| Lock wait timeout | 300 s |

The record lives **outside** the checkout on purpose (in `deploy-lib.sh`, under `WHY THE RECORD LIVES OUTSIDE THE CHECKOUT`). Nothing in the deploy path writes inside `/opt/lemondrop`.

The diagnostic reports live outside the checkout **for the same reason**, and both scripts refuse a report directory inside it rather than quietly writing there. A report is run-specific output like the record — it is worthless in a pull request, it is deleted by the next `git clean -fdx`, and inside the tree it is exactly the untracked-file clutter the record's header describes.

### 0.3 Exit codes

From `deploy-lib.sh`, the `EX_*` constants. Distinct so a wrapper can tell the classes apart without parsing text.

| Code | Name | Meaning |
|---|---|---|
| 0 | `EX_OK` | Succeeded. |
| 2 | `EX_REFUSED` | A guard said no: bad reference, schema mismatch, missing record, wrong arguments. **Nothing was changed.** |
| 3 | `EX_FAILED` | Something was attempted and did not work. |
| 4 | `EX_LOCKED` | Another deployment holds the lock. |

`2` means "I declined"; `3` means "I tried". If you are scripting around this, that distinction is the whole reason the codes differ.

### 0.4 ✅ The deploy tooling IS committed — this section supersedes an earlier draft that said otherwise

**An earlier draft of this runbook said the tooling was untracked and that `main` did not contain it. That is no longer true, and the sentence is kept here only so the change is visible rather than silent.**

It was true at the time of that draft, and it was the correct thing to warn about: `scripts/deploy.sh`, `scripts/rollback.sh`, `scripts/verify-deployment.sh` and `scripts/lib/deploy-lib.sh` were untracked working-tree files, and `.env.example` and `docker-compose.yml` were modified but uncommitted. Commit `25e072f` (`feat(deploy): scripted deployment and rollback by registry digest`) landed all of it. What `git status` says now:

```
$ git status --short --branch
## main...origin/main [ahead 1]
?? docs/deployment.md
?? docs/m3-study-guide/
?? docs/m4-plan.md
```

`scripts/` is **clean**. The digest-pinned compose default and `.env.example`'s `API_IMAGE` are committed. The untracked files listed above are documentation, not deploy tooling.

**What this changes operationally:** the host's `git pull --ff-only` is now a real delivery path for the deploy scripts (§2.3, Option A), and the digest pinned in `docker-compose.yml` and `.env.example` is on `main` rather than being a local-only belief (§3.2). The checkout on the host still has to actually be a checkout, and still has to have been pulled — confirm with §2.2 rather than assuming.

---

## 1. Prerequisites

### 1.1 Operator workstation

| Requirement | Why | Notes |
|---|---|---|
| AWS CLI v2 | SSM, and reading Terraform output | `RUNBOOK.md:9` |
| AWS credentials for profile `lemondrop` | — | `RUNBOOK.md:4` — all AWS commands assume this profile and region `eu-west-1` |
| Region `eu-west-1` | — | `RUNBOOK.md:4`; `infra/versions.tf` backend block per `RUNBOOK.md:29-38` |
| The EC2 instance id | target of every SSM call | `i-0c3155b1b6bb31298` per `RUNBOOK.md:92`; also `terraform output ec2_instance_id` (`infra/outputs.tf:172-175`). **Confirm it is current before using it** — `RUNBOOK.md` is a Milestone 2 document and `i-0c3155b1b6bb31298` is the value it recorded then. §12.1 row 1 of `docs/verification-milestone-3.md` records that the instance id was *unchanged* across the Milestone 3 resize to `t3.small`, which is the reason this runbook still quotes it. |
| Docker, with Compose v2 (`docker compose`, not `docker-compose`) | To resolve a digest, and if you verify from your own machine | `README.md` (Prerequisites) — the stack was built and verified against Compose v5.5.1 |
| `jq` (optional) | Only if you read Secrets Manager by hand | Not needed by any step in this runbook. The host resolves the database credential itself. |

**The instance has no SSH key and no public IP** (`RUNBOOK.md:89`, `infra/outputs.tf:180-186`). Everything reaches it through SSM.

### 1.2 Permissions the operator needs

Split carefully, because these are two different systems and conflating them is how people end up with a permission they did not intend to grant.

**AWS (your IAM principal, on your workstation):**

| Action | Resource | Used for |
|---|---|---|
| `ssm:StartSession` | the instance | Interactive shell |
| `ssm:SendCommand` | the instance | Running anything non-interactively |
| `ssm:GetCommandInvocation` | the instance | Reading the result of a `SendCommand` |
| `ssm:ListCommands` / `ssm:ListCommandInvocations` | the instance | Finding a previous command id |
| `ssm:GetParameter` / `ssm:GetParameters` | `/aws/service/ami-amazon-linux-latest/*`, and this stack's DB host/port parameters | Only if you run Terraform. **Not needed for a deploy.** |
| `ec2:DescribeInstances` | — | Confirming the instance id |

`ssm:SendCommand` + `ssm:GetCommandInvocation` is the minimum for the workflow in this runbook; the exact pair `RUNBOOK.md:98-106` uses.

**GitHub (your account):**

| What | Why |
|---|---|
| Read access to this repository | To read this runbook and to know what commit you are deploying |
| Ability to read Actions run logs / job summaries for `main` | To obtain the registry digest of the image built for a commit — see §3.3 |

Nothing in the deploy path needs write access to either system. In particular, **a deploy does not push anything to a registry** — it pulls. The image was pushed by CI, separately, before you got here.

**GHCR requires no AWS permission at all.** The API image lives in GitHub Container Registry, not in ECR. There is no ECR repository in this stack (`infra/` contains no ECR resources). **The package was observed anonymously readable**, so at the time of that observation `docker pull ghcr.io/...` needed no credentials of any kind, on the host or anywhere else (§10 item 7 records the evidence, and the limits on what that evidence means). If it stops being anonymously readable, you need a GitHub token with `read:packages` **on the host**, which is a separate operational problem. **Package visibility is a setting separate from repository visibility**, and anyone with access to the package can change it, so this paragraph describes what was observed rather than a standing guarantee — §3.3's check is what an operator runs.

### 1.3 Permissions the host does *not* have, and why that is a feature

From `infra/iam.tf` and `scripts/lib/deploy-lib.sh`, the block headed `── WHAT IS *NOT* IN HERE ──`:

- The EC2 instance role can call `secretsmanager:GetSecretValue` on **exactly one ARN** — the application credential `data.aws_secretsmanager_secret.app_db` (`iam.tf:537-545`). Action list is `GetSecretValue` only; `Resource` is one ARN, never `*`.
- It **cannot** read the RDS master secret. `docs/verification-milestone-3.md` §12.1 row 18 records the operator confirming `AccessDeniedException` — the ARN resolved, policy said no. That is the control working, and it is recorded as a PASS.
- The `lemondrop_app` database role it carries has **no DDL rights**. `deploy.sh`, in `schema_gate()`, states the consequence plainly: "There is no migration that can be run from this host, by this script, with an override, because there is no credential here that could run one."

**Therefore: migrations cannot be run from EC2, and this is deliberate, not an oversight.** The schema gate in `deploy.sh`'s `schema_gate()` fails closed with no override flag, and its refusal message says why. The separate approved procedure for a schema change is `api/alembic/README.md`, executed out of band with the RDS master credential from a workstation. Never from the host.

---

## 2. How the scripts reach the host

**Read this section before planning a deploy.** It is the step most likely to be skipped, and skipping it makes everything downstream impossible.

### 2.1 The problem, stated exactly

The application checkout on the host is created and refreshed by the boot script — a `git clone --depth 1` on first boot, `git pull --ff-only` thereafter (`infra/compute.tf` step 3, mirrored in `scripts/boot.sh`). The deploy tooling is tracked source, so in principle the ordinary source-update path carries it: `deploy.sh`'s `DELIVERY` block says `git -C /opt/lemondrop pull --ff-only` "is sufficient and is the cheapest thing that can work."

Two things stop that from being a plan:

1. Even though the scripts are now committed (§0.4), the host's checkout is only current if someone has pulled it. An **ordinary reboot does not run the boot script at all** (§9.5.1), so nothing refreshes the checkout on its own. Whether Option A is available is a question about the host's checkout, not about the repository — check §2.2.
2. `git pull --ff-only` needs `/opt/lemondrop` to be a working checkout with history to fast-forward within. The boot script clones `--depth 1`, and `deploy.sh`'s `DELIVERY` block records that a shallow clone has nothing to fast-forward into until it fetches.

### 2.2 Confirming whether they are already there

Run these on the host (SSM session, or as the commands of a `SendCommand`):

```bash
sudo ls -l /opt/lemondrop/scripts/deploy.sh \
           /opt/lemondrop/scripts/rollback.sh \
           /opt/lemondrop/scripts/verify-deployment.sh \
           /opt/lemondrop/scripts/lib/deploy-lib.sh
```

All four must exist and be readable. Then confirm they are this project's, not an older copy:

```bash
sudo grep -c 'DEPLOYED_REVISION\|deployed-revision.env' /opt/lemondrop/scripts/lib/deploy-lib.sh
sudo grep -n 'PREVIOUS_IMAGE_DIGEST' /opt/lemondrop/scripts/rollback.sh | head -1
```

A non-zero first count and a `PREVIOUS_IMAGE_DIGEST` hit in `rollback.sh` mean the copy on the host carries the record format this runbook describes. A missing file means you are on a pre-M4 host and section 2.3 applies.

Also confirm the checkout is a real checkout, because two deploy steps read git objects from it:

```bash
sudo git -C /opt/lemondrop rev-parse --git-dir     # must print .git or an absolute path, not fail
sudo git -C /opt/lemondrop rev-parse --short HEAD
```

`deploy.sh` refuses with `EX_REFUSED` (2) if `/opt/lemondrop` is not a git checkout when it needs to read a schema head (`deploy-lib.sh`, `alembic_head_at_revision()`).

### 2.3 The transport, described honestly

**There is no transport script in this repository, and this runbook does not supply one.** That omission is deliberate and is stated as such in `deploy.sh`, in its `DELIVERY` block ("NOT WRITTEN HERE, ON PURPOSE"):

> NOT WRITTEN HERE, ON PURPOSE: any SSM transport, any `aws ssm send-command` wrapper, any CI job. Deploying this code to a host, and running it there, are two different operations with two different approvals, and collapsing them means the approval for one silently becomes the approval for the other.

So there are exactly two options, and choosing between them is an approval decision you make deliberately:

**Option A — pull, if and only if the tooling is committed and the checkout is healthy.**

```bash
sudo git -C /opt/lemondrop pull --ff-only
```

Cheapest; uses the same source-update path the boot script already uses. Requires the files to be committed and pushed to the branch the host tracks. If it fails with a shallow-clone error, see §2.4.

**Option B — explicit file transfer of the four files.**

A file copy, over whatever transport you are already approved to use (SSM `SendCommand` with a here-document, an S3 object staged into the instance's own role-readable bucket, an approved session). This is a *file-copy operation and nothing more* — `deploy.sh`'s `DELIVERY` block describes it exactly that way.

**What Option B must not be:** a mechanism that embeds credentials in `user_data` or anywhere else Terraform reads. `infra/variables.tf:611-622` and `docs/boot-script.md:205-219` explain why: `user_data` is returned in full by `ec2:DescribeInstanceAttribute`, is written in plain text to `/var/lib/cloud/instances/<instance-id>/user-data.txt`, and is echoed to `/var/log/cloud-init-output.log`.

After a transfer, the files should be owned by root and executable where they are executable:

```bash
sudo chown root:root /opt/lemondrop/scripts/deploy.sh \
                    /opt/lemondrop/scripts/rollback.sh \
                    /opt/lemondrop/scripts/verify-deployment.sh
sudo chmod 0755 /opt/lemondrop/scripts/deploy.sh \
                /opt/lemondrop/scripts/rollback.sh \
                /opt/lemondrop/scripts/verify-deployment.sh
sudo chmod 0644 /opt/lemondrop/scripts/lib/deploy-lib.sh   # sourced, not executed
```

**A note on the repository's own state, which affects Option A specifically.** `docs/boot-script.md:205-207` records that boot step 3 **currently fails on boot** because the clone target is a private GitHub repository that the instance cannot authenticate to. `infra/variables.tf:619-622` says the same. But `docs/m4-plan.md:780` asserts the repository *is* public, and `docs/verification-milestone-3.md` §12 records a working deployed stack, which implies the clone succeeded at some point. **The repository contradicts itself on this point** and I cannot resolve it from the files. So: check §2.2's `rev-parse` output rather than assuming, and if `/opt/lemondrop/.git` is absent, Option A is not available and Option B is the only path.

### 2.4 The source revision must be fetchable on the host

Independent of the scripts, the schema gate needs the target commit's **source tree** present in `/opt/lemondrop`:

```bash
sudo git -C /opt/lemondrop cat-file -e <40-char-sha>^{commit} && echo present
```

If that fails, `alembic_head_at_revision` prints the exact command to run (in `deploy-lib.sh`, `alembic_head_at_revision()`, which prints the command):

```bash
sudo git -C /opt/lemondrop fetch --depth 1 origin <40-char-sha>
```

The deploy script will not fetch for you. `deploy-lib.sh`, `alembic_head_at_revision()`: "deploy.sh will not fetch for you: it reaches the registry and nothing else." This is almost always necessary on a host cloned `--depth 1`.

**Why a source tree is needed at all:** the published image cannot report its own schema. `api/requirements.txt` deliberately excludes alembic (it is in `requirements-dev.txt`) and `api/Dockerfile` copies only `app/`, so the image contains neither the migration tooling nor `api/alembic/versions/` (stated in `deploy-lib.sh`, in `alembic_head_at_revision()`, under `── WHY NOT \`alembic heads\` INSIDE THE IMAGE ──`). And it cannot be read from the database, because the host has no DDL credential (§1.3). So the head is read from git with `git show`, deriving it the way alembic does: the set of `revision` values minus the set of non-`None` `down_revision` values (`deploy-lib.sh`, `alembic_head_at_revision()`). Zero heads and more than one head are both refusals, not "compatible" (`deploy-lib.sh`, `revisions_agree()`).

---

## 3. Choosing a revision

### 3.1 Always by digest, never by tag

`validate_image_digest` in `deploy-lib.sh` accepts exactly one shape:

```
<registry>/<repository>@sha256:<64 lowercase hex digits>
```

Everything else is refused, each with a stated reason, in `deploy-lib.sh`'s `validate_image_digest()`:

| Refused | Why |
|---|---|
| `lemondrop-api` (bare name) | Docker resolves this as `docker.io/library/lemondrop-api` — a public Docker Hub image this project does not control. `validate_image_digest()` in `deploy-lib.sh` calls this "the single most important refusal in this file." |
| `ghcr.io/owner/img:latest` | A tag is a **mutable pointer**; GHCR enforces no immutability on one. `validate_image_digest()` in `deploy-lib.sh`. |
| `ghcr.io/owner/img:sha` | Same problem, smaller: it *looks* immutable because it looks like a commit, and is not. |
| `…@sha256:abc…` (truncated) | A digest that is not 64 hex characters is not a digest; accepting a prefix would let a typo select a real, **different** image. |
| `…:tag@sha256:…` | Legal in docker, refused here: the digest alone decides content, so the tag only makes the recorded string disagree with `docker inspect`. |
| anything with whitespace | — |

**Why this matters, in the project's own words.** `docs/verification-milestone-3.md` §11.2: *"A tag overwritten in place is not a rollback point — it is the same failure mode as having no rollback at all, only harder to notice."* And in `.github/workflows/release.yml`, under `── WHAT THE SHA TAG IS, AND WHAT IT IS NOT ──`: the `:${GITHUB_SHA}` tag is "a NAMING CONVENTION, NOT AN IMMUTABILITY GUARANTAGE. GHCR offers no immutability enforcement for container tags: `docker push` against an existing `:sha` tag SUCCEEDS and silently OVERWRITES the manifest that tag resolves to."

**A tag is a pointer; a digest is the content.** `docker pull …@sha256:…` resolves to the same bytes forever. `docker pull …:<tag>` does not, after a second push.

### 3.2 The digest written down in this repository — a worked EXAMPLE, not a current revision

`docker-compose.yml` pins its `image:` default to a fully-qualified, digest-pinned reference. **That digest is stale by construction and you must not deploy it on the strength of this document.**

**The format is what matters here; the value is an example:**

```
ghcr.io/fvitorino00/lemondrop-api@sha256:<64 lowercase hex digits>
```

**Why no concrete digest is given as current.** A new digest is produced by **every merge to `main`**, because every push that passes the release gates publishes a new image. At the time of writing the committed defaults in `docker-compose.yml` and `.env.example` name `sha256:0bdb7afa…42986`, and both files also carry earlier digests in their surrounding commentary — `sha256:d4aac49d…` and `sha256:780f04cd…` — published by successive runs. **Every one of those is a record of a past run, not a pointer to the current one.** A runbook that names one as "the" digest is wrong the moment `main` moves, and it will be read as current long after it stopped being so.

**So: get the digest from the release run (§3.3), not from a file in this repository.** The two places in this repository that name a digest are the compose default and `.env.example`, and both exist so that boot has a *safe* value — not so that an operator has an *approved* one. The comment above the `image:` line says as much, and records that with no `build:` key that line now decides what actually gets **run**, not merely what a local build would be called.

Two further caveats on the example digest, both of which survive the commit:

- The comment above it asserts the image is one this project "published, verified, and can pull anonymously". The anonymity half was **contradicted elsewhere in the repository**, and that contradiction is now **answered by observation** (§10 item 7). `docs/verification.md:148` records the repository as *private* and `docs/m4-plan.md:780` asserts it is *public*, and `docs/m4-plan.md` open question 4 (line ~790) asked: "**Is the GHCR package to be public or private?** … Public follows from the repo being public, but package visibility is set independently and should be confirmed." **That disagreement is about repository visibility and it does not bear on package readability** — a public repository does not imply a public package, and the package is what a pull actually touches. The package was observed anonymously readable; the repository-visibility question tangled up with it is a different question, still open, and irrelevant to whether the host can pull.

Treat the pinned value as a worked example of the reference format and as a *safe default*, not as an approved production revision. Confirm §3.3 for any digest you actually intend to deploy, and run §3.3's anonymous-pullability check **on that digest, on the day** — §10 item 7 records readability observed at verification time against an older digest, not a property of this one or of any future one.

### 3.3 How to obtain the digest for a given commit

The authoritative source is the **`publish` job of `.github/workflows/release.yml`**, in this order. (`.github/workflows/release.yml` is **not** cited by line number anywhere below: commit `05d37bb` added 321 lines to it and moved every anchor in this section. It is cited by the step's `name:` field and by the quoted strings the job writes, which is what you should search for.)

1. **Job summary.** The step named **`record the pushed digest`** writes a Markdown summary block (`>> "$GITHUB_STEP_SUMMARY"`) containing:
   ```
   - sha tag:      `ghcr.io/<owner>/lemondrop-api:<40-char-sha>`  (naming convention — not registry-enforced immutability)
   - main tag:     `ghcr.io/<owner>/lemondrop-api:main`            (moving pointer, convenience only — never deployable)
   - **registry manifest digest (authoritative):** `ghcr.io/<owner>/lemondrop-api@sha256:<64-hex>`
   ```
   Find it in GitHub → the repository → **Actions** → the run for your commit → the `publish` job → job summary.

2. **Job log.** The same step echoes a line at the end:
   ```
   published digest: ghcr.io/<owner>/lemondrop-api@sha256:<64-hex>
   ```

**The tags you will also see, and must not deploy:**
- `:<40-char-sha>` — deployable *reference*, not an immutable one (§3.1).
- `:main` — a moving pointer, "convenience only — never deployable" (that exact string is in the summary block).

**Two different hashes exist and they are never interchanged** (the `── IT IS A DIFFERENT VALUE FROM \`EXPECTED_DIGEST\`, AND IS NEVER SWAPPED WITH IT ──` block in `release.yml`, and the `Labelling the image removes that requirement` comment near the top):
- **The registry manifest digest** (`RepoDigests`, the registry's own hash of what it stored) — **this is the one any deployment pins to.**
- **The local image-config ID** (`docker image inspect --format '{{.Id}}'`), which the pipeline uses for its artifact-identity check because it needs no registry.

`release.yml`, same block: "Writing the local ID into the 'published digest' field would be a correctness bug, not a cosmetic one."

**Confirm a digest is pullable before you deploy it.** From any machine with no registry credentials:

```bash
docker manifest inspect ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex> >/dev/null && echo PULLABLE
```

**Judge it by whether the command succeeded — not by whether a `401` appeared.** GHCR answers an unauthenticated manifest `GET` with `401` and a `www-authenticate: Bearer realm="https://ghcr.io/token", service="ghcr.io", scope="…:pull"` challenge for **every** package, public or private; that challenge is how a client obtains a read token, not a verdict on privacy. `docker manifest inspect` performs that exchange anonymously and prints the manifest when the package allows it. Reading the `401` as "private" is a false negative.

If you want the conclusion to be anonymous **by construction** rather than by inference, prove it with an empty credential store and check that nothing was written into it:

```bash
D=$(mktemp -d)                       # verified empty
DOCKER_CONFIG="$D" docker pull ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex> && echo PULLABLE
ls -A "$D"                           # empty afterwards => no credential was written or consulted
```

If the command itself fails and the anonymous exchange does not complete, the package is not anonymously readable at that moment and the host will not be able to pull it either. **The package visibility setting can be changed by anyone with access to it**, so this check — not this document, and not §10 item 7 — is the answer for any given day.

**Confirm the digest belongs to the commit you think it does:**

```bash
docker buildx imagetools inspect ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex>
```

Read the digest back and compare it, character for character, to what the Actions summary printed. A truncated digest in a runbook is worse than none.

---

## 4. Deployment

### 4.1 Decide before you type: is this a rollback or an investigation?

From `docs/m4-plan.md` §4.4 item 4, restated at the head of `rollback.sh` so the decision is made *before* the incident rather than during it:

| Situation | Action |
|---|---|
| `/health` or `/search` fails within the wait | **Roll back.** No judgement call. |
| `/health` fine but `/search` wrong | **Roll back**, then investigate. |
| A latency regression, results still correct | **Investigate first.** Do not roll back a correct deployment over performance. |
| A migration was applied out of band | Do **not** roll the API back on its own unless that migration is known to be backward compatible. Check the recorded alembic head first (§6.4). |

### 4.2 Read the current state first

On the host, as root:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh
```

This mutates nothing — no lock file, no log, no record, no container (stated at the head of `verify-deployment.sh`). It is safe on a host that is on fire, mid-deploy, or that has never been deployed to. **Its exit code is 0 only when it found no problems at all** (`verify-deployment.sh`, in its exit-code handling at the foot of `main()`).

Pay attention to the `── do they agree? ──` section. `AGREE` means the running image is the one the record names. `DIVERGENCE` means it is not, and the script prints the three usual causes with the reboot first (in `verify-deployment.sh`'s `── do they agree? ──` section).

If there is no usable record, the script says so and adds: "scripts/rollback.sh would refuse." That is true; §7.1 covers it.

### 4.3 Run the deploy

```
sudo /opt/lemondrop/scripts/deploy.sh <registry>/<repo>@sha256:<64-hex> [source-git-sha]
```

**One argument is sufficient** for any image published by a release run that carries OCI labels, which is every image published since commit `05d37bb`. The second argument is **optional** — see §4.4 for what it is still for.

Example shape — **substitute real values, do not paste this**:

```bash
# A labelled image: the digest alone.
sudo /opt/lemondrop/scripts/deploy.sh \
  ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex-digest>

# An image with no labels, or when you want the argument cross-checked
# against the label (see §4.4 — supplying it is not redundant).
sudo /opt/lemondrop/scripts/deploy.sh \
  ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex-digest> \
  <40-char-commit-sha>
```

Always run it as `sudo`. The state directory, lock and log are root-owned; a non-root run cannot take the lock or write the record. `DEPLOYED_BY` is recorded from `$SUDO_USER` (the `DEPLOYED_BY=` key in `write_record`, and again in `adopt_current()` in `deploy.sh`), which is why the record says who you are rather than "root".

### 4.4 The source revision: optional on a labelled image, and still worth passing

**An earlier draft of this section said the second argument was required, and that the published image carried no revision label. Both statements were true when written and both are false now.** The label support landed in commit `05d37bb`; the scripts that read it landed in `25e072f`. What follows is the current behaviour. The reasoning in the old draft was sound; it described an image that is no longer the one you are deploying.

**Images published since `05d37bb` carry three OCI labels.** `.github/workflows/release.yml` stamps them on the build-push step, under the `labels:` key:

| Label | Fact it carries |
|---|---|
| `org.opencontainers.image.revision` | **Provenance** — which commit's tree this image is |
| `org.opencontainers.image.source` | Where that tree lives |
| `org.lemondrop.alembic-head` | **Schema** — which alembic revision the code in this image expects the database to be at |

`scripts/lib/deploy-lib.sh` reads all three, in the functions `image_label()`, `image_source_revision()`, `image_source_url()` and `image_alembic_head()`. `image_label()` is a real function in that file — verify with `grep -n image_label scripts/lib/deploy-lib.sh`, which returns hits. An earlier draft of this runbook claimed that grep returned `0` and that the labelling work was unlanded and self-inconsistent. That was a true reading of an older tree and it is no longer a reading of anything.

**So the flow on a labelled image is:**

```
sudo /opt/lemondrop/scripts/deploy.sh ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex>
```

That is sufficient. `deploy.sh` takes one or two arguments — its argument check is `expected 1 or 2 arguments, got $#` — and with one it prints `no source revision given.`, explains that the old refusal no longer applies because "Images built by a release run now carry both facts as OCI labels", and continues to the pull. The two facts are then established from the image itself by `resolve_deploy_facts()` in `deploy-lib.sh`, and the authoritative schema gate runs on the image's own `org.lemondrop.alembic-head` before anything is switched.

**The second argument is not redundant, and passing it is still worth doing:**

- **It is required on an unlabelled image.** The image published from commit `8cddfe8` (`sha256:0bdb7afa…42986`) predates `05d37bb` and carries no labels at all. `deploy-lib.sh` says so explicitly — "Every function below therefore degrades to the operator-supplied source revision rather than refusing, and says loudly that it has done so." That image must stay deployable, and the argument is how. If you deploy it with one argument, the deploy will reach the authoritative gate and refuse, asking for the revision explicitly.
- **It cross-checks the label.** If you supply it and the argument and `org.opencontainers.image.revision` name *different* commits, `revisions_agree()` in `deploy-lib.sh` treats them as a conflict and `deploy.sh` **refuses** rather than silently picking one. That is the check worth more than the argument's disappearance: it is what catches a digest that does not belong to the commit you think you are deploying.
- **It enables the early gate.** With a revision supplied, the pre-pull schema gate can run against the source tree *before* the download, so a schema-incompatible deploy is refused without spending a download. Without one, the only thing spent is the download.

**Passing it on a labelled image therefore costs you one argument and buys you an early refusal and a provenance conflict check. The only reason to omit it is habit.**

**Do not read a label off the pipeline and assume the host's copy of the scripts can read it.** Confirm the host is running a `deploy-lib.sh` that has `image_label()`:

```bash
sudo grep -c 'image_label()' /opt/lemondrop/scripts/lib/deploy-lib.sh   # 0 means old scripts
```

If that prints `0`, the host predates label support and you **must** pass the second argument. If the digest you are deploying was published before `05d37bb`, you must pass it regardless of what the host's scripts can do.

If the revision you pass is not present in the host's checkout, §2.4's `git fetch` is the fix.

### 4.5 What the script does, in order, and what you will see

The order is the design (`deploy.sh`, under `── THE ORDER IS THE DESIGN ──`). **Nothing is changed until every check that can be made without changing something has passed.**

⚠️ **An earlier draft of this table listed ten steps and silently omitted 6b and 6c.** They are real, they are load-bearing, and they are where the labelled-image flow of §4.4 actually happens. The table below is the sequence in `deploy.sh`'s `main()`, including them.

| # | Step | What you see | Changes anything? |
|---|---|---|---|
| 1 | **lock** (`acquire_lock` in `deploy.sh main()`) | `waiting up to 300s for the deployment lock (/var/lock/lemondrop-deploy.lock)` then `lock acquired (pid N)` | creates the lock file only |
| 2 | **validate** (`validate_image_digest`, plus three host checks) | a refusal reason on stderr if the reference is not a digest; `refusing to deploy '<ref>'. See the reasons above.` then exit 2. Also refuses if `/opt/lemondrop`, its `.env`, or its `docker-compose.yml` is missing | no |
| 3 | **capture** (`capture_state()` in `deploy.sh`) | `existing record: IMAGE_DIGEST=…` or `no existing record at …`; `rollback tag: lemondrop-api:rollback-<UTCstamp> -> sha256:…` | writes a `.env` backup to `/var/lib/lemondrop/env.before-deploy.XXXXXX` (mode 0600) and one docker tag |
| 4 | *(the ERR trap is installed here — `trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR`, immediately after `capture_state`)* | — | — |
| 5 | **registry check** | `checking the registry for <ref> …` then `  manifest found.` | no — one small registry request, before anything is switched |
| 6 | **schema gate, first pass** — *early optimisation only* | with a revision supplied: `reading the alembic head at <sha> …` / `  head from the source tree: <head>`. Without one: `no source revision given.` and an explanation that the authoritative gate will run after the pull | no |
| 7 | **pull** | `pulling <ref> …` / `  pulled image id: sha256:…` (and possibly a `NOTE: the image also answers to …` when the registry lists an index and a platform manifest separately) | downloads the image |
| **6b** | **establish the two facts from the image** (`resolve_deploy_facts()`) | `establishing what this image is, from the image itself …` / `  source revision : <sha>  (from: <label\|argument>)` / `  alembic head    : <head>  (from: <label\|argument>)`. **This is where §4.4 happens** | no — a refusal here is free, which is why it is here and not after `compose up` |
| **6c** | **schema gate, authoritative** | `schema gate: OK — target head '0001' matches the recorded head.` — or, on a **labelled image whose `org.lemondrop.alembic-head` does not match the recorded `ALEMBIC_HEAD`**, the `════════ SCHEMA MISMATCH — REFUSING ════════════════` block below | no |
| 8 | **switch** | `writing API_IMAGE into /opt/lemondrop/.env …` then `recreating ONLY the api service …` | **first change:** `.env`, then the `api` container |
| 9 | **verify** (`verify_stack`) | `verifying the new deployment …` then the readiness and known-good-search lines | no |
| 10 | **record** (`write_record`) | the `──────────────── DEPLOYED ─────────────────────────` block | writes the record |

**The two-pass schema gate is deliberate and is not a bug.** Step 6 is an *optimisation*: it can refuse before spending a download, and if the source tree cannot answer it says so and continues rather than refusing. Step 6c is the *decision*: it runs against the head that will actually be recorded, and it is the one that fails closed. When a revision **is** supplied the gate runs **twice** — once early against the source tree, once authoritatively against the image. `deploy.sh` states the rationale: "The gate runs in both cases, and in the first case it runs TWICE … That is strictly more work and never less checking, which is the only direction a fail-closed gate is allowed to move in."

**Nothing is lost by 6b/6c being before step 8.** Everything above step 8 downloaded bytes into a local image cache. `.env` is untouched, no container has been recreated, and the record has not been written.

**Notes on individual steps.**

- **Step 5 comes before the pull on purpose** (`deploy.sh`, under `── IS THE DIGEST OBTAINABLE ──`): "A typo'd digest discovered after the old container is gone is a self-inflicted outage; discovered now it is a message."
- **Step 6 comes before the pull on purpose too** (`deploy.sh`, `── SCHEMA GATE (FIRST PASS …) ──`): "the gate needs no image and no network — only the source tree — so running it here refuses a schema-incompatible deploy without spending a download on an artifact nobody is going to run."
- **⚠️ Step 6c's refusal — the labelled-image head mismatch — has no override, by design.** On a labelled image, `6c` compares the image's own `org.lemondrop.alembic-head` against the `ALEMBIC_HEAD` in the record. If they differ, `schema_gate()` prints and refuses (exit 2), before `.env` is touched:

  ```
  ════════ SCHEMA MISMATCH — REFUSING ════════════════
    recorded alembic head (the running deployment): 0001
    target  alembic head (revision <40-char-sha>):     0002
  ```

  The script names both values, refuses to migrate, and says why it cannot: "This script will NOT migrate, and there is no flag to make it. The EC2 role can read only the application secret and `lemondrop_app` has no DDL rights (`infra/iam.tf`), so a migration cannot be run from this host at all."

  **This is a different refusal from §7.1's `SCHEMA DISAGREEMENT`, and the difference is which side moved.** Here both values come from artefacts this host can read: the record says what was deployed, the label says what this image expects, and the disagreement is between two revisions of *this project's* schema history — almost always a migration that was applied out of band without a redeploy. The fix is either to deploy the revision whose head still matches the record, or to apply the missing migration from a workstation with the RDS master credential (`api/alembic/README.md`) and record the new head. **Do not edit `ALEMBIC_HEAD` in the record to make the gate pass.** That is the "do not hand-edit it into something truer" that `adopt_current()` warns about on the neighbouring path (§7.1), and it is the one edit that would make every *subsequent* deploy compare against a fiction.

  The other two `6c` refusals — `schema gate: no usable baseline.` (no record at all, §7.1) and `schema gate: the record … carries no ALEMBIC_HEAD.` (a record with no schema head) — both exit 2 and change nothing. Note the second one exists to stop "unknown" being treated as "compatible".

- **Step 8 order is `.env` first, then the service** (`deploy.sh`, `── SWITCH ──`): the reverse order would recreate the api against the *old* `API_IMAGE`, restarting the old image for no reason and then changing the pin without ever having run it.
- **Step 8's three flags are load-bearing** (`deploy.sh`, the comments on the `compose up -d --no-build --no-deps --force-recreate api` line):
  - `--no-build` — **mandatory.** "Without it compose rebuilds from ./api and the whole strategy silently reverts to today's defect — deploying a locally built image while the record claims a digest that was tested."
  - `--no-deps` — the embedder and reranker keep running with their models warm. Recreating them would re-load ~410 MB of GGUF on a t3.micro for no reason.
  - `--force-recreate` — the api must be *replaced*, not left alone because its configuration appears unchanged to compose.
- **Step 10 is last, on purpose** (`deploy.sh`, `── RECORD ──`): "A record written before verification is a record of a deployment that might not work, and the next deploy would use its head as a baseline — so an unverified deploy that poisoned the record would refuse every later one. Recording last is what makes the record trustworthy."
- **The success block names where each fact came from.** `revision : <sha>  (from: <label|argument>)` — read that suffix. It is the difference between "the image told us" and "you told us", and on an unlabelled image it is the only warning you get.
- **⚠️ On the ADOPTION path that suffix has a third value, and it is the only one you get.** Everything above describes a **deploy**. Adoption (`--adopt-current`, §7.1) prints `revision    : <sha>  (from: image-label (org.opencontainers.image.revision))` when the running image is labelled, and otherwise:

  ```
    revision    : <unknown>  (from: UNKNOWN — the image carries no
                             org.opencontainers.image.revision label)
                  Recorded as unknown, on purpose. The checkout's HEAD is
                  not evidence of what built these bytes: it is whatever
                  boot.sh last cloned, and on this host it is ahead of the
                  running image's own tree.
  ```

  **Nothing is substituted for a missing label** — not the checkout's `HEAD`, not a timestamp, not a guess — so `REVISION` is written **empty** rather than filled from the tree. Adoption deliberately no longer calls `resolve_deploy_facts()`; the header comment in `adopt_current()` records why: feeding `git rev-parse HEAD` in as the revision slot "was wrong twice over", because for an unlabelled image it asserted evidence that did not exist, and for a labelled one it made the checkout a *competing* assertion — manufacturing a spurious `PROVENANCE CONFLICT` whenever a labelled image legitimately disagreed with a checkout that had moved on. `adopt_current()` records what is **running**; a deploy resolves what is **about to run**, and they now have different code.

  `verify-deployment.sh` reports the empty revision as `PROVENANCE UNKNOWN`, and the next deploy's own labels are the first real provenance this host will have.

**The success block looks like this** (shape from `deploy.sh`, under the `DEPLOYED` banner):

```
──────────────────────── DEPLOYED ──────────────────────────
  revision      : <40-char-sha>  (from: <image label | your argument>)
  digest        : ghcr.io/…@sha256:…
  alembic head  : <head>  (from: <image label | your argument>)
  rollback tag  : lemondrop-api:rollback-<UTCstamp>
  previous      : ghcr.io/…@sha256:…   (or <none recorded>)
  record        : /var/lib/lemondrop/deployed-revision.env

  Verify at any time with: scripts/verify-deployment.sh
  Undo with:               scripts/rollback.sh
─────────────────────────────────────────────────────────────
```

Only `VERIFICATION=PASS` in the record means this block was reached honestly. There is no path to it that skips step 9.

### 4.6 Reading the record

```bash
sudo cat /var/lib/lemondrop/deployed-revision.env
```

Format: one `KEY=value` per line, `#` comments and blanks permitted. **Parse it with `grep`/`sed`, never `source` it** (stated in `deploy-lib.sh`, above `RECORD_KEYS_RE`) — a file that gets `set -a; . record` is a file that can set any variable it likes.

Fourteen keys (the `RECORD_KEYS_RE` regex in `deploy-lib.sh`):

| Key | Meaning |
|---|---|
| `RECORD_VERSION` | `1` |
| `REVISION` | the git commit deployed. **May be empty** after an `--adopt-current` onto an unlabelled image (§4.5) |
| `SOURCE_REVISION` | same value, written by the deploy path |
| `IMAGE_DIGEST` | the digest deployed. **May be empty** after an `--adopt-current`, and after a legacy rollback (see §6.3, §6.4). An empty digest is what routes `verify-deployment.sh` to **`UNPINNED (LEGACY)`** — a third verdict, "nothing was compared", exit 0 — instead of the permanent false `DIVERGENCE` an empty-vs-empty comparison would produce. It used to be filled with a synthetic `unrecorded-local-image (<id>)` placeholder, which could never match a real digest list and so reported `DIVERGENCE` forever on a healthy host |
| `IMAGE_ID` | the image's own ID. **Written only when `IMAGE_DIGEST` is empty** — on a digest-bearing record the digest already names the exact bytes and a second identifier for the same image is a drift hazard the format otherwise refuses. It is the **only** field naming the running bytes on a legacy adoption, where the digest is empty and (on an unlabelled image) so is the revision. **Deliberately NOT a required key**, and it is the only optional one: every record already in the field predates it, and requiring it would make `record_is_valid` classify all of them as `TRUNCATED`, which would make `schema_gate` refuse the next deploy on every host that has ever been deployed to. An absent `IMAGE_ID` therefore means "this record names its image by digest" |
| `ALEMBIC_HEAD` | schema head at that revision. Empty is legal but blocks every later deploy (§7.1) |
| `DEPLOYED_AT_UTC` | ISO-8601 UTC |
| `DEPLOYED_BY` | `$SUDO_USER` |
| `VERIFICATION` | `PASS` or `UNKNOWN` |
| `VERIFIED_AT_UTC` | ISO-8601 UTC |
| `ROLLBACK_TAG` | local timestamped tag of the pre-deploy image |
| `PREVIOUS_REVISION` | what was deployed before this one |
| `PREVIOUS_IMAGE_DIGEST` | **the rollback target** |
| `PREVIOUS_ALEMBIC_HEAD` | the schema you would be returning to |

The record is written **atomically** — temp file in the same directory, `sync`, then `mv` (`deploy-lib.sh`, `write_record()`). A reader never sees a partial file, and a power cut cannot leave a correctly-named file full of zeroes.

It ends up **root-owned, mode 0644** (`write_record()` in `deploy-lib.sh`). If you later run a deploy or rollback *without* `sudo`, the write will fail — see §7.5.

---

## 5. Verification

### 5.1 ⚠️ Run these from the right network context

**Run readiness and the known-good search on the host, against `localhost:8000` — or from inside the compose network. Do not run them through the public ALB.**

Why, and this is not a style preference:

- The ALB's idle timeout is **60 seconds** (`infra/variables.tf:890-894`, default `60`; applied at `infra/load_balancer.tf:67`).
- The API's own worst-case request time is **~240 seconds**. `docs/verification-milestone-3.md` §10.8 tabulates it: `INFERENCE_TIMEOUT_SECONDS = 120` is a **per-call** budget (`api/app/main.py:106`, applied at `main.py:547`), and `/search` calls upstream **twice sequentially** — embed, then rerank — so 120 + 120 = ~240 s.
- **The ALB times out before the API does.** §12.4 item 4 records this as "an unaddressed known configuration defect" that "remains outstanding".

**This milestone does not fix that mismatch.** A search that takes longer than 60 s is perfectly correct on localhost and will still fail through the ALB. The one ALB observation on record is **15.55 seconds** (§12.1 row 12), and §12.4 item 4 is explicit that one observation is "**not** a margin measurement … and no distribution was taken."

### 5.2 On the host, against localhost

The scripts already do this, and this is what `deploy.sh` step 9 runs:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh
```

Under the hood (in `deploy-lib.sh` — `wait_for_ready()`, `known_good_search()`, `assert_probe_is_grounded()` and `verify_stack()`):

**Readiness** — `wait_for_ready`, polling `GET /health/ready` every 5 s up to 300 s:

```bash
curl -sS -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8000/health/ready
```

Success prints: `readiness: 200 from http://127.0.0.1:8000/health/ready after Ns (attempt N)`.
Failure prints: `readiness: NEVER 200 from … within 300s (last status: NNN)`.

`/health/ready`, not `/health` — `deploy-lib.sh`, `wait_for_ready()`: ready is the endpoint that reports the embedder, the reranker **and the database**. A container merely alive while its workers load GGUF answers 200 to `/health` and 503 to everything a user calls.

The base URL comes from `LEMDROP_API_BASE_URL` if set, otherwise `http://127.0.0.1:` + `API_HOST_PORT` from `.env`, defaulting to `8000` (`deploy-lib.sh`, `api_base_url()`).

**The known-good search** — `known_good_search`, `POST /search`:

```bash
curl -sS -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{"collection":"it-support","query":"recover a file a user deleted by mistake from the Recycle Bin"}'
```

Success prints:
```
known-good search: PASS — 'it-support' query ranked 'support-recycle-bin-file-recovery' first (10 candidates considered).
```

**Where every part of that assertion comes from** (the `LEMDROP_PROBE_*` defaults at the head of `deploy-lib.sh`, re-checked at run time by `assert_probe_is_grounded()`):

| Element | Value | Source |
|---|---|---|
| Collection | `it-support` | re-checked against `data/corpus.json` at run time |
| Expected top-ranked `document_id` | `support-recycle-bin-file-recovery` | re-checked against `data/corpus.json` at run time; present at `data/corpus.json:602` |
| The query | `recover a file a user deleted by mistake from the Recycle Bin` | `docs/verification-milestone-3.md` §8.2 row 1 — the recorded live run against the real cross-encoder over the real 40-document corpus |
| The expectation that it ranks **first** | — | §8.2 row 1 again |

**It asserts rank-first, not "appears in the top N"** (`deploy-lib.sh`, in `known_good_search()`): "If the reranker returns noise, the expected document usually still appears — in eighth place. That deployment serves users badly and passes this check."

**It re-grounds itself against the corpus on every run** (`assert_probe_is_grounded()` in `deploy-lib.sh`). If `data/corpus.json` no longer contains that document id, the probe fails with "The corpus changed. The known-good search is stale and its result proves nothing." That is the guard that stops a vacuous pass. On the host, if `/opt/lemondrop/data/corpus.json` is unreadable you get `CANNOT CHECK` — which `verify-deployment.sh` counts as a problem (`note_problem()` in `verify-deployment.sh`), and `assert_probe_is_grounded()` in `deploy-lib.sh` warns you in terms: "Do not read a pass here as proof the probe still matches the data."

**You can also run the same probe from inside the compose network**, which is the other correct context:

```bash
cd /opt/lemondrop
sudo docker compose -p lemondrop exec -T api \
  python -c "import urllib.request,json;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=10).status)"
```

### 5.3 Check ALB reachability separately — and know what it does not prove

```bash
ALB=$(aws ec2 describe-load-balancers --names "$(terraform output alb_dns_name)" --region eu-west-1 \
      --query 'LoadBalancers[0].DNSName' --output text)
curl -i "http://$ALB/health/ready"
```

The DNS name is also recorded literally in `RUNBOOK.md:75`.

**A passing `localhost:8000` check does NOT prove the ALB will route to it.** They are different questions:

| Question | Answered by |
|---|---|
| Is the process serving correct results? | localhost check |
| Will the load balancer route to it, and complete the request? | the ALB check, **and** only a request whose duration is under 60 s |

A request that exceeds the idle timeout fails at the ALB while succeeding on the host, with no error on the instance. So: **check both, and interpret a slow-but-correct localhost search as a pass on correctness and a warning on the ALB path.**

Note also that `/health/ready` returning 200 through the ALB is the ALB's own health-check signal (§12.1 row 11 recorded 200), and it says nothing about whether `/search` completes within 60 s.

---

## 6. Rollback

### 6.1 The rule

```
sudo /opt/lemondrop/scripts/rollback.sh
```

**No arguments.** The target is chosen by the record, not by whoever is holding the incident (`rollback.sh`, `main()`): "a rollback target is chosen by the record, not by whoever is holding the incident." Any argument is refused with `EX_REFUSED` (2).

This is deliberately symmetrical with `deploy.sh` and independently usable — "the moment a rollback is needed is precisely the moment the person running it should not have to reconstruct how the deploy path works" (head of `rollback.sh`).

### 6.2 What the record gives it

From `/var/lib/lemondrop/deployed-revision.env`:

- `PREVIOUS_IMAGE_DIGEST` — the target, when non-empty.
- `ROLLBACK_TAG` — the fallback, when the previous deployment predates digest-pinned deploys.
- `PREVIOUS_ALEMBIC_HEAD` — the schema you are returning to.

There is no third option and no prompting (in `rollback.sh`'s target-selection block): "an interactive question here is a question asked to someone who is already in the middle of an incident."

### 6.3 What it does, in order

| # | Step | Reference |
|---|---|---|
| 1 | Takes the lock. Exit 4 if held. | `rollback.sh`, `main()` |
| 2 | `record_is_valid()` — refuses on missing or malformed. **Nothing is changed.** | `deploy-lib.sh`, `record_is_valid()` |
| 3 | Prints what the record says: currently deployed, rollback target, fallback tag. | `rollback.sh`, `main()` |
| 4 | Chooses the target: digest if one was recorded, else the local rollback tag (§6.4). | `rollback.sh`, `main()` |
| 5 | States the schema question out loud if the heads differ — **as a warning, not a gate**. "a rollback is the wrong moment to refuse" | `rollback.sh`, `main()` |
| 6 | Copies `.env` to `/var/lib/lemondrop/env.before-rollback.XXXXXX` (mode 0600) before touching it. | `rollback.sh`, `main()` |
| 7 | Restores: pulls the digest if absent locally, writes `API_IMAGE`, recreates only `api` with `--no-build --no-deps --force-recreate`. | `rollback.sh`, `main()` |
| 8 | **Re-verifies** — readiness *and* the known-good search. | `rollback.sh`, `main()` |
| 9 | Rewrites the record, atomically, last. | `deploy-lib.sh`, `write_record()` |

Step 8 is not optional theatre: "A rollback is not finished when the container starts. It is finished when the restored image is serving correctly — otherwise a rollback to an equally broken image reports success and halves the evidence" (`rollback.sh`, step 8 of `main()`). On failure it exits `EX_FAILED` (3) and tells you `.env` as it was is at the backup path.

**It never deletes the record.** Not on success, not on failure, not when it refuses (head of `rollback.sh`): "The record is the only thing that makes 'what is running?' answerable, and a rollback that consumed it would mean a second rollback has nothing to work from."

After a rollback, `PREVIOUS_*` are emptied, so a **second rollback has no target and refuses** (the `PREVIOUS_*` empty-check in `rollback.sh`): "That is deliberate — a second rollback would be a guess." If you need to roll back twice, you are doing it by hand, deliberately.

### 6.4 The legacy M3 case — a rollback tag with no digest

A host last deployed by M3 behaviour has a record whose `PREVIOUS_IMAGE_DIGEST` is empty: nothing was digest-addressed, and the running image was **built on the host**, so it exists in no registry (head of `rollback.sh`). There is no registry reference to go back to.

What there *is* is the timestamped rollback tag `deploy.sh` took of the running image before it changed anything — `lemondrop-api:rollback-<UTCstamp>`, created from the image **ID** rather than from a name (`capture_state()` in `deploy.sh`), because a name can be moved and an image ID cannot.

The legacy path (the legacy branch of `rollback.sh`'s `main()`):

1. Verifies the tag is present locally. If not, it **refuses** (2): "It was built on this host and never pushed, so there is nowhere to fetch it from."
2. Re-tags it as `lemondrop-api`, because `--no-build` will not build it and the `lemondrop-api` tag may since have moved onto a newer image.
3. **Removes** the `API_IMAGE` key from `.env` rather than blanking it, so compose resolves the bare local name again — exactly the M3 wiring. Pointing `API_IMAGE` at the timestamped tag would also work but would leave the host configured by a migration script rather than by boot.sh.
4. Recreates `api` and re-verifies.
5. Records `IMAGE_DIGEST=` **empty**, because in the legacy path there is no digest to write — **and, on the same path, records `IMAGE_ID=`** with the restored image's ID. The two are written together and for the same reason: `IMAGE_ID` is written exactly when `IMAGE_DIGEST` is empty (§4.6), and on the legacy path that is *every* record. Without it the rewritten record would describe a deployment it cannot identify at all — no digest, and on an unlabelled image no revision either. The id is read by `docker image inspect` if the rollback did not already have it in hand.

An empty `IMAGE_DIGEST` is not an error. `verify-deployment.sh` prints, for a host-built image: "none — this image was built on this host and was never pulled from or pushed to a registry. That is the M3 behaviour, and it means it has no registry reference to roll back to."

**Know this before you need it:** on an M3 host, the rollback target is a local docker tag. Nothing prunes it, so it survives — but it also means the rollback only works on *that* host. There is no copy anywhere else.

### 6.5 Rehearsal procedure

A rollback you have never run is a hypothesis. Rehearse it **before** you need it. Note that `docs/m4-plan.md:670-673` makes this the milestone's actual acceptance criterion, and requires it to be performed by someone other than the author.

**Do it on a throwaway host, never on the one serving traffic.** There is no rehearsal mode and no dry-run flag; `deploy.sh --help` is the only non-mutating invocation.

```
PRE-REHEARSAL
  1. Record the current state.
       sudo /opt/lemondrop/scripts/verify-deployment.sh
       sudo cat /var/lib/lemondrop/deployed-revision.env | tee /root/pre-rehearsal-record.txt
       sudo docker images --digests | tee /root/pre-rehearsal-images.txt

  2. Make sure there is somewhere to roll back TO. With no PREVIOUS_IMAGE_DIGEST
     and no ROLLBACK_TAG, rollback.sh will refuse (2) and you will have rehearsed
     nothing. Deploy twice, or deploy once over an adopted M3 state.

  3. Note the time. Everything below should be undone by a rollback.

REHEARSAL
  4. Deploy revision B over revision A.
       sudo /opt/lemondrop/scripts/deploy.sh <digest-B> <sha-B>
     Expect exit 0 and the DEPLOYED block. Confirm:
       - IMAGE_DIGEST is digest-B
       - PREVIOUS_IMAGE_DIGEST is digest-A
       - ROLLBACK_TAG names an image local to this host

  5. Roll back.
       sudo /opt/lemondrop/scripts/rollback.sh
     Expect exit 0 and ROLLED BACK. Confirm:
       - IMAGE_DIGEST is digest-A again
       - PREVIOUS_* are now empty
       - scripts/verify-deployment.sh reports AGREE
       - the embedder and reranker container IDs did NOT change
         (they must not: only api is ever recreated)

  6. Time the rollback. It is a single container recreate plus re-verification;
     re-verification dominates (readiness alone is bounded at 300 s).

  7. Deliberately break it and rehearse the refusal paths:
       - delete the record        -> rollback.sh must exit 2, change nothing (§7.1)
       - truncate the record      -> rollback.sh must exit 2, change nothing (§7.1)
       - point PREVIOUS_IMAGE_DIGEST at a digest that does not exist
                                 -> docker pull fails, exit 3, .env backup named (§7.5)

  8. Restore the pre-rehearsal state:
       sudo /opt/lemondrop/scripts/deploy.sh <digest-A> <sha-A>
     Then re-run verify-deployment.sh and compare with step 1.
```

**What the rehearsal does not prove:** §10 item 1 — no real `docker` interaction in these paths has ever been exercised. A rehearsal that passes on a host is genuine evidence; a rehearsal that has never been run is not evidence of anything.

---

## 7. Recovery

Each scenario below: what you will see, why it happens, and the exact commands.

### 7.1 The revision record is missing or malformed

**What you will see:**

- `verify-deployment.sh`: `NO USABLE RECORD at /var/lib/lemondrop/deployed-revision.env.` and a counted problem, plus "Cannot compare: there is no record."
- `rollback.sh`: `REFUSING: no usable revision record.` … "Restarting whatever happens to be tagged is not a rollback, it is a coin flip." Exit **2**, nothing changed.
- `deploy.sh`: `schema gate: no usable baseline.` … "Deploying without one would mean deploying without knowing what the database currently is." Exit **2**.

**Why it refuses rather than guessing** (the header comment of `rollback.sh`): a missing record has no defined target. A *malformed* one is the sharper case — a write truncated by a full disk or a power cut can leave a file that still has `RECORD_VERSION` and `IMAGE_DIGEST` while the rest is gone, and `PREVIOUS_IMAGE_DIGEST` is exactly the field that decides where the rollback goes. Reading the fields that survived and acting on them "would restore nothing and report success." `record_is_valid` refuses the whole file instead.

It distinguishes *"this key is empty"* (legal — a first deployment, or one already rolled back) from *"this key is not there at all"* (only a damaged or foreign file).

**Recovery.** First, **look before you recreate anything**:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh
sudo docker inspect -f '{{.Image}}' "$(docker compose -p lemondrop -f /opt/lemondrop/docker-compose.yml ps -q api)"
sudo cat /var/lib/lemondrop/deployed-revision.env 2>&1
```

Then, if the running image is the one you want as the baseline. **`--adopt-current` takes one mandatory argument: the alembic revision the database is actually at.** It has no default and no fallback, and running it bare refuses (see *Why the argument is mandatory* below):

```bash
# 0001 is this host's database-verified revision — see "The database head this
# host is at" below in this section, for how that was established and why you
# must re-read it. On a DIFFERENT host the value is whatever that host's
# database is at; the argument is <db-verified-alembic-revision>, not universal.
sudo /opt/lemondrop/scripts/deploy.sh --adopt-current 0001
```

`--adopt-current` (`adopt_current()` in `deploy.sh`) writes a record describing what is running **right now** and changes nothing else — it only reads. It refuses if a record already exists, **including a malformed one** (the `[ -f "$LEMDROP_RECORD_FILE" ]` test at the top of `adopt_current()`). So a damaged record must be moved aside first:

```bash
sudo mv /var/lib/lemondrop/deployed-revision.env \
        /var/lib/lemondrop/deployed-revision.env.bad.$(date -u +%Y%m%dT%H%M%SZ)
sudo /opt/lemondrop/scripts/deploy.sh --adopt-current 0001   # or <db-verified-alembic-revision>
```

**⚠️ Do the `mv` last, or not at all.** The two commands above are shown together because they are the two halves of one recovery, not because they are independent. The `mv` is what makes the damaged record disappear to `adopt_current()`; the argument is what makes it succeed. Run with the argument missing and you have moved the evidence aside and recorded nothing — the record is now in `.bad.<stamp>`, the host has no baseline, and every later deploy refuses against no baseline. That is strictly worse than the damaged record you started with. **Confirm the revision first (§7.1 below), then move the file, then adopt.**

It prints everything it is about to record — container, image id, digest, revision, alembic head — and says "If any of it is wrong, fix the cause and delete the record — do not hand-edit it into something truer." **Read those lines before accepting them.** On an image built on this host the digest line reads `<none>`, the record gets an empty `IMAGE_DIGEST` **and** an `IMAGE_ID` naming the running bytes (§4.6).

**⚠️ A trap worth naming.** `--adopt-current` adopts whatever is running, healthy or not. If the host is currently serving a broken image, adopting it cements a broken baseline and every later deploy will be compared against it. That is why step 1 above is `verify-deployment.sh`.

**Why the argument is mandatory, and what the refusal now says.** An earlier draft of this section quoted a refusal about "no alembic head could be determined … every future deploy would refuse against an empty baseline", and pointed the reader at §2.4 to fix the checkout. **Both are gone.** That was the pre-`09cf02d` behaviour, when adoption derived the head from the git tree and could therefore fail to derive one. Adoption no longer consults the tree at all, so there is nothing left to fail to determine.

Running the bare command now refuses before touching anything — exit **2**, no record written, no state created:

```
$ bash scripts/deploy.sh --adopt-current
refusing: --adopt-current requires the database-verified alembic revision.
Usage:
  deploy.sh <registry>/<repository>@sha256:<64-hex-digest> [source-git-revision]
  deploy.sh --adopt-current <database-verified-alembic-revision>
  … (usage text) …
```

and the second refusal is the arity check — note it counts the flag:

```
$ bash scripts/deploy.sh --adopt-current 0001 extra
… (usage text) …
FATAL: --adopt-current takes one argument, the alembic revision the database is at (got 3).
```

**The value must be read out of band, because this host cannot read it.** The EC2 instance role holds the *application* secret only, and `lemondrop_app` is DML-only with no DDL rights — `CREATE EXTENSION vector` needs `rds_superuser`, which is precisely the split between the two credentials (`infra/iam.tf`, under *WHY THE APPLICATION CREDENTIAL AND NOT THE MASTER PASSWORD* and *⚠️ MIGRATIONS DELIBERATELY LOSE THEIR EC2 PATH. ⚠️*). The procedure for reading and migrating it is `api/alembic/README.md`, under *Against RDS, later*. `deploy.sh`, `rollback.sh` and `verify-deployment.sh` can all **compare against** `ALEMBIC_HEAD` and none of them can **confirm** it — nothing in this repository can. The argument is you, doing the looking, on purpose.

It is deliberately **not** taken from the git tree either: the checkout answers "what schema does this code expect", and this argument means "what schema is the database at". Those differ whenever a migration was applied out of band with the RDS master credential, which is the normal way this host's schema moves — and `boot.sh` clones `--depth 1` of whatever `main` was at boot, so the tree is routinely ahead of the database. `validate_alembic_revision_id()` rejects anything that could not be a revision id at all: non-identifier characters, more than 64 characters, a leading `-`/`.`/`_`, and the three symbolic names `head`, `heads` and `base`. **A value that survives is not proven correct — nothing on this host can prove that — it is merely not malformed, and the record says which of the two it is.**

**The other adoption refusal: the image's own label contradicts your value.** If the running image carries an `org.lemondrop.alembic-head` label and it is not the revision you verified in the database, adoption refuses before writing anything:

```
════════ SCHEMA DISAGREEMENT — REFUSING ════════
  the running image's org.lemondrop.alembic-head label says : <label value>
  the revision you verified in the database says       : <your argument>
```

The label says what the code **expects**; your value says what the database **is**. Disagreement means the api running right now expects a schema it is not being served — either a migration applied out of band without a redeploy, or the wrong revision recorded. **Re-read the revision from the database and work out which of the two is right before adopting.** The label is never used as the value; it is only used to contradict you.

**The database head this host is at.** This is written down here because the value has to be typed into a command and typing it from memory is how a stale number becomes a baseline:

| Fact | Value | How established | When |
|---|---|---|---|
| Live RDS alembic revision | `0001` | read out of band by the operator from the RDS instance, per `api/alembic/README.md` (*Against RDS, later*) | 2026-10-14 |

**Read the corroboration for what it is.** `docs/verification-milestone-3.md:145` row 1 records "Revision `0001` applied successfully", executed and reported by the operator. It confirms that **`0001` is the single migration this repository has**, and it is the origin of the number. It is **not** independent evidence about the RDS instance: row 8 of the same table, and the paragraph beneath it, record that the migration target resolved to `127.0.0.1:5432` — the local container — and state "Nothing in this section is evidence about the RDS instance." The `0001` above is the operator's out-of-band read from RDS; that row is why the value is plausible, not why it is believed.

**⚠️ THIS IS AN EVIDENCE RECORD, NOT A CACHED BELIEF — RE-READ IT BEFORE YOU ADOPT.** This document is not the database. The argument you pass is the database's answer; `0001` written here is a note about what that answer was on 2026-10-14.

- **Re-read the revision from RDS before adopting.** The procedure is `api/alembic/README.md`.
- **If it is no longer `0001`, the NEW value is what `--adopt-current` takes.** Do not pass `0001` because this document says `0001`. A baseline that contradicts the database is not a harmless typo: it is a value every later deploy's fail-closed schema gate is measured against, so it converts one mistyped argument into a host that refuses every deploy until someone reconciles it by hand.
- **This is the exact failure `deploy.sh` was rewritten to eliminate.** `validate_alembic_revision_id()`'s header comment says so directly: the value is not looked up in the checkout because "the entire reason this argument exists is that the answer comes from the database, and the database is frequently not what the tree says". A runbook that hard-codes a revision *without this warning* would reintroduce the very substitute — a value carried around in a file instead of read from its source — through the documentation instead of through the code.
- **Recorded 2026-10-14.** If you are reading this after a migration has been applied, treat the value as unverified until you have re-read it.

**If you know exactly what should be running**, and the record is gone entirely, the `write_record` failure branch of `deploy.sh` gives the other route, for the specific case where verification passed but the record write failed: record by hand from the values the deploy printed, or re-run `deploy.sh` with the same arguments once the directory is writable. The script's own instruction is: "Do NOT re-run this deploy to fix it."

### 7.2 A deploy was interrupted mid-flight

**What you will see:** whatever the terminal showed when it died. The log is authoritative:

```bash
sudo tail -n 200 /var/log/lemondrop-deploy.log
```

**Why the script handles most of this itself.** The `ERR` trap is installed immediately after `capture_state()` and before anything is changed (`trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR` in `deploy.sh`). From that point on, any uncaught failure runs `on_err()`, which restores the previous deployment and exits non-zero. Every *deliberate* abort goes through `fail()`, which does the same.

The block above `restore_previous()` in `deploy.sh` records why that matters, and it is a bug that actually happened: "it is what happened the first time this was run. Verification failed, the script printed 'Rolling back', and then exited 3 having rolled nothing back and left `.env` pinned to an image that was not serving." The `ERR` trap does not catch `exit`, which is why `fail` exists.

**What the trap cannot cover:** `SIGKILL`, a power cut, or an OOM kill of the shell. Then no trap runs, and you may be left with `.env` pointing at a digest whose container is not running.

**Recovery.** These files are what the trap would have used, and they are still on disk:

```bash
# 1. What is actually running?
sudo /opt/lemondrop/scripts/verify-deployment.sh

# 2. The rollback tag the deploy took BEFORE it changed anything.
sudo ls -lt /var/lib/lemondrop/env.before-deploy.*  | head
sudo docker images 'lemondrop-api' --format '{{.Repository}}:{{.Tag}}  {{.ID}}  {{.CreatedAt}}'

# 3. Restore .env from the backup the deploy took.
sudo cp /var/lib/lemondrop/env.before-deploy.<XXXXXX> /opt/lemondrop/.env

# 4. Recreate api from the pre-deploy image.
sudo docker tag <pre-deploy-image-id> lemondrop-api
cd /opt/lemondrop
sudo docker compose -p lemondrop up -d --no-build --no-deps --force-recreate api

# 5. Confirm.
sudo /opt/lemondrop/scripts/verify-deployment.sh
```

Step 3 uses `cp`; `env_restore` in the script uses `cat >` so a deliberately-chmod-ed `.env` keeps its mode (`deploy-lib.sh`, `env_restore()`). If `.env` has a non-default mode, use `cat` instead of `cp`.

**The lock is not a problem here.** See §7.3.

### 7.3 The lock is held

**You will see:** exit **4** (`EX_LOCKED`), and in the log `another deployment holds /var/lock/lemondrop-deploy.lock and did not release it within 300s`.

**The premise "held by a dead process" cannot happen, by design.** `acquire_lock()` (in `deploy-lib.sh`) uses `flock(2)` on an open file descriptor, not a PID file. The kernel releases the lock when the descriptor closes — on exit, on `kill -9`, and on power loss, because there is no process left to hold it. The `flock`-versus-PID-file block above `acquire_lock()` in `deploy-lib.sh` explains the choice:

> The classic stale-lock bug is a PID file … That is wrong whenever the two runs cannot see each other's PID namespace … and it is wrong in the specific case that matters here — a host that was power-cycled mid-deploy still has the PID file, and every subsequent deploy then refuses until a human deletes it.

**So there is nothing to clean up. Do not delete the lock file.** It contains no state and its presence on disk, empty and unlocked, is correct (stated in `deploy-lib.sh` beside `acquire_lock()`). Deleting it is at best a no-op and at worst removes the inode a live deploy is holding a lock on.

What you are actually looking at is a **live process that is not making progress**, or a non-writable lock file:

```bash
# Is a deploy actually running right now?
sudo ps -ef | grep -E 'deploy\.sh|rollback\.sh' | grep -v grep

# Who holds the lock file?
sudo fuser -v /var/lock/lemondrop-deploy.lock

# What is the current holder doing? Its log line is the newest:
sudo tail -n 30 /var/log/lemondrop-deploy.log
```

**Wait rather than kill, if you can.** The bound is 300 s by default (`LEMDROP_LOCK_TIMEOUT`), which is deliberate: "a deploy that hangs forever holding the lock is indistinguishable from one that is working" (`deploy-lib.sh`, on `LEMDROP_LOCK_TIMEOUT`). A deploy can legitimately hold the lock for minutes while it waits out a 300 s readiness poll.

If you must break it, confirm there is genuinely no live deploy first — `verify-deployment.sh` does not take the lock and can observe a deploy in progress, which is exactly when you want to look (stated at the head of `verify-deployment.sh`).

**A different exit-4 cause:** the lock file is not writable by your uid. `acquire_lock` probes the open *before* `exec` and logs `the lock file … is not writable by this user (uid N)` (`acquire_lock()` in `deploy-lib.sh`). Run with `sudo`.

### 7.4 A deployment failed verification

**You will see:**

```
VERIFICATION FAILED. Restoring the previous deployment.
FATAL: the new image did not pass verification; it is not being left in place.
```

then either

```
──────────────────── ROLLBACK COMPLETE ─────────────────────
```

or

```
──────────────── ROLLBACK INCOMPLETE ─────────────────
```

Exit code **3**.

**What "verification failed" can mean** — from `verify_stack()` (in `deploy-lib.sh`), which reports *every* failure rather than stopping at the first:

| Message | Meaning |
|---|---|
| `probe grounding: FAIL — document id … is not in …/corpus.json` | The corpus changed. The probe is stale and its result proves nothing. Pick a new probe and update `LEMDROP_PROBE_*` in `deploy-lib.sh` **deliberately**. |
| `probe grounding: CANNOT CHECK — … is not readable here` | `/opt/lemondrop/data/corpus.json` is missing or unreadable. **Do not read a pass as proof** (in `assert_probe_is_grounded()` in `deploy-lib.sh`). |
| `readiness: NEVER 200 … within 300s (last status: NNN)` | The api never became ready. |
| `known-good search: HTTP NNN from POST …/search` | Search failed outright. The first 400 bytes of the response are printed. |
| `known-good search: RANKED WRONG — top result was 'X', expected 'Y'` | **The service is ready and answering 200 to a real search, and serving the wrong document first.** "a total failure for a user and invisible to every other check here" (in `known_good_search()` in `deploy-lib.sh`). |
| `known-good search: NOT ATTEMPTED — the service is not ready` | Both halves report separately; the search is skipped when readiness failed (in `verify_stack()` in `deploy-lib.sh`). |

**If it said `ROLLBACK COMPLETE`:** the previous image is restored, `.env` is restored, and — read this — "The revision record was NOT changed — it still describes the deployment that just failed, which is correct: nothing was deployed" (`restore_previous()` in `deploy.sh`). Confirm:

```bash
sudo /opt/lemondrop/scripts/verify-deployment.sh
```

**If it said `ROLLBACK INCOMPLETE`:** the script has already printed the exact manual command to run, with the tag or image id substituted in. Follow it. The three incomplete sub-cases are:

| Sub-case | What the script prints |
|---|---|
| `.env` restore failed | `rollback: .env RESTORE FAILED. The copy is at <path>` — restore by hand (§7.2 step 3) and re-run `deploy.sh` |
| Pre-deploy image was never tagged (no container was running before) | `no api container was running before this deploy, so there is no previous image to return to. The api service has been left as it is; remove it by hand` |
| The rollback tag is gone from the local image store | `docker tag <pre-deploy-image-id> lemondrop-api:recovered` then recreate — the full command is printed |
| The restored image is up but not serving | `ROLLBACK INCOMPLETE` + `docker compose logs --tail=100 api` + `scripts/verify-deployment.sh`. "This is now a separate incident." |

**Then work out why.** A verification failure is a fact about the image, not about the deploy machinery:

```bash
sudo docker compose -p lemondrop -f /opt/lemondrop/docker-compose.yml logs --tail=200 api
sudo cat /var/log/lemondrop-deploy.log | tail -n 100
```

### 7.5 The host is in an unknown state

Work from the outside in, cheapest and read-only first. **Do not run `deploy.sh` or `rollback.sh` until you know what is running** — `verify-deployment.sh` is the tool for exactly this and mutates nothing.

```
 1. What does the record say?
      sudo cat /var/lib/lemondrop/deployed-revision.env

 2. What is actually running?  (read-only, takes no lock, safe mid-deploy)
      sudo /opt/lemondrop/scripts/verify-deployment.sh

 3. What do the containers say?
      cd /opt/lemondrop
      sudo docker compose -p lemondrop ps
      sudo docker compose -p lemondrop logs --tail=100 api embedder reranker

 4. Is it answering?
      curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 http://127.0.0.1:8000/health/ready

 5. Are the workers still the ones they were?  (they must not change across a deploy)
      sudo docker compose -p lemondrop ps embedder reranker

 6. Resources.  Two failures mimic everything else above.
      sudo free -m     # an OOM kill while loading the reranker is the first suspect
      sudo df -h /     # a full root volume fails in ways that look like every other fault
      sudo dmesg -T | tail -50      # look for oom-kill

 7. Did a boot happen?
      sudo tail -n 100 /var/log/lemondrop-boot.log
      sudo tail -n 100 /var/log/cloud-init-output.log
      sudo last -x | head

 8. Disk for state — a full /var is why a record can be truncated in the first place.
      sudo ls -l /var/lib/lemondrop/
      sudo df -h /var /var/log
```

`infra/compute.tf:576-581` (post-boot diagnostic block) names the same two suspects: `free -m` — "an OOM kill while loading the reranker is the first suspect"; `df -h /` — "a full root volume fails in ways that mimic every other fault."

**Then decide.** If you can name what should be running and you can name a digest, deploy it (§4.3). If you have a record, roll back (§6). If you have neither, restore by hand in the order §7.2 gives.

**A note on accumulating state files.** Each deploy leaves `env.before-deploy.XXXXXX` in `/var/lib/lemondrop` and never removes it — the script needs it for the restore and there is no cleanup step. Each *successful* rollback removes its own `env.before-rollback.XXXXXX` (in `rollback.sh`). They are mode 0600 and root-owned. They are small; they are also copies of a `.env`, so do not world-readable them and do not casually `rm` them before you are certain no restore is pending.

---

## 8. What a failed deployment does — read this before trusting it

Both claims below were checked against the source, not inferred.

### 8.1 It restores the image **AND** `.env`

`restore_previous()`, in `deploy.sh`, does both, in this order:

1. **`.env` first** (`restore_previous()` in `deploy.sh`) — `env_restore "$PREV_ENV_BACKUP" "$LEMDROP_APP_DIR/.env"`, from the full copy `capture_state()` took *before anything read or wrote it*. It is a **full file copy, not a diff and not just the `API_IMAGE` line** (`capture_state()` in `deploy.sh`): "A rollback that restores the image but leaves `.env` pointing at the new digest starts the OLD image and then fails to record or to re-pin on the next deploy, and the resulting state is harder to reason about than either end of it."

2. **Then the image** (`restore_previous()` in `deploy.sh`) — if there is no previous container, it says so and leaves `api` alone. Otherwise it points `API_IMAGE` at the pre-deploy rollback tag and recreates the service.

3. **Then it re-verifies** (`restore_previous()` in `deploy.sh`): "rollback: the previous image is ready and its known-good search passes."

The rollback tag is taken from the **image ID**, not from a name (`capture_state()` in `deploy.sh`; `running_image_id()` in `deploy-lib.sh`): "an immutable local identifier and survives every retagging in the world, which is why the rollback tag is taken from THIS and not from a name."

`restore_previous` is re-entrancy-guarded (`restore_previous()` in `deploy.sh`): it runs compose, and a failure inside it would otherwise re-enter the same function through the same trap.

If the `.env` restore fails, the script says so loudly and names the backup path rather than continuing (`restore_previous()` in `deploy.sh`).

### 8.2 It does not rewrite the record on failure

The record is written at **step 10, after verification has passed** (`deploy.sh`, `── RECORD ──`). There is no earlier write. `deploy.sh`, `── RECORD ──`: "A record written before verification is a record of a deployment that might not work, and the next deploy would use its head as a baseline — so an unverified deploy that poisoned the record would refuse every later one. Recording last is what makes the record trustworthy."

`restore_previous` never calls `write_record` — it only restores `.env` and the image. And on success the script says so explicitly, because that is the surprising part and you should not have to take it on trust (`restore_previous()` in `deploy.sh`): "The revision record was NOT changed — it still describes the deployment that just failed, which is correct: nothing was deployed."

`rollback.sh` likewise never deletes the record and rewrites it only at the very end, after re-verification (head of `rollback.sh`, and its record-rewrite step).

**The one exception, and it is deliberate.** If verification *passed* but the record write itself failed, the deploy is live and unrecorded (the `write_record` failure branch of `deploy.sh`). The script exits 3 with an explicit warning: "THE DEPLOYMENT IS LIVE AND UNRECORDED … Do NOT re-run this deploy to fix it … Until then, scripts/rollback.sh will refuse." That is a different situation from a failed deployment, and it is the one case where you must hand-intervene (§7.1).

---

## 9. ⚠️ The boot script, reboots, and the hazard nobody has closed

This section is about **boot**, and it is the reason the deploy tooling exists in the shape it does.

### 9.1 What actually runs on the host is `infra/compute.tf`, not `scripts/boot.sh`

**The EC2 instance executes the boot script inlined as cloud-init `user_data` in `infra/compute.tf:287-587`.** `scripts/boot.sh` is a **parallel copy that EC2 does not execute**. Nothing in `infra/` references `scripts/boot.sh`; it exists as the editable, lintable, diffable copy, per `docs/boot-script.md:463`.

**The two copies have already drifted, by exactly one line:**

```
$ sed 's/^    //' <(sed -n '288,586p' infra/compute.tf) | diff -u - scripts/boot.sh
-# script was measured at 24,994. Measure any addition against that ceiling.
+# script was measured at 15,068. Measure any addition against that ceiling.
```

That drift is **deliberate and documented** — `docs/boot-script.md:478-508` explains that correcting the stale number inside the heredoc changed Terraform's hash and armed the replacement of a live instance, so the correction was reverted and the true figures were recorded in documentation instead. The current measurements (`docs/boot-script.md:473-478`):

| | bytes |
|---|---|
| Rendered heredoc (4-space indent, what AWS counts) | **16,180** |
| De-indented `scripts/boot.sh` | 15,068 |
| EC2 ceiling | 16,384 |
| **Headroom** | **204** |

**So: when you need to know what the host does at boot, read `infra/compute.tf` and cite its line numbers. Do not read `scripts/boot.sh` and assume EC2 will run it.** The two are independent, and they are independent because making them dependent would mean editing a hash input (below).

### 9.2 ⚠️ The inline script is effectively frozen

`infra/compute.tf:185`:

```hcl
user_data_replace_on_change = true
```

**Any edit to that inline script — a single byte, including a comment — makes the next `terraform apply` destroy and replace the EC2 instance.** The comment at `infra/compute.tf:180-184` is explicit that this is the intended behaviour, not an accident: "Forcing replacement makes the plan say what is actually true: the script is part of the host's identity."

What replacement destroys:

- the **root volume** — `delete_on_termination` is the default and is stated (`compute.tf:199-201`)
- the **model weights** — ~340 MB of GGUF re-downloaded from HuggingFace at boot (`compute.tf`, step 5)
- the **checkout** at `/opt/lemondrop`, including the deploy tooling a transfer put there
- the `.env` boot regenerates, and with it the digest a deploy pinned (§9.4)

`docs/boot-script.md:499-506` records that this has already happened once: commit `f13e4c0` corrected a comment from 24,994 to 15,068, which "made the number accurate and, in the same commit, armed the replacement of a working instance. The correction was reverted."

**Treat `compute.tf:287-587` as frozen.** If you believe it needs a change, say so out loud and get the operator to accept the instance replacement before touching it (`docs/boot-script.md:510-516`).

### 9.3 ⚠️ What `docker compose up` does at boot — and why it can serve an unversioned image

The authoritative lines, `infra/compute.tf:552-554`:

```
552:    docker compose pull embedder reranker 2>&1 | tee -a "$LOG_FILE" \
553:      || log "WARNING: 'docker compose pull' failed; continuing with local build/cache"
554:    docker compose up -d --remove-orphans 2>&1 | tee -a "$LOG_FILE"
```

Read those three lines carefully. Four consequences follow, and **none of them raises an error**:

1. **The `api` service is never pulled.** Only `embedder` and `reranker` are named. The comment at `compute.tf:545-549` says the naming is on purpose — "a bare `docker compose pull` also pulls the api, whose image `lemondrop-api` is built here and exists in no registry."

2. **There is no `--build` flag.** Line 554 is `up -d --remove-orphans`, full stop.

3. **Therefore compose reuses an existing local image when one is present.** Without `--build`, compose starts the image it already has.

4. ⚠️ **THIS ONE USED TO READ "therefore, on a clean instance with no local image, compose *builds* it … because `docker-compose.yml:311` still has `build: ./api`." That is no longer true.** `build:` was **removed** in commit `84c0c36`, together with the `.env.example` change it was coupled to. On a clean instance with no local image, compose now **pulls the digest** named on the `image:` line — it does not build one. §9.6 carries the removal reasoning; the `docker-compose.yml` line numbers quoted in it are historical.

**So this section's conclusion has narrowed, and the narrowing is the point of the work.** *Before* `84c0c36`, both a first boot and a reboot could end with an unversioned, locally-built api serving production traffic, with no error anywhere. *After* it, a clean instance ends up on the pinned digest instead. Two things remain true and are **not** fixed by the removal:

- **A host that already has a stale local image still runs it.** Without `--build`, compose prefers what it already has. Removing `build:` stops a *build*; it does not stop a *stale local tag* from being what compose picks.
- **A boot that does run the bootstrap still reverts the `.env` pin** (§9.4), so the digest compose falls back to is the one `.env.example` ships, not the one a deploy wrote.

The failure `verify-deployment.sh` exists to make visible is unchanged, and is the failure this section was written about: "Nothing is corrupted, no error is raised anywhere, and the stack is healthy — it is simply not running what the record says it is. The DIVERGENCE line below is the only thing that makes that visible." **Run it after every event that could have run the bootstrap** — §9.5.1 says which events those are, and the honest answer is narrower than "every reboot."


And note that line 553 turns a **failed pull of the worker images** into a `WARNING:` and continues. So even a registry outage produces a warning, not a stop. If you see `WARNING: 'docker compose pull' failed; continuing with local build/cache` in the boot log, the workers came from cache and their provenance is unestablished.

### 9.4 An **instance replacement** reverts the digest pin — by design

⚠️ **The heading of this section used to say "A reboot reverts the digest pin". §9.5.1 falsified that.** By direct observation on the host, **an ordinary reboot does not re-execute `user_data` at all**, so it does not run boot step 4 and does not revert anything. The event that reverts the pin is a **Terraform replacement provisioning a new instance** (§9.2, §9.5.1). `.env.example` now says the same thing in its own words: "⚠️ AN INSTANCE REPLACEMENT REVERTS IT. AN ORDINARY REBOOT DOES NOT."

Boot step 4 is `cp .env.example .env`, **unconditional, whenever it runs** (`infra/compute.tf` step 4; the parallel copy in `scripts/boot.sh`). The rationale at `compute.tf` and in `.env.example` is that `.env` is machine-owned and `API_HOST_PORT` must agree with `local.app_port` — "An operator-edited `.env` drifts out of agreement and produces a stack that is healthy and unreachable, which is the worst combination of properties."

Whatever `deploy.sh` wrote into `.env` — the digest pin — **is discarded when that step runs**. Note what `.env.example` ships now: **not** the bare name `lemondrop-api`. It ships the **same digest-pinned reference** as the compose default (`.env.example`, the `API_IMAGE=` line). So an instance replacement no longer reverts the stack to M3 behaviour and a locally-built image; it reverts it to **whatever digest was current when `.env.example` was last committed**. That is a different and much smaller hazard, and it is exactly the failure `DIVERGENCE` exists to catch.

`deploy.sh` is blunt about the durability of the pin across a boot: "THE DIGEST PIN IN `.env` IS NOT DURABLE ACROSS A BOOT, and pretending otherwise would be the most damaging claim this file could make." What survives any boot event is (a) the record in `/var/lib/lemondrop`, which boot cannot touch, and (b) `scripts/verify-deployment.sh`, whose divergence check turns "something quietly reverted us" from an invisible event into a reported one.

**Operational consequence: run `verify-deployment.sh` after every instance replacement — and after any event you are unsure about — before you believe anything.** Read §9.5.1's limits before generalising "reboots are safe": n = 1, stop/start was never tested, and a manual re-run of the boot script would be indistinguishable from a boot.

### 9.5 ⚠️ Whether a reboot re-runs `user_data` at all is NOT CONFIRMED

**ANSWERED — see §9.5.1 below. This question was asked here and has since been answered by observation. The text below is left exactly as it was written, so you can see what was assumed at the time and correct it if the observation was wrong. Read §9.5.1 as the current status.**

**I am not going to tell you whether it does, because this repository does not establish it.**

What is established:

- `infra/compute.tf` contains **no cloud-init override**. There is no `cloud_final_modules`, no `runcmd`, no `bootcmd`, no `/etc/cloud/cloud.cfg.d` write anywhere in `infra/` — I grepped for all of them and found none. So the only thing that could re-run the boot script is cloud-init re-executing `user_data` itself.
- The repository's design assumes it *does*. `infra/compute.tf:300` (inside the heredoc): "This re-runs often (user_data_replace_on_change, by hand while debugging)." `deploy.sh`'s `DELIVERY` block and `verify-deployment.sh` both reason as though a boot re-runs it.
- `.env.example` and `deploy.sh` describe the reboot-reverts-the-pin behaviour as certain. (`deploy.sh`'s `DELIVERY`/durability comment: "THE DIGEST PIN IN `.env` IS NOT DURABLE ACROSS A BOOT".) **Both have since been corrected** — `.env.example` now says "AN INSTANCE REPLACEMENT REVERTS IT. AN ORDINARY REBOOT DOES NOT", and §9.5.1 is the observation that forced it.

**What is not established:** whether a *stop/start* or *reboot* of a running instance actually causes cloud-init on Amazon Linux 2023 to re-run the `user_data` script. **That has not been confirmed on this host.** Confirming it requires exactly one read-only host inspection — reading the boot log's timestamps against the instance's boot history — and **that inspection has not been performed.** I am not going to infer it in either direction, because the two answers have opposite operational consequences and guessing is how a host ends up serving an unversioned build after someone decided it was safe to reboot.

**Do this once, before you rely on either story:**

```bash
# On the host:
sudo stat -c '%y %n' /var/log/lemondrop-boot.log
sudo head -5 /var/log/lemondrop-boot.log
# From your workstation, correlate with the instance's own boot history:
aws ec2 describe-instance-status --instance-ids <id> --region eu-west-1
```

Record what you find in `docs/verification-milestone-3.md` or a successor. Until then, treat §9.4 as the conservative case.

### 9.5.1 ✅ RESOLVED BY OBSERVATION — an ordinary reboot does NOT re-run `user_data`

**This is what was actually observed, not what was inferred.** It supersedes the
"NOT CONFIRMED" status in §9.5. The method asked for in §9.5 was performed:
read-only inspection of the instance's own logs, boot history, and cloud-init
semaphores. The conclusion is the reassuring half of the two possibilities — and
the reassuring half is the one that matters less than it first appears.

**The reboot itself.**

| Fact | Value |
| --- | --- |
| SSM command | `53394a4f-75a5-40e2-b007-7b7274384a9a` |
| Status / ResponseCode | Success / 0 |
| Reboots observed | **exactly one**, on **2026-10-13 at 18:49** |

**The boot log did not move.** `/var/log/lemondrop-boot.log` was **not modified**
by that reboot: mtime **2026-10-12 19:53:53**, still containing its **6**
`step N/6` markers. A reboot that had re-executed `user_data` would have appended
a fresh set of markers and reset that mtime. It did neither.

**The cloud-init per-instance semaphores were not refreshed.** All four —
`config_scripts_user`, `config_scripts_per_instance`, `config_runcmd`,
`config_write_files` — are dated **2026-10-12 19:50**, i.e. created at first
boot and never touched since. `config_scripts_user` is the semaphore that
specifically gates `user_data`, and it is the oldest of the four.

**The history is complete, so the absence above is real and not truncation.**
`wtmp` begins at the first boot and is not rotated — the journal shows
**exactly 2 boots**. The same instance id and the same kernel appear across both,
so **no instance replacement has occurred**; otherwise the second entry would be
a different host and the log would start later.

**cloud-init itself DID run on 2026-10-13.** Its own log records `status: done`
at **18:49:11**. This is the trap worth naming explicitly, because it is the
easiest thing in this document to misread: **cloud-init running is not
`user_data` re-running.** On AL2023 the per-instance modules re-execute and
re-evaluate their conditions, decide there is nothing to do, and exit — while
the cloud-init process itself clearly did start and complete. Any future check
that looks only at "did cloud-init run today" will report the wrong answer.

**CONCLUSION — and it is narrower than "reboots are safe".**

> An ordinary **reboot** does **not** re-execute `user_data`.
>
> A **Terraform replacement that provisions a NEW instance** runs the bootstrap
> **unconditionally at first boot** — new instance, empty semaphores, first-boot
> cloud-init. That path *would* hit `docker compose up -d --remove-orphans` with
> no `--build` and no local image, which, while `build: ./api` was present in
> `docker-compose.yml`, meant an **unversioned image built from whatever the
> clone contained** (§9.3, §9.6).
>
> So removing `build:` hardens the **replacement** path. It does **not** harden
> the reboot path, because the reboot path was never the one executing the
> bootstrap.

**LIMITS OF THIS EVIDENCE — read them before generalising.**

- **n = 1.** One reboot, one observation. This is sufficient to refute the claim
  that a reboot re-runs `user_data`, because the mechanism was checked directly
  (semaphore dates and log mtime), but it is **not** sufficient to establish that
  *no* sequence of reboots ever does. A second reboot post-dating the first is
  not evidence either way, since the semaphores would be equally untouched.
- **A stop/start was not tested.** Only `reboot` was observed. They are
  different EC2 operations and this evidence says nothing about start/stop.
- **Whether an operator has ever manually re-run the boot script is UNKNOWN.**
  No attempt was made to establish it, and a manual run would leave a signature
  this check cannot distinguish from a first boot.
- **The per-instance semaphore DIRECTORY was not enumerated** — only the four
  semaphores named above were read. A different module directory existing
  unexamined is not excluded by this evidence.

**⚠️ ONE PROBE WAS UNINFORMATIVE AND MUST NOT BE READ AS A COUNT.** A probe for
the legacy `running boot-config` log marker returned **0 matches**. That is not
evidence that the boot never ran: **AL2023 does not emit that string.** The
marker belongs to a different distribution's boot-config path. A zero from that
probe is a property of the string, not of the system, and quoting it as an
execution count would be a straight misreading. The mtime and semaphore evidence
above is what carries the conclusion; this probe carries nothing.

### 9.6 The `build:` removal dependency

**STATUS UPDATE — this section described a dependency that has now been satisfied, in a single change rather than two.** `build:` **has been removed** from `docker-compose.yml`, and `.env.example` **now ships the digest** on its `API_IMAGE` line. The two edits were made together, exactly as this section insisted they must be, so the `docker.io/library/lemondrop-api` substitution described below is closed rather than merely argued against. See §9.5.1 for why this hardens the *replacement* path rather than the reboot path. The reasoning below is left as written, because the coupling it describes is real and the reasoning is still what justifies the ordering.

⚠️ **The `docker-compose.yml` line numbers quoted in this section are now STALE** — the removal of `build:` added roughly 95 lines above them. Verified current anchors: the `image:` line quoted below as `:369` is now **`:436`**; the "fail closed" block quoted as `:325-347` is now **`:384-407`**; the "untouched" claim quoted at `:357-360` is now **`:436-439`**. They were not renumbered in place here, deliberately: renumbering is a mechanical pass that belongs with the commit that lands this, not inside an observation note. Treat the line numbers below as historical and the prose as current.

⚠️ **The historical quote at `:357-360` is also now the opposite of the file's contents.** It reads "`build: ./api` above is untouched, and stays that way for now." No such line exists. It is quoted here because this section is a record of what the coupling *was*, and because that history is what justifies the two-edits-one-change ordering; it is not a statement about the file today. **The two `docker-compose.yml` anchors above are the verified current ones — trust those, not the quoted prose.**

`docker-compose.yml:357-360`: "`build: ./api` above is untouched, and stays that way for now: removing it is gated on proving the deploy path behaves, which is Stage 5 work that has not been exercised against a real host yet."

**Do not remove `build:` on its own.** The two edits are one bug apart, and `docker-compose.yml:325-347` explains why in detail:

- With `build:` present and `API_IMAGE` unset, compose resolves `${API_IMAGE:-…}`. Before Stage 5 the default was the bare name `lemondrop-api`, which is not qualified by any registry — so if `API_IMAGE` were ever unset *and* `build:` were removed, compose would resolve it as `docker.io/library/lemondrop-api`: **a public Docker Hub image this project does not control, does not publish, and has never tested.** "That is not a hypothetical: the removal of `build:` is the very next change in this milestone, and the two edits are one commit apart from being one bug apart."

The default is now the digest-pinned GHCR reference, which closes that hole. `.env.example`'s `API_IMAGE` line and the removal of `build:` were coupled for a mechanical reason recorded in `.env.example`: **docker cannot tag a locally built image with a digest reference**, so a template shipping the bare name had to change in the same commit as the removal. `.env.example` now ships **the same digest** as the compose default, and says so: "there is one reachable production value, and it is the right one."

⚠️ **An earlier draft of this paragraph claimed `.env.example:102` "still ships `API_IMAGE=lemondrop-api`" and quoted `.env.example:80-82` as saying the digest "becomes the right value for THIS line at exactly one future moment". Both are false.** Neither line number resolves to either statement any more, and the string "exactly one future moment" **no longer occurs anywhere in `.env.example`** (`grep` returns nothing). That moment has passed; it was commit `84c0c36`.

If `build:` is removed and `.env` still said `API_IMAGE=lemondrop-api`, boot step 4 would regenerate `.env` with that value and line 554 would try to **pull `docker.io/library/lemondrop-api`** — the uncontrolled substitution, in the other direction. That is no longer reachable, because `.env.example` ships the digest. This is precisely why the two edits had to be one change (`compute.tf:552-554`, §9.3): the removal alone would have opened the hole in this direction instead of closing it in the other.

---

## 10. Known limitations — what is NOT verified

This codebase's value is that its documentation is trustworthy. That means the limitations have to be as prominent as the features.

**1. These three scripts have never been executed against a host with a real Docker daemon.** **No test file invokes `deploy.sh`, `rollback.sh` or `verify-deployment.sh`**, and no workflow in `.github/workflows/` runs them. Every `docker pull`, `docker tag`, `docker compose up`, `docker inspect` and `docker manifest inspect` call in these paths is therefore **unexercised in CI and unexercised on a live host**. The control flow, the argument handling, the record format and the HTTP probes have been read, and the logic is defensible — but the destructive paths are unproven. **The first deploy onto a real host is an experiment. Do it on a throwaway host.**

    **⚠️ NARROWED BY STAGE 6, TWICE OVER. This item's evidence sentence was "**no test file references** `deploy.sh`, `rollback.sh`, `verify-deployment.sh` or `deploy-lib.sh`". Both halves of that are now wrong, in different ways, so it is restated above and the corrections are recorded here rather than left to rot.**

    - **THE WORDS NOW APPEAR; THE SCRIPTS ARE STILL NOT INVOKED.** `scripts/test-diagnose.sh` greps `diagnose.sh`'s source for the strings `deploy.sh` / `rollback.sh` / `verify-deployment.sh` — an assertion that it invokes none of them — and both diagnostics' reports *name* `verify-deployment.sh` in the line that says the comparison is not performed. So `grep` for those filenames across tracked files now returns hits. What is unchanged, and what the item actually asserts, is that **nothing runs them**.
    - **`deploy-lib.sh` IS NOW EXERCISED, PARTIALLY.** `scripts/diagnose.sh` sources it (the same three lines `verify-deployment.sh` uses) and the `tier-classification` job in `tests.yml` runs that on every pull request, so its `LEMDROP_*` defaults, its `readonly EX_*` constants and its `log`/`say`/`die` definitions are now **loaded** in CI. The three functions `diagnose.sh` actually *calls* — `say`, `api_base_url`, and `env_get` through `api_base_url` — **execute** too.
    - **EVERYTHING ELSE IN IT IS STILL UNEXERCISED, and that is the whole point of the item.** `deploy.sh`, `rollback.sh` and `verify-deployment.sh` are untouched by CI. And no *function body* in `deploy-lib.sh` that touches Docker, the lock, the record or the network has been called: not `known_good_search`, `verify_stack`, `wait_for_ready`, `restore_previous`, `env_restore`, `api_container_id` or `record_is_valid`. Sourcing a file defines functions; it does not run them.
    - **NOT CLAIMED BY STAGE 6:** none of it exercises a Docker daemon, a real `/health/ready`, or Windows PowerShell 5.1. The `diagnose.sh` tests substitute a stub `curl` and a stub `docker` on `PATH`; the `diagnose.ps1` tests substitute fixture files through `LEMDROP_DIAGNOSE_HTTP_STUB`. The stubs make the scripts' *control flow* testable and nothing more — which is why this item survives Stage 6 rather than being withdrawn by it. `scripts/diagnose.ps1` is **executed on PowerShell 7.4.6 and written for 5.1; 5.1 cannot run on Linux and was not executed** — the header of that file says so, and nothing in this document should be read as having verified it.

**2. Every destructive path is a code path nobody has watched fail.** Specifically unproven: that `restore_previous` actually restores a working service when compose fails mid-way; that `env_restore` succeeds when `.env` has been chmod-ed; that `flock` behaves as intended under SSM `SendCommand`'s process model; that the ERR trap fires on every failure it is supposed to.

**3. ~~The schema-head second argument is a limitation, not a design choice.~~ RESOLVED.** This item is **withdrawn**, not merely softened: `deploy.sh` does **not** require the source git revision on every invocation any more. Published images carry `org.opencontainers.image.revision` and `org.lemondrop.alembic-head` (commit `05d37bb`), `deploy-lib.sh` reads them via `image_label()` and `resolve_deploy_facts()`, and `deploy.sh <digest>` alone is sufficient on a labelled image (§4.4). The 318-line `release.yml` change this item called "in flight" and "not yet self-consistent" is **committed**.

    **What replaces the limitation, and it is narrower than you might hope.** The second argument is still worth passing, because supplying it on a labelled image adds an early pre-pull schema gate and a provenance conflict check that refuses when the argument and the label disagree (§4.4). It is still **required** on an unlabelled image — and one such image is still pinned in this repository's compose default. So a mistyped commit SHA still produces a refusal, not a wrong deploy; that part never changed.

**4. The `ALB idle timeout (60 s) vs. worst-case `/search` (~240 s)` mismatch is unfixed.** `docs/verification-milestone-3.md` §10.8 tabulates it; §12.4 item 4 records it as "an unaddressed known configuration defect" and "STILL OUTSTANDING". §10.8 also records that raising it was *deliberately deferred* pending an EC2 latency measurement that has still not been taken. The single 15.55 s ALB observation (§12.1 row 12) is not a distribution.

**5. ~~Whether a reboot re-runs `user_data` is unconfirmed.~~ ANSWERED, with limits that are themselves unconfirmed.** §9.5.1 records the observation: an ordinary **reboot does not re-execute `user_data`** (SSM command `53394a4f-75a5-40e2-b007-7b7274384a9a`, boot log mtime and all four cloud-init semaphores unchanged). What is **still** unconfirmed: n = 1; a **stop/start was never tested**; whether an operator ever **manually re-ran** the boot script is unknown and would be indistinguishable from a boot; and the per-instance semaphore **directory was not enumerated**. The absence of a `running boot-config` log marker is **not** a count — AL2023 does not emit that string. Read §9.5.1 before relying on "reboots are safe".

**6. ~~`build:` is still in `docker-compose.yml`, and its removal is gated on this work.~~ DONE.** `build:` was **removed** in commit `84c0c36`, together with the `.env.example` `API_IMAGE` change it was coupled to. §9.6 records the status and the reasoning; §9.3 records what the removal did and did not fix. **What the removal did not fix:** a host that already holds a stale local image under the right name still runs it, since `docker compose up` at boot has no `--build` and prefers what it has (§9.3 items 2–4).

**7. ~~Anonymous pullability of the GHCR package is contradicted across the repository and is unresolved.~~ ANSWERED.** The package **is** anonymously readable, and the contradiction that made this an open question was a category error. **This item is kept in place, marked answered, rather than deleted**, so that the change is visible — read the struck text above as the question as it stood, and everything below as what settled it.

    **What was observed**, against digest `sha256:d4aac49dc28027818950dfcab9ab99c40bd0662a536060958c24b60a05c37867`:

    - An unauthenticated manifest `GET` returned `HTTP/2 401` with `www-authenticate: Bearer realm="https://ghcr.io/token", service="ghcr.io", scope="repository:fvitorino00/lemondrop-api:pull"`. **That 401 is not evidence of privacy.** GHCR returns that challenge for every package, public or private, and treating it as a verdict would be a false negative.
    - Following the challenge anonymously returned `HTTP/2 200`, with `docker-content-digest` matching the digest requested, character for character.
    - A `docker pull` with `DOCKER_CONFIG` pointed at a verified-empty directory exited **0**, and that directory was **still empty afterwards** — no credential was written or consulted, so the pull was anonymous **by construction**, not by assumption.

    **Package visibility is a setting separate from repository visibility.** A public repository does not imply a public package. The `docs/verification.md:148` (private) versus `docs/m4-plan.md:780` (public) disagreement is about *repository* visibility and does not bear on package readability; it was never the question this item was asking.

    **What this item does and does not establish.** Readability was observed **at the time of verification**, against that digest. Later releases have published newer digests, so the evidence is about package readability and is **not** a claim that this digest is current (§3.2; item 8). It is **not** a claim of permanent availability, **not** immunity to a visibility change, and **no** future-access guarantee: the package setting can be changed by anyone with access to it, at any time, without this document noticing. **§3.3's check is what an operator runs before a deploy — not this paragraph.**

**8. The digests written down are examples, and they go stale on every merge.** §3.2. `docker-compose.yml` and `.env.example` each name a digest-pinned reference — the same one — and neither records the commit, the CI run, or the verification that produced it beyond what the release job's own summary prints. **They are now committed, so this is no longer an "uncommitted change" problem; it is a staleness problem.** Every merge to `main` publishes a new digest, so the committed values are stale by construction and will stay that way. **Take the digest from the release run's job summary (§3.3), never from a file in this repository.** The committed values exist so boot has a *safe* default, not so an operator has an *approved* one.

**9. ~~The deploy tooling is uncommitted.~~ RESOLVED.** §0.4. `scripts/deploy.sh`, `scripts/rollback.sh`, `scripts/verify-deployment.sh` and `scripts/lib/deploy-lib.sh` are **committed and tracked**, as are the `docker-compose.yml` and `.env.example` digest pins and the 321-line label addition to `.github/workflows/release.yml`. `scripts/` is clean in `git status`.

    **The residual risk is the host, not the repository.** `git pull --ff-only` on `/opt/lemondrop` can only deliver the tooling if the checkout is current **and** someone has pulled — and §9.5.1 establishes that an ordinary reboot does **not** pull. So a host can be running scripts that predate the tooling entirely, and that is invisible from the repository. **Confirm the host's copy directly** (§2.2, §4.4) rather than inferring it from the fact that the files are committed.

    This item deliberately states **no commit SHA**, deliberately. Naming `HEAD` here made the sentence wrong the moment it was written — which is what the deleted "the committed state of this repository is `8cddfe8`" did. **Read `git rev-parse HEAD` on the day you need it.**

**10. Whether the boot step 3 clone works is unresolved.** §2.3. `docs/boot-script.md:205-207` records it as failing on boot against a private repository; `docs/m4-plan.md:780` says the repository is public; §12 records a working deployed stack. Check the host; do not assume.

**11. `README.md` and `RUNBOOK.md` contain Milestone 2 values that Milestone 3 superseded.** `RUNBOOK.md:53` still shows `-var app_instance_type=t3.micro`, while `docs/verification-milestone-3.md` §12.1 row 1 records the host running **`t3.small`**. Treat `RUNBOOK.md` as accurate for AWS access mechanics (which are what it is for) and `docs/verification-milestone-3.md` as authoritative for instance facts.

**12. No load, concurrency, or soak testing exists.** `docs/verification-milestone-3.md` §12.5 row 7: "No load profile, no concurrency measurement, no soak; CPU credits unmeasured at every size; the 15.55s observation is not a margin measurement." §12.5 row 7 is the qualifier row, and it carries these straight into §12.4 **items 2 and 3** — "Sustained and concurrent load are untested" and "CPU credit exhaustion on the `t3` family is UNMEASURED". ⚠️ **An earlier draft of this item cited "§12.4 item 7" for that quote. That names the wrong thing:** §12.4 item 7 is the negative control, and it is **RESOLVED**. `t3` instances deplete CPU credits under sustained cross-encoder scoring, and the failure mode is degraded latency rather than an error.

**13. The corpus is synthetic** (§12.4 item 6) and the probe is anchored to one document in it. `assert_probe_is_grounded` catches the corpus changing underneath the probe — that is all it does.

**14. The 204-byte `user_data` headroom** (§9.1) means the boot script is close to EC2's 16,384-byte ceiling. `docs/boot-script.md:520-528` gives the exact measurement command. Anything added to the heredoc must be measured, not eyeballed.

---

## 11. Pre-flight checklist

Tick every box before touching anything. Each line is a fact you observed, not a thing you intend to check.

### Environment and identity

- [ ] AWS profile and region confirmed (`lemondrop`, `eu-west-1`).
- [ ] Instance id confirmed **current** — `terraform output ec2_instance_id` or `aws ec2 describe-instances`, not the value quoted in `RUNBOOK.md`.
- [ ] SSM reachability confirmed with a read-only command: `aws ssm get-command-invocation` on a harmless `SendCommand`.
- [ ] You know you are using `sudo`, and you know why (state dir, lock and record are root-owned).

### Tooling on the host

- [ ] All four files present under `/opt/lemondrop/scripts/` (§2.2's `ls -l` returned no errors).
- [ ] They are this project's version — the `PREVIOUS_IMAGE_DIGEST` grep in `rollback.sh` hits.
- [ ] `/opt/lemondrop` is a git checkout: `git -C /opt/lemondrop rev-parse --git-dir` succeeds.
- [ ] Your target commit is present in that checkout: `git -C /opt/lemondrop cat-file -e <sha>^{commit}`.
- [ ] `/opt/lemondrop/data/corpus.json` is readable — otherwise the probe grounding check reports `CANNOT CHECK` and a pass proves nothing.

### What you are about to deploy

- [ ] The digest came from the **publish job's summary or log** for your commit, not from a tag and not from this document (§3.3).
- [ ] You re-read the digest back and it matches, character for character, 64 lowercase hex.
- [ ] `docker manifest inspect <ref>` **succeeded** from a machine with no registry credentials — anonymous pullability confirmed **for this digest, today**. §10 item 7 records readability observed at verification time against an older digest; it is history, not a standing guarantee, and the package setting can change (§3.3).
- [ ] You looked at what the commit contains. You did not take the digest on trust.

### State before the change

- [ ] `verify-deployment.sh` has been run and its output read. You know whether it says `AGREE`, `DIVERGENCE`, or "no usable record".
- [ ] You have copied the current record somewhere off the host: `sudo cp /var/lib/lemondrop/deployed-revision.env /root/deployed-revision.before.$(date -u +%Y%m%dT%H%M%SZ)`.
- [ ] You have a rollback target: `PREVIOUS_IMAGE_DIGEST` is set, **or** `ROLLBACK_TAG` names an image present in `docker images`.
- [ ] You have read the recorded `ALEMBIC_HEAD`, and you know the head of your target revision.
- [ ] No deploy or rollback is already running: `ps -ef | grep -E 'deploy\.sh|rollback\.sh'`.
- [ ] Free disk and memory are adequate: `free -m`, `df -h /`.

### Scope and judgement

- [ ] This is a deploy, not an investigation, or not a rollback — §4.1's table, decided **now**.
- [ ] Nobody is relying on a migration being backward compatible without having said so.
- [ ] You are not about to edit anything in `infra/compute.tf` (§9.2 — it replaces the instance).
- [ ] You are not about to change `build:` or the `image:` default in `docker-compose.yml` without changing `.env.example`'s `API_IMAGE` in the same commit — the two are one bug apart (§9.6).
- [ ] You know who to tell, and you will tell them, regardless of the outcome.

### After

- [ ] `verify-deployment.sh` reports `AGREE` and no problems; exit 0.
- [ ] The embedder and reranker container ids are **unchanged** — only `api` is ever recreated. Confirm from `docker compose ps embedder reranker` (its `── do they agree? ──` output prints them).
- [ ] `cat /var/lib/lemondrop/deployed-revision.env` shows the digest you deployed, `VERIFICATION=PASS`, and the timestamp you expect.
- [ ] The known-good search passed **from the host against `localhost:8000`**, not through the ALB (§5.1).
- [ ] ALB reachability checked separately, and the result interpreted for what it is (§5.3).
- [ ] If you rolled back: the record was updated, not deleted, and a second rollback is now impossible by design (§6.3).

---

## Appendix A — one-line reference

```bash
# What is running?
sudo /opt/lemondrop/scripts/verify-deployment.sh

# Read-only diagnostic, on the host: containers + health + a timestamped report
# in /var/lib/lemondrop/diagnostics/. Mutates nothing; runs no known-good search.
sudo /opt/lemondrop/scripts/diagnose.sh [--base-url URL] [--report-dir DIR]

# Deploy (one argument is enough on a labelled image; the 2nd cross-checks it — §4.4)
sudo /opt/lemondrop/scripts/deploy.sh <registry>/<repo>@sha256:<64-hex> [<40-char-sha>]

# First time on an M3 host: record what is running, change nothing.
# The revision is MANDATORY — no default, no fallback. 0001 is this host's
# database-verified head (§7.1); on another host it is <db-verified-alembic-revision>,
# and you must read it from that host's RDS. Re-read it; do not trust this line.
sudo /opt/lemondrop/scripts/deploy.sh --adopt-current 0001

# Roll back (no arguments)
sudo /opt/lemondrop/scripts/rollback.sh

# The record
sudo cat /var/lib/lemondrop/deployed-revision.env
sudo grep '^IMAGE_DIGEST=\|^ALEMBIC_HEAD=\|^PREVIOUS_IMAGE_DIGEST=' /var/lib/lemondrop/deployed-revision.env

# Read-only diagnostic, on a WINDOWS workstation. HTTP only — no Docker, because
# the stack is not there. Writes to %LOCALAPPDATA%\lemondrop\diagnostics\.
# §10 item 1: executed on PowerShell 7.4.6; written for 5.1; 5.1 NOT verified.
powershell -NoProfile -File C:\path\to\lemondrop\scripts\diagnose.ps1 [-BaseUrl URL] [-ReportDir DIR]

# Logs
sudo tail -n 200 /var/log/lemondrop-deploy.log
sudo tail -n 100 /var/log/lemondrop-boot.log
sudo tail -n 100 /var/log/cloud-init-output.log

# Containers
cd /opt/lemondrop
sudo docker compose -p lemondrop ps
sudo docker compose -p lemondrop logs --tail=100 api

# Readiness and the known-good search, ON THE HOST
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 http://127.0.0.1:8000/health/ready
curl -sS -X POST http://127.0.0.1:8000/search -H 'content-type: application/json' \
  -d '{"collection":"it-support","query":"recover a file a user deleted by mistake from the Recycle Bin"}'

# Boot-time behaviour lives HERE, not in scripts/boot.sh
sed -n '552,554p' infra/compute.tf
sed -n '185,185p' infra/compute.tf      # user_data_replace_on_change = true

# Is the source revision fetchable on the host?
sudo git -C /opt/lemondrop cat-file -e <40-char-sha>^{commit} || \
  sudo git -C /opt/lemondrop fetch --depth 1 origin <40-char-sha>
```

## Appendix B — where everything is documented

| Question | File |
|---|---|
| What the boot script does and why | `docs/boot-script.md`; the script itself is `infra/compute.tf:287-587` |
| What was verified on AWS, and what was not | `docs/verification-milestone-3.md` (§12 is the cloud acceptance record) |
| The live search this runbook's probe is anchored to | `docs/verification-milestone-3.md` §8.2 |
| The ALB timeout defect | `docs/verification-milestone-3.md` §10.8, §12.4 item 4 |
| Why digest and never tag | `docs/verification-milestone-3.md` §11.2; `release.yml`, under `── WHAT THE SHA TAG IS, AND WHAT IT IS NOT ──` |
| Why migrations cannot run from EC2 | `infra/iam.tf`; `api/alembic/README.md` (the out-of-band procedure) |
| The milestone this work belongs to | `docs/m4-plan.md` (Stage 5; §4.4 for the rollback design) |
| Infrastructure access mechanics | `RUNBOOK.md` |
| Milestone 1 and 2 verification records | `docs/verification.md`, `docs/verification-milestone-2.md` |
| Local development | `README.md` |