# ═══════════════════════════════════════════════════════════════════════════
# BOOTSTRAP — Terraform/provider constraints
# ═══════════════════════════════════════════════════════════════════════════
#
# WHY THIS DIRECT EXISTS SEPARATELY
# ─────────────────────────────────
# The main config in `infra/` uses an S3 backend. An S3 backend is special: the
# bucket has to exist BEFORE `terraform init` can talk to it, because `init` is
# the command that downloads the backend. So the state bucket cannot be created
# by the config that depends on it — that is a genuine chicken-and-egg
# problem, not a style preference.
#
# The standard resolution is a two-stage bootstrap:
#   stage 1 (this directory)  → creates the state bucket. No backend.
#   stage 2 (`infra/`)         → everything else. Uses the bucket as backend.
#
# The bucket in this directory has no `backend` block at all, so its own state
# is local. That local state is disposable: once the bucket exists, this config
# has done its job forever and should not be re-applied. Re-running it would
# fail with a name conflict, which is the correct and loud outcome.
#
# NOTE ON required_version
# ────────────────────────
# This is ">= 1.10" and NOT the ">= 1.5" used by most configs. The reason is
# the state-locking decision documented in ./README.md: we lock with S3 native
# locking (`use_lockfile = true`), which was introduced in Terraform 1.10. A
# ">= 1.5" floor here would advertise support for versions that cannot
# implement the locking the main config depends on.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# No `backend` block, on purpose. See the header comment above.
