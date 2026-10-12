# ═══════════════════════════════════════════════════════════════════════════
# MANAGED DATABASE — RDS PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════
#
# Everything in this file is gated behind `var.enable_managed_database`, so
# turning the toggle off removes the cost AND the capability — it does not
# leave a half-configured database behind. See the cost table in variables.tf.
#
# WHAT THIS IS FOR, STATED HONESTLY
# The api in this milestone does NOT query the database. There is no
# DATABASE_URL in .env.example, no SQLAlchemy, no psycopg — the application in
# this repository is a stateless proxy in front of two inference workers. So
# the database below satisfies the milestone's "managed datastore that is not
# publicly accessible, with restricted secret access" acceptance criteria. It
# is a provisioned, secured, password-managed database awaiting a consumer.
#
# That is stated here so nobody later discovers it as a surprise. It also means
# the cost of this resource is currently pure acceptance-criteria cost, which
# is a real thing to know when deciding whether to run the stack for a week.

# ── DB subnet group — deliberately spans BOTH private subnets ──────────────
#
# ⚠️  THIS IS INTENTIONALLY NOT SINGLE-AZ, AND THE COMMENT BELOW IS THE POINT
# ⚠️
# The instance below is Single-AZ (multi_az = false, for cost). It would be
# perfectly consistent to build a subnet group with only private[0], and that
# would have been less code. This uses both private subnets anyway, because a
# DB subnet group is the resource that determines where the database CAN live.
#
# A subnet group restricted to one AZ is a structure that actively resists a
# later change: promoting the instance to Multi-AZ requires the group to span
# two AZs, and RDS will refuse the upgrade while it does not. Changing the
# subnet group is not a replacement — it is fine — but it is a change nobody
# thinks of at the moment they are trying to fix an availability problem.
#
# By building the group correctly from the start, "promote to Multi-AZ" becomes
# a change to ONE argument (`multi_az`) on ONE resource, and nothing else. The
# network is already Multi-AZ-shaped and only the instance is not.
#
# The subnet group is also FREE. There is no cost argument for making it
# single-AZ, so making it single-AZ would have been a cost saving that cost
# nothing and bought nothing.
resource "aws_db_subnet_group" "db" {
  count = var.enable_managed_database ? 1 : 0

  # name_prefix rather than a fixed `name`. The count toggle means this
  # resource can be destroyed and recreated; a fixed name would then collide
  # with a leftover in the region and fail with AlreadyExists on the second
  # apply. The random suffix avoids that, and the tag below is what you search
  # on when you want to find it.
  name_prefix = "${local.name_prefix}-db-subnets-"
  description = "Private subnets for RDS, spanning every AZ the stack uses"

  # Splat, not an index. This evaluates to the full list regardless of how
  # many private subnets exist — two today, more tomorrow if the CIDR lists
  # grow — and it never goes out of range the way a [0] can. The subnets
  # themselves are count-based on a variable validated to be non-empty, so
  # this list is never empty while the resource exists.
  subnet_ids = aws_subnet.private[*].id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-subnets"
  })

  # ── Why a precondition and not a `check` block ────────────────────────────
  #
  # This is a question of SEVERITY, not expressiveness — both mechanisms can
  # read var.private_subnet_cidrs, and a check block would have been the
  # shorter, more consistent choice given main.tf already uses checks. A `check`
  # block does not halt execution: per the HashiCorp Terraform CHANGELOG
  # v1.5.0, a failed check assertion emits a WARNING and the run continues.
  #
  # That is fine when the thing being warned about is a warning. It is not fine
  # here. RDS rejects a DB subnet group that does not span at least two
  # Availability Zones, so a one-entry private_subnet_cidrs produces a config
  # that plans cleanly and is REFUSED BY AWS AT APPLY TIME — by which point the
  # VPC, four subnets, the NAT gateway, the ALB and the EC2 instance have all
  # been created and are already billing. A warning that arrives after the
  # spending has started is not a warning, it is a receipt.
  #
  # A `precondition` halts the plan instead. The mismatch is caught before any
  # resource is created, at zero cost. The check block in main.tf stays as an
  # early warning; this is the backstop that actually prevents the spend.
  lifecycle {
    precondition {
      condition     = length(var.private_subnet_cidrs) >= 2
      error_message = "RDS requires a DB subnet group spanning at least two Availability Zones. private_subnet_cidrs has ${length(var.private_subnet_cidrs)} entry/entries. AWS rejects a single-AZ DB subnet group at APPLY time, after the VPC, NAT gateway, ALB and EC2 have already been created and are billing. Set at least two private subnet CIDRs."
    }
  }
}

