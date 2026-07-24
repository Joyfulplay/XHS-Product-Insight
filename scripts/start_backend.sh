#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/root/XHS-Product-Insight}
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8000}

cd "$PROJECT_DIR"

echo "[1/4] Project: $PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is not installed in WSL. Please install Python 3 first."
  exit 1
fi

if [ ! -d venv ]; then
  echo "[2/4] Creating Python virtual environment..."
  python3 -m venv venv
else
  echo "[2/4] Using existing Python virtual environment."
fi

source venv/bin/activate

echo "[3/4] Installing/updating backend dependencies..."
python -m pip install -r requirements.txt

export PYTHONPATH="$PROJECT_DIR/backend:${PYTHONPATH:-}"

echo "[4/4] Starting FastAPI backend at http://$HOST:$PORT"
echo "Keep this window open while using the browser extension."
echo "Press Ctrl+C in this window to stop the backend."

python -m uvicorn main:app --reload --app-dir backend --host "$HOST" --port "$PORT"
