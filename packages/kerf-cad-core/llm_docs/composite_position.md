# gdt_check_composite_position

*Module: `kerf_cad_core.gdt.composite_position` · Domain: cad*

## Description

Evaluate composite positional tolerance compliance for a feature pattern per ASME Y14.5-2018 §10.5 (Composite Position).

Two independent tolerance zones are evaluated:
  PLTZF (upper frame, §10.5.1): each feature deviation from nominal ≤ upper_pltzf_tolerance_mm (diametral). Governs location relative to the full datum reference frame (datums_pltzf e.g. [A, B, C]).
  FRTZF (lower frame, §10.5.1): measured pattern centroid-shifted to align with nominal pattern; residual inter-feature deviation ≤ lower_frtzf_tolerance_mm (diametral). Governs pattern spacing/orientation relative to orientation-only datums (datums_frtzf e.g. [A]).

Both tolerances are diametral (total zone width). lower_frtzf must be ≤ upper_pltzf per §10.5.1 Note 2.

With mmc_modifier=true: bonus = max(0, feature_size_mm − mmc_size_mm) is added to each feature's effective tolerance per §4.5.

Returns: pltzf_violations, frtzf_violations, overall_pass, max_pltzf_deviation_mm, max_frtzf_deviation_mm, pltzf_centroid_shift_mm, honest_caveat.

HONEST FLAG: positional tolerance only (not orientation). FRTZF uses centroid translation only — no 6-DOF rigid-body registration. Datum simulator computation not performed.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "features": {
      "type": "array",
      "description": "Feature points in the pattern. Each has nominal and measured 3-D positions (x, y, z) in mm.",
      "minItems": 1,
      "items": {
        "type": "object",
        "properties": {
          "feature_id": {
            "type": "string",
            "description": "Unique identifier, e.g. 'H1'."
          },
          "nominal_xyz_mm": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "description": "Nominal [x, y, z] position in mm."
          },
          "measured_xyz_mm": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "description": "Measured [x, y, z] position in mm."
          },
          "feature_size_mm": {
            "type": "number",
            "description": "Measured feature size (e.g. hole diameter) in mm."
          },
          "mmc_size_mm": {
            "type": [
              "number",
              "null"
            ],
            "description": "MMC size for bonus calc. Hole at MMC = smallest diameter. Null disables bonus."
          }
        },
        "required": [
          "feature_id",
          "nominal_xyz_mm",
          "measured_xyz_mm",
          "feature_size_mm"
        ]
      }
    },
    "upper_pltzf_tolerance_mm": {
      "type": "number",
      "description": "PLTZF diametral positional tolerance in mm (upper frame \u2014 controls pattern location vs. full datum frame)."
    },
    "lower_frtzf_tolerance_mm": {
      "type": "number",
      "description": "FRTZF diametral positional tolerance in mm (lower frame \u2014 controls inter-feature spacing). Must be \u2264 upper_pltzf_tolerance_mm."
    },
    "datums_pltzf": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "PLTZF datum reference letters, e.g. ['A','B','C']."
    },
    "datums_frtzf": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "FRTZF datum reference letters, e.g. ['A']."
    },
    "mmc_modifier": {
      "type": "boolean",
      "description": "Apply MMC bonus per \u00a74.5 using mmc_size_mm on each feature. Default false (RFS)."
    }
  },
  "required": [
    "features",
    "upper_pltzf_tolerance_mm",
    "lower_frtzf_tolerance_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="gdt_check_composite_position",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
