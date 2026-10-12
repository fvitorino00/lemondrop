# ═══════════════════════════════════════════════════════════════════════════
# Variables
# ═══════════════════════════════════════════════════════════════════════════

variable "aws_region" {
  description = "AWS region for all resources in this stack."
  type        = string
  default     = "eu-west-1"

  # Ireland (eu-west-1) is the closest AWS region to Portugal, which minimises
  # latency for the operator and for the application's users. The operator may
  # change it freely — nothing in this config hardcodes an availability zone
  # letter, so changing the region does not break the subnet mapping. It does
  # require updating the backend block in versions.tf (backend blocks cannot use
  # variables), since state must live in the same region as the bucket.
}

variable "project_name" {
  description = "Project name, used as a resource name prefix and as a tag."
  type        = string
  default     = "lemondrop"
}

variable "environment" {
  description = "Deployment environment. Also selects the state key prefix convention."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the public subnets, one per availability zone."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) > 0
    error_message = "public_subnet_cidrs must not be empty; the stack requires at least one public subnet for the load balancer."
  }
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for the private subnets, one per availability zone. Must be the same length as public_subnet_cidrs."
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24"]

  validation {
    condition     = length(var.private_subnet_cidrs) > 0
    error_message = "private_subnet_cidrs must not be empty; the stack requires private subnets for EC2 and RDS."
  }
}

# ═══════════════════════════════════════════════════════════════════════════
# allowed_api_cidr — NO DEFAULT, DELIBERATELY
# ═══════════════════════════════════════════════════════════════════════════
#
# This is the operator's home IP allowlist. The only thing permitted to reach
# the load balancer on port 80 is an address in this range.
#
# It has NO DEFAULT on purpose. A default here would be a foot-gun with the
# worst possible failure mode:
#
#   default = "0.0.0.0/0"  →  typo-proof, silently opens the API to the whole
#                              internet. The stack would still plan, still
#                              apply, and still pass a naive "is the ALB
#                              reachable" check. Nobody notices until someone
#                              else finds it.
#
# A missing required variable fails at the EARLIEST possible moment — `plan`,
# before a single resource is created — with a message naming the variable.
# That is the correct failure mode for a security control: loud, early, and
# impossible to miss. Comfortable defaults are a convenience for correctness
# settings, not for safety settings.
#
# Current value is 213.22.54.159/32. If the operator's home IP changes, this is
# what they change, and `terraform plan` shows the rule diffing before it is
# applied.
variable "allowed_api_cidr" {
  description = "CIDR permitted to reach the load balancer on port 80. The operator's home IP allowlist, currently 213.22.54.159/32. NO DEFAULT — an accidental 0.0.0.0/0 here would expose the API to the internet."
  type        = string

  validation {
    condition     = var.allowed_api_cidr != "0.0.0.0/0"
    error_message = "allowed_api_cidr must not be 0.0.0.0/0. This stack is designed to be reachable only from the operator's own IP."
  }
}

# ═══════════════════════════════════════════════════════════════════════════
# COST-CONTROL TOGGLES — READ THIS BEFORE SETTING ANY OF THEM TO FALSE
# ═══════════════════════════════════════════════════════════════════════════
#
# These three booleans are the stack's cost-control mechanism. Each one is a
# default-true feature that bills continuously. Each one is ALSO a milestone
# acceptance criterion.
#
#   ┌─────────────────────────┬───────────────────┬──────────────────────────┐
#   │ toggle                  │ cost              │ what false disables      │
#   ├─────────────────────────┼───────────────────┼──────────────────────────┤
#   │ enable_nat_gateway      │ ~$32/mo + $/GB    │ private-subnet egress:    │
#   │                         │ (most expensive   │ no image pulls, no model  │
#   │                         │ line item)        │ downloads, no apt from    │
#   │                         │                   │ the private subnets       │
#   ├─────────────────────────┼───────────────────┼──────────────────────────┤
#   │ enable_managed_database │ not in Free Tier; │ RDS acceptance criterion; │
#   │                         │ bills continuously│ API has no datastore      │
#   ├─────────────────────────┼───────────────────┼──────────────────────────┤
#   │ enable_load_balancer    │ not in Free Tier; │ ALB acceptance criterion; │
#   │                         │ bills continuously│ no public entry point     │
#   └─────────────────────────┴───────────────────┴──────────────────────────┘
#
# Turning one off removes the COST *and* the CAPABILITY. These are not
# "harmless optimisations" — they are incomplete-milestone switches. A plan
# with all three false does not satisfy the milestone, and the resulting stack
# will not boot the application end to end, because there is no load balancer
# to publish the API and no database for it to talk to.
#
# The operator chooses knowingly, one toggle at a time. Nothing in this config
# disables them automatically.

