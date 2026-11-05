# Mini-Colosseum v2.0 Windows One-Command Launcher
# Launches the Python backend and opens the RocqIDE scientific workbench in default browser

Set-Location $PSScriptRoot

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " MINI-COLOSSEUM: Research-Harness Workbench on Meta Muse Models" -ForegroundColor Cyan
Write-Host " Implementing Stellar Colosseum (arXiv:2609.15983)" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# Locate Python dynamically
$pythonCmd = $null
foreach ($candidate in @("py", "python", "python3", "$env:LOCALAPPDATA\Python\bin\python.exe")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $candidate
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "Error: Python 3 is required but not found on PATH." -ForegroundColor Red
    Write-Host "Install Python 3 from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

Write-Host "Using Python: $pythonCmd" -ForegroundColor Gray

$port = 8765
$url = "http://127.0.0.1:$port"

# Start backend process
Write-Host "Starting Python backend orchestrator on $url..." -ForegroundColor Green
$proc = Start-Process $pythonCmd -ArgumentList "-m", "backend.main", "$port" -PassThru -NoNewWindow

# Wait for backend to be ready
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 300
    try {
        $res = Invoke-WebRequest -Uri "$url/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($res.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
}

if ($ready) {
    Write-Host "Backend is ready! Opening $url in default browser..." -ForegroundColor Green
    Start-Process $url
    Write-Host "`nMini-Colosseum is active. Press Ctrl+C or close this window to stop the server." -ForegroundColor Yellow
    try {
        Wait-Process -Id $proc.Id
    } catch {
        # Ctrl+C or window close
    } finally {
        Write-Host "Stopping Mini-Colosseum backend..." -ForegroundColor Cyan
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        } catch {}
        Write-Host "Shutdown complete." -ForegroundColor Green
    }
} else {
    Write-Host "Error: Backend failed to start on $url within 12 seconds." -ForegroundColor Red
    try {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    } catch {}
    exit 1
}
