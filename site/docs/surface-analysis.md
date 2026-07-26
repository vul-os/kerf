# Surface Analysis (Curvature, Zebra, Draft, Hausdorff)

> Diagnostic quality checks for NURBS surfaces: Gaussian/mean curvature, zebra-stripe continuity, draft-angle maps, and Hausdorff deviation — the Class-A surfacing quality toolkit.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/surface_analysis.py`
**Shipped**: Wave 7
**LLM tools**: `feature_surface_curvature_combs`, `feature_draft_angle_analysis`, `feature_zebra_stripe`

---

## What it is

After a NURBS surface is built or imported, engineers need to verify its quality before committing to downstream operations. This module provides the standard Class-A surfacing checks: Gaussian and mean curvature (analytically computed from the Weingarten equations), principal curvature maps, zebra-stripe reflection continuity analysis, draft-angle analysis for mouldability, Hausdorff deviation between two surfaces, and naked-edge detection.

These checks are run automatically by the `class_a_acceptance_harness` function, which returns a single pass/fail report with quantified residuals.

## How to use it

### From chat (natural language)

> "Check the curvature continuity across the hood seam and flag any G1 breaks"

The LLM calls `feature_zebra_stripe` on the two adjacent patches.

### From Python

```python
from kerf_cad_core.geom.surface_analysis import (
    mean_curvature, gaussian_curvature, principal_curvatures,
    draft_angle, zebra_stripe_continuity_analyser,
    hausdorff_deviation, class_a_acceptance_harness,
)

kH = mean_curvature(surf, u=0.5, v=0.5)
kG = gaussian_curvature(surf, u=0.5, v=0.5)
k1, k2 = principal_curvatures(surf, u=0.5, v=0.5)

# Draft angle map (degrees) for injection mould pull in +Z
draft_map = draft_angle(surf, pull_direction=[0,0,1], nu=40, nv=40)
min_draft = draft_map["min_deg"]

# Zebra stripes across a seam
report = zebra_stripe_continuity_analyser(
    surf_a, surf_b, shared_edge="v1", n_stripes=8)
print(report["continuity"])  # "G0", "G1", or "G2"
```

### From an LLM tool spec

```json
{"tool": "feature_zebra_stripe", "surface_ids": ["hood_A", "hood_B"],
 "shared_edge": "v1", "n_stripes": 12}
```

## How it works

Curvature is computed analytically from the first and second fundamental forms evaluated at (u, v). The Weingarten equations give the shape operator, whose eigenvalues are the principal curvatures k₁, k₂. Mean curvature H = (k₁+k₂)/2; Gaussian curvature K = k₁k₂. Zebra stripes simulate reflected parallel light bands: stripe visibility is determined by the angle between the surface normal and the light direction, sampled across a UV grid.

Hausdorff deviation uses a two-pass refined Newton algorithm: it first estimates the directed Hausdorff distance by sampling, then refines each maximum-distance point by Newton iteration to the nearest point on the second surface.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `mean_curvature(surf, u, v)` | `float` | Mean curvature H at (u,v) |
| `gaussian_curvature(surf, u, v)` | `float` | Gaussian curvature K at (u,v) |
| `principal_curvatures(surf, u, v)` | `(float, float)` | k₁, k₂ |
| `draft_angle(surf, pull_direction, nu, nv)` | `dict` | Draft map and min draft angle |
| `zebra_stripe_continuity_analyser(a, b, ...)` | `dict` | Seam continuity classification |
| `hausdorff_deviation(surf_a, surf_b, n)` | `dict` | Bidirectional Hausdorff distance |
| `class_a_acceptance_harness(surfaces, ...)` | `dict` | Full quality report |

## Example

```python
from kerf_cad_core.geom.surface_analysis import hausdorff_deviation

result = hausdorff_deviation(reference_surf, scanned_surf, n=50)
print(f"Max deviation: {result['hausdorff_m']*1000:.3f} mm")
print(f"RMS deviation: {result['rms_m']*1000:.3f} mm")
```

## Honest caveats

Curvature computations are analytical but depend on control-point accuracy; poorly conditioned surfaces with near-zero Jacobians produce NaN at those parameters. Draft analysis reports per-triangle approximations on tessellated bodies. Hausdorff computation at n=50 samples is fast but may miss narrow high-deviation spikes; use n=100+ for final acceptance.

## References

- do Carmo (1976). *Differential Geometry of Curves and Surfaces*. Prentice Hall.
- Beier & Chen (1994). "Highlight-line algorithm for realtime surface-quality assessment." *CAD* 26(4).
