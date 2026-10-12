# ═══════════════════════════════════════════════════════════════════════════
# COMPUTE — the EC2 host that runs all three Compose services
# ═══════════════════════════════════════════════════════════════════════════
#
# One instance, one role: `api` (FastAPI, publishes host port 8000), `embedder`
# (llama.cpp, container port 8080, NO published port), `reranker` (llama.cpp,
# container port 8080, NO published port).
#
# The instance has exactly ONE published port, and it is the api's. That is not
# an accident of the compose file — it is the mechanism by which the inference
# services are unreachable from the internet. See the long note at the top of
# security_groups.tf: the workers are beside the api on a Docker bridge
# network, not behind its door, and nothing in this stack builds a path to
# them.
#
# THIS RESOURCE IS NOT GATED BY ANY TOGGLE.
# There is no `enable_compute`. EC2 is always created, for the same reason
# `sg_app_ec2` is always created in security_groups.tf: it is the thing the
# milestone is for, and a stack with no compute does not boot the application
# at all. The consequence is load-bearing for the whole directory — because
# aws_instance.app always has count = 1, `aws_instance.app[0]` is safe to
# reference from ANYWHERE without a guard, including from the count-gated
# load_balancer.tf. That single fact is what keeps the conditional-reference
# surface in this stack small. Do not add a toggle to this resource without
# auditing every reference to it, because removing this guarantee is what
# turns a safe reference into a plan-time "Invalid index" failure.

