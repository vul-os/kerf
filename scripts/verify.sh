#!/usr/bin/env bash
# =============================================================================
# scripts/verify.sh — verify a downloaded Kerf release artifact, fail-closed.
#
# COPY THIS FILE. It is a template, not a shared dependency. It has no imports,
# no sourced helpers and no sibling scripts: `curl` and one of `sha256sum` /
# `shasum` are the whole runtime. See RELEASE-TEMPLATE.md for what to change.
#
# WHAT IT IS FOR
# ──────────────
# A release publishes assets plus a `SHA256SUMS` manifest. This script fetches
# the manifest, looks up the EXACT entry for the artifact you asked for,
# downloads the artifact and compares digests. It is what a user runs before
# executing bytes they pulled off the internet.
#
# THE CONTRACT: FAIL CLOSED
# ─────────────────────────
# There are exactly two outcomes: "these bytes are the published bytes" (exit
# 0) or a non-zero exit with a diagnostic naming what was wrong. There is NO
# --skip-verify, NO "warn and continue", and — the one that matters most — NO
# path where an ABSENT or UNREADABLE manifest is treated as "nothing to check".
#
# That last case is the bug this file exists to not have. A verifier that
# shrugs at a 404 on SHA256SUMS prints a line that looks like verification
# happened while checking nothing at all, and is strictly worse than no
# verifier: it converts "I don't know" into "it's fine".
#
# FOUR DEFECTS THIS DELIBERATELY DOES NOT HAVE
# ────────────────────────────────────────────
# These were all found in a sibling installer by adversarial audit. If you edit
# this file, re-read them, because each one is easy to reintroduce:
#
#  1. NO FALL-OPEN. Every fetch failure aborts. Nothing degrades to an
#     unverified path when the network, the CDN or the origin misbehaves.
#
#  2. NO SILENT DEATH AT A PIPELINE. Under `set -e` + `pipefail`, an assignment
#     like `x="$(grep ... | awk ... | head -1)"` KILLS THE SCRIPT with no
#     message when the grep matches nothing — so the carefully written "no
#     entry found" guard below it never runs. Every lookup pipeline here ends
#     in `|| true` and its result is then explicitly tested for emptiness. The
#     guard has to be reachable to be a guard.
#
#  3. NO `\n` IN A `%s`. Diagnostics are multi-line by design; `die` takes one
#     line per argument and prints each with its own `printf`. Nothing embeds
#     "\n" in a message, so no message can render as literal backslash-n, and
#     no filename or digest echoed back into a message is ever interpreted as
#     a printf format or a `%b` escape.
#
#  4. NO SUBSTRING / REGEX NAME MATCH. The artifact name is compared with awk
#     against FIELD 2 of the manifest, as a string. A substring grep treats the
#     name as a regex — every "." in "kerf-v0.1.0-linux-x64.tar.gz" is a wildcard
#     — and would happily return the digest of "...tar.gz.sig", or of a
#     differently-punctuated asset. The selftest plants exactly those two traps.
#
# EXIT CODES — each failure mode has its own code AND its own diagnostic
# ─────────────────────────────────────────────────────────────────────
#   0   every requested artifact matched the published digest
#   2   usage error (no artifact named, no --tag/--base-url, unknown flag)
#   3   SHA256SUMS could not be fetched / does not exist (HTTP error, DNS,
#       refused connection, or absent from a local --dir)
#   4   SHA256SUMS was served, but the body is an HTML page, not a manifest
#       (captive portal, CDN error page, a 200 that means "no such key")
#   5   SHA256SUMS is empty, or contains no well-formed "<64 hex>  <name>" line
#   6   SHA256SUMS is valid but has no entry for the artifact requested
#   7   the artifact itself could not be fetched (HTTP error, or an HTML page
#       served where artifact bytes were expected)
#   8   the artifact download was truncated — the origin closed the connection
#       before delivering the Content-Length it declared
#   9   digest mismatch: the bytes are not the published bytes
#  10   a required local tool (curl, sha256sum/shasum) is missing
#  11   --attest was requested and the provenance attestation did not verify
#  12   refusing a plaintext http:// origin (non-loopback)
#
# On any non-zero exit the partial download is deleted, so a failed run can
# never leave a file that a later step mistakes for a verified one.
#
# USAGE
# ─────
#   scripts/verify.sh --tag v0.1.0 kerf-v0.1.0-linux-x64.tar.gz
#   scripts/verify.sh --tag v0.1.0 --attest kerf-v0.1.0-linux-x64.tar.gz
#   scripts/verify.sh --repo vul-os/kerf --tag v0.1.0 --out ~/Downloads ASSET
#   scripts/verify.sh --base-url https://example.com/rel ASSET       # any origin
#   scripts/verify.sh --dir ./release-out ASSET...   # already downloaded
#   scripts/verify.sh --selftest                     # prove the guards refuse
#
# The digest check needs only curl + sha256sum. `--attest` additionally
# verifies the sigstore/OIDC build provenance GitHub attached at release time,
# and needs the `gh` CLI; without it the run says so out loud rather than
# implying provenance was checked.
# =============================================================================

