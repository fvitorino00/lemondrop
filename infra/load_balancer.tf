# ═══════════════════════════════════════════════════════════════════════════
# APPLICATION LOAD BALANCER — the public door
# ═══════════════════════════════════════════════════════════════════════════
#
# Everything here is gated behind `var.enable_load_balancer`. Turning it off
# removes the cost AND the capability — sg_alb still exists (it is free and it
# is part of the security story), but there is no load balancer behind it, so
# there is no way in from the internet.
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  ⚠️  NO TLS IN THIS MILESTONE. TRAFFIC IS CLEARTEXT HTTP OVER THE       │
# │  PUBLIC INTERNET. THIS IS NOT A CHOICE — IT IS AN ABSENCE.               │
# │                                                                          │
# │  There is no ACM certificate, no listener on 443, no certificate         │
# │  resource anywhere in this stack. Requests to /embed and /rerank —        │
# │  including the text of what a user searched for and the vectors and      │
# │  scores that come back — travel in cleartext, across the public           │
# │  internet, between the operator and eu-west-1.                           │
# │                                                                          │
# │  The only mitigation is that ingress is restricted to the operator's      │
# │  /32 (see var.allowed_api_cidr and security_groups.tf). That narrows      │
# │  WHO can read the traffic. It does nothing about anyone ON THE PATH,     │
# │  which crosses the public internet and must be treated as hostile.       │
# │                                                                          │
# │  THIS MUST BE FIXED BEFORE THIS STACK EVER TOUCHES REAL DATA.            │
# │  Fixing it means: an ACM certificate (DNS-validated via Route 53), a      │
# │  listener on 443 with certificate_arn, and an HTTP→HTTPS redirect on 80.  │
# │  None of that is here because no certificate can be issued for a domain   │
# │  that does not exist yet.                                                 │
# │                                                                          │
# │  This warning is duplicated from the one on sg_alb's ingress rule in      │
# │  security_groups.tf. Duplication is deliberate: that comment is read by   │
# │  someone auditing security groups, and this one by someone reading       │
# │  networking. Each of us reads the file in front of us.                    │
# └──────────────────────────────────────────────────────────────────────────┘

# ── The load balancer ──────────────────────────────────────────────────────
resource "aws_lb" "main" {
  count = var.enable_load_balancer ? 1 : 0

  name = "${local.name_prefix}-alb"

  internal = false # PUBLIC. This is the internet-facing resource.

  # `load_balancer_type` is the correct and only attribute for this on aws_lb.
  # There is no `type` argument. Valid values are "application", "network" and
  # "gateway"; this stack wants "application" because /embed and /rerank are
  # HTTP request/response calls behind one door.
  load_balancer_type = "application"

  # BOTH public subnets, via splat. An ALB in one AZ has no failover: it is
  # still up, still serving every request in that AZ, and still single-AZ. The
  # second subnet costs nothing — an ALB bills per load balancer and per LCU,
  # not per AZ — so paying for one zone and calling it highly available is
  # paying for a decoration.
  subnets = aws_subnet.public[*].id

  # The EXISTING security group from security_groups.tf, not a new one. Phase 2
  # consumes Phase 1's security story; creating a second group here would
  # quietly undo every guarantee that file documents.
  security_groups = [aws_security_group.alb.id]

  # 60s, matching the AWS default and var.lb_idle_timeout. Nothing here opens a
  # long-lived connection — /embed and /rerank are request/response calls — so a
  # longer timeout would only widen the window in which a dead connection
  # occupies a target slot.
  idle_timeout = var.lb_idle_timeout

  # ── Deletion protection: same gotcha as the database's ────────────────────
  # Default TRUE. `terraform destroy` will FAIL on the load balancer until you
  # pass -var lb_enable_deletion_protection=false. That is a guard against an
  # accidental destroy removing the stack's only entry point.
  #
  # The honest difference from the database's protection: nothing is LOST
  # here. The ALB holds no data, and re-applying recreates it in minutes. So
  # this is a lower-stakes guard, and it is reasonable to turn it off if
  # destroy convenience matters more. Unlike the database, no one is going to
  # lose anything, which is why this is a preference and not a rule.
  enable_deletion_protection = var.lb_enable_deletion_protection

  # ── Access logs: OFF by default, and the reason is ABSENCE, not cost ──────
  #
  # ALB access logs are written to an S3 bucket. This stack does not create
  # one, and creating one here would mean a bucket, a bucket policy,
  # ownership-controls resources to work around S3's ACL model, a lifecycle
  # rule so the logs do not bill forever, and IAM permissions to write to it —
  # a log-archive subsystem, worth having, and not part of this milestone.
  #
  # So the honest default is off with the requirement documented, rather than a
  # bucket appearing as a surprise next to a load balancer. To enable it,
  # supply a bucket YOU already have:
  #
  #   terraform apply -var lb_access_logs_enabled=true \
  #                    -var lb_access_logs_bucket=my-existing-logs-bucket
  #
  # The bucket must already exist and must be in the SAME REGION as this load
  # balancer. Note that access logs persist REQUEST URLs — so the text a user
  # sent to /embed would be written into that bucket, in a log whose own access
  # story then has to be argued for separately. That is a second decision, not
  # a checkbox.
  #
  # The `dynamic` block is used rather than a literal `access_logs` block so
  # that the argument is ABSENT when logging is off, rather than present with
  # bucket = "". An ALB validates the bucket name, and an empty string is not a
  # bucket; sending it is a provider error waiting for the first person who
  # disables logging after enabling it.
  dynamic "access_logs" {
    for_each = var.lb_access_logs_enabled ? [local.name_prefix] : []

    content {
      bucket  = var.lb_access_logs_bucket
      prefix  = "${local.name_prefix}/alb"
      enabled = true
    }
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-alb"
  })
}

# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  BOOT TIMING vs. THE HEALTH CHECK — AND AN HONEST LIMIT ON WHAT CAN BE
#     DONE ABOUT IT FROM HERE
# ═══════════════════════════════════════════════════════════════════════════
#
# A real, measurable, boot-time fact starts this section, because it is the
# reason the health_check block below is tuned the way it is:
#
#   A FRESH INSTANCE DOWNLOADS ~340MB OF GGUF MODEL WEIGHTS BEFORE THE API CAN
#   ANSWER A SINGLE REQUEST.
#
# The sequence on every new instance:
#   0s     cloud-init starts
#   ~30s   docker installed
#   ~45s   application cloned
#   ~50s   scripts/fetch-models.sh starts pulling bge-small + bge-reranker
#   1–5min MODELS DOWNLOADED (depends on NAT bandwidth; NAT is metered per GB,
#          so a slow transfer here is also a billable one)
#   5–7min docker compose up; workers start LOADING models into RAM; the api's
#          own compose healthcheck waits on both workers (condition:
#          service_healthy) before the api is even started
#   ~7min+ /health finally answers 200
#
# For every second of that window the ALB health check on /health returns
# connection-refused, because there is no listener yet. That is correct
# behaviour being reported accurately.
#
# ── ⚠️  THERE IS NO GRACE PERIOD ON AN ALB TARGET GROUP. ⚠️
#
# This file previously carried:
#
#     health_check_grace_period_seconds = var.app_health_check_grace_period_seconds
#
# on this target group, under an essay explaining at length what a 300-second
# grace period protected against. That attribute DOES NOT EXIST on
# aws_lb_target_group. It is an attribute of aws_ecs_service, where it means
# something real: the delay before ECS starts counting health check results
# for a task that has just started. An ALB target group has no equivalent
# escape hatch. The knob was invented by analogy with ECS, the essay around it
# was written to justify a lever that was never there, and the whole document
# read as though a solved problem had been solved. It had not.
#
# So the mitigation described below has been rewritten to describe the mechanism
# that ACTUALLY exists.
#
# ── THE REAL MECHANISM: unhealthy_threshold × interval ──
#
# An ALB marks a target unhealthy after `unhealthy_threshold` CONSECUTIVE
# failures, with those probes spaced `interval` seconds apart. Tolerance is
# therefore the PRODUCT of the two, not the threshold alone. AWS caps
# `unhealthy_threshold` at 10 and `interval` at 300 for an ALB — and because the
# product is what matters, the practical ceiling for a target group of this
# shape is set by the interval actually configured. With `interval = 30`, the
# maximum tolerance is:
#
#     10 × 30s = 5 MINUTES
#
# There is no configuration of this resource that buys more than that. The
# settings below sit AT that ceiling: `unhealthy_threshold` is pinned at the
# maximum legal value of 10 and `interval` is 30. Raising the threshold is
# rejected by AWS; raising the interval trades probe frequency for a longer
# window (and at 300s the ceiling becomes 50 minutes, at the cost of detecting a
# genuinely dead target almost fifty times more slowly than this does).
#
# ── THE HONEST CONSEQUENCE: 503s DURING BOOT ARE EXPECTED ──
#
# The boot timeline above reaches /health at roughly 7 minutes. The ceiling is
# 5. If the download and model load run to the top of their range — which is a
# routine outcome on a cold NAT gateway, not an exotic one — the target WILL be
# marked unhealthy before /health answers, and the ALB WILL return 503s to
# anything routed at it during boot.
#
# That is expected behaviour for THIS architecture, not an application bug. The
# target recovers on its own as soon as the api's listener is up. It is stated
# here because the misdiagnosis it invites is expensive: every diagnostic taken
# from outside — curl the ALB, read the target group, inspect the health check
# reason — reports "unhealthy application", because from the load balancer's
# point of view that is exactly what it is observing. The evidence that would
# settle it is inside the instance, which has no public IP and was just created.
# Without this paragraph the next operator to see a 503 during boot starts
# changing api code.
#
# ── THE DURABLE FIX IS AN AMI, AND IT IS OUT OF SCOPE HERE ──
#
# No amount of threshold tuning solves this, because the problem is that boot
# downloads 340MB that could already have been on disk. The real answer is to
# pre-bake the model weights into the machine image — a Packer build or an
# equivalent AMI assembly step that installs docker, the application and the
# GGUF files up front — so a replacement instance boots with the models already
# present and /health answers in seconds rather than minutes. That is a
# deliberate change to how this stack produces AMIs and is explicitly OUT OF
# SCOPE for this milestone.
#
# Until that exists, these settings are the maximum the platform allows and
# they are NOT sufficient to cover the full boot window. Treat a 503 during the
# first minutes after `terraform apply` as expected.

