#!/usr/bin/env bash
# dev-install.sh — install the Kerf workspace packages editable, from source.
#
#   ./scripts/dev-install.sh [persona]      # persona defaults to "mech"
#
# Why this exists
# ---------------
# The repo is a `uv` workspace: `[tool.uv.sources]` in the root pyproject.toml
# redirects the `kerf-*` requirements to the local `packages/*` dirs. That
# redirect is understood by `uv` but NOT by plain `pip` — so a bare
# `pip install -e .[mech]` makes pip try to fetch `kerf-core`, `kerf-api`, …
# from PyPI (where they are unpublished) and fails with
# "No matching distribution found for kerf-core".
#
# Two working paths from source:
#   • uv users:  uv sync --extra <persona>   (uv resolves the workspace)
#   • pip users: this script, which installs every package a persona needs
#     editable in a SINGLE `pip install` invocation so pip satisfies the
#     inter-package `kerf-* >= 0.1.0` requirements from the local checkout.
#
# Heavy solver deps are NOT handled here
# --------------------------------------
# The `mech`/`full` personas' compute extras — pythonOCC (`kerf-cad-core[occ]`)
# and FEniCSx/dolfinx (`kerf-fem[fenicsx]`) — are conda-forge-only and cannot be
# pip-installed. Install those in a conda env; see docs/local-install.md. This
# script installs the pure-Python/PyPI stack, which is enough to boot the server
# (CAD/FEM tools degrade gracefully when their solver is absent).
#
# Env overrides:
#   PIP   — pip executable to use (default: `pip`; point at a venv/conda pip)

set -euo pipefail

persona="${1:-mech}"
PIP="${PIP:-pip}"

# Resolve repo root from this script's location so it works from any cwd.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# Package sets mirror the [project.optional-dependencies] personas in the root
# pyproject.toml. Keep in sync when a persona's plugin list changes.
core="kerf-core kerf-auth kerf-api kerf-chat"

case "$persona" in
  api-only)
    pkgs="$core kerf-v1" ;;
  mech)
    pkgs="$core kerf-cad-core kerf-tess kerf-fem kerf-cam kerf-topo kerf-mates" ;;
  electronics)
    pkgs="$core kerf-electronics" ;;
  bim)
    pkgs="$core kerf-bim" ;;
  full)
    pkgs="$core kerf-v1 kerf-billing kerf-cloud kerf-pricing \
          kerf-cad-core kerf-tess kerf-fem kerf-cam kerf-topo kerf-mates \
          kerf-electronics kerf-bim kerf-imports kerf-render kerf-workers" ;;
  *)
    echo "error: unknown persona '$persona'" >&2
    echo "usage: $0 [api-only|mech|electronics|bim|full]" >&2
    exit 1 ;;
esac

# Extras to pull in alongside a package. Only PyPI-installable ones belong here
# — the conda-forge-only solvers (pythonOCC, dolfinx) are deliberately absent,
# see the note above. IfcOpenShell IS on PyPI, and without it kerf-bim registers
# /compile-ifc but every .bim file fails to compile with
# "ifcopenshell not available", so the BIM viewer never receives a model.
declare -A extras=(
  [kerf-bim]="[ifc]"
)

# Only install packages that actually exist in this checkout (cloud packages
# may be absent from an OSS-only tree). Build the `-e path` argument list.
args=()
missing=()
for name in $pkgs; do
  if [ -d "packages/$name" ]; then
    args+=(-e "packages/${name}${extras[$name]:-}")
  else
    missing+=("$name")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "note: skipping packages not present in this checkout: ${missing[*]}" >&2
fi

echo "installing '$persona' persona editable with: $PIP"
echo "  packages: ${args[*]}"
"$PIP" install "${args[@]}"

echo
echo "done. Next:"
echo "  npm install"
echo "  npm run init && npm run migrate   # writes kerf.toml, applies DB schema"
echo "  npm run dev                        # Vite :5173 + kerf-server :8080"
