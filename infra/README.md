# `infra/` — lemondrop AWS infrastructure (Phase 1: network foundation)

Terraform for the VPC, subnets, routing, and security groups that the lemondrop stack runs on. This directory is **Phase 1 only**. EC2, the Application Load Balancer, and RDS are Phase 2 and are deliberately **not** here — see [Scope](#scope).

> **This configuration has never been validated.** Terraform is not installed on the authoring machine, so `terraform init`, `validate`, `fmt`, and `plan` have **not** been run. The HCL was written carefully and cross-checked by hand (see the verification notes at the bottom), but "cross-checked by hand" is not "verified". Run `terraform validate` yourself before you trust it with money.

---

## Scope

| In this directory (Phase 1) | Not in this directory (Phase 2) |
|---|---|
| S3 state bucket (`bootstrap/`) | EC2 instance |
| VPC, IGW | Application Load Balancer |
| 2 public + 2 private subnets | RDS PostgreSQL instance |
| Route tables, conditional NAT gateway | IAM roles, instance profile |
| 3 security groups (`sg_alb`, `sg_app_ec2`, `sg_db`) | The ALB resource itself (`sg_alb` is here — the group is the security story) |

The split is deliberate. EC2, ALB, and RDS all consume the outputs in `outputs.tf`; building them here would have meant writing code against resources that did not exist yet and could not be verified. Nothing in this directory depends on Phase 2.

---

## The three-step operator workflow

### Step 1 — Bootstrap the state bucket (once, ever)

The main config uses an S3 backend. Terraform initialises the backend during `terraform init`, **before** it evaluates any resource — so the bucket the backend points at has to exist before this directory can run at all. The bucket cannot be created by the config that depends on it.

```bash
cd infra/bootstrap
terraform init
terraform apply -var 'state_bucket_name=lemondrop-tfstate-<your-account-id>'
terraform output state_bucket_name
```

Full rationale, the locking decision, and the DynamoDB fallback (if you are on Terraform < 1.10) are in [`bootstrap/README.md`](bootstrap/README.md).

### Step 2 — Point the backend at it, then `init`

Open [`versions.tf`](versions.tf) and replace the three literal values in the `backend "s3"` block with the outputs above:

```hcl
backend "s3" {
  bucket = "<state_bucket_name output>"   # ← edit this
  key    = "<state_key_prefix output>"    # ← edit this
  region = "<state_bucket_region output>" # ← edit this

  use_lockfile = true
  encrypt      = true
}
```

These must be **literal strings**. A backend block cannot reference variables, data sources, or locals — Terraform parses it before any of that exists. That copy-paste is a real, manual step; the bootstrap outputs exist to make it mechanical rather than guesswork.

Then:

```bash
cd infra
terraform init
```

### Step 3 — Set the required variable and plan

`allowed_api_cidr` has **no default** — deliberately. See [why](#why-does-allowed_api_cidr-have-no-default).

```bash
terraform plan \
  -var 'allowed_api_cidr=213.22.54.159/32' \
  -var 'state_bucket_name=unused-in-this-directory'  # not needed; bucket is in backend
```

```bash
terraform plan -var 'allowed_api_cidr=213.22.54.159/32'
terraform apply -var 'allowed_api_cidr=213.22.54.159/32'
```

If your home IP changes, re-run `apply` with the new value. That is the single change needed to regain access.

---

## 💰 COST WARNING

**With all three toggles at their defaults (all `true`), this stack bills roughly $65–100 per month.**

| Resource | Approximate monthly cost | Free Tier? |
|---|---|---|
| **NAT Gateway** | **~$32/mo + $/GB processed** | ❌ no |
| RDS PostgreSQL (Phase 2) | ~$15–25/mo | ❌ no |
| Application Load Balancer (Phase 2) | ~$16–20/mo + LCU charges | ❌ no |
| EC2 (Phase 2) | ~$5–15/mo depending on type | ⚠️ partially, and only in some regions |
| VPC, subnets, route tables, security groups, IGW | $0 | free |
| S3 state bucket | negligible at this size | ❌ no |

Three things that are commonly misunderstood and that this project will not pretend otherwise about:

1. **ALB and RDS are not covered by AWS Free Tier.** They bill continuously from creation until destruction.
2. **A stopped resource still bills.** Stopping an RDS instance or an EC2 instance does not stop its instance charge — only destroying it does.
3. **`terraform destroy` is how you stop the meter.** Not `terraform stop` (there is no such thing), not detaching, not leaving it idle. Destroy.

```bash
# stop the meter, in this order
cd infra            && terraform destroy
cd infra/bootstrap  && terraform destroy   # optional; the bucket costs ~nothing
```

Budget for the resources that exist but are idle. An idle NAT gateway still bills its ~$32/month in full.

---

## What each toggle costs, and what turning it off breaks

These three booleans in [`variables.tf`](variables.tf) are the cost-control mechanism. **Each one removes cost AND an acceptance criterion.** They are not free optimisations.

| Variable | Default | Cost when true | Turning it off removes |
|---|---|---|---|
| `enable_nat_gateway` | `true` | ~$32/mo + $/GB | The NAT gateway charge and its per-GB processing. It does **not** remove the private subnets' outbound path — see below. |
| `enable_managed_database` | `true` | ~$15–25/mo | The RDS acceptance criterion. The api has no datastore. |
| `enable_load_balancer` | `true` | ~$16–20/mo + LCU | The ALB acceptance criterion. No public entry point to the api at all. |

A plan with all three `false` costs almost nothing and **does not satisfy the milestone**. The resulting stack will not boot the application end to end. Set them knowingly, one at a time.

### 🔴 What `enable_nat_gateway = false` actually does to routing

This is the one toggle with a security consequence, not just a capability one.

When NAT is disabled, the private subnets' default route (`0.0.0.0/0`) points at the **internet gateway** instead of the NAT gateway. A subnet is private because of its **route**, not because of its name or its CIDR. So with that route in place:

- EC2 in the private subnet **can** pull images and download models directly. That is what the ~$32/month bought you instead.
- EC2 in the private subnet can also reach **any destination on the internet**, directly, sourcing from its own public IP.
- RDS in that subnet (Phase 2) is still **not publicly reachable** — `publicly_accessible = false` and the `sg_db` rule both still hold. But "not reachable" and "has no outbound path" are different properties, and after this change the second one is false.
- The only thing left between an instance there and the internet is the instance firewall. There is no longer a network layer behind it.

This is a deliberate cost trade, marked as such in `main.tf` next to the route that creates it. It is not an oversight. If the milestone's security story requires real egress isolation for the tier holding EC2 and RDS, leave this `true` and accept the $32/month.

**This was measured on a deployed instance, not inferred from the diagram.** With NAT disabled, an EC2 instance booted successfully, pulled a 263MB container image, and downloaded 340MB of model weights over this route. An earlier revision of this README's cost table claimed the opposite — that disabling NAT stops image pulls and model downloads. That claim was backwards, and the deployed stack disproved it.

---

## Why does `allowed_api_cidr` have no default?

A default would be a foot-gun with the worst possible failure mode.

```hcl
default = "0.0.0.0/0"   # a typo one day from exposing the API to the internet
```

That would still plan, still apply, and still pass a naive "is the ALB reachable?" check. Nobody would notice until someone else found it.

A **missing required variable** fails at the earliest possible moment — `plan`, before a single resource is created — with a message naming the variable. That is the correct failure mode for a security control: loud, early, impossible to miss. Comfortable defaults are for correctness settings, not safety settings.

There is also a `validation` block on it that **requires a single-host CIDR (`/32`)**. It is not enough to set `0.0.0.0/0` and be caught by a string comparison — a value like `0.0.0.0/1` or any `/16` is just as dangerous and would not be caught. The block parses the value and requires prefix length `32`, so anything broader than one host fails at `plan` with an explicit message. The deployed value is `213.22.54.159/32` and satisfies it.

---

## The inference services are structurally unreachable

The `embedder` and `reranker` do not appear anywhere in this stack. No security group, no ingress rule for port 8080, no subnet, no target group.

Grep `infra/` for `8080` and you get **comments only** — no security group rule, resource attribute, or target group anywhere in `infra/` references port 8080. The hits are prose explaining the absence, across `compute.tf`, `load_balancer.tf`, `security_groups.tf`, and this file. That is the design.

The milestone requires that they cannot be reached directly from the internet. That can be satisfied two ways:

- **(a) Write a rule forbidding it** — a deny rule, an empty-ingress group, an ALB listener that omits them.
- **(b) Build no path to them at all.**

This stack does **(b)**, which is strictly stronger. A deny rule is a statement about the present that someone can delete, widen by changing a port, or defeat by adding a broader allow rule in a later commit — and none of those would break anything visibly. An absent path has no such failure mode: to make the embedder reachable, someone would have to *add* a rule and a target. New resources, reviewable as new.

**The mechanism:** all three services run on one EC2 instance as Docker Compose services on an instance-local bridge network. Only `api` is attached to a host port — `docker-compose.yml` contains exactly one `ports:` key and it is on `api`. So the workers' port 8080 exists only inside the instance's own network namespace. Internet traffic is stopped by `sg_app_ec2` before it reaches the host; allowed traffic (ALB → 8000) lands on the `api` container only.

Structurally: the instance has **exactly one door** — port 8000, from the ALB, from your IP. The inference services are not behind that door; they are beside it, on a network the door does not lead to. The `api` reaches them as `http://embedder:8080` over Docker's embedded DNS, resolvable only from inside the instance.

**What would break it** (recorded so the next person knows what not to do):

- adding `ports: - "8080:8080"` to the `embedder` or `reranker` service
- adding a host port mapping on `api` that forwards at a worker
- adding a security group rule for port 8080 on `sg_app_ec2`
- adding an ALB target group pointing at port 8080
- binding a worker to `0.0.0.0` rather than the bridge interface

### The honest gap: unrestricted egress

`sg_app_ec2` has **unrestricted egress** (`0.0.0.0/0`, all protocols). It is required: the host must pull container images, install packages, and download GGUF model weights — without which `/embed` and `/rerank` cannot work at all.

**Terraform cannot restrict egress per container.** A security group attaches to an ENI; an ENI belongs to the instance, not to a container. All three Compose services share the host's single ENI and therefore share that one rule. There is no security-group configuration, in this repo or any other, that lets the `api` pull images while preventing the `embedder` from doing the same.

So that gap is **not closed**, and this README does not claim otherwise. What *is* true:

- No security group and no route in this stack grants the inference containers an **inbound** path. An outbound connection initiated by the embedder lands on an RFC1918 address inside the instance's own namespace and goes no further.
- The security group remains **deny-by-default on ingress**, so the unrestricted egress rule grants no new inbound reachability. It widens only the outbound direction, where the unanswerable question is "which container started this" — and such a connection is not useful to an attacker without a foothold on the instance already.

True per-container egress filtering would need host-level tooling (Docker's `DOCKER-USER` iptables chain, `docker network disconnect`, per-container egress proxies). Those are operational controls on the instance, not infrastructure-declared controls, and this config does not provide them.

---

## Known limitations

Stated plainly rather than left to be discovered:

| Limitation | Why | Fix |
|---|---|---|
| **No TLS.** The load balancer is port 80 HTTP only. `/embed` and `/rerank` payloads travel in cleartext. | No TLS certificate can be issued for a domain that does not exist yet. | ACM certificate + a 443 listener + a 80→443 redirect listener. Required before any real use with real data. |
| **NAT is single-AZ.** One gateway in the first AZ, not one per AZ. | ~$32/mo vs ~$64/mo. For a dev stack with one instance, one is enough; the asymmetry is an accepted availability risk. | One NAT gateway per AZ. Not a trivial change — each private route table must target its own zone's gateway. |
| **Unrestricted `sg_app_ec2` egress.** | Required for image/package/model pulls. | Host-level iptables. See above. |
| **`sg_db` has no egress at all.** | A managed database does not need outbound access for this application. Deny-all is correct and free. | Add an explicit narrow rule if Phase 2 needs RDS to reach an external endpoint. |

---

## Verification status

**No Terraform command has been run.** Terraform is not installed on the authoring machine and there are no AWS credentials there. `init`, `validate`, `fmt`, `plan`, and `apply` have all not been executed.

What was done instead, by hand:

1. Every `var.*` reference in `*.tf` was grepped and confirmed to be declared in `variables.tf` — and every variable in `variables.tf` confirmed to be used.
2. Every `aws_vpc.`, `aws_subnet.`, `aws_security_group.`, `aws_nat_gateway.`, `aws_internet_gateway.`, `aws_route_table.`, `aws_eip.`, `aws_route.`, `aws_route_table_association.` reference was cross-checked against the resource blocks actually written — no dangling references.
3. File inventory and line counts recorded.

Hand-checking catches typos and missing declarations. It does **not** catch type errors, provider schema violations, invalid argument names, or backend misconfiguration. Run `terraform init && terraform validate` as your first action, and treat any error you find as real.
