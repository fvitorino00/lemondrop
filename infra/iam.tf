# ═══════════════════════════════════════════════════════════════════════════
# IDENTITY — instance role, session management, secret access
# ═══════════════════════════════════════════════════════════════════════════
#
# The application host is in a PRIVATE SUBNET. There is no bastion, no public
# IP (by default), and no SSH port in any security group. Everything that
# touches this host — including the operator, including this stack — goes
# through the instance role below.
#
# The principle this file follows: the role can do the specific things the
# host needs, and the list is written down, short, and readable. Not a
# wildcard, not an administrative policy, not a role the operator has to
# second-guess.

# ── Trust policy: only EC2 may assume this role ─────────────────────────────
#
# Written with aws_iam_policy_document rather than jsonencode() so that the
# JSON that will be sent to AWS is reviewable in a diff as structured data
# rather than as escaped string literals.
data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    sid     = "EC2AssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name        = "${local.name_prefix}-ec2"
  description = "Application host for lemondrop: SSM session management and read-only database secret access."

  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json

  # Deliberately NOT set. A maximum session duration on an EC2 instance role
  # is meaningless (the role is assumed per-request, not for a session), and
  # setting it invites the reader to believe there IS a session here.

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ec2"
    Role = "application-host"
  })
}

# ═══════════════════════════════════════════════════════════════════════════
# MANAGED POLICIES — the base, attached rather than hand-rolled
# ═══════════════════════════════════════════════════════════════════════════
#
# WHY THESE ARE AWS-MANAGED POLICIES ATTACHED WITH
# `aws_iam_role_policy_attachment` RATHER THAN A COPY-PASTED POLICY DOCUMENT
#
# The hand-rolled alternative looks like this and is genuinely tempting:
#
#     resource "aws_iam_role_policy" "ssm" {
#       name   = "inline-session-manager"
#       role   = aws_iam_role.ec2.id
#       policy = data.aws_iam_policy_document.session_manager.json   # 200 lines
#     }
#
# It is rejected for four reasons, in order of how much they cost:
#
#   1. IT GOES STALE SILENTLY. AmazonSSMManagedInstanceCore is maintained by
#      AWS. Session Manager's wire protocol changes — new message channels, new
#      document APIs, new logging endpoints — and AWS updates the managed policy
#      when it does. A copy frozen in this repo does not get those updates, so
#      the failure mode is: AWS ships a change, Session Manager half-works,
#      and the debugging session starts at "compare the managed policy to
#      yours" instead of at the actual problem.
#
#   2. IT COPIES CAPABILITIES THIS ROLE DOES NOT NEED. The managed policy is
#      broader than "run Session Manager" because AWS makes one bundle for
#      every use of it — inventory, compliance, patch baseline, association
#      reporting. Hand-rolling to avoid over-permissioning usually ends with
#      someone copying AWS's list wholesale to make it work, which produces the
#      managed policy by a slower and less honest route.
#
#   3. THE TRUST CHAIN IS WHERE HAND-ROLLING ACTUALLY HURTS. Building a role,
#      its trust policy, its policies, its attachments and its instance
#      profile by hand means six resources that must agree, and a role with
#      NO trust policy attachment fails at assume-time with an error that
#      describes IAM's internals rather than the missing piece. `attach` with
#      a managed ARN cannot be wired wrong.
#
#   4. THE ATTACHMENT IS REVIEWABLE IN ONE LINE. `policy_arn = "arn:aws:iam::
#      aws:policy/AmazonSSMManagedInstanceCore"` says exactly what is attached.
#      A reviewer auditing this role does not need to reconstruct intent from
#      200 lines of JSON to answer "what can this do".
#
# WHAT THIS DOES NOT MEAN: that managed policies are always correct. An
# AWS-managed policy is still a policy you have attached to a role you own, and
# AWS publishing an update to it changes what that role can do. That is a real
# property to be aware of, not one to be paralysed about — the fix, if it ever
# matters, is a permissions boundary, which is out of scope for one dev host.

