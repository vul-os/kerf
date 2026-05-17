# Jewelry Repair Estimator — `jewelry/repair.py`

Cost and time estimates for 12 common jewelry repair types, keyed to metal, stone, and regional labour rates.

---

## Repair types

| Key | Description |
|-----|-------------|
| `resize_ring` | Ring resizing (up or down, in sizes) |
| `prong_retipping` | Individual prong retipping (count of prongs) |
| `prong_rebuild` | Full prong rebuild from base |
| `solder_chain` | Solder a broken chain link |
| `clasp_replace` | Replace a clasp fitting |
| `polish_rhodium` | Polish + rhodium plate (white gold/silver) |
| `restring_pearls` | Pearl/bead restringing (see `stringing.py` for full detail) |
| `reset_stone` | Reset a loose stone |
| `replace_stone` | Replace a lost/damaged stone (stone cost separate) |
| `solder_shank` | Repair cracked/broken shank |
| `laser_weld` | Laser weld repair (precision, minimal heat) |
| `full_restoration` | Multi-step restoration (polish + solder + prongs) |

---

## Public API

### `estimate_repair(repair_type, *, metal="yellow_gold_18k", stone_ct=0.0, prong_count=1, size_change=0, labour_rate_usd_per_hr=75.0) → dict`

Returns:
```json
{
  "repair_type": "prong_retipping",
  "labour_hrs": 0.5,
  "labour_cost_usd": 37.50,
  "material_cost_usd": 8.00,
  "total_cost_usd": 45.50,
  "notes": "Per-prong rate; multiply by prong_count"
}
```

### `estimate_repair_batch(items: list[dict]) → list[dict]`

Batch version — pass a list of repair dicts, returns a list of estimate dicts.

---

## Usage

```python
from kerf_cad_core.jewelry.repair import estimate_repair

# Ring resize, white gold
est = estimate_repair("resize_ring", metal="white_gold_18k", size_change=2)
print(est["total_cost_usd"])

# 4 prongs retipped, yellow gold
est = estimate_repair("prong_retipping", prong_count=4, labour_rate_usd_per_hr=90.0)
```

---

## Notes

- Stone replacement cost is not included in `replace_stone` — add the stone market value separately.
- `labour_rate_usd_per_hr` is the jeweller's bench rate; typical range USD 60–120.
- Metal affects material cost only (gold weight consumed, solder type).
