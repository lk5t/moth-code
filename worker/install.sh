#!/usr/bin/env bash
# MOTH Worker installer (Linux and macOS) — run from an extracted, checksum-verified release directory.
#   ./install.sh --server https://moth.example --token me_...   [--name my-server] [--no-service]
#
# Works with or without administrator rights and on CPU-only machines (a GPU is used when present):
#   * installs into a Python virtual environment (system packages are not modified):
#       as root: /opt/moth-worker            otherwise: ~/.local/share/moth-worker/venv
#   * installs PyTorch matching the hardware (CUDA build for NVIDIA GPUs, CPU build otherwise),
#   * enrolls the machine with the one-time token,
#   * starts the worker automatically at boot and restarts it if it stops:
#       systemd (root, or the user's systemd with lingering), else cron (no administrator needed),
#       launchd on macOS.
# Uninstall at any time:  moth-worker uninstall
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="" TOKEN="" NAME="" SYSTEM_TORCH=0 SERVICE=1 TORCH_INDEX="" SERVICE_MODE="auto"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --use-system-torch) SYSTEM_TORCH=1; shift ;;
    --torch-index) TORCH_INDEX="$2"; shift 2 ;;
    --no-service) SERVICE=0; shift ;;
    --service) SERVICE_MODE="$2"; shift 2 ;;   # auto | systemd | cron | launchd
    --allow-cpu) shift ;;                       # accepted for older commands; CPU workers need no flag
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
done
[[ -n "$SERVER" && -n "$TOKEN" ]] || { echo "usage: $0 --server URL --token TOKEN" >&2; exit 64; }
OS="$(uname -s)"
[[ "$OS" == "Linux" || "$OS" == "Darwin" ]] || { echo "Use install.ps1 on Windows." >&2; exit 1; }

say() { printf '\033[38;2;193;18;31m▲ MOTH\033[0m %s\n' "$*"; }
fail() { printf '\033[38;2;193;18;31m▲ MOTH\033[0m %s\n' "$*" >&2; exit 1; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
[[ -n "$PY" ]] || fail "Python 3.10 or newer is required. Ubuntu/Debian: sudo apt install python3 python3-venv · macOS: install Python from python.org"
"$PY" -c 'import venv, ensurepip' 2>/dev/null || fail "The Python venv module is missing. Ubuntu/Debian: sudo apt install python3-venv (then run this command again)"

if [[ $EUID -eq 0 ]]; then PREFIX=/opt/moth-worker; else PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/moth-worker/venv"; fi
say "installing into $PREFIX"
if [[ -x "$PREFIX/bin/python" ]] && "$PREFIX/bin/python" -c 'import sys' 2>/dev/null; then
  say "reusing the existing environment"
elif [[ $SYSTEM_TORCH -eq 1 ]]; then "$PY" -m venv --system-site-packages "$PREFIX"
else "$PY" -m venv "$PREFIX"; fi
PIP=("$PREFIX/bin/python" -m pip --disable-pip-version-check)
"${PIP[@]}" install --quiet --upgrade pip

if [[ $SYSTEM_TORCH -eq 0 ]] && ! "$PREFIX/bin/python" -c 'import torch' 2>/dev/null; then
  if [[ "$OS" == "Darwin" ]]; then
    say "installing PyTorch (macOS)"
    "${PIP[@]}" install --quiet torch
  else
    if [[ -z "$TORCH_INDEX" ]]; then
      CUDA="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9]*\)\.\([0-9]*\).*/\1\2/p' | head -1 || true)"
      if [[ -z "$CUDA" ]]; then TORCH_INDEX="https://download.pytorch.org/whl/cpu"; say "no NVIDIA GPU found: this will be a CPU worker"
      elif (( CUDA >= 128 )); then TORCH_INDEX="https://download.pytorch.org/whl/cu128"
      elif (( CUDA >= 126 )); then TORCH_INDEX="https://download.pytorch.org/whl/cu126"
      else TORCH_INDEX="https://download.pytorch.org/whl/cu118"; fi
    fi
    say "installing PyTorch from $TORCH_INDEX (a few hundred MB, once)"
    "${PIP[@]}" install --quiet torch --index-url "$TORCH_INDEX"
  fi
fi

say "installing MOTH Worker"
"${PIP[@]}" install --quiet --upgrade "$HERE/backend" "$HERE/worker"

EXTRA=()
[[ -n "$NAME" ]] && EXTRA+=(--name "$NAME")
say "checking the hardware and enrolling with $SERVER"
"$PREFIX/bin/moth-worker" enroll --server "$SERVER" --token "$TOKEN" ${EXTRA[@]+"${EXTRA[@]}"}

if [[ $SERVICE -eq 1 ]]; then
  "$PREFIX/bin/moth-worker" install-service --mode "$SERVICE_MODE"
else
  say "start the worker with: $PREFIX/bin/moth-worker run"
fi
say "done. Manage this worker in MOTH Code → Workers. Remove it any time with: $PREFIX/bin/moth-worker uninstall"