variable "enable_nat_gateway" {
  description = "Create a NAT gateway so private subnets can reach the internet (image, package, and model pulls)."
  type        = bool
  default     = true

  # ── COST ────────────────────────────────────────────────────────────────
  # A NAT gateway is the single most expensive line item in this stack:
  #   ~$32/month for the gateway itself (it bills whether or not it is used,
  #   including when idle), PLUS per-GB data processing on top.
  # It is the reason `terraform destroy` is documented as the way to stop the
  # meter. See infra/README.md for the full cost table.
  #
  # ── WHAT false DOES ─────────────────────────────────────────────────────
  # The private subnets get a default route to the INTERNET GATEWAY instead of
  # to the NAT gateway. Consequence, stated plainly:
  #   * The private subnets can no longer reach the internet for image pulls,
  #     package installs, or model downloads. EC2 boot will fail to pull a base
  #     image unless you switch it to a public subnet.
  #   * The "private" subnets are no longer egress-isolated. They route directly
  #     to the IGW and traffic leaves with the instance's own public address.
  #     This is a deliberate cost trade, and main.tf carries a loud comment
  #     where it happens. It is not an oversight.
  #
  # Accepting `false` means accepting "no egress isolation for the tier that
  # holds EC2 and, in Phase 2, RDS".
}

variable "enable_managed_database" {
  description = "Create an RDS PostgreSQL instance (managed database)."
  type        = bool
  default     = true

  # RDS is NOT covered by AWS Free Tier and bills CONTINUOUSLY from the moment
  # it is created until it is destroyed. A stopped instance still incurs the
  # instance charge — stopping does not stop the meter, only destroying does.
  # A db.t3.micro PostgreSQL instance with modest storage runs roughly $15-25/
  # month depending on configuration and region.
  #
  # Consumed by Phase 2, not by this config. The variable is declared here so
  # the cost switch for the whole stack lives in one file, and so Phase 2
  # inherits a declared contract rather than inventing one.
}

variable "enable_load_balancer" {
  description = "Create an Application Load Balancer to expose the API."
  type        = bool
  default     = true

  # An ALB is NOT covered by AWS Free Tier and bills CONTINUOUSLY, per-hour,
  # whether or not it receives a single request. A single ALB is roughly $16-20/
  # month plus LCU (load-balancer capacity unit) charges that grow with traffic.
  #
  # Consumed by Phase 2, not by this config. Note that sg_alb exists in THIS
  # config regardless of this toggle — the security group is part of the
  # security story and is cheap (security groups themselves are free). Phase 2
  # decides whether the load balancer resource is created behind it.
}

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 VARIABLES — compute, database, load balancer
# ═══════════════════════════════════════════════════════════════════════════
#
# Added by Phase 2 (compute.tf, database.tf, load_balancer.tf, iam.tf).
# Everything here is a DEFAULT-TRUE production setting, EXCEPT where a default
# would be a foot-gun — those are called out at the variable.
#
# Nothing in this section reintroduces a "comfortable default" for a security
# control. Where a safe default is expensive or noisy (deletion protection),
# the default is the SAFE one and the cost of changing it is the operator's to
# pay knowingly.

# ── Compute ────────────────────────────────────────────────────────────────

