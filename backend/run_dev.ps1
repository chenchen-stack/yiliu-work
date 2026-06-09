# Dev backend with hot reload
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Error "Create venv first: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

function Clear-PortListeners([int]$Port) {
    for ($round = 0; $round -lt 4; $round++) {
        $portPids = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            Where-Object { $_ -gt 0 })
        foreach ($procId in $portPids) {
            taskkill /F /PID $procId 2>$null | Out-Null
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and ($_.CommandLine -like "*uvicorn*app.main:app*") } |
            ForEach-Object {
                taskkill /F /PID $_.ProcessId 2>$null | Out-Null
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        Start-Sleep -Seconds 1
        if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            return $true
        }
    }
    return -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

$port = 8000
if (-not (Clear-PortListeners $port)) {
    Write-Warning "Port 8000 is stuck (zombie listener). Trying 8001..."
    $port = 8001
    if (-not (Clear-PortListeners $port)) {
        Write-Warning "Port 8001 is also busy. Stop python/uvicorn processes and retry."
        exit 1
    }
}

if ($port -ne 8000) {
    Write-Host "Backend will listen on http://127.0.0.1:$port (set VITE_API_TARGET accordingly)"
}

Start-Sleep -Seconds 1
& ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port $port --reload
