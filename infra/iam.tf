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

# ── AWS-managed EC2 role ───────────────────────────────────────────────────
# AWS's own base policy for EC2 instances: CloudWatch agent and SSM agent
# communication. Not optional if you want CloudWatch metrics or Session
# Manager.
resource "aws_iam_role_policy_attachment" "ec2_instance_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2InstanceRole"
}

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
# The one thing the managed policy genuinely does NOT grant is noted below,
# under ssm_parameter_read — and that gap is real, so it gets its own policy.

# ═══════════════════════════════════════════════════════════════════════════
# SSM PARAMETER READ — a genuine gap in the managed policy, closed narrowly
# ═══════════════════════════════════════════════════════════════════════════
#
# ⚠️  AmazonSSMManagedInstanceCore DOES NOT GRANT `ssm:GetParameters` ⚠️
#
# This surprises people, including people who have attached it and then
# wondered why `aws ssm get-parameters` returned AccessDenied from the
# instance. That policy covers the agent's control channel — registering the
# instance, running documents, reporting associations. Reading YOUR OWN
# parameters is a different permission and is not in it.
#
# So this policy exists, scoped to exactly the three parameters created at the
# bottom of this file, and to nothing else in the account. Note that
# `ssm:DescribeParameters` is deliberately NOT included: it cannot be
# resource-scoped (AWS requires "Resource": "*" for it), and it is a
# metadata-only listing call that this stack has no use for. Nothing in this
# file grants a wildcard against SSM.
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
    resources = aws_ssm_parameter.app_core[*].arn
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
# The resource below is therefore ONE ARN, built from the RDS instance that
# creates it:
#
#     aws_db_instance.db[0].master_user_secret[0].secret_arn
#
# Three properties of that expression, in order of importance:
#
#   1. IT IS THE ACTUAL SECRET. Not a name this file guesses. RDS names the
#      secret itself, and this is the ARN AWS reports for it. A hand-written
#      ARN would be a string that has to be kept in sync with a name AWS
#      chooses — a silent failure where the policy is syntactically valid,
#      applies cleanly, grants nothing, and is discovered only when the
#      application fails to find its own database password.
#   2. IT FOLLOWS THE SECRET. If the database is destroyed and recreated — a
#      version bump, a restore, a wrong-region incident cleaned up — the secret
#      ARN changes with it and this policy changes with it. A hardcoded ARN
#      would keep granting the OLD secret, or nothing, and would need a human
#      to notice.
#   3. IT IS ONE ARN. If the count guard were ever removed by accident, this
#      policy would still name exactly one secret, because it is a single
#      element in a list. There is no splat here and nothing to expand.
#
# KNOWN AND ACCEPTED — the AWS-managed KMS key
# The secret is encrypted with the AWS-managed `aws/secretsmanager` key. That
# key's policy delegates access decisions to IAM on the secret itself, so no
# explicit `kms:Decrypt` grant is needed for this role to read it. If the
# secret is ever re-encrypted with a customer-managed key, this policy must
# gain a `kms:Decrypt` statement scoped to THAT key, or reads will fail with
# an AccessDenied that names KMS rather than Secrets Manager.

data "aws_iam_policy_document" "db_secret_read" {
  # Same gate as the database. Ungated, this would reference
  # aws_db_instance.db[0] with no instance at index 0, and the plan would fail
  # with "Invalid index" — the exact class of bug this gating exists to
  # prevent, on the one resource where a plan-time failure would be most
  # confusing to debug.
  count = var.enable_managed_database ? 1 : 0

  statement {
    sid    = "ReadOnlyDatabaseMasterSecret"
    effect = "Allow"

    # GetSecretValue ONLY. Not DescribeSecret (metadata this role has no use
    # for), not GetSecretValue on a wildcard, not ListSecrets. The narrowest
    # action that makes the application work.
    actions = ["secretsmanager:GetSecretValue"]

    # ⚠️  ONE ARN. NEVER "*". ⚠️  See the box above.
    resources = [aws_db_instance.db[0].master_user_secret[0].secret_arn]
  }
}

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
# discovery, not configuration. The host's IAM role is scoped to read exactly
# these three parameters and nothing else, so "what can this instance read out
# of the account" is a short, checkable list.
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

resource "aws_ssm_parameter" "app_core" {
  count = var.enable_managed_database ? 1 : 0

  name  = "${var.project_name}/${var.environment}/db/host"
  type  = "String"
  value = aws_db_instance.db[0].address

  description = "RDS endpoint hostname. Read by the application host through its instance role."

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-host"
  })
}

resource "aws_ssm_parameter" "app_db_port" {
  count = var.enable_managed_database ? 1 : 0

  name  = "${var.project_name}/${var.environment}/db/port"
  type  = "String"
  value = tostring(local.db_port)

  description = "RDS port. Read by the application host through its instance role."

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-port"
  })
}

resource "aws_ssm_parameter" "app_db_secret_arn" {
  count = var.enable_managed_database ? 1 : 0

  name  = "${var.project_name}/${var.environment}/db/secret-arn"
  type  = "String"
  value = aws_db_instance.db[0].master_user_secret[0].secret_arn

  description = "ARN of the Secrets Manager secret holding the master password. The SECRET, not the password. Read by the application host through its instance role."

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-secret-arn"
  })
}