variable "app_instance_type" {
  description = "EC2 instance type for the application host that runs all three Compose services."
  type        = string
  default     = "t3.small"

  # ⚠️  THIS DEFAULT HAS NOT BEEN BENCHMARKED. READ THIS BEFORE TRUSTING IT. ⚠️
  #
  # The host runs THREE services and must hold two models resident in RAM at
  # the same time:
  #   * bge-small-en-v1.5 Q8_0  — ~130MB on disk, plus llama.cpp runtime
  #   * bge-reranker-base Q8_0 — ~278MB on disk, plus llama.cpp runtime
  #   * the FastAPI process and its pinned Python dependencies
  # GGUF file size is NOT peak RSS. Loading a Q8_0 model allocates the mapped
  # weights plus the KV/context buffers plus the server's own process overhead.
  # Two models loaded concurrently is the real constraint, and the honest
  # statement is that nobody has measured it yet on this instance type.
  #
  # What IS true, and is the reason this is not t3.micro:
  #   t3.micro has 1 GiB of RAM. Loading a single reranker into it, alongside
  #   the API, is very unlikely to fit. Choosing it as the default would be
  #   claiming a sufficiency that has not been tested, and it would fail as an
  #   OOM kill on boot — which, given the ALB grace-period discussion in
  #   load_balancer.tf, is exactly the kind of failure that gets misdiagnosed
  #   as "the app is slow".
  #
  # t3.small (2 GiB) is a STARTING POINT, not a recommendation. If the boot log
  # shows an OOM kill, or the api never becomes healthy, raise this before
  # investigating anything else. t3.medium (4 GiB) is the next step.
  #
  # Measure it rather than guessing:
  #   ssh/ssm →  docker stats --no-stream
  #             docker compose logs embedder reranker | grep -i 'memory\|error'
  #
  # If this becomes a multi-AZ or production deployment, t3 is also the wrong
  # FAMILY: t3 is burstable, and inference is a sustained load. m6i/m7i is the
  # right family. Out of scope for a single dev host.
}

variable "app_root_volume_size" {
  description = "Root volume size in GiB for the application host. Must hold the OS, Docker images, and both GGUF models (~340MB) plus build layers."
  type        = number
  default     = 30

  # Deliberately modest, deliberately gp3. The instance stores:
  #   AL2023 + Docker + packages          ~ 6-8 GiB
  #   the api image (built on the host)     ~ 1-2 GiB
  #   llama.cpp server image               ~ 1-2 GiB
  #   models/*.gguf                        ~ 0.34 GiB
  # 30 GiB leaves headroom without being a cost decision the operator did not
  # make. If the root volume fills, Docker's disk usage becomes invisible
  # failure — see compute.tf for the comment on the pre-flight check.
}

variable "app_associate_public_ip" {
  description = "Assign a public IP to the application host. Default false; the instance lives in a private subnet and is reached via SSM Session Manager."
  type        = bool
  default     = false

  # THE INTERACTION WITH enable_nat_gateway IS THE POINT OF THIS VARIABLE.
  #
  # With a NAT gateway (the default), a private instance with no public IP is
  # fully operable: the SSM agent reaches the internet through the NAT egress
  # and registers with Systems Manager. Session Manager works. No public
  # address is needed and none is wanted.
  #
  # With NAT DISABLED, the private subnet's default route points at the
  # INTERNET GATEWAY (see main.tf, `aws_route.private_default_via_igw`). A
  # private instance with no public IP then has NO working path out of the
  # subnet at all: the SSM agent cannot reach ssm.*.amazonaws.com, so Session
  # Manager silently never connects, AND — because port 22 is not open and the
  # optional SSH key in compute.tf needs a public IP — there is no second
  # access path either. The instance would be running and unreachable.
  #
  # So: `enable_nat_gateway = false` REQUIRES `app_associate_public_ip = true`,
  # otherwise you have provisioned an unreachable host. Pass it explicitly:
  #
  #   terraform apply -var enable_nat_gateway=false \
  #                    -var app_associate_public_ip=true
  #
  # This variable exists so that escape hatch is one flag instead of a diff.
}

variable "create_ssh_key" {
  description = "Create an EC2 key pair for SSH fallback access. Default false — the recommended access path is SSM Session Manager."
  type        = bool
  default     = false

  # OFF BY DEFAULT, DELIBERATELY, for the same reason `allowed_api_cidr` has no
  # default: the recommended path already works, and enabling the fallback by
  # default means every stack in every account ships an SSH key pair nobody
  # asked for. Note this only creates the KEY PAIR. It opens nothing — port 22
  # is not in any security group in security_groups.tf, so a key pair on its
  # own grants no access. Turning this on does not make the instance reachable;
#   it makes it *reachable-if-someone-also-opens-22*, which is a deliberate,
  #   reviewable second step.
}

