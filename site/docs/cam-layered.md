# Layered CAM (HSM Pocket / Slot / Rest)

> High-speed machining strategies — constant engagement, trochoidal, and rest passes — with no external CAM library required.

**Module**: `packages/kerf-cam/src/kerf_cam/adaptive.py`
**Shipped**: Wave 7
**LLM tools**: `hsm_adaptive_pocket`, `hsm_trochoidal_slot`, `hsm_rest_machining`

---

## What it is

Layered CAM covers the three most common 2.5D HSM strategies for milling flat pockets and slots in soft-to-hard metals. Traditional raster clearing forces the tool through abrupt direction reversals that spike radial chip load; HSM keeps engagement bounded throughout, enabling high feedrates and long tool life.

Use this when you need: (1) adaptive pocket clearing where the boundary is a closed polygon, (2) trochoidal slot milling where a slot is narrower than ~2× tool diameter, or (3) a clean-up pass after a large tool leaves material in corners.

## How to use it

### From chat

> "Generate an adaptive clearing toolpath for a 100 mm × 80 mm rectangular pocket using a 10 mm end-mill, 30% engagement, 2 mm depth, 2000 mm/min feed."

### From Python

```python
from kerf_cam.adaptive import adaptive_pocket, trochoidal_slot, rest_machining

boundary = [(0,0),(100,0),(100,80),(0,80)]
result = adaptive_pocket(boundary, tool_diameter=10.0,
                         engagement_fraction=0.30, depth=2.0, feed=2000.0)
print(result["metadata"])  # rings, actual_max_engagement_mm
```

### From an LLM tool spec

```json
{"boundary": [[0,0],[100,0],[100,80],[0,80]],
 "tool_diameter": 10.0, "engagement_fraction": 0.30,
 "depth": 2.0, "feed": 2000.0}
```

## How it works

`adaptive_pocket` iteratively offsets the pocket boundary inward by `step_over = engagement_fraction × D` using vertex-normal bisector averaging. Self-intersecting rings are screened by a raster point-in-polygon filter. Consecutive rings connect via short chord transitions to avoid retract overhead; corner transitions run at 60% nominal feed.

`trochoidal_slot` walks the slot centreline in increments of `trochoid_radius` and emits one full circle per step. Successive circles overlap by 50%, guaranteeing full slot width coverage while peak radial engagement equals `trochoid_radius`.

`rest_machining` builds a pixel grid at 0.5 mm resolution, marks every cell inside the boundary not swept by the prior large-tool path, and generates a zigzag small-tool clearing pass over those regions.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `adaptive_pocket(boundary, tool_diameter, engagement_fraction, depth, feed)` | `dict` | Inward-spiral adaptive clearing |
| `trochoidal_slot(slot_polyline, tool_diameter, trochoid_radius, feed)` | `dict` | Loop-based slot milling |
| `rest_machining(prior_toolpaths, boundary, large_tool_diameter, small_tool_diameter, feed)` | `dict` | Corner/remnant clearing |

All return `{polylines, feeds, total_length, metadata}`.

## Example

```python
slot = [(0, 0), (150, 0)]
r = trochoidal_slot(slot, tool_diameter=6.0, trochoid_radius=2.5, feed=1800.0)
print(f"{r['metadata']['circles']} circles, {r['total_length']:.1f} mm path")
```

## Honest caveats

The polygon-offset method uses first-order vertex-normal averaging; very tight concave corners (< 8.6°) are clamped. No 3D gouge check — verify the toolpath in a simulator before cutting. The grid resolution for rest machining defaults to 0.5 mm; for large parts reduce it or the grid becomes slow. G-code emission requires kerf-cam posts.

## References

- Ibaraki, S. et al. (2010). Cutting performance of a new adaptive control system for milling. *Int. J. Mach. Tools Manuf.* 50(7), 649–656.
- Yao, Z. et al. (2018). Trochoidal milling review. *Int. J. Adv. Manuf. Technol.* 98, 2767–2786.
