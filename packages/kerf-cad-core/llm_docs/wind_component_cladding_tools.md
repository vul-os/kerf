# arch_compute_wind_cc_pressure

*Module: `kerf_cad_core.arch.wind_component_cladding_tools` · Domain: cad*

## Description

Compute design wind pressure on building components and cladding (C&C) per ASCE 7-22 §30.3 — Low-Rise Buildings (h ≤ 60 ft).

USE THIS (not arch_compute_wind_load) for: windows, doors, wall panels, roof cladding, parapets, curtain-wall glazing, coping, fascia.

Key differences from MWFRS §27 arch_compute_wind_load:
  • Higher localised GCp peak coefficients (edge vortex amplification)
  • No separate gust factor G — already embedded in GCp
  • GCpi = ±0.18 (enclosed) included in the design pressure
  • Pressure zones: Zone 1 interior < Zone 4 edge < Zone 5 corner (walls)
                    Zone 1 interior < Zone 2 edge < Zone 3 corner (roofs)

Design pressure:
  p_positive = qh·(GCp_positive + 0.18)  [net inward, toward surface]
  p_negative = qh·(GCp_negative − 0.18)  [net outward, suction]
  where qh = 0.00256·Kh·Kzt·Kd·V²  (Eq 26.10-1)

GCp effective-area reduction (Fig 30.3-2A/C): larger area → lower |GCp|.
  Wall anchors at 10 ft² and 500 ft²; roof anchors at 10 ft² and 100 ft².

GCp anchors (at 10 ft²):
  Zone_1_interior_wall: +0.9 / −1.1
  Zone_4_wall_edge:     +1.0 / −1.1
  Zone_5_corner_wall:   +1.0 / −1.4 (highest wall suction)
  Zone_1_roof_interior: +0.3 / −1.0
  Zone_2_roof_edge:     +0.3 / −1.8
  Zone_3_roof_corner:   +0.3 / −2.8 (highest roof suction)

SCOPE: Low-rise (h ≤ 60 ft), enclosed buildings only. NOT computed: partially-enclosed GCpi=±0.55 (§26.13.2), open-building GCpi=0, high-rise C&C (§30.4), parapets (§30.9), roof slopes >7° (Fig 30.3-2D). Minimum pressure ±16 psf (§30.2.2) must be checked manually.

Returns qz_psf, GCp_positive, GCp_negative, p_design_positive_psf, p_design_negative_psf, ASD_or_LRFD, code_section, honest_caveat.

## Input schema

```json
{
  "type": "object",
  "required": [
    "V_basic_mph",
    "exposure_category",
    "mean_height_h_ft",
    "length_ft",
    "width_ft",
    "area_ft2",
    "zone",
    "component_type"
  ],
  "properties": {
    "V_basic_mph": {
      "type": "number",
      "description": "Basic wind speed V (mph) from ASCE 7-22 Fig 26.5-1 (Risk Category II) or Fig 26.5-2A/B/C for other risk categories. Must be > 0."
    },
    "exposure_category": {
      "type": "string",
      "enum": [
        "B",
        "C",
        "D"
      ],
      "description": "Surface roughness / exposure per \u00a726.7: 'B'=urban/suburban; 'C'=open terrain; 'D'=coastal/water."
    },
    "mean_height_h_ft": {
      "type": "number",
      "description": "Mean roof height h (ft). Must be > 0. ASCE 7-22 \u00a730.3 applies only for h \u2264 60 ft."
    },
    "length_ft": {
      "type": "number",
      "description": "Building length parallel to wind direction (ft). Must be > 0."
    },
    "width_ft": {
      "type": "number",
      "description": "Building width perpendicular to wind direction (ft). Must be > 0."
    },
    "area_ft2": {
      "type": "number",
      "description": "Effective wind area of the component (ft\u00b2). For most elements this equals the tributary area. For one-way spanning members use span \u00d7 (span/3). Must be > 0."
    },
    "zone": {
      "type": "string",
      "enum": [
        "Zone_1_interior_wall",
        "Zone_4_wall_edge",
        "Zone_5_corner_wall",
        "Zone_1_roof_interior",
        "Zone_2_roof_edge",
        "Zone_3_roof_corner"
      ],
      "description": "Pressure zone per ASCE 7-22 \u00a730.3 / Fig 30.3-2: Zone_1_interior_wall = field of wall; Zone_4_wall_edge = edge strip; Zone_5_corner_wall = corner (highest wall suction); Zone_1_roof_interior = roof field; Zone_2_roof_edge = roof edge strip; Zone_3_roof_corner = roof corner (highest suction \u22122.8 at 10 ft\u00b2)."
    },
    "component_type": {
      "type": "string",
      "enum": [
        "wall",
        "roof"
      ],
      "description": "'wall' for windows, doors, wall panels (Fig 30.3-2A). 'roof' for roof cladding, skylights (Fig 30.3-2C, slope \u22647\u00b0)."
    },
    "K_zt": {
      "type": "number",
      "description": "Topographic factor per \u00a726.8. Default = 1.0 (flat terrain). Set > 1.0 for hills/ridges/escarpments."
    },
    "risk_category": {
      "type": "string",
      "enum": [
        "I",
        "II",
        "III",
        "IV"
      ],
      "description": "Risk Category per \u00a71.5 / Table 1.5-1 (documentation only). V_basic_mph must already be from the correct RC map."
    },
    "enclosure": {
      "type": "string",
      "enum": [
        "enclosed",
        "partially_enclosed",
        "open"
      ],
      "description": "Building enclosure classification per \u00a726.12. Only 'enclosed' (GCpi=\u00b10.18) is fully supported; 'partially_enclosed' and 'open' are NOT implemented \u2014 the call will succeed but GCpi=\u00b10.18 will be used with a warning embedded in honest_caveat."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_compute_wind_cc_pressure",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
