# turning

*Module: `kerf_cad_core.turning.tools` · Domain: cad*

This module registers **8** LLM tool(s):

- [`turning_cutting_params`](#turning-cutting-params)
- [`turning_roughing_passes`](#turning-roughing-passes)
- [`turning_finishing_pass`](#turning-finishing-pass)
- [`turning_facing`](#turning-facing)
- [`turning_parting`](#turning-parting)
- [`turning_od_threading`](#turning-od-threading)
- [`turning_id_threading`](#turning-id-threading)
- [`turning_grooving`](#turning-grooving)

---

## `turning_cutting_params`

Compute spindle RPM (constant surface speed) and feed rate (mm/min) for each point in a 2-D turning profile.

Profile convention: list of [Z, X] pairs where Z is the axial position (mm, positive towards tailstock) and X is the radius in mm (not diameter).

Returns per-point dict with z_mm, x_mm, diameter_mm, rpm, feed_mm_min.

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "profile": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "description": "List of [Z, X] pairs. Z = axial mm; X = radius mm.",
      "minItems": 1
    },
    "css_m_per_min": {
      "type": "number",
      "description": "Constant surface speed in m/min. Default 180."
    },
    "feed_mm_rev": {
      "type": "number",
      "description": "Feed per revolution in mm/rev. Default 0.20."
    },
    "rpm_min": {
      "type": "number",
      "description": "Minimum spindle RPM. Default 50."
    },
    "rpm_max": {
      "type": "number",
      "description": "Maximum spindle RPM. Default 3500."
    }
  },
  "required": [
    "profile"
  ]
}
```

---

## `turning_roughing_passes`

Generate G71-equivalent OD roughing passes from a 2-D turning profile.

Starting from the stock OD radius, generates successive axial passes stepping inward by depth-of-cut until the profile contour (plus a finish allowance) is reached.  Returns ISO G-code lines and per-pass metadata.

Profile: list of [Z, X] pairs (Z axial mm, X radius mm, monotone Z).

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "profile": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "description": "2-D profile as list of [Z_mm, X_radius_mm] pairs.",
      "minItems": 2
    },
    "stock_x_mm": {
      "type": "number",
      "description": "Initial stock radius (mm). Must be > max profile X."
    },
    "doc_mm": {
      "type": "number",
      "description": "Radial depth of cut per pass (mm). Default 2.0."
    },
    "css_m_per_min": {
      "type": "number",
      "description": "Constant surface speed (m/min). Default 180."
    },
    "feed_mm_rev": {
      "type": "number",
      "description": "Feed per revolution (mm/rev). Default 0.20."
    },
    "rpm_min": {
      "type": "number",
      "description": "Min RPM. Default 50."
    },
    "rpm_max": {
      "type": "number",
      "description": "Max RPM. Default 3500."
    },
    "retract_mm": {
      "type": "number",
      "description": "Rapid clearance (mm). Default 2.0."
    },
    "finish_allowance_mm": {
      "type": "number",
      "description": "Radial material left for finishing pass (mm). Default 0.3."
    }
  },
  "required": [
    "profile",
    "stock_x_mm"
  ]
}
```

---

## `turning_finishing_pass`

Generate a G70-equivalent finishing pass that follows the exact 2-D turning profile at a fine feed rate.

RPM is computed per-segment using constant surface speed.
Returns ISO G-code lines and pass metadata.

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "profile": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "description": "2-D profile as list of [Z_mm, X_radius_mm] pairs.",
      "minItems": 2
    },
    "css_m_per_min": {
      "type": "number",
      "description": "Constant surface speed (m/min). Default 180."
    },
    "feed_mm_rev": {
      "type": "number",
      "description": "Finishing feed (mm/rev). Default 0.08."
    },
    "rpm_min": {
      "type": "number"
    },
    "rpm_max": {
      "type": "number"
    },
    "retract_mm": {
      "type": "number"
    },
    "doc_mm": {
      "type": "number",
      "description": "Finishing depth of cut for metadata. Default 0.25."
    }
  },
  "required": [
    "profile"
  ]
}
```

---

## `turning_facing`

Generate a facing cycle that cuts the end face of the workpiece.

The tool feeds from the OD (x_max_mm) inward to the bore or spindle centreline at the specified Z position.  Multiple passes step the face back axially by doc_mm per pass.

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "x_max_mm": {
      "type": "number",
      "description": "Outer radius at the face (mm). Must be > 0."
    },
    "z_face_mm": {
      "type": "number",
      "description": "Axial position of the face to be cut (mm)."
    },
    "doc_mm": {
      "type": "number",
      "description": "Axial depth of cut per pass (mm). Default 2.0."
    },
    "n_passes": {
      "type": "integer",
      "description": "Number of facing passes. Default 1.",
      "minimum": 1
    },
    "css_m_per_min": {
      "type": "number",
      "description": "Surface speed (m/min)."
    },
    "feed_mm_rev": {
      "type": "number",
      "description": "Feed per rev (mm/rev)."
    },
    "rpm_min": {
      "type": "number"
    },
    "rpm_max": {
      "type": "number"
    },
    "retract_mm": {
      "type": "number"
    },
    "bore_radius_mm": {
      "type": "number",
      "description": "Inner bore radius (stop before). Default 0 (through-centre)."
    }
  },
  "required": [
    "x_max_mm",
    "z_face_mm"
  ]
}
```

---

## `turning_parting`

Generate a parting (cut-off) cycle at a specified Z position.

Feeds a parting blade inward from the OD to the bore or spindle centreline.  Optional peck parting for deeper cuts.

Recommended CSS: 60-100 m/min; feed: 0.03-0.08 mm/rev.

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z_part_mm": {
      "type": "number",
      "description": "Axial position of the parting cut (mm)."
    },
    "x_max_mm": {
      "type": "number",
      "description": "Outer radius at cut location (mm). Must be > 0."
    },
    "css_m_per_min": {
      "type": "number",
      "description": "Surface speed (m/min). Default 80 (lower for parting)."
    },
    "feed_mm_rev": {
      "type": "number",
      "description": "Feed per rev (mm/rev). Default 0.05."
    },
    "rpm_min": {
      "type": "number"
    },
    "rpm_max": {
      "type": "number",
      "description": "Max RPM (default 1200 \u2014 limited for parting)."
    },
    "retract_mm": {
      "type": "number"
    },
    "bore_radius_mm": {
      "type": "number",
      "description": "Stop radius for hollow workpiece. Default 0."
    },
    "peck_depth_mm": {
      "type": "number",
      "description": "Peck depth increment for deep/interrupted cuts (mm). Omit for single plunge."
    }
  },
  "required": [
    "z_part_mm",
    "x_max_mm"
  ]
}
```

---

## `turning_od_threading`

Generate an external (OD) threading cycle using a G76-style degressive infeed schedule.

Produces G32 constant-lead thread cuts with compound infeed at 'infeed_deg' degrees (default 29.5° for 60° threads).  Thread depth defaults to 0.6495 × pitch for ISO/metric threads.

Returns G-code and per-pass metadata including cumulative depth and spring pass flags.

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z_start_mm": {
      "type": "number",
      "description": "Thread start Z (approach end), mm."
    },
    "z_end_mm": {
      "type": "number",
      "description": "Thread end Z (relief end), mm.  z_end != z_start."
    },
    "x_major_mm": {
      "type": "number",
      "description": "Major diameter radius (OD), mm."
    },
    "pitch_mm": {
      "type": "number",
      "description": "Thread pitch (mm). Default 1.5."
    },
    "thread_depth_mm": {
      "type": "number",
      "description": "Full radial thread depth (mm). Default: 0.6495 \u00d7 pitch."
    },
    "infeed_deg": {
      "type": "number",
      "description": "Compound infeed angle (degrees). Default 29.5\u00b0 (60\u00b0 thread)."
    },
    "first_pass_depth_mm": {
      "type": "number",
      "description": "First pass radial depth (mm). Default 0.3."
    },
    "min_pass_depth_mm": {
      "type": "number",
      "description": "Minimum pass depth for degression (mm). Default 0.05."
    },
    "spring_passes": {
      "type": "integer",
      "description": "Number of no-feed spring passes at full depth. Default 2.",
      "minimum": 0
    },
    "css_m_per_min": {
      "type": "number",
      "description": "Surface speed (m/min). Default 100 for threading."
    },
    "rpm_min": {
      "type": "number"
    },
    "rpm_max": {
      "type": "number",
      "description": "Max threading RPM (default 800)."
    },
    "retract_mm": {
      "type": "number"
    }
  },
  "required": [
    "z_start_mm",
    "z_end_mm",
    "x_major_mm"
  ]
}
```

