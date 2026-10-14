#!/usr/bin/env bash
#
# lemondrop — read-only diagnostic report. (M4 Stage 6, the Linux/WSL half.)
#
#   ./scripts/diagnose.sh [--base-url URL] [--report-dir DIR] [--selftest]
#
# ── THE BOUNDARY. READ THIS BEFORE ADDING A LINE TO THIS FILE ─────────────────
# READ-ONLY. It deploys nothing, adopts nothing, rolls back nothing, restarts
# nothing, pulls nothing and mutates nothing. The only file it writes is the one
# report it was asked to write.
#
# IT DOES NOT REIMPLEMENT THE VERDICT LOGIC. scripts/verify-deployment.sh owns the
# three verdicts AGREE / DIVERGENCE / UNPINNED (LEGACY) and owns comparing the
# revision record to the running image. This script emits none of those three
# strings, reads no record, compares nothing, and calls none of deploy.sh,
# rollback.sh or verify-deployment.sh. A fourth verdict belongs THERE, not here.
#
# IT DOES NOT RUN THE KNOWN-GOOD SEARCH. That probe is a POST to /search, and over
# the ALB it hits the documented 60 s idle-timeout vs ~240 s mismatch (docs/
# deployment.md §10 item 4), so from some vantage points it would report a timeout
# as a fault. It belongs to verify_stack() in deploy-lib.sh.
#
# NO CREDENTIALS, EVER. No token parameter, no environment dump, no raw response
# body in the report: only the status code, the latency, and a fixed allowlist of
# the four ReadinessResponse fields. A future maintainer wanting to add a token
# must not — a diagnostic report is the file most likely to be pasted into a
# ticket. (The one inherited `.env` access is api_base_url()'s API_HOST_PORT port
# lookup, reused so the URL precedence cannot drift. It is a port.) NO TLS CODE:
# the API is plain HTTP here, and that is the moment TLS config would belong.

set -Eeuo pipefail
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/deploy-lib.sh
. "$_SCRIPT_DIR/lib/deploy-lib.sh"

# Exit codes are deploy-lib.sh's, not new ones: EX_OK, EX_REFUSED, EX_FAILED. 1 is
# deliberately unused — on PowerShell an uncaught error exits 1, and reserving it
# would make a crash indistinguishable from a designed outcome. EX_REFUSED = "I
# declined to run" (no report); EX_FAILED = "I ran and found something" (report
# written). Do not collapse those two.
: "${LEMDROP_DIAGNOSE_DIR:=${LEMDROP_STATE_DIR}/diagnostics}"
BASE_URL=""; REPORT_DIR=""; DO_SELFTEST=0; PROBLEMS=0
note_problem() { PROBLEMS=$((PROBLEMS + 1)); say "  !! $*"; }
refuse()       { printf 'diagnose.sh: REFUSED: %s\n' "$*" >&2; exit "$EX_REFUSED"; }
now_utc()      { date -u +%Y-%m-%dT%H:%M:%SZ; }
stamp_file()   { date -u +%Y%m%dT%H%M%SZ; }   # colons are illegal in a Windows name

# Reject anything that is not a plain http/https URL with no userinfo. The
# credentials case is the one that matters: a base URL carrying user:pass@ would
# otherwise be printed verbatim into a report file.
validate_base_url() {
  local url="$1" rest authority
  [ -n "$url" ] || { say "  empty"; return 1; }
  case "$url" in *[[:space:]]*) say "  contains whitespace"; return 1 ;; esac
  case "$url" in http://*|https://*) ;; *) say "  scheme is not http:// or https://"; return 1 ;; esac
  rest="${url#*://}"; authority="${rest%%/*}"
  case "$authority" in *@*) say "  carries embedded credentials (user:password@)"; return 1 ;; esac
  return 0
}

selftest() {
  local fails=0 ts fn
  check()  { if [ "$2" = "$3" ]; then say "  ok   $1"; else say "  FAIL $1: got '$2', want '$3'"; fails=$((fails + 1)); fi; }
  rejects() { if validate_base_url "$1" >/dev/null 2>&1; then say "  FAIL $2: accepted '$1'"; fails=$((fails + 1)); else say "  ok   $2 rejects '$1'"; fi; }
  ts="$(now_utc)"; fn="diagnose-$(stamp_file).txt"
  check "timestamp is ISO-8601 UTC" "$(printf '%s' "$ts" | grep -cE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')" "1"
  check "filename shape"             "$(printf '%s' "$fn" | grep -cE '^diagnose-[0-9]{8}T[0-9]{6}Z\.txt$')" "1"
  check "filename has no colon"      "$(printf '%s' "$fn" | grep -c ':')" "0"
  check "accepts http loopback"      "$(validate_base_url 'http://127.0.0.1:8000' >/dev/null 2>&1 && echo ok)" "ok"
  check "accepts https"              "$(validate_base_url 'https://example.invalid' >/dev/null 2>&1 && echo ok)" "ok"
  rejects 'http://user:pass@example.invalid' 'embedded credentials'
  rejects 'http://exa mple.invalid'            'whitespace'
  rejects 'ftp://example.invalid'              'non-http scheme'
  rejects '127.0.0.1:8000'                     'missing scheme'
  say "diagnose.sh --selftest: $([ "$fails" -eq 0 ] && echo PASS || echo FAIL) ($fails failure(s))"
  [ "$fails" -eq 0 ] || exit "$EX_FAILED"
  exit "$EX_OK"
}
while [ $# -gt 0 ]; do
  case "$1" in
    --base-url)    [ $# -ge 2 ] || refuse "--base-url needs a value"; BASE_URL="$2"; shift 2 ;;
    --base-url=*)  BASE_URL="${1#*=}"; shift ;;
    --report-dir)  [ $# -ge 2 ] || refuse "--report-dir needs a value"; REPORT_DIR="$2"; shift 2 ;;
    --report-dir=*) REPORT_DIR="${1#*=}"; shift ;;
    --selftest)    DO_SELFTEST=1; shift ;;
    -h|--help)     say "usage: $0 [--base-url URL] [--report-dir DIR] [--selftest]"; exit "$EX_OK" ;;
    *)             refuse "unknown argument: $1" ;;
  esac
