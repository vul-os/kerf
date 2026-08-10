#!/usr/bin/env bash
# build-desktop.sh — build the Kerf desktop one-file binary.
#
#   ./scripts/build-desktop.sh
#
# Cross-platform: runs under bash on macOS, Linux, AND Windows (GitHub's
# windows-latest runners ship Git for Windows' bash, which is what CI uses —
# see .github/workflows/release.yml's `desktop` job). It auto-detects the
# venv layout (POSIX bin/ vs. Windows Scripts/) and the produced binary's
# name (kerf-desktop vs. kerf-desktop.exe); nothing else about the build
# differs per OS. Verified locally on macOS only — see docs/desktop-build.md
# and the `desktop` job comments for what CI additionally proves on Windows
# and Linux.
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
#      packages/kerf-desktop/dist/kerf-desktop (kerf-desktop.exe on
#      Windows).
#
# Output:
#   packages/kerf-desktop/dist/kerf-desktop        (macOS, Linux)
#   packages/kerf-desktop/dist/kerf-desktop.exe    (Windows)
#
# See docs/desktop-build.md for what the binary includes, what it does
# NOT (OCCT B-rep, real FEM — both conda-only), and how to run it.
#
# Env overrides:
#   DESKTOP_VENV   — venv path to build in (default: .venv-desktop-build,
#                     gitignored, at the repo root)
#   PYTHON         — interpreter to create that venv with (default: python3;
#                     on a Windows runner where only `python` is on PATH,
#                     set PYTHON=python)
#   DESKTOP_VENV_SYSTEM_SITE_PACKAGES
#                  — if "1", create the venv with --system-site-packages.
#                    Linux only, and only useful if you've apt-installed
#                    python3-gi et al for the system interpreter yourself;
#                    the `desktop` CI job does NOT set this (see its
#                    comment for why: apt's python3-gi is bound to the
#                    system interpreter, which may not match the venv's).
#                    Default: unset ("0").

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

venv_dir="${DESKTOP_VENV:-$repo_root/.venv-desktop-build}"
python_bin="${PYTHON:-python3}"

echo "==> [1/3] building frontend (web/dist)"
if [ "${KERF_SKIP_FRONTEND_BUILD:-}" = "1" ]; then
  # CI builds the frontend in a dedicated step so a vite failure shows up in
  # the run log instead of being buried in this subshell.
  echo "    (skipped: KERF_SKIP_FRONTEND_BUILD=1 — web/dist built by the caller)"
else
  ( cd web && npm run build )
fi

if [ ! -f web/dist/index.html ]; then
  echo "error: web/dist/index.html missing after 'npm run build'" >&2
  exit 1
fi

echo "==> [2/3] preparing build venv at $venv_dir"
if [ ! -d "$venv_dir" ]; then
  venv_extra_args=()
  if [ "${DESKTOP_VENV_SYSTEM_SITE_PACKAGES:-0}" = "1" ]; then
    venv_extra_args+=(--system-site-packages)
  fi
  # "${arr[@]}" on an EMPTY array trips `set -u` on bash 3.2, which is what
  # macOS (and the macos-latest runner) ships — the v0.1.7 desktop legs all
  # died here with "venv_extra_args[@]: unbound variable". The ${arr[@]+...}
  # form expands to nothing when the array is empty instead of erroring, and
  # is portable back to bash 3.
  "$python_bin" -m venv ${venv_extra_args[@]+"${venv_extra_args[@]}"} "$venv_dir"
fi

# POSIX venvs (macOS, Linux) put executables in bin/; venvs created by a
# Windows python.exe (even when this script itself runs under Windows' bash)
# put them in Scripts/ with a .exe suffix. Detect rather than assume.
if [ -x "$venv_dir/bin/pip" ]; then
  venv_bin="$venv_dir/bin"
  venv_pip="$venv_bin/pip"
  venv_pyinstaller="$venv_bin/pyinstaller"
elif [ -x "$venv_dir/Scripts/pip.exe" ]; then
  venv_bin="$venv_dir/Scripts"
  venv_pip="$venv_bin/pip.exe"
  venv_pyinstaller="$venv_bin/pyinstaller.exe"
else
  echo "error: no pip found under $venv_dir/bin or $venv_dir/Scripts — venv creation failed?" >&2
  exit 1
fi

"$venv_pip" install --upgrade pip -q

# pywebview's GTK/WebKitGTK backend (the only backend on Linux — there is no
# bundled Chromium) needs PyGObject + pycairo at import time. Neither is a
# hard dependency of pywebview (only pulled in via its `[gtk]` extra), so on
# a Linux build host we install them explicitly here. They compile from
# source against system dev headers (libgirepository1.0-dev, libcairo2-dev,
# pkg-config, gcc/python3-dev) — the `desktop` CI job's Linux leg installs
# those before calling this script; without them this pip install fails
# loudly with a "pkg-config not found" style error instead of silently
# shipping a binary whose window never opens.
extra_pip_args=()
case "$(uname -s)" in
  Linux*) extra_pip_args+=(pygobject pycairo) ;;
esac

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
  -e "packages/kerf-desktop[build]" \
  ${extra_pip_args[@]+"${extra_pip_args[@]}"}

echo "==> [3/3] running PyInstaller"
( cd packages/kerf-desktop && "$venv_pyinstaller" --noconfirm kerf-desktop.spec )

bin_out="packages/kerf-desktop/dist/kerf-desktop"
[ -f "${bin_out}.exe" ] && bin_out="${bin_out}.exe"

if [ ! -f "$bin_out" ]; then
  echo "error: PyInstaller reported success but no binary found at packages/kerf-desktop/dist/kerf-desktop(.exe)" >&2
  exit 1
fi

echo
echo "done: $bin_out"
du -h "$bin_out" 2>/dev/null || true
