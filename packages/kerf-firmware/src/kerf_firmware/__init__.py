"""kerf-firmware: board catalogue and library registry client."""
__version__ = "0.1.0"

from kerf_firmware.const_allocation import (  # noqa: F401
    SymbolEntry,
    ConstAllocationReport,
    analyze_const_allocation,
)
