# Laser Hallmark and Production Tools — `jewelry/production.py`

Production utilities: mold-shrinkage compensation, sprue/casting-tree layout, hallmark/stamp placement, weight estimates, and batch cost rollup.

There is no standalone `laser_marking.py` module — hallmark/laser-stamp functionality is `hallmark_spec` and related functions in `production.py`.

---

## Public API

### `hallmark_spec(alloy, *, maker_mark="KERF", face="inner_band", depth_mm=0.15, text_height_mm=0.8) → dict`

Returns a laser-hallmark placement specification:
```json
{
  "fineness_stamp": "750",
  "maker_mark": "KERF",
  "face": "inner_band",
  "depth_mm": 0.15,
  "text_height_mm": 0.8,
  "position": "centre",
  "notes": "Industry standard: 0.15 mm depth for laser hallmark"
}
```

Alloy keys: `yellow_gold_18k` → `"750"`, `yellow_gold_14k` → `"585"`, `platinum_950` → `"950"`, `sterling_silver` → `"925"`, etc.

### `mold_shrinkage_scale(alloy) → float`

Returns the uniform scale factor `1 / (1 − shrinkage_pct / 100)` for wax/resin pattern oversizing.

### `casting_tree_layout(pieces, *, trunk_dia_mm=5.0, runner_spacing_mm=8.0, feed_direction="bottom_up") → dict`

Auto-places N pieces on a casting tree:
```json
{
  "piece_count": 8,
  "tree_height_mm": 95.0,
  "total_wax_weight_g": 42.5,
  "total_metal_weight_g": 186.0,
  "sprue_diameters_mm": [2.9, 2.9, ...],
  "layout": [{"piece_id": 0, "z_mm": 15.0, "angle_deg": 0.0}, ...]
}
```

### `piece_weight(volume_mm3, alloy) → dict`

Returns `{"wax_g": ..., "metal_g": ..., "sprue_dia_mm": ...}`.

### `batch_cost(pieces, alloy, *, casting_fee_usd=25.0, labour_per_piece_usd=15.0, spot_gold_usd_per_ozt=None) → dict`

Batch cost rollup: metal + casting + labour + stone cost (stones passed in `pieces` list).

### `finger_size_scale(ring_params, target_size, *, system="US") → dict`

Uniform scale to convert a finished ring to a target finger size.

---

## Usage

```python
from kerf_cad_core.jewelry.production import (
    hallmark_spec, mold_shrinkage_scale, casting_tree_layout, piece_weight
)

# Hallmark spec for 18k yellow gold
stamp = hallmark_spec("yellow_gold_18k", maker_mark="ACME")

# Scale factor for wax pattern
scale = mold_shrinkage_scale("yellow_gold_18k")  # ≈ 1.047

# Layout 6 identical pieces on a tree
pieces = [{"volume_mm3": 850}] * 6
tree = casting_tree_layout(pieces, feed_direction="bottom_up")
print(tree["total_metal_weight_g"])
```

---

## References

- Legor Group alloy data sheets (2023)
- Platinum Guild International technical notes
- Stuller Inc. alloy reference guide
- Chvorinov's rule (sprue diameter heuristic)
