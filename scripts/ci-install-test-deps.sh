#!/usr/bin/env bash
# ci-install-test-deps.sh — install every package's test-only deps, for CI.
#
#   ./scripts/ci-install-test-deps.sh
#
# Why this exists (separate from dev-install.sh)
# -----------------------------------------------
# dev-install.sh installs a "persona" — a curated subset of packages a real
# deployment needs (see its own header). Running the test suite needs more
# than that in two ways it does not cover:
#
#   1. Coverage: `make test-kernel` / `make test-domains` exercise packages
#      outside every persona's list entirely (e.g. kerf-aero, kerf-textiles,
#      kerf-mold, kerf-cli, kerf-worker, kerf-sdk — none are in the "full"
#      persona). The repo-root conftest.py puts every package's src/ on
#      sys.path regardless of whether it was pip-installed, so the MODULE
#      still imports — but that only papers over the package itself; a
#      package that pip never saw still has none of its declared runtime
#      dependencies installed, nor is it a real installed distribution
#      (kerf-cli/tests/test_packaging.py checks importlib.metadata entry
#      points, which needs a real install, not just a sys.path insert).
#   2. Test-only deps: several packages declare a `[project.optional-
#      dependencies].dev` extra for deps their tests need but production
#      code doesn't (moto for kerf-core, respx for kerf-sdk/kerf-render,
#      steputils for kerf-cad-core, ...). dev-install.sh installs plain
#      `-e path`, with no extras, for the packages it does cover — so even
#      persona packages are missing their test-only deps.
#
# This script installs EVERY packages/kerf-* directory that has a
# pyproject.toml, editable, with `[dev]` appended. Packages that don't
# declare a `dev` extra just get a harmless
# "WARNING: kerf-x does not provide the extra 'dev'" — pip does not error on
# that, it's not worth the complexity of checking first. All packages are
# passed to a SINGLE pip invocation (same reasoning as dev-install.sh:
# inter-package `kerf-x>=0.1.0` requirements need to resolve from the local
# checkout, which only works if every local path is visible to the same
# resolver call).
#
# Deliberately NOT here: no extra other than `[dev]` is ever requested, so
# this never pulls in the conda-forge-only extras (kerf-cad-core[occ],
# kerf-fem[fenicsx]) — those still cannot be installed by pip at all; see
# dev-install.sh's header. Run dev-install.sh FIRST if you also want the
# "full" persona's own runtime deps resolved via its normal path — this
# script is additive, not a replacement.
#
# Non-Python SDK dirs (kerf-sdk-go, kerf-sdk-rs, kerf-sdk-ts, kerf-sdk-lua)
# are skipped — no pyproject.toml, not pip-installable.

set -euo pipefail

PIP="${PIP:-pip}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

args=()
for dir in packages/kerf-*/; do
  dir="${dir%/}"
  [ -f "$dir/pyproject.toml" ] || continue
  args+=("-e" "${dir}[dev]")
done

echo "installing [dev] extras for ${#args[@]} package paths with: $PIP"
"$PIP" install "${args[@]}"
