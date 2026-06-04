# Gear Geometry and Strength

*Domain: Mechanical · Module: `packages/kerf-cad-core/src/kerf_cad_core/gearstrength/` · Shipped: Wave 8*

## Overview

Involute gear geometry (module, pressure angle, addendum/dedendum, helix angle for helical gears) and AGMA 2101-D04 / ISO 6336 gear strength calculation: bending stress (Lewis + AGMA Yj factor), contact stress (Hertz + AGMA I factor), dynamic factor (AGMA Kv), and surface fatigue life. Covers spur, helical, bevel, and worm gear pairs.

## When to use

- Sizing a gear pair for a given torque, speed, and service life.
- Checking an existing gear design against AGMA or ISO allowable stress limits.
- Computing gear geometry parameters for hobbing or grinding machine setup.

## API

```python
from kerf_cad_core.gearstrength.tools import (
    InvoluteGear, GearPair,
    agma_bending_stress, agma_contact_stress,
    gear_geometry,
)

pinion = InvoluteGear(
    module_mm=2.5, teeth=20,
    pressure_angle_deg=20.0,
    helix_angle_deg=15.0,
    face_width_mm=25.0,
    material="4140_steel_HRC38",
)
gear = InvoluteGear(module_mm=2.5, teeth=60, ...)

pair = GearPair(pinion=pinion, gear=gear, power_kW=5.0, rpm=1500)

bend = agma_bending_stress(pair)
contact = agma_contact_stress(pair)

print(bend["SF"])       # bending safety factor
print(contact["SH"])    # contact safety factor
```

## LLM tools

`feature_gear_design`, `feature_gearbox_sizing`

## References

- AGMA 2101-D04, *Fundamental Rating Factors and Calculation Methods for Involute Spur and Helical Gear Teeth*.
- ISO 6336-1:2019, *Calculation of load capacity of spur and helical gears*.

## Honest caveats

The AGMA strength factors (Yj, I, Kv, KH) use closed-form approximations from the AGMA standard; exact values require the AGMA geometry factor charts or the full ISO 6336 numerical method. Bevel gear calculations use the Tregold's approximation (virtual spur gear). Worm gear contact calculations omit the sliding friction thermal analysis — check blank temperature separately for high-speed worm sets.