# ═══════════════════════════════════════════════════════════════════════════
# Session Manager — THE CHOSEN ACCESS PATH
# ═══════════════════════════════════════════════════════════════════════════
#
# `aws ssm start-session` into the instance. No key pair, no port 22, no
# bastion, no inbound rule of any kind on sg_app_ec2. The operator's access to
# this host is authenticated by IAM — the same identity the operator already
# has — and it is auditable in CloudTrail as an IAM-authorised API call rather
# than as an SSH connection to a port that happens to be open.
#
# This is also the reason create_ssh_key defaults to false in compute.tf: the
# fallback is off because the primary path already covers every case the
# fallback would have covered.
resource "aws_iam_role_policy_attachment" "session_manager" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ── THE REJECTED ALTERNATIVE, WRITTEN OUT ──────────────────────────────────
#
# A hand-rolled equivalent of the attachment above would look like this. It is
# recorded rather than deleted so that the decision is legible later — and so
# that nobody re-derives it from scratch and ships the copy by accident.
#
#   data "aws_iam_policy_document" "session_manager_custom" {
#     statement {
#       sid       = "SessionManagerChannels"
#       effect    = "Allow"
#       actions   = ["ssmmessages:CreateControlChannel",
#                    "ssmmessages:CreateDataChannel",
#                    "ssmmessages:OpenControlChannel",
#                    "ssmmessages:OpenDataChannel"]
#       resources = ["*"]
#     }
#
#     statement {
#       sid    = "RegisterInstanceWithSSM"
#       effect = "Allow"
#       actions = ["ssm:UpdateInstanceInformation",
#                  "ssm:ListAssociations",
#                  "ssm:ListInstanceAssociations",
#                  "ssm:DescribeAssociation",
#                  "ssmmessages:ListDatapoints"]
#       resources = ["*"]
#     }
#
#     statement {
#       sid       = "InstanceDocumentAccess"
#       effect    = "Allow"
#       actions   = ["ssm:GetDocument", "ssm:DescribeDocument"]
#       resources = ["arn:aws:ssm:*:*:document/AWS-*"]
#     }
#   }
#
#   resource "aws_iam_role_policy" "session_manager" {
#     role   = aws_iam_role.ec2.id
#     policy = data.aws_iam_policy_document.session_manager_custom.json
#   }
#
# REJECTED BECAUSE (in order):
#   * Every statement needs "Resource": "*" anyway. ssmmessages: actions are
#     channel-scoped and have no resource you can name. So this "tightened"
#     policy is not actually tighter than the managed one — it is the same
#     policy with more places to get it wrong and no security gained.
#   * It breaks the first time AWS adds a message type or a document API.
#   * It is ~30 lines of policy that says nothing a reviewer cannot get from
#     one line naming the managed policy.
#
# CORRECTION TO AN EARLIER COMMENT IN THIS FILE: it claimed that
# AmazonSSMManagedInstanceCore does NOT grant `ssm:GetParameters`, and used
# that supposed gap to justify the policy below. That was wrong — the
# published v2 policy grants BOTH `ssm:GetParameter` and `ssm:GetParameters`
# (on Resource "*"), along with the rest of the agent's core actions. The
# access was never missing; only the SCOPE was too broad.

