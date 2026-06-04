# arch_check_pier_axial

*Module: `kerf_cad_core.arch.pier_axial_capacity_tools` · Domain: cad*

## Description

Check axial-load capacity of a slender masonry or reinforced concrete pier under a given factored demand load.

Supported material types:
  • clay_masonry      — TMS 402-22 §8.3: φ·Pn = φ·0.80·f'm·Ag·C_s
  • concrete_masonry  — TMS 402-22 §8.3: same formula
  • reinforced_concrete — ACI 318-19 §22.4.2.2: φ·Pn = φ·0.80·[0.85·f'c·(Ag−As)+fy·As]·C_s

Slenderness reduction (TMS Eq 8-22):
  C_s = 1 − (h_eff / (140·r))²   for h_eff/r ≤ 99
  h_eff/r > 99 → slenderness_limit_exceeded (φ·Pn returned as 0)

Radius of gyration: r = min(pier_width, pier_thickness) / √12 (governing weak-axis r for rectangular section).

Effective height: h_eff = k · h, where k depends on end_conditions:
  fixed_fixed=0.5, pin_pin=1.0, fixed_pin=0.7, cantilever=2.0

Returns phi_Pn_kN, slenderness_factor, h_over_r, governing_failure_mode (yielding|slender_buckling|slenderness_limit_exceeded), demand_capacity_ratio, adequate, honest_caveat.

SCOPE: Concentric axial load ONLY — no eccentricity, no moment interaction, no PM curve. TMS Eq 8-22 valid for h_eff/r ≤ 99 only. All dimensions in mm; stresses/strengths in MPa; forces in kN.

## Input schema

```json
{
  "type": "object",
  "required": [
    "pier_width_mm",
    "pier_thickness_mm",
    "height_h_mm",
    "material",
    "f_prime_MPa",
    "end_conditions",
    "P_factored_kN"
  ],
  "properties": {
    "pier_width_mm": {
      "type": "number",
      "description": "Width of the pier cross-section in mm (in-plane dimension). Must be > 0."
    },
    "pier_thickness_mm": {
      "type": "number",
      "description": "Thickness of the pier cross-section in mm (out-of-plane dimension). Must be > 0."
    },
    "height_h_mm": {
      "type": "number",
      "description": "Clear unsupported height of the pier in mm. Must be > 0. Combined with k to give h_eff = k\u00b7h."
    },
    "material": {
      "type": "string",
      "enum": [
        "clay_masonry",
        "concrete_masonry",
        "reinforced_concrete"
      ],
      "description": "Material type governing the capacity formula. 'clay_masonry' or 'concrete_masonry' \u2192 TMS 402-22 \u00a78.3. 'reinforced_concrete' \u2192 ACI 318-19 \u00a722.4.2.2."
    },
    "f_prime_MPa": {
      "type": "number",
      "description": "Specified compressive strength in MPa. For masonry: net f'm. For RC: f'c (cylinder strength). Must be > 0."
    },
    "As_total_mm2": {
      "type": "number",
      "description": "Total longitudinal reinforcement area in mm\u00b2. Set to 0 for unreinforced masonry. Required for reinforced_concrete. Default 0.0."
    },
    "fy_MPa": {
      "type": "number",
      "description": "Yield strength of reinforcing steel in MPa (e.g. 420). Required for reinforced_concrete. Default 420.0."
    },
    "end_conditions": {
      "type": "string",
      "enum": [
        "fixed_fixed",
        "pin_pin",
        "fixed_pin",
        "cantilever"
      ],
      "description": "Boundary conditions at pier ends. fixed_fixed \u2192 k=0.5 (both ends restrained against rotation). pin_pin \u2192 k=1.0 (both ends pinned, default for typical piers). fixed_pin \u2192 k=0.7 (one fixed, one pinned). cantilever \u2192 k=2.0 (fixed base, free top)."
    },
    "P_factored_kN": {
      "type": "number",
      "description": "Factored axial compressive demand Pu in kN. Must be \u2265 0."
    },
    "phi": {
      "type": "number",
      "description": "Strength-reduction factor \u03c6. Default 0.65 (compression-controlled, TMS 402-22 \u00a79.3 / ACI Table 21.2.2). Must be in (0, 1]."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_pier_axial",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
