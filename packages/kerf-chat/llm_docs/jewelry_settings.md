# Jewelry setting generators

Nineteen LLM tools create parametric stone-setting solids as `.feature` nodes.
Each tool appends a node to an existing `.feature` file; the OCCT worker
evaluates the node and returns a `TopoDS_Solid` (or placement data for array
settings like pavé, halo, and cluster).

Units: millimetres throughout.

---

## `jewelry_create_prong_head`

Generates a prong-head setting that holds a gemstone above a shank.

### How it works

1. A cylindrical bearing seat (diameter = `stone_diameter + 2 × prong_wire_diameter`)
   carries the stone at a `seat_angle_deg` chamfer.
2. `prong_count` round prong wires (diameter = `prong_wire_diameter`) are
   distributed evenly around the stone, rising `prong_height` above the girdle
   plane.
3. Style variants:
   - **`standard`** — plain prongs, no connecting rail.
   - **`basket`** — one or more horizontal band rails connecting alternate prong
     bases (set `basket_rail_count` ≥ 1).
   - **`trellis`** — diagonal cross-members between adjacent prong pairs; creates
     an X-pattern viewed from below.
   - **`cathedral`** — arch ribs ascending from the prong bases to a lower shank
     seat, giving a higher-set look typical of solitaire engagement rings.

### Parameters

| Parameter            | Required | Default     | Notes                                        |
|----------------------|----------|-------------|----------------------------------------------|
| `file_id`            | yes      | —           | Target `.feature` file uuid                  |
| `stone_diameter`     | yes      | —           | Girdle diameter in mm (e.g. 6.5 for 1 ct round) |
| `prong_count`        | yes      | —           | `4` (square set) or `6` (Tiffany)            |
| `prong_wire_diameter`| yes      | —           | Prong wire diameter in mm (typical 0.8–1.5)  |
| `prong_height`       | yes      | —           | Height above girdle plane in mm              |
| `head_style`         | no       | `"standard"`| `standard`, `basket`, `trellis`, `cathedral` |
| `basket_rail_count`  | no       | `1`         | Rails for basket/trellis; ignored for standard |
| `seat_angle_deg`     | no       | `15`        | Bearing-ledge chamfer angle in degrees       |
| `id`                 | no       | auto        | Explicit node id                             |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 6.5,
  "prong_count": 6,
  "prong_wire_diameter": 1.0,
  "prong_height": 2.2,
  "head_style": "basket",
  "basket_rail_count": 1,
  "seat_angle_deg": 15
}
```

Result node op: `jewelry_prong_head`. Boolean-fuse onto a `sweep1` ring shank
to complete the solitaire head.

---

## `jewelry_create_bezel`

Generates a full or partial bezel collar that surrounds the stone's girdle.

### How it works

A cylinder of inner diameter = `stone_diameter` and outer diameter =
`stone_diameter + 2 × wall_thickness` is extruded to `bezel_height`. A
horizontal bearing ledge at `bearing_ledge_height` provides the seat for the
stone's girdle.

Style variants:
- **`full`** — 360° collar; classic gold bezel.
- **`partial`** — a gap of `partial_opening_deg` degrees is cut from the front
  face. Typical for east-west oval, marquise, or pear stones that need visual
  access from the side. Opening must be in [1, 359°].
- **`collet`** — minimal-wall tube bezel (collet). Taper optional via
  `taper_angle_deg`.
- **`tapered`** — outer wall inclines inward at `taper_angle_deg` degrees
  (rub-over / gypsy look). Requires `taper_angle_deg > 0`.

### Parameters

| Parameter              | Required | Default  | Notes                                           |
|------------------------|----------|----------|-------------------------------------------------|
| `file_id`              | yes      | —        | Target `.feature` file uuid                     |
| `stone_diameter`       | yes      | —        | Girdle diameter in mm                           |
| `wall_thickness`       | yes      | —        | Bezel wall thickness in mm (typical 0.3–0.8)    |
| `bezel_height`         | yes      | —        | Total height of the collar in mm                |
| `bearing_ledge_height` | yes      | —        | Height of the stone seat from base; must be < `bezel_height` |
| `bezel_style`          | no       | `"full"` | `full`, `partial`, `collet`, `tapered`          |
| `partial_opening_deg`  | no       | `60`     | Gap degrees for partial style [1, 359]          |
| `taper_angle_deg`      | no       | `0`      | Outer wall inward taper (≥ 0°)                  |
| `id`                   | no       | auto     | Explicit node id                                |

### Worked example — partial east-west oval bezel

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 9.0,
  "wall_thickness": 0.55,
  "bezel_height": 3.2,
  "bearing_ledge_height": 1.3,
  "bezel_style": "partial",
  "partial_opening_deg": 110
}
```

