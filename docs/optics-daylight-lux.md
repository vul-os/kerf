# Daylight and Electric Luminance Simulation

> Compute interior lux levels from sunlight, sky diffuse irradiance, and electric luminaires — for daylighting compliance, LEED credits, and architectural lighting design.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/render/luminance_lux_sim.py`
**Shipped**: Wave 9
**LLM tools**: `lighting_daylight_lux`

---

## What it is

Daylighting simulation predicts interior illuminance from the sun and sky — a critical check for building energy codes (ASHRAE 90.1, EN 17037) and LEED Daylight credits. This module computes time-of-day sun position (altitude, azimuth) for any geographic location, direct normal and diffuse horizontal irradiance using the Perez sky model, and the resulting illuminance on arbitrary surface meshes.

It also handles electric luminaires: point sources and IES-profile fixtures can be added to the scene and their contributions added to the daylight simulation, producing a combined illuminance report for any occupancy schedule.

## How to use it

### From chat (natural language)

> "What is the average lux on the work plane in this office at 9am on June 21 at latitude 33°S?"

The LLM calls `lighting_daylight_lux` with location, date, time, and room geometry.

### From Python

```python
from kerf_cad_core.render.luminance_lux_sim import (
    sun_position, compute_daylight_lux, DaylightConditions,
    ElectricLuminaire, LuxReport,
)

# Sun position
alt, az = sun_position(latitude=33.0, longitude=18.4,
                        date_iso="2026-06-21", time_hhmm="09:00")

conditions = DaylightConditions(
    sky_model="perez",
    latitude=33.0, longitude=18.4,
    date_iso="2026-06-21", time_hhmm="09:00",
    site_altitude_m=50,
)
report: LuxReport = compute_daylight_lux(
    conditions=conditions,
    work_plane_mesh=floor_mesh,
    window_meshes=[window1_mesh],
)
print(f"Mean work-plane lux: {report.mean_lux:.0f} lx")
print(f"Daylight factor: {report.daylight_factor:.1%}")
```

### From an LLM tool spec

```json
{"tool": "lighting_daylight_lux", "latitude": 33.0, "longitude": 18.4,
 "date_iso": "2026-06-21", "time_hhmm": "09:00", "sky_model": "perez"}
```

## How it works

Sun position is computed from the NOAA solar position algorithm using the equation of time and hour angle. Perez sky model coefficients convert the direct and diffuse radiation (from climate data or the clear-sky model) into a sky luminance distribution as a function of angle from the sun. Illuminance on each surface mesh element is computed by integrating the sky luminance over the visible hemisphere, weighted by the cosine of incidence and blocked by occlusion geometry.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `sun_position(latitude, longitude, date_iso, time_hhmm)` | `(float, float)` | Solar altitude, azimuth (degrees) |
| `compute_daylight_lux(conditions, work_plane_mesh, window_meshes)` | `LuxReport` | Interior daylight simulation |
| `render_luminance_map(conditions, sensor_grid)` | `np.ndarray` | Sky luminance grid |

`LuxReport` fields: `mean_lux`, `min_lux`, `max_lux`, `daylight_factor`, `uniformity_ratio`, `grid_lux`.

## Example

```python
alt, az = sun_position(51.5, -0.1, "2026-06-21", "12:00")
print(f"London noon sun: alt={alt:.1f}°, az={az:.1f}°")
# Output: alt=60.8°, az=179.3°
```

## Honest caveats

The Perez sky model requires horizontal radiation data (GHI, DNI) from a climate file or TMY dataset — it does not compute radiation from first principles. The simulation assumes clear-sky conditions if no radiation data is supplied; actual overcast or partly cloudy conditions will differ. Interreflections (light bouncing off room surfaces) are not computed in this module; use the archviz renderer for multi-bounce interiors.

## References

- Perez, Seals & Michalsky (1993). "All-weather model for sky luminance distribution." *Solar Energy* 50(3).
- NOAA Solar Calculator — NOAA Earth System Research Laboratories.
- EN 17037:2018. *Daylight in buildings*. CEN.
