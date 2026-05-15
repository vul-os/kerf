# jewelry_ring — Ring Shank & Size System

## Overview

Two LLM tools for jewelry ring-band CAD:

| Tool | Purpose |
|------|---------|
| `jewelry_ring_size_to_diameter` | Convert ring size ↔ inner diameter (mm) |
| `jewelry_create_ring_shank` | Append a `ring_shank` node to a `.feature` file |

---

## Ring-size systems

### US system

**Formula** (Hoover & Strong / industry standard):

```
inner_diameter_mm = 11.63 + 0.8128 × us_size
```

Source: Hoover & Strong ring-size reference; cross-checked against Stuller 2024
catalog and Town Talk published tables.

| US Size | Inner Diam (mm) | Circumference (mm) |
|---------|-----------------|-------------------|
| 0       | 11.63           | 36.5              |
| 3       | 14.07           | 44.2              |
| 5       | 15.69           | 49.3              |
| 6       | 16.50           | 51.8              |
| 7       | 17.32           | 54.4              |
| 8       | 18.14           | 57.0              |
| 9       | 18.95           | 59.5              |
| 10      | 19.76           | 62.1              |
| 13      | 22.20           | 69.7              |
| 16      | 24.65           | 77.4              |

Half-sizes accepted (7.5, "7½"). Valid range: 0–16.

### UK / AU system

Letter scale A–Z+3. Each letter maps to a specific circumference (mm) per the
British Standard / ISO 8653. Example values:

| UK/AU | Circumference (mm) | Approx. inner diam (mm) |
|-------|--------------------|------------------------|
| H     | 46.8               | 14.9                   |
| J     | 49.3               | 15.7                   |
| L     | 51.9               | 16.5                   |
| N     | 54.4               | 17.3                   |
| P     | 57.0               | 18.1                   |
| R     | 59.5               | 18.9                   |
| T     | 62.1               | 19.8                   |
| Z     | 69.7               | 22.2                   |
| Z+1   | 70.4               | 22.4                   |

Half-sizes: "N½", "P½", etc.

### EU system

EU size = inner circumference in mm (integer or half, range 41–76).

```
inner_diameter_mm = eu_size / π
```

### JP system

JIS B 4901 lookup table; integer sizes 1–30.

| JP | Circumference (mm) |
|----|-------------------|
| 1  | 38.1              |
| 7  | 43.5              |
| 13 | 48.8              |
| 17 | 52.4              |
| 23 | 57.7              |
| 30 | 64.0              |

---

## Sizing formula derivation

For any system, once inner diameter `d` is known:

```
inner_radius_mm     = d / 2
circumference_mm    = π × d
outer_diameter_mm   = d + 2 × thickness_mm
```

---

## Profile catalog

| Profile | Description |
|---------|-------------|
| `d_shape` | Flat outer face, curved inner bore — classic men's band |
| `comfort_fit` | Domed outer, rounded inner — slides on easily, most popular |
| `flat` | Fully flat top/bottom, square edges — modern/contemporary |
| `half_round` | Domed top, flat bottom — most common women's band |
| `knife_edge` | V-ridge along outer centre line — architectural/dramatic |
| `euro` | Square-ish with gently rounded corners — European standard |
| `tapered` | Width + thickness taper from shoulder to base; use with `taper_ratio` |
| `cigar_band` | Wide flat-top band with heavy bevelled edges — bold statement; use `cigar_bevel_ratio` (0 < v < 0.4, default 0.2) |
| `bombe` | Convex domed outer surface, flat inner bore — full rounded look; use `bombe_dome_ratio` (0 < v ≤ 1.0, default 0.5) |
| `concave` | Concave channel carved into the outer face — elegant groove detail; use `concave_depth_ratio` (0 < v < 0.5, default 0.3) |
| `square` | Square cross-section with sharp 90° corners — architectural/modern |
| `hammered` | Outer surface divided into flat hammer-strike facets — artisan texture; use `hammered_facet_count` (4–128, default 32) |
| `split_band` | Two parallel rail bands separated by a central gap — open split look; use `split_band_gap_mm` (> 0, default 1.0 mm) |

### Profile-specific hints (v2 profiles)

v2 profiles emit a `profile_hints` sub-object in the node for the occtWorker:

#### `cigar_band`
- `bevel_width_mm`: width of each bevel edge
- `flat_top_width_mm`: flat top face width

#### `bombe`
- `dome_height_mm`: outer dome height above base
- `dome_ratio`: fraction of half-width used for dome height