Result node op: `jewelry_bezel`.

---

## `jewelry_create_channel`

Generates a channel setting — two parallel rails with a connecting floor — for
a calibrated row of stones.

### How it works

1. Two vertical rails of height = `rail_height` and thickness = `rail_thickness`
   are placed parallel, separated by `stone_diameter` (inner face-to-face).
2. A floor of thickness = `floor_thickness` connects the rails underneath.
3. Stones are distributed at `stone_spacing` centre-to-centre along the X-axis.
4. The worker's evaluate result includes `seat_positions` — an array of per-stone
   XYZ positions in the channel's local frame — so a downstream boolean can cut
   individual calibrated stone seats.

Channel total length = `stone_count × stone_spacing`.

### Parameters

| Parameter        | Required | Notes                                                               |
|------------------|----------|---------------------------------------------------------------------|
| `file_id`        | yes      | Target `.feature` file uuid                                         |
| `stone_diameter` | yes      | Stone girdle width in mm                                            |
| `stone_count`    | yes      | Number of stones in the row (≥ 1)                                   |
| `stone_spacing`  | yes      | Centre-to-centre spacing in mm. Must be > `stone_diameter`          |
| `rail_height`    | yes      | Height of the rail above the stone seat in mm                       |
| `rail_thickness` | yes      | Rail wall thickness in mm                                           |
| `floor_thickness`| yes      | Channel floor thickness in mm                                       |
| `id`             | no       | Explicit node id                                                    |

### Worked example — 7-stone channel in a band ring

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 2.5,
  "stone_count": 7,
  "stone_spacing": 2.8,
  "rail_height": 1.5,
  "rail_thickness": 0.5,
  "floor_thickness": 0.4
}
```

Channel length = 7 × 2.8 = 19.6 mm. Result node op: `jewelry_channel`.

**Downstream seat cutting**: pair with a `feature_boolean` `cut` loop that
references each element in `seat_positions`, or use a future `gem_seat` op once
it lands.

---

## `jewelry_pave_array`

Distributes stone placements across a rectangular region using a hex-offset
grid and returns the array of placement transforms.

### How it works

1. The usable region is `region_width − 2 × edge_margin` × `region_height − 2 × edge_margin`.
2. Column pitch = `stone_diameter + stone_spacing` (centre-to-centre).
3. Grid rows are evenly spaced at the same pitch.
4. Odd rows are shifted by half a column pitch (hex-offset layout) for tighter
   packing and the characteristic pavé bead appearance.
5. Stones whose edge circle would fall outside the usable boundary are filtered
   out automatically.
6. The node stores `placements` — an array of `{u, v, row, col}` dicts where
   `u`, `v` are fractional coordinates [0, 1] across the region.
7. The OCCT worker converts `{u, v}` coordinates to full world-space transforms
   using `surface_normal` and `surface_origin`, and posts them in the evaluate
   result's `transforms` array.

**This tool does NOT cut stone seats.** It records placements only. To produce
actual seat geometry, pair with a downstream boolean-cut loop or a `gem_seat`
operation.

### Parameters

| Parameter        | Required | Default       | Notes                                             |
|------------------|----------|---------------|---------------------------------------------------|
| `file_id`        | yes      | —             | Target `.feature` file uuid                       |
| `region_width`   | yes      | —             | X-extent of the pavé region in mm                 |
| `region_height`  | yes      | —             | Y-extent of the pavé region in mm                 |
| `stone_diameter` | yes      | —             | Stone girdle diameter in mm                       |
| `stone_spacing`  | yes      | —             | Gap between stone edges in mm (≥ 0)               |
| `edge_margin`    | yes      | —             | Minimum margin from boundary to stone edge in mm  |
| `surface_normal` | no       | `[0, 0, 1]`  | World-space surface normal [nx, ny, nz]           |
| `surface_origin` | no       | `[0, 0, 0]`  | World-space origin of the region [x, y, z]        |
| `id`             | no       | auto          | Explicit node id                                  |

### Worked example — pavé on a ring shoulder

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "region_width": 12.0,
  "region_height": 4.0,
  "stone_diameter": 1.5,
  "stone_spacing": 0.2,
  "edge_margin": 0.5,
  "surface_normal": [0.0, 1.0, 0.0],
  "surface_origin": [0.0, 5.0, 0.0]
}
```

