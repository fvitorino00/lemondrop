# ═══════════════════════════════════════════════════════════════════════════
# SECURITY GROUPS — the core of this milestone's security story
# ═══════════════════════════════════════════════════════════════════════════
#
# Three security groups, wired so that every reachable path is explicit:
#
#   internet (operator IP only)
#        │  :80
#        ▼
#   ┌─────────┐   :8000    ┌──────────────┐   :5432   ┌────────┐
#   │  sg_alb │ ─────────▶ │ sg_app_ec2   │ ─────────▶ │ sg_db  │
#   └─────────┘            └──────────────┘            └────────┘
#   ALB (Phase 2)          EC2 running all 3           RDS (Phase 2)
#                          compose services
#
# Every arrow is a single explicit rule. Nothing is allowed implicitly by
# omission, because omission is how rules get widened by accident later.
#
# ── WHY THE RULES ARE SEPARATE RESOURCES, NOT INLINE ─────────────────────
# `aws_vpc_security_group_ingress_rule` / `..._egress_rule` are used instead of
# inline `ingress {}` / `egress {}` blocks on `aws_security_group`. The reason
# is a hard dependency cycle:
#
#   sg_alb's egress goes TO sg_app_ec2   → sg_alb depends on sg_app_ec2
#   sg_app_ec2's ingress comes FROM sg_alb → sg_app_ec2 depends on sg_alb
#
# Inline rules are attributes of their own resource, so both resources would
# have to exist before either could be created. Terraform would deadlock and
# report a cycle. Splitting the rules into their own resources means each rule
# depends only on the security groups it names, and the cycle disappears
# because the dependency is no longer self-referential.
#
# Side benefit: with the standalone rule resources, the security groups
# themselves carry NO inline rules, which means AWS does NOT create its default
# allow-all egress rule. A security group declared here is deny-by-default in
# both directions until a rule resource says otherwise. That default is doing
# real work below — see sg_db.
#
# These rule resources require AWS provider >= 5.0, which is what versions.tf
# pins.

# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  THE MOST IMPORTANT SECURITY NOTE IN THIS FILE  ⚠️
# ═══════════════════════════════════════════════════════════════════════════
#
# THE EMBEDDER AND THE RERANKER ARE NOT REPRESENTED ANYWHERE IN THIS STACK.
#
# There is no security group for them. There is no ingress rule with port 8080
# in it. There is no subnet of their own. There is no load balancer target
# group, no listener rule, nothing. Grepping this directory for "8080" returns
# COMMENTS ONLY — no security group rule, resource attribute, or target group
# references port 8080 anywhere in infra/. That is the design.
#
# WHY THAT IS THE CORRECT WAY TO ENFORCE "NO DIRECT INTERNET ACCESS TO THE
# INFERENCE SERVICES"
#
# The milestone requires that the inference services cannot be reached directly
# from the internet. There are two ways to satisfy that:
#
#   (a) Write a rule that forbids it — e.g. a deny rule, or a security group
#       with no ingress, or an ALB listener that does not mention them.
#   (b) Build no path to them at all.
#
# This stack takes (b), and (b) is strictly stronger than (a). A deny rule is a
# statement about the present that someone can delete, widen by changing a
# port, or defeat by adding an allow rule on a broader CIDR in a later commit,
# none of which would break anything visibly. An absent path has no such
# failure mode: to make the embedder reachable, someone would have to ADD a
# port 8080 rule and an ALB target — new resources, new code, reviewable as
# new.
#
# The mechanism that makes this true:
#
#   The three services run on ONE EC2 instance as Docker Compose services on
#   an instance-local bridge network. Only `api` is attached to the host's port
#   8000 and only `api` is attached to the host's port 8000 for the load
#   balancer. `embedder` and `reranker` publish no host port at all — see
#   docker-compose.yml, which contains exactly ONE `ports:` key, and it is on
#   `api`.
#
#   So their port 8080 exists only inside the instance's own network namespace.
#   Traffic from the internet is stopped by sg_app_ec2 before it reaches the
#   host. Traffic that IS allowed (the ALB, on 8000) lands on the api container
#   only. The embedder and reranker listen on a Docker bridge interface that no
#   security group route, no public IP, and no load balancer target points at.
#
#   Structurally: the instance has exactly one door (port 8000, from the ALB,
#   from the operator's IP). The inference services are not behind that door —
#   they are beside it, on a network that the door does not lead to. The api
#   reaches them as `http://embedder:8080` over Docker's embedded DNS, which
#   is resolvable only from inside the instance.
#
# Therefore: there is no path from the internet to the inference services BY
# CONSTRUCTION, not by a rule that could be accidentally widened. That is the
# strongest form the requirement can be satisfied in, and it is why their
# absence here is a deliberate, load-bearing decision rather than an omission
# Phase 2 needs to fix.
#
# WHAT WOULD BREAK IT (for whoever changes this later)
#   * adding `ports: - "8080:8080"` to the embedder or reranker service in
#     docker-compose.yml
#   * adding a second host port mapping to the api service that forwards
#     straight at a worker
#   * adding a security group rule for port 8080 on sg_app_ec2
#   * adding an ALB target group pointing at port 8080
#   * binding a worker to 0.0.0.0 instead of the bridge interface
# Any of those reopens the path. None of them is in this stack.
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# sg_alb — the only security group with an internet-facing rule
# ═══════════════════════════════════════════════════════════════════════════
resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-sg-alb"
  description = "Application Load Balancer - the only internet-facing security group"
  vpc_id      = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sg-alb"
    Role = "edge"
  })
}

