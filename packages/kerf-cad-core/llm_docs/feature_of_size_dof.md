# gdt_compute_fos_dof

*Module: `kerf_cad_core.gdt.feature_of_size_dof` · Domain: cad*

## Description

Enumerate the Degrees of Freedom (DOF) constrained vs released by a Feature of Size (FOS) + geometric tolerance combination, per ASME Y14.5-2018 §4.7 (Datum Reference Frame and DOF) + §7.3 (FOS).

Critical for inspection planning: identifies which translation (TX/TY/TZ) and rotation (RX/RY/RZ) DOFs are controlled by the tolerance, and which remain free (require additional datums or gauging to constrain).

feature_type options:
  cylinder   — external cylindrical shaft / pin (axis along Z assumed)
  hole       — internal cylindrical bore / hole (same DOF as cylinder)
  slot       — open slot (centre-plane FOS, §7.3)
  width      — synonym for slot
  planar_pair — two opposing flat surfaces (tab, boss — centre-plane FOS)
  sphere     — spherical feature (point FOS, §7.3)

tolerance_symbol options:
  position        — location of feature axis/centre-plane/point
  perpendicularity — 90° orientation to reference datum
  parallelism     — parallel orientation to reference datum
  angularity      — angular orientation to reference datum
  runout          — circular runout (§7.3.4 — couples axis + tilt)
  total_runout    — total runout (§7.3.5 — same DOF coupling)

DOF model (cylinder/hole — axis along Z):
  position         → constrains TX, TY
  perpendicularity / parallelism / angularity → constrains RX, RY
  runout / total_runout → constrains TX, TY, RX, RY

DOF model (slot/width/planar_pair):
  position → constrains TX
  orientation → constrains RX, RY

DOF model (sphere):
  position → constrains TX, TY, TZ
  orientation → constrains nothing (symmetric)

Returns {dof_constrained, dof_released, total_constrained, datum_required_count, code_section, honest_caveat}.

HONEST FLAG: feature-class lookup table only; does not handle complex pattern-of-feature compositions (§11.3) or PLTZF/FRTZF interactions (§10.5).

## Input schema

```json
{
  "type": "object",
  "properties": {
    "feature_type": {
      "type": "string",
      "enum": [
        "cylinder",
        "hole",
        "planar_pair",
        "slot",
        "sphere",
        "width"
      ],
      "description": "Geometric type of the feature of size: cylinder | hole | slot | sphere | planar_pair | width"
    },
    "tolerance_symbol": {
      "type": "string",
      "enum": [
        "angularity",
        "parallelism",
        "perpendicularity",
        "position",
        "runout",
        "total_runout"
      ],
      "description": "GD&T characteristic applied to this feature: position | perpendicularity | parallelism | angularity | runout | total_runout"
    }
  },
  "required": [
    "feature_type",
    "tolerance_symbol"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="gdt_compute_fos_dof",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