# ═══════════════════════════════════════════════════════════════════════════
# SSM PARAMETER READ — narrows a managed grant this stack over-had
# ═══════════════════════════════════════════════════════════════════════════
#
# WHY THIS EXISTS, accurately stated: AmazonSSMManagedInstanceCore already
# grants `ssm:GetParameter` and `ssm:GetParameters` — but on "Resource": "*",
# meaning this role can read EVERY parameter in the account, not just its own.
# This stack does not need that. This policy re-grants the same two actions
# scoped to exactly the three parameters created at the bottom of this file.
#
# ⚠️  THIS POLICY IS AN ENFORCEMENT POINT — THE EXPLICIT DENY CARVES OUT THE THREE NEEDED PARAMETERS. ⚠️
#
# IAM attachments to a role are ADDITIVE and this stack now adds an explicit
# deny. The AWS-managed AmazonSSMManagedInstanceCore attached above keeps
# `ssm:GetParameter*` on "Resource": "*" in force, so a customer Allow by
# itself revokes nothing. An explicit Deny is the only construct that survives
# an additive attachment, so this policy's Deny statement restricts reads to
# the three parameters this stack needs — the effective grant is exactly those
# three and nothing else (the Deny statement and its rationale are in the data
# source below; see iam.tf:213-286).
#
# Note that `ssm:DescribeParameters` is deliberately NOT included: it cannot
# be resource-scoped (AWS requires "Resource": "*" for it), and it is a
# metadata-only listing call that this stack has no use for. Nothing in this
# file grants a wildcard against SSM.
#
# ── UNCHANGED BY THE APPLICATION-CREDENTIAL REPOINTING ABOVE ────────────────
#
# Narrowing the Secrets Manager policy to the application credential removes
# this role's wildcard reach over every SECRET in the account. The equivalent
# narrowing for SSM is what this policy and its explicit Deny now do: they
# restrict parameter reads to this stack's three parameters instead of every
# parameter in the account. Those are two different wildcards, and both are
# now narrowed.
#
# So this policy is changed by that change, deliberately. The SSM wildcard is
# no longer a known limitation for parameter reads: the Deny statement in the
# data source below revokes `ssm:GetParameter*` on every resource except the
# three this stack needs. The remaining gap is structural, not scoped — the
# role still carries AmazonSSMManagedInstanceCore, which is broader than
# Session Manager strictly needs. Detaching that managed policy and granting
# the agent's actions explicitly is its own change, with its own blast radius
# (it is what keeps Session Manager working), and is not attempted here.
#
# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  THIS POLICY WAS TEMPORARILY REVERTED; NOW RESTORED WITH AN EXPLICIT DENY  ⚠️
# ═══════════════════════════════════════════════════════════════════════════
#
# Both the `description` below and the `resources` expression in the statement
# are back to their pre-3ca8d77 form, byte for byte. That is deliberate. The
# current apply is meant to carry the application-credential repointing and
# nothing else; folding an unrelated M2 fix into it would put a second,
# separately-debatable change into the same plan and make it impossible to
# attribute a resulting diff to either one.
#
# WHAT THE REVERT COSTS
#
# This policy therefore AGAIN COVERS ONE OF THE THREE SSM PARAMETERS it
# discusses — `app_core` only. `app_db_port` and `app_db_secret_arn` are not in
# `resources` again. The sentence inside the statement block that says "the
# list always has three entries" is WRONG and is wrong precisely because of
# this revert; it was restored verbatim from 3ca8d77^ rather than quietly
# repaired, so that the revert is a real revert and not a paraphrase. Do not
# read that sentence as fact — read this block instead.
#
# WHY THAT IS HARMLESS TODAY — AND ONLY TODAY
#
# The AWS-managed AmazonSSMManagedInstanceCore policy attached to this role
# above already grants `ssm:GetParameter` and `ssm:GetParameters` on
# "Resource": "*". IAM attachments to a role are ADDITIVE and there is no deny
# anywhere in this stack, so narrowing this customer policy removes nothing
# that the managed one is not already granting. The effective set of readable
# parameters is identical before and after the revert. This policy is
# documentation of intent, not an enforcement point — which is exactly why
# re-adding two ARNs to it is safe to defer and worth deferring.
#
# ⚠️  THIS REVERT IS NOW SUPERSEDED; THE POLICY IS AN ENFORCEMENT POINT  ⚠️
#
# The defect this revert reinstates is Milestone 2 audit defect 3, recorded in
# commit 3ca8d77 ("fix: correct four defects found in the Milestone 2 audit"):
# the SSM read policy covered one of the three parameters its own comments
# claimed it covered, so the rendered document and its documentation
# disagreed. 3ca8d77 corrected it by concat-ing three splats, mirroring
# outputs.tf's `db_ssm_parameter_names`.
#
# It remains owed, and it must land as its OWN reviewed apply — with its own
# review, its own plan, and no unrelated change travelling alongside it. Do
# not treat the reverted state below as the intended end state, and do not
# "fix" it by hand at some later point without re-reading this block first.
#
# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  THE SSM BOUNDARY IS RESTRICTED TO THREE PARAMETERS — AN EXPLICIT DENY  ⚠️
# ⚠️  CARVES THEM OUT OF THE MANAGED-POLICY WILDCARD; NO LONGER A TRACKED GAP  ⚠️
# ═══════════════════════════════════════════════════════════════════════════
#
# The asymmetry this file now embodies, stated once, plainly:
#
#   * NARROWING SECRETS MANAGER IS A REAL BOUNDARY IMPROVEMENT. Repointing
#     db_secret_read from the RDS master secret to the application credential
#     removes this role's reach over every other SECRET in the account, and
#     nothing else in the account grants secretsmanager:GetSecretValue. That
#     narrowing actually takes effect.
#
#   * NARROWING SSM IS NOW REAL. The explicit Deny statement in the data
#     source below denies `ssm:GetParameter*` on every resource except this
#     stack's three parameters (NotResource), carving them out of the managed
#     policy's wildcard. Deny wins over the additive managed Allow, so the
#     effective grant is exactly these three parameters. This boundary is
#     enforced here, not merely documented.
#
# So the SSM half of "restricted parameter and secret access" is now enforced:
# parameter reads are limited to this stack's three parameters. The remaining
# gap is structural, not scoped — see the FOLLOW-UP note below.
#
# FOLLOW-UP (not this change): detach AmazonSSMManagedInstanceCore from this
# role and grant the agent's actions explicitly, resource-scoped where AWS
# allows it and on "*" only where AWS does not (ssmmessages and
# ssm:DescribeParameters). That is what would make the SSM side of the
# boundary real. It is its own change, with its own blast radius — that managed
# policy is what keeps Session Manager working — and it needs its own review.
data "aws_iam_policy_document" "ssm_parameter_read" {
  # Count-gated on the SAME condition as the parameters themselves. A data
  # source whose `resources` list is empty produces a policy document with an
  # empty Resource array, which IAM rejects — so this cannot simply be
  # unconditional. Because the gate matches the resources' gate exactly, the
  # `[0]` inside the block is reached only when index 0 exists.
  count = var.enable_managed_database ? 1 : 0

  statement {
    sid    = "ReadOnlyApplicationParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameters",
      "ssm:GetParameter",
    ]

    # Splat, not an index: yields the full list when they exist and an empty
    # list when they do not, with no chance of an out-of-range error. Under
    # this count guard the list always has three entries.
    resources = concat(
      aws_ssm_parameter.app_core[*].arn,
      aws_ssm_parameter.app_db_port[*].arn,
      aws_ssm_parameter.app_db_secret_arn[*].arn,
    )
  }

  # ⚠️  EXPLICIT DENY — REQUIRED BECAUSE IAM ATTACHMENTS ARE ADDITIVE ⚠️
  #
  # The EC2 role also carries AmazonSSMManagedInstanceCore (iam.tf:112-115),
  # which grants ssm:GetParameter* on "Resource": "*". IAM attachments to a
  # role are additive and this stack declares no other deny, so without this
  # statement the role can read EVERY parameter in the account — not just the
  # three above. An explicit Deny is the only construct that survives an
  # additive managed-policy attachment; nothing in a customer Allow can revoke
  # a managed Allow. The reason the deny is necessary, and why it scopes the
  # way it does, is recorded at iam.tf:213-286.
  #
  # A plain `resources = ["*"]` Deny would NOT close the hole here: Deny wins
  # over Allow, so it would also deny reads of the three parameters this
  # stack needs. NotResource carves those three out of the denial instead, so
  # they remain readable (via this Allow and the managed policy) while every
  # other parameter in the account is denied. The effective grant is exactly
  # these three parameters and nothing else.
  #
  # TRADE-OF: this Deny narrows future SSM use. Any ssm:GetParameter* call
  # against any parameter outside the three is denied, even if a later change
  # has a legitimate reason to read it. Session Manager is unaffected — it
  # uses ssmmessages, ssm:GetDocument and ssm:UpdateInstanceInformation, not
  # ssm:GetParameter*. Revisiting this trade-off is its own change; see the
  # follow-up note at iam.tf:174-205 about detaching the managed policy.
  statement {
    sid     = "DenySSMReadOutsideStackParameters"
    effect  = "Deny"
    actions = ["ssm:GetParameter*"]
    # NotResource: deny the wildcard actions on every resource EXCEPT the
    # three this stack needs, so those three stay readable and everything
    # else in the account is denied. `ssm:GetParameter*` matches
    # ssm:GetParameter and ssm:GetParameters (trailing wildcard).
    not_resources = concat(
      aws_ssm_parameter.app_core[*].arn,
      aws_ssm_parameter.app_db_port[*].arn,
      aws_ssm_parameter.app_db_secret_arn[*].arn,
    )
  }
}

