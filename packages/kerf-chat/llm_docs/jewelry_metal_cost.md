# Jewelry metal weight, casting cost & full jeweller's quote

Use the `jewelry_metal_cost` tool to estimate how much a jewelry part weighs
in a given metal, what gross metal you need to order for casting, itemised
gemstone costs, labour / setting / finishing, and a complete quote with markup.

## When to use

- A user asks "how much will this ring weigh in 18k gold?" or "compare the
  casting cost in platinum vs. sterling silver"
- After building a `.feature` file or `.jscad` model, the user wants a
  quick material cost before sending to a caster
- Helping pick a metal based on cost targets
- Producing a full jeweller's quote including centre stone, side stones,
  bench time, setting, and rhodium plating

## Tool inputs

```json
{
  "volume_mm3": 300.0,          // required — part volume in mm³
  "metal": "18k_yellow",        // or density_g_cm3 for custom alloys

  // Metal price — one of:
  "metal_price_per_gram": 48.0, // explicit per-gram price (takes priority)
  "price_preset": "usd_2024_approx", // orientation defaults (NOT live prices)

  "casting_allowance_pct": 15,  // default 15; 10–25 typical range

  // Gemstone cost line items (optional)
  "stones": [
    {
      "cut": "round_brilliant",
      "carat": 0.5,             // explicit carat weight (preferred)
      "price_per_carat": 2000.0,
      "count": 1,
      "note": "VS1 G colour"
    },
    {
      "cut": "pave",
      "mm": 1.8,                // alternatively: stone diameter in mm
      "price_per_carat": 150.0,
      "count": 24
    }
  ],

  // Labour & setting (parametric, optional)
  "bench_hours": 4.0,           // bench hours
  "hourly_rate": 75.0,          // hourly rate in your currency
  "setting_type": "prong",      // prong|bezel|pave|channel|flush|invisible|tension|bar
  "setting_fee_per_stone": 12.0, // override default fee per stone

  // Finishing (optional)
  "finishing_type": "rhodium",  // named finishing type
  "finishing_cost": 35.0,       // or explicit override

  // Markup
  "markup_pct": 20.0,           // markup on subtotal; default 0

  // Multi-metal comparison (optional)
  "compare_metals": ["14k_yellow", "sterling_925", "platinum_950"],
  "compare_prices": {
    "14k_yellow": 37.5,
    "sterling_925": 0.80,
    "platinum_950": 32.0
  }
}
```

Either `metal` or `density_g_cm3` must be provided; `density_g_cm3` takes
priority and lets you pass the density from a `.material` file:
```
density_g_cm3 = mat["physical"]["rho_kg_m3"] / 1000.0
```

Stone carat weight can come directly from the gemstones tool output. Supply
`carat` (exact) or `mm` (estimated via standard mm→carat formula). Carat is
always preferred for accuracy.

## Full quote result schema

```json
{
  "metal": "18k_yellow",
  "label": "18k Yellow Gold",
  "hallmark": 750,
  "density_g_cm3": 15.58,
  "volume_mm3": 300.0,
  "net_grams": 4.674,
  "net_dwt": 3.004,
  "net_ozt": 0.1503,
  "allowance_pct": 15.0,
  "gross_grams": 5.375,
  "metal_price_per_gram": 48.0,
  "metal_cost": 258.00,
  "casting_cost": 258.00,
  "stones": {
    "line_items": [
      {"cut": "round_brilliant", "carat_each": 0.5, "count": 1,
       "price_per_carat": 2000.0, "line_total": 1000.0, "note": "VS1 G colour"}
    ],
    "total_carats": 0.5,
    "total_stones": 1,
    "total_cost": 1000.0
  },
  "stone_cost": 1000.0,
  "labour": {
    "bench_hours": 4.0,
    "hourly_rate": 75.0,
    "bench_labour_cost": 300.0,
    "setting_type": "prong",
    "setting_fee_per_stone": 12.0,
    "stone_count": 1,
    "setting_cost": 12.0,
    "finishing_type": "rhodium",
    "finishing_cost": 35.0,
    "total_labour": 347.0
  },
  "labour_total": 347.0,
  "subtotal": 1605.0,
  "markup_pct": 20.0,
  "markup_amount": 321.0,
  "total": 1926.0
}
```

