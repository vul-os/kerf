# arch_check_bearing_wall_axial

*Module: `kerf_cad_core.arch.bearing_wall_axial_tools` · Domain: cad*

## Description

Check axial-load capacity of a plain concrete, reinforced concrete, or masonry bearing wall.

ACI 318-19 §11.5.3.1 (concrete/RC — empirical method):
  φ·Pn = 0.55·φ·f'c·Ag·[1 − (k·lc/(32·t))²]
  Valid when e ≤ t/6 (small eccentricity bound). k: fixed_fixed=0.8, pin_pin=1.0, cantilever=2.0.

TMS 402-22 §8.3 Eq 8-22 (clay_masonry / concrete_masonry):
  r = t/√12; h_eff = k·h; C_s = 1 − (h_eff/(140·r))² (valid h_eff/r ≤ 99).
  φ·Pn = φ·0.80·f'm·Ag·C_s

Returns phi_Pn_kN_per_m, slenderness_factor, dcr, adequate, governing_check, honest_caveat.

SCOPE: ACI §11.5.3.1 EMPIRICAL method only. Large eccentricity (e>t/6) requires full PM interaction (ACI §11.4). Reinforcement NOT credited in ACI §11.5.3.1. TMS Eq 8-22 valid for h_eff/r ≤ 99 only. No in-plane shear (ACI §11.6). All inputs in mm and MPa; force in kN/m.

## Input schema

```json
{
  "type": "object",
  "required": [
    "wall_thickness_t_mm",
    "wall_height_h_mm",
    "wall_length_lw_m",
    "material",
    "f_prime_MPa",
    "P_factored_kN_per_m"
  ],
  "properties": {
    "wall_thickness_t_mm": {
      "type": "number",
      "description": "Wall thickness t (mm). Must be > 0."
    },
    "wall_height_h_mm": {
      "type": "number",
      "description": "Clear storey height h between supports (mm). Must be > 0. Governs slenderness and empirical \u03c6Pn."
    },
    "wall_length_lw_m": {
      "type": "number",
      "description": "Horizontal plan length of wall (m). Informational. Must be > 0."
    },
    "material": {
      "type": "string",
      "enum": [
        "concrete",
        "reinforced_concrete",
        "clay_masonry",
        "concrete_masonry"
      ],
      "description": "Wall material. 'concrete'/'reinforced_concrete' use ACI \u00a711.5.3.1; 'clay_masonry'/'concrete_masonry' use TMS 402-22 \u00a78.3 Eq 8-22."
    },
    "f_prime_MPa": {
      "type": "number",
      "description": "Compressive strength (MPa): f'c for concrete/RC, f'm for masonry. Must be > 0."
    },
    "P_factored_kN_per_m": {
      "type": "number",
      "description": "Factored axial compressive demand per unit wall width (kN/m). Must be >= 0."
    },
    "As_per_m": {
      "type": "number",
      "description": "Vertical reinforcement area (mm\u00b2/m). Default 0. NOTE: NOT credited in ACI \u00a711.5.3.1 empirical formula."
    },
    "fy_MPa": {
      "type": "number",
      "description": "Steel yield strength (MPa). Default 420. Informational only in ACI \u00a711.5.3.1 method."
    },
    "end_conditions": {
      "type": "string",
      "enum": [
        "fixed_fixed",
        "pin_pin",
        "cantilever"
      ],
      "description": "End conditions. fixed_fixed\u2192k=0.8 (ACI Commentary R11.5.3.1); pin_pin\u2192k=1.0; cantilever\u2192k=2.0."
    },
    "eccentricity_e_mm": {
      "type": "number",
      "description": "Load eccentricity from wall centroid (mm). Default 0. ACI \u00a711.5.3.1 requires e \u2264 t/6. If e > t/6, formula is not applicable; governing_check = 'large_eccentricity_method_required'."
    },
    "phi": {
      "type": "number",
      "description": "Strength-reduction factor \u03c6. Default 0.65 (ACI 318-19 Table 21.2.2 compression-controlled)."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_bearing_wall_axial",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
