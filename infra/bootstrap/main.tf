# ═══════════════════════════════════════════════════════════════════════════
# BOOTSTRAP — the Terraform state bucket
# ═══════════════════════════════════════════════════════════════════════════
#
# This file creates ONE resource and nothing else: an S3 bucket that will hold
# the Terraform state for the main config in `infra/`. If you are looking for
# anything else here — VPCs, subnets, security groups, EC2, RDS — it is in
# `infra/`, not here. This directory exists only to break the chicken-and-egg
# dependency described in ./terraform.tf.
#
# The four properties below are all required by the milestone and each has a
# distinct job:
#
#   versioning  → state history. Without it a corrupted or truncated state file
#                 is unrecoverable; you cannot "undo" the last apply.
#   encryption  → state contains secrets in plaintext (RDS passwords, IAM
#                 keys, ALB/cert material). It must not sit unencrypted.
#   public access block → a state bucket is a prize. These four settings close
#                 every known path to making it public.
#   locking    → NOT a resource here. See the comment at the bottom: we use S3
#                 native locking, which means there is no DynamoDB table and
#                 no `aws_dynamodb_table` in this file.

locals {
  bucket_name = var.state_bucket_name
}

# ── The bucket ───────────────────────────────────────────────────────────
# Created with `aws_s3_bucket` alone. In AWS provider 5.x all bucket settings
# are separate resources (aws_s3_bucket_versioning, ..._encryption_configuration,
# ..._public_access_block). Writing `versioning = {...}` inline on
# `aws_s3_bucket` is the provider v4 style and is removed/deprecated in v5.
resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name
  tags   = var.tags

  # Deliberately NOT set here:
  #   lifecycle { prevent_destroy = true }
  # It would be defensible for a state bucket, but this milestone's documented
  # teardown path is `terraform destroy` to stop the meter, and prevent_destroy
  # would make that fail. If you adopt this stack long-term, add it AFTER you
  # are certain destroy is not your cleanup path.
}

# ── Versioning (required by the milestone) ───────────────────────────────
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    # "Enabled", not "Suspended". Suspended state files are real and confusing
    # during an incident; enabled is unambiguous.
    status = "Enabled"
  }
}

# ── Server-side encryption ───────────────────────────────────────────────
# SSE-S3 (AES256) rather than aws:kms. Rationale: SSE-S3 is free and keys are
# managed by AWS, whereas a customer-managed KMS key costs ~$1/month and adds
# a key policy that can lock you out of your own state file. The threat model
# here is "someone reads the object over the network", which SSE-S3 already
# covers. Move to KMS only if the milestone's threat model changes.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      # AES256 = SSE-S3. Applied to every new object; the default is not
      # overridden by any later rule because there is no later rule.
      sse_algorithm = "AES256"
    }
    # `bucket_key_enabled` is deliberately ABSENT. It is an SSE-KMS-only
    # setting (it controls the S3 Bucket Key that reduces KMS request costs),
    # and it has no meaning under AES256. Setting it to false here would be
    # asserting a KMS-specific intent while using SSE-S3 — at best noise, at
    # worst a provider validation error. When this config moves to
    # aws:kms, add it then.
  }
}

# ── Public access block (all four settings) ──────────────────────────────
# All four are set because they guard different attack paths:
#   block_public_acls        → stops ACLs granting public read
#   ignore_public_acls        → stops already-public ACLs from taking effect
#   block_public_policy       → stops a policy granting public access
#   restrict_public_buckets  → stops public access via the bucket policy AND
#                               via ACLs, at the account/bucket boundary
# Setting only some of them leaves a real gap. This is the one place where
# "all four" is not ceremony.
resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Guard: the placeholder bucket name must not be applied ───────────────
# `check` blocks shipped GENERALLY AVAILABLE in Terraform 1.5.0 (HashiCorp
# CHANGELOG v1.5.0); they were experimental in 1.3.0. An earlier revision of
# this comment claimed 1.9, which was wrong.
#
# Semantics, stated precisely so the severity here is not mistaken: a failed
# check assertion emits a WARNING. It does NOT halt the run, and execution
# continues. That is the right severity HERE — and unlike the subnet-length
# case in ../main.tf, it is genuinely right. This check guards the single
# resource in this directory, an S3 bucket that costs a rounding error per
# month. A hard stop would abort `apply` over a cosmetic name and teach the
# operator to bypass the check. The warn-and-continue behaviour costs one
# confusingly-named bucket if ignored, which is an acceptable trade for not
# making the guard something people disable.
check "state_bucket_name_is_not_placeholder" {
  assert {
    condition     = var.state_bucket_name != "lemondrop-tfstate-CHANGE-ME"
    error_message = "state_bucket_name is still the placeholder. Set it to a globally-unique name (e.g. \"lemondrop-tfstate-<account-id>\") and use the same value in the backend block in infra/versions.tf."
  }
}

# ═══════════════════════════════════════════════════════════════════════════
# STATE LOCKING — why there is no DynamoDB table here
# ═══════════════════════════════════════════════════════════════════════════
# Terraform needs a lock around state so two concurrent `apply` runs cannot
# interleave writes and corrupt the file. Historically the only S3-compatible
# option was a DynamoDB table, which meant every stack carried an extra
# always-on resource (~$0 early, but a real table, a real thing to back up and
# reason about) purely for bookkeeping.
#
# Terraform 1.10 introduced S3 native locking: the backend writes a
# `.tflock` object in the bucket itself and uses conditional writes to
# arbitrate. It is activated with `use_lockfile = true` in the backend block
# — which is why `infra/versions.tf` sets `required_version = ">= 1.10"` and
# why this bootstrap is pinned to 1.10 too.
#
# The lock file is an ordinary object in an already-versioned bucket, so it is
# encrypted and access-blocked along with everything else. There is nothing
# left for a second resource to do.
#
# If you ever need the old behaviour (Terraform < 1.10, or an S3-compatible
# store that lacks conditional writes), see ./README.md for the exact
# commented-out `aws_dynamodb_table` and backend arguments that restore it.
