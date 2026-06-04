# Daylight Factor Simulation

> Mean Daylight Factor via the BRS split-flux method, plus spatial daylight autonomy indicators for window sizing and daylighting code compliance.

**Module**: `packages/kerf-energy/src/kerf_energy/daylight.py`
**Shipped**: Wave 9
**LLM tools**: `energy_daylight_factor`

---

## What it is

Daylight Factor (DF) is the ratio of interior illuminance to simultaneous unobstructed outdoor illuminance under an overcast CIE sky, expressed as a percentage. It is the primary metric for daylighting adequacy in BS 8206-2 and CIBSE LG10: a DF ≥ 2% is the minimum for task lighting, DF ≥ 5% indicates good daylighting. This module computes the mean DF for a room using the Building Research Station (BRS) split-flux formula, handling glazing transmittance, external obstruction angle, and room reflectance.

## How to use it

### From chat

> "Calculate the daylight factor for a 6 m × 5 m open-plan office with a 4 m² window (τ = 0.65), facing a building across the street that obstructs 40% of the sky. Average surface reflectance 0.45."

### From Python

```python
from kerf_energy.daylight import daylight_factor_split_flux

df = daylight_factor_split_flux(
    window_area_m2=4.0,
    room_floor_area_m2=30.0,
    tau=0.65,
    sky_component_fraction=0.60,   # 40% obstructed
    average_reflectance=0.45,
)
print(f"Mean DF: {df:.2f}%")
```

### From an LLM tool spec

```json
{"window_area_m2": 4.0, "room_floor_area_m2": 30.0,
 "tau": 0.65, "sky_component_fraction": 0.6,
 "average_reflectance": 0.45}
```

## How it works

The BRS split-flux formula: DF = (τ × A_w × θ) / (A_total × (1 − ρ̄²)) × 100%, where τ is glazing transmittance, A_w is window area, θ is the sky-component fraction (accounting for external obstruction), A_total is total room surface area (approximated as 6 × floor area for a compact room when not specified), and ρ̄ is the area-weighted average surface reflectance. The denominator term (1 − ρ̄²) models multiple inter-reflections within the room. The formula gives the mean DF at the working plane level (0.8 m above floor).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `daylight_factor_split_flux(window_area_m2, room_floor_area_m2, tau, sky_component_fraction, average_reflectance, externally_obstructed_fraction)` | `float` (%) | BRS mean DF |

## Example

```python
from kerf_energy.daylight import daylight_factor_split_flux

# Compare two window options for a 40 m² classroom
df_2m2 = daylight_factor_split_flux(2.0, 40.0, tau=0.7, sky_component_fraction=0.8)
df_6m2 = daylight_factor_split_flux(6.0, 40.0, tau=0.7, sky_component_fraction=0.8)
print(f"2 m² window: {df_2m2:.2f}%  |  6 m² window: {df_6m2:.2f}%")
```

## Honest caveats

The BRS split-flux formula gives the mean DF across the floor plane; it does not indicate spatial distribution or uniformity ratio. For LEED v4 compliance (spatial daylight autonomy sDA ≥ 55%), a climate-based simulation (Radiance, Daysim, or EnergyPlus) is required. This module does not compute direct sunlight admittance or annual insolation.

## References

- Hopkinson, R.G., Petherbridge, P. & Longmore, J. (1966). *Daylighting*. Heinemann. (split-flux derivation)
- BS 8206-2:2008. *Lighting for buildings — Code of practice for daylighting*.
- IES LM-83-12. Spatial Daylight Autonomy (sDA) and Annual Sunlight Exposure (ASE).
