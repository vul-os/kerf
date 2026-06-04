# Daylight Factor and Lux Simulation

*Domain: Building Energy · Module: `packages/kerf-energy/src/kerf_energy/daylight.py` · Shipped: Wave 10*

## Overview

Computes the Daylight Factor (DF) for a room using the split-flux method (BRE / CIBSE LG10) and checks compliance against BS 8206 Part 2 targets. Provides direct component (DC), externally reflected component (ERC), and internally reflected component (IRC) contributions. Used for early-stage daylighting design without a full Radiance simulation.

## When to use

- Early-stage daylighting assessment for planning applications.
- Checking if a proposed glazing area meets BS 8206 / BREEAM HEA-01 targets.
- Comparing window-to-floor-area ratios for different facade configurations.

## API

```python
from kerf_energy.daylight import (
    daylight_factor_split_flux,
    check_bs8206_compliance,
)

df = daylight_factor_split_flux(
    glazing_area_m2=4.0,
    room_floor_area_m2=20.0,
    room_height_m=2.7,
    window_head_height_m=2.3,
    obstruction_angle_deg=15.0,
    reflectance_ceiling=0.7,
    reflectance_walls=0.5,
    reflectance_floor=0.2,
    transmittance=0.65,
)

compliance = check_bs8206_compliance(space_type="office", df_percent=df["DF_percent"])
print(compliance["compliant"], compliance["target_df"])
```

## LLM tools

`energy_daylight`

## References

- BRE, "Site layout planning for daylight and sunlight", BRE 209 (2011).
- CIBSE, *Lighting Guide LG10: Daylighting and window design* (2014).
- BS 8206-2:2008, "Lighting for buildings — Part 2: Code of practice for daylighting".

## Honest caveats

The split-flux method is a simplified analytical model and does not account for complex room geometry, obstructions between rooms, or directional sky models. It provides an average daylight factor at the reference plane, not a point-in-time spatial distribution. For compliance-grade results use the Radiance-based path.
