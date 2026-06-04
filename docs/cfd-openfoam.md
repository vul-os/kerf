# OpenFOAM Case Generation and Bridge

*Domain: CFD · Module: `packages/kerf-cfd/src/kerf_cfd/openfoam_bridge.py` · Shipped: Wave 9*

## Overview

Generates complete, runnable OpenFOAM case directories from a structured description: mesh blocks (blockMesh), boundary patches, turbulence model selection (k-ε, k-ω SST, Spalart-Allmaras), transport properties, and solver settings for simpleFoam (steady RANS), buoyantSimpleFoam (thermal), and interFoam (VoF multiphase). The bridge handles both case creation and results parsing (field summary, convergence residuals).

## When to use

- Running a 3-D steady RANS simulation on a geometry defined in Kerf.
- Setting up a multiphase (air/water) free-surface simulation.
- Automating an OpenFOAM case setup pipeline as part of a design study.

## API

```python
from kerf_cfd.openfoam_bridge import (
    OpenFOAMCase, BoundaryPatch,
    generate_case, parse_log,
)

case = OpenFOAMCase(
    solver="simpleFoam",
    turbulence_model="kOmegaSST",
    Re=50000,
    mesh_blocks=[...],     # blockMeshDict entries
    patches=[
        BoundaryPatch("inlet",  "fixedValue", U=[10,0,0]),
        BoundaryPatch("outlet", "zeroGradient"),
        BoundaryPatch("walls",  "noSlip"),
    ],
)

case_dir = generate_case(case, path="/tmp/foam_case")
# → writes 0/, constant/, system/ sub-directories
```

## LLM tools

`cfd_run` (analysis_type `"cfd_turbulent"`, `"cfd_multiphase"`)

## References

- Patankar, *Numerical Heat Transfer and Fluid Flow* (1980).
- OpenFOAM Foundation, *OpenFOAM User Guide*, v11 (2023).

## Honest caveats

The case generator creates valid OpenFOAM cases for common configurations, but mesh quality and boundary condition correctness are the user's responsibility. blockMesh-generated structured hexahedral meshes may be insufficient for complex geometries — snappyHexMesh support is provided via the `cfd_snappy_mesh` tool. OpenFOAM must be installed locally or available on the Koyeb GPU worker for execution.
