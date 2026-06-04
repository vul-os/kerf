# gdt_check_circular_runout

*Module: `kerf_cad_core.gdt.runout_circular` · Domain: cad*

## Description

Evaluate circular (single-plane) runout tolerance compliance per ASME Y14.5-2018 §12.4.

Given a set of measured radial points around a feature at one or more axial positions, computes the FIM (Full Indicator Movement) = max(r) − min(r) for each cross-section, and pass/fail against the tolerance value.

Distinct from total runout (§12.5 / runout_check with 'total'): circular runout is evaluated independently at each axial cross-section without any axial sweep — the indicator remains fixed axially while the part makes one full revolution.

Input structure:
  measurements_per_cross_section: list of sections; each section is a list of {angular_position_deg, radial_measurement_mm, axial_position_mm} objects.  Minimum 3 measurements per section.
  tolerance_mm: circular runout tolerance from the feature control frame (mm).
  datum_axis_id: datum letter cited in the FCF (default 'A').

Returns: fim_per_section_mm, max_fim_mm, governing_axial_position_mm, pass_fail ('PASS'|'FAIL'), margin_mm (tolerance − max_fim; negative = violation), num_measurements_total, honest_caveat.

HONEST FLAG: measurements must be pre-computed radial distances from the TRUE datum axis. Datum simulator computation (minimum zone cylinder per ASME B89.3.1 / ISO 12181-1 §4.3) is NOT performed. Probe offset/cosine error corrections must be applied by the caller.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "measurements_per_cross_section": {
      "type": "array",
      "description": "List of cross-section measurement arrays. Each inner array represents one axial position. Minimum 1 section; minimum 3 measurements per section.",
      "minItems": 1,
      "items": {
        "type": "array",
        "description": "Measurements at a single axial position.",
        "minItems": 3,
        "items": {
          "type": "object",
          "properties": {
            "angular_position_deg": {
              "type": "number",
              "description": "Angular position in degrees [0, 360)."
            },
            "radial_measurement_mm": {
              "type": "number",
              "description": "Measured radius from datum axis (mm, > 0)."
            },
            "axial_position_mm": {
              "type": "number",
              "description": "Axial position where this measurement was taken (mm). All points in the same section should share this value. Default 0.0."
            }
          },
          "required": [
            "angular_position_deg",
            "radial_measurement_mm"
          ]
        }
      }
    },
    "tolerance_mm": {
      "type": "number",
      "description": "Circular runout tolerance from the feature control frame (mm, > 0). Pass when max_fim_mm \u2264 tolerance_mm."
    },
    "datum_axis_id": {
      "type": "string",
      "description": "Datum axis letter cited in the feature control frame, e.g. 'A'. Informational \u2014 used in the honest caveat only. Default 'A'."
    }
  },
  "required": [
    "measurements_per_cross_section",
    "tolerance_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="gdt_check_circular_runout",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
