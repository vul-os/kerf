# Composite Laminate Analysis (CLT)

*Domain: Manufacturing — Composites · Module: `packages/kerf-composites/src/kerf_composites/clt.py` · Shipped: Wave 9*

## Overview

Classical Lamination Theory (CLT) analysis for fibre-reinforced polymer laminates. Computes the ABD stiffness matrix (membrane A, bending-membrane coupling B, bending D), effective engineering constants, per-ply stress/strain in material coordinates, and first-ply failure using Tsai-Wu, Tsai-Hill, Hashin, and max-stress criteria. Companion modules cover AFP/ATL drapeability, interlaminar shear stress, and thermal residual stress.

## When to use

- Sizing a composite laminate for a given in-plane load and bending moment.
- Computing effective stiffness and thermal expansion coefficients for FEA material inputs.
- First-ply failure prediction under combined in-plane loading.
- Optimising ply orientations for stiffness or strength targets.

## API

```python
from kerf_composites.clt import (
    LaminatePly, LaminateLayup,
    build_abd, effective_engineering_constants,
    compute_ply_stresses, first_ply_failure,
)

layup = LaminateLayup(plies=[
    LaminatePly(theta=0,   t=0.125, material="T300_epoxy"),
    LaminatePly(theta=45,  t=0.125, material="T300_epoxy"),
    LaminatePly(theta=-45, t=0.125, material="T300_epoxy"),
    LaminatePly(theta=90,  t=0.125, material="T300_epoxy"),
])

abd = build_abd(layup)
eff = effective_engineering_constants(abd, total_thickness=0.5)

# Apply in-plane load Nx=10 kN/m
failure = first_ply_failure(layup, Nx=10e3, Ny=0, Nxy=0, criterion="tsai_wu")
print(failure["safety_factor"])
```

## LLM tools

`layup_analysis`, `composites_drape`, `composites_interlaminar`, `composites_thermal`

## References

- Jones, *Mechanics of Composite Materials*, 2nd ed. (1999).
- Tsai & Wu, "A general theory of strength for anisotropic materials", *J. Composite Materials* 5, 1971.
- Hashin, "Failure criteria for unidirectional fibre composites", *J. Appl. Mech.* 47, 1980.

## Honest caveats

CLT assumes plane-stress and perfect bonding between plies. Progressive failure, delamination, and geometric nonlinearity (large deflections) are not modelled. The material database covers common aerospace-grade laminates; custom materials can be specified as orthotropic moduli. First-ply failure identifies the first ply to fail, not the laminate ultimate load.