When no stones / labour / markup / finishing_type / price_preset are used,
the tool takes the legacy `casting_cost` path and returns the simpler schema
(for backwards compatibility with existing prompts):

```json
{
  "net_grams": ..., "gross_grams": ..., "metal_cost": ...,
  "labor": ..., "finishing": ..., "total_cost": ...
}
```

## Metal density table (g/cm³)

Sources: World Gold Council Handbook on Gold Alloys, Legor Group data sheets
(2023), Platinum Guild International, Handy & Harman, NIST, CDA, Argentium International.

| Key               | Metal                     | g/cm³ | Hallmark |
|-------------------|---------------------------|-------|----------|
| 10k_yellow        | 10k Yellow Gold           | 11.57 | 417      |
| 14k_yellow        | 14k Yellow Gold           | 13.07 | 583      |
| 18k_yellow        | 18k Yellow Gold           | 15.58 | 750      |
| 22k_yellow        | 22k Yellow Gold           | 17.80 | 917      |
| 24k_yellow        | 24k Yellow Gold (Fine)    | 19.32 | 999      |
| 10k_white         | 10k White Gold            | 11.61 | 417      |
| 14k_white         | 14k White Gold            | 13.25 | 583      |
| 18k_white         | 18k White Gold            | 15.60 | 750      |
| 22k_white         | 22k White Gold            | 17.60 | 917      |
| 10k_rose          | 10k Rose Gold             | 11.59 | 417      |
| 14k_rose          | 14k Rose Gold             | 13.20 | 583      |
| 18k_rose          | 18k Rose Gold             | 15.45 | 750      |
| 22k_rose          | 22k Rose Gold             | 17.75 | 917      |
| platinum_950      | Platinum 950              | 21.40 | 950      |
| platinum_900      | Platinum 900              | 21.30 | 900      |
| palladium_950     | Palladium 950             | 11.00 | 950      |
| palladium_500     | Palladium 500             | 10.60 | 500      |
| sterling_925      | Sterling Silver 925       | 10.36 | 925      |
| fine_silver       | Fine Silver               | 10.49 | 999      |
| argentium_935     | Argentium Silver 935      | 10.40 | 935      |
| titanium          | Titanium (Grade 2)        |  4.51 | —        |
| brass             | Brass (70/30)             |  8.53 | —        |
| bronze            | Bronze (90/10)            |  8.78 | —        |

## Setting types & default fees (USD)

| Key        | Description                        | Default $/stone |
|------------|------------------------------------|-----------------|
| prong      | Prong / claw setting               | $12             |
| bezel      | Bezel / rub-over setting           | $18             |
| pave       | Pavé / micro-pavé                  |  $5             |
| channel    | Channel setting                    |  $8             |
| flush      | Flush / gypsy setting              | $10             |
| invisible  | Invisible setting                  | $22             |
| tension    | Tension setting                    | $25             |
| bar        | Bar setting                        | $10             |

Override with `setting_fee_per_stone` if your bench rate differs.

## Finishing types & default costs (USD)

| Key           | Description                  | Default $ |
|---------------|------------------------------|-----------|
| polish        | High-polish                  |  $0 (in labour) |
| satin         | Satin / brushed              | $15       |
| hammer        | Hammered texture             | $20       |
| rhodium       | Rhodium plating (white gold) | $35       |
| black_rhodium | Black rhodium plating        | $45       |
| gold_plate    | Gold vermeil / plating       | $25       |
| antique       | Antiquing / oxidation        | $20       |
| sandblast     | Sandblasted matte            | $18       |

## Price presets

`price_preset: "usd_2024_approx"` provides orientation-only spot-derived
USD/g prices. These are **NOT live prices** — they are approximate midpoints
for a broad 2024 range. Always ask the user to verify with their supplier.

The preset is only used when `metal_price_per_gram` is 0. An explicit
`metal_price_per_gram` always wins.

## Formulas

### Volume → net weight

```
volume_cm3  = volume_mm3 / 1000
net_grams   = density_g_cm3 × volume_cm3
```

### Net weight → dwt / ozt

