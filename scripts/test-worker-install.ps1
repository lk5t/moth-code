# End-to-end test of one-command MOTH Worker installation on Windows (used by CI on windows-latest).
# A real MOTH Server publishes a worker release; the Windows command MOTH Code shows is executed exactly
# as a user would (CPU-only machine, real PyTorch download); the scheduled task starts the worker,
# which completes a verified training job; then `moth-worker uninstall` removes everything.
# One script on purpose: GitHub Actions ends a step's background processes when the step ends.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Work = Join-Path $env:RUNNER_TEMP "moth-worker-e2e"
New-Item -ItemType Directory -Force $Work | Out-Null
$Port = 8962
$Base = "http://127.0.0.1:$Port"
$env:MOTH_SERVER_DATA_DIR = Join-Path $Work "server"
$env:MOTH_SERVER_PUBLIC_URL = $Base
$env:PYTHONPATH = "$Root\server;$Root\backend"

Write-Host "== bootstrap training data, coordinator and Owner"
python "$Root\scripts\dev-bootstrap-training.py" "$Work\boot" | Out-Null
python -m moth_server.cli training-init --model "$Work\boot\models\moth-dev-base" --dataset "$Work\boot\dataset" --shards 4 --steps 4 --batch-size 2 --seq-len 32 --min-contributions 1
"crimson wings 2026!" | python -m moth_server.cli init-owner --email owner@moth.test --password-stdin
$wv = (Select-String -Path "$Root\worker\moth_worker\__init__.py" -Pattern '__version__ = "(.*)"').Matches[0].Groups[1].Value
python "$Root\scripts\build-worker-release.py" --out "$Work\dist"
python -m moth_server.cli worker-release "$Work\dist\moth-worker-$wv.tar.gz" --version $wv

Write-Host "== start the server"
$server = Start-Process python -ArgumentList "-m", "moth_server.cli", "serve", "--port", "$Port" -PassThru -WindowStyle Hidden `
  -RedirectStandardOutput "$Work\server.log" -RedirectStandardError "$Work\server.err"
for ($i = 0; $i -lt 60; $i++) { try { Invoke-RestMethod "$Base/v1/health" | Out-Null; break } catch { Start-Sleep 1 } }
try {
  $login = Invoke-RestMethod -Method Post "$Base/v1/auth/login" -ContentType "application/json" -Body '{"username":"LK5T","password":"crimson wings 2026!"}'
  $auth = @{ Authorization = "Bearer $($login.token)" }
  $e = Invoke-RestMethod -Method Post "$Base/v1/training/enrollments" -Headers $auth -ContentType "application/json" -Body '{"name":"ci-windows"}'
  if (-not $e.windows_command) { throw "the server did not return a Windows command" }
  Write-Host "Windows command: $($e.windows_command -replace 'me_[^'']+', 'me_<redacted>')"

  Write-Host "== run the command exactly as a user would (PowerShell, no administrator steps, CPU-only)"
  $userCwd = Get-Location
  Invoke-Expression $e.windows_command
  Set-Location $userCwd
  $wHome = Join-Path $env:LOCALAPPDATA "MOTH\worker"
  $mw = Join-Path $wHome "venv\Scripts\moth-worker.exe"
  if (-not (Test-Path $mw)) { throw "moth-worker.exe was not installed" }
  & (Join-Path $wHome "venv\Scripts\python.exe") -c "import torch; assert not torch.cuda.is_available(); print('PyTorch', torch.__version__, '(CPU)')"
  schtasks /Query /TN "MOTH Worker" | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "the scheduled task was not created" }

  Write-Host "== the worker started by the scheduled task completes a verified job"
  $verified = 0
  for ($i = 0; $i -lt 150; $i++) {
    $w = (Invoke-RestMethod "$Base/v1/training/workers" -Headers $auth).workers | Select-Object -Last 1
    $verified = $w.verified_jobs
    if ($verified -ge 1) { break }
    Start-Sleep 2
  }
  Write-Host "verified jobs: $verified; compute: $($w.hardware.compute); status: $($w.status)"
  if ($verified -lt 1) { Get-Content (Join-Path $wHome "worker.log") -ErrorAction SilentlyContinue | Select-Object -Last 30; throw "no verified job" }

  Write-Host "== uninstall removes the task, revokes the worker and deletes its files"
  & $mw --home $wHome uninstall --yes
  Start-Sleep 8
  schtasks /Query /TN "MOTH Worker" 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { throw "the scheduled task is still there" }
  $w = (Invoke-RestMethod "$Base/v1/training/workers" -Headers $auth).workers | Select-Object -Last 1
  if ($w.status -ne "revoked") { throw "the worker was not revoked (status $($w.status))" }
  if (Test-Path $wHome) { throw "files were left in $wHome" }
  Write-Host "PASS: Windows one-command worker install, scheduled-task start, verified job and uninstall"
} finally {
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
  Get-Content "$Work\server.err" -ErrorAction SilentlyContinue | Select-Object -Last 20
}
