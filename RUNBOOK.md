# RUNBOOK — lemondrop AWS infrastructure

Operational runbook for the Milestone 2 AWS stack. All commands assume the
`lemondrop` AWS profile and region `eu-west-1`.

> ⚠️ **READ `docs/deployment.md` BEFORE YOU TRUST A VALUE IN THIS FILE.**
>
> This is a Milestone 2 document and it is kept for what it is — the AWS access
> mechanics (bootstrap, backend wiring, SSM, teardown) — which have not been
> superseded. **Its hardcoded infrastructure values are M2-era records, not
> configuration**, and one of them (the RDS master username) is not merely stale
> but contradicts another file in this repository. Discover values; do not copy
> them. `docs/deployment.md` §1.1, §1.3, §7.1.1 and §10 item 11 are the routes.
>
> **And which values, specifically, so that "discover, do not copy" is actionable
> rather than a slogan.** Five literals remain in this file. None of them is the
> authority for anything, and each has a route:
>
> | Literal still written here | Where | Why it is not the authority | Route to the real value |
> |---|---|---|---|
> | the instance id | §4, §5 | the M2 record of the host `lemondrop-dev` ran on | `docs/deployment.md` §7.1.1 step 1 — `describe-instances` filtered on the `Role=application-host` tag, which `infra/compute.tf` sets |
> | the ALB DNS name | §3 | the same M2 record | `docs/deployment.md` §5.3 — `elbv2 describe-load-balancers --names <name_prefix>-alb` |
> | `lemondrop-tfstate-filipe` | §2a, §2b | a bucket name recorded once, in one account | `aws s3api list-buckets`, and the `bucket` argument at `infra/versions.tf:42`, which is the value `terraform init` actually reads |
> | `213.22.54.159/32` | §2c | your address is not the address you had in Milestone 2, and a wrong one locks you out of the API rather than failing loudly | `infra/variables.tf`'s `allowed_api_cidr` — **no default on purpose** — is where the rule lives: read your own address at apply time |
> | `t3.micro` | §2c, §2c's variable table | the host was resized after this was written | `aws ec2 describe-instances … --query 'Reservations[].Instances[].InstanceType'` |
>
> **None of these five is an input to a deploy, a verification or a rollback**, and
> no procedure in `docs/deployment.md` requires a value from this file. The first two
> were required by it once and no longer are — §1.1 and §5.3 discover both. The last
> three are inputs to §2's `terraform plan` / `apply`, which is the provisioning path,
> and `docs/deployment.md` §10 item 18 records that no procedure in this repository
> invokes Terraform at all.
>
> **What `docs/deployment.md` does cite this file for:** AWS access *mechanics* — the
> profile and region in the header, the CLI prerequisite, the SSM command pair — and the
> RDS CA bundle URL. Both survive a value going stale. §10 item 11 of that document
> cites one value here, `app_instance_type`, **as the example of a stale one**, which is
> the opposite of depending on it.

## 1. Prerequisites

- Terraform >= 1.10
- AWS CLI v2, configured with a `lemondrop` profile
- `jq` and `psql` (PostgreSQL client) on the operator machine
- `openssl` and `curl`, for the RDS CA bundle (`docs/deployment.md` §7.1.1)
- `secretsmanager:GetSecretValue` on **the RDS master secret**, on **your own
  principal** — the EC2 instance role does not have it and must not be given it
  (`docs/deployment.md` §1.3, §7.1.1)
- The Session Manager plugin for the AWS CLI, for §4's `start-session`
- The repository must be reachable from the EC2 instance (public repo, or a
  deploy mechanism such as a pre-baked AMI or Systems Manager package)

## 2. Deploy

> **AWS profile note (2026-10-22):** the `[default]` login session expired on
> 2026-10-17 and is unrecoverable without an interactive `aws login`. Until the
> default session is restored, AWS operations need `AWS_PROFILE=lemondrop`.

### 2a. Bootstrap the S3 state bucket (one-time)

```bash
cd infra/bootstrap
terraform init
terraform apply
```

This creates `lemondrop-tfstate-filipe` with versioning, encryption, public
access blocked, and native locking.

### 2b. Wire the backend literals

Edit `infra/versions.tf` and set the backend block to:

```hcl
terraform {
  backend "s3" {
    bucket       = "lemondrop-tfstate-filipe"
    key          = "lemondrop/dev/terraform.tfstate"
    region       = "eu-west-1"
    use_lockfile = true
  }
}
```

### 2c. Plan and apply the main stack

