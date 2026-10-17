#!/usr/bin/env bash
#
# Tests for scripts/deploy.sh, scripts/rollback.sh, scripts/verify-deployment.sh
# and scripts/lib/deploy-lib.sh (M4 Stage 5).
#
#   ./scripts/test-deploy-rollback.sh
#
# No bats, no shunit, no framework: a plain script that prints ok/FAIL and exits
# non-zero on the first failure, so it is equally usable by a human and by CI.
#
# WHAT IT NEEDS: bash, coreutils, grep, awk, mktemp. What it must NOT need, and
# what it therefore proves it does not need: a docker daemon, a network, AWS,
# root. `curl` and `docker` are stubbed on PATH, which is why this runs in a
# clean checkout.
#
# ALL PATHS ARE OVERRIDDEN. `scripts/lib/deploy-lib.sh:36-62` supports the
# `LEMDROP_*` environment overrides, so every path below lives in a scratch
# directory and no real host, record, registry or container is touched.
#
# THE CONTROLS THAT MATTER, stated up front:
#   1. the REGRESSION CONTROL for B1 — a redundant deploy target is refused and
#      the record is NOT made self-referential;
#   2. the REGRESSION CONTROL for B2 — the legacy rollback branch refuses and
#      cannot silently resolve to the digest-pinned compose default;
#   3. the READ-ONLY CONTROL for verify-deployment.sh — with no usable record it
#      reports a clear, non-zero result;
#   4. the SYNTAX CONTROL — deploy.sh, rollback.sh, verify-deployment.sh and
#      deploy-lib.sh all pass `bash -n` (and shellcheck when available).

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/lib/deploy-lib.sh"
DEPLOY="$HERE/deploy.sh"
ROLLBACK="$HERE/rollback.sh"
VERIFY="$HERE/verify-deployment.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

ok()   { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got '$2', want '$3')"; fi; }
has()   { if grep -qF -- "$2" "$1"; then ok "$3"; else bad "$3 ('$2' not found)"; fi; }
hasnt() { if grep -qF -- "$2" "$1"; then bad "$3 ('$2' FOUND — boundary violated)"; else ok "$3"; fi; }

# ── The environment overrides (scratch directory, never a real host) ──────────
APP_DIR="$TMP/app";       mkdir -p "$APP_DIR"
STATE_DIR="$TMP/state";   mkdir -p "$STATE_DIR"
RECORD_FILE="$STATE_DIR/deployed-revision.env"
LOCK_FILE="$STATE_DIR/lemondrop-deploy.lock"
LOG_FILE="$STATE_DIR/lemondrop-deploy.log"
CORPUS_FILE="$APP_DIR/data/corpus.json"   # deliberately NOT created: grounding
                                          # reports "CANNOT CHECK", no fatal.

# A digest-pinned reference shaped like the one docker-compose.yml:436 pins.
DIGEST="ghcr.io/fvitorino00/lemondrop-api@sha256:0bdb7afa566bbff0c8db481cd78a048b130bb8fc8531739530d98fe3cde42986"
OTHER_DIGEST="ghcr.io/fvitorino00/lemondrop-api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

export LEMDROP_APP_DIR="$APP_DIR"
export LEMDROP_STATE_DIR="$STATE_DIR"
export LEMDROP_RECORD_FILE="$RECORD_FILE"
export LEMDROP_LOCK_FILE="$LOCK_FILE"
export LEMDROP_LOG_FILE="$LOG_FILE"
export LEMDROP_CORPUS_FILE="$CORPUS_FILE"
# Keep the stubbed runs fast: readiness/search timeouts that would otherwise
# wait 300s collapse to a single failed attempt.
export LEMDROP_READY_TIMEOUT=1
export LEMDROP_SEARCH_TIMEOUT=1

# Shared library functions (record_is_valid) used to assert record well-formedness.
# shellcheck source=scripts/lib/deploy-lib.sh
. "$LIB"

# ── The stubs ─────────────────────────────────────────────────────────────────
STUB="$TMP/bin"; mkdir -p "$STUB"