set -euo pipefail

# ── Things a copying repo changes ────────────────────────────────────────────
DEFAULT_REPO="vul-os/kerf"
MANIFEST="SHA256SUMS"
# Asset name the --selftest synthetic origin publishes. The dots are
# load-bearing: two of the cases are name-matching traps that only bite a
# regex/substring lookup when the name contains "." characters.
SELFTEST_ARTIFACT="kerf-v9.9.9-linux-x64.tar.gz"
HTTP_TIMEOUT="${VERIFY_HTTP_TIMEOUT:-120}"

# ── Exit codes (named, so the selftest asserts on names not magic numbers) ───
E_USAGE=2
E_SUMS_FETCH=3
E_SUMS_HTML=4
E_SUMS_MALFORMED=5
E_NO_ENTRY=6
E_ART_FETCH=7
E_TRUNCATED=8
E_MISMATCH=9
E_NO_TOOL=10
E_ATTEST=11
E_INSECURE=12

if [ -t 2 ] && command -v tput >/dev/null 2>&1; then
  RED="$(tput setaf 1)"; GRN="$(tput setaf 2)"; YEL="$(tput setaf 3)"
  BLD="$(tput bold)"; RST="$(tput sgr0)"
else
  RED=''; GRN=''; YEL=''; BLD=''; RST=''
fi

# die <exit-code> <line> [line...]
#
# One argument per output line. The message is a printf ARGUMENT, never the
# format string (a '%' in a filename must not corrupt output), and it is
# rendered with %s, never %b (a backslash in a filename must not become an
# escape). Defect 3 lived precisely here.
die() {
  local code="$1"; shift
  printf '%s%s: FATAL:%s %s\n' "$RED" "$SELF_NAME" "$RST" "$1" >&2
  shift
  local line
  for line in "$@"; do printf '        %s\n' "$line" >&2; done
  exit "$code"
}
info() { printf '%s%s:%s %s\n' "$GRN" "$SELF_NAME" "$RST" "$*"; }
warn() { printf '%s%s: WARN:%s %s\n' "$YEL" "$SELF_NAME" "$RST" "$*" >&2; }

# Derived with parameter expansion and shell builtins ONLY (`cd`/`pwd`), never
# `basename`/`dirname`. This runs BEFORE the tool preflight below, so if it
# shelled out and PATH were broken, `set -e` would kill the script here with no
# message — reproducing, inside the verifier, the silent-death failure the
# verifier exists to refuse.
SELF_NAME="${BASH_SOURCE[0]##*/}"
SELF_DIR="${BASH_SOURCE[0]%/*}"
[ "$SELF_DIR" = "${BASH_SOURCE[0]}" ] && SELF_DIR="."
SELF_PATH="$(cd "$SELF_DIR" && pwd)/${SELF_NAME}"

# ── Preflight: no tool, no verification (never a skip) ───────────────────────
command -v curl >/dev/null 2>&1 || die "$E_NO_TOOL" \
  "curl is not installed, so nothing can be fetched or verified." \
  "Install curl and re-run. This script will not proceed unverified."

SHA_CMD=()
if command -v sha256sum >/dev/null 2>&1; then
  SHA_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  SHA_CMD=(shasum -a 256)
else
  die "$E_NO_TOOL" \
    "neither sha256sum nor shasum is available — no digest can be computed." \
    "Install GNU coreutils (Linux) or Perl's shasum (shipped with macOS)." \
    "Refusing to report an artifact as verified without computing its digest."
fi

# ── Small helpers ────────────────────────────────────────────────────────────

# sha256_of <file> → lowercase hex digest, or empty (never aborts the script).
sha256_of() {
  # `|| true` terminates the pipeline so `set -e`/`pipefail` cannot kill the
  # caller's assignment before the caller's emptiness check runs. Defect 2.
  "${SHA_CMD[@]}" "$1" 2>/dev/null | awk '{print $1}' | tr 'A-F' 'a-f' || true
}

# digest_for <artifact-name> <manifest-file> → the digest recorded for EXACTLY
# that name, lowercased, or nothing at all. Callers MUST treat empty as
# "unverifiable" and abort.
#
# Two things it deliberately does not do:
#   * it does not substring-match and it does not regex-match — awk compares
#     field 2 as a string, so "a.tar.gz" cannot match "aXtar.gz" and cannot
#     match "a.tar.gz.sig" (defect 4);
#   * it does not trust what it found — the value must be exactly 64 hex
#     characters, so an HTML body, a truncated line or a foreign format yields
#     nothing instead of feeding garbage into the comparison.
digest_for() {
  local want="$1" file="$2" found
  found="$(awk -v w="$want" '$2 == w || $2 == "*" w { print $1; exit }' "$file" 2>/dev/null || true)"
  printf '%s' "$found" | tr 'A-F' 'a-f' | grep -Ex '[0-9a-f]{64}' || true
}

