# settings

*Module: `kerf_cad_core.jewelry.settings` · Domain: cad*

This module registers **25** LLM tool(s):

- [`jewelry_create_prong_head`](#jewelry-create-prong-head)
- [`jewelry_create_bezel`](#jewelry-create-bezel)
- [`jewelry_create_channel`](#jewelry-create-channel)
- [`jewelry_pave_array`](#jewelry-pave-array)
- [`jewelry_create_tension`](#jewelry-create-tension)
- [`jewelry_create_flush`](#jewelry-create-flush)
- [`jewelry_create_halo`](#jewelry-create-halo)
- [`jewelry_create_three_stone`](#jewelry-create-three-stone)
- [`jewelry_create_cluster`](#jewelry-create-cluster)
- [`jewelry_create_bar`](#jewelry-create-bar)
- [`jewelry_create_bead_grain`](#jewelry-create-bead-grain)
- [`jewelry_create_gypsy_pave`](#jewelry-create-gypsy-pave)
- [`jewelry_create_illusion`](#jewelry-create-illusion)
- [`jewelry_create_invisible`](#jewelry-create-invisible)
- [`jewelry_create_prong_variant`](#jewelry-create-prong-variant)
- [`jewelry_create_head_gallery`](#jewelry-create-head-gallery)
- [`jewelry_create_under_bezel`](#jewelry-create-under-bezel)
- [`jewelry_create_peg_setting`](#jewelry-create-peg-setting)
- [`jewelry_create_coronet`](#jewelry-create-coronet)
- [`jewelry_create_suspension_mount`](#jewelry-create-suspension-mount)
- [`jewelry_create_vtip_protector`](#jewelry-create-vtip-protector)
- [`jewelry_create_bombe_cluster`](#jewelry-create-bombe-cluster)
- [`jewelry_create_patterned_bezel`](#jewelry-create-patterned-bezel)
- [`jewelry_create_trellis_prong`](#jewelry-create-trellis-prong)
- [`jewelry_create_bar_channel_graduated`](#jewelry-create-bar-channel-graduated)

---

## `jewelry_create_prong_head`

Append a `jewelry_prong_head` node to a `.feature` file. Generates a parametric prong-head setting (4-prong, 6-prong, basket, trellis, or cathedral style) sized to accept a stone of `stone_diameter`. The head solid includes a bearing ledge at `seat_angle_deg` to seat the gemstone girdle, `prong_count` round prong wires of `prong_wire_diameter`, and a basket rail (if `head_style` is 'basket' or 'trellis'). Output: a TopoDS_Solid head body ready for boolean fuse onto a shank.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm (e.g. 6.5 for a 1 ct round brilliant)."
    },
    "prong_count": {
      "type": "integer",
      "enum": [
        4,
        6
      ],
      "description": "Number of prongs. 4 (square set) or 6 (classic Tiffany)."
    },
    "prong_wire_diameter": {
      "type": "number",
      "description": "Round-wire prong diameter in mm. Typical range 0.8\u20131.5 mm."
    },
    "prong_height": {
      "type": "number",
      "description": "Height the prong extends above the stone's girdle plane in mm."
    },
    "head_style": {
      "type": "string",
      "enum": [
        "standard",
        "basket",
        "trellis",
        "cathedral"
      ],
      "description": "Head geometry style. 'standard': plain prongs, no connecting rail. 'basket': horizontal rail band connecting alternate prong bases. 'trellis': cross-diagonal rail between adjacent prongs. 'cathedral': arch ribs rising from prong base to a lower shank seat."
    },
    "basket_rail_count": {
      "type": "integer",
      "description": "Number of horizontal basket rails (default 1). Ignored for 'standard'."
    },
    "seat_angle_deg": {
      "type": "number",
      "description": "Angle (degrees) of the bearing ledge chamfer. Default 15\u00b0."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "prong_count",
    "prong_wire_diameter",
    "prong_height"
  ]
}
```

---

## `jewelry_create_bezel`

Append a `jewelry_bezel` node to a `.feature` file. Generates a parametric bezel setting — a full or partial metal collar surrounding a gemstone, with a horizontal bearing ledge on which the stone's girdle seats. Styles: 'full' (360° collar), 'partial' (gap of `partial_opening_deg`), 'collet' (tube bezel, minimal wall), 'tapered' (outer wall angled inward at `taper_angle_deg` for a rub-over look). Output: a TopoDS_Solid bezel body ready for boolean fuse onto a shank.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "wall_thickness": {
      "type": "number",
      "description": "Bezel wall thickness in mm. Typical: 0.3\u20130.8 mm."
    },
    "bezel_height": {
      "type": "number",
      "description": "Total height of the bezel collar in mm (from base to top)."
    },
    "bearing_ledge_height": {
      "type": "number",
      "description": "Height of the bearing ledge from the base. The stone girdle rests here. Must be < bezel_height."
    },
    "bezel_style": {
      "type": "string",
      "enum": [
        "full",
        "partial",
        "collet",
        "tapered"
      ],
      "description": "Bezel geometry style."
    },
    "partial_opening_deg": {
      "type": "number",
      "description": "Gap angle (degrees) for 'partial' style. Range [1, 359]. Ignored for 'full'/'collet'/'tapered'."
    },
    "taper_angle_deg": {
      "type": "number",
      "description": "Outer wall inward taper angle in degrees (0 = straight). Used for 'tapered'/'collet' styles."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "wall_thickness",
    "bezel_height",
    "bearing_ledge_height"
  ]
}
```

---

## `jewelry_create_channel`

Append a `jewelry_channel` node to a `.feature` file. Generates a parametric channel setting — two parallel metal rails with a floor, sized to hold a row of `stone_count` calibrated stones of `stone_diameter` at `stone_spacing` centre-to-centre intervals. The channel runs along the X-axis. The worker's evaluate result includes `seat_positions` — a list of per-stone XYZ positions relative to the channel's local origin — so a downstream gem-seat op can cut each seat. Output: a TopoDS_Solid channel body.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Stone girdle diameter (width) in mm."
    },
    "stone_count": {
      "type": "integer",
      "description": "Number of stones in the channel row. Must be >= 1."
    },
    "stone_spacing": {
      "type": "number",
      "description": "Centre-to-centre spacing between adjacent stones in mm. Must be > stone_diameter."
    },
    "rail_height": {
      "type": "number",
      "description": "Height of the channel rails above the stone seat in mm."
    },
    "rail_thickness": {
      "type": "number",
      "description": "Thickness of each rail wall in mm."
    },
    "floor_thickness": {
      "type": "number",
      "description": "Thickness of the channel floor in mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "stone_count",
    "stone_spacing",
    "rail_height",
    "rail_thickness",
    "floor_thickness"
  ]
}
```

---

## `jewelry_pave_array`

Append a `jewelry_pave` node to a `.feature` file. Distributes stone placements across a rectangular target surface region using a hex-offset grid layout. Returns the array of placement transforms (u,v fractional coordinates on the region surface) so a downstream gem-seat op can cut individual stone seats. The operation does NOT cut seats itself — it only records the placement grid. Pair with a boolean-cut loop or a future gem_seat op to produce actual seats. Parameters control stone diameter, centre-to-centre spacing, and an edge margin that keeps the outermost stones' edges inside the region boundary. Odd rows are shifted by half a column pitch (hex offset) for tighter packing and the characteristic pavé bead appearance.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "region_width": {
      "type": "number",
      "description": "Width (X-extent) of the target region in mm."
    },
    "region_height": {
      "type": "number",
      "description": "Height (Y-extent) of the target region in mm."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Stone girdle diameter in mm."
    },
    "stone_spacing": {
      "type": "number",
      "description": "Gap between adjacent stone edges in mm (centre-to-centre = stone_diameter + stone_spacing)."
    },
    "edge_margin": {
      "type": "number",
      "description": "Minimum margin from the region boundary to the outermost stone edge in mm."
    },
    "surface_normal": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "World-space normal of the target surface plane [nx, ny, nz]. Default [0, 0, 1]."
    },
    "surface_origin": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "World-space origin of the region [x, y, z]. Default [0, 0, 0]."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "region_width",
    "region_height",
    "stone_diameter",
    "stone_spacing",
    "edge_margin"
  ]
}
```

---

## `jewelry_create_tension`

Append a `jewelry_tension` node to a `.feature` file. Generates a tension setting where the stone is held purely by the spring pressure of two opposing band ends. The stone floats in a gap between the band ends; each end has an inward-curved bearing rail that grips the stone's girdle. Output: a node spec consumed by the OCCT worker's opJewelryTension handler to produce two TopoDS_Solid band-end bodies.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "band_thickness": {
      "type": "number",
      "description": "Thickness of the band metal at the setting point in mm (typical 2.0\u20134.0)."
    },
    "gap": {
      "type": "number",
      "description": "Gap between the two band-end faces in mm. Must be < stone_diameter so the stone is retained."
    },
    "rail_width": {
      "type": "number",
      "description": "Width of the bearing rail that grips the girdle in mm (typical 0.3\u20130.8)."
    },
    "rail_depth": {
      "type": "number",
      "description": "Depth of the bearing rail notch in mm (typical 0.2\u20130.5)."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "band_thickness",
    "gap",
    "rail_width",
    "rail_depth"
  ]
}
```

---

## `jewelry_create_flush`

Append a `jewelry_flush` node to a `.feature` file. Generates a flush (gypsy) setting where the stone is set into a drilled seat so its table sits level with — or just proud of — the surrounding metal surface. The worker's opJewelryFlush handler drills a cylindrical pocket of `stone_diameter` × `seat_depth` and adds a chamfered opening edge (bevel) to ease the stone in and catch light. Output: a boolean-cut node spec. Pair with the parent metal body using a `feature_boolean` cut.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "seat_depth": {
      "type": "number",
      "description": "Depth of the drilled seat in mm (typically 60\u201380% of stone depth)."
    },
    "bevel_width": {
      "type": "number",
      "description": "Width of the opening bevel/chamfer in mm (typical 0.1\u20130.3)."
    },
    "bevel_angle_deg": {
      "type": "number",
      "description": "Angle of the bevel chamfer in degrees (typical 30\u201360\u00b0)."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "seat_depth",
    "bevel_width",
    "bevel_angle_deg"
  ]
}
```

---

## `jewelry_create_halo`

Append a `jewelry_halo` node to a `.feature` file. Generates a halo setting — a ring of small accent/pavé stones surrounding a center stone seat. The `halo_stone_count` accent stones of `halo_stone_size` are placed evenly around the center stone at a radial distance of `halo_gap` from the center stone edge. A metal halo frame of `halo_metal_width` surrounds the accent ring. The center stone seat is NOT generated by this tool — add a `jewelry_create_prong_head` or `jewelry_create_bezel` node separately for the center stone. Output: node spec consumed by the OCCT worker's opJewelryHalo handler.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "center_diameter": {
      "type": "number",
      "description": "Girdle diameter of the center stone in mm."
    },
    "halo_stone_size": {
      "type": "number",
      "description": "Diameter of each individual halo accent stone in mm (typical 1.0\u20131.8)."
    },
    "halo_stone_count": {
      "type": "integer",
      "description": "Number of accent stones in the halo ring (typical 14\u201332). Must be >= 3."
    },
    "halo_gap": {
      "type": "number",
      "description": "Radial gap between the center stone edge and the nearest halo stone edge in mm (typical 0.1\u20130.3)."
    },
    "halo_metal_width": {
      "type": "number",
      "description": "Width of the metal frame surrounding the halo accent ring in mm (typical 0.3\u20130.6)."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "center_diameter",
    "halo_stone_size",
    "halo_stone_count",
    "halo_gap",
    "halo_metal_width"
  ]
}
```

---

## `jewelry_create_three_stone`

Append a `jewelry_three_stone` node to a `.feature` file. Generates a three-stone setting — a center stone flanked by two graduated side stones on a shared base/gallery. The center stone seat has diameter `center_diameter`; the two side stone seats have diameter `side_diameter` (typically 60–75% of center). All three seats share a common base of height `base_height`. Output: node spec consumed by the OCCT worker's opJewelryThreeStone handler to produce a combined base solid with three seat positions posted in the evaluate result.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "center_diameter": {
      "type": "number",
      "description": "Girdle diameter of the center stone in mm."
    },
    "side_diameter": {
      "type": "number",
      "description": "Girdle diameter of each side stone in mm. Typically 60\u201375% of center_diameter."
    },
    "stone_spacing": {
      "type": "number",
      "description": "Gap between adjacent stone edges in mm (typical 0.1\u20130.3)."
    },
    "base_height": {
      "type": "number",
      "description": "Height of the shared gallery base in mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "center_diameter",
    "side_diameter",
    "stone_spacing",
    "base_height"
  ]
}
```

---

## `jewelry_create_cluster`

Append a `jewelry_cluster` node to a `.feature` file. Generates a cluster setting where `stone_count` small stones are grouped together on a domed base to read visually as one large stone. Stones of `stone_size` are arranged on a circular platform of `cluster_diameter`. The dome curvature is controlled by `dome_height` (the height of the domed base profile). Output: node spec consumed by the OCCT worker's opJewelryCluster handler. The evaluate result includes `seat_positions` — per-stone XYZ positions on the dome surface — for downstream seat-cutting.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cluster_diameter": {
      "type": "number",
      "description": "Overall diameter of the cluster platform in mm."
    },
    "stone_size": {
      "type": "number",
      "description": "Girdle diameter of each individual stone in the cluster in mm."
    },
    "stone_count": {
      "type": "integer",
      "description": "Number of stones in the cluster. Must be >= 1."
    },
    "dome_height": {
      "type": "number",
      "description": "Height of the dome profile above the base plane in mm. Use 0.0 for a flat cluster."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cluster_diameter",
    "stone_size",
    "stone_count",
    "dome_height"
  ]
}
```

---

## `jewelry_create_bar`

Append a `jewelry_bar` node to a `.feature` file. Generates a bar setting — two parallel metal bars running along either side of a row of `stone_count` calibrated stones of `stone_diameter`, spaced at `pitch` centre-to-centre. Unlike a channel setting there are NO prongs between stones: each stone is gripped along its full girdle by the bars alone, creating a clean uninterrupted look popular in men's bands and eternity rings. The bars have cross-section `bar_width` × `bar_height`. Constraint: pitch must be greater than stone_diameter. Output: a TopoDS_Solid pair of bars with stone seat cutouts.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of each stone in mm."
    },
    "bar_width": {
      "type": "number",
      "description": "Width of each metal bar in mm (typical 0.4\u20131.0)."
    },
    "bar_height": {
      "type": "number",
      "description": "Height of each metal bar above the stone seat in mm (typical 0.5\u20131.2)."
    },
    "stone_count": {
      "type": "integer",
      "description": "Number of stones in the bar row. Must be >= 1."
    },
    "pitch": {
      "type": "number",
      "description": "Centre-to-centre distance between adjacent stones in mm. Must be > stone_diameter."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "bar_width",
    "bar_height",
    "stone_count",
    "pitch"
  ]
}
```

---

## `jewelry_create_bead_grain`

Append a `jewelry_bead_grain` node to a `.feature` file. Generates a bead (grain) setting where each stone is held by small raised metal beads that are cut up from the surrounding metal surface and pushed over the stone's girdle. Parameters control the stone diameter, the number of beads per stone (`bead_count_per_stone`, minimum 2), the bead diameter, and the overall field layout (`line` for a single row or `grid` for a rectangular array). Output: node spec consumed by opJewelryBeadGrain. Combines with a gem-seat boolean cut for the stone pocket.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of each stone in mm."
    },
    "bead_count_per_stone": {
      "type": "integer",
      "description": "Number of raised beads retaining each stone. Must be >= 2. Typical values: 2 (tight inline), 3, 4."
    },
    "bead_diameter": {
      "type": "number",
      "description": "Diameter of each raised bead in mm (typical 0.3\u20130.8)."
    },
    "field_layout": {
      "type": "string",
      "enum": [
        "line",
        "grid"
      ],
      "description": "'line' \u2014 single row of stones. 'grid' \u2014 rectangular array of stones."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "bead_count_per_stone",
    "bead_diameter",
    "field_layout"
  ]
}
```

---

## `jewelry_create_gypsy_pave`

Append a `jewelry_gypsy_pave` node to a `.feature` file. Generates a gypsy-pavé (star setting) — a flush-set stone with bright-cut engraved rays radiating outward from the stone's edge across the surrounding metal surface. The stone sits flush (its table level with the metal) and the `star_ray_count` V-cut rays create a decorative star or sunburst halo that catches light. Also called 'star setting' or 'bright-cut star'. Minimum ray count: 4. Output: node spec consumed by opJewelryGypsyPave.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "seat_depth": {
      "type": "number",
      "description": "Depth of the flush seat in mm (typically 60\u201380% of stone depth)."
    },
    "star_ray_count": {
      "type": "integer",
      "description": "Number of engraved star rays radiating from the stone. Must be >= 4. Typical: 6, 8, 12."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "seat_depth",
    "star_ray_count"
  ]
}
```

---

## `jewelry_create_illusion`

Append a `jewelry_illusion` node to a `.feature` file. Generates an illusion (miracle-plate) setting — a small stone set at the centre of a larger polished metal plate whose faceted surface reflects light like the stone itself, creating the visual illusion that the stone is the size of the plate. The plate (`plate_diameter`) must be larger than `stone_diameter`. The plate surface is divided into `facet_count` radial mirror-polished faces (minimum 4). Output: node spec consumed by opJewelryIllusion.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the actual stone in mm."
    },
    "plate_diameter": {
      "type": "number",
      "description": "Outer diameter of the illusion plate in mm. Must be > stone_diameter."
    },
    "facet_count": {
      "type": "integer",
      "description": "Number of radial mirror facets on the plate surround. Must be >= 4. Typical: 8, 12, 16."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "plate_diameter",
    "facet_count"
  ]
}
```

---

## `jewelry_create_invisible`

Append a `jewelry_invisible` node to a `.feature` file. Generates an invisible setting — a `grid_rows` × `grid_cols` array of princess (square) or calibrated stones held on a concealed rail framework with no visible metal between adjacent stones. Each stone's girdle has a groove that fits over the crossed rails; from above the stones appear as a continuous, metal-free surface. Rail geometry is defined by `rail_width` and `rail_height`. The evaluate result includes `seat_positions` for downstream boolean stone-pocket cutting. Output: node spec consumed by opJewelryInvisible.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_size": {
      "type": "number",
      "description": "Side length (diameter) of each square stone in mm."
    },
    "rail_width": {
      "type": "number",
      "description": "Width of each hidden rail in mm (typical 0.2\u20130.5)."
    },
    "rail_height": {
      "type": "number",
      "description": "Height (thickness) of each rail in mm (typical 0.5\u20131.5)."
    },
    "grid_rows": {
      "type": "integer",
      "description": "Number of stone rows in the grid. Must be >= 1."
    },
    "grid_cols": {
      "type": "integer",
      "description": "Number of stone columns in the grid. Must be >= 1."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_size",
    "rail_width",
    "rail_height",
    "grid_rows",
    "grid_cols"
  ]
}
```

---

## `jewelry_create_prong_variant`

Append a `jewelry_prong_variant` node to a `.feature` file. Generates one of six specialised prong-wire variants (double, claw, V, fishtail, split, decorative) sized to the stone. All variants share `stone_diameter`, `prong_count`, `wire_gauge`, and `prong_height`; each adds a variant-specific parameter. 

Variants:
- **`double_prong`** — two side-by-side wires per prong position. `variant_param` = gap between wires in mm (default 0.3).
- **`claw_prong`** — curved claw tip hooks over the girdle. `variant_param` = claw hook depth in mm (default 0.4).
- **`v_prong`** — V-shaped prong for pointed stones (marquise/pear/princess). `variant_param` = V half-angle in degrees (default 45).
- **`fishtail_prong`** — split fishtail tip for decorative look. `variant_param` = fishtail spread width in mm (default 0.8).
- **`split_prong`** — prong split into two tines from mid-height. `variant_param` = split start as fraction of prong_height (default 0.5).
- **`decorative_prong`** — custom cross-section profile. `variant_profile` selects profile: `round`, `tapered`, `filigree`, `star`, `leaf`.

Output: node spec consumed by the OCCT worker's opJewelryProngVariant handler.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "variant": {
      "type": "string",
      "enum": [
        "claw_prong",
        "decorative_prong",
        "double_prong",
        "fishtail_prong",
        "split_prong",
        "v_prong"
      ],
      "description": "Prong variant type."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "prong_count": {
      "type": "integer",
      "description": "Number of prong positions around the stone (typically 4 or 6)."
    },
    "wire_gauge": {
      "type": "number",
      "description": "Prong wire diameter in mm (typical 0.8\u20131.5)."
    },
    "prong_height": {
      "type": "number",
      "description": "Height the prong extends above the stone's girdle plane in mm."
    },
    "variant_param": {
      "type": "number",
      "description": "Variant-specific numeric parameter (see variant descriptions above). Default 0.0 (worker uses built-in default for each variant)."
    },
    "variant_profile": {
      "type": "string",
      "enum": [
        "filigree",
        "leaf",
        "round",
        "star",
        "tapered"
      ],
      "description": "Profile for `decorative_prong` variant. One of: round, tapered, filigree, star, leaf. Ignored for all other variants."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "variant",
    "stone_diameter",
    "prong_count",
    "wire_gauge",
    "prong_height"
  ]
}
```

---

## `jewelry_create_head_gallery`

Append a `jewelry_head_gallery` node to a `.feature` file. Generates a basket/peg head (open framework that accepts a stone seat) combined with a decorative gallery rail running below the head. The head's `head_diameter` should match the stone-setting diameter of a companion `jewelry_create_prong_head` or `jewelry_create_bezel` node. 

Gallery styles:
- **`plain`** — a plain round-wire or rectangular strip.
- **`scalloped`** — U-shaped scallops cut from the lower rail edge at `motif_pitch` intervals.
- **`milgrain_edge`** — rows of tiny raised milgrain beads along both edges; `motif_pitch` = bead diameter.
- **`pierced`** — open pierced motifs repeating at `motif_pitch` intervals.
- **`filigree`** — filigree wire-work lattice; `motif_pitch` = cell size.

Output: node spec consumed by the OCCT worker's opJewelryHeadGallery handler.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "head_diameter": {
      "type": "number",
      "description": "Outer diameter of the head basket in mm."
    },
    "head_height": {
      "type": "number",
      "description": "Height of the head basket in mm."
    },
    "gallery_height": {
      "type": "number",
      "description": "Height of the gallery rail band below the head in mm."
    },
    "gallery_style": {
      "type": "string",
      "enum": [
        "filigree",
        "milgrain_edge",
        "pierced",
        "plain",
        "scalloped"
      ],
      "description": "Decorative style of the gallery rail."
    },
    "motif_pitch": {
      "type": "number",
      "description": "Motif repeat pitch in mm (scallop c-c, milgrain bead diameter, pierced motif c-c, or filigree cell size). Set to 0 for `plain` style. Must be >= 0."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "head_diameter",
    "head_height",
    "gallery_height",
    "gallery_style",
    "motif_pitch"
  ]
}
```

---

## `jewelry_create_under_bezel`

Append a `jewelry_under_bezel` node to a `.feature` file. Generates a sub-collet (under-bezel) — a short metal collar that sits beneath the stone and raises it above the shank. Used as a secondary support under bezels, halos, or other settings where the stone needs to be elevated. The collet has inner bore = `stone_diameter`, outer wall = `stone_diameter + 2 × wall_thickness`, and height = `collet_height`. A flat base plate of `base_diameter` × `base_thickness` extends below the collet for fusing onto a shank. Output: a TopoDS_Solid consumed by opJewelryUnderBezel.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "wall_thickness": {
      "type": "number",
      "description": "Wall thickness of the collet in mm (typical 0.3\u20130.8)."
    },
    "collet_height": {
      "type": "number",
      "description": "Height of the collet tube in mm."
    },
    "base_diameter": {
      "type": "number",
      "description": "Diameter of the flat base plate in mm. Must be >= stone_diameter + 2 \u00d7 wall_thickness."
    },
    "base_thickness": {
      "type": "number",
      "description": "Thickness of the base plate in mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "wall_thickness",
    "collet_height",
    "base_diameter",
    "base_thickness"
  ]
}
```

---

## `jewelry_create_peg_setting`

Append a `jewelry_peg_setting` node to a `.feature` file. Generates a peg (post) setting for earrings and pendants — a cylindrical post with a shallow stone-cup at the top and an optional base disc. The stone sits in the cup (held by adhesive or a small retaining ledge); the peg solders into an earring back or pendant finding. Parameters: `stone_diameter` for the cup seat, `peg_diameter` / `peg_length` for the post, and `base_diameter` / `base_thickness` for the soldering foot. Output: a TopoDS_Solid consumed by opJewelryPegSetting.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm (sets the cup seat size)."
    },
    "peg_diameter": {
      "type": "number",
      "description": "Diameter of the cylindrical post in mm."
    },
    "peg_length": {
      "type": "number",
      "description": "Length (height) of the post in mm."
    },
    "base_diameter": {
      "type": "number",
      "description": "Diameter of the soldering base disc in mm. Must be >= peg_diameter."
    },
    "base_thickness": {
      "type": "number",
      "description": "Thickness of the base disc in mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "peg_diameter",
    "peg_length",
    "base_diameter",
    "base_thickness"
  ]
}
```

---

## `jewelry_create_coronet`

Append a `jewelry_coronet` node to a `.feature` file. Generates a crown (coronet) setting — a tapered arrangement of `prong_count` graduated prong wires that lean inward toward the stone and form a regal coronet silhouette typical of antique and Victorian jewellery. Each prong wire has diameter `wire_gauge` and rises to `crown_height` above the girdle plane, tapering inward by `taper` mm (0 = straight; typical 0.2–0.6 mm for the classic dome effect). The setting base is a short cylinder fused onto a shank. Output: node spec consumed by the OCCT worker's opJewelryCoronet handler.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "prong_count": {
      "type": "integer",
      "description": "Number of prongs in the coronet (typically 6, 8, or 10)."
    },
    "crown_height": {
      "type": "number",
      "description": "Height the prongs rise above the girdle plane in mm."
    },
    "taper": {
      "type": "number",
      "description": "Inward lean of each prong tip relative to its base in mm. 0 = straight prongs. Positive = lean inward (coronet dome); must be < wire_gauge so tips remain solid."
    },
    "wire_gauge": {
      "type": "number",
      "description": "Prong wire diameter in mm (typical 0.8\u20131.5)."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "prong_count",
    "crown_height",
    "taper",
    "wire_gauge"
  ]
}
```

---

## `jewelry_create_suspension_mount`

Append a `jewelry_suspension_mount` node to a `.feature` file. Generates an articulated dangle mount for drop earrings and pendants — a stone seat attached to a jump-ring-style pivot loop that lets the setting swing freely on an ear wire or pendant bail. 

Seat styles:
- **`bezel_cup`** — a full bezel collar seat.
- **`prong_cup`** — an open prong-head cup (typically 4 prongs).
- **`claw_cup`** — a claw-tip prong cup for maximum stone visibility.

The pivot ring is sized by `ring_inner_diameter` (the passage diameter through which the ear wire or bail slides) and `ring_wire_diameter` (the ring cross-section). A short `bail_height` cylinder connects the seat to the ring. Output: node spec consumed by opJewelrySuspensionMount.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "seat_style": {
      "type": "string",
      "enum": [
        "bezel_cup",
        "claw_cup",
        "prong_cup"
      ],
      "description": "Stone seat type. 'bezel_cup': full bezel collar. 'prong_cup': open 4-prong cup. 'claw_cup': claw-tip prong cup."
    },
    "seat_depth": {
      "type": "number",
      "description": "Depth of the stone seat in mm (typically 40\u201360% of stone depth)."
    },
    "ring_wire_diameter": {
      "type": "number",
      "description": "Wire cross-section diameter of the pivot jump ring in mm (typical 0.7\u20131.2)."
    },
    "ring_inner_diameter": {
      "type": "number",
      "description": "Inner passage diameter of the pivot ring in mm. Must be > ring_wire_diameter."
    },
    "bail_height": {
      "type": "number",
      "description": "Height of the bail cylinder connecting seat to pivot ring in mm (typical 1.0\u20133.0)."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "seat_style",
    "seat_depth",
    "ring_wire_diameter",
    "ring_inner_diameter",
    "bail_height"
  ]
}
```

---

## `jewelry_create_vtip_protector`

Append a `jewelry_vtip_protector` node to a `.feature` file. Generates protective V-tip metal caps for the pointed corners of fancy-cut stones (pear, marquise, heart, trillion). Each cap is a V-channel sleeve that wraps snugly around the stone's sharp corner to prevent chipping during wear. 

Stone shapes supported:
- **`pear`** — 1 pointed tip (bottom culet) or 2 (top and bottom).
- **`marquise`** — 2 pointed tips (both ends of the oval).
- **`heart`** — 2 tips (the two lower lobes of the cleft).
- **`trillion`** — 3 tips (one per corner of the triangular stone).

The V-channel internal angle `seat_angle_deg` must match the stone's corner included angle for a snug fit (typical 40–70° pear/marquise; 60° trillion). `tip_count` overrides the default count if you need custom cap placement. Output: node spec consumed by opJewelryVtipProtector.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_shape": {
      "type": "string",
      "enum": [
        "heart",
        "marquise",
        "pear",
        "trillion"
      ],
      "description": "Shape of the fancy-cut stone. One of: pear, marquise, heart, trillion."
    },
    "tip_count": {
      "type": "integer",
      "description": "Number of V-tip caps to generate. Default per shape: pear=1, marquise=2, heart=2, trillion=3. Must be >= 1."
    },
    "tip_width": {
      "type": "number",
      "description": "Width of the V-channel opening at the base in mm (typical 0.4\u20131.0)."
    },
    "tip_length": {
      "type": "number",
      "description": "Length of the cap along the stone edge from the corner in mm (typical 0.5\u20131.5)."
    },
    "wall_thickness": {
      "type": "number",
      "description": "Wall thickness of the V-channel cap in mm (typical 0.2\u20130.5)."
    },
    "seat_angle_deg": {
      "type": "number",
      "description": "Internal angle of the V-channel in degrees \u2014 must match the stone's corner included angle. Typical: 40\u201370\u00b0 (pear/marquise), 60\u00b0 (trillion). Must be in (0, 180)."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_shape",
    "tip_count",
    "tip_width",
    "tip_length",
    "wall_thickness",
    "seat_angle_deg"
  ]
}
```

---

## `jewelry_create_bombe_cluster`

Append a `jewelry_bombe_cluster` node to a `.feature` file. Generates a bombé (dome) cluster setting — a strongly domed multi-stone cluster where stone seats are distributed across a spherical cap surface. Unlike the flat `jewelry_cluster`, the bombé uses a full spherical-cap dome geometry described by `dome_radius` and `cap_half_angle_deg`. Stones are placed using a Fibonacci-spiral layout for even coverage. `stone_count` stones of `stone_size` are distributed across the dome; a flat base ring of `base_height` closes the bottom for shank attachment. Output: node spec consumed by opJewelryBombeCluster. The evaluate result includes `seat_positions` — per-stone world-space transforms on the dome.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "dome_radius": {
      "type": "number",
      "description": "Radius of the spherical dome in mm (typical 4\u201315 mm)."
    },
    "stone_size": {
      "type": "number",
      "description": "Girdle diameter of each stone in the cluster in mm."
    },
    "stone_count": {
      "type": "integer",
      "description": "Number of stones distributed across the dome. Must be >= 1."
    },
    "cap_half_angle_deg": {
      "type": "number",
      "description": "Half-angle subtended by the dome cap at the sphere centre, in degrees. Controls how much of the sphere is visible. Typical range: 45\u201380\u00b0. Must be in (0, 90)."
    },
    "base_height": {
      "type": "number",
      "description": "Height of the flat base ring at the cap equator in mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "dome_radius",
    "stone_size",
    "stone_count",
    "cap_half_angle_deg",
    "base_height"
  ]
}
```

---

## `jewelry_create_patterned_bezel`

Append a `jewelry_patterned_bezel` node to a `.feature` file. Generates a decorative bezel collar with a repeating patterned outline — lotus petal, compass point, or star-notch — cut into the bezel wall. 

Patterns:
- **`lotus`** — rounded petal cutouts from the top edge; classic floral look popular in Indian and Art Nouveau jewellery.
- **`compass`** — pointed projections at `petal_count` compass directions extending outward beyond the stone (compass rose / sun-ray bezel).
- **`star`** — V-notch star outline along the top edge, creating alternating peaks and valleys (star bezel).
- **`plain`** — a standard full bezel with no decorative cutouts.

`petal_count` controls the number of repeating motif units (typical 6–16). The `bearing_ledge_height` stone seat is unaffected by the pattern. Output: node spec consumed by opJewelryPatternedBezel.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "wall_thickness": {
      "type": "number",
      "description": "Bezel wall thickness in mm (typical 0.3\u20130.8)."
    },
    "bezel_height": {
      "type": "number",
      "description": "Total height of the bezel collar in mm."
    },
    "bearing_ledge_height": {
      "type": "number",
      "description": "Height of the bearing ledge from base in mm. Must be < bezel_height."
    },
    "pattern": {
      "type": "string",
      "enum": [
        "compass",
        "lotus",
        "plain",
        "star"
      ],
      "description": "Decorative pattern for the bezel collar. One of: lotus, compass, star, plain."
    },
    "petal_count": {
      "type": "integer",
      "description": "Number of repeating decorative motif units around the collar. Must be >= 3. Typical: 6, 8, 12, 16. Ignored for 'plain' pattern."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "wall_thickness",
    "bezel_height",
    "bearing_ledge_height",
    "pattern",
    "petal_count"
  ]
}
```

---

## `jewelry_create_trellis_prong`

Append a `jewelry_trellis_prong` node to a `.feature` file. Generates a trellis (cross-prong) basket setting — prong wires that cross each other in an interwoven pattern, forming a decorative cage around the stone. 

Weave styles:
- **`x_cross`** — adjacent prong pairs form a clean X; wires pass over/under alternately (plain weave).
- **`diagonal`** — all crossing wires slant the same direction (twill style), creating diagonal hatching.
- **`square`** — straight prongs connected by horizontal cross-bars at `cross_height` (square lattice look).

`prong_count` must be even (pairs cross each other). `cross_height` sets the height above the girdle plane where wires cross. Output: node spec consumed by opJewelryTrellisProng.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_diameter": {
      "type": "number",
      "description": "Girdle diameter of the stone in mm."
    },
    "prong_count": {
      "type": "integer",
      "description": "Number of prong wires. Must be even (>= 4) so wires pair for crossing. Typical: 4, 6, 8."
    },
    "wire_gauge": {
      "type": "number",
      "description": "Prong wire diameter in mm (typical 0.8\u20131.5)."
    },
    "prong_height": {
      "type": "number",
      "description": "Height the prong extends above the stone's girdle plane in mm."
    },
    "weave_style": {
      "type": "string",
      "enum": [
        "diagonal",
        "square",
        "x_cross"
      ],
      "description": "Crossing/weave pattern. One of: diagonal, square, x_cross."
    },
    "cross_height": {
      "type": "number",
      "description": "Height above the girdle plane at which adjacent prong wires cross, in mm. Must be > 0 and < prong_height."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_diameter",
    "prong_count",
    "wire_gauge",
    "prong_height",
    "weave_style",
    "cross_height"
  ]
}
```

---

## `jewelry_create_bar_channel_graduated`

Append a `jewelry_bar_channel_graduated` node to a `.feature` file. Generates a graduated-row setting combining bar separators and a channel floor — a row of stones that decreases in size from largest (centre) to smallest (ends), with a pair of metal bar pillars between each adjacent stone pair. Useful for tapered eternity bands, graduated diamond rows, and bypass rings where the stone sizes follow the ring taper. `stone_count` stones are sized linearly from `largest_diameter` to `smallest_diameter`; bars of `bar_width` × `bar_height` stand between each adjacent pair; a `floor_thickness` floor closes the bottom. The evaluate result includes `stones` — per-stone {index, diameter, x_center} for downstream boolean seat cutting. Output: node spec consumed by opJewelryBarChannelGraduated.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "stone_count": {
      "type": "integer",
      "description": "Number of stones in the graduated row. Must be >= 1."
    },
    "largest_diameter": {
      "type": "number",
      "description": "Girdle diameter of the largest (first/centre) stone in mm."
    },
    "smallest_diameter": {
      "type": "number",
      "description": "Girdle diameter of the smallest (last/end) stone in mm. Must be <= largest_diameter."
    },
    "stone_spacing": {
      "type": "number",
      "description": "Edge-to-edge gap between adjacent stones in mm (typical 0.1\u20130.3)."
    },
    "bar_width": {
      "type": "number",
      "description": "Width (thickness) of each bar pillar between stones in mm (typical 0.4\u20131.0)."
    },
    "bar_height": {
      "type": "number",
      "description": "Height of the bar pillars above the stone seat in mm (typical 0.5\u20131.5)."
    },
    "floor_thickness": {
      "type": "number",
      "description": "Thickness of the channel floor in mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "stone_count",
    "largest_diameter",
    "smallest_diameter",
    "stone_spacing",
    "bar_width",
    "bar_height",
    "floor_thickness"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
