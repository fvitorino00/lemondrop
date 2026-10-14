#!/usr/bin/env bash
#
# lemondrop — shared deployment library (M4 Stage 5).
#
# Sourced, never executed. `deploy.sh`, `rollback.sh` and `verify-deployment.sh`
# all `.` this file.
#
# ── WHY A SHARED FILE AND NOT THREE SELF-CONTAINED SCRIPTS ────────────────────
# Three things in here are CONTRACTS between those scripts, not conveniences:
#
#   1. the image-reference validator — if `deploy.sh` accepts a reference
#      `rollback.sh` would reject, the failure appears at rollback time, which
#      is the worst possible moment to discover a disagreement;
#   2. the revision-record FORMAT — `deploy.sh` writes it and both other scripts
#      parse it, and a format that drifts between a writer and two readers
#      fails by silently reading the wrong field, not by erroring;
#   3. the known-good search probe — three copies of a search that is supposed
#      to be the same search is three different searches.
#
# Each of those is a silent-failure hazard duplicated three times if this file
# does not exist. The rest (argument handling, lock acquisition, rollback) is
# per-script and lives there.
#
# ── WHAT IS *NOT* IN HERE ─────────────────────────────────────────────────────
# No AWS. No boto3. No SSM. No Terraform. This file reads the local filesystem,
# runs `docker` and runs `git`, and that is the entire surface. The EC2 role can
# read only the application database secret (infra/iam.tf) — never the RDS master
# — so the `lemondrop_app` role has no DDL rights and **a migration cannot run
# from this host**. Every schema check below is therefore a REFUSAL: the code
# decides whether it is safe to proceed and stops if not. Nothing here changes a
# database, and nothing here could.
#
# ── CONFIGURATION ─────────────────────────────────────────────────────────────
# Every path is overridable through the environment. The production defaults are
# the ones that matter; the overrides exist so the whole of this can be
# exercised against a scratch directory without root and without touching a real
# host. See scripts/deploy.sh for how the defaults are what an EC2 host expects.

# ── Paths ─────────────────────────────────────────────────────────────────────
#
# WHY THE RECORD LIVES OUTSIDE THE CHECKOUT. $LEMDROP_STATE_DIR defaults to
# /var/lib/lemondrop, NOT to $LEMDROP_APP_DIR. The revision record is DEPLOYED
# STATE, not source: it changes on every deploy, it is meaningless in a pull
# request, and it is host-specific (it names this host's running image). Inside
# the checkout it would be untracked-but-visible clutter — `git status` noise on
# every deploy, a permanent source of "why is there an untracked file", and a
# file that a `git clean -fdx` (or the next fresh clone) removes without asking.
# Worse, this repository runs a `state-leak` hygiene gate over tracked paths
# (`.github/workflows/hygiene.yml`), and a state file living in the tree invites
# exactly the `git add -f` that gate exists to catch.
#
# /var/lib is also where the platform already keeps state that must survive a
# reboot and must not be owned by a user account. The record MUST survive
# `scripts/boot.sh`, which is `git pull`-based and would otherwise have no way
# to distinguish its own files from the application's.
: "${LEMDROP_APP_DIR:=/opt/lemondrop}"
: "${LEMDROP_STATE_DIR:=/var/lib/lemondrop}"
: "${LEMDROP_RECORD_FILE:=${LEMDROP_STATE_DIR}/deployed-revision.env}"
: "${LEMDROP_LOCK_FILE:=/var/lock/lemondrop-deploy.lock}"
: "${LEMDROP_LOG_FILE:=/var/log/lemondrop-deploy.log}"
: "${LEMDROP_CORPUS_FILE:=${LEMDROP_APP_DIR}/data/corpus.json}"

# Bounded waits. 300s for readiness is boot.sh's number, reused deliberately
# rather than invented smaller: only the `api` container is recreated, but its
# healthcheck still waits on both workers, and on a t3.micro that is genuinely
# slow. A shorter window here would turn a correct deploy into a rollback.
: "${LEMDROP_READY_TIMEOUT:=300}"
: "${LEMDROP_SEARCH_TIMEOUT:=300}"

# How long to wait for the deployment lock. Bounded because a deploy that hangs
# forever holding the lock is indistinguishable from one that is working.
: "${LEMDROP_LOCK_TIMEOUT:=300}"

# Compose project name. Defaults to the directory basename, which is what
# `docker compose` derives when run from $LEMDROP_APP_DIR; stated explicitly so
# the scripts cannot be pointed at the wrong project's containers by accident.
: "${LEMDROP_COMPOSE_PROJECT:=lemondrop}"

# ── The known-good search probe ───────────────────────────────────────────────
#
# NOT INVENTED. Every value below is taken from this repository:
#
#   * the document id and its collection come from `data/corpus.json`, and are
#     re-checked against that file at run time by `assert_probe_is_grounded`
#     below — so a corpus change cannot leave behind a probe that "passes"
#     vacuously against a document that no longer exists;
#   * the query and the fact that this document ranks FIRST come from
#     docs/verification-milestone-3.md §8.2, the recorded live run against the
#     real cross-encoder over the real 40-document corpus.
#
# This is the check that catches the failure a health endpoint cannot: an api
# that is perfectly ready and answers 200 to everything while returning
# nonsense from `/search`. The reranker could be misconfigured, the vector
# dimension wrong, the collection predicate broken — every one of those is
# "healthy" and every one of them is a total outage for a user.
: "${LEMDROP_PROBE_COLLECTION:=it-support}"
: "${LEMDROP_PROBE_DOCUMENT_ID:=support-recycle-bin-file-recovery}"
: "${LEMDROP_PROBE_QUERY:=recover a file a user deleted by mistake from the Recycle Bin}"

# ── The image published and verified by this project ──────────────────────────
# Deliberately NOT recorded here. A second copy of a digest is a drift hazard:
# the moment compose's default and this constant disagree, one of them is
# wrong and nothing says which. docker-compose.yml is the single place the
# known-good reference is written down, and these scripts never need it — they
# deploy whatever digest they are given, and refuse anything that is not one.

# Exit codes. Distinct values so a wrapper can tell the classes apart without
# parsing text, and so "it refused" is never mistaken for "the network broke".
readonly EX_OK=0
readonly EX_REFUSED=2       # a guard said no: bad reference, schema mismatch, missing record
readonly EX_FAILED=3        # something was attempted and did not work
readonly EX_LOCKED=4        # another deploy holds the lock

# ═════════════════════════════════════════════════════════════════════════════
# Output
# ═════════════════════════════════════════════════════════════════════════════

