# jewelry_ring — Ring Sizing and Parametric Ring-Band Builders

Ring-size conversion (US / UK+AU / EU / JP) and parametric shank, band, and composite ring builders for engagement rings, wedding bands, eternity bands, signet rings, stacking sets, and more.

## When to use

Use these tools whenever a jeweller needs to:
- Convert between ring sizing systems (US, UK/AU, EU, JP) and inner diameter in mm
- Build a plain or styled ring shank (d-shape, flat, court, euro, knife-edge, half-round, low dome)
- Design an eternity / anniversary band with channel, shared-prong, or pavé stone layout
- Create a signet ring with an engravable flat, oval, or cushion seal face
- Generate stacking band sets with wishbone or contoured wedding bands
- Build composite solitaire, men's comfort-fit, wedding set, cocktail, or bypass / toi-et-moi rings
- Compute finger circumference and internal diameter from a ring size number

Keywords: ring size, ring sizing, inner diameter, US ring size, UK ring size, EU ring size, ring shank, band, eternity band, anniversary ring, signet ring, stacking rings, solitaire ring, engagement ring, wedding band, men's band, comfort fit, cocktail ring, bypass ring, toi-et-moi, contoured band, wishbone band.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_ring_size_to_diameter` | Read-only: converts a ring size in US/UK/EU/JP to inner diameter and circumference (mm); also supports inverse — given a diameter, returns the nearest size in all systems |
| `jewelry_create_ring_shank` | Appends a `ring_shank` node; inputs: `ring_size`, `system`, `profile` (d_shape/flat/court/euro/knife_edge/half_round/low_dome), `width_mm`, `thickness_mm`; returns shank node with outer diameter |
| `jewelry_create_eternity_band` | Appends an `eternity_band` node; full/half/three-quarter stone layout in channel, shared-prong, or pavé; stone count auto-derived from ring circumference |
| `jewelry_create_signet_ring` | Appends a `signet_ring` node; flat/oval/cushion seal face with optional intaglio engraving depth hint |
| `jewelry_create_stacking_band_set` | Appends a `stacking_band_set` node; N thin bands with controlled gap; optional wishbone/contour band to nest against a solitaire shank |
| `jewelry_create_contoured_band` | Appends a `contoured_band` node; curved shadow band shaped to hug an engagement ring; set `match_radius_mm` to engagement ring outer radius |
| `jewelry_create_solitaire_ring` | Appends a `solitaire_ring` composite node; shank + centre-stone head attach-point; accepts `head_height_mm` and `center_stone_diameter_mm` for downstream prong/bezel head |
| `jewelry_create_mens_band` | Appends a `mens_band` node; wider comfort/euro/bevel profile; optional centre groove/inlay channel, milgrain-edge hint, surface-finish hint |
| `jewelry_create_wedding_set` | Appends a `wedding_set` composite node; engagement ring + matched contoured wedding band pair, auto-derived contour match radius |
| `jewelry_create_cocktail_ring` | Appends a `cocktail_ring` composite node; tapered shank + large dome/cluster/bezel/prong top-mount platform attach-point |
| `jewelry_create_bypass_ring` | Appends a `bypass_ring` composite node; two-arm crossover or toi-et-moi ring with two stone mount attach-points; styles: `crossover` or `toi_et_moi` |

## Example

Jeweller: "I need a US size 7 solitaire engagement ring in 18k white gold with a 1 ct round brilliant, plus a matching shadow band."

1. `jewelry_ring_size_to_diameter` — size=7, system=`us` → 17.35 mm inner diameter
2. `jewelry_create_solitaire_ring` — ring_size=7, system=`us`, center_stone_diameter_mm=6.5
3. `jewelry_create_prong_head` — stone_diameter=6.5, prong_count=6 → attach to shank
4. `jewelry_create_contoured_band` — ring_size=7, match_radius_mm=<outer radius from shank> → shadow wedding band
