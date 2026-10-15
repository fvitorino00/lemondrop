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

> ⚠️ **The two `docs/` paths in that listing have never been committed, and nothing tracked may cite them.**
>
> `docs/m3-study-guide/` and `docs/m4-plan.md` are **untracked** — `git status` reports them as `??`, and a clean clone of this repository does not contain either. **The listing above is a historical capture and it is stale in two ways**: this document was itself untracked when it was taken, and those two paths are still untracked now. It is kept because §0.4 is about what the capture proved at the time.
>
> **The consequence is a rule, not a curiosity: a tracked file may not point a reader at either path.** A citation to an untracked document is a dangling reference — the reader follows it and arrives at nothing, and if the citation was to a *criterion*, the criterion is unavailable to everyone who was not already holding the file. Every such citation in this repository has been replaced with a tracked document that carries the substance. **Nothing here was fixed by committing the two files: their untracked status is a finding about the repository, not a licence to change it.**

**What this changes operationally:** the host's `git pull --ff-only` is now a real delivery path for the deploy scripts (§2.3, Option A), and the digest pinned in `docker-compose.yml` and `.env.example` is on `main` rather than being a local-only belief (§3.2). The checkout on the host still has to actually be a checkout, and still has to have been pulled — confirm with §2.2 rather than assuming.

---

## 1. Prerequisites

### 1.1 Operator workstation

| Requirement | Why | Notes |
|---|---|---|
| AWS CLI v2 | SSM, and reading Terraform output | `RUNBOOK.md:9` |
| AWS credentials for profile `lemondrop` | — | `RUNBOOK.md:4` — all AWS commands assume this profile and region `eu-west-1` |
| Region `eu-west-1` | — | `RUNBOOK.md:4`; `infra/versions.tf` backend block per `RUNBOOK.md:29-38` |
| The EC2 instance id | target of every SSM call | **Discovered, not quoted** — `aws ec2 describe-instances --filters 'Name=tag:Role,Values=application-host' 'Name=instance-state-name,Values=running' --query 'Reservations[].Instances[].InstanceId' --output text` (§7.1.1 step 1 gives the full query, with the `ManagedBy=terraform` filter that stops it matching a second stack). `terraform output ec2_instance_id` (`infra/outputs.tf:172-175`) is a second route and needs state access (§7.1.1's note). ❗ **`RUNBOOK.md` records `i-0c3155b1b6bb31298` and this runbook does not depend on it.** `docs/verification-milestone-3.md` §12.1 row 1 records that the instance id was *unchanged* across the Milestone 3 resize, which is why the value still appears in that file — and why it is the value that would fool you. **Read it from AWS.** |
| Docker, with Compose v2 (`docker compose`, not `docker-compose`) | To resolve a digest, and if you verify from your own machine | `README.md` (Prerequisites) — the stack was built and verified against Compose v5.5.1 |
| `jq` (optional) | Only if you read Secrets Manager by hand | Not needed by any step in this runbook. The host resolves the database credential itself. |

**The instance has no SSH key and no public IP** (`RUNBOOK.md:89`, `infra/outputs.tf:180-186`). Everything reaches it through SSM.

### 1.2 Permissions the operator needs

Split carefully, because these are two different systems and conflating them is how people end up with a permission they did not intend to grant.

**AWS (your IAM principal, on your workstation):**

| Action | Resource | Used for |
|---|---|---|
| `ssm:StartSession` | the instance | Interactive shell, **and the port-forwarding session that reaches RDS (§7.1.1)** |
| `ssm:SendCommand` | the instance | Running anything non-interactively |
| `ssm:GetCommandInvocation` | the instance | Reading the result of a `SendCommand` |
| `ssm:ListCommands` / `ssm:ListCommandInvocations` | the instance | Finding a previous command id |
| `ssm:GetParameter` / `ssm:GetParameters` | `/aws/service/ami-amazon-linux-latest/*`, and this stack's DB host/port parameters | Only if you run Terraform. **Not needed for a deploy — and equally not needed to read the database revision, because §7.1.1's primary route uses `rds:DescribeDBInstances`.** The SSM-parameter alternative in §7.1.1 needs only the two DB parameters. |
| `ec2:DescribeInstances` | — | Confirming the instance id — **and §7.1.1 step 1 uses the same call to discover it, which is now how §1.1 says to obtain it** |
| `elasticloadbalancing:DescribeLoadBalancers` | — | ⚠️ **§5.3's ALB reachability check only.** It is how the ALB's DNS name is discovered, which §5.3's check needs and **which nothing on the host can supply**. **Not needed for a deploy, for a verification against localhost, or for a rollback** — only for the one check that answers "will the load balancer route to it?", which is a different question from "is the process serving correct results?" (§5.3's table). The action is ELBv2's and the CLI call is `aws elbv2 describe-load-balancers` — **not `aws ec2 describe-load-balancers`, which is not an EC2 API and does not exist.** |
| `rds:DescribeDBInstances` | the DB instance | ⚠️ **Reading the database revision only (§7.1.1).** Nothing in the deploy path needs it. |
| `secretsmanager:GetSecretValue` | **the RDS master secret** | ⚠️ **Reading the database revision only (§7.1.1). This is a grant on YOUR principal, not on the instance — §7.1.1 and §1.3 say why the instance role cannot have it.** Nothing in the deploy path needs it. |

`ssm:SendCommand` + `ssm:GetCommandInvocation` is the minimum for the workflow in this runbook; the exact pair `RUNBOOK.md:160-168` uses. **The three read-only `Describe*` calls above are the discovery routes, not deploy permissions**: `ec2:DescribeInstances` for the instance id (§1.1, §7.1.1 step 1), `elasticloadbalancing:DescribeLoadBalancers` for the ALB DNS name (§5.3), `rds:DescribeDBInstances` for the database endpoint, port, db name, master secret ARN and master username (§7.1.1 step 1). **None of them is used by anything on the host**, and none is used by `deploy.sh`, `rollback.sh` or `verify-deployment.sh`.

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

**A note on the repository's own state, which affects Option A specifically.** `docs/boot-script.md:204-207` records that boot step 3 **currently fails on boot** because the clone target is a private GitHub repository that the instance cannot authenticate to, and `infra/variables.tf:619-622` says the same. But `docs/verification-milestone-3.md` §12 records a working deployed stack, which implies the clone succeeded at some point. **The tracked documents do not agree on this point** and I cannot resolve it from the files: the only two that speak to visibility are `docs/verification.md:148`, which records the repository as *private*, and `docs/boot-script.md:204-207`, which records the clone failing against a private repository — there is **no tracked document asserting the opposite**, so this is a gap in the record rather than a contradiction between two of them. So: check §2.2's `rev-parse` output rather than assuming, and if `/opt/lemondrop/.git` is absent, Option A is not available and Option B is the only path.

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

- The comment above it asserts the image is one this project "published, verified, and can pull anonymously". The anonymity half was **contested elsewhere in the repository**, and that contest is now **answered by observation** (§10 item 7). **Repository visibility and package visibility are two different settings**, and the repository records the first — `docs/verification.md:148` records the repository as *private*, `docs/boot-script.md:204-207` records a clone against it failing on boot — **and records nothing about the second, which is what a pull touches.** A public repository does not imply a public package. The package was observed anonymously readable; the repository-visibility question is a separate one, still open, and irrelevant to whether the host can pull. **Run §3.3's check on the digest, on the day, rather than trusting either this paragraph or the compose comment.**

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

### 3.4 What a **tested revision** is

**This term appears in this milestone's acceptance criterion and nothing here had ever defined it**, which made it the single most consequential undefined term in the repository: a deployer could satisfy any reading of it and not know which one they had satisfied. It is defined here, and the definition has three parts that have to hold **together**. Any one of them alone is not a tested revision.

| # | It must be… | How you know | Where it is enforced |
|---|---|---|---|
| 1 | a **commit that reached the release branch** and produced a **successful** `release` run | the run for that SHA concluded green, and its `publish` job was not skipped | `.github/workflows/release.yml`: `on: push` restricted to `branches: [main]`; `publish` carries `if: github.ref == 'refs/heads/main'` |
| 2 | **the registry manifest digest that run published** | the `publish` job summary, or the `published digest:` line in its log — §3.3 | `validate_image_digest()` in `deploy-lib.sh` (§3.1) accepts nothing else |
| 3 | **the source revision that image reports, and the validated schema label on it** | `org.opencontainers.image.revision` and `org.lemondrop.alembic-head`, read off the image | the schema gate and the provenance check (§4.4); `deploy-lib.sh`'s `image_label()` |

**Why each part is load-bearing rather than redundant.** Part 1 is the only thing that produced an image at all — CI builds and publishes, and nobody builds by hand. Part 2 is the only reference the deploy tooling will accept, and the only one that survives a second push (§3.1). Part 3 is the only statement of what the image **expects the database to be at**, and it is what `--adopt-current`'s `SCHEMA DISAGREEMENT` check compares against your out-of-band reading (§7.1). **A revision with no digest cannot be deployed; a digest with no labels cannot be reasoned about against the database; and a local commit has neither.**

**Reading part 3 off the image, using the same idiom the deploy script uses** (`deploy-lib.sh:572-583`, so what you read here is what `image_label()` reads there). This needs the image pulled locally — `docker manifest inspect` (§3.3) does not fetch one:

