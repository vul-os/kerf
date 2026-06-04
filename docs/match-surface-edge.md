# Match Surface Edge (G0 – G3 Continuity)

> Adjust a NURBS patch boundary to meet an adjacent surface at positional, tangent, curvature, or curvature-rate continuity — Rhino's MatchSrf, in pure Python.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/match_srf_g3.py`
**Shipped**: Wave 8 (NURBS Phase 4, Cap. 3)
**LLM tools**: `feature_match_surface_edge`

---

## What it is

In multi-patch NURBS surfacing, adjacent panels must share not just position (G0) but also tangent direction (G1) and often curvature (G2) to appear smooth in reflections. Automotive Class-A requires G2 or G3. This module solves for the boundary control-point rows of a target surface so that its cross-boundary derivatives up to order 3 match a reference surface at every sample point along the seam.

The implementation extends the classic Boehm boundary-condition technique to G3 by solving a sparse linear least-squares system over the unknown control-point rows (up to four rows for G3). Results include residuals at each order so engineers can immediately quantify seam quality.

## How to use it

### From chat (natural language)

> "Match edge_3 of patch_A to edge_1 of patch_B with G2 continuity"

The LLM calls `feature_match_surface_edge` with `{target: 'patch_A', target_side: 'u1', reference: 'patch_B', reference_side: 'u0', order: 2}` and returns a `MatchSrfG3Report`.

### From Python

```python
from kerf_cad_core.geom.match_srf_g3 import (
    match_srf_g3, MatchSrfG3Spec, ContinuityOrder, estimate_continuity,
)

spec = MatchSrfG3Spec(
    target=patch_a,
    reference=patch_b,
    target_side='u1',
    reference_side='u0',
    order=ContinuityOrder.G2,
    tol=1e-6,
)
report = match_srf_g3(spec)
print(f"G0 gap: {report.g0_residual:.2e} m")
print(f"G1 gap: {report.g1_residual:.2e} rad")
print(f"G2 gap: {report.g2_residual:.2e} 1/m")
matched_surface = report.matched_surface
```

### From an LLM tool spec

```json
{"tool": "feature_match_surface_edge", "target_id": "patch_A", "target_side": "u1",
 "reference_id": "patch_B", "reference_side": "u0", "order": 2}
```

## How it works

For each continuity order k (0–3), the constraint requires that the k-th cross-boundary derivative of the target surface equals that of the reference at every sample point along the shared edge. The k=0 constraint fixes the boundary row directly; k=1 and above constrain the next inner rows via a sparse linear system. The algorithm samples the seam at `n_samples` Greville abscissae and builds a per-row least-squares problem, solved with `numpy.linalg.lstsq`. G3 requires surface degree ≥ 4 in the matching direction.

Residuals `g0_residual`, `g1_residual`, … are the RMS errors across all sample points after fitting.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `match_srf_g3(spec)` | `MatchSrfG3Report` | Main solver |
| `match_srf_g3_functional(target, reference, ...)` | `MatchSrfG3Report` | Keyword-arg convenience form |
| `estimate_continuity(surf_a, side_a, surf_b, side_b)` | `dict` | Measure existing seam quality |

`MatchSrfG3Report` fields: `matched_surface`, `g0_residual`, `g1_residual`, `g2_residual`, `g3_residual`, `iterations`, `converged`, `n_cps_modified`.

## Example

```python
spec = MatchSrfG3Spec(target=patch_a, reference=patch_b,
                       target_side='u1', reference_side='u0',
                       order=ContinuityOrder.G1, tol=1e-7)
rpt = match_srf_g3(spec)
assert rpt.converged
print(f"G1 residual: {rpt.g1_residual:.2e}")  # e.g. 3.1e-09 rad
```

## Honest caveats

G3 matching requires degree ≥ 4 surfaces; on degree-3 patches, the fourth-row constraint is silently dropped and the result is capped at G2. Large curvature mismatches may require multiple passes or manual CP editing. This operation only modifies the target surface — it does not build a blend or filler strip between the two patches (for that, use a loft or sweep).

## References

- Piegl & Tiller (1997). *The NURBS Book*, 2nd ed. §10.3.
- Farin (2002). *Curves and Surfaces for CAGD*. §10.
- Pottmann & Leopoldseder (2003). "A concept for parametric surface fitting which avoids the parametrization problem." *CAGD* 20.
