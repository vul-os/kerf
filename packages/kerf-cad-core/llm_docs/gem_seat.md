# gem_seat

*Module: `kerf_cad_core.jewelry.gem_seat` · Domain: cad*

This module registers **9** LLM tool(s):

- [`jewelry_cut_gem_seat`](#jewelry-cut-gem-seat)
- [`jewelry_cut_channel_seat`](#jewelry-cut-channel-seat)
- [`jewelry_cut_bezel_seat`](#jewelry-cut-bezel-seat)
- [`jewelry_cut_fishtail_seat`](#jewelry-cut-fishtail-seat)
- [`jewelry_cut_multi_stone_seat`](#jewelry-cut-multi-stone-seat)
- [`jewelry_cut_pave_field_seat`](#jewelry-cut-pave-field-seat)
- [`jewelry_cut_cluster_halo_seat`](#jewelry-cut-cluster-halo-seat)
- [`jewelry_cut_gypsy_seat`](#jewelry-cut-gypsy-seat)
- [`jewelry_cut_baguette_channel_seat`](#jewelry-cut-baguette-channel-seat)

---

## `jewelry_cut_gem_seat`

Append a `gem_seat` node to a `.feature` file. Generates a gem-seat cutter solid (bearing cone + girdle ledge + optional through-hole for light) parameterised from the gemstone's cut and size. The seat cutter is positioned at `position` with `orientation_deg` rotation. If `auto_cut_host_id` is provided, a `boolean` cut node is also appended so the seat is immediately subtracted from the host solid — this is the most common single-step workflow. Without auto_cut_host_id, call feature_boolean manually:   feature_boolean(file_id, target_a_id=<host>, target_b_id=<seat_id>, kind='cut'). Seat geometry algorithm:   1. Bearing cone  — truncated cone, half-angle = pavilion_angle,      top_radius = girdle_radius + girdle_clearance, depth = pavilion_depth + culet_clearance.   2. Girdle ledge  — thin cylinder of height = girdle_mm + seat_allowance.   3. Crown relief  — countersink taper (crown_angle/2) of depth crown_relief_mm.   4. Optional through-hole for light ingress (through_hole=true). For non-round cuts pass girdle_shape to match the stone outline exactly. The OCCT worker's opGemSeat assembles these primitives into a single closed TopoDS_Solid cutter.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut to match. Used for default proportions."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight in carats (converted to mm). Provide carat OR diameter_mm."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Primary dimension in mm. Provide diameter_mm OR carat."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x, y, z] seat centre in model space (mm). Default [0,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx, ry, rz] Euler angles (degrees). Default [0,0,0]."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance around girdle (mm). Default 0.05."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Extra depth below pavilion tip (mm). Default 0.10."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial allowance on girdle ledge height (mm). Default 0.02."
    },
    "crown_relief_mm": {
      "type": "number",
      "description": "Depth of crown-relief countersink above girdle (mm). Default 0.30."
    },
    "through_hole": {
      "type": "boolean",
      "description": "Add a cylindrical through-hole for light ingress. Default false."
    },
    "through_hole_radius_mm": {
      "type": "number",
      "description": "Through-hole radius (mm). Default: culet estimate. Requires through_hole=true."
    },
    "girdle_shape": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Optional: use the girdle outline profile matching this cut. Useful when the seat cut name differs from the stone's visual shape, or to explicitly request a non-round bearing ledge for fancy cuts (oval, marquise, pear, emerald, cushion). Defaults to `cut` value."
    },
    "aspect_ratio": {
      "type": "number",
      "description": "Width/length ratio override for fancy-cut girdle profile. Optional."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "If set, append a boolean cut node subtracting the seat from this host feature node id immediately after the seat node. Equivalent to running feature_boolean(kind='cut', target_a_id=auto_cut_host_id, target_b_id=<new_seat_id>)."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id for the gem_seat node."
    }
  },
  "required": [
    "file_id",
    "cut"
  ]
}
```

---

## `jewelry_cut_channel_seat`

Append a `channel_seat` node to a `.feature` file. Generates a continuous bearing groove for a row of N stones at a given pitch. The groove cutter is a swept slot sized to the stone's girdle + clearance, with per-stone bearing pockets. Emits positions for all N stones. Use auto_cut_host_id to immediately subtract the groove from the host solid. Validation: pitch_mm must exceed stone diameter_mm (spacing must exceed stone size).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut for all stones in the row."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight (carats). Provide carat OR diameter_mm."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."
    },
    "n_stones": {
      "type": "integer",
      "minimum": 1,
      "description": "Number of stones in the row."
    },
    "pitch_mm": {
      "type": "number",
      "description": "Centre-to-centre stone spacing (mm). Must exceed diameter_mm."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] centre of the first stone. Default [0,0,0]."
    },
    "axis_direction": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[dx,dy,dz] row direction unit vector. Default [1,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] groove cutter orientation. Default [0,0,0]."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.05."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion tip (mm). Default 0.10."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "crown_relief_mm": {
      "type": "number",
      "description": "Crown countersink depth (mm). Default 0.30."
    },
    "groove_wall_thickness_mm": {
      "type": "number",
      "description": "Minimum metal wall between groove and channel face (mm). Default 0.20."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract the groove from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut",
    "n_stones",
    "pitch_mm"
  ]
}
```

---

## `jewelry_cut_bezel_seat`

Append a `bezel_seat` node to a `.feature` file. Generates an inner bearing ledge sized for a bezel or collet setting. The inner bore is cylindrical by default; set tapered=true for a collet (tapered bore) that grips the stone. Supports all cuts including fancy shapes (oval/marquise/pear/emerald/cushion) via automatic girdle profile computation. Use auto_cut_host_id to immediately subtract the seat from the host solid.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight (carats). Provide carat OR diameter_mm."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."
    },
    "bezel_wall_height_mm": {
      "type": "number",
      "description": "Height of the bezel collet wall above the girdle ledge (mm). Default 1.0."
    },
    "tapered": {
      "type": "boolean",
      "description": "If true, use a tapered bore (collet style). Default false."
    },
    "taper_angle_deg": {
      "type": "number",
      "description": "Half-angle of tapered bore (degrees). Only used if tapered=true. Default 5.0."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] seat centre. Default [0,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] Euler angles. Default [0,0,0]."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.08."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion tip (mm). Default 0.10."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "crown_relief_mm": {
      "type": "number",
      "description": "Crown countersink depth (mm). Default 0.20."
    },
    "through_hole": {
      "type": "boolean",
      "description": "Add through-hole. Default false."
    },
    "through_hole_radius_mm": {
      "type": "number",
      "description": "Through-hole radius (mm)."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract the seat from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut"
  ]
}
```

---

## `jewelry_cut_fishtail_seat`

Append a `fishtail_seat` node to a `.feature` file. Generates a small accent-stone seat with bright-cut facet grooves radiating outward from the girdle ledge. The bright-cut geometry hint is stored in the node for the OCCT worker to mill radial facet cuts. Typically used for pavé and channel-pavé accent stones.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut (usually round_brilliant for accent stones)."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight (carats). Provide carat OR diameter_mm."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."
    },
    "bright_cut_angle_deg": {
      "type": "number",
      "description": "Half-angle of each bright-cut groove from vertical (degrees). Default 45."
    },
    "bright_cut_depth_mm": {
      "type": "number",
      "description": "Axial depth of each bright-cut groove (mm). Default 0.15."
    },
    "n_bright_facets": {
      "type": "integer",
      "minimum": 1,
      "description": "Number of radial bright-cut grooves. Default 4."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] seat centre. Default [0,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] Euler angles. Default [0,0,0]."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.04."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion tip (mm). Default 0.08."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "crown_relief_mm": {
      "type": "number",
      "description": "Crown countersink depth (mm). Default 0.25."
    },
    "through_hole": {
      "type": "boolean",
      "description": "Add through-hole. Default false."
    },
    "through_hole_radius_mm": {
      "type": "number",
      "description": "Through-hole radius (mm)."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract the seat from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut"
  ]
}
```

---

## `jewelry_cut_multi_stone_seat`

Append a `multi_stone_seat` node to a `.feature` file. Generates a shared base seat for a graduated multi-stone arrangement: a center stone flanked by smaller side stones (e.g. 3-stone or 5-stone). Returns the center seat geometry, per-side-stone geometry, and all stone positions. n_side_stones must be even (symmetric) and >= 2. side_pitch_mm must exceed the larger of center_diameter_mm / side_diameter_mm.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut for all stones (center + sides)."
    },
    "center_carat": {
      "type": "number",
      "description": "Center stone weight (carats)."
    },
    "center_diameter_mm": {
      "type": "number",
      "description": "Center stone primary dimension (mm)."
    },
    "side_carat": {
      "type": "number",
      "description": "Side stone weight (carats, each)."
    },
    "side_diameter_mm": {
      "type": "number",
      "description": "Side stone primary dimension (mm, each)."
    },
    "n_side_stones": {
      "type": "integer",
      "minimum": 2,
      "description": "Total number of side stones. Must be even (symmetric). Default 2."
    },
    "side_pitch_mm": {
      "type": "number",
      "description": "Centre-to-centre spacing between adjacent stones (mm). Must exceed stone diameter."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] centre stone position. Default [0,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] Euler angles. Default [0,0,0]."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.05."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion tip (mm). Default 0.10."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "crown_relief_mm": {
      "type": "number",
      "description": "Crown countersink depth (mm). Default 0.30."
    },
    "through_hole_center": {
      "type": "boolean",
      "description": "Add through-hole to center seat only. Default false."
    },
    "through_hole_radius_mm": {
      "type": "number",
      "description": "Center through-hole radius (mm)."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract the seat group from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut",
    "side_pitch_mm"
  ]
}
```

---

## `jewelry_cut_pave_field_seat`

Append a `pave_field_seat` node to a `.feature` file. Generates a grid or honeycomb arrangement of small identical bearing seats across a rectangular region for pavé-field settings. Returns all stone positions and a single per-seat geometry dict. Use `arrangement='honeycomb'` for the classic offset-row pavé look. Positions are centred in the field (origin at field centre). Use auto_cut_host_id to immediately chain a boolean cut for all seats. Note: the OCCT worker will receive all positions and the per-seat geometry; the union of all seat cutters is subtracted from the host.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut for all pav\u00e9 stones (usually round_brilliant)."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight (carats). Provide carat OR diameter_mm."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."
    },
    "field_width_mm": {
      "type": "number",
      "description": "Width (X extent) of the pav\u00e9 field region (mm)."
    },
    "field_height_mm": {
      "type": "number",
      "description": "Height (Y extent) of the pav\u00e9 field region (mm)."
    },
    "arrangement": {
      "type": "string",
      "enum": [
        "grid",
        "honeycomb"
      ],
      "description": "Row arrangement: 'grid' (regular) or 'honeycomb' (alternating offset). Default 'grid'."
    },
    "min_spacing_mm": {
      "type": "number",
      "description": "Minimum metal between adjacent seat edges (mm). Default 0.30."
    },
    "edge_margin_mm": {
      "type": "number",
      "description": "Minimum clearance from field boundary to nearest seat edge (mm). Default 0.25."
    },
    "preset": {
      "type": "string",
      "enum": [
        "deep",
        "standard",
        "tight"
      ],
      "description": "Named bearing preset controlling clearances. 'tight' (0.03 girdle / 0.20 crown), 'standard' (0.05 / 0.30), 'deep' (0.07 / 0.40). Explicit clearance params override preset values."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.04."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion tip (mm). Default 0.08."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "crown_relief_mm": {
      "type": "number",
      "description": "Crown countersink depth (mm). Default 0.25."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] offset applied to all stone positions. Default [0,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] field orientation Euler angles. Default [0,0,0]."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract all seats from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut",
    "field_width_mm",
    "field_height_mm"
  ]
}
```