```bash
docker pull ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex>

docker image inspect \
  --format '{{range $k, $v := .Config.Labels}}{{printf "%s=%s\n" $k $v}}{{end}}' \
  ghcr.io/fvitorino00/lemondrop-api@sha256:<64-hex \
  | sed -n 's/^org\.opencontainers\.image\.revision=//p;s/^org\.lemondrop\.alembic-head=//p'
```

**The revision must be the full 40-character SHA.** `release.yml` labels with `${{ steps.refs.outputs.source_revision }}`, which is `GITHUB_SHA` — 40 characters — and abbreviated SHAs are ambiguous across a long history. §10 item 9 records the same reasoning for why no SHA is written into this document: *read `git rev-parse HEAD` on the day you need it.*

#### How an independent engineer finds the release from this repository alone

Everything needed is in `.github/workflows/release.yml`, and nothing is in this document:

1. **The workflow publishes on push to the release branch.** Its trigger is `on: push: branches: [main]` plus `workflow_dispatch`. `branches: [main]` is the whole of the answer to "when does an image appear".
2. **The job that carries the authoritative digest is `publish`**, displayed as **`publish to GHCR`**. It `needs: [build]`, and it holds the only `packages: write` in this repository's CI.
3. **The step is named `record the pushed digest`.** It writes `>> "$GITHUB_STEP_SUMMARY"` and echoes `published digest: <ref>@sha256:<64-hex>` — the two places §3.3 sends you.
4. **The digest must be read from that run's evidence.** ⚠️ **Not from any file in the tree.** `docker-compose.yml` and `.env.example` both name a digest-pinned reference, and **both are stale by construction** — a new digest is produced by every merge to `main` (§3.2, §10 item 8). They exist so boot has a *safe* default, not so an operator has an *approved* one. **A digest read out of the tree is a record of a past run.**

#### ⚠️ THE UNPUSHED-HEAD TRAP — an unpushed checkout is not deployable

> ⚠️ **A local commit that has not been pushed has no image. Not an old one, not a stale one — none. The pipeline has not run, the registry holds no manifest for it, and there is nothing to pull.**
>
> **An unpushed checkout must never be assumed deployable, under any circumstances, for any reason.** This is not a theoretical caution: it is an **observed trap**. During the cold-reader walkthrough recorded in `docs/second-engineer-acceptance.md`, the revision under test was a `main` that was **ahead of `origin/main`**, and therefore **had no published image at all**. A reviewer following this runbook literally would have taken a digest, deployed it, and deployed *the previous commit's image* while believing it was their own.

The check, before anything else:

```bash
git fetch origin
git rev-parse HEAD                       # the 40-char SHA you are considering
git rev-parse origin/main                # where the release branch actually is

# ON origin/main  => a release run may exist for it; confirm it, per steps 2-3 below.
# NOT ON origin/main => THERE IS NO IMAGE. Stop.
git merge-base --is-ancestor HEAD origin/main \
  && echo "on origin/main — a release run must now be confirmed for this SHA" \
  || echo "NOT on origin/main — this commit has never been built. There is nothing to deploy."
```

⚠️ **Two ways "on `origin/main`" is still not enough:**

- **The run must have succeeded.** `release.yml`'s `concurrency` block cancels a previous in-flight run on a second push to `main`, and a **cancelled run publishes nothing** — the workflow says so in the comment above the `concurrency:` key, and the design is that nothing is published until every gate has passed. A SHA on `origin/main` with a cancelled or failed run has no image either.
- **The `publish` job must not have been skipped.** Its `if: github.ref == 'refs/heads/main'` means a `workflow_dispatch` run on any other ref builds and passes gates and publishes nothing. **A green run is not the same as a published digest** — read the summary.

**And the corollary, which is the reason this section exists at all:** you cannot discover the digest of a commit you have not pushed, from anywhere, including from this repository. **That is not a gap in the documentation; it is the definition of the situation.** What the documentation owes you is the ability to tell that you are in it — which is what the check above is.

**What you deploy is therefore always four facts, never one:** the full commit SHA, the release run that published it, the digest that run recorded, and the two labels the image carries. §4.4 then makes the SHA optional on a labelled image — **but the SHA was never optional for deciding *which* image you are deploying**, which is the question §3.4 answers.

---

## 4. Deployment

### 4.1 Decide before you type: is this a rollback or an investigation?

Stated identically in the header comment of `scripts/rollback.sh`, under `── WHEN TO USE THIS, DECIDED IN ADVANCE ──`, so the decision is made *before* the incident rather than during it — and stated there rather than only here, because the reader who needs it will be holding the script:

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

### 4.2.1 ⚠️ UNFIXED — deploying the digest that is already running destroys the rollback pointer

**This section is here because it is the last thing read before §4.3, not because it is the last thing that matters.** Running `deploy.sh` with the digest that is **already running** is not a no-op, and nothing in the script stops it. There is **no redundant-deploy guard**: `deploy.sh` contains no comparison of the target digest against the running image, anywhere. The deploy runs to completion, verifies, prints the green `DEPLOYED` banner, and exits 0 — leaving the record **self-referential**, with `IMAGE_DIGEST` and `PREVIOUS_IMAGE_DIGEST` naming the same image.

**This is not hypothetical. It happened on the live EC2 host during the Milestone 4 acceptance rehearsal.** `deploy.sh` was run twice against the same digest, and the second run overwrote the rollback pointer with the digest it had just deployed. `docs/verification-milestone-4.md` §8.2 is the record, and §10 item 3 of that document carries it into the list of what its green verdicts do not mean.

**What a redundant deploy does, in order.** Nothing in this table is conditional. It is the whole of what `deploy.sh` does when the target is the running digest:

| Step | What happens | Reference |
|---|---|---|
| capture | Tags a **new** timestamped rollback tag — `lemondrop-api:rollback-<UTCstamp>` — on the image that is **already running**. A second tag naming the same bytes, not a second image | `deploy.sh:305-308`, from `PREV_IMAGE_ID` read at `deploy.sh:293` |
| pull | Pulls the image again. Same bytes; a full download to arrive where it started | `deploy.sh:846` |
| switch | Rewrites `API_IMAGE` in `.env`, then **recreates the api container** — `compose up -d --no-build --no-deps --force-recreate api`. Connections dropped, models untouched, and up to a **300 s** readiness wait for a service that never changed (`LEMDROP_READY_TIMEOUT`, `deploy-lib.sh:67`) | `deploy.sh:913`, then `deploy.sh:925` |
| record | Re-points `ROLLBACK_TAG` at the image that is running now, and writes the record with `IMAGE_DIGEST` and `PREVIOUS_IMAGE_DIGEST` **naming the same image** | `deploy.sh:953`, `deploy.sh:967`, `deploy.sh:961`, `deploy.sh:969` |

**Why the record becomes self-referential — the two lines that do the damage.** `deploy.sh:944`:

```
    prev_digest="$(record_get IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"
```

and `deploy.sh:969`:

```
    "PREVIOUS_IMAGE_DIGEST=${prev_digest}" \
```

`:944` reads the previous digest from the record's **then-current** `IMAGE_DIGEST`. On a redundant deploy that value **is the target** — the record is already naming the image you are about to deploy. `:969` then writes it back out as `PREVIOUS_IMAGE_DIGEST`. The result is `IMAGE_DIGEST` == `PREVIOUS_IMAGE_DIGEST`, and `PREVIOUS_IMAGE_DIGEST` is documented as **the rollback target** (§4.6). It now names the image that is running.

**The consequence, end to end, in one sentence.** The intended previous image is no longer reachable through the normal path, because `rollback.sh:163-171` selects `PREVIOUS_IMAGE_DIGEST` as its target whenever that key is non-empty, so the rollback restores the image that is already running — and re-running `rollback.sh` in that state does not help either, because it restores what is running, reports success, and then blanks `PREVIOUS_*` (`rollback.sh:438`), erasing the last record-level reference.

On the rehearsal host this cost the pointer to the original legacy image. **The image itself survived** in the local store under its timestamped tag — `docs/verification-milestone-4.md` §9.1 records `lemondrop-api:rollback-20261014T232428Z` intact — but nothing in the record pointed at it any more, and that is the only place a rollback can look (§6.2).

**⚠️ `Undo with: scripts/rollback.sh` is not true of a redundant deploy.** The `DEPLOYED` banner quoted in §4.5 ends with that line, and `deploy.sh:988` prints it:

```
  say "  Undo with:               scripts/rollback.sh"
```

On a redundant deploy the record it is pointing at is the one described above, and `rollback.sh` **cannot usefully undo it** — it has no target but the running image. Read that banner line as "rollback is available if this deploy created a rollback point", which on this path it did not.

#### The pre-flight check you must run by hand

**Nothing performs this check for you, so it is a checklist item, not a reassurance.** The question to ask is exact: *is the digest I am about to deploy the one already recorded as deployed?* Answer it **before** typing the command, from the record:

```bash
sudo grep '^IMAGE_DIGEST=' /var/lib/lemondrop/deployed-revision.env
sudo grep '^PREVIOUS_IMAGE_DIGEST=' /var/lib/lemondrop/deployed-revision.env
```

**If your target digest equals the value in `IMAGE_DIGEST`, do not deploy it.** That equality is precisely the condition under which `deploy.sh:944` reads the target back as its own "previous" digest.

