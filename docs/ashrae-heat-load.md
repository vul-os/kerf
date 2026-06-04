# ASHRAE Cooling and Heating Load Calculations

*Domain: Building Energy · Module: `packages/kerf-energy/src/kerf_energy/heat_load.py` · Shipped: Wave 10*

## Overview

Implements ASHRAE Fundamentals (2021) CLTD/CLF cooling load calculation methods and simple manual-J heating load calculations. Covers conductive wall/roof loads, solar gain through glazing, occupancy, lighting, and equipment sensible heat gains. Returns a zone-level peak cooling load and heating load for HVAC equipment sizing.

## When to use

- Sizing air-conditioning equipment for residential or light-commercial spaces.
- Compliance checking against ASHRAE 90.1 manual calculations.
- Pre-design load estimates before a full EnergyPlus 8760-hour simulation.

## API

```python
from kerf_energy.heat_load import (
    ZoneHeatLoad, WallElement, GlazingElement,
    OccupancyLoad, LightingLoad, EquipmentLoad,
    zone_heating_load_w,
)

zone = ZoneHeatLoad(
    walls=[
        WallElement(area=20.0, U=0.35, facing="south"),
        WallElement(area=15.0, U=0.35, facing="west"),
    ],
    glazing=[
        GlazingElement(area=4.0, U=2.0, SHGC=0.4, facing="south"),
    ],
    occupancy=OccupancyLoad(n_people=4, sensible_w=75, latent_w=55),
    lighting=LightingLoad(power_w=200),
    equipment=EquipmentLoad(sensible_w=500),
    outdoor_design_temp=35.0,
    indoor_setpoint=24.0,
)

peak_cooling_w = zone.peak_cooling_load(hour=15)
peak_heating_w = zone_heating_load_w(
    [WallElement(area=35.0, U=0.35, facing="north")],
    outdoor_design_temp=-5.0,
    indoor_setpoint=20.0,
)
```

## LLM tools

`energy_heat_load`

## References

- ASHRAE, *Fundamentals Handbook*, 2021, ch. 18 (Nonresidential Cooling and Heating Load Calculations).
- ASHRAE, *Residential Cooling and Heating Load Calculations* (Manual J equivalent methodology).

## Honest caveats

CLTD values are tabulated for medium-weight construction facing four cardinal directions. Non-cardinal orientations use linear interpolation. Latent loads are not summed into the total cooling load — add them separately. The calculation follows simplified CLTD/CLF; for high-accuracy results or code-compliance energy modelling use the full 8760-hour simulation path (`energy_8760`).
