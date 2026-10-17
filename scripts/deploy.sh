#!/usr/bin/env bash
#
# lemondrop — deploy a published api image to THIS host. (M4 Stage 5)
#
#   sudo ./scripts/deploy.sh <registry>/<repo>@sha256:<64-hex> [source-git-revision]
#   sudo ./scripts/deploy.sh --adopt-current <database-verified-alembic-revision>
#
# ── WHAT THIS REPLACES ────────────────────────────────────────────────────────
# Boot-time deployment: `git clone` at branch tip, then `docker compose up
# --build`, which builds the api on whatever machine is running it from
# whatever the branch happened to be at that instant. Nothing names the running
# version, the test suite has no causal relationship to the artifact in
# production, and rolling back needs git history that `boot.sh --depth 1`
# explicitly does not have.
#
# This script deploys an artifact that CI already built, tested and published,
# addressed by manifest digest. Rolling back becomes "start the previous
# image" — no history, no rebuild, no network fetch of source.
#
# ── WHY THE DIGEST IS NOT OPTIONAL ────────────────────────────────────────────
# docs/verification-milestone-3.md §11.2, on a tag: "A tag overwritten in place
# is not a rollback point — it is the same failure mode as having no rollback at
# all, only harder to notice." A tag is a mutable pointer and GHCR enforces no
# immutability on one. Two deploys of `…:main` a week apart can be different
# bytes, and the second one is not a rollback of the first. Hence: digest, and
# `validate_image_digest` in scripts/lib/deploy-lib.sh refuses everything else.
#
# ── WHY THIS SCRIPT RUNS ON THE HOST AND NOT IN CI ────────────────────────────
# Because a deployment is a decision, and CI turning "we deployed" into "it
# deployed" makes the first bad deploy invisible. A human runs this, having
# looked at what is being deployed. Getting the scripts onto the host is a
# separate, approved operation and is described in DELIVERY, at the bottom of
# this file. No SSM transport is written here, on purpose.
#
# ── THE ORDER IS THE DESIGN ───────────────────────────────────────────────────
# Every step below exists because of a specific way the obvious ordering fails.
# In particular, NOTHING is changed until every check that can be made without
# changing something has passed:
#
#   1. lock           two deploys must not interleave
#   2. validate       a bad reference must never reach the registry
#   3. capture        the previous state must exist before it is replaced
#   4. tag            the running image must have a stable name to return to
#   5. registry check a typo'd digest must fail in seconds, not minutes
#   6. SCHEMA GATE    fail closed — refuse, never migrate. Runs twice: once from
#                     the source tree when a revision was supplied, and once
#                     from the image after the pull. See step 6 below.
#   7. pull           only now is the network spent
#   6b/6c FACTS + GATE
#                     the image's own labels establish the revision and the
#                     schema head, the authoritative schema gate runs on them
#   8. switch         .env, then ONE service
#   9. verify         ready AND a correct search, before anything is recorded
#  10. record         only after 9 has passed
#
# and at any point after step 3, a failure restores BOTH the image and `.env`.
#
# STATED HONESTLY, because the numbering is not tidy: 6b/6c are numbered for
# where they sit in the argument, and they run AFTER 7 because reading a label
# requires the image. A deploy that supplies no revision cannot therefore be
# refused before the download — only after it, and still before anything on
# this host is touched. That is the price of trusting the image's own account
# of itself, and it is the only part of the ordering this file has given up.

# -E (errtrace): without it the ERR trap is not inherited by shell functions, so
# a failure inside a helper goes untrapped. Same reasoning as scripts/boot.sh:26.
set -Eeuo pipefail

# Resolve the library relative to THIS FILE, not to $PWD. A deploy run from the
# wrong directory must not source a different deploy-lib.sh, or fail confusingly.
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
# shellcheck source=scripts/lib/deploy-lib.sh
# shellcheck disable=SC1091  # deploy-lib.sh is sourced dynamically via $_LIB_DIR;
#                            # ShellCheck follows it only when it is also passed
#                            # as an input (the combined run). The per-file runs
#                            # used by the harness cannot, so this narrow,
#                            # line-scoped suppression covers them; deploy-lib.sh
#                            # is still checked independently on its own.
. "$_LIB_DIR/deploy-lib.sh"

usage() {
  cat <<'EOF'
Usage:
  deploy.sh <registry>/<repository>@sha256:<64-hex-digest> [source-git-revision]
  deploy.sh --adopt-current <database-verified-alembic-revision>

Deploys a published, tested api image to this host and records what it deployed.

  <image digest>      REQUIRED, and must be digest-pinned. Tags, bare names and
                      empty arguments are refused — see validate_image_digest()
                      in scripts/lib/deploy-lib.sh for the reason behind each.

  [source-git-revision]
                      OPTIONAL on any image that carries OCI labels, and
                      REQUIRED on one that does not. The image's
                      org.opencontainers.image.revision label is preferred;
                      org.lemondrop.alembic-head is preferred for the schema.
                      When they are absent, this argument is used instead and a
                      loud warning says so — the image published from commit
                      8cddfe8 (sha256:0bdb7afa…42986) has no labels and must
                      stay deployable.

                      Supplying it when the image IS labelled is not redundant:
                      if the argument and the label name different commits, the
                      two are in conflict and this script REFUSES rather than
                      picking one. That check is worth more than the argument's
                      disappearance.

  --adopt-current <database-verified-alembic-revision>
                      Write an initial revision record describing what is
                      running RIGHT NOW, changing nothing. For the one-time
                      M3 -> M4 transition on a host that has never had a
                      record. Refuses if a record already exists. This is not a
                      way to skip the schema check: there is no comparison to
                      skip when there is no baseline. See adopt_current() below.

                      <database-verified-alembic-revision> is REQUIRED, with no
                      default and no fallback — running this without it refuses.
                      It is the alembic revision actually at the RDS instance,
                      as read out of band (see api/alembic/README.md), because
                      that is the number every later deploy's fail-closed schema
                      gate is measured against. This host cannot read it: the
                      EC2 role holds the application secret only and lemondrop_app
                      has no DDL rights (infra/iam.tf). It is NOT taken from the
                      git tree — the checkout is routinely AHEAD of the database
                      or behind it, and either way it answers a different
                      question ("what does this code expect?") than the one the
                      record means ("what is the database at?"). An image's
                      org.lemondrop.alembic-head label is not a substitute either
                      and is not used as one: it says what the image EXPECTS.

Only the `api` service is recreated. The embedder, the reranker, their loaded
models and the database are not touched.
EOF
}

# ═════════════════════════════════════════════════════════════════════════════
# State captured before anything is changed
# ═════════════════════════════════════════════════════════════════════════════
#
# CAPTURED_* are set by capture_state() and consumed by restore_previous().
# They are globals because the ERR trap runs at the top level, outside the scope
# of main(), and a trap that cannot see the state it needs is a trap that
# silently does nothing.
CAPTURED=0                  # 0 until step 3 has succeeded
PREV_ENV_BACKUP=""
PREV_IMAGE_ID=""
PREV_CONTAINER_ID=""
PREV_ROLLBACK_TAG=""
ROLLING_BACK=0

