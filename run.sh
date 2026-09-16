#!/usr/bin/env bash
set -euo pipefail

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
