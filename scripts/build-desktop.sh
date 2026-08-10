#!/usr/bin/env bash
# build-desktop.sh — build the Kerf desktop one-file binary.
#
#   ./scripts/build-desktop.sh
#
# What this does:
#   1. Builds the frontend (npm run build -> web/dist).
#   2. Creates (or reuses) a build venv and installs the "desktop" persona
#      into it: kerf-core, kerf-auth, kerf-api, kerf-chat, kerf-cad-core,
#      kerf-tess, kerf-fem, kerf-cam, kerf-topo, kerf-mates, kerf-desktop
#      (with its [build] extra: pyinstaller). This is the SAME package set
#      as the `mech` persona in the root pyproject.toml, minus nothing —
#      every dependency here is pip-installable; see
#      packages/kerf-desktop/pyproject.toml for exactly why OCCT
#      (pythonOCC) and FEM (FEniCSx/dolfinx) are excluded.
#   3. Runs PyInstaller against packages/kerf-desktop/kerf-desktop.spec,
#      which embeds web/dist and produces one binary at
#      packages/kerf-desktop/dist/kerf-desktop.
#
# Output:
#   packages/kerf-desktop/dist/kerf-desktop   (the one-file binary)
#
# See docs/desktop-build.md for what the binary includes, what it does
# NOT (OCCT B-rep, real FEM — both conda-only), and how to run it.
#
# Env overrides:
#   DESKTOP_VENV   — venv path to build in (default: .venv-desktop-build,
#                     gitignored, at the repo root)
#   PYTHON         — interpreter to create that venv with (default: python3)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

venv_dir="${DESKTOP_VENV:-$repo_root/.venv-desktop-build}"
python_bin="${PYTHON:-python3}"

echo "==> [1/3] building frontend (web/dist)"
( cd web && npm run build )

if [ ! -f web/dist/index.html ]; then
  echo "error: web/dist/index.html missing after 'npm run build'" >&2
  exit 1
fi

echo "==> [2/3] preparing build venv at $venv_dir"
if [ ! -d "$venv_dir" ]; then
  "$python_bin" -m venv "$venv_dir"
fi
venv_pip="$venv_dir/bin/pip"
venv_pyinstaller="$venv_dir/bin/pyinstaller"

"$venv_pip" install --upgrade pip -q
"$venv_pip" install -q \
  -e packages/kerf-core \
  -e packages/kerf-auth \
  -e packages/kerf-api \
  -e packages/kerf-chat \
  -e packages/kerf-cad-core \
  -e packages/kerf-tess \
  -e packages/kerf-fem \
  -e packages/kerf-cam \
  -e packages/kerf-topo \
  -e packages/kerf-mates \
  -e "packages/kerf-desktop[build]"

echo "==> [3/3] running PyInstaller"
( cd packages/kerf-desktop && "$venv_pyinstaller" --noconfirm kerf-desktop.spec )

echo
echo "done: packages/kerf-desktop/dist/kerf-desktop"
du -h packages/kerf-desktop/dist/kerf-desktop 2>/dev/null || true
