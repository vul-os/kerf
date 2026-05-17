#!/usr/bin/env bash
# entrypoint.sh — Kerf Cycles Worker startup script
#
# Environment variables (all optional):
#
#   KERF_BLENDER_PATH    Path to a user-supplied Blender binary (BYO mode).
#                        When set, this binary is used instead of the Docker-
#                        bundled /opt/blender/blender.
#                        Example: /Applications/Blender.app/Contents/MacOS/Blender
#
#   KERF_API_URL         Base URL of the Kerf API this worker reports to.
#                        Example: https://my-kerf.example.com
#
#   KERF_API_TOKEN       Auth token for the Kerf API.
#
#   KERF_WORKER_CONCURRENCY
#                        Number of render jobs to process in parallel.
#                        Defaults to 1.  GPU boxes typically want 1;
#                        CPU-only boxes may benefit from 2-4.
#
set -euo pipefail

# ── Version banner ──────────────────────────────────────────────────────────
KERF_RENDER_VERSION=$(python3 -c "
try:
    from importlib.metadata import version
    print(version('kerf-render'))
except Exception:
    print('dev')
" 2>/dev/null || echo "dev")

echo "========================================================"
echo " Kerf Cycles Worker"
echo " kerf-render version : ${KERF_RENDER_VERSION}"
echo " Python              : $(python3 --version 2>&1)"
echo "========================================================"

# ── Blender path resolution ─────────────────────────────────────────────────
if [ -n "${KERF_BLENDER_PATH:-}" ]; then
    if [ ! -x "${KERF_BLENDER_PATH}" ]; then
        echo "ERROR: KERF_BLENDER_PATH is set to '${KERF_BLENDER_PATH}' but that file is not executable." >&2
        exit 1
    fi
    BLENDER_BIN="${KERF_BLENDER_PATH}"
    echo " Blender (BYO)       : ${BLENDER_BIN}"
else
    # Prefer blender on PATH; fall back to the Docker-bundled location.
    BLENDER_BIN="$(command -v blender 2>/dev/null || echo '/opt/blender/blender')"
    echo " Blender (bundled)   : ${BLENDER_BIN}"
fi
export KERF_BLENDER_BIN="${BLENDER_BIN}"

# Print Blender version (non-fatal if missing — worker handles that gracefully)
if [ -x "${BLENDER_BIN}" ]; then
    BLENDER_VER="$("${BLENDER_BIN}" --version 2>/dev/null | head -1 || echo 'unknown')"
    echo " Blender version     : ${BLENDER_VER}"
else
    echo " WARNING: Blender binary not found at '${BLENDER_BIN}'." >&2
    echo "          Set KERF_BLENDER_PATH or ensure 'blender' is on PATH." >&2
fi

# ── API connectivity ─────────────────────────────────────────────────────────
if [ -n "${KERF_API_URL:-}" ]; then
    echo " API URL             : ${KERF_API_URL}"
else
    echo " API URL             : (not set — standalone / test mode)"
fi

if [ -n "${KERF_API_TOKEN:-}" ]; then
    echo " API token           : (set)"
else
    echo " API token           : (not set)"
fi

echo " Concurrency         : ${KERF_WORKER_CONCURRENCY:-1}"
echo "========================================================"

# ── Launch worker ───────────────────────────────────────────────────────────
exec python3 -m kerf_render.cycles_worker "$@"