resource "aws_iam_policy" "ssm_parameter_read" {
  count = var.enable_managed_database ? 1 : 0

  name        = "${local.name_prefix}-ec2-ssm-parameter-read"
  description = "Read-only access to this stack's own SSM parameters (db host, port, secret ARN)."
  policy      = data.aws_iam_policy_document.ssm_parameter_read[0].json

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ec2-ssm-parameter-read"
  })
}

resource "aws_iam_role_policy_attachment" "ssm_parameter_read" {
  count = var.enable_managed_database ? 1 : 0

  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.ssm_parameter_read[0].arn
}

# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  SECRET ACCESS — THE MOST IMPORTANT POLICY IN THIS FILE  ⚠️
# ═══════════════════════════════════════════════════════════════════════════
#
# This is the milestone's "restricted secret access" requirement, and it is the
# one place in this stack where a single character of sloppiness hands over the
# account.
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  A WILDCARD "Resource": "*" ON secretsmanager:GetSecretValue GRANTS     │
# │  READ ACCESS TO EVERY SECRET IN THE ACCOUNT.                             │
# │                                                                          │
# │  Not this stack's database password. Every secret: every other database,  │
# │  every API key, every third-party credential, every token anyone has ever │
# │  stored. It is the single most common IAM over-permission mistake in      │
# │  cloud infrastructure, and it looks completely correct in a plan.         │
# │                                                                          │
# │  It is also the mistake that survives review. "Resource: *" on a          │
# │  secretsmanager statement reads as unremarkable — IAM examples do it,     │
# │  tutorials do it, and it grants nothing obviously catastrophic until     │
# │  someone uses the role.                                                  │
# └──────────────────────────────────────────────────────────────────────────┘
#
# The resource below is therefore ONE ARN — and as of this revision it is the
# APPLICATION credential, not the master password:
#
#     data.aws_secretsmanager_secret.app_db[0].arn
#
# This file used to grant the master secret instead, via
# aws_db_instance.db[0].master_user_secret[0].secret_arn. The change is
# deliberate and is the security point of the whole change; the reasoning is
# set out below.
#
# Three properties of the new expression, in order of importance:
#
#   1. IT IS THE ACTUAL SECRET. Not a name this file guesses. The data source
#      resolves the name to the ARN AWS reports, at plan time. A hand-written
#      ARN would be a string that has to be kept in sync with a name AWS
#      chooses — a silent failure where the policy is syntactically valid,
#      applies cleanly, grants nothing, and is discovered only when the
#      application fails to find its own database password.
#   2. IT FOLLOWS THE SECRET. If the secret is deleted and recreated — a
#      rotation, a re-bootstrap — the ARN changes, the data source resolves the
#      new one, and this policy follows. Note what this now does that the old
#      expression did not have to: the app credential is INDEPENDENT of the RDS
#      instance, so destroying and recreating the database no longer changes
#      this ARN at all. The credential the application uses now outlives the
#      thing it authenticates to.
#   3. IT IS ONE ARN. If the count guard were ever removed by accident, this
#      policy would still name exactly one secret, because it is a single
#      element in a list. There is no splat here and nothing to expand.
#
# WHY THE APPLICATION CREDENTIAL AND NOT THE MASTER PASSWORD
#
# The master secret is the RDS owner's credential: it owns the database, it can
# CREATE EXTENSION, it can drop tables, it can read every row of every schema.
# Granting it to the EC2 role meant granting the application — and anything
# that gets code execution on that host — the ability to dismantle the database
# it is meant to be using.
#
# The app secret holds the `lemondrop_app` role, which has SELECT/INSERT/UPDATE
# on public.documents and nothing else. That is what the application actually
# needs, and it is what it now gets.
#
# ⚠️  THIS IS A CONTROL, NOT A CONVENTION. ⚠️
#
# Instance-profile credentials are readable by ANY process on the instance.
# Not just the application — any shell, any container, anything that can reach
# 169.254.169.254. So a policy that names the master secret is not a policy
# that "the application is careful not to abuse". It is a policy that hands
# database-admin to every process on the box, and relies on all of them being
# careful. Naming the app secret makes the blast radius of a compromise equal
# to the application's actual privileges, which is the only blast radius that
# can be reasoned about.
#
# ⚠️  MIGRATIONS DELIBERATELY LOSE THEIR EC2 PATH. ⚠️
#
# This is the intended consequence, not a regression, and it is the reason to
# read this comment before "fixing" it. After this change the instance role
# cannot read the master secret, so Alembic cannot run from EC2 — it could not
# run from EC2 as the app role in any case, because CREATE EXTENSION requires
# rds_superuser, which is precisely the split between the two credentials.
#
# The correct path for migrations is unchanged and remains: run them from the
# OPERATOR'S WORKSTATION, using the operator's own AWS profile to read the
# master secret, over an SSM port-forward to RDS. Never from EC2. If someone
# reaches for an EC2 migration path after this change, they are about to widen
# this policy back to the master secret to make it work. The answer is to fix
# the runbook, not the policy.
#
# Resolution on EC2 is unaffected by any of this: the resolver in
# api/app/config.py reads the SSM parameter at the bottom of this file, follows
# the ARN it finds there, and only ever needed the APP secret. AWS_RESOLVE-style
# DSN resolution keeps working.
#
# ⚠️  NARROWING SECRETS MANAGER DOES NOT NARROW SSM. ⚠️
#
# `ssm_parameter_read` further down this file is a separate concern and is NOT
# changed by this revision. Its own description already records that it is not
# an effective restriction, because the AWS-managed AmazonSSMManagedInstanceCore
# attached above grants wildcard ssm:GetParameter* and IAM attachments are
# additive with no deny. So this change removes the wildcard access to every
# SECRET in the account while leaving the wildcard access to every PARAMETER in
# the account exactly where it was. That asymmetry is a known, separately
# documented limitation with its own follow-up — this revision does not fix it,
# and does not claim to.
#
# KNOWN AND ACCEPTED — the AWS-managed KMS key
# The secret is encrypted with the AWS-managed `aws/secretsmanager` key (the
# bootstrap's create_secret call passes no KmsKeyId). That key's policy
# delegates access decisions to IAM on the secret itself, so no explicit
# `kms:Decrypt` grant is needed for this role to read it. If the secret is ever
# re-encrypted with a customer-managed key, this policy must gain a
# `kms:Decrypt` statement scoped to THAT key, or reads will fail with an
# AccessDenied that names KMS rather than Secrets Manager.

