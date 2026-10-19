#!/usr/bin/env bash
# Starts the demo site, runs the agent against it, and stops the site.
#
#   ./run.sh              the agent, with a model
#   ./run.sh --check      the same run with no model (Playwright), as CI does
#   ./run.sh --headless   any other flag goes to agent.py
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${PIDGEON_API_KEY:?Set PIDGEON_API_KEY in .env (see .env.example).}"

PYTHON="${PYTHON:-python}"

# The first run gives the site an address and a key of its own.
if [ -z "${SITE_PIDGEON_API_KEY:-}" ]; then
  touch .env
  "$PYTHON" site/sender.py
  set -a; . ./.env; set +a
fi

export RUN_STARTED="$(date +%s)"
export SITE_PORT="${SITE_PORT:-8765}"
export SITE_URL="http://localhost:$SITE_PORT"
export BROWSER_USE_LOGGING_LEVEL="${BROWSER_USE_LOGGING_LEVEL:-warning}"

"$PYTHON" site/server.py --port "$SITE_PORT" &
site=$!
trap 'kill "$site" 2>/dev/null' EXIT

for _ in $(seq 50); do
  curl -sf "$SITE_URL/" >/dev/null && break
  kill -0 "$site" 2>/dev/null || exit 1
  sleep 0.2
done

if [ "${1:-}" = "--check" ]; then
  "$PYTHON" check.py
else
  "$PYTHON" agent.py --url "$SITE_URL" "$@"
fi
