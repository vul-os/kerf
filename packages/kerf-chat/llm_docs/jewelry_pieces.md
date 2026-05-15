# jewelry_pieces — Whole-Piece Jewelry Builders

## Overview

Five LLM tools for complete jewelry-piece CAD (pendant, earrings, brooch,
cufflink, bangle).  Each tool appends a composite node to a `.feature` file
and emits `attach_points` so downstream `gem_seat`, `settings`, and `findings`
nodes can fuse onto the piece without repeating geometry.

| Tool | Node `op` | Purpose |
|------|-----------|---------|
| `jewelry_create_pendant` | `pendant` | Frame / plate + integrated bail + stone mount attach-points |
| `jewelry_create_earrings` | `earrings` | Matched left+right pair; stud / drop / hoop / huggie / chandelier |
| `jewelry_create_brooch` | `brooch` | Frame + stone seats + pin-finding mount hints |
| `jewelry_create_cufflink` | `cufflink` | Matched left+right pair; face + post + toggle/T-bar/chain/bullet/whale-back |
| `jewelry_create_bangle` | `bangle` | Closed bangle or open cuff by wrist size; hinge/clasp mount hints |

All tools require `file_id` (uuid of a `.feature` file).  All dimensions in mm.
No OCCT is invoked by these tools — the `occtWorker` evaluates the resulting
node spec.

---

## Attach-point schema

Every piece builder emits an `attach_points` list.  Each entry:

```json
{
  "type": "stone_seat | bail_hole | ear_wire | pin_mount | post | clasp_mount | hinge | chain_hole",
  "role": "<human label>",
  "position": [x, y, z],
  "normal": [nx, ny, nz],
  "diameter_mm": 6.0,
  "height_mm": 1.5
}
```

Additional fields appear per piece type (documented below).

Downstream nodes that consume attach-points:
- `jewelry_create_gem_seat` — reads `stone_seat` entries to cut seats and add prongs/bezels.
- `jewelry_create_setting` — reads `stone_seat` entries to build prong/bezel heads.
- `jewelry_create_finding` — reads `bail_hole`, `ear_wire`, `pin_mount`, `clasp_mount`
  entries to materialise bail / ear-wire / pin-stem / catch findings.

---

## Pendant

### Tool: `jewelry_create_pendant`

Builds a frame/plate pendant body with an integrated bail and optional stone
seats.  The frame outline is parametric.

**Required**: `file_id`

**Key parameters**:

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `style` | str | `solitaire_drop` | `solitaire_drop`, `halo`, `cluster`, `locket`, `charm` |
| `outline_shape` | str | `teardrop` | `round`, `oval`, `teardrop`, `square`, `rectangle`, `hexagon`, `heart`, `free_form` |
| `width_mm` | float | 12.0 | Frame width (X), mm |
| `height_mm` | float | 18.0 | Frame height (Y, not counting bail), mm |
| `thickness_mm` | float | 1.5 | Frame plate / bezel wall thickness, mm |
| `bail_type` | str | `loop` | `loop`, `pinch`, `snap`, `tube` |
| `bail_wire_gauge_mm` | float | 1.0 | Bail wire diameter, mm |
| `bail_loop_id_mm` | float | 0 | Inner diameter of bail loop, mm; 0 = auto (gauge × 3) |
| `chain_hole_diameter_mm` | float | 0 | Chain-hole diameter, mm; 0 = auto |
| `centre_stone_diameter_mm` | float | 6.0 | Centre stone seat, mm; 0 = no stone |
| `halo_stone_diameter_mm` | float | 0 | Halo stone diameter, mm; 0 = no halo |
| `halo_stone_count` | int | 0 | Number of halo stones; ≥ 3 when halo enabled |
| `locket_hinge_side` | str | `left` | `left` or `right`; locket style only |

**Attach-points emitted**:

- `bail_hole` (role: `bail`) — bail chain-hole at top centre.
- `stone_seat` (role: `centre_stone`) — when `centre_stone_diameter_mm > 0`.
- `stone_seat` (role: `halo_stone_N`) — one per halo stone, evenly distributed.

**Locket** style additionally emits `locket_hinge` in `composite_ops` and
stores `locket_hinge_side`.

**Example**:
```json
{
  "file_id": "<uuid>",
  "style": "halo",
  "outline_shape": "round",
  "width_mm": 14.0,
  "height_mm": 14.0,
  "centre_stone_diameter_mm": 6.5,
  "halo_stone_diameter_mm": 1.8,
  "halo_stone_count": 10
}
```

---

## Earrings

### Tool: `jewelry_create_earrings`

