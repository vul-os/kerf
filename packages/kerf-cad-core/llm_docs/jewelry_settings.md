# jewelry_settings — Parametric Stone Setting Generators

Twenty-five setting types covering every major prong, bezel, channel, pavé, tension, flush, halo, cluster, bar, bead, illusion, invisible, and specialty mounting style used in fine jewellery.

## When to use

Use these tools whenever a jeweller needs to:
- Add a prong head (4-prong, 6-prong, basket, trellis, cathedral) for a solitaire or side stone
- Set a stone in a bezel (full or partial), channel, bar, tension, flush/gypsy, or pavé layout
- Build a halo of accent stones around a centre stone
- Create three-stone, cluster, bombe cluster, or illusion settings
- Apply bead/grain, gypsy-pavé (star setting), invisible, or bar-channel-graduated layouts
- Add gallery rails, under-bezels, coronets, peg settings, V-tip protectors, or suspension mounts
- Use specialty styles: trellis prong, patterned bezel, bombe cluster, bar-channel graduated

Keywords: prong setting, 4-prong, 6-prong, basket setting, bezel setting, channel setting, pavé, pave, tension setting, flush setting, gypsy setting, halo, three-stone, cluster setting, bar setting, bead grain, illusion plate, invisible setting, coronet, trellis prong, gallery rail, V-tip protector, bombe, patterned bezel.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_create_prong_head` | Appends a `jewelry_prong_head` node; inputs: `stone_diameter`, `prong_count` (4/6), style (basket/trellis/cathedral); includes bearing ledge at `seat_angle_deg` |
| `jewelry_create_bezel` | Appends a `jewelry_bezel` node; full or partial bezel/collet with horizontal bearing ledge; supports all fancy cuts |
| `jewelry_create_channel` | Appends a `jewelry_channel` node; two parallel metal rails for a row of N calibrated stones at `stone_spacing` pitch |
| `jewelry_pave_array` | Appends a `jewelry_pave` node; hex-offset grid of stone placements across a rectangular target region; returns placement transforms for downstream gem-seat ops |
| `jewelry_create_tension` | Appends a `jewelry_tension` node; spring-tension band ends grip stone's girdle; stone floats in gap |
| `jewelry_create_flush` | Appends a `jewelry_flush` node; drilled pocket so stone table sits flush with or just proud of metal surface |
| `jewelry_create_halo` | Appends a `jewelry_halo` node; ring of small accent stones around a centre stone; `halo_stone_count`, `halo_stone_size`, `halo_gap` |
| `jewelry_create_three_stone` | Appends a `jewelry_three_stone` node; centre + two graduated side stones on a shared gallery base |
| `jewelry_create_cluster` | Appends a `jewelry_cluster` node; group of small stones on a domed base reading as one large stone |
| `jewelry_create_bar` | Appends a `jewelry_bar` node; two parallel metal bars along a row of N stones; no prongs between stones |
| `jewelry_create_bead_grain` | Appends a `jewelry_bead_grain` node; small raised metal beads cut up from surrounding metal and pushed over stone's girdle |
| `jewelry_create_gypsy_pave` | Appends a `jewelry_gypsy_pave` node; flush stone with bright-cut star rays engraved outward from its edge |
| `jewelry_create_illusion` | Appends a `jewelry_illusion` node; small stone centred on polished faceted plate that magnifies apparent stone size |
| `jewelry_create_invisible` | Appends a `jewelry_invisible` node; grid of princess/calibrated stones on concealed rail — no visible metal between stones |
| `jewelry_create_prong_variant` | Appends a `jewelry_prong_variant` node; six specialised prong-wire types: double, claw, V, fishtail, split, decorative |
| `jewelry_create_head_gallery` | Appends a `jewelry_head_gallery` node; basket/peg head + decorative gallery rail beneath |
| `jewelry_create_under_bezel` | Appends a `jewelry_under_bezel` node; sub-collet collar that raises a stone above the shank; used under bezels or halos |
| `jewelry_create_peg_setting` | Appends a `jewelry_peg_setting` node; cylindrical post with shallow stone-cup for earrings/pendants |
| `jewelry_create_coronet` | Appends a `jewelry_coronet` node; tapered Victorian/antique crown of graduated prong wires |
| `jewelry_create_suspension_mount` | Appends a `jewelry_suspension_mount` node; articulated dangle mount for drop earrings/pendants with jump-ring pivot |
| `jewelry_create_vtip_protector` | Appends a `jewelry_vtip_protector` node; V-channel metal caps for pointed corners of pear, marquise, heart, trillion |
| `jewelry_create_bombe_cluster` | Appends a `jewelry_bombe_cluster` node; strongly domed multi-stone cluster with seats across a spherical-cap surface |
| `jewelry_create_patterned_bezel` | Appends a `jewelry_patterned_bezel` node; decorative bezel with lotus-petal, compass-point, or star-notch pattern cut into the wall |
| `jewelry_create_trellis_prong` | Appends a `jewelry_trellis_prong` node; prong wires that cross/interweave in x_cross, basket_weave, or spiral cage pattern |
| `jewelry_create_bar_channel_graduated` | Appends a `jewelry_bar_channel_graduated` node; graduated-row setting with bar separators and channel floor; stone size decreases from centre to ends |

## Example

Jeweller: "Build a 6-prong solitaire head for a 1 ct round diamond with a decorative gallery rail."

1. `jewelry_create_prong_head` — stone_diameter=6.5, prong_count=6, style=`basket`
2. `jewelry_create_head_gallery` — head_diameter=6.5 → gallery rail fused below the head
3. `jewelry_cut_gem_seat` — to cut the matching bearing seat into the shank at the head location
