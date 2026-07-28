#!/usr/bin/env bash
# install.sh — Kerf installer
#
#   curl -fsSL https://kerf.sh/install.sh | sh
#
# Downloads the latest (or pinned) Kerf release tarball from GitHub Releases,
# unpacks it, and runs the bundled setup.sh (creates a Python venv, installs
# the Kerf packages, writes a default config).
#
# Kerf is Python + Node, not a compiled binary — there is nothing to "install"
# beyond a versioned source + pre-built-frontend bundle plus a venv. The
# per-OS tarballs (macos-arm64 / macos-x64 / linux-x64) are identical in
# content and exist for naming-convention parity with a future single-binary
# build (TODO); today they differ only in the label you download.
#
# Env overrides:
#   KERF_VERSION  — tag to install, e.g. v0.1.0 (default: latest release)
#   KERF_HOME     — install location (default: ~/.local/share/kerf/<version>)
#   KERF_REPO     — GitHub repo to install from (default: kerf-sh/kerf)
#
# Requirements: bash, curl, tar, python3 3.11+ (checked by the bundled setup)
set -euo pipefail

REPO="${KERF_REPO:-kerf-sh/kerf}"

if [ -t 1 ]; then
  RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
  BLUE='\033[0;34m'; RESET='\033[0m'
else
  RED=''; YELLOW=''; GREEN=''; BLUE=''; RESET=''
fi

info() { printf "${BLUE}[kerf]${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}[kerf]${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}[kerf]${RESET} WARNING: %s\n" "$*" >&2; }
fail() { printf "${RED}[kerf]${RESET} ERROR: %s\n" "$*" >&2; exit 1; }

# ── Dependency check ─────────────────────────────────────────────────────────
command -v curl >/dev/null 2>&1 || fail "curl is required but not installed."
command -v tar  >/dev/null 2>&1 || fail "tar is required but not installed."

# ── Platform detection ───────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin*)
    case "$ARCH" in
      arm64)          ASSET_OS="macos-arm64" ;;
      x86_64)         ASSET_OS="macos-x64" ;;
      *) fail "Unsupported macOS architecture: $ARCH" ;;
    esac
    ;;
  Linux*)
    case "$ARCH" in
      x86_64|amd64)   ASSET_OS="linux-x64" ;;
      *)
        warn "No prebuilt tarball for linux/$ARCH — falling back to the universal source tarball."
        ASSET_OS="src"
        ;;
    esac
    ;;
  MINGW*|MSYS*|CYGWIN*)
    fail "Native Windows isn't supported. Install Windows Subsystem for Linux (WSL2) with Ubuntu, then re-run this script inside WSL."
    ;;
  *)
    fail "Unsupported OS: $OS. Kerf supports macOS and Linux (or Windows via WSL2)."
    ;;
esac

info "Platform: ${ASSET_OS}"

# ── Resolve version ──────────────────────────────────────────────────────────
KERF_VERSION="${KERF_VERSION:-}"
if [ -z "$KERF_VERSION" ]; then
  info "Resolving latest release..."
  KERF_VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
    | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
  [ -n "$KERF_VERSION" ] || fail "Could not resolve the latest release from https://github.com/${REPO}/releases. Set KERF_VERSION=vX.Y.Z to pin a version."
fi
info "Version: ${KERF_VERSION}"

VERSION_NO_V="${KERF_VERSION#v}"
KERF_HOME="${KERF_HOME:-$HOME/.local/share/kerf/${VERSION_NO_V}}"

# ── Already installed? ───────────────────────────────────────────────────────
if [ -d "$KERF_HOME" ] && [ -x "$KERF_HOME/setup.sh" ]; then
  info "Kerf ${KERF_VERSION} is already downloaded at ${KERF_HOME}."
  info "Re-running its setup.sh to make sure the venv + config are up to date..."
  "$KERF_HOME/setup.sh"
  mkdir -p "$HOME/.local/share/kerf"
  ln -sfn "$KERF_HOME" "$HOME/.local/share/kerf/current"
  ok "Done. See next steps above."
  exit 0
fi

# ── Download + unpack ────────────────────────────────────────────────────────
ASSET="kerf-${KERF_VERSION}-${ASSET_OS}.tar.gz"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${KERF_VERSION}/${ASSET}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

info "Downloading ${DOWNLOAD_URL} ..."
if ! curl -fsSL -o "${TMP_DIR}/${ASSET}" "$DOWNLOAD_URL"; then
  fail "Download failed. Check that ${KERF_VERSION} exists at https://github.com/${REPO}/releases"
