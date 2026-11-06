# MOTH Worker installer for Windows 10/11 — run from an extracted, checksum-verified release directory.
#   .\install.ps1 -Server https://moth.example -Token me_...  [-Name my-pc] [-NoService]
# No administrator rights needed. Installs into %LOCALAPPDATA%\MOTH\worker (a Python virtual
# environment; nothing system-wide is changed), installs PyTorch for the hardware (CUDA build for
# NVIDIA GPUs, CPU build otherwise), enrolls with the one-time token, and creates a scheduled task that
# starts the worker at logon (at startup when run as administrator) and restarts it if it stops.
# Remove it any time:  & "$env:LOCALAPPDATA\MOTH\worker\venv\Scripts\moth-worker.exe" uninstall
param(
  [Parameter(Mandatory = $true)][string]$Server,
  [Parameter(Mandatory = $true)][string]$Token,
  [string]$Name = "",
  [switch]$NoService,
  [switch]$UseSystemTorch,
  [string]$TorchIndex = ""
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
function Say($m) { Write-Host "▲ MOTH " -ForegroundColor Red -NoNewline; Write-Host $m }
function Fail($m) { Say $m; exit 1 }

function Find-Python {
  foreach ($c in @(@("py", "-3"), @("python"), @("python3"))) {
    try {
      $pre = @(); if ($c.Length -gt 1) { $pre = @($c[1..($c.Length - 1)]) }
      $exe = & $c[0] @pre -c "import sys; assert sys.version_info >= (3, 10); print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    } catch { }
  }
  return $null
}

$Py = Find-Python
if (-not $Py) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Say "Python 3.10+ was not found; installing Python 3.12 for this user with winget"
    winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $Py = Find-Python
  }
  if (-not $Py) { Fail "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/windows/ and run this command again." }
}

$HomeDir = Join-Path $env:LOCALAPPDATA "MOTH\worker"
$Venv = Join-Path $HomeDir "venv"
New-Item -ItemType Directory -Force $HomeDir | Out-Null
Say "installing into $Venv"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
  if ($UseSystemTorch) { & $Py -m venv --system-site-packages $Venv } else { & $Py -m venv $Venv }
  if ($LASTEXITCODE -ne 0) { Fail "Could not create the Python environment." }
}
$VPy = Join-Path $Venv "Scripts\python.exe"
& $VPy -m pip install --quiet --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "Could not update pip (check the internet connection)." }

& $VPy -c "import torch" 2>$null
if ($LASTEXITCODE -ne 0 -and -not $UseSystemTorch) {
  if (-not $TorchIndex) {
    $cuda = $null
    try { $smi = & nvidia-smi 2>$null; if ($smi -match "CUDA Version:\s*(\d+)\.(\d+)") { $cuda = [int]($Matches[1] + $Matches[2]) } } catch { }
    if (-not $cuda) { $TorchIndex = "https://download.pytorch.org/whl/cpu"; Say "no NVIDIA GPU found: this will be a CPU worker" }
    elseif ($cuda -ge 128) { $TorchIndex = "https://download.pytorch.org/whl/cu128" }
    elseif ($cuda -ge 126) { $TorchIndex = "https://download.pytorch.org/whl/cu126" }
    else { $TorchIndex = "https://download.pytorch.org/whl/cu118" }
  }
  Say "installing PyTorch from $TorchIndex (a few hundred MB, once)"
  & $VPy -m pip install --quiet --disable-pip-version-check torch --index-url $TorchIndex
  if ($LASTEXITCODE -ne 0) { Fail "Could not install PyTorch." }
}

Say "installing MOTH Worker"
& $VPy -m pip install --quiet --disable-pip-version-check --upgrade (Join-Path $Here "backend") (Join-Path $Here "worker")
if ($LASTEXITCODE -ne 0) { Fail "Could not install MOTH Worker." }

$Mw = Join-Path $Venv "Scripts\moth-worker.exe"
$enrollArgs = @("--home", $HomeDir, "enroll", "--server", $Server, "--token", $Token)
if ($Name) { $enrollArgs += @("--name", $Name) }
Say "checking the hardware and enrolling with $Server"
& $Mw @enrollArgs
if ($LASTEXITCODE -ne 0) { Fail "Enrollment failed (see the message above). Generate a new command in MOTH Code if the token expired." }

if (-not $NoService) {
  & $Mw --home $HomeDir install-service
  if ($LASTEXITCODE -ne 0) { Say "Start the worker manually with: & `"$Mw`" --home `"$HomeDir`" run" }
} else {
  Say "start the worker with: & `"$Mw`" --home `"$HomeDir`" run"
}
Say "done. Manage this worker in MOTH Code → Workers. Remove it any time with: & `"$Mw`" --home `"$HomeDir`" uninstall"