restore_previous() {
  # Guard against re-entry: restore_previous runs compose, and a failure inside
  # it would re-enter this function through the same trap.
  [ "$ROLLING_BACK" -eq 0 ] || return 0
  ROLLING_BACK=1

  say ""
  say "──────────────────────── ROLLING BACK ────────────────────────"

  if [ -n "$PREV_ENV_BACKUP" ] && [ -f "$PREV_ENV_BACKUP" ]; then
    if env_restore "$PREV_ENV_BACKUP" "$LEMDROP_APP_DIR/.env"; then
      say "rollback: .env restored from the copy taken before this deploy."
    else
      say "rollback: .env RESTORE FAILED. The copy is at $PREV_ENV_BACKUP —"
      say "          restore it by hand and then re-run deploy.sh."
    fi
  fi

  if [ -z "$PREV_IMAGE_ID" ]; then
    say "rollback: no api container was running before this deploy, so there"
    say "          is no previous image to return to. The api service has been"
    say "          left as it is; remove it by hand if that is not what you want."
  elif [ -n "$PREV_ROLLBACK_TAG" ] && docker image inspect "$PREV_ROLLBACK_TAG" >/dev/null 2>&1; then
    # The rollback tag names the exact image the container was created from, and
    # it was taken from the image ID rather than from a name precisely because
    # a name can be moved. Point API_IMAGE at it and start it.
    if env_set "$LEMDROP_APP_DIR/.env" API_IMAGE "$PREV_ROLLBACK_TAG"; then
      say "rollback: API_IMAGE set to the pre-deploy image tag $PREV_ROLLBACK_TAG"
    fi
    if compose up -d --no-build --no-deps --force-recreate api; then
      say "rollback: api recreated from $PREV_ROLLBACK_TAG"
      say ""
      say "rollback: verifying the previous image is serving again…"
      if verify_stack; then
        say "rollback: the previous image is ready and its known-good search passes."
        say "          The revision record was NOT changed — it still describes"
        say "          the deployment that just failed, which is correct: nothing"
        say "          was deployed."
        say "──────────────────── ROLLBACK COMPLETE ─────────────────────"
        return 0
      fi
      say "rollback: the previous image was restored but is NOT serving correctly."
      say "          This is now a separate incident. See:"
      say "            docker compose logs --tail=100 api"
      say "            scripts/verify-deployment.sh"
      say "──────────────── ROLLBACK INCOMPLETE ─────────────────"
      return 1
    fi
    say "rollback: FAILED to recreate the api container from $PREV_ROLLBACK_TAG."
    say "          Start it by hand:"
    say "            cd $LEMDROP_APP_DIR && API_IMAGE=$PREV_ROLLBACK_TAG docker compose up -d --no-build --no-deps --force-recreate api"
    say "──────────────── ROLLBACK INCOMPLETE ─────────────────"
    return 1
  else
    say "rollback: the pre-deploy image $PREV_IMAGE_ID is no longer available"
    say "          locally (tag $PREV_ROLLBACK_TAG missing). Start it by hand:"
    say "            docker tag $PREV_IMAGE_ID $LEMDROP_COMPOSE_PROJECT-api:recovered"
    say "            cd $LEMDROP_APP_DIR && API_IMAGE=$LEMDROP_COMPOSE_PROJECT-api:recovered \\"
    say "              docker compose up -d --no-build --no-deps --force-recreate api"
    say "──────────────── ROLLBACK INCOMPLETE ─────────────────"
    return 1
  fi
}

# ── WHY fail() EXISTS INSTEAD OF die() ────────────────────────────────────────
# `die` (in scripts/lib/deploy-lib.sh) logs and exits. On its own that is a
# correct way to abort — until the moment the ERR trap starts being load-bearing,
# which is when it stops being correct.
#
# The ERR trap catches commands that FAIL. It does not catch `exit`. So the
# single most important line in this script —
#
#     if ! verify_stack; then ...; exit "$EX_FAILED"; fi
#
# would have exited WITHOUT rolling back, on the one failure path that matters
# most. That is not hypothetical: it is what happened the first time this was
# run. Verification failed, the script printed "Rolling back", and then exited 3
# having rolled nothing back and left `.env` pinned to an image that was not
# serving.
#
# So every deliberate abort goes through `fail`, which restores the previous
# deployment whenever anything has been captured, and the ERR trap handles
# everything uncaught. Both paths converge on `restore_previous`, which is
# itself re-entrancy-guarded.
fail() {
  local msg="$1" code="${2:-$EX_FAILED}"
  log "FATAL: $msg"
  if [ "${CAPTURED:-0}" -eq 1 ]; then
    say ""
    restore_previous || true
  fi
  exit "$code"
}

# Any uncaught failure from here on, once state has been captured, restores the
# previous deployment and then exits non-zero. Deliberately NOT installed before
# capture_state(): before that point nothing has changed, so there is nothing to
# restore, and a rollback path that runs against empty state prints alarming
# text about a container that never existed.
on_err() {
  local rc="$1" line="$2" cmd="$3"
  say ""
  say "FAILED at line $line (exit $rc): $cmd"
  if [ "$CAPTURED" -eq 1 ]; then
    restore_previous || true
  else
    say "nothing had been changed at this point, so there is nothing to roll back."
  fi
  exit "$rc"
}

# ═════════════════════════════════════════════════════════════════════════════
# Steps
# ═════════════════════════════════════════════════════════════════════════════

