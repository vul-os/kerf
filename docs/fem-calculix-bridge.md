# CalculiX FEA Bridge

*Domain: Structural FEM · Module: `packages/kerf-fem/src/kerf_fem/calculix_bridge.py` · Shipped: Wave 8*

## Overview

Bridges from Kerf's mesh and load data to CalculiX (.inp file generation), job execution, and result parsing (.frd file reading). Covers linear static, modal, thermal, nonlinear static (material and geometric), and explicit dynamic analysis types. Provides a corpus of reference cases (`calculix_corpus.py`) with known analytic solutions for regression testing.

## When to use

- Running 3-D solid FEA on a tetrahedral mesh from `kerf-tess`.
- Modal analysis of a 3-D structure to extract natural frequencies and mode shapes.
- Submitting a CalculiX job to the Koyeb GPU worker for large problems.

## API

```python
from kerf_fem.calculix_bridge import (
    CalculiXJob, CalculiXBoundaryCondition,
    write_inp_file, parse_frd_results,
    submit_job,
)

job = CalculiXJob(
    mesh=tet_mesh,         # dict with nodes/elements
    material={"E": 200e9, "nu": 0.3, "rho": 7850},
    loads=[{"node_set": "TOP", "Fy": -10000}],
    boundary_conditions=[
        CalculiXBoundaryCondition(node_set="FIXED", dofs=[1,2,3]),
    ],
    analysis_type="static",
)

inp_path = write_inp_file(job, path="/tmp/calc_job.inp")
result = submit_job(inp_path)           # runs ccx locally
data   = parse_frd_results(result.frd_path)
```

## LLM tools

`fem_run`, `fem_job_status`

## References

- Dhondt, *The Finite Element Method for Three-Dimensional Thermomechanical Applications* (2004).
- CalculiX User's Manual, v2.21 (2023).

## Honest caveats

CalculiX must be installed on the server or the job must be dispatched to the Koyeb GPU worker. The bridge generates linear tetrahedral (C3D4) and quadratic (C3D10) elements. Shell and beam elements are available but require manual mesh setup — they are not auto-generated from the BRep. Large nonlinear jobs may require manual convergence parameter tuning.
