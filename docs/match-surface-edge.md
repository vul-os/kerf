# Match Surface Edge (G0/G1/G2/G3)

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/geom/match_srf.py` · Shipped: Wave 8 (NURBS Phase 4 Cap. 3)*

## Overview

Adjusts the control-point rows adjacent to a NURBS surface boundary so the seam satisfies G0 (positional), G1 (tangent), G2 (curvature), or G3 (curvature-rate) continuity with a target surface. This is Rhino's `MatchSrf` operation implemented entirely in NumPy, using the Boehm analytic boundary-condition approach. The operation modifies the source surface in-place (via a copy) without rebuilding topology.

## When to use

- Closing tangent or curvature gaps between adjacent NURBS patches after surfacing.
- Preparing lofted or swept surfaces for G2-continuous fairing.
- Automotive Class-A surface work requiring curvature-continuous panel joins.
- Verifying seam quality with deviation diagnostics.

## API

```python
from kerf_cad_core.geom.match_srf import match_surface_edge, MatchResult

result: MatchResult = match_surface_edge(
    target_surface=tgt_surf,   # NurbsSurface
    target_edge="v1",          # 'u0', 'u1', 'v0', 'v1'
    source_surface=src_surf,   # NurbsSurface (modified copy returned)
    source_edge="v0",
    continuity="G2",           # 'G0', 'G1', 'G2', or 'G3'
    samples=32,
    tolerance=1e-6,
)

print(result.max_g0_deviation)   # positional gap
print(result.max_g1_deviation)   # tangent angle gap (radians)
print(result.max_g2_deviation)   # curvature deviation
modified_surf = result.surface
```

## LLM tools

`feature_match_surface_edge`

## References

- Pottmann & Leopoldseder, "A concept for parametric surface fitting which avoids the parametrization problem", *CAGD* 20 (2003).
- Piegl & Tiller, *The NURBS Book*, §10.3.

## Honest caveats

G3 continuity adjustment requires degree >= 4 in the matching direction; on degree-3 surfaces the G3 gate leaves the fourth CP row unchanged. The OCC `GeomFill_NSections` binding (transition strip) is a separate WASM-blocked path; `match_surface_edge` only modifies the source surface, not builds a filler strip. High curvature mismatches can require several passes.
