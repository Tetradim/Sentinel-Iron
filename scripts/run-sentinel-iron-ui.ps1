param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8765,
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
Write-Host "Starting Sentinel Iron UI at http://$HostName`:$Port" -ForegroundColor Cyan
python -m sentinel_iron.ui_server --host $HostName --port $Port --repo-root $RepoRoot
