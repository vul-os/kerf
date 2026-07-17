#!/usr/bin/env bash
#
# dev.sh — one-command local dev loop for Kerf.
#
#   API : http://localhost:8080   (kerf-server, LOCAL_MODE=true, auto-login)
#   Web : http://localhost:5173   (Vite; proxies /api → :8080)
#
# Usage:
#   ./scripts/dev.sh
#   DATABASE_URL=postgres://other@host/db ./scripts/dev.sh   # override DB
#
# Stop: Ctrl-C (both processes shut down cleanly).
#
# Prerequisites:
#   - Python 3.11+ with kerf_core and all packages installed
#     (pip install -e packages/kerf-core or the project venv)
#   - Node 20+ with node_modules present (npm install)
#   - PostgreSQL (pg@16 recommended); installed via Homebrew on macOS
#     or package manager on Linux

set -euo pipefail

_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$_REPO_ROOT"

# ── Config ────────────────────────────────────────────────────────────────────
# pc role + kerf db (per project memory)
DATABASE_URL="${DATABASE_URL:-postgres://pc@localhost:5432/kerf?sslmode=disable}"
export DATABASE_URL

# ── Local secrets (optional, gitignored) ─────────────────────────────────────
if [[ -f .env.local ]]; then
  # shellcheck disable=SC1091
  set -a; source .env.local; set +a
fi

# ── Local-mode settings ───────────────────────────────────────────────────────
export LOCAL_MODE=true
export CLOUD_ENABLED=false

# ── 1. Ensure Postgres is running ─────────────────────────────────────────────
echo "▸ checking Postgres …"
if ! pg_isready -q 2>/dev/null; then
  echo "  Postgres not running — attempting to start …"
  if command -v brew &>/dev/null; then
    # macOS Homebrew
    if brew services list | grep -q "postgresql@16"; then
      brew services start postgresql@16
    elif brew services list | grep -q "postgresql"; then
      brew services start postgresql
    else
      echo "  ERROR: postgresql not found in brew services."
      echo "         Install with: brew install postgresql@16"
      exit 1
    fi
  elif command -v pg_ctl &>/dev/null; then
    # Linux / macOS fallback
    pg_ctl start
  else
    echo "  ERROR: Cannot start Postgres — pg_ctl not in PATH."
    echo "         Start Postgres manually, then re-run ./scripts/dev.sh"
    exit 1
  fi
  # Wait up to 10 seconds for pg to accept connections
  for i in $(seq 1 10); do
    pg_isready -q && break
    sleep 1
    if [[ $i -eq 10 ]]; then
      echo "  ERROR: Postgres did not start within 10 s."
      exit 1
    fi
  done
  echo "  Postgres started."
else
  echo "  Postgres is running."
fi

# ── 2. Ensure kerf database exists ────────────────────────────────────────────
# pc role + kerf db (per project memory)
_PGDB="${DATABASE_URL##*/}"
_PGDB="${_PGDB%%\?*}"   # strip query string
_PGROLE="pc"
echo "▸ ensuring database '${_PGDB}' exists …"
if ! psql "$DATABASE_URL" -c "" &>/dev/null; then
  createdb -U "${_PGROLE}" "${_PGDB}"
  echo "  Created database '${_PGDB}'."
else
  echo "  Database '${_PGDB}' already exists."
fi

# ── 3. Run pending migrations ─────────────────────────────────────────────────
echo "▸ running migrations …"
PYTHONPATH="$(printf '%s:' "$_REPO_ROOT"/packages/kerf-*/src | sed 's/:$//')" \
  python3 -m kerf_core.db.migrations.runner "$DATABASE_URL"

# ── 4. Build static config + docs manifest ────────────────────────────────────
echo "▸ building config + docs manifest …"
node ./scripts/init-config.mjs
node ./scripts/build-docs-manifest.mjs

# ── 5. SIGINT trap — kill both background processes on Ctrl-C ─────────────────
_API_PID=""
_cleanup() {
  echo ""
  echo "▸ shutting down …"
  [[ -n "$_API_PID" ]] && kill "$_API_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "  done."
}
trap _cleanup INT TERM

# ── 6. Start backend (port 8080) in the background ───────────────────────────
echo "▸ starting API (:8080, local mode) …"
PYTHONPATH="$(printf '%s:' "$_REPO_ROOT"/packages/kerf-*/src | sed 's/:$//')" \
  python3 -m kerf_core --port 8080 --reload &
_API_PID=$!

# ── 7. Start Vite dev server in the foreground ───────────────────────────────
echo "▸ starting web (:5173) — Ctrl-C to stop"
npx vite --port 5173

# If Vite exits normally (e.g. port already in use), also stop the API
_cleanup
