"""sky130/installer.py — SKY130 PDK installation helpers.

Checks whether the SkyWater SKY130 PDK is already installed on the host
machine and provides a one-line installation hint via the `volare` PDK
version manager.

Installation methods supported:
  1. PDK_ROOT environment variable pointing to a directory that contains
     a sky130A sub-directory.
  2. Default volare cache at ~/.volare/sky130A.

References:
  https://github.com/efabless/volare
  https://skywater-pdk.readthedocs.io
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_pdk_available() -> bool:
    """Return True if the SKY130A PDK appears to be installed.

    Checks, in order:
      1. ``$PDK_ROOT/sky130A`` directory exists.
      2. ``~/.volare/sky130A`` directory exists.
    """
    # 1. Explicit PDK_ROOT env variable
    pdk_root = os.environ.get("PDK_ROOT", "")
    if pdk_root:
        candidate = Path(pdk_root) / "sky130A"
        if candidate.is_dir():
            return True

    # 2. volare default cache location
    volare_candidate = Path.home() / ".volare" / "sky130A"
    if volare_candidate.is_dir():
        return True

    return False


def pdk_path() -> Optional[Path]:
    """Return the path to the installed SKY130A PDK, or None if not found.

    Search order matches :func:`is_pdk_available`.
    """
    pdk_root = os.environ.get("PDK_ROOT", "")
    if pdk_root:
        candidate = Path(pdk_root) / "sky130A"
        if candidate.is_dir():
            return candidate

    volare_candidate = Path.home() / ".volare" / "sky130A"
    if volare_candidate.is_dir():
        return volare_candidate

    return None


def install_hint() -> str:
    """Return a one-line installation hint for the SKY130A PDK.

    The recommended approach is to use the ``volare`` PDK version manager
    (https://github.com/efabless/volare) which handles version pinning and
    deduplication automatically.
    """
    return (
        "volare enable sky130A  "
        "# https://github.com/efabless/volare — installs PDK to ~/.volare/sky130A"
    )
