# Family Ring Builder — `jewelry/family_ring.py`

Birthstone family ring generator: places birthstones for family members in one of five arrangement patterns on a shank.

---

## Arrangement types

| Type | Description |
|------|-------------|
| `linear` | Stones in a row across the band (classic bar-set) |
| `cluster` | Central stone surrounded by satellite stones |
| `chevron` | V-shaped arrangement |
| `stacked` | Layered rows for larger families |
| `spiral` | Stones wind around the shank |

---

## Birthstone catalog

January → Garnet, February → Amethyst, March → Aquamarine, April → Diamond,
May → Emerald, June → Pearl/Alexandrite, July → Ruby, August → Peridot,
September → Sapphire, October → Opal/Tourmaline, November → Citrine/Topaz,
December → Blue Topaz/Tanzanite.

---

## Public API

### `family_ring(members, *, shank_width_mm=4.0, shank_style="comfort_fit", arrangement="linear", metal="yellow_gold_14k", stone_size_mm=3.0) → dict`

`members` is a list of `{"name": str, "birth_month": int}` dicts (1–12).

Returns:
```json
{
  "arrangement": "linear",
  "stone_count": 4,
  "stones": [
    {"name": "Alice", "month": 3, "stone": "Aquamarine",
     "color": "#70C1B3", "position_mm": -6.0},
    ...
  ],
  "shank_width_mm": 4.0,
  "total_width_mm": 26.0,
  "metal": "yellow_gold_14k",
  "estimated_cost_usd": 420.0,
  "notes": "Shank widened to accommodate 4 stones at 3 mm each + 2 mm spacing"
}
```

### `birthstone_for_month(month: int) → dict`

Returns `{"stone": str, "color_hex": str, "mohs": float}` for a given month (1–12).

---

## Usage

```python
from kerf_cad_core.jewelry.family_ring import family_ring

members = [
    {"name": "Mom", "birth_month": 5},
    {"name": "Dad", "birth_month": 9},
    {"name": "Child 1", "birth_month": 3},
    {"name": "Child 2", "birth_month": 12},
]
ring = family_ring(members, arrangement="chevron", metal="white_gold_14k")
print(ring["stones"])
print(ring["total_width_mm"])
```

---

## Notes

- Maximum recommended stones for `linear`: 7 (shank width limits). Beyond 7 use `stacked`.
- `stone_size_mm` is the stone diameter (round) or longest dimension (fancy).
- `estimated_cost_usd` includes metal and stone cost; making charge not included.