#### `concave`
- `channel_depth_mm`: depth of concave groove
- `channel_width_mm`: width of groove (60% of band_width)

#### `square`
- `corner_radius_mm`: always 0.0 (worker may add a micro-fillet for tooling)

#### `hammered`
- `facet_count`: number of flat facets around the circumference
- `facet_arc_deg`: arc span per facet (360 / facet_count)

#### `split_band`
- `gap_mm`: gap between the two rails
- `rail_width_mm`: each rail's width ((band_width − gap) / 2)

---

## Shoulder styles

The shoulder style describes how the shank meets the centre head or setting.

| Style | Description |
|-------|-------------|
| `plain` | Uniform band all the way around — no modification at top |
| `cathedral` | Arched shoulders that rise toward the setting; classic solitaire look |
| `split_shank` | Band splits into two prongs near the setting; dramatic open look |
| `bypass` | Two ends of the band pass alongside each other rather than meeting |

### Cathedral geometry hints

The `opRingShank` worker uses these hints from the node:

- `arch_height_mm`: how far the arch rises above the band top (≈ 35% of inner radius)
- `arch_start_deg`: degrees from the 12-o'clock position where the arch begins (default 70°)
- `blend_radius_mm`: fillet radius blending the arch to the shank

### Split-shank hints

- `split_start_deg`: angle from 12-o'clock where the split begins (default 55°)
- `prong_gap_mm`: gap between the two prongs
- `prong_width_mm`: each prong's width

### Bypass hints

- `bypass_offset_mm`: lateral offset of each end (default 60% of band width)
- `overlap_deg`: how many degrees the two ends overlap at the top (default 30°)

---

## v2 node-spec fields

### Band engraving (`engraving`)

Parametric engraving spec — **geometry hint only**; OCCT text rendering is
deferred to the occtWorker `opRingShank` implementation.

```json
{
  "engraving": {
    "text": "Always & Forever",
    "font_height_mm": 1.5,
    "depth_mm": 0.3,
    "position_deg": 180.0,
    "align": "centre"
  }
}
```

| Field | Default | Constraint |
|-------|---------|-----------|
| `text` | — | required; 1–200 chars |
| `font_height_mm` | 1.5 | > 0 mm |
| `depth_mm` | 0.3 | > 0 mm |
| `position_deg` | 180.0 | 0–360° (0 = bottom of band) |
| `align` | `"centre"` | `"centre"` / `"left"` / `"right"` |

### Sizing beads (`sizing_beads`)

Small hemispherical protrusions on the inner bore to create a snug fit
without resizing.

```json
{
  "sizing_beads": {
    "count": 2,
    "bead_diameter_mm": 1.0,
    "bead_height_mm": 0.4,
    "position_deg": 270.0
  }
}
```

| Field | Default | Constraint |
|-------|---------|-----------|
| `count` | 2 | 1–4 beads |
| `bead_diameter_mm` | 1.0 | > 0 mm |
| `bead_height_mm` | 0.4 | > 0 mm; must be < thickness / 4 |
| `position_deg` | 270.0 | 0–360° (first bead angular start) |

### Comfort-fit interior radius override (`comfort_fit_radius`)

Override the default interior dome radius (mm) for the `comfort_fit` profile.
If omitted, the occtWorker uses its default (≈ 0.8 × inner_radius).

```json
{ "comfort_fit_radius": 4.5 }
```

Constraint: > 0 mm.  Stored in node as `comfort_fit_radius_mm`.

### Finger-fit taper (`finger_fit_taper`)

Asymmetric taper angle (degrees) so the band is slightly wider on the knuckle
side, making it easier to slide over the knuckle while still fitting the finger.

```json
{ "finger_fit_taper": 5.0 }
```

Constraint: 0–15 degrees.  Stored as `finger_fit_taper_deg`.  0 = symmetric
(default); key is omitted from the node if value is 0.

### Width profile curve (`width_profile`)

An array of 2–10 floats describing the width taper from the shoulder (index 0)
to the back of the band (last index).  Each value is a ratio relative to
`band_width` — `1.0` = full width, `0.6` = 60% of `band_width`.

```json
{ "width_profile": [1.0, 0.90, 0.80, 0.75] }
```

Constraints:
- 2–10 elements
- Each value in range `(0, 1]`
- Omit for uniform width (no taper)

---

## Tool usage

### `jewelry_ring_size_to_diameter` — size conversion

**Forward** (size → diameter):

```json
{
  "system": "us",
  "size": 7
}
```

