# Starts Circuit Breaker: checks prerequisites, builds the UI if needed, and runs the server.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1 [-Port 8000] [-Rebuild] [-Check]
param(
    [int]$Port = 8000,
    [switch]$Rebuild,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# Keep caches off a full system drive when D: exists.
if (Test-Path 'D:\') {
    foreach ($d in 'D:\cache\pip', 'D:\cache\hf', 'D:\cache\npm', 'D:\cache\pw', 'D:\tmp') { New-Item -ItemType Directory -Force $d | Out-Null }
    $env:PIP_CACHE_DIR = 'D:\cache\pip'; $env:HF_HOME = 'D:\cache\hf'; $env:TEMP = 'D:\tmp'; $env:TMP = 'D:\tmp'
    $env:PLAYWRIGHT_BROWSERS_PATH = 'D:\cache\pw'; $env:npm_config_cache = 'D:\cache\npm'
}

$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    Write-Host 'Creating virtual environment and installing requirements...'
    python -m venv .venv
    if (-not (Test-Path $Py)) { Fail 'Could not create .venv. Install Python 3.10+ and make sure "python" is on PATH.' }
    & $Py -m pip install -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail 'pip install failed; see the output above.' }
}

$Dist = Join-Path $Root 'web\dist\index.html'
if ($Rebuild -or -not (Test-Path $Dist)) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail 'npm not found. Install Node.js 18+ to build the UI.' }
    Push-Location web
    if (-not (Test-Path node_modules)) { npm install --no-fund --no-audit; if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'npm install failed.' } }
    npm run build; if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'UI build failed; see the output above.' }
    Pop-Location
}

if (-not (Test-Path '.env')) { Write-Host 'No .env found: the investigator will use local Ollama if running, otherwise labelled templates.' -ForegroundColor Yellow }
try { Invoke-RestMethod 'http://localhost:11434/api/tags' -TimeoutSec 2 | Out-Null; Write-Host 'Ollama is reachable on :11434.' } catch { Write-Host 'Ollama not reachable on :11434 (fine if you use the Gemini API).' }

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) { Fail "Port $Port is already in use (PID $($busy[0].OwningProcess)). Stop that process or pass -Port." }

Write-Host "Starting Circuit Breaker on http://127.0.0.1:$Port ..."
$env:HOST = '127.0.0.1'; $env:PORT = "$Port"
$server = Start-Process -FilePath $Py -ArgumentList '-m', 'backend' -PassThru -NoNewWindow

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($server.HasExited) { Fail "Server exited with code $($server.ExitCode); see the output above." }
    try { Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 | Out-Null; $ready = $true; break } catch { }
}
if (-not $ready) { Stop-Process -Id $server.Id -Force; Fail 'Server did not become ready within 60 s.' }

$h = Invoke-RestMethod "http://127.0.0.1:$Port/api/health"
Write-Host "Ready: http://127.0.0.1:$Port  (investigator: $($h.llm.state) $($h.llm.provider) $($h.llm.model))" -ForegroundColor Green

if ($Check) {
    & $Py scripts\demo_check.py "http://127.0.0.1:$Port"
    if ($LASTEXITCODE -ne 0) { Write-Host 'demo_check reported failures (server left running).' -ForegroundColor Red }
}

Write-Host 'Press Ctrl+C to stop.'
try { Wait-Process -Id $server.Id } finally { if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force } }