Always emits a **matched pair** (left + right, mirrored about the YZ plane).
Every attach-point carries a `side` field (`"left"` or `"right"`).

**Required**: `file_id`

**Styles and their key attach-points**:

| Style | Attach-points |
|-------|--------------|
| `stud` | `post` (ear post) + `ear_wire` (butterfly back) + optional `stone_seat` |
| `drop` | `ear_wire` (fish-hook top) + optional `stone_seat` |
| `hoop` | `hinge` (hoop hinge) + `clasp_mount` (latch) |
| `huggie` | `hinge` (hinged snap) + `clasp_mount` + optional `stone_seat` |
| `chandelier` | `ear_wire` (top) + `stone_seat` (face) + `chain_hole` (tier connectors) |

**Key parameters**:

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `style` | str | `stud` | See above |
| `face_diameter_mm` | float | 8.0 | Face disc diameter, mm |
| `face_thickness_mm` | float | 1.2 | Face disc thickness, mm |
| `drop_length_mm` | float | 20.0 | drop/chandelier: total drop length, mm |
| `hoop_inner_diameter_mm` | float | 16.0 | hoop/huggie: hoop inner diameter, mm |
| `wire_gauge_mm` | float | 0.8 | Post (stud) or ear-wire (drop/hoop) diameter, mm |
| `post_length_mm` | float | 10.0 | stud/huggie: post length through earlobe, mm |
| `tier_count` | int | 2 | chandelier: drop tiers (1–5) |
| `tier_spacing_mm` | float | 8.0 | chandelier: vertical tier spacing, mm |
| `stone_diameter_mm` | float | 5.0 | Face stone seat, mm; 0 = no stone |
| `stone_count` | int | 1 | Stone seats on face |

**Pairing**: left earring X-positions are negated relative to right.

**Example** (drop earrings with stone):
```json
{
  "file_id": "<uuid>",
  "style": "drop",
  "face_diameter_mm": 10.0,
  "drop_length_mm": 30.0,
  "wire_gauge_mm": 0.8,
  "stone_diameter_mm": 6.0
}
```

---

## Brooch

### Tool: `jewelry_create_brooch`

Builds a brooch frame with stone seats and **pin-finding mount hints** in
`attach_points`.  The hints tell the occtWorker where to place pin-finding
geometry.  To materialise the actual pin stem / joint / catch findings, call
`jewelry_create_finding` after the brooch frame is placed.

**Required**: `file_id`

**Key parameters**:

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `shape` | str | `oval` | `round`, `oval`, `square`, `rectangular`, `freeform`, `floral`, `geometric` |
| `width_mm` | float | 35.0 | Frame width, mm |
| `height_mm` | float | 25.0 | Frame height, mm |
| `thickness_mm` | float | 1.8 | Frame plate thickness, mm |
| `frame_wire_gauge_mm` | float | 1.2 | Border wire gauge, mm |
| `stone_diameter_mm` | float | 4.0 | Stone seat diameter, mm; 0 = no stones |
| `stone_count` | int | 5 | Number of stone seats |
| `pin_stem_length_mm` | float | 0 | Pin stem length; 0 = auto (width × 1.1) |
| `safety_catch` | bool | true | Include secondary safety catch hint |

**Attach-points emitted**:

- `stone_seat` (role: `stone_N`) — one per stone, evenly spaced along centre X axis.
- `pin_mount` (role: `pin_finding`) — back centre; `finding_mount_hint = "pin_stem"`.
- `pin_mount` (role: `pin_joint`) — back left; `finding_mount_hint = "joint"`.
- `pin_mount` (role: `pin_catch`) — back right; `finding_mount_hint = "catch_rotating"`.

---

## Cufflink

### Tool: `jewelry_create_cufflink`

Always emits a **matched pair** (left + right, mirrored).  Every
attach-point carries a `side` field.

**Required**: `file_id`

**Back styles**:

| Style | Description |
|-------|-------------|
| `toggle` | Hinged T-bar that flips parallel for insertion (default) |
| `t_bar` | Fixed T-bar |
| `chain` | Decorative face + back plate connected by a chain |
| `bullet` | Cylindrical fixed back |
| `whale_back` | Hinged whale-tail flip-back |

**Key parameters**:

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `face_diameter_mm` | float | 16.0 | Face disc diameter, mm |
| `face_thickness_mm` | float | 3.0 | Face disc thickness, mm |
| `post_length_mm` | float | 8.0 | Post stem length, mm |
| `post_diameter_mm` | float | 2.5 | Post diameter, mm |
| `back_style` | str | `toggle` | See above |
| `back_diameter_mm` | float | 12.0 | Back element diameter, mm |
| `chain_length_mm` | float | 8.0 | `chain` back only: chain length, mm |
| `stone_diameter_mm` | float | 0 | Face stone seat, mm; 0 = no stone |

