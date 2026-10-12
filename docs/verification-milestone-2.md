# Milestone 2 — Infrastructure Acceptance Record

This document is the acceptance record for Milestone 2: the AWS infrastructure
that hosts the lemondrop application. It records what was deployed, the exact
commands used to verify it, the output those commands produced, and a verdict
for each requirement. Its scope is M2 infrastructure only — the M1 application
verification lives in `docs/verification.md` on `main` and is not repeated here.

The distinction that matters throughout: **VERIFIED** means the command was run
against the live stack and the output below is what it returned.
**SUPPORTED-NOT-VERIFIED** means the claim is consistent with evidence but the
specific test has not been run. Nothing here is claimed without a command and an
output.

Deployed stack: region `eu-west-1`, account `615105803772`. VPC with 2 AZs, 2
public subnets, 2 private subnets, NAT gateway, Internet Gateway. EC2 `t3.micro`
in a private subnet running Docker Compose with three containers
(`lemondrop-api-1`, `lemondrop-embedder-1`, `lemondrop-reranker-1`). ALB on port
80. RDS PostgreSQL 16. State in S3 with versioning, encryption, and native
locking.

---

## 1. Acceptance criteria

| # | Criterion | Command | Observed output | Verdict |
|---|---|---|---|---|
| 1 | ALB routes to a healthy application target | `curl -i http://lemondrop-dev-alb-285677848.eu-west-1.elb.amazonaws.com/health` | HTTP 200, body `{"status":"ok","embedder":"ok","reranker":"ok"}`. Boot log: `=== lemondrop boot: SUCCESS — api healthy after 10s ===`. Memory: 913Mi total, 280Mi available with everything running. | **VERIFIED** |
| 2 | EC2 reaches RDS over a private, TLS-verified path | `psql "postgresql://lemondrop:$(aws secretsmanager get-secret-value --secret-id arn:aws:secretsmanager:eu-west-1:615105803772:secret:rds!db-b2bb4e62-9b1b-457f-9cd3-fd54665c9c39-e0PB5i --query SecretString --output text \| jq -r .password)@lemondrop-dev-postgres.c5g80qskaezr.eu-west-1.rds.amazonaws.com:5432/lemondrop?sslmode=verify-full -c "SELECT 1"` | Returned `1`. Password fetched at runtime from Secrets Manager via the instance role. CA bundle from `https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem`. | **VERIFIED** |
| 3 | Provisioning is reproducible | `terraform apply` (run five times) | Five successful applies. State persisted to S3. Each apply after the first reported only intended changes — no drift, no replacement of healthy resources. | **SUPPORTED-NOT-VERIFIED** |

**Why criterion 3 is not verified.** A destroy/apply cycle has not been run.
Five consecutive applies demonstrate idempotency and state persistence, which is
strong evidence, but it does not exercise the destroy path or prove a clean
rebuild from empty state. Treat reproducibility as supported by evidence, not
proven.

---

## 2. Security and networking requirements

| # | Requirement | Command / check | Observed output | Verdict |
|---|---|---|---|---|
| 1 | RDS is not publicly reachable | `aws rds describe-db-instances --query 'DBInstances[0].PubliclyAccessible'` | `False` | **VERIFIED** |
| 2 | RDS resolves to an RFC1918 address | `dig +short lemondrop-dev-postgres.c5g80qskaezr.eu-west-1.rds.amazonaws.com` | `10.0.11.204` | **VERIFIED** |
| 3 | RDS port closed to the internet | `timeout 5 bash -c 'cat < /dev/null > /dev/tcp/lemondrop-dev-postgres.c5g80qskaezr.eu-west-1.rds.amazonaws.com/5432'` | Timed out — connection refused/unreachable from the host. | **VERIFIED** |
| 4 | Inference services have no public exposure | `timeout 5 bash -c 'cat < /dev/null > /dev/tcp/<instance>/8080'` | `PORT_8080_CLOSED_FROM_HOST` — no security group rule, no target, no published port. | **VERIFIED** |
| 5 | API restricted to operator IP | `aws ec2 describe-security-groups --group-ids <sg_app_ec2> --query 'SecurityGroups[0].IpPermissions'` | Inbound rule on port 80: `cidr_ipv4 = 213.22.54.159/32`. | **VERIFIED** |

---