```
pennyweight (dwt) = grams / 1.55517384   (1 dwt = 1/20 ozt)
troy ounce (ozt)  = grams / 31.1034768   (NIST)
```

### Casting gross weight

```
gross_grams     = net_grams × (1 + casting_allowance_pct / 100)
allowance_grams = gross_grams − net_grams
```

### Stone cost

```
line_total = carat_each × price_per_carat × count
stone_cost = sum(line_total for all specs)
```

If `mm` is supplied instead of `carat` (round brilliant approximation):
```
carat ≈ diameter_mm³ × 0.00370   (factor varies by cut)
```
Use explicit `carat` when accuracy matters.

### mm → carat factors (approximate)

| Cut             | Factor   |
|-----------------|----------|
| round_brilliant | 0.00370  |
| princess        | 0.00390  |
| oval            | 0.00280  |
| cushion         | 0.00350  |
| pear            | 0.00240  |
| marquise        | 0.00200  |
| emerald         | 0.00240  |
| asscher         | 0.00350  |
| radiant         | 0.00360  |
| heart           | 0.00230  |

### Full cost breakdown

```
metal_cost    = gross_grams × metal_price_per_gram
stone_cost    = sum of stone line items
labour_total  = (bench_hours × hourly_rate)
              + (setting_fee_per_stone × stone_count)
              + finishing_cost
subtotal      = metal_cost + stone_cost + labour_total
markup_amount = subtotal × markup_pct / 100
total         = subtotal + markup_amount
```

## Casting allowance rationale

Lost-wax casting always produces more metal waste than the finished part:

- **Sprue**: the channel connecting the model to the sprue base; 8–12% of net
  weight for typical hollow shanks, more for thick or multi-gated pieces.
- **Button**: the disc of metal that solidifies in the flask button cup; 3–5%.
- **Flashing**: thin fins at parting lines; 1–3%.

The **default 15%** is the industry midpoint for single-gate vacuum–pressure
casting of rings and pendants. Use 10% for CNC-cut wax with optimised
spruing; use 20–25% for complex multi-piece or very thick castings.

## Worked example

An 18k yellow gold ring, size 7 (US), 300 mm³, with a 0.5 ct VS1 G round
brilliant at $2 000/ct, 4 hours bench labour at $75/h, prong setting, rhodium:

```
net_grams   = 15.58 × 0.3 = 4.674 g
gross_grams = 4.674 × 1.15 = 5.375 g  (15% casting)
metal_cost  = 5.375 × $48 = $258.00

stone_cost  = 0.5 ct × $2 000 = $1 000.00

bench       = 4h × $75 = $300.00
setting     = 1 × $12 = $12.00 (prong)
finishing   = $35.00 (rhodium)
labour_total = $347.00

subtotal    = $258 + $1000 + $347 = $1 605.00
markup 20%  = $321.00
total       = $1 926.00
```

## Notes on metal prices

There is **no live price feed** in Kerf. Ask the user to enter a current
price per gram. Common reference points (these change daily):

- **Fine gold spot** (~$64 USD/g at ~$2 000/ozt)
- **18k yellow** ≈ 75% × fine gold spot + alloy cost, typically ~$45–50/g
- **Sterling silver** ≈ ~$0.80–1.10/g
- **Platinum 950** ≈ $28–40/g
- **Palladium 950** ≈ $35–50/g

Always remind the user that casting-house prices include alloy preparation
and may differ from spot metal cost.

## Getting volume from a model

In the OCCT worker (JavaScript side):

```js
const props = new OCC.GProp_GProps()
OCC.brepgprop.VolumeProperties(shape, props, 1e-5)
const volumeMm3 = props.Mass()  // mm³ when model units are mm
```

In the Python pyworker:

```python
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.GProp import GProp_GProps
props = GProp_GProps()
brepgprop.VolumeProperties(shape, props)
volume_mm3 = props.Mass()
```

## Deferred UI note

A `JewelryCostPanel.jsx` frontend component for displaying the full quote
breakdown (metal + stone line items + labour table + markup slider) is out
of scope for this implementation. The tool returns a complete JSON quote
schema that a future panel can consume without API changes.