variable "ssh_public_key_path" {
  description = "Path to a PUBLIC ssh key file, used only when create_ssh_key is true. Never point this at a private key."
  type        = string
  default     = null

  # A path, not key material. The value is a PUBLIC key, which is public by
  # definition and safe to hold in state; a private key is not, and a variable
  # named ssh_public_key would one day be pointed at the wrong file in a
  # .tfvars and put a private key into the state bucket.
  #
  # Null by default, so the common case — no SSH at all — never reads a file.
  # The validation makes the null/true pairing explicit: asking for a key
  # without saying where the key is fails HERE, at plan time, with a message
  # that names the problem, rather than deeper in with an opaque file error.
  #
  # `file()` is evaluated only inside the count-gated aws_key_pair resource, so
  # with create_ssh_key = false this path is never touched and a missing file
  # cannot fail the plan.

  validation {
    condition     = var.ssh_public_key_path != null || !var.create_ssh_key
    error_message = "ssh_public_key_path must be set when create_ssh_key is true. Point it at a PUBLIC key, e.g. -var ssh_public_key_path=~/.ssh/id_ed25519.pub"
  }
}

variable "app_source_url" {
  description = "Git URL the application host clones its source from at boot. Must be reachable from the instance's subnet."
  type        = string
  default     = "https://github.com/fvitorino00/lemondrop.git"

  # The instance has no copy of the application; user_data clones it at boot.
  # This must be a URL the instance can actually reach. That means EITHER a
  # public repository OR a mechanism for a private one — and the obvious
  # mechanism (a deploy token in the clone URL) is EXPLICITLY NOT USED here,
  # because that would put a credential in user_data, which is stored in plain
  # text on the instance and readable via ec2:DescribeInstanceAttribute. See
  # compute.tf for the full reasoning.
  #
  # If this repository is private, `git clone` in user_data fails and the boot
  # log says so. The fix is NOT a token in the URL — bake an AMI, or push to a
  # registry the instance can pull anonymously, or supply the credential over
  # SSM after the fact.

  validation {
    condition     = can(regex("^https://", var.app_source_url)) || can(regex("^git@", var.app_source_url))
    error_message = "app_source_url must be an https:// or git@ URL so user_data never has to be taught to prompt for credentials."
  }
}

variable "app_health_check_grace_period_seconds" {
  description = "Seconds the ALB target group waits before counting health check failures against the target. Covers the boot-time model download."
  type        = number
  default     = 300

  # NOT a performance tuning knob — it exists because of the ~340MB of GGUF
  # that scripts/fetch-models.sh downloads AT BOOT, before the api can answer a
  # single request. During that window every ALB health check on /health fails,
  # because there is no listener yet. Without a grace period the target would
  # be marked unhealthy, would never be marked healthy, and the stack would
  # look broken for a reason that has nothing to do with the application.
  #
  # 300s is generous on purpose. Being generous costs nothing: the clock only
  # runs while the target is UNHEALTHY, and an instance that boots correctly
  # goes healthy in well under five minutes. Being too short is the failure
  # mode that matters, and it is expensive to diagnose because it looks like
  # an application bug. Raise this before you ever lower it.

  validation {
    condition     = var.app_health_check_grace_period_seconds >= 120
    error_message = "app_health_check_grace_period_seconds must be at least 120. The boot-time model download alone can take minutes; a short grace period turns boot timing into a false application failure."
  }
}

# ── Database ───────────────────────────────────────────────────────────────

variable "db_instance_class" {
  description = "RDS instance class for the PostgreSQL database."
  type        = string
  default     = "db.t3.micro"

  # A dev-scale default. The API in this milestone does not yet query the
  # database (see database.tf), so this is sized for "the acceptance criterion
  # is that a managed PostgreSQL instance exists, is private, and holds the
  # master password in Secrets Manager" — not for throughput.
  #
  # db.t3.micro is burstable: its CPU credit behaviour makes sustained load a
  # bad fit, exactly like t3 on the compute side. Raise this the moment the
  # database does real work.

  validation {
    condition     = length(var.db_instance_class) > 0
    error_message = "db_instance_class must not be empty."
  }
}

variable "db_engine_version" {
  description = "PostgreSQL engine major version for the RDS instance. Pinned so that a future apply cannot silently change the database major version."
  type        = string
  default     = "16"

  # PINNED, AND NOT "latest". Leaving engine_version unset lets AWS resolve the
  # engine at CREATE time and, in some provider paths, at a later apply — which
  # means the database can change engine version underneath you as a side
  # effect of an unrelated edit. A major version is the right granularity to
  # pin at:
  #
  #   * Pinning the MAJOR ("16") blocks any major upgrade. A major upgrade
  #     cannot happen as a side effect of `terraform apply`; it requires
  #     changing this variable deliberately, and the plan shows it.
  #   * It deliberately does NOT block MINOR upgrades, which is what you want:
  #     PostgreSQL minor releases are security and bug fixes, AWS applies them
  #     in the maintenance window, and pinning "16.3" to prevent them would be
  #     choosing to run an unpatched database.
  #
  # Why a major pin and not an exact minor like "16.3": availability of a given
  # minor version varies by region and changes as AWS retires them, so an exact
  # pin fails `terraform plan` with a provider error in a region that does not
  # offer that build. The cost of that failure is high and the benefit is low.
  #
  # If you need an exact minor, pass -var db_engine_version=16.x and pin to one
  # your region actually offers.
}