Result node op: `jewelry_pave`. The evaluate result contains `placement_count`
and `transforms` (4×4 column-major matrices in world space).

### Packing tips

- Tighter spacing (`stone_spacing = 0.1–0.15 mm`) increases stone count and
  creates the dense pavé look; allow extra polish time for the setter.
- Set `edge_margin ≈ stone_diameter / 2` so the outermost stones clear the
  metal boundary cleanly.
- On curved surfaces (ring shoulders), apply the `jewelry_pave` node with the
  correct `surface_normal`; the worker projects placements onto the face normal
  at evaluation time.

---

## `jewelry_create_tension`

Generates a tension setting where the stone is held by spring pressure between
two opposing band ends — no prongs or bezel.

### How it works

1. Two band-end bodies of thickness `band_thickness` face each other with a
   gap of `gap` between them.  The stone diameter must exceed `gap` so the
   stone is retained by the spring tension.
2. Each facing surface has an inward-curved bearing rail of width `rail_width`
   and depth `rail_depth` that grips the stone's girdle.

Derived node hints: `_seat_radius` (= stone_diameter / 2),
`_band_spread` (= stone_diameter + gap).

### Parameters

| Parameter        | Required | Notes                                                              |
|------------------|----------|--------------------------------------------------------------------|
| `file_id`        | yes      | Target `.feature` file uuid                                        |
| `stone_diameter` | yes      | Girdle diameter of the stone in mm                                 |
| `band_thickness` | yes      | Thickness of the band metal at the setting point in mm (2.0–4.0)  |
| `gap`            | yes      | Gap between band-end faces in mm. Must be < `stone_diameter`       |
| `rail_width`     | yes      | Width of the bearing rail in mm (typical 0.3–0.8)                  |
| `rail_depth`     | yes      | Depth of the bearing rail notch in mm (typical 0.2–0.5)            |
| `id`             | no       | Explicit node id                                                   |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 6.5,
  "band_thickness": 3.2,
  "gap": 5.8,
  "rail_width": 0.5,
  "rail_depth": 0.3
}
```

Result node op: `jewelry_tension`. The evaluate result posts two band-end
`TopoDS_Solid` bodies.

---

## `jewelry_create_flush`

Generates a flush (gypsy) setting where the stone is set into a drilled seat
so its table sits level with the surrounding metal surface.

### How it works

1. A cylindrical seat of diameter `stone_diameter` and depth `seat_depth` is
   drilled into the metal.
2. A chamfered opening edge of width `bevel_width` at `bevel_angle_deg`
   eases the stone in and catches light.

Derived node hints:
- `_seat_volume_approx` = π r² × seat_depth (mm³) — material-removal estimate.
- `_opening_diameter` = stone_diameter + 2 × bevel_width × tan(bevel_angle_deg).

### Parameters

| Parameter         | Required | Notes                                                              |
|-------------------|----------|--------------------------------------------------------------------|
| `file_id`         | yes      | Target `.feature` file uuid                                        |
| `stone_diameter`  | yes      | Girdle diameter of the stone in mm                                 |
| `seat_depth`      | yes      | Depth of the drilled seat in mm (typically 60–80% of stone depth)  |
| `bevel_width`     | yes      | Width of the opening chamfer in mm (typical 0.1–0.3)               |
| `bevel_angle_deg` | yes      | Angle of the bevel in degrees. Must be < 90°. Typical: 30–60°      |
| `id`              | no       | Explicit node id                                                   |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 3.5,
  "seat_depth": 1.8,
  "bevel_width": 0.2,
  "bevel_angle_deg": 45
}
```

Result node op: `jewelry_flush`. Pair with a `feature_boolean` cut against
the parent metal body to produce the actual seat pocket.

---

## `jewelry_create_halo`

Generates a halo setting — a ring of small accent stones surrounding a center
stone seat.

### How it works

1. A ring of `halo_stone_count` accent stones of diameter `halo_stone_size`
   is placed evenly at a radial distance of `halo_gap` from the center stone
   edge.
2. A metal halo frame of width `halo_metal_width` surrounds the accent ring.

**The center stone seat is NOT generated by this tool.** Add a
`jewelry_create_prong_head` or `jewelry_create_bezel` node separately for the
center stone.

