# SSL Certificate Manager - Docker Management Script (Windows PowerShell)
# Usage: .\certmanager.ps1 [start|stop|restart|destroy|status|logs|build|key]

param(
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "restart", "destroy", "status", "logs", "build", "key", "regenerate", "help")]
    [string]$Command = "help"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ComposeFile = Join-Path $ScriptDir "docker-compose.yml"
$ContainerName = "ssl-cert-manager"

function Start-CertManager {
    Write-Host "=== Starting SSL Certificate Manager ===" -ForegroundColor Cyan
    docker compose -f $ComposeFile up -d --build
    Write-Host ""
    Write-Host "  Started. Access at: " -NoNewline
    Write-Host "http://localhost" -ForegroundColor Green
    Write-Host "  API docs at: " -NoNewline
    Write-Host "http://localhost/api/docs" -ForegroundColor Green
    Write-Host ""
    Write-Host "  First run? Get your API key with: .\certmanager.ps1 key" -ForegroundColor Yellow
}

function Stop-CertManager {
    Write-Host "=== Stopping SSL Certificate Manager ===" -ForegroundColor Cyan
    docker compose -f $ComposeFile stop
    Write-Host "Stopped. Data is preserved." -ForegroundColor Green
}

function Restart-CertManager {
    Write-Host "=== Restarting SSL Certificate Manager ===" -ForegroundColor Cyan
    docker compose -f $ComposeFile restart
    Write-Host "Restarted." -ForegroundColor Green
}

function Remove-CertManager {
    Write-Host "=== Destroying SSL Certificate Manager ===" -ForegroundColor Red
    Write-Host ""
    $confirm = Read-Host "Remove data volume too? All certificates and keys will be PERMANENTLY DELETED (y/N)"
    if ($confirm -eq "y") {
        Write-Host "Removing container AND data volume..." -ForegroundColor Red
        docker compose -f $ComposeFile down -v
        Write-Host "Container and data volume REMOVED." -ForegroundColor Red
    }
    else {
        Write-Host "Removing container only (data preserved in volume)..." -ForegroundColor Yellow
        docker compose -f $ComposeFile down
        Write-Host "Container removed. Volume preserved." -ForegroundColor Green
    }
}

function Get-CertManagerStatus {
    Write-Host "=== SSL Certificate Manager Status ===" -ForegroundColor Cyan
    Write-Host ""
    docker compose -f $ComposeFile ps
    Write-Host ""
    Write-Host "--- Health Check ---" -ForegroundColor Cyan
    try {
        $health = Invoke-RestMethod -Uri "http://localhost/api/v1/health" -TimeoutSec 5
        Write-Host "  Status: $($health.status)" -ForegroundColor Green
        Write-Host "  Version: $($health.version)"
        Write-Host "  Database: $($health.database)"
        Write-Host "  Keytool: $($health.keytool)"
    } catch {
        Write-Host "  Service not reachable. Is it running?" -ForegroundColor Red
    }
}

function Get-CertManagerLogs {
    Write-Host "=== SSL Certificate Manager Logs ===" -ForegroundColor Cyan
    Write-Host "(Press Ctrl+C to exit)" -ForegroundColor Gray
    docker compose -f $ComposeFile logs -f --tail=50
}

function Build-CertManager {
    Write-Host "=== Rebuilding SSL Certificate Manager ===" -ForegroundColor Cyan
    docker compose -f $ComposeFile build --no-cache
    Write-Host "Build complete. Run '.\certmanager.ps1 start' to start." -ForegroundColor Green
}

function Get-ApiKey {
    Write-Host "=== API Key ===" -ForegroundColor Cyan
    Write-Host ""
    try {
        $key = docker exec $ContainerName cat /data/.api_key 2>$null
        if ($key) {
            Write-Host "  $key" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "  Paste this into Settings in the browser." -ForegroundColor Gray
        } else {
            Write-Host "  Could not read API key. Is the container running?" -ForegroundColor Red
        }
    } catch {
        Write-Host "  Container not running. Start with: .\certmanager.ps1 start" -ForegroundColor Red
    }
}

function Update-AboutPage {
    # Deliberately its own explicit command, not wired into Start-CertManager
    # or Build-CertManager - the About page's Regenerate action overwrites
    # its current content wholesale, including any hand-added notes (e.g. a
    # license-review sign-off), so it should only run when someone actually
    # means it, not as a side effect of every routine restart.
    Write-Host "=== Regenerating About Page ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  This overwrites the current About page content, including any hand-added notes." -ForegroundColor Yellow
    try {
        $key = docker exec $ContainerName cat /data/.api_key 2>$null
        if (-not $key) {
            Write-Host "  Could not read API key. Is the container running?" -ForegroundColor Red
            return
        }
        $headers = @{ "X-API-Key" = $key }
        $result = Invoke-RestMethod -Uri "http://localhost/api/v1/about/regenerate" -Method Post -Headers $headers -TimeoutSec 30
        Write-Host "  Done. Last updated by $($result.updated_by) at $($result.updated_at)." -ForegroundColor Green
    } catch {
        Write-Host "  Failed to regenerate. Is the container running and healthy? ($_)" -ForegroundColor Red
    }
}

function Show-Help {
    Write-Host ""
    Write-Host "SSL Certificate Manager - Docker Management" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage: .\certmanager.ps1 [command]"
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor White
    Write-Host "  start     " -NoNewline -ForegroundColor Green; Write-Host "Build and start the application"
    Write-Host "  stop      " -NoNewline -ForegroundColor Yellow; Write-Host "Stop the application (data preserved)"
    Write-Host "  restart   " -NoNewline -ForegroundColor Yellow; Write-Host "Restart the application"
    Write-Host "  destroy   " -NoNewline -ForegroundColor Red; Write-Host "Remove container (prompts to remove data)"
    Write-Host "  status    " -NoNewline -ForegroundColor Cyan; Write-Host "Show container status and health"
    Write-Host "  logs      " -NoNewline -ForegroundColor Gray; Write-Host "Follow live container logs"
    Write-Host "  build     " -NoNewline -ForegroundColor Cyan; Write-Host "Rebuild the image without starting"
    Write-Host "  key         " -NoNewline -ForegroundColor Yellow; Write-Host "Show the API key"
    Write-Host "  regenerate  " -NoNewline -ForegroundColor Cyan; Write-Host "Rebuild the About page's dependency versions (overwrites hand-added notes - run deliberately, e.g. after a rebuild that bumped a dependency)"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor White
    Write-Host "  .\certmanager.ps1 start        # Start for the first time"
    Write-Host "  .\certmanager.ps1 key          # Get the API key"
    Write-Host "  .\certmanager.ps1 regenerate   # Refresh About page versions after a rebuild"
    Write-Host "  .\certmanager.ps1 destroy      # Remove everything"
    Write-Host ""
}

switch ($Command) {
    "start"   { Start-CertManager }
    "stop"    { Stop-CertManager }
    "restart" { Restart-CertManager }
    "destroy" { Remove-CertManager }
    "status"  { Get-CertManagerStatus }
    "logs"    { Get-CertManagerLogs }
    "build"   { Build-CertManager }
    "key"     { Get-ApiKey }
    "regenerate" { Update-AboutPage }
    "help"    { Show-Help }
}