resource "aws_lb_target_group" "app" {
  count = var.enable_load_balancer ? 1 : 0

  name = "${local.name_prefix}-app-tg"
  vpc_id = aws_vpc.main.id

  # The ONE door. Port 8000 on the api and nothing else.
  #
  # Note what is NOT here: there is no second target group, no listener rule,
  # and no target for port 8080. The embedder and reranker publish no host
  # port, so there is nothing on this host for such a target to point at —
  # their 8080 exists only inside Docker's bridge network. That is the
  # structural half of "the inference services are not reachable from the
  # internet"; security_groups.tf holds the other half.
  port     = local.app_port
  protocol = "HTTP"
  # instance targets, not ip targets. The instance is in a private subnet and
  # will have no public IP; ip targets in a private subnet would work but
  # couple the target group's identity to an address that changes on every
  # replacement. The instance id is the stable identity.
  target_type = "instance"

  health_check {
    # The api's /health route. The same route the milestone's acceptance
    # criteria use — so what the operator curls by hand and what the ALB
    # checks are the same thing, and a failure means the same failure.
    path = "/health"

    # The api returns 200 from /health. The default matcher for an ALB HTTP
    # health check is 200, so it is stated rather than inherited.
    matcher = "200"

    # 30s between checks, 10s timeout. Generous relative to a local FastAPI
    # response, because a check that times out under a momentary CPU spike
    # during model loading wastes one of a very small number of allowed
    # failures. See the tolerance arithmetic in the essay above before
    # changing either number.
    interval = 30
    timeout  = 10

    # Two consecutive successes to be healthy — the legal range is 2-10, and 2
    # stops one lucky probe from declaring the stack ready.
    #
    # TEN consecutive failures to be unhealthy, which is the MAXIMUM an ALB
    # allows. This is not a balance between tolerance and sensitivity; it is
    # the only setting that buys the most boot time, because tolerance =
    # unhealthy_threshold × interval and the interval is already at a value
    # that makes 30s worth having. See the essay above.
    healthy_threshold   = 2
    unhealthy_threshold = var.app_health_check_unhealthy_threshold
  }

  # 30s of connection draining on deregistration. Short, because the api holds
  # no long-lived state: a request either completes or it is retried. This
  # matters during `terraform destroy` and during any future replacement,
  # where an abruptly cut request would surface as a user-visible error rather
  # than a clean close.
  deregistration_delay = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-app-tg"
  })
}

