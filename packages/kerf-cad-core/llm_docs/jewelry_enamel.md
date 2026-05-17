# Enamel Planning — `jewelry/enamel.py`

Firing schedule, cost model, and surface area estimates for five enamel techniques.

---

## Enamel techniques

| Key | Description |
|-----|-------------|
| `cloisonne` | Wire-outlined cells filled with enamel |
| `champlevé` | Recessed cells cut into metal, filled with enamel |
| `guilloché` | Engine-turned background under translucent enamel |
| `plique_a_jour` | Open-cell backless translucent enamel (stained-glass effect) |
| `painted` | Freehand painted enamel over opaque base |

---

## Public API

### `enamel_plan(technique, *, surface_area_mm2, cell_count=1, firing_count=None, kiln_temp_c=None, metal="copper", base_coat=True) → dict`

Returns:
```json
{
  "technique": "cloisonne",
  "firing_schedule": [
    {"stage": "base_coat", "temp_c": 820, "hold_min": 2},
    {"stage": "fill_1",    "temp_c": 820, "hold_min": 2},
    {"stage": "fill_2",    "temp_c": 820, "hold_min": 2},
    {"stage": "stone_out", "temp_c": 780, "hold_min": 1}
  ],
  "enamel_volume_mm3": 48.5,
  "enamel_cost_usd": 3.20,
  "labour_hrs": 4.5,
  "labour_cost_usd": 337.50,
  "total_cost_usd": 340.70,
  "notes": "Cloisonné wire solderd before first fire"
}
```

### `enamel_surface_area(geometry_dict) → float`

Estimates enamel-facing surface area in mm² from a geometry parameter dict (ring band, pendant, brooch face, etc.).

---

## Usage

```python
from kerf_cad_core.jewelry.enamel import enamel_plan

plan = enamel_plan(
    "cloisonne",
    surface_area_mm2=400.0,
    cell_count=24,
    metal="fine_silver"
)
print(plan["total_cost_usd"], plan["firing_schedule"])
```

---

## Notes

- `firing_count` defaults per technique: cloisonné 3–4, champlevé 2–3, guilloché 2, plique_a_jour 4–6, painted 3.
- `kiln_temp_c` defaults per technique and enamel type (soft/medium/hard); override for specific enamel brands.
- Fine silver and copper are the preferred metals; gold and fine silver fire most cleanly.