## 3. Cost breakdown

Estimated, eu-west-1 on-demand, always-on:

| Resource | Estimate |
|---|---|
| ALB | ~$16/mo + LCU |
| NAT gateway | ~$32/mo + per-GB |
| RDS db.t3.micro | ~$17/mo |
| EC2 t3.micro | ~$9/mo |
| EBS 30GB gp3 | ~$3/mo |
| S3 state | ~$0 |
| **Total** | **~$74/mo** |

Against $120 in credits expiring April 4, 2027 — roughly 1.6 months at the
current rate. See `COSTS.md` for the full cost reference and the toggles that
change it.

---

## 4. Teardown

Run in this order. Both deletion-protection flags are required or `destroy`
fails.

```bash
cd infra

# 1. Disable RDS deletion protection and allow the final snapshot to be skipped.
terraform apply -var db_deletion_protection=false -var skip_final_snapshot=true

# 2. Disable ALB deletion protection.
terraform apply -var lb_enable_deletion_protection=false

# 3. Destroy. Both flags are also passed here so the destroy itself is not blocked.
terraform destroy \
  -var db_deletion_protection=false \
  -var lb_enable_deletion_protection=false
```

**Final-snapshot caveat.** RDS is configured with `skip_final_snapshot=false`,
so a destroy leaves a final snapshot that continues to cost money. The step
above sets `skip_final_snapshot=true` before destroying to avoid that. If you
want the snapshot, run step 1 without it and delete the snapshot manually after.

**NAT gateway.** It must be released by the destroy or it keeps billing. The
destroy above releases it as part of the NAT gateway resource. Verify no
`aws_nat_gateway` resources remain in the console if destroy reports success but
you want to be certain.

---

## 5. Known limits and untested claims

Stated plainly:

- **The API does not use PostgreSQL yet.** The `psql` probe proves the network
  path from EC2 to RDS, not application integration. The application still runs
  without a database. Wiring the API to RDS is Milestone 3.
- **Reproducibility is supported, not verified.** Five applies persisted state
  and produced only intended changes, but a destroy/apply cycle has not been
  run. The destroy path is unexercised.
- **The boot script's steps 2–6 have now executed successfully on AL2023.**
  This was the failure that cost the deployment session — the original script
  exceeded EC2's 16KB user_data limit and the package-install path was wrong for
  AL2023. Both were fixed and the current script boots cleanly.
- **CPU throughput has never been benchmarked.** No load test has been run
  against `/embed` or `/rerank`. The t3.micro is a dev box, not a performance
  baseline.
- **Memory is tight but functional.** 913Mi total, 280Mi available with all three
  containers running. Enough for the current dev workload; not headroom for
  anything larger.

---

## 6. Re-check this record

A future reader can verify these claims rather than trusting them. Run these
against the live stack:

```bash
# Criterion 1 — ALB health
curl -i http://lemondrop-dev-alb-285677848.eu-west-1.elb.amazonaws.com/health
# Expected: HTTP 200, {"status":"ok","embedder":"ok","reranker":"ok"}

# Criterion 2 — RDS reachability over TLS
psql "postgresql://lemondrop:$(aws secretsmanager get-secret-value \
  --secret-id arn:aws:secretsmanager:eu-west-1:615105803772:secret:rds!db-b2bb4e62-9b1b-457f-9cd3-fd54665c9c39-e0PB5i \
  --query SecretString --output text | jq -r .password)@lemondrop-dev-postgres.c5g80qskaezr.eu-west-1.rds.amazonaws.com:5432/lemondrop?sslmode=verify-full" \
  -c "SELECT 1"
# Expected: 1

# RDS not publicly accessible
aws rds describe-db-instances --query 'DBInstances[0].PubliclyAccessible'
# Expected: False

# Inference port closed
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/<instance>/8080'
# Expected: timeout / connection refused

# SSM session to the instance (no SSH key needed)
aws ssm start-session --target i-0c3155b1b6bb31298

# Boot log
aws ssm send-command --instance-ids i-0c3155b1b6bb31298 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["tail -n 100 /var/log/lemondrop-boot.log"]'
# Then: aws ssm get-command-invocation --command-id <id> --instance-id i-0c3155b1b6bb31298
```

If any of these no longer match, this record is stale and should be updated or
the stack rebuilt.
