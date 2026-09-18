#!/usr/bin/env bash
# Run on Linux from project root (parent of config/ and server.py):
#   chmod +x scripts/bootstrap_linux_venv.sh
#   ./scripts/bootstrap_linux_venv.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -f "requirements.txt" ]] || [[ ! -f "server.py" ]]; then
  echo "Run this from the project root (expected requirements.txt and server.py)." >&2
  exit 1
fi
if [[ -d ".venv" ]]; then
  echo "Note: .venv already exists. Remove it first for a clean recreate, or run: source .venv/bin/activate" >&2
fi
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -c "import fastapi, faiss, sentence_transformers; print('imports: ok')"
echo "Next: copy .env (see .env.example), install Ollama, npm ci && npm run build (from project root, Vite)"
echo "Run server:  source .venv/bin/activate && python -m uvicorn server:app --host 127.0.0.1 --port 8000"
