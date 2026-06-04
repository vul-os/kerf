# civil_generate_corridor_sheets

*Module: `kerf_cad_core.civil.corridor_sheet_tools` · Domain: cad*

## Description

Generate plan + profile + cross-section sheets for a road/rail corridor and export them as a multi-sheet DXF file (AutoCAD R12/R14 ASCII).

Output sheet types
------------------
  Plan view        — horizontal alignment centreline (layer CIVIL-PLAN-ALIGN), edge strings at half_carriageway_m offset (CIVIL-PLAN-EDGE), station tick marks (CIVIL-PLAN-STATION).
  Profile view     — finished-grade polyline (CIVIL-PROFILE-FG), existing-ground polyline (CIVIL-PROFILE-EG), grade stubs (CIVIL-PROFILE-GRADE).
  Cross-sections   — one per station_interval_m: carriageway (CIVIL-XS-ROAD), cut/fill side-slopes (CIVIL-XS-SLOPE), existing ground stub (CIVIL-XS-GROUND).

All DXF coordinates are in metres.  No BLOCKS or PAPER_SPACE section; everything is in MODEL space so any DXF reader (QCAD, LibreCAD, AutoCAD, BricsCAD) can open the file directly.

Limitations
-----------
  - Existing-ground line is synthetic (sinusoidal).  Replace with     surveyed DTM points for production drawings.
  - Vertical alignment uses linear PVI interpolation; parabolic vertical     curves are not applied inside the sheet generator (use     align_vertical to verify K-values separately).
  - Text annotations / title blocks are not written (DXF MTEXT/TEXT     not yet implemented).

Returns {ok, dxf_path, num_sheets, stations_drawn, total_length_m, honest_caveat}. Never raises; errors returned as {ok: false, errors: [...]}.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "corridor_name": {
      "type": "string",
      "description": "Name of the corridor (used in DXF layer prefix)."
    },
    "start_station_m": {
      "type": "number",
      "description": "Start station of the corridor in metres.  Default: 0.0."
    },
    "end_station_m": {
      "type": "number",
      "description": "End station of the corridor in metres (must be > start_station_m)."
    },
    "station_interval_m": {
      "type": "number",
      "description": "Interval between cross-section stations (metres).  Default: 20.0.  Smaller = more cross-sections."
    },
    "scale_horizontal": {
      "type": "number",
      "description": "Nominal horizontal plot scale factor (e.g. 200 \u2192 1:200).  Controls sheet viewport size.  Default: 200."
    },
    "scale_vertical": {
      "type": "number",
      "description": "Nominal vertical scale factor for the profile view (e.g. 50 \u2192 1:50).  Informational only.  Default: 50."
    },
    "half_carriageway_m": {
      "type": "number",
      "description": "Half-width of the carriageway from centreline (metres).  Default: 3.65 m (one AASHTO/TRH4 lane)."
    },
    "cut_slope_ratio": {
      "type": "number",
      "description": "Cut side-slope ratio H:V (horizontal run per 1 m vertical).  Default: 1.5 (1.5H:1V)."
    },
    "fill_slope_ratio": {
      "type": "number",
      "description": "Fill side-slope ratio H:V.  Default: 2.0 (2H:1V)."
    },
    "design_elevation_at_start_m": {
      "type": "number",
      "description": "Design surface elevation at the start station (metres).  Used when no PVI data is supplied.  Default: 100.0."
    },
    "horizontal_waypoints": {
      "type": "array",
      "description": "Horizontal alignment centreline as [[easting, northing], ...] in metres.  Leave empty or omit for a straight alignment along the +X axis.",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2
      }
    },
    "pvi_stations": {
      "type": "array",
      "description": "Stations of vertical alignment PVI points (metres), in ascending order.",
      "items": {
        "type": "number"
      }
    },
    "pvi_elevations": {
      "type": "array",
      "description": "Elevations at each PVI point (metres).  Must have the same length as pvi_stations.",
      "items": {
        "type": "number"
      }
    },
    "output_path": {
      "type": "string",
      "description": "Full path for the output DXF file.  If empty or omitted, a temporary file is created and its path is returned."
    }
  },
  "required": [
    "end_station_m"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="civil_generate_corridor_sheets",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