variable "db_name" {
  description = "Name of the initial database created on the RDS instance."
  type        = string
  default     = "lemondrop"
}

variable "db_master_username" {
  description = "Master username for the RDS instance. NOT a password — see database.tf on manage_master_user_password."
  type        = string
  default     = "lemondrop_admin"

  # The USERNAME is not a secret in the way the password is — it is part of the
  # connection string and appears in the SSM parameters the application reads.
  # There is a real AWS hard limit on its length and no benefit to making it
  # obscure, which is why `password` variables are treated differently from
  # this one throughout this config.
  #
  # The password is NOT declared anywhere in this config. That is the whole
  # point of `manage_master_user_password`; see database.tf.
}

variable "db_allocated_storage" {
  description = "Initial allocated storage in GiB for the RDS instance."
  type        = number
  default     = 20

  validation {
    condition     = var.db_allocated_storage >= 20
    error_message = "db_allocated_storage must be at least 20 GiB; the RDS PostgreSQL engine's minimum is 20."
  }
}

variable "db_deletion_protection" {
  description = "RDS deletion protection. Default TRUE — this means `terraform destroy` WILL FAIL on the database until you explicitly disable it."
  type        = bool
  default     = true

  # ⚠️  READ THIS BEFORE YOU EVER NEED TO DESTROY THE DATABASE  ⚠️
  #
  # TRUE (the default) means:
  #
  #   terraform destroy
  #     → aws_db_instance.db: deletion_protection must be set to false first
  #     → Error: DBInstanceCannotBeDeleted
  #     → destroy STOPS.
  #
  # This is not a bug and not a Terraform quirk — it is AWS refusing to delete
  # a database that was not marked disposable. It is a guard against exactly
  # the worst thing that can happen to a stack: `terraform destroy` pointed at
  # the wrong workspace, or run by someone who did not realise what the stack
  # contained.
  #
  # To destroy, you must SAY OUT LOUD that this database is disposable:
  #
  #   terraform destroy -var db_deletion_protection=false \
  #                      -var db_skip_final_snapshot=true
  #
  # (the second flag is only needed if you do not want to pay for the final
  # snapshot). Deletion protection has no default that is "convenient",
  # because the default is the one that is safe.
}

variable "db_skip_final_snapshot" {
  description = "Skip the final snapshot on destroy. Default FALSE — take the snapshot, pay for the storage."
  type        = bool
  default     = false

  # FALSE (the default) means destroy leaves a snapshot behind, recoverable:
  #
  #   terraform destroy -var db_deletion_protection=false
  #     → snapshot <identifier>-final is created
  #     → the database is gone; the DATA is not
  #
  # TRUE skips it and discards the data. That is a deliberate act and it is
  # free, which is exactly why it is not the default.
  #
  # THE COST, stated plainly: snapshots are stored and BILLED forever. A 20 GiB
  # gp3 PostgreSQL snapshot runs roughly $2.30/month at $0.115/GB-month, and it
  # keeps billing until someone deletes it by hand in the console — Terraform
  # will not clean it up, because it is not a resource in this config. That is
  # the same meter-running-after-destroy problem as the NAT gateway, at a much
  # smaller scale. If you want the snapshot gone, delete it manually.
  #
  # Note the interaction: with skip_final_snapshot = false, a
  # db_final_snapshot_identifier MUST be supplied (see database.tf).
}

variable "db_final_snapshot_identifier" {
  description = "Identifier for the final snapshot taken on destroy. Defaults to a deterministic name derived from the stack name."
  type        = string
  default     = null

  # RDS rejects a destroy with SkipFinalSnapshot=false unless a final snapshot
  # identifier is provided, so this cannot simply be null in the common case.
  #
  # It is derived deterministically rather than from timestamp() on purpose. A
  # timestamp() value changes on EVERY plan, which produces a permanent
  # no-op-looking diff on every run and is the kind of noise that teaches
  # operators to ignore diffs. The cost of the deterministic name is that
  # destroying twice on the same day collides — RDS reports that a snapshot of
  # that name already exists. Pass -var db_final_snapshot_identifier=<other>
  # in that case; that is a rarer event and deserves a deliberate flag.
}