# ── Ingress: port 80 from the operator's IP ONLY ─────────────────────────
#
# ⚠️  KNOWN LIMITATION — THIS IS PLAINTEXT HTTP  ⚠️
#
# Port 80 (HTTP), not 443 (HTTPS), because NO TLS CERTIFICATE IS PROVISIONED
# IN THIS MILESTONE. There is no ACM certificate, no listener on 443, no
# certificate resource anywhere in this stack. Requests and responses between
# the operator and the load balancer — including the /embed and /rerank
# payloads and their responses — travel in cleartext over the public internet.
#
# This is a real limitation and must be fixed before any real use of this stack
# with real data. Fixing it means: an ACM certificate (DNS-validated via
# Route 53, or a manually-issued one added to ACM), a `aws_lb_listener` on 443
# with `certificate_arn`, and an HTTP→HTTPS redirect listener on 80. None of
# that belongs in this milestone because no certificate can be issued for a
# domain that does not exist yet.
#
# Mitigating factor, and it is only that: the CIDR is restricted to a single
# host (/32), so the plaintext is exposed to interception only along the path
# between that host and AWS — but that path crosses the public internet and
# must be treated as hostile.
#
# The "/32" here is ENFORCED, not merely assumed: the validation block on
# var.allowed_api_cidr in variables.tf rejects any prefix length other than 32,
# so this rule cannot be widened to a range without failing at `plan`.
resource "aws_vpc_security_group_ingress_rule" "alb_from_operator" {
  security_group_id = aws_security_group.alb.id
  description       = "Port 80 from the operator home IP only"

  ip_protocol       = "tcp"
  from_port         = local.lb_port
  to_port           = local.lb_port
  cidr_ipv4         = var.allowed_api_cidr
}

# ── Egress: to the EC2 security group on the app port ONLY ───────────────
# The load balancer forwards to the instance and to nothing else. It cannot
# reach the database, and it cannot reach the internet.
resource "aws_vpc_security_group_egress_rule" "alb_to_ec2" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward traffic to the app port on EC2, and nowhere else"

  ip_protocol                  = "tcp"
  from_port                    = local.app_port
  to_port                      = local.app_port
  referenced_security_group_id = aws_security_group.app_ec2.id
}

# ═══════════════════════════════════════════════════════════════════════════
# sg_app_ec2 — the host running all three Compose services
# ═══════════════════════════════════════════════════════════════════════════
resource "aws_security_group" "app_ec2" {
  name        = "${local.name_prefix}-sg-app-ec2"
  description = "EC2 running the api, embedder and reranker Compose services"
  vpc_id      = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sg-app-ec2"
    Role = "application"
  })
}