done
[ "$DO_SELFTEST" -eq 0 ] || selftest
# Precedence is api_base_url()'s: --base-url, else LEMDROP_API_BASE_URL, else
# http://127.0.0.1:${API_HOST_PORT:-8000}. Only the flag is handled here.
[ -n "$BASE_URL" ] || BASE_URL="$(api_base_url)"
validate_base_url "$BASE_URL" || refuse "base URL is not usable: $BASE_URL"
[ -n "$REPORT_DIR" ] || REPORT_DIR="$LEMDROP_DIAGNOSE_DIR"
case "$REPORT_DIR" in "$_SCRIPT_DIR"/*|"$_SCRIPT_DIR") refuse "report dir is inside the checkout ($REPORT_DIR); diagnostics live outside it, same reason the record does" ;; esac
LINES=()
r() { LINES+=("$1"); say "$1"; }
probe() {  # sets P_CODE, P_MS and PROBE_BODY
  local out body; body="$(mktemp)"; PROBE_BODY="$body"
  if ! command -v curl >/dev/null 2>&1; then P_CODE=000; P_MS=0; return 1; fi
  out="$(curl -sS -o "$body" -w '%{http_code} %{time_total}' --max-time 10 "$BASE_URL$1" 2>/dev/null)" || true
  P_CODE="${out%% *}"; [ -n "$P_CODE" ] || P_CODE=000
  P_MS="$(awk -v t="${out##* }" 'BEGIN{printf "%d", (t+0)*1000}')"
}
r "lemondrop diagnostic report"
r "format: lemondrop-diagnostic/1"
r "── diagnostic ──"
r "  script        : diagnose.sh (bash)"
r "  generated(UTC): $(now_utc)"
r "  host          : $(hostname 2>/dev/null || echo unknown)"
r "  base url      : $BASE_URL"
r "  http transport: $(command -v curl 2>/dev/null || echo 'curl NOT FOUND on PATH')"
r "── service status ──"
r "  vantage: docker container state, read from the host that runs the stack."
CID=""
if ! command -v docker >/dev/null 2>&1 || ! docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
  r "  docker CLI absent, or no reachable daemon — no container state collected."
  note_problem "docker is unusable here, so container state was not collected"
else
  CID="$(docker ps -q --filter "label=com.docker.compose.project=$LEMDROP_COMPOSE_PROJECT" --filter "label=com.docker.compose.service=api" 2>/dev/null | head -n 1)"
  docker ps --filter "label=com.docker.compose.project=$LEMDROP_COMPOSE_PROJECT" --format '  {{.Names}} | {{.State}} | {{.Status}}' 2>/dev/null \
    || r "  (no containers for project $LEMDROP_COMPOSE_PROJECT)"
  if [ -n "$CID" ]; then
    r "  api: $(docker inspect -f 'state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}' "$CID" 2>/dev/null)"
    r "  api image id: $(docker image inspect -f '{{.Id}}' "$(docker inspect -f '{{.Image}}' "$CID" 2>/dev/null)" 2>/dev/null)"
  else
    r "  no api container is running for project '$LEMDROP_COMPOSE_PROJECT'."
    note_problem "no api container is running for project '$LEMDROP_COMPOSE_PROJECT'"
  fi
fi
r "── health endpoints ──"
probe /health/live
r "  GET /health/live  : http ${P_CODE}, ${P_MS} ms"
[ "$P_CODE" = "200" ] || note_problem "/health/live answered ${P_CODE}, not 200"
probe /health/ready
r "  GET /health/ready : http ${P_CODE}, ${P_MS} ms"
[ "$P_CODE" = "200" ] || note_problem "/health/ready answered ${P_CODE}, not 200"
r "── readiness fields ──"
# ReadinessResponse (api/app/main.py): these four fields, an allowlist not a dump.
for f in status embedder reranker database; do
  v="$(grep -o "\"$f\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$PROBE_BODY" 2>/dev/null | head -n 1 | sed 's/.*:[[:space:]]*"\(.*\)"$/\1/')"
  r "  $(printf '%-14s' "$f"): ${v:-<not present>}"
  [ "$v" = "ok" ] || note_problem "readiness field '$f' is '${v:-<absent>}', not 'ok'"
done
rm -f "$PROBE_BODY"
r "── scope ──"
r "  COMPARISON NOT PERFORMED. The revision record was not read and nothing was"
r "  compared. The three record-vs-image verdicts belong to verify-deployment.sh"
r "  and this script emits none of them (they are named in its header comment)."
r "  Not run: the known-good search (a POST to /search; see this file's header)."
r "  No TLS: this deployment is plain HTTP."
r "  problems found: $PROBLEMS (0 = clean, >0 = see the !! lines above)"
mkdir -p "$REPORT_DIR" 2>/dev/null || refuse "report dir '$REPORT_DIR' cannot be created"
REPORT_PATH="$REPORT_DIR/diagnose-$(stamp_file).txt"
printf '%s\n' "${LINES[@]}" > "$REPORT_PATH" || refuse "report dir '$REPORT_DIR' is not writable; no report produced"
say ""
say "report written: $REPORT_PATH"
if [ "$PROBLEMS" -eq 0 ]; then exit "$EX_OK"; fi
exit "$EX_FAILED"
