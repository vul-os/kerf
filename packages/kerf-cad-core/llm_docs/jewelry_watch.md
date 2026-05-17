# Watch Case Parametrics — `jewelry/watch.py`

Parametric watch case geometry: round, cushion, and tonneau case profiles; bezel styles; movement catalog integration.

---

## Case shapes

| Shape | Parameters |
|-------|-----------|
| `round` | `diameter_mm`, `lug_width_mm`, `thickness_mm` |
| `cushion` | `width_mm`, `height_mm`, `corner_radius_mm`, `thickness_mm` |
| `tonneau` | `width_mm`, `height_mm`, `barrel_radius_mm`, `thickness_mm` |

---

## Bezel styles

`flat`, `domed`, `fluted`, `diamond_set`, `coin_edge`, `rotating_diver`

---

## Public API

### `case_params(shape, *, diameter_mm=40.0, width_mm=40.0, height_mm=45.0, lug_width_mm=20.0, corner_radius_mm=5.0, barrel_radius_mm=20.0, thickness_mm=10.0, bezel_style="flat") → dict`

Returns a parameter dict describing the case geometry suitable for CAD feature construction.

### `movement_clearance(movement_ref, case_params_dict) → dict`

Checks whether a named movement fits within the case:

```json
{
  "fits": true,
  "movement_ref": "ETA_2824",
  "clearance_dial_mm": 1.2,
  "clearance_height_mm": 0.8,
  "warnings": []
}
```

### `lug_geometry(case_params_dict) → dict`

Returns lug geometry: `lug_width_mm`, `lug_length_mm`, `spring_bar_dia_mm`, `lug_spread_mm`.

### `list_movements() → list[str]`

Returns all movement references in the internal catalog (ETA, Miyota, Sellita, Seiko NH families).

---

## Usage

```python
from kerf_cad_core.jewelry.watch import case_params, movement_clearance

params = case_params("round", diameter_mm=39, thickness_mm=9.5, bezel_style="domed")
fit = movement_clearance("ETA_2824", params)
if not fit["fits"]:
    print(fit["warnings"])
```

---

## Notes

- Case geometry is returned as a parameter dict; use with the B-rep builders (`brep_build.py`) or feature evaluators to produce actual solid geometry.
- `lug_width_mm` must match a standard spring-bar size (16–24 mm).
