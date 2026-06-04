# Pressure Vessel Design (ASME VIII)

*Domain: Mechanical · Module: `packages/kerf-cad-core/src/kerf_cad_core/pressvessel/` · Shipped: Wave 8*

## Overview

ASME BPVC Section VIII Division 1 and Division 2 pressure vessel design calculations: minimum required thickness for cylindrical shells, hemispherical and ellipsoidal heads, conical sections, and nozzle openings; joint efficiency; required area replacement for nozzles; flange design per ASME B16.5; and hydrostatic test pressure determination.

## When to use

- Calculating minimum wall thickness for a pressure vessel under internal or external pressure.
- Checking nozzle reinforcement pad requirements.
- Generating a design calculation package for a vessel code stamp.

## API

```python
from kerf_cad_core.pressvessel.tools import (
    cylindrical_shell_thickness,
    hemispherical_head_thickness,
    ellipsoidal_head_thickness,
    nozzle_reinforcement,
    test_pressure,
)

# ASME VIII-1, internal pressure
result = cylindrical_shell_thickness(
    P_MPa=1.5,          # design pressure
    D_inside_mm=500,
    S_MPa=138.0,        # allowable stress (SA-516 Gr.70 at 250°C)
    E=1.0,              # weld joint efficiency
    CA_mm=3.0,          # corrosion allowance
)
print(result["t_required_mm"])
print(result["t_total_with_ca_mm"])
```

## LLM tools

`vessel_shell_thickness`, `vessel_head_thickness`, `vessel_nozzle_check`

## References

- ASME BPVC Section VIII Division 1 — 2023 Edition, UG-27 (cylindrical shells), UG-32 (heads).
- ASME BPVC Section VIII Division 2 — 2023 Edition, Part 4 (design by rule).

## Honest caveats

ASME VIII-1 UG-27 and UG-32 formulas are the simplified closed-form equations valid for D/t > 10 (thin-wall). Thick-wall vessels (D/t < 10) require the Lamé equation. External pressure design (vacuum vessels) uses a different graph-based method not implemented here. Fatigue analysis per ASME VIII-2 Annex 3-F is not covered.
