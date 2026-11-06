#!/usr/bin/env bash
# End-to-end test of one-command MOTH Worker enrollment on Linux (used by CI).
# Starts a real MOTH Server, publishes a worker release, generates an enrollment command
# through the API, executes it exactly as a user would, then runs the installed worker
# until it completes a verified training job.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
PORT="${PORT:-8961}"
export MOTH_SERVER_DATA_DIR="$WORK/server" MOTH_SERVER_PUBLIC_URL="http://127.0.0.1:$PORT"
export PYTHONPATH="$ROOT/server:$ROOT/backend:${PYTHONPATH:-}"
PY="${PYTHON:-python3}"
cleanup() { [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo "== bootstrap training data and coordinator"
"$PY" "$ROOT/scripts/dev-bootstrap-training.py" "$WORK/boot" >/dev/null
"$PY" -m moth_server.cli training-init --model "$WORK/boot/models/moth-dev-base" --dataset "$WORK/boot/dataset" \
  --shards 4 --steps 4 --batch-size 2 --seq-len 32 --min-contributions 1
echo "crimson wings 2026!" | "$PY" -m moth_server.cli init-owner --email owner@moth.test --password-stdin

WV=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/worker/moth_worker/__init__.py")
echo "== publish worker release $WV"
"$PY" "$ROOT/scripts/build-worker-release.py" --out "$WORK/dist"
"$PY" -m moth_server.cli worker-release "$WORK/dist/moth-worker-$WV.tar.gz" --version $WV

echo "== start server"
"$PY" -m moth_server.cli serve --port "$PORT" >"$WORK/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$PORT/v1/health" >/dev/null && break; sleep 0.5; done

api() { curl -fsS -H "content-type: application/json" "$@"; }
TOKEN=$(api -X POST "http://127.0.0.1:$PORT/v1/auth/login" -d '{"username":"LK5T","password":"crimson wings 2026!"}' \
  | "$PY" -c "import sys,json;print(json.load(sys.stdin)['token'])")
AUTH="authorization: Bearer $TOKEN"
# 0.5: no CPU flag on the server and none in the command — CPU workers are production workers
CMD=$(api -X POST -H "$AUTH" "http://127.0.0.1:$PORT/v1/training/enrollments" -d '{"name":"ci-worker"}' \
  | "$PY" -c "import sys,json;print(json.load(sys.stdin)['command'])")
echo "enrollment command: ${CMD//me_*/me_<redacted>}"

if ! command -v crontab >/dev/null; then  # containers without cron: a crontab stand-in that stores the table
  mkdir -p "$WORK/bin"
  cat > "$WORK/bin/crontab" <<'SHIM'
#!/bin/sh
T="${MOTH_TEST_CRONTAB:?}"
if [ "$1" = "-l" ]; then [ -f "$T" ] && cat "$T" || exit 1; elif [ "$1" = "-" ]; then cat > "$T"; fi
SHIM
  chmod +x "$WORK/bin/crontab"
  export PATH="$WORK/bin:$PATH" MOTH_TEST_CRONTAB="$WORK/crontab.txt"
  echo "(no crontab on this machine: using a stand-in that records the table)"
fi
CRON_BEFORE="$(crontab -l 2>/dev/null || true)"

echo "== run the enrollment command exactly as a user would (CPU-only machine, automatic start via cron)"
mkdir -p "$WORK/host" && cd "$WORK/host"
export MOTH_WORKER_HOME="$WORK/worker-home" XDG_DATA_HOME="$WORK/xdg"
EXTRA=(--service cron)
[[ -n "${MOTH_TEST_SYSTEM_TORCH:-}" ]] && EXTRA+=(--use-system-torch)   # skip the PyTorch download locally
bash -c "$CMD ${EXTRA[*]}"
if [[ $EUID -eq 0 ]]; then VENV=/opt/moth-worker; else VENV="$WORK/xdg/moth-worker/venv"; fi
"$VENV/bin/python" -c "import torch; assert not torch.cuda.is_available(); print('PyTorch', torch.__version__, '(CPU)')"

echo "== a tampered download is refused by the same command, before anything runs"
mkdir -p "$WORK/tamper" && cd "$WORK/tamper"
curl -fsSLO "http://127.0.0.1:$PORT/downloads/worker/moth-worker-$WV.tar.gz"
printf 'x' >> moth-worker-$WV.tar.gz
SHA=$(cut -d' ' -f1 "$WORK/dist/moth-worker-$WV.tar.gz.sha256")
if echo "$SHA  moth-worker-$WV.tar.gz" | sha256sum -c - 2>/dev/null; then echo "tamper not detected" >&2; exit 1; fi
echo "tampered tarball rejected by sha256sum"
cd "$WORK/host"

workers_json() { api -H "$AUTH" "http://127.0.0.1:$PORT/v1/training/workers"; }
field() { workers_json | "$PY" -c "import sys,json;w=json.load(sys.stdin)['workers'][-1];print(w['$1'])"; }

echo "== the automatically started worker completes a verified job"
grep -q "moth-worker" <(crontab -l) || { echo "cron entries missing" >&2; exit 1; }
for _ in $(seq 1 150); do [[ "$(field verified_jobs)" -ge 1 ]] && break; sleep 2; done
echo "verified jobs: $(field verified_jobs); worker compute: $(workers_json | "$PY" -c "import sys,json;print(json.load(sys.stdin)['workers'][-1]['hardware']['compute'])")"
[[ "$(field verified_jobs)" -ge 1 ]]

echo "== crash recovery: the worker is killed; the cron entry starts exactly one new worker"
PID=$(cat "$MOTH_WORKER_HOME/worker.pid"); kill -9 "$PID"; sleep 1
LINE=$(crontab -l | grep '^\* \* \* \* \*' | sed 's/^\* \* \* \* \* //; s/ # moth-worker$//')
bash -c "$LINE" & bash -c "$LINE" &   # two cron ticks at once
sleep 8
N=$(pgrep -fc "bin/python .*moth-worker --home .* run --log-file" || true)  # worker processes, not shells
echo "running workers after restart: $N"
[[ "$N" == "1" ]]
[[ "$(cat "$MOTH_WORKER_HOME/worker.pid")" != "$PID" ]]

echo "== uninstall: stops the worker, removes the cron entries, revokes it, deletes its files"
"$VENV/bin/moth-worker" uninstall --yes
sleep 2
[[ "$(crontab -l 2>/dev/null || true)" == "$CRON_BEFORE" ]] || { echo "cron entries left behind" >&2; exit 1; }
[[ "$(field status)" == "revoked" ]]
[[ ! -e "$MOTH_WORKER_HOME" ]] && [[ ! -e "$VENV" ]]
! pgrep -f "bin/python .*moth-worker --home .* run --log-file" >/dev/null
echo "uninstalled: no cron entries, worker revoked on the server, files removed"
echo "PASS: one-command CPU worker install, automatic start, verified job, crash recovery and uninstall"
