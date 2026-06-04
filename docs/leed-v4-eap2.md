# LEED v4 EA Prerequisite 2 — Minimum Energy Performance

> Whole-building energy cost savings and EUI targets for LEED v4 EA Credit: Optimize Energy Performance (up to 18 points).

**Module**: `packages/kerf-energy/src/kerf_energy/heat_load.py`, `solar.py`
**Shipped**: Wave 12
**LLM tools**: `energy_leed_eap2`

---

## What it is

LEED v4 Energy & Atmosphere Prerequisite 2 (EAp2) requires the proposed building to be designed to a minimum of 5% better energy cost than the ASHRAE 90.1-2010 baseline model. The EA Credit: Optimize Energy Performance then awards additional points for each further 1–2% improvement, up to 18 points for 50%+ improvement. This module computes the estimated energy cost improvement using simplified whole-building loads and helps position the design relative to LEED point thresholds.

## How to use it

### From chat

> "Estimate the LEED EA credit points for a 3000 m² office in CZ3. Proposed model: chiller COP 5.5, roof U = 0.03, WWR = 22%. Baseline: ASHRAE 90.1-2010 CZ3 defaults."

### From Python

```python
from kerf_energy.heat_load import zone_heat_load

proposed_eui = 95.0   # kBtu/ft² from energy model
baseline_eui  = 120.0  # ASHRAE 90.1-2010 CZ3 baseline
improvement = (baseline_eui - proposed_eui) / baseline_eui * 100
print(f"Energy improvement: {improvement:.1f}%")

# LEED v4 points: new construction, office
if improvement >= 5:
    # Map improvement % to points (LEED v4 NC Table EAc2)
    points = min(18, max(0, int((improvement - 5) / 3) + 1))
    print(f"EA credit points: {points}")
```

### From an LLM tool spec

```json
{"building_type": "office", "floor_area_m2": 3000,
 "climate_zone": "CZ3",
 "proposed_eui_kwh_m2": 105, "baseline_eui_kwh_m2": 135,
 "leed_version": "v4"}
```

## How it works

The module computes an estimated whole-building Energy Use Intensity (EUI) by summing heating, cooling, lighting, and equipment end-uses from the CLTD heat-load and daylight-factor modules. The baseline EUI is taken from ASHRAE 90.1-2010 Appendix G for the building type and climate zone. Energy cost improvement is the percentage reduction in simulated annual energy cost versus the baseline. LEED v4 NC Table EAc2 maps this improvement percentage to credit points on a stepped scale starting at 6% (1 point) up to 50%+ (18 points).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `leed_eap2_check(proposed_eui, baseline_eui, building_type)` | `dict` | Pass/fail + credit point estimate |

Returns: `{"prerequisite_met": bool, "improvement_pct": float, "estimated_points": int, "notes": [...]}`.

## Example

```python
r = {"improvement_pct": 22.5}
points = min(18, max(0, int((r["improvement_pct"] - 5) / 3) + 1))
print(f"~{points} EA credit points")  # ~6 points
```

## Honest caveats

This module estimates LEED points from simplified EUI calculations — it does not replace a full ASHRAE 90.1 Appendix G energy model (EnergyPlus, eQUEST, or OpenStudio). Actual LEED certification requires a third-party CxA-reviewed energy model. EUI-to-cost conversion uses a fixed electricity cost of $0.12/kWh and gas cost of $0.60/therm; update these for your utility rates.

## References

- US Green Building Council (2014). *LEED v4 for Building Design and Construction*, EA Prerequisite 2, EA Credit: Optimize Energy Performance.
- ASHRAE (2010). *Standard 90.1-2010*, Appendix G — Performance Rating Method.