Derived node hints:
- `_halo_radius` = center_diameter/2 + halo_gap + halo_stone_size/2.
- `_halo_outer_diameter` = 2 × (halo_radius + halo_stone_size/2 + halo_metal_width).
- `_accent_pitch_deg` = 360 / halo_stone_count.

### Parameters

| Parameter          | Required | Notes                                                             |
|--------------------|----------|-------------------------------------------------------------------|
| `file_id`          | yes      | Target `.feature` file uuid                                       |
| `center_diameter`  | yes      | Girdle diameter of the center stone in mm                         |
| `halo_stone_size`  | yes      | Diameter of each halo accent stone in mm (typical 1.0–1.8)       |
| `halo_stone_count` | yes      | Number of accent stones (typical 14–32). Must be >= 3             |
| `halo_gap`         | yes      | Radial gap from center stone edge to halo stone edge in mm        |
| `halo_metal_width` | yes      | Width of the metal halo frame in mm (typical 0.3–0.6)             |
| `id`               | no       | Explicit node id                                                  |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "center_diameter": 6.5,
  "halo_stone_size": 1.2,
  "halo_stone_count": 18,
  "halo_gap": 0.15,
  "halo_metal_width": 0.4
}
```

Result node op: `jewelry_halo`. The halo outer diameter for this example is
approximately 10.9 mm.

---

## `jewelry_create_three_stone`

Generates a three-stone setting — a center stone flanked by two graduated
side stones on a shared base/gallery.

### How it works

1. A center stone seat of diameter `center_diameter` is placed at the origin.
2. Two side stone seats of diameter `side_diameter` are placed at
   ±(center_diameter/2 + stone_spacing + side_diameter/2) along the X-axis.
3. A shared base of height `base_height` connects all three seats.

Derived node hints:
- `_side_offset_x` = center_diameter/2 + stone_spacing + side_diameter/2.
- `_total_width` = 2 × _side_offset_x + side_diameter.

### Parameters

| Parameter         | Required | Notes                                                              |
|-------------------|----------|--------------------------------------------------------------------|
| `file_id`         | yes      | Target `.feature` file uuid                                        |
| `center_diameter` | yes      | Girdle diameter of the center stone in mm                          |
| `side_diameter`   | yes      | Girdle diameter of each side stone in mm (typically 60–75% of center) |
| `stone_spacing`   | yes      | Gap between adjacent stone edges in mm (typical 0.1–0.3)           |
| `base_height`     | yes      | Height of the shared gallery base in mm                            |
| `id`              | no       | Explicit node id                                                   |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "center_diameter": 6.5,
  "side_diameter": 4.0,
  "stone_spacing": 0.2,
  "base_height": 1.5
}
```

Result node op: `jewelry_three_stone`. Total width for this example is
≈ 15.7 mm. The evaluate result includes `seat_positions` — three XYZ
positions in local frame — for downstream individual seat cutting.

---

## `jewelry_create_cluster`

Generates a cluster setting where multiple small stones are grouped on a
domed base to read visually as one larger stone.

### How it works

1. `stone_count` stones of `stone_size` are arranged on a circular platform
   of `cluster_diameter`.  Stone centres are placed on a ring of radius =
   cluster_diameter/2 − stone_size/2 (evenly spaced angularly).
2. A single-stone cluster places the stone at the origin.
3. The base dome profile has height `dome_height` (use 0.0 for a flat base).

Derived node hints:
- `positions` — list of {x, y, angle_deg} dicts in the cluster's local XY plane.
- `_placement_radius` — radial distance of stone centres from the cluster axis.
- `_actual_count` — matches `stone_count`.

### Parameters

| Parameter          | Required | Notes                                                              |
|--------------------|----------|--------------------------------------------------------------------|
| `file_id`          | yes      | Target `.feature` file uuid                                        |
| `cluster_diameter` | yes      | Overall diameter of the cluster platform in mm                     |
| `stone_size`       | yes      | Girdle diameter of each individual stone in mm                     |
| `stone_count`      | yes      | Number of stones. Must be >= 1                                     |
| `dome_height`      | yes      | Height of the dome profile in mm. Use 0.0 for flat                 |
| `id`               | no       | Explicit node id                                                   |