```bash
cd infra

terraform init

terraform plan \
  -var allowed_api_cidr=213.22.54.159/32 \
  -var enable_nat_gateway=true \
  -var app_associate_public_ip=false \
  -var app_instance_type=t3.micro

terraform apply \
  -var allowed_api_cidr=213.22.54.159/32 \
  -var enable_nat_gateway=true \
  -var app_associate_public_ip=false \
  -var app_instance_type=t3.micro
```

Variable reference:

| Variable | Value used | Meaning |
|---|---|---|
| `allowed_api_cidr` | `213.22.54.159/32` | Operator IP — the only source allowed to reach the API on port 80 |
| `enable_nat_gateway` | `true` | Private subnets route outbound through a NAT gateway |
| `app_associate_public_ip` | `false` | EC2 has no public IP — reachable only via ALB |
| `app_instance_type` | `t3.micro` | Dev-sized instance |

## 3. Verify it works

```bash
# 1. ALB health — expect HTTP 200 and {"status":"ok","embedder":"ok","reranker":"ok"}
curl -i http://lemondrop-dev-alb-285677848.eu-west-1.elb.amazonaws.com/health

# 2. RDS reachability over TLS — expect the query to return 1
#
# ⚠️ THE THREE VALUES BELOW ARE MILESTONE 2 ERA AND ARE NOT THE AUTHORITY.
#    The endpoint hostname, the master secret's ARN and the master username are
#    ALL DISCOVERED from AWS, and the procedure that discovers them is
#    docs/deployment.md §7.1.1. Read that section; it also carries the
#    SSM port-forwarding tunnel this connection needs (RDS is not reachable
#    from the internet), the CA bundle check, and the `host`/`hostaddr` split
#    that keeps sslmode=verify-full meaningful through the tunnel.
#
#    This block used to carry all three literally — the endpoint hostname, the
#    master secret's ARN and the master username — and they have been replaced by
#    placeholders on purpose. The username is not merely stale: it is in conflict
#    with the Terraform input default in infra/variables.tf, and neither one is
#    authoritative. A Terraform input default is a FALLBACK, not a record of
#    what any apply was run with. The only authoritative source is the RDS
#    instance itself:
#
#      endpoint, port, db name, master secret ARN, master username
#        <- aws rds describe-db-instances --db-instance-identifier <id> \
#              --query 'DBInstances[0].{h:Endpoint.Address,p:Endpoint.Port,
#                       d:DBName,s:MasterUserSecret.SecretArn,u:MasterUsername}'
#
#    Hardcoding any of them here is what made them go stale silently.
psql "host=<rds-endpoint-from-describe-db-instances> hostaddr=127.0.0.1 port=<local-tunnel-port> \
  user=<master-username-from-describe-db-instances> dbname=<db-name> \
  sslmode=verify-full sslrootcert=<path-to>/rds-global-bundle.pem" \
  -c "SELECT version_num FROM public.alembic_version"

# 3. Inference port must be closed — expect timeout / connection refused
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/<instance>/8080'
```

## 4. Connect to the instance

No SSH key, no public IP, no bastion. Use SSM Session Manager:

```bash
aws ssm start-session --target i-0c3155b1b6bb31298
```

## 5. Read the boot log

```bash
aws ssm send-command \
  --instance-ids i-0c3155b1b6bb31298 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["tail -n 100 /var/log/lemondrop-boot.log"]'

aws ssm get-command-invocation \
  --command-id <command-id-from-send> \
  --instance-id i-0c3155b1b6bb31298
```

Terminal verdicts:

| Verdict | Meaning |
|---|---|
| `=== lemondrop boot: SUCCESS — api healthy after 10s ===` | All steps completed and the API responded to a health check |
| `FAILED at line N` | The script halted at step N; the log above the verdict has the cause |
| `FINISHED WITH WARNINGS` | Boot completed but a non-critical step reported a problem |

## 6. Tear down

```bash
cd infra

# 1. Disable RDS deletion protection (destroy will fail otherwise)
terraform apply -var db_deletion_protection=false -var db_skip_final_snapshot=true

# 2. Disable ALB deletion protection (destroy will fail otherwise)
terraform apply -var lb_enable_deletion_protection=false

# 3. Destroy
terraform destroy \
  -var db_deletion_protection=false \
  -var lb_enable_deletion_protection=false
```

The `db_skip_final_snapshot=true` in step 1 prevents a costly final RDS snapshot.
The NAT gateway is released by the destroy — verify none remain in the console.

> ⚠️ **A note on the flag name, because this section used to get it wrong.** The
> variable is `db_skip_final_snapshot` (`infra/variables.tf:781`), not
> `skip_final_snapshot`. The earlier spelling would have failed the apply with
> "value for undeclared variable" — a guard that never fires is worse than no
> guard, so it is corrected here rather than left as written. If you are reading
> a historical transcript that used the old spelling, that is what went wrong.

