param(
  [Parameter(Mandatory = $true)]
  [string]$ReportName,
  [string]$IncludeRootName = "包干航线",
  [string]$RefreshToolRoot = $(if ($env:FR_REFRESH_TOOL_ROOT) { $env:FR_REFRESH_TOOL_ROOT } else { "" }),
  [string]$EdgeCdpUrl = $(if ($env:FR_CDP_URL) { $env:FR_CDP_URL } elseif ($env:OPM_EDGE_CDP_URL) { $env:OPM_EDGE_CDP_URL } else { "http://127.0.0.1:9222" }),
  [string]$EdgeProfileDir = $(if ($env:FR_EDGE_PROFILE_DIR) { $env:FR_EDGE_PROFILE_DIR } else { ".\fr_batch\edge_profile_nlquery" }),
  [string]$FallbackEdgeCdpUrl = "http://127.0.0.1:9222",
  [string]$FallbackEdgeProfileDir = $(if ($env:FR_FALLBACK_EDGE_PROFILE_DIR) { $env:FR_FALLBACK_EDGE_PROFILE_DIR } else { ".\fr_batch\edge_profile" }),
  [string]$OutputRoot = $(if ($env:FR_MIRROR_ROOT) { $env:FR_MIRROR_ROOT } elseif ($env:OPM_MIRROR_ROOT) { $env:OPM_MIRROR_ROOT } else { ".\fr_mirror" }),
  [string]$BatchRoot = $(if ($env:FR_BATCH_ROOT) { $env:FR_BATCH_ROOT } elseif ($env:OPM_BATCH_ROOT) { $env:OPM_BATCH_ROOT } else { ".\fr_batch" }),
  [ValidateSet("never","if_missing","always")]
  [string]$Overwrite = "always",
  [string]$Token = $(if ($env:FR_AUTH_TOKEN) { $env:FR_AUTH_TOKEN } elseif ($env:OPM_FINE_AUTH_TOKEN) { $env:OPM_FINE_AUTH_TOKEN } else { "" }),
  [string]$CasTicket = $(if ($env:OPM_CAS_TICKET) { $env:OPM_CAS_TICKET } else { "" }),
  [string]$FineRemember = "-1"
)

# FR_BASE_URL for FineReport server (used in fallback start URL)
$env:FR_BASE_URL = if ($env:FR_BASE_URL) { $env:FR_BASE_URL } elseif ($env:OPM_BASE_URL) { $env:OPM_BASE_URL } else { "http://localhost:8075/webroot/decision" }

$ErrorActionPreference = "Stop"
$cdpVersionUrl = ($EdgeCdpUrl.TrimEnd('/')) + "/json/version/"

# Force local CDP traffic to bypass any configured HTTP proxy.
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$env:ALL_PROXY = ""
$env:all_proxy = ""

$downloadScript = if ([string]::IsNullOrWhiteSpace($RefreshToolRoot)) { "" } else { Join-Path $RefreshToolRoot "scripts\invoke-opm-download.ps1" }
if ([string]::IsNullOrWhiteSpace($RefreshToolRoot)) {
  throw "Live refresh requires FR_REFRESH_TOOL_ROOT to point to a compatible incremental download tool. Offline query remains available without it."
}
if (-not (Test-Path $downloadScript)) {
  throw "Live refresh tool not found under FR_REFRESH_TOOL_ROOT. Expected script: scripts\invoke-opm-download.ps1"
}
$httpScript = Join-Path $BatchRoot "opm_batch_http.ps1"

function Test-EdgeCdpReady {
  param([string]$Url)
  try {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
    if ($resp.StatusCode -ne 200) { return $false }
    $txt = [string]$resp.Content
    return ($txt -match "webSocketDebuggerUrl" -or $txt -match "DevTools")
  } catch {
    return $false
  }
}

function Ensure-EdgeCdpReady {
  param([string]$Root, [string]$Url, [int]$Port, [string]$ProfileDir)
  if (Test-EdgeCdpReady -Url $Url) { return }
  $edgeStart = Join-Path $Root "scripts\start-opm-edge.ps1"
  if (-not (Test-Path $edgeStart)) { return }
  Write-Host "CDP endpoint not ready. Starting fixed-profile Edge..."
  & pwsh -NoProfile -File $edgeStart -EdgeProfileDir $ProfileDir -RemoteDebugPort $Port -StartUrl $env:FR_BASE_URL
  Start-Sleep -Seconds 3
}

function Invoke-IncrementalRefresh {
  param(
    [string]$Root,
    [string]$CdpUrl,
    [string]$ProfileDir
  )
  $localVersionUrl = ($CdpUrl.TrimEnd('/')) + "/json/version/"
  $localPort = [int]([uri]$CdpUrl).Port
  Ensure-EdgeCdpReady -Root $Root -Url $localVersionUrl -Port $localPort -ProfileDir $ProfileDir
  & pwsh -NoProfile -File $downloadScript -IncludeRootName $IncludeRootName -Overwrite $Overwrite -EdgeCdpUrl $CdpUrl -EdgeProfileDir $ProfileDir
  return $LASTEXITCODE
}
Write-Host "Running incremental refresh for root: $IncludeRootName"
Invoke-IncrementalRefresh -Root $RefreshToolRoot -CdpUrl $EdgeCdpUrl -ProfileDir $EdgeProfileDir
$downloadExitCode = $LASTEXITCODE
if ($downloadExitCode -ne 0 -and -not [string]::IsNullOrWhiteSpace($FallbackEdgeCdpUrl) -and $FallbackEdgeCdpUrl -ne $EdgeCdpUrl) {
  Write-Host "Primary profile refresh failed. Trying fallback profile..."
  Invoke-IncrementalRefresh -Root $RefreshToolRoot -CdpUrl $FallbackEdgeCdpUrl -ProfileDir $FallbackEdgeProfileDir
  $downloadExitCode = $LASTEXITCODE
}
if ($downloadExitCode -ne 0) {
  if ((Test-Path $httpScript) -and -not [string]::IsNullOrWhiteSpace($Token) -and -not [string]::IsNullOrWhiteSpace($CasTicket)) {
    Write-Host "CDP flow failed. Trying HTTP fallback with provided token/cas ticket..."
    & pwsh -NoProfile -File $httpScript -Mode run -OutputRoot $OutputRoot -IncludeRootName $IncludeRootName -Token $Token -CasTicket $CasTicket -FineRemember $FineRemember -Overwrite $Overwrite -MaxRetry 2
    if ($LASTEXITCODE -eq 0) {
      Write-Host "HTTP fallback refresh succeeded."
      return
    }
    Write-Host "HTTP fallback failed with exit code $LASTEXITCODE."
  }
  $edgeStart = Join-Path $RefreshToolRoot "scripts\start-opm-edge.ps1"
  if (Test-Path $edgeStart) {
    Write-Host "Attempting to open fixed-profile Edge for QR login..."
    $edgePort = [int]([uri]$EdgeCdpUrl).Port
    & pwsh -NoProfile -File $edgeStart -EdgeProfileDir $EdgeProfileDir -RemoteDebugPort $edgePort -StartUrl $env:FR_BASE_URL
  }
  throw "Incremental download failed (exit=$downloadExitCode). Please complete QR login in the opened Edge window, then retry. If CDP remains unavailable, set FR_AUTH_TOKEN (or OPM_FINE_AUTH_TOKEN) and OPM_CAS_TICKET to enable HTTP fallback. This live-refresh helper is optional and requires FR_REFRESH_TOOL_ROOT."
}

Write-Host "Refresh done. Next step should rescan catalog and retry query."