# ── Ingress: the app port, from the ALB ONLY ─────────────────────────────
# Port 8000 from sg_alb and nothing else. No 0.0.0.0/0. This single rule is
# what makes "only the api is reachable from outside" true at the network
# layer: the load balancer is the only host in the account permitted to open
# this port.
resource "aws_vpc_security_group_ingress_rule" "ec2_from_alb" {
  security_group_id            = aws_security_group.app_ec2.id
  description                  = "App port from the load balancer only"

  ip_protocol                  = "tcp"
  from_port                    = local.app_port
  to_port                      = local.app_port
  referenced_security_group_id = aws_security_group.alb.id
}

# ── Egress: UNRESTRICTED — a known gap, documented below ─────────────────
#
# ⚠️  KNOWN GAP — UNRESTRICTED EGRESS  ⚠️
#
# This rule allows the instance to send traffic to ANY destination on ANY port.
# It exists because the instance must be able to:
#   * pull container images (Docker Hub, GHCR, ECR)
#   * install OS packages (apt/yum repositories)
#   * download GGUF model weights (HuggingFace and similar)
#     — required: scripts/fetch-models.sh pulls the models this application
#       is built around, and the api cannot serve /embed or /rerank without
#       them on disk.
#   * reach the NAT gateway's EIP and AWS APIs
#
# MITIGATION NOTE — WHY THIS IS NOT FULLY CONTROLLED, STATED HONESTLY
#
# Terraform (and AWS security groups generally) CANNOT restrict egress per
# CONTAINER. A security group attaches to an ENI, and an ENI belongs to the
# instance — not to a container. All three Compose services share the host's
# single ENI and therefore share this one unrestricted egress rule. There is
# no way, in this config or any other security-group config, to let the api
# pull images while preventing the embedder from doing the same, because
# security groups have no visibility into Docker's bridge network and no
# concept of a container.
#
# So this gap is NOT closed, and any statement that egress is "controlled"
# would be false. What IS true, and what the milestone actually requires:
#
#   * No security group and no route in this stack grants the inference
#     containers an INBOUND path. Egress from them, if they have any, arrives
#     at a Docker bridge interface that nothing outside the instance can reach
#     or address. An outbound connection initiated by the embedder lands on an
#     RFC1918 address inside the instance's own namespace and goes no further.
#   * Therefore "direct internet access to the inference services is
#     prohibited" — where "access" means reaching or being reached — is
#     satisfied structurally, not by a rule that could be widened.
#
# True per-container egress filtering would require host-level tooling that is
# beyond this milestone: e.g. Docker's own iptables DOCKER-USER chain, or
# `docker network disconnect`, or per-container egress proxies. Those are an
# operational control on the instance, not an infrastructure-declared control,
# and this config does not claim to provide them.
#
# What this config does provide, and it is not nothing: the security group is
# still deny-by-default on INGRESS, so the unrestricted rule grants no new
# inbound reachability. It only widens the outbound direction, where the
# unaddressable question is "which container started this connection", and
# that connection is not useful to an attacker without a foothold on the
# instance already.
#
# ── WHY THIS RULE OMITS from_port AND to_port ─────────────────────────────
#
# `ip_protocol = "-1"` means ALL PROTOCOLS. The AWS contract for that value is
# that the port arguments must be OMITTED ENTIRELY:
#
#   * ip_protocol = "-1"  with NO from_port / to_port  →  all protocols, all
#     ports. This is what "unrestricted egress" actually means, and it is what
#     this rule intends.
#   * ip_protocol = "-1"  WITH from_port / to_port     →  contradictory
#     request: "all protocols AND this specific port range". AWS rejects it.
#
# AWS states this itself, verbatim:
#
#   "You may not specify all protocols and specific ports. Please specify each
#    protocol and port range combination individually, or all protocols and no
#    port range."
#
# Adding `from_port = 0` / `to_port = 0` here therefore made the request
# self-contradictory and AWS refused it:
#
#   Error: updating VPC Security Group Rule (sgr-...)
#   operation error EC2: ModifySecurityGroupRules, ... StatusCode: 400,
#   api error InvalidParameterValue: You may not specify all protocols and
#   specific ports.
#
# ── THE TWO CHECKS THAT DID NOT CATCH IT, AND WHY ─────────────────────────
#
# This rule had been CREATED successfully before it failed. That is not
# evidence of correctness: AWS accepted the create and rejected the update.
# Creation permissiveness is not a contract, and a resource that exists and is
# currently right in the console is not a resource that is correctly declared.
#
# `terraform validate` cannot catch this either. The constraint is enforced
# AWS-SIDE, inside EC2's ModifySecurityGroupRules, not by the provider's
# schema validator — which only rejects port arguments whose value is non-zero,
# so a `0`/`0` pair sails through it. Schema validation passing means the HCL
# is well-formed; it says nothing about whether the API call is satisfiable.
#
# An earlier audit of this exact resource cleared it on the strength of that
# provider-side check. That reasoning was wrong in kind, not in detail: it
# consulted the wrong validator for the wrong side of the boundary. The rule to
# carry forward is that for AWS API constraints, the API contract is the
# authority — not the provider schema, not a green validate, and not the fact
# that a previous apply happened to succeed.
#
# The other four rule resources in this file are constrained by the same
# contract and were audited against it: each names a specific protocol
# (`ip_protocol = "tcp"`) with an explicit, coherent from_port/to_port pair, so
# none of them pairs "-1" with a port range.
resource "aws_vpc_security_group_egress_rule" "ec2_egress_all" {
  security_group_id = aws_security_group.app_ec2.id
  description       = "UNRESTRICTED EGRESS - required for image, package and model pulls. Known gap; see the MITIGATION note above."

  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ═══════════════════════════════════════════════════════════════════════════
# sg_db — the network-layer enforcement of "RDS is not publicly accessible"
# ═══════════════════════════════════════════════════════════════════════════
resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-sg-db"
  description = "RDS PostgreSQL - reachable only from the EC2 application host"
  vpc_id      = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sg-db"
    Role = "data"
  })

  # NOTE ON EGRESS: there is deliberately NO egress rule resource for this
  # security group. Because the rules are standalone resources (see the header
  # comment), declaring no egress rule means this group has NO egress at all —
  # AWS's automatic allow-all egress rule only exists when a group is created
  # with inline egress blocks or with none at all via the classic attribute
  # form. A managed database does not need outbound access for this application,
  # so deny-all is both correct and free. If Phase 2 needs RDS to reach an
  # external endpoint (monitoring, a managed logging service), add an explicit,
  # narrow rule here — an explicit deny-all is auditable, an implicit one
  # is not.
}

