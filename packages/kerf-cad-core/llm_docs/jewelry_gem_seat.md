# jewelry_gem_seat — Gem-Seat Boolean Cutters

Parametric gem-seat cutter solids that boolean-subtract a precision bearing pocket into a host solid (ring shank, bezel, band) so a gemstone can be set correctly.

## When to use

Use these tools after placing a gemstone and/or a setting node to cut the matching seat into the host metal body. The right seat tool depends on the setting style:

- Single stone (prong or bezel) — `jewelry_cut_gem_seat`
- Row of round/oval stones in a channel — `jewelry_cut_channel_seat`
- Single bezel/collet bore — `jewelry_cut_bezel_seat`
- Pavé accent stones needing fishtail bright-cut facets — `jewelry_cut_fishtail_seat`
- Three-stone / five-stone graduated arrangement — `jewelry_cut_multi_stone_seat`
- Pavé field across a rectangular face — `jewelry_cut_pave_field_seat`
- Halo or cluster with centre + accent ring — `jewelry_cut_cluster_halo_seat`
- Flush/gypsy (countersink, no bearing cone overhang) — `jewelry_cut_gypsy_seat`
- Step-cut baguette, trapezoid, or carré in a channel — `jewelry_cut_baguette_channel_seat`

Keywords: gem seat, bearing, bearing cone, seat cutter, girdle ledge, prong seat, bezel seat, channel seat, pavé seat, fishtail seat, gypsy seat, flush seat, baguette channel, multi-stone seat, halo seat, cluster seat, boolean cut.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_cut_gem_seat` | Appends a `gem_seat` node; bearing cone + girdle ledge + optional light-through hole; sized from gemstone cut and diameter; optional `auto_cut_host_id` to immediately boolean-subtract from host solid |
| `jewelry_cut_channel_seat` | Appends a `channel_seat` node; continuous swept bearing groove for a row of N stones at a given pitch; emits per-stone positions |
| `jewelry_cut_bezel_seat` | Appends a `bezel_seat` node; inner bore for bezel/collet (cylindrical or tapered collet); supports all fancy-shape cuts |
| `jewelry_cut_fishtail_seat` | Appends a `fishtail_seat` node; accent-stone seat with bright-cut facet grooves radiating from the girdle ledge; for pavé and channel-pavé |
| `jewelry_cut_multi_stone_seat` | Appends a `multi_stone_seat` node; shared base seat for centre + N side stones in a graduated 3-stone or 5-stone arrangement |
| `jewelry_cut_pave_field_seat` | Appends a `pave_field_seat` node; grid or honeycomb arrangement of identical bearing seats across a rectangular region |
| `jewelry_cut_cluster_halo_seat` | Appends a `cluster_halo_seat` node; centre stone seat + equally-spaced accent ring at a given radius and count; centre and accent stones can differ in cut/size |
| `jewelry_cut_gypsy_seat` | Appends a `gypsy_seat` node; flush/countersink seat — no bearing cone overhang above metal surface; straight cylinder + shallow countersink |
| `jewelry_cut_baguette_channel_seat` | Appends a `baguette_channel_seat` node; rectangular straight-wall groove for step-cut stones (baguette, trapezoid, carré) |

## Example

Jeweller: "Set a 0.50 ct oval ruby in a bezel, flush with the shank."

1. `jewelry_create_gemstone` — cut=`oval`, carat=0.5, material=`ruby`
2. `jewelry_create_bezel` — style=`full`, stone size from above
3. `jewelry_cut_bezel_seat` — tapered=false, sized to the oval ruby → boolean-subtracts bearing bore from the bezel collet
