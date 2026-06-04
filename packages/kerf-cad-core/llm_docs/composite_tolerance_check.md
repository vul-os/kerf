# gdt_validate_composite_frame

*Module: `kerf_cad_core.gdt.composite_tolerance_check` · Domain: cad*

## Description

Validate an ASME Y14.5-2018 composite (stacked) feature control frame consisting of a PLTZF (Pattern-Locating Tolerance Zone Framework) on top of one or more FRTZF (Feature-Relating Tolerance Zone Framework) segments.

Rules checked (§10.5.2 Composite Position + §11.6 Composite Profile):
  R1  All segments share the same geometric symbol (position / profile_surface / profile_line).
  R2  Each lower segment tolerance ≤ the segment above it (FRTZF tol ≤ PLTZF tol, §10.5.1 Note 2).
  R3  Lower segment datum_refs ⊆ upper segment datum_refs — no new datums allowed below the PLTZF (§10.5.1(b)).

symbol options: position | profile_surface | profile_line
material_condition options: MMC | LMC | RFS (default RFS)

Returns {valid, violations, standard_section, honest_caveat}.
HONEST FLAG: validates frame structure only — does not verify inspection measurement data against the tolerance zones.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "feature_id": {
      "type": "string",
      "description": "Identifier for the feature being toleranced."
    },
    "segments": {
      "type": "array",
      "description": "Ordered list of composite frame segments, top to bottom. Index 0 = PLTZF, index 1 = FRTZF, index 2+ = additional refinement segments (multi-tier). Minimum 2 segments.",
      "items": {
        "type": "object",
        "properties": {
          "symbol": {
            "type": "string",
            "enum": [
              "position",
              "profile_surface",
              "profile_line"
            ],
            "description": "Geometric characteristic (same for all segments)."
          },
          "tol_value_mm": {
            "type": "number",
            "description": "Tolerance zone size in mm (> 0)."
          },
          "datum_refs": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "Ordered datum reference letters (e.g. ['A','B','C']). Lower segments must be a subset of the segment above."
          },
          "material_condition": {
            "type": "string",
            "enum": [
              "MMC",
              "LMC",
              "RFS"
            ],
            "description": "Material condition modifier. Default RFS."
          }
        },
        "required": [
          "symbol",
          "tol_value_mm"
        ]
      },
      "minItems": 2
    }
  },
  "required": [
    "feature_id",
    "segments"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="gdt_validate_composite_frame",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
