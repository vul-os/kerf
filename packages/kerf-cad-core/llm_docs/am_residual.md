# Additive Manufacturing Residual Stress — `procsim/am_residual.py`

Inherent-strain-based residual stress and distortion estimates for LPBF (laser powder bed fusion) and DED (directed energy deposition) processes.

---

## Physical model

Inherent-strain method (Simufact / Goldak approach): assigns a uniform eigenstrain `ε*` to each deposited layer; global distortion estimated from Stoney equation for thin substrate or beam-bending model for tall builds.

Stress relief: temperature/time-dependent recovery fraction via Zener–Hollomon parameter.

---

## Public API

### `am_residual_estimate(process, *, layer_height_mm, num_layers, scan_strategy="zigzag", material="316L_steel", substrate_thickness_mm=20.0, preheat_c=None) → dict`

`process`: `"lpbf"` or `"ded"`

`scan_strategy`: `"zigzag"`, `"island_67deg"`, `"unidirectional"`

Returns:
```json
{
  "inherent_strain_xx": -0.0028,
  "inherent_strain_yy": -0.0031,
  "peak_residual_stress_mpa": 380.0,
  "stoney_curvature_1_per_m": 0.35,
  "max_deflection_mm": 1.2,
  "delamination_risk": "medium",
  "notes": "Island 67° strategy reduces peak stress ~25% vs zigzag"
}
```

### `stress_relief_cycle(material, *, temp_c, hold_min) → dict`

Predicts residual stress reduction after a stress-relief heat treatment:
```json
{
  "material": "316L_steel",
  "temp_c": 600,
  "hold_min": 120,
  "stress_reduction_pct": 72.0,
  "zener_hollomon_param": 3.2e12,
  "notes": "600°C / 2hr typical for 316L; ~70–75% stress relief"
}
```

### `support_strategy(geometry_dict, *, overhang_deg=45.0, process="lpbf") → dict`

Flags faces requiring supports and estimates support material volume/removal time.

---

## Usage

```python
from kerf_cad_core.procsim.am_residual import am_residual_estimate, stress_relief_cycle

result = am_residual_estimate(
    "lpbf", layer_height_mm=0.03, num_layers=400,
    scan_strategy="island_67deg", material="316L_steel"
)
print(result["peak_residual_stress_mpa"])
print(result["max_deflection_mm"])

relief = stress_relief_cycle("316L_steel", temp_c=600, hold_min=120)
print(relief["stress_reduction_pct"])
```

---

## References

- Goldak, J. et al., "A new finite element model for welding heat sources," *Metallurgical Transactions B* 15(2), 1984.
- Mercelis, P. & Kruth, J-P., "Residual stresses in selective laser sintering and selective laser melting," *Rapid Prototyping Journal* 12(5), 2006.
