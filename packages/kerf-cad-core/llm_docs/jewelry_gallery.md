# jewelry_gallery — Basket, Gallery, and Shoulder Builders

Parametric basket / gallery / under-gallery and shoulder-arch sub-structure builder — the openwork framework beneath a ring head. Provides RhinoGold / MatrixGold parity for the Gallery tool.

## When to use

Use these tools whenever a jeweller needs to:
- Build the structural metal frame between a stone-setting head and the ring shank (basket / gallery)
- Add horizontal rail bands, scallop/airline openwork cutouts, or diagonal strut braces to a prong head
- Create an under-bezel gallery collar beneath a bezel collet with decorative border treatment (scalloped, milgrain, pierced, filigree)
- Add cathedral shoulder arches that sweep from the prong base down to the shank
- Create an interlocking trellis (cross-diagonal) shoulder connecting adjacent prongs
- Check whether wire diameter is structurally adequate for a given stone carat load
- Estimate metal volume, surface area, and weight for a basket assembly before casting

Keywords: gallery, basket, under-gallery, shoulder, prong basket, cathedral shoulder, trellis, ring gallery, scallop cutout, airline cutout, diagonal strut, gallery rail, basket height, under-bezel gallery, milgrain border, pierced gallery.

## Wire diameter minimums (bench practice, Gees / RhinoGold)

| Stone weight | Min wire diameter |
|---|---|
| < 0.25 ct | 0.8 mm |
| 0.25 – 0.75 ct | 0.9 mm |
| 0.75 – 1.50 ct | 1.0 mm |
| 1.50 – 3.00 ct | 1.1 mm |
| > 3.00 ct | 1.2 mm |

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_build_basket_gallery` | Appends a `gallery_basket` node; N-prong basket with prong wires, horizontal rail bands, cutout style, optional diagonal struts; required: `file_id`, `prong_count` (3–12), `stone_diameter_mm`, `wire_diameter_mm`, `basket_height_mm` |
| `jewelry_build_under_bezel_gallery` | Appends a `gallery_under_bezel` node; flat-bottomed sub-collet collar with decorative border; required: `file_id`, `stone_diameter_mm`, `wall_thickness_mm`, `gallery_height_mm` |
| `jewelry_build_cathedral_shoulders` | Appends a `gallery_cathedral` node; arch ribs sweeping from prong base to shank; required: `file_id`, plus prong/stone/wire/basket/shank params |
| `jewelry_build_trellis_shoulders` | Appends a `gallery_trellis` node; interlocking cross-diagonal X-pattern between adjacent prongs; required: `file_id`, `prong_count`, `stone_diameter_mm`, `wire_diameter_mm`, `basket_height_mm` |
| `jewelry_estimate_gallery_metal` | Read-only: compute metal volume (mm³), surface area (mm²), weight (grams) for a basket spec; also emits structural warning if `wire_diameter_mm` is below minimum for `stone_carat` |

### Key parameters for `jewelry_build_basket_gallery`

- `prong_count` — 3 to 12; typical 4 or 6
- `stone_diameter_mm` — girdle diameter (e.g. 6.5 mm for 1 ct round brilliant)
- `wire_diameter_mm` — round-wire diameter; typical 0.8–1.5 mm
- `basket_height_mm` — overall height from base to stone-seat plane
- `rail_count` — horizontal rails (1–6; default 1)
- `taper_ratio` — basket taper toward base (0 = no taper; 0.5 = base radius 75% of head radius)
- `splay_angle_deg` — outward prong splay from vertical (default 5°)
- `cutout_style` — `none` | `scallop` | `airline` | `oval` | `marquise`
- `diagonal_struts` — add X-brace struts between adjacent prongs (bool)
- `stone_carat` — optional; triggers structural wire-diameter warning

### Border styles for `jewelry_build_under_bezel_gallery`

`plain` | `scalloped` | `milgrain` | `pierced` | `filigree`

## Example

Jeweller: "Build a 6-prong solitaire head with a scalloped gallery for a 1 ct round brilliant, 18k yellow gold."

1. `jewelry_estimate_gallery_metal` — prong_count=6, stone_diameter_mm=6.5, wire_diameter_mm=1.0, basket_height_mm=4.5, density_g_cm3=15.53, stone_carat=1.0 → 0.34 g estimated; no wire warning
2. `jewelry_build_basket_gallery` — file_id=`<id>`, prong_count=6, stone_diameter_mm=6.5, wire_diameter_mm=1.0, basket_height_mm=4.5, cutout_style=`scallop`, rail_count=1
3. `jewelry_build_cathedral_shoulders` — add cathedral arches to merge head into shank
