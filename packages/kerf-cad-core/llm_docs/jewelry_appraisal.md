# Jewelry Appraisal — `jewelry/appraisal.py`

Insurance and market appraisal calculations for jewelry items: three valuation levels, metal spot pricing, gemstone tables, and labour/making charges.

---

## Valuation levels

| Level | Description | Typical use |
|-------|-------------|-------------|
| `replacement` | Full retail replacement cost | Insurance coverage |
| `fair_market` | Price a willing buyer/seller would agree | Estate, donation |
| `liquidation` | Quick-sale floor value | Probate, pawn |

Relationship: `replacement > fair_market > liquidation`.

---

## Public API

### `appraise_item(item_dict, *, level="replacement", spot_gold_usd_per_ozt=None, spot_silver_usd_per_ozt=None, labour_rate_usd_per_hr=75.0) → dict`

`item_dict` fields:

| Field | Description |
|-------|-------------|
| `metal` | e.g. `"yellow_gold_18k"`, `"platinum_950"`, `"sterling_silver"` |
| `metal_weight_g` | Finished weight in grams |
| `stones` | List of `{"cut": str, "carat": float, "clarity": str, "color": str}` |
| `making_hrs` | Estimated bench hours (craftsmanship uplift) |
| `design_premium` | 0–1.0 multiplier for designer/brand premium |

Returns:
```json
{
  "level": "replacement",
  "metal_value_usd": 420.50,
  "stone_value_usd": 1800.00,
  "making_charge_usd": 262.50,
  "design_premium_usd": 124.15,
  "total_usd": 2607.15,
  "breakdown": {...}
}
```

### `spot_metal_value(metal, weight_g, spot_usd_per_ozt) → float`

Metal melt value at given spot price.

### `stone_replacement_value(cut, carat, clarity, color) → float`

Per-stone replacement value from internal Rapaport-style table.

---

## Usage

```python
from kerf_cad_core.jewelry.appraisal import appraise_item

item = {
    "metal": "yellow_gold_18k",
    "metal_weight_g": 5.2,
    "stones": [{"cut": "round_brilliant", "carat": 0.5,
                "clarity": "VS1", "color": "F"}],
    "making_hrs": 3.5,
    "design_premium": 0.0,
}
result = appraise_item(item, level="replacement", spot_gold_usd_per_ozt=2000)
print(result["total_usd"])
```

---

## Notes

- Spot price defaults to module constants if `None`; pass live spot for current appraisals.
- Stone values use simplified Rapaport-style table — not a substitute for a certified GIA appraisal.
- `fair_market` applies a 0.65× multiplier to replacement; `liquidation` applies 0.40×.
