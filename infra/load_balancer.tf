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
  type     = "application"

  # load_balancer_type is set explicitly even though `type = "application"`
  # above says the same thing. They are different attributes in the provider:
  # `type` is the AWS-facing value and `load_balancer_type` constrains which
  # implementations Terraform will let you configure. Setting only the first
  # leaves the second defaulted, and defaulting a load balancer's capabilities
  # is not something to leave implicit in a file whose whole subject is
  # accidental exposure.
  load_balancer_type = "application"

  # BOTH public subnets, via splat. An ALB in one AZ has no failover: it is
  # still up, still serving every request in that AZ, and still single-AZ. The
  # second subnet costs nothing — an ALB bills per load balancer and per LCU,
  # not per AZ — so paying for one zone and calling it highly available is
  # paying for a decoration.
  subnet_ids = aws_subnet.public[*].id

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
# ⚠️  THE HEALTH CHECK GRACE PERIOD — A BOOT-TIMING PROBLEM, NOT A TUNING ONE
# ═══════════════════════════════════════════════════════════════════════════
#
# This block carries the single most important number in the file, and the
# reason it exists is a specific, measurable, boot-time fact:
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
# WHAT GOES WRONG WITHOUT health_check_grace_period_seconds:
#
#   The ALB's failure threshold (5 consecutive failures) is reached in under
#   two minutes. The target is marked unhealthy. Requests routed to it get 503
#   from the load balancer. It recovers when the boot finishes — but the
#   OPERATOR'S EXPERIENCE is: "I applied the stack, the DNS name is there, and
#   everything 503s. The application is broken."
#
#   And that diagnosis is WRONG, in a way that costs hours. The application is
#   fine. It is a boot-timing issue. But every diagnostic taken from the
#   outside — curl the ALB, check the target group, read the health check
#   reason — says "unhealthy application", because from the load balancer's
#   point of view that is exactly what it is observing. The evidence that
#   would settle it is INSIDE the instance, and the instance has no public IP,
#   no SSH key, and was just created — so the obvious move is to conclude the
#   app is at fault, and to start changing api code.
#
#   That is the failure this number prevents: a correct milestone failing its
#   own acceptance criterion for a reason that has nothing to do with the code.
#
# WHY 300 SECONDS
# Generous on purpose. Being generous costs literally nothing: the clock only
# advances while the target is UNHEALTHY, and a correctly booting instance goes
# healthy well inside five minutes. Being too short costs the entire debugging
# session above. There is no scenario where the too-long setting hurts and a
# real scenario where the too-short one does — so the asymmetry decides it.
#
# If a future image or model set makes boot genuinely slower, RAISE THIS. Do
# not lower it, and do not "fix" a slow boot by shrinking this number: that
# converts a diagnosable delay into an indistinguishable application failure.

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
    # during model loading contributes unhealthy counts during exactly the
    # window the grace period is already covering. Belt and braces.
    interval = 30
    timeout  = 10

    # Two consecutive successes to be healthy, and five consecutive failures to
    # be unhealthy. The asymmetric thresholds (2 up, 5 down) stop one lucky
    # probe from declaring the stack ready, while stopping one unlucky probe
    # from taking it out of service.
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  # ← THE NUMBER. See the essay above before changing it.
  health_check_grace_period_seconds = var.app_health_check_grace_period_seconds

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
# `aws_instance.app[0]` is referenced from inside a count-gated resource. That
# is safe ONLY because aws_instance.app has NO count — it is always created
# (see the note at the top of compute.tf). If anyone ever puts a toggle on the
# instance, THIS LINE BECOMES A PLAN-TIME FAILURE whenever that toggle is
# false, with an "Invalid index" error that names aws_instance.app rather than
# the toggle that caused it.
#
# That coupling is the reason the instance is deliberately ungated, and it is
# why adding `enable_compute` is not a small change to compute.tf — it is a
# change to this file as well.
resource "aws_lb_target_group_attachment" "app" {
  count = var.enable_load_balancer ? 1 : 0

  target_group_arn = aws_lb_target_group.app[0].arn
  target_id        = aws_instance.app[0].id

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