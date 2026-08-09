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
# The working path from source, today, is this script: it installs every
# package a persona needs editable in a SINGLE `pip install` invocation so
# pip satisfies the inter-package `kerf-* >= 0.1.0` requirements from the
# local checkout. `uv sync --extra <persona>` does NOT currently work for any
# persona — kerf-cad-core, kerf-cam, kerf-fem, and kerf-topo each declare a
# conda-forge-only extra (see below), and uv resolves one lockfile for the
# whole workspace, so it always tries to satisfy those extras regardless of
# which `--extra` you request, failing with "No solution found ...
# requirements are unsatisfiable" even for `--extra api-only` or a bare
# `uv sync`.
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

# The package set is DERIVED from the root pyproject.toml's
# [project.optional-dependencies] rather than duplicated here.
#
# It used to be a hardcoded list per persona with a comment saying "keep in
# sync when a persona's plugin list changes". It drifted badly: `full` was
# missing 36 of its packages (kerf-pub among them, so CI installed no
# /api/pub/* surface at all and the Workshop e2e spec 404'd), while listing two
# — kerf-billing and kerf-pricing — that no persona contains. A list that must
# be hand-synced with another list eventually is not.
pkgs="$(python3 - "$persona" <<'PYEOF'
import re, sys, tomllib
persona = sys.argv[1]
data = tomllib.load(open("pyproject.toml", "rb"))
extras = data["project"].get("optional-dependencies", {})
if persona not in extras:
    sys.stderr.write(
        f"error: unknown persona {persona!r}\n"
        f"usage: dev-install.sh [{'|'.join(sorted(extras))}]\n"
    )
    raise SystemExit(1)
def bare(dep):
    return re.split(r"[<>=!\[;\s]", dep.strip(), maxsplit=1)[0]

# Every kerf-* directory in packages/ is installable from this checkout.
root = __import__("pathlib").Path("packages")
local = {d.name for d in root.iterdir() if d.is_dir() and d.name.startswith("kerf-")}

# Close over workspace-local dependencies. A persona lists the plugins it wants,
# but those plugins may depend on other workspace packages that no persona names
# — kerf-horology depends on kerf-partsgen, which is a workspace member and is
# not on PyPI. Without this closure pip tries to fetch it from the index and the
# whole install dies with "No matching distribution found for kerf-partsgen".
seen, queue, out = set(), [bare(d) for d in extras[persona]], []
while queue:
    name = queue.pop(0)
    if name in seen or not name.startswith("kerf-") or name == "kerf-sdk":
        continue
    seen.add(name)
    if name not in local:
        continue
    out.append(name)
    sub = root / name / "pyproject.toml"
    if sub.exists():
        subdata = tomllib.load(open(sub, "rb"))
        queue += [bare(d) for d in subdata.get("project", {}).get("dependencies", [])]
print(" ".join(dict.fromkeys(out)))
PYEOF
)" || exit 1

if [[ -z "$pkgs" ]]; then
  echo "error: persona '$persona' resolved to no kerf-* packages" >&2
  exit 1
fi

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
