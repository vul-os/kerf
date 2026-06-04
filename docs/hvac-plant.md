# HVAC Duct Sizing & Plant

> ASHRAE velocity-method duct sizing for rectangular and round ducts, plus duct-network pressure-drop calculation for HVAC plant design.

**Module**: `packages/kerf-hvac/src/kerf_hvac/sizing.py`, `duct.py`, `pressure.py`
**Shipped**: Wave 11
**LLM tools**: `hvac_size_duct`, `hvac_pressure_drop`

---

## What it is

HVAC plant design begins with duct sizing: for each branch of the air-distribution network, choose the smallest standard duct cross-section that carries the design airflow without exceeding the maximum velocity limit. Oversized ducts waste material and space; undersized ducts generate noise and excessive static pressure. This module implements the ASHRAE velocity method and SMACNA pressure-drop calculations for rectangular and round ductwork.

## How to use it

### From chat

> "Size a rectangular supply duct for 1200 cfm at maximum 800 fpm velocity. Convert to SI and give the hydraulic diameter."

### From Python

```python
from kerf_hvac.sizing import size_duct
from kerf_hvac.duct import DuctShape, cfm_to_m3s, fpm_to_ms

result = size_duct(
    flow_m3s=cfm_to_m3s(1200),
    v_max_m_s=fpm_to_ms(800),
    shape=DuctShape.RECTANGULAR
)
print(f"Width: {result.width_mm:.0f} mm × Height: {result.height_mm:.0f} mm")
print(f"Velocity: {result.actual_velocity_m_s:.2f} m/s")
print(f"Hydraulic diameter: {result.hydraulic_diameter_m*1000:.0f} mm")
```

### From an LLM tool spec

```json
{"flow_cfm": 1200, "max_velocity_fpm": 800,
 "shape": "rectangular", "max_aspect_ratio": 4}
```

## How it works

The velocity method selects the smallest standard duct whose cross-sectional area satisfies A ≥ Q/V_max. For round ducts, standard diameters are in 25 mm increments from 100 to 1625 mm. For rectangular ducts, width and height are rounded up to the nearest 25 mm module with aspect ratio ≤ 4:1 (ASHRAE recommendation). Hydraulic diameter D_h = 4A/P where P is the wetted perimeter. Pressure drop uses the Darcy-Weisbach equation with Colebrook friction factor for the duct Reynolds number, plus fitting loss coefficients from ASHRAE Duct Design Fundamentals.

## API reference

| Function / Class | Returns | Purpose |
|---|---|---|
| `size_duct(flow_m3s, v_max_m_s, shape)` | `SizingResult` | Select smallest standard duct |
| `DuctSection(shape, width, height, diameter, length)` | `DuctSection` | Duct segment data model |
| `cfm_to_m3s(cfm)` | `float` | Unit conversion |
| `fpm_to_ms(fpm)` | `float` | Unit conversion |

`SizingResult` fields: `shape`, `width_mm`, `height_mm`, `diameter_mm`, `actual_velocity_m_s`, `area_m2`, `hydraulic_diameter_m`, `aspect_ratio`.

## Example

```python
from kerf_hvac.sizing import size_duct
from kerf_hvac.duct import DuctShape

r = size_duct(flow_m3s=0.5, v_max_m_s=4.0, shape=DuctShape.ROUND)
print(f"Round duct: Ø{r.diameter_mm:.0f} mm, V={r.actual_velocity_m_s:.2f} m/s")
```

## Honest caveats

The velocity method does not account for system effect (turbulence from fittings near the fan outlet). SMACNA fitting loss coefficients are built in for standard elbows and tees only; custom fitting coefficients must be supplied by the caller. Variable air volume (VAV) systems require load-schedule-weighted sizing, not covered here.

## References

- ASHRAE (2020). *HVAC Systems and Equipment Handbook*, Ch. 21 (Duct Design Fundamentals).
- SMACNA (2006). *HVAC Duct Construction Standards — Metal and Flexible*, 3rd ed.