# manifest_line_count <file> → number of well-formed "<64 hex>  <name>" lines.
manifest_line_count() {
  awk '$1 ~ /^[0-9A-Fa-f]{64}$/ && NF >= 2 { n++ } END { print n+0 }' "$1" 2>/dev/null || true
}

# looks_like_html <file> <content-type> → 0 if this is an HTML page.
looks_like_html() {
  local file="$1" ctype="${2:-}"
  case "$ctype" in
    text/html*|application/xhtml*) return 0 ;;
  esac
  [ -s "$file" ] || return 1
  if head -c 512 -- "$file" 2>/dev/null | LC_ALL=C grep -qiE '<(!doctype|html|head|body)\b'; then
    return 0
  fi
  return 1
}

# Plaintext http to anywhere but loopback means the manifest and the artifact
# both arrive from an unauthenticated channel, which makes comparing one
# against the other theatre. Loopback is allowed so the selftest can run.
require_secure_url() {
  case "$1" in
    https://*) return 0 ;;
    http://127.0.0.1:*|http://127.0.0.1/*|http://localhost:*|http://localhost/*) return 0 ;;
    *) die "$E_INSECURE" \
         "refusing to verify over a plaintext, non-loopback origin:" \
         "  $1" \
         "Both the manifest and the artifact would arrive unauthenticated, so" \
         "comparing them proves only that one attacker was self-consistent." \
         "Use an https:// URL." ;;
  esac
}

# fetch <url> <dest> → curl's exit status; sets FETCH_CODE/CTYPE/SIZE/ERR.
FETCH_CODE=""; FETCH_CTYPE=""; FETCH_SIZE=""; FETCH_ERR=""
fetch() {
  local url="$1" dest="$2" rc=0 out="" rest="" errf
  errf="${TMPDIR_V}/curl.err"
  : > "$errf"
  out="$(curl --fail --silent --show-error --location \
              --max-time "$HTTP_TIMEOUT" \
              --write-out '%{http_code}|%{content_type}|%{size_download}' \
              --output "$dest" -- "$url" 2>"$errf")" || rc=$?
  FETCH_CODE="${out%%|*}"
  rest="${out#*|}"
  FETCH_CTYPE="${rest%%|*}"
  FETCH_SIZE="${rest##*|}"
  FETCH_ERR="$(tr -d '\r' < "$errf" | head -3 | tr '\n' ' ' || true)"
  return "$rc"
}

# ── Argument parsing ─────────────────────────────────────────────────────────
REPO=""
TAG=""
BASE_URL=""
LOCAL_DIR=""
OUT_DIR="."
DO_ATTEST=0
ARTIFACTS=()

usage() {
  sed -n '/^# USAGE/,/^# =\{10,\}/p' -- "$SELF_PATH" | sed 's/^# \{0,1\}//' >&2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)      REPO="${2:-}";      shift 2 ;;
    --repo=*)    REPO="${1#*=}";     shift ;;
    --tag)       TAG="${2:-}";       shift 2 ;;
    --tag=*)     TAG="${1#*=}";      shift ;;
    --base-url)  BASE_URL="${2:-}";  shift 2 ;;
    --base-url=*) BASE_URL="${1#*=}"; shift ;;
    --dir)       LOCAL_DIR="${2:-}"; shift 2 ;;
    --dir=*)     LOCAL_DIR="${1#*=}"; shift ;;
    --out)       OUT_DIR="${2:-}";   shift 2 ;;
    --out=*)     OUT_DIR="${1#*=}";  shift ;;
    --attest)    DO_ATTEST=1;        shift ;;
    --selftest)  SELFTEST=1;         shift ;;
    -h|--help)   usage; exit 0 ;;
    --) shift; while [ $# -gt 0 ]; do ARTIFACTS+=("$1"); shift; done ;;
    -*) die "$E_USAGE" "unknown option: $1" "Run with --help for usage." ;;
    *)  ARTIFACTS+=("$1"); shift ;;
  esac
done

TMPDIR_V=""
cleanup() { [ -n "$TMPDIR_V" ] && rm -rf -- "$TMPDIR_V"; return 0; }
trap cleanup EXIT
TMPDIR_V="$(mktemp -d "${TMPDIR:-/tmp}/kerf-verify.XXXXXX")"

