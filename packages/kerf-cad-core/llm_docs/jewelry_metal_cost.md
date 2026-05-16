# jewelry_metal_cost — Metal Weight, Casting Cost, and Full Jeweller's Quote

Pure-math metal weight estimator and full jeweller's quote engine: computes net and casting gross weight, itemised stone costs, labour, setting fees, finishing, markup, and optional multi-metal comparison — all from a part volume in mm³.

## When to use

Use this tool whenever a jeweller needs to:
- Estimate how many grams of 18k yellow/white/rose gold, platinum 950, sterling silver, or any other alloy a piece will weigh
- Calculate casting gross weight with sprue/button/flashing allowance (default 15%)
- Get weight in grams, dwt (pennyweights), and troy ounces
- Compute metal casting cost from a metal price per gram
- Build a full itemised quote with stone costs, bench labour hours, setting fees, finishing charges, and markup percentage
- Compare the same design across multiple metals (e.g. 18k yellow vs platinum vs sterling)
- Convert between grams, dwt, and troy ounces

Keywords: metal weight, casting weight, casting cost, gold price, platinum price, silver price, pennyweight, dwt, troy ounce, alloy, 18k gold, 14k gold, platinum 950, sterling silver, sprue, casting allowance, jeweller's quote, labour cost, setting fee, finishing, markup.

## Note on usage

`jewelry_metal_cost` is a **pure-math, read-only** tool — it does not write any `.feature` file. Supply `volume_mm3` from a CAD volume query (`GProp_GProps.Mass()` in mm model units) or from the output of a shape-creation tool. Metal prices are user-supplied inputs; use spot gold/silver prices plus your supplier's premium, or use the `usd_2024_approx` preset for orientation only.

## Valid metal keys

```
Gold:      10k_yellow  14k_yellow  18k_yellow  22k_yellow  24k_yellow
           10k_white   14k_white   18k_white   22k_white
           10k_rose    14k_rose    18k_rose    22k_rose
Platinum:  platinum_950  platinum_900
Palladium: palladium_950  palladium_500
Silver:    sterling_925  fine_silver  argentium_935
Other:     titanium  brass  bronze
```

## Example

Jeweller: "What does this ring cost to cast in 18k yellow gold, with one 1 ct round brilliant at $8,000/ct, 2 bench hours at $75/hr, prong setting, and 20% markup?"

`jewelry_metal_cost` — volume_mm3=950, metal=`18k_yellow`, metal_price_per_gram=38.0, stones=[{cut:`round_brilliant`, carat:1.0, price_per_carat:8000, count:1}], bench_hours=2, hourly_rate=75, setting_type=`prong`, markup_pct=20 → full quote breakdown
