# Mount Finder — `jewelry/mount_finder.py`

Stone-to-mount matching: given a cut, carat weight, hardness, and target metal, returns compatible mounting styles ranked by suitability.

---

## Public API

### `find_mounts(cut, *, carat=1.0, mohs_hardness=7.0, metal="yellow_gold_18k", use="ring", budget_usd=None) → list[dict]`

Returns a ranked list of compatible mount styles:

```json
[
  {
    "style": "prong_4",
    "suitability_score": 0.92,
    "risk_level": "low",
    "notes": "Classic 4-prong solitaire; maximises light return",
    "estimated_cost_usd": 180.0
  },
  {
    "style": "bezel_full",
    "suitability_score": 0.85,
    "risk_level": "very_low",
    "notes": "Best protection for lower Mohs hardness stones"
  }
]
```

### `mount_requirements(style) → dict`

Returns the geometric and hardness constraints for a given mount style:
- `min_mohs`: minimum stone hardness recommended
- `suitable_cuts`: list of compatible cuts
- `prong_count` / `bezel_type` / etc.

### `list_cuts() → list[str]`

All recognised stone cuts: `round_brilliant`, `princess`, `cushion`, `emerald`, `oval`, `pear`, `marquise`, `radiant`, `asscher`, `heart`, `trillion`, `baguette`, `cabochon`.

---

## Usage

```python
from kerf_cad_core.jewelry.mount_finder import find_mounts

# Tanzanite (Mohs 6.5) oval — needs protective setting
mounts = find_mounts("oval", carat=1.5, mohs_hardness=6.5,
                     metal="platinum_950", use="ring")
for m in mounts[:3]:
    print(m["style"], m["suitability_score"], m["risk_level"])
```

---

## Notes

- Suitability score combines cut compatibility, hardness safety, use-case durability.
- Soft stones (Mohs < 7) score higher for bezel and channel settings than prong.
- `budget_usd` filters out styles whose `estimated_cost_usd` exceeds the budget.