# =============================================================================
# The verifier
# =============================================================================
run_verify() {
  # ── Resolve where the manifest and the artifacts come from ────────────────
  local sums_src="" mode=""
  if [ -n "$LOCAL_DIR" ]; then
    mode="local"
    [ -z "$BASE_URL" ] || die "$E_USAGE" "--dir and --base-url are mutually exclusive."
    sums_src="${LOCAL_DIR%/}/${MANIFEST}"
  else
    mode="remote"
    if [ -z "$BASE_URL" ]; then
      [ -n "$TAG" ] || die "$E_USAGE" \
        "no release named: pass --tag vX.Y.Z (or --base-url URL, or --dir DIR)." \
        "There is deliberately no default tag: guessing which release you meant" \
        "and then verifying it successfully would answer a question you did not ask."
      REPO="${REPO:-$DEFAULT_REPO}"
      BASE_URL="https://github.com/${REPO}/releases/download/${TAG}"
    fi
    BASE_URL="${BASE_URL%/}"
    require_secure_url "$BASE_URL"
    sums_src="${BASE_URL}/${MANIFEST}"
  fi

  [ "${#ARTIFACTS[@]}" -gt 0 ] || die "$E_USAGE" \
    "no artifact named — nothing to verify." \
    "Usage: $SELF_NAME --tag vX.Y.Z <artifact-filename> [more...]" \
    "Exiting non-zero: a run that checked nothing must not look like a pass."

  # An empty or whitespace-only name is almost always an unquoted shell
  # variable that expanded to nothing in the CALLER (`verify.sh $ASSETS` with
  # ASSETS unset). Reject it here as a usage error: it would otherwise be
  # reported as "no entry for ''", which is fail-closed but sends the reader
  # hunting through the manifest for a bug that is in their own command line.
  local a
  for a in "${ARTIFACTS[@]}"; do
    [ -n "${a//[[:space:]]/}" ] || die "$E_USAGE" \
      "an empty (or whitespace-only) artifact name was passed." \
      "This is usually an unquoted variable that expanded to nothing, e.g." \
      "  $SELF_NAME --tag vX.Y.Z \$ASSET   with ASSET unset" \
      "Refusing rather than reporting 'no entry' for a name you did not mean."
  done

  # ── 1. Obtain the manifest ────────────────────────────────────────────────
  local sums="${TMPDIR_V}/${MANIFEST}"
  if [ "$mode" = "local" ]; then
    [ -d "$LOCAL_DIR" ] || die "$E_SUMS_FETCH" \
      "no such directory: $LOCAL_DIR" \
      "Nothing to verify. An absent directory is not an empty-but-fine release."
    [ -f "$sums_src" ] || die "$E_SUMS_FETCH" \
      "$MANIFEST is missing from $LOCAL_DIR" \
      "REFUSING to treat a missing manifest as 'nothing to check'. Without it" \
      "there is no published digest to compare against, so these bytes are" \
      "unverified — which is not the same as verified-and-fine." \
      "Download $MANIFEST from the release and put it next to the artifacts."
    cp -- "$sums_src" "$sums"
  else
    info "fetching manifest: $sums_src"
    local rc=0
    fetch "$sums_src" "$sums" || rc=$?
    if [ "$rc" -ne 0 ]; then
      die "$E_SUMS_FETCH" \
        "could not fetch $MANIFEST from:" \
        "  $sums_src" \
        "HTTP status ${FETCH_CODE:-none}; curl exit ${rc}: ${FETCH_ERR:-no detail}" \
        "REFUSING to continue. A release that publishes no manifest, or a" \
        "manifest this machine cannot reach, leaves the artifact unverifiable —" \
        "and an unverifiable artifact is a failure, not a pass."
    fi
    if looks_like_html "$sums" "$FETCH_CTYPE"; then
      die "$E_SUMS_HTML" \
        "the origin returned an HTML page where $MANIFEST was expected." \
        "  $sums_src" \
        "HTTP status ${FETCH_CODE}, content-type ${FETCH_CTYPE:-unknown}, ${FETCH_SIZE:-0} bytes." \
        "This is what a captive portal, a login wall, or a CDN answering 200" \
        "with an error page for a missing key looks like. It is NOT a manifest," \
        "and parsing it would find no digests while looking like it tried."
    fi
  fi

  # ── 2. The manifest must actually be a manifest ───────────────────────────
  if [ ! -s "$sums" ]; then
    die "$E_SUMS_MALFORMED" \
      "$MANIFEST is empty (0 bytes)." \
      "  source: $sums_src" \
      "An empty manifest vouches for nothing while looking like a manifest." \
      "Treating it as 'no artifacts to check' is the exact bug this refuses."
  fi
  local valid_lines
  valid_lines="$(manifest_line_count "$sums")"
  if [ "${valid_lines:-0}" -eq 0 ]; then
    die "$E_SUMS_MALFORMED" \
      "$MANIFEST contains no well-formed checksum line." \
      "  source: $sums_src" \
      "Expected lines of the form '<64 hex digits>  <filename>'; found none in" \
      "$(wc -l < "$sums" | tr -d ' ') line(s). The file was truncated, is in a foreign format," \
      "or is an error body that did not announce itself as HTML."
  fi
  info "manifest OK: ${valid_lines} entr(y|ies)"

  # ── 3. Per artifact: exact lookup, fetch, compare ─────────────────────────
  mkdir -p -- "$OUT_DIR"
  local name expected actual target part rc
  for name in "${ARTIFACTS[@]}"; do
    # Exact field-2 match; empty means unverifiable, which means stop.
    expected="$(digest_for "$name" "$sums")"
    if [ -z "$expected" ]; then
      die "$E_NO_ENTRY" \
        "$MANIFEST has no entry for '${name}'." \
        "  source: $sums_src" \
        "The manifest was fetched and parsed (${valid_lines} valid entr(y|ies)), but none of" \
        "them names this artifact with a 64-hex digest. Names are matched" \
        "EXACTLY — '${name}' does not match '${name}.sig', and a '.' in the name" \
        "is a literal dot, not a wildcard. Either you asked for a filename this" \
        "release does not publish, or the release shipped an asset the manifest" \
        "does not vouch for. Both are refusals."
    fi

    if [ "$mode" = "local" ]; then
      target="${LOCAL_DIR%/}/${name}"
      [ -f "$target" ] || die "$E_ART_FETCH" \
        "'${name}' is listed in $MANIFEST but is not present in $LOCAL_DIR" \
        "The manifest vouches for a file that is not here."
    else
      target="${OUT_DIR%/}/${name}"
      part="${target}.part"
      info "fetching artifact: ${BASE_URL}/${name}"
      rc=0
      fetch "${BASE_URL}/${name}" "$part" || rc=$?
      if [ "$rc" -eq 18 ]; then
        rm -f -- "$part"
        die "$E_TRUNCATED" \
          "the download of '${name}' was TRUNCATED." \
          "  ${BASE_URL}/${name}" \
          "The origin declared a Content-Length and then closed the connection" \
          "early; ${FETCH_SIZE:-0} bytes arrived (curl exit 18)." \
          "The partial file has been deleted. This is reported separately from a" \
          "digest mismatch on purpose: a short read is a transport failure to" \
          "retry, not evidence of tampering."
      fi
      if [ "$rc" -ne 0 ]; then
        rm -f -- "$part"
        die "$E_ART_FETCH" \
          "could not fetch '${name}':" \
          "  ${BASE_URL}/${name}" \
          "HTTP status ${FETCH_CODE:-none}; curl exit ${rc}: ${FETCH_ERR:-no detail}" \
          "The manifest vouches for this artifact but the origin did not serve it."
      fi
      target="$part"
    fi

    actual="$(sha256_of "$target")"
    if [ -z "$actual" ]; then
      [ "$mode" = "local" ] || rm -f -- "$target"
      die "$E_MISMATCH" \
        "could not compute a SHA-256 digest for '${name}'." \
        "The file is unreadable or the digest tool produced nothing." \
        "Refusing to report an artifact as verified without a computed digest."
    fi

    if [ "$actual" != "$expected" ]; then
      # An HTML body that the origin served with a non-HTML content-type shows
      # up here. Say which it is — "you were served an error page" and "these
      # bytes were tampered with" are different problems with different fixes.
      if [ "$mode" = "remote" ] && looks_like_html "$target" "$FETCH_CTYPE"; then
        rm -f -- "$target"
        die "$E_ART_FETCH" \
          "the origin returned an HTML page where '${name}' bytes were expected." \
          "  ${BASE_URL}/${name}" \
          "HTTP status ${FETCH_CODE}, content-type ${FETCH_CTYPE:-unknown}, ${FETCH_SIZE:-0} bytes." \
          "The body does not match the published digest and is an HTML document:" \
          "a CDN error page or a login wall answered 200. Nothing was installed."
      fi
      # Say what actually happened to the file. In --dir mode nothing was
      # downloaded and nothing is deleted (the file is the user's own), so
      # claiming a deletion here would be a false statement in a security
      # diagnostic — exactly the kind of unearned reassurance this file exists
      # to avoid, just pointed the other way.
      local disposition
      if [ "$mode" = "local" ]; then
        disposition="The file has been left in place: it is yours, not something this script fetched."
      else
        rm -f -- "$target"
        disposition="The partial download has been deleted."
      fi
      die "$E_MISMATCH" \
        "SHA-256 MISMATCH for '${name}' — these are not the published bytes." \
        "  expected: ${expected}" \
        "  actual:   ${actual}" \
        "  source:   ${sums_src}" \
        "DO NOT run, unpack or install this file. ${disposition}" \
        "Either the transfer corrupted it or the artifact was substituted."
    fi

    if [ "$mode" = "remote" ]; then
      mv -f -- "$target" "${OUT_DIR%/}/${name}"
      target="${OUT_DIR%/}/${name}"
    fi
    info "OK  ${name}  ${actual}"

    # ── 4. Optional: provenance attestation (sigstore/OIDC, no local key) ───
    if [ "$DO_ATTEST" -eq 1 ]; then
      command -v gh >/dev/null 2>&1 || die "$E_ATTEST" \
        "--attest was requested but the GitHub CLI ('gh') is not installed." \
        "Refusing to continue: you asked for the signature to be checked, and" \
        "silently downgrading to 'digest only' would report a guarantee this" \
        "run did not obtain. Install gh, or drop --attest and accept that the" \
        "manifest is trusted only as far as its TLS origin."
      local ar="${REPO:-$DEFAULT_REPO}"
      info "verifying build provenance for ${name} (repo ${ar}) ..."
      if ! gh attestation verify "$target" --repo "$ar" >/dev/null 2>&1; then
        die "$E_ATTEST" \
          "provenance attestation FAILED for '${name}' (repo ${ar})." \
          "The digest matched $MANIFEST, but no valid sigstore attestation ties" \
          "these bytes to a workflow run in that repository — so the manifest" \
          "itself is unvouched-for and a matching digest proves only internal" \
          "consistency. Re-run 'gh attestation verify \"$target\" --repo ${ar}'" \
          "for the full output. Do not use this artifact."
      fi
      info "provenance OK ${name}"
    fi
  done

  printf '\n%s%s: %d artifact(s) verified against %s.%s\n' \
    "$GRN$BLD" "$SELF_NAME" "${#ARTIFACTS[@]}" "$sums_src" "$RST"
  if [ "$DO_ATTEST" -eq 1 ]; then
    printf '%s\n' "  Build provenance attestation: VERIFIED."
  else
    # Never let a pass imply more than it checked.
    printf '%s\n' "  Digests match. Build provenance attestation NOT checked —" \
                  "  re-run with --attest (needs the gh CLI) to check the signature."
  fi
}

