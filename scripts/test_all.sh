#!/usr/bin/env bash
#
# test_all.sh — unified test harness for Kerf.
#
# Usage:
#   ./scripts/test_all.sh
#
# Runs (in order):
#   1. Backend pytest (all packages/kerf-*/tests/)
#   2. Frontend vitest run
#   3. Frontend production build (npm run build)
#
# Non-zero exit on any failure. Each section prints a clear header.
# Set DATABASE_URL to override the default local Postgres URL.

set -uo pipefail
_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Defaults ─────────────────────────────────────────────────────────────────
DATABASE_URL="${DATABASE_URL:-postgres://pc@localhost:5432/kerf?sslmode=disable}"
export DATABASE_URL

PASS=0
FAIL=0
FAILED_SECTIONS=()

_section() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  $1"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

_pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
_fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); FAILED_SECTIONS+=("$1"); }

# ── 1. Backend pytest ─────────────────────────────────────────────────────────
_section "1/3  Backend — pytest"

cd "$_REPO_ROOT"

# Build PYTHONPATH from all packages/kerf-*/src dirs
PYPATH=""
for pkg_src in "$_REPO_ROOT"/packages/kerf-*/src; do
  [[ -d "$pkg_src" ]] || continue
  PYPATH="${PYPATH:+${PYPATH}:}${pkg_src}"
done
export PYTHONPATH="$PYPATH"

# 1a. Parallel bulk — every package EXCEPT the DB-integration ones, run across
# all cores via pytest-xdist.
#   - Must run from the repo root so the repo-root conftest.py loads (it
#     installs the asyncio-loop + tools-namespace shims that per-package
#     rootdirs would otherwise skip).
#   - PYTHONHASHSEED is pinned so set/dict iteration order is identical across
#     xdist workers; without it workers disagree on parametrized-test order
#     ("Different tests were collected between gw0 and gw1") and the run aborts.
#   - PYTEST_WORKERS overrides the worker count (default: auto = one per core).
if PYTHONHASHSEED=0 PYTHONPATH="$PYPATH" python3 -m pytest \
      packages/ \
      -n "${PYTEST_WORKERS:-auto}" \
      --ignore=packages/kerf-cloud \
      --ignore=packages/kerf-billing \
      --tb=short -q 2>&1; then
  _pass "pytest (bulk, parallel)"
else
  _fail "pytest (bulk, parallel)"
fi

# 1b. DB-integration packages (cloud + billing) — run SERIALLY (no -n). These
# assert on shared real-Postgres state (GC sweeps, billing debits) and cannot
# run concurrently against one database without per-worker DB isolation; they
# pass deterministically single-process. Set SKIP_DB_TESTS=1 to skip when no
# Postgres is available (DATABASE_URL).
if [[ "${SKIP_DB_TESTS:-0}" == "1" ]]; then
  echo "  [skip] cloud + billing (SKIP_DB_TESTS=1)"
elif PYTHONHASHSEED=0 PYTHONPATH="$PYPATH" python3 -m pytest \
      packages/kerf-cloud/tests/ \
      packages/kerf-billing/tests/ \
      --tb=short -q 2>&1; then
  _pass "pytest (cloud + billing, serial / DB)"
else
  _fail "pytest (cloud + billing, serial / DB)"
fi

# ── 2. Frontend vitest ────────────────────────────────────────────────────────
_section "2/3  Frontend — vitest run"

cd "$_REPO_ROOT"
if npx vitest run 2>&1; then
  _pass "vitest"
else
  _fail "vitest"
fi

# ── 3. Frontend production build ──────────────────────────────────────────────
_section "3/3  Frontend — npm run build"

cd "$_REPO_ROOT"
if npm run build 2>&1; then
  _pass "npm run build"
else
  _fail "npm run build"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  TEST SUMMARY"
echo "════════════════════════════════════════════════════════════════════════"
echo "  Passed : $PASS"
echo "  Failed : $FAIL"

if [[ ${#FAILED_SECTIONS[@]} -gt 0 ]]; then
  echo ""
  echo "  Failed sections:"
  for s in "${FAILED_SECTIONS[@]}"; do
    echo "    - $s"
  done
  echo ""
  echo "  RESULT: FAIL"
  exit 1
else
  echo ""
  echo "  RESULT: PASS"
  exit 0
fi
