# Surface Analysis (Curvature, Zebra, Draft)

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/geom/surface_analysis.py` · Shipped: Wave 7*

## Overview

Computes diagnostic curvature and aesthetic quality measures on NURBS surfaces: Gaussian curvature, mean curvature, principal curvatures, zebra-stripe continuity analysis, draft-angle analysis, and deviation maps. These are the standard Class-A surfacing quality checks.

## When to use

- Verifying continuity (G0/G1/G2) across adjacent surface patches visually.
- Checking minimum draft angle before injection-moulding tooling.
- Generating a curvature comb or false-colour curvature map.
- Measuring deviation between a design surface and a target scan.

## API

```python
from kerf_cad_core.geom.surface_analysis import (
    mean_curvature, gaussian_curvature, principal_curvatures,
    draft_angle, deviation,
    zebra_stripe, zebra_stripe_continuity_analyser,
    draft_angle_analysis,
)

kH = mean_curvature(surf, u=0.5, v=0.5)
kG = gaussian_curvature(surf, u=0.5, v=0.5)
k1, k2 = principal_curvatures(surf, u=0.5, v=0.5)

# Check minimum draft for a given pull direction
draft = draft_angle(surf, pull_direction=[0, 0, 1],
                    nu=40, nv=40)

# Zebra-stripe continuity map across a seam
report = zebra_stripe_continuity_analyser(surf_a, surf_b,
                                           shared_edge="v1",
                                           n_stripes=8)
```

## LLM tools

`feature_surface_curvature_combs`, `feature_draft_angle_analysis`, `feature_zebra_stripe`

## References

- do Carmo, *Differential Geometry of Curves and Surfaces* (1976).
- Beier & Chen, "Highlight-line algorithm for realtime surface-quality assessment", *CAD* 26(4), 1994.

## Honest caveats

All curvature computations use the Weingarten equations evaluated at sampled UV grid points. Results are analytical (no finite differences) but depend on the accuracy of the control-point layout — poorly conditioned surfaces with near-zero Jacobian will produce NaN curvatures at those points. Draft angle analysis reports per-triangle approximations when called on a tessellated mesh.