# =============================================================================
# Selftest — a synthetic origin server that is wrong in every specific way
# =============================================================================
# The guards above are only worth having if their refusals are exercised. This
# stands up a local HTTP origin whose routes are each broken in exactly one way
# and asserts the exit code AND that a diagnostic was actually printed. The
# "no diagnostic at all" outcome is asserted against explicitly, because that
# was the real-world bug: several guards died silently at a pipeline.
SELFTEST="${SELFTEST:-0}"

write_origin_server() {
  cat > "$1" <<'PYEOF'
import hashlib, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ART   = os.environ["VERIFY_SELFTEST_ARTIFACT"]
MAN   = os.environ["VERIFY_SELFTEST_MANIFEST"]
GOOD  = b"published-release-artifact-bytes\n" * 64
OTHER = b"tampered-substituted-bytes!!!\n" * 64
HTML  = (b"<!DOCTYPE html><html><head><title>404 Not Found</title></head>"
         b"<body><h1>Not Found</h1></body></html>")

def line(name, data):
    return "%s  %s\n" % (hashlib.sha256(data).hexdigest(), name)

ROUTES = {}
def add(case, path, status, ctype, body, declared=None):
    ROUTES["/%s/%s" % (case, path)] = (status, ctype, body, declared)

good_sums = line(ART, GOOD).encode()

# 0. everything correct
add("good", MAN, 200, "text/plain", good_sums)
add("good", ART,          200, "application/gzip", GOOD)

# 3. manifest 404 (artifact present, so only the manifest is wrong)
add("nosums", ART, 200, "application/gzip", GOOD)

# 4. manifest served as an HTML error page, HTTP 200
add("htmlsums", MAN, 200, "text/html", HTML)
add("htmlsums", ART,          200, "application/gzip", GOOD)

# 4b. HTML body but a *lying* content-type — sniffing must still catch it
add("htmlsums2", MAN, 200, "text/plain", HTML)
add("htmlsums2", ART,          200, "application/gzip", GOOD)

# 5. empty manifest
add("emptysums", MAN, 200, "text/plain", b"")
add("emptysums", ART,          200, "application/gzip", GOOD)

# 5b. manifest with content but no checksum lines
add("junksums", MAN, 200, "text/plain", b"Not Found\nerror: no such release\n")
add("junksums", ART,          200, "application/gzip", GOOD)

# 5c. manifest truncated mid-digest
add("truncsums", MAN, 200, "text/plain", good_sums[:20])
add("truncsums", ART,          200, "application/gzip", GOOD)

# 6. valid manifest, but it names a different artifact
add("noentry", MAN, 200, "text/plain", line("some-other-asset.tar.gz", GOOD).encode())
add("noentry", ART,          200, "application/gzip", GOOD)

# 6b. the two name-matching traps, in one manifest:
#     - "...tar.gz.sig"      would be hit by a substring grep
#     - "...v9X9X9-dist..."  would be hit by a regex where '.' is a wildcard
trap_sums = (line(ART + ".sig", OTHER) +
             line(ART.replace(".", "X"), OTHER)).encode()
add("regextrap", MAN, 200, "text/plain", trap_sums)
add("regextrap", ART,          200, "application/gzip", GOOD)

# 6c. the same trap, arranged so a substring match FALSELY PASSES. The manifest
#     vouches ONLY for "<ART>.sig"; the origin serves those exact bytes under
#     the name <ART>. Exact matching must refuse (no entry for <ART>). A
#     substring grep finds the ".sig" line, compares against its digest, and
#     reports the artifact VERIFIED — a guarantee nobody ever gave.
add("sigswap", MAN, 200, "text/plain", line(ART + ".sig", OTHER).encode())
add("sigswap", ART,          200, "application/gzip", OTHER)

# 7. manifest fine, artifact 404
add("noart", MAN, 200, "text/plain", good_sums)

# 7b. manifest fine, artifact served as an HTML error page with HTTP 200
add("htmlart", MAN, 200, "text/plain", good_sums)
add("htmlart", ART,          200, "text/html", HTML)

# 8. artifact declares more bytes than it sends, then the connection drops
add("truncart", MAN, 200, "text/plain", good_sums)
add("truncart", ART,          200, "application/gzip", GOOD[:100], 50000)

# 9. manifest fine, artifact bytes substituted
add("mismatch", MAN, 200, "text/plain", good_sums)
add("mismatch", ART,          200, "application/gzip", OTHER)

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def do_GET(self):
        r = ROUTES.get(self.path)
        if r is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(HTML)))
            self.end_headers()
            self.wfile.write(HTML)
            return
        status, ctype, body, declared = r
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body) if declared is None else declared))
        self.end_headers()
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except Exception:
            pass
        if declared is not None:
            # Deliver less than promised, then hang up: curl sees a short read.
            self.close_connection = True

srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
print("PORT %d" % srv.server_address[1], flush=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
try:
    threading.Event().wait()
except KeyboardInterrupt:
    pass
PYEOF
}

SELFTEST_FAILURES=0
CASE_ROWS=()

# expect_exit <label> <expected-code> <expect-diagnostic:yes|no> -- <cmd...>
expect_exit() {
  local label="$1" want="$2" want_diag="$3"; shift 3
  [ "${1:-}" = "--" ] && shift
  local outf="${TMPDIR_V}/case.out" rc=0
  : > "$outf"
  "$@" >"$outf" 2>&1 || rc=$?

  local diag
  diag="$(grep -m1 -E 'FATAL:' "$outf" | sed 's/.*FATAL: *//' || true)"
  [ -n "$diag" ] || diag="$(head -1 "$outf" || true)"
  [ -n "$diag" ] || diag="(NO DIAGNOSTIC PRINTED)"

  local verdict="ok"
  if [ "$rc" -ne "$want" ]; then
    verdict="FAIL(exit ${rc}, want ${want})"
    SELFTEST_FAILURES=$((SELFTEST_FAILURES + 1))
  elif [ "$want_diag" = "yes" ] && [ "$diag" = "(NO DIAGNOSTIC PRINTED)" ]; then
    # This is the failure the whole file is about: a guard that aborts with no
    # message tells the user nothing and reads like a crash, not a refusal.
    verdict="FAIL(silent)"
    SELFTEST_FAILURES=$((SELFTEST_FAILURES + 1))
  fi
  CASE_ROWS+=("${label}|${rc}|${verdict}|${diag}")
  printf '  %-34s exit %-3s %-22s %s\n' "$label" "$rc" "$verdict" "$diag"
}