---

## `turning_id_threading`

Generate an internal (ID/bore) threading cycle using a G76-style degressive infeed schedule.

Mirror of turning_od_threading for bores: the tool starts at the minor radius and moves outward (+X) with each pass.

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z_start_mm": {
      "type": "number",
      "description": "Thread start Z (approach end), mm."
    },
    "z_end_mm": {
      "type": "number",
      "description": "Thread end Z, mm.  z_end != z_start."
    },
    "x_minor_mm": {
      "type": "number",
      "description": "Bore (minor) radius before threading, mm."
    },
    "pitch_mm": {
      "type": "number",
      "description": "Thread pitch (mm). Default 1.5."
    },
    "thread_depth_mm": {
      "type": "number",
      "description": "Full radial thread depth (mm). Default: 0.6495 \u00d7 pitch."
    },
    "infeed_deg": {
      "type": "number",
      "description": "Compound infeed angle (degrees). Default 29.5\u00b0."
    },
    "first_pass_depth_mm": {
      "type": "number",
      "description": "First pass depth (mm). Default 0.2."
    },
    "min_pass_depth_mm": {
      "type": "number",
      "description": "Minimum pass depth (mm). Default 0.03."
    },
    "spring_passes": {
      "type": "integer",
      "description": "Spring passes at full depth. Default 2.",
      "minimum": 0
    },
    "css_m_per_min": {
      "type": "number"
    },
    "rpm_min": {
      "type": "number"
    },
    "rpm_max": {
      "type": "number"
    },
    "retract_mm": {
      "type": "number"
    }
  },
  "required": [
    "z_start_mm",
    "z_end_mm",
    "x_minor_mm"
  ]
}
```

---

## `turning_grooving`

Generate a grooving (recessing) cycle.

Cuts a groove of specified width and depth centred at z_center_mm, starting from x_start_mm (OD).  If the groove is wider than the tool, multiple overlapping plunges are generated automatically.

Optional peck grooving for deep grooves.

Errors: {ok:false, reason} — never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z_center_mm": {
      "type": "number",
      "description": "Axial centre of the groove (mm)."
    },
    "x_start_mm": {
      "type": "number",
      "description": "OD radius at groove location (mm)."
    },
    "groove_depth_mm": {
      "type": "number",
      "description": "Radial depth of groove (mm). Default 2.0."
    },
    "groove_width_mm": {
      "type": "number",
      "description": "Total axial width of groove (mm). Default 3.0."
    },
    "tool_width_mm": {
      "type": "number",
      "description": "Grooving insert width (mm). Default 3.0."
    },
    "css_m_per_min": {
      "type": "number",
      "description": "Surface speed (m/min). Default 100."
    },
    "feed_mm_rev": {
      "type": "number",
      "description": "Feed per rev (mm/rev). Default 0.05."
    },
    "rpm_min": {
      "type": "number"
    },
    "rpm_max": {
      "type": "number"
    },
    "retract_mm": {
      "type": "number"
    },
    "peck_depth_mm": {
      "type": "number",
      "description": "Peck increment for deep grooves (mm). Omit for direct plunge."
    }
  },
  "required": [
    "z_center_mm",
    "x_start_mm"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
