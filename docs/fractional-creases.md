# Fractional Crease Weights in Subdivision

> Control edge sharpness continuously from fully smooth (0.0) to fully sharp (1.0) on a Catmull-Clark mesh — for product design edges that require neither a hard crease nor a full fillet.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/subd/fractional_crease.py`
**Shipped**: Wave 8
**LLM tools**: `feature_subd_crease_fractional`

---

## What it is

Standard Catmull-Clark subdivision gives smooth surfaces everywhere. To sharpen selected edges — think of the ridge on a car door, a filleted-but-defined product parting line, or a recessed panel edge — crease weights are assigned. A crease weight of 1.0 applies a hard-crease rule (the edge subdivides as if it were a boundary); a weight of 0.0 applies the smooth rule. Fractional weights (0 < w < 1) blend linearly between the two rules, producing a soft, controlled sharpness that is difficult to achieve with BRep fillets.

This module implements the DeRose et al. (1998) fractional crease scheme, extended to support per-vertex crease accumulation and the `evaluate_limit_with_creases` function for exact limit evaluation at creased vertices.

## How to use it

### From chat (natural language)

> "Set crease weight 0.6 on the shoulder edges of the handle cage and preview the limit surface"

The LLM calls `feature_subd_crease_fractional` with the edge IDs and weight.

### From Python

```python
from kerf_cad_core.subd.fractional_crease import (
    CreaseSubdMesh, CreaseEdge, subdivide_with_creases,
    evaluate_limit_with_creases,
)

mesh = CreaseSubdMesh(
    vertices=verts,
    faces=faces,
    crease_edges=[
        CreaseEdge(v0=0, v1=1, weight=0.8),
        CreaseEdge(v0=1, v1=2, weight=0.8),
    ],
)
refined = subdivide_with_creases(mesh, levels=3)
limit_pos = evaluate_limit_with_creases(refined, vertex_index=5)
print(f"Limit position at vertex 5: {limit_pos}")
```

### From an LLM tool spec

```json
{"tool": "feature_subd_crease_fractional", "edge_ids": [0,1,2], "weight": 0.8}
```

## How it works

For each subdivision level, edges with crease weight > 0 use a modified edge point rule that blends the sharp midpoint (average of endpoints) and the smooth edge point by the crease weight. Vertex points adjacent to crease edges use a crease vertex rule that treats the crease edges as semi-sharp boundaries. Each subdivision decrements the crease weight by 1 (integer part); weights below 1 are consumed in one subdivision step as a fractional blend.

Limit evaluation at creased vertices follows a modified Stam approach using the crease-modified subdivision matrix.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `subdivide_with_creases(mesh, levels)` | `CreaseSubdMesh` | Subdivide with crease weighting |
| `evaluate_limit_with_creases(mesh, vertex_index)` | `Vec3` | Exact limit position at vertex |

`CreaseEdge` fields: `v0`, `v1`, `weight` (float 0–∞; 1.0 = fully sharp, values > 1 survive multiple levels).

## Example

```python
mesh = CreaseSubdMesh(verts, faces,
    crease_edges=[CreaseEdge(0, 1, 2.5)])  # survives 2 full levels + 0.5 blend
refined = subdivide_with_creases(mesh, levels=3)
print(len(refined.vertices))
```

## Honest caveats

Crease weights above 1.0 survive multiple subdivision levels (a weight of 2.0 is fully sharp for 2 levels, then smooth). Weight values above 3 are effectively permanent creases for typical mesh densities. Fractional crease weighting changes the limit surface compared to the standard Catmull-Clark formula; `evaluate_limit_with_creases` gives the exact modified limit, not the standard Stam formula.

## References

- DeRose, Kass & Truong (1998). "Subdivision surfaces in character animation." *SIGGRAPH* 1998.
- Hoppe, DeRose, Duchamp, Halstead, Jin, McDonald, Schweitzer & Stuetzle (1994). "Piecewise smooth surface reconstruction." *SIGGRAPH* 1994.
