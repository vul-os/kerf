# NURBS Surface Derivatives and Differential Geometry

> Compute arbitrary-order partial derivatives, fundamental forms, and differential geometry invariants on NURBS surfaces — for curvature-driven toolpaths, isogeometric analysis, and Class-A checks.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/geom/nurbs_derivative.py`
**Shipped**: Wave 8
**LLM tools**: `feature_nurbs_derivative_eval`

---

## What it is

Many CAE and CAM operations require derivatives of the surface geometry, not just point positions. Isogeometric analysis (IGA) evaluates stiffness matrices using the exact surface geometry. CNC toolpath generation needs the principal curvature directions to orient the cutter. Class-A surface checks compute the Gaussian and mean curvature map.

This module provides analytic derivatives of NURBS surfaces up to arbitrary order using the recursive B-spline derivative algorithm (Piegl & Tiller Algorithm A3.2). It also computes the first and second fundamental forms (E, F, G, L, M, N) and all standard differential geometry invariants: principal curvatures, shape operator, Gauss-Bonnet integrals, and geodesic curvature.

## How to use it

### From chat (natural language)

> "Compute the first and second fundamental forms of the hood surface at u=0.5, v=0.3"

The LLM calls `feature_nurbs_derivative_eval`.

### From Python

```python
from kerf_cad_core.geom.nurbs_derivative import (
    surface_derivatives, fundamental_forms,
)

# First and second partials (order 2)
d = surface_derivatives(surf, u=0.5, v=0.3, order=2)
# d[i][j] = ∂^(i+j)S / ∂u^i ∂v^j

# First fundamental form (metric tensor) and curvature tensor
forms = fundamental_forms(surf, u=0.5, v=0.3)
print(f"E={forms['E']:.4f}, F={forms['F']:.4f}, G={forms['G']:.4f}")
print(f"k1={forms['k1']:.4f}, k2={forms['k2']:.4f}")
print(f"H (mean)={forms['H']:.4f}, K (Gaussian)={forms['K']:.4f}")
```

### From an LLM tool spec

```json
{"tool": "feature_nurbs_derivative_eval", "surface_id": "hood",
 "u": 0.5, "v": 0.3, "order": 2}
```

## How it works

B-spline derivatives are computed by the Cox–de Boor recursion applied to the derivative knot vector: the k-th derivative of a B-spline of degree p is a B-spline of degree p-k with scaled difference control points. For rational NURBS, the quotient rule gives the Cartesian derivatives from the homogeneous ones (Algorithm A4.2 of Piegl & Tiller).

The fundamental forms use the computed first and second partials: E = S_u·S_u, F = S_u·S_v, G = S_v·S_v (first form); L = S_uu·n, M = S_uv·n, N = S_vv·n (second form, n = unit normal). Principal curvatures are the eigenvalues of the shape operator II·I⁻¹.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `surface_derivatives(surf, u, v, order)` | `np.ndarray[order+1, order+1, 3]` | All partials to given order |
| `surface_derivative_single(surf, u, v, du, dv)` | `np.ndarray[3]` | Single mixed partial ∂^(du+dv)S/∂u^du∂v^dv |
| `fundamental_forms(surf, u, v)` | `dict` | E,F,G,L,M,N,k1,k2,H,K,shape_operator |

## Example

```python
forms = fundamental_forms(surf, u=0.5, v=0.5)
print(f"Gaussian curvature K = {forms['K']:.6f}")
print(f"Mean curvature H = {forms['H']:.6f}")
print(f"Principal k1={forms['k1']:.4f}, k2={forms['k2']:.4f}")
```

## Honest caveats

Derivatives at knot boundaries may be discontinuous for low-continuity knot vectors (multiplicity = degree). Numerically, the quotient rule for rational surfaces can amplify floating-point errors when the weight function is near zero — always check that weights are positive. For surfaces with high-multiplicity internal knots, use `surface_derivative_single` at each span boundary separately.

## References

- Piegl & Tiller (1997). *The NURBS Book*, 2nd ed. Algorithms A3.2, A4.2.
- do Carmo (1976). *Differential Geometry of Curves and Surfaces*. §3.
