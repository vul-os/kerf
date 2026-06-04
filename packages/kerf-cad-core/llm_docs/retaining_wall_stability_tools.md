# arch_check_retaining_wall_stability

*Module: `kerf_cad_core.arch.retaining_wall_stability_tools` · Domain: cad*

## Description

Check overturning, sliding, and bearing stability of a cantilevered concrete retaining wall under Rankine active earth pressure (Bowles 'Foundation Engineering' 5e §12.3; Das 'Principles of Geotechnical Engineering' §13).

Earth pressure:
  Ka = tan²(45 − φ/2)
  Pa = 0.5·γ_s·H²·Ka  (horizontal resultant, acts at H/3)

Stability factors of safety:
  FoS_overturning = ΣM_resist / ΣM_overt  ≥ 2.0
  FoS_sliding     = ΣW·tan(δ) / Pa         ≥ 1.5
  FoS_bearing     = q_a / q_max             ≥ 3.0
    where q_max = (ΣW/B)·(1 + 6e/B), e = B/2 − x̄

SCOPE LIMITATIONS:
  - Rankine active pressure only (level backfill, cohesionless)
  - NO surcharge load
  - NO seismic (Mononobe-Okabe) component
  - NO passive resistance from soil in front of toe
  - NO hydrostatic pressure (free-draining assumed)

All inputs in SI: metres, kN/m³, kPa, degrees.
Returns Ka, Pa_kN_per_m, FoS_overturning, FoS_sliding, q_max_kPa, FoS_bearing, all_adequate, governing_failure_mode, honest_caveat.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "wall_height_H_m": {
      "type": "number",
      "description": "Total retained height H from top of stem to bottom of base footing (m). Includes the base slab thickness. Must be > 0."
    },
    "stem_thickness_t_m": {
      "type": "number",
      "description": "Thickness of the vertical concrete stem t (m). Must be > 0. Typical range 0.2\u20130.5 m."
    },
    "base_width_B_m": {
      "type": "number",
      "description": "Total base width B = toe_length + stem_thickness + heel_length (m). Must equal the sum of the three components. Typical range: 0.4H\u20130.7H."
    },
    "base_thickness_h_m": {
      "type": "number",
      "description": "Thickness of the horizontal base slab h (m). Must be > 0 and < H. Typical range 0.1H\u20130.15H."
    },
    "heel_length_m": {
      "type": "number",
      "description": "Heel length \u2014 distance from back face of stem to the back edge of the base slab (soil side), in metres. Must be \u2265 0. Longer heel increases overturning resistance."
    },
    "toe_length_m": {
      "type": "number",
      "description": "Toe length \u2014 distance from front face of stem to the front edge of the base slab, in metres. Must be \u2265 0. Typical: 0.1\u20130.25 m."
    },
    "concrete_unit_weight_kN_m3": {
      "type": "number",
      "description": "Unit weight of concrete \u03b3_c (kN/m\u00b3). Default 24.0. Normal concrete: 24 kN/m\u00b3; lightweight: 16\u201320 kN/m\u00b3."
    },
    "soil_unit_weight_kN_m3": {
      "type": "number",
      "description": "Moist unit weight of backfill \u03b3_s (kN/m\u00b3). Must be > 0. Typical: loose sand 16\u201318; dense sand 18\u201320; gravel 18\u201320."
    },
    "friction_angle_phi_deg": {
      "type": "number",
      "description": "Effective friction angle of backfill \u03c6 (degrees). Range (0, 50]. Typical: loose sand 28\u201332\u00b0; medium sand 30\u201335\u00b0; dense sand/gravel 35\u201342\u00b0."
    },
    "base_friction_delta_deg": {
      "type": "number",
      "description": "Friction angle at the concrete base\u2013soil interface \u03b4 (degrees). Typically 0.5\u03c6 to 0.67\u03c6 for concrete on soil; use \u03c6 for rough concrete poured on gravel. Must be in [0, \u03c6]."
    },
    "allowable_bearing_q_a_kPa": {
      "type": "number",
      "description": "Allowable bearing capacity of the founding soil q_a (kPa). Must come from a geotechnical investigation. Typical: soft clay 50\u2013100; medium clay 100\u2013200; dense sand 200\u2013400; gravel 300\u2013600; rock > 1000. Must be > 0."
    }
  },
  "required": [
    "wall_height_H_m",
    "stem_thickness_t_m",
    "base_width_B_m",
    "base_thickness_h_m",
    "heel_length_m",
    "toe_length_m",
    "soil_unit_weight_kN_m3",
    "friction_angle_phi_deg",
    "base_friction_delta_deg",
    "allowable_bearing_q_a_kPa"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_retaining_wall_stability",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