# ── The application secret: a REFERENCE, not ownership ───────────────────────
#
# WHY THE SECRET IS NOT CREATED BY TERRAFORM
#
# The secret `lemondrop/dev/db/app` is created OUT OF BAND, by
# lemondrop_app_bootstrap.py, and is deliberately not managed by this
# configuration. The credential has to be generated and delivered without ever
# passing through Terraform — a managed `aws_secretsmanager_secret_version`
# would put the generated password into the state file, which lives in an S3
# bucket, and a password in state is a password in the world. The bootstrap
# keeps the value out of state by never handing it to Terraform at all; it
# hands over the ARN.
#
# ⚠️  THIS IS A REFERENCE. `terraform destroy` WILL NOT DELETE THIS SECRET. ⚠️
#
# That is intentional, and it is the correct behaviour for something this
# configuration does not own. A data source records that a thing exists; it
# confers no lifecycle authority over it. Deleting an operator-created
# credential because someone destroyed the stack that merely referenced it
# would be a data-loss bug, not a feature. The teardown path for this secret is
# lemondrop_app_bootstrap.py's own, run deliberately.
#
# ⚠️  THIS STORES METADATA ONLY. THE VALUE MUST NEVER REACH STATE. ⚠️
#
# What this data source persists into state: the secret's NAME, its ARN, its
# description, its created date, and its tags. That is the whole of it.
#
# What it must never persist: the SecretString. `aws_secretsmanager_secret`
# reads metadata by design and is not capable of returning the value, which is
# why it is the right shape for this reference.
#
# Therefore: DO NOT ADD `aws_secretsmanager_secret_version` TO THIS
# CONFIGURATION. It is the one resource type that WOULD write the password into
# state, which is the exact failure manage_master_user_password exists to
# prevent (see database.tf). If a future change appears to need it — to rotate
# the credential, say — that is the signal to run the bootstrap script again,
# not to reach for a Terraform resource that resolves the secret. This note is
# load-bearing; do not delete it as a stale comment.
#
# ⚠️  THE PLAN WILL FAIL IF THIS SECRET DOES NOT EXIST. THAT IS CORRECT. ⚠️
#
# Read past `count = 0` and the plan error is ResourceNotFoundException on this
# secret. That is not a defect in this file and it is not something to suppress
# with a lifecycle or a `try`. It means the bootstrap has not been run, and the
# SSM parameter below would otherwise be publishing an ARN that resolves to
# nothing — so the application would fail at connection time with a confusing
# "parameter not found" far from the actual cause. Failing here fails early and
# names the real problem. Run lemondrop_app_bootstrap.py, then plan again.
data "aws_secretsmanager_secret" "app_db" {
  # Same gate as the database. Ungated, this would be looked up on every plan
  # even for a stack with no managed database, and the two references to it
  # below (the policy document and the SSM parameter) would then have to be
  # gated differently to avoid indexing a list that does not exist. Same
  # condition, same `[0]`, reached only when index 0 exists.
  count = var.enable_managed_database ? 1 : 0

  # A literal name, and deliberately so: this secret is not built from any
  # variable in this file. It is created by the bootstrap script, which is not
  # Terraform, which means there is no interpolation for Terraform to do —
  # writing `/${var.project_name}/${var.environment}/db/app` here would be a
  # string that LOOKS derived and matches the SSM parameters' naming rule while
  # being coupled to a different author's naming choice. If the bootstrap ever
  # changes SECRET_NAME, THIS line is what has to change with it, and there is
  # exactly one of it.
  name = "lemondrop/dev/db/app"
}

