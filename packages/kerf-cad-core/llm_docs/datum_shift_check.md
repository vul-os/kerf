# gdt_compute_datum_shift

*Module: `kerf_cad_core.gdt.datum_shift_check` · Domain: cad*

## Description

Compute ASME Y14.5-2018 datum shift (bonus tolerance) for a datum feature of size referenced in a Datum Reference Frame (DRF) with an MMC or LMC material condition modifier.

Datum shift (§4.5 + §7.3.5) is the extra tolerance available to the toleranced feature when the datum feature departs from its MMC or LMC boundary:
  MMC modifier: shift = |measured_size - mmc_size|
  LMC modifier: shift = |measured_size - lmc_size|
  RFS modifier: shift = 0 (no bonus regardless of departure)

total_available_tolerance = base_position_tolerance + bonus_shift

material_condition_modifier options: MMC | LMC | RFS

Returns {datum_letter, base_tolerance_zone_mm, bonus_shift_mm, total_available_tolerance_mm, shift_allowed, code_section, honest_caveat}.

HONEST FLAG: per-datum shift only — multi-datum DRF cascade interactions (secondary shift constrained by primary fixation, §4.11.4) are computed datum-by-datum; composite frame validation (§10.5.2 PLTZF/FRTZF) is separate (use gdt_validate_composite_frame).

## Input schema

```json
{
  "type": "object",
  "properties": {
    "datum_letter": {
      "type": "string",
      "description": "Datum identifier letter, e.g. 'A', 'B', 'C'."
    },
    "mmc_size_mm": {
      "type": "number",
      "description": "Maximum Material Condition size in mm (> 0). For a hole: smallest acceptable diameter. For a shaft: largest acceptable diameter."
    },
    "lmc_size_mm": {
      "type": "number",
      "description": "Least Material Condition size in mm (> 0). For a hole: largest acceptable diameter. For a shaft: smallest acceptable diameter."
    },
    "measured_size_mm": {
      "type": "number",
      "description": "Actual measured mating size of the datum feature (mm, > 0)."
    },
    "material_condition_modifier": {
      "type": "string",
      "enum": [
        "MMC",
        "LMC",
        "RFS"
      ],
      "description": "Material condition modifier on the datum feature reference. MMC: bonus when feature departs from MMC (most common for holes). LMC: bonus when feature departs from LMC (inner-boundary protection). RFS: no datum shift (zero bonus, always)."
    },
    "base_position_tolerance_mm": {
      "type": "number",
      "description": "Stated position (or other geometric) tolerance from the feature control frame (mm, > 0)."
    }
  },
  "required": [
    "datum_letter",
    "mmc_size_mm",
    "lmc_size_mm",
    "measured_size_mm",
    "material_condition_modifier",
    "base_position_tolerance_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="gdt_compute_datum_shift",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
