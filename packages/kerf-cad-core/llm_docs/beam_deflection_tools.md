# arch_compute_beam_deflection

*Module: `kerf_cad_core.arch.beam_deflection_tools` · Domain: cad*

## Description

Compute mid-span deflection δ_max, maximum bending moment M_max, and maximum shear V_max for a single-span structural beam using closed-form Euler-Bernoulli formulas (Roark 9e §8 + AISC Manual Table 3-23). 

Supported load cases:
  • simply_supported + point_center — point load P at mid-span; δ=PL³/(48EI), M=PL/4.
  • simply_supported + udl — uniform distributed load w over full span; δ=5wL⁴/(384EI), M=wL²/8.
  • cantilever + point_center — tip point load P; δ=PL³/(3EI), M=PL.
  • cantilever + udl — UDL over full cantilever; δ=wL⁴/(8EI), M=wL²/2.
  • fixed_fixed + udl — UDL on fully fixed beam; δ=wL⁴/(384EI), M=wL²/12 at supports.

All dimensions in millimetres; forces in N; stresses in MPa. Returns δ_max_mm, M_max_Nmm, V_max_N, deflection_location_mm, and an honest caveat listing scope limits. Scope: linear-elastic, small-deflection only. No buckling, no yield, no shear deformation, no partial-span loads.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "length_mm": {
      "type": "number",
      "description": "Clear span length in mm. Must be > 0. Example: 6000 for a 6 m span."
    },
    "E_MPa": {
      "type": "number",
      "description": "Elastic (Young's) modulus in MPa. Typical: 200 000 (steel), 70 000 (aluminium), 12 000\u201316 000 (LVL timber). Default 200 000 MPa."
    },
    "I_mm4": {
      "type": "number",
      "description": "Second moment of area about the bending axis in mm\u2074. Example W14x90: I_x = 270 000 000 mm\u2074 (AISC v15 Table 1-1, Ix = 999 in\u2074 \u2248 415 880 000 mm\u2074 \u2014 use section-specific value)."
    },
    "support_type": {
      "type": "string",
      "enum": [
        "simply_supported",
        "cantilever",
        "fixed_fixed"
      ],
      "description": "'simply_supported' \u2014 pin at each end. 'cantilever' \u2014 fully fixed at one end, free at the other. 'fixed_fixed' \u2014 encastr\u00e9 at both ends."
    },
    "load_type": {
      "type": "string",
      "enum": [
        "point_center",
        "udl"
      ],
      "description": "'point_center' \u2014 single point load P at mid-span (or free tip for cantilever). 'udl' \u2014 uniform distributed load w (N/mm) over full span."
    },
    "load_value": {
      "type": "number",
      "description": "Load magnitude. For point_center: total point load P in N. For udl: load intensity w in N/mm. Must be \u2265 0. Example: 100 000 N = 100 kN; 5 N/mm = 5 kN/m."
    }
  },
  "required": [
    "length_mm",
    "E_MPa",
    "I_mm4",
    "support_type",
    "load_type",
    "load_value"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_compute_beam_deflection",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
