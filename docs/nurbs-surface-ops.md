# NURBS Surface Operations

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/geom/nurbs.py` · Shipped: Wave 6*

## Overview

Kerf's NURBS engine implements degree-arbitrary B-spline curves and tensor-product surfaces with full derivative evaluation, knot insertion, degree elevation, and degree reduction. The implementation follows the algorithms in Piegl & Tiller, "The NURBS Book" (2nd ed., 1997) and operates in pure Python + NumPy without requiring an OCC worker.

## When to use

- Evaluating points, tangents, or curvature on a NURBS curve or surface at a parametric location.
- Inserting knots to add control points without changing shape.
- Elevating or reducing degree to convert between formats.
- Fitting minimal control-point representations to sampled geometry.

## API

```python
from kerf_cad_core.geom.nurbs import (
    NurbsCurve, NurbsSurface,
    de_boor, curve_derivative,
    surface_evaluate, surface_derivatives, surface_normal,
    knot_insertion, degree_elevation, reduce_degree_curve,
    make_circle_nurbs, make_arc_nurbs, make_ellipse_nurbs,
)

# Evaluate a point on a NURBS curve
pt = de_boor(curve, u=0.5)

# First derivative
d1 = curve_derivative(curve, u=0.5, order=1)

# Surface point and normal at (u, v)
p   = surface_evaluate(surf, u=0.3, v=0.7)
n   = surface_normal(surf, u=0.3, v=0.7)

# Insert a knot twice
new_curve = knot_insertion(curve, u=0.4, num_insertions=2)
```

## LLM tools

`feature_nurbs_knot_insert`, `feature_nurbs_degree_elevate`, `feature_nurbs_fit`

## References

- Piegl & Tiller, *The NURBS Book*, 2nd ed. (1997), algorithms A2.1–A5.8.
- Boehm, "Inserting new knots into B-spline curves", *CAD* 12 (1980).

## Honest caveats

Rational (weighted) surfaces are supported for evaluation, but `reduce_degree_curve` uses the Bezier decompose-and-reduce approach which can accumulate tolerance error for high-degree surfaces (degree > 7). Degree reduction of surfaces is provided separately via `reduce_degree_surface` and may not converge to the requested tolerance on highly curved surfaces.
