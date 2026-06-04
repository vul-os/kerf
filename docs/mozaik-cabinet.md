# Cabinet Cut-List Generator (Mozaik-style)

> Turn a cabinet placement list into an optimised sheet cut-list with yield and waste report.

**Module**: `packages/kerf-woodworking/src/kerf_woodworking/cabinet_cut_list.py`
**Shipped**: Wave 10
**LLM tools**: `woodworking_cut_list`

---

## What it is

The cabinet cut-list generator decomposes one or more cabinet placements (box dimensions, door count, drawer count, material) into individual panel pieces, then packs them onto standard sheet sizes (2440 × 1220 mm, 3050 × 1220 mm, or custom) using a First-Fit Decreasing strip-packing heuristic. The output is a per-sheet cutting layout, total yield, and a waste percentage report in the style of Mozaik Cabinet Software.

## How to use it

### From chat

> "Generate the cut list for a 900 mm base cabinet in 18 mm white melamine, two doors, one drawer."

### From Python

```python
from kerf_woodworking.cabinet_cut_list import CabinetPlacement, generate_cut_list

cab = CabinetPlacement(
    name="base_900",
    width_mm=900, height_mm=720, depth_mm=560,
    material="18mm_melamine_white",
    doors=2, drawers=1,
    sheet_width_mm=2440, sheet_height_mm=1220,
)
report = generate_cut_list([cab])
print(report.total_sheets, report.yield_pct)
for sheet in report.sheets:
    print(sheet.placements)
```

### From an LLM tool spec

```json
{"tool": "woodworking_cut_list", "input": {"pieces": [{"label": "side", "length_mm": 720, "width_mm": 560, "qty": 2}], "board_length_mm": 2440, "board_width_mm": 1220, "kerf_mm": 3}}
```

## How it works

`_decompose_cabinet` expands a cabinet spec into named `CutListItem` records (two sides, top, bottom, back, doors, drawer fronts, drawer boxes). Items are sorted by area (largest first). `_pack_panels_onto_sheets` uses a strip-packing algorithm: each strip is the height of the tallest remaining piece; pieces fill the strip left-to-right with a kerf gap (3 mm default).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `generate_cut_list(cabinets, kerf_mm)` | `CutListReport` | Packed sheets and yield stats |
| `CabinetPlacement(...)` | instance | Cabinet dimension and material spec |
| `CutListItem(...)` | instance | Single panel record |

## Example

```python
report = generate_cut_list([cab])
# CutListReport(total_sheets=2, yield_pct=78.4,
#               waste_pct=21.6, pieces=14)
```

## Honest caveats

The strip-packing heuristic is fast but not optimal; a branch-and-bound or guillotine-cut solver would improve yield by 3–8% on typical cabinet jobs. Material grain direction is not enforced in this module — use `mozaik-grain` to validate grain constraints after layout. Edge-banding strips are not included in the cut list.

## References

- Wäscher et al., "An improved typology of cutting and packing problems," *EJOR* 183(3), 2007.
- Mozaik Cabinet Software cut-list format (2023).