variable "db_backup_retention_period" {
  description = "Days of automated backups to retain. Set to 0 to DISABLE automated backups entirely."
  type        = number
  default     = 7

  # Small but NON-ZERO. Seven days of automated backups on a development
  # database costs a few dollars a month and is the only thing standing between
  # a bad migration and an afternoon retyping fixture data.
  #
  # ⚠️  0 IS NOT "KEEP NONE", IT IS "KEEP NONE, AUTOMATICALLY" ⚠️
  # Setting this to 0 disables automated backups completely. It does not keep
  # zero backups and delete them; it stops taking them. On a db.t3.micro that
  # is a few dollars a month saved and an entire recovery story removed, which
  # is almost never the ratio anyone intended when they typed `0`.

  validation {
    condition     = var.db_backup_retention_period >= 0 && var.db_backup_retention_period <= 35
    error_message = "db_backup_retention_period must be between 0 and 35 days. RDS maximum retention is 35 days."
  }
}

# ── Load balancer ──────────────────────────────────────────────────────────

variable "lb_enable_deletion_protection" {
  description = "ALB deletion protection. Default TRUE — `terraform destroy` will FAIL on the load balancer until this is false."
  type        = bool
  default     = true

  # The SAME operational gotcha as db_deletion_protection, on a cheaper
  # resource, and for the same reason: an accidental destroy pointed at the
  # wrong workspace should not silently remove the entry point to the
  # application. To destroy: -var lb_enable_deletion_protection=false
  #
  # The asymmetry that matters: the ALB holds NO DATA. Unlike the database,
  # nothing irreplaceable is lost by removing it, and re-applying recreates it
  # in a few minutes. So this is a lower-stakes guard than the database's, and
  # it is reasonable to turn it off here if destroy convenience matters more
  # than the guard. Turning it on is still the default.
}

variable "lb_idle_timeout" {
  description = "ALB idle timeout in seconds for connections between the load balancer and the target."
  type        = number
  default     = 60

  # The ALB default is 60s and it is kept deliberately rather than raised to
  # something accommodating. Nothing in this milestone opens a long-lived
  # connection: /embed and /rerank are request/response HTTP calls, and the
  # api is the only target. A long idle timeout here would only widen the
  # window in which a half-dead connection occupies a target slot.
  #
  # If a future feature needs streaming or SSE, THIS is the number to raise —
  # and it is the number people forget to raise, which is the usual reason a
  # streaming endpoint "works locally and silently truncates behind a load
  # balancer".

  validation {
    condition     = var.lb_idle_timeout >= 1 && var.lb_idle_timeout <= 4000
    error_message = "lb_idle_timeout must be between 1 and 4000 seconds (the ALB's valid range)."
  }
}

variable "lb_access_logs_enabled" {
  description = "Enable ALB access logging to S3. Default FALSE — logging needs a bucket this config does not create."
  type        = bool
  default     = false

  # ⚠️  DISABLED BY DEFAULT, AND THE REASON IS NOT COST — IT IS ABSENCE ⚠️
  #
  # ALB access logs are written to an S3 bucket. This stack does not create
  # one, and inventing one here would mean: a bucket, a bucket policy, an
  # ownership-controls resource to work around S3's ACL model, a lifecycle rule
  # so the logs do not bill forever, and a set of IAM permissions to write to
  # it. That is a log-archive subsystem, it is worth having, and it is not part
  # of this milestone.
  #
  # So the honest default is OFF with the requirement documented, rather than a
  # bucket created as a surprise. To turn it on you supply your own bucket:
  #
  #   terraform apply -var lb_access_logs_enabled=true \
  #                    -var lb_access_logs_bucket=my-existing-logs-bucket
  #
  # The bucket must already exist and must be in the SAME REGION as the load
  # balancer. Note the access log bucket is a place where request URLs — and
  # therefore the TEXT of what a user sent to /embed — would be persisted, so
  # it needs its own access story, not an anonymous one.
}

variable "lb_access_logs_bucket" {
  description = "Name of an EXISTING S3 bucket for ALB access logs. Required only when lb_access_logs_enabled is true."
  type        = string
  default     = ""

  # Never created by this config. See lb_access_logs_enabled for why.
}
