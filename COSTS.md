# COSTS — lemondrop AWS infrastructure

Cost reference for the Milestone 2 AWS stack. Region `eu-west-1`, on-demand
pricing. All figures are estimates for an always-on deployment; actual bills
will vary with traffic.

## Per-resource breakdown

| Resource | Estimate | Notes |
|---|---|---|
| ALB | ~$16/mo + LCU | Bills per hour regardless of traffic; LCU charges on top |
| NAT gateway | ~$32/mo + per-GB | Bills per hour plus data-processing per GB |
| RDS db.t3.micro | ~$17/mo | Instance + storage |
| EC2 t3.micro | ~$9/mo | |
| EBS 30GB gp3 | ~$3/mo | |
| S3 state | ~$0 | Versioning + encryption on a tiny object |
| **Total** | **~$74/mo** | |

## Credit situation

$120 in AWS credits are available and expire **April 4, 2027**. At the
estimated ~$74/mo burn, that covers roughly **1.6 months**. Plan to tear down
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
