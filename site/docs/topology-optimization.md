# Topology Optimization (SIMP)

*Domain: Mechanical · Module: `packages/kerf-topo/` · Shipped: Wave 6*

## Overview

Density-based topology optimisation using the SIMP (Solid Isotropic Material with Penalisation) method on a 2-D grid. Minimises structural compliance (maximises stiffness) for a given volume fraction, with optional manufacturing constraints (minimum member size, casting draw direction) and multi-load-case support via weighted compliance aggregation. The LLM agent (`/run-topo`) uses Opus to interpret results and suggest design refinements.

## When to use

- Finding the optimal material distribution for a structural bracket or support.
- Reducing part weight by identifying load-carrying material paths.
- Generating organic topology geometry for additive manufacturing.

## API

```python
# Via the LLM tool — the SIMP solver runs server-side:
# Tool: run_topo_simp
# Args: nelx, nely, volfrac, penal, rmin, filter_type, load_cases

# Direct Python:
from kerf_cad_core.topology.manufacturing_constraints import (
    build_filter_weights, density_filter,
)
from kerf_cad_core.topology.multi_load import (
    weighted_compliance, accumulate_sensitivity,
    pareto_two_load, normalise_weights,
)
```

## LLM tools

`run_topo_simp`, `feature_topo_export_stl`

## References

- Sigmund, "A 99 line topology optimization code written in MATLAB", *Struct. Optim.* 21(2), 2001.
- Andreassen et al., "Efficient topology optimization in MATLAB using 88 lines of code", *Struct. Multidisc. Optim.* 43, 2011.
- Bendsøe & Sigmund, *Topology Optimization: Theory, Methods, and Applications*, 2nd ed. (2004).

## Honest caveats

The SIMP solver is 2-D only (plane-stress or plane-strain). 3-D topology optimization is dispatched to the FEniCSx GPU worker, which requires a GPU-capable machine — either local or a trusted node offering compute (see `docs/node-architecture.md`). The density filter radius `rmin` controls minimum member size but does not guarantee printability for specific AM processes. Checker-board patterns are suppressed by the filter but may reappear at very low rmin values.
