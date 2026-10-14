#!/usr/bin/env bash
#
# lemondrop — report what this host is running. (M4 Stage 5)
#
#   sudo ./scripts/verify-deployment.sh
#
# ── THIS IS THE SECOND ENGINEER'S FIRST COMMAND ───────────────────────────────
# Not a deployment tool. It deploys nothing, changes nothing and writes nothing,
# and it is safe to run on a host that is on fire, on a host mid-deploy, or on
# a host that has never been deployed to at all. Everything else in this
# milestone assumes somebody already knows the answer to "what is running?",
# and this is what produces that answer.
#
# ── IT MUTATES NOTHING. THAT IS THE POINT. ────────────────────────────────────
# No lock file is created — `verify-deployment.sh` deliberately does NOT take the
# deployment lock, even a shared one, because opening a lock file for writing
# creates it, and a read-only tool that creates files in /var/lock is not
# read-only. It can therefore observe a deploy in progress, which is a state an
# operator genuinely needs to be able to look at, and it reports that state for
# what it is rather than waiting for it or being blocked by it.
# No log file is written. No record is written or touched. No container is
# started, stopped or recreated.
#
# ── WHAT IT REPORTS, AND WHY EACH LINE IS THERE ───────────────────────────────
# The record and the running image are reported SEPARATELY and compared at the
# end, because the interesting fact is usually not either one — it is whether
# they agree. The case this exists for:
#
#   scripts/boot.sh step 4 is `cp .env.example .env`, run on EVERY boot. A
#   deploy's digest pin lives in that file. So a reboot silently returns
#   production to a host-built image while the record still names the digest
#   that was deployed. Nothing is corrupted, no error is raised anywhere, and
#   the stack is healthy — it is simply not running what the record says it is.
#   The DIVERGENCE line below is the only thing that makes that visible.

set -Eeuo pipefail

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
# shellcheck source=scripts/lib/deploy-lib.sh
. "$_LIB_DIR/deploy-lib.sh"

PROBLEMS=0
note_problem() { PROBLEMS=$((PROBLEMS + 1)); say "  !! $*"; }

say "═══════════ lemondrop — what is this host running? ═══════════"
say "  app dir : $LEMDROP_APP_DIR"
say "  record  : $LEMDROP_RECORD_FILE"
say ""

# ── 1. THE RECORD ─────────────────────────────────────────────────────────────
say "── revision record ───────────────────────────────────────────"
RECORD_OK=0
if record_is_valid "$LEMDROP_RECORD_FILE"; then
  RECORD_OK=1
  for k in REVISION IMAGE_DIGEST ALEMBIC_HEAD DEPLOYED_AT_UTC DEPLOYED_BY \
           VERIFICATION VERIFIED_AT_UTC ROLLBACK_TAG \
           PREVIOUS_REVISION PREVIOUS_IMAGE_DIGEST PREVIOUS_ALEMBIC_HEAD; do
    say "  $(printf '%-22s' "$k"): $(record_get "$k" "$LEMDROP_RECORD_FILE")"
  done
  say ""
else
  say "  NO USABLE RECORD at $LEMDROP_RECORD_FILE."
  say "  This host has never been deployed to by scripts/deploy.sh, or the"
  say "  record was damaged. Everything below is measured from the running"
  say "  system alone, so it describes what IS running but not what was"
  say "  intended — and scripts/rollback.sh would refuse to run."
  note_problem "no usable revision record. 'what is running' and 'what should be running' cannot be compared, and scripts/rollback.sh would refuse."
fi
say ""

# ── 2. THE RUNNING IMAGE ──────────────────────────────────────────────────────
say "── running api ───────────────────────────────────────────────"
CID="$(api_container_id || true)"
RUNNING_IMAGE_ID=""
RUNNING_DIGESTS=""

if [ -z "$CID" ]; then
  say "  NO api container is running for project '$LEMDROP_COMPOSE_PROJECT'."
  note_problem "no api container is running"