### Worked example — 7-stone cluster ring

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "cluster_diameter": 10.0,
  "stone_size": 1.5,
  "stone_count": 7,
  "dome_height": 1.0
}
```

Result node op: `jewelry_cluster`. The evaluate result includes `seat_positions`
(XYZ on the dome surface) for downstream seat-cutting.

---

## `jewelry_create_bar`

Generates a bar setting — two parallel metal bars running along either side of
a row of calibrated stones with no prongs between the stones.

### How it works

1. `stone_count` stone seats of `stone_diameter` are spaced at `pitch`
   centre-to-centre along the X-axis.
2. Two metal bars of cross-section `bar_width` × `bar_height` run along either
   side of the row.  The bars grip each stone's girdle; no individual prong
   separates adjacent stones, giving a clean, uninterrupted look popular in
   men's bands and eternity rings.
3. Bar inner face-to-face separation = `stone_diameter` (the worker adds
   0.05 mm per side for fit clearance).

Constraint: `pitch` > `stone_diameter`.

Derived node hints:
- `_bar_length` = `stone_count × pitch`.
- `_bar_separation` = `stone_diameter`.

### Parameters

| Parameter        | Required | Notes                                                               |
|------------------|----------|---------------------------------------------------------------------|
| `file_id`        | yes      | Target `.feature` file uuid                                         |
| `stone_diameter` | yes      | Stone girdle diameter in mm                                         |
| `bar_width`      | yes      | Width of each metal bar in mm (typical 0.4–1.0)                    |
| `bar_height`     | yes      | Height of each bar above the stone seat in mm (typical 0.5–1.2)    |
| `stone_count`    | yes      | Number of stones in the row (≥ 1)                                   |
| `pitch`          | yes      | Centre-to-centre spacing in mm. Must be > `stone_diameter`          |
| `id`             | no       | Explicit node id                                                    |

### Worked example — 5-stone bar-set eternity band segment

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 2.5,
  "bar_width": 0.6,
  "bar_height": 0.9,
  "stone_count": 5,
  "pitch": 2.9
}
```

Result node op: `jewelry_bar`. Bar length = 5 × 2.9 = 14.5 mm.

---

## `jewelry_create_bead_grain`

Generates a bead (grain) setting where each stone is held by small raised metal
beads cut up from the surrounding surface.

### How it works

1. Each stone is drilled into a seat of `stone_diameter`.
2. `bead_count_per_stone` metal beads of `bead_diameter` are raised from the
   surrounding metal and pushed over the stone's girdle edge to retain it.
   Beads are evenly spaced around each stone.
3. `field_layout` controls the multi-stone arrangement:
   - **`line`** — a single linear row of stones.
   - **`grid`** — a rectangular array of stones.

Derived node hints:
- `_bead_pitch_deg` = 360 / `bead_count_per_stone`.
- `_bead_ring_radius` = `stone_diameter` / 2.

### Parameters

| Parameter              | Required | Notes                                                         |
|------------------------|----------|---------------------------------------------------------------|
| `file_id`              | yes      | Target `.feature` file uuid                                   |
| `stone_diameter`       | yes      | Stone girdle diameter in mm                                   |
| `bead_count_per_stone` | yes      | Beads per stone (≥ 2). Typical: 2, 3, 4                      |
| `bead_diameter`        | yes      | Diameter of each raised bead in mm (typical 0.3–0.8)         |
| `field_layout`         | yes      | `"line"` or `"grid"`                                         |
| `id`                   | no       | Explicit node id                                              |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 2.0,
  "bead_count_per_stone": 4,
  "bead_diameter": 0.5,
  "field_layout": "grid"
}
```

Result node op: `jewelry_bead_grain`.

---

## `jewelry_create_gypsy_pave`

Generates a gypsy-pavé (star setting) — a flush-set stone with bright-cut
engraved rays radiating outward from the stone edge across the surrounding metal.

### How it works

1. A flush seat of `stone_diameter` × `seat_depth` is drilled into the metal
   (stone sits level with the surface).
2. `star_ray_count` V-cut bright-cut rays radiate outward from the stone's girdle
   edge, creating a decorative star or sunburst halo. Also called "star setting"
   or "bright-cut star" in the trade.

Constraint: `star_ray_count` ≥ 4.

Derived node hints:
- `_ray_pitch_deg` = 360 / `star_ray_count`.
- `_seat_radius` = `stone_diameter` / 2.

### Parameters

| Parameter        | Required | Notes                                                              |
|------------------|----------|--------------------------------------------------------------------|
| `file_id`        | yes      | Target `.feature` file uuid                                        |
| `stone_diameter` | yes      | Stone girdle diameter in mm                                        |
| `seat_depth`     | yes      | Flush seat depth in mm (typically 60–80% of stone depth)           |
| `star_ray_count` | yes      | Number of engraved rays (≥ 4). Typical: 6, 8, 12                  |
| `id`             | no       | Explicit node id                                                   |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 2.5,
  "seat_depth": 1.4,
  "star_ray_count": 8
}
```