---

## `jewelry_cut_cluster_halo_seat`

Append a `cluster_halo_seat` node to a `.feature` file. Generates a center-stone seat surrounded by a ring of equally-spaced accent seats at a given radius and count (halo / cluster setting). Center and accent stones can have different cuts and sizes. All accent seats are identical and placed at angles 360/n_accent apart. Use start_angle_deg to rotate the ring. Use auto_cut_host_id to immediately subtract all seats from the host.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "center_cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Cut of the center stone."
    },
    "center_carat": {
      "type": "number",
      "description": "Center stone weight (carats). Provide center_carat OR center_diameter_mm."
    },
    "center_diameter_mm": {
      "type": "number",
      "description": "Center stone primary dimension (mm). Provide center_diameter_mm OR center_carat."
    },
    "accent_cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Cut of accent (halo) stones (usually round_brilliant)."
    },
    "accent_carat": {
      "type": "number",
      "description": "Accent stone weight (carats). Provide accent_carat OR accent_diameter_mm."
    },
    "accent_diameter_mm": {
      "type": "number",
      "description": "Accent stone primary dimension (mm). Provide accent_diameter_mm OR accent_carat."
    },
    "n_accent": {
      "type": "integer",
      "minimum": 3,
      "description": "Number of accent stones in the ring (>= 3)."
    },
    "halo_radius_mm": {
      "type": "number",
      "description": "Centre-to-centre radius from center stone to accent stones (mm)."
    },
    "start_angle_deg": {
      "type": "number",
      "description": "Angular offset (degrees) for the first accent stone. Default 0."
    },
    "preset": {
      "type": "string",
      "enum": [
        "deep",
        "standard",
        "tight"
      ],
      "description": "Named bearing preset. See jewelry_cut_pave_field_seat for values."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] center stone position. Default [0,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] Euler angles. Default [0,0,0]."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.04."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion tip (mm). Default 0.08."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "crown_relief_mm": {
      "type": "number",
      "description": "Crown countersink depth (mm). Default 0.25."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract all seats from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "center_cut",
    "accent_cut",
    "n_accent",
    "halo_radius_mm"
  ]
}
```

---

## `jewelry_cut_gypsy_seat`

Append a `gypsy_seat` node to a `.feature` file. Generates a flush / gypsy-set countersink seat — the stone's girdle sits at the metal surface with no bearing cone overhang above. The cutter is a straight cylinder with a shallow countersink at the top to accept the lower crown facets. Unlike jewelry_cut_gem_seat, there is no crown relief overhang above the metal. Use for gypsy settings, burnish settings, and tube-set stones. Use auto_cut_host_id to immediately subtract the seat from the host solid.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight (carats). Provide carat OR diameter_mm."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Stone primary dimension (mm). Provide diameter_mm OR carat."
    },
    "countersink_angle_deg": {
      "type": "number",
      "description": "Half-angle of the top countersink taper (degrees). Default 45."
    },
    "countersink_depth_mm": {
      "type": "number",
      "description": "Axial depth of the countersink (mm). Default 0.20."
    },
    "through_hole": {
      "type": "boolean",
      "description": "Add through-hole. Default false."
    },
    "through_hole_radius_mm": {
      "type": "number",
      "description": "Through-hole radius (mm)."
    },
    "preset": {
      "type": "string",
      "enum": [
        "deep",
        "standard",
        "tight"
      ],
      "description": "Named bearing preset. See jewelry_cut_pave_field_seat for values."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] seat centre. Default [0,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] Euler angles. Default [0,0,0]."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.03."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion tip (mm). Default 0.10."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract the seat from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut"
  ]
}
```