# ═══════════════════════════════════════════════════════════════════════════
# AMI — resolved from SSM Parameter Store, never hardcoded
# ═══════════════════════════════════════════════════════════════════════════
#
# ⚠️  A HARDCODED AMI ID IS A FUTURE INCIDENT, AND PROBABLY A QUIET ONE ⚠️
#
# "ami-0c55b159cbfafe1f0" is not a durable fact. It is a pointer into a
# regional catalogue that AWS edits continuously: instances are deprecated and
# retired on a schedule, and a retired ID returns an error at launch. The
# failure has three shapes, and the worst one is the common one:
#
#   * LAUNCH FAILS, LOUDLY. `terraform apply` errors with InvalidAMIID.NotFound.
#     You find out immediately. Annoying, not dangerous.
#   * LAUNCH SILENTLY SUCCEEDS ON SOMETHING ELSE. A regional catalogue lookup
#     can resolve an ID you did not intend — a different generation, a
#     different architecture, a different kernel with a different driver
#     stack. Nothing in the apply looks wrong. The instance boots and the
#     problem surfaces later as a driver error or a kernel panic, hours away
#     from the edit that caused it.
#   * THE AMI IS FINE AND SOMETHING ELSE IS NOT. The most expensive version:
#     an image pinned a year ago for a driver fix, quietly missing a CVE patch
#     that shipped since. "Pinned" does not mean "safe", and this failure
#     never shows up anywhere you would think to look.
#
# The SSM public parameter resolves to the CURRENT AMI in the CURRENT region at
# plan time. It follows AWS's security updates, it is regional (so changing
# aws_region cannot produce an AMI that does not exist there), and it costs
# nothing. The trade is stated honestly: you give up byte-for-byte
# reproducibility of the host, because "today's latest AL2023" is a moving
# target.
#
# For a development host that boots its own container images and downloads its
# own models, "current and patched" beats "identical to March". A production
# host that must be reproducible should pin by NAME — bake an AMI and reference
# its ID deliberately, with the update as a reviewed change. That is the same
# argument as pinning db_engine_version to a major version rather than
# leaving it to AWS, and the same reason.
#
# This parameter lives in AWS's PUBLIC parameter namespace and is readable
# without credentials, so it resolves on a fresh account before anything else
# exists.
#
# ── The x86_64 SUFFIX IS NOT COSMETIC. IT IS LOAD-BEARING. ─────────────────
#
# The path ends in `x86_64`. The ARM equivalent of this parameter exists and is
# one string edit away — and that edit BOOT-BREAKS THE APPLICATION, at a point
# where the error is maximally confusing.
#
# The application's two inference services run on
# `ghcr.io/ggml-org/llama.cpp:server`, an amd64 image. The api's Dockerfile
# builds FROM `python:3.12-slim` and installs prebuilt amd64 wheels. If this
# instance were Graviton (c7g, t4g, m7g — the ARM family), the boot would
# proceed, Docker would resolve whatever manifest arm64 produced, and the
# application would then fail INSIDE a container minutes after a boot that
# appeared to succeed — with an architecture or missing-library error that
# points at the image, not at the parameter.
#
# That is a real trade-off, not a free choice. Graviton is materially cheaper
# per hour and usually better performance-per-watt. The reason to decline it
# HERE is that the upstream llama.cpp image is the load-bearing dependency of
# both /embed and /rerank, and its CPU behaviour on ARM has not been benchmarked
# for this application. Optimising the instance before the model path is proven
# would be optimising the wrong thing.
#
# If this ever moves to ARM, the prerequisite is verified ARM images for both
# llama.cpp and the api — not a parameter change. See var.app_instance_type for
# the other half of this trade: the instance FAMILY is unsettled, and that is
# deliberate.
data "aws_ssm_parameter" "app_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# ═══════════════════════════════════════════════════════════════════════════
# SSH KEY — OFF BY DEFAULT, A FALLBACK, NOT AN ACCESS PATH
# ═══════════════════════════════════════════════════════════════════════════
#
# The RECOMMENDED way to reach this host is Session Manager:
#
#     aws ssm start-session --target <instance-id>
#
# No key pair, no port 22, no bastion, no inbound rule on sg_app_ec2. Access
# is authenticated by the operator's IAM identity and recorded in CloudTrail as
# an IAM-authorised API call rather than as an SSH connection to a port that
# happens to be open.
#
# This resource exists for the case where Session Manager is unavailable — the
# agent failed to register, or the operator is debugging the very thing that
# makes Session Manager work. That case is real, which is why this is a
# variable rather than deleted.
#
# BUT CREATING THE KEY DOES NOT MAKE YOU ABLE TO LOG IN. Port 22 is not open in
# any security group in security_groups.tf, and nothing here opens it. This
# creates a key; it opens nothing. Using it is a separate, deliberate change to
# a security group — which is the correct shape for a fallback: the capability
# exists, and arming it shows up in a diff.
#
# No private key is generated, stored, or handled here. `aws_key_pair` takes a
# PUBLIC key and AWS never sees the private half, so this resource creates no
# secret. A generated key (`tls_private_key`) was rejected precisely because
# THAT would put a private key in Terraform state.
resource "aws_key_pair" "app" {
  count = var.create_ssh_key ? 1 : 0

  key_name = "${local.name_prefix}-app"

  # Read from the operator's filesystem at plan time. This is safe precisely
  # because the value is a public key — and it is why there is no
  # ssh_public_key VARIABLE holding key material: a variable would invite
  # someone to put the private key in a .tfvars, where it would sit in state
  # and on disk. Public keys are public; private keys never enter this config.
  public_key = file(var.ssh_public_key_path)

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-app"
  })
}