else
  say "  container    : $CID"
  RUNNING_IMAGE_ID="$(running_image_id "$CID" || true)"
  say "  image id     : ${RUNNING_IMAGE_ID:-<could not read>}"
  RUNNING_DIGESTS="$(image_repo_digests "$RUNNING_IMAGE_ID" || true)"
  if [ -n "$RUNNING_DIGESTS" ]; then
    say "  digest(s)    :"
    printf '%s\n' "$RUNNING_DIGESTS" | sed 's/^/                 /'
  else
    say "  digest(s)    : none — this image was built on this host and was"
    say "                 never pulled from or pushed to a registry. That is"
    say "                 the M3 behaviour, and it means it has no registry"
    say "                 reference to roll back to."
  fi
  say ""
  say "  what .env pins:"
  say "    API_IMAGE  : $(env_get API_IMAGE "$LEMDROP_APP_DIR/.env" || true)"
  if [ -z "$(env_get API_IMAGE "$LEMDROP_APP_DIR/.env" || true)" ]; then
    say "                 <absent> — compose is using its default. If the default"
    say "                 is a digest and the running image has no RepoDigests,"
    say "                 the image on this host did not come from the registry."
  fi
  say ""
  # ── THE IMAGE'S OWN ACCOUNT OF ITSELF ───────────────────────────────────────
  # A third source, independent of both the record and this host's filesystem:
  # what the image says it is. `org.opencontainers.image.revision` is
  # provenance; `org.lemondrop.alembic-head` is schema. They are compared
  # against the record separately below, and neither is ever used to infer the
  # other — a commit sha is not an alembic revision and a tool that treated it
  # as one would report agreement on most images and lie on exactly the ones
  # that matter.
  RUNNING_LABEL_REVISION=""
  RUNNING_LABEL_ALEMBIC_HEAD=""
  if [ -n "$RUNNING_IMAGE_ID" ]; then
    RUNNING_LABEL_REVISION="$(image_source_revision "$RUNNING_IMAGE_ID" || true)"
    RUNNING_LABEL_ALEMBIC_HEAD="$(image_alembic_head "$RUNNING_IMAGE_ID" || true)"
    say "  labels on the image:"
    if [ -n "$RUNNING_LABEL_REVISION" ] || [ -n "$RUNNING_LABEL_ALEMBIC_HEAD" ]; then
      say "    revision     : ${RUNNING_LABEL_REVISION:-<absent>}"
      say "    alembic head : ${RUNNING_LABEL_ALEMBIC_HEAD:-<absent>}"
    else
      say "    <none> — this image was published before the release workflow"
      say "    stamped OCI labels (build-push-action set none), so it cannot say"
      say "    which commit it came from or which schema it expects. Deploys of"
      say "    such an image fall back to an operator-supplied revision; see"
      say "    scripts/lib/deploy-lib.sh:resolve_deploy_facts."
    fi
  fi
  say ""
  say "  workers (must NOT change during an api deploy or rollback):"
  compose ps embedder reranker 2>/dev/null | sed 's/^/    /' || say "    (could not read)"
fi
say ""

