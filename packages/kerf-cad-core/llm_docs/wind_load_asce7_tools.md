# arch_compute_wind_load

*Module: `kerf_cad_core.arch.wind_load_asce7_tools` · Domain: cad*

## Description

Compute design wind pressure on a building wall per ASCE 7-22 §26–27 Directional Procedure (Main Wind Force-Resisting System — MWFRS).

Calculates:
  • Kz — velocity pressure exposure coefficient (Table 26.10-1)
  • qz — velocity pressure at mean roof height: 0.00256·Kz·Kzt·Kd·V² (psf)
  • Cp — external pressure coefficients: windward=+0.8, leeward per Fig 27.4-1
  • p_windward = qz·G·Cp_windward  (G=0.85 rigid, §26.11.1)
  • p_leeward  = qz·G·|Cp_leeward|
  • total_drag = qz·G·(Cp_windward − Cp_leeward)

Exposure constants (Table 26.10-1):
  B: α=7.0, zg=1200 ft (urban/suburban)
  C: α=9.5, zg=900 ft  (open terrain — most common)
  D: α=11.5, zg=700 ft (coastal/water)

Scope: rigid buildings only; enclosed/partially-enclosed/open for documentation. NOT computed: internal pressure GCpi (§26.13), parapet loads (§27.7), roof pressures, tornado loads (§32), Envelope Procedure (§28).

Returns qz_psf, Kz, Cp_windward, Cp_leeward, p_windward_psf, p_leeward_psf, total_drag_psf, L_over_B, code_section, honest_caveat.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "V_basic_mph": {
      "type": "number",
      "description": "Basic wind speed V (mph) from ASCE 7-22 Fig 26.5-1 (Risk Category II) or Fig 26.5-2A/B/C for other risk categories. Must be > 0. Typical US: 85\u2013200 mph. Select the map for the correct risk category."
    },
    "exposure_category": {
      "type": "string",
      "enum": [
        "B",
        "C",
        "D"
      ],
      "description": "Surface roughness / exposure per ASCE 7-22 \u00a726.7: 'B' = urban, suburban, wooded (z0\u22481 ft); 'C' = open terrain, scattered obstructions < 30 ft (z0\u22480.07 ft); 'D' = flat, unobstructed areas and water surfaces (z0\u22480.016 ft)."
    },
    "mean_height_h_ft": {
      "type": "number",
      "description": "Mean roof height h (ft). For flat roofs use eave height; for gable/hip roofs use mid-slope height. Must be > 0."
    },
    "length_ft": {
      "type": "number",
      "description": "Horizontal building dimension parallel to wind direction L (ft). Used for L/B ratio to determine leeward Cp. Must be > 0."
    },
    "width_ft": {
      "type": "number",
      "description": "Horizontal building dimension perpendicular to wind direction B (ft). Must be > 0."
    },
    "K_zt": {
      "type": "number",
      "description": "Topographic factor per ASCE 7-22 \u00a726.8 and Fig 26.8-1. Default = 1.0 (flat terrain). Set > 1.0 for hills, ridges, or escarpments."
    },
    "risk_category": {
      "type": "string",
      "enum": [
        "I",
        "II",
        "III",
        "IV"
      ],
      "description": "Risk Category per ASCE 7-22 \u00a71.5 / Table 1.5-1. Used for documentation only \u2014 V_basic_mph must already be from the correct risk-category wind speed map."
    },
    "enclosure": {
      "type": "string",
      "enum": [
        "enclosed",
        "partially_enclosed",
        "open"
      ],
      "description": "Building enclosure classification per \u00a726.12. Used for documentation; internal pressure GCpi (\u00a726.13) is NOT computed in this tool."
    }
  },
  "required": [
    "V_basic_mph",
    "exposure_category",
    "mean_height_h_ft",
    "length_ft",
    "width_ft"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_compute_wind_load",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
