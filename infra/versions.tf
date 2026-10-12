# ═══════════════════════════════════════════════════════════════════════════
# Terraform and provider version constraints, and remote state backend
# ═══════════════════════════════════════════════════════════════════════════

terraform {
  # ── Why ">= 1.10" — the floor is set by ONE feature, not two ─────────────
  # Two features in this config postdate Terraform 1.5, but only one of them
  # sets the floor:
  #
  #   * `check` blocks                     → Terraform 1.5.0 (June 2023)
  #     `main.tf` uses check blocks for cross-variable CIDR validation. They
  #     shipped GENERALLY AVAILABLE in 1.5.0 (HashiCorp CHANGELOG v1.5.0) —
  #     they were experimental in 1.3.0 and stopped being experimental in
  #     1.5.0. An earlier revision of this comment claimed 1.9; that was wrong
  #     and is corrected here.
  #
  #   * `use_lockfile` in the s3 backend   → Terraform 1.10  ← BINDING
  #     This is S3-native state locking. It is the ONLY reason the floor is not
  #     1.5, and it is therefore the reason the floor is 1.10.
  #
  # So the floor is 1.10, driven by state locking ALONE. The check blocks
  # would be perfectly happy on 1.5; raising the floor to 1.10 is a decision
  # about the backend block, not about validation.
  #
  # The floor is set at the real requirement rather than at a
  # comfortable-sounding number: a 1.5 floor would advertise support for a
  # version that cannot parse `use_lockfile` below, and that failure mode is
  # an init-time error naming an argument most operators have never seen.
  #
  # RELATED: DynamoDB-based state locking is now DEPRECATED by HashiCorp in
  # favour of `use_lockfile`. That is a further, independent reason this stack
  # creates no lock table: a DynamoDB lock table would be provisioning a
  # deprecated mechanism whose only advantage (pre-1.10 support) this config
  # has already given up. There is no `aws_dynamodb_table` anywhere in this
  # stack, deliberately.
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Provider 5.x is where all S3 bucket settings moved out of the
      # aws_s3_bucket resource into their own resources (versioning, encryption,
      # public access block). bootstrap/main.tf is written in that style.
      version = "~> 5.0"
    }
  }
}

# ═══════════════════════════════════════════════════════════════════════════
# REMOTE STATE BACKEND — EDIT THESE LITERALS BEFORE `terraform init`
# ═══════════════════════════════════════════════════════════════════════════
#
# ⚠️  OPERATOR ACTION REQUIRED  ⚠️
#
# The three values below MUST match the outputs of `infra/bootstrap`:
#
#   bucket → `terraform output state_bucket_name`  (run in infra/bootstrap)
#   region → `terraform output state_bucket_region`
#   key    → `terraform output state_key_prefix`
#
# These are LITERAL STRINGS and they have to be literal. A backend block is
# evaluated before variables, data sources, locals, and even the provider are
# available — Terraform initialises the backend during `init`, which happens
# before any of that is read. There is no way to interpolate `var.aws_region`
# here, and any attempt to do so will fail at init with a parse error.
#
# That is why `infra/bootstrap/outputs.tf` exists: it exists purely to be
# copy-pasted into this block by a human. Change the values, do not parameterise
# them.
#
# The bucket must already exist or `init` fails. See infra/bootstrap/README.md.

backend "s3" {
  bucket = "lemondrop-tfstate-CHANGE-ME" # ← from: terraform output state_bucket_name
  key    = "lemondrop/dev/terraform.tfstate" # ← from: terraform output state_key_prefix
  region = "eu-west-1"          # ← from: terraform output state_bucket_region

  # Native state locking. Writes a .tflock object inside the bucket and
  # arbitrates with conditional writes. Replaces the old DynamoDB lock table —
  # there is no aws_dynamodb_table anywhere in this stack. Requires
  # Terraform >= 1.10, which is why required_version says so.
  use_lockfile = true

  # State holds secrets in plaintext (RDS passwords from Phase 2, any key
  # material). Encrypt it in flight and at rest.
  encrypt = true
}
