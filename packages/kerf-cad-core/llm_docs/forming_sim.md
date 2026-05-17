# Forming Simulation — `procsim/forming_sim.py`

Sheet metal formability assessment using the Keeler-Goodwin Forming Limit Curve (FLC), strain path analysis, safety margin, and springback estimation.

---

## Public API

### `forming_limit_curve(material, *, thickness_mm=1.0, strain_rate=0.0) → dict`

Computes the Keeler-Goodwin FLC for a material:
```json
{
  "material": "DC04",
  "thickness_mm": 1.0,
  "fld0_major": 0.28,
  "curve_points": [[minor_strain, major_strain], ...],
  "notes": "Keeler-Goodwin empirical FLC; thickness correction applied"
}
```

### `strain_path_check(e_major, e_minor, fld_curve, *, safety_margin=0.1) → dict`

Checks a (major, minor) strain state against the FLC:
```json
{
  "ok": true,
  "safety_margin_fraction": 0.18,
  "distance_to_fld_mm": 0.06,
  "risk_level": "safe",
  "failure_mode": null
}
```

`risk_level`: `"safe"`, `"marginal"`, `"necking"`, `"fracture"`.

### `springback_estimate(yield_stress_mpa, elastic_modulus_gpa, bend_radius_mm, thickness_mm) → dict`

Estimates springback angle for a bend:
```json
{
  "springback_deg": 3.8,
  "die_compensation_deg": 3.8,
  "final_angle_deg": 90.0,
  "notes": "Overbend by 3.8° to achieve 90° after springback"
}
```

### `blank_size_estimate(part_shape, *, method="developed_length") → dict`

Estimates flat blank dimensions from a bent part description.

---

## Usage

```python
from kerf_cad_core.procsim.forming_sim import (
    forming_limit_curve, strain_path_check, springback_estimate
)

fld = forming_limit_curve("DC04", thickness_mm=1.5)
check = strain_path_check(0.22, -0.05, fld["curve_points"])
print(check["risk_level"])

sb = springback_estimate(yield_stress_mpa=280, elastic_modulus_gpa=210,
                          bend_radius_mm=5, thickness_mm=1.5)
print(sb["springback_deg"])
```

---

## References

- Keeler, S.P. & Backofen, W.A., "Plastic instability and fracture in sheets stretched over rigid punches," *Trans. ASM* 56, 1963.
- Goodwin, G.M., "Application of strain analysis to sheet metal forming problems," *SAE Technical Paper* 680093, 1968.
