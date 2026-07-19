"""Tests for geom/auto_lightweight.py — B-rep auto-lightweight pass.

Oracle design
-------------
1. Already-lightweight identity  — a body with a minimal-representation
   NurbsCurve has removed_knots == 0 and removed_cps == 0.

2. Rational-but-polynomial       — a NurbsCurve with all weights == 1.0
   is recognised as polynomial; reduce_curve_to_polynomial strips the
   weights; evaluation agrees to 1e-12.

3. Knot removal                  — a degree-3 curve with one redundant
   interior knot (inserted then exposed to lightweight_body) has it
   removed; evaluation agrees within tol.

4. Size reduction                — a body whose face surface has extra
   knots inserted reports size_after < size_before and at least 20%
   reduction.

References: Piegl & Tiller §5.4; Lyche & Mørken 1988.
"""

import importlib.util
import os
import sys

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Load modules directly to avoid optional-package import chains
# ---------------------------------------------------------------------------

_BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src/kerf_cad_core")
)

def _load(rel_path, module_name):
    abs_path = os.path.join(_BASE, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod

# These loads register stand-in entries under `kerf_cad_core.*` in the
# process-global sys.modules so the loaded files' internal relative imports
# resolve. That cache is shared by the whole pytest session, so any stub left
# behind here — a `kerf_cad_core.geom` that isn't a real package — shadows the
# genuine package for every test file collected afterward. Snapshot and
# restore sys.modules once the local aliases below are captured; nothing past
# this block needs the stubs to remain installed.
_SNAPSHOT_KEYS = (
    "kerf_cad_core",
    "kerf_cad_core.geom",
    "kerf_cad_core.geom.nurbs",
    "kerf_cad_core.geom.brep",
    "kerf_cad_core.geom.auto_lightweight",
)
_snapshot = {k: sys.modules.get(k) for k in _SNAPSHOT_KEYS}

# Load in dependency order
_nurbs_mod = _load("geom/nurbs.py", "kerf_cad_core.geom.nurbs")
_brep_mod  = _load("geom/brep.py",  "kerf_cad_core.geom.brep")

# Patch the geom sub-package namespace so auto_lightweight's lazy imports work
import types
_geom_pkg = types.ModuleType("kerf_cad_core.geom")
_geom_pkg.nurbs = _nurbs_mod
_geom_pkg.brep  = _brep_mod
sys.modules["kerf_cad_core.geom"] = _geom_pkg

_kcc_pkg = types.ModuleType("kerf_cad_core")
sys.modules.setdefault("kerf_cad_core", _kcc_pkg)

_lw_mod = _load("geom/auto_lightweight.py", "kerf_cad_core.geom.auto_lightweight")

# Undo the sys.modules patching now that the module objects we need are
# captured directly (see aliases below) — restore whatever was there before
# (nothing, in the normal case) so later test files still see the real
# `kerf_cad_core.geom` package.
for _k, _v in _snapshot.items():
    if _v is None:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _v
del _snapshot, _k, _v

# Aliases
NurbsCurve   = _nurbs_mod.NurbsCurve
NurbsSurface = _nurbs_mod.NurbsSurface
make_box     = _brep_mod.make_box
Body         = _brep_mod.Body
Shell        = _brep_mod.Shell
Solid        = _brep_mod.Solid
Face         = _brep_mod.Face
Loop         = _brep_mod.Loop
Coedge       = _brep_mod.Coedge
Edge         = _brep_mod.Edge
Vertex       = _brep_mod.Vertex
Line3        = _brep_mod.Line3
Plane        = _brep_mod.Plane

lightweight_body             = _lw_mod.lightweight_body
is_rational_actually_polynomial = _lw_mod.is_rational_actually_polynomial
reduce_curve_to_polynomial   = _lw_mod.reduce_curve_to_polynomial
_curve_size                  = _lw_mod._curve_size
_body_size                   = _lw_mod._body_size
_correct_knot_insert         = _nurbs_mod._correct_knot_insert
minimal_cp_refit             = _nurbs_mod.minimal_cp_refit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cubic_bezier(p0, p1, p2, p3):
    """Single-segment degree-3 Bezier in 3-D."""
    pts = np.array([p0, p1, p2, p3], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=pts, knots=knots)


def _insert_knot(curve: NurbsCurve, u: float, num: int = 1) -> NurbsCurve:
    """Insert knot *u* via the correct Boehm formula."""
    P = curve.control_points.astype(float)
    U = curve.knots.astype(float)
    W = curve.weights
    if W is not None:
        Pw = np.column_stack([P * W[:, None], W])
    else:
        Pw = P.copy()
    for _ in range(num):
        Pw, U = _correct_knot_insert(Pw, U, curve.degree, u)
    if W is not None:
        new_W = Pw[:, -1].copy()
        new_P = Pw[:, :-1] / np.where(np.abs(new_W) > 1e-14, new_W, 1.0)[:, None]
        return NurbsCurve(degree=curve.degree, control_points=new_P, knots=U, weights=new_W)
    return NurbsCurve(degree=curve.degree, control_points=Pw, knots=U)


def _body_with_curve(curve: NurbsCurve) -> Body:
    """Minimal Body wrapping a single edge curve (open wire topology)."""
    v0 = Vertex(curve.evaluate(curve.knots[curve.degree]), tol=1e-7)
    v1 = Vertex(curve.evaluate(curve.knots[-(curve.degree + 1)]), tol=1e-7)
    edge = Edge(curve, float(curve.knots[curve.degree]),
                float(curve.knots[-(curve.degree + 1)]), v0, v1, tol=1e-7)
    # Build a trivial open loop (wire)
    ce0 = Coedge(edge, True)
    ce1 = Coedge(edge, False)
    loop = Loop([ce0, ce1], is_outer=True)
    body = Body(wires=[loop])
    return body


def _body_with_nurbs_face(surface: NurbsSurface) -> Body:
    """Minimal Body wrapping a single open NURBS face (sheet)."""
    face = Face(surface, loops=[], orientation=True, tol=1e-7)
    shell = Shell([face], is_closed=False)
    body = Body(shells=[shell])
    return body


# ---------------------------------------------------------------------------
# Test 1: Already-lightweight identity
# ---------------------------------------------------------------------------

def test_already_lightweight_identity():
    """A body whose curve is already at minimal representation is unchanged.

    Oracle: lightweight_body on a minimal-CP curve returns removed_knots == 0
    and removed_cps == 0.
    """
    # Degree-3 single-segment Bezier has no interior knots — nothing to remove.
    curve = _make_cubic_bezier(
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, 2.0, 0.0],
        [3.0, 0.0, 0.0],
    )
    body = _body_with_curve(curve)
    result = lightweight_body(body, tol=1e-6)

    assert result.removed_knots == 0, (
        f"Expected 0 knots removed on a minimal Bezier, got {result.removed_knots}"
    )
    assert result.removed_cps == 0, (
        f"Expected 0 CPs removed on a minimal Bezier, got {result.removed_cps}"
    )
    assert result.errors == [], f"Unexpected errors: {result.errors}"