---

## `jewelry_cut_baguette_channel_seat`

Append a `baguette_channel_seat` node to a `.feature` file. Generates a rectangular straight-wall bearing groove for step-cut stones (baguette, trap/trapezoid, carré). Unlike the round channel_seat which uses a circular bearing cone, this cutter is a prismatic rectangular slot — the correct bearing profile for rectangular/square girdles. Provide stone dimensions directly as length_mm and width_mm (no cut-derived proportions; step-cut pavilions are shallow and user-measured). pitch_mm must exceed length_mm. Use auto_cut_host_id to immediately subtract the groove from the host solid.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut (usually baguette, emerald, or princess for metadata)."
    },
    "length_mm": {
      "type": "number",
      "description": "Stone long-axis dimension (mm). Required."
    },
    "width_mm": {
      "type": "number",
      "description": "Stone short-axis dimension (mm). Required."
    },
    "pavilion_depth_mm": {
      "type": "number",
      "description": "Pavilion depth (mm). Required (step-cuts have shallow pavilions)."
    },
    "n_stones": {
      "type": "integer",
      "minimum": 1,
      "description": "Number of stones in the channel."
    },
    "pitch_mm": {
      "type": "number",
      "description": "Centre-to-centre spacing (mm). Must exceed length_mm."
    },
    "wall_thickness_mm": {
      "type": "number",
      "description": "Minimum metal wall between groove and channel face (mm). Default 0.20."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x,y,z] centre of first stone. Default [0,0,0]."
    },
    "axis_direction": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[dx,dy,dz] row direction. Default [1,0,0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx,ry,rz] groove orientation. Default [0,0,0]."
    },
    "preset": {
      "type": "string",
      "enum": [
        "deep",
        "standard",
        "tight"
      ],
      "description": "Named bearing preset. See jewelry_cut_pave_field_seat for values."
    },
    "girdle_clearance_mm": {
      "type": "number",
      "description": "Radial clearance (mm). Default 0.05."
    },
    "culet_clearance_mm": {
      "type": "number",
      "description": "Depth below pavilion (mm). Default 0.10."
    },
    "seat_allowance_mm": {
      "type": "number",
      "description": "Axial ledge allowance (mm). Default 0.02."
    },
    "auto_cut_host_id": {
      "type": "string",
      "description": "Host node id to subtract the groove from."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut",
    "length_mm",
    "width_mm",
    "pavilion_depth_mm",
    "n_stones",
    "pitch_mm"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
