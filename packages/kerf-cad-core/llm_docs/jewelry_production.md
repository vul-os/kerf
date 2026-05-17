# jewelry_production — Production Operations (MatrixGold Production Tab Parity)

Jewelry production workflow tools covering mold-shrinkage compensation, casting-tree layout, hallmark/stamp placement, wax/resin and metal weight, per-piece and batch cost rollup, finger-size scaling, and file/polish stock allowance.

## When to use

Use these tools when a jeweller needs to:
- Scale up a wax/resin pattern to compensate for casting shrinkage per alloy
- Auto-layout N pieces on a casting sprue tree
- Generate a hallmark / maker-mark placement spec for laser or hand-stamping
- Compute wax pattern weight, metal casting weight, and tree totals
- Roll up per-piece cost (metal + casting + labour + stones) or batch costs
- Rescale a ring to a different finger size after design
- Apply a file/polish stock allowance to a rough-machined ring band

Keywords: mold shrinkage, casting shrinkage, shrinkage compensation, scale factor, casting tree, sprue, sprue diameter, hallmark, fineness stamp, maker mark, wax weight, resin weight, casting weight, batch cost, ring resize, finger size, polish allowance, stock allowance, Chvorinov.

## Shrinkage table

Sources: Revoire P., Aurum Jewellery Technical Bulletin 12 (2022); Legor Group alloy data sheets; Platinum Guild International technical notes; Stuller Inc. alloy reference guide.

| Alloy | Shrinkage (%) |
|---|---|
| Gold yellow (all karats) | ~1.25 |
| Gold white alloys | ~1.30 |
| Gold rose alloys | ~1.28 |
| Platinum 950 | ~1.80 |
| Platinum 900 | ~1.85 |
| Palladium 950 | ~1.50 |
| Palladium 500 | ~1.40 |
| Sterling silver 925 | ~1.40 |
| Fine silver | ~1.35 |
| Argentium 935 | ~1.30 |
| Titanium | ~0.50 |
| Brass | ~1.60 |
| Bronze | ~1.50 |

Scale factor = 1 / (1 − shrinkage_pct / 100)

## Sprue diameter heuristic

`sprue_dia_mm = clamp(2.0, 6.0, 1.5 × volume_mm3^(1/3) / 10)` — calibrated so 200 mm³ → ~2.9 mm, 5 000 mm³ → ~5.3 mm. Industry range: 2–6 mm.

## Wax / resin densities

- WAX_DENSITY_G_CM3 = 0.93 g/cm³ (typical injection wax for lost-wax casting)
- RESIN_DENSITY_G_CM3 = 1.10 g/cm³ (Formlabs Castable Wax resin)

## Polish / file stock allowance

Rough-machined ring convention: 0.10–0.30 mm per side; default 0.15 mm.  
`finished_volume ≈ rough_volume × (1 − 3 × stock_mm / avg_dim_mm)`

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_shrink_compensate` | Read-only: return scale factor and scaled dimension for a given `alloy` and nominal dimension; required: `alloy`, optional `dimension_mm` |
| `jewelry_casting_tree` | Read-only: full casting-tree layout — trunk diameter, runner spacing, piece count, tree weight, flask yield ratio; required: `piece_volume_mm3`, `n_pieces`, `alloy`; optional: `trunk_dia_mm`, `runner_spacing_mm`, `feed_direction`, `flask_fill_mm` |
| `jewelry_hallmark_spec` | Read-only: generate hallmark/stamp placement spec — `fineness_stamp`, `maker_mark`, face, depth_mm, text_height_mm, position; required: `alloy`, optional `maker_mark` (4-char, default `KERF`) |
| `jewelry_production_weights` | Read-only: wax/resin pattern weight and cast metal weight for a piece and tree; required: `piece_volume_mm3`, `alloy`; optional `pattern_material` (wax/resin), `n_pieces` |
| `jewelry_batch_cost` | Read-only: per-piece and batch cost rollup — metal cost + casting fee + labour + stone cost; required: `piece_volume_mm3`, `alloy`, `metal_price_per_g`, optional labour / stone line items |
| `jewelry_ring_resize` | Read-only: compute scale factor to resize a ring from one finger size to another; required: `from_size`, `to_size`, `size_system`; returns `diameter_scale`, `volume_scale`, `weight_ratio` |
| `jewelry_polish_stock` | Read-only: compute finished volume from rough + stock allowance; required: `rough_volume_mm3`, optional `stock_mm` (default 0.15), `avg_dim_mm` |

## Example

Jeweller: "I have a 500 mm³ sterling silver ring. Get casting shrinkage, sprue spec, and hallmark."

1. `jewelry_shrink_compensate` — alloy=`sterling_silver_925`, dimension_mm=18.0 → scale_factor=1.0142, scaled dimension=18.256 mm
2. `jewelry_casting_tree` — piece_volume_mm3=500, n_pieces=8, alloy=`sterling_silver_925` → trunk_dia_mm=5.3, tree_weight_g≈46.7 g
3. `jewelry_hallmark_spec` — alloy=`sterling_silver_925`, maker_mark=`MYFM` → {fineness_stamp:"925", depth_mm:0.15, text_height_mm:0.8, face:"inner_band"}
