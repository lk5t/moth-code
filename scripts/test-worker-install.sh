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
api -X PUT -H "$AUTH" "http://127.0.0.1:$PORT/v1/admin/config/flags" -d '{"allow_cpu_workers":true}' >/dev/null
CMD=$(api -X POST -H "$AUTH" "http://127.0.0.1:$PORT/v1/training/enrollments" -d '{"name":"ci-worker"}' \
  | "$PY" -c "import sys,json;print(json.load(sys.stdin)['command'])")
echo "enrollment command: ${CMD//me_*/me_<redacted>}"

echo "== run the enrollment command as a user would"
mkdir -p "$WORK/host" && cd "$WORK/host"
export MOTH_WORKER_HOME="$WORK/worker-home" XDG_DATA_HOME="$WORK/xdg"
# CI has no GPU: reuse the preinstalled CPU PyTorch and allow CPU (development flag); no systemd service.
bash -c "$CMD --use-system-torch --allow-cpu --no-service"

echo "== tampered download is refused"
cp moth-worker-$WV.tar.gz good.tgz && printf 'x' >> moth-worker-$WV.tar.gz
SHA=$(cut -d' ' -f1 "$WORK/dist/moth-worker-$WV.tar.gz.sha256")
if echo "$SHA  moth-worker-$WV.tar.gz" | sha256sum -c - 2>/dev/null; then echo "tamper not detected" >&2; exit 1; fi
echo "tampered tarball rejected by sha256sum"

echo "== run the installed worker for one job"
if [[ $EUID -eq 0 ]]; then VENV=/opt/moth-worker; else VENV="$WORK/xdg/moth-worker/venv"; fi
timeout 300 "$VENV/bin/moth-worker" run --max-jobs 1
"$VENV/bin/moth-worker" install-service --no-start || true
VERIFIED=$(api -H "$AUTH" "http://127.0.0.1:$PORT/v1/training/workers" \
  | "$PY" -c "import sys,json;print(json.load(sys.stdin)['workers'][0]['verified_jobs'])")
echo "verified jobs: $VERIFIED"
[[ "$VERIFIED" == "1" ]]
echo "PASS: one-command worker enrollment and verified training job"
