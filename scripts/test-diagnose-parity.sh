#!/usr/bin/env bash
#
# Cross-language heading parity for the Stage 6 diagnostics. (M4 Stage 6.)
#
#   ./scripts/test-diagnose-parity.sh
#
# WHY THIS EXISTS, IN ONE PARAGRAPH. diagnose.sh and diagnose.ps1 are two
# implementations of one report, written in two languages, maintained by people
# who may never read the other file. Values legitimately differ — the Bash half
# sees docker containers, the PowerShell half has no docker — but the SHAPE may
# not. Two reports with the same name and different section order are a report
# format that has forked, and a fork is invisible until someone diffs them by
# hand. This test extracts the ordered `── heading ──` list from one real report
# of each kind and asserts they are identical. It is the anti-drift control.
#
# WHERE IT LIVES AND WHY: scripts/, beside the two scripts it compares, rather
# than in the PowerShell test or the Bash test. Either of those could be run
# without the other being run at all, and this is precisely the check that must
# not be optional in half of its cases.
#
# IT NEEDS pwsh. Without it the test SKIPS, loudly and with a non-zero exit
# distinguishable from a pass, rather than silently doing nothing — a parity gate
# that quietly passes when it could not run is worse than no gate.

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }

if ! command -v pwsh >/dev/null 2>&1; then
  bad "pwsh is not on PATH, so the PowerShell half could not be compared."
  printf '\ntest-diagnose-parity.sh: %d passed, %d failed (SKIPPED - no pwsh)\n' "$PASS" "$FAIL"
  exit 3
fi

# Same stubs as test-diagnose.sh, and the same fixture shape: the point is that
# BOTH reports describe the same healthy service, so any heading difference is a
# format difference and not a data difference.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=""; url=""; prev=""
for a in "$@"; do
  case "$prev" in -o) out="$a" ;; esac
  case "$a" in http*) url="$a" ;; esac
  prev="$a"
done
body=""; code=000
case "$url" in
  */health/live)  code=200; body='{"status":"ok"}' ;;
  */health/ready) code=200; body='{"status":"ok","embedder":"ok","reranker":"ok","database":"ok"}' ;;
esac
[ -n "$out" ] && printf '%s' "$body" > "$out"
printf '%s %s' "$code" "0.012"
EOF
cat > "$TMP/bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  version) printf '29.8.2\n' ;;
  ps) case " $* " in *" -q "*) printf 'c0ffee1234567890\n' ;; *) printf 'lemondrop-api-1 | running | Up 3 hours (healthy)\n' ;; esac ;;
  inspect) case " $* " in *"{{.Image}}"*) printf 'sha256:abc123\n' ;; *"{{.State.Status}}"*) printf 'state=running health=healthy restarts=0\n' ;; *) printf '' ;; esac ;;
  image) printf 'sha256:deadbeef\n' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$TMP/bin/curl" "$TMP/bin/docker"

mkdir -p "$TMP/fx" "$TMP/bash" "$TMP/ps"
printf '200\n{"status":"ok"}\n' > "$TMP/fx/health_live.txt"
printf '200\n{"status":"ok","embedder":"ok","reranker":"ok","database":"ok"}\n' > "$TMP/fx/health_ready.txt"

PATH="$TMP/bin:$PATH" "$HERE/diagnose.sh" --base-url http://127.0.0.1:8000 --report-dir "$TMP/bash" >/dev/null 2>&1
BASH_REPORT="$(find "$TMP/bash" -name 'diagnose-*.txt' | head -n 1)"
LEMDROP_DIAGNOSE_HTTP_STUB="$TMP/fx" pwsh -NoProfile -File "$HERE/diagnose.ps1" -ReportDir "$TMP/ps" >/dev/null 2>&1
PS_REPORT="$(find "$TMP/ps" -name 'diagnose-*.txt' | head -n 1)"

if [ -z "$BASH_REPORT" ] || [ -z "$PS_REPORT" ]; then
  bad "could not produce both reports (bash='${BASH_REPORT:-none}' ps='${PS_REPORT:-none}')"
  printf '\ntest-diagnose-parity.sh: %d passed, %d failed\n' "$PASS" "$FAIL"
  exit 3
fi

# The heading is whatever sits between the ── fences, so the padding width is
# free and cannot itself cause a spurious difference.
grep -o '── [^─]*──' "$BASH_REPORT" | sed 's/── //; s/ ──$//' > "$TMP/bash.headings"
grep -o '── [^─]*──' "$PS_REPORT"   | sed 's/── //; s/ ──$//' > "$TMP/ps.headings"

printf '\n  bash headings:\n'; sed 's/^/    /' "$TMP/bash.headings"
printf '  powershell headings:\n'; sed 's/^/    /' "$TMP/ps.headings"
printf '\n'

if diff -u "$TMP/bash.headings" "$TMP/ps.headings" > "$TMP/diff"; then
  ok "the two implementations emit the SAME ordered section headings ($(wc -l < "$TMP/bash.headings" | tr -d ' ') sections)"
else
  bad "the two implementations have drifted apart:"
  sed 's/^/    /' "$TMP/diff"
fi

# And the two things both must carry, checked on the PAIR rather than per file.
cat "$BASH_REPORT" "$PS_REPORT" > "$TMP/both"
for token in "format: lemondrop-diagnostic/1" "COMPARISON NOT PERFORMED"; do
  if [ "$(grep -cF "$token" "$TMP/both")" = "2" ]; then ok "both reports carry '$token'"
  else bad "expected exactly 2 occurrences of '$token' across both reports"; fi
done
if grep -qE 'AGREE|DIVERGENCE|UNPINNED' "$TMP/both"; then
  bad "a verdict string from verify-deployment.sh appears in a diagnostic report"
else
  ok "neither report contains any record-vs-image verdict string"
fi

printf '\ntest-diagnose-parity.sh: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 3
exit 0
