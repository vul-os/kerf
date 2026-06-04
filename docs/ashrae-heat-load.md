# ASHRAE Heat-Load Calculation (CLTD/CLF)

> Cooling and heating load estimation using the ASHRAE Cooling-Load Temperature-Difference / Cooling-Load Factor method for building zones.

**Module**: `packages/kerf-energy/src/kerf_energy/heat_load.py`
**Shipped**: Wave 9
**LLM tools**: `energy_heat_load`

---

## What it is

Before sizing HVAC equipment you need an accurate estimate of the peak cooling and heating loads for each zone. ASHRAE's CLTD/CLF method is the approved hand-calculation procedure from the Handbook of Fundamentals Chapter 18: it accounts for solar gain through walls and roofs via pre-tabulated temperature-difference corrections that implicitly model thermal mass. Use this for preliminary equipment sizing, energy budgeting, and LEED load documentation.

## How to use it

### From chat

> "Calculate the peak cooling load at 3 PM for a south-facing office zone: 40 m² floor, 8 m² glazing (SC = 0.6), 20 m² exterior wall, medium-weight construction, 40°N latitude, July 21."

### From Python

```python
from kerf_energy.heat_load import (
    cltd_for_wall, cltd_for_roof, wall_heat_gain, roof_heat_gain, zone_heat_load
)

# South wall heat gain at 3 PM (hour 15)
cltd = cltd_for_wall(hour=15, facing="south")
q_wall = wall_heat_gain(u_value=0.5, area_m2=20.0, cltd=cltd)
q_roof = roof_heat_gain(u_value=0.3, area_m2=40.0, hour=15)
print(f"Wall gain: {q_wall:.0f} W, Roof gain: {q_roof:.0f} W")
```

### From an LLM tool spec

```json
{"zone_name": "Office 1", "floor_area_m2": 40,
 "wall_u": 0.5, "wall_area_m2": 20, "wall_facing": "south",
 "roof_u": 0.3, "roof_area_m2": 40,
 "glazing_area_m2": 8, "shading_coeff": 0.6,
 "hour": 15, "occupants": 4}
```

## How it works

CLTD values are tabulated per hour (1–24), surface type (wall/roof), and exposure. For medium-weight walls the module uses ASHRAE HOF 2021 Table 1 Ch. 18 representative values. Wall heat gain: Q_wall = U × A × CLTD. Solar gain through glass: Q_glass = A × SC × SHGC × CLF where CLF is the Cooling-Load Factor that accounts for room thermal storage dampening the instantaneous solar pulse. Internal gains (people, lights, equipment) are added via their respective CLF fractions. Heating load (winter design day) uses the ASHRAE simplified steady-state conduction: Q = U × A × ΔT.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `cltd_for_wall(hour, facing)` | `float` (°C) | CLTD for exterior wall |
| `cltd_for_roof(hour)` | `float` (°C) | CLTD for flat roof |
| `wall_heat_gain(u_value, area_m2, cltd)` | `float` (W) | Conductive wall gain |
| `roof_heat_gain(u_value, area_m2, hour)` | `float` (W) | Conductive roof gain |
| `zone_heat_load(zone_spec)` | `dict` | Complete zone peak load |

## Example

```python
from kerf_energy.heat_load import zone_heat_load

result = zone_heat_load({
    "floor_area_m2": 50, "wall_u": 0.45, "wall_area_m2": 30,
    "roof_u": 0.25, "roof_area_m2": 50,
    "glazing_area_m2": 10, "shading_coeff": 0.7,
    "occupants": 6, "lighting_w_m2": 12, "hour": 14
})
print(f"Peak cooling load: {result['total_cooling_w']:.0f} W")
```

## Honest caveats

CLTD/CLF uses simplified tabulated values calibrated for July 21, 40°N, dark surface — corrections for latitude, month, surface colour, and daily temperature range should be applied for other climates. The method is superseded by the Radiant Time Series (RTS) method in ASHRAE 2021 for precision work but remains acceptable for preliminary sizing. Internal gains use fixed CLF = 1.0 (no thermal storage effect on occupant/lighting gains).

## References

- ASHRAE (2021). *Handbook of Fundamentals*, Ch. 18 — Nonresidential Cooling and Heating Load Calculations.
- Spitler, J.D. (2014). *Load Calculation Applications Manual*, 2nd ed. ASHRAE.
