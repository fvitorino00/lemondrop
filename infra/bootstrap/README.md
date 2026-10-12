# Terraform state bootstrap (`infra/bootstrap/`)

This directory creates **one resource**: the S3 bucket that Terraform will use to store state for the main configuration in `infra/`.

It exists because of a genuine chicken-and-egg problem, not for tidiness.

## Why this cannot live in `infra/`

The main config declares a remote backend:

```hcl
backend "s3" {
  bucket = "..."
  key    = "..."
  region = "..."
}
```

Terraform must download and initialise the backend during `terraform init` — before it evaluates any resource. If the bucket that the backend points at is created by a resource in the same config, `init` has nothing to talk to and fails before it can ever plan the resource that would fix it. The bucket cannot be created by the config that depends on it.

So the work splits into two stages:

| Stage | Directory | Backend | Purpose |
|---|---|---|---|
| 1 | `infra/bootstrap/` | local (none) | create the state bucket |
| 2 | `infra/` | S3 (the bucket from stage 1) | everything else |

Stage 1 runs exactly once. Its local state is disposable — once the bucket exists this config has done its job forever, and re-applying it fails loudly with a bucket-name conflict, which is the correct outcome.

## Run it

```bash
cd infra/bootstrap

# 1. Set a globally-unique bucket name. S3 bucket names are global across all
#    AWS accounts; "lemondrop-tfstate" alone will almost certainly collide.
#    Use an account id or a random suffix.
terraform init
terraform apply -var 'state_bucket_name=lemondrop-tfstate-123456789012'
```

The `state_bucket_name` variable has a placeholder default (`lemondrop-tfstate-CHANGE-ME`). A `check` block warns at plan/apply time if you forget to change it; the apply would technically succeed and create an awkwardly-named bucket, which is exactly what the check is there to prevent.

Then copy the outputs:

```bash
terraform output state_bucket_name
terraform output state_bucket_region
terraform output state_key_prefix
```

Paste those three values into the `backend "s3"` block in `infra/versions.tf`. Terraform cannot do this for you — see "The manual step" below.

## What the bucket gets

| Property | Value | Why |
|---|---|---|
| Versioning | `Enabled` | required by the milestone; state history is the only way back from a corrupted state file |
| Server-side encryption | `AES256` (SSE-S3) | state holds plaintext secrets (RDS passwords, keys). SSE-S3 is free and AWS-managed; a customer-managed KMS key would add ~$1/month plus a key policy that can lock you out of your own state |
| Public access block | all four settings | `block_public_acls`, `block_public_policy`, `ignore_public_acls`, `restrict_public_buckets` — each blocks a different path to making a state bucket public, so all four are needed |

Deliberately **not** set: `lifecycle { prevent_destroy = true }`. It is defensible for a state bucket, but this milestone's documented teardown path is `terraform destroy` to stop the meter, and `prevent_destroy` would make that fail. Add it only once destroy is definitively not your cleanup path.

## State locking: S3 native locking, not DynamoDB

**Decision: S3 native locking via `use_lockfile = true`. There is no DynamoDB table in this stack.**

Terraform must lock state while applying, or two concurrent runs can interleave writes and corrupt the file. Until Terraform 1.10 the only way to do that with S3 was a DynamoDB table, which meant every stack carried an extra always-on resource purely for bookkeeping.

Terraform 1.10 introduced S3 native locking: the backend writes a `.tflock` object inside the bucket and arbitrates with conditional writes. The lock file is an ordinary object in an already-versioned, encrypted, access-blocked bucket, so there is nothing left for a second resource to do. The upside is one fewer resource to create, secure, back up, pay for, and eventually delete.

**This is why both `infra/bootstrap/terraform.tf` and `infra/versions.tf` pin `required_version = ">= 1.10"`.** The 1.10 floor is not cosmetic — it is the version that introduced the feature the locking design depends on.

### If you are on Terraform < 1.10

Upgrade. It is the better answer. If you genuinely cannot — an air-gapped environment pinned to an older release, or an S3-compatible object store without conditional writes — add a DynamoDB lock table and pass its keys to the backend.

<details>
<summary>Commented-out DynamoDB equivalent (do not uncomment unless you need it)</summary>

In `infra/bootstrap/main.tf`:

```hcl
resource "aws_dynamodb_table" "tf_locks" {
  name         = "lemondrop-tf-locks"
  billing_mode = "PAY_PER_REQUEST" # on-demand; costs nothing until used
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
```

In `infra/bootstrap/outputs.tf`:

```hcl
output "lock_table_name" {
  description = "Copy into dynamodb_table in the backend block."
  value       = aws_dynamodb_table.tf_locks.name
}

output "lock_table_hash_key" {
  description = "Copy into dynamodb_table_key in the backend block."
  value       = aws_dynamodb_table.tf_locks.hash_key
}
```

In `infra/versions.tf`, the backend block:

```hcl
backend "s3" {
  bucket = "..."
  key    = "..."
  region = "..."

  use_lockfile = true # REMOVE this line if using DynamoDB locking

  # dynamodb_table       = "lemondrop-tf-locks"
  # dynamodb_table_key   = "LockID"
  # dynamodb_table_hash_key = "LockID"  # only if your lock table uses a composite key
}
```

Remove `use_lockfile` when using DynamoDB locking. Running both at once is not a supported combination — DynamoDB locking is deprecated and will be removed in a future Terraform release.

</details>

## The manual step (not optional)

A `backend` block cannot reference variables, locals, data sources, or outputs. Terraform parses it before anything else in the config exists, so `bucket`, `key`, and `region` must be **literal strings**.

That makes the copy-paste from `terraform output` into `infra/versions.tf` a genuine manual step. The outputs exist to make it mechanical rather than guesswork.

## Cleanup

The state bucket is not covered by AWS Free Tier for the storage itself, but at this size the cost is negligible (fractions of a cent). It is still a resource that exists and bills. To remove everything this directory created:

```bash
cd infra/bootstrap
terraform destroy
```

Note that the bucket's versioning history makes the first delete produce a "delete marker"; emptying versioning or waiting out the window is required before S3 will let the name be reused.