run_selftest() {
  command -v python3 >/dev/null 2>&1 || die "$E_NO_TOOL" \
    "python3 is required to run the synthetic-origin selftest." \
    "(It is a TEST-only dependency; verifying a real release needs only curl" \
    "and sha256sum/shasum.)"

  local py="${TMPDIR_V}/origin.py" logf="${TMPDIR_V}/origin.log"
  write_origin_server "$py"
  VERIFY_SELFTEST_ARTIFACT="$SELFTEST_ARTIFACT" \
  VERIFY_SELFTEST_MANIFEST="$MANIFEST" \
    python3 "$py" > "$logf" 2>&1 &
  local srv_pid=$!
  # shellcheck disable=SC2064
  trap "kill ${srv_pid} 2>/dev/null || true; cleanup" EXIT

  local port="" _tick
  for _tick in $(seq 1 100); do
    port="$(awk '/^PORT /{print $2; exit}' "$logf" 2>/dev/null || true)"
    [ -n "$port" ] && break
    sleep 0.1
  done
  [ -n "$port" ] || die 1 "synthetic origin failed to start:" "$(cat "$logf" || true)"

  local base="http://127.0.0.1:${port}"
  local art="$SELFTEST_ARTIFACT"
  local outd="${TMPDIR_V}/dl"
  mkdir -p "$outd"

  printf '\n%s%s selftest — synthetic origin on %s%s\n\n' "$BLD" "$SELF_NAME" "$base" "$RST"
  printf '  %-34s %-8s %-22s %s\n' "CASE" "EXIT" "VERDICT" "DIAGNOSTIC (first line)"
  printf '  %s\n' "------------------------------------------------------------------------------"

  local V=(bash "$SELF_PATH" --out "$outd")

  expect_exit "happy path"                    0                   no  -- "${V[@]}" --base-url "$base/good"       "$art"
  expect_exit "SHA256SUMS 404"                "$E_SUMS_FETCH"     yes -- "${V[@]}" --base-url "$base/nosums"     "$art"
  expect_exit "SHA256SUMS is HTML (ctype)"    "$E_SUMS_HTML"      yes -- "${V[@]}" --base-url "$base/htmlsums"   "$art"
  expect_exit "SHA256SUMS is HTML (sniffed)"  "$E_SUMS_HTML"      yes -- "${V[@]}" --base-url "$base/htmlsums2"  "$art"
  expect_exit "SHA256SUMS empty"              "$E_SUMS_MALFORMED" yes -- "${V[@]}" --base-url "$base/emptysums"  "$art"
  expect_exit "SHA256SUMS has no digests"     "$E_SUMS_MALFORMED" yes -- "${V[@]}" --base-url "$base/junksums"   "$art"
  expect_exit "SHA256SUMS truncated"          "$E_SUMS_MALFORMED" yes -- "${V[@]}" --base-url "$base/truncsums"  "$art"
  expect_exit "no entry for artifact"         "$E_NO_ENTRY"       yes -- "${V[@]}" --base-url "$base/noentry"    "$art"
  expect_exit "no entry (.sig / regex traps)" "$E_NO_ENTRY"       yes -- "${V[@]}" --base-url "$base/regextrap"  "$art"
  expect_exit "no entry (.sig false-pass trap)" "$E_NO_ENTRY"     yes -- "${V[@]}" --base-url "$base/sigswap"    "$art"
  expect_exit "artifact 404"                  "$E_ART_FETCH"      yes -- "${V[@]}" --base-url "$base/noart"      "$art"
  expect_exit "artifact is HTML page (200)"   "$E_ART_FETCH"      yes -- "${V[@]}" --base-url "$base/htmlart"    "$art"
  expect_exit "artifact truncated"            "$E_TRUNCATED"      yes -- "${V[@]}" --base-url "$base/truncart"   "$art"
  expect_exit "digest mismatch"               "$E_MISMATCH"       yes -- "${V[@]}" --base-url "$base/mismatch"   "$art"

  # Local (--dir) mode: the missing-manifest case on the path a user takes
  # after downloading assets by hand from a browser.
  local ld="${TMPDIR_V}/localdir"
  mkdir -p "$ld"
  printf 'x' > "${ld}/${art}"
  expect_exit "local dir, no SHA256SUMS"      "$E_SUMS_FETCH"     yes -- bash "$SELF_PATH" --dir "$ld" "$art"
  : > "${ld}/${MANIFEST}"
  expect_exit "local dir, empty SHA256SUMS"   "$E_SUMS_MALFORMED" yes -- bash "$SELF_PATH" --dir "$ld" "$art"
  expect_exit "local dir does not exist"      "$E_SUMS_FETCH"     yes -- bash "$SELF_PATH" --dir "${TMPDIR_V}/absent" "$art"

  # Transport and usage.
  expect_exit "plaintext http origin"         "$E_INSECURE"       yes -- bash "$SELF_PATH" --base-url "http://example.com/rel" "$art"
  expect_exit "no artifact named"             "$E_USAGE"          yes -- bash "$SELF_PATH" --tag v9.9.9
  expect_exit "no --tag / --base-url"         "$E_USAGE"          yes -- bash "$SELF_PATH" "$art"
  expect_exit "unknown flag"                  "$E_USAGE"          yes -- bash "$SELF_PATH" --no-verify "$art"
  expect_exit "empty artifact name (unset var)" "$E_USAGE"        yes -- bash "$SELF_PATH" --base-url "$base/good" ""
  # A stripped PATH: curl is unreachable, so nothing can be checked. Invoked via
  # the absolute path of the running shell, since PATH cannot find `bash` either.
  local bash_abs="${BASH:-/bin/bash}"
  expect_exit "no curl / no digest tool"      "$E_NO_TOOL"        yes -- env PATH="${TMPDIR_V}/empty-path" "$bash_abs" "$SELF_PATH" --base-url "$base/good" "$art"

  # --attest with no gh on PATH must refuse, not quietly downgrade.
  local fakebin="${TMPDIR_V}/fakebin" t p
  mkdir -p "$fakebin"
  for t in bash curl sha256sum shasum awk grep sed tr head cat wc mktemp mkdir rm mv env seq tput sleep; do
    p="$(command -v "$t" 2>/dev/null || true)"
    [ -n "$p" ] && ln -sf "$p" "${fakebin}/${t}"
  done
  expect_exit "--attest but no gh installed"  "$E_ATTEST"         yes -- env PATH="$fakebin" "$bash_abs" "$SELF_PATH" --out "$outd" --attest --repo "$DEFAULT_REPO" --base-url "$base/good" "$art"

  printf '\n'
  if [ "$SELFTEST_FAILURES" -ne 0 ]; then
    die 1 "selftest: ${SELFTEST_FAILURES} case(s) did not behave as specified."
  fi
  printf '%s%s: selftest passed — %d cases, every failure mode refused with its own exit code and its own diagnostic.%s\n' \
    "$GRN$BLD" "$SELF_NAME" "${#CASE_ROWS[@]}" "$RST"
}

mkdir -p "${TMPDIR_V}/empty-path"

if [ "$SELFTEST" = "1" ]; then
  run_selftest
else
  run_verify
fi
