# Piping Stress Analysis and Isometrics

*Domain: Piping · Module: `packages/kerf-cad-core/src/kerf_cad_core/piping/` · Shipped: Wave 8*

## Overview

Process piping design and stress analysis: pipe routing from P&ID node lists (parametric elbow, tee, reducer placement), pressure/temperature rated schedule sizing (ASME B31.3), hanger/support placement via Caesar II-compatible stress analysis, and isometric drawing generation. Produces ISO-formatted piping isometrics with material take-off (MTO) lists.

## When to use

- Routing process piping between equipment nozzles on a plot plan.
- Checking pipe wall thickness for a given design pressure and temperature per ASME B31.3.
- Generating a piping isometric drawing with spool numbers and material list.

## API

```python
from kerf_cad_core.piping.tools import (
    pipe_wall_thickness_b31,
    piping_stress_analysis,
    generate_piping_isometric,
)

# ASME B31.3 wall thickness
result = pipe_wall_thickness_b31(
    P_MPa=1.5,
    D_o_mm=60.3,         # OD for 2" NPS
    S_MPa=137.9,         # allowable stress (A106 Gr.B at 260°C)
    E=1.0,               # joint efficiency
    Y=0.4,               # coefficient (ductile material)
)
print(result["t_min_mm"], result["t_with_ca_mm"])
```

## LLM tools

`piping_layout`, `piping_stress_check`, `piping_iso_generate`

## References

- ASME B31.3-2022, *Process Piping*, ch. III (pressure design).
- CAESAR II User's Guide (pipe stress compliance).

## Honest caveats

ASME B31.3 wall thickness calculation uses the simplified formula (2P.1). The full stress analysis (sustained, expansion, and occasional loads) requires the beam-element pipe stress model. Flange leakage checks per ASME PCC-1 and nozzle loads per WRC Bulletin 107 are not implemented. Isometric generation assumes straight-line routing with standard elbows; complex piping geometry requires manual routing specification.
