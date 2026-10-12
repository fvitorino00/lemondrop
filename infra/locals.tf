# ═══════════════════════════════════════════════════════════════════════════
# Locals — shared naming and tagging
# ═══════════════════════════════════════════════════════════════════════════

locals {
  # ── Resource name prefix ────────────────────────────────────────────────
  # "<project>-<environment>" keeps dev and prod resources distinguishable in
  # the AWS console and, more importantly, in a state file, in IAM policies, and
  # in a security group rule. A stack whose every resource is named "lemondrop"
  # cannot be reasoned about once a second one exists.
  name_prefix = "${var.project_name}-${var.environment}"

  # ── Application port ────────────────────────────────────────────────────
  # The single port the api service publishes. api/Dockerfile binds uvicorn to
  # 8000 and that must not drift: it is referenced by the security group rules
  # below, by the Phase 2 user-data / compose configuration, and by
  # API_INTERNAL_PORT in .env.example. Three consumers, one constant.
  app_port = 8000

  # ── Database port ───────────────────────────────────────────────────────
  # Standard PostgreSQL. Consumed by the sg_db ingress rule below and by the
  # Phase 2 RDS resource.
  db_port = 5432

  # ── Load balancer port ──────────────────────────────────────────────────
  # 80 (HTTP), not 443. See the long comment on sg_alb in security_groups.tf:
  # no TLS certificate is provisioned in this milestone. This is a known
  # limitation, not a decision.
  lb_port = 80
}

# ═══════════════════════════════════════════════════════════════════════════
# Common tags — applied to EVERY taggable resource in this stack
# ═══════════════════════════════════════════════════════════════════════════
#
# `ManagedBy = "terraform"` is the one that earns its keep: it is how you find
# everything this stack owns when you need to audit or destroy it. It pairs
# with the "terraform destroy stops the meter" claim in the README — if a
# resource does not carry this tag, destroy will not clean it up, so every
# taggable resource in this config must merge this map rather than hand-rolling
# its own tags.

locals {
  common_tags = {
    Project   = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
    Repo      = "https://github.com/fvitorino00/lemondrop"
  }
}
