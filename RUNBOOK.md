# RUNBOOK — lemondrop AWS infrastructure

Operational runbook for the Milestone 2 AWS stack. All commands assume the
`lemondrop` AWS profile and region `eu-west-1`.

## 1. Prerequisites

- Terraform >= 1.10
- AWS CLI v2, configured with a `lemondrop` profile
- `jq` and `psql` (PostgreSQL client) on the operator machine
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
psql "postgresql://lemondrop:$(aws secretsmanager get-secret-value \
  --secret-id arn:aws:secretsmanager:eu-west-1:615105803772:secret:rds!db-b2bb4e62-9b1b-457f-9cd3-fd54665c9c39-e0PB5i \
  --query SecretString --output text | jq -r .password)@lemondrop-dev-postgres.c5g80qskaezr.eu-west-1.rds.amazonaws.com:5432/lemondrop?sslmode=verify-full" \
  -c "SELECT 1"

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
| Password comes back as a JSON object, not a string | Secrets Manager stores the secret as a JSON blob | Extract with `jq -r .password` |
| `psql` fails with a TLS verification error | The RDS CA bundle is missing on the instance | Download `https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem` and point `sslrootcert` at it |
