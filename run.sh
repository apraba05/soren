#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
# GEMINI_API_KEY in .env turns on the live model; without it the offline reader runs
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export PORT="${PORT:-8000}"

echo "Policy-Gated Invoice Exception Router -> http://localhost:${PORT}"
exec python3 app.py