fi

# ── Verify checksum (FAIL-CLOSED) ────────────────────────────────────────────
# Every path out of this block is either "verified" or "abort". This used to
# warn-and-continue when SHA256SUMS 404'd or didn't list the asset, which meant
# the common failure — no checksum file at all — installed unverified bytes
# while printing a line that looked like a verification step had run. A
# verifier that reports safety it did not check is worse than no verifier.
#
# There is deliberately no skip switch. SHA256SUMS is produced unconditionally
# by .github/workflows/release.yml (`sha256sum kerf-* > SHA256SUMS`) and
# attached to the release alongside the tarballs, so its absence means the
# release is incomplete or the download was tampered with — neither is a
# condition to shrug at. If you genuinely need unverified bytes, download the
# tarball yourself and unpack it by hand; that is an explicit act, not a
# silent default.
info "Verifying checksum..."
CHECKSUMS_URL="https://github.com/${REPO}/releases/download/${KERF_VERSION}/SHA256SUMS"

curl -fsSL -o "${TMP_DIR}/SHA256SUMS" "$CHECKSUMS_URL" 2>/dev/null \
  || fail "Could not fetch ${CHECKSUMS_URL} — refusing to install unverified bytes. Every Kerf release publishes SHA256SUMS; if it is missing, the release is incomplete. Report it at https://github.com/${REPO}/issues"

[ -s "${TMP_DIR}/SHA256SUMS" ] \
  || fail "${CHECKSUMS_URL} is empty — refusing to install unverified bytes."

# Exact filename match on field 2 — not a regex over the line, so a `.` in the
# asset name can never match a different asset.
EXPECTED=$(awk -v want="$ASSET" '$2 == want || $2 == "*" want { print $1; exit }' "${TMP_DIR}/SHA256SUMS")
[ -n "$EXPECTED" ] \
  || fail "${ASSET} is not listed in SHA256SUMS — refusing to install an asset the release does not vouch for."

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL=$(sha256sum "${TMP_DIR}/${ASSET}" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
  ACTUAL=$(shasum -a 256 "${TMP_DIR}/${ASSET}" | awk '{print $1}')
else
  fail "Neither sha256sum nor shasum is available — cannot verify ${ASSET}. Install coreutils (Linux) or Perl's shasum (macOS ships it) and re-run."
fi

[ -n "$ACTUAL" ] || fail "Checksum computation produced no output for ${ASSET}. Aborting."
[ "$EXPECTED" = "$ACTUAL" ] \
  || fail "Checksum mismatch for ${ASSET} — expected ${EXPECTED}, got ${ACTUAL}. Aborting."
ok "Checksum verified."

mkdir -p "$KERF_HOME"
info "Unpacking to ${KERF_HOME} ..."
tar -xzf "${TMP_DIR}/${ASSET}" -C "$KERF_HOME"

# Tarballs contain their content at the top level OR under one wrapper dir
# (kerf-vX.Y.Z/) depending on how they were produced; handle both.
if [ ! -x "$KERF_HOME/setup.sh" ]; then
  # -mindepth 1: without it `find` also yields $KERF_HOME itself, so a
  # KERF_HOME whose own basename starts with "kerf-" (e.g. KERF_HOME=~/kerf-dev)
  # matched first and the unwrap silently did nothing.
  INNER="$(find "$KERF_HOME" -mindepth 1 -maxdepth 1 -type d -name 'kerf-*' | head -1)"
  if [ -n "$INNER" ] && [ -x "$INNER/setup.sh" ]; then
    shopt -s dotglob 2>/dev/null || true
    mv "$INNER"/* "$KERF_HOME"/
    rmdir "$INNER"
  fi
fi

[ -x "$KERF_HOME/setup.sh" ] || fail "Unpacked archive doesn't contain an executable setup.sh — this release looks broken."

# ── Run the bundled setup ────────────────────────────────────────────────────
info "Running bundled setup..."
"$KERF_HOME/setup.sh"

mkdir -p "$HOME/.local/share/kerf"   # KERF_HOME may live elsewhere; the
                                     # "current" symlink still goes here
ln -sfn "$KERF_HOME" "$HOME/.local/share/kerf/current"
ok "Kerf ${KERF_VERSION} installed at ${KERF_HOME} (symlinked as ~/.local/share/kerf/current)."