cat > "$STUB/curl" <<'STUBEOF'
#!/usr/bin/env bash
# Minimal curl stand-in: nothing is listening, so every call reports 000.
printf '%s %s' "000" "0.001"
STUBEOF

cat > "$STUB/docker" <<'STUBEOF'
#!/usr/bin/env bash
# Minimal docker stand-in: understands only the flags the deploy tooling passes.
case "$1" in
  version) printf '29.8.2\n' ;;
  compose)
    shift
    case "$1" in
      ps)
        case " $* " in
          *" -q "*) printf '' ;;   # no api container is running
          *) printf 'lemondrop-api-1 | running | Up 3 hours (healthy)\n' ;;
        esac ;;
      *) exit 1 ;;
    esac ;;
  inspect) printf 'sha256:deadbeef\n' ;;
  manifest|pull|tag) : ;;            # success, no-op
  image) printf 'sha256:deadbeef\n' ;;
  *) exit 1 ;;
esac
STUBEOF

chmod +x "$STUB/curl" "$STUB/docker"

# ── A valid revision record ───────────────────────────────────────────────────
# Every key `record_is_valid` requires must be present (empty values allowed),
# or the record is TRUNCATED and every consumer refuses it.
write_record_fixture() {
  local prev_digest="${1-}" prev_rev="${2-}" prev_head="${3-}" rollback_tag="${4-}"
  cat > "$RECORD_FILE" <<EOF
# lemondrop deployment record — fixture for scripts/test-deploy-rollback.sh.
RECORD_VERSION=1
REVISION=abcdef0123456789abcdef0123456789abcdef01
SOURCE_REVISION=abcdef0123456789abcdef0123456789abcdef01
IMAGE_DIGEST=$DIGEST
IMAGE_ID=sha256:deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
ALEMBIC_HEAD=head1234
DEPLOYED_AT_UTC=2026-01-01T00:00:00Z
DEPLOYED_BY=test-operator
VERIFICATION=PASS
VERIFIED_AT_UTC=2026-01-01T00:00:00Z
ROLLBACK_TAG=$rollback_tag
PREVIOUS_REVISION=$prev_rev
PREVIOUS_IMAGE_DIGEST=$prev_digest
PREVIOUS_ALEMBIC_HEAD=$prev_head
EOF
}

# ── 1. Syntax ─────────────────────────────────────────────────────────────────
printf '\n[1] syntax\n'
for S in "$DEPLOY" "$ROLLBACK" "$VERIFY" "$LIB"; do
  if bash -n "$S" 2>"$TMP/syn.$(basename "$S")"; then
    ok "bash -n $(basename "$S")"
  else
    bad "bash -n $(basename "$S"): $(cat "$TMP/syn.$(basename "$S")")"
  fi
done
if command -v shellcheck >/dev/null 2>&1; then
  for S in "$DEPLOY" "$ROLLBACK" "$VERIFY" "$LIB"; do
    if shellcheck "$S" 2>"$TMP/sc.$(basename "$S")"; then
      ok "shellcheck $(basename "$S")"
    else
      bad "shellcheck $(basename "$S"): $(cat "$TMP/sc.$(basename "$S")")"
    fi
  done
else
  ok "shellcheck not installed — skipped (bash -n is the floor)"
fi

# ── 2. B1 regression: redundant deploy is refused, record not self-referential ─
printf '\n[2] B1: redundant deploy refused, record not self-referential\n'
touch "$APP_DIR/.env" "$APP_DIR/docker-compose.yml"
# Record already names $DIGEST as deployed: re-deploying it is redundant.
write_record_fixture "" "" "" ""
OUT="$TMP/b1.out"; mkdir -p "$OUT"
PATH="$STUB:$PATH" LEMDROP_READY_TIMEOUT=1 LEMDROP_SEARCH_TIMEOUT=1 \
  "$DEPLOY" "$DIGEST" >"$TMP/b1.stdout" 2>"$TMP/b1.stderr"
