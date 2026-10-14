#Requires -Version 5.1
#
# Tests for scripts/diagnose.ps1 (M4 Stage 6).
#
#   pwsh -NoProfile -File ./scripts/test-diagnose.ps1
#
# No Pester, no framework: a plain script that prints ok/FAIL and exits non-zero
# on failure, so a human and CI run the identical invocation.
#
# WHAT IT NEEDS: PowerShell. What it must NOT need, and what it therefore proves
# it does not need: a docker daemon, a network, AWS, root, or Windows. The HTTP
# layer is substituted through LEMDROP_DIAGNOSE_HTTP_STUB, the same substitution
# the Bash half gets from putting a stub `curl` on PATH.
#
# ── TESTED VERSIONS, STATED PLAINLY ───────────────────────────────────────────
# EXECUTED HERE: PowerShell 7.4.6 on Linux.
# NOT EXECUTED HERE: Windows PowerShell 5.1. It does not exist on Linux. The
# constructs it drives (UTF-8 report writing, the non-2xx throw) are covered
# below, but coverage here means "the logic was executed on 7", NOT "5.1 was
# verified". See the header of scripts/diagnose.ps1.

[CmdletBinding()] param()

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Sut = Join-Path $Here 'diagnose.ps1'
$script:Tmp = Join-Path ([IO.Path]::GetTempPath()) ("lemondrop-diag-test-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $script:Tmp -Force | Out-Null
$script:P = 0; $script:F = 0
function Ok($m) { $script:P++; Write-Output "  ok   $m" }
function Bad($m) { $script:F++; Write-Output "  FAIL $m" }
function Check($m, $got, $want) { if ("$got" -eq "$want") { Ok $m } else { Bad "$m (got '$got', want '$want')" } }
function Has($path, $needle, $m) { if (Select-String -LiteralPath $path -SimpleMatch -Quiet -Pattern $needle) { Ok $m } else { Bad "$m ('$needle' not found)" } }
function Hasnt($path, $needle, $m) { if (Select-String -LiteralPath $path -SimpleMatch -Quiet -Pattern $needle) { Bad "$m ('$needle' FOUND - boundary violated)" } else { Ok $m } }

# ── The fixtures ──────────────────────────────────────────────────────────────
# Captured from the real service. The /health/ready body is ReadinessResponse
# (api/app/main.py): four string fields in declaration order, serialised
# compactly on ONE line, because that is what FastAPI does. An invented
# approximation here would give green tests over a broken script.
$Healthy = Join-Path $script:Tmp 'healthy'
New-Item -ItemType Directory -Path $Healthy -Force | Out-Null
Set-Content -LiteralPath (Join-Path $Healthy 'health_live.txt') -Encoding utf8 -Value @('200', '{"status":"ok"}')
Set-Content -LiteralPath (Join-Path $Healthy 'health_ready.txt') -Encoding utf8 -Value @('200', '{"status":"ok","embedder":"ok","reranker":"ok","database":"ok"}')
$Degraded = Join-Path $script:Tmp 'degraded'
New-Item -ItemType Directory -Path $Degraded -Force | Out-Null
Set-Content -LiteralPath (Join-Path $Degraded 'health_live.txt') -Encoding utf8 -Value @('200', '{"status":"ok"}')
Set-Content -LiteralPath (Join-Path $Degraded 'health_ready.txt') -Encoding utf8 -Value @('503', '{"status":"degraded","embedder":"ok","reranker":"ok","database":"connect refused"}')

# Run the SUT in a child pwsh so its `exit` code is observable and its $lines
# cannot leak into this script's scope.
#
# The environment is set with [Environment]::SetEnvironmentVariable and restored
# afterwards, NOT with `Start-Process -Environment`: that parameter does not
# exist on Windows PowerShell 5.1, so using it would make this test itself
# un-runnable on the version it is here to support. A child process inherits the
# parent's environment, so this is the one form that works on both.
function Invoke-Sut([hashtable]$envs, [string[]]$sutArgs) {
    $saved = @{}
    foreach ($k in $envs.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k)
        [Environment]::SetEnvironmentVariable($k, $envs[$k])
    }
    try {
        $out = Join-Path $script:Tmp ("run-" + [Guid]::NewGuid().ToString('N').Substring(0, 6) + '.txt')
        $psi = @{
            FilePath               = (Get-Process -Id $PID).Path
            ArgumentList           = (@('-NoProfile', '-File', $Sut) + $sutArgs)
            NoNewWindow            = $true; Wait = $true; PassThru = $true
            RedirectStandardOutput = $out
            RedirectStandardError  = "$out.err"
        }
        $p = Start-Process @psi
        $stdout = (Get-Content -LiteralPath $out -Raw)
        $stderr = if (Test-Path "$out.err") { Get-Content -LiteralPath "$out.err" -Raw } else { '' }
        return @{ Code = $p.ExitCode; Out = $stdout; Err = $stderr }
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
    }
}

# ── 1. Parse ──────────────────────────────────────────────────────────────────
Write-Output "`n[1] parse"
$errs = $null; $toks = $null
[System.Management.Automation.Language.Parser]::ParseFile($Sut, [ref]$toks, [ref]$errs) | Out-Null
Check 'diagnose.ps1 parses with no errors' $(if ($errs) { $errs.Count } else { 0 }) 0
# #requires -Version 7.0 would exclude the Windows operator's own interpreter.
$src = Get-Content -LiteralPath $Sut -Raw
if ($src -match '#Requires\s+-Version\s+7') { Bad 'diagnose.ps1 must not require PowerShell 7' } else { Ok 'no #requires 7 floor' }
if ($src -match '#Requires\s+-Version\s+5\.1') { Ok 'declares the 5.1 floor it was written for' } else { Bad 'no #requires 5.1 floor declared' }

