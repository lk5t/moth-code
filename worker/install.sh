#!/usr/bin/env bash
# MOTH Worker installer — run from an extracted, checksum-verified release directory.
#   ./install.sh --server https://moth.example --token me_...   [--name my-3060] [--use-system-torch] [--no-service]
# Installs into a Python virtual environment (no system packages are modified), installs a
# CUDA build of PyTorch matching the driver, enrolls the machine with the one-time token,
# and installs a systemd service that restarts automatically.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="" TOKEN="" NAME="" SYSTEM_TORCH=0 SERVICE=1 ALLOW_CPU=0 TORCH_INDEX=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --use-system-torch) SYSTEM_TORCH=1; shift ;;
    --torch-index) TORCH_INDEX="$2"; shift 2 ;;
    --no-service) SERVICE=0; shift ;;
    --allow-cpu) ALLOW_CPU=1; shift ;;   # development/testing only
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
done
[[ -n "$SERVER" && -n "$TOKEN" ]] || { echo "usage: $0 --server URL --token TOKEN" >&2; exit 64; }
[[ "$(uname -s)" == "Linux" ]] || { echo "MOTH Worker supports Linux only." >&2; exit 1; }

say() { printf '\033[38;2;193;18;31m▲ MOTH\033[0m %s\n' "$*"; }

PY="$(command -v python3 || true)"
[[ -n "$PY" ]] || { echo "python3 (3.10+) is required." >&2; exit 1; }
"$PY" - <<'PYCHECK' || { echo "Python 3.10+ with venv is required (e.g. apt install python3-venv)." >&2; exit 1; }
import sys, venv
assert sys.version_info >= (3, 10)
PYCHECK

if [[ $EUID -eq 0 ]]; then PREFIX=/opt/moth-worker; else PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/moth-worker/venv"; fi
say "installing into $PREFIX"
if [[ $SYSTEM_TORCH -eq 1 ]]; then "$PY" -m venv --system-site-packages "$PREFIX"; else "$PY" -m venv "$PREFIX"; fi
PIP="$PREFIX/bin/python -m pip"
$PIP install --quiet --upgrade pip

if [[ $SYSTEM_TORCH -eq 0 ]]; then
  if [[ -z "$TORCH_INDEX" ]]; then
    CUDA="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9]*\)\.\([0-9]*\).*/\1\2/p' | head -1)"
    if [[ -z "$CUDA" ]]; then TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    elif (( CUDA >= 128 )); then TORCH_INDEX="https://download.pytorch.org/whl/cu128"
    elif (( CUDA >= 126 )); then TORCH_INDEX="https://download.pytorch.org/whl/cu126"
    else TORCH_INDEX="https://download.pytorch.org/whl/cu118"; fi
  fi
  say "installing PyTorch from $TORCH_INDEX"
  $PIP install --quiet torch --index-url "$TORCH_INDEX"
fi

say "installing MOTH Worker"
$PIP install --quiet "$HERE/backend" "$HERE/worker"

EXTRA=()
[[ -n "$NAME" ]] && EXTRA+=(--name "$NAME")
[[ $ALLOW_CPU -eq 1 ]] && EXTRA+=(--allow-cpu)
say "detecting hardware and enrolling"
"$PREFIX/bin/moth-worker" enroll --server "$SERVER" --token "$TOKEN" "${EXTRA[@]}"

if [[ $SERVICE -eq 1 ]]; then
  "$PREFIX/bin/moth-worker" install-service
else
  say "start the worker with: $PREFIX/bin/moth-worker run"
fi
say "done — manage this worker from MOTH Code → Training & Referrals"