RC=$?
check "redundant deploy exits 2 (EX_REFUSED), not 0" "$RC" "2"
has "$TMP/b1.stdout" "REDUNDANT DEPLOY — REFUSING" "refusal names the redundant deploy"
has "$TMP/b1.stdout" "$DIGEST" "refusal names the running digest"
has "$TMP/b1.stdout" "verify-deployment.sh" "refusal instructs the operator to use verification"
# The record must not be made self-referential: IMAGE_DIGEST unchanged,
# PREVIOUS_IMAGE_DIGEST still empty.
check "IMAGE_DIGEST still names the original digest" \
  "$(grep '^IMAGE_DIGEST=' "$RECORD_FILE")" "IMAGE_DIGEST=$DIGEST"
check "PREVIOUS_IMAGE_DIGEST still empty (not self-referential)" \
  "$(grep '^PREVIOUS_IMAGE_DIGEST=' "$RECORD_FILE")" "PREVIOUS_IMAGE_DIGEST="
# Nothing else in the record changed: it is still well-formed.
check "record still valid after the refused deploy" \
  "$(record_is_valid "$RECORD_FILE" >/dev/null 2>&1 && echo valid || echo invalid)" "valid"

# ── 3. B1 negative control: a different digest is NOT refused as redundant ────
printf '\n[3] B1 negative control: different digest is not refused as redundant\n'
PATH="$STUB:$PATH" "$DEPLOY" "$OTHER_DIGEST" >"$TMP/b1neg.stdout" 2>&1
RC=$?
check "different digest produces no REDUNDANT DEPLOY refusal" \
  "$(grep -c 'REDUNDANT DEPLOY — REFUSING' "$TMP/b1neg.stdout")" "0"
[ "$RC" != "0" ] && ok "different digest fails at a later stage (not as redundant)" \
  || bad "different digest exited 0 unexpectedly"

# ── 4. B2 regression: legacy rollback branch refuses ──────────────────────────
printf '\n[4] B2: legacy rollback branch refuses, cannot resolve to digest default\n'
# A record with no previous digest but a rollback tag routes rollback to the
# legacy branch, which must refuse rather than start the digest-pinned default.
write_record_fixture "" "" "" "lemondrop-api:rollback-20260101T000000Z"
# .env carries an API_IMAGE pin the legacy branch would otherwise strip.
printf 'API_IMAGE=%s\n' "$DIGEST" > "$APP_DIR/.env"
PATH="$STUB:$PATH" "$ROLLBACK" >"$TMP/b2.stdout" 2>&1
RC=$?
check "legacy rollback exits 2 (EX_REFUSED), not 0" "$RC" "2"
has "$TMP/b2.stdout" "REFUSING: legacy M3 rollback branch" "legacy refusal is emitted"
has "$TMP/b2.stdout" "incompatible with this compose file" "names the compose-file incompatibility"
has "$TMP/b2.stdout" "docker-compose.yml:436" "names the digest-pinned default"
has "$TMP/b2.stdout" "Nothing has been changed" "refusal states nothing was changed"
# .env must be untouched: API_IMAGE still present (not stripped to the default).
check ".env still carries API_IMAGE (legacy branch did not strip it)" \
  "$(grep -c '^API_IMAGE=' "$APP_DIR/.env")" "1"

# ── 5. verify-deployment.sh with no usable record ─────────────────────────────
printf '\n[5] verify-deployment.sh: no usable record is a clear non-zero result\n'
# No record file at all.
rm -f "$RECORD_FILE"
touch "$APP_DIR/.env"
PATH="$STUB:$PATH" "$VERIFY" >"$TMP/b3.stdout" 2>&1
RC=$?
check "verify exits non-zero (EX_FAILED=3) with no usable record" "$RC" "3"
has "$TMP/b3.stdout" "NO USABLE RECORD" "verdict names the missing record"
has "$TMP/b3.stdout" "Cannot compare" "verdict states record and running image cannot be compared"
if grep -qE 'VERDICT: [1-9] problem' "$TMP/b3.stdout"; then
  ok "verdict reports a non-zero problem count"
else
  bad "verdict problem count reads zero"
fi

printf '\ntest-deploy-rollback.sh: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 3
exit 0