data "aws_iam_policy_document" "db_secret_read" {
  # Same gate as the database, and the same gate as the data source above it.
  # The rationale for gating this block at all has changed: it used to be that
  # the statement referenced aws_db_instance.db[0], which has no index 0 when
  # the database is unmanaged. It no longer references the database — it
  # references data.aws_secretsmanager_secret.app_db[0] — but that data source
  # is itself count-gated, so an ungated policy document would carry the same
  # "Invalid index" failure one level up. Keeping the gates identical is what
  # makes the `[0]` inside this block safe, and the sibling resources below
  # (the policy and its attachment) gate identically for the same reason.
  count = var.enable_managed_database ? 1 : 0

  statement {
    # Renamed from ReadOnlyDatabaseMasterSecret, which is no longer true of it.
    # The Sid is part of the rendered policy document, so it is also what shows
    # up in an IAM Access Analyzer finding and in CloudTrail — a reader seeing
    # "Master" on a live stack would correctly conclude the stack still grants
    # the master password. It does not.
    sid    = "ReadOnlyApplicationDbSecret"
    effect = "Allow"

    # GetSecretValue ONLY. Not DescribeSecret (metadata this role has no use
    # for), not GetSecretValue on a wildcard, not ListSecrets. The narrowest
    # action that makes the application work. UNCHANGED by this revision: the
    # action list was never the problem, the Resource was.
    actions = ["secretsmanager:GetSecretValue"]

    # ⚠️  ONE ARN. NEVER "*". ⚠️  See the box above.
    #
    # Repointed from aws_db_instance.db[0].master_user_secret[0].secret_arn to
    # the application credential's ARN. See the box above for why, and for the
    # fact that this file deliberately removes the instance's ability to read
    # the master secret at all.
    resources = [data.aws_secretsmanager_secret.app_db[0].arn]
  }
}

# ⚠️  THIS IS AN IN-PLACE UPDATE. IT IS NOT A REPLACEMENT. ⚠️
#
# Stated first and plainly, because an earlier version of this comment said the
# opposite and was wrong: `policy` is NOT ForceNew on aws_iam_policy. When the
# rendered document changes, the provider's resourcePolicyUpdate calls
# CreatePolicyVersion against the EXISTING managed policy. Repointing this
# document's single ARN from the RDS master secret to the application secret is
# therefore an ordinary document edit applied to a live policy. The policy
# keeps its ARN, aws_iam_role_policy_attachment.db_secret_read below is not
# touched, and no managed policy is created or deleted.
#
# ⚠️  SO THIS CHANGE CARRIES NO WINDOW OF ANY KIND. ⚠️
#
# There is no moment in which the EC2 role can read neither secret, and no
# moment spent waiting for an attachment to be re-pointed at a new ARN. There
# is nothing here to schedule around and no "only safe before the M3
# application is deployed" caveat attached to the document change — that
# caveat never belonged here. An application on the host throughout the apply
# holds a grant the whole time; the grant is rewritten underneath it, not
# withdrawn and reissued, so there is no AccessDenied to hit.
#
# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  WHAT WOULD REPLACE THIS POLICY — AND IT IS NOT `policy`.           ⚠️
# ═══════════════════════════════════════════════════════════════════════════
#
# `description` IS ForceNew. That is the argument on this resource that forces
# replacement, and on this resource it is the only reason a window can exist at
# all. Correcting the stale description — which this revision deliberately does
# NOT do, for the reason set out in the block immediately below — would not be
# a string update. It would create a new managed policy under the same name,
# re-point the attachment at the new ARN, and delete the old one. IAM is
# eventually consistent and Terraform does not do that create-then-attach-then-
# detach atomically, so between the old policy losing effect and the new one
# being attached the EC2 role holds NO secretsmanager grant at all. An
# application running on that host in that window gets an AccessDenied on its
# database credential — not a wrong answer, a hard failure.
#
# ⚠️  SEQUENCING FOR ANY FUTURE CHANGE THAT FORCES REPLACEMENT. ⚠️
#
# The ordering below is the guidance for THAT operation, not for the document
# edit above, and it is worth keeping for the day it is needed. Order it so
# that no moment exists without a working credential:
#
#     1. ADD    the new permission to the document, leaving the superseded
#               one in place. This is a document edit, so it lands in place and
#               costs nothing by itself. Two statements, two ARNs, both
#               permitted.
#     2. Deploy the application and let it resolve and use the new credential
#               until it is demonstrably working on that path. From here on,
#               nothing depends on the grant that the next step removes.
#     3. MAKE THE CHANGE THAT FORCES REPLACEMENT. For this resource that is
#               the description. The replacement window falls here, and it
#               falls only on a grant nothing needs.
#
# Only step 3 has a window, and by then nothing depends on what that window
# removes. Steps 1 and 2 are not there to protect the policy from step 3 — they
# are there to make step 3 disposable. Skip them and the replacement interrupts
# a live application; keep them and the replacement is a formality.
#
# Collapsing the three into one apply is what would be unsafe. The reason THIS
# revision does not need them is not that it is carefully sequenced, but that
# it is not a replacement at all. Say it in those terms in the PR: the document
# is repointed in place, the description is wrong on purpose and is waiting for
# its own reviewed apply. Nobody should have to re-derive which is which.
#
# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  THE `description` BELOW IS NOW INACCURATE. THIS IS KNOWN, AND IT IS  ⚠️
# ⚠️  DELIBERATE. IT IS NOT AN OVERSIGHT.                           ⚠️
# ═══════════════════════════════════════════════════════════════════════════
#
# Read this before trusting the string next to `description`.
#
# The policy DOCUMENT of this resource has been repointed: `resources` names
# data.aws_secretsmanager_secret.app_db[0].arn — the APPLICATION credential —
# and it no longer names aws_db_instance.db[0].master_user_secret[0].secret_arn
# at all. The stack does not grant the master password secret any more.
#
# The `description`, however, still reads "Read-only access to THIS STACK'S
# database master password secret." That is FALSE. It describes the document
# this resource used to carry. Do not read it as truth, do not quote it as a
# description of what is granted, and do not treat a future reviewer who
# notices the mismatch as having found a new defect — this note is the
# explanation, and it was written before the apply, not after.
#
# WHY IT WAS NOT CORRECTED
#
# `description` is ForceNew on aws_iam_policy. Correcting it is not an in-place
# string update — it forces the managed policy to be REPLACED: a new policy
# created under the same name, the attachment re-pointed at the new ARN, the
# old policy deleted. That is precisely the disruptive, gap-producing
# operation the operator has declined for this apply. The policy argument
# updates in place and does not force replacement; the description does. So the
# description stays wrong on purpose, and the cost of keeping it wrong — a
# misleading sentence in one resource block — is being traded for not
# destroying and recreating a live IAM policy.
#
# FOLLOW-UP (not this change): correct the description to name the application
# credential. Do it as its own reviewed apply, with the replacement and its
# brief window in mind. Until then, this comment is the accurate description
# and the `description` argument is the inaccurate one.
resource "aws_iam_policy" "db_secret_read" {
  count = var.enable_managed_database ? 1 : 0

  name        = "${local.name_prefix}-ec2-db-secret-read"
  description = "Read-only access to THIS STACK'S database master password secret. Nothing else in the account."
  policy      = data.aws_iam_policy_document.db_secret_read[0].json

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ec2-db-secret-read"
  })
}

