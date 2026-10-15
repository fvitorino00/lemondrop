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
    use_locking  = true
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
terraform apply -var db_deletion_protection=false -var skip_final_snapshot=true

# 2. Disable ALB deletion protection (destroy will fail otherwise)
terraform apply -var lb_enable_deletion_protection=false

# 3. Destroy
terraform destroy \
  -var db_deletion_protection=false \
  -var lb_enable_deletion_protection=false
```

The `skip_final_snapshot=true` in step 1 prevents a costly final RDS snapshot.
The NAT gateway is released by the destroy — verify none remain in the console.

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
