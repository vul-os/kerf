# Injection Mold Flow Simulation — `procsim/moldflow.py`

Simplified injection moulding process simulation: power-law slit flow, fill time, pressure drop, clamp tonnage, and freeze-off estimation.

---

## Physical model

Power-law viscosity model (Throne, 1979) for slit-flow approximation:

- **Apparent viscosity:** `η = K × (γ̇)^(n-1)` where `K` is the consistency index and `n` is the power-law exponent.
- **Pressure drop (slit):** `ΔP = (2L/H) × K × (6Q / (W H²))^n`
- **Clamp force:** `F_clamp = ΔP × A_projected`
- **Freeze-off:** thermal solidification time from Barone-Caulk model.

---

## Public API

### `fill_simulation(cavity_dict, material_dict, *, injection_speed_mm3_s=5000.0, melt_temp_c=230.0, mold_temp_c=40.0) → dict`

`cavity_dict`: `{"length_mm": 150, "width_mm": 80, "thickness_mm": 3, "projected_area_mm2": 12000}`

`material_dict`: `{"name": "PP", "K_pa_s_n": 4500, "n": 0.35, "density_g_cm3": 0.91}`

Returns:
```json
{
  "fill_time_s": 1.8,
  "pressure_drop_mpa": 42.5,
  "clamp_force_kn": 510.0,
  "freeze_off_s": 8.2,
  "shear_rate_1_per_s": 1240.0,
  "apparent_viscosity_pa_s": 185.0,
  "gate_freeze_time_s": 3.1,
  "warnings": ["High shear rate — verify material stability"]
}
```

### `material_library() → list[dict]`

Returns built-in material records: ABS, PP, HDPE, PA6, PC, POM, TPU.

### `clamp_tonnage(projected_area_mm2, fill_pressure_mpa, *, safety_factor=1.2) → float`

Returns required clamp tonnage in kN.

### `wall_thickness_check(thickness_mm, material) → dict`

Checks wall thickness against min/max guidelines for the material:
```json
{"ok": true, "min_mm": 1.0, "max_mm": 4.0, "recommended_mm": 2.5, "notes": "..."}
```

---

## Usage

```python
from kerf_cad_core.procsim.moldflow import fill_simulation, material_library

mats = material_library()
pp = next(m for m in mats if m["name"] == "PP")

cavity = {
    "length_mm": 150, "width_mm": 80,
    "thickness_mm": 3, "projected_area_mm2": 12000
}
result = fill_simulation(cavity, pp, injection_speed_mm3_s=4000)
print(result["clamp_force_kn"], "kN")
print(result["fill_time_s"], "s fill time")
```

---

## References

- Throne, J.L., *Plastics Process Engineering*, Marcel Dekker, 1979 — power-law slit flow.
- Barone, M.R. & Caulk, D.A., "A model for the flow of a chopped fiber reinforced polymer compound in compression moulding," *J. Applied Mechanics* 53, 1986 — freeze-off model.
