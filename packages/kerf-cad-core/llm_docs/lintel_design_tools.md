# arch_design_lintel

*Module: `kerf_cad_core.arch.lintel_design_tools` · Domain: cad*

## Description

Check a lintel over a wall opening for moment, shear, and deflection capacity. Supports three material types: steel (AISC Manual Table 3-23 + AISC 360-22 §F1/§G2), reinforced_concrete (ACI 318-19 §9), and reinforced_masonry (TMS 402-22 §5). 

Load model:
  • Superimposed UDL factored: w_u = 1.2·DL + 1.6·LL (ASCE 7-16 §2.3.1 combo 2).
  • Masonry arching action: when masonry_above_height ≥ L/2, only the 45° isoceles triangular load within the arching triangle is applied (TMS 402-22 Commentary §5.3.1; BIA TN-31B); otherwise full rectangular load.

Capacity:
  • Steel: solid-rectangle section approximation (S_x=b·h²/6). φ·Mn = 0.90·Fy·S_x; φ·Vn = 1.00·0.6·Fy·0.5·b·h.
  • RC: ρ_max=0.018 estimate; φ·Mn = 0.90·As·fy·(d−a/2); φ·Vn = 0.75·0.17·√f'c·b·d (no stirrups).
  • RM: ρ_max=0.010 estimate; φ·Mn = 0.90·As·fy·(d−a/2); φ·Vn = 0.80·A_n·√f'm/3.

Deflection limit: L/360 (floor_lintel=true) or L/240 (default, masonry/roof).

Returns M_max, V_max, delta_max, phi_Mn, phi_Vn, moment_dcr, shear_dcr, deflection_ok, adequate, and an honest caveat.

SCOPE: Simple span ONLY. No continuous-beam moment redistribution. Steel LTB not checked. RC/RM rebar layout estimated from ρ_max. Load combo 1.2D+1.6L only.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "opening_span_mm": {
      "type": "number",
      "description": "Clear span of the wall opening in mm. Must be > 0. Example: 1200 for a 1.2 m door opening."
    },
    "wall_thickness_mm": {
      "type": "number",
      "description": "Wall thickness in mm. Used for context; lintel_width_mm governs section capacity. Example: 230 mm for a standard CMU wall."
    },
    "material": {
      "type": "string",
      "enum": [
        "steel",
        "reinforced_concrete",
        "reinforced_masonry"
      ],
      "description": "Lintel material type. 'steel' \u2014 angle, channel, or wide-flange shape; fc_or_fy_MPa = Fy (yield stress). 'reinforced_concrete' \u2014 cast-in-place RC beam; fc_or_fy_MPa = f'c. 'reinforced_masonry' \u2014 grouted RM lintel; fc_or_fy_MPa = f'm."
    },
    "lintel_depth_mm": {
      "type": "number",
      "description": "Overall depth of the lintel cross-section in mm. Must be > 0. Steel: total section depth (e.g. 101.6 mm for L4\u00d74\u00d71/4). RC/RM: total beam depth including cover."
    },
    "lintel_width_mm": {
      "type": "number",
      "description": "Width of the lintel cross-section in mm. Must be > 0. Steel: flange width (or combined angle leg width). RC/RM: beam width (typically equals wall_thickness_mm). Example: 101.6 mm for L4\u00d74\u00d71/4 back-to-back, 230 mm for CMU RM lintel."
    },
    "fc_or_fy_MPa": {
      "type": "number",
      "description": "Material strength in MPa. Must be > 0. Steel \u2192 Fy: 250 (A36), 345 (A992). Reinforced concrete \u2192 f'c: 21, 28, 35 MPa. Reinforced masonry \u2192 f'm: 10, 14, 20 MPa."
    },
    "dead_load_kN_per_m": {
      "type": "number",
      "description": "Service dead load (superimposed, excluding masonry self-weight) in kN/m. Must be \u2265 0. Example: 5 kN/m for floor framing above."
    },
    "live_load_kN_per_m": {
      "type": "number",
      "description": "Service live load in kN/m. Must be \u2265 0. Example: 3 kN/m."
    },
    "masonry_above_height_mm": {
      "type": "number",
      "description": "Height of masonry above the lintel (to floor/beam/slab above) in mm. 0 \u2192 no masonry self-weight. > 0 \u2192 arching action applies per TMS 402-22 Commentary \u00a75.3.1: if h_masonry \u2265 L/2, 45\u00b0 triangular load only; if h_masonry < L/2, full rectangular UDL from masonry weight. Example: 2400 mm for a storey of masonry."
    },
    "floor_lintel": {
      "type": "boolean",
      "description": "True if the lintel supports a floor (deflection limit L/360). False (default) if supporting roof or masonry wall (limit L/240). Omit for the default L/240 limit."
    }
  },
  "required": [
    "opening_span_mm",
    "wall_thickness_mm",
    "material",
    "lintel_depth_mm",
    "lintel_width_mm",
    "fc_or_fy_MPa",
    "dead_load_kN_per_m",
    "live_load_kN_per_m",
    "masonry_above_height_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_design_lintel",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
