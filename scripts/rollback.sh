#!/usr/bin/env bash
#
# lemondrop — return this host to the previously recorded deployment. (M4 Stage 5)
#
#   sudo ./scripts/rollback.sh
#
# ── SYMMETRIC WITH deploy.sh, AND INDEPENDENTLY USABLE ────────────────────────
# It reads the same record `deploy.sh` writes, restores the same two things —
# the IMAGE and `.env` — and re-verifies with the same checks. It does not need
# `deploy.sh` to have run in this process, this shell, or this boot. That matters
# because the moment a rollback is needed is precisely the moment the person
# running it should not have to reconstruct how the deploy path works.
#
# ── IT NEVER DELETES THE RECORD ───────────────────────────────────────────────
# Not on success, not on failure, not when it refuses. The record is the only
# thing that makes "what is running?" answerable, and a rollback that consumed
# it would mean a second rollback has nothing to work from. It is rewritten only
# to describe what is now running, and even that is done atomically at the very
# end, after verification.
#
# ── WHY THE LEGACY M3 CASE NEEDS ITS OWN PATH ────────────────────────────────
# A host that was last deployed by M3 behaviour has a record with no digest in
# it: nothing was digest-addressed, and the running image was built on the host.
# There is no registry reference to go back to. What there IS is the rollback
# tag `deploy.sh` took of the running image before it changed anything — an
# immutable local name pointing at exact bytes. So the legacy path restores the
# TAG, not a digest, and re-tags it back to `lemondrop-api` so that compose's
# default resolves to it.
#
# ── WHEN TO USE THIS, DECIDED IN ADVANCE ──────────────────────────────────────
# docs/m4-plan.md §4.4 item 4, restated here because a decision made mid-incident
# is how bad calls get made:
#
#   /health or /search fails within the wait  -> rollback. No judgement call.
#   /health fine but /search wrong             -> rollback, then investigate.
#   a latency regression, results still right  -> INVESTIGATE FIRST. Do not roll back a
#                                                  correct deployment over performance.
#   a migration was applied out of band       -> do not roll the API back on its own
#                                                  unless that migration is known to be
#                                                  backward compatible. Check the head
#                                                  recorded below before you start.

set -Eeuo pipefail

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
# shellcheck source=scripts/lib/deploy-lib.sh
. "$_LIB_DIR/deploy-lib.sh"

usage() {
  cat <<'EOF'
Usage: rollback.sh

Returns this host to the deployment recorded as PREVIOUS_* in
/var/lib/lemondrop/deployed-revision.env — restoring the image AND .env — then
re-verifies readiness and the known-good search. Recreates only the `api`
service; the embedder, the reranker, their models and the database are not
touched. Takes no arguments: a rollback target is chosen by the record, not by
whoever is holding the incident.

Refuses on a missing or malformed record. Never deletes the record.
EOF
}

