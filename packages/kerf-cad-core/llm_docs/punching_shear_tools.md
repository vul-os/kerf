# arch_check_punching_shear

*Module: `kerf_cad_core.arch.punching_shear_tools` · Domain: cad*

## Description

Check two-way (punching) shear capacity of a flat concrete slab around a column per ACI 318-19 §22.6 (no shear reinforcement).

Critical section: perimeter b_0 at d/2 from the column face (ACI 318-19 §22.6.4.1).

Concrete shear stress vc = min of ACI §22.6.5.2 equations:
  (a)  vc = 0.33 · λ · √f'c                        [basic]
  (b)  vc = 0.17 · (1 + 2/β_c) · λ · √f'c          [aspect-ratio]
  (c)  vc = 0.083 · (α_s · d/b_0 + 2) · λ · √f'c   [perimeter]

Design strength: φ·Vn = φ · vc · b_0 · d   (φ = 0.75 default)

Returns b_0_mm, vc_governing_MPa, phi_vc_kN, demand_capacity_ratio, adequate (bool), governing_eqn, and honest_caveat.

SCOPE: No shear reinforcement (Vs = 0). No unbalanced-moment interaction. No slab openings/re-entrant corners. No axial load effect on vc. √f'c cap at √69 MPa not auto-enforced. Slab edge/corner: set alpha_s=30 (edge) or 20 (corner). All inputs in mm and MPa; force in kN.

## Input schema

```json
{
  "type": "object",
  "required": [
    "column_size_mm",
    "slab_thickness_mm",
    "fc_MPa",
    "effective_depth_d_mm",
    "column_shape",
    "V_applied_kN"
  ],
  "properties": {
    "column_size_mm": {
      "type": "number",
      "description": "Column side dimension for square columns (mm), or diameter for circular columns, or short-side dimension for rectangular columns.  Must be > 0."
    },
    "slab_thickness_mm": {
      "type": "number",
      "description": "Overall slab thickness h (mm).  Must be > 0."
    },
    "fc_MPa": {
      "type": "number",
      "description": "Specified compressive strength f'c (MPa).  Must be > 0. ACI 318-19 \u00a722.6.5.1 caps \u221af'c at \u221a69 MPa \u2248 8.31 MPa for normalweight concrete \u2014 ensure f'c \u2264 69 MPa for code-compliant results."
    },
    "effective_depth_d_mm": {
      "type": "number",
      "description": "Effective slab depth d (mm) to the centroid of the tension reinforcement.  Must be > 0 and < slab_thickness_mm."
    },
    "column_shape": {
      "type": "string",
      "enum": [
        "square",
        "rectangular",
        "circular"
      ],
      "description": "'square' \u2014 equal-sided column (\u03b2_c = 1). 'rectangular' \u2014 requires column_width_b_mm (long side). 'circular' \u2014 b_0 = \u03c0\u00b7(diameter + d)."
    },
    "V_applied_kN": {
      "type": "number",
      "description": "Applied factored punching shear V_u (kN).  Must be \u2265 0."
    },
    "column_width_b_mm": {
      "type": "number",
      "description": "Long-side dimension of a rectangular column (mm). Required when column_shape == 'rectangular'. Must be \u2265 column_size_mm."
    },
    "alpha_s": {
      "type": "integer",
      "enum": [
        40,
        30,
        20
      ],
      "description": "ACI \u03b1_s location factor: 40 = interior column (default), 30 = edge column, 20 = corner column (ACI 318-19 \u00a722.6.5.2c)."
    },
    "lambda_factor": {
      "type": "number",
      "description": "Lightweight-concrete modification factor \u03bb per ACI 318-19 \u00a719.2.4.  Default 1.0 (normalweight). Use 0.75 for all-lightweight or 0.85 for sand-lightweight."
    },
    "phi": {
      "type": "number",
      "description": "ACI strength-reduction factor for shear. Default 0.75 per ACI 318-19 Table 21.2.1."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_punching_shear",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