# ── Ingress: 5432 from the application host ONLY ─────────────────────────
#
# THIS RULE IS THE NETWORK-LAYER ENFORCEMENT OF THE MILESTONE REQUIREMENT
# "RDS MUST NOT BE PUBLICLY ACCESSIBLE".
#
# It is deliberately redundant with the `publicly_accessible = false` setting
# that Phase 2 will put on the RDS resource. The redundancy is the point. The
# two controls fail independently and for different reasons:
#
#   * `publicly_accessible = false` is an attribute of the instance. It can be
#     flipped to true by a careless diff, and in some failure modes (a
#     misapplied subnet group, an RDS Proxy in the wrong VPC) the instance's
#     addressability is determined by something other than that flag.
#   * This security group is independent of the instance. Even if the database
#     somehow acquired a public IP, this group still has exactly one inbound
#     rule, and it names one security group — the application host. 0.0.0.0/0
#     on 5432 appears nowhere in this stack.
#
# Defence in depth, enforced twice, in two different layers. If a future change
# got the database reachable from the internet by any other route, this rule
# would still refuse the connection.
resource "aws_vpc_security_group_ingress_rule" "db_from_ec2" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from the application host only - the sole inbound path to the database"

  ip_protocol                  = "tcp"
  from_port                    = local.db_port
  to_port                      = local.db_port
  referenced_security_group_id = aws_security_group.app_ec2.id
}

# NO OTHER INGRESS RULE IS DEFINED FOR sg_db. Not one. The database is
# reachable from the application host or from nowhere.
