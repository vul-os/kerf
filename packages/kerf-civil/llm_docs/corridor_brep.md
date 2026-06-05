# Corridor B-rep and IFC Alignment — LLM Reference

Swept road corridor geometry: B-rep solid, volume estimate, and IFC export.

## Tool: `civil_corridor_brep`

Build a swept B-rep Body representing a straight road corridor.

```json
{
  "alignment_length_m": 300,
  "interval_m": 20,
  "lane_width_m": 3.65,
  "shoulder_width_m": 2.4,
  "lanes_each_side": 1,
  "crown_slope_pct": 2.0,
  "grade_pct": 0.0,
  "datum_elev_m": 10.0
}
```

Returns `face_count` and `shell_count`.

---

## Tool: `civil_corridor_volume`

Estimate pavement volume (m³) using prismatoid integration.

Assumes 0.5 m combined pavement + base course depth.

```json
{
  "alignment_length_m": 300,
  "lane_width_m": 3.65,
  "shoulder_width_m": 2.4
}
```

Returns `volume_m3`.

---

## Tool: `civil_corridor_ifc_alignment`

Return an `IfcAlignmentProduct` dict for IFC export.

```json
{
  "alignment_length_m": 300,
  "lane_width_m": 3.65,
  "shoulder_width_m": 2.4,
  "lanes_each_side": 1
}
```

Returns:

```json
{
  "ok": true,
  "ifc_dict": {
    "type": "IfcAlignmentProduct",
    "total_length_m": 300.0,
    "lane_width_m": 3.65,
    "shoulder_width_m": 2.4,
    "lanes_each_side": 1,
    "cut_slope_h_v": 2.0,
    "fill_slope_h_v": 2.0,
    "crown_slope_pct": 2.0
  }
}
```

Reference: ISO 16739-1:2018 — IfcAlignmentProduct; AASHTO Green Book.

---

## Tool: `civil_corridor_model`  ← **full template-driven corridor model**

Sweeps a parametric road cross-section assembly (point-coded: CL, edge-lane,
shoulder, optional ditch, cut/fill side-slopes to daylight) along a
horizontal + vertical alignment at regular station intervals.

Optionally ingests an existing terrain TIN to:
  • Find daylight points by intersecting cut/fill slopes against terrain.
  • Compute per-station cut/fill cross-section areas (shoelace formula).
  • Aggregate earthwork volumes (AASHTO average-end-area method).
  • Produce a mass-haul (Brückner) curve with swell factor.

### Example request (with terrain):

```json
{
  "alignment_length_m": 500,
  "interval_m": 20,
  "datum_elev_m": 98.0,
  "grade_pct": 1.5,
  "lane_width_m": 3.65,
  "shoulder_width_m": 2.4,
  "lanes_each_side": 1,
  "crown_slope_pct": 2.0,
  "shoulder_slope_pct": 5.0,
  "cut_slope": 2.0,
  "fill_slope": 2.0,
  "ditch_width_m": 1.0,
  "ditch_depth_m": 0.6,
  "swell_factor": 1.25,
  "terrain_points": [
    [-50, 0,   100], [50, 0,   100],
    [-50, 500, 100], [50, 500, 100]
  ]
}
```

### Returns:

```json
{
  "ok": true,
  "station_count": 27,
  "cross_sections": [
    {
      "station_m": 0.0,
      "cl_elev_m": 98.0,
      "cut_area_m2": 34.7,
      "fill_area_m2": 0.0,
      "points": [
        {"offset_m": -10.44, "elev_m": 100.0, "label": "daylight_left"},
        {"offset_m":  -7.05, "elev_m": 99.4,  "label": "ditch_left"},
        {"offset_m":  -6.05, "elev_m": 97.807,"label": "shoulder_left"},
        {"offset_m":  -3.65, "elev_m": 97.927,"label": "edge_lane_left"},
        {"offset_m":   0.0,  "elev_m": 98.0,  "label": "CL"},
        {"offset_m":   3.65, "elev_m": 97.927,"label": "edge_lane_right"},
        {"offset_m":   6.05, "elev_m": 97.807,"label": "shoulder_right"},
        {"offset_m":   7.05, "elev_m": 99.4,  "label": "ditch_right"},
        {"offset_m":  10.44, "elev_m": 100.0, "label": "daylight_right"}
      ]
    }
  ],
  "earthwork": {
    "total_cut_m3": 17360.0,
    "total_fill_m3": 0.0,
    "net_m3": -17360.0
  },
  "mass_haul": [
    {"station_m": 0,   "mass_ordinate_m3": 0,       "cut_vol_m3": 0,    "fill_vol_m3": 0},
    {"station_m": 20,  "mass_ordinate_m3": 694.7,   "cut_vol_m3": 694.7,"fill_vol_m3": 0}
  ],
  "corridor_strings": {
    "CL":            [[0,0,98.0], [0,20,98.3], ...],
    "daylight_right":[[10.44,0,100.0], ...]
  }
}
```

### Point codes

| Code            | Description                                      |
|-----------------|--------------------------------------------------|
| `CL`            | Centreline                                       |
| `edge_lane_*`   | Edge of travel lane (AASHTO §2.2)                |
| `shoulder_*`    | Edge of shoulder (AASHTO §2.3)                   |
| `ditch_*`       | Ditch bottom (only when ditch_width_m > 0)       |
| `daylight_*`    | Slope intercepts existing terrain                |

### Standard methods
- AASHTO GDPS-4-M (Green Book) §2.2 lane, §2.3 shoulder, §4.2 crown,
  §3.3.2 cut/fill slopes.
- Daylight: iterative offset stepping at `daylight_step_m` intervals.
- Cut/fill areas: shoelace formula on design-vs-terrain polygon strips.
- Volumes: average-end-area per AASHTO §2.2.3.
- Mass haul: Brückner method with `swell_factor` (typical earth = 1.25).