# ---------------------------------------------------------------------------
# Test 2: Rational-but-polynomial downgrade
# ---------------------------------------------------------------------------

def test_rational_but_polynomial_downgrade():
    """A NurbsCurve with all-1.0 weights is geometrically polynomial.

    Oracles:
    a) is_rational_actually_polynomial returns True.
    b) reduce_curve_to_polynomial produces a non-rational curve.
    c) Evaluation of the downgraded curve agrees with the original to 1e-12.
    """
    pts = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, 2.0, 0.0],
        [3.0, 0.0, 0.0],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    weights = np.ones(4)
    rational_curve = NurbsCurve(degree=3, control_points=pts,
                                knots=knots, weights=weights)

    # Oracle a: recognised as polynomial
    assert is_rational_actually_polynomial(rational_curve, tol=1e-6), (
        "Expected all-unit-weight curve to be identified as polynomial"
    )

    # Oracle b: downgrade strips weights
    poly_curve = reduce_curve_to_polynomial(rational_curve)
    assert poly_curve.weights is None, (
        "reduce_curve_to_polynomial must set weights=None"
    )

    # Oracle c: evaluation matches
    t_vals = np.linspace(0.0, 1.0, 21)
    for t in t_vals:
        pt_rat = rational_curve.evaluate(t)
        pt_poly = poly_curve.evaluate(t)
        diff = float(np.linalg.norm(pt_rat - pt_poly))
        assert diff < 1e-12, (
            f"Evaluation mismatch at t={t:.3f}: "
            f"rational={pt_rat}, poly={pt_poly}, diff={diff:.3e}"
        )

    # Oracle d: lightweight_body does the downgrade automatically
    body = _body_with_curve(rational_curve)
    result = lightweight_body(body, tol=1e-6)
    # The edge curve in the body should now be non-rational
    edge_curves = [e.curve for e in body.all_edges()]
    assert all(c.weights is None for c in edge_curves
               if isinstance(c, NurbsCurve)), (
        "lightweight_body should downgrade all-unit-weight curves to polynomial"
    )


