# NURBS Surface Operations

> Degree-arbitrary B-spline curves and tensor-product surfaces with full evaluation, knot manipulation, and fitting — for engineers who need exact geometry, not triangles.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/nurbs.py`
**Shipped**: Wave 6
**LLM tools**: `feature_nurbs_knot_insert`, `feature_nurbs_degree_elevate`, `feature_nurbs_fit`

---

## What it is

NURBS (Non-Uniform Rational B-Splines) are the industry standard for representing free-form curves and surfaces in CAD. Unlike meshes, a NURBS surface has a compact analytic representation — a grid of weighted control points, a degree, and a knot vector — that can be evaluated exactly at any parameter value.

Kerf's NURBS engine implements the core algorithms from Piegl & Tiller (1997) in pure Python + NumPy, covering degree-arbitrary curves and tensor-product surfaces. It supports derivative evaluation up to arbitrary order, knot insertion (Boehm's algorithm), degree elevation, and approximate degree reduction. No OpenCASCADE worker is required for these operations.

Engineers reach for this module when they need to interrogate or reshape exact surface geometry: extracting normals and curvature for toolpath generation, inserting knots before a boolean, or fitting a cloud of measured points to a minimal B-spline representation.

## How to use it

### From chat (natural language)

> "Evaluate the surface normal at u=0.3, v=0.7 on the hood panel"

The LLM calls `feature_nurbs_fit` or evaluates via the internal surface engine and returns a normal vector.

### From Python

```python
from kerf_cad_core.geom.nurbs import (
    NurbsSurface, surface_evaluate, surface_normal,
    surface_derivatives, knot_insertion, degree_elevation,
)

# Surface point and normal
pt = surface_evaluate(surf, u=0.3, v=0.7)
n  = surface_normal(surf, u=0.3, v=0.7)

# First partials
d = surface_derivatives(surf, u=0.3, v=0.7, order=1)
# d[1][0] = dS/du,  d[0][1] = dS/dv

# Add a knot without changing shape
refined = knot_insertion(curve, u=0.4, num_insertions=2)

# Raise degree from 3 → 4
elevated = degree_elevation(curve, times=1)
```

### From an LLM tool spec

```json
{"tool": "feature_nurbs_knot_insert", "curve_id": "c1", "u": 0.4, "count": 2}
```

## How it works

B-spline basis functions `N_{i,p}(u)` are evaluated with the Cox–de Boor recursion. Points on a rational (NURBS) surface are computed as the projective average of the 4-component homogeneous control points — a standard rational extension of the de Boor algorithm.

Knot insertion uses Boehm's algorithm (1980): it solves for a new, extended control-point set that keeps the curve or surface geometrically identical. Degree elevation follows the Prautzsch–Piper procedure — each Bezier segment is elevated then the segments are recombined. Degree reduction is the approximate Bezier decompose-and-reduce method, which minimises the L² deviation from the original.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `surface_evaluate(surf, u, v)` | `np.ndarray[3]` | Point on surface |
| `surface_normal(surf, u, v)` | `np.ndarray[3]` | Unit normal |
| `surface_derivatives(surf, u, v, order)` | `np.ndarray[order+1, order+1, 3]` | Partial derivatives |
| `knot_insertion(curve, u, num_insertions)` | `NurbsCurve` | Refine without shape change |
| `degree_elevation(curve, times)` | `NurbsCurve` | Raise polynomial degree |
| `reduce_degree_curve(curve, tol)` | `NurbsCurve` | Approximate degree reduction |

## Example

```python
from kerf_cad_core.geom.nurbs import make_circle_nurbs, surface_evaluate

circle = make_circle_nurbs(radius=5.0)
pt = surface_evaluate(circle, u=0.25, v=0.0)
print(pt)  # approx [0.0, 5.0, 0.0]
```

## Honest caveats

Rational (weighted) surfaces are fully supported for evaluation, but `reduce_degree_curve` uses Bezier decompose-and-reduce, which can accumulate tolerance error at high degrees (> 7). Degree reduction of surfaces is handled by the separate `reduce_degree_surface` function and may not converge to the requested tolerance on highly curved patches. For production CAD workflows requiring exact IGES/STEP round-trip, prefer the OCCT-backed path.

## References

- Piegl & Tiller (1997). *The NURBS Book*, 2nd ed. Algorithms A2.1–A5.8.
- Boehm (1980). "Inserting new knots into B-spline curves." *CAD* 12.
- Prautzsch, Boehm & Paluszny (2002). *Bézier and B-Spline Techniques*. Springer.
