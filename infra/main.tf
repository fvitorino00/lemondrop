# ═══════════════════════════════════════════════════════════════════════════
# NETWORK FOUNDATION — VPC, subnets, routing, NAT
# ═══════════════════════════════════════════════════════════════════════════
#
# Topology built here:
#
#     Internet
#        │
#   Internet Gateway  (aws_internet_gateway.main)
#        │
#   ┌────┴─────────────────────────┬────────────────────────────────┐
#   │ public route table          │ private route tables (1 per AZ) │
#   │  0.0.0.0/0 → IGW             │  0.0.0.0/0 → NAT GW (if on)   │
#   │                              │              → IGW  (if off)   │
#   │ public-a  10.0.1.0/24        │ private-a  10.0.11.0/24        │
#   │ public-b  10.0.2.0/24        │ private-b  10.0.12.0/24        │
#   │ (ALB in Phase 2)             │ (EC2 + RDS in Phase 2)         │
#   └──────────────────────────────┴────────────────────────────────┘
#
# Two AZs, two public subnets, two private subnets. This is the minimum that
# makes an ALB meaningful: an ALB in a single AZ has no failover, so paying
# for one while gaining no high availability would be paying for a decoration.

# ── Availability zones ───────────────────────────────────────────────────
# DERIVED, NOT HARDCODED. Hardcoding "eu-west-1a" / "eu-west-1b" would break
# the moment the operator deploys to a region with a different set of zones, and
# would break in any region where those specific zone letters are not offered to
# the account. This lookup returns only the zones actually AVAILABLE to this
# account, which is a subset AWS decides per account. (The region comes from the
# provider's environment — see the aws_region variable in variables.tf — not
# from any literal in this file.)
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  # One AZ per public subnet. `slice` is used so the length is driven by the
  # CIDR list rather than by however many zones the account happens to expose —
  # an account with 6 zones should not get 6 subnets because the variable
  # asked for 2.
  azs = slice(data.aws_availability_zones.available.names, 0, length(var.public_subnet_cidrs))

  # Convenience for conditional routing below. `null` when NAT is disabled, so
  # the route resources can be expressed with a single index-safe form.
  nat_gateway_id = var.enable_nat_gateway ? aws_nat_gateway.main[0].id : null
}

# ═══════════════════════════════════════════════════════════════════════════
# Validation — `check` blocks (Terraform 1.5.0+)
# ═══════════════════════════════════════════════════════════════════════════
#
# These are `check` blocks rather than variable validations for one reason: a
# check block can compare TWO variables against each other, and a variable
# validation block can only see its own variable plus others it declares in
# scope. Equal-length public/private subnet lists is a cross-variable property,
# so it belongs here.
#
# `check` blocks report a WARNING and continue rather than halting the run —
# that is documented Terraform behaviour, not a preference.
#
# ⚠️  A WARNING IS AN EARLY WARNING HERE, NOT A GUARANTEE. ⚠️
#
# The length-mismatch check below is kept because it tells the operator early
# and cheaply. It is NOT sufficient on its own, and the reason is specific
# rather than general: a mismatched list does not merely plan-with-a-warning,
# it produces a single-AZ DB subnet group, which AWS rejects — at APPLY time,
# after the VPC, NAT gateway, ALB and EC2 have been created and are billing.
# So "caught during plan, zero cost" was the wrong conclusion for this check.
# The thing that actually prevents the spend is the `precondition` on
# aws_db_subnet_group.db in database.tf, which halts the plan. That precondition
# is the backstop; this check is the early warning.
#
# The other two checks below do not have the same exposure — neither mismatch
# produces a later AWS-side failure with spend attached — so a warning is an
# adequate severity for them.

check "subnet_cidr_lists_match" {
  assert {
    condition     = length(var.public_subnet_cidrs) == length(var.private_subnet_cidrs)
    error_message = "public_subnet_cidrs and private_subnet_cidrs must have the same number of entries — one public and one private subnet per availability zone."
  }
}

check "subnet_cidr_lists_are_not_empty" {
  assert {
    condition     = length(var.public_subnet_cidrs) > 0 && length(var.private_subnet_cidrs) > 0
    error_message = "public_subnet_cidrs and private_subnet_cidrs must both be non-empty."
  }
}