# Step 3. Everything needed to put this host back exactly as it is, taken while
# the old deployment is still running and untouched.
#
# The `.env` backup is a full copy, not a diff and not just the API_IMAGE line.
# A rollback that restores the image but leaves `.env` pointing at the new digest
# starts the OLD image and then fails to record or to re-pin on the next deploy,
# and the resulting state is harder to reason about than either end of it.
capture_state() {
  local stamp; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  PREV_ENV_BACKUP="$(mktemp "$LEMDROP_STATE_DIR/env.before-deploy.XXXXXX")" \
    || fail "cannot create a backup file in $LEMDROP_STATE_DIR"
  chmod 0600 "$PREV_ENV_BACKUP"

  if [ ! -f "$LEMDROP_APP_DIR/.env" ]; then
    log "there is no .env at $LEMDROP_APP_DIR/.env."
    log "  On EC2 this file is generated by scripts/boot.sh step 4 from"
    log "  .env.example. Its absence means boot has not run on this host, and"
    log "  there is no environment to deploy into."
    exit "$EX_REFUSED"
  fi
  # The FULL current .env, captured before anything reads or writes it.
  cat "$LEMDROP_APP_DIR/.env" > "$PREV_ENV_BACKUP" \
    || fail "cannot read $LEMDROP_APP_DIR/.env"

  if [ -f "$LEMDROP_RECORD_FILE" ]; then
    log "existing record: $(grep '^IMAGE_DIGEST=' "$LEMDROP_RECORD_FILE" || echo '(no IMAGE_DIGEST line)')"
  else
    log "no existing record at $LEMDROP_RECORD_FILE"
  fi

  PREV_CONTAINER_ID="$(api_container_id)"
  if [ -n "$PREV_CONTAINER_ID" ]; then
    PREV_IMAGE_ID="$(running_image_id "$PREV_CONTAINER_ID")"
  fi

  if [ -n "$PREV_IMAGE_ID" ]; then
    # Step 4: retag BEFORE anything else, so the image the container is running
    # has a stable, timestamped name to return to.
    #
    # WHY A TIMESTAMP IN THE NAME. A tag like `lemondrop-api:previous` would be
    # overwritten by the next deploy, which makes it no rollback point at all —
    # the M3 failure mode verbatim. A timestamped tag names exactly one deploy's
    # predecessor and is never rewritten. It is recorded, so it survives the
    # process that created it.
    PREV_ROLLBACK_TAG="lemondrop-api:rollback-${stamp}"
    docker tag "$PREV_IMAGE_ID" "$PREV_ROLLBACK_TAG" \
      || fail "cannot tag the running image $PREV_IMAGE_ID as $PREV_ROLLBACK_TAG"
    log "rollback tag: $PREV_ROLLBACK_TAG -> $PREV_IMAGE_ID"
  else
    log "no api container is running; there is no previous image to tag"
  fi

  CAPTURED=1
}

# Step 6. THE SCHEMA GATE. Fail closed, always, with no override.
#
# ── WHAT IT COMPARES, AND WHY THAT IS THE ONLY COMPARISON ─────────────────────
# The alembic head of the TARGET source revision against the alembic head
# RECORDED when the running deployment was recorded. Equal: proceed. Different:
# refuse.
#
# ── WHAT IT DELIBERATELY DOES NOT DO ──────────────────────────────────────────
# It does not check whether the target revision *contains a migration file*.
# That check is wrong, and wrong in the direction that matters: repositories
# accumulate migration files across releases, so "this revision has migrations
# under api/alembic/" is true of nearly every deploy and would refuse almost
# all of them while proving nothing. The question is not "were migrations
# written" but "does the head differ". A revision that adds a migration file
# without moving the head — a reverted migration, a squashed branch — changes
# nothing, and must not stop a deploy.
#
# ── WHY THERE IS NO OVERRIDE FLAG ─────────────────────────────────────────────
# Because every override flag is a promise that the thing being overridden will
# be handled by someone else, later, and M4 §4.4 item 5 is explicit that the
# whole rollback story rests on the deploy being safe on its own terms. Worse,
# the override cannot be meaningfully granted from here: the EC2 role reads only
# the application secret and `lemondrop_app` has no DDL rights
# (infra/iam.tf). There is no migration that can be run from this host, by
# this script, with an override, because there is no credential here that could
# run one. The only correct action available on a head mismatch is to STOP.
#
# The separate, approved procedure is: apply the migration out of band, with the
# RDS master credential, from a workstation — see api/alembic/README.md for how
# that is done and what it refuses to do. Then record the new head and deploy.
schema_gate() {
  local target_rev="$1" target_head="$2"
  local recorded_head

  if ! record_is_valid "$LEMDROP_RECORD_FILE"; then
    say "schema gate: no usable baseline. Deploying without one would mean"
    say "  deploying without knowing what the database currently is."
    say "  If this host has never been deployed to, run:"
    say "      scripts/deploy.sh --adopt-current <db-verified-alembic-revision>"
    say "  once, by hand, having looked at what it reports."
    return 1
  fi

  recorded_head="$(record_get ALEMBIC_HEAD "$LEMDROP_RECORD_FILE")"
  if [ -z "$recorded_head" ]; then
    say "schema gate: the record at $LEMDROP_RECORD_FILE carries no ALEMBIC_HEAD."
    say "  That means the deployed revision's schema was never written down, so"
    say "  there is nothing to compare the target against. Refusing rather than"
    say "  treating 'unknown' as 'compatible' — that is the failure this gate exists for."
    return 1
  fi

  if [ "$recorded_head" = "$target_head" ]; then
    log "schema gate: OK — target head '$target_head' matches the recorded head."
    return 0
  fi

  say ""
  say "════════════════ SCHEMA MISMATCH — REFUSING ════════════════"
  say "  recorded alembic head (the running deployment): $recorded_head"
  say "  target  alembic head (revision ${target_rev}):     $target_head"
  say ""
  say "  These differ. The image you asked to deploy expects a database"
  say "  schema the database is not at. Deploying it would start an api that"
  say "  cannot read or write its own table — or, worse, that writes against a"
  say "  schema a rollback would then have to be compatible with."
  say ""
  say "  This script will NOT migrate, and there is no flag to make it. The EC2"
  say "  role can read only the application secret and lemondrop_app has no DDL"
  say "  rights (infra/iam.tf), so a migration cannot be run from this host at"
  say "  all. Anything else would be a lie about what this host can do."
  say ""
  say "  WHAT TO DO — a separate, approved procedure:"
  say "    1. Deploy a revision whose head is '$recorded_head', if one exists."
  say "    2. Otherwise, change the schema from '$recorded_head' to"
  say "       '$target_head' out of band, with the RDS master credential, from a"
  say "       workstation — see api/alembic/README.md. Never from EC2."
  say "       (Whichever direction this is: a target BEHIND the recorded head"
  say "       means the database has moved on and this image is too old.)"
  say "    3. Re-run scripts/deploy.sh --adopt-current <the new head you just"
  say "       applied to the database, verified out of band> to record the new"
  say "       baseline, then deploy."
  say "    4. Check whether '$recorded_head' -> '$target_head' is backward"
  say "       compatible BEFORE assuming a rollback to '$recorded_head' is still"
  say "       safe afterwards. If it is not, rolling the API back alone is not"
  say "       an option and the database must move too."
  say ""
  say "  Nothing has been changed. The running deployment is untouched."
  say "═════════════════════════════════════════════════════════════"
  return 1
}

