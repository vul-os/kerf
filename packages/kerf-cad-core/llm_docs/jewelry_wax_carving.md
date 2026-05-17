# Wax Carving Planner — `jewelry/wax_carving.py`

Stock selection, roughing/detail stage planning, and cast weight estimation for lost-wax carving.

---

## Stock types

| Type | Description |
|------|-------------|
| `tube_wax` | Hollow tube — rings, bangles |
| `block_wax` | Solid block — pendants, brooches, free-form |
| `sheet_wax` | Flat sheet — thin panels, appliqués |
| `wire_wax` | Round/square wire — prongs, frames |

Wax hardness grades: `blue` (hard, brittle, fine detail), `purple` (medium), `green` (flexible, undercuts), `pink` (injection wax, soft).

---

## Public API

### `carving_plan(geometry_dict, *, wax_grade="blue", stock_type="block_wax", finish="hand_polish") → dict`

`geometry_dict` must contain: `envelope_x_mm`, `envelope_y_mm`, `envelope_z_mm`, `final_volume_mm3`.

Returns:
```json
{
  "stock_type": "block_wax",
  "stock_dims": {"x_mm": 35, "y_mm": 25, "z_mm": 20},
  "wax_grade": "blue",
  "roughing_stage": {
    "material_removed_pct": 60,
    "tool_recs": ["wax bur 3 mm ball", "flex shaft"],
    "time_est_hrs": 1.5
  },
  "detail_stage": {
    "tool_recs": ["wax carver", "needle files", "scraper"],
    "time_est_hrs": 2.0
  },
  "finishing_stage": {"time_est_hrs": 0.5},
  "total_carving_hrs": 4.0
}
```

### `cast_weight(wax_volume_mm3, metal) → dict`

Estimates cast metal weight from wax volume using metal-specific density and casting shrinkage:

```json
{
  "wax_volume_mm3": 850.0,
  "metal": "yellow_gold_18k",
  "density_g_cm3": 15.5,
  "shrinkage_pct": 4.5,
  "estimated_cast_weight_g": 13.8,
  "sprue_allowance_g": 2.1,
  "total_metal_needed_g": 15.9
}
```

---

## Usage

```python
from kerf_cad_core.jewelry.wax_carving import carving_plan, cast_weight

plan = carving_plan(
    {"envelope_x_mm": 30, "envelope_y_mm": 20, "envelope_z_mm": 15,
     "final_volume_mm3": 900},
    wax_grade="blue", stock_type="block_wax"
)

weight = cast_weight(plan["stock_dims"]["x_mm"] *
                     plan["stock_dims"]["y_mm"] *
                     plan["stock_dims"]["z_mm"] * 0.6,
                     metal="yellow_gold_18k")
print(weight["total_metal_needed_g"])
```

---

## Notes

- Shrinkage factor is metal-specific: gold ~4–5%, silver ~5–6%, platinum ~3–4%.
- Sprue allowance defaults to 15% of part volume.
- Blue wax suited for high-detail work; green wax for undercuts and flexible removal.