# ── 2. Self-test ──────────────────────────────────────────────────────────────
Write-Output "`n[2] self-test"
$r = Invoke-Sut @{} @('-SelfTest')
Check '-SelfTest exits 0' $r.Code 0
if ($r.Out -match 'PASS') { Ok '-SelfTest reports PASS' } else { Bad "-SelfTest did not report PASS`n$($r.Out)" }

# ── 3. Stubbed end-to-end, healthy ────────────────────────────────────────────
Write-Output "`n[3] stubbed end-to-end (healthy)"
$OutOk = Join-Path $script:Tmp 'ok'
$r = Invoke-Sut @{ LEMDROP_DIAGNOSE_HTTP_STUB = $Healthy } @('-ReportDir', $OutOk)
Check 'clean run exits 0 (EX_OK)' $r.Code 0
$report = @(Get-ChildItem -LiteralPath $OutOk -Filter 'diagnose-*.txt' -ErrorAction SilentlyContinue)[0]
if ($report) { Ok "report file created: $($report.Name)" } else { Bad 'no report file created'; $report = $null }
if ($report) {
    Has $report.FullName 'format: lemondrop-diagnostic/1' 'report declares its format'
    Has $report.FullName 'COMPARISON NOT PERFORMED'        'report marks the comparison as not performed'
    Has $report.FullName '── readiness fields ──'          'report carries the readiness section'
    Has $report.FullName 'database      : ok'              'all four readiness fields parsed from the fixture body'
    Has $report.FullName 'GET /health/ready : http 200'    'health endpoints recorded with status codes'
    Check 'report filename has no colon' ($report.Name -match ':') $false
    # The vantage point must be stated, or a reader sees an empty container list
    # and concludes the stack is down.
    Has $report.FullName 'no docker access from this machine' 'the report states it has no docker access'
    Has $report.FullName 'its absence is NOT a'                'the report says the missing container list is not a finding'

    Write-Output "`n[4] the boundary: no verdict strings anywhere"
    foreach ($v in @('AGREE', 'DIVERGENCE', 'UNPINNED')) { Hasnt $report.FullName $v "no $v in the report" }
    $both = Join-Path $script:Tmp 'both.txt'
    Set-Content -LiteralPath $both -Value ((Get-Content -LiteralPath $report.FullName -Raw) + $r.Out) -Encoding utf8
    foreach ($v in @('AGREE', 'DIVERGENCE', 'UNPINNED')) { Hasnt $both $v "no $v in report or stdout" }

    Write-Output "`n[5] encoding: UTF-8, no BOM, not UTF-16LE"
    $bytes = [System.IO.File]::ReadAllBytes($report.FullName)
    $bom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    Check 'report has no UTF-8 BOM' $bom $false
    $utf16 = ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE)
    Check 'report is not UTF-16LE (what 5.1 Out-File writes)' $utf16 $false
    Check 'report decodes as UTF-8 round-trip' ([Text.Encoding]::UTF8.GetString($bytes) -match 'format: lemondrop-diagnostic/1') $true
}

# ── 6. Negative control: a 503 is a FINDING, and the report is still written ──
Write-Output "`n[6] negative control (503 from /health/ready)"
$OutBad = Join-Path $script:Tmp 'bad'
$r = Invoke-Sut @{ LEMDROP_DIAGNOSE_HTTP_STUB = $Degraded } @('-ReportDir', $OutBad)
Check 'a 503 exits 3 (EX_FAILED), not 0' $r.Code 3
$badReport = @(Get-ChildItem -LiteralPath $OutBad -Filter 'diagnose-*.txt' -ErrorAction SilentlyContinue)[0]
if ($badReport) { Ok 'the report is STILL written on failure' } else { Bad 'no report written on failure' }
if ($badReport) {
    Has $badReport.FullName 'GET /health/ready : http 503' 'the 503 is recorded, not swallowed as a crash'
    Has $badReport.FullName 'database      : connect refused' 'the degraded readiness field is recorded'
    foreach ($v in @('AGREE', 'DIVERGENCE', 'UNPINNED')) { Hasnt $badReport.FullName $v "no $v on the failure path" }
}

# ── 7. Refusal control: exit 2 and NO report ─────────────────────────────────
Write-Output "`n[7] refusal control (exit 2, no report)"
$OutRef = Join-Path $script:Tmp 'ref'
$r = Invoke-Sut @{ LEMDROP_DIAGNOSE_HTTP_STUB = $Healthy } @('-BaseUrl', 'http://user:pass@example.invalid', '-ReportDir', $OutRef)
Check 'a base URL with credentials exits 2 (EX_REFUSED)' $r.Code 2
if ($r.Err -match 'credentials') { Ok 'the refusal names the actual problem' } else { Bad 'the refusal does not name the problem' }
Check 'no report file was produced' (@(Get-ChildItem -LiteralPath $OutRef -Filter 'diagnose-*.txt' -ErrorAction SilentlyContinue).Count) 0

Remove-Item -LiteralPath $script:Tmp -Recurse -Force -ErrorAction SilentlyContinue
Write-Output "`ntest-diagnose.ps1: $script:P passed, $script:F failed"
if ($script:F -ne 0) { exit 3 }
exit 0
