#!/usr/bin/env bash
#
# Tests for scripts/diagnose.sh (M4 Stage 6).
#
#   ./scripts/test-diagnose.sh
#
# No bats, no shunit, no framework: a plain script that prints ok/FAIL and exits
# non-zero on the first failure, so it is equally usable by a human and by CI.
#
# WHAT IT NEEDS: bash, coreutils, grep, awk, mktemp. What it must NOT need, and
# what it therefore proves it does not need: a docker daemon, a network, AWS,
# root. `curl` and `docker` are stubbed on PATH, which is why this runs in a
# clean checkout.
#
# THE THREE CONTROLS THAT MATTER, stated up front:
#   1. the BOUNDARY assertion — no AGREE / DIVERGENCE / UNPINNED may appear in the
#      stdout or the report. Those three strings are verify-deployment.sh's
#      verdicts; a diagnostic that emitted one would be reimplementing logic it
#      was told not to own, and it is the cheapest possible way to catch that.
#   2. the NEGATIVE CONTROL — a stubbed 503 must produce exit 3 AND a written
#      report. A gate that cannot return a bad result is untested.
#   3. the REFUSAL CONTROL — a bad URL must produce exit 2 AND no report at all,
#      because "I declined to run" and "I ran and found something" are different
#      answers and collapsing them is the bug this exists to prevent.

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$HERE/diagnose.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

ok()   { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got '$2', want '$3')"; fi; }
has()   { if grep -qF -- "$2" "$1"; then ok "$3"; else bad "$3 ('$2' not found)"; fi; }
hasnt() { if grep -qF -- "$2" "$1"; then bad "$3 ('$2' FOUND — boundary violated)"; else ok "$3"; fi; }

# ── The fixtures ──────────────────────────────────────────────────────────────
# Captured from the real service, not invented. The /health/ready body is
# ReadinessResponse (api/app/main.py): four string fields, in declaration order,
# serialised compactly on ONE line because that is what FastAPI does. A stub
# that diverged from this would give green tests over a broken script.
STUB="$TMP/bin"; mkdir -p "$STUB"

cat > "$STUB/curl" <<'STUBEOF'
#!/usr/bin/env bash
# Minimal curl stand-in: understands only the flags diagnose.sh actually passes.
out=""; url=""; prev=""
for a in "$@"; do
  case "$prev" in -o) out="$a" ;; esac
  case "$a" in http*) url="$a" ;; esac
  prev="$a"
done
body=""; code=000
case "$url" in
  */health/live)  code="${FIX_LIVE_CODE:-200}"  body='{"status":"ok"}' ;;
  */health/ready) code="${FIX_READY_CODE:-200}"
                  body="${FIX_READY_BODY:-{\"status\":\"ok\",\"embedder\":\"ok\",\"reranker\":\"ok\",\"database\":\"ok\"}}" ;;
esac
[ -n "$out" ] && printf '%s' "$body" > "$out"
printf '%s %s' "$code" "0.012"
STUBEOF

cat > "$STUB/docker" <<'STUBEOF'
#!/usr/bin/env bash
case "$1" in
  version) printf '29.8.2\n' ;;
  ps)      case " $* " in *" -q "*) printf 'c0ffee1234567890\n' ;; *)
             printf 'lemondrop-api-1 | running | Up 3 hours (healthy)\n' ;;
           esac ;;
  inspect) case " $* " in
             *"{{.Image}}"*) printf 'sha256:abc123\n' ;;
             *"{{.State.Status}}"*) printf 'state=running health=healthy restarts=0\n' ;;
             *) printf '' ;; esac ;;
  image)   printf 'sha256:deadbeef\n' ;;
  *) exit 1 ;;
esac
STUBEOF
chmod +x "$STUB/curl" "$STUB/docker"

# ── 1. Syntax ─────────────────────────────────────────────────────────────────
printf '\n[1] syntax\n'
if bash -n "$SUT" 2>"$TMP/syn"; then ok "bash -n scripts/diagnose.sh"; else bad "bash -n: $(cat "$TMP/syn")"; fi
if grep -qE '^[[:space:]]*(deploy\.sh|rollback\.sh|verify-deployment\.sh)' "$SUT"; then
  bad "diagnose.sh must never invoke a deploy/rollback/verify script"
else
  ok "diagnose.sh invokes none of deploy.sh / rollback.sh / verify-deployment.sh"
fi

# ── 2. Self-test ──────────────────────────────────────────────────────────────
printf '\n[2] self-test\n'
"$SUT" --selftest >"$TMP/st.out" 2>&1; check "--selftest exits 0" "$?" "0"
has "$TMP/st.out" "PASS" "--selftest reports PASS"