# ── 3. RECORD vs RUNNING ──────────────────────────────────────────────────────
say "── do they agree? ────────────────────────────────────────────"
if [ "$RECORD_OK" -eq 1 ] && [ -n "$RUNNING_IMAGE_ID" ]; then
  RECORDED_DIGEST="$(record_get IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"
  if [ -n "$RECORDED_DIGEST" ] && printf '%s\n' "$RUNNING_DIGESTS" | grep -qxF "$RECORDED_DIGEST" 2>/dev/null; then
    say "  AGREE — the running image IS the one the record names."
  else
    say "  DIVERGENCE — the record and the running image do not match."
    say "    record  : $RECORDED_DIGEST"
    say "    running : $(printf '%s' "$RUNNING_DIGESTS" | tr '\n' ' ')"
    say ""
    say "    Usual causes, most likely first:"
    say "      1. This host was REBOOTED. scripts/boot.sh step 4 copies"
    say "         .env.example over .env on every boot, which discards the"
    say "         digest a deploy wrote there, so the api came back up as a"
    say "         local build instead of the deployed image."
    say "      2. Something deployed or restarted the api without going"
    say "         through scripts/deploy.sh."
    say "      3. The record was written on a different host, or restored from"
    say "         a backup of another host's."
    say ""
    say "    Do not assume the cause. Read scripts/deploy.sh's log"
    say "    (/var/log/lemondrop-deploy.log) and compare with the boot log"
    say "    (/var/log/lemondrop-boot.log) before deciding."
    say ""
    say "    If it is (1), re-deploy to restore the pin:"
    say "      scripts/deploy.sh <digest> <source-revision>"
    note_problem "record and running image disagree"
  fi

  # ── THE TWO FACTS, CHECKED SEPARATELY ───────────────────────────────────────
  # Only meaningful once the digest check above has passed, or when there is no
  # record to compare against at all — both are fine, because each comparison
  # is guarded on having both sides.
  #
  # Two comparisons, never one. PROVENANCE is "does the record name the commit
  # the running image says it was built from?". SCHEMA is "does the record's
  # baseline head match the schema the running image says it expects?". A tool
  # that collapsed them into one comparison would report most healthy hosts as
  # agreeing, because on most hosts both happen to be right together.
  if [ -n "$RUNNING_IMAGE_ID" ]; then
    say ""
    if [ -n "$RUNNING_LABEL_REVISION" ]; then
      if [ "$RECORD_OK" -ne 1 ]; then
        say "  PROVENANCE: the running image was built from ${RUNNING_LABEL_REVISION},"
        say "              and there is no record saying anything else."
      else
        RECORDED_REVISION="$(record_get REVISION "$LEMDROP_RECORD_FILE")"
        if [ -z "$RECORDED_REVISION" ]; then
          say "  PROVENANCE: the running image reports revision"
          say "              ${RUNNING_LABEL_REVISION}, but the record carries none."
        elif revisions_agree "$RECORDED_REVISION" "$RUNNING_LABEL_REVISION"; then
          say "  PROVENANCE AGREE — record and image both name ${RECORDED_REVISION}."
        else
          say "  PROVENANCE DISAGREE — the record and the running image name"
          say "              different commits:"
          say "                record : ${RECORDED_REVISION}"
          say "                image  : ${RUNNING_LABEL_REVISION}"
          say "              The image is authoritative about what is IN it. The record"
          say "              is authoritative about what was DEPLOYED. If the running"
          say "              image is not the one the record describes, this host is"
          say "              not running what the record says it is."
          note_problem "the record's revision and the running image's revision label disagree"
        fi
      fi
    fi

    if [ -n "$RUNNING_LABEL_ALEMBIC_HEAD" ]; then
      if [ "$RECORD_OK" -ne 1 ]; then
        say ""
        say "  SCHEMA: the running image expects alembic head"
        say "          ${RUNNING_LABEL_ALEMBIC_HEAD}, and there is no recorded baseline"
        say "          to compare it against."
      else
        RECORDED_HEAD="$(record_get ALEMBIC_HEAD "$LEMDROP_RECORD_FILE")"
        say ""
        if [ -z "$RECORDED_HEAD" ]; then
          say "  SCHEMA: the running image expects alembic head"
          say "          ${RUNNING_LABEL_ALEMBIC_HEAD}, but the record carries no baseline"
          say "          head. scripts/deploy.sh will refuse every deploy until one is"
          say "          established with: scripts/deploy.sh --adopt-current"
        elif [ "$RECORDED_HEAD" = "$RUNNING_LABEL_ALEMBIC_HEAD" ]; then
          say "  SCHEMA AGREE — the recorded baseline head and the running image's"
          say "          expected head are both ${RECORDED_HEAD}."
        else
          say "  SCHEMA DISAGREE — the running image expects alembic head"
          say "          ${RUNNING_LABEL_ALEMBIC_HEAD}, but the record's baseline head is"
          say "          ${RECORDED_HEAD}."
          say "          The image is the deployed code, so this is the one that matters"
          say "          for whether the api can read its own table. scripts/deploy.sh"
          say "          fails closed on exactly this comparison, so the next deploy"
          say "          will refuse."
          note_problem "the record's alembic head and the running image's schema label disagree"
        fi
      fi
    fi
  fi
elif [ "$RECORD_OK" -eq 1 ]; then
  say "  Cannot compare: no api container is running to compare the record against."
else
  # Silence here would read as "they agree". With no record there is nothing to
  # agree with, and saying nothing is the one thing this report must not do.
  say "  Cannot compare: there is no record. 'what is running' is reported above;"
  say "  'what should be running' is unknown, so the two cannot be checked against"
  say "  each other. An empty section here is NOT a clean bill of health."
fi
say ""

# ── 4. IS IT SERVING? ─────────────────────────────────────────────────────────
# Both halves, and both reported. A half-answer here is worse than none, because
# "healthy" is the word people stop reading at.
say "── is it serving? ───────────────────────────────────────────"
say "  base url: $(api_base_url)"
assert_probe_is_grounded || note_problem "the known-good search probe could not be grounded in $LEMDROP_CORPUS_FILE"
wait_for_ready "$LEMDROP_READY_TIMEOUT" || note_problem "the api did not become ready"
known_good_search || note_problem "the known-good search did not pass"
say ""

# ── 5. VERDICT ────────────────────────────────────────────────────────────────
say "──────────────────────────────────────────────────────────────"
if [ "$PROBLEMS" -eq 0 ]; then
  say "VERDICT: everything above is consistent. Nothing to do."
  exit "$EX_OK"
fi
say "VERDICT: ${PROBLEMS} problem(s), each marked !! above. This script reports;"
say "it does not fix. scripts/deploy.sh and scripts/rollback.sh are the tools"
say "that change anything, and both refuse rather than guess."
exit "$EX_FAILED"
