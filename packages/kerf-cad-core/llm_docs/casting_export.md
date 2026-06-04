# jewelry_casting_export

*Module: `kerf_cad_core.jewelry.casting_export` · Domain: cad*

## Description

Generate a casting-ready production export summary for a jewelry piece.

Returns a casting summary with:
  - Per-alloy shrinkage compensation percentage
  - Sprue count and gate location recommendations
  - Build orientation for the investment flask
  - Wax support strategy
  - Estimated net metal weight and total pour weight (with sprue overhead)
  - Gemstone exclusion list (gems are removed from cast; metal body only)

Alloy keys (same as jewelry_metal_cost):
  Gold:      10k_yellow, 14k_yellow, 18k_yellow, 22k_yellow, 24k_yellow
             10k_white,  14k_white,  18k_white,  22k_white
             10k_rose,   14k_rose,   18k_rose,   22k_rose
  Platinum:  platinum_950, platinum_900
  Palladium: palladium_950, palladium_500
  Silver:    sterling_925, fine_silver, argentium_935
  Other:     titanium, brass, bronze

Shrinkage per alloy (approximate industry midpoints):
  18k yellow gold: 1.25%  |  18k white gold: 1.30%
  Platinum 950:    1.80%  |  Sterling 925:   1.40%

Sprue / support strategy is heuristic based on piece volume:
  <500 mm³: 1 sprue, no support
  500–2000 mm³: 1 sprue, minimal wax
  2000–5000 mm³: 2 sprues, wax supports
  >5000 mm³: 3 sprues, full wax tree

volume_mm3 is the metal-body volume only (gems excluded). Use the volume from a CAD volume query (GProp_GProps.Mass() in mm units).

## Input schema

```json
{
  "type": "object",
  "properties": {
    "alloy": {
      "type": "string",
      "description": "Alloy key for the casting metal. See tool description for full list. Example: '18k_yellow', 'platinum_950', 'sterling_925'."
    },
    "volume_mm3": {
      "type": "number",
      "description": "Volume of the metal body in mm\u00b3 (gems excluded). From GProp_GProps.Mass() in Kerf/OCCT mm model units."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Minimum wall thickness of the piece in mm. Used for thin-wall warnings (< 0.6 mm). Default 1.0."
    },
    "gemstone_refs": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Optional list of gemstone names or node IDs being excluded from the casting export (gems are not cast). Stored in summary for traceability."
    }
  },
  "required": [
    "alloy",
    "volume_mm3"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="jewelry_casting_export",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