# A log write must never be the reason an operation dies. The same reasoning as
# scripts/boot.sh:40 — a full disk, a read-only mount or a permission problem on
# the log must not become an unexplained failure of a deployment, because an
# unexplained deployment failure is precisely what these scripts exist to
# eliminate. Hence `|| true`.
log() { printf '%s [%s]\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LEMDROP_LOG_FILE" 2>/dev/null || true; }

# To stdout only. Used by verify-deployment.sh, which is read-only and must not
# create a log file as a side effect of being read.
say() { printf '%s\n' "$*"; }

# Named, logged, then exited. A deliberate refusal reads differently from a
# crash, and the distinction matters when the reader is deciding whether to try
# again or to go and look at something.
die() { log "FATAL: $1"; exit "${2:-$EX_FAILED}"; }

# ═════════════════════════════════════════════════════════════════════════════
# Image reference validation
# ═════════════════════════════════════════════════════════════════════════════

# A deploy reference must be a fully-qualified, digest-pinned image reference.
#
# Accepted, and only this:
#
#     <registry>/<repository>@sha256:<64 lowercase hex>
#
# Rejected, each for a stated reason rather than by accident of the regex:
#
#   ""                              nothing to deploy
#   lemondrop-api                   a BARE NAME. Docker resolves this as
#                                   docker.io/library/lemondrop-api — a public
#                                   Docker Hub image this project does not
#                                   control. The single most important refusal
#                                   in this file.
#   ghcr.io/owner/img:latest        a TAG. Mutable pointer; GHCR does not
#                                   enforce immutability (see the SHA tag
#                                   discussion in .github/workflows/release.yml),
#                                   so two deploys of "the same" tag can be
#                                   different bytes and nobody can tell which.
#   ghcr.io/owner/img:sha           same problem, smaller: it LOOKS immutable
#                                   because it looks like a commit, and is not.
#   ghcr.io/owner/img@sha256:abc…   a truncated or non-hex digest. Rejected
#                                   because a digest that is not 64 hex
#                                   characters is not a digest, and accepting a
#                                   prefix would let a typo select a real,
#                                   DIFFERENT image.
#   ghcr.io/owner/img:tag@sha256:…  legal in docker, rejected here. The digest
#                                   alone decides the content, so the tag adds
#                                   no information and only makes the recorded
#                                   string disagree with what `docker inspect`
#                                   reports.
#
# Returns 0 on accept; on reject prints an explanation to stderr and returns 1.
# It never exits, so a caller can decide whether a refusal is fatal.
validate_image_digest() {
  local ref="${1-}"

  if [ -z "$ref" ]; then
    printf 'refusing: no image reference given. Expected %s\n' \
      '<registry>/<repository>@sha256:<64-hex-digest>' >&2
    return 1
  fi

  case "$ref" in
    *' '*)
      printf 'refusing: %s contains whitespace.\n' "$ref" >&2
      return 1 ;;
  esac

  # A tag is anything after the LAST PATH COMPONENT of the name — that is,
  # after the last "/" and before the "@".
  #
  # The digest is cut off FIRST, and that ordering is the entire subtlety:
  # "repo@sha256:abc…" contains a colon, so testing the last path component for
  # a colon before removing the digest classifies EVERY valid reference as a
  # tagged one. (It did, on the first run of this function — which is why it is
  # written as two steps rather than one.)
  local name_upto_at="${ref%%@*}"
  local name_last="${name_upto_at##*/}"
  case "$name_last" in
    *:*)
      printf 'refusing: %s carries a TAG. A tag is a mutable pointer, so "the same" tag can be different bytes on two different deploys. Deploy the digest, never a tag.\n' "$ref" >&2
      return 1 ;;
  esac

  # The registry component must LOOK like a host. Docker's own rule: the first
  # path component is a registry if it contains a "." or a ":" or is exactly
  # "localhost". Anything else means there is no registry in the reference at
  # all, which is the bare-name case this whole function exists to stop.
  #
  # Written as `case`, not as `[ "$ref" != */* ]`: an unquoted `*/*` inside `[ ]`
  # is a glob that bash pathname-expands against the current directory, so it
  # becomes every path in the tree and `[ ]` fails with "too many arguments" —
  # which is what happened the first time this was written and tested.
  case "$ref" in
    */*) : ;;
    *)
      printf 'refusing: %s is a BARE NAME with no registry. Docker would resolve it as docker.io/library/%s — a public Docker Hub image this project neither publishes nor controls.\n' "$ref" "$ref" >&2
      return 1 ;;
  esac
  local registry="${ref%%/*}"
  case "$registry" in
    *.*|*:|localhost) : ;;
    *)
      printf 'refusing: %s names no registry. The first path component must be a host (a dot, a port, or localhost); "%s" is a Docker Hub namespace, not a host.\n' "$ref" "$registry" >&2
      return 1 ;;
  esac

  if ! printf '%s' "$ref" | grep -Eq '^[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)+@sha256:[0-9a-f]{64}$'; then
    printf 'refusing: %s is not <registry>/<repository>@sha256:<64 lowercase hex digits>.\n' "$ref" >&2
    return 1
  fi
  return 0
}

# ═════════════════════════════════════════════════════════════════════════════
# The revision record
# ═════════════════════════════════════════════════════════════════════════════
#
# Format: one `KEY=value` per line, `#` comments and blanks permitted. NOT
# sourced as shell — a file that gets `set -a; . record` is a file that can set
# any variable it likes, and a corrupted or hand-edited record would then be
# executed rather than parsed. Every value is validated against the expected
# shape for its key instead.
#
# WHY NOT ONE LINE. The M4 plan proposed a single space-separated line. That is
# fine until a value needs to contain a space — a git message, an error, a
# reason — and then it is ambiguous with no way to detect the ambiguity. Keyed
# lines make the record greppable (`grep '^IMAGE_DIGEST=' …`), which is what a
# human does with it at 3am, and adding a field is a one-line change to every
# reader rather than a redefinition of every position.

# `IMAGE_ID` is OPTIONAL, and it is the only key that is. It is written ONLY
# when `IMAGE_DIGEST` is empty — the M3 legacy case, where the image was built on
# this host and has no registry reference at all — because on a digest-bearing
# record the digest already names the exact bytes, and a second identifier for
# the same image is precisely the drift hazard this file refuses elsewhere (see
# the published-digest note above). On a legacy adoption it is the ONLY thing in
# the record that says which artifact is running: without it the record carries
# an empty digest and, on an unlabelled image, an empty revision as well.
#
# It is deliberately NOT in either required-key tier below, for a reason that is
# about the field and not about the format: every record already in the field
# predates the key, and requiring it would make `record_is_valid` classify all of
# them as TRUNCATED — which would make `schema_gate` refuse the next deploy on
# every host that has ever been deployed to. An absent IMAGE_ID therefore means
# "this record names its image by digest", and a reader that wants an image id
# for such a record takes it from the digest.
readonly RECORD_KEYS_RE='^(RECORD_VERSION|REVISION|SOURCE_REVISION|IMAGE_DIGEST|IMAGE_ID|ALEMBIC_HEAD|DEPLOYED_AT_UTC|DEPLOYED_BY|VERIFICATION|VERIFIED_AT_UTC|ROLLBACK_TAG|PREVIOUS_REVISION|PREVIOUS_IMAGE_DIGEST|PREVIOUS_ALEMBIC_HEAD)='

# Exit 0 if the record is readable and well-formed. Prints why not on stderr.
#
# "Malformed" is defined as: not a regular file, missing a REQUIRED key, more
# than one line for a key, a line that is not `KEY=value`, or a key that is not
# in the known set. The last of those is deliberate — an unknown key means
# something wrote a record this version does not understand, and reading the
# fields you recognise out of it is how you half-restore a deployment.
record_is_valid() {
  local file="${1-}"
  if [ -z "$file" ] || [ ! -f "$file" ]; then
    printf 'no record at %s\n' "${file:-<unset>}" >&2
    return 1
  fi
  if [ ! -r "$file" ]; then
    printf 'record at %s is not readable by this user\n' "$file" >&2
    return 1
  fi
  if [ ! -s "$file" ]; then
    printf 'record at %s is empty\n' "$file" >&2
    return 1
  fi

  local line key
  local seen_rec="" seen_dig="" seen_ver="" seen_verat=""
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|'#'*) continue ;;
    esac
    if ! printf '%s' "$line" | grep -Eq "$RECORD_KEYS_RE"; then
      printf 'record at %s is MALFORMED: not a KEY=value line I recognise:\n  %s\n' "$file" "$line" >&2
      return 1
    fi
    key="${line%%=*}"
    # Written as `if`, never as `[ … ] && …`: under `set -e` an AND-list whose
    # left side is false is itself a failing command, and it would take the
    # whole script down on the first line that has no duplicate key.
    case "$key" in
      RECORD_VERSION)
        if [ -n "$seen_rec" ]; then printf 'record has a duplicate RECORD_VERSION line\n' >&2; return 1; fi
        seen_rec=1 ;;
      IMAGE_DIGEST)
        if [ -n "$seen_dig" ]; then printf 'record has a duplicate IMAGE_DIGEST line\n' >&2; return 1; fi
        seen_dig=1 ;;
      VERIFICATION)
        if [ -n "$seen_ver" ]; then printf 'record has a duplicate VERIFICATION line\n' >&2; return 1; fi
        seen_ver=1 ;;
      VERIFIED_AT_UTC)
        if [ -n "$seen_verat" ]; then printf 'record has a duplicate VERIFIED_AT_UTC line\n' >&2; return 1; fi
        seen_verat=1 ;;
    esac
  done < "$file"

  local missing=""
  for key in RECORD_VERSION REVISION IMAGE_DIGEST DEPLOYED_AT_UTC VERIFICATION; do
    grep -q "^${key}=" "$file" || missing="${missing} ${key}"
  done
  if [ -n "$missing" ]; then
    printf 'record at %s is MALFORMED: missing required key(s):%s\n' "$file" "$missing" >&2
    return 1
  fi

  # Second tier: keys that must be PRESENT but whose value may legitimately be
  # empty. A first-ever deployment has no previous revision and a post-rollback
  # record has no previous-but-one, so "PREVIOUS_IMAGE_DIGEST=" is meaningful
  # and must be allowed — but the key being ABSENT is not, because
  # write_record always emits every key.
  #
  # This exists for one specific failure: a truncation that happens to land
  # exactly on a line boundary. The structural checks above catch truncation
  # that leaves a half-written line, and the required-key checks catch one that
  # swallowed a whole required key — but a record cut cleanly after VERIFIED_AT_UTC
  # is syntactically perfect and merely SHORT, and nothing else can tell it from
  # a record that legitimately has no previous deployment. Requiring the keys to
  # be present, empty or not, is what catches it.
  for key in SOURCE_REVISION ALEMBIC_HEAD DEPLOYED_BY VERIFIED_AT_UTC ROLLBACK_TAG \
             PREVIOUS_REVISION PREVIOUS_IMAGE_DIGEST PREVIOUS_ALEMBIC_HEAD; do
    grep -q "^${key}=" "$file" || missing="${missing} ${key}(absent)"
  done
  if [ -n "$missing" ]; then
    printf 'record at %s is TRUNCATED or was not written by this project: key(s) absent:%s\n' "$file" "$missing" >&2
    return 1
  fi
  return 0
}

# Print the value of one key, or the empty string. Refuses to guess when the key
# appears more than once — a duplicated key means the file is damaged, and
# returning the first match would be picking a side in a disagreement.
record_get() {
  local key="$1" file="$2"
  [ -f "$file" ] || return 0
  local n
  n=$(grep -c "^${key}=" "$file" 2>/dev/null || true)
  [ "$n" -le 1 ] || return 1
  [ "$n" -eq 1 ] || return 0
  sed -n "s/^${key}=//p" "$file" | head -n 1
}

# Write the record ATOMICALLY: a temp file in the SAME directory, then rename.
#
# WHY THIS MATTERS HERE RATHER THAN IN GENERAL. `deploy.sh` writes the record
# only after verification has passed, so the window where a half-written record
# exists is small — but it is not zero, and it is exactly the window in which a
# crash, a full disk or a power cut would otherwise leave a truncated file at
# the authoritative path. `rollback.sh` would then read a record with, say, no
# PREVIOUS_IMAGE_DIGEST, and restore… nothing, while reporting success.
#
# A reader never sees a partial file because `rename(2)` within one filesystem
# is atomic: it observes either the old file or the new one. `mv` is used
# because it is the rename, and because the temp file is deliberately created
# beside the destination rather than in /tmp — `mv` across filesystems is a copy
# followed by an unlink, which is not atomic and would reintroduce the exact
# race this is here to remove.
#
# Usage: write_record <file> <KEY=value>...
write_record() {
  local dest="$1"; shift
  local dir; dir="$(dirname "$dest")"
  mkdir -p "$dir" || return 1
  local tmp
  tmp="$(mktemp "$dir/.deployed-revision.XXXXXX")" || return 1
  {
    printf '# lemondrop deployment record — written by scripts/deploy.sh.\n'
    printf '#\n'
    printf '# This file lives OUTSIDE the git checkout (/var/lib/lemondrop) on purpose:\n'
    printf '# it is host state, not source. Do not move it into the repository, do not\n'
    printf '# commit it, and do not delete it — scripts/rollback.sh reads it, and a\n'
    printf '# deploy that cannot record cannot roll back.\n'
    printf '#\n'
    printf '# It is written to a temp file and renamed into place, so a reader never\n'
    printf '# observes a partial record. Parse it with grep/sed, never with `source`.\n'
    printf '\n'
    local kv
    for kv in "$@"; do printf '%s\n' "$kv"; done
  } > "$tmp" || { rm -f "$tmp"; return 1; }

  # Durable before visible. The data is in the page cache after write(2); the
  # rename makes it visible to other processes. Without the sync, a power cut
  # can leave a correctly-named, correctly-sized file full of zeroes — a record
  # that passes every structural check and names a deployment that never
  # happened. Cheap, and it is the one failure mode a "write then rename" scheme
  # is otherwise quietly vulnerable to.
  sync "$tmp" 2>/dev/null || sync 2>/dev/null || true
  chmod 0644 "$tmp"
  mv -f "$tmp" "$dest" || { rm -f "$tmp"; return 1; }
  return 0
}

# ═════════════════════════════════════════════════════════════════════════════
# .env handling
# ═════════════════════════════════════════════════════════════════════════════

env_get() {
  local key="$1" file="$2"
  [ -f "$file" ] || return 0
  sed -n "s/^${key}=//p" "$file" | head -n 1
}

# Set one key in .env IN PLACE, preserving every other line byte for byte.
#
# Why not `echo "$KEY=$VAL" >> .env`? Because compose takes the LAST occurrence
# of a repeated key, so an append-only "set" would work by accident today and
# leave a file that grows on every deploy and has two contradictory values for
# the same setting. Why not rewrite the whole file? Because `.env` holds
# operator-set values that this script has no business reconstructing, and a
# deploy that loses one of them is worse than a deploy that fails.
#
# The key is replaced if present and appended if absent — boot.sh's generated
# `.env` comes from `.env.example`, which carries API_IMAGE, but an `.env` from
# an older checkout will not have the key at all, and that must be a working
# deploy rather than an error.
env_set() {
  local file="$1" key="$2" value="$3"
  [ -f "$file" ] || return 1
  local tmp
  tmp="$(mktemp "$(dirname "$file")/.env.XXXXXX")" || return 1
  if grep -q "^${key}=" "$file"; then
    awk -v k="$key" -v v="$value" '
      BEGIN { FS="=" }
      $1 == k { print k "=" v; next }
      { print }
    ' "$file" > "$tmp" || { rm -f "$tmp"; return 1; }
  else
    # Append, making sure the previous final line is terminated first —
    # otherwise the new key is concatenated onto it and the file silently grows
    # a key nobody wrote.
    {
      cat "$file"
      if [ -s "$file" ] && [ "$(tail -c 1 "$file" | wc -l)" -eq 0 ]; then printf '\n'; fi
      printf '%s=%s\n' "$key" "$value"
    } > "$tmp" || { rm -f "$tmp"; return 1; }
  fi
  mv -f "$tmp" "$file" || { rm -f "$tmp"; return 1; }
  return 0
}

# Restore .env from a backup taken earlier in this run, keeping the DESTINATION's
# permissions rather than the backup's. `cat >` instead of `cp`: it writes
# through the existing inode, so a deliberately-chmod-ed .env keeps its mode,
# and it cannot fail in the way `cp` can when source and destination differ in
# ownership.
env_restore() {
  local backup="$1" dest="$2"
  [ -f "$backup" ] || return 1
  cat "$backup" > "$dest" || return 1
  return 0
}

# ═════════════════════════════════════════════════════════════════════════════
# Compose
# ═════════════════════════════════════════════════════════════════════════════

compose() { ( cd "$LEMDROP_APP_DIR" && docker compose -p "$LEMDROP_COMPOSE_PROJECT" "$@" ); }

# The container id of the running api, or empty when nothing is running.
api_container_id() { compose ps -q api 2>/dev/null | head -n 1; }

# The image ID (sha256:…) the running api container was created from. This is an
# immutable local identifier and survives every retagging in the world, which is
# why the rollback tag is taken from THIS and not from a name.
running_image_id() {
  local cid="$1"
  [ -n "$cid" ] || return 0
  docker inspect -f '{{.Image}}' "$cid" 2>/dev/null | head -n 1
}

# The digest-qualified references the local image is known by. Empty for an
# image that was built on this host and never pulled, which is the M3 legacy
# case and is not an error.
image_repo_digests() {
  local image_id="$1"
  [ -n "$image_id" ] || return 0
  docker inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$image_id" 2>/dev/null || true
}

# ═════════════════════════════════════════════════════════════════════════════
# Image labels — two facts, read off the image itself
# ═════════════════════════════════════════════════════════════════════════════
#
# `.github/workflows/release.yml` stamps three labels onto every image it
# publishes:
#
#   org.opencontainers.image.revision   PROVENANCE — which commit's tree
#   org.opencontainers.image.source     where that tree lives
#   org.lemondrop.alembic-head          SCHEMA — which alembic revision the
#                                       code in this image expects the database
#                                       to be at
#
# ── WHY THE SCHEMA LABEL IS NOT THE COMMIT LABEL, IN ONE PARAGRAPH ────────────
# Because they are answers to different questions in different versioning
# schemes, and neither one determines the other. The commit says WHAT CODE this
# is; the alembic head says WHAT TABLE SHAPE that code needs. A commit can ship
# without moving the head — a README, a revert, a squashed branch — and one
# commit can move the head more than once. So the two labels are read, stored
# and compared as two separate facts throughout these scripts, and a deploy
# that cannot establish BOTH of them independently has not established
# anything. `org.lemondrop.alembic-head` is in its own namespace rather than in
# `org.opencontainers.*` because squatting the standard vocabulary with a
# project-specific value would make it indistinguishable from a standard
# annotation to any consumer that only knows the standard ones — and because
# `org.opencontainers.image.version`, the field that looks like the natural
# home for it, means "the version of this software", which a migration
# revision is not.
#
# ── WHY THIS IS A FALLBACK AND NOT A REPLACEMENT ──────────────────────────────
# The image already published from commit 8cddfe8
# (sha256:0bdb7afa…42986) carries NO labels at all: build-push-action set none,
# and nothing in api/Dockerfile adds any. It stays deployable. Every function
# below therefore degrades to the operator-supplied source revision rather than
# refusing, and says loudly that it has done so. The day a labelled image is
# published, the same command prefers the label and the warning goes away — with
# no change to the invocation.

readonly LABEL_REVISION='org.opencontainers.image.revision'
readonly LABEL_SOURCE='org.opencontainers.image.source'
readonly LABEL_ALEMBIC_HEAD='org.lemondrop.alembic-head'

# The value of one label on one image, or the empty string.
#
# WHY `range` AND NOT `index`. `{{index .Config.Labels "k"}}` is the obvious
# spelling and it does work — checked against Docker 29.8.2 on an image whose
# labels map is genuinely nil (`.Config.Labels` prints as `null` there), where
# `index` returns the empty string and exits 0, because Go's template `index`
# substitutes a map's element zero value for a missing key.
#
# It is not used anyway, for a boring reason: there are three labels and three
# callers, and `index` is one label per `docker image inspect`. `range` renders
# the whole map in ONE call, so this function — which is called three times per
# resolution and once per field in verify-deployment.sh — talks to the daemon
# once instead of three times. On a host mid-incident that is not a rounding
# error.
#
# WHY THE WHOLE `docker` CALL IS GUARDED WITH `|| true`. `docker image inspect`
# exits non-zero for an image this host does not have — checked: exit 1 — and
# under `set -o pipefail` that would propagate out of this function and take the
# calling script down. An unreadable label is not a fatal condition; it is a
# missing one, and the caller decides what missing means.
#
# STATED LIMITS. `sed` treats the `.` in the key as a regex metacharacter, so the
# pattern is very slightly looser than the literal key. The key is always one of
# the three constants above and never caller input, so the looseness cannot be
# steered. And the value is taken as the first matching line, which is the whole
# value unless a value contains a newline — something neither `docker build
# --label` nor build-push-action's `labels:` can produce.
image_label() {
  local image="${1-}" key="${2-}"
  if [ -z "$image" ] || [ -z "$key" ]; then
    return 0
  fi
  local labels
  labels="$(docker image inspect \
    --format '{{range $k, $v := .Config.Labels}}{{printf "%s=%s\n" $k $v}}{{end}}' \
    "$image" 2>/dev/null || true)"
  printf '%s\n' "$labels" | sed -n "s/^${key}=//p" | head -n 1
  return 0
}

image_source_revision() { image_label "${1-}" "$LABEL_REVISION"; }
image_source_url()      { image_label "${1-}" "$LABEL_SOURCE"; }
image_alembic_head()    { image_label "${1-}" "$LABEL_ALEMBIC_HEAD"; }

# Do two revision strings name the same commit?
#
# WHY THIS IS NOT A PLAIN `=`. The label is always a full 40-character sha
# because build-push-action received `github.sha` unaltered. The argument is
# typed by a human at 3am, and humans type eight characters. `8cddfe8` and
# `8cddfe8e4c…` are the same commit, and refusing that as a "conflict" would be
# a false alarm on the one path where the two sources are most likely to agree.
#
# So: equal strings agree; one being a prefix of the other agrees (that is what
# an abbreviation IS); and if neither, git is asked to resolve both to commits
# and compare those. Git is asked last and its failure is not an error — a
# `--depth 1` clone cannot resolve a revision it does not have, and that must
# not turn into a refusal. When none of the three can establish agreement, the
# caller treats it as a conflict, which is the safe direction: a false conflict
# costs one explanatory error, a false agreement would deploy the wrong tree.
revisions_agree() {
  local a="${1-}" b="${2-}"
  if [ -z "$a" ] || [ -z "$b" ]; then
    return 1
  fi
  # Lowercased because git object names are case-insensitive on input and an
  # operator may paste a mixed-case sha from a web page.
  local al bl
  al="$(printf '%s' "$a" | tr '[:upper:]' '[:lower:]')"
  bl="$(printf '%s' "$b" | tr '[:upper:]' '[:lower:]')"
  if [ "$al" = "$bl" ]; then
    return 0
  fi
  case "$al" in "$bl"*) return 0 ;; esac
  case "$bl" in "$al"*) return 0 ;; esac

  if git -C "$LEMDROP_APP_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    local ca cb
    ca="$(git -C "$LEMDROP_APP_DIR" rev-parse "${a}^{commit}" 2>/dev/null || true)"
    cb="$(git -C "$LEMDROP_APP_DIR" rev-parse "${b}^{commit}" 2>/dev/null || true)"
    if [ -n "$ca" ] && [ -n "$cb" ] && [ "$ca" = "$cb" ]; then
      return 0
    fi
  fi
  return 1
}

# The loud warning. Printed as a block, because the condition it reports is the
# one an operator is most likely to skim past: the deploy is about to work, and
# what it is doing is trusting a human-typed string instead of something the
# image says about itself.
warn_image_has_no_revision_label() {
  local image="${1-}"
  say ""
  say "══════════ UNLABELLED IMAGE — LEGACY FALLBACK PATH ══════════"
  say "  ${image} carries no ${LABEL_REVISION} label."
  say ""
  say "  That means either it was published before the release workflow began"
  say "  stamping OCI labels, or it was built by something that did not. Either"
  say "  way it cannot say which commit it came from. Continuing, because it is"
  say "  the image that was asked for and refusing would make an image that is"
  say "  already published — and already verified — undeployable."
  say ""
  say "  Falling back to the source revision you supplied on the command line."
  say "  Nothing here can check that string against the image: you are the"
  say "  source of truth for it. A wrong revision yields a wrong schema head,"
  say "  and a wrong schema head yields a wrong verdict from the schema gate."
  say ""
  say "  To remove the ambiguity, publish a new image from a release run that"
  say "  stamps these labels. Until then, take the revision from the merge"
  say "  commit in the release run that published the digest."
  say "═══════════════════════════════════════════════════════════════"
  log "WARNING: ${image} has no ${LABEL_REVISION} label; falling back to the operator-supplied revision ${2-:-<none>}."
}

warn_image_has_no_alembic_label() {
  local image="${1-}"
  say ""
  say "NOTE: ${image} carries no ${LABEL_ALEMBIC_HEAD} label."
  say "      Its schema head will be read from the source tree at the revision"
  say "      below, using the same revisions-minus-down_revisions rule alembic"
  say "      itself uses. That is a fallback, not a second opinion: if the image"
  say "      were built from a different tree than the revision names, nothing"
  say "      here would notice."
  log "NOTE: ${image} has no ${LABEL_ALEMBIC_HEAD} label; deriving the head from the source tree."
}

# ═════════════════════════════════════════════════════════════════════════════
# Establishing the two facts
# ═════════════════════════════════════════════════════════════════════════════
#
# Sets four globals on success and returns 0; prints nothing. Returns 1 and
# explains itself on any refusal. Globals rather than a return value because
# there are two of them plus their provenance, and four positional outputs on a
# function this consequential is a way to transpose two arguments silently.
#
#   DEPLOY_SOURCE_REVISION  which commit this image is from
#   DEPLOY_REVISION_SOURCE  "image-label" | "operator-argument"
#   DEPLOY_ALEMBIC_HEAD     which alembic revision its code expects
#   DEPLOY_HEAD_SOURCE      "image-label" | "source-tree"
#
# PREFERENCE ORDER, and it is deliberately NOT symmetric. Provenance prefers the
# label, because the label is written by the build that made the bytes. Schema
# prefers the label too, and where the label is absent it falls back to the
# source tree — but only after the revision has been established, because the
# tree is read AT that revision and an unknown revision has no tree.
#
# THE IMAGE MUST BE PRESENT. Reading a label needs the image, and this is called
# after the pull for that reason: `docker manifest inspect` returns a manifest,
# not an image config, and the labels live in the config. Fetching the config
# blob by hand from the registry would need credentials these scripts do not
# have and must not acquire. The cost of that is stated in deploy.sh: a deploy
# with no operator-supplied revision can no longer be refused before the
# download, only after it.

resolve_deploy_facts() {
  local image="${1-}" arg_rev="${2-}"

  DEPLOY_SOURCE_REVISION=""
  DEPLOY_REVISION_SOURCE=""
  DEPLOY_ALEMBIC_HEAD=""
  DEPLOY_HEAD_SOURCE=""

  local label_rev label_head
  label_rev="$(image_source_revision "$image")"
  label_head="$(image_alembic_head "$image")"

  # ── PROVENANCE: LABEL AGAINST ARGUMENT ─────────────────────────────────────
  # Two sources naming two different commits is a genuine contradiction. One of
  # them is wrong, this script cannot tell which, and picking either would be
  # picking a side in a disagreement — so it refuses and prints both. This is
  # checked BEFORE either is used, so nothing downstream can act on a revision
  # that is already known to be contested.
  if [ -n "$label_rev" ] && [ -n "$arg_rev" ] && ! revisions_agree "$label_rev" "$arg_rev"; then
    say ""
    say "════════════ PROVENANCE CONFLICT — REFUSING ═════════════"
    say "  the image's ${LABEL_REVISION} label says : ${label_rev}"
    say "  the revision you passed on the command line says : ${arg_rev}"
    say ""
    say "  Those are different commits. One of the two is wrong: either the"
    say "  argument is a typo or a stale copy-paste, or the digest does not"
    say "  belong to the image you think it does."
    say ""
    say "  This will not be resolved by choosing one. If the label is right,"
    say "  the deploy is:"
    say "    scripts/deploy.sh <digest> ${label_rev}"
    say "  If the argument is right, the image is not the one you meant and the"
    say "  digest is the thing to re-check."
    say ""
    say "  Nothing has been changed."
    say "══════════════════════════════════════════════════════════"
    return 1
  fi

  # ── PROVENANCE: WHICH ONE ─────────────────────────────────────────────────
  if [ -n "$label_rev" ]; then
    DEPLOY_SOURCE_REVISION="$label_rev"
    DEPLOY_REVISION_SOURCE="image-label"
  elif [ -n "$arg_rev" ]; then
    DEPLOY_SOURCE_REVISION="$arg_rev"
    DEPLOY_REVISION_SOURCE="operator-argument"
    warn_image_has_no_revision_label "$image" "$arg_rev"
  else
    say ""
    say "REFUSING: no source revision available."
    say "  ${image} carries no ${LABEL_REVISION} label and none was given on the"
    say "  command line. The schema head cannot be read from the image (it holds"
    say "  no alembic tooling and no alembic/versions/), and it cannot be read"
    say "  from the database (this host has no DDL credential and is not"
    say "  permitted to have one). So there is no remaining source for it."
    say ""
    say "  Give the revision explicitly:"
    say "    scripts/deploy.sh <digest> <source-git-revision>"
    say ""
    say "  Nothing has been changed."
    return 1
  fi

  # ── SCHEMA: WHICH ONE ──────────────────────────────────────────────────────
  if [ -n "$label_head" ]; then
    DEPLOY_ALEMBIC_HEAD="$label_head"
    DEPLOY_HEAD_SOURCE="image-label"
  else
    warn_image_has_no_alembic_label "$image"
    # stderr is NOT suppressed here. This is the path where the source tree is
    # the only source of the answer, so its failure has to be visible and named.
    DEPLOY_ALEMBIC_HEAD="$(alembic_head_at_revision "$DEPLOY_SOURCE_REVISION")" || return 1
    DEPLOY_HEAD_SOURCE="source-tree"
  fi

  # ── THE CROSS-CHECK ────────────────────────────────────────────────────────
  # When the source tree at the resolved revision CAN be read, and it disagrees
  # with what the image claims, the image and the tree are not the same thing.
  # That is a third contradiction, distinct from the one above: both sources
  # can be individually plausible while describing different artifacts. It is
  # refused rather than warned about, because the schema gate below is about to
  # compare one number against a recorded one, and it is better to have no
  # number than a number nobody can account for.
  #
  # `2>/dev/null`, because a `--depth 1` clone cannot read this and that is not
  # an error on the label path — it is the normal state of the host described in
  # scripts/boot.sh. Only a successful derivation is compared.
  local git_head
  git_head="$(alembic_head_at_revision "$DEPLOY_SOURCE_REVISION" 2>/dev/null || true)"
  if [ -n "$git_head" ] && [ "$git_head" != "$DEPLOY_ALEMBIC_HEAD" ]; then
    say ""
    say "════════════ SCHEMA LABEL DISAGREES WITH THE SOURCE TREE ═════════════"
    say "  the image's ${LABEL_ALEMBIC_HEAD} label says : ${DEPLOY_ALEMBIC_HEAD}"
    say "  the source tree at ${DEPLOY_SOURCE_REVISION} says : ${git_head}"
    say ""
    say "  One image is not the tree of one commit, or the label was built by a"
    say "  different alembic than the one this checkout reads with. Either way"
    say "  the schema head is not established, and the schema gate cannot run on"
    say "  an answer nobody can account for."
    say ""
    say "  Nothing has been changed."
    say "════════════════════════════════════════════════════════════════════"
    return 1
  fi

  return 0
}

#
# ═════════════════════════════════════════════════════════════════════════════
# Schema head from a SOURCE TREE — the fallback, never the first choice
# ═════════════════════════════════════════════════════════════════════════════
#
# ── WHY NOT `alembic heads` INSIDE THE IMAGE ──────────────────────────────────
# Because it is not there. `api/requirements.txt` does not include alembic — it
# is deliberately in `requirements-dev.txt`, and api/Dockerfile copies only
# `app/`, so the published image contains neither the migration tooling NOR the
# `alembic/versions/` directory. This is a correct and deliberate decision
# documented in both files ("the API container never runs migrations"), and it
# has a consequence nobody has written down yet: **the image cannot report its
# own schema head.** Any design that asks the image is asking a question of
# something that was built specifically to not have the answer.
#
# ── WHY NOT FROM THE DATABASE ─────────────────────────────────────────────────
# Because the EC2 role cannot, and must not. `infra/iam.tf` grants
# secretsmanager:GetSecretValue on the APPLICATION secret only; the RDS master
# credential is not readable from this host by design, and the `lemondrop_app`
# role it carries has no DDL rights. "What revision is the database on?" is a
# question with no permitted answer from this host — which is precisely why the
# baseline is a RECORDED value rather than a probed one. `deploy.sh` compares
# against what it last wrote down, and refuses when that disagrees.
#
# ── WHY THIS IS THE FALLBACK AND NOT THE PRIMARY SOURCE ───────────────────────
# A newer image carries the answer itself, in `org.lemondrop.alembic-head`, set
# at build time by `alembic heads` against the tree that was built (see
# resolve_deploy_facts above and the label step in release.yml). Reading it from
# the image is better: it needs no git history, it cannot be wrong about which
# tree it describes, and it works on a `--depth 1` clone where a commit is
# simply not present.
#
# This function remains because the image already published from commit 8cddfe8
# (sha256:0bdb7afa…42986) carries no labels at all. For that digest there is
# nothing else to ask, and refusing it would make a published, gated, verified
# image undeployable. So the derivation stays, warns loudly when it is what
# produced the answer, and stops being reached as soon as a labelled image
# exists.
#
# ── WHAT IT DERIVES, AND THE LIMIT THAT IS ────────────────────────────────────
# The git tree of a named source revision, read with `git show`. No network, no
# database, no third-party binary. The head is derived the way alembic derives
# it: the set of `revision` values minus the set of non-None `down_revision`
# values. That is a reimplementation, and it is a fallback precisely because of
# that — it handles the linear history this repository has and refuses the
# branched one below, where `alembic heads` would report the ambiguity instead
# of concealing it. The build-time label has no such limit, because it is
# alembic itself doing the walking.

#
# ── WHY A BRANCHED OR UNPARSEABLE HISTORY REFUSES ─────────────────────────────
# `alembic heads` reports MORE THAN ONE head for a branched history, and a
# tuple-valued `down_revision = ("a", "b")` is not parsed by the sed below. Both
# cases would otherwise silently produce "one head" or "no head" and be treated
# as compatible. Zero heads and more than one head are both refusals.

# Print the single alembic head at <rev>, or fail with a reason on stderr.
alembic_head_at_revision() {
  local rev="$1"
  local git_dir="$LEMDROP_APP_DIR"

  if ! git -C "$git_dir" rev-parse --git-dir >/dev/null 2>&1; then
    printf '%s is not a git checkout, so the schema of any revision in it cannot be read.\n' "$git_dir" >&2
    return 1
  fi
  if ! git -C "$git_dir" cat-file -e "${rev}^{commit}" 2>/dev/null; then
    printf 'revision %s is not present in %s.\n' "$rev" "$git_dir" >&2
    printf '  boot.sh clones with --depth 1, so this is expected on a fresh host. Fetch just this one:\n' >&2
    printf '    git -C %s fetch --depth 1 origin %s\n' "$git_dir" "$rev" >&2
    printf '  (deploy.sh will not fetch for you: it reaches the registry and nothing else.)\n' >&2
    return 1
  fi

  local files
  files=$(git -C "$git_dir" ls-tree -r --name-only "$rev" -- api/alembic/versions/ 2>/dev/null) || return 1
  files=$(printf '%s\n' "$files" | grep '\.py$' | grep -v '/__pycache__/' || true)

  if [ -z "$files" ]; then
    printf 'revision %s contains no files under api/alembic/versions/, so it declares NO migrations at all.\n' "$rev" >&2
    printf '  Refusing rather than treating "no migrations" as "no schema change": a wrong tree here means a wrong answer, not an empty one.\n' >&2
    return 1
  fi

  local revisions="" downs="" f r d
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    r=$(git -C "$git_dir" show "${rev}:${f}" 2>/dev/null | sed -n 's/^revision[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
    if [ -z "$r" ]; then
      printf 'could not read a `revision = "…"` line from %s at %s.\n' "$f" "$rev" >&2
      return 1
    fi
    d=$(git -C "$git_dir" show "${rev}:${f}" 2>/dev/null | sed -n 's/^down_revision[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
    revisions="${revisions}${r}"$'\n'
    [ -n "$d" ] && downs="${downs}${d}"$'\n'
  done <<< "$files"

  local heads
  heads=$(comm -23 \
            <(printf '%s' "$revisions" | sort -u) \
            <(printf '%s' "$downs"   | sort -u) | sed '/^$/d')

  local count
  count=$(printf '%s' "$heads" | grep -c . || true)
  if [ "$count" -eq 0 ]; then
    printf 'every migration at %s is the down_revision of another: the history is circular or unreadable.\n' "$rev" >&2
    return 1
  fi
  if [ "$count" -gt 1 ]; then
    printf 'revision %s has %s alembic HEADS (branched migration history):\n' "$rev" "$count" >&2
    printf '%s\n' "$heads" | sed 's/^/  /' >&2
    printf '  A branched history has no single "head", so it cannot be compared to the recorded one. Refusing.\n' >&2
    return 1
  fi
  printf '%s' "$heads" | head -n 1
  return 0
}

# ═════════════════════════════════════════════════════════════════════════════
# HTTP
# ═════════════════════════════════════════════════════════════════════════════

api_base_url() {
  if [ -n "${LEMDROP_API_BASE_URL-}" ]; then printf '%s' "$LEMDROP_API_BASE_URL"; return 0; fi
  local port
  port=$(env_get API_HOST_PORT "$LEMDROP_APP_DIR/.env")
  [ -n "$port" ] || port=8000
  printf 'http://127.0.0.1:%s' "$port"
}

# Poll /health/ready until it answers 200, or the timeout expires.
#
# Why `/health/ready` and not `/health`: ready is the endpoint that reports the
# embedder, the reranker and the DATABASE. A container that is merely alive
# while its workers are still loading GGUF files answers 200 to /health and
# 503 to everything a user calls. Waiting for the wrong one means deploying an
# image that is not yet able to serve, and then recording a deployment as
# verified that has never answered a search.
wait_for_ready() {
  local timeout="${1:-$LEMDROP_READY_TIMEOUT}"
  local base; base="$(api_base_url)"
  local started=$SECONDS i http=000
  # A C-style loop rather than `seq`: one less coreutils dependency, which is
  # the same reasoning boot.sh:280 gives for the same construct.
  for ((i = 1; i * 5 <= timeout; i++)); do
    # `|| true`, not `|| printf '000'`: curl's `-w '%{http_code}'` ALREADY
    # prints 000 when it cannot connect, so the fallback appends a second one
    # and the report says "last status: 000000" — which reads like a real
    # (and meaningless) HTTP code.
    http=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$base/health/ready" 2>/dev/null || true)
    http="${http:-000}"
    if [ "$http" = "200" ]; then
      # Elapsed, not the loop bound. `i * 5` is the WORST case for this attempt,
      # not how long it took, and printing it as "after Ns" claims a delay that
      # did not happen — which is the sort of small inaccuracy that trains a
      # reader to stop believing the numbers next to it.
      say "readiness: 200 from $base/health/ready after $((SECONDS - started))s (attempt $i)"
      return 0
    fi
    sleep 5
  done
  say "readiness: NEVER 200 from $base/health/ready within ${timeout}s (last status: $http)"
  return 1
}

# ── THE KNOWN-GOOD SEARCH ─────────────────────────────────────────────────────
#
# Re-check, on every run, that the probe still refers to something real in the
# committed corpus. Without this the probe rots silently: change the corpus and
# the document disappears, the search returns some other document first, and
# the assertion fails with a message about ranking rather than about the probe
# no longer meaning anything. Worse, if the assertion were merely loosened, it
# would pass against a document nobody chose. A gate never observed failing is
# not known to work, so the check that makes the gate meaningful is checked too.
assert_probe_is_grounded() {
  local corpus="$LEMDROP_CORPUS_FILE"
  if [ ! -f "$corpus" ]; then
    say "probe grounding: CANNOT CHECK — $corpus is not readable here."
    say "  The known-good search below compares against an id this script could"
    say "  not confirm is in the corpus. On this host that is expected: the"
    say "  checkout and the corpus are separate concerns. Do not read a pass"
    say "  here as proof the probe still matches the data."
    return 1
  fi
  if ! grep -qE "\"id\"[[:space:]]*:[[:space:]]*\"${LEMDROP_PROBE_DOCUMENT_ID}\"" "$corpus"; then
    say "probe grounding: FAIL — document id '${LEMDROP_PROBE_DOCUMENT_ID}' is not in $corpus."
    say "  The corpus changed. The known-good search is stale and its result"
    say "  proves nothing. Pick a new probe from the corpus and update"
    say "  LEMDROP_PROBE_* in scripts/lib/deploy-lib.sh deliberately."
    return 1
  fi
  if ! grep -qE "\"collection\"[[:space:]]*:[[:space:]]*\"${LEMDROP_PROBE_COLLECTION}\"" "$corpus"; then
    say "probe grounding: FAIL — collection '${LEMDROP_PROBE_COLLECTION}' is not in $corpus."
    return 1
  fi
  say "probe grounding: ok — ${LEMDROP_PROBE_DOCUMENT_ID} exists in ${LEMDROP_PROBE_COLLECTION} in $(basename "$corpus")"
  return 0
}

# Run the known-good search. Returns 0 only when the TOP-RANKED result is the
# expected document.
#
# ── WHY THE FIRST RESULT IS CHECKED AND NOT MERELY "THE DOCUMENT APPEARS" ─────
# Because "appears somewhere in the top 5" is a much weaker statement than
# "ranks first", and it is the weaker statement that would survive a genuinely
# broken retrieval pipeline. If the reranker returns noise, the expected
# document usually still appears — in eighth place. That deployment serves
# users badly and passes this check. Rank-first is what M3 §8.2 actually
# recorded, so rank-first is what is asserted here.
#
# ── PARSING WITHOUT jq, AGAINST A SINGLE-LINE BODY ──────────────────────────
# AL2023 does not ship jq, and adding a package to a deployment script is worse
# than a grep.
#
# The first `"document_id"` in the body is the TOP-RANKED result, because
# `results` is the first declared field of SearchResponse and `document_id` is
# the first declared field of SearchResultDocument — Pydantic serialises in
# declaration order, deterministically. So the assertion depends on response
# MODEL ORDER, not on luck, and if that order ever changes the check fails
# loudly (a wrong id) rather than quietly (no id found).
#
# `grep -o` IS LOAD-BEARING, and it is here because of a bug found by running
# this against a REAL response instead of a pretty-printed fixture. FastAPI
# serialises compactly: the entire body is ONE line. A
# `sed 's/^.*"document_id".../\1/p'` on a single line has a GREEDY `.*` prefix,
# which consumes as much as it can and therefore captures the LAST
# `document_id` in the document — the FIFTH-ranked result. `head -1` does not
# rescue it: there is only one line, so `head -1` returns that same last match.
# The probe would then have asserted that the WORST result is the expected
# document: failing on every healthy deployment, and reading like a retrieval
# outage on a perfectly good stack.
#
# `grep -o` prints ONE MATCH PER LINE, which is the only reason "the first
# occurrence" is expressible with coreutils at all. Do not "simplify" this back
# to a single sed.
known_good_search() {
  local base; base="$(api_base_url)"
  local body_file
  body_file="$(mktemp)" || return 1

  local payload
  payload=$(printf '{"collection":"%s","query":"%s"}' "$LEMDROP_PROBE_COLLECTION" "$LEMDROP_PROBE_QUERY")

  local http
  http=$(curl -sS -o "$body_file" -w '%{http_code}' --max-time "$LEMDROP_SEARCH_TIMEOUT" \
          -X POST "$base/search" -H 'content-type: application/json' -d "$payload" 2>/dev/null || true)
  http="${http:-000}"

  if [ "$http" != "200" ]; then
    say "known-good search: HTTP ${http} from POST $base/search"
    say "  (first 400 bytes of the response: $(head -c 400 "$body_file" | tr '\n' ' '))"
    rm -f "$body_file"
    return 1
  fi

  local first
  first=$(grep -o '"document_id"[[:space:]]*:[[:space:]]*"[^"]*"' "$body_file" \
            | head -n 1 | sed 's/^.*"\([^"]*\)"$/\1/')

  if [ -z "$first" ]; then
    say "known-good search: HTTP 200 but the response carried no document_id."
    say "  (first 400 bytes: $(head -c 400 "$body_file" | tr '\n' ' '))"
    rm -f "$body_file"
    return 1
  fi

  local considered
  considered=$(grep -o '"candidates_considered"[[:space:]]*:[[:space:]]*[0-9]*' "$body_file" \
                | head -n 1 | sed 's/.*:\([0-9]*\)$/\1/')

  rm -f "$body_file"

  if [ "$first" != "$LEMDROP_PROBE_DOCUMENT_ID" ]; then
    say "known-good search: RANKED WRONG — top result was '${first}', expected '${LEMDROP_PROBE_DOCUMENT_ID}'."
    say "  The service is ready and answering 200 to a real search. It is still"
    say "  serving the wrong document first, which is a total failure for a user"
    say "  and invisible to every other check here."
    return 1
  fi

  say "known-good search: PASS — '${LEMDROP_PROBE_COLLECTION}' query ranked '${first}' first (${considered:-?} candidates considered)."
  return 0
}

# Both halves, in order, with the result of each reported whether it passed or
# not. A verification whose failures are silent is a verification nobody can act
# on, and the whole point of this function is to be readable at 3am.
verify_stack() {
  local rc=0
  assert_probe_is_grounded || rc=1
  wait_for_ready "$LEMDROP_READY_TIMEOUT" || rc=1
  if [ "$rc" -ne 0 ]; then
    say "known-good search: NOT ATTEMPTED — the service is not ready, so a search"
    say "  result would measure nothing."
    return 1
  fi
  known_good_search || rc=1
  return "$rc"
}

# ═════════════════════════════════════════════════════════════════════════════
# The lock
# ═════════════════════════════════════════════════════════════════════════════

# Take an exclusive lock on one dedicated file descriptor, held for the lifetime
# of this process.
#
# ── WHY `flock` AND NOT A PID FILE ───────────────────────────────────────────
# The classic stale-lock bug is a PID file: a script writes its PID into a lock
# file, and a later run decides the lock is stale if no such process exists.
# That is wrong whenever the two runs cannot see each other's PID namespace (a
# container, an SSM session, a different boot), and it is wrong in the specific
# case that matters here — a host that was power-cycled mid-deploy still has the
# PID file, and every subsequent deploy then refuses until a human deletes it.
#
# `flock(2)` has none of that. The lock is an open file descriptor, and the
# kernel releases it when the descriptor closes — which happens on exit, on
# kill -9, and on power loss, because there is no process left to hold it. There
# is no file content to go stale and nothing to clean up. The lock FILE remains
# on disk afterwards, empty and unlocked, which is correct and costs nothing.
#
# `-w` bounds the wait. Unbounded would mean a hung first deploy blocks every
# later one silently; the timeout turns that into a refusal with a number in it.
acquire_lock() {
  local timeout="${1:-$LEMDROP_LOCK_TIMEOUT}"
  local dir; dir="$(dirname "$LEMDROP_LOCK_FILE")"
  mkdir -p "$dir" 2>/dev/null || true

  # Probe the open BEFORE `exec`. In a non-interactive shell a failed redirect on
  # `exec` terminates the shell — it does not return non-zero to be tested — so
  # an unwritable lock file has to be discovered before it is used, not after.
  if ! ( : >>"$LEMDROP_LOCK_FILE" ) 2>/dev/null; then
    log "the lock file $LEMDROP_LOCK_FILE is not writable by this user (uid $(id -u))"
    return 1
  fi
  exec 9>"$LEMDROP_LOCK_FILE"

  log "waiting up to ${timeout}s for the deployment lock ($LEMDROP_LOCK_FILE)"
  if flock -w "$timeout" 9; then
    log "lock acquired (pid $$)"
    return 0
  fi
  log "another deployment holds $LEMDROP_LOCK_FILE and did not release it within ${timeout}s"
  return 1
}
