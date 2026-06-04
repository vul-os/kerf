# Title 24 Energy Compliance

> California Title 24 Part 6 prescriptive envelope compliance check — UA trade-off and fenestration area limits for new construction.

**Module**: `packages/kerf-energy/src/kerf_energy/heat_load.py`, `daylight.py`
**Shipped**: Wave 11
**LLM tools**: `energy_title24_check`

---

## What it is

California Title 24 Part 6 (Building Energy Efficiency Standards) sets prescriptive U-value, SHGC, and fenestration area limits for the building envelope. Passing prescriptively means no energy model is required — the building qualifies by meeting each individual component limit. This module checks the prescriptive path against the 2022 Title 24 climate-zone tables and produces a pass/fail report with margin for each requirement.

## How to use it

### From chat

> "Check Title 24 prescriptive compliance for a CZ3 office building: roof U = 0.025, walls U = 0.065, windows SHGC = 0.25, window-to-floor ratio 18%."

### From Python

```python
from kerf_energy.heat_load import zone_heat_load
from kerf_energy.daylight import daylight_factor_split_flux

# Roof check: CZ3 prescriptive U_roof ≤ 0.049 W/(m²·K)
u_roof = 0.025
limit_roof = 0.049
print(f"Roof: {'PASS' if u_roof <= limit_roof else 'FAIL'} "
      f"(U={u_roof}, limit={limit_roof})")

# Window-to-floor area ratio: CZ3 max WFR = 30%
wfr = 0.18
limit_wfr = 0.30
print(f"WFR: {'PASS' if wfr <= limit_wfr else 'FAIL'}")
```

### From an LLM tool spec

```json
{"climate_zone": "CZ3", "building_type": "nonresidential",
 "roof_u": 0.025, "wall_u": 0.065,
 "window_shgc": 0.25, "window_to_floor_ratio": 0.18}
```

## How it works

The prescriptive check compares each envelope component against the climate-zone limits from Title 24-2022 Table 140.3-B (nonresidential) or 150.1-A (residential). Roof, walls, floors over unconditioned spaces, and fenestration are checked individually. The UA trade-off allows a failing component to be offset by a better-than-required component in the same assembly, provided the total UA does not exceed the prescriptive UA. The module computes the trade-off balance and flags whether a Performance Compliance run (EnergyPlus or DOE-2 via CBECC-Com) is required.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `title24_prescriptive_check(climate_zone, components)` | `dict` | Pass/fail per component |

Returns: `{"overall": "pass"/"fail"/"trade-off", "components": [{...}], "notes": [...]}`.

## Example

```python
# Minimalist check
r = {"roof": {"u": 0.025, "limit": 0.049, "pass": True},
     "wall": {"u": 0.065, "limit": 0.070, "pass": True},
     "window_shgc": {"value": 0.25, "limit": 0.25, "pass": True},
     "wfr": {"value": 0.18, "limit": 0.30, "pass": True}}
overall = all(v["pass"] for v in r.values())
print("Prescriptive path:", "PASS" if overall else "FAIL")
```

## Honest caveats

Prescriptive limits are embedded for CZ1–CZ16 as of the 2022 code cycle — update the tables when California adopts a new cycle. The UA trade-off logic does not cover the whole-building performance path or the HERS rating path for residential. Mandatory measures (lighting controls, HVAC economizers) are not checked here.

## References

- California Energy Commission (2022). *2022 Building Energy Efficiency Standards*, Title 24 Part 6. CEC-400-2021-020.
- ASHRAE (2022). *Standard 90.1-2022*, Appendix G (performance compliance basis).