Result node op: `jewelry_gypsy_pave`. Pair with a boolean cut against the parent
metal body.

---

## `jewelry_create_illusion`

Generates an illusion (miracle-plate) setting — a small stone surrounded by a
larger faceted metal plate that creates the visual illusion of a bigger stone.

### How it works

1. A stone seat of `stone_diameter` is placed at the centre.
2. A polished metal plate of `plate_diameter` surrounds the stone. The plate
   annular surface is divided into `facet_count` radial mirror-polished faces
   that reflect light similarly to the stone's own facets.
3. `plate_diameter` must be > `stone_diameter`.

Constraint: `facet_count` ≥ 4.

Derived node hints:
- `_plate_wall_width` = (`plate_diameter` − `stone_diameter`) / 2.
- `_facet_pitch_deg` = 360 / `facet_count`.

### Parameters

| Parameter        | Required | Notes                                                              |
|------------------|----------|--------------------------------------------------------------------|
| `file_id`        | yes      | Target `.feature` file uuid                                        |
| `stone_diameter` | yes      | Actual stone girdle diameter in mm                                 |
| `plate_diameter` | yes      | Outer diameter of the illusion plate in mm. Must be > `stone_diameter` |
| `facet_count`    | yes      | Number of radial plate facets (≥ 4). Typical: 8, 12, 16           |
| `id`             | no       | Explicit node id                                                   |

### Worked example

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 2.5,
  "plate_diameter": 5.0,
  "facet_count": 12
}
```

Result node op: `jewelry_illusion`. A 2.5 mm stone visually reads as 5 mm.

---

## `jewelry_create_invisible`

Generates an invisible setting — a grid of princess (square) stones held on a
concealed rail framework with no visible metal between adjacent stones.

### How it works

1. A `grid_rows` × `grid_cols` array of square stones of `stone_size` is laid
   out in a rectangular grid.
2. Crossed metal rails of `rail_width` × `rail_height` are hidden underneath;
   each stone's girdle has a groove that slides onto the rails. From above the
   stones appear as a continuous, metal-free surface.
3. The evaluate result includes `seat_positions` — a list of {row, col, x, y}
   dicts for downstream boolean stone-pocket cutting.

Constraints: `grid_rows` ≥ 1, `grid_cols` ≥ 1.

Derived node hints:
- `_total_width` = `grid_cols × stone_size`.
- `_total_height` = `grid_rows × stone_size`.
- `_stone_count` = `grid_rows × grid_cols`.

### Parameters

| Parameter    | Required | Notes                                                              |
|--------------|----------|--------------------------------------------------------------------|
| `file_id`    | yes      | Target `.feature` file uuid                                        |
| `stone_size` | yes      | Side length of each square stone in mm                             |
| `rail_width` | yes      | Width of each hidden rail in mm (typical 0.2–0.5)                  |
| `rail_height`| yes      | Height (thickness) of each rail in mm (typical 0.5–1.5)            |
| `grid_rows`  | yes      | Number of stone rows (≥ 1)                                         |
| `grid_cols`  | yes      | Number of stone columns (≥ 1)                                      |
| `id`         | no       | Explicit node id                                                   |

### Worked example — 2×4 invisible-set princess ring top

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_size": 3.0,
  "rail_width": 0.3,
  "rail_height": 0.8,
  "grid_rows": 2,
  "grid_cols": 4
}
```

Result node op: `jewelry_invisible`. Total setting footprint: 12 × 6 mm,
8 stones. `seat_positions` lists all 8 stone pockets for downstream cutting.

---

## `jewelry_create_prong_variant`

Generates a specialised prong-wire variant (double, claw, V, fishtail, split,
or decorative) for stones that need a different grip geometry.

### Variants

| Variant           | Description                                                         | `variant_param` meaning                        |
|-------------------|---------------------------------------------------------------------|------------------------------------------------|
| `double_prong`    | Two parallel wires per prong position — extra grip area             | Gap between the two wires in mm (default 0.3) |
| `claw_prong`      | Curved claw tip hooks over the girdle; maximum security             | Claw hook depth in mm (default 0.4)           |
| `v_prong`         | V-shaped prong for pointed-corner stones (marquise / pear / princess) | V half-angle in degrees (default 45)       |
| `fishtail_prong`  | Split fishtail tip fans over the girdle; decorative look            | Fishtail spread width in mm (default 0.8)     |
| `split_prong`     | Prong split into two tines from mid-height; bypass / two-tone rings | Split start as fraction of `prong_height` (default 0.5) |
| `decorative_prong`| Custom cross-section profile (see `variant_profile`)                | Unused; see `variant_profile`                 |

Decorative profiles (`variant_profile`): `round`, `tapered`, `filigree`, `star`, `leaf`.

### Parameters

| Parameter          | Required | Default    | Notes                                                           |
|--------------------|----------|------------|-----------------------------------------------------------------|
| `file_id`          | yes      | —          | Target `.feature` file uuid                                     |
| `variant`          | yes      | —          | One of the six variants above                                   |
| `stone_diameter`   | yes      | —          | Girdle diameter in mm                                           |
| `prong_count`      | yes      | —          | Number of prong positions (>= 2; typically 4 or 6)             |
| `wire_gauge`       | yes      | —          | Prong wire diameter in mm (typical 0.8–1.5)                    |
| `prong_height`     | yes      | —          | Height above girdle in mm                                       |
| `variant_param`    | no       | `0.0`      | Variant-specific numeric (see table); 0 = worker default       |
| `variant_profile`  | no       | `"round"`  | Profile for `decorative_prong`; ignored otherwise              |
| `id`               | no       | auto       | Explicit node id                                                |

### Worked example — claw prong for marquise

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "variant": "v_prong",
  "stone_diameter": 10.5,
  "prong_count": 4,
  "wire_gauge": 1.1,
  "prong_height": 2.8,
  "variant_param": 45
}
```

Result node op: `jewelry_prong_variant`. Boolean-fuse onto a shank.

---

## `jewelry_create_head_gallery`

Generates a basket/peg head with a decorative gallery rail below it.

### How it works

1. A basket/peg head framework of outer diameter `head_diameter` and height
   `head_height` provides an open stone seat.  Pair with a companion
   `jewelry_create_prong_head` or `jewelry_create_bezel` node (matching
   `stone_diameter`) to complete the setting.
2. A gallery rail of height `gallery_height` wraps below the head.  Five
   decorative styles are available, each tiling a motif at `motif_pitch`
   intervals around the circumference (π × `head_diameter`).

### Gallery styles

| Style           | Description                                          |
|-----------------|------------------------------------------------------|
| `plain`         | Plain round-wire or rectangular strip; no tiling    |
| `scalloped`     | U-shaped scallops on the lower rail edge            |
| `milgrain_edge` | Rows of raised milgrain beads on both edges         |
| `pierced`       | Open pierced motifs; openwork appearance            |
| `filigree`      | Fine wire-work lattice across the entire rail face  |

### Parameters

| Parameter        | Required | Default    | Notes                                                                       |
|------------------|----------|------------|-----------------------------------------------------------------------------|
| `file_id`        | yes      | —          | Target `.feature` file uuid                                                 |
| `head_diameter`  | yes      | —          | Outer diameter of the head basket in mm                                     |
| `head_height`    | yes      | —          | Height of the basket framework in mm                                        |
| `gallery_height` | yes      | —          | Height of the gallery rail band in mm                                       |
| `gallery_style`  | yes      | —          | Style of the gallery decoration (see table above)                           |
| `motif_pitch`    | yes      | —          | Motif repeat pitch in mm; set to `0` for `plain`. Must be > 0 for others   |
| `id`             | no       | auto       | Explicit node id                                                            |

### Worked example — scalloped gallery under a 6-prong head

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "head_diameter": 9.5,
  "head_height": 3.5,
  "gallery_height": 1.2,
  "gallery_style": "scalloped",
  "motif_pitch": 1.5
}
```

Result node op: `jewelry_head_gallery`. Fuse onto a shank with a boolean union.

---

## `jewelry_create_under_bezel`

Generates a sub-collet (under-bezel) that elevates a stone above the shank.

### How it works

A short annular collet of inner bore = `stone_diameter` and wall thickness
= `wall_thickness` rises to `collet_height`.  A flat base disc of
`base_diameter` × `base_thickness` extends outward at the foot for soldering
onto the shank.  Use as secondary support beneath bezels, halos, or any
setting that needs the stone raised higher.

`base_diameter` must be >= `stone_diameter + 2 × wall_thickness`.

### Parameters