# Is this string shaped like something alembic could call a revision?
#
# SHAPE ONLY, and the omission is deliberate: the value is NOT looked up in the
# checkout. The entire reason this argument exists is that the answer comes from
# the database, and the database is frequently not what the tree says — a
# migration applied out of band with the RDS master credential is the normal way
# this host's schema moves, and boot.sh clones --depth 1 of whatever main was at
# boot. A checkout that could confirm the value would be a checkout that could
# contradict it, which is the confusion this argument was added to remove.
#
# What IS rejected is anything that could not be a revision id at all, plus the
# three symbolic names alembic itself reserves. A value that survives this is not
# proven correct — nothing on this host can prove that — it is merely not
# malformed, and the record says which of the two it is.
validate_alembic_revision_id() {
  local id="${1-}"

  if [ -z "$id" ]; then
    say ""
    say "refusing: no alembic revision was given."
    say "  --adopt-current requires the revision the DATABASE is at, read out of"
    say "  band, because this host cannot read it: the EC2 role holds the"
    say "  application secret only and lemondrop_app has no DDL rights"
    say "  (infra/iam.tf)."
    say ""
    say "  Read it from the RDS instance (api/alembic/README.md) and pass it:"
    say "    scripts/deploy.sh --adopt-current <alembic-revision>"
    say ""
    say "  It is deliberately NOT read from the git tree: the checkout answers"
    say "  'what schema does this code expect', and this argument is 'what"
    say "  schema is the database at'. Those differ whenever a migration has been"
    say "  applied out of band, which is the normal way this host's schema moves."
    return 1
  fi

  if [ "${#id}" -gt 64 ]; then
    say ""
    say "refusing: '${id}' is ${#id} characters long."
    say "  An alembic revision identifier is a short opaque string. A value this"
    say "  long is a paste of something else — a sentence, a command, a URL."
    return 1
  fi

  # Identifier characters only. This is what rejects whitespace (which is what
  # would otherwise end up inside the record and make a later reader choke on it),
  # shell metacharacters, path separators and a quoted string pasted whole.
  case "$id" in
    *[!A-Za-z0-9._-]*)
      say ""
      say "refusing: '${id}' is not a plausible alembic revision identifier."
      say "  Expected letters, digits, '.', '_' and '-' only, up to 64 characters."
      say "  Got: $(printf '%s' "$id" | tr -c '[:print:]' '?')"
      return 1 ;;
  esac

  # Must BEGIN with an alphanumeric. A leading '-', '.' or '_' is not a revision
  # id but is exactly the shape of a CLI flag, a path fragment or a placeholder
  # someone typed to mean "no value" — and all three would otherwise pass a
  # character-class check.
  case "$id" in
    [A-Za-z0-9]*) : ;;
    *)
      say ""
      say "refusing: '${id}' does not start with a letter or a digit."
      say "  An alembic revision identifier starts with an alphanumeric character."
      return 1 ;;
  esac

  # alembic's own symbolic names. They are not revision ids, and writing one into
  # the baseline would be a value no migration can ever be compared against.
  case "$(printf '%s' "$id" | tr '[:upper:]' '[:lower:]')" in
    head|heads|base)
      say ""
      say "refusing: '${id}' is an alembic symbolic name, not a revision id."
      say "  'head', 'heads' and 'base' move as the history moves. The baseline"
      say "  has to be a value that means one specific schema."
      return 1 ;;
  esac

  return 0
}

# --adopt-current. Records what is running now, and changes nothing at all.
#
# This exists because the very first deployment on an existing M3 host has no
# baseline to compare against: nothing was ever recorded, so there is no "head
# the database is at". The alternatives were to refuse forever, or to invent one.
# Inventing one is wrong; the operator looks, confirms, and writes down what is
# true.
#
# ── TWO FACTS, AND NEITHER OF THEM IS GUESSED ──────────────────────────────────
#
#   ALEMBIC_HEAD   comes from the OPERATOR, who read it out of the database with
#                  a credential this host does not have. Mandatory argument, no
#                  default, no derivation from git. The database is the
#                  authority: it is what every later deploy's schema gate
#                  compares against, so anything the tree says about it is a
#                  different fact, not a fallback for it.
#
#   REVISION       comes from the IMAGE, if the image can say. When it cannot,
#                  the record says so — by carrying no revision — rather than
#                  carrying the checkout's HEAD. The checkout is what boot.sh
#                  last cloned; on a host whose checkout has moved since the
#                  image was built, HEAD is a statement about the tree on disk,
#                  not about the bytes that are running, and recording it would
#                  assert a provenance nobody established. An unknown revision is
#                  a fact a reader can act on. An invented one is not.
#
# WHY THIS FUNCTION NO LONGER CALLS `resolve_deploy_facts`. It used to, with
# `git rev-parse HEAD` in the operator-argument slot. That was wrong twice over:
# for an unlabelled image it fed the checkout in as if it were evidence, and for
# a labelled one it made the checkout a COMPETING assertion, so a host whose
# checkout was ahead of the image it was running got a PROVENANCE CONFLICT
# refusal — a contradiction manufactured out of a number that was never a claim
# about the image. Adoption records what is RUNNING; a deploy resolves what is
# ABOUT TO RUN. Those are different questions and they now have different code.