# ── Attaching the instance ─────────────────────────────────────────────────
#
# ⚠️  THIS IS THE CROSS-FILE REFERENCE THAT A COUNT TOGGLE WOULD BREAK ⚠️
#
# `aws_instance.app` is referenced from inside a count-gated resource. That is
# safe ONLY because aws_instance.app has NO count — it is always created
# (see the note at the top of compute.tf). Note the reference carries no [0]:
# a resource without count is a single value, and indexing it is a plan-time
# error in Terraform, not an accident that happens to work. If anyone ever puts
# a toggle on the instance, this line does not become an "Invalid index" error —
# it becomes a conditional-reference problem, because a counted resource needs
# a one() or try() around it.
#
# That coupling is the reason the instance is deliberately ungated, and it is
# why adding `enable_compute` is not a small change to compute.tf — it is a
# change to this file as well.
resource "aws_lb_target_group_attachment" "app" {
  count = var.enable_load_balancer ? 1 : 0

  target_group_arn = aws_lb_target_group.app[0].arn
  target_id        = aws_instance.app.id

  # Explicit, and equal to local.app_port. For instance targets the default is
  # the TARGET GROUP's port, so this is redundant — but it is the port that
  # matters and redundancy on the single value in this file that decides what
  # is reachable is worth the one line.
  port = local.app_port
}

# ── The listener ───────────────────────────────────────────────────────────
resource "aws_lb_listener" "http" {
  count = var.enable_load_balancer ? 1 : 0

  load_balancer_arn = aws_lb.main[0].arn
  port              = local.lb_port
  protocol          = "HTTP"

  # ⚠️  CLEARTEXT. See the box at the top of this file. ⚠️
  # No `certificate_arn`. No `ssl_policy`. Port 80 only. Everything crossing
  # this listener is readable by anyone on the path.
  #
  # There is no redirect-to-HTTPS listener here either, because with no 443
  # listener a redirect would send every user of this stack to a connection
  # that refuses. Adding the redirect without adding TLS is how a stack ends up
  # looking more secure than it is.

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app[0].arn

    # Nothing here inspects the path. There is no rule routing /embed and
    # /rerank anywhere, and that is the point: the api is the only application
    # behind this listener, and the inference services are not reachable through
    # it because they were never published to the host at all. If a future
    # change adds a listener rule pointing at 8080, that change reopens the
    # path this design closes — see the "WHAT WOULD BREAK IT" list in
    # security_groups.tf.
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-http"
  })
}

# ── Why the load log bucket is NOT created here ────────────────────────────
#
# Because inventing one would be worse than not having it. An S3 bucket for ALB
# logs needs, at minimum: the bucket, a bucket policy (ALB requires specific
# permissions on the bucket principal), ownership controls to work around S3's
# ACL model for log delivery, a lifecycle rule so old logs do not bill forever,
# and a KMS key or default encryption decision. Each of those is its own
# decision with its own failure modes, and none of them belongs in a file whose
# job is "put an HTTP load balancer in front of one instance".
#
# The requirement is documented and the switch is one variable away. What is
# NOT acceptable is a bucket that appears unasked for, holding request URLs, on
# a bill nobody was tracking.

# ═══════════════════════════════════════════════════════════════════════════
# Name-length validation — a check block, and it lives HERE on purpose
# ═══════════════════════════════════════════════════════════════════════════
#
# ALB and target group names are capped at 32 characters by AWS, and the names
# below are DERIVED: "${project_name}-${environment}-alb". Nothing validates
# project_name's length anywhere, so a long project name produces a plan that
# looks completely fine and an apply that fails with:
#
#     Error: ValidationError: Load balancer name must be at most 32 characters
#
# — after the VPC, subnets, NAT gateway and instance have all been created, so
# the stack is half-built and the failure is about a cosmetic name rather than
# anything the operator was thinking about.
#
# It is a `check` block rather than a variable validation for the same reason
# the checks in main.tf are: the property is about the COMBINATION of two
# variables and a suffix, which a single-variable validation cannot see. It is
# here rather than in main.tf because main.tf is Phase 1 and these are the two
# resources whose names are affected — a check belongs next to the thing it
# warns about, so that someone renaming project_name sees it in context.
#
# Severity: a warning, which is the correct severity for a length problem. It
# does not block a plan, it tells you before the expensive half of the stack
# exists rather than after.
check "load_balancer_names_fit_aws_limits" {
  assert {
    condition = alltrue([
      length("${local.name_prefix}-alb") <= 32,
      length("${local.name_prefix}-app-tg") <= 32,
      length("${local.name_prefix}-http") <= 32,
    ])
    error_message = "A load balancer or target group name derived from project_name/environment exceeds AWS's 32-character limit. The plan will apply the network and compute layers and THEN fail naming the load balancer. Shorten var.project_name or var.environment."
  }
}