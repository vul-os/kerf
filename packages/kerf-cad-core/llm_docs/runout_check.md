# gdt_check_runout

*Module: `kerf_cad_core.gdt.runout_check` · Domain: cad*

## Description

Verify circular or total runout tolerance compliance for a rotational feature per ASME Y14.5-2018 §13 and ISO 1101:2017 §18.

runout_type options:
  'circular' (§13.2 / ISO §18.3) — checks each axial cross-section independently; compliant when FIM at each section ≤ tolerance.
  'total'    (§13.3 / ISO §18.4) — checks entire surface simultaneously; compliant when max(R) - min(R) over ALL points ≤ tolerance.

Each inspection_point requires:
  theta_deg            — angular position (degrees)
  axial_z_mm           — axial position along datum axis (mm)
  radius_measured_mm   — measured radius from datum axis (mm, > 0)

Returns {max_runout_mm, mean_radius_mm, fom, compliant, per_section_runout, honest_caveat}.

fom (Figure of Merit) = max_runout / tolerance; fom < 1.0 = pass.

HONEST FLAG: ideal datum axis assumed — radii must be pre-computed from a known datum axis. Chebyshev-optimal axis fit (ASME B89.3.1 / ISO 12181-1 §4.3) is not performed. Axial deviation for face runout surfaces (ASME §13.3 full definition) is not checked.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "feature_id": {
      "type": "string",
      "description": "Feature identifier, e.g. 'shaft-OD', 'bore-1'."
    },
    "runout_tolerance_mm": {
      "type": "number",
      "description": "Runout tolerance from the feature control frame (mm, > 0)."
    },
    "runout_type": {
      "type": "string",
      "enum": [
        "circular",
        "total"
      ],
      "description": "'circular' \u2014 per cross-section FIM check (ASME \u00a713.2); 'total' \u2014 full-surface FIM check (ASME \u00a713.3)."
    },
    "nominal_radius_mm": {
      "type": "number",
      "description": "Nominal design radius (mm, > 0). Used for reference reporting."
    },
    "inspection_points": {
      "type": "array",
      "description": "List of measured inspection points (>= 2 required).",
      "items": {
        "type": "object",
        "properties": {
          "theta_deg": {
            "type": "number",
            "description": "Angular position in degrees [0, 360)."
          },
          "axial_z_mm": {
            "type": "number",
            "description": "Axial position along datum axis (mm)."
          },
          "radius_measured_mm": {
            "type": "number",
            "description": "Measured radius from datum axis (mm, > 0)."
          }
        },
        "required": [
          "theta_deg",
          "axial_z_mm",
          "radius_measured_mm"
        ]
      },
      "minItems": 2
    }
  },
  "required": [
    "feature_id",
    "runout_tolerance_mm",
    "runout_type",
    "nominal_radius_mm",
    "inspection_points"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="gdt_check_runout",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
