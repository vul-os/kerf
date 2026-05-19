"""Aerospace fasteners catalogue and sizing utilities.

Submodules
----------
catalogue : 180+ Hi-Lok / Cherry / NAS / MS / AS / Huck-Lok / Tinnerman entries
sizing    : joint_allowable() and pick_fastener() selection helpers
"""

from .catalogue import (
    CATALOGUE,
    REQUIRED_FIELDS,
    get_by_spec,
    filter_catalogue,
)
from .sizing import (
    joint_allowable,
    pick_fastener,
)

__all__ = [
    "CATALOGUE",
    "REQUIRED_FIELDS",
    "get_by_spec",
    "filter_catalogue",
    "joint_allowable",
    "pick_fastener",
]