**Attach-points emitted** (per side):

- `stone_seat` (role: `face_stone`) — when `stone_diameter_mm > 0`.
- `post` (role: `post_stem`) — post mount at back of face.
- `clasp_mount` (role: `back_element`) — back mechanism attach-point;
  carries `back_style` and (for chain) `chain_length_mm`.

---

## Bangle / Cuff Bracelet

### Tool: `jewelry_create_bangle`

Closed bangle (full circle) or open cuff (C-shape), sized by wrist
circumference or US bangle size.

**Required**: `file_id`

**Wrist size systems**:

| System | Format | Example |
|--------|--------|---------|
| `us` | XS, S, M, L, XL, XXL | `"M"` |
| `mm` | circumference in mm | `200.0` |
| `inches` | circumference in inches | `7.87` |

**US bangle inner diameters** (reference):

| Size | Inner diam (mm) |
|------|-----------------|
| XS | 57.2 |
| S | 60.3 |
| M | 63.5 |
| L | 66.7 |
| XL | 69.9 |
| XXL | 76.2 |

**Key parameters**:

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `form` | str | `closed` | `closed` or `open_cuff` |
| `wrist_size` | str/float | `"M"` | Size in chosen system |
| `wrist_size_system` | str | `us` | `mm`, `inches`, `us` |
| `cross_section` | str | `round` | `round`, `oval`, `flat`, `half_round`, `square` |
| `band_width_mm` | float | 6.0 | Band width along arm axis, mm |
| `thickness_mm` | float | 2.0 | Radial wall thickness, mm |
| `opening_angle_deg` | float | 45.0 | `open_cuff` only: gap angle in degrees (0–120] |
| `hinge_style` | str | `none` | `closed` only: `none`, `box_hinge`, `tube_hinge` |
| `clasp_hint` | str | `none` | `none`, `box_clasp`, `push_pull`, `magnetic` |

**Attach-points emitted**:

- Closed bangle with hinge: `hinge` (role: `bangle_hinge`) at 9-o'clock +
  `clasp_mount` (role: `bangle_clasp`) at 3-o'clock.
- Open cuff: two `clasp_mount` entries (roles: `cuff_end_left`, `cuff_end_right`)
  at the gap edges.
- Rigid closed bangle (no hinge): no attach-points.

**Output fields**: `inner_diameter_mm`, `outer_diameter_mm`,
`wrist_circumference_mm`, `arc_deg` (open cuff only).

**Example** (open cuff with magnetic clasp):
```json
{
  "file_id": "<uuid>",
  "form": "open_cuff",
  "wrist_size": "M",
  "wrist_size_system": "us",
  "cross_section": "flat",
  "band_width_mm": 12.0,
  "thickness_mm": 1.8,
  "opening_angle_deg": 45.0,
  "clasp_hint": "magnetic"
}
```

---

## Typical workflows

### Solitaire pendant with prong setting

```
1. jewelry_create_pendant  → pendant node (stone_seat attach-point at centre)
2. jewelry_create_gem_seat → reads stone_seat → cuts bearing from pendant body
3. jewelry_create_setting  → prong head fused at stone_seat position
4. jewelry_create_finding  → bail (family=bail, kind=loop) materialised at bail_hole
```

### Brooch with multiple stones

```
1. jewelry_create_brooch       → brooch node (stone_seat + pin_mount attach-points)
2. jewelry_create_gem_seat ×N  → one call per stone_seat attach-point
3. jewelry_create_finding      → pin stem (family=pin_finding, kind=pin_stem) at pin_finding mount
4. jewelry_create_finding      → joint at pin_joint mount
5. jewelry_create_finding      → catch at pin_catch mount
```

### Stud earrings with pavé face

```
1. jewelry_create_earrings   → earrings node (pair; post + butterfly back attach-points)
2. jewelry_create_gem_seat   → reads stone_seat, applied per side
3. jewelry_create_setting    → pavé setting per stone seat
4. jewelry_create_finding    → ear nut (family=ear_finding, kind=ear_nut) per ear
```

---

## Deferred

**FeatureView integration** — the `FeatureView` React component is not yet
wired to render `pendant`, `earrings`, `brooch`, `cufflink`, or `bangle` node
ops.  The `occtWorker` tessellation operator `opPiece` (which consumes these
node specs) is similarly deferred.  These pieces are fully specified in the
`.feature` file node graph; the render path will be implemented in a
subsequent milestone.
