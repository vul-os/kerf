# Fabrication Quoting (`quoting`)

One-click fabrication quote engine: given a part geometry summary,
classifies viable manufacturing processes, estimates unit cost for each,
and returns a ranked recommendation with a formatted chat report.

---

## When to use

Reach for this tool when the user asks about:

- "how much would this part cost to make?"
- comparing CNC vs. casting vs. injection moulding vs. 3D printing vs. forging
- identifying which processes are blocked by undercuts, thin walls, lack of draft
- getting a cost-sorted process table with blockers and advantages
- which manufacturing process is best for a given tolerance class or quantity

---

## Tool

### `fab_quote`

Given a part geometry summary dict, runs the full pipeline:
`analyze_part` → `viable_processes` → `cost_per_process` → `recommend` →
`quote_report` and returns all results.

**Required:** `geometry_summary` (dict)
**Optional:** `quantity` (int, default 1)

**`geometry_summary` fields** (all optional, safe defaults applied):

| Field | Unit | Default | Description |
|-------|------|---------|-------------|
| `bbox_x/y/z` | mm | 100 | Bounding-box dimensions |
| `volume_cm3` | cm³ | 100 | Solid volume |
| `surface_area_cm2` | cm² | 200 | Total surface area |
| `mass_kg` | kg | 0.5 | Estimated mass |
| `num_holes` | — | 0 | Total hole count |
| `num_threads` | — | 0 | Threaded feature count |
| `num_undercuts` | — | 0 | Undercut count |
| `thin_wall_count` | — | 0 | Thin-wall region count |
| `min_wall_mm` | mm | 3.0 | Thinnest wall |
| `draft_angle_deg` | deg | 0 | Minimum draft angle |
| `is_flat_blank` | bool | false | Sheet-metal compatible |
| `num_bends` | — | 0 | Sheet-metal bend count |
| `complexity_score` | 0–1 | 0.3 | Normalised complexity |
| `requires_high_strength` | bool | false | Forging indicator |
| `is_symmetric` | bool | false | Rotational/mirror symmetry |
| `tolerance_class` | str | medium | coarse/medium/fine/precision |
| `finish_quality` | str | standard | rough/standard/fine/optical |
| `material_cost_per_kg` | USD/kg | 5.0 | Raw material unit cost |

**Returns:**

```json
{
  "ok": true,
  "part_summary": {"bbox_mm": [...], "volume_cm3": ..., "mass_kg": ..., "tolerance_class": "...", "complexity_score": ...},
  "viable_processes": [{"process": "CNC", "viability_score": 0.85, "blockers": [], "advantages": [...]}, ...],
  "cost_table": [{"process": "...", "viability_score": ..., "unit_total_cost": ...}, ...],
  "recommendation": {"ok": true, "process": "CNC", "unit_cost": 12.50, "reason": "...", "runner_up": "casting"},
  "report_text": "====\nFAB QUOTE REPORT\n..."
}
```

**Errors:** `{ok:false, reason}` — never raises.

---

## Processes evaluated

| Process | Key viability conditions |
|---------|--------------------------|
| CNC | Always viable; penalised for high complexity, many undercuts, high qty |
| casting | Blocked by min wall < 2.5 mm, no draft, precision tolerance |
| injection | Qty ≥ 1000 to amortise tooling; blocked by undercuts, no draft |
| sheet_metal | Favoured when `is_flat_blank: true`; blocked by non-flat 3D geometry |
| 3d_print | Always viable; penalised at qty > 500 or large volume |
| forging | Favoured by `requires_high_strength`, symmetry; blocked by undercuts, qty < 500 |

---

## Programmatic API

```python
from kerf_cad_core.quoting.fab_quote import (
    analyze_part, viable_processes, cost_per_process, recommend, quote_report
)

geo = {"bbox_x": 80, "bbox_y": 50, "bbox_z": 30, "volume_cm3": 40, "mass_kg": 0.3,
       "num_holes": 4, "tolerance_class": "fine"}
part   = analyze_part(geo)
procs  = viable_processes(part, quantity=500)
quotes = cost_per_process(part, procs, quantity=500)
rec    = recommend(quotes)
print(quote_report(part, quotes, rec))
```

---

## Usage examples

**Quick quote for a simple bracket:**

```
fab_quote
  geometry_summary: {bbox_x:100, bbox_y:60, bbox_z:20, volume_cm3:30, mass_kg:0.2,
                     num_holes:6, tolerance_class:"medium"}
  quantity: 50
→ {recommendation: {process:"CNC", unit_cost:8.30}, report_text:"..."}
```

**High-volume plastic housing:**

```
fab_quote
  geometry_summary: {bbox_x:120, bbox_y:80, bbox_z:40, volume_cm3:80, mass_kg:0.15,
                     draft_angle_deg:2.0, material_cost_per_kg:3.0}
  quantity: 10000
→ {recommendation: {process:"injection", unit_cost:0.45}, ...}
```

---

## Notes

- Cost estimates use conservative mid-market parametric rates (CNC $95/hr,
  injection $120/hr, forging press $150/hr, FDM $20/hr).
- Injection tooling default: $15,000 amortised over 100,000 shots.
- `tolerance_class: "precision"` restricts recommendation to CNC only.
- All costs are in the caller's currency (treated as opaque scalars).

---

## References

Kalpakjian, S., Schmid, S. — *Manufacturing Engineering and Technology*, 7th ed. Pearson, 2013 (process selection heuristics).