adopt_current() {
  local db_head="${1-}"
  say "── adopting the current state as the first recorded deployment ──"
  if [ -f "$LEMDROP_RECORD_FILE" ]; then
    say "REFUSING: a record already exists at $LEMDROP_RECORD_FILE."
    say "  Adopting over a real record would destroy the rollback point it holds."
    say "  To deploy a new revision, run deploy.sh <digest> <source-revision>."
    return "$EX_REFUSED"
  fi

  # Validated BEFORE anything is read from docker, so a mistyped argument costs a
  # message and not a look at the host.
  if ! validate_alembic_revision_id "$db_head"; then
    say ""
    say "NOT ADOPTED. Nothing has been changed."
    return "$EX_REFUSED"
  fi

  local cid image_id
  cid="$(api_container_id)"
  if [ -z "$cid" ]; then
    say "REFUSING: no api container is running. There is no state to adopt."
    return "$EX_REFUSED"
  fi
  image_id="$(running_image_id "$cid")"
  if [ -z "$image_id" ]; then
    say "REFUSING: could not read the image ID of container $cid."
    return "$EX_REFUSED"
  fi

  # ── WHAT THE IMAGE SAYS ABOUT ITSELF ───────────────────────────────────────
  # Read, never derived. A labelled image is authoritative about what it is and
  # its label is used as it stands; an unlabelled image is recorded as unlabelled.
  #
  # NOTHING IS SUBSTITUTED FOR A MISSING LABEL. Not the checkout's HEAD, not a
  # timestamp, not a guess: an image with no org.opencontainers.image.revision
  # genuinely does not carry its provenance, and a record that says so is a record
  # a reader can reason about. `scripts/verify-deployment.sh` reports it as
  # PROVENANCE UNKNOWN, and `scripts/deploy.sh` treats the next deploy's own
  # labels as the first real provenance this host will have.
  local rev="" rev_source="" label_rev
  label_rev="$(image_source_revision "$image_id")"
  if [ -n "$label_rev" ]; then
    rev="$label_rev"
    rev_source="image-label (${LABEL_REVISION})"
  else
    rev=""
    rev_source="UNKNOWN — the image carries no ${LABEL_REVISION} label"
  fi

  # ── THE IMAGE'S SCHEMA LABEL vs THE DATABASE ────────────────────────────────
  # The label says what the code EXPECTS; the operator's value says what the
  # database IS. When those differ, the api that is running right now expects a
  # schema the database is not at — which is either an incident in progress or a
  # database that has moved on without the host noticing, and neither is a state
  # to write a schema baseline into. Refused, with both values named, because the
  # alternative is a baseline that will make every later deploy compare against a
  # contradiction.
  local label_head
  label_head="$(image_alembic_head "$image_id")"
  if [ -n "$label_head" ] && [ "$label_head" != "$db_head" ]; then
    say ""
    say "════════ SCHEMA DISAGREEMENT — REFUSING ════════"
    say "  the running image's ${LABEL_ALEMBIC_HEAD} label says : ${label_head}"
    say "  the revision you verified in the database says       : ${db_head}"
    say ""
    say "  The label is what this image's code EXPECTS. Your value is what the"
    say "  database IS. They differ, so the api that is running right now expects"
    say "  a schema it is not being served — which is either a migration applied"
    say "  out of band without the api being redeployed, or the wrong revision"
    say "  recorded."
    say ""
    say "  Re-read the revision from the database and check which of the two is"
    say "  right before adopting. Nothing has been changed."
    say "═════════════════════════════════════════════════════"
    return "$EX_REFUSED"
  fi

  # ── THE DIGEST, OR AN HONEST EMPTY ──────────────────────────────────────────
  # An image built on this host has no RepoDigests and no registry reference to
  # find. There was a placeholder here — the string "unrecorded-local-image
  # (<id>)" — and it was wrong twice over: `verify-deployment.sh` compared it
  # against a list of real digests, could never match, and reported DIVERGENCE on
  # a host that was running exactly what the record described; and
  # `rollback.sh` carried it into PREVIOUS_IMAGE_DIGEST, where
  # `validate_image_digest` refused it for the whitespace in the parentheses —
  # blocking the one operation that exists to recover this host.
  #
  # The empty field is correct and is load-bearing: it is what lets
  # verify-deployment.sh report "nothing was compared" (UNPINNED (LEGACY)) rather
  # than a permanent false alarm, and what lets rollback.sh take its documented
  # legacy-tag path. IMAGE_ID carries the identity the digest cannot.
  local digest
  digest="$(image_repo_digests "$image_id" | head -n 1)"

  local verified=UNKNOWN
  say ""
  say "  container   : $cid"
  say "  image id    : $image_id"
  if [ -n "$digest" ]; then
    say "  digest      : $digest"
  else
    say "  digest      : <none> — this image was built on this host and has no"
    say "                registry reference. IMAGE_DIGEST is recorded EMPTY, which"
    say "                is what makes verify-deployment.sh report UNPINNED (LEGACY)"
    say "                and what sends a later rollback down its legacy-tag path."
    say "                The running bytes are identified by IMAGE_ID instead."
  fi
  say "  revision    : ${rev:-<unknown>}  (from: ${rev_source})"
  if [ -z "$rev" ]; then
    say "                Recorded as unknown, on purpose. The checkout's HEAD is"
    say "                not evidence of what built these bytes: it is whatever"
    say "                boot.sh last cloned, and on this host it is ahead of the"
    say "                running image's own tree."
  fi
  say "  alembic head: $db_head  (from: operator-supplied, verified out-of-band"
  say "                against the database — this script did not read the database"
  say "                and cannot: lemondrop_app has no DDL rights, infra/iam.tf)"
  say ""
  say "  This is what is being recorded. Nothing was changed: adoption only"
  say "  reads. If any of it is wrong, fix the cause and delete the record — do"
  say "  not hand-edit it into something truer."

  local -a kv=(
    "RECORD_VERSION=1"
    "REVISION=${rev}"
    "SOURCE_REVISION="
    "IMAGE_DIGEST=${digest}"
  )
  if [ -z "$digest" ]; then
    # Only when the digest cannot name the image. See the note on IMAGE_ID in
    # scripts/lib/deploy-lib.sh: on a digest-bearing record the digest IS the
    # identity, and a second identifier for the same bytes is a drift hazard.
    kv+=("IMAGE_ID=${image_id}")
  fi
  kv+=(
    "ALEMBIC_HEAD=${db_head}"
    "DEPLOYED_AT_UTC=ADOPTED (not deployed by this script)"
    "DEPLOYED_BY=${SUDO_USER:-${USER:-unknown}}"
    "VERIFICATION=${verified}"
    "VERIFIED_AT_UTC="
    "ROLLBACK_TAG="
    "PREVIOUS_REVISION="
    "PREVIOUS_IMAGE_DIGEST="
    "PREVIOUS_ALEMBIC_HEAD="
  )
  write_record "$LEMDROP_RECORD_FILE" "${kv[@]}" \
    || fail "could not write $LEMDROP_RECORD_FILE"

  say ""
  say "adopted. Record written to $LEMDROP_RECORD_FILE"
  return 0
}

