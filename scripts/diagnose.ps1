#Requires -Version 5.1
#
# lemondrop — read-only diagnostic report. (M4 Stage 6, the Windows half.)
#
#   .\scripts\diagnose.ps1 [-BaseUrl URL] [-ReportDir DIR] [-SelfTest]
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
# ticket. NO TLS CODE: the API is plain HTTP here, and that is the moment TLS
# configuration would belong.
#
# ── WHY THIS FILE HAS NO DOCKER ───────────────────────────────────────────────
# It runs on a Windows workstation where the stack is NOT. Docker Desktop would
# describe a machine that has no containers to describe, so every real
# deployment would record an empty container list — a confident false negative,
# which is worse than no data. So service status here is the application's own
# `/health/ready` verdict, labelled as such, and container-level state is
# `scripts/diagnose.sh`'s job on the host. The absence of a container list below
# is NOT a finding, and this script never reports it as one.
#
# ── WHICH POWERSHELL WAS TESTED, AND WHICH WAS ONLY WRITTEN FOR ───────────────
# EXECUTED: PowerShell 7.4.6 on Linux (pwsh), plus the Bash half of Stage 6.
# WRITTEN FOR BUT NOT EXECUTED: Windows PowerShell 5.1. It cannot run on Linux
# at all, so nothing in this file has been proven to work on it. The constructs
# that differ between the two, and that the 5.1 target drives here, are:
#   * report encoding — 5.1's `Out-File` defaults to UTF-16LE, so the report is
#     written with [System.IO.File]::WriteAllText and an explicit UTF8Encoding
#     ($false, no BOM). `Out-File` is never used.
#   * non-2xx handling — 5.1's `Invoke-WebRequest` THROWS on a 503. For a
#     diagnostic a 503 is the normal case and is a finding, not a crash, so the
#     status code is read out of the caught exception's Response (Get-StatusCode
#     below) and recorded. Both the extraction and the end-to-end 503 path are
#     covered by scripts/test-diagnose.ps1.
#   * `-UseBasicParsing` is passed everywhere a 5.1 parse of HTML could matter.
# If a construct is added that only 5.1 or only 7 has, say so here rather than
# letting a green 7.x run stand in for a version nothing ran on.

[CmdletBinding()]
param(
    [string]$BaseUrl,
    [string]$ReportDir,
    [switch]$SelfTest
)

# deploy-lib.sh's EX_* values, restated because a .ps1 cannot source a .sh. They
# are a contract with deploy.sh/rollback.sh/verify-deployment.sh, not a local
# invention. 1 is deliberately UNUSED: on PowerShell an uncaught error exits 1,
# and reserving it would make a crash indistinguishable from a designed outcome.
$EX_OK = 0; $EX_REFUSED = 2; $EX_FAILED = 3
$ALLOWLIST = @('status', 'embedder', 'reranker', 'database')   # ReadinessResponse
$ReportFormat = 'lemondrop-diagnostic/1'

function Say([string]$m) { Write-Output $m }

