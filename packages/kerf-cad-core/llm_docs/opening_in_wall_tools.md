# arch_check_opening_in_wall

*Module: `kerf_cad_core.arch.opening_in_wall_tools` · Domain: cad*

## Description

Check that a wall opening (door or window) satisfies structural code requirements: tributary load redistribution to jamb piers (IBC §2308.4 prescriptive intent), jamb axial capacity (ACI 318-19 §11.5.3.1 or TMS 402-22 §8.3), and lintel/header bending moment and deflection limits (AISC Table 3-23 / ACI 318-19 §9 / TMS 402-22 §5). 

Supported materials: 'concrete' (RC pier, ACI §11.5.3.1), 'masonry' (TMS 402-22 §8.3), 'wood_frame' (simplified bearing check). 

Tributary width per jamb = opening_width/2 + jamb_width/2 + header_above_height. Factored jamb load = 1.2 × axial_load × trib_width + 0.5 × lateral × opening_area. 

Returns: tributary_load_on_jamb_kN, jamb_axial_capacity_kN, jamb_dcr, lintel_moment_dcr, lintel_deflection_mm, all_adequate, governing_check, honest_caveat. 

SCOPE: Simplified tributary method — full 2-D stress-concentration analysis around opening corners NOT modelled. Wood-frame: NDS 2018 Cp factor NOT computed. Lateral load combinations must be checked separately.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "wall_height_m": {
      "type": "number",
      "description": "Total clear storey height of the wall in metres. Must be > 0. Example: 3.0"
    },
    "wall_thickness_m": {
      "type": "number",
      "description": "Wall thickness in metres. Must be > 0. Example: 0.200 for 200mm CMU wall."
    },
    "opening_width_m": {
      "type": "number",
      "description": "Clear opening width in metres. Must be > 0. Example: 1.2 for a 1.2m window."
    },
    "opening_height_m": {
      "type": "number",
      "description": "Clear opening height in metres. Must be > 0 and < wall_height_m. Example: 1.5."
    },
    "header_above_opening_height_m": {
      "type": "number",
      "description": "Height of wall panel above the lintel up to the next structural element (floor slab, roof, bond beam) in metres. Used in tributary width and masonry arching action. Must be >= 0. Example: 1.0."
    },
    "lintel_depth_m": {
      "type": "number",
      "description": "Overall depth of the lintel/header cross-section in metres. Must be > 0. Example: 0.300 for a 300mm deep lintel."
    },
    "jamb_width_m": {
      "type": "number",
      "description": "Width of each jamb pier (measured along wall face) in metres. Must be > 0. Example: 0.400 for a 400mm jamb pier."
    },
    "material": {
      "type": "string",
      "enum": [
        "concrete",
        "masonry",
        "wood_frame"
      ],
      "description": "Wall/structural material. 'concrete' \u2192 ACI 318-19 \u00a711.5.3.1 jamb capacity; RC lintel check. 'masonry' \u2192 TMS 402-22 \u00a78.3 jamb capacity; RM lintel check. 'wood_frame' \u2192 simplified bearing area check; steel-proxy lintel check."
    },
    "f_prime_or_fy_MPa": {
      "type": "number",
      "description": "Material strength in MPa. Must be > 0. concrete \u2192 f'c (e.g. 25, 30 MPa). masonry \u2192 f'm (e.g. 10, 14, 20 MPa). wood_frame \u2192 Fc allowable compressive stress parallel to grain (e.g. 9 MPa for SPF #2)."
    },
    "applied_axial_kN_per_m": {
      "type": "number",
      "description": "Service axial load from above (gravity + superimposed) per unit length of wall (kN/m). Must be >= 0. Example: 30.0 kN/m for typical storey loading."
    },
    "applied_lateral_kN_per_m2": {
      "type": "number",
      "description": "Uniform lateral pressure on the wall face (kN/m\u00b2), e.g. wind or seismic equivalent uniform pressure. Must be >= 0. Example: 1.0 kN/m\u00b2 for wind."
    }
  },
  "required": [
    "wall_height_m",
    "wall_thickness_m",
    "opening_width_m",
    "opening_height_m",
    "header_above_opening_height_m",
    "lintel_depth_m",
    "jamb_width_m",
    "material",
    "f_prime_or_fy_MPa",
    "applied_axial_kN_per_m",
    "applied_lateral_kN_per_m2"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_opening_in_wall",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
