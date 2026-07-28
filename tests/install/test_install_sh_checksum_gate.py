"""The release installer's checksum gate must FAIL CLOSED.

``install.sh`` used to warn-and-continue when ``SHA256SUMS`` 404'd or did not
list the asset it had just downloaded. That is the *common* failure mode, and
it printed "Verifying checksum..." on the way past — reporting safety it had
not checked. These tests hold every path out of that block to "verified" or
"abort".

The installer is exercised for real: a stub ``curl`` earlier on ``PATH`` serves
a fixture directory instead of GitHub, so nothing here touches the network and
nothing is installed outside the test's temporary ``HOME``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"

VERSION = "v9.9.9"
ASSET_NAMES = {
    ("Darwin", "arm64"): f"kerf-{VERSION}-macos-arm64.tar.gz",
    ("Darwin", "x86_64"): f"kerf-{VERSION}-macos-x64.tar.gz",
    ("Linux", "x86_64"): f"kerf-{VERSION}-linux-x64.tar.gz",
}

# The stub curl. Serves <served>/<basename-of-URL> and exits 22 — curl's
# "HTTP error" status under -f — when the file is not there, which is exactly
# what a 404 on SHA256SUMS looks like to install.sh.
_CURL_STUB = r"""#!/usr/bin/env bash
set -u
out=""
url=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  case "$arg" in -*) ;; *) url="$arg" ;; esac
  prev="$arg"
done
name="${url##*/}"
name="${name%%\?*}"
src="__SERVED__/${name}"
if [ ! -f "$src" ]; then
  exit 22
fi
if [ -n "$out" ]; then
  cp "$src" "$out"
else
  cat "$src"
fi
"""


def _asset_name() -> str:
    key = (os.uname().sysname, os.uname().machine)
    name = ASSET_NAMES.get(key)
    if name is None:
        pytest.skip(f"install.sh has no tarball label for {key}")
    return name


def _make_bundle(path: Path) -> None:
    """A minimal release tarball: one executable setup.sh that records that it ran."""
    stage = path.parent / "stage" / f"kerf-{VERSION}"
    stage.mkdir(parents=True)
    setup = stage / "setup.sh"
    setup.write_text("#!/usr/bin/env bash\necho SETUP-RAN\n")
    setup.chmod(0o755)
    with tarfile.open(path, "w:gz") as tf:
        tf.add(stage, arcname=f"kerf-{VERSION}")


@pytest.fixture
def installer(tmp_path):
    """Yields ``run(sha256sums: str | None) -> CompletedProcess``.

    ``sha256sums=None`` means the file is absent (the 404 case).
    """
    served = tmp_path / "served"
    served.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    asset = _asset_name()
    _make_bundle(served / asset)
    digest = hashlib.sha256((served / asset).read_bytes()).hexdigest()

    curl = bin_dir / "curl"
    curl.write_text(_CURL_STUB.replace("__SERVED__", str(served)))
    curl.chmod(0o755)

    def run(sha256sums: str | None) -> subprocess.CompletedProcess:
        sums = served / "SHA256SUMS"
        if sums.exists():
            sums.unlink()
        if sha256sums is not None:
            sums.write_text(sha256sums)
        env = dict(os.environ)
        env.update(
            PATH=f"{bin_dir}:{env['PATH']}",
            HOME=str(home),
            KERF_VERSION=VERSION,
            KERF_HOME=str(home / "kerf-install"),
        )
        return subprocess.run(
            ["bash", str(INSTALL_SH)],
            env=env, capture_output=True, text=True, timeout=120,
        )

    run.asset = asset          # type: ignore[attr-defined]
    run.digest = digest        # type: ignore[attr-defined]
    run.kerf_home = home / "kerf-install"  # type: ignore[attr-defined]
    yield run
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_missing_sha256sums_is_a_hard_error(installer):
    """The regression that motivated this file: a 404 must abort, not warn."""
    res = installer(None)
    assert res.returncode != 0, res.stdout
    assert "refusing to install unverified bytes" in res.stderr
    assert not installer.kerf_home.exists(), "aborted install must leave nothing behind"
    assert "SETUP-RAN" not in res.stdout


def test_empty_sha256sums_is_a_hard_error(installer):
    res = installer("")
    assert res.returncode != 0, res.stdout
    assert "is empty" in res.stderr
    assert "SETUP-RAN" not in res.stdout


def test_asset_absent_from_sha256sums_is_a_hard_error(installer):
    """A SHA256SUMS that exists but does not vouch for THIS asset is not a pass."""
    res = installer(f"{'0' * 64}  kerf-{VERSION}-some-other-asset.tar.gz\n")
    assert res.returncode != 0, res.stdout
    assert "is not listed in SHA256SUMS" in res.stderr
    assert "SETUP-RAN" not in res.stdout


def test_checksum_mismatch_is_a_hard_error(installer):
    res = installer(f"{'a' * 64}  {installer.asset}\n")
    assert res.returncode != 0, res.stdout
    assert "Checksum mismatch" in res.stderr
    assert "SETUP-RAN" not in res.stdout


def test_matching_checksum_installs(installer):
    """The gate must still let a correct release through — fail-closed, not stuck-closed."""
    res = installer(f"{installer.digest}  {installer.asset}\n")
    assert res.returncode == 0, res.stderr
    assert "Checksum verified." in res.stdout
    assert "SETUP-RAN" in res.stdout


def test_binary_mode_sha256sums_is_accepted(installer):
    """GNU coreutils' binary marker (`*name`) must not read as an unlisted asset."""
    res = installer(f"{installer.digest} *{installer.asset}\n")
    assert res.returncode == 0, res.stderr
    assert "Checksum verified." in res.stdout


# Coverage assertion (see packages/kerf-pub/tests/test_conformance_vectors.py
# for the same pattern over the DMTAP corpus): every exit from install.sh's
# checksum block is named here, so a new branch cannot be added without either
# a test or a deliberate edit to this list.
CHECKSUM_BLOCK_OUTCOMES = {
    "sha256sums-404": "test_missing_sha256sums_is_a_hard_error",
    "sha256sums-empty": "test_empty_sha256sums_is_a_hard_error",
    "asset-not-listed": "test_asset_absent_from_sha256sums_is_a_hard_error",
    "digest-mismatch": "test_checksum_mismatch_is_a_hard_error",
    "digest-match": "test_matching_checksum_installs",
    "digest-match-binary-mode": "test_binary_mode_sha256sums_is_accepted",
}


def test_every_checksum_outcome_has_a_test():
    assert len(CHECKSUM_BLOCK_OUTCOMES) == 6
    for outcome, test_name in CHECKSUM_BLOCK_OUTCOMES.items():
        assert test_name in globals(), f"{outcome}: {test_name} does not exist"

    # The block must contain no warn-and-continue path. `warn` in install.sh
    # prints and returns; only `fail` aborts. If a `warn` reappears between
    # "Verifying checksum..." and "Checksum verified." the gate has been
    # re-opened, so assert its absence rather than trusting review.
    body = INSTALL_SH.read_text()
    start = body.index('info "Verifying checksum..."')
    end = body.index('ok "Checksum verified."')
    block = body[start:end]
    assert "warn " not in block, (
        "install.sh's checksum block regained a warn-and-continue path:\n" + block
    )
    assert block.count("fail ") == 6