# Invariant formatting throughout: the report is a UTC artefact and must not
# pick up a machine's regional date or time settings.
function Get-UtcStamp { (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', [Globalization.CultureInfo]::InvariantCulture) }
function Get-FileStamp { (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ', [Globalization.CultureInfo]::InvariantCulture) }

# Returns a BOOLEAN ONLY, and the reason in $script:UrlReason.
#
# WHY: a PowerShell function returns EVERYTHING it writes uncaptured, so a
# `Say '  contains whitespace'; return $false` returns a two-element ARRAY, and
# `if (Test-BaseUrl $u)` on a non-empty array is TRUE. That makes the function
# accept everything while appearing to work. Caught by -SelfTest, not by reading.
function Test-BaseUrl([string]$url) {
    if ([string]::IsNullOrWhiteSpace($url)) { $script:UrlReason = 'empty'; return $false }
    if ($url -match '\s') { $script:UrlReason = 'contains whitespace'; return $false }
    if ($url -notmatch '^(?i)https?://') { $script:UrlReason = 'scheme is not http:// or https://'; return $false }
    # The userinfo check is the one that matters: a base URL carrying
    # user:password@ would otherwise be printed verbatim into a report file.
    # Note the double parentheses: indexing a parenthesised expression directly
    # (`(expr)[0]`) parses on PowerShell 7 and FAILS on 5.1, so it is written the
    # way that parses on both.
    $authority = ((($url -replace '^(?i)https?://', '') -split '/')[0])
    if ($authority.Contains('@')) { $script:UrlReason = 'carries embedded credentials (user:password@)'; return $false }
    $script:UrlReason = 'ok'
    return $true
}

# 5.1 throws WebException with .Response.StatusCode; 7 throws
# HttpResponseException with .Response.StatusCode. Both have .Response, so one
# walk of the exception chain covers each without a version check. Returns 0
# when there is no status at all (connection refused) — that is 000, not a guess.
function Get-StatusCode($err) {
    $ex = if ($err -and $err.PSObject.Properties['Exception']) { $err.Exception } else { $err }
    while ($null -ne $ex) {
        if ($null -ne $ex.PSObject.Properties['Response'] -and $null -ne $ex.Response) {
            try { return [int]$ex.Response.StatusCode } catch { return 0 }
        }
        $ex = $ex.InnerException
    }
    return 0
}

# One HTTP GET. Returns @{ Code; Ms; Body }.
#
# THE STUB SEAM. LEMDROP_DIAGNOSE_HTTP_STUB points at a directory of fixture
# files, named after the path (`health_live.txt`, `health_ready.txt`), first
# line the status code and the rest the body. It exists so this script can be
# executed end to end with no network and no service, and the report PRINTS that
# it is in use, so a stubbed run can never be read as a real one. That is the
# same substitution the Bash half gets from putting a stub `curl` on PATH.
function Invoke-HealthGet([string]$url) {
    if ($env:LEMDROP_DIAGNOSE_HTTP_STUB) {
        $name = (($url -replace '^(?i)https?://[^/]+', '') -replace '^/', '' -replace '/', '_')
        $file = Join-Path $env:LEMDROP_DIAGNOSE_HTTP_STUB "$name.txt"
        if (-not (Test-Path $file)) { return @{ Code = 0; Ms = 0; Body = '' } }
        $raw = @(Get-Content -LiteralPath $file)
        return @{ Code = [int]$raw[0]; Ms = 0; Body = (($raw | Select-Object -Skip 1) -join '') }
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        $sw.Stop()
        # Invoke-RestMethod would parse the JSON but discards the status code and
        # the timing, which are two of the four things this report exists to say.
        return @{ Code = [int]$resp.StatusCode; Ms = $sw.ElapsedMilliseconds; Body = [string]$resp.Content }
    } catch {
        $sw.Stop()
        return @{ Code = (Get-StatusCode $_); Ms = $sw.ElapsedMilliseconds; Body = '' }
    }
}

# Report-line helpers. They live above -SelfTest because -SelfTest asserts on
# AddLine's command type, and PowerShell must be able to resolve the name by
# then. Named AddLine/AddProblem, never a bare letter: see the -SelfTest alias
# check, which exists because the first version of this file used `R`.
function AddLine([string]$s) { [void]$lines.Add($s); Say $s }
function AddProblem([string]$s) { $script:Problems++; Say "  !! $s" }

function Invoke-SelfTest {
    # $script:Fails, not a local: `Ok` and `Rejects` are functions in their own
    # right, and a local $fails would be invisible to them. A counter that does
    # not count reports PASS beside visible FAILs - which is the exact
    # "green that means nothing" this suite is written against.
    $script:Fails = 0
    function Ok($n, $c) { if ($c) { Say "  ok   $n" } else { Say "  FAIL $n"; $script:Fails++ } }
    function Rejects($u, $n) { if (Test-BaseUrl $u) { Say ("  FAIL {0}: accepted '{1}'" -f $n, $u); $script:Fails++ } else { Say ("  ok   {0} rejects '{1}' ({2})" -f $n, $u, $script:UrlReason) } }
    Ok 'timestamp is ISO-8601 UTC'  ((Get-UtcStamp) -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
    $fn = "diagnose-$(Get-FileStamp).txt"
    Ok 'filename shape'        ($fn -match '^diagnose-\d{8}T\d{6}Z\.txt$')
    Ok 'filename has no colon' (-not $fn.Contains(':'))
    Ok 'accepts http loopback' (Test-BaseUrl 'http://127.0.0.1:8000')
    Ok 'accepts https'         (Test-BaseUrl 'https://example.invalid')
    Rejects 'http://user:pass@example.invalid' 'embedded credentials'
    Rejects 'http://exa mple.invalid'            'whitespace'
    Rejects 'ftp://example.invalid'              'non-http scheme'
    Rejects '127.0.0.1:8000'                     'missing scheme'
    # The 5.1 hazard, in isolation: an error record shaped the way 5.1 throws
    # (WebException.Response.StatusCode) must yield 503, not 0 and not a crash.
    $shaped = [pscustomobject]@{ Exception = [pscustomobject]@{
        Response = [pscustomobject]@{ StatusCode = [int]503 } } }
    Ok 'a 5.1-shaped non-200 exception yields its status, not a crash' ((Get-StatusCode $shaped) -eq 503)
    Ok 'an exception with no response yields 000' ((Get-StatusCode ([pscustomobject]@{ Exception = [pscustomobject]@{} })) -eq 0)
    # PowerShell resolves ALIAS before FUNCTION, so a helper named after a built-in
    # alias (`r` is Invoke-History) is silently never called and the script writes
    # an empty report while exiting 0. This is not hypothetical: it is what this
    # check was added for, after the first version of this file did exactly that.
    Ok 'the report-line helper is a function and not a shadowed alias' ((Get-Command AddLine).CommandType -eq 'Function')
    Say "diagnose.ps1 -SelfTest: $(if ($script:Fails -eq 0) { 'PASS' } else { 'FAIL' }) ($($script:Fails) failure(s))"
    if ($script:Fails -ne 0) { exit $EX_FAILED }
    exit $EX_OK
}

if ($SelfTest) { Invoke-SelfTest }

# Precedence matches api_base_url() in scripts/lib/deploy-lib.sh: -BaseUrl, else
# LEMDROP_API_BASE_URL, else http://127.0.0.1:${API_HOST_PORT:-8000}.
if (-not $BaseUrl) {
    if ($env:LEMDROP_API_BASE_URL) { $BaseUrl = $env:LEMDROP_API_BASE_URL }
    else {
        $port = if ($env:API_HOST_PORT) { $env:API_HOST_PORT } else { '8000' }
        $BaseUrl = "http://127.0.0.1:$port"
    }
}
if (-not (Test-BaseUrl $BaseUrl)) {
    Write-Error "diagnose.ps1: REFUSED: base URL is not usable ($($script:UrlReason)): $BaseUrl"
    exit $EX_REFUSED
}
if (-not $ReportDir) {
    $ReportDir = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'lemondrop\diagnostics' }
                 else { Join-Path ([IO.Path]::GetTempPath()) 'lemondrop-diagnostics' }
}
if ((Resolve-Path -LiteralPath $ReportDir -ErrorAction SilentlyContinue) -and
    ((Resolve-Path -LiteralPath $ReportDir).Path -like "$((Resolve-Path $PSScriptRoot).Path)*")) {
    Write-Error "diagnose.ps1: REFUSED: report dir is inside the checkout ($ReportDir); diagnostics live outside it, same reason the record does"
    exit $EX_REFUSED
}

$script:Problems = 0; $lines = New-Object System.Collections.ArrayList
AddLine 'lemondrop diagnostic report'
AddLine "format: $ReportFormat"
AddLine '── diagnostic ──'
AddLine '  script        : diagnose.ps1 (PowerShell)'
AddLine "  generated(UTC): $(Get-UtcStamp)"
AddLine "  host          : $(if ($env:COMPUTERNAME) { $env:COMPUTERNAME } elseif ($env:HOSTNAME) { $env:HOSTNAME } else { 'unknown' })"
AddLine "  base url      : $BaseUrl"
AddLine "  http transport: $(if ($env:LEMDROP_DIAGNOSE_HTTP_STUB) { "STUB FIXTURES from $env:LEMDROP_DIAGNOSE_HTTP_STUB - NOT A REAL RUN" } else { 'Invoke-WebRequest (System.Net)' })"
AddLine '── service status ──'
# These lines make the vantage point impossible to misread. There is no
# docker here, and the absence of a container list is not a finding.
AddLine '  vantage: /health/ready fields only - no docker access from this machine.'
AddLine '  note   : container-level state is NOT reported here and its absence is NOT a'
AddLine '           finding. Run scripts/diagnose.sh on the EC2 host for that.'
$live = Invoke-HealthGet "$BaseUrl/health/live"
$ready = Invoke-HealthGet "$BaseUrl/health/ready"
AddLine "  reported by the application: status=$($ready.Code -ge 200 -and $ready.Code -lt 300) (HTTP $($ready.Code))"
AddLine '── health endpoints ──'
AddLine "  GET /health/live  : http $($live.Code), $($live.Ms) ms"
if ($live.Code -ne 200) { AddProblem "/health/live answered $($live.Code), not 200" }
AddLine "  GET /health/ready : http $($ready.Code), $($ready.Ms) ms"
if ($ready.Code -ne 200) { AddProblem "/health/ready answered $($ready.Code), not 200" }
AddLine '── readiness fields ──'
# ReadinessResponse (api/app/main.py): these four fields and nothing else - an
# allowlist, not a dump. The raw body is never written to the report.
$parsed = $null
if ($ready.Body) { try { $parsed = $ready.Body | ConvertFrom-Json } catch { $parsed = $null } }
foreach ($f in $ALLOWLIST) {
    $v = if ($parsed -and $parsed.PSObject.Properties[$f]) { [string]$parsed.$f } else { '<not present>' }
    AddLine ("  {0,-14}: {1}" -f $f, $v)
    if ($v -ne 'ok') { AddProblem "readiness field '$f' is '$v', not 'ok'" }
}
AddLine '── scope ──'
AddLine '  COMPARISON NOT PERFORMED. The revision record was not read and nothing was'
AddLine '  compared. The three record-vs-image verdicts belong to verify-deployment.sh'
AddLine '  and this script emits none of them (they are named in its header comment).'
AddLine '  Not run: the known-good search (a POST to /search; see this file header).'
AddLine '  No TLS: this deployment is plain HTTP.'
AddLine "  problems found: $($script:Problems) (0 = clean, >0 = see the !! lines above)"

if (-not (Test-Path -LiteralPath $ReportDir)) {
    try { New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null }
    catch { Write-Error "diagnose.ps1: REFUSED: report dir '$ReportDir' cannot be created"; exit $EX_REFUSED }
}
$reportPath = Join-Path $ReportDir "diagnose-$(Get-FileStamp).txt"
try {
    # UTF-8 without a BOM, explicitly. 5.1's Out-File would write UTF-16LE.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($reportPath, (($lines -join [Environment]::NewLine) + [Environment]::NewLine), $utf8)
} catch {
    Write-Error "diagnose.ps1: REFUSED: report dir '$ReportDir' is not writable; no report produced"; exit $EX_REFUSED
}
Say ''
Say "report written: $reportPath"
if ($script:Problems -eq 0) { exit $EX_OK }
exit $EX_FAILED