`scripts/verify-deployment.sh` (§4.2, which you are about to have run anyway) answers the same question, and this is how to read it:

| `── do they agree? ──` says | What it means for your target | What to do |
|---|---|---|
| `AGREE — the running image IS the one the record names.` (`verify-deployment.sh:172-173`) | The record's `IMAGE_DIGEST` **is the running digest**. If your target is that digest, you are about to deploy the running image and destroy the rollback pointer | **Do not deploy it.** If you believe a new image should be running, the digest you have is the old one — go back to §3.3 |
| `DIVERGENCE — the record and the running image do not match.` (`verify-deployment.sh:217`) | The record names a digest that is **not** running, so a target equal to the record's `IMAGE_DIGEST` is not a redundant deploy. The running image is a third thing, and nothing here is redundant | Safe from *this* failure mode. A divergence has its own causes, printed most-likely-first by the script — read §4.2's account of them before deploying over it |
| `UNPINNED (LEGACY) — … NOTHING WAS COMPARED.` (`verify-deployment.sh:176`) | **The check did not run.** The running image is a locally built image with no registry digest at all, so it cannot equal your target — a redundant deploy is not possible here | Safe from *this* failure mode. Expect `PREVIOUS_IMAGE_DIGEST` to be written **empty** (§6.4) |

The `AGREE` row is the one to be careful with, and it is the **normal** reading on a healthy digest-pinned host. `AGREE` is a good verdict about the host and it is simultaneously the signal that **the digest you just read out of the record is the one you must not deploy.** A green `verify-deployment.sh` is not permission to redeploy what it just told you is running.

#### Status: UNFIXED, tracked, deferred

**This is a known gap and it is UNFIXED.** Nothing in `deploy.sh` guards against it, and nothing in this runbook should be read as saying that a guard exists, might arrive soon, or is half-built. It was found by executing the deploy path on a live host during Milestone 4 and is recorded at `docs/verification-milestone-4.md` §8.2 ("a redundant deploy has no guard, and this is UNFIXED"), in that document's §10 item 3, and in its §12 table's row 22 ("Redundant-deploy guard in `deploy.sh` | **UNTESTED — and the guard does not exist**"). Fixing it is **deliberately out of scope** for that milestone. **Until it is fixed, the check above is the operator's responsibility** — it is a manual pre-flight step, not a diagnostic that runs for you.

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

**Discover the DNS name from AWS. Do not read it out of a file, and do not use Terraform to get it.**

```bash
# The load balancer's name is "${project_name}-${environment}-alb" by construction —
# `name = "${local.name_prefix}-alb"` on `aws_lb.main`, and `local.name_prefix` is
# "${var.project_name}-${var.environment}" (infra/locals.tf:11). With the variable
# defaults that is `lemondrop-dev-alb`.

ALB=$(aws elbv2 describe-load-balancers --names lemondrop-dev-alb \
      --query 'LoadBalancers[0].DNSName' --output text)

test -n "$ALB" || { echo "no load balancer by that name — is the environment dev?"; exit 1; }

curl -i "http://$ALB/health/ready"
```

**Three things about that command line, each of which was wrong or missing before.**