resource "aws_iam_role_policy_attachment" "db_secret_read" {
  count = var.enable_managed_database ? 1 : 0

  # UNTOUCHED BY THIS REVISION, and that is worth knowing rather than assuming.
  # The document above changed; this attachment did not and has no reason to.
  # `policy` is not ForceNew, so the managed policy keeps the same ARN through
  # a document edit, policy_arn below resolves to the identical string, and
  # Terraform has nothing to detach and nothing to attach. An earlier version
  # of this comment claimed the opposite — that this block is recreated as a
  # side effect of a policy replacement, and that it is the mechanism by which
  # a "reads NEITHER secret" window happens. Both were wrong, and both were
  # true only of the FORCE-NEW argument, `description`. This block IS the
  # mechanism by which such a window would happen, were that argument ever
  # changed: the role has no other grant for this secret, so the moment the
  # attachment is re-pointed and the old policy deleted, it holds no
  # secretsmanager grant at all. That is why the description is left stale
  # here, and why the sequencing above is written for a change of that kind.
  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.db_secret_read[0].arn
}

# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  NO ACCESS KEYS. NONE. AND NOT BY OMISSION — BY DECISION. ⚠️
# ═══════════════════════════════════════════════════════════════════════════
#
# There is no `aws_iam_access_key` in this file, and no IAM user anywhere in
# this stack. The absence is deliberate and it is the difference between this
# role being short-lived and being permanent.
#
# WHY, PLAINLY:
#   An access key on an instance profile is the pattern behind a large fraction
#   of real AWS credential compromises. It is long-lived — measured in months —
#   it does not expire, does not rotate on its own, and does not expire when
#   the human who created it leaves. It is written to disk. It survives in
#   cloud-init logs, in shell history, in a core dump, in a container image
#   layer, in an SSM session transcript. Every one of those is a copy that
#   nothing is tracking.
#
#   And it is not needed for anything. The SSM agent gets temporary credentials
#   from the instance role through IMDS, rotates them automatically, and they
#   are scoped to this role's policies — which is one secret ARN and three SSM
#   parameters. There is no capability in this stack that an access key would
#   grant and the role would not.
#
#   The failure mode is asymmetric too. With temporary credentials, a
#   compromised instance is a compromise that expires in hours and shows up as
#   an unusual role assumption in CloudTrail. With an access key, it is a
#   compromise that persists until someone notices and rotates it, and it is
#   still working after the attacker is gone.
#
# IF YOU FIND YOURSELF WANTING AN ACCESS KEY HERE
# That want is a signal, not a requirement. It usually means one of:
#   * a tool that cannot use the instance profile → use a user with
#     `aws sso` / IAM Identity Center credentials on the operator's laptop
#     instead, which are also temporary and also CloudTrail-visible;
#   * a CI system needing access → give the CI system a role, not a key
#     (OIDC federation from GitHub Actions is a few lines and no long-lived
#     secret exists anywhere);
#   * genuine debugging need → add a CloudTrail log to see what is actually
#     being called, instead of a credential that bypasses the question.

# ── Instance profile — how the host receives the role ──────────────────────
#
# The profile is the bridge: EC2's metadata service serves temporary
# credentials from it, and every AWS call the host makes is signed with them.
resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name_prefix}-ec2"
  role = aws_iam_role.ec2.name

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ec2"
  })
}

# ═══════════════════════════════════════════════════════════════════════════
# SSM CORE PARAMETERS — how the host finds the database without hardcoding it
# ═══════════════════════════════════════════════════════════════════════════
#
# The application needs three facts to reach the database: where it is, what
# port, and which secret holds the password. Two of those three are values that
# AWS decides — the endpoint hostname and the secret's ARN are not knowable
# before the database exists — and the third is a constant.
#
# The wrong answer is to pass them into the host at launch. The right answer is
# to publish them where the host can look them up with its own permissions:
# discovery, not configuration. The host's IAM role carries a policy scoped to
# exactly these three parameters and nothing else, so "what this stack's own
# policy can read out of the account" is a short, checkable list.
#
# ⚠️  THAT LIST DESCRIBES THIS POLICY, NOT THE ROLE'S EFFECTIVE POWERS. ⚠️
# The role is also attached AmazonSSMManagedInstanceCore, which grants
# ssm:GetParameter* on "Resource": "*", and IAM attachments are additive with
# no deny. So the role can in fact read every parameter in the account. This
# policy narrows what would be granted absent the managed one; it does not
# narrow what is actually granted today.
#
# ⚠️  THERE IS AND WILL NEVER BE A FOURTH PARAMETER FOR THE PASSWORD ⚠️
# ⚠️  RDS-managed master passwords live in SECRETS MANAGER and only there. ⚠️
#
# Not in Terraform state (see `manage_master_user_password` in database.tf for
# why that matters when state is in an S3 bucket), not in this file, not in
# user_data, not in an environment variable, not on a command line. The
# hostname and port are configuration; a credential is not. Publishing a
# password to Parameter Store would be storing it somewhere with a different
# access story, a different blast radius, and no compensating advantage —
# and it would reintroduce exactly the plaintext-in-state problem that
# manage_master_user_password exists to solve.
#
# What the host does instead, at the moment it needs the password:
#
#     aws secretsmanager get-secret-value \
#       --secret-id <the ARN from the parameter below> \
#       --query SecretString --output text
#
# That call is authorised by the single-ARN policy above. The password is
# read into the process that needs it, at the moment it needs it, and is not
# written anywhere.

