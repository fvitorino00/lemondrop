# ═══════════════════════════════════════════════════════════════════════════
# Outputs — consumed by PHASE 2
# ═══════════════════════════════════════════════════════════════════════════
#
# PHASE 2 NOTE
# ────────────
# These outputs are the entire contract between Phase 1 (this directory) and
# Phase 2 (compute and database). Phase 2 must consume them by reference —
# `aws_subnet.private[*].id` and friends — rather than re-deriving subnet IDs
# or re-declaring a VPC. Re-declaring them would create two VPCs, or two
# conflicting ideas about which subnets exist, and the resulting failure would
# look like a routing problem rather than a duplication problem.
#
# Every output below is safe to reference from Phase 2 today, including the
# nullable NAT one — see its note.

output "vpc_id" {
  description = "ID of the VPC. Phase 2 attaches EC2, the ALB, and RDS to this."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets, one per AZ, in the same order as var.public_subnet_cidrs. The ALB (Phase 2) is placed here."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets, one per AZ, in the same order as var.private_subnet_cidrs. EC2 and RDS (Phase 2) are placed here."
  value       = aws_subnet.private[*].id
}

output "availability_zones" {
  description = "The availability zones the subnets were placed in, in index order. Phase 2 uses these for per-AZ placement (e.g. the RDS subnet group, which requires one entry per AZ)."
  value       = local.azs
}

output "nat_gateway_id" {
  description = <<-EOT
    ID of the NAT gateway, or null when var.enable_nat_gateway is false.

    NULLABLE BY DESIGN. When NAT is disabled the resource has count = 0 and
    does not exist, so this output is null rather than an error. That means
    Phase 2 can reference it unconditionally — including in a conditional
    expression — without risking an "index out of range" failure on a
    resource that was never created. Do NOT write `aws_nat_gateway.main[0].id`
    in Phase 2; use this output, which is already indexed safely.
  EOT
  value       = local.nat_gateway_id
}

# ── Security group outputs — the reachability contract ───────────────────
#
# These exist because Phase 2 must WIRE the existing security groups, not
# create new ones. Duplicating a security group in Phase 2 would quietly undo
# every guarantee security_groups.tf documents — most importantly, a fresh
# "allow the internet in" group created next to the careful one is how this
# kind of stack loses its security story.

output "sg_alb_id" {
  description = "Security group for the load balancer (Phase 2). Phase 2 must place the ALB's ENIs here and must not create a replacement."
  value       = aws_security_group.alb.id
}

output "sg_app_ec2_id" {
  description = "Security group for the EC2 host running all three Compose services (Phase 2). Phase 2 attaches the instance here; it must not create a replacement."
  value       = aws_security_group.app_ec2.id
}

output "sg_db_id" {
  description = "Security group for RDS (Phase 2). Phase 2 associates it with the DB instance's subnet group AND keeps publicly_accessible = false — the two controls are independent and both are required."
  value       = aws_security_group.db.id
}

# ── Bootstrap values, surfaced for convenience ──────────────────────────
#
# These duplicate facts that live in versions.tf's backend block, on purpose:
# the backend block cannot reference outputs, so an operator comparing this
# output against their backend `bucket` argument should be able to see the
# bucket name and region in one place without switching directories.
#
# ⚠️  READ THE HONEST VERSION OF THAT BEFORE RELYING ON IT. ⚠️
#
# `state_bucket_name_expected` below is a STATIC STRING. It is NOT read from the
# backend block and it does NOT reflect it, because a backend block cannot be
# referenced from an output — Terraform evaluates the backend during `init`,
# before variables, data sources, locals, and the provider exist. There is no
# expression that would make it reflect the configured bucket.
#
# So `output "region"` below is real (it reads var.aws_region), but
# `state_bucket_name_expected` is an ECHO of the placeholder, not a reading of
# the backend. The authoritative value is the `bucket` argument in
# versions.tf:74, and nothing in this file can cross-check it.
#
# An earlier revision of this section claimed an operator could compare the two
# and detect a mismatch. That was false, and dangerously so: the failure mode
# is an operator editing versions.tf — which is what they are told to do — and
# forgetting this output, at which point this file keeps reporting the
# placeholder as though it were the configured bucket and the cross-check
# silently detects nothing forever.
#
# It is kept rather than deleted because it still does one honest job: it is a
# greppable marker of the placeholder, so `grep -rn CHANGE-ME infra/` tells you
# which files still need the operator's attention. That is a real use, and it
# does not depend on this value ever being correct.

output "region" {
  description = "Region these resources are in. Must match the backend region in versions.tf. Unlike the bucket output below, this one is real — it reads var.aws_region — so comparing it against the backend `region` is a genuine cross-check."
  value       = var.aws_region
}

