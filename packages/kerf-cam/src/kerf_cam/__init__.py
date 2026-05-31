"Kerf CAM plugin — toolpath generation via OpenCAMlib."

__version__ = "0.1.0"

from kerf_cam.dry_machining_check import (  # noqa: F401
    DryMachiningSpec,
    DryMachiningReport,
    check_dry_machining,
)

from kerf_cam.chip_load_validate import (  # noqa: F401
    ChipLoadSpec,
    ChipLoadReport,
    validate_chip_load,
)