main() {
  local target="" source_rev="" adopt_head=""

  case "${1-}" in
    -h|--help) usage; exit "$EX_OK" ;;
    '')
      # An explicitly empty argument is a mistake worth naming, not a request
      # for help. Falling through to the usage text here would exit 0 for a
      # command that deployed nothing, and a deploy script that exits 0 when it
      # did nothing is how a failed deploy gets recorded as a successful one.
      say "refusing: no image reference given."
      usage
      exit "$EX_REFUSED" ;;
    --adopt-current)
      # 1 argument is a refusal, not a default. The baseline alembic head has no
      # derivable source on this host — see validate_alembic_revision_id — so
      # there is nothing to fall back to, and exiting 0 here would leave the
      # operator believing a baseline was written when none was.
      case $# in
        1)
          say "refusing: --adopt-current requires the database-verified alembic revision."
          usage
          exit "$EX_REFUSED" ;;
        2) adopt_head="$2" ;;
        *)
          usage
          fail "--adopt-current takes one argument, the alembic revision the database is at (got $#)." "$EX_REFUSED" ;;
      esac
      mkdir -p "$LEMDROP_STATE_DIR" || fail "cannot create $LEMDROP_STATE_DIR"
      acquire_lock || exit "$EX_LOCKED"
      # Explicit status capture rather than `adopt_current; exit $?`: under
      # `set -e` a bare failing command exits the shell before the `exit $?`
      # line is ever reached. The status is the same either way, but a script
      # whose control flow depends on that subtlety is a script nobody should
      # have to read twice.
      set +e
      adopt_current "$adopt_head"
      local rc=$?
      set -e
      exit "$rc"
      ;;
  esac

  # SC2015: A && B || C is not if-then-else; C may run when A is true. The explicit
  # if below behaves identically (usage + fail → exit EX_REFUSED for 0 or 3+ args)
  # and silences SC2015 on every ShellCheck version.
  if ! { [ $# -ge 1 ] && [ $# -le 2 ]; }; then
    usage
    fail "expected 1 or 2 arguments, got $#." "$EX_REFUSED"
  fi
  target="$1"
  source_rev="${2-}"

  say "── lemondrop deploy ──────────────────────────────────────"
  say "  target       : $target"
  say "  app dir      : $LEMDROP_APP_DIR"
  say "  record       : $LEMDROP_RECORD_FILE"
  say "  compose proj : $LEMDROP_COMPOSE_PROJECT"
  say ""

  # ── 1. LOCK ────────────────────────────────────────────────────────────────
  mkdir -p "$LEMDROP_STATE_DIR" || fail "cannot create $LEMDROP_STATE_DIR"
  acquire_lock || exit "$EX_LOCKED"

  # ── 2. VALIDATE ────────────────────────────────────────────────────────────
  # Before the lock would have been defensible too; after it, because a retry
  # storm of malformed invocations should not queue behind a real deploy.
  if ! validate_image_digest "$target"; then
    fail "refusing to deploy '$target'. See the reasons above." "$EX_REFUSED"
  fi
  [ -d "$LEMDROP_APP_DIR" ] || fail "$LEMDROP_APP_DIR does not exist. Is this the application host?" "$EX_REFUSED"
  [ -f "$LEMDROP_APP_DIR/.env" ] || fail "$LEMDROP_APP_DIR/.env does not exist. Has boot.sh run on this host?" "$EX_REFUSED"
  [ -f "$LEMDROP_APP_DIR/docker-compose.yml" ] || fail "$LEMDROP_APP_DIR is not a compose checkout." "$EX_REFUSED"

  # ── GUARD: refuse a redundant deploy before anything is mutated ──────────────
  # If the target digest is already the record's IMAGE_DIGEST, this deploy would
  # write itself back as PREVIOUS_IMAGE_DIGEST (deploy.sh:969), making the record
  # self-referential: rollback.sh would then restore the image that is already
  # running and blank PREVIOUS_*, erasing the last record-level reference to what
  # ran before (docs/deployment.md §4.2.1). Refuse here, before capture_state
  # touches the record, before any tag, before any .env write. Nothing on this
  # host is changed: nothing is tagged, pulled, restarted, or written.
  if [ -f "$LEMDROP_RECORD_FILE" ] && record_is_valid "$LEMDROP_RECORD_FILE"; then
    recorded="$(record_get IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"
    if [ -n "$recorded" ] && [ "$recorded" = "$target" ]; then
      say ""
      say "══════════════════════════════════════════════════════════════════════════════"
      say "REDUNDANT DEPLOY — REFUSING"
      say "  target        : $target"
      say "  IMAGE_DIGEST  : $recorded  (in $LEMDROP_RECORD_FILE)"
      say ""
      say "  The digest you asked to deploy is already the recorded deployment — the"
      say "  image that is running on this host."
      say ""
      say "  Deploying it would write itself back as PREVIOUS_IMAGE_DIGEST, so"
      say "  scripts/rollback.sh would restore the image already running and then"
      say "  blank PREVIOUS_*, erasing the last record-level reference to what was"
      say "  running before. Nothing has been changed: nothing is tagged, pulled,"
      say "  restarted, or written."
      say ""
      say "  Use scripts/verify-deployment.sh instead. It reports AGREE exactly"
      say "  when the running image is the one the record names — which is this"
      say "  state — and tells you whether a redeploy is meaningful at all."
      say "══════════════════════════════════════════════════════════════════════════════"
      exit "$EX_REFUSED"
    fi
  fi

  # ── 3 & 4. CAPTURE, THEN TAG ───────────────────────────────────────────────
  capture_state
  trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR

  # ── 5. IS THE DIGEST OBTAINABLE ────────────────────────────────────────────
  # Before the pull, and before anything is switched. A manifest inspect costs
  # one small registry request and answers the only question that matters here:
  # does this exact digest exist? A typo'd digest discovered after the old
  # container is gone is a self-inflicted outage; discovered now it is a message.
  say ""
  say "checking the registry for $target …"
  if ! docker manifest inspect "$target" >/dev/null 2>&1; then
    say "REFUSING: the registry did not return a manifest for $target."
    say "  Either the digest is wrong, or the image is not anonymously pullable."
    say "  Nothing has been pulled and nothing has been changed."
    exit "$EX_REFUSED"
  fi
  say "  manifest found."

  # ── 6. SCHEMA GATE (FIRST PASS — WHAT CAN BE KNOWN WITHOUT THE IMAGE) ─────
  # Before the pull on purpose. The gate needs no image and no network — only the
  # source tree — so running it here refuses a schema-incompatible deploy
  # without spending a download on an artifact nobody is going to run.
  #
  # AND NOW, HONESTLY: "no image" no longer means "no answer".
  # org.opencontainers.image.revision and org.lemondrop.alembic-head carry both
  # facts on any image published by a release run with labels, and reading them
  # requires the image to be present locally — a registry manifest does not
  # carry image-config labels, and fetching the config blob by hand would need a
  # registry credential these scripts must not acquire. So:
  #
  #   * an operator-supplied revision  -> the tree is readable NOW, so the gate
  #     runs NOW and a mismatch costs nothing but this message;
  #   * no operator-supplied revision -> the image may still be able to answer,
  #     so nothing is refused yet. The authoritative gate runs after the pull
  #     and before anything is switched. The only thing spent is the download.
  #
  # What is NOT lost in the second case: the gate still runs before .env is
  # touched and before a single container is recreated, so a refused deploy has
  # still changed nothing but the local image cache.
  #
  # The gate runs in both cases, and in the first case it runs TWICE — once
  # here and once after the pull, against the label if there is one. That is
  # strictly more work and never less checking, which is the only direction a
  # fail-closed gate is allowed to move in.
  say ""
  if [ -n "$source_rev" ]; then
    say "reading the alembic head at $source_rev …"
    local pre_head pre_out
    # The reason is captured, not dropped, and a failure here is not a refusal:
    # this first pass is an OPTIMISATION — it saves a download by refusing
    # early — and the decision belongs to the authoritative gate after the pull,
    # which prefers the image's own label. A `--depth 1` checkout cannot answer
    # for an older revision, and refusing there fails every labelled deploy on a
    # host configured exactly as documented. So: name why the check is being
    # skipped, and let the authoritative gate decide on the image.
    # stderr is NOT suppressed — that is where the reason lives. On success it
    # is empty, so merging it into the capture costs nothing.
    if pre_out="$(alembic_head_at_revision "$source_rev" 2>&1)" \
       && [ -n "$pre_out" ]; then
      pre_head="$pre_out"
      say "  head from the source tree: $pre_head"
      schema_gate "$source_rev" "$pre_head" || exit "$EX_REFUSED"
    else
      say "  the source tree could not answer for $source_rev:"
      if [ -n "$pre_out" ]; then
        printf '%s\n' "$pre_out" | sed 's/^/    /'
      fi
      say ""
      say "  Skipping the pre-pull schema gate. It is an early check, not the"
      say "  decision: it only saves the download by refusing sooner. Nothing"
      say "  has been pulled, switched or written."
      say ""
      say "  The deploy continues to the pull, and the AUTHORITATIVE schema gate"
      say "  runs after it, before anything is switched, on the head read from"
      say "  the image's own org.lemondrop.alembic-head label. That gate is"
      say "  unchanged and still fails closed: no record, no recorded head, or"
      say "  a head that is not the recorded one all refuse this deploy, with"
      say "  no override."
    fi
  else
    say "no source revision given."
    say "  That used to be a refusal: the published image carried no revision"
    say "  label, so the schema head could only be read from a named source"
    say "  tree. Images built by a release run now carry both facts as OCI"
    say "  labels, and the image itself is the better source — but a label is"
    say "  read off the image, and the image is not here yet."
    say ""
    say "  So the digest is checked against the registry, pulled, and the two"
    say "  facts are read from the image. Nothing is switched, restarted or"
    say "  written until after the schema gate has run on what the image says."
    say ""
    say "  If that image turns out to predate label support, this deploy will"
    say "  refuse and ask for the revision explicitly."
  fi

  # ── 7. PULL ────────────────────────────────────────────────────────────────
  say ""
  say "pulling $target …"
  docker pull "$target" || fail "docker pull failed for $target"

  # Prove the pulled image is the one that was asked for. `docker pull` on a
  # digest reference is not supposed to be able to deliver anything else, but a
  # deployment that trusts that without looking is a deployment whose central
  # guarantee is an assumption. Checked against RepoDigests, not against a name.
  local pulled_id pulled_digest
  pulled_id="$(docker image inspect -f '{{.Id}}' "$target" 2>/dev/null || true)"
  pulled_digest="$(image_repo_digests "$target" | head -n 1)"
  if [ -n "$pulled_digest" ] && [ "$pulled_digest" != "$target" ]; then
    say "NOTE: the image also answers to $pulled_digest"
    say "      (a registry can list an index and a platform manifest separately)."
    say "      Continuing: the requested reference is what was asked for."
  fi
  say "  pulled image id: ${pulled_id:-unknown}"

  # ── 6b. THE TWO FACTS, ESTABLISHED FROM THE IMAGE ──────────────────────────
  # The image is here now, so it can be asked. Two questions, asked separately,
  # answered by separate sources, and never derived from one another:
  #
  #   PROVENANCE  which commit's tree is this image?      -> org.opencontainers.image.revision
  #   SCHEMA      which alembic head does its code need?  -> org.lemondrop.alembic-head
  #
  # `resolve_deploy_facts` prefers the labels, falls back to the argument this
  # script was given, REFUSES when the two disagree about provenance, and
  # refuses when the image's schema label contradicts the source tree at the
  # revision it names. See scripts/lib/deploy-lib.sh for why each of those is a
  # refusal rather than a warning.
  #
  # WHY THIS IS STILL BEFORE ANYTHING IS SWITCHED. Everything above this line
  # downloaded bytes into a local image cache. The .env is untouched, no
  # container has been recreated, and the record has not been written. A refusal
  # here is therefore free, which is the whole reason it belongs here rather
  # than after `compose up`.
  say ""
  say "establishing what this image is, from the image itself …"
  if ! resolve_deploy_facts "$target" "$source_rev"; then
    say ""
    say "Nothing has been switched. The previous deployment is untouched."
    exit "$EX_REFUSED"
  fi
  say "  source revision : $DEPLOY_SOURCE_REVISION  (from: $DEPLOY_REVISION_SOURCE)"
  say "  alembic head    : $DEPLOY_ALEMBIC_HEAD  (from: $DEPLOY_HEAD_SOURCE)"

  # ── 6c. SCHEMA GATE (AUTHORITATIVE) ─────────────────────────────────────────
  # The same fail-closed gate as the first pass, run against the target head
  # that will actually be recorded. Unchanged in substance: equal heads proceed,
  # different heads refuse, and there is no flag. What changed is only which
  # number is being compared, and that the number can now come from the image
  # instead of from a human's memory.
  say ""
  schema_gate "$DEPLOY_SOURCE_REVISION" "$DEPLOY_ALEMBIC_HEAD" || exit "$EX_REFUSED"
  local target_head="$DEPLOY_ALEMBIC_HEAD"
  # `source_rev` is REPLACED, not shadowed. From here on it means "the revision
  # this image is from", which is not necessarily the string that was typed on
  # the command line — and everything below (the record, the summary) must name
  # the revision that was actually established, not the one that was offered.
  # What the operator typed has already been printed by the fallback warning
  # above, in the box that explains it.
  source_rev="$DEPLOY_SOURCE_REVISION"

  # ── 8. SWITCH ──────────────────────────────────────────────────────────────
  # `.env` first, then the service. The reverse order would recreate the api
  # against the OLD API_IMAGE, i.e. restart the old image for no reason, and
  # then change the pin without ever having run it.
  say ""
  say "writing API_IMAGE into $LEMDROP_APP_DIR/.env …"
  env_set "$LEMDROP_APP_DIR/.env" API_IMAGE "$target" \
    || fail "could not write API_IMAGE into .env (backup: $PREV_ENV_BACKUP)"

  say "recreating ONLY the api service …"
  # --no-build : MANDATORY. Without it compose rebuilds from ./api and the whole
  #             strategy silently reverts to today's defect — deploying a locally
  #             built image while the record claims a digest that was tested.
  # --no-deps  : the embedder and reranker keep running with their models warm.
  #             Recreating them would re-load ~410MB of GGUF on a t3.micro for
  #             no reason, and boot.sh:248-250 records how little headroom there is.
  # --force-recreate : the api must be REPLACED, not left alone because its
  #             configuration appears unchanged to compose.
  compose up -d --no-build --no-deps --force-recreate api \
    || fail "docker compose could not recreate the api service"

  # ── 9. VERIFY BEFORE ACCEPTING ─────────────────────────────────────────────
  say ""
  say "verifying the new deployment …"
  if ! verify_stack; then
    say ""
    say "VERIFICATION FAILED. Restoring the previous deployment."
    fail "the new image did not pass verification; it is not being left in place."
  fi

  # ── 10. RECORD ─────────────────────────────────────────────────────────────
  # Only now. A record written before verification is a record of a deployment
  # that might not work, and the next deploy would use its head as a baseline —
  # so an unverified deploy that poisoned the record would refuse every later
  # one. Recording last is what makes the record trustworthy.
  local prev_digest="" prev_rev="" prev_head=""
  if [ -f "$LEMDROP_RECORD_FILE" ] && record_is_valid "$LEMDROP_RECORD_FILE"; then
    prev_digest="$(record_get IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"
    prev_rev="$(record_get REVISION "$LEMDROP_RECORD_FILE")"
    prev_head="$(record_get ALEMBIC_HEAD "$LEMDROP_RECORD_FILE")"
  fi

  local rollback_tag=""
  if [ -n "$PREV_IMAGE_ID" ]; then
    # Name the rollback tag of what is running NOW, so a later rollback has a
    # reference even when the previous record carried no digest (the M3 case).
    rollback_tag="lemondrop-api:rollback-$(date -u +%Y%m%dT%H%M%SZ)"
    docker tag "$PREV_IMAGE_ID" "$rollback_tag" 2>/dev/null || rollback_tag="$PREV_ROLLBACK_TAG"
  fi

    # BELT AND BRACES: the redundant-deploy guard above (before capture_state)
    # makes this unreachable, but state the invariant at the write site so a
    # future edit cannot silently reintroduce a self-referential record.
    if [ -n "$prev_digest" ] && [ "$prev_digest" = "$target" ]; then
      say ""
      say "REFUSING: PREVIOUS_IMAGE_DIGEST would equal IMAGE_DIGEST ($target)."
      say "  The record would become self-referential and scripts/rollback.sh could"
      say "  no longer reach what ran before. Nothing has been changed."
      say ""
      say "  The deployment is live and verified but UNRECORDED: record what is"
      say "  running now, by hand, from the values printed above."
      exit "$EX_REFUSED"
    fi

    write_record "$LEMDROP_RECORD_FILE" \
      "RECORD_VERSION=1" \
      "REVISION=${source_rev}" \
      "SOURCE_REVISION=${source_rev}" \
      "IMAGE_DIGEST=${target}" \
      "ALEMBIC_HEAD=${target_head}" \
      "DEPLOYED_AT_UTC=$(date -u +%FT%TZ)" \
      "DEPLOYED_BY=${SUDO_USER:-${USER:-unknown}}" \
      "VERIFICATION=PASS" \
      "VERIFIED_AT_UTC=$(date -u +%FT%TZ)" \
      "ROLLBACK_TAG=${rollback_tag}" \
      "PREVIOUS_REVISION=${prev_rev}" \
      "PREVIOUS_IMAGE_DIGEST=${prev_digest}" \
      "PREVIOUS_ALEMBIC_HEAD=${prev_head}" \
    || fail "verification passed but the record could not be written at $LEMDROP_RECORD_FILE.
        THE DEPLOYMENT IS LIVE AND UNRECORDED: the image is the one that was asked for and it
        has passed verification, so the service is correct. What is missing is the written
        rollback point. Do NOT re-run this deploy to fix it — instead record what is running
        now, by hand, from the values printed above, or re-run deploy.sh with the same
        arguments once the directory is writable. Until then, scripts/rollback.sh will refuse."

  say ""
  say "──────────────────────── DEPLOYED ──────────────────────────"
  say "  revision      : $source_rev  (from: $DEPLOY_REVISION_SOURCE)"
  say "  digest        : $target"
  say "  alembic head  : $target_head  (from: $DEPLOY_HEAD_SOURCE)"
  say "  rollback tag  : ${rollback_tag:-<none — nothing was running before>}"
  say "  previous      : ${prev_digest:-<none recorded>}"
  say "  record        : $LEMDROP_RECORD_FILE"
  say ""
  say "  Verify at any time with: scripts/verify-deployment.sh"
  say "  Undo with:               scripts/rollback.sh"
  say "─────────────────────────────────────────────────────────────"
  return 0
}

# ═════════════════════════════════════════════════════════════════════════════
# DELIVERY TO EC2 — DESCRIBED HERE, NOT IMPLEMENTED HERE
# ═════════════════════════════════════════════════════════════════════════════
#
# These scripts are IN this repository, and the running host's checkout PREDATES
# them. That is the whole problem: `scripts/boot.sh` does `git clone --depth 1`
# of whatever `main` is at boot time, so a host that last booted before this
# commit has no `scripts/deploy.sh` to run, and no amount of care in this file
# changes that.
#
# Getting them onto such a host is a SEPARATE, APPROVED operation, and
# deliberately not written here. Three properties of that operation, recorded
# so the choice is a decision rather than an accident:
#
# 1. `git -C /opt/lemondrop pull --ff-only` is sufficient and is the cheapest
#    thing that can work — these files are tracked source, so the ordinary
#    source-update path already carries them. It is what `boot.sh` step 3
#    already does on every boot.
#    It is NOT always available: boot.sh step 3 stops with a named error if
#    /opt/lemondrop is not a checkout, and a `--depth 1` clone has no history to
#    fast-forward within until it fetches. So the fallback is an explicit
#    transfer of the four files, which is a file-copy operation over whatever
#    transport the operator is already using, and nothing more.
#
# 2. THE CHECKOUT MUST NOT BE THE PLACE THE RECORD LIVES, and this is the
#    single most important property of the design. `LEMDROP_STATE_DIR` defaults
#    to /var/lib/lemondrop, outside the repository, for reasons given in
#    scripts/lib/deploy-lib.sh. If the record were written inside /opt/lemondrop
#    then every deploy would leave an untracked file in the working tree, `git
#    status` would be dirty after every deploy, a `git clean -fdx` or the next
#    fresh clone would delete the only record of what is running, and this
#    repository's `state-leak` hygiene gate would exist precisely to object to
#    it. Nothing in the deploy path writes inside the checkout.
#
# 3. THE DIGEST PIN IN `.env` IS NOT DURABLE ACROSS A BOOT, and pretending
#    otherwise would be the most damaging claim this file could make.
#    `boot.sh` step 4 is `cp .env.example .env` — unconditional, every boot, on
#    purpose, because `.env` is machine-owned and must agree with
#    `local.app_port`. Whatever deploy.sh wrote there is discarded. The stack
#    comes back up, healthy, on M3 behaviour.
#    So the pin survives as: (a) the record in /var/lib/lemondrop, which boot
#    cannot touch; and (b) `scripts/verify-deployment.sh`, whose DIVERGENCE
#    check is what turns "a reboot quietly reverted us" from an invisible event
#    into a reported one. That second half is the whole reason the divergence
#    check exists and the reason this comment is here.
#
# 4. THE FOUR FILES ARE ONE UNIT WHEN THE RECORD FORMAT CHANGES, and this
#    version is such a change. `--adopt-current` now writes an `IMAGE_ID` key
#    on records that carry no digest (see the note on that key in deploy-lib.sh).
#    The key is deliberately NOT in the required-key tier, so every record that
#    predates it still validates — but a record that CONTAINS it is refused by a
#    reader whose `RECORD_KEYS_RE` predates it: the old `verify-deployment.sh`
#    reports the record as MALFORMED and the old `rollback.sh` refuses outright.
#    Measured, not assumed (see the harness case X1).
#    So: deliver `deploy.sh`, `verify-deployment.sh`, `rollback.sh` AND
#    `lib/deploy-lib.sh` together, in one operation, on every host. A partial
#    delivery is worse than a late one.
#
# NOT WRITTEN HERE, ON PURPOSE: any SSM transport, any `aws ssm send-command`
# wrapper, any CI job. Deploying this code to a host, and running it there, are
# two different operations with two different approvals, and collapsing them
# means the approval for one silently becomes the approval for the other.

main "$@"
