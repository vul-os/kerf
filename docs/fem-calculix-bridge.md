# CalculiX FEA Bridge

> Generate CalculiX .inp decks, submit jobs, and parse .frd results — the bridge between Kerf geometry and production 3D structural FEA.

**Module**: `packages/kerf-fem/src/kerf_fem/calculix_bridge.py`
**Shipped**: Wave 8
**LLM tools**: `fem_run`, `fem_job_status`

---

## What it is

CalculiX is an open-source FEA solver with commercial-grade capability: C3D4/C3D10 tetrahedral elements, C3D8/C3D20 hexahedral elements, linear static, nonlinear static (geometric and material), modal, thermal, and explicit dynamic analysis. It accepts Abaqus-compatible .inp files and outputs .frd results files.

The CalculiX bridge takes a Kerf mesh (from the tessellator), material properties, loads, and boundary conditions, and: (1) generates a valid .inp file, (2) executes CalculiX locally or dispatches to the Koyeb GPU worker, and (3) parses the .frd results back into Python dictionaries. A corpus of reference cases (`calculix_corpus.py`) provides analytic benchmarks for regression testing.

## How to use it

### From chat (natural language)

> "Run a linear static analysis on the bracket mesh, fix the base, apply 10kN at the top, material steel"

The LLM calls `fem_run` and dispatches to the CalculiX bridge.

### From Python

```python
from kerf_fem.calculix_bridge import CalculiXBridge

ccx = CalculiXBridge()
result = ccx.run_static(
    mesh={"nodes": nodes, "elements": elements, "element_type": "C3D10"},
    material={"E": 200e9, "nu": 0.3, "rho": 7850},
    loads=[{"node_set": "TOP", "Fy": -10000}],
    boundary_conditions=[{"node_set": "BASE", "dofs": [1,2,3]}],
)
print(f"Max von Mises: {result.max_von_mises_pa/1e6:.1f} MPa")
print(f"Max displacement: {result.max_displacement_m*1000:.2f} mm")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "analysis_type": "static", "mesh_id": "bracket",
 "material": {"E": 200e9, "nu": 0.3}, "fix_set": "BASE", "load_set": "TOP"}
```

## How it works

The bridge assembles a CalculiX .inp deck with: `*NODE` section, `*ELEMENT` section, `*MATERIAL` with `*ELASTIC`, `*BOUNDARY` conditions (Dirichlet DOF pins), `*CLOAD` or `*DLOAD` load definitions, and the analysis step keyword (`*STATIC`, `*FREQUENCY`, `*BUCKLE`, etc.). After running `ccx job_name`, the .frd binary file is parsed by `_parse_frd_displacements` and `_parse_dat_stresses` to extract nodal results.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `CalculiXBridge().run_static(mesh, material, loads, bcs)` | `Result` | Linear static analysis |
| `CalculiXBridge().run_modal(mesh, material, bcs, n_modes)` | `Result` | Modal analysis |
| `write_inp_file(bridge, path)` | `Path` | Write .inp without running |
| `parse_frd_results(frd_path)` | `dict` | Parse .frd results file |

`Result` fields: `max_von_mises_pa`, `max_displacement_m`, `nodal_displacements`, `element_stresses`, `frequencies_hz` (modal).

## Example

```python
ccx = CalculiXBridge()
if not ccx._ccx_available():
    print("CalculiX not found — install ccx or use Koyeb worker")
else:
    result = ccx.run_static(mesh, mat, loads, bcs)
    print(f"Max σ_VM = {result.max_von_mises_pa/1e6:.1f} MPa")
```

## Honest caveats

CalculiX must be installed locally (`ccx` in PATH) or the job dispatched to the Koyeb GPU worker. The bridge generates C3D4 (linear tet) and C3D10 (quadratic tet) elements — shell and beam elements are available in CalculiX but not auto-generated from BRep. Large nonlinear jobs may need manual convergence parameter tuning (increment size, maximum iterations). For Abaqus-incompatible features (XFEM, cohesive elements), use direct .inp authoring.

## References

- Dhondt (2004). *The Finite Element Method for Three-Dimensional Thermomechanical Applications*. Wiley.
- CalculiX (2023). *CalculiX User's Manual*, v2.21. calculix.de.