Response:
```json
{
  "system": "us",
  "size": 7,
  "inner_diameter_mm": 17.3196,
  "inner_radius_mm": 8.6598,
  "circumference_mm": 54.4388
}
```

**Inverse** (diameter → nearest size):

```json
{
  "system": "uk",
  "diameter_mm": 17.32
}
```

Response:
```json
{
  "system": "uk",
  "diameter_mm": 17.32,
  "nearest_size": "N",
  "nearest_size_diameter_mm": 17.3197
}
```

### `jewelry_create_ring_shank` — shank builder

```json
{
  "file_id": "<uuid>",
  "ring_size": 7,
  "system": "us",
  "band_width": 4.0,
  "thickness": 1.8,
  "profile": "comfort_fit",
  "shoulder_style": "cathedral"
}
```

Response:
```json
{
  "file_id": "<uuid>",
  "id": "ring_shank-1",
  "op": "ring_shank",
  "inner_diameter_mm": 17.3196,
  "outer_diameter_mm": 20.9196,
  "circumference_mm": 54.4388,
  "profile": "comfort_fit",
  "shoulder_style": "cathedral",
  "band_width_mm": 4.0,
  "thickness_mm": 1.8
}
```

**v2 example — hammered band with engraving, sizing beads and width taper:**

```json
{
  "file_id": "<uuid>",
  "ring_size": 7,
  "system": "us",
  "band_width": 5.0,
  "thickness": 2.0,
  "profile": "hammered",
  "hammered_facet_count": 24,
  "shoulder_style": "cathedral",
  "engraving": {
    "text": "Always & Forever",
    "font_height_mm": 1.5,
    "depth_mm": 0.3,
    "position_deg": 180.0,
    "align": "centre"
  },
  "sizing_beads": {
    "count": 2,
    "bead_diameter_mm": 1.0,
    "bead_height_mm": 0.35,
    "position_deg": 270.0
  },
  "comfort_fit_radius": 4.0,
  "finger_fit_taper": 3.0,
  "width_profile": [1.0, 0.9, 0.8]
}
```

---

## Worked example — US size 7 solitaire shank

1. Convert size: US 7 → 17.32 mm inner diameter, 54.44 mm circumference.
2. Choose profile `comfort_fit` (rounded inside for comfort).
3. Choose shoulder style `cathedral` (arched for a solitaire setting).
4. Band width 4 mm, thickness 1.8 mm → outer diameter 20.92 mm.
5. Cathedral arch height = 17.32/2 × 0.35 ≈ 3.03 mm above band top.
6. The `ring_shank-1` node is appended; the occtWorker evaluates it via
   `opRingShank`, sweeping the cross-section profile along a full 360° circle
   of radius 8.66 mm using a corrected Frenet frame, then applies the
   cathedral arch sweep on top.

---

## Validation rules

| Parameter | Constraint |
|-----------|-----------|
| system | us / uk / au / eu / jp |
| US size | 0–16 (half-sizes OK) |
| UK/AU size | A–Z+3 |
| EU size | 41–76 mm circumference |
| JP size | 1–30 (integer) |
| band_width | > 0 mm |
| thickness | > 0 mm |
| taper_ratio | > 0 |
| profile | see catalog above (13 profiles) |
| shoulder_style | plain / cathedral / split_shank / bypass |
| hammered_facet_count | 4–128 (default 32) |
| split_band_gap_mm | > 0; < band_width − 0.5 mm |
| bombe_dome_ratio | (0, 1.0] (default 0.5) |
| concave_depth_ratio | (0, 0.5) (default 0.3) |
| cigar_bevel_ratio | (0, 0.4) (default 0.2) |
| engraving.text | 1–200 chars |
| engraving.font_height_mm | > 0 mm (default 1.5) |
| engraving.depth_mm | > 0 mm (default 0.3) |
| engraving.position_deg | 0–360 (default 180) |
| engraving.align | centre / left / right |
| sizing_beads.count | 1–4 (default 2) |
| sizing_beads.bead_diameter_mm | > 0 mm (default 1.0) |
| sizing_beads.bead_height_mm | > 0 mm; < thickness / 4 (default 0.4) |
| sizing_beads.position_deg | 0–360 (default 270) |
| comfort_fit_radius | > 0 mm (optional override) |
| finger_fit_taper | 0–15 degrees (default 0 = symmetric) |
| width_profile | 2–10 floats, each in (0, 1] |

Error code `BAD_ARGS` is returned for all constraint violations.
