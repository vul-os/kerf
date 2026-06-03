#!/usr/bin/env bash
#
# seed-dev.sh — seed the local Kerf database with realistic dev data.
#
# Delegates to scripts/seed_dev_data.py (idempotent — re-running is safe).
#
# Usage:
#   ./scripts/seed-dev.sh
#   DATABASE_URL=postgres://other@host/db ./scripts/seed-dev.sh   # override DB
#
# What it creates (all prefixed with _seed_ so they're easy to identify):
#   - _seed_BIM Example      : 1 BIM project (walls/floor/roof shell)
#   - _seed_Mechanical Part  : 1 mechanical project (5-feature part)
#   - _seed_PCB Example      : 1 PCB project (3 components)
#   - _seed_Component Library: 1 library project (10 BOM parts)
#
# All seeds are idempotent — projects that already exist are skipped.

set -euo pipefail

_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$_REPO_ROOT"

# pc role + kerf db (per project memory)
export DATABASE_URL="${DATABASE_URL:-postgres://pc@localhost:5432/kerf?sslmode=disable}"

echo "▸ seeding dev data into ${DATABASE_URL%%\?*} …"
PYTHONPATH="$(printf '%s:' "$_REPO_ROOT"/packages/kerf-*/src | sed 's/:$//')" \
  python3 "$_REPO_ROOT/scripts/seed_dev_data.py"
echo "▸ seed complete."
