# OpenFOAM Case Generation and Bridge

> Generate complete, runnable OpenFOAM case directories from a Kerf geometry description — blockMesh, boundary conditions, turbulence model, and solver settings in one call.

**Module**: `packages/kerf-cfd/src/kerf_cfd/openfoam_bridge.py`
**Shipped**: Wave 9
**LLM tools**: `cfd_run` (analysis_type `"cfd_turbulent"`, `"cfd_multiphase"`)

---

## What it is

OpenFOAM is the industry-standard open-source CFD solver used across automotive, aerospace, marine, and HVAC engineering. Setting up an OpenFOAM case correctly — with consistent boundary conditions, turbulence model initial fields, numerical scheme selections, and solver relaxation factors — requires deep OpenFOAM knowledge and takes hours by hand.

This module generates complete, runnable OpenFOAM case directories from a structured Python description: `0/` initial field files, `constant/` transport properties and turbulence model coefficients, and `system/` blockMeshDict, controlDict, fvSchemes, and fvSolution files. It supports simpleFoam (steady incompressible RANS), buoyantSimpleFoam (thermal RANS), and interFoam (VoF free-surface). Results can be parsed back by `read_results`.

## How to use it

### From chat (natural language)

> "Set up a k-ω SST OpenFOAM case for flow over a bluff body at Re=50,000, inlet velocity 10 m/s"

The LLM calls `cfd_run` with `analysis_type='cfd_turbulent'`.

### From Python

```python
from kerf_cfd.openfoam_bridge import (
    OpenFOAMCaseSpec, export_to_openfoam, read_results,
)

spec = OpenFOAMCaseSpec(
    solver="simpleFoam",
    turbulence_model="kOmegaSST",
    nu=1.5e-5,
    inlet_velocity=(10.0, 0.0, 0.0),
    mesh_vertices=[...],  # blockMeshDict vertex list
    mesh_blocks=[...],
)
result = export_to_openfoam(spec, output_dir="/tmp/foam_case")
# Returns OpenFOAMExportResult with case_dir path and mesh quality warnings
```

### From an LLM tool spec

```json
{"tool": "cfd_run", "analysis_type": "cfd_turbulent",
 "solver": "simpleFoam", "turbulence_model": "kOmegaSST",
 "Re": 50000, "inlet_U": [10, 0, 0]}
```

## How it works

The bridge writes OpenFOAM's native dictionary format using Python string templates. `fvSchemes` is set to second-order schemes (linearUpwind for convection, Gauss linear for diffusion) for production runs. `fvSolution` uses GAMG for pressure and smoothSolver for velocity. Turbulence initial fields (k, ε or ω) are estimated from turbulence intensity and mixing length: k = 1.5(U·I)², ε = Cμ^0.75 k^1.5/L.

`read_results` parses the OpenFOAM field files and returns pressure, velocity, and turbulence fields as NumPy arrays.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `export_to_openfoam(spec, output_dir)` | `OpenFOAMExportResult` | Write case directory |
| `read_results(case_dir, time_step)` | `ResultBundle` | Parse field files |
| `write_polymesh(mesh, path)` | `None` | Write polyMesh directory |

`OpenFOAMExportResult` fields: `case_dir`, `mesh_quality_warnings`, `estimated_cell_count`.

## Example

```python
spec = OpenFOAMCaseSpec(solver="simpleFoam", turbulence_model="kEpsilon",
                         nu=1e-5, inlet_velocity=(5,0,0),
                         mesh_vertices=verts, mesh_blocks=blocks)
res = export_to_openfoam(spec, "/tmp/test_case")
print(f"Case written to: {res.case_dir}")
print(f"Mesh warnings: {res.mesh_quality_warnings}")
```

## Honest caveats

The bridge generates valid OpenFOAM cases for common configurations, but mesh quality and boundary condition correctness are the user's responsibility. blockMesh generates structured hexahedral meshes only — complex geometries need snappyHexMesh (`cfd-snappy-mesh`). OpenFOAM must be installed locally (or on a trusted node offering compute — see `docs/node-architecture.md`) for execution — the bridge does not run the solver. Y⁺ wall treatment must be set manually based on mesh resolution.

## References

- Patankar (1980). *Numerical Heat Transfer and Fluid Flow*. McGraw-Hill.
- OpenFOAM Foundation (2023). *OpenFOAM User Guide*, v11. openfoam.org.