# ── RDS instance ───────────────────────────────────────────────────────────
resource "aws_db_instance" "db" {
  count = var.enable_managed_database ? 1 : 0

  identifier = "${local.name_prefix}-postgres"

  # ── Engine ─────────────────────────────────────────────────────────────────
  #
  # engine_version is PINNED to a major version — see var.db_engine_version for
  # why the pin exists and why it is a major rather than an exact minor. The
  # short version: leaving it unset lets AWS resolve the engine version for
  # you, which means a future apply can change the database underneath you as
  # a side effect of an unrelated edit. Pinning the major blocks that while
  # still letting AWS ship minor security patches in the maintenance window.
  engine         = "postgres"
  engine_version = var.db_engine_version

  # db.t3.micro — a dev-scale default, NOT a performance claim. See
  # var.db_instance_class. Burstable: fine for idle, wrong for sustained load.
  instance_class = var.db_instance_class

  # ── Storage ────────────────────────────────────────────────────────────────
  # gp3 over gp2: same durability class, up to 3x the throughput, and it is
  # the current generation. 20 GiB is the PostgreSQL engine's floor.
  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = null # AWS-managed key. Not "more secure" — the
  # choice here is that rotating this key is an operator decision with a data
  # migration attached, and the default key already encrypts at rest.

  # Storage autoscaling. Without it, a database that grows past 20 GiB goes
  # into STORAGE_EXHAUSTED and stops accepting writes — and on a stack where
  # nothing queries the database yet, that is a failure nobody is watching for.
  # The ceiling is a cost bound: the database cannot grow past it silently.
  max_allocated_storage = 100

  copy_tags_to_snapshot = true # so a restored database is still findable by tag

  # ── Identity ───────────────────────────────────────────────────────────────
  db_name  = var.db_name
  username = var.db_master_username
  port     = local.db_port

  # ═══════════════════════════════════════════════════════════════════════
  # ⚠️  manage_master_user_password — WHY THERE IS NO PASSWORD VARIABLE ⚠️
  # ═══════════════════════════════════════════════════════════════════════
  #
  # This ONE argument is why `password` does not appear anywhere in this
  # config, and why variables.tf declares no `db_password`. There is no
  # `password = var.db_password` here to compare against, because the alternative
  # is not "less secure", it is a different class of problem:
  #
  #   password = var.db_password
  #     → the plaintext password enters Terraform state
  #     → state is stored in an S3 bucket (see the backend block in versions.tf)
  #     → the password now lives in a bucket whose contents, encryption, and
  #       access policy are a SEPARATE problem from the database's
  #     → `terraform state pull` by anyone with bucket access prints it
  #     → and the value had to get INTO the variable in the first place, which
  #       means a .tfvars file, a CI variable, or a command line — each of which
  #       is a copy of the password that nobody is tracking
  #
  # With this argument, AWS creates the master password, stores it in Secrets
  # Manager, and ROTATES it (with `manage_master_user_password_rotation_`
  # handling if enabled — it is not, because rotation on a single dev database
  # adds a failure mode nobody wants while the api has no DB connection yet).
  # The password never exists in state, never exists in a tfvars file, and
  # never exists in user_data. It exists in exactly one place — Secrets
  # Manager — and the application fetches it at runtime through the strictly
  # scoped policy in iam.tf.
  #
  # The reference to the resulting secret is the instance's
  # `master_user_secret[0].secret_arn`, used in iam.tf. Note that this makes
  # the secret ARN UNKNOWN AT PLAN TIME (AWS chooses the secret's name), so
  # the IAM policy and the SSM parameter that embed it plan as
  # "known after apply". That is expected and is not a plan error.
  manage_master_user_password = true

  # ── Network placement ─────────────────────────────────────────────────────
  db_subnet_group_name   = aws_db_subnet_group.db[0].name
  vpc_security_group_ids = [aws_security_group.db.id]

  # ⚠️  NOT PUBLICLY ACCESSIBLE — AND DELIBERATELY REDUNDANT WITH sg_db ⚠️
  #
  # `publicly_accessible = false` is an explicit milestone requirement, and
  # sg_db in security_groups.tf already refuses 5432 from anywhere but the
  # application host. That redundancy is the point, because the two controls
  # are attributes of DIFFERENT THINGS and fail independently:
  #
  #   * THIS flag is a property OF THE INSTANCE. It can be flipped to true by
  #     a careless diff, and in some failure modes the instance's
  #     addressability is decided by something else entirely — a misapplied
  #     subnet group, an RDS Proxy in the wrong VPC, a manual console click
  #     that Terraform does not know about and will silently revert on the next
  #     apply (which is a different kind of surprise, not a smaller one).
  #   * sg_db is a property OF THE NETWORK. It exists whether or not this
  #     instance exists. Even if the database acquired a public address
  #     somehow, that group still has exactly one inbound rule and it names
  #     one security group.
  #
  # Two controls, two independent failure modes. A stack that had only this
  # flag would be one careless diff away from public. A stack that had only
  # the security group would be one console click away from public.
  publicly_accessible = false

  # ── Availability: Single-AZ, ON PURPOSE ────────────────────────────────────
  #
  # multi_az = false is a deliberate availability trade and it is not free.
  # If the AZ hosting this instance becomes unavailable — a hardware or
  # networking event in that zone — the database does not fail over and does
  # not come back until the AZ does. RDS would raise a "MultiAZ failover is
  # occurring" only in the paid-for version of itself; in the Single-AZ
  # version the connection simply fails, for as long as the zone is down.
  #
  # What you still get, and it is not nothing: RDS instance-level replacement
  # on host failure, and automated backups with point-in-time recovery within
  # the retention window. What you do NOT get: automatic failover to the
  # second AZ.
  #
  # ⚠️  ON THIS ACCOUNT, RETENTION IS 0, SO THE BACKUP HALF OF THAT IS ALSO
  # ⚠️  NOT IN EFFECT.  ⚠️
  # db_backup_retention_period defaults to 0 because the Free Plan permits no
  # automated backups, which makes this line a statement about what the
  # Single-AZ trade costs ONCE THE ACCOUNT IS UPGRADED, not a claim about what
  # is running today. Today this instance has neither failover nor automated
  # backups, and the compensation for that is the same as it was before: on a
  # stack where nothing queries the database yet, there is no data to lose.
  # Upgrade the plan and set the retention before the api holds anything
  # irreplaceable. See var.db_backup_retention_period.
  #
  # The cost of Multi-AZ is roughly the price of a second instance, every hour,
  # forever. For a development database that is a bad ratio. Flip
  # multi_az to true when this database holds something you cannot re-create
  # from a migration.
  multi_az = false

  # ── Lifecycle ──────────────────────────────────────────────────────────────
  #
  # ⚠️  BOTH OF THESE ARE DEFAULTS THAT WILL SURPRISE YOU ON DESTROY ⚠️
  #
  #   deletion_protection = true (the default)
  #     → `terraform destroy` FAILS with "DBInstanceCannotBeDeleted".
  #     → You must run: terraform destroy -var db_deletion_protection=false
  #     → This is AWS refusing to delete a database nobody marked disposable.
  #       It is a guard against an accidental destroy pointed at the wrong
  #       workspace, and it is the correct default. It is ALSO the single most
  #       common "why is my destroy failing" moment in a stack like this, and
  #       you now know about it before you need it.
  #
  #   skip_final_snapshot = false (the default)
  #     → destroy leaves a snapshot behind. The database is gone; the DATA is
  #       not.
  #     → That snapshot BILLS FOREVER (~$2.30/month for 20 GiB of gp3) until
  #       someone deletes it in the console. Terraform will not remove it,
  #       because it is not a resource in this config.
  #     → skip_final_snapshot = true skips it and discards the data. Free, and
  #       why it is not the default.
  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : coalesce(var.db_final_snapshot_identifier, "${local.name_prefix}-final")

  # ── Backups ────────────────────────────────────────────────────────────────
  # Retention is var.db_backup_retention_period, which defaults to 0 — so on
  # this account automated backups are OFF. That is a plan constraint, not a
  # preference: the Free Plan caps retention at 0, and any higher value fails
  # the apply with FreeTierRestrictionError. See var.db_backup_retention_period
  # for what a non-zero value would buy once the account is on a Paid plan.
  backup_retention_period = var.db_backup_retention_period
  backup_window           = "03:00-04:00" # UTC. Quiet hours in Ireland.

  # ── Observability ──────────────────────────────────────────────────────────
  #
  # THIS IS THE "USEFUL LOGS" THEME FROM MILESTONE 1, APPLIED TO THE DATABASE.
  # A database whose errors are invisible is a database that fails silently,
  # and "silently" is the whole problem: there is no request to fail, no
  # client to see a timeout, and no log to grep. Postgres logs the things that
  # actually go wrong — auth failures from the wrong secret, connections
  # refused, the slow queries, the recovery replay after a restart — and by
  # default AWS DISCARDS them. Turning them off is the difference between
  # debugging from evidence and debugging from guesses.
  #
  #   postgresql → normal server logging
  #   upgrade    → engine upgrade events; the reason a migration happened
  #                without anyone asking for it
  #
  # COST: CloudWatch Logs ingestion and storage. Small for a dev database, and
  # it is not free. It is still the cheapest debugging you will ever buy.
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  # ── Performance Insights ───────────────────────────────────────────────────
  #
  # OFF by default, and the reason is purely cost: Performance Insights is
  # billed SEPARATELY from the instance, per instance per month, on top of the
  # instance charge, and it is one of the easiest line items to leave enabled
  # across a dozen instances by accident. Nothing in this milestone needs
  # query-level latency data — the database is not being queried yet. Turn it
  # on when it is, and expect the extra charge to appear on the bill that
  # month rather than this one.
  performance_insights_enabled = false

  # Changes take effect at the next maintenance window rather than immediately.
  # Deliberate: an immediate engine/instance-class change is an outage on a
  # database, and applying it at 3am on a dev stack is not worth the latency.
  apply_immediately = false

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-postgres"
  })

  # The instance cannot be created before the subnet group exists. Terraform
  # infers this from the db_subnet_group_name reference above, so this
  # depends_on is redundant — it is written out because the failure it prevents
  # ("InsufficientSubnetGroupFault") is famously unhelpful, and this is one of
  # the two places where saying so is cheap.
  depends_on = [aws_db_subnet_group.db]
}