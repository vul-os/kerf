# Jewelry setting generators

Four LLM tools create parametric stone-setting solids as `.feature` nodes.
Each tool appends a node to an existing `.feature` file; the OCCT worker
evaluates the node and returns a `TopoDS_Solid` (or placement data for pavé).

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