# ---------------------------------------------------------------------------
# Test 3: Knot removal on a curve with redundant interior knot
# ---------------------------------------------------------------------------

def test_knot_removal_redundant_interior_knot():
    """A curve with a redundant interior knot has it removed by lightweight_body.

    Setup: start with a degree-3 Bezier (no interior knots), insert knot at
    t=0.5 → the knot is geometrically redundant (shape is unchanged).

    Oracles:
    a) lightweight_body reports removed_knots > 0.
    b) The simplified curve evaluates to the same points as the original
       within tol (1e-6).
    """
    tol = 1e-6
    original = _make_cubic_bezier(
        [0.0, 0.0, 0.0],
        [1.0, 3.0, 0.0],
        [2.0, 3.0, 0.0],
        [3.0, 0.0, 0.0],
    )
    # Insert knot once at t=0.5 — geometrically redundant on a single-segment curve
    bloated = _insert_knot(original, 0.5, num=1)
    assert bloated.num_control_points == original.num_control_points + 1, (
        "Knot insertion should add one CP"
    )

    body = _body_with_curve(bloated)
    size_before_body = _body_size(body)

    result = lightweight_body(body, tol=tol)

    assert result.removed_knots > 0, (
        f"Expected at least 1 knot removed; got {result.removed_knots}. "
        f"Errors: {result.errors}"
    )
    assert result.removed_cps > 0, (
        f"Expected at least 1 CP removed; got {result.removed_cps}"
    )

    # Evaluate simplified curve vs original
    simplified_edge = list(body.all_edges())[0]
    simplified_curve = simplified_edge.curve
    t_vals = np.linspace(0.0, 1.0, 33)
    for t in t_vals:
        pt_orig = original.evaluate(t)
        pt_simp = simplified_curve.evaluate(t)
        diff = float(np.linalg.norm(pt_orig - pt_simp))
        assert diff <= tol + 1e-9, (
            f"Evaluation diverged at t={t:.3f}: orig={pt_orig}, "
            f"simplified={pt_simp}, diff={diff:.3e} > tol={tol}"
        )


# ---------------------------------------------------------------------------
# Test 4: Size reduction ≥ 20% on an over-parameterised body
# ---------------------------------------------------------------------------

