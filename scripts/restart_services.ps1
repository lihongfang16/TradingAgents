# Restart Services Script
# Kills all API and Web processes, then restarts them

Write-Host "=== STEP 1: Stopping all services ==="

# Function to kill process tree
function Kill-ProcessTree {
    param([int]$ProcId)
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcId }
    foreach ($child in $children) {
        Kill-ProcessTree -ProcId $child.ProcessId
        Write-Host "  Killing child PID $($child.ProcessId)"
        Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "  Killing parent PID $ProcId"
    Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
}

# Kill API on port 8000
$apiConns = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
foreach ($conn in $apiConns) {
    $procId = $conn.OwningProcess
    Write-Host "[API] Killing process tree at PID $procId"
    Kill-ProcessTree -ProcId $procId
}

# Kill Web on port 8501
$webConns = Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
foreach ($conn in $webConns) {
    $procId = $conn.OwningProcess
    Write-Host "[WEB] Killing process tree at PID $procId"
    Kill-ProcessTree -ProcId $procId
}

# Wait for sockets to close
Write-Host "Waiting for sockets to close..."
Start-Sleep -Seconds 5

# Verify
$p8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
$p8501 = Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }

if ($p8000) { Write-Host "WARNING: Port 8000 still held by PID $($p8000.OwningProcess)" }
else { Write-Host "Port 8000: FREE" }
if ($p8501) { Write-Host "WARNING: Port 8501 still held by PID $($p8501.OwningProcess)" }
else { Write-Host "Port 8501: FREE" }

Write-Host ""
Write-Host "=== STEP 2: Starting API server ==="
$apiProc = Start-Process -FilePath "python" -ArgumentList "start_api.py" -PassThru -WindowStyle Hidden
Write-Host "[API] Started with PID $($apiProc.Id)"

Write-Host ""
Write-Host "=== STEP 3: Starting Web UI ==="
$webProc = Start-Process -FilePath "python" -ArgumentList "start_web.py" -PassThru -WindowStyle Hidden
Write-Host "[WEB] Started with PID $($webProc.Id)"

Write-Host ""
Write-Host "Waiting for services to initialize..."
Start-Sleep -Seconds 8

Write-Host ""
Write-Host "=== STEP 4: Verification ==="

# Test API
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/docs" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "[API] Health check: $($response.StatusCode) OK"
} catch {
    Write-Host "[API] Health check: FAILED - $_"
}

# Test Web
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8501" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "[WEB] Health check: $($response.StatusCode) OK"
} catch {
    Write-Host "[WEB] Health check: FAILED - $_"
}

Write-Host ""
Write-Host "=== Services restarted ==="
