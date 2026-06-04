# arch_check_column_load

*Module: `kerf_cad_core.arch.column_load_check_tools` · Domain: cad*

## Description

Check whether a structural column satisfies its axial-load capacity under a given service (or factored) demand load. Supports two column types:
  • steel  — AISC 360-22 §E3 LRFD (flexural buckling, inelastic E3-2 and elastic Euler E3-3; φ_c = 0.90). Accepts W-shapes, HSS, or any section with gross area A_mm2 and min radius of gyration r_min_mm.
  • concrete — ACI 318-19 §22.4.2.2 (short tied column, φ·Pn = φ·0.80·[0.85·f'c·(Ag−Ast) + fy·Ast]; φ = 0.65 tied / 0.75 spiral).
Returns design strength φ·Pn (kN), demand/capacity ratio (DCR), governing mode, PASS/FAIL status, and an honest code-compliance caveat. All dimensions in millimetres; stresses/strengths in MPa; forces in kN.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "column_type": {
      "type": "string",
      "enum": [
        "steel",
        "concrete"
      ],
      "description": "'steel' \u2192 AISC 360-22 \u00a7E3 LRFD check. 'concrete' \u2192 ACI 318-19 \u00a722.4.2.2 short-column check."
    },
    "P_demand_kN": {
      "type": "number",
      "description": "Required (factored for LRFD) axial compressive demand in kN. Must be > 0."
    },
    "section_label": {
      "type": "string",
      "description": "[Steel only] Section label, e.g. 'W14x90' or 'HSS 152x152x9.5'. Used for reporting only."
    },
    "A_mm2": {
      "type": "number",
      "description": "[Steel only] Gross cross-sectional area in mm\u00b2."
    },
    "r_min_mm": {
      "type": "number",
      "description": "[Steel only] Minimum radius of gyration (weak axis) in mm. For W-shapes use ry; for HSS use the governing r."
    },
    "Fy_MPa": {
      "type": "number",
      "description": "[Steel only] Yield stress in MPa, e.g. 345 for A572 Gr 50."
    },
    "K": {
      "type": "number",
      "description": "[Steel only] Effective-length factor. Typical values: 1.0 (pin-pin), 0.7 (pin-fixed), 0.5 (fixed-fixed)."
    },
    "L_mm": {
      "type": "number",
      "description": "[Steel only] Unbraced column length in mm."
    },
    "E_MPa": {
      "type": "number",
      "description": "[Steel only] Elastic modulus in MPa. Default 200 000 MPa."
    },
    "A_g_mm2": {
      "type": "number",
      "description": "[Concrete only] Gross section area in mm\u00b2 (b \u00d7 h for rect; \u03c0 r\u00b2 for circ)."
    },
    "A_st_mm2": {
      "type": "number",
      "description": "[Concrete only] Total area of longitudinal rebar in mm\u00b2."
    },
    "fc_MPa": {
      "type": "number",
      "description": "[Concrete only] Specified concrete compressive strength f'c in MPa."
    },
    "fy_MPa": {
      "type": "number",
      "description": "[Concrete only] Rebar yield strength in MPa, e.g. 420."
    },
    "phi": {
      "type": "number",
      "description": "[Concrete only] Strength-reduction factor \u03c6. Default 0.65 (tied); use 0.75 for spiral-reinforced columns."
    }
  },
  "required": [
    "column_type",
    "P_demand_kN"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_column_load",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
