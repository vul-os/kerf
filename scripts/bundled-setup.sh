#!/usr/bin/env bash
# bundled-setup.sh — runs INSIDE an unpacked Kerf release tarball.
#
# This is not meant to be run from a git clone. It is copied to the root of
# every `kerf-vX.Y.Z-*.tar.gz` release archive as `setup.sh` by
# .github/workflows/release.yml, alongside the pre-built frontend (dist/)
# and the `packages/kerf-*` Python source. Root install.sh downloads and
# unpacks the archive, then execs this script.
#
# What it does:
#   1. Verifies python3 >= 3.11 is on PATH (Kerf's floor, per pyproject.toml).
#   2. Creates a venv at <this-dir>/venv.
#   3. Editable-installs every bundled packages/kerf-* plugin (except
#      kerf-sdk, which is PyPI-only) — equivalent to the "full" persona.
#      v0 ships one persona per tarball; a slimmer persona-scoped tarball
#      is a TODO for a later release (see docs/releasing.md).
#   4. Copies kerf.example.toml -> kerf.toml if one doesn't already exist.
#   5. Prints next steps (createdb, migrate, start).
#
# Safe to re-run: an existing venv or kerf.toml is left alone (rerun with
# KERF_FORCE_VENV=1 to rebuild the venv from scratch, e.g. after an upgrade).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$DIR/venv"
CONFIG_FILE="$DIR/kerf.toml"

if [ -t 1 ]; then
  BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
else
  BOLD=''; GREEN=''; YELLOW=''; RED=''; RESET=''
fi

info() { printf "${GREEN}[kerf setup]${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}[kerf setup]${RESET} WARNING: %s\n" "$*" >&2; }
fail() { printf "${RED}[kerf setup]${RESET} ERROR: %s\n" "$*" >&2; exit 1; }

# ── 1. Python floor check ───────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install Python 3.11+ and re-run this script."

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  fail "Python 3.11+ required (found $(python3 --version 2>&1)). See https://kerf.sh/docs for install help."
fi
info "python3 $(python3 --version 2>&1 | awk '{print $2}') — ok"

# ── 2. venv ──────────────────────────────────────────────────────────────────
if [ -d "$VENV_DIR" ] && [ "${KERF_FORCE_VENV:-0}" != "1" ]; then
  info "venv already exists at $VENV_DIR — reusing (set KERF_FORCE_VENV=1 to rebuild)."
else
  info "Creating venv at $VENV_DIR ..."
  rm -rf "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

PIP="$VENV_DIR/bin/pip"
"$PIP" install --upgrade pip --quiet

# ── 3. Editable-install every bundled plugin package (skip kerf-sdk) ────────
info "Installing Kerf packages (this can take a few minutes on first run) ..."
PKG_ARGS=()
for pkg_dir in "$DIR"/packages/kerf-*/; do
  pkg="$(basename "$pkg_dir")"
  [ "$pkg" = "kerf-sdk" ] && continue
  PKG_ARGS+=("-e" "$pkg_dir")
done
if [ "${#PKG_ARGS[@]}" -eq 0 ]; then
  fail "No packages/kerf-* directories found under $DIR — this archive looks incomplete."
fi
"$PIP" install --quiet "${PKG_ARGS[@]}"
info "Packages installed into $VENV_DIR"

# ── 4. Config ────────────────────────────────────────────────────────────────
if [ -f "$CONFIG_FILE" ]; then
  info "Config already exists at $CONFIG_FILE — leaving it alone."
else
  cp "$DIR/kerf.example.toml" "$CONFIG_FILE"
  info "Config written to $CONFIG_FILE (from kerf.example.toml)."
  warn "Edit $CONFIG_FILE: set [database].url and at least one [llm.*] api_key before starting."
fi

# ── 5. Next steps ─────────────────────────────────────────────────────────────
printf "\n${BOLD}Kerf installed at %s${RESET}\n\n" "$DIR"
printf "Next steps:\n\n"
printf "  1. Make sure Postgres 14+ is running, then create the database:\n"
printf "       createdb kerf\n\n"
printf "  2. Edit config if you haven't:\n"
printf "       \$EDITOR %s\n\n" "$CONFIG_FILE"
printf "  3. Apply migrations:\n"
printf "       %s/bin/python -m kerf_core.db.migrations.runner \"\$DATABASE_URL\"\n\n" "$VENV_DIR"
printf "  4. Start the server (serves the pre-built frontend from ./dist):\n"
printf "       KERF_FRONTEND_DIST=%s/dist \\\\\n" "$DIR"
printf "       KERF_CONFIG=%s \\\\\n" "$CONFIG_FILE"
printf "       %s/bin/kerf-server --host 0.0.0.0 --port 8080\n\n" "$VENV_DIR"
printf "  5. Open http://localhost:8080\n\n"
printf "  Docs: https://kerf.sh/docs\n"