check "enough_availability_zones" {
  assert {
    condition     = length(data.aws_availability_zones.available.names) >= length(var.public_subnet_cidrs)
    error_message = "This account does not expose as many availability zones as there are public subnets requested. Reduce the subnet lists or use a region with more zones."
  }
}

# ═══════════════════════════════════════════════════════════════════════════
# VPC
# ═══════════════════════════════════════════════════════════════════════════
resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  # DNS support is not optional decoration here. Phase 2 runs an RDS instance
  # in the private subnets; without hostname support the RDS endpoint resolves
  # only to an IP, and the api container cannot use it as a hostname. Cheap to
  # enable now, awkward to retrofit onto a live VPC.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-vpc"
  })
}

# ── Internet gateway ─────────────────────────────────────────────────────
# The VPC's only door to the internet. Created as its own resource because AWS
# has no "internet-enabled VPC" flag — attaching an IGW is the mechanism.
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-igw"
  })
}

# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC SUBNETS
# ═══════════════════════════════════════════════════════════════════════════
#
# `map_public_ip_on_launch = true` because the Phase 2 ALB is a public-facing
# AWS-managed resource, but the NAT gateway (and, if NAT is ever disabled, the
# EC2 instances themselves) benefits from a public address. For an EC2 instance
# this flag is convenient and lazy — every reboot reassigns a new public IP
# unless an Elastic IP is attached. The NAT gateway has a fixed EIP, so the
# flag does NOT actually determine the NAT gateway's address.
#
# The real security boundary is NOT this flag. It is the security group
# (security_groups.tf): a public IP address on an instance means nothing if no
# security group rule admits the traffic. This flag says "address available",
# not "traffic allowed".

resource "aws_subnet" "public" {
  count = length(var.public_subnet_cidrs)

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-public-${local.azs[count.index]}"
    Tier = "public"
  })
}

# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE SUBNETS
# ═══════════════════════════════════════════════════════════════════════════
#
# `map_public_ip_on_launch = false` is explicit rather than omitted. The
# default is false anyway, but stating it makes the intent checkable: a reviewer
# can see that "no public address" was a decision here, not an accident of
# defaults.
#
# No NAT gateway association is set on the subnet resource — routing is done
# entirely through the route tables below, which is the modern pattern
# (`aws_subnet` no longer needs a `route_table_id`; association is its own
# resource so it can be managed and destroyed independently).

resource "aws_subnet" "private" {
  count = length(var.private_subnet_cidrs)

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.private_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-private-${local.azs[count.index]}"
    Tier = "private"
  })
}

# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTING — one shared route table, routed to the IGW
# ═══════════════════════════════════════════════════════════════════════════
#
# ONE route table shared by both public subnets, not one per subnet. Every
# public subnet routes to the same IGW, so separate route tables would contain
# identical routes and exist only to multiply future maintenance. AWS route
# tables themselves are free, so the saving is not cost — it is the number of
# places a routing bug can hide.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-public-rt"
    Tier = "public"
  })
}

resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ═══════════════════════════════════════════════════════════════════════════
# NAT GATEWAY — conditional, and the most expensive thing in this stack
# ═══════════════════════════════════════════════════════════════════════════
#
# ⚠️  COST  ⚠️  ~$32/month for the gateway itself, PLUS per-GB data processing.
# It bills whether or not anything uses it. It is the single largest line item
# and the main reason this README tells you that `terraform destroy` is how you
# stop the meter.
#
# It is created ONLY in the FIRST availability zone, via `count` on a boolean
# rather than `for_each` over the AZ list. A NAT gateway per AZ would be the
# "correct" highly-available topology and would double this cost to ~$64/month.
# For a dev environment with one EC2 instance, one gateway is enough; the
# asymmetry is an accepted availability risk for a cost saving. Going per-AZ
# later is a non-trivial change (each private route table must then target its
# own zone's gateway), so this is a decision to revisit, not a detail.

