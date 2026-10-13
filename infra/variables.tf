# ═══════════════════════════════════════════════════════════════════════════
# Variables
# ═══════════════════════════════════════════════════════════════════════════

variable "aws_region" {
  description = "DOCUMENTATION ONLY — this variable does not configure the AWS provider. The region that resources are actually created in comes from the AWS_REGION environment variable or the operator's AWS CLI/config profile. See the comment below."
  type        = string
  default     = "eu-west-1"

  # ⚠️  THIS VARIABLE DOES NOT CONTROL WHERE ANY RESOURCE IS CREATED. ⚠️
  #
  # There is no `provider "aws" { region = ... }` block anywhere in infra/.
  # The provider therefore resolves its region from the environment
  # (AWS_REGION / AWS_DEFAULT_REGION) or from the operator's AWS CLI config
  # profile — never from this variable. This variable is referenced exactly once
  # in the whole stack: outputs.tf, where it is echoed as the `region` output.
  #
  # It is kept because it documents the intended region and because the output
  # echo is useful as a marker, but changing it alone will NOT move any resource.
  # A provider block was deliberately NOT added to wire it up: that would change
  # how region resolves for a stack that has already been deployed, which is an
  # infrastructure change nobody asked for at this stage.
  #
  # Ireland (eu-west-1) is the closest AWS region to Portugal, which minimises
  # latency for the operator and for the application's users. Per operator
  # report the deployed stack lives in eu-west-1 and AWS_REGION=eu-west-1 was
  # exported — so the environment and this variable currently agree. Nothing in
  # this config hardcodes an availability zone letter, so a genuine region
  # change does not break the subnet mapping. It does require updating the
  # backend block in versions.tf (backend blocks cannot use variables), since
  # state must live in the same region as the bucket.
  #
  # OPERATIONAL CONSEQUENCE: if the environment's region and this variable ever
  # disagree, the `region` output will report the variable's value while the
  # resources sit in the environment's region. The outputs would then disagree
  # with reality, and this variable WOULD NOT REVEAL IT — the disagreement is
  # invisible from inside this config. To check the real region, inspect the
  # provider's environment, not this variable.
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
    # This REQUIRES a single-host (/32) CIDR. An earlier revision compared
    # strings (`!= "0.0.0.0/0"`), which rejected exactly one value out of the
    # whole dangerous family: 0.0.0.0/1, 0.0.0.0/2, or any /16 sailed straight
    # through and would have landed on the internet-facing ALB ingress rule.
    # The comments above have always described a single host; this block is what
    # makes that description true.
    #
    # `cidrhost` proves the string is a well-formed CIDR. `try(...)` yields 0 for
    # anything it cannot read as a prefix length (missing "/", a non-numeric
    # suffix), so a malformed value is rejected with THIS error message rather
    # than crashing on an out-of-range list index. Note that `cidrhost` returns
    # a bare address with no prefix suffix — `cidrhost(x/32, 0)` is "1.2.3.4",
    # not "1.2.3.4/32" — so it cannot be compared for equality against the input
    # string; requiring a /32 is what actually distinguishes one host from a
    # range.
    condition = (
      can(cidrhost(var.allowed_api_cidr, 0)) &&
      try(tonumber(split("/", var.allowed_api_cidr)[1]), 0) == 32
    )
    error_message = "allowed_api_cidr must be a single host in CIDR notation, for example 203.0.113.10/32. A wider range such as 0.0.0.0/1 or a /16 would expose the load balancer far more broadly than intended, which is why this variable has no default."
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
#   │                         │ (most expensive   │ NOT blocked: subnets go   │
#   │                         │ line item)        │ straight to the IGW and   │
#   │                         │                   │ egress UNFILTERED         │
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
  #   * Image pulls, package installs, and model downloads STILL WORK — provided
  #     the instance has a public IP (`app_associate_public_ip = true`). Turning
  #     the NAT gateway off does not remove the private subnets' outbound path;
  #     it changes where that path leads. EC2 keeps booting, keeps pulling its
  #     base image, and keeps fetching weights without a NAT gateway in the way.
  #   * The "private" subnets are no longer egress-isolated. They route directly
  #     to the IGW and traffic leaves with the instance's own public address,
  #     unfiltered and unmetered-by-NAT. This is a deliberate cost trade, and
  #     main.tf carries a loud comment where it happens. It is not an oversight.
  #
  # WHAT YOU ACTUALLY SAVE: the ~$32/month gateway charge plus per-GB NAT data
  # processing. WHAT YOU ACTUALLY GIVE UP: the network layer that made these
  # subnets private in the first place. The two are not the same thing, and
  # conflating them is how a security control ends up documented backwards.
  #
  # EMPIRICAL EVIDENCE, NOT INFERENCE: this was observed on a DEPLOYED instance,
  # not deduced from the Terraform. With NAT disabled, an EC2 instance booted
  # successfully, pulled a 263MB container image, and downloaded 340MB of model
  # weights — all over the IGW route. An earlier revision of this comment
  # asserted the opposite, that private subnets lose internet access entirely;
  # the deployed stack disproved it, so the claim was removed rather than kept
  # as a warning.
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

  # ⚠️  READ THE REVIEWED-PLAN SECTION BELOW BEFORE RUNNING ANY terraform apply.  ⚠️
  #
  # ── WHAT IS PROVEN — TWO SEPARATE CLAIMS, AND THEY MUST NOT BE BLURRED ───
  #
  # PROVEN (M2) — t3.micro BOOTS THIS STACK. On t3.micro, with both models
  # resident and all three containers healthy: 913Mi total, roughly 280Mi
  # available, and the boot completed:
  #
  #   === lemondrop boot: SUCCESS — api healthy after 10s ===
  #
  # This remains true. It was measured, it was not guessed, and nothing in
  # M3 erases it. The earlier pessimism — that 1 GiB is "very unlikely to
  # fit" two models and would OOM on boot — was an UNMEASURED guess, and the
  # measurement contradicted it.
  #
  # PROVEN (M3) — t3.micro CANNOT SERVE RETRIEVAL. Three kernel OOM kills of
  # llama-server in the reranker's cgroup, AFTER the reranker had already
  # been reduced to a single inference slot:
  #
  #   18:18:16  killed llama-server  anon-rss 425504 kB
  #   18:20:21  killed llama-server  anon-rss 428608 kB
  #   18:40:13  killed llama-server  anon-rss 437408 kB   ← AFTER --parallel 1
  #
  # The host at the time: 913Mi total, ~194Mi available, zero swap. The
  # reranker weights ALONE are 289.8 MiB — larger than the entire available
  # memory before a single byte of KV cache. Whole-stack local RSS measured
  # at 832 MiB.
  #
  # The decisive detail is the LAST line of that table: peak RSS did not fall
  # with one slot, it rose slightly. That establishes the memory is dominated
  # by fixed model weights and llama.cpp runtime, NOT by KV cache — which is
  # why tuning concurrency could never have been the fix.
  #
  # THE DISTINCTION IS THE POINT. "It boots" and "it serves" are different
  # properties of an instance, and only the second one has now failed. A host
  # can pass a healthcheck, hold its models resident, and answer /healthz
  # perfectly while being killed by the kernel every time a real query is
  # scored. Recording both claims honestly is more useful than either claim
  # alone: the boot result is why the stack is trusted to deploy at all, and
  # the serve result is why the hardware underneath it has to change.
  #
  # ── WHY t3.small (2 GiB) ────────────────────────────────────────────────
  #
  # It roughly DOUBLES memory. That is what it buys, and it is the whole of
  # what it buys.
  #
  # Stated plainly so it cannot be over-read: THIS IS NOT A BENCHMARK OF
  # t3.small. The SIZING REASONING below was written BEFORE the resize and is
  # preserved as it was written, because the reasoning is what the choice
  # rested on: t3.small is the next step up from an instance with a
  # MEASURED, REPRODUCED failure, chosen because it is the SMALLEST instance
  # that plausibly clears a ~290MiB-weight-plus-runtime model on a host that
  # had ~194MiB to give. It was a hypothesis with a size attached, chosen
  # against a measured floor — not a verified sufficiency.
  #
  # THAT HYPOTHESIS HAS NOW BEEN EXERCISED. The instance was resized, and
  # retrieval ran on it and WORKED: 40 of 40 documents ingested, /search
  # returned 10 candidates and 5 results with the correct top documents,
  # collection isolation passed, the search survived an API container
  # restart, and no new kernel OOM occurred within the verified search
  # window. The public ALB returned HTTP 200 for /search in 15.55 seconds —
  # a SINGLE OBSERVATION, not a latency distribution, and nothing here may be
  # quoted as a latency figure. See `docs/verification-milestone-3.md` §12.1
  # for the row-by-row record, §12.3 for the failures that preceded it, and
  # §12.4 for what the green rows do NOT mean.
  #
  # So the sufficiency question this default was set up to answer has been
  # answered by measurement, as it said it would have to be. Read the next
  # section for what remains open — latency distribution, headroom, and
  # sustained load are not answered by a single successful search.
  #
  # ── WHY NOT BIGGER ──────────────────────────────────────────────────────
  #
  # t3.medium (4 GiB) is available, as is the m-family, and both are the right
  # answer for anything sustained. They are declined HERE, not on principle:
  # buying more than the minimum to fix a measured failure is a decision that
  # should be made ON evidence, and the evidence available says take the
  # smallest step that plausibly works, MEASURE, then decide. t3.medium would
  # have been chosen on the assumption that 2 GiB is not enough — an
  # assumption with nothing behind it, purchased in advance of a measurement
  # that has not happened.
  #
  # If t3.small proves insufficient, that is not a setback. That is NEW
  # EVIDENCE, and the next decision is informed by it instead of guessed.
  # (It has not proved insufficient: it has served retrieval successfully.
  # Whether 2 GiB is enough for a SUSTAINED workload is a different question
  # and is answered below, under the family limitation, not here.)
  #
  # ── ⚠️  THE KNOWN LIMITATION — t3 IS THE WRONG FAMILY, AT ANY SIZE  ⚠️ ───
  #
  # This is a real limitation and it is not fixed by this change. t3 is
  # BURSTABLE. Cross-encoder scoring is a SUSTAINED CPU load, not a burst:
  # every query runs the reranker over a candidate set for seconds at a time.
  # Sustained load spends CPU credits, credits deplete, and once depleted the
  # instance is THROTTLED — baseline CPU is held to a fraction of normal and
  # rerank latency degrades accordingly. A t3.small that survives the memory
  # gap can still spend its working life throttled, and the symptom then
  # looks like "search got slow" rather than "search is broken", which is a
  # harder failure to diagnose later.
  #
  # So: t3.small should make retrieval WORK. It does not make the ARCHITECTURE
  # RIGHT. m6i/m7i remains the correct family for sustained inference, and
  # this default is a capacity fix, not a family endorsement. See the family
  # note in compute.tf, which points here for the other half of that trade.
  #
  # ── WHY `--parallel 1` STAYS ────────────────────────────────────────────
  #
  # It did not, by itself, fix the OOM. It is being kept anyway, and the
  # reason it is NOT being reverted in the same breath as the resize is
  # deliberate:
  #
  #   * It removed a MEASURED 71.5 MiB of avoidable KV-cache overhead. That
  #     is real memory returned, and on a host that was 194Mi short, every
  #     MiB of avoidable overhead is a MiB that does not have to come out of
  #     headroom.
  #   * It costs ~13% median latency locally. On a 2 GiB host, trading 13%
  #     latency for 71.5 MiB of headroom is a trade worth making; the memory
  #     is the scarcer resource.
  #   * Reverting it now would buy NOTHING. The OOM was caused by weights and
  #     runtime, which --parallel never controlled — that is precisely what
  #     the rising RSS under one slot demonstrated. Removing the flag would
  #     put 71.5 MiB back and fix none of the 437 MiB that actually died.
  #
  # Keep the flag. Change the hardware. Those are independent decisions and
  # they resolve in opposite directions from the previous milestone, which is
  # exactly why the previous note ("if it breaks, raise the instance") and
  # this one must both be read together.
  #
  # ── WHAT WAS CONSIDERED AND REJECTED — DO NOT RE-LITIGATE ───────────────
  #
  #   * TIGHTENING `--ctx-size`. REJECTED. llama.cpp TRUNCATES over-long input
  #     rather than raising an error. An undersized context therefore
  #     silently degrades relevance scores, with no failure surfacing ANYWHERE
  #     — no crash, no log line, no non-200, just quietly worse search results
  #     that look like a model problem. That is strictly WORSE than the loud
  #     kernel OOM this configuration is now fixing, and it was rejected on
  #     those grounds BEFORE the instance size was touched. It is recorded
  #     here because it is the change most likely to be proposed again by
  #     someone who has only seen the memory number.
  #   * A SMALLER QUANTIZED RERANKER. REJECTED. A model change means a
  #     re-download, a re-measurement of rerank quality and latency, and a
  #     new relevance baseline — a substantially larger intervention than the
  #     failure warrants, and one that changes what the system ANSWERS rather
  #     than what it costs to answer.
  #   * A BLIND `terraform apply` THAT CHANGES `instance_type`. EXPLICITLY
  #     REJECTED BY THE OPERATOR, and it is not a close call — see below. The
  #     resize was NOT run that way: a Terraform plan was REVIEWED first, and
  #     the apply was executed against that reviewed plan.
  #
  # ── ⚠️  HOW THE RESIZE WAS ACTUALLY CARRIED OUT  ⚠️ ──────────────────────
  #
  # THIS IS THE MOST IMPORTANT THING IN THIS COMMENT.
  #
  # An EARLIER VERSION OF THIS COMMENT said something different, and it was
  # WRONG. It claimed that `instance_type` on `aws_instance` is ForceNew in
  # the AWS provider, that a plan carrying the change would therefore propose
  # DESTROY + CREATE rather than an in-place resize, and that the only path
  # preserving the instance was a MANUAL stop → modify → start on the AWS
  # side with `terraform apply` forbidden.
  #
  # THE OPERATOR'S ACCOUNT OF WHAT WAS EXECUTED GOVERNS, and it is this:
  #
  #   THE RESIZE WAS CARRIED OUT THROUGH A REVIEWED TERRAFORM PLAN AND A
  #   TERRAFORM APPLY. The plan was READ before it was applied, and the apply
  #   PRESERVED THE EC2 INSTANCE ID — which the operator has INDEPENDENTLY
  #   CONFIRMED. See `docs/verification-milestone-3.md` §12.1 row 1 and §12.2.
  #
  # THE OBSERVED OUTCOME IS THE EVIDENCE. An instance ID that survived the
  # apply is not consistent with a destroy-and-recreate having been executed.
  # This comment therefore does NOT re-assert ForceNew, and the ForceNew
  # inference that motivated the manual-resize story is withdrawn. The risk
  # that motivated it — a replacement losing the instance ID, the root volume,
  # the models, the checkout and the images — is REAL and is still worth
  # respecting; what is withdrawn is the claim about how Terraform behaves and
  # the claim that apply could not be used.
  #
  # THE LESSON IS UNCHANGED AND IS THE REASON TO KEEP THIS BLOCK. The action
  # that loses the instance ID, the volume, the models, the checkout and the
  # images is an UNREVIEWED apply of a plan that proposes replacement. The
  # thing that prevents it is READING THE PLAN FIRST — which is exactly what
  # was done. If you remember one thing from this block, remember that the
  # plan is read before it is applied, not after.
  #
  # ── THE RECONCILING CHANGE ───────────────────────────────────────────────
  #
  # The default in THIS file declares the same steady state the instance now
  # runs. That is a RECONCILING change: it exists so that every subsequent
  # plan proposes reverting the capacity upgrade. Without it, a later plan
  # would propose shrinking a box that was just enlarged — produced by nothing
  # more than forgetting a flag, which is the same hazard class this milestone
  # has been removing since M2.
  #
  # ── WHAT THIS CHANGE IS NOT ─────────────────────────────────────────────
  #
  # THE CHANGE IN THIS FILE ALONE DOES NOT RESIZE ANYTHING. Nothing here
  # touches a live AWS resource, and nothing here will. It reconciles the
  # DECLARED DEFAULT with the STEADY STATE THE INSTANCE NOW RUNS. The capacity
  # change itself was already carried out, through a reviewed Terraform plan
  # and a Terraform apply — see the section above.
  #
  # Do not describe this change as an upgrade, and do not let a plan run
  # from it be treated as approval to apply. It is documentation and drift
  # correction, exactly as the previous change at this variable was.
  #
  # ── IF t3.small BREAKS ──────────────────────────────────────────────────
  #
  # If the boot log shows an OOM kill, or the api never becomes healthy,
  # raise this before investigating anything else. t3.medium (4 GiB) is the
  # next step up; the correct answer is the FAMILY below. Measure it rather
  # than guessing:
  #   ssh/ssm →  docker stats --no-stream
  #             docker compose logs embedder reranker | grep -i 'memory\|error'
  #
  # ── WHAT IS STILL UNVERIFIED ON t3.small ─────────────────────────────────
  #
  #   * NOTHING about whether retrieval works. That WAS unproven when this
  #     default was written, and it has since been exercised: ingestion,
  #     search, ranking, isolation and survival across an API container
  #     restart all passed on this instance. `docs/verification-milestone-3.md`
  #     §12.1 is the row-by-row record. Do not re-open it.
  #   * M3 rerank latency ON EC2 remains untaken as a DISTRIBUTION. The rerank
  #     latency that motivates the 10-candidate funnel — ~11-12.5s median
  #     over ten documents, i.e. ~1.1-1.25s per candidate — was measured on
  #     the developer's workstation, NOT on any EC2 instance. The cloud run
  #     produced ONE /search observation of 15.55s, which is not a latency
  #     distribution and does not answer this. It is the number that decides
  #     whether the ALB lb_idle_timeout needs raising.
  #   * Sustained-load behaviour, and therefore the CPU-credit throttling
  #     described above, is unmeasured at every size. A working single search
  #     says nothing about how t3.small behaves over hours.
  #   * Terraform state HAS NOW been confirmed to agree with reality. A
  #     read-only `terraform plan -detailed-exitcode` reported NO CHANGES and
  #     exit 0, independently verified by the operator. This is an
  #     OBSERVATION, not the argument the block below used to make.
  #     See §12.1 row 20 and §12.4 item 1 — RESOLVED.
  #
  # ── WHY THIS CHANGE SHOULD PRODUCE NO RESOURCE DIFF ──────────────────────
  #
  # The resize has been carried out and this file now declares the instance
  # type the instance runs, so the reasoning for an empty plan is that state
  # records t3.small, this file declares t3.small, and there is nothing left
  # to plan.
  #
  # THAT REASONING HAS NOW BEEN CONFIRMED BY OBSERVATION. This comment block
  # itself still runs NO terraform — no plan, no init, no validate was ever
  # executed to write it, and none was executed to correct it. The correction
  # is to the PROSE, not to the reasoning it criticized: the check that was
  # missing has been run by the operator, independently, and reported as
  # NO CHANGES with exit 0.
  #
  # The distinction is kept deliberately. `terraform plan -detailed-exitcode`
  # returns 0 for no changes and 2 for changes present, so the EXIT STATUS is
  # the result and must be quoted, not eyeballed. What is now quoted is 0.
  # NO APPLY WAS RUN to produce it, and none should be — this is a read-only
  # reconciliation, and running an apply to make a verification row look
  # complete would invalidate the very row it was meant to support.
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

variable "app_health_check_unhealthy_threshold" {
  description = "Consecutive failed ALB health checks before the target is marked unhealthy. With the interval configured in load_balancer.tf this sets how long boot has to produce a healthy /health."
  type        = number
  default     = 10

  # RENAMED from app_health_check_grace_period_seconds. That name described an
  # attribute that does not exist on aws_lb_target_group — grace periods belong
  # to aws_ecs_service. This variable was kept and repointed at the knob that
  # genuinely governs the same problem, rather than deleted, because the
  # operator still needs one documented place to tune boot tolerance.
  #
  # It exists because of the ~340MB of GGUF that scripts/fetch-models.sh
  # downloads AT BOOT, before the api can answer a single request. During that
  # window every ALB health check on /health fails, because there is no listener
  # yet.
  #
  # TOLERANCE IS THIS NUMBER × interval, NOT THIS NUMBER ALONE. The ALB waits
  # `interval` seconds between probes and marks the target unhealthy after this
  # many CONSECUTIVE failures, so at interval = 30 the window is:
  #
  #     10 × 30s = 5 MINUTES
  #
  # 10 is the maximum AWS permits for an ALB target group, so this is the
  # ceiling, not a preference. The boot timeline in compute.tf reaches /health
  # at roughly 7 minutes, which is BEYOND that ceiling: on a slow cold start
  # the target WILL go unhealthy and the ALB WILL return 503s until boot
  # finishes. That is expected for this architecture. The durable fix is to
  # bake the models into the AMI so boot does not download them — out of scope
  # for this milestone.
  #
  # Raising this is not possible; it is already at the cap. Lowering it buys
  # nothing and costs a real failure mode, so raise the AMI instead.

  validation {
    condition     = var.app_health_check_unhealthy_threshold >= 2 && var.app_health_check_unhealthy_threshold <= 10
    error_message = "app_health_check_unhealthy_threshold must be between 2 and 10. AWS caps an ALB target group's unhealthy_threshold at 10."
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
  description = "Days of automated backups to retain. Defaults to 0 because this account is on the AWS Free Plan, which permits no automated backups at all. 1-35 requires a Paid plan."
  type        = number
  default     = 0

  # ZERO, AND NOT BY ACCIDENT — BECAUSE OF THE ACCOUNT'S PLAN, NOT BECAUSE
  # ZERO IS A GOOD DEFAULT.
  #
  # ⚠️  THE FREE PLAN PERMITS 0 AND NOTHING ELSE. ⚠️
  # This account is on the AWS Free Plan, whose maximum backup retention period
  # is 0. Applying with any value above that fails with:
  #     FreeTierRestrictionError: The specified backup retention period exceeds
  #     the maximum available to free tier customers.
  # That is exactly how the first apply of this stack failed. The account plan
  # is a property of the ACCOUNT, not of this config, so it cannot be worked
  # around in Terraform — the only way to raise this number is to upgrade the
  # account, at which point 1-35 become legal.
  #
  # WHAT A NON-ZERO VALUE WOULD BUY, and why that argument is correct in
  # general and wrong here. Seven days of automated backups on a development
  # database is a few dollars a month, and it is genuinely the only thing
  # standing between a bad migration and an afternoon retyping fixture data.
  # On a Paid plan, 7 would be a defensible default and this comment would be
  # arguing for it. It is not one here: on the Free Plan the choice is not
  # "retention or no retention", it is "apply or no apply".
  #
  # ⚠️  0 IS NOT "KEEP NONE", IT IS "KEEP NONE, AUTOMATICALLY" ⚠️
  # Setting this to 0 disables automated backups completely. It does not keep
  # zero backups and delete them; it stops taking them. On this stack that is
  # currently defensible, because nothing queries the database yet (see
  # database.tf) and there is no data to lose — the database is provisioned to
  # satisfy an acceptance criterion, and its contents are re-creatable from a
  # migration. THE MOMENT THE API HOLDS SOMETHING THAT CANNOT BE RE-CREATED,
  # upgrade the account plan and raise this, and treat the upgrade as the
  # prerequisite rather than as an optional improvement.

  # 0-35 is the RDS-wide legal range. Note this validation CANNOT enforce the
  # Free Plan's stricter maximum of 0, because that limit is not knowable from
  # inside the config — a value of 7 passes this check and still fails at apply
  # on a Free plan. The range check catches typos and out-of-range values at
  # plan time; the account-plan check can only fail at apply, which is why the
  # default is 0 and the reason is documented above.
  validation {
    condition     = var.db_backup_retention_period >= 0 && var.db_backup_retention_period <= 35
    error_message = "db_backup_retention_period must be between 0 and 35 days. RDS maximum retention is 35 days. Note that on the AWS Free Plan the maximum is 0 — a value above 0 will pass this check and then fail at apply with FreeTierRestrictionError."
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