output "state_bucket_name_expected" {
  description = "The PLACEHOLDER bucket name, echoed as a literal. This does NOT reflect the configured backend and cannot: a backend block cannot be referenced from an output. The authoritative value is the `bucket` argument in versions.tf. Do not treat a difference between this and your backend as a detected misconfiguration — it only proves this file was not edited, which tells you nothing about versions.tf. Use `grep -rn CHANGE-ME infra/` to find every file that still needs attention."
  value       = "lemondrop-tfstate-CHANGE-ME"
}

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 OUTPUTS — compute, load balancer, database
# ═══════════════════════════════════════════════════════════════════════════
#
# Appended by Phase 2. Every Phase 1 output above is unchanged.
#
# ── THE NULLABILITY FORM, AND WHY IT IS ONE(SPLAT) ─────────────────────────
#
# Every output below that CAN be null is written as:
#
#     one(aws_thing.gated[*].attribute)
#
# and NOT as the obvious:
#
#     var.enable_thing ? aws_thing.gated[0].attribute : null
#
# The ternary is the form Phase 1 uses (see `nat_gateway_id`, which wraps
# `local.nat_gateway_id` from main.tf — and note that main.tf's own version of
# that line, `var.enable_nat_gateway ? aws_nat_gateway.main[0].id : null`, is
# the one place in this stack that still carries the risk; it is flagged for
# review, not changed here). Indexing a resource whose count is 0 inside a
# conditional is the single most common bug in count-gated Terraform, and when
# it bites it reports:
#
#     Error: Invalid index
#     The given key does not identify an element in this collection value.
#
# which names the resource and not the boolean that caused it. Worse, it is
# invisible in a plan run with everything enabled — it only appears when
# someone turns a feature OFF, which is exactly when they are trying to save
# money and least able to debug it.
#
# The splat does not have that failure mode, or the uncertainty about it.
#
# The splat `aws_thing.gated[*]` never fails: it produces an EMPTY LIST when
# count is 0 and a one-element list otherwise. `one()` turns a one-element list
# into its element and an empty list into null. No branch, no evaluation-order
# subtlety, and — unlike `try()` — nothing for a future version to change the
# error semantics of.
#
# Each output below therefore yields `null` when its toggle is false, rather
# than erroring. `terraform output alb_dns_name` prints `null` on a stack with
# the load balancer disabled, which is a true and useful answer.

output "alb_dns_name" {
  description = "Public DNS name of the Application Load Balancer, or null when var.enable_load_balancer is false. This is the URL the milestone's acceptance criteria are checked against."
  # null when enable_load_balancer = false — see the note above.
  value       = one(aws_lb.main[*].dns_name)
}

output "alb_dns_zone_id" {
  description = "Route 53 hosted zone ID of the load balancer, or null when var.enable_load_balancer is false. Useful when aliasing a record to the ALB later."
  value       = one(aws_lb.main[*].zone_id)
}

output "ec2_instance_id" {
  description = "Instance ID of the application host. Pass it to `aws ssm start-session --target <id>` for shell access."
  value       = aws_instance.app.id
}

output "ec2_public_ip" {
  description = "Public IP of the application host, or an empty string — which is the DEFAULT, because the instance lives in a private subnet. Empty when the instance is unreachable except through SSM."
  # The instance is in aws_subnet.private, where map_public_ip_on_launch is
  # false (main.tf). It gets a public address ONLY if the operator passes
  # -var app_associate_public_ip=true, and even then only while that subnet
  # setting and the instance setting agree — which is the interaction
  # documented on that variable.
  #
  # NOT null: aws_instance.public_ip is a string attribute that AWS reports as
  # "" when there is no public address, so this output is an empty string rather
  # than a null. Read it with a length() check, not a null check.
  value       = aws_instance.app.public_ip
}

output "ec2_private_ip" {
  description = "Private IP of the application host. Stable for the life of the instance and the address to use from anywhere inside the VPC."
  value       = aws_instance.app.private_ip
}

output "ec2_public_dns" {
  description = "Public DNS name of the application host, or an empty string when it has no public address. Empty is the DEFAULT, because the instance lives in a private subnet."
  # NOT null. aws_instance.public_dns is a string attribute that AWS reports as
  # "" when the instance has no public address, so this output is an empty
  # string rather than a null — do not test it with a null check.
  value       = aws_instance.app.public_dns
}

output "ec2_ssh_key_name" {
  description = "Name of the EC2 key pair attached to the application host, or null when create_ssh_key is false (the default). Remember: a key does not open port 22."
  value       = one(aws_key_pair.app[*].key_name)
}

output "rds_endpoint" {
  description = "Connection endpoint (host:port) for the RDS instance, or null when var.enable_managed_database is false."
  value       = one(aws_db_instance.db[*].endpoint)
}

output "rds_address" {
  description = "Hostname of the RDS instance, or null when var.enable_managed_database is false. This is the same value published to SSM at /db/host/."
  value       = one(aws_db_instance.db[*].address)
}

output "rds_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the RDS master password, or null when var.enable_managed_database is false. The SECRET — the password is never an output, because a password in state is a password in the S3 state bucket."
  value       = one(aws_db_instance.db[*].master_user_secret[*].secret_arn)
}

output "rds_db_name" {
  description = "Name of the initial database on the RDS instance, or null when var.enable_managed_database is false."
  value       = one(aws_db_instance.db[*].db_name)
}

output "db_ssm_parameter_names" {
  description = "SSM parameter names the application host reads to discover the database, or an empty list when var.enable_managed_database is false."
  # Deliberately a LIST. The host fetches all of them in one GetParameters
  # call, so exposing the set means the caller can do the same instead of
  # hardcoding three names in whatever consumes this output. concat() over
  # three splats yields all three names when the database is enabled and an
  # empty list when it is not — so a caller can iterate it without a null
  # check, and cannot get a partial list.
  value = concat(
    aws_ssm_parameter.app_core[*].name,
    aws_ssm_parameter.app_db_port[*].name,
    aws_ssm_parameter.app_db_secret_arn[*].name,
  )
}