resource "aws_eip" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  domain = "vpc"

  # Scoped to this NAT gateway rather than left at the account default, so it
  # can be charged back and so a stray Elastic IP elsewhere in the account is
  # not mistaken for this one.
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-nat-eip"
  })

  # Ordered after the default route for consistency with aws_nat_gateway.main
  # below, which is the resource that actually needs the subnet to be
  # internet-reachable. An EIP can be allocated without any route at all, so
  # `aws_route.public_default` is the minimal sufficient edge here — the
  # association is not needed, because nothing about the NAT subnet's route
  # table is required for the address allocation itself.
  depends_on = [aws_route.public_default]
}

resource "aws_nat_gateway" "main" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-nat"
  })

  # ── Why the dependency is on the ROUTE, not on the IGW resource ──────────
  #
  # A NAT gateway can only be created into a subnet that is INTERNET-REACHABLE,
  # and that is a property of the ROUTE, not of the internet gateway. An
  # `aws_internet_gateway` resource existing tells you the door was installed;
  # it says nothing about whether a path to it exists from any given subnet.
  # Those are different conditions, and only the second one is what AWS checks
  # when it creates this resource.
  #
  # Depending on the IGW resource was therefore a weaker edge than it looked
  # like: Terraform could satisfy it while the default route did not yet
  # exist, attempt the NAT gateway, and fail with a provider error that names
  # neither the route table nor the missing association.
  #
  # Two references, two distinct things that must both be true:
  #   aws_route.public_default               → the 0.0.0.0/0 → IGW route exists
  #   aws_route_table_association.public     → the NAT subnet is IN that table
  # A route table with no default route, and a route that no subnet is
  # associated with, are each individually insufficient.
  depends_on = [aws_route.public_default, aws_route_table_association.public]
}

# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE ROUTING — one route table per private subnet, one per AZ
# ═══════════════════════════════════════════════════════════════════════════
#
# Unlike the public side, private subnets get ONE route table EACH rather than
# a shared one. This is required for correctness, not symmetry: a NAT gateway
# lives in one specific AZ, and a private subnet in a different AZ must route
# to it across an AZ boundary. When NAT is disabled the routes are identical
# and could be shared, but keeping the shape uniform means Phase 2 can add
# VPC endpoints or a per-AZ gateway later without restructuring.
resource "aws_route_table" "private" {
  count = length(var.private_subnet_cidrs)

  vpc_id = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-private-rt-${local.azs[count.index]}"
    Tier = "private"
  })
}

# ── Private default route: NAT gateway (cost paid, isolation kept) ───────
resource "aws_route" "private_default_via_nat" {
  count = var.enable_nat_gateway ? length(var.private_subnet_cidrs) : 0

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[0].id
}

# ── Private default route: internet gateway (cost saved, isolation GONE) ──
#
# ⚠️⚠️⚠️  READ THIS BEFORE SETTING enable_nat_gateway = false  ⚠️⚠️⚠️
#
# THIS ROUTE REMOVES EGRESS ISOLATION FROM THE PRIVATE SUBNETS. IT IS A
# DELIBERATE COST-SAVING TRADE, NOT AN OVERSIGHT AND NOT A MISTAKE.
#
# A private subnet is private because of its ROUTE, not because of its name or
# its CIDR. Pointing 0.0.0.0/0 at the IGW makes every instance in this subnet
# able to send traffic to the internet directly, with the instance's own public
# address as the source. Concretely, when this path is active:
#
#   * EC2 in the private subnet can pull images, install packages, and download
#     models WITHOUT a NAT gateway. That is the upside you are paying for.
#   * EC2 in the private subnet can also reach ANY destination on the internet,
#     directly and unfiltered. That is the downside.
#   * RDS in the private subnet (Phase 2) sits in the same subnet. `publicly_
#     accessible = false` still holds and no security group rule opens 5432 to
#     the world, so the database is NOT publicly reachable. But "not reachable"
#     and "has no outbound path" are different properties, and after this
#     change the second one is false.
#   * The only thing still standing between an instance here and the internet is
#     the instance firewall (security groups). There is no longer a network
#     layer behind it.
#
# This is the trade the cost toggle is buying. If the milestone's security
# story requires genuine egress isolation for the tier holding EC2 and RDS,
# leave `enable_nat_gateway = true` and accept the ~$32/month.
resource "aws_route" "private_default_via_igw" {
  count = var.enable_nat_gateway ? 0 : length(var.private_subnet_cidrs)

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "private" {
  count = length(var.private_subnet_cidrs)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}
