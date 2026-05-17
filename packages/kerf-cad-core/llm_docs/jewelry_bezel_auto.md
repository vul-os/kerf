# jewelry_bezel_auto — Bezel / Tube-Setting Auto-from-Stone Wizard

RhinoGold / MatrixGold parity: derives a complete bezel or tube setting automatically from a gemstone spec (cut + size). All sizing is driven by industry min-wall rules, girdle-to-table proportions, and stone outline geometry.

## When to use

Use these tools when a jeweller needs to:
- Generate a full bezel collet from a gemstone without manually specifying every wall dimension
- Build a tube setting for a round stone (short-hand for ID/OD/height + burnish lip)
- Choose a bezel style (straight, bombé, scalloped, half-bezel, V-bezel/collet cone, illusion)
- Apply an edge treatment (sharp, burnished, bright-cut)
- Add an optional under-gallery cutout at the base of the bezel for light ingress
- Include a V-groove bearing seat at the girdle plane

Keywords: bezel, bezel auto, tube setting, collet, bezel wizard, bezel from stone, straight bezel, bombe bezel, scallop bezel, half bezel, v-bezel, illusion setting, edge treatment, burnished edge, bright-cut edge, under-gallery cutout, tube bezel, seat groove, girdle clearance.

## Bezel styles

| Style | Description |
|---|---|
| `straight` | Full-height vertical bezel wall (collet) — canonical form |
| `full_bezel` | Synonym for `straight`; 360° vertical wall |
| `bombe` | Outward-bowing ("bombé") outer wall; OD peaks at mid-height |
| `scallop` | Wall scalloped / notched between four low points; circular arc notches allow light entry from sides |
| `half_bezel` | Bezel walls at two long ends only (east–west open sides); typically for oval/marquise |
| `v_bezel` | Inward-tapering V-form wall (collet cone) |
| `illusion` | Faceted metal plate extends beyond stone edge; outer rim = stone ø × illusion_factor (makes stone appear larger) |

## Edge treatments

| Treatment | Description |
|---|---|
| `sharp` | Top edge left as machined; fine bright-cut look |
| `burnished` | Top edge rolled inward to grip the stone girdle |
| `bright_cut` | Top edge faceted at 45° for maximum sparkle |

## Min-wall rules

Inner profile follows the stone girdle outline (circle for round/oval; polygon / stadium for fancy cuts with corner radii). Wall thickness is scaled from industry minimum-wall rules: thicker walls for heavier stones, thinner walls for delicate melee.

## Seat groove

Optional V-groove (bearing ledge) on the inner wall at `girdle_seat_z` below the top edge: depth 0.1 mm, half-angle 15°. Compatible with `jewelry_cut_bezel_seat` geometry.

## Under-gallery cutout

When `under_gallery_cutout=True`, the wizard computes a sub-circular cutout from the bezel base (integrates with gallery.py conventions). Returns cutout volume for the caller to subtract from the ring shank.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_bezel_auto_from_stone` | Appends a `bezel_auto` node; full wizard; required: `file_id`, `cut`, stone size (`carat` or `diameter_mm`), `bezel_style`; optional: `edge_treatment`, `under_gallery_cutout`, `seat_groove`, `illusion_factor` |
| `jewelry_tube_setting_auto` | Appends a `tube_setting` node; round-stone tube bezel shorthand; required: `file_id`, `stone_diameter_mm`; optional: `wall_thickness_mm`, `lip_height_mm`, `burnish_edge` |

### Key parameters for `jewelry_bezel_auto_from_stone`

- `cut` — gemstone cut (any cut supported by gemstones.py)
- `carat` or `diameter_mm` — stone size
- `material` — optional; affects carat↔mm conversion (coloured stones)
- `bezel_style` — see styles table above
- `edge_treatment` — `sharp` | `burnished` | `bright_cut` (default `burnished`)
- `girdle_clearance_mm` — radial clearance at girdle (default 0.05 mm)
- `min_wall_mm` — override minimum wall (default derived from stone size)
- `under_gallery_cutout` — bool (default false)
- `seat_groove` — bool; add V-groove bearing ledge (default true)
- `illusion_factor` — outer rim scale for illusion style (default 1.35)

### `jewelry_tube_setting_auto` key outputs

- `inner_diameter_mm` — girdle ø + clearance
- `outer_diameter_mm` — inner + 2 × wall
- `height_mm` — tube height (proportional to stone size)
- `lip_height_mm` — burnish lip height at top edge

## Example

Jeweller: "Create a burnished bezel for a 0.75 ct oval ruby with an under-gallery cutout."

1. `jewelry_bezel_auto_from_stone` — file_id=`<id>`, cut=`oval`, carat=0.75, material=`ruby`, bezel_style=`straight`, edge_treatment=`burnished`, under_gallery_cutout=true
   → bezel node appended; cutout_volume_mm3 returned
2. Follow with `jewelry_cut_bezel_seat` to cut the matching bearing bore into the bezel inner wall
