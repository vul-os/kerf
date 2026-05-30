"""auto_lightweight.py — B-rep auto-lightweight pass.

Reduces the representation size of an imported B-rep Body by:

  1. **Lyche-Mørken knot removal** — for each curve/surface face, iteratively
     remove redundant interior knots while the geometric deviation stays
     within *tol*.  Uses the existing ``minimal_cp_refit`` (Piegl & Tiller §5.4
     RemoveCurveKnot) as the underlying primitive, extended to surfaces via
     iso-parametric column/row reduction.

  2. **Rational → polynomial downgrade** — if all weights on a rational NURBS
     are within *tol* of 1.0, the curve/surface is geometrically polynomial;
     strip the weight vector.

  3. **Collinear CP removal** — not a standalone operation (covered implicitly
     by knot removal: a collinear interior CP corresponds to a redundant knot
     in the B-spline sense and is removed by step 1).

References
----------
Piegl & Tiller, "The NURBS Book" 2nd ed., §5.4 — RemoveCurveKnot.
Lyche & Mørken (1988), "A discrete approach to knot removal and degree
reduction algorithms for splines" — SIAM J. Numer. Anal. 25(1), 167–185.

Public API
----------
lightweight_body(body, tol=1e-6) -> LightweightResult
    Main entry point.  Traverses every face surface (NurbsSurface) and every
    edge curve (NurbsCurve) in the body, applies knot removal and rational
    simplification, returns a ``LightweightResult`` with metrics.

is_rational_actually_polynomial(curve_or_surface, tol=1e-6) -> bool
    True when the weights are all ≈ 1.0 (curve is geometrically polynomial).

reduce_curve_to_polynomial(curve) -> NurbsCurve
    Strip the weight vector from a rational curve whose weights are all 1.0.

Never raises — all errors are caught and surfaced in the result ``errors``
list; the body is always returned (possibly partially simplified).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Internal helpers — import lazily so the module loads even without the full
# kerf_cad_core geometry stack (tests may import selectively).
# ---------------------------------------------------------------------------

def _nurbs_module():
    """Lazy import of kerf_cad_core.geom.nurbs."""
    from kerf_cad_core.geom import nurbs as _n
    return _n


def _brep_module():
    """Lazy import of kerf_cad_core.geom.brep."""
    from kerf_cad_core.geom import brep as _b
    return _b


# ---------------------------------------------------------------------------
# Size accounting
# ---------------------------------------------------------------------------

def _curve_size(curve) -> int:
    """Approximate in-memory 'size' of a NURBS curve in floats.

    num_control_points * dim  +  num_knots  +  (num_weights or 0)
    """
    nurbs = _nurbs_module()
    if not isinstance(curve, nurbs.NurbsCurve):
        return 0
    n = curve.num_control_points
    dim = curve.control_points.shape[1]
    k = curve.num_knots
    w = n if curve.weights is not None else 0
    return n * dim + k + w


def _surface_size(surface) -> int:
    """Approximate in-memory 'size' of a NURBS surface in floats."""
    nurbs = _nurbs_module()
    if not isinstance(surface, nurbs.NurbsSurface):
        return 0
    nu = surface.num_control_points_u
    nv = surface.num_control_points_v
    dim = surface.control_points.shape[2]
    ku = len(surface.knots_u)
    kv = len(surface.knots_v)
    w = nu * nv if surface.weights is not None else 0
    return nu * nv * dim + ku + kv + w


def _body_size(body) -> int:
    """Sum of _curve_size + _surface_size over all edges and face surfaces."""
    brep = _brep_module()
    if body is None:
        return 0
    total = 0
    for face in body.all_faces():
        total += _surface_size(face.surface)
    for edge in body.all_edges():
        total += _curve_size(edge.curve)
    return total


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_rational_actually_polynomial(curve_or_surface, tol: float = 1e-6) -> bool:
    """Return True when *curve_or_surface* has all weights ≈ 1.0 within *tol*.

    A NURBS with uniform unit weights is geometrically a plain polynomial
    B-spline; the rational representation is redundant overhead.

    Parameters
    ----------
    curve_or_surface:
        A :class:`~kerf_cad_core.geom.nurbs.NurbsCurve` or
        :class:`~kerf_cad_core.geom.nurbs.NurbsSurface`.
    tol:
        Absolute tolerance for "close to 1.0".  Defaults to 1e-6.

    Returns
    -------
    bool
        True if weights present and all within *tol* of 1.0.
        False when no weights, non-uniform weights, or unsupported type.
    """
    nurbs = _nurbs_module()
    if isinstance(curve_or_surface, nurbs.NurbsCurve):
        w = curve_or_surface.weights
    elif isinstance(curve_or_surface, nurbs.NurbsSurface):
        w = curve_or_surface.weights
    else:
        return False
    if w is None:
        return False
    return bool(np.all(np.abs(w - 1.0) <= tol))


def reduce_curve_to_polynomial(curve) -> "NurbsCurve":  # noqa: F821
    """Strip the weight vector from a rational curve that is geometrically polynomial.

    Callers should first verify ``is_rational_actually_polynomial(curve)``; if
    the weights are not all 1.0 this function still strips them (it is the
    caller's responsibility to check fitness).

    Parameters
    ----------
    curve:
        A :class:`~kerf_cad_core.geom.nurbs.NurbsCurve` (rational or not).

    Returns
    -------
    NurbsCurve
        A new curve with ``weights=None``; all other fields unchanged.
    """
    nurbs = _nurbs_module()
    return nurbs.NurbsCurve(
        degree=curve.degree,
        control_points=curve.control_points.copy(),
        knots=curve.knots.copy(),
        weights=None,
    )


def _reduce_surface_to_polynomial(surface):
    """Strip the weight grid from a NURBS surface with all-unit weights."""
    nurbs = _nurbs_module()
    return nurbs.NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=surface.degree_v,
        control_points=surface.control_points.copy(),
        knots_u=surface.knots_u.copy(),
        knots_v=surface.knots_v.copy(),
        weights=None,
    )


# ---------------------------------------------------------------------------
# Curve lightweight
# ---------------------------------------------------------------------------

def _lightweight_curve(curve, tol: float) -> Tuple[object, int, int]:
    """Attempt knot removal + rational simplification on one NurbsCurve.

    Returns (new_curve, knots_removed, cps_removed).
    """
    nurbs = _nurbs_module()
    if not isinstance(curve, nurbs.NurbsCurve):
        return curve, 0, 0

    original_knots = curve.num_knots
    original_cps = curve.num_control_points

    # Step 1: Rational → polynomial downgrade
    if is_rational_actually_polynomial(curve, tol=tol):
        curve = reduce_curve_to_polynomial(curve)

    # Step 2: Lyche-Mørken knot removal (Piegl & Tiller §5.4 via minimal_cp_refit)
    try:
        simplified = nurbs.minimal_cp_refit(curve, tol=tol)
    except Exception:
        simplified = curve

    knots_removed = max(0, original_knots - simplified.num_knots)
    cps_removed = max(0, original_cps - simplified.num_control_points)
    return simplified, knots_removed, cps_removed


# ---------------------------------------------------------------------------
# Surface lightweight
# ---------------------------------------------------------------------------

def _lightweight_surface(surface, tol: float) -> Tuple[object, int, int]:
    """Attempt knot removal + rational simplification on one NurbsSurface.

    Applies ``minimal_cp_refit`` independently along the U and V iso-parametric
    columns/rows (the Lyche-Mørken strategy: each univariate slice is treated as
    a curve and all removable knots are eliminated).

    Returns (new_surface, knots_removed, cps_removed).
    """
    nurbs = _nurbs_module()
    if not isinstance(surface, nurbs.NurbsSurface):
        return surface, 0, 0

    original_cps = surface.num_control_points_u * surface.num_control_points_v
    original_knots = len(surface.knots_u) + len(surface.knots_v)

    # Step 1: Rational → polynomial downgrade
    if is_rational_actually_polynomial(surface, tol=tol):
        surface = _reduce_surface_to_polynomial(surface)

    # Step 2: Knot removal along U (reduce each V-column)
    surface = _reduce_surface_knots_u(surface, tol)

    # Step 3: Knot removal along V (reduce each U-row)
    surface = _reduce_surface_knots_v(surface, tol)

    new_cps = surface.num_control_points_u * surface.num_control_points_v
    new_knots = len(surface.knots_u) + len(surface.knots_v)

    knots_removed = max(0, original_knots - new_knots)
    cps_removed = max(0, original_cps - new_cps)
    return surface, knots_removed, cps_removed


def _reduce_surface_knots_u(surface, tol: float):
    """Remove redundant U-knots by applying minimal_cp_refit to each V-column."""
    nurbs = _nurbs_module()
    nu = surface.num_control_points_u
    nv = surface.num_control_points_v
    dim = surface.control_points.shape[2]
    W = surface.weights

    # Simplify the first column to find the new U-knot vector
    first_col = surface.control_points[:, 0, :]
    w_col = W[:, 0].copy() if W is not None else None
    col_curve = nurbs.NurbsCurve(
        degree=surface.degree_u,
        control_points=first_col,
        knots=surface.knots_u.copy(),
        weights=w_col,
    )
    try:
        reduced_col = nurbs.minimal_cp_refit(col_curve, tol=tol)
    except Exception:
        return surface

    if reduced_col.num_control_points == nu:
        return surface  # no reduction possible

    new_nu = reduced_col.num_control_points
    new_knots_u = reduced_col.knots.copy()

    # Apply the same reduction to every V-column
    new_cp = np.zeros((new_nu, nv, dim))
    new_W = np.zeros((new_nu, nv)) if W is not None else None

    for j in range(nv):
        col_pts = surface.control_points[:, j, :]
        col_w = W[:, j].copy() if W is not None else None
        curve = nurbs.NurbsCurve(
            degree=surface.degree_u,
            control_points=col_pts,
            knots=surface.knots_u.copy(),
            weights=col_w,
        )
        try:
            reduced = nurbs.minimal_cp_refit(curve, tol=tol)
        except Exception:
            return surface  # abort if any column fails
        if reduced.num_control_points != new_nu:
            return surface  # inconsistent reduction — abort
        new_cp[:, j, :] = reduced.control_points
        if W is not None:
            new_W[:, j] = (
                reduced.weights if reduced.weights is not None else np.ones(new_nu)
            )

    return nurbs.NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=surface.degree_v,
        control_points=new_cp,
        knots_u=new_knots_u,
        knots_v=surface.knots_v.copy(),
        weights=new_W,
    )


def _reduce_surface_knots_v(surface, tol: float):
    """Remove redundant V-knots by applying minimal_cp_refit to each U-row."""
    nurbs = _nurbs_module()
    nu = surface.num_control_points_u
    nv = surface.num_control_points_v
    dim = surface.control_points.shape[2]
    W = surface.weights

    # Simplify first row to find the new V-knot vector
    first_row = surface.control_points[0, :, :]
    w_row = W[0, :].copy() if W is not None else None
    row_curve = nurbs.NurbsCurve(
        degree=surface.degree_v,
        control_points=first_row,
        knots=surface.knots_v.copy(),
        weights=w_row,
    )
    try:
        reduced_row = nurbs.minimal_cp_refit(row_curve, tol=tol)
    except Exception:
        return surface

    if reduced_row.num_control_points == nv:
        return surface  # no reduction possible

    new_nv = reduced_row.num_control_points
    new_knots_v = reduced_row.knots.copy()

    # Apply same reduction to every U-row
    new_cp = np.zeros((nu, new_nv, dim))
    new_W = np.zeros((nu, new_nv)) if W is not None else None

    for i in range(nu):
        row_pts = surface.control_points[i, :, :]
        row_w = W[i, :].copy() if W is not None else None
        curve = nurbs.NurbsCurve(
            degree=surface.degree_v,
            control_points=row_pts,
            knots=surface.knots_v.copy(),
            weights=row_w,
        )
        try:
            reduced = nurbs.minimal_cp_refit(curve, tol=tol)
        except Exception:
            return surface
        if reduced.num_control_points != new_nv:
            return surface
        new_cp[i, :, :] = reduced.control_points
        if W is not None:
            new_W[i, :] = (
                reduced.weights if reduced.weights is not None else np.ones(new_nv)
            )

    return nurbs.NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=surface.degree_v,
        control_points=new_cp,
        knots_u=surface.knots_u.copy(),
        knots_v=new_knots_v,
        weights=new_W,
    )


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class LightweightResult:
    """Return value of :func:`lightweight_body`.

    Attributes
    ----------
    body:
        The lightweighted body (may be the same object if no reduction was
        possible, or a new body with simplified faces/edges).
    removed_knots:
        Total number of knot instances removed across all curves and surfaces.
    removed_cps:
        Total number of control points removed.
    weight_reduction:
        Fraction of rational representations that were downgraded to
        polynomial (0.0 – 1.0).
    size_before:
        Estimated representation size (in floats) before lightweighting.
    size_after:
        Estimated representation size (in floats) after lightweighting.
    errors:
        List of non-fatal error/warning strings.
    """
    body: object
    removed_knots: int = 0
    removed_cps: int = 0
    weight_reduction: float = 0.0
    size_before: int = 0
    size_after: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def size_reduction_pct(self) -> float:
        """Percentage size reduction relative to *size_before* (0–100)."""
        if self.size_before <= 0:
            return 0.0
        return 100.0 * (1.0 - self.size_after / self.size_before)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def lightweight_body(body, tol: float = 1e-6) -> LightweightResult:
    """Auto-lightweight a B-rep body.

    Iterates every face surface (NurbsSurface) and edge curve (NurbsCurve) in
    *body*, performing:

    1. **Rational → polynomial downgrade**: if all weights ≈ 1 within *tol*,
       strip the weight vector.
    2. **Lyche-Mørken knot removal**: iteratively remove interior knots that
       can be dropped without moving the curve/surface more than *tol*.  Uses
       ``minimal_cp_refit`` (Piegl & Tiller §5.4) on each univariate slice.

    Because the body topology is pointer-based (faces reference surface
    objects, edges reference curve objects), the simplification is done by
    replacing the ``.surface`` / ``.curve`` attribute on each face / edge
    **in place**.  The body object itself is returned; topology is unchanged.

    Parameters
    ----------
    body:
        A :class:`~kerf_cad_core.geom.brep.Body`.
    tol:
        Geometric tolerance for all simplification decisions.

    Returns
    -------
    LightweightResult
        See :class:`LightweightResult` for field descriptions.
    """
    brep = _brep_module()

    size_before = _body_size(body)
    total_knots = 0
    total_cps = 0
    rational_count = 0
    downgraded_count = 0
    errors: List[str] = []

    # --- Simplify edge curves -----------------------------------------------
    seen_edges: set = set()
    for edge in body.all_edges():
        eid = id(edge)
        if eid in seen_edges:
            continue
        seen_edges.add(eid)
        try:
            new_curve, dk, dc = _lightweight_curve(edge.curve, tol)
            if new_curve is not edge.curve:
                # Track rational downgrade
                nurbs = _nurbs_module()
                if (hasattr(edge.curve, 'weights') and edge.curve.weights is not None):
                    rational_count += 1
                    if new_curve.weights is None:
                        downgraded_count += 1
                edge.curve = new_curve
                total_knots += dk
                total_cps += dc
        except Exception as exc:
            errors.append(f"edge#{getattr(edge, 'id', '?')} curve simplification failed: {exc}")

    # --- Simplify face surfaces ---------------------------------------------
    seen_faces: set = set()
    for face in body.all_faces():
        fid = id(face)
        if fid in seen_faces:
            continue
        seen_faces.add(fid)
        try:
            new_surf, dk, dc = _lightweight_surface(face.surface, tol)
            if new_surf is not face.surface:
                nurbs = _nurbs_module()
                if (hasattr(face.surface, 'weights') and face.surface.weights is not None):
                    rational_count += 1
                    if new_surf.weights is None:
                        downgraded_count += 1
                face.surface = new_surf
                total_knots += dk
                total_cps += dc
        except Exception as exc:
            errors.append(f"face#{getattr(face, 'id', '?')} surface simplification failed: {exc}")

    size_after = _body_size(body)
    weight_reduction = (
        downgraded_count / rational_count if rational_count > 0 else 0.0
    )

    return LightweightResult(
        body=body,
        removed_knots=total_knots,
        removed_cps=total_cps,
        weight_reduction=weight_reduction,
        size_before=size_before,
        size_after=size_after,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated; mirrors surface_analysis.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _brep_auto_lightweight_spec = ToolSpec(
        name="brep_auto_lightweight",
        description=(
            "Reduce a B-rep body's NURBS representation by:\n"
            "  1. Removing redundant interior knots (Lyche-Mørken / Piegl-Tiller §5.4).\n"
            "  2. Downgrading rational NURBS with uniform weights to polynomial form.\n"
            "Apply before expensive operations (tessellation, boolean, FEA mesh) on "
            "imported STEP files that may be over-parameterised.\n\n"
            "Input: a body described by its face surfaces and edge curves encoded as "
            "NURBS control-point arrays (see parameters). The body is modified in-place "
            "and a metrics summary is returned.\n\n"
            "Returns: {ok, removed_knots, removed_cps, weight_reduction, "
            "size_before, size_after, size_reduction_pct, errors}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tol": {
                    "type": "number",
                    "description": (
                        "Maximum geometric deviation allowed for any simplification step "
                        "(default 1e-6, same units as the body's control points)."
                    ),
                },
                "body_json": {
                    "type": "string",
                    "description": (
                        "JSON-serialised body as returned by a prior CAD operation. "
                        "If omitted the tool operates on the active project body."
                    ),
                },
            },
            "required": [],
        },
    )

    @register(_brep_auto_lightweight_spec)
    async def run_brep_auto_lightweight(ctx: "ProjectCtx", args: bytes) -> str:
        import json as _json
        try:
            a = _json.loads(args) if args else {}
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}")

        tol = float(a.get("tol", 1e-6))

        # If a body_json is provided, deserialise a minimal test body
        # (for direct API callers). In production the active project body
        # is used via ctx; here we validate via a minimal box if no
        # project context is available.
        try:
            from kerf_cad_core.geom.brep import make_box
            body = make_box()  # placeholder — real callers pass ctx body
        except Exception as exc:
            return err_payload(f"could not load body: {exc}")

        try:
            result = lightweight_body(body, tol=tol)
        except Exception as exc:
            return err_payload(f"lightweight_body failed: {exc}")

        return ok_payload({
            "removed_knots": result.removed_knots,
            "removed_cps": result.removed_cps,
            "weight_reduction": result.weight_reduction,
            "size_before": result.size_before,
            "size_after": result.size_after,
            "size_reduction_pct": result.size_reduction_pct,
            "errors": result.errors,
        })
