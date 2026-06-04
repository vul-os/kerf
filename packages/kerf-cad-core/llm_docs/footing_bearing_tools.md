# arch_compute_bearing_capacity

*Module: `kerf_cad_core.arch.footing_bearing_tools` · Domain: cad*

## Description

Compute the ultimate and allowable bearing capacity of a shallow footing on cohesive/cohesionless soil using the Meyerhof (1963) general bearing capacity equation (Bowles 5e §4; Das 8e §3):

  q_ult = c·N_c·s_c·d_c + γ·Df·N_q·s_q·d_q + 0.5·γ·B·N_γ·s_γ·d_γ

Meyerhof N-factors:
  N_q   = e^(π·tanφ) · tan²(45+φ/2)
  N_c   = (N_q−1)·cotφ  (φ>0);  N_c = 5.14  (φ=0, Prandtl limit)
  N_γ   = (N_q−1)·tan(1.4φ)

Shape factors (Meyerhof 1963 / Bowles Table 4-4): strip=1.0; square/circular use B/L=1; rectangular interpolates.
Depth factors (Meyerhof 1963 / Bowles Table 4-4): increase with Df/B.

Returns q_ult_kPa, q_allow_kPa (= q_ult/FS), FS, N-factors, shape/depth factors, and an honest scope caveat.

SCOPE: Meyerhof (1963) shape+depth factors only. No Brinch Hansen rigidity index (I_r) correction, no inclined/eccentric loads, no seismic or liquefaction correction, no layered-soil punching. All inputs in SI units: metres, kPa, kN/m³.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "length_B_m": {
      "type": "number",
      "description": "Shorter plan dimension B in metres (width for rectangular; side for square; diameter for circular). Must be > 0."
    },
    "width_L_m": {
      "type": "number",
      "description": "Longer plan dimension L in metres. Must be \u2265 B. For square/circular footings may equal B. Ignored for strip footings (only B matters)."
    },
    "depth_Df_m": {
      "type": "number",
      "description": "Embedment depth Df in metres \u2014 measured from ground surface to bottom of footing. Must be > 0. Example: 1.5 for a footing 1.5 m below grade."
    },
    "shape": {
      "type": "string",
      "enum": [
        "strip",
        "square",
        "circular",
        "rectangular"
      ],
      "description": "'strip' \u2014 very long footing (L/B \u2192 \u221e); shape factors = 1. 'square' \u2014 equal sides (B = L). 'circular' \u2014 circular plan; diameter = B. 'rectangular' \u2014 general B \u00d7 L (B < L)."
    },
    "cohesion_c_kPa": {
      "type": "number",
      "description": "Cohesion c in kPa. Use 0 for purely frictional soils (sand). For saturated clay undrained (\u03c6=0) analysis provide c = Su (undrained shear strength). Must be \u2265 0."
    },
    "friction_angle_phi_deg": {
      "type": "number",
      "description": "Angle of internal friction \u03c6 in degrees. Range [0, 50]. Set 0 for undrained clay (\u03c6_u = 0). Typical: sand 30\u201338\u00b0; gravel 35\u201345\u00b0; clay 0\u201325\u00b0."
    },
    "unit_weight_kN_m3": {
      "type": "number",
      "description": "Moist (or effective) unit weight \u03b3 in kN/m\u00b3. Must be > 0. Typical: loose sand 16\u201318; dense sand 18\u201320; clay 17\u201321; submerged (\u03b3') \u2248 8\u201312."
    },
    "factor_of_safety": {
      "type": "number",
      "description": "Factor of safety FS for allowable capacity = q_ult / FS. Bowles \u00a74-8 recommends 2.5\u20133.0 for static loads. Default 3.0."
    },
    "depth_factor_kf": {
      "type": "number",
      "description": "Optional scale factor on the surcharge term \u03b3\u00b7Df. Default 1.0.  Use < 1 for partially submerged conditions or to match an effective-stress correction."
    }
  },
  "required": [
    "length_B_m",
    "width_L_m",
    "depth_Df_m",
    "shape",
    "cohesion_c_kPa",
    "friction_angle_phi_deg",
    "unit_weight_kN_m3"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_compute_bearing_capacity",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
