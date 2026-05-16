# jewelry_tool_metal_cost — LLM Tool: jewelry_metal_cost

Registers the `jewelry_metal_cost` LLM tool with the Kerf tool registry. This is the agent-facing entry point for all metal weight, casting cost, and full jeweller's quote calculations.

## When to use

Use the `jewelry_metal_cost` tool whenever a jeweller chat agent needs to:
- Compute net metal weight (g / dwt / ozt) from a part volume in mm³
- Calculate casting gross weight with a configurable sprue/button allowance
- Build an itemised full quote: metal cost + stone costs + bench labour + setting fees + finishing + markup
- Compare costs across multiple alloys side-by-side
- Confirm the fineness hallmark for any alloy key (e.g. 18k = 750 parts per thousand)

This tool is **read-only** (no `.feature` file write). It is the single tool to reach for any costing, weight, or quote question about a jewelry piece.

Keywords: metal cost, weight estimate, casting cost, jeweller's quote, gold price, platinum price, silver price, alloy weight, sprue allowance, stone cost, labour, setting fee, finishing, markup, multi-metal comparison, pennyweight, troy ounce, dwt, volume to weight.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_metal_cost` | Computes metal weight and full casting cost/quote from `volume_mm3` and `metal` key (or `density_g_cm3`); optional: `metal_price_per_gram`, `price_preset`, `casting_allowance_pct`, `stones` list, `bench_hours`, `hourly_rate`, `setting_type`, `setting_fee_per_stone`, `finishing_type`, `finishing_cost`, `markup_pct`, `compare_metals`, `compare_prices`; returns net weight in g/dwt/ozt, casting gross weight, and full itemised quote |

### Key inputs

- `volume_mm3` (required) — part volume from `GProp_GProps.Mass()` in mm model units
- `metal` — alloy key (e.g. `18k_yellow`); see full list in `jewelry_metal_cost.md`
- `price_preset` — `usd_2024_approx` for orientation defaults (not live prices)
- `stones` — array of `{cut, carat, price_per_carat, count}` for stone line items
- `compare_metals` — list of alloy keys to include in a side-by-side comparison table

## Example

Jeweller: "Estimate the casting weight and cost of a platinum-950 ring with volume 1,200 mm³."

`jewelry_metal_cost` — volume_mm3=1200, metal=`platinum_950`, metal_price_per_gram=32.0, casting_allowance_pct=15 → net weight ≈ 25.7 g, casting gross ≈ 29.5 g, metal cost at supplied price