def test_size_reduction_over_parameterised():
    """An over-parameterised face surface shrinks by ≥ 20% after lightweighting.

    Setup: build a flat bilinear NURBS surface (degree 1 × 1, 2×2 CPs) and
    bloat it by inserting redundant knots into both U and V directions (4
    extra knots each → multiplies the CP grid substantially).  Then run
    lightweight_body and verify size_after < 0.80 * size_before.
    """
    # Minimal flat surface: degree (1,1), 2×2 CPs, standard clamped knots
    # The surface is f(u,v) = (u, v, 0) — a unit square.
    base_cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
    ], dtype=float)
    base_ku = np.array([0.0, 0.0, 1.0, 1.0])
    base_kv = np.array([0.0, 0.0, 1.0, 1.0])
    base_surf = NurbsSurface(degree_u=1, degree_v=1,
                             control_points=base_cp,
                             knots_u=base_ku, knots_v=base_kv)

    # Elevate to degree 3 in both directions so there is room to insert
    # redundant interior knots.  Use minimal_cp_refit's inverse: we insert
    # knots into a degree-3 version.
    #
    # Simplest approach: build a degree-3 equivalent by elevating the flat
    # bilinear surface manually.  For a flat surface the degree-3 version
    # has 4×4 CPs and the same geometry.
    # Knots for 4 CPs, degree 3: [0,0,0,0,1,1,1,1]
    ku3 = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    kv3 = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    # For a flat (u,v,0) surface, the degree-3 Bezier CPs are just the
    # tensor product of (0, 1/3, 2/3, 1) × (0, 1/3, 2/3, 1).
    us = np.array([0.0, 1/3, 2/3, 1.0])
    vs = np.array([0.0, 1/3, 2/3, 1.0])
    cp3 = np.zeros((4, 4, 3))
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            cp3[i, j] = [u, v, 0.0]
    surf3 = NurbsSurface(degree_u=3, degree_v=3,
                         control_points=cp3,
                         knots_u=ku3, knots_v=kv3)

    # Now insert 3 redundant knots in U and 3 in V (all at different positions,
    # all geometrically redundant on a flat surface).
    def _insert_srf_knot_u(surf, u_val):
        """Insert one U-knot into each V-column of the surface."""
        nu = surf.num_control_points_u
        nv = surf.num_control_points_v
        dim = surf.control_points.shape[2]
        new_cols = []
        new_ku = None
        for j in range(nv):
            col = surf.control_points[:, j, :]
            curve = NurbsCurve(degree=surf.degree_u,
                               control_points=col,
                               knots=surf.knots_u.copy())
            P = col.astype(float)
            U = surf.knots_u.astype(float)
            Pw = P.copy()
            Pw_new, U_new = _correct_knot_insert(Pw, U, surf.degree_u, u_val)
            new_cols.append(Pw_new)
            if new_ku is None:
                new_ku = U_new
        new_nu = new_cols[0].shape[0]
        new_cp = np.zeros((new_nu, nv, dim))
        for j, col_pts in enumerate(new_cols):
            new_cp[:, j, :] = col_pts
        return NurbsSurface(degree_u=surf.degree_u, degree_v=surf.degree_v,
                            control_points=new_cp,
                            knots_u=new_ku, knots_v=surf.knots_v.copy())

    def _insert_srf_knot_v(surf, v_val):
        """Insert one V-knot into each U-row of the surface."""
        nu = surf.num_control_points_u
        nv = surf.num_control_points_v
        dim = surf.control_points.shape[2]
        new_rows = []
        new_kv = None
        for i in range(nu):
            row = surf.control_points[i, :, :]
            P = row.astype(float)
            U = surf.knots_v.astype(float)
            Pw = P.copy()
            Pw_new, U_new = _correct_knot_insert(Pw, U, surf.degree_v, v_val)
            new_rows.append(Pw_new)
            if new_kv is None:
                new_kv = U_new
        new_nv = new_rows[0].shape[0]
        new_cp = np.zeros((nu, new_nv, dim))
        for i, row_pts in enumerate(new_rows):
            new_cp[i, :, :] = row_pts
        return NurbsSurface(degree_u=surf.degree_u, degree_v=surf.degree_v,
                            control_points=new_cp,
                            knots_u=surf.knots_u.copy(), knots_v=new_kv)

    # Insert 3 redundant knots in U (at 0.25, 0.5, 0.75)
    bloated = surf3
    for u_val in [0.25, 0.5, 0.75]:
        bloated = _insert_srf_knot_u(bloated, u_val)
    # Insert 3 redundant knots in V
    for v_val in [0.25, 0.5, 0.75]:
        bloated = _insert_srf_knot_v(bloated, v_val)

    assert bloated.num_control_points_u > surf3.num_control_points_u, (
        "Bloated surface should have more U CPs than the base"
    )
    assert bloated.num_control_points_v > surf3.num_control_points_v, (
        "Bloated surface should have more V CPs than the base"
    )

    body = _body_with_nurbs_face(bloated)
    result = lightweight_body(body, tol=1e-6)

    assert result.size_before > 0, "size_before should be positive"
    assert result.size_after < result.size_before, (
        f"Expected size reduction; size_before={result.size_before}, "
        f"size_after={result.size_after}"
    )
    reduction = result.size_reduction_pct
    assert reduction >= 20.0, (
        f"Expected ≥20% size reduction; got {reduction:.1f}% "
        f"(before={result.size_before}, after={result.size_after})"
    )
