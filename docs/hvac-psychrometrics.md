# HVAC Psychrometrics and Plant Sizing

*Domain: HVAC · Module: `packages/kerf-cad-core/src/kerf_cad_core/hvac/` · Shipped: Wave 8*

## Overview

Psychrometric calculations (moist-air properties at any state point), HVAC plant sizing (AHU, chillers, cooling towers), duct sizing by equal-friction and velocity methods, and coil performance. Implements the ASHRAE 2021 Fundamentals psychrometric equations and the ASHRAE Handbook of Fundamentals coil-performance correlations.

## When to use

- Computing supply-air conditions, AHU coil loads, and humidification/dehumidification requirements.
- Sizing supply/return ducts for a zone air distribution system.
- Generating a psychrometric process chart for a given AHU sequence.

## API

```python
from kerf_cad_core.hvac.psychro import (
    moist_air_properties,
    enthalpy_moist_air,
    dew_point,
    wet_bulb_from_dry_bulb_rh,
)
from kerf_cad_core.hvac.duct import (
    duct_size_equal_friction,
    duct_size_velocity_method,
)

# Moist-air properties at 26°C, 60% RH, 101.325 kPa
props = moist_air_properties(T_dry_C=26.0, RH=0.60)
print(props["W_kg_per_kg"])   # humidity ratio
print(props["h_kJ_per_kg"])   # specific enthalpy

# Duct sizing
duct = duct_size_equal_friction(
    Q_m3_s=0.5,
    friction_Pa_per_m=0.8,
)
```

## LLM tools

`hvac_psychro`, `hvac_duct_size`, `hvac_coil_size`

## References

- ASHRAE, *Fundamentals Handbook* 2021, ch. 1 (Psychrometrics).
- ASHRAE, *HVAC Systems and Equipment Handbook* 2020, ch. 19 (Coils).
- SMACNA, *HVAC Duct Construction Standards*, 3rd ed.

## Honest caveats

Psychrometric equations are valid for pressures between 70–105 kPa. At high altitudes or unusual barometric conditions supply the actual pressure. The duct-sizing methods assume straight circular or rectangular ducts; fittings, transitions, and diffusers are sized separately using loss coefficients. Refrigerant-circuit coil modelling is not included.
