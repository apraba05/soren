#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export PORT="${PORT:-8000}"

echo "Policy-Gated Invoice Exception Router -> http://localhost:${PORT}"
exec python3 app.py