- ⚠️ **It is `aws elbv2 describe-load-balancers`, not `aws ec2 describe-load-balancers`.** The second is not an EC2 API and does not exist. `DescribeLoadBalancers` belongs to ELBv2 and the IAM action is **`elasticloadbalancing:DescribeLoadBalancers`** — which was absent from §1.2's table while this section called for it. It is there now.
- ⚠️ **It does not need Terraform, and therefore does not need state access.** An earlier version of this section ran `terraform output alb_dns_name`, which requires **read access to the S3 state backend** — the bucket named in the `backend "s3"` block at `infra/versions.tf:41-55`, which `terraform output` reads through `s3:ListBucket` and `s3:GetObject` on that bucket (and, because the block sets `use_lockfile = true`, `s3:PutObject` / `s3:DeleteObject` on the same bucket's `.tflock` objects — **there is no DynamoDB lock table in this stack, and `infra/versions.tf:47-48` says so**). **§1.2's table does not grant any of that, and nothing in this runbook provisions it**, which made this the one step whose value had no documented route for an operator holding only §1.2. It has one now.
- ⚠️ **`--names` takes the ALB's name, not the DNS name**, so the argument is derived from the stack's naming convention rather than from the answer. If your stack was applied with non-default `project_name` / `environment`, substitute them; the defaults are `lemondrop` and `dev` (`infra/variables.tf:44`, `:50`) and `environment` is constrained to `dev`, `staging` or `prod` (`:47-55`). **If `describe-load-balancers` returns nothing, that is a naming question, not a missing load balancer** — `aws elbv2 describe-load-balancers --query 'LoadBalancers[].{N:LoadBalancerName,D:DNSName}' --output table` lists all of them and answers it in one call.

**`terraform output alb_dns_name` remains a valid second route** (`infra/outputs.tf:161-165`) if you already have state access, and the two are worth cross-checking when you have both — §7.1.1's note on the Terraform outputs says the same about the RDS values. **The rule is the same in both places: the outputs are a second route, not a prerequisite.**

The DNS name is also recorded literally in `RUNBOOK.md:114`, ⚠️ **as a Milestone 2 record and not as the authority** — that file's own header says its values are M2-era records and that `docs/deployment.md` §5.3 is the route.

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

⚠️ **This field is destroyed by a redundant deploy, and the guard that would prevent it does not exist.** `PREVIOUS_IMAGE_DIGEST` is written from whatever `IMAGE_DIGEST` said when the deploy began (`deploy.sh:944` → `deploy.sh:969`), so deploying the digest that is already running writes this field with that same digest — and the rollback then selects the image that is running. §4.2.1 has the full consequence, the pre-flight check, and its status. **A rollback target that names the running image is a symptom, not a cause: look at what was deployed, not at what this command reports.**

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

A rollback you have never run is a hypothesis. Rehearse it **before** you need it. **The milestone's acceptance criterion is that this be done by someone other than the author** — `docs/verification-milestone-4.md` §13.1 records the criterion and §13.2 records its status.

**Do it on a throwaway host, never on the one serving traffic.** There is no rehearsal mode and no dry-run flag; `deploy.sh --help` is the only non-mutating invocation.

> ⚠️ **⚠️ THIS REPOSITORY DESCRIBES NO THROWAWAY HOST. ⚠️**
>
> "Do it on a throwaway host" is an instruction about *where*, and this repository has never said whether such a host exists. **It does not describe one, does not name one, and does not state that one exists.** §10 item 17 records that as a known limitation and scopes it to the variant it affects. **Nothing in this procedure provisions one, and creating one is infrastructure work outside the scope of a documentation pass.**

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

**The value must be read out of band, because this host cannot read it.** The EC2 instance role holds the *application* secret only, and `lemondrop_app` is DML-only with no DDL rights — `CREATE EXTENSION vector` needs `rds_superuser`, which is precisely the split between the two credentials (`infra/iam.tf`, under *WHY THE APPLICATION CREDENTIAL AND NOT THE MASTER PASSWORD* and *⚠️ MIGRATIONS DELIBERATELY LOSE THEIR EC2 PATH. ⚠️*). **The complete procedure for *reading* it is §7.1.1**, end to end, including the tunnel, the TLS and the credential; the procedure for *migrating* it is `api/alembic/README.md`, under *Against RDS, later*. `deploy.sh`, `rollback.sh` and `verify-deployment.sh` can all **compare against** `ALEMBIC_HEAD` and none of them can **confirm** it — nothing in this repository can. The argument is you, doing the looking, on purpose.

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
| Live RDS alembic revision | `0001` | read out of band by the operator from the RDS instance — **§7.1.1** carries the complete procedure; `docs/verification-milestone-4.md` §5 is the record of the M4 read | 2026-10-14 |

**Read the corroboration for what it is.** `docs/verification-milestone-3.md:145` row 1 records "Revision `0001` applied successfully", executed and reported by the operator. It confirms that **`0001` is the single migration this repository has**, and it is the origin of the number. It is **not** independent evidence about the RDS instance: row 8 of the same table, and the paragraph beneath it, record that the migration target resolved to `127.0.0.1:5432` — the local container — and state "Nothing in this section is evidence about the RDS instance." The `0001` above is the operator's out-of-band read from RDS; that row is why the value is plausible, not why it is believed.

**⚠️ THIS IS AN EVIDENCE RECORD, NOT A CACHED BELIEF — RE-READ IT BEFORE YOU ADOPT.** This document is not the database. The argument you pass is the database's answer; `0001` written here is a note about what that answer was on 2026-10-14.

- **Re-read the revision from RDS before adopting.** The complete procedure is **§7.1.1** — discover, tunnel, TLS, credential, query. `api/alembic/README.md` is the *migration* procedure and assumes you already have the URL; §7.1.1 is how you obtain everything in it.
- **If it is no longer `0001`, the NEW value is what `--adopt-current` takes.** Do not pass `0001` because this document says `0001`. A baseline that contradicts the database is not a harmless typo: it is a value every later deploy's fail-closed schema gate is measured against, so it converts one mistyped argument into a host that refuses every deploy until someone reconciles it by hand.
- **This is the exact failure `deploy.sh` was rewritten to eliminate.** `validate_alembic_revision_id()`'s header comment says so directly: the value is not looked up in the checkout because "the entire reason this argument exists is that the answer comes from the database, and the database is frequently not what the tree says". A runbook that hard-codes a revision *without this warning* would reintroduce the very substitute — a value carried around in a file instead of read from its source — through the documentation instead of through the code.
- **Recorded 2026-10-14.** If you are reading this after a migration has been applied, treat the value as unverified until you have re-read it.

**If you know exactly what should be running**, and the record is gone entirely, the `write_record` failure branch of `deploy.sh` gives the other route, for the specific case where verification passed but the record write failed: record by hand from the values the deploy printed, or re-run `deploy.sh` with the same arguments once the directory is writable. The script's own instruction is: "Do NOT re-run this deploy to fix it."

### 7.1.1 Reading the live database revision — the complete procedure

**Every other command in this runbook can be run from a checkout. This one cannot**, which is why it is its own section rather than a line in §7.1. `--adopt-current` takes the database's alembic revision as an argument and **nothing in this repository can produce that argument**: the host cannot read it (§1.3) and the deploy tooling can compare against it but never confirm it (§7.1 above). This is the procedure that closes that hole, and it was absent — the technique was described in three places and the invocations in none.

It is a **read**. One `SELECT`, one row, nothing written. It does **not** migrate, and it does **not** run from the host: see *Not this* at the end.

#### The access this requires, and the access it does not

| Requirement | Why | Where it comes from |
|---|---|---|
| `ssm:StartSession` on the EC2 instance | the tunnel | §1.2 |
| `rds:DescribeDBInstances` on the instance | the endpoint, the port, the master secret ARN, the master username | §1.2 |
| `secretsmanager:GetSecretValue` **on the RDS master secret** | the password | §1.2 |
| `ssm:GetParameter` on `/…/db/host` and `/…/db/port` | *only* for the no-Terraform alternative below | §1.2 |
| `psql`, `jq`, `curl`, `openssl` on the workstation | the client, the JSON extraction, the CA bundle, the bundle check | §1.1 |

> ⚠️ **`secretsmanager:GetSecretValue` on the MASTER secret is an operator-side grant and the EC2 instance role does not have it. This is a control, not an oversight.**
>
> `infra/iam.tf:530-545` attaches the instance role a single-ARN `secretsmanager:GetSecretValue` policy, and the ARN it names is `data.aws_secretsmanager_secret.app_db[0].arn` — the **application** credential, not the RDS master secret. The Sid was renamed to `ReadOnlyApplicationDbSecret` for exactly this reason (`iam.tf:525-530`), and the comment at `iam.tf:539-545` records that the ARN was **repointed** from the master secret to the application secret. `docs/verification-milestone-3.md` §12.1.1 row 18 records the operator getting a genuine **`AccessDeniedException`** on the master secret — "the ARN resolved, policy said no" — and records that as a **PASS**. `docs/deployment.md` §1.3 states the same boundary.
>
> **So: if this procedure returns `AccessDeniedException`, the correct reading is that your own principal lacks the grant — not that the secret is missing, and not that you should go and widen the instance role's policy.** Widening it is the defect the repository removed. The grant belongs on the person at the keyboard, and `docs/second-engineer-acceptance.md` §4 item 4 is where that access is provisioned.

#### 1 — Identify the two instances, and the master secret, without typing any of it

**Nothing below is deployment-specific.** Every host name, port, identifier, ARN and username is **discovered from AWS at run time**, because a hardcoded one goes stale silently and a stale endpoint is how a reader ends up pointed at somebody else's database.

```bash
# ── The application host. `Role` and `ManagedBy` are tag KEYS defined in this
#    repository, not operator choices: infra/compute.tf sets Role=application-host
#    on aws_instance.app, and infra/locals.tf merges ManagedBy=terraform into
#    common_tags, which every taggable resource in the stack carries.

EC2_ID="$(aws ec2 describe-instances \
  --filters 'Name=tag:Role,Values=application-host' \
            'Name=tag:ManagedBy,Values=terraform' \
            'Name=instance-state-name,Values=running' \
  --query 'Reservations[].Instances[].[InstanceId]' --output text)"

# ── The RDS instance, identified by the same ManagedBy tag.

RDS_ID="$(aws rds describe-db-instances \
  --filters 'Name=tag:ManagedBy,Values=terraform' \
  --query 'DBInstances[].DBInstanceIdentifier' --output text)"

# ── Everything else from RDS instance metadata, which is the AUTHORITATIVE
#    source for all four. Nothing here is read from a file in this repository.

RDS_HOST="$(aws rds describe-db-instances --db-instance-identifier "$RDS_ID" \
  --query 'DBInstances[0].Endpoint.Address' --output text)"

RDS_PORT="$(aws rds describe-db-instances --db-instance-identifier "$RDS_ID" \
  --query 'DBInstances[0].Endpoint.Port' --output text)"

RDS_DB_NAME="$(aws rds describe-db-instances --db-instance-identifier "$RDS_ID" \
  --query 'DBInstances[0].DBName' --output text)"

RDS_MASTER_SECRET_ARN="$(aws rds describe-db-instances --db-instance-identifier "$RDS_ID" \
  --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)"

RDS_MASTER_USER="$(aws rds describe-db-instances --db-instance-identifier "$RDS_ID" \
  --query 'DBInstances[0].MasterUsername' --output text)"
```

**No `--region` is passed, deliberately.** `infra/variables.tf:5-8` says it outright: `aws_region` is *"DOCUMENTATION ONLY — this variable does not configure the AWS provider"*, and the region resources live in comes from the AWS CLI configuration. **Take the region from your profile, not from `var.aws_region`** — the variable is not authoritative for where anything is. Pass `--region` if your profile does not already carry one.

**Read them back before you use any of them.** An empty value is a *different situation* from a wrong one, and it is much easier to tell apart here than three stages later:

```bash
printf 'ec2=%s\nrds=%s\nhost=%s\nport=%s\ndb=%s\nuser=%s\nsecret=%s\n' \
  "$EC2_ID" "$RDS_ID" "$RDS_HOST" "$RDS_PORT" \
  "$RDS_DB_NAME" "$RDS_MASTER_USER" "$RDS_MASTER_SECRET_ARN"
```

⚠️ **Both tag filters can return more than one resource, and then the shell variables hold several values at once.** `var.environment` is constrained to `dev`, `staging` or `prod` (`infra/variables.tf:47-55`), and `local.common_tags` does not include the environment as a filterable *value* unless you filter on `tag:Environment` yourself. **If a line above contains a tab or a space rather than one value, you have more than one stack in this account** — narrow both queries with `'Name=tag:Environment,Values=<env>'` before going further, and do not let `--db-instance-identifier` receive a two-element string.

**Cross-check the instance identity against the Terraform definition.** `infra/database.tf:96` sets `identifier = "${local.name_prefix}-postgres"`, so the **first label of the RDS endpoint hostname is the DB instance identifier**:

```bash
printf 'derived-from-endpoint: %s\nrds_id-you-found:      %s\n' \
  "${RDS_HOST%%.*}" "$RDS_ID"
```

Two names that should be equal and are derived by unrelated paths. `local.name_prefix` is `${var.project_name}-${var.environment}` (`infra/locals.tf:11`), so a mismatch here is not cosmetic — it means you have found a **different stack**, and every later command will be pointed at it.

> ⚠️ **The Terraform outputs are a second route to the same values, not a substitute.** `infra/outputs.tf` publishes `rds_address`, `rds_endpoint`, `rds_secret_arn`, `rds_db_name` and `ec2_instance_id` — `terraform output rds_address` and so on. **They require read access to the S3 state backend**, which is not in the §1.2 permission table and is not needed for this procedure; that is why `describe-db-instances` is the route above. Use the outputs when you already have state access, and cross-check the two when you have both.

**The route that needs no Terraform and no `rds:` permission** — the SSM parameters the application itself uses (`infra/iam.tf:821-847`):

```bash
RDS_HOST="$(aws ssm get-parameter --name /lemondrop/dev/db/host \
  --query 'Parameter.Value' --output text)"
RDS_PORT="$(aws ssm get-parameter --name /lemondrop/dev/db/port \
  --query 'Parameter.Value' --output text)"
```

**The path components are not literals.** `iam.tf:824` and `:838` build them as `/${var.project_name}/${var.environment}/db/host` and `…/db/port`, from defaults `lemondrop` and `dev` (`infra/variables.tf:44`, `:50`). `iam.tf:779-806` is emphatic about the format — a leading slash, **no** trailing slash, no empty segment — because that rule has been got wrong once in each direction and both mistakes cost an apply.

> ⚠️ **There is a third parameter, `/…/db/secret-arn`, and it is NOT the master secret. Do not use it here.**
>
> `infra/iam.tf:849-878` **repointed** it from the RDS master secret's ARN to the **application** credential's ARN (`data.aws_secretsmanager_secret.app_db[0].arn`), precisely so the ARN the host resolves is one the host is actually permitted to read — the comment at `iam.tf:863-868` names the failure the repointing fixed: a host resolving a valid ARN it could not read, surfacing as `AccessDenied` at first use. **Reading that parameter here and using it in step 4 will produce an `AccessDeniedException` that looks exactly like a missing operator grant and is not one.** The master secret ARN comes from `MasterUserSecret.SecretArn` — `docs/verification-milestone-3.md` §12.1.1 records the M3 operator deriving it that way for the same reason.

#### 2 — The CA bundle, fetched and checked

`sslmode=verify-full` needs a trust anchor, and `libpq`'s default (`~/.postgresql/root.crt`) will not have Amazon's in it.

```bash
CA_DIR="$HOME/.lemondrop"; mkdir -p "$CA_DIR"
CA_BUNDLE="$CA_DIR/rds-global-bundle.pem"

curl --proto '=https' --tlsv1.2 -fsSL -o "$CA_BUNDLE" \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem

# It must be a PEM bundle, not an HTML error page that happened to be a 200.
grep -c 'BEGIN CERTIFICATE' "$CA_BUNDLE"

# And every certificate in it must parse. `openssl crl2pkcs7 -nocrl` reads a
# bundle of PEM certificates; `pkcs7 -print_certs` lists what came out.
openssl crl2pkcs7 -nocrl -certfile "$CA_BUNDLE" \
  | openssl pkcs7 -print_certs -noout
```

`--proto '=https'` forbids a redirect to plaintext, and curl validates the TLS chain against your system trust store, so the download is itself authenticated. **The two checks after it are not ceremony:** a bundle that is empty or truncated produces a TLS error whose message says nothing about certificates, and a `grep -c` of `0` is the only thing that distinguishes the two.

The URL is the one already recorded in `RUNBOOK.md`'s troubleshooting table, under the row *"psql fails with a TLS verification error"*. **Nothing secret is in it and nothing secret comes out of it** — the bundle is public, and you can delete it when you are done.

> ⚠️ **If the connection fails on certificate verification, do not "fix" it by weakening `sslmode`.** `sslmode=require` encrypts without verifying anything, including which server you encrypted to. `docs/verification-milestone-3.md` §12.1.1 names the failure this procedure exists to avoid: connecting a forwarded socket so that `verify-full` ends up verifying a certificate against `127.0.0.1` "either fails outright or, **worse, is satisfied by loosening the check until it passes**." A downgraded `sslmode` is indistinguishable, after the fact, from a correct one. Fix the bundle or fix the name.

#### 3 — The tunnel: an SSM port-forwarding session through the EC2 host

**RDS is not reachable from the internet.** `infra/database.tf:196` sets `publicly_accessible = false`, and `infra/security_groups.tf:355-364` allows TCP 5432 into the database from **exactly one** source — `aws_security_group.app_ec2` — with no other ingress rule defined for it. `docs/verification-milestone-3.md` §12.1.1 rows 13–18 record that even the M3 operator did not reach RDS over a public path.

The route is a port-forwarding session **from your workstation, through the EC2 instance, to the database**. Run this in its own terminal and leave it open:

```bash
aws ssm start-session \
  --target "$EC2_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "portNumber=$RDS_PORT,host=$RDS_HOST"
```

**Read the local port off the CLI's own output.** It prints a line of the form `Port <NNNNN> opened for sessionId <…>` when the tunnel is up. **Do not assume a number** — the CLI assigns it, and assuming one is how you end up reading a row out of whatever is listening on that port. Then, in your *other* terminal:

```bash
# docs/verification-milestone-3.md §12.1.1 records 15432 for the M3 operator's run.
# YOUR number is whatever YOUR CLI printed, one line above.
RDS_LOCAL_PORT=15432
```

**Why `…ToRemoteHost` and not the plain `…Session` document.** The database is not on the instance; it is a separate RDS endpoint the instance can reach and you cannot. The `…ToRemoteHost` document takes the **destination** as parameters — `host` and `portNumber` — and forwards over the instance's own VPC attachment. `docs/verification-milestone-3.md` §12.1.1 records this exact document for exactly this check, and **it is the route this procedure is written against**, not a reconstructed one.

The tunnel carries no credentials and changes no host state. It is an open local socket for as long as you leave the session running, **which is the reason to close it when you are finished.**

#### 4 — The password, into the environment and nowhere else

```bash
export PGPASSWORD="$(aws secretsmanager get-secret-value \
  --secret-id "$RDS_MASTER_SECRET_ARN" \
  --query SecretString --output text | jq -r .password)"
```

**`export` on its own line is the entire security property of that command.** The secret value is written by the assignment and read by `psql` from the environment; it never appears in `argv`, so it is not in `ps` output, not in `~/.bash_history`, and not in the transcript of this session. `jq -r .password` is the extraction **Milestone 2 recorded** — `docs/verification-milestone-2.md` row 2 — and `RUNBOOK.md`'s troubleshooting table records that when the value comes back as a JSON object rather than a string, this is the step that got it wrong.

> ⚠️ **Two forms that look equivalent and are not.**
>
> ```bash
> PGPASSWORD="$(…)" psql …      # ❌ the password is in this command line,
>                               #   in the shell history, and in every
>                               #   `ps aux` on the machine while it runs.
> ```
>
> ```bash
> echo "$PGPASSWORD"            # ❌ the value reaches your terminal, your
>                               #   scrollback, and anything recording it.
> ```

**If you want proof the fetch worked without printing the value**, ask Secrets Manager for metadata instead — it answers without returning the secret:

```bash
aws secretsmanager describe-secret --secret-id "$RDS_MASTER_SECRET_ARN" \
  --query '{name:.Name, created:.CreatedDate, rotated:.LastRotatedDate}'
```

#### 5 — The query, with `host` and `hostaddr` split

```bash
psql "host=$RDS_HOST hostaddr=127.0.0.1 port=$RDS_LOCAL_PORT user=$RDS_MASTER_USER dbname=$RDS_DB_NAME sslmode=verify-full sslrootcert=$CA_BUNDLE" \
  -c 'SELECT version_num FROM public.alembic_version;'
```

**One line, and the keyword/value form rather than a URI, because that is the form that makes the split expressible.** Two hosts cannot be stated in a URI authority the way they are here: `host=` and `hostaddr=` are two separate keywords and this is the only connection-string shape that carries both without ambiguity.

**Each half is load-bearing, and they do opposite jobs:**

| Keyword | Value | What it is for |
|---|---|---|
| `host` | the **real RDS endpoint** | the **name the TLS certificate is verified against** — never resolved, never dialled |
| `hostaddr` | `127.0.0.1` | the **address the TCP connection actually goes to** — the forwarded socket |
| `port` | the **local** port your tunnel opened | `libpq` applies it to the connection it makes, which is `hostaddr` |
| `sslmode` | `verify-full` | chain **and** hostname verification, both on |
| `sslrootcert` | the bundle from step 2 | the trust anchor for that chain |

**`libpq` connects to `hostaddr` and verifies against `host`.** That single sentence is the whole reason this works, and it is what `docs/verification-milestone-3.md` §12.1.1 records as the finding worth preserving. Point `host` at `127.0.0.1` instead and `verify-full` verifies a certificate against the literal string `127.0.0.1` — which no RDS certificate can match, so the connection fails, or you weaken `sslmode` until it succeeds and have thrown the verification away.

**Why `public.alembic_version` and the column `version_num`.** Both are Alembic's defaults. `api/alembic/env.py` calls `context.configure()` at `:182-194` (shared, for the offline path) and at `:223` (online) **without overriding `version_table` or `version_table_schema`**, so the defaults stand and the table is the standard one-column version table in the default schema.

#### 6 — The output, and how to read it

```
 version_num
-------------
 0001
(1 row)
```

**Exactly one row, and one column.** That is the entire expected result, and its shape is the assertion:

| What you got | What it means |
|---|---|
| **one row**, one revision id | ✅ This is the value `--adopt-current` takes. |
| **zero rows** | the table is absent, or in a schema that is not `public`. Check `dbname` — you may be on the wrong database, or the schema has never been migrated. |
| **more than one row** | this is not the default single-column version table. You are not reading what you think you are reading; **stop and investigate rather than picking the first row.** |
| a non-revision-looking string | `validate_alembic_revision_id()` will refuse it in `deploy.sh` — a symbolic name, a leading `-`/`.`/`_`, more than 64 characters. |

Then: §7.1 above takes this value as `<db-verified-alembic-revision>`, and the value you just read is the value you pass.

#### 7 — Close it out

```bash
unset PGPASSWORD          # the export from step 4
# Leave the tunnel: Ctrl-C in the terminal running start-session. Nothing else
# closes it, and an open loopback socket should not outlive the check.
rm -f "$CA_BUNDLE"         # optional; the bundle is public
```

#### If it fails

| What came back | What it is | Do this |
|---|---|---|
| `Connection refused` on `127.0.0.1` | the tunnel is not up, or `RDS_LOCAL_PORT` is not the port it opened | re-read step 3's output; start the session again |
| `server closed the connection unexpectedly` at `127.0.0.1` | tunnel up, nothing listening for PostgreSQL behind it | the SSM agent or the document rejected it — check the session's own output before retrying |
| `certificate verify failed` | the CA bundle is missing, truncated, or not the one this server chains to | step 2. **Do not weaken `sslmode`.** |
| hostname mismatch in the TLS error | `host` is wrong — you are verifying against a name the certificate does not carry | re-check `$RDS_HOST` from step 1; do not switch to `hostaddr` alone |
| `AccessDeniedException` from `get-secret-value` | **your principal lacks `secretsmanager:GetSecretValue` on the master secret** — the control described above | the grant is provisioned, not configured in this repository. **Do not widen the instance role** |
| `ResourceNotFoundException` from `get-secret-value` | the ARN **never resolved** — wrong region, wrong account, or you passed `/…/db/secret-arn` | fix the ARN source. ⚠️ **This is not "denied".** `docs/verification-milestone-3.md` §12.1.1 is explicit that the two mean opposite things and that reporting a `ResourceNotFound` as a denial is "a check that failed to run while wearing the costume of one" |
| `role "…" does not exist` | the username did not come from step 1 | see the username note below |
| timeout, no answer | the EC2-to-database path is not what this runbook says it is | `infra/security_groups.tf:355-364` allows 5432 from `sg_app_ec2` and nowhere else. Confirm the instance is the tagged application host |

#### The master username is a discovered value, not a configured one

**Two tracked documents in this repository gave two different values for the RDS master username, and neither was authoritative.** Both are recorded here rather than deleted, because one of them has been changed and a reader comparing this section against an older revision needs to know what changed and why.

| Source | What it said | What kind of statement that was |
|---|---|---|
| `RUNBOOK.md`, §3 step 2 | a Milestone-2-era username, inlined in a `psql` URI | a value typed into a Milestone 2 verification command, **never reconciled against anything** |
| `infra/variables.tf:728` | a *different* username | ⚠️ **a Terraform *input default* — the value Terraform would use if no `-var` were passed.** Not a record of what any apply was run with. |

**What changed, and what did not.** `RUNBOOK.md`'s three values — the username, the endpoint and the master secret's ARN — **have been replaced by placeholders that point here**, rather than corrected to the other document's value. **A third hardcoded value would have been a third thing to go stale, and nothing in the repository detects staleness.** `infra/variables.tf` is **deliberately unchanged**, because it is not wrong: it says what this configuration would do applied today with no input, which is a true and useful thing for a variable default to say. `docs/deployment.md` §10 item 11 records the change.

**The distinction in the last column is the one that matters, and it applies to more than the username.** A variable default is a *fallback*, not a record. `-var`, `TF_VAR_…`, a `.tfvars` file, and a re-run of `plan` with no overrides can each change what the stack actually uses without a single character of `variables.tf` changing. **Reading `variables.tf` tells you what this configuration would do if applied today with no input. It does not tell you what was applied.**

**The authoritative route is the RDS instance's own metadata**, which is the same place the secret ARN in step 1 comes from:

```bash
aws rds describe-db-instances --db-instance-identifier "$RDS_ID" \
  --query 'DBInstances[0].MasterUsername' --output text
```

That is `$RDS_MASTER_USER`, already set in step 1 and already used in step 5. **It cannot be stale**, because it is read from the thing itself rather than from a file describing it.

#### Not this

- **This is a read.** Do not add `alembic upgrade`, do not run `psql -f`, do not "fix" a surprising revision while you have the tunnel open. **Applying a migration is `api/alembic/README.md`, under *Against RDS, later*,** which requires the RDS **master** credential because `CREATE EXTENSION vector` needs `rds_superuser` — a privilege the application role does not have and must not be given (§1.3).
- **This does not run from the host.** The whole reason for the tunnel is that the host has neither the credential nor the network path (§1.3). `docs/verification-milestone-4.md` §5 is the record of the M4 operator doing exactly this from a workstation and getting `0001`.
- **This does not establish what the host is running.** It establishes what the **database** is at. §7.1 above is why those two differ, and `--adopt-current` refuses when the image's own `org.lemondrop.alembic-head` label disagrees with what you read here.

#### What was checked against what

Recorded because this procedure is the kind of thing that gets trusted because it is specific.

| Element | Checked against |
|---|---|
| Tag keys `ManagedBy`, `Role=application-host`, `Name=<prefix>-postgres` | `infra/locals.tf:44-48`, `infra/compute.tf:589-592`, `infra/database.tf:96` |
| SSM parameter paths and their format rule | `infra/iam.tf:821-847`, `:779-806`; `infra/variables.tf:44`, `:50` |
| `/…/db/secret-arn` is the **application** ARN | `infra/iam.tf:849-878` and its `:863-868` comment |
| Instance role holds the application secret only | `infra/iam.tf:530-545`; `docs/verification-milestone-3.md` §12.1.1 row 18 |
| Port 5432 reachable from `sg_app_ec2` only | `infra/security_groups.tf:355-364`; `infra/locals.tf:23` |
| Not publicly accessible | `infra/database.tf:196` |
| `public.alembic_version`, column `version_num` | `api/alembic/env.py:182-194`, `:223` — no `version_table` override |
| `MasterUserSecret.SecretArn`, `MasterUsername`, `DBName`, `Endpoint.Address`, `Endpoint.Port` | the RDS service model in the AWS CLI shipped on this workstation; `docs/verification-milestone-3.md` §12.1.1 records `DBInstances[0].MasterUserSecret.SecretArn` in use |
| `AWS-StartPortForwardingSessionToRemoteHost` with `portNumber` / `host` | `docs/verification-milestone-3.md` §12.1.1, which names that document for this check; the CLI's `start-session` synopsis and the request it serializes for those two parameters |
| The RDS global CA bundle URL | `RUNBOOK.md` §7, troubleshooting table — the row that names it |
| `.password` in the master secret's JSON | `docs/verification-milestone-2.md` row 2, and the same `RUNBOOK.md` row |
| Region comes from the CLI, not `var.aws_region` | `infra/variables.tf:5-8` |
| `libpq` connects to `hostaddr` and verifies against `host` | the local `psql` on this workstation: a connection string carrying `host=<name> hostaddr=127.0.0.1` connected to `127.0.0.1`, which is the behaviour the split depends on; the verification consequence is `docs/verification-milestone-3.md` §12.1.1's recorded finding |

**Not verified without AWS access, and therefore stated as unknown here:** that these commands succeed against the live stack today; the local port the CLI assigns on any given run; and whether this stack's `sg_app_ec2` still admits 5432 as `security_groups.tf` describes. **The procedure is written from the definitions; the values are read at run time, so a definition that has changed is visible as a changed value rather than as a silent wrong answer.**

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

    **Package visibility is a setting separate from repository visibility.** A public repository does not imply a public package. The repository records its own visibility — `docs/verification.md:148` (*private*) and `docs/boot-script.md:204-207` (a clone against it failing on boot) — and records **nothing** about the GHCR package's visibility, which is the setting a pull actually meets. **There is no second tracked document asserting the opposite**, so the disagreement this item was written to resolve was with a document that is not in the revision; what remains is the observation below, and it is the whole of the answer.

    **What this item does and does not establish.** Readability was observed **at the time of verification**, against that digest. Later releases have published newer digests, so the evidence is about package readability and is **not** a claim that this digest is current (§3.2; item 8). It is **not** a claim of permanent availability, **not** immunity to a visibility change, and **no** future-access guarantee: the package setting can be changed by anyone with access to it, at any time, without this document noticing. **§3.3's check is what an operator runs before a deploy — not this paragraph.**

**8. The digests written down are examples, and they go stale on every merge.** §3.2. `docker-compose.yml` and `.env.example` each name a digest-pinned reference — the same one — and neither records the commit, the CI run, or the verification that produced it beyond what the release job's own summary prints. **They are now committed, so this is no longer an "uncommitted change" problem; it is a staleness problem.** Every merge to `main` publishes a new digest, so the committed values are stale by construction and will stay that way. **Take the digest from the release run's job summary (§3.3), never from a file in this repository.** The committed values exist so boot has a *safe* default, not so an operator has an *approved* one.

**9. ~~The deploy tooling is uncommitted.~~ RESOLVED.** §0.4. `scripts/deploy.sh`, `scripts/rollback.sh`, `scripts/verify-deployment.sh` and `scripts/lib/deploy-lib.sh` are **committed and tracked**, as are the `docker-compose.yml` and `.env.example` digest pins and the 321-line label addition to `.github/workflows/release.yml`. `scripts/` is clean in `git status`.

    **The residual risk is the host, not the repository.** `git pull --ff-only` on `/opt/lemondrop` can only deliver the tooling if the checkout is current **and** someone has pulled — and §9.5.1 establishes that an ordinary reboot does **not** pull. So a host can be running scripts that predate the tooling entirely, and that is invisible from the repository. **Confirm the host's copy directly** (§2.2, §4.4) rather than inferring it from the fact that the files are committed.

    This item deliberately states **no commit SHA**, deliberately. Naming `HEAD` here made the sentence wrong the moment it was written — which is what the deleted "the committed state of this repository is `8cddfe8`" did. **Read `git rev-parse HEAD` on the day you need it.**

**10. Whether the boot step 3 clone works is unresolved.** §2.3. `docs/boot-script.md:204-207` records it as failing on boot against a private repository, and `docs/verification.md:148` records the repository as private; §12 records a working deployed stack, which implies it succeeded at some point. **No tracked document asserts the repository is public, so this is an unresolved question rather than a contradiction between tracked documents** — and it is unresolved in the direction that matters, because a private repository is the recorded state. Check the host; do not assume.

**11. `README.md` and `RUNBOOK.md` contain Milestone 2 values that Milestone 3 superseded.** `RUNBOOK.md:53` still shows `-var app_instance_type=t3.micro`, while `docs/verification-milestone-3.md` §12.1 row 1 records the host running **`t3.small`**. Treat `RUNBOOK.md` as accurate for AWS access mechanics (which are what it is for) and `docs/verification-milestone-3.md` as authoritative for instance facts.

    **What has been done about the values this item covers, and what has not.** `RUNBOOK.md` is Milestone 2 era and carries **hardcoded, deployment-specific values that go stale silently** — the RDS endpoint, the master secret's ARN, the master username, the instance id, the ALB DNS name and the state-bucket name. **The three a second reader must have in order to read the database at all — the endpoint, the secret ARN and the master username — have been pointed at §7.1.1's discovery procedure rather than at a corrected value**, because a corrected value is a value that goes stale again and nothing detects it. **The remaining ones are still literal in that file**, and the honest position is the one this item already took: `RUNBOOK.md` is accurate for *mechanics*; §7.1.1 step 1 and §11 are the routes for *values*.

    **And one of them was not merely stale — it was wrong, and could not be reconciled.** The master username appeared in `RUNBOOK.md` and in `infra/variables.tf` with **two different values and nothing saying which was current**. §7.1.1 resolves it by route rather than by picking one: the authoritative source is `DBInstances[0].MasterUsername`, and the distinction that makes `variables.tf` the wrong place to look — **a Terraform input default is a fallback, not a record of what was applied** — is stated there in full. **`infra/variables.tf` is deliberately unchanged**, because it is not wrong: it says what the configuration would do with no input, which is a true and useful thing for it to say.

**12. No load, concurrency, or soak testing exists.** `docs/verification-milestone-3.md` §12.5 row 7: "No load profile, no concurrency measurement, no soak; CPU credits unmeasured at every size; the 15.55s observation is not a margin measurement." §12.5 row 7 is the qualifier row, and it carries these straight into §12.4 **items 2 and 3** — "Sustained and concurrent load are untested" and "CPU credit exhaustion on the `t3` family is UNMEASURED". ⚠️ **An earlier draft of this item cited "§12.4 item 7" for that quote. That names the wrong thing:** §12.4 item 7 is the negative control, and it is **RESOLVED**. `t3` instances deplete CPU credits under sustained cross-encoder scoring, and the failure mode is degraded latency rather than an error.

**13. The corpus is synthetic** (§12.4 item 6) and the probe is anchored to one document in it. `assert_probe_is_grounded` catches the corpus changing underneath the probe — that is all it does.

**14. The 204-byte `user_data` headroom** (§9.1) means the boot script is close to EC2's 16,384-byte ceiling. `docs/boot-script.md:520-528` gives the exact measurement command. Anything added to the heredoc must be measured, not eyeballed.

**15. ⚠️ UNSAFE AND UNVERIFIED — the legacy rollback branch of `rollback.sh` can start an image that is not the rollback target, and its own checks will not notice.** This is not a "may have issues" note, and nothing else in this section softens it. The branch is **defective by reading the code**, **has never been executed**, and **must not be rehearsed until it is fixed.** Fixing it is deliberately **out of scope for Milestone 4**; §6.4 and §6.5 are left exactly as written and this item is where the correction lives.

    **The defect, in three steps.** The legacy branch does two things that were mutually consistent when they were written and are not any more:

    1. It **re-tags** the rollback target under the bare local name — `rollback.sh:238`, `docker tag "$target" lemondrop-api`.
    2. It then **removes** the `API_IMAGE` key from `.env` — `rollback.sh:265-281`, which ends at `say "  removed the API_IMAGE key from .env (legacy wiring restored)"`.
    3. With `API_IMAGE` absent, compose interpolates its **default**, and that default is a digest-pinned GHCR reference — `docker-compose.yml:436`, `image: ${API_IMAGE:-ghcr.io/fvitorino00/lemondrop-api@sha256:0bdb7afa566bbff0c8db481cd78a048b130bb8fc8531739530d98fe3cde42986}`.

    **So the `docker tag` at `:238` is inert.** Compose is never asked to resolve the name `lemondrop-api` at all; it is handed the pinned default, and because the recreate at `rollback.sh:367` passes `--no-build`, the pinned digest is what the `api` container starts. The tag `:238` creates sits unused. The compose file says as much in the comment immediately above the pin — `docker-compose.yml:425-427`: *"the qualified digest below was already the default, so removing `build:` did not have to also change this line to be safe."*

    **The rationale is written into the script, and the script's own sentence is what makes this diagnosable.** `rollback.sh:229-231` says:

    ```
        # Legacy: .env goes back to having NO API_IMAGE key, so compose resolves the
        # `lemondrop-api` name again — exactly the M3 wiring. Pointing API_IMAGE at
    ```

    *"so compose resolves the `lemondrop-api` name again"* is **false against the current compose file**. The sentence holds only if the default at `docker-compose.yml:436` is the bare name, and it is not — it is a digest pin. **A comment that was correct when written is still a wrong instruction**, and this one now describes the failure rather than preventing it.

    **What the branch's own check looks at, and it is not the container.** `rollback.sh:246` computes the identity it goes on to report:

    ```
      restored_image_id="$(docker image inspect -f '{{.Id}}' "$target" 2>/dev/null || true)"
    ```

    On this branch `$target` is the **rollback tag** — `rollback.sh:173`, `target="$rollback_tag"` — not a container and not the image compose actually started. Nothing between `:238` and `:367` inspects the running container, and `:367` (`compose up -d --no-build --no-deps --force-recreate api`) is the only `compose up` in the script. So `:246` reports **what the operator asked for.** The comparison at `:251-263` can therefore print `say "  this is the image ID the adoption record pinned (${recorded_image_id})."` — `rollback.sh:253` — **while a different image is serving.** The check names an image ID and never asks which image is running.

    **Confirmed as asked, and the answer is worse than a weak check: when the record carries no `IMAGE_ID`, the comparison is SKIPPED ENTIRELY.** `rollback.sh:248` is `if [ -n "$restored_image_id" ] && [ -z "$recorded_image_id" ]; then`. What follows is prose, not a comparison — `:249-250` reports that the id *"is stated, not verified"*. The `elif` at `:251` is `elif [ -n "$recorded_image_id" ]; then`, so on a record with no `IMAGE_ID` **no comparison is attempted and no mismatch warning can be emitted from this block at all.** It is not a check that can fail; it is a branch that is never entered. `rollback.sh:150` reads that key from the **pre-rollback** record, so this is precisely the M3-era record §6.4 is about.

    **The rollback's own re-verification cannot see it either.** `rollback.sh:376` calls `verify_stack()`, which is `assert_probe_is_grounded`, then `wait_for_ready`, then `known_good_search` — `deploy-lib.sh:1093-1104`. **All three are content checks; none is an identity check.** A healthy service answering a grounded search is equally true of the wrong image, so a legacy rollback that started the pinned default would exit 0 and report success. The failure message at `rollback.sh:379` — `say "  The container is now running $target, which is what the record asked"` — asserts a property of a container nobody inspected.

    **The digest-bearing branch is UNAFFECTED, and it is the one that was verified in practice.** `rollback.sh:163-190` is the target-selection block: when `PREVIOUS_IMAGE_DIGEST` is non-empty it validates the digest (`:165`) and sets `target="$prev_digest"` (`:171`); only the `elif` at `:172` sets `legacy=1` (`:174`). The `docker tag` at `:238` sits inside `if [ "$legacy" -eq 1 ]` (`:228`) and **does not execute on the digest path at all.** That path writes `API_IMAGE` explicitly — `rollback.sh:292`, `env_set "$LEMDROP_APP_DIR/.env" API_IMAGE "$target"` — so compose resolves the digest and never the default. **This branch was exercised live: a real rollback to `sha256:6036f724…`, SSM command `4450c9b0-edd0-4d83-8632-3d64f9e72630`, SUCCESS.** Every rollback claim elsewhere in this runbook — §6.1, §6.2, §6.3, §6.5, §7.4 — selects that path and inherits that result. `docs/verification-milestone-4.md` is the record.

    **What might still catch it afterwards, and what is NOT ESTABLISHED.** A *separate* `scripts/verify-deployment.sh` invocation compares the record against the **running container** — `verify-deployment.sh:93` (`RUNNING_IMAGE_ID="$(running_image_id "$CID" || true)"`), `:149`, and `:203-215`. Because the pinned default carries `RepoDigests`, `RUNNING_DIGESTS` would be non-empty, that block's condition at `:203-204` would not be met, and control would reach the `else` at `:216` and print `DIVERGENCE`. **That is a reading of the code, not an observation: the legacy branch has never been executed, so nobody has watched it happen.** Treat it as a mitigation that is plausible and unproven — **not as a reason to go and run it.**

    **What to do instead, today.** Do not rehearse the legacy path — not on a throwaway host, not on a sacrificial one. §6.5's rehearsal is sound **for the digest branch**, and its step 4 ("Deploy revision B over revision A") writes a `PREVIOUS_IMAGE_DIGEST`, which is what selects the digest path; that is the rehearsal to run. Rehearing the legacy branch would mean deliberately constructing a record with no `PREVIOUS_IMAGE_DIGEST` plus a local rollback tag, and there is no reason to manufacture that state until the branch is fixed. Until it is: **treat `rollback.sh` on a legacy host as having no working rollback**, and make the digest path available on that host first (§7.1).

    **This item narrows §10 item 1, and only item 1.** Item 1 asserts that `deploy.sh`, `rollback.sh` and `verify-deployment.sh` "have never been executed against a host with a real Docker daemon". **That is no longer true** — they were executed live during Milestone 4, and `docs/verification-milestone-4.md` is the record — so of item 1's *"unexercised in CI and unexercised on a live host"*, only the CI half still stands. What remains unexercised is the legacy branch above, and the mutating control flow generally: **no test suite invokes any of the three scripts, and their first live use was this milestone.** Item 1 is left in place rather than rewritten, per the convention item 7 sets.

**16. ⚠️ UNFIXED — `deploy.sh` has no redundant-deploy guard, and deploying the digest that is already running destroys the rollback pointer.** Unlike item 15 this one is **not** a reading of code that has never run: **it was executed, on the live host, during Milestone 4.** `deploy.sh` was run twice against the same digest, and the second run overwrote `PREVIOUS_IMAGE_DIGEST` with the digest it had just deployed. The record became self-referential, and the intended previous image stopped being reachable through the normal path. `docs/verification-milestone-4.md` §8.2 is the record; §10 item 3 of that document carries it into the list of what its green verdicts do not mean.

    **The defect, at `file:line`.** Nothing in `deploy.sh` compares the target digest against the running image. `deploy.sh:944` reads `prev_digest="$(record_get IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"` from the record's **then-current** value, which on a redundant deploy **is the target**, and `deploy.sh:969` writes it back out as `"PREVIOUS_IMAGE_DIGEST=${prev_digest}"`. `PREVIOUS_IMAGE_DIGEST` is the rollback target (§4.6), so `rollback.sh:163-171` then selects the image that is running. The deploy still tags a rollback point (`deploy.sh:305-308`), pulls again (`deploy.sh:846`), rewrites `.env` (`deploy.sh:913`), recreates the `api` container (`deploy.sh:925`), verifies, and prints the green `DEPLOYED` banner — which ends in `Undo with: scripts/rollback.sh` (`deploy.sh:988`), a line that **cannot** be true of this record.

    **What to do about it today.** §4.2.1 is the operator-facing statement, placed before §4.3 for that reason: what to check before deploying, how to read `verify-deployment.sh`'s `── do they agree? ──` verdict for the purpose, and why `AGREE` — the *good* verdict — is the one that means "do not deploy this digest". **The check is manual because nothing performs it.** It is also the manual step that the same document's §11 pre-flight checklist assumes nobody has to think about, which is why it is called out here rather than left to §4.2.

    **Status: UNFIXED, and deliberately deferred.** No guard exists, none is in flight, and no fix is scheduled. Nothing in `deploy.sh` should be read as offering partial protection: the nearest candidate, `deploy.sh:855`, compares the **just-pulled** image's `RepoDigests` against the requested reference, and is an explanatory note that continues — not a redundancy check. Until this is fixed, **a redundant deploy is a manual-prevention-only hazard, and the image it orphans may still be recoverable from its timestamped rollback tag (§6.4) even though the record no longer names it.**

**17. ⚠️ There is no rehearsal host, and that is conditional on which variant of the second-engineer exercise is run.** §6.5 says to rehearse a rollback on a throwaway host and never on the one serving traffic, and item 1 above says the same. **This repository has never described such a host, never named one, and never stated whether one exists.** Nothing here provisions one and **nothing should be read as offering to.**

    **What it blocks, stated conditionally because the condition is not this repository's to settle.** `docs/second-engineer-acceptance.md` §3 defines two variants and **explicitly does not choose between them** — that decision is owed by the assessor, and it is open. Its consequence for this item:

    - **Under a cold-reader walkthrough (no deployment performed, nothing on any host touched), this item does not block anything.** The rehearsal never happens, because nothing is deployed and therefore nothing is rolled back. **The honest statement of the limitation still stands** — the runbook instructs an operator to rehearse somewhere it does not describe.
    - **Under a live deployment demonstration, it is blocking.** That variant ends in a rollback, and this item is about rehearsing rollbacks. An unbriefed second engineer following §6.5 literally has nowhere described to go.

    **What creating one would take, and why it is out of scope here.** A rehearsal host is infrastructure: an EC2 instance, or a second full stack under a different `var.environment` (`infra/variables.tf:47-55` constrains that to `dev`, `staging`, `prod`), with its own RDS instance, its own state key, and its own cost. **That is provisioning work, and it is not documentation.** It is recorded here as a limitation rather than solved, because a limitation that is written down can be planned for and one that is quietly assumed away cannot.

    **What is available today, without one.** The digest branch of the rollback was exercised live during Milestone 4 and is recorded in `docs/verification-milestone-4.md` §9 — which is evidence, and is **not** a substitute for a rehearsal on a disposable host. §6.5's step list is the procedure; what is missing is only somewhere to run it. **Do not rehearse on the serving host to work around this.** That is the one reading of §6.5 that is never correct.

**18. ⚠️ The provisioning-from-zero path has never been walked end to end.** `RUNBOOK.md` §2a–2c describes building the stack from nothing: bootstrap the state bucket, wire the backend literals, `terraform plan`, `terraform apply`. **No record in this repository shows that sequence being run once, start to finish, on a stack that did not already exist.** Every `terraform apply` that this repository documents evidence for was a **reconciliation** of an existing stack — `docs/verification-milestone-3.md` §12.1.1 row 20 records one as *"Already independently verified — no changes, exit 0"*, which is the opposite of a first apply.

    **Why it is a limitation and not an observation.** `docs/verification-milestone-4.md` §13.1 records that the milestone's acceptance sentence, read strictly, is in tension with this: *"a second engineer must be able to deploy a tested revision without manually reconstructing the original environment"*. **If that sentence is taken to include standing the infrastructure up from nothing, this item is the reason it is not yet closed.** Read as *"the original deployment steps"* — deploying a known artifact to a running host — this path is out of scope, and **§2.3, §3.4 and §6.5 describe that path completely.** The tension is recorded rather than resolved, per §13.1's own refusal to pick a winner.

    **What this does not affect.** Everything in §4 and §5. A deploy reaches an **existing** host; it does not build one. Nothing in this runbook's deploy path invokes Terraform.

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
- [ ] **Your commit is on `origin/main`, and its release run concluded green with `publish` not skipped** (§3.4). ⚠️ **An unpushed commit has no image — this box is the one that catches it.**
- [ ] You read the image's own `org.opencontainers.image.revision` and `org.lemondrop.alembic-head` labels off the digest you pulled (§3.4), and the revision label is your commit.
- [ ] You re-read the digest back and it matches, character for character, 64 lowercase hex.
- [ ] `docker manifest inspect <ref>` **succeeded** from a machine with no registry credentials — anonymous pullability confirmed **for this digest, today**. §10 item 7 records readability observed at verification time against an older digest; it is history, not a standing guarantee, and the package setting can change (§3.3).
- [ ] You looked at what the commit contains. You did not take the digest on trust.

### State before the change

- [ ] `verify-deployment.sh` has been run and its output read. You know whether it says `AGREE`, `DIVERGENCE`, or "no usable record".
- [ ] You have copied the current record somewhere off the host: `sudo cp /var/lib/lemondrop/deployed-revision.env /root/deployed-revision.before.$(date -u +%Y%m%dT%H%M%SZ)`.
- [ ] You have a rollback target: `PREVIOUS_IMAGE_DIGEST` is set, **or** `ROLLBACK_TAG` names an image present in `docker images`.
- [ ] You have read the recorded `ALEMBIC_HEAD`, and you know the head of your target revision.
- [ ] **If you are adopting or reconciling a baseline: you re-read the revision from the live database with §7.1.1, and you use the value you read — not the `0001` in this document, and not `ALEMBIC_HEAD`.**
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

# The live database's alembic revision — §7.1.1 carries the full procedure.
# Two lines of it, for the case where you already have the tunnel open and the
# credentials exported. It is a READ; nothing here writes to the database.
psql "host=$RDS_HOST hostaddr=127.0.0.1 port=$RDS_LOCAL_PORT user=$RDS_MASTER_USER dbname=$RDS_DB_NAME sslmode=verify-full sslrootcert=$CA_BUNDLE" \
  -c 'SELECT version_num FROM public.alembic_version;'

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
| Why migrations cannot run from EC2 | `infra/iam.tf`; `api/alembic/README.md` (the out-of-band migration procedure) |
| **How to read the live database's alembic revision** | **§7.1.1** — the complete procedure. `docs/verification-milestone-4.md` §5 is the recorded instance of it |
| What "a tested revision" means, and how to find its digest | §3.3, §3.4 |
| The milestone this work belongs to, and its acceptance criteria | `docs/verification-milestone-4.md` (§8–§9 for the deploy and rollback performed; **§13 for the acceptance criteria**) |
| The rollback decision table, in the script as well as here | `scripts/rollback.sh`, header block `── WHEN TO USE THIS, DECIDED IN ADVANCE ──` |
| Infrastructure access mechanics | `RUNBOOK.md` — **and read §10 items 11 and 17 before trusting a value in it** |
| Milestone 1 and 2 verification records | `docs/verification.md`, `docs/verification-milestone-2.md` |
| Local development | `README.md` |