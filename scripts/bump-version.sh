#!/usr/bin/env bash
# bump-version.sh — bump the monorepo version in one shot.
#
# Usage:  ./scripts/bump-version.sh <new-version>
#   e.g.  ./scripts/bump-version.sh 0.2.0
#
# Updates:
#   VERSION                          (single source of truth)
#   pyproject.toml                   (root meta-package)
#   packages/kerf-*/pyproject.toml   (all plugins EXCEPT kerf-sdk)
#   package.json                     (frontend / npm)
#
# Then commits the bump with:
#   chore: bump version to v<new-version>
#
# After this script, tag and push:
#   git tag v<new-version>
#   git push origin v<new-version>
#
# kerf-sdk is deliberately excluded — it has its own independent version
# cadence on PyPI, triggered by sdk-v* tags.

set -euo pipefail

# ── Args ──────────────────────────────────────────────────────────────────────
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <new-version>  (e.g. $0 0.2.0)" >&2
  exit 1
fi

NEW="$1"

# Basic semver shape check (X.Y.Z, optionally with pre-release/build suffix)
if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9] ]]; then
  echo "Error: '$NEW' doesn't look like a semver version (expected X.Y.Z...)." >&2
  exit 1
fi

# ── Repo root ─────────────────────────────────────────────────────────────────
REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

# ── Dirty-tree guard ──────────────────────────────────────────────────────────
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: working tree is dirty. Commit or stash changes before bumping." >&2
  exit 1
fi

# ── Read current version from VERSION file ────────────────────────────────────
CURRENT="$(cat VERSION | tr -d '[:space:]')"
echo "Bumping  $CURRENT  →  $NEW"

# ── Helper: in-place sed that works on both GNU and BSD/macOS ─────────────────
sedi() {
  # macOS sed requires an explicit backup extension with -i; GNU sed is happy
  # with an empty string.  Use a tmp-file approach to stay portable.
  local pattern="$1" file="$2"
  local tmp
  tmp="$(mktemp)"
  sed "$pattern" "$file" > "$tmp" && mv "$tmp" "$file"
}

# ── 1. VERSION file ───────────────────────────────────────────────────────────
printf '%s\n' "$NEW" > VERSION

# ── 2. Root pyproject.toml ────────────────────────────────────────────────────
sedi "s/^version = \"${CURRENT}\"/version = \"${NEW}\"/" pyproject.toml

# ── 3. Plugin packages (skip kerf-sdk) ───────────────────────────────────────
for f in packages/kerf-*/pyproject.toml; do
  # kerf-sdk has its own independent version cadence — skip it.
  if [[ "$f" == packages/kerf-sdk/* ]]; then
    continue
  fi
  sedi "s/^version = \"${CURRENT}\"/version = \"${NEW}\"/" "$f"
done

# ── 4. package.json ───────────────────────────────────────────────────────────
# Match the "version": "X.Y.Z" line specifically (first occurrence is enough).
sedi "s/\"version\": \"${CURRENT}\"/\"version\": \"${NEW}\"/" package.json

# ── 5. Commit ─────────────────────────────────────────────────────────────────
FILES_TO_STAGE=(
  VERSION
  pyproject.toml
  package.json
)
for f in packages/kerf-*/pyproject.toml; do
  [[ "$f" == packages/kerf-sdk/* ]] && continue
  FILES_TO_STAGE+=("$f")
done

git add "${FILES_TO_STAGE[@]}"
git commit -m "chore: bump version to v${NEW}"

echo ""
echo "Done.  Next steps:"
echo "  git tag v${NEW}"
echo "  git push origin v${NEW}"
echo ""
echo "GitHub Actions will build + push Docker images and create the release."
