"Kerf CFD plugin — FV-SIMPLE incompressible RANS solver, turbulence models, OpenFOAM bridge."

__version__ = "0.1.0"

from kerf_cfd.openfoam_bridge import (  # noqa: F401
    OpenFOAMCaseSpec,
    OpenFOAMExportResult,
    export_to_openfoam,
)