# ⚠️  NAMING RULE — AN API CONTRACT, NOT STYLE. READ BEFORE EDITING. ⚠️
#
# A Parameter Store name is a FULLY QUALIFIED PATH, and the path form is:
#
#     /<root>/<hierarchy>/<leaf>      →  /lemondrop/dev/db/host   ✅
#
# It must BEGIN with a forward slash. It must NOT END with one. It must not
# contain an empty path segment (a double slash).
#
# ⚠️  THIS RULE HAS ALREADY BEEN MIS-APPLIED ONCE IN EACH DIRECTION. ⚠️
#
# Apply #1: the names were written without a leading slash and AWS returned
#     ValidationException: Parameter name must be a fully qualified name.
# The reading applied to that was that the names needed TRAILING slashes, so
# they were changed to "…/db/host/". That reading was wrong, and it produced a
# second apply failure:
#     ValidationException: Parameter name must not end with slash.
#
# Both errors are real; the rule they describe is the one above. "Fully
# qualified" means the path is rooted — it is the LEADING slash that expresses
# that, not the trailing one. Do not "simplify" these names by dropping the
# leading slash, and do not re-add a trailing slash to satisfy a different
# error message. If a future apply rejects these names, read WHICH of the three
# rules is actually being violated before changing the string.
#
# It is written out on each resource rather than assembled in a local because a
# local is one more place for a slash to be lost — and nothing in Terraform
# validates this at plan time, so a regression here surfaces only at apply.
#
# The names are interpolated from var.project_name and var.environment rather
# than written as literals, so the "dev" in "lemondrop/dev/db" is the variable
# default and follows the environment name if it changes.
#
# The read policy above uses aws_ssm_parameter.app_core[*].arn, which AWS
# derives from these names, so it follows the change automatically.
#
# Nothing in user_data reads these three by name — compute.tf explicitly
# forbids hardcoding a DATABASE_URL and tells the future application to fetch
# at runtime through the instance role. So there is no second copy of these
# paths to keep in sync, and no boot script to break if they change. The
# db_ssm_parameter_names output in outputs.tf derives from the resources
# rather than repeating them, which is the same property.
resource "aws_ssm_parameter" "app_core" {
  count = var.enable_managed_database ? 1 : 0

  name  = "/${var.project_name}/${var.environment}/db/host"
  type  = "String"
  value = aws_db_instance.db[0].address

  description = "RDS endpoint hostname. Read by the application host through its instance role."

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-host"
  })
}

resource "aws_ssm_parameter" "app_db_port" {
  count = var.enable_managed_database ? 1 : 0

  name  = "/${var.project_name}/${var.environment}/db/port"
  type  = "String"
  value = tostring(local.db_port)

  description = "RDS port. Read by the application host through its instance role."

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-port"
  })
}

resource "aws_ssm_parameter" "app_db_secret_arn" {
  count = var.enable_managed_database ? 1 : 0

  # ⚠️  THE NAME IS AN API CONTRACT. DO NOT RENAME. ⚠️
  #
  # `DB_SSM_SECRET_ARN_LEAF = "secret-arn"` in api/app/config.py builds the leaf
  # from var.project_name / var.environment and reads this exact parameter.
  # Renaming this parameter, adding a second one alongside it, or moving the
  # value under a new key all break resolution on the running host with a
  # missing-parameter error that points at the resolver rather than here. The
  # leaf is the interface; only the VALUE below is allowed to change.
  name = "/${var.project_name}/${var.environment}/db/secret-arn"
  type = "String"

  # Repointed from aws_db_instance.db[0].master_user_secret[0].secret_arn to the
  # application credential's ARN, so that the ARN this parameter publishes is
  # one the EC2 role is actually permitted to read (see the policy above). Left
  # pointing at the master ARN, the host would resolve an ARN it can no longer
  # read — a failure that surfaces as AccessDenied at first use, with a DSN
  # assembled from a perfectly valid secret name.
  #
  # An in-place update: only .value changes here, which the provider applies
  # as a PutParameter against the same name. No create, no destroy, no gap —
  # the same property the policy DOCUMENT has, which is why the two edits ship
  # in one apply without anything being interrupted. (The policy's
  # `description` is not an in-place update, and is not being changed here; see
  # the block above the policy resource for why it stays stale.)
  value = data.aws_secretsmanager_secret.app_db[0].arn

  description = "ARN of the Secrets Manager secret holding the APPLICATION database credential (the least-privilege lemondrop_app role). NOT the RDS master password secret. The ARN, never the credential itself. Read by the application host through its instance role."

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-secret-arn"
  })
}