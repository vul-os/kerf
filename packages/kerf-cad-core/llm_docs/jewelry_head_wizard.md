# jewelry_head_wizard — Parametric Head/Prong Wizard and Ring Builder

MatrixGold / RhinoGold parity head wizard: full parametric prong-head library, auto prong placement, head-to-shank merge, and composite ring builder.

## When to use

Use these tools when a jeweller needs to:
- Select or customise a prong head from the eight standard families (4-prong, 6-prong, double-claw, basket, V-prong, half-bezel, full-bezel, halo, tension)
- Auto-place N prong claws evenly around a stone girdle, with corner-biased placement for fancy cuts
- Attach a head to a ring shank at a given seat height
- Build a complete ring by composing head + shank profile + ring-size target into one spec node
- Validate head-to-shank fit, minimum-metal constraints, and estimate casting weight

Keywords: prong head, claw head, solitaire head, 4-prong, 6-prong, double claw, basket head, V-prong, half-bezel, full bezel, halo head, tension setting, head library, prong placement, ring builder, head merge, shank, seat height.

## Head families

| Family | Description |
|---|---|
| `four_prong_solitaire` | Classic 4-prong round/princess head; even 90° spacing |
| `six_prong_solitaire` | Classic 6-prong head; even 60° spacing |
| `double_claw` | Two narrow paired claws per station (8- or 12-claw total) |
| `basket` | Horizontal gallery rail connects all prong bases; open/closed with pierced gallery option |
| `v_prong` | V-shaped tipped prongs for marquise, pear, trillion |
| `half_bezel` | Bezel walls at the two opposing ends + side prongs |
| `full_bezel` | 360° bezel collar; zero prongs |
| `halo` | Centre seat + concentric accent-stone ring |
| `tension` | Stone gripped between two band ends; no prongs or bezel |

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_head_library_get` | Read-only: look up a head family spec by name and stone cut; returns default prong count, wire diameter, splay angle, and compatible stone cuts |
| `jewelry_place_prongs` | Read-only: auto-compute N prong positions around a stone girdle outline; round/oval stones get angular spacing; fancy cuts (princess, emerald, asscher, radiant, cushion, trillion, marquise, pear, heart) get corner-biased placement; returns per-prong XY positions and tip heights |
| `jewelry_build_head` | Appends a head node; required: `file_id`, `head_family`, `stone_cut`, `stone_diameter_mm`; optional: `prong_count`, `wire_diameter_mm`, `splay_angle_deg`, `head_style` overrides |
| `jewelry_ring_builder` | Appends a composite ring node; composes head + shank profile + ring size; computes inner diameter from ring-size lookup; validates fit and minimum-metal; estimates weight; required: `file_id`, `head_family`, `stone_cut`, `stone_diameter_mm`, `ring_size`, `size_system`, `alloy` |

### `jewelry_place_prongs` key outputs

- `prong_positions` — list of `{angle_deg, x_mm, y_mm, z_tip_mm}` per prong
- `clipping_strategy` — `angular` for round/oval, `corner_biased` for fancy cuts
- For fancy cuts: prongs placed at girdle corners/tips to secure the exposed points

### `jewelry_ring_builder` key inputs

- `ring_size`, `size_system` — US / UK / EU / JP (delegates to ring.py)
- `head_family`, `stone_cut`, `stone_diameter_mm` — head geometry
- `shank_profile` — comfort_fit / court / flat / knife_edge / d_shape (delegates to profile_lib.py)
- `shank_width_mm`, `shank_thickness_mm` — shank cross-section
- `alloy` — used for density and casting weight estimate
- `seat_height_mm` — height of stone seat above finger (stone visible height)

## Example

Jeweller: "Design a 6-prong platinum head for a 1.5 ct princess cut, US size 6."

1. `jewelry_head_library_get` — head_family=`six_prong_solitaire`, stone_cut=`princess` → confirms compatible; default wire_diameter_mm=1.0, splay=5°
2. `jewelry_place_prongs` — head_family=`six_prong_solitaire`, stone_cut=`princess`, stone_diameter_mm=6.9 → corner-biased placement, 6 prong positions
3. `jewelry_ring_builder` — file_id=`<id>`, head_family=`six_prong_solitaire`, stone_cut=`princess`, stone_diameter_mm=6.9, ring_size=6, size_system=`us`, alloy=`platinum_950`, shank_profile=`comfort_fit`
