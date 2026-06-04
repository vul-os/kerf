# Seam Allowance

> Add or remove a constant seam allowance offset around any pattern piece boundary.

**Module**: `packages/kerf-apparel/src/kerf_apparel/seam_allowance.py`
**Shipped**: Wave 10
**LLM tools**: `apparel_add_seam`

---

## What it is

Seam allowance tools inset or outset a 2-D pattern piece boundary by a specified amount (typically 1 cm for standard seams, 1.5 cm for AAMA) using a miter-join polygon offset. The offset correctly handles concave corners (notches, dart legs) and convex corners (collar points) by clamping the mitre limit to avoid spikes.

## How to use it

### From chat

> "Add a 1.5 cm seam allowance to the front bodice pattern piece."

### From Python

```python
from kerf_apparel.seam_allowance import add_seam_allowance, remove_seam_allowance
from kerf_apparel.blocks import PatternPiece

piece = PatternPiece(name="front_bodice", boundary=pts)
with_seam = add_seam_allowance(piece, offset_cm=1.5)
net_piece  = remove_seam_allowance(with_seam, offset_cm=1.5)
```

### From an LLM tool spec

```json
{"tool": "apparel_add_seam", "input": {"piece_name": "front_bodice", "boundary": [[...]], "offset_cm": 1.5}}
```

## How it works

`offset_polyline` computes the inward/outward normal at each vertex as the angle bisector between adjacent edge normals. The offset distance is projected along this bisector. At sharp convex corners the bisector direction can diverge; a miter limit of 4× the offset distance clips extreme excursions and replaces them with a bevel. Concave corners (negative signed area sector) are handled by clipping the offset boundary against itself.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `add_seam_allowance(piece, offset_cm)` | `PatternPiece` | Outset pattern boundary |
| `remove_seam_allowance(piece, offset_cm)` | `PatternPiece` | Inset pattern boundary |
| `offset_polyline(pts, offset)` | `list[Point]` | Raw polyline offset utility |

## Example

```python
seam_piece = add_seam_allowance(piece, offset_cm=1.0)
# PatternPiece(name='front_bodice', n_boundary_pts=124)
# area increases by approximately perimeter × offset
```

## Honest caveats

The miter-join offset is accurate for straight and gently curved edges. Very tight curves (radius < 2× offset) may produce self-intersecting results; check `result.is_valid` before use. The same offset is applied to all edges; in practice, some edges (neckline, hem) may require a different allowance — apply per-edge using separate calls or manual editing. Notches and drill holes are not propagated by the offset.

## References

- AAMA/ASTM Standard Seam Allowances, Technical Bulletin TB-1 (2017).
- Shamos, *Computational Geometry: An Introduction*, Springer (1985), Ch. 3.
