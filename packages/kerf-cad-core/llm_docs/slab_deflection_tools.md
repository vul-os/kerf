# arch_compute_slab_deflection

*Module: `kerf_cad_core.arch.slab_deflection_tools` · Domain: cad*

## Description

Compute center-point deflection δ_max and maximum bending moments M_xx / M_yy for a two-way rectangular concrete slab under uniform load (UDL) using Kirchhoff thin-plate theory.

Supported boundary conditions:
  • simply_supported — all four edges simply supported (AESS); α from Timoshenko Table 41.
  • fixed_fixed — all four edges fully fixed (AEFC); α from Timoshenko Table 42 (a/b=1 exact; others approximate).

Formula: δ_max = α · q · a⁴ / D
  a = shorter plan span [mm], D = E·h³/(12·(1−ν²)) [N·mm].

All plan dimensions in mm; load in kPa; stiffness D in N·mm; moments in N·mm/mm.
Returns delta_max_mm, M_max_xx_Nmm_per_mm, M_max_yy_Nmm_per_mm, plate_stiffness_D, and an honest_caveat.

SCOPE: linear-elastic Kirchhoff thin plate only. NOT included: shear deformation (Mindlin), plastic hinges, concrete cracking, creep/shrinkage, punching shear.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "length_a_mm": {
      "type": "number",
      "description": "Length of one side of the slab in mm. Must be > 0. Example: 5000 for a 5 m span."
    },
    "width_b_mm": {
      "type": "number",
      "description": "Length of the perpendicular side of the slab in mm. Must be > 0. The shorter dimension is automatically used as span a (Timoshenko convention)."
    },
    "thickness_h_mm": {
      "type": "number",
      "description": "Slab thickness h in mm. Must be > 0. Typical RC slab: 150\u2013300 mm."
    },
    "E_MPa": {
      "type": "number",
      "description": "Elastic modulus in MPa. Typical concrete: 25 000\u201335 000 MPa (C25/30: ~31 000; C30/37: ~33 000; C40/50: ~35 000). Default 30 000 MPa."
    },
    "poisson": {
      "type": "number",
      "description": "Poisson's ratio \u03bd. Concrete: 0.2 (Eurocode 2; ACI 318-19). Default 0.2."
    },
    "udl_kPa": {
      "type": "number",
      "description": "Uniform distributed load in kPa (kN/m\u00b2). Must be \u2265 0. Typical: self-weight + imposed = 5\u201315 kPa."
    },
    "edge_condition": {
      "type": "string",
      "enum": [
        "simply_supported",
        "fixed_fixed"
      ],
      "description": "'simply_supported' \u2014 all four edges pinned (rotation free). 'fixed_fixed' \u2014 all four edges encastr\u00e9 (zero rotation)."
    }
  },
  "required": [
    "length_a_mm",
    "width_b_mm",
    "thickness_h_mm",
    "udl_kPa",
    "edge_condition"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_compute_slab_deflection",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