| Parameter         | Required | Notes                                                              |
|-------------------|----------|--------------------------------------------------------------------|
| `file_id`         | yes      | Target `.feature` file uuid                                        |
| `stone_diameter`  | yes      | Stone girdle diameter in mm                                        |
| `wall_thickness`  | yes      | Collet wall thickness in mm (typical 0.3–0.8)                     |
| `collet_height`   | yes      | Height of the collet tube in mm                                    |
| `base_diameter`   | yes      | Base disc diameter in mm (>= stone_diameter + 2 × wall_thickness) |
| `base_thickness`  | yes      | Base disc thickness in mm                                          |
| `id`              | no       | Explicit node id                                                   |

### Worked example — under-bezel for a bezel-set oval

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 9.0,
  "wall_thickness": 0.5,
  "collet_height": 2.5,
  "base_diameter": 11.0,
  "base_thickness": 0.4
}
```

Result node op: `jewelry_under_bezel`. Fuse onto a shank; place a bezel node
directly on top.

---

## `jewelry_create_peg_setting`

Generates a peg (post) setting for earrings and pendants.

### How it works

A cylindrical post of `peg_diameter` × `peg_length` has a shallow cup at its
top (inner diameter = `stone_diameter`) that holds the stone with adhesive or
a retaining ledge.  An optional base disc of `base_diameter` × `base_thickness`
at the foot of the post solders into an earring back or pendant finding.

`base_diameter` must be >= `peg_diameter`.

### Parameters

| Parameter         | Required | Notes                                               |
|-------------------|----------|-----------------------------------------------------|
| `file_id`         | yes      | Target `.feature` file uuid                         |
| `stone_diameter`  | yes      | Stone girdle diameter in mm (sets the cup size)     |
| `peg_diameter`    | yes      | Post diameter in mm                                 |
| `peg_length`      | yes      | Post height in mm                                   |
| `base_diameter`   | yes      | Soldering foot diameter in mm (>= peg_diameter)     |
| `base_thickness`  | yes      | Soldering foot thickness in mm                      |
| `id`              | no       | Explicit node id                                    |

### Worked example — stud-earring peg for a 4 mm stone

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 4.0,
  "peg_diameter": 1.5,
  "peg_length": 6.0,
  "base_diameter": 3.0,
  "base_thickness": 0.5
}
```

Result node op: `jewelry_peg_setting`. Combine with an ear-post finding.

---

## `jewelry_create_coronet`

Generates a crown (coronet) setting — a vintage-look ring of graduated prongs
that lean inward to form a regal dome.

### How it works

1. `prong_count` prong wires (diameter = `wire_gauge`) are evenly distributed
   around the stone and rise to `crown_height`.
2. Each prong tapers inward by `taper` mm over its height so the tips lean
   over the stone (typical `taper` 0.2–0.6 mm for the classic coronet silhouette;
   `taper = 0` gives straight prongs like a plain prong head).
3. `taper` must be < `wire_gauge` so prong tips remain geometrically solid.
4. A low cylinder base (height ≈ `crown_height × 0.25`) forms the prong
   footings; boolean-fuse onto a shank to complete the ring.

### Parameters

| Parameter         | Required | Notes                                                         |
|-------------------|----------|---------------------------------------------------------------|
| `file_id`         | yes      | Target `.feature` file uuid                                   |
| `stone_diameter`  | yes      | Stone girdle diameter in mm                                   |
| `prong_count`     | yes      | Number of prongs (>= 3; typical 6, 8, or 10)                 |
| `crown_height`    | yes      | Height the prongs rise above the girdle plane in mm           |
| `taper`           | yes      | Inward lean of prong tips in mm (0 = straight; must be < `wire_gauge`) |
| `wire_gauge`      | yes      | Prong wire diameter in mm (typical 0.8–1.5)                  |
| `id`              | no       | Explicit node id                                              |

### Worked example — 8-prong Victorian coronet

```json
{
  "file_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "stone_diameter": 7.0,
  "prong_count": 8,
  "crown_height": 4.0,
  "taper": 0.4,
  "wire_gauge": 1.0
}
```

Result node op: `jewelry_coronet`. Boolean-fuse onto a shank.

---

## FeatureView inspector entries — deferred

The five new settings (`jewelry_prong_variant`, `jewelry_head_gallery`,
`jewelry_under_bezel`, `jewelry_peg_setting`, `jewelry_coronet`) do **not**
yet have FeatureView inspector panel entries (`src/components/` is out of
scope for this agent).  Add inspector cards for each in a follow-up task,
following the pattern of the existing `JewelryProngHeadPanel` and
`JewelryBezelPanel` components.