main() {
  case "${1-}" in
    -h|--help) usage; exit "$EX_OK" ;;
    "") : ;;
    *) usage; die "rollback takes no arguments (got '$1'). The target comes from the record." "$EX_REFUSED" ;;
  esac

  say "── lemondrop rollback ───────────────────────────────────"
  say "  app dir : $LEMDROP_APP_DIR"
  say "  record  : $LEMDROP_RECORD_FILE"
  say ""

  mkdir -p "$LEMDROP_STATE_DIR" 2>/dev/null || true
  acquire_lock || exit "$EX_LOCKED"

  # ── THE RECORD IS THE ONLY SOURCE OF THE TARGET ────────────────────────────
  #
  # A missing or malformed record is a REFUSAL, not a fallback. The obvious
  # "helpful" alternative — carry on and restart whatever is currently tagged —
  # is what makes a rollback into a coin flip, and this script exists to remove
  # judgement calls from the worst ten minutes of someone's week.
  #
  # The malformed case is specifically about PARTIAL records. A write truncated
  # by a full disk or a power cut can leave a file that still has RECORD_VERSION
  # and IMAGE_DIGEST while the rest is gone — and PREVIOUS_IMAGE_DIGEST is
  # exactly the field that decides where this goes. Reading the fields that
  # survived and acting on them would restore nothing and report success.
  # `record_is_valid` refuses the whole file instead, and it distinguishes
  # "this key is empty" (legal: a first deployment, or one already rolled back)
  # from "this key is not there at all" (only a damaged or foreign file).
  #
  # LIMIT, stated rather than implied: a truncation that lands exactly on a line
  # boundary and removes only OPTIONAL fields would not be caught by shape
  # alone. Every key write_record emits is required to be present for exactly
  # that reason; what remains uncovered is a truncation so early that
  # DEPLOYED_AT_UTC itself is gone, which the required-key check does catch.
  if ! record_is_valid "$LEMDROP_RECORD_FILE"; then
    say ""
    say "REFUSING: no usable revision record."
    say "  Without it there is no defined rollback target. Restarting whatever"
    say "  happens to be tagged is not a rollback, it is a coin flip."
    say ""
    say "  If you know what to run, do it explicitly and by digest:"
    say "    cd $LEMDROP_APP_DIR"
    say "    API_IMAGE=<registry>/<repo>@sha256:<64-hex> \\"
    say "      docker compose up -d --no-build --no-deps --force-recreate api"
    say ""
    say "  Nothing has been changed."
    exit "$EX_REFUSED"
  fi

  local cur_rev cur_digest cur_head
  cur_rev="$(record_get REVISION "$LEMDROP_RECORD_FILE")"
  cur_digest="$(record_get IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"
  cur_head="$(record_get ALEMBIC_HEAD "$LEMDROP_RECORD_FILE")"

  local prev_rev prev_digest prev_head rollback_tag
  prev_rev="$(record_get PREVIOUS_REVISION "$LEMDROP_RECORD_FILE")"
  prev_digest="$(record_get PREVIOUS_IMAGE_DIGEST "$LEMDROP_RECORD_FILE")"
  prev_head="$(record_get PREVIOUS_ALEMBIC_HEAD "$LEMDROP_RECORD_FILE")"
  rollback_tag="$(record_get ROLLBACK_TAG "$LEMDROP_RECORD_FILE")"

  say "  RECORD SAYS"
  say "    currently deployed : ${cur_digest:-<unknown>} (revision ${cur_rev:-<unknown>}, head ${cur_head:-<unknown>})"
  say "    rollback target    : ${prev_digest:-<no digest recorded — legacy M3 deployment>}"
  say "    fallback tag       : ${rollback_tag:-<none>}"
  say ""

  # ── CHOOSE THE TARGET ──────────────────────────────────────────────────────
  #
  # A digest when one was recorded; the local rollback tag when there is not.
  # There is no third option and no prompting: an interactive question here is a
  # question asked to someone who is already in the middle of an incident.
  local target="" legacy=0
  if [ -n "$prev_digest" ]; then
    if ! validate_image_digest "$prev_digest"; then
      say "REFUSING: the record's PREVIOUS_IMAGE_DIGEST is not a digest reference."
      say "  A record written by something other than scripts/deploy.sh is not"
      say "  trusted to name a rollback target. Nothing has been changed."
      exit "$EX_REFUSED"
    fi
    target="$prev_digest"
  elif [ -n "$rollback_tag" ] && [ "$rollback_tag" != "-" ]; then
    target="$rollback_tag"
    legacy=1
    say "This host's record carries no previous digest — the previous deployment predates"
    say "digest-pinned deploys (M3 behaviour, image built on this host). Rolling back to the"
    say "local rollback tag instead, which names the exact bytes that were running:"
    say "  $target"
    say ""
    if ! docker image inspect "$target" >/dev/null 2>&1; then
      say "REFUSING: $target is not present in this host's local image store."
      say "  It was built on this host and never pushed, so there is nowhere to"
      say "  fetch it from. Nothing has been changed."
      exit "$EX_REFUSED"
    fi
  else
    say "REFUSING: the record names neither a previous digest nor a rollback tag."
    say "  There is no rollback target. Nothing has been changed."
    exit "$EX_REFUSED"
  fi

  # ── THE SCHEMA QUESTION, ASKED OUT LOUD ────────────────────────────────────
  #
  # Not a gate — a rollback is the wrong moment to refuse — but it is stated,
  # because it is the one hazard M4 §4.4 item 5 identifies, and an operator who
  # does not know the recorded head cannot tell whether going back is even
  # schema-compatible.
  say ""
  if [ -n "$prev_head" ] && [ -n "$cur_head" ] && [ "$prev_head" != "$cur_head" ]; then
    say "⚠️  THE SCHEMA HEAD DIFFERS between what is deployed and what you are"
    say "    rolling back to:  now='${cur_head}'  ->  target='${prev_head}'"
    say "    Rolling the API back against a different schema is only safe if that"
    say "    schema change is backward compatible. Check that BEFORE relying on"
    say "    this. This script cannot check it: it has no DDL credential and the"
    say "    EC2 role is not permitted to have one (infra/iam.tf)."
    say "    Continuing — a refusal here would be worse than a stated risk."
    say ""
  fi

  # ── CAPTURE `.env` BEFORE TOUCHING IT ──────────────────────────────────────
  # A rollback that changes the image but leaves `.env` pointing at the failed
  # digest starts the old image and misreports what is deployed, which is worse
  # than having done nothing.
  local env_backup
  env_backup="$(mktemp "$LEMDROP_STATE_DIR/env.before-rollback.XXXXXX")" \
    || die "cannot create a backup file in $LEMDROP_STATE_DIR"
  chmod 0600 "$env_backup"
  if [ -f "$LEMDROP_APP_DIR/.env" ]; then
    cat "$LEMDROP_APP_DIR/.env" > "$env_backup" || die "cannot read .env"
  else
    : > "$env_backup"
  fi

  # ── RESTORE ────────────────────────────────────────────────────────────────
  say "restoring $target …"

  if [ "$legacy" -eq 1 ]; then
    # Legacy: .env goes back to having NO API_IMAGE key, so compose resolves the
    # `lemondrop-api` name again — exactly the M3 wiring. Pointing API_IMAGE at
    # the timestamped rollback tag would also work, but it would leave the host
    # configured by a migration script rather than by boot.sh, and the next
    # `docker compose up` from anywhere else would then disagree with it.
    #
    # The tag has to be re-created under the name compose will look for,
    # because --no-build will not build it and the original `lemondrop-api` tag
    # may since have been moved onto the newer image.
    docker tag "$target" lemondrop-api \
      || die "cannot re-tag $target as lemondrop-api (backup: $env_backup)"
    say "  re-tagged $target as lemondrop-api"
    if grep -q '^API_IMAGE=' "$LEMDROP_APP_DIR/.env"; then
      # Remove the key rather than blanking it: an empty API_IMAGE is a
      # different thing from an absent one, and compose's `:-` treats them the
      # same only by accident of its default syntax.
      #
      # The temp file is created in the STATE directory, not beside `.env`: a
      # half-written temp file left in the checkout is untracked clutter in a
      # git tree, and this repository runs a hygiene gate over exactly that.
      local stripped
      stripped="$(mktemp "$LEMDROP_STATE_DIR/.env.stripped.XXXXXX")" \
        || die "cannot create a temp file in $LEMDROP_STATE_DIR"
      grep -v '^API_IMAGE=' "$LEMDROP_APP_DIR/.env" > "$stripped" \
        || { rm -f "$stripped"; die "could not read .env"; }
      cat "$stripped" > "$LEMDROP_APP_DIR/.env" \
        || { rm -f "$stripped"; die "could not write .env (backup: $env_backup)"; }
      rm -f "$stripped"
      say "  removed the API_IMAGE key from .env (legacy wiring restored)"
    fi
  else
    # Pull the previous digest if it is not already here. It usually is — the
    # image it names is the one that was running a moment ago — but "usually" is
    # not a guarantee, and a rollback that fails because of a cache miss would be
    # a poor advertisement for having a rollback.
    if ! docker image inspect "$target" >/dev/null 2>&1; then
      say "  not present locally, pulling …"
      docker pull "$target" || die "could not pull $target (backup: $env_backup)"
    fi
    env_set "$LEMDROP_APP_DIR/.env" API_IMAGE "$target" \
      || die "could not write API_IMAGE into .env (backup: $env_backup)"
    say "  API_IMAGE set to $target"
  fi

  # ── WHAT THE IMAGE SAYS ABOUT ITSELF ────────────────────────────────────────
  # Same labels deploy.sh prefers, read from the image that is about to run,
  # because a rollback is exactly when you least want to be working from a
  # record field that nothing has checked since it was written.
  #
  # TWO FACTS, TWO USES, AND THEY ARE NOT SYMMETRIC — deliberately.
  #
  # PROVENANCE (org.opencontainers.image.revision) is used to FILL IN an empty
  # `prev_rev`. Provenance is a description of the artifact; the image is the
  # authority on that, and an empty field where the image could have supplied
  # one is a worse record. It is never used to OVERRIDE a `prev_rev` the record
  # already has: if the two disagree, that is a disagreement between two written
  # records and this script states it rather than picking a winner — the same
  # doctrine as the schema question above, and for the same reason. This is the
  # worst possible moment to be the thing that stops a rollback.
  #
  # SCHEMA (org.lemondrop.alembic-head) is used for NOTHING but a second
  # opinion. It is deliberately NOT written into the record. ALEMBIC_HEAD is the
  # baseline claim — "the schema this deployment expects the database to be at" —
  # and adopting the image's self-description as a baseline would launder an
  # unverified claim into the one number every future deploy is measured against.
  # If the record has no head, it stays empty and the next deploy refuses, which
  # is the correct outcome for an unknown baseline.
  local label_rev label_head
  label_rev="$(image_source_revision "$target")"
  label_head="$(image_alembic_head "$target")"

  if [ -n "$label_rev" ]; then
    if [ -z "$prev_rev" ]; then
      say ""
      say "  the rollback target's image reports revision ${label_rev}, and the"
      say "  record carried no revision for it. Taking the image's own account:"
      say "    ${label_rev}"
      prev_rev="$label_rev"
    elif ! revisions_agree "$prev_rev" "$label_rev"; then
      say ""
      say "⚠️  PROVENANCE DISAGREEMENT between the record and the target image:"
      say "    record  says this rollback target is : ${prev_rev}"
      say "    image   says it is                   : ${label_rev}"
      say "    Continuing — refusing a rollback over a disagreement about which"
      say "    revision was here is worse than the disagreement. But the record"
      say "    is NOT being updated with the image's value, and the next deploy"
      say "    will be checked against the record. Reconcile by hand afterwards."
    else
      say ""
      say "  the target image's revision label agrees with the record (${label_rev})."
    fi
  fi

  if [ -n "$label_head" ]; then
    if [ -z "$prev_head" ]; then
      say ""
      say "  NOTE: the target image reports alembic head ${label_head}, but the"
      say "        record carried no head for it. The record's ALEMBIC_HEAD is"
      say "        left EMPTY on purpose: a baseline this script cannot verify"
      say "        is not a baseline. scripts/deploy.sh will refuse against it"
      say "        until an operator runs --adopt-current on the restored stack."
    elif [ "$prev_head" != "$label_head" ]; then
      say ""
      say "⚠️  SCHEMA DISAGREEMENT between the record and the target image:"
      say "    record says this rollback target expects : ${prev_head}"
      say "    image  says it expects                  : ${label_head}"
      say "    One of them is wrong about which schema a deployed image needs."
      say "    Continuing — but do not trust this rollback's schema compatibility"
      say "    on the strength of either of them alone."
    fi
  fi

  say "recreating ONLY the api service …"
  compose up -d --no-build --no-deps --force-recreate api \
    || die "docker compose could not recreate the api service (backup: $env_backup)"

  # ── RE-VERIFY, THEN RECORD ─────────────────────────────────────────────────
  # A rollback is not finished when the container starts. It is finished when the
  # restored image is serving correctly — otherwise a rollback to an equally
  # broken image reports success and halves the evidence.
  say ""
  say "verifying the rollback …"
  if ! verify_stack; then
    say ""
    say "THE ROLLBACK DID NOT RESTORE A WORKING SERVICE."
    say "  The container is now running $target, which is what the record asked"
    say "  for, and it is not serving correctly. That is a different incident"
    say "  from the one that triggered the rollback."
    say "  .env as it was before this rollback: $env_backup"
    say "  Next: docker compose logs --tail=100 api"
    exit "$EX_FAILED"
  fi

  # Recorded last, atomically, and never deleted. The record now describes the
  # deployment this host has returned to, and keeps its own PREVIOUS_* — which
  # are this target's predecessors. A second rollback therefore rolls back
  # further, rather than forward.
  #
  # The digest written back is the one we ASKED docker to start, and only if
  # `docker inspect` independently confirms it is among the image's RepoDigests.
  # If that confirmation does not arrive, the field is left empty rather than
  # filled with whatever inspect happened to return: a record that names a
  # digest nobody verified is worse than a record that admits it does not know,
  # because the whole point of this file is that it can be trusted without
  # cross-checking against the host.
  local digests_prev=""
  if [ "$legacy" -eq 0 ]; then
    if image_repo_digests "$target" | grep -qxF "$target"; then
      digests_prev="$target"
    else
      say ""
      say "  NOTE: could not confirm by inspect that the running image's RepoDigests"
      say "        contains $target. The record will NOT claim a digest it has not"
      say "        verified, so IMAGE_DIGEST is left empty. The service is running"
      say "        the right image; only the written-down proof of which image that"
      say "        is, is missing. scripts/verify-deployment.sh will report this."
    fi
  fi
  write_record "$LEMDROP_RECORD_FILE" \
    "RECORD_VERSION=1" \
    "REVISION=${prev_rev}" \
    "SOURCE_REVISION=${prev_rev}" \
    "IMAGE_DIGEST=${digests_prev}" \
    "ALEMBIC_HEAD=${prev_head}" \
    "DEPLOYED_AT_UTC=$(date -u +%FT%TZ) (rolled back by scripts/rollback.sh)" \
    "DEPLOYED_BY=${SUDO_USER:-${USER:-unknown}}" \
    "VERIFICATION=PASS" \
    "VERIFIED_AT_UTC=$(date -u +%FT%TZ)" \
    "ROLLBACK_TAG=" \
    "PREVIOUS_REVISION=" \
    "PREVIOUS_IMAGE_DIGEST=" \
    "PREVIOUS_ALEMBIC_HEAD=" \
    || die "the rollback WORKED and the record could not be updated. The service is correct; the record is stale. Do not delete it — reconcile it by hand."

  say ""
  say "────────────────────── ROLLED BACK ───────────────────────"
  say "  now running : $target"
  say "  revision    : ${prev_rev:-<unknown>}"
  say "  was         : ${cur_digest:-<unknown>}"
  say ""
  say "  The record was updated, not deleted. Running rollback.sh again"
  say "  would have no target: this record's PREVIOUS_* fields are now empty."
  say "  That is deliberate — a second rollback would be a guess."
  say "──────────────────────────────────────────────────────────"
  rm -f "$env_backup"
  return 0
}

main "$@"