# ── The instance ───────────────────────────────────────────────────────────
resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.app_ami.value
  instance_type               = var.app_instance_type
  subnet_id                   = aws_subnet.private[0].id
  vpc_security_group_ids      = [aws_security_group.app_ec2.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  associate_public_ip_address = var.app_associate_public_ip

  # key_name uses `one(splat)` and NOT the obvious
  # `var.create_ssh_key ? aws_key_pair.app[0].key_name : null`.
  #
  # That ternary looks equivalent and is the single most reliable way to
  # produce an "Invalid index" failure at plan time: Terraform evaluates the
  # resource reference even in the branch it does not take, so with
  # create_ssh_key = false the plan dies on index [0] of an empty list.
  # The splat `aws_key_pair.app[*]` produces an empty LIST rather than an error
  # when count is 0, and `one()` turns that empty list into `null`. No branch,
  # no evaluation-order subtlety, no way to get it wrong.
  #
  # THE RULE FOR THIS WHOLE DIRECTORY: any reference that CAN be empty uses
  # one(splat) or lives inside a matching count guard. See load_balancer.tf
  # for the two other shapes this stack uses.
  key_name = one(aws_key_pair.app[*].key_name)

  # ── user_data is only read at LAUNCH ───────────────────────────────────────
  # Changing this attribute does nothing to a running instance; without this
  # flag Terraform would report "updated in place" and leave the host running
  # the OLD boot script forever, which is a class of bug that produces a
  # confidently-wrong deployment. Forcing replacement makes the plan say what is
  # actually true: the script is part of the host's identity.
  user_data_replace_on_change = true

  # ── Root volume ───────────────────────────────────────────────────────────
  root_block_device {
    # Encrypted at rest. AL2023 AMIs already default to encrypted root volumes,
    # but stating it makes this a decision rather than an inherited default —
    # the same reasoning as `map_public_ip_on_launch = false` in main.tf.
    encrypted = true

    # gp3, modest. Must hold the OS, both container images, the build layers,
    # and the ~340MB of models. See var.app_root_volume_size.
    volume_type = "gp3"
    volume_size = var.app_root_volume_size

    # delete_on_termination is the default and is stated anyway: on a dev host
    # the disk should die with the instance, and a stopped instance holding an
    # 8 GiB orphan volume is a bill that continues for no benefit.
    delete_on_termination = true
  }

  # ── IMDSv2 only ───────────────────────────────────────────────────────────
  # http_tokens = "required" means the metadata service refuses to serve
  # instance profile credentials to any caller that cannot present a session
  # token, which closes the SSRF-to-credential-theft path behind a long series
  # of real compromises.
  #
  # This is the same subject as the rest of iam.tf from a different angle: the
  # credentials the host uses should be hard to STEAL, not merely absent by
  # policy. Note that the hop limit of 1 is what makes this control effective —
  # it stops a proxy or a container reaching IMDS from a hop further away.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # ── ⚠️  NO SECRETS IN THIS SCRIPT.  ⚠️
  #
  # Everything below is the application boot. There is no database password in
  # it, no token, no key, and nothing of that shape. That is not a style
  # preference; user_data is the wrong place for a credential for three
  # separate reasons:
  #
  #   1. IT IS READABLE BY ANYONE WHO CAN CALL DescribeInstanceAttribute.
  #      user_data is returned in full by ec2:DescribeInstanceAttribute — a
  #      much broader permission than ec2:StartInstances or
  #      ec2:TerminateInstances. A read-only operational role with those two
  #      is a completely normal setup, and it would hand over the database
  #      password to it.
  #
  #   2. IT IS WRITTEN TO DISK, IN PLAIN TEXT, FOREVER.
  #      /var/lib/cloud/instances/<instance-id>/user-data.txt. Anyone with
  #      SSM shell access, any read-only file role, any volume backup, any
  #      forensic image of the instance. It survives reboots. Nothing in this
  #      stack encrypts it at rest.
  #
  #   3. IT IS ECHOED TO A LAUNCH-TIME LOG.
  #      cloud-init writes user_data and its stdout to
  #      /var/log/cloud-init-output.log. Anything printed there gets captured
  #      by whatever reads that log — a log shipper, an S3 export, a support
  #      bundle — and that is the path credentials actually leak through in
  #      practice, more often than the exploit paths people worry about.
  #
  # The database password is fetched AT RUNTIME by the application, through the
  # instance role, from Secrets Manager, using the single-ARN policy in iam.tf.
  # See the bottom of iam.tf for the exact call. Nothing about that flow needs
  # a launch-time secret, so putting the value here would have been strictly
  # worse than not having it at all.
  user_data = <<-EOF
    #!/usr/bin/env bash
    #
    # lemondrop application host — boot script (cloud-init user_data).
    #
    # IDEMPOTENT BY DESIGN — with a stated boundary on what that means.
    # Every step below either checks before it acts or is natively idempotent
    # (dnf, git pull, the model fetcher's skip-if-present, compose up), so a
    # re-run over a HEALTHY prior run converges on the same state rather than
    # duplicating work or failing on things that already exist. That matters
    # for two reasons: user_data_replace_on_change re-runs this on every script
    # change, and an operator debugging a boot will re-run it by hand.
    #
    # The boundary, stated so this claim is not read as stronger than it is:
    # idempotent means "safe to repeat", NOT "repairs whatever it finds". A
    # prior boot that failed part-way leaves partial state behind, and this
    # script does not clean that up for you. Step 3 is the clearest case —
    # an $APP_DIR that exists but is not a git checkout halts the boot with a
    # named error rather than deleting the directory or cloning over it,
    # because deciding that a half-built directory is disposable is the
    # operator's call, not this script's. Other steps may have similar
    # boundaries. Read a failure, resolve it, re-run.
    #
    # LOGGED THROUGHOUT. Every step announces itself to
    # /var/log/lemondrop-boot.log AND to /var/log/cloud-init-output.log. A
    # failed boot on a host with no SSH key and no public IP is otherwise a
    # mystery, and "mystery" is the most expensive kind of infrastructure bug:
    # the only handle you have is the log written to tell you where it stopped.
    # Read it with:
    #
    #     sudo tail -n 100 /var/log/lemondrop-boot.log
    #     sudo cat  /var/log/cloud-init-output.log
    #
    # NO SECRETS IN THIS FILE. See the comment on user_data above.

    set -euo pipefail

    LOG_FILE="/var/log/lemondrop-boot.log"
    APP_DIR="/opt/lemondrop"
    APP_URL="${var.app_source_url}"
    APP_PORT="${local.app_port}"
    COMPOSE_PLUGIN_RELEASE="v2.29.1"

    log() { printf '%s [%s]\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG_FILE"; }

    log "=== lemondrop boot: START ==="
    log "app dir      : $APP_DIR"
    log "app url      : $APP_URL"
    log "app host port: $APP_PORT"

    # ── 1. Packages ──────────────────────────────────────────────────────────
    # docker: the runtime for all three services.
    # git   : the application source is cloned, not baked into the AMI.
    # curl  : scripts/fetch-models.sh downloads the GGUF weights with it.
    # None of these are present on a stock AL2023 AMI.
    log "step 1/6: installing packages (docker, git, curl)"
    dnf install -y docker git curl

    systemctl enable --now docker
    if ! systemctl is-active --quiet docker; then
      log "FATAL: the docker service did not start. Cannot continue."
      exit 1
    fi
    log "  docker: $(docker --version)"

    # ── 2. Docker Compose ────────────────────────────────────────────────────
    # The AL2023 docker package does not reliably bundle the Compose v2 CLI
    # plugin, and this stack needs it — `docker-compose` (v1, hyphenated) is a
    # different command with different flags. Try the packaged plugin first and
    # install the official binary only if it is genuinely absent.
    #
    # The release is PINNED rather than "latest": an unpinned curl-to-shell of
    # a binary is the same reproducibility problem as a hardcoded AMI id, and
    # it would also break silently whenever GitHub changes a URL.
    #
    # linux-x86_64 matches the AMI architecture chosen above, for the same
    # reason. On an ARM host this asset name 404s, which `set -e` turns into a
    # loud, immediate failure instead of a mysterious one.
    if docker compose version >/dev/null 2>&1; then
      log "step 2/6: compose plugin present ($(docker compose version --short))"
    else
      log "step 2/6: installing docker compose plugin $COMPOSE_PLUGIN_RELEASE"
      install -d -m 0755 /usr/libexec/docker/cli-plugins
      curl -fsSL -o /usr/libexec/docker/cli-plugins/docker-compose \
        "https://github.com/docker/compose/releases/download/$COMPOSE_PLUGIN_RELEASE/docker-compose-linux-x86_64"
      chmod 0755 /usr/libexec/docker/cli-plugins/docker-compose
      log "  compose: $(docker compose version --short)"
    fi

    # ── 3. Application source ───────────────────────────────────────────────
    # The instance starts with no copy of the application, so it fetches one.
    # --depth 1 because a boot does not need history; it needs the current
    # tree, and a shallow clone is several times faster on a small instance.
    #
    # If the repository is PRIVATE this step fails with an authentication error
    # and says so in this log. That is expected, and it is NOT fixed by putting
    # a token in the URL — see app_source_url for why that is not done here.
    # The alternatives are a baked AMI or a registry the instance can pull from
    # anonymously.
    log "step 3/6: fetching application source"
    if [ -e "$APP_DIR/.git" ]; then
      log "  existing checkout found, fast-forwarding"
      git -C "$APP_DIR" pull --ff-only
    elif [ -e "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
      # ⚠️  THIS BRANCH EXISTS AND IS DELIBERATE. ⚠️
      #
      # $APP_DIR exists but is not a git checkout. That is reachable, not
      # theoretical: a first boot that failed at an earlier step can leave the
      # directory behind, and so can anyone — or anything — removing .git from
      # an otherwise perfectly good tree.
      #
      # The old guard tested only `[ -d "$APP_DIR/.git" ]`, so this case fell
      # through to `git clone`, which fails with "destination path already
      # exists and is not an empty directory". Under `set -e` that aborts the
      # boot with a git error that never mentions the real problem: the
      # directory is not empty AND is not a repo. Two distinct faults, one
      # unhelpful message.
      #
      # The test above is `-e` on .git rather than `-d` because in a worktree or
      # submodule `.git` is a FILE, not a directory — the old `-d` test would
      # misclassify a working checkout as this fatal case and refuse a tree
      # that was perfectly fine.
      #
      # It is deliberately NOT `git rev-parse --git-dir`, which looks tidier
      # and is wrong here: rev-parse reports success for any directory NESTED
      # INSIDE a repository, inheriting from the parent. If anything above
      # $APP_DIR were ever a checkout, an empty or partial $APP_DIR would be
      # misread as a valid one, and the `git pull --ff-only` above would then
      # run against the PARENT repository. `-e` asks only about $APP_DIR/.git,
      # so the answer cannot come from somewhere else.
      #
      # Deliberately NOT auto-repaired. Deleting $APP_DIR to make the clone
      # succeed would be a bootstrap that silently destroys whatever it finds
      # — and that directory can hold a generated .env, downloaded model
      # weights, and hand-edits, none of which this script is entitled to
      # discard. Fail loudly, name the fault, and let a human decide.
      #
      # An EMPTY leftover directory is deliberately NOT caught by this branch:
      # `git clone` into an empty directory succeeds, so halting there would
      # break a boot that used to work for no gain. The condition above tests
      # for non-emptiness precisely so this fatal path fires only where the
      # clone would genuinely have failed.
      log "FATAL: $APP_DIR exists, is not empty, and is not a git checkout."
      log "       Refusing to clone into it, and refusing to delete it — it"
      log "       may hold a generated .env, downloaded models, or your edits."
      log "       Remove it yourself (losing whatever is in it) or restore the"
      log "       checkout, then re-run this boot script."
      exit 1
    else
      log "  cloning $APP_URL"
      git clone --depth 1 "$APP_URL" "$APP_DIR"
    fi
    log "  commit: $(git -C "$APP_DIR" rev-parse --short HEAD)"

    # ── 4. Environment file ──────────────────────────────────────────────────
    # `.env` is gitignored, so it never arrives with the clone — and Compose
    # substitutes empty strings for missing variables, which is how a stack
    # ends up with API_HOST_PORT="" and a compose file that still looks fine.
    # It is generated here from the committed .env.example.
    #
    # REGENERATED EVERY BOOT, ON PURPOSE. This file is machine-owned and never
    # hand-edited, and its one variable that matters here — API_HOST_PORT —
    # must agree with local.app_port, which is ALSO what the ALB target group
    # is configured with. An operator-edited .env would drift out of agreement
    # with the load balancer and produce a stack that is healthy and
    # unreachable, which is the worst possible combination of properties.
    # Overwriting is the correct behaviour for a generated file.
    log "step 4/6: generating .env from .env.example"
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    sed -i "s|^API_HOST_PORT=.*|API_HOST_PORT=$APP_PORT|" "$APP_DIR/.env"
    log "  $(grep '^API_HOST_PORT=' "$APP_DIR/.env")"

    # NOTE, for whoever adds database support to the api: do NOT add a
    # DATABASE_URL line here. There is no password to put in one, and the
    # endpoint hostname is not knowable from this file — both are fetched at
    # runtime from SSM and Secrets Manager through the instance role. See the
    # bottom of iam.tf.

    # ── 5. Model weights ────────────────────────────────────────────────────
    # ~340MB of GGUF downloaded FROM HuggingFace AT BOOT. This is the slow
    # step, it happens on every fresh instance, and it is the single reason the
    # ALB target group needs a 300-second health check grace period — see
    # var.app_health_check_grace_period_seconds and load_balancer.tf.
    #
    # If this step fails, EVERYTHING downstream fails, and the api never
    # becomes healthy because its compose healthcheck waits on two workers
    # whose models are not on disk. So let it fail LOUDLY here, where the cause
    # is visible, rather than quietly later.
    log "step 5/6: fetching model weights (~340MB from HuggingFace)"
    bash "$APP_DIR/scripts/fetch-models.sh" 2>&1 | tee -a "$LOG_FILE"
    log "  models directory: $(du -sh "$APP_DIR/models" | cut -f1)"

    # ── 6. Start the stack ───────────────────────────────────────────────────
    # The api builds locally from ./api (it has a `build:` section, no published
    # image); the two workers pull the published llama.cpp image. `pull` is
    # best-effort, so a transient registry failure does not abort a boot that
    # could still succeed from a locally cached image.
    log "step 6/6: starting compose services"
    cd "$APP_DIR"
    docker compose pull 2>&1 | tee -a "$LOG_FILE" || log "WARNING: 'docker compose pull' failed; continuing with local build/cache"
    docker compose up -d --remove-orphans 2>&1 | tee -a "$LOG_FILE"
    docker compose ps 2>&1 | tee -a "$LOG_FILE"

    # ── Post-boot verification ───────────────────────────────────────────────
    # Confirm the api answers, so that "the stack is up" is an OBSERVED fact
    # rather than an assumption. 300 seconds, because the api's own compose
    # healthcheck waits for BOTH workers to finish loading their models into
    # memory — a correct boot legitimately looks unhealthy for a while.
    #
    # Exits 0 even on timeout, deliberately. A non-zero exit here would mark
    # the boot as failed at the cloud-init layer, which is noise on top of an
    # ALB grace period that is already handling the real delay — and it would
    # bury the diagnostics below, which are the thing the operator actually
    # needs. A loud warning beats a failure code that says nothing about which
    # of six steps went wrong.
    log "verifying /health (up to 300s)"
    for i in $(seq 1 60); do
      if curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/health"; then
        log "=== lemondrop boot: SUCCESS — api healthy after $((i * 5))s ==="
        exit 0
      fi
      sleep 5
    done

    log "WARNING: the api did not answer /health within 300s."
    log "This is NOT necessarily a failure — model loading can exceed it. Diagnose:"
    log "  docker compose ps"
    log "  docker compose logs --tail=100 api embedder reranker"
    log "  free -m    # an OOM kill while loading the reranker is the first suspect"
    log "  df -h /    # a full root volume fails in ways that mimic every other fault"
    log "=== lemondrop boot: FINISHED WITH WARNINGS ==="
    exit 0
  EOF

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-app"
    Role = "application-host"
  })
}