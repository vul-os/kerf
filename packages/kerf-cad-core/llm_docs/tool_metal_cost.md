# jewelry_metal_cost

*Module: `kerf_cad_core.jewelry.tool_metal_cost` · Domain: cad*

## Description

Estimate metal weight and casting cost for a jewelry piece, with optional gemstone cost, labour, setting fees, finishing, and a full jeweller's quote.

Given a part volume (in mm³) and metal selection, returns:
  - net weight (g / dwt / ozt)
  - casting gross weight with sprue/button/flashing allowance
  - itemised stone cost line items (if stones provided)
  - labour, setting, and finishing costs
  - full quote breakdown with configurable markup
  - optional multi-metal comparison table

Volume can be entered manually or read from a OCCT volume query (GProp_GProps.Mass() in mm model units). Metal price is a user input — no live feed. Use spot gold/silver prices as a baseline and add your supplier's premium. Alternatively supply a price_preset name (e.g. 'usd_2024_approx') for orientation-only defaults.

Valid metal keys (pass as `metal`):
  Gold:      10k_yellow, 14k_yellow, 18k_yellow, 22k_yellow, 24k_yellow
             10k_white,  14k_white,  18k_white,  22k_white
             10k_rose,   14k_rose,   18k_rose,   22k_rose
  Platinum:  platinum_950, platinum_900
  Palladium: palladium_950, palladium_500
  Silver:    sterling_925, fine_silver, argentium_935
  Other:     titanium, brass, bronze

Stone specs (for stones list):
  cut, carat (or mm), price_per_carat, count, note
  Carat can come directly from the gemstones tool output.

Setting types: prong, bezel, pave, channel, flush, invisible, tension, bar
Finishing types: polish, satin, hammer, rhodium, black_rhodium, gold_plate, antique, sandblast

## Input schema

```json
{
  "type": "object",
  "properties": {
    "volume_mm3": {
      "type": "number",
      "description": "Part volume in cubic millimetres. In OCCT/Kerf this is the value returned by GProp_GProps.Mass() when model units are mm."
    },
    "metal": {
      "type": "string",
      "description": "Metal key.  See tool description for the full list. Mutually exclusive with density_g_cm3."
    },
    "density_g_cm3": {
      "type": "number",
      "description": "Explicit density override in g/cm\u00b3. Use when you have already resolved the density from a .material file (physical.rho_kg_m3 / 1000). Mutually exclusive with metal."
    },
    "metal_price_per_gram": {
      "type": "number",
      "description": "Metal price in your currency per gram. Example: 18k yellow gold \u2248 $38 USD/g at ~$1950/ozt spot (varies daily; check your supplier). Default 0. Overrides price_preset when non-zero."
    },
    "price_preset": {
      "type": "string",
      "description": "Named price preset for orientation defaults. Currently available: 'usd_2024_approx'. Only used when metal_price_per_gram is 0. These are NOT live prices \u2014 always verify with your supplier."
    },
    "casting_allowance_pct": {
      "type": "number",
      "description": "Sprue / button / flashing overhead as a percentage of net weight. Default 15. Typical range 10 (optimised gate) \u2013 25 (complex mould)."
    },
    "stones": {
      "type": "array",
      "description": "Optional list of stone specs for gemstone cost line items. Each item: {cut, carat (or mm), price_per_carat, count, note}. Carat can come from the gemstones tool output. Do not use if there are no stones.",
      "items": {
        "type": "object",
        "properties": {
          "cut": {
            "type": "string"
          },
          "carat": {
            "type": "number"
          },
          "mm": {
            "type": "number"
          },
          "price_per_carat": {
            "type": "number"
          },
          "count": {
            "type": "integer"
          },
          "note": {
            "type": "string"
          }
        },
        "required": [
          "price_per_carat"
        ]
      }
    },
    "bench_hours": {
      "type": "number",
      "description": "Bench labour hours. Default 0."
    },
    "hourly_rate": {
      "type": "number",
      "description": "Bench hourly rate in your currency. Default 0."
    },
    "setting_type": {
      "type": "string",
      "description": "Stone setting style: prong, bezel, pave, channel, flush, invisible, tension, bar. Default 'prong'."
    },
    "setting_fee_per_stone": {
      "type": "number",
      "description": "Override per-stone setting fee. If absent, uses the default fee for setting_type."
    },
    "finishing_type": {
      "type": "string",
      "description": "Named finishing: polish, satin, hammer, rhodium, black_rhodium, gold_plate, antique, sandblast. If absent, no finishing charge is added."
    },
    "finishing_cost": {
      "type": "number",
      "description": "Explicit finishing cost override (overrides finishing_type default)."
    },
    "markup_pct": {
      "type": "number",
      "description": "Markup percentage applied to subtotal (e.g. 20 = +20%). Default 0 (no markup). Must be >= 0."
    },
    "labor": {
      "type": "number",
      "description": "Legacy flat bench labor cost (casting + cleanup + polish). Use bench_hours + hourly_rate for the full parametric model. When both are supplied, bench_hours \u00d7 hourly_rate is used and labor is ignored for the full quote."
    },
    "finishing": {
      "type": "number",
      "description": "Legacy flat finishing / plating / rhodium cost. Use finishing_type or finishing_cost for the parametric model."
    },
    "compare_metals": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Optional list of metal keys to include in a multi-metal comparison table in addition to the primary estimate. If omitted no comparison table is returned."
    },
    "compare_prices": {
      "type": "object",
      "description": "Optional per-metal price overrides for the comparison table {metal_key: price_per_gram}. Metals absent from this map use price 0 (weight-only rows).",
      "additionalProperties": {
        "type": "number"
      }
    }
  },
  "required": [
    "volume_mm3"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="jewelry_metal_cost",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