# ── 3. Stubbed end-to-end, healthy ────────────────────────────────────────────
printf '\n[3] stubbed end-to-end (healthy)\n'
OUT="$TMP/ok"; mkdir -p "$OUT"
PATH="$STUB:$PATH" "$SUT" --base-url http://127.0.0.1:8000 --report-dir "$OUT" >"$TMP/ok.out" 2>&1
RC=$?
REPORT="$(find "$OUT" -name 'diagnose-*.txt' | head -n 1)"
check "clean run exits 0 (EX_OK)" "$RC" "0"
[ -n "$REPORT" ] && ok "report file created: $(basename "$REPORT")" || { bad "no report file created"; REPORT="$TMP/ok.out"; }
has "$REPORT" "format: lemondrop-diagnostic/1" "report declares its format"
has "$REPORT" "COMPARISON NOT PERFORMED" "report marks the comparison as not performed"
has "$REPORT" "── readiness fields ──"   "report carries the readiness section"
has "$REPORT" "database      : ok"       "all four readiness fields parsed from the fixture body"
has "$REPORT" "GET /health/ready : http 200" "health endpoints recorded with status codes"
check "report filename has no colon" "$(basename "$REPORT" | grep -c ':')" "0"

printf '\n[4] the boundary: no verdict strings anywhere\n'
hasnt "$REPORT" "AGREE"     "no AGREE in the report"
hasnt "$REPORT" "DIVERGENCE" "no DIVERGENCE in the report"
hasnt "$REPORT" "UNPINNED"   "no UNPINNED in the report"
cat "$REPORT" "$TMP/ok.out" > "$TMP/both.txt"
hasnt "$TMP/both.txt" "AGREE"     "no AGREE in report or stdout"
hasnt "$TMP/both.txt" "DIVERGENCE" "no DIVERGENCE in report or stdout"
hasnt "$TMP/both.txt" "UNPINNED"   "no UNPINNED in report or stdout"

# ── 5. Negative control: a 503 is a FINDING, and the report still gets written ─
printf '\n[5] negative control (503 from /health/ready)\n'
BAD="$TMP/bad"; mkdir -p "$BAD"
PATH="$STUB:$PATH" FIX_READY_CODE=503 \
  FIX_READY_BODY='{"status":"degraded","embedder":"ok","reranker":"ok","database":"connect refused"}' \
  "$SUT" --base-url http://127.0.0.1:8000 --report-dir "$BAD" >"$TMP/bad.out" 2>&1
check "a 503 exits 3 (EX_FAILED), not 0" "$?" "3"
BREPORT="$(find "$BAD" -name 'diagnose-*.txt' | head -n 1)"
[ -n "$BREPORT" ] && ok "the report is STILL written on failure" || bad "no report written on failure"
has "$BREPORT" "GET /health/ready : http 503" "the 503 is recorded in the report"
has "$BREPORT" "database      : connect refused" "the degraded readiness field is recorded"
# Matched as a property, not a number: a 503 on /health/ready AND a non-'ok'
# database field are TWO findings, and pinning "1" would make this test fail the
# day a second check is added. What matters is that the counter is not zero.
if grep -qE 'problems found: [1-9]' "$BREPORT"; then ok "the problem counter is non-zero"; else bad "the problem counter still reads 0"; fi
hasnt "$BREPORT" "AGREE" "no AGREE on the failure path either"

printf '\n[6] refusal control: exit 2 and NO report\n'
REF="$TMP/ref"; mkdir -p "$REF"
PATH="$STUB:$PATH" "$SUT" --base-url 'http://user:pass@example.invalid' --report-dir "$REF" >"$TMP/ref.out" 2>&1
check "a base URL with credentials exits 2 (EX_REFUSED)" "$?" "2"
has "$TMP/ref.out" "credentials" "the refusal names the actual problem"
check "no report file was produced" "$(find "$REF" -name 'diagnose-*.txt' | wc -l | tr -d ' ')" "0"
PATH="$STUB:$PATH" "$SUT" --nonsense >/dev/null 2>&1
check "an unknown argument exits 2 (EX_REFUSED)" "$?" "2"

printf '\n[7] read-only: nothing is written outside the report dir\n'
PATH="$STUB:$PATH" "$SUT" --base-url http://127.0.0.1:8000 --report-dir "$OUT" >/dev/null 2>&1
check "no deploy log file was created" "$([ -e /var/log/lemondrop-deploy.log ] && echo yes || echo no)" "no"
check "no revision record was created" "$([ -e /var/lib/lemondrop/deployed-revision.env ] && echo yes || echo no)" "no"

printf '\ntest-diagnose.sh: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 3
exit 0
