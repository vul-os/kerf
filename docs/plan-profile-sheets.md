# Plan-and-Profile Sheets

> Auto-compose civil plan-and-profile drawing sheets from horizontal alignment, vertical profile, and corridor cross-section data.

**Module**: `packages/kerf-civil/src/kerf_civil/dxf_export.py`, `corridor.py`
**Shipped**: Wave 11
**LLM tools**: `civil_plan_profile_sheet`, `civil_dxf_export`

---

## What it is

Plan-and-profile sheets are the deliverable for road, pipeline, and utility corridor projects: the top half shows the plan view (alignment on a map), and the bottom half shows the elevation profile with existing and design grade lines plotted against chainage. These sheets are required for contractor tendering, regulatory approval, and construction. This module generates them as DXF R12 or as annotated SVG, sourcing geometry from `HorizontalAlignment`, `VerticalAlignment`, and TIN surface data.

## How to use it

### From chat

> "Generate plan-and-profile sheets at 1:1000 plan scale and 1:100 vertical scale for my road alignment, chainage 0–800 m, on A1 sheets."

### From Python

```python
from kerf_civil.dxf_export import export_corridor_dxf
from kerf_civil.corridor import build_corridor

corridor = build_corridor(
    horizontal=alignment,
    vertical=vert_alignment,
    typical_section=cross_section,
    stations=[0, 20, 40, 60, 80, 100]
)
dxf_str = export_corridor_dxf(corridor)
with open("corridor.dxf", "w") as f:
    f.write(dxf_str)
```

### From an LLM tool spec

```json
{"alignment_id": "<uuid>", "vertical_id": "<uuid>",
 "sheet_size": "A1", "plan_scale": 1000, "profile_scale_v": 100,
 "start_chainage": 0, "end_chainage": 800}
```

## How it works

The DXF exporter traces the horizontal alignment polyline at 5 m intervals to produce the plan-view centreline. Superelevated cross-sections are swept perpendicularly at each station to produce edge-of-road and batter lines. The profile view plots the existing ground (from TIN interpolation at each station) and the design profile (from vertical alignment evaluation) as two parallel polylines in a separate viewport at the bottom of the sheet. Stationing tick marks, annotation text (chainage, elevation, grade breaks), and north arrow are added as TEXT and LINE entities in standard civil drafting layers.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `build_corridor(horizontal, vertical, typical_section, stations)` | `Corridor` | 3D corridor data model |
| `export_corridor_dxf(corridor)` | `str` | DXF R12 plan+profile sheet |
| `Corridor.section_at(chainage)` | `dict` | Cross-section at a given station |

## Example

```python
from kerf_civil.corridor import build_corridor, Corridor
corr = build_corridor(alignment, vert, section, list(range(0, 500, 20)))
s = corr.section_at(200)
print("Cut depth at 200 m:", s["cut_depth_m"])
```

## Honest caveats

The DXF output uses a flat R12 format — no viewports in the traditional AutoCAD sense. Users should import into Civil 3D or QGIS to assign paper-space viewports. Plan and profile are in the same model-space DXF file separated by a Y offset equal to the plan height; manual viewport setup is needed in most CAD software. Sheet border and title block templates are not included.

## References

- AASHTO (2018). *Guide for Development of Bicycle Facilities*, Appendix B (plan sheet examples).
- Autodesk (2020). *Civil 3D Plan Production Objects* documentation.
