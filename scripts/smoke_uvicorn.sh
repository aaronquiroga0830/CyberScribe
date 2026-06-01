#!/usr/bin/env bash
# After bootstrap_linux_venv.sh: quick check that the app serves the SPA (GET / => 200).
# Usage: ./scripts/smoke_uvicorn.sh [PORT]   default 8000
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${1:-8000}"
if [[ ! -x .venv/bin/python ]]; then
  echo "No .venv; run ./scripts/bootstrap_linux_venv.sh first." >&2
  exit 1
fi
# shellcheck source=/dev/null
source .venv/bin/activate
uvicorn server:app --host 127.0.0.1 --port "$PORT" >>/tmp/agentic_rag_smoke_$$.log 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; rm -f /tmp/agentic_rag_smoke_$$.log; }
trap cleanup EXIT
# First import of the app can take 30-90s on cold start (ML stack).
for i in $(seq 1 120); do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/"; then
    echo "smoke: GET / OK (port ${PORT})"
    exit 0
  fi
  sleep 0.5
done
echo "smoke: server did not respond. Log:" >&2
cat /tmp/agentic_rag_smoke_$$.log >&2
exit 1