> ⚠️ **This section is documentation. Nothing in the documentation pass that
> added §6.1–6.4 ran `terraform destroy`, `terraform apply` or `terraform plan`.
> The commands are recorded to be run by an operator, and must be read against
> the destroy plan (§6.1) before they are run.**

### 6.1 Inspect the destroy plan before you destroy

Read the destroy plan and confirm which **billable** resources it removes,
*before* disabling the protection flags and running destroy. Terraform is not
invoked in this repository's documentation, so this is a documented command, not
one that was run:

```bash
cd infra
terraform plan -destroy \
  -var db_deletion_protection=false \
  -var db_skip_final_snapshot=true \
  -var lb_enable_deletion_protection=false
```

Check the plan lists, at minimum: the **ALB** and its listener/target group, the
**NAT gateway** and its **Elastic IP**, the **RDS instance**, and the **EC2
instance** (with its EBS root volume, `delete_on_termination = true`,
`infra/compute.tf:188-203`). The right cross-check is the tag this stack puts on
every taggable resource — `ManagedBy = "terraform"` (`infra/locals.tf:43-49`). If
a billable resource is *not* in the plan, it will keep billing after you think
you have stopped: see `COSTS.md` → [What survives `terraform destroy`](COSTS.md#what-survives-terraform-destroy).

**What the plan will NOT show, and why.** With `db_skip_final_snapshot=false`
(the default) a destroy leaves a **final RDS snapshot** behind. That snapshot is
created *by* the destroy and is not a resource in the configuration, so it never
appears in a destroy plan and Terraform will not remove it. It bills until
deleted by hand. Passing `db_skip_final_snapshot=true`, as above, skips it.

### 6.2 Preserve the evidence before teardown

**The distinction the milestone requires: teardown removes the billable *lab
resources*; it must not destroy the *evidence retained in Git*.** These are two
different storage locations and the destroy only touches one of them.

**Evidence retained in Git — survives teardown by construction.** The destroy
targets AWS, not the repository. These tracked files are unaffected:

- the verification records — `docs/verification-milestone-2.md` … `-4.md`,
  `docs/verification.md`;
- the incident records — `INCIDENTS.md` (and any records added to it);
- the cost record — `COSTS.md`, including its observed-bill facility;
- the operational docs — this file, `docs/architecture.md`,
  `docs/end-to-end-demo.md`, `docs/deployment.md`.

**Evidence that lives only on the host — dies with the EC2 instance.** Copy it
off *before* teardown if it is evidence, not infrastructure:

| Path | What it holds | Why it is at risk |
|---|---|---|
| `/var/lib/lemondrop/diagnostics/` | timestamped read-only diagnostic reports | destroyed with the instance; `docs/verification-milestone-4.md` §12.4 records one such report that was produced and **not retained** |
| `/var/lib/lemondrop/deployed-revision.env` | the revision record — "what is running?" | destroyed with the instance; it is host state, not source |
| `/var/log/lemondrop-deploy.log` | the deploy/rollback log | destroyed with the instance |
| `/var/log/lemondrop-boot.log` | the boot log | destroyed with the instance |

The line the milestone draws: **the record of what happened is evidence and must
be preserved; the instances that produced it are lab resources and may be
destroyed.** Pull the four paths above off the host, decide which are evidence,
and retain those in Git (or wherever the operator keeps records) **before**
running destroy. A report you did not copy out is a report you no longer have.

**The Terraform state is a third thing and is neither.** It lives in the S3
bucket `lemondrop-tfstate-filipe` (`infra/versions.tf:41-58`), which is created
by `infra/bootstrap` and **is not destroyed by this stack's destroy**. It is
bookkeeping, not evidence — but it is also what lets a later `apply` know what
exists, so leave it unless you mean to discard the stack entirely.

### 6.3 Verify the removal afterwards

After the destroy, verify the billable resources are actually gone. The routes
below use the same discovery patterns the rest of this file uses; none was run in
this pass:

```bash
# ALB — expect an error or null when the stack is gone
aws elbv2 describe-load-balancers --names lemondrop-dev-alb

# NAT gateway — expect no available gateways for this stack
aws ec2 describe-nat-gateways --filter Name=tag:Project,Values=lemondrop

# EC2 instance — expect none carrying the host's own tag
aws ec2 describe-instances --filters Name=tag:Role,Values=application-host

# RDS — expect DBInstanceNotFound
aws rds describe-db-instances --db-instance-identifier lemondrop-dev-postgres

# Elastic IPs — an unassociated EIP bills; expect none left from this stack
aws ec2 describe-addresses --filters Name=tag:Project,Values=lemondrop
```

**The two checks most people skip, and should not:**

- **The final RDS snapshot.** `aws rds describe-db-snapshots --snapshot-type manual`
  — if one survives and the data is not wanted, delete it, or it bills forever
  (`COSTS.md` → [What survives `terraform destroy`](COSTS.md#what-survives-terraform-destroy)).
- **A stray Elastic IP.** The stack's EIP is released by destroy, but a
  manually-allocated one elsewhere in the account is not, and an unassociated
  EIP bills on an hourly rate.

### 6.4 The deletion-protection flags that block a destroy

Two flags default to `true` and make a plain `terraform destroy` **fail**. They
are guards against an accidental destroy pointed at the wrong workspace, and
they are the most common "why is my destroy failing" moments in this stack.

| Flag | Default | Where it is set | Failure if not disabled |
|---|---|---|---|
| RDS `db_deletion_protection` | `true` | `infra/variables.tf:751-754` | destroy fails with `DBInstanceCannotBeDeleted` |
| ALB `lb_enable_deletion_protection` | `true` | `infra/variables.tf:873-876` | destroy fails on the load balancer |

The `-var …=false` overrides in steps 1–3 above disarm both for the run. The RDS
one protects **data** (a database nobody marked disposable); the ALB one protects
only the entry point (`infra/load_balancer.tf:69-79` says so, and notes that
nothing is lost when the ALB is recreated). Disarm the data-protecting one
deliberately, having decided what happens to the data.

## 7. Troubleshooting

Symptom → cause → fix for every failure hit during the M2 deployment.

| Symptom | Cause | Fix |
|---|---|---|
| `curl` not found on the instance | Minimal AL2023 image ships without curl | Use `dnf install curl` or test with `wget`/`bash /dev/tcp` |
| `dnf` conflicts with `cloud-init` package runs | Both touch the package manager simultaneously | Serialize: wait for `cloud-init` to finish (`cloud-init status --wait`) before running `dnf` |
| `docker` not available via `dnf install docker` | AL2023 does not package `docker` in the default repos | Install via `amazon-linux-extras install docker` |
| EC2 rejects `user_data` — size limit | EC2 `user_data` hard limit is 16,384 bytes; the original script was ~25KB | Split the rationale into `docs/boot-script.md` and keep the script itself at 15,068 bytes |
| `git clone` of the app repo fails from the instance | The repo is private and the instance has no credentials | Make the repo public, or bake the app into a Golden AMI, or use SSM to push a package |
| `terraform validate` rejects the SG CIDR | CIDR must be a `/32` to be a valid single-host rule | Use `213.22.54.159/32`, not a bare IP |
| Password comes back as a JSON object, not a string | Secrets Manager stores the secret as a JSON blob | Extract with `jq -r .password` — and never with `PGPASSWORD=… psql`, which puts the password in the shell history and in every `ps` on the machine. `docs/deployment.md` §7.1.1 |
| `psql` fails with a TLS verification error | The RDS CA bundle is missing on the instance | Download `https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem` and point `sslrootcert` at it |
| `AccessDeniedException` reading the master secret | The instance role holds the **application** credential only, not the RDS master secret | This is the control working, not a fault. `infra/iam.tf` grants `secretsmanager:GetSecretValue` on one ARN and it is not the master one; `docs/verification-milestone-3.md` records the denial as a PASS. Read the master secret from **your own** principal, which needs its own grant. `docs/deployment.md` §7.1.1 |
| `ResourceNotFoundException` reading the master secret | The ARN never resolved — wrong region, wrong account, or you read `/…/db/secret-arn` (which holds the **application** ARN) instead | Fix the ARN source. **This is not the same as `AccessDenied`** and must not be reported as one |

## 8. Monitoring — what to watch, and what "healthy" looks like

This stack has **no alerting**. A `grep` of `infra/` for
`aws_cloudwatch_metric_alarm` returns nothing, and **ALB access logs are off**
(`lb_access_logs_enabled` defaults to `false`, `infra/load_balancer.tf:81-115`).
Monitoring here is **pull-based**: you look, and nothing pages you. That is a
known limitation, not a plan.

### 8.1 What "healthy" looks like

| Signal | Healthy value | Where |
|---|---|---|
| Containers | all three `(healthy)` | `docker compose ps` on the host |
| API readiness | `GET /health` → 200, `{"status":"ok","embedder":"ok","reranker":"ok"}` | `docker compose` healthcheck, the ALB health check, and by hand |
| API + database | `GET /health/ready` → 200 with `"database":"ok"` | the route itself; see `README.md` [API routes](README.md#api-routes) |
| Deployed identity | `verify-deployment.sh` → **AGREE** (or `UNPINNED (LEGACY)` on an adopted M3 host) | `scripts/verify-deployment.sh` |
| `llama.cpp` workers | `/health` on 8080 answers 200 inside the container | `scripts/diagnose.sh` |

**`/health` and `/health/ready` answer different questions, and both can be true
at once.** With the database down, `/health/live` returns 200 and `/health/ready`
returns 503 — the process is fine, its dependency is not. Read the pair, not one
of them.

### 8.2 ⚠️ 503s during boot are EXPECTED, not a fault

A fresh instance downloads ~340MB of model weights before the API can answer.
The ALB target group tolerates at most `10 × 30s = 5 minutes` of failures, and
the boot can exceed that — so **the ALB will return 503s during a cold boot and
recover on its own.** Every outside-the-instance diagnostic reports "unhealthy
application", because that is what the ALB is observing.
`infra/load_balancer.tf:122-217` is the full explanation; the evidence that
settles it is inside the instance. **Do not start changing API code over a
boot-time 503.**

### 8.3 Where the logs are

| Log | Path / command | Holds |
|---|---|---|
| Boot | `/var/log/lemondrop-boot.log`, `/var/log/cloud-init-output.log` | the boot script and its terminal verdict |
| Deploy / rollback | `/var/log/lemondrop-deploy.log` | the `deploy.sh` / `rollback.sh` log |
| Containers | `docker compose logs [--tail=50] [--since 5m] [-f <svc>]` | per-service output; `json-file`, rotated at `10m` × 3 |
| Diagnostics | `/var/lib/lemondrop/diagnostics/` | timestamped read-only reports (`scripts/diagnose.sh`) |
| Database | CloudWatch Logs — RDS exports `postgresql` and `upgrade` | Postgres server log and engine-upgrade events (`infra/database.tf:263-280`) |
| ALB | **none.** Access logs off; metrics exist in CloudWatch but **no dashboard or alarm is configured** | — |

The read-only pair to reach for first is `scripts/verify-deployment.sh` (what is
this host running?) then `scripts/diagnose.sh` (are the services and the database
reachable?). Both are safe on a host that is on fire, mid-deploy, or never
deployed to. Their full inventory — including what each does **not** tell you —
is `INCIDENTS.md` §6.2.

## 9. Restart — distinct from deploy and rollback

A restart changes **nothing about what is running**. It is neither a deploy (a
new artifact) nor a rollback (a previous artifact), and it must not be reached
for when either of those is the actual remedy. What it does is stop and start a
process, on the same image.

| What you want | Command | What it does / does not do |
|---|---|---|
| Restart one container | `docker compose restart <service>` | Stops and starts that container on the same image. **Reloads its model from disk** if it is `embedder` or `reranker` (tens of seconds), and changes its container id. |
| Recreate one container | `docker compose up -d --force-recreate <service>` | Replaces the container. The deploy/rollback scripts recreate **only `api`** this way; the workers' ids must not change across a deploy (`docs/deployment.md` §6.5 step 5). |
| Restart the whole stack | `docker compose restart` | All services, same images. `depends_on: service_healthy` is not re-evaluated by a plain restart. |
| Reboot the host | `aws ec2 reboot-instances --instance-ids <id>` | Ordinary reboot. **Does not re-run `user_data`** (`docs/deployment.md` §9.5.1) and **does not re-pull the image**. |
| Stop / start the host | `aws ec2 stop-instances` / `start-instances` | A **stop/start was never tested** for `user_data` behaviour (`docs/deployment.md` §10 item 5) and can change the host's public IP if it has one. Prefer a reboot. |

Three rules that keep a restart from becoming an incident:

1. **Restart the smallest thing.** An unresponsive `api` is a container restart,
   not a host reboot — and a host reboot is not a deploy.
2. **A restart is not a rollback.** If the API is up but returning wrong
   results, restarting it changes nothing. That is a correctness problem: see
   `docs/deployment.md` §4.1's decision table before choosing rollback.
3. **`restart: unless-stopped`** is already set on every service
   (`docker-compose.yml`), so containers come back after a host reboot on their
   own. A container that is *crash-looping* is exiting repeatedly — read its logs
   (`--since 5m` is the one for a restart loop) rather than restarting it again.

**What a restart never fixes.** It does not change the image, does not rewrite
the record, and does not re-pull a digest. If the symptom is "the host is running
an image the record does not name", that is `verify-deployment.sh`'s DIVERGENCE
verdict and the remedy is a deploy — not a restart.
