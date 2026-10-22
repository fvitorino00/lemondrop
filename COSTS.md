# COSTS — lemondrop AWS infrastructure

Cost reference for the AWS stack. Region `eu-west-1`, on-demand pricing. All
figures below are **estimates for an always-on deployment** — the *expected*
column. **No figure in this file has been read off a real bill.** The section
[Observed cost](#observed-cost--unverified--not-yet-observed) is the place that
will hold real numbers once a bill exists, and it is empty on purpose.

> **Audited for Milestone 5.** The M5 work is operating, troubleshooting,
> recovering and dismantling this system, so this file now also records **what
> keeps billing while idle**, **what survives a `terraform destroy`**, and the
> **budget-evidence gap**. Nothing here is a new estimate; the per-resource
> table is the M2 estimate, kept as the expected column.

## Per-resource breakdown — EXPECTED (estimates, not observations)

| Resource | Estimate | Notes |
|---|---|---|
| ALB | ~$16/mo + LCU | Bills per hour regardless of traffic; LCU charges on top |
| NAT gateway | ~$32/mo + per-GB | Bills per hour plus data-processing per GB |
| RDS db.t3.micro | ~$17/mo | Instance + storage |
| EC2 t3.small | ~$16.64/mo | |
| EBS 30GB gp3 | ~$3/mo | |
| **Total** | **~$82/mo** | |

**These line items carry a caveat, and are left as written rather than silently
corrected**, because the brief for M5 is to audit and name the gap, not to
re-estimate:

- **EC2 was `t3.micro` at `~$9/mo`; corrected to `t3.small` at `~$16.64/mo`.**
  `var.app_instance_type` defaults to **`t3.small`**
  (`infra/variables.tf:259-262`), and `docs/verification-milestone-3.md` §12.1
  records the host running `t3.small`. The stale t3.micro figure understated
  the EC2 line by roughly $7.64/month, and the total line was understated by
  the same amount (corrected above from ~$74/mo to ~$82/mo). Only a bill
  settles the exact figure.
- **The EBS size matches, the number may not.** The root volume is
  `var.app_root_volume_size = 30` GiB gp3 (`infra/variables.tf:522-525`,
  `infra/compute.tf:188-203`), so `30GB gp3` is right; the `~$3/mo` figure is an
  estimate and is not labelled as observed.

## Observed cost — PARTIALLY OBSERVED

A billing record has been read, but the period is open and the record is
estimated. Do not read a derived estimate as an observed charge.

| Line item | Expected (from the table above) | **Observed (from a real bill)** | Period | Source of the observation |
|---|---|---|---|---|
| ALB | ~$16/mo + LCU | AWS Cost Explorer total BlendedCost ≈ $0.00 (near-zero, negative by sub-penny rounding) | 2026-10-01 to 2026-10-21 inclusive (Cost Explorer end exclusive) | `aws ce get-cost-and-usage`, account 615105803772, `Estimated: true` (`~/lemondrop-investigation/OBSERVED-COST-EVIDENCE.txt` §4) |
| NAT gateway | ~$32/mo + per-GB | included in near-zero total above | same | same |
| RDS | ~$17/mo | included in near-zero total above | same | same |
| EC2 | ~$16.64/mo (t3.small; was stale t3.micro ~$9/mo) | **EC2 compute line shows $0.00** in Cost Explorer despite a t3.small running since 2026-10-13; discrepancy unexplained by the read | same | same |
| EBS | ~$3/mo | included in near-zero total above | same | same |
| S3 state | ~$0 | included in near-zero total above | same | same |
| Other / adjustments | — | included in near-zero total above | same | same |
| **Total** | **~$82/mo** | **Near-zero estimated total** (BlendedCost -0.0000000508 USD, UnblendedCost -0.0000000319 USD, AmortizedCost -0.0000000319 USD) | 2026-10-01 to 2026-10-21 inclusive | AWS Cost Explorer GetCostAndUsage, `Estimated: true` |

**DERIVED-ESTIMATE-NOT-A-BILL (do not enter as observed):** for the EC2 t3.small
running since 2026-10-13, 198.5920 h × $0.0228/h = ~**$4.53**. This is an
arithmetic cross-check, not a billing record; it disagrees with the Cost Explorer
read, which is the point of keeping both. A closed-period invoice is required to
settle the column (`~/lemondrop-investigation/OBSERVED-COST-EVIDENCE.txt` §5, §7, §8).

To make a row real: read the figure off an AWS Cost Explorer or billing export,
record the **period it covers** and the **exact source** (so a reader can
re-check it). An "observed" figure with no period and no source is an estimate
wearing the wrong label.

## Credit situation

$120 in AWS credits are available and expire **April 4, 2027**. At the
estimated ~$82/mo burn, that covers roughly **1.5 months**. Plan to tear down
or secure ongoing funding before the credits lapse.

## What bills vs. what is free

**Bills per hour regardless of traffic:**

- ALB
- NAT gateway
- RDS
- EC2
- EBS

**Free (no hourly charge):**

- VPC
- Subnets
- Security groups
- IAM roles and policies
- S3 state storage

**Creates a recurring charge that outlives its resource:**

- An RDS **final snapshot** — created on destroy because `db_skip_final_snapshot`
  defaults to `false`. See [below](#what-survives-terraform-destroy).

## Cost toggles

Three variables change the monthly total. Each is a trade, not a free saving.

| Variable | Default | If changed | Effect |
|---|---|---|---|
| `enable_nat_gateway` | `true` | `false` | Saves ~$32/mo + per-GB. Private subnets route via the IGW instead — egress isolation is gone. Instances need a public IP for the route to work. |
| `enable_managed_database` | `true` | `false` | Saves ~$17/mo. RDS is not provisioned; the application has no database. |
| `enable_load_balancer` | `true` | `false` | Saves ~$16/mo + LCU. No ALB; the API is unreachable from the internet. |

## Stopping vs. destroying RDS

Stopping the RDS instance (not destroying) halts the instance compute charge
but **storage continues to bill**. For a dev stack you are not using, a stop is
a partial saving; a destroy is the only way to stop all RDS charges. Remember
that `deletion_protection=true` will block a stop/destroy until disabled.

## What continues to bill while idle — verified against the Terraform

Each line below was read from the configuration, not assumed. The estimate
column is the expected figure; none is observed.

| Idle resource | Bills while idle? | Verified at |
|---|---|---|
| **ALB** | Yes — hourly, whether or not any request arrives | `infra/load_balancer.tf:38-120` |
| **NAT gateway** | Yes — hourly, plus per-GB processed; an idle gateway bills in full | `infra/main.tf:254-284` |
| **NAT Elastic IP** | Yes while allocated (an unassociated EIP bills on an hourly rate). Managed by Terraform, so a destroy releases it — see below. | `infra/main.tf:233-252` |
| **RDS instance** | Yes — hourly | `infra/database.tf:92-172` |
| **RDS storage** | Yes — **even after the instance is stopped**; a stop halts compute, not storage | `infra/database.tf:113-127`, this file [above](#stopping-vs-destroying-rds) |
| **EC2 instance** | Yes while running; a **stopped** instance does not bill instance hours | `infra/compute.tf:154-177` |
| **EBS root volume** | Yes — **including while the instance is stopped**; the volume bills until it is deleted (or terminated with the instance) | `infra/compute.tf:188-203` |
| **S3 state bucket** | Yes, but negligible at this size (a tiny object plus versioning) | `infra/versions.tf:41-58` |

**A trap worth naming:** a **stopped** EC2 instance is *not* a saving on its
storage. The instance-hour stops, the EBS volume does not. The same shape
applies to a **stopped** RDS instance — the instance-hour stops, the storage does
not. Neither a stop nor a "detach" is how you stop the meter; only a destroy is.

## What survives `terraform destroy`

Two things to get right at teardown, and they point in opposite directions.

1. **The RDS final snapshot SURVIVES the destroy, and bills.** `db_skip_final_snapshot`
   defaults to `false` (`infra/variables.tf:781-784`), so a destroy leaves a
   snapshot behind and the database's **data is kept** while the instance is
   gone. That snapshot is **not a Terraform resource** — it is created by the
   destroy itself — so Terraform will not remove it, and it bills (the config's
   own note estimates ~$2.30/mo for 20 GiB of gp3, `infra/database.tf:242-252`)
   until someone deletes it in the console. **To discard the data instead, pass
   `-var db_skip_final_snapshot=true`**, which is free and destroys it.
2. **The NAT Elastic IP does NOT survive** — it is a Terraform-managed resource
   (`aws_eip.nat`, `infra/main.tf:233-252`), so `terraform destroy` releases it.
   This is the opposite of the snapshot: nothing to clean up by hand, *provided
   the EIP is the one Terraform created*. A manually-allocated EIP elsewhere in
   the account would bill and Terraform would not know about it.

The `ManagedBy = "terraform"` tag on every taggable resource
(`infra/locals.tf:43-49`) is how you find what this stack owns when you audit for
leftovers. **A resource without that tag is not cleaned up by destroy** — which
is exactly why the final snapshot, which destroy creates rather than manages,
outlives it.

Both flags that block a destroy live in `variables.tf`: **RDS
`db_deletion_protection`** (default `true`, `infra/variables.tf:751-754`) and
**ALB `lb_enable_deletion_protection`** (default `true`,
`infra/variables.tf:873-876`). `RUNBOOK.md` §6 records the order to disable them.

## Budget and alerts — the gap

**There is no budget alert configured, and this is a real gap against the
milestone, which requires cost to be estimated *before* provisioning against an
*approved* budget.**

- The credit situation is recorded above: **$120 in credits, expiring April 4,
  2027** — roughly 1.5 months at the estimated burn.
- **No AWS Budgets resource exists.** A `grep` of `infra/` for `aws_budgets` or
  `budget` returns **prose only** — that is, the word "Budget" in
  `infra/README.md`'s "budget for the resources that exist but are idle", and
  nothing else. There is no `aws_budgets_budget`, no `aws_budgets_budget_action`,
  and no CloudWatch billing alarm anywhere in the stack.
- **The consequence.** Nothing notifies anyone when spend crosses a threshold,
  and nothing stops spend at all. **A budget alert is a notification, not an
  automatic spending limit** — AWS Budgets will email you (if configured) but
  does not itself stop a resource. Stopping the meter is `terraform destroy`
  (`RUNBOOK.md` §6), and only that.

**What is therefore unverified / missing, stated plainly:**

| Required by the milestone | Status |
|---|---|
| Cost estimated before provisioning | Estimates exist in this file — but they are estimates, not a bill (§[Observed cost](#observed-cost--unverified--not-yet-observed)). |
| Estimated against an **approved** budget | **NOT RECORDED.** No approved budget figure is on file, and no document names one. |
| A budget alert configured | **MISSING.** No budget resource exists in the Terraform. |
| Alert understood as a notification, not a limit | Recorded here, so it is not re-litigated. |

Closing this gap is an infrastructure change (an `aws_budgets_budget` resource or
a console budget). It is **out of scope for documentation**, and it is recorded
here rather than fixed, because the honest position is that the guardrail the
milestone asks for does not exist.

