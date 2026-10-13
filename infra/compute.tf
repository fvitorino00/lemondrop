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
# aws_instance.app has NO count, it is a SINGLE VALUE, so `aws_instance.app`
# can be referenced unconditionally from anywhere, including from the
# count-gated resources in load_balancer.tf.
#
# It must be referenced WITHOUT an index. An uncounted resource is not a list
# that happens to have one element, so `aws_instance.app[0]` is a plan-time
# error ("does not have count or for_each set, references to it must not
# include an index key"), not a safe-looking idiom. Do not add a toggle to this
# resource without auditing every reference to it: adding one does not make
# these references invalid, it makes them CONDITIONAL, and each one then needs
# a one() or try() to survive a false toggle.

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
# plan time. It follows AWS's security updates, it is regional (so an AMI lookup
# can never return an image that does not exist in the region the provider is
# actually configured for), and it costs nothing. The trade is stated honestly:
# you give up byte-for-byte reproducibility of the host, because "today's latest
# AL2023" is a moving target.
#
# Note that "the region" here means the region the PROVIDER resolved, which
# comes from AWS_REGION or the AWS CLI config — NOT from var.aws_region, which
# configures nothing. See the aws_region variable in variables.tf.
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
    # Design rationale, failure history and known limits: docs/boot-script.md.
    # They live there because EC2 rejects user_data over 16,384 bytes and this
    # script was measured at 24,994. Measure any addition against that ceiling.
    #
    # IDEMPOTENT means "safe to repeat", NOT "repairs what it finds". Every step
    # checks before it acts or is natively idempotent, so a re-run over a healthy
    # prior run converges. It does NOT clean up a failed part-way run: an $APP_DIR
    # that exists but is not a checkout halts the boot with a named error rather
    # than deleting it — whether a half-built directory is disposable is the
    # operator's call. This re-runs often (user_data_replace_on_change, by hand
    # while debugging), so the distinction matters.
    #
    # LOGGED THROUGHOUT to /var/log/lemondrop-boot.log AND
    # /var/log/cloud-init-output.log. A failed boot with no SSH key and no public IP
    # is otherwise a mystery; the log is the only handle:
    #
    #     sudo tail -n 100 /var/log/lemondrop-boot.log
    #     sudo cat  /var/log/cloud-init-output.log
    #
    # ⚠️  NO SECRETS IN THIS FILE. See the comment on user_data in compute.tf.

    # -E (errtrace) is NOT decoration: without it the ERR trap is NOT inherited by
    # shell functions, so a failure inside log/die/on_err goes untrapped.
    set -Eeuo pipefail

    LOG_FILE="/var/log/lemondrop-boot.log"
    APP_DIR="/opt/lemondrop"
    APP_URL="${var.app_source_url}"
    APP_PORT="${local.app_port}"
    COMPOSE_PLUGIN_RELEASE="v2.29.1"
    PLUGIN_DIR="/usr/libexec/docker/cli-plugins"
    BOOT_STATUS="did not finish"

    # tee may fail here WITHOUT taking the script down: a failed log write (ro fs,
    # full disk, bad perms) must not become the reason the boot dies unexplained —
    # the exact failure shape this script exists to eliminate.
    log() { printf '%s [%s]\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG_FILE" || true; }

    # Named, logged, then exited: a deliberate abort with a stated reason, so "the
    # operator chose to stop" never looks like "something crashed".
    die() {
      BOOT_STATUS="FAILED — $1"
      log "FATAL: $1"
      exit 1
    }

    # The highest-value line here: any uncaught non-zero exit prints the LINE
    # NUMBER, COMMAND and EXIT CODE, then the EXIT trap prints the terminal marker.
    # Without it a failed boot is a log that just stops, with no visible reason.
    on_err() {
      BOOT_STATUS="FAILED at line $2 (exit $1)"
      log "FATAL: boot died at line $2, exit status $1"
      log "       command: $3"
      log "       the command's own output is immediately above this line"
    }
    trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR

    # Always fires, so the last log line is a verdict rather than a truncation.
    finish() { log "=== lemondrop boot: $BOOT_STATUS ==="; }
    trap finish EXIT

    log "=== lemondrop boot: START ==="
    log "app dir      : $APP_DIR"
    log "app url      : $APP_URL"
    log "app host port: $APP_PORT"

    # 1. Packages-------------------------------------------------------
    # git   : the source is cloned, not baked into the AMI.
    # curl  : NOT INSTALLED, and that is the correction. AL2023 ships
    #         curl-minimal, which already provides /usr/bin/curl. Requesting full
    #         `curl` beside it is a package conflict that kills the boot at this
    #         line. Installing nothing beats installing something, so use what is
    #         there and VERIFY it below.
    # ca-certificates: a belt-and-braces no-op — it IS the preinstalled trust store
    #         package, so it cannot conflict.
    log "step 1/6: installing packages (docker, git) and verifying curl"
    dnf install -y git ca-certificates

    # docker comes from amazon-linux-extras, NOT from a bare dnf install---
    # AL2023 publishes Docker Engine as an EXTRAS TOPIC, not enabled by default, so
    # `dnf install docker` is "No match for argument" on a stock image. Two guards:
    # `command -v` means a re-run never calls the installer; `||` falls back to dnf
    # for an image that does carry docker in its base repo.
    if ! command -v docker >/dev/null 2>&1; then
      log "  installing docker from amazon-linux-extras"
      amazon-linux-extras install -y docker || dnf install -y docker
    fi
    if ! command -v docker >/dev/null 2>&1; then
      die "docker is still absent after amazon-linux-extras and dnf both ran"
    fi

    # A clear error if curl really is missing, not the dnf conflict dump this guard
    # exists to make unnecessary.
    if ! command -v curl >/dev/null 2>&1; then
      log "       AL2023 normally provides curl via the curl-minimal package, so"
      log "       reaching this means the image is not a stock AL2023 AMI."
      log "       If you fix it, install curl-minimal — NOT full curl, which"
      log "       conflicts with curl-minimal and is what broke the last boot."
      die "no curl on this host"
    fi
    log "  curl: $(curl --version 2>/dev/null | head -n 1 || true)"

    systemctl enable --now docker

    # Wait for the daemon, don't just check it was asked to start-------
    # `systemctl enable --now` QUEUES the start job; it does not wait for dockerd.
    # `systemctl is-active` right afterwards legitimately returns non-zero while
    # the unit is still `activating` (real seconds on a cold t3.micro).
    # Treating that as fatal is wrong and unactionable when dockerd was about to
    # come up. Poll until it answers, and ask `docker info` too:
    # unit can be `active` a moment before the socket is usable.
    log "  waiting for the docker daemon to answer (up to 60s)"
    docker_ready=0
    for ((i = 1; i <= 30; i++)); do
      if systemctl is-active --quiet docker && docker info >/dev/null 2>&1; then
        docker_ready=1
        break
      fi
      sleep 2
    done
    if [ "$docker_ready" -ne 1 ]; then
      log "       systemctl status docker"
      log "       journalctl -u docker --no-pager --lines=50"
      die "docker is installed but the daemon never became ready"
    fi
    log "  docker: $(docker --version)"

    # 2. Docker Compose-------------------------------------------------
    # The AL2023 docker package does not reliably bundle the Compose v2 plugin, and
    # `docker-compose` (v1, hyphenated) is a different command, different flags.
    # PINNED, not "latest": an unpinned curl-to-shell of a binary breaks silently
    # whenever GitHub changes a URL. linux-x86_64 matches the AMI arch; on ARM this
    # asset 404s, which `set -e` turns into a loud failure, not a mystery.
    if docker compose version >/dev/null 2>&1; then
      log "step 2/6: compose plugin present ($(docker compose version --short))"
    else
      log "step 2/6: installing docker compose plugin $COMPOSE_PLUGIN_RELEASE"
      # A default docker CLI plugin search path on Linux, hence here and not in a
      # path only this script knows about.
      install -d -m 0755 "$PLUGIN_DIR"
      # Downloaded to .part and moved into place only on success. Writing straight to
      # the final path leaves an interrupted transfer sitting at the name docker
      # looks for, so every LATER run finds a plugin that exists, is executable and
      # is garbage — the "plausible file poisons the next run" failure
      # fetch-models.sh already guards against for the GGUFs.
      if ! curl -fsSL -o "$PLUGIN_DIR/docker-compose.part" \
        "https://github.com/docker/compose/releases/download/$COMPOSE_PLUGIN_RELEASE/docker-compose-linux-x86_64"; then
        rm -f "$PLUGIN_DIR/docker-compose.part"
        die "could not download the docker compose plugin $COMPOSE_PLUGIN_RELEASE"
      fi
      chmod 0755 "$PLUGIN_DIR/docker-compose.part"
      mv "$PLUGIN_DIR/docker-compose.part" "$PLUGIN_DIR/docker-compose"
      log "  compose: $(docker compose version --short)"
    fi

    # 3. Application source---------------------------------------------
    # --depth 1: a boot needs the current tree, not history, and a shallow clone is
    # several times faster on a small instance.
    #
    # If the repository is PRIVATE this fails with an authentication error and says
    # so in this log. Expected — and NOT fixed by a token in the URL; see
    # app_source_url for why, docs/boot-script.md for the options.
    log "step 3/6: fetching application source"
    if [ -e "$APP_DIR/.git" ]; then
      log "  existing checkout found, fast-forwarding"
      git -C "$APP_DIR" pull --ff-only
    elif [ -e "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
      # ⚠️  THIS BRANCH IS DELIBERATE. ⚠️
      #
      # $APP_DIR exists but is not a checkout — reachable, not theoretical: an
      # earlier failed boot can leave it, and so can anyone removing .git from a
      # good tree. Git's own error ("already exists and is not an empty directory")
      # never mentions the real problem: not empty AND not a repo.
      #
      # `-e` on .git, not `-d`: in a worktree or submodule .git is a FILE, and `-d`
      # would misclassify a good checkout as this fatal case. Not
      # `git rev-parse --git-dir` either — it succeeds for any directory NESTED
      # INSIDE a repo, so a parent checkout would make the `git pull --ff-only`
      # above run against the PARENT repository.
      #
      # NOT auto-repaired: deleting $APP_DIR would silently destroy a generated
      # .env, downloaded weights and hand-edits. An EMPTY leftover is also not
      # caught — `git clone` into an empty dir succeeds, so halting there would
      # break a working boot for no gain.
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

    # 4. Environment file-----------------------------------------------
    # `.env` is gitignored and never arrives with the clone, and Compose substitutes
    # empty strings for missing variables — how a stack gets
    # API_HOST_PORT="" and still looks fine. Generated here from .env.example.
    #
    # REGENERATED EVERY BOOT, ON PURPOSE: machine-owned, never hand-edited, and
    # API_HOST_PORT must agree with local.app_port, ALSO the ALB target group's
    # port. An operator-edited .env drifts out of agreement and produces a stack
    # that is healthy and unreachable — the worst combination of properties.
    log "step 4/6: generating .env from .env.example"
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    sed -i "s|^API_HOST_PORT=.*|API_HOST_PORT=$APP_PORT|" "$APP_DIR/.env"
    # This VERIFIES the substitution; not decoration. sed only rewrites a line
    # already matching ^API_HOST_PORT=, so if .env.example ever loses that key the
    # sed does nothing and Compose interpolates an empty port — a healthy,
    # unreachable stack by the quietest route. Note this used to be a bare
    # `log "$(grep ...)"`: a grep matching nothing returned 1 and was SWALLOWED,
    # because command substitution in an argument position does not trip `set -e`.
    if ! grep -q "^API_HOST_PORT=$APP_PORT$" "$APP_DIR/.env"; then
      log "       .env contains: $(grep '^API_HOST_PORT=' "$APP_DIR/.env" || true)"
      die ".env does not set API_HOST_PORT=$APP_PORT; check .env.example for that key"
    fi
    log "  $(grep '^API_HOST_PORT=' "$APP_DIR/.env" || true)"

    # For whoever adds database support to the api: do NOT add a DATABASE_URL line
    # here. There is no password for one and the hostname is not knowable here —
    # both are fetched at runtime from SSM and Secrets Manager via the instance
    # role. See the bottom of iam.tf.

    # 5. Model weights--------------------------------------------------
    # ~340MB of GGUF from HuggingFace AT BOOT: the slow step, every fresh
    # instance, and why the ALB target group runs at the maximum
    # unhealthy_threshold — even then 10 x 30s = 5 minutes, a window this boot can
    # exceed.
    #
    # If this fails EVERYTHING downstream fails: the api never becomes healthy,
    # because its healthcheck waits on two workers whose models are not on disk. So
    # let it fail LOUDLY here, where the cause is visible. pipefail makes this
    # pipeline's status the WORST of its two commands, so the abort happens HERE,
    # nowhere else; the ERR trap records WHICH line.
    log "step 5/6: fetching model weights (~340MB from HuggingFace)"
    bash "$APP_DIR/scripts/fetch-models.sh" 2>&1 | tee -a "$LOG_FILE"
    log "  models directory: $(du -sh "$APP_DIR/models" | cut -f1)"

    # Resource headroom, recorded BEFORE the stack starts---------------
    # Two lines, here because an OOM kill and a full root volume are both SILENT
    # from outside: the container dies, the ALB sees nothing on 8000, and the log
    # reads like a clean run that never became healthy. The numbers let the next
    # person compare against the host at the moment of failure instead of guessing.
    # t3.micro is ~913Mi with no swap and the two GGUFs are ~410MB resident once
    # loaded. Tight — if this boot dies there, the memory line above is the evidence.
    log "  memory before start:"
    free -m | tee -a "$LOG_FILE"
    log "  disk before start:"
    df -h / | tee -a "$LOG_FILE"

    # 6. Start the stack------------------------------------------------
    # The api builds locally from ./api (`build:`, no published image); the workers
    # pull the published llama.cpp image.
    #
    # The pull is NAMED per service on purpose: a bare `docker compose pull` also
    # pulls the api, whose image `lemondrop-api` is built here and exists in no
    # registry, so it could only fail and trip its own "WARNING: pull failed".
    log "step 6/6: starting compose services"
    cd "$APP_DIR"
    docker compose pull embedder reranker 2>&1 | tee -a "$LOG_FILE" \
      || log "WARNING: 'docker compose pull' failed; continuing with local build/cache"
    docker compose up -d --remove-orphans 2>&1 | tee -a "$LOG_FILE"
    docker compose ps 2>&1 | tee -a "$LOG_FILE"

    # Post-boot verification--------------------------------------------
    # Confirm the api answers, so "the stack is up" is an OBSERVED fact. 300s,
    # because the api's own healthcheck waits for BOTH workers to load their
    # models — a correct boot legitimately looks unhealthy for a while.
    #
    # Exits 0 even on timeout, deliberately: non-zero would mark the boot failed at
    # the cloud-init layer — noise on top of an ALB grace period already handling
    # the delay — and would bury the diagnostics below, which are what the operator
    # needs.
    log "verifying /health (up to 300s)"
    # A C-style loop, not `seq 1 60`: one less coreutils dependency for no gain.
    for ((i = 1; i <= 60; i++)); do
      if curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/health"; then
        BOOT_STATUS="SUCCESS — api healthy after $((i * 5))s"
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
    log "Compare both against the 'before start' readings logged in step 6."
    # The EXIT trap prints the terminal marker, so this sets the verdict; the last
    # log line is the same shape whichever path the boot took.
    BOOT_STATUS="FINISHED WITH WARNINGS — api never answered /health"
    exit 0
  EOF

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-app"
    Role = "application-host"
  })
}

