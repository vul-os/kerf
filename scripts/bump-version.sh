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
#   web/package.json                 (frontend / npm)
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

# ── 0. Pre-flight ─────────────────────────────────────────────────────────────
# Every path this script touches is checked BEFORE anything is rewritten.
#
# Why: the steps below rewrite version strings first and `git add` them last, so
# a single wrong path used to fail at the very end with "pathspec did not match"
# — exiting non-zero while leaving the whole tree bumped but uncommitted. That
# is how v0.1.4 was tagged onto the wrong commit: the caller piped this script
# through `tail`, which masked the non-zero exit, and the `&&` chain carried on.
# The frontend restructure (package.json -> web/package.json) is exactly the
# kind of move that reintroduces this, so fail loudly and early instead.
_missing=()
for _f in VERSION pyproject.toml web/package.json; do
  [[ -e "$_f" ]] || _missing+=("$_f")
done
for _f in packages/kerf-*/pyproject.toml; do
  [[ "$_f" == packages/kerf-sdk/* ]] && continue
  [[ -e "$_f" ]] || _missing+=("$_f")
done
if (( ${#_missing[@]} )); then
  echo "bump-version: refusing to run — these paths do not exist:" >&2
  printf '  %s\n' "${_missing[@]}" >&2
  echo "Nothing has been modified. Update this script's paths and re-run." >&2
  exit 1
fi

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
sedi "s/\"version\": \"${CURRENT}\"/\"version\": \"${NEW}\"/" web/package.json

# ── 5. Commit ─────────────────────────────────────────────────────────────────
FILES_TO_STAGE=(
  VERSION
  pyproject.toml
  # web/package.json, not package.json — the frontend moved into web/ and this
  # path was not updated, so `git add` failed with "pathspec did not match" and
  # the script exited 128 AFTER already rewriting every version string. That
  # left the tree bumped but uncommitted, which is how v0.1.4 once got tagged
  # onto the wrong commit.
  web/package.json
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
