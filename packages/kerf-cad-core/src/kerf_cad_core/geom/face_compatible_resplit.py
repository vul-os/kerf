"""BREP-FACE-COMPATIBLE-RESPLIT — make two adjacent NURBS faces knot-compatible
along their shared edge.

Algorithm:
  1. Identify which parameter direction of each face corresponds to the
     shared edge (``edge_dir_a`` / ``edge_dir_b``).
  2. Compute the *union* of the internal knots along that direction
     (Piegl-Tiller §6.5 "Compatibility of Surfaces").
  3. For every knot in the union that is missing from face A's knot vector,
     insert it via the tensor-product Boehm algorithm (P&T Algorithm A5.1).
     Repeat for face B.
  4. If the degrees differ along the shared direction, degree-elevation is
     required (Hoffmann 1989 §6).  This is flagged via
     ``CompatibilityResult.degree_mismatch`` so the caller can apply
     ``_elevate_curve_bspline`` as needed; degree elevation is NOT performed
     automatically here to keep the function composable.

Depth bar (from task spec):
  face_a knots_u = [0,0,0,0.5,1,1,1]  (degree 2)
  face_b knots_u = [0,0,0,0.3,0.7,1,1,1]  (degree 2)
  After: both have [0,0,0,0.3,0.5,0.7,1,1,1] along the shared direction.

References:
  • Piegl & Tiller, "The NURBS Book" (2nd ed.), §6.5 — Compatibility of Surfaces
  • Hoffmann, "Geometric & Solid Modelling" (1989), §6 — Surface Compatibility
  • Piegl & Tiller Algorithm A5.1 — Surface knot insertion (tensor product)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, find_span


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class CompatibilityResult:
    """Result returned by :func:`make_faces_compatible`.

    Attributes
    ----------
    face_a_new:
        Updated copy of face A with knots inserted along the shared direction.
    face_b_new:
        Updated copy of face B with knots inserted along the shared direction.
    knots_inserted:
        The knot values that were added (union minus original interior knots
        of each face, deduplicated across both faces).
    shared_edge_dir_a:
        ``'u'`` or ``'v'`` — which direction of face A aligns with the shared
        edge.
    shared_edge_dir_b:
        ``'u'`` or ``'v'`` — which direction of face B aligns with the shared
        edge.
    degree_mismatch:
        ``True`` when the degrees along the shared direction differ between the
        two faces.  In this case the knot vectors are made as compatible as
        possible (by inserting into the lower-degree face's representation),
        but full G0 compatibility requires degree elevation first
        (Hoffmann 1989 §6).  The caller should apply
        ``kerf_cad_core.geom.nurbs._elevate_curve_bspline`` before or after
        calling this function.
    already_compatible:
        ``True`` when both faces were already compatible (no insertions needed).
    error:
        Non-empty string when the operation failed (e.g. no shared edge found).
    """

    face_a_new: Optional[NurbsSurface] = None
    face_b_new: Optional[NurbsSurface] = None
    knots_inserted: List[float] = field(default_factory=list)
    shared_edge_dir_a: str = ""
    shared_edge_dir_b: str = ""
    degree_mismatch: bool = False
    already_compatible: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _internal_knots(knots: np.ndarray, degree: int) -> np.ndarray:
    """Return the distinct internal breakpoints of a clamped knot vector.

    Strips the ``degree+1`` leading and trailing repeated boundary knots and
    deduplicates.  Result is a sorted 1-D float64 array (may be empty).

    Ref: Piegl-Tiller §6.5 eq. 6.1.
    """
    a = knots[degree]
    b = knots[-(degree + 1)]
    interior = knots[degree + 1: -(degree + 1)]
    # keep only values strictly inside [a, b]
    mask = (interior > a + 1e-14) & (interior < b - 1e-14)
    uniq = np.unique(interior[mask])
    return uniq


def _knot_insert_surface_u(srf: NurbsSurface, u_new: float) -> NurbsSurface:
    """Insert a single knot ``u_new`` into the U direction of *srf*.

    Implements P&T Algorithm A5.1 (one U-direction insertion per V-strip).
    Handles the weight grid when present (rational NURBS).

    References: Piegl-Tiller §5.2 Algorithm A5.1, §6.5.
    """
    p = srf.degree_u
    U = srf.knots_u
    n_u = srf.num_control_points_u
    n_v = srf.num_control_points_v
    P = srf.control_points  # (n_u, n_v, dim)
    W = srf.weights         # (n_u, n_v) or None
    dim = P.shape[2]

    k = find_span(n_u - 1, p, u_new, U)
    U_new = np.insert(U, k + 1, u_new)

    P_new = np.zeros((n_u + 1, n_v, dim))
    W_new = np.zeros((n_u + 1, n_v)) if W is not None else None

    for v_idx in range(n_v):
        pts = P[:, v_idx, :]
        new_pts = np.zeros((n_u + 1, dim))

        for i in range(k - p + 1):
            new_pts[i] = pts[i]
        for i in range(k, n_u):
            new_pts[i + 1] = pts[i]

        for i in range(k - p + 1, k + 1):
            denom = U[i + p] - U[i]
            alpha = (u_new - U[i]) / denom if abs(denom) > 1e-15 else 1.0
            new_pts[i] = alpha * pts[i] + (1.0 - alpha) * pts[i - 1]

        P_new[:, v_idx, :] = new_pts

        if W is not None:
            wts = W[:, v_idx]
            new_wts = np.zeros(n_u + 1)
            for i in range(k - p + 1):
                new_wts[i] = wts[i]
            for i in range(k, n_u):
                new_wts[i + 1] = wts[i]
            for i in range(k - p + 1, k + 1):
                denom = U[i + p] - U[i]
                alpha = (u_new - U[i]) / denom if abs(denom) > 1e-15 else 1.0
                new_wts[i] = alpha * wts[i] + (1.0 - alpha) * wts[i - 1]
            W_new[:, v_idx] = new_wts  # type: ignore[index]

    return NurbsSurface(
        degree_u=srf.degree_u,
        degree_v=srf.degree_v,
        control_points=P_new,
        knots_u=U_new,
        knots_v=srf.knots_v.copy(),
        weights=W_new,
    )


def _knot_insert_surface_v(srf: NurbsSurface, v_new: float) -> NurbsSurface:
    """Insert a single knot ``v_new`` into the V direction of *srf*.

    Symmetric to :func:`_knot_insert_surface_u`.
    """
    q = srf.degree_v
    V = srf.knots_v
    n_u = srf.num_control_points_u
    n_v = srf.num_control_points_v
    P = srf.control_points
    W = srf.weights
    dim = P.shape[2]

    k = find_span(n_v - 1, q, v_new, V)
    V_new = np.insert(V, k + 1, v_new)

    P_new = np.zeros((n_u, n_v + 1, dim))
    W_new = np.zeros((n_u, n_v + 1)) if W is not None else None

    for u_idx in range(n_u):
        pts = P[u_idx, :, :]
        new_pts = np.zeros((n_v + 1, dim))

        for j in range(k - q + 1):
            new_pts[j] = pts[j]
        for j in range(k, n_v):
            new_pts[j + 1] = pts[j]

        for j in range(k - q + 1, k + 1):
            denom = V[j + q] - V[j]
            alpha = (v_new - V[j]) / denom if abs(denom) > 1e-15 else 1.0
            new_pts[j] = alpha * pts[j] + (1.0 - alpha) * pts[j - 1]

        P_new[u_idx, :, :] = new_pts

        if W is not None:
            wts = W[u_idx, :]
            new_wts = np.zeros(n_v + 1)
            for j in range(k - q + 1):
                new_wts[j] = wts[j]
            for j in range(k, n_v):
                new_wts[j + 1] = wts[j]
            for j in range(k - q + 1, k + 1):
                denom = V[j + q] - V[j]
                alpha = (v_new - V[j]) / denom if abs(denom) > 1e-15 else 1.0
                new_wts[j] = alpha * wts[j] + (1.0 - alpha) * wts[j - 1]
            W_new[u_idx, :] = new_wts  # type: ignore[index]

    return NurbsSurface(
        degree_u=srf.degree_u,
        degree_v=srf.degree_v,
        control_points=P_new,
        knots_u=srf.knots_u.copy(),
        knots_v=V_new,
        weights=W_new,
    )


def _insert_knots_direction(srf: NurbsSurface, direction: str,
                             to_insert: np.ndarray) -> NurbsSurface:
    """Insert each value in *to_insert* once into *srf* along *direction*.

    Direction is ``'u'`` or ``'v'``.  Each value is only inserted once
    regardless of its target multiplicity (suitable for inter-surface
    compatibility which requires multiplicity ≤ degree).
    """
    result = srf
    for t in to_insert:
        if direction == "u":
            result = _knot_insert_surface_u(result, t)
        else:
            result = _knot_insert_surface_v(result, t)
    return result


def _missing_knots(
    existing_knots: np.ndarray,
    degree: int,
    target_internal: np.ndarray,
    tol: float = 1e-12,
) -> np.ndarray:
    """Return knots in *target_internal* that are absent from *existing_knots*.

    A knot is considered *present* if there is any value in *existing_knots*
    within ``tol`` of it.

    Ref: Piegl-Tiller §6.5 — merge of knot vectors before insertion.
    """
    missing = []
    for t in target_internal:
        if not np.any(np.abs(existing_knots - t) <= tol):
            missing.append(t)
    return np.array(missing, dtype=float)


# ---------------------------------------------------------------------------
# Shared-edge detection
# ---------------------------------------------------------------------------

_EDGE_DIRS = ("u", "v")


def _detect_shared_direction(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    shared_edge_a: str,
    shared_edge_b: str,
) -> Tuple[str, str]:
    """Return (dir_a, dir_b) from caller-supplied hints.

    The hint strings are ``'u_min'``, ``'u_max'``, ``'v_min'``, ``'v_max'``
    (the iso-parameter boundary on which the shared edge lies).  The
    *direction* is the perpendicular axis — for a ``u_min``/``u_max`` boundary
    the knot vector that needs to be made compatible is the **v** direction;
    for a ``v_min``/``v_max`` boundary it is the **u** direction.

    Wait — actually for Piegl-Tiller §6.5 the convention is different:
    If two surfaces share an edge along u=const, the **v** knot vectors must
    match.  If they share an edge along v=const, the **u** knot vectors must
    match.  This function returns the direction to be harmonised.
    """
    dir_a = "v" if shared_edge_a.startswith("u") else "u"
    dir_b = "v" if shared_edge_b.startswith("u") else "u"
    return dir_a, dir_b


def _infer_shared_edge(
    srf_a: NurbsSurface, srf_b: NurbsSurface, tol: float = 1e-6
) -> Tuple[str, str]:
    """Auto-detect which boundaries of srf_a and srf_b are geometrically shared.

    Samples the four iso-parameter boundary mid-points of each surface
    (u_min, u_max, v_min, v_max) and finds the pair (one from A, one from B)
    that is nearest in 3-D space.  Returns (edge_tag_a, edge_tag_b) using tags
    ``'u_min'``, ``'u_max'``, ``'v_min'``, ``'v_max'``.

    If the closest pair has a mid-point gap > *tol* × bbox_diagonal the
    function returns ``('', '')`` (no shared edge found).

    Ref: Hoffmann 1989 §6.1 — boundary curve identification.
    """
    # bbox diagonal for adaptive tolerance
    all_pts = np.concatenate([
        srf_a.control_points.reshape(-1, srf_a.control_points.shape[2]),
        srf_b.control_points.reshape(-1, srf_b.control_points.shape[2]),
    ], axis=0)
    diag = float(np.linalg.norm(all_pts.max(axis=0) - all_pts.min(axis=0)))
    if diag < 1e-14:
        diag = 1.0
    abs_tol = tol * diag

    def _mid_pt(srf: NurbsSurface, tag: str) -> np.ndarray:
        from kerf_cad_core.geom.nurbs import surface_evaluate
        u0 = srf.knots_u[srf.degree_u]
        u1 = srf.knots_u[-(srf.degree_u + 1)]
        v0 = srf.knots_v[srf.degree_v]
        v1 = srf.knots_v[-(srf.degree_v + 1)]
        if tag == "u_min":
            return surface_evaluate(srf, u0, (v0 + v1) / 2.0)
        if tag == "u_max":
            return surface_evaluate(srf, u1, (v0 + v1) / 2.0)
        if tag == "v_min":
            return surface_evaluate(srf, (u0 + u1) / 2.0, v0)
        return surface_evaluate(srf, (u0 + u1) / 2.0, v1)  # v_max

    tags = ["u_min", "u_max", "v_min", "v_max"]
    best_dist = float("inf")
    best_a = best_b = ""
    for ta in tags:
        pa = _mid_pt(srf_a, ta)
        for tb in tags:
            pb = _mid_pt(srf_b, tb)
            d = float(np.linalg.norm(pa - pb))
            if d < best_dist:
                best_dist = d
                best_a, best_b = ta, tb

    if best_dist > abs_tol:
        return "", ""
    return best_a, best_b


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_faces_compatible(
    face_a: NurbsSurface,
    face_b: NurbsSurface,
    edge_dir_a: str = "",
    edge_dir_b: str = "",
    tol: float = 1e-6,
) -> CompatibilityResult:
    """Make two NURBS faces knot-compatible along their shared edge.

    Given two adjacent NURBS surface patches *face_a* and *face_b* that share
    an edge (e.g. obtained from a B-rep sewing pass or a Boolean operation),
    insert the missing knots into each surface so that the knot vectors along
    the shared boundary direction are *identical* (Piegl-Tiller §6.5).

    The algorithm:
      1. Identify which iso-parameter boundary of each face lies on the shared
         edge (auto-detected geometrically, or supplied via *edge_dir_a* /
         *edge_dir_b*).
      2. Determine which parametric *direction* (u or v) must be harmonised —
         the direction *along* the shared edge (P-T §6.5).
      3. Form the union of the internal breakpoints from both knot vectors.
      4. Insert any breakpoints missing from face A into face A, and vice-versa,
         using the tensor-product Boehm algorithm (P-T Algorithm A5.1).
      5. Return both updated surfaces.

    Parameters
    ----------
    face_a, face_b:
        NURBS surface patches to be harmonised.  Must be defined on [0,1]² or
        any compatible clamped B-spline domain.
    edge_dir_a:
        Optional hint — ``'u_min'``, ``'u_max'``, ``'v_min'``, or ``'v_max'``
        indicating which boundary of *face_a* is the shared edge.  If empty the
        boundary is auto-detected by geometric proximity of iso-boundary
        mid-points.
    edge_dir_b:
        Same for *face_b*.  Must be supplied if *edge_dir_a* is supplied.
    tol:
        Geometric tolerance used for auto-detection (as a fraction of the
        combined bounding-box diagonal) and knot deduplication.

    Returns
    -------
    CompatibilityResult
        ``error`` is non-empty on failure.  ``face_a_new`` / ``face_b_new``
        are ``None`` on failure.

    Honest caveats
    ---------------
    * **Degree mismatch** — if ``face_a.degree_u != face_b.degree_u`` (or the
      corresponding v degrees), full compatibility requires degree elevation
      (Hoffmann 1989 §6).  This function flags ``degree_mismatch=True`` and
      still inserts the missing knots into the *lower-degree* surface's
      representation, but the resulting surfaces will not be truly compatible
      until the degrees are equalised.  Use
      ``kerf_cad_core.geom.nurbs._elevate_curve_bspline`` on the row/column
      curves of the lower-degree surface.
    * **Rational NURBS** — knot insertion is weight-correct (homogeneous-
      coordinate Boehm), but degree elevation of rational surfaces is not
      implemented here.
    * **Multiplicity** — this function inserts each missing knot exactly once.
      If the target multiplicity is > 1 (degenerate surfaces), it should be
      called with multiple entries in the target union.

    References
    ----------
    * Piegl & Tiller, *The NURBS Book*, 2nd ed., §6.5 "Compatibility of
      Surfaces".
    * Hoffmann, *Geometric and Solid Modelling*, 1989, §6 "Surface
      Compatibility".
    * Piegl & Tiller Algorithm A5.1 — NURBS surface knot insertion.
    """
    result = CompatibilityResult()

    # ------------------------------------------------------------------
    # Step 1 — identify the shared edge boundaries
    # ------------------------------------------------------------------
    if edge_dir_a and edge_dir_b:
        bnd_a, bnd_b = edge_dir_a, edge_dir_b
    else:
        bnd_a, bnd_b = _infer_shared_edge(face_a, face_b, tol)

    if not bnd_a or not bnd_b:
        result.error = (
            "No shared edge detected between face_a and face_b "
            "(closest boundary mid-points exceed geometric tolerance). "
            "Supply edge_dir_a / edge_dir_b hints if the surfaces are "
            "disconnected in the ambient geometry but logically adjacent."
        )
        return result

    # ------------------------------------------------------------------
    # Step 2 — the direction to harmonise is *along* the shared edge
    # ------------------------------------------------------------------
    # A boundary 'u_min' or 'u_max' is a v-isoparametric line, so the
    # direction *along* it is v; the perpendicular is u.  For Piegl-Tiller §6.5
    # "compatibility along the seam" we need to match the knot vector in the
    # direction *along* the shared boundary curve.
    dir_a = "v" if bnd_a.startswith("u") else "u"
    dir_b = "v" if bnd_b.startswith("u") else "u"

    result.shared_edge_dir_a = dir_a
    result.shared_edge_dir_b = dir_b

    # ------------------------------------------------------------------
    # Step 3 — degree check
    # ------------------------------------------------------------------
    deg_a = face_a.degree_u if dir_a == "u" else face_a.degree_v
    deg_b = face_b.degree_u if dir_b == "u" else face_b.degree_v

    if deg_a != deg_b:
        result.degree_mismatch = True
        # Proceed anyway — insert what we can; the result is partially correct.

    # ------------------------------------------------------------------
    # Step 4 — compute union of internal breakpoints
    # ------------------------------------------------------------------
    knots_a = face_a.knots_u if dir_a == "u" else face_a.knots_v
    knots_b = face_b.knots_u if dir_b == "u" else face_b.knots_v

    internal_a = _internal_knots(knots_a, deg_a)
    internal_b = _internal_knots(knots_b, deg_b)

    union_all = np.unique(np.concatenate([internal_a, internal_b]))

    # ------------------------------------------------------------------
    # Step 5 — insert missing knots into each face
    # ------------------------------------------------------------------
    missing_in_a = _missing_knots(knots_a, deg_a, union_all, tol=tol * 1e-3)
    missing_in_b = _missing_knots(knots_b, deg_b, union_all, tol=tol * 1e-3)

    knots_inserted_set = set(missing_in_a.tolist()) | set(missing_in_b.tolist())

    if len(missing_in_a) == 0 and len(missing_in_b) == 0 and not result.degree_mismatch:
        result.already_compatible = True
        result.face_a_new = face_a
        result.face_b_new = face_b
        result.knots_inserted = []
        return result

    face_a_new = _insert_knots_direction(face_a, dir_a, missing_in_a)
    face_b_new = _insert_knots_direction(face_b, dir_b, missing_in_b)

    result.face_a_new = face_a_new
    result.face_b_new = face_b_new
    result.knots_inserted = sorted(knots_inserted_set)
    return result


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import numpy as _np

    _spec = ToolSpec(
        name="brep_make_faces_compatible",
        description=(
            "Make two adjacent NURBS B-rep face surfaces knot-compatible along "
            "their shared edge by inserting the missing knots into each surface "
            "(Piegl-Tiller §6.5 'Compatibility of Surfaces'; Hoffmann 1989 §6).\n"
            "\n"
            "Given two NURBS surface patches that share a boundary edge but have "
            "incompatible knot vectors along the shared direction, this tool "
            "computes the union of internal breakpoints and inserts any missing "
            "knots into each surface using the tensor-product Boehm algorithm "
            "(P&T Algorithm A5.1).  The resulting surfaces have identical knot "
            "vectors along the seam and are ready for Boolean operations, "
            "surface sewing, or BREP repair.\n"
            "\n"
            "Example: face_a has knots_u=[0,0,0,0.5,1,1,1] (degree 2) and "
            "face_b has knots_u=[0,0,0,0.3,0.7,1,1,1] (degree 2).  After "
            "compatibilization both have [0,0,0,0.3,0.5,0.7,1,1,1].\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  reason          : str (empty on success)\n"
            "  face_a_new      : updated NURBS surface dict\n"
            "  face_b_new      : updated NURBS surface dict\n"
            "  knots_inserted  : [float, ...] — values inserted into union\n"
            "  shared_edge_dir_a : 'u' or 'v'\n"
            "  shared_edge_dir_b : 'u' or 'v'\n"
            "  degree_mismatch : bool — True if degrees differ (degree elevation "
            "                    required for full compatibility; see Hoffmann §6)\n"
            "  already_compatible : bool — True if no insertions were needed\n"
            "\n"
            "Limitations:\n"
            "  - Degree mismatch: if degrees along the seam differ, knots are "
            "    inserted but the surfaces are not truly compatible until degree "
            "    elevation is applied (degree_mismatch flag is set).\n"
            "  - Multiplicity > 1 at a single knot is not forced automatically.\n"
            "  - If both surfaces do not share a geometric boundary, supply "
            "    edge_dir_a / edge_dir_b hints explicitly.\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "face_a": {
                    "type": "object",
                    "description": "First NURBS surface (face A).",
                    "properties": {
                        "degree_u": {"type": "integer"},
                        "degree_v": {"type": "integer"},
                        "control_points": {
                            "type": "array",
                            "description": "3-D control-point grid as [nu][nv][3] nested array.",
                        },
                        "knots_u": {"type": "array", "items": {"type": "number"}},
                        "knots_v": {"type": "array", "items": {"type": "number"}},
                    },
                    "required": ["degree_u", "degree_v", "control_points", "knots_u", "knots_v"],
                },
                "face_b": {
                    "type": "object",
                    "description": "Second NURBS surface (face B).",
                    "properties": {
                        "degree_u": {"type": "integer"},
                        "degree_v": {"type": "integer"},
                        "control_points": {
                            "type": "array",
                            "description": "3-D control-point grid as [nu][nv][3] nested array.",
                        },
                        "knots_u": {"type": "array", "items": {"type": "number"}},
                        "knots_v": {"type": "array", "items": {"type": "number"}},
                    },
                    "required": ["degree_u", "degree_v", "control_points", "knots_u", "knots_v"],
                },
                "edge_dir_a": {
                    "type": "string",
                    "description": (
                        "Optional boundary hint for face_a: 'u_min', 'u_max', "
                        "'v_min', or 'v_max'.  Auto-detected if omitted."
                    ),
                    "enum": ["", "u_min", "u_max", "v_min", "v_max"],
                },
                "edge_dir_b": {
                    "type": "string",
                    "description": "Same as edge_dir_a but for face_b.",
                    "enum": ["", "u_min", "u_max", "v_min", "v_max"],
                },
                "tol": {
                    "type": "number",
                    "description": "Geometric tolerance fraction of bounding-box diagonal (default 1e-6).",
                },
            },
            "required": ["face_a", "face_b"],
        },
    )

    def _parse_srf(d: dict, name: str) -> NurbsSurface:
        try:
            cp = _np.array(d["control_points"], dtype=float)
            if cp.ndim == 2:
                # treat as (n, 3) — single row of control points
                cp = cp.reshape(cp.shape[0], 1, cp.shape[1])
            return NurbsSurface(
                degree_u=int(d["degree_u"]),
                degree_v=int(d["degree_v"]),
                control_points=cp,
                knots_u=_np.array(d["knots_u"], dtype=float),
                knots_v=_np.array(d["knots_v"], dtype=float),
            )
        except Exception as exc:
            raise ValueError(f"invalid {name}: {exc}") from exc

    def _srf_to_dict(srf: NurbsSurface) -> dict:
        return {
            "degree_u": srf.degree_u,
            "degree_v": srf.degree_v,
            "control_points": srf.control_points.tolist(),
            "knots_u": srf.knots_u.tolist(),
            "knots_v": srf.knots_v.tolist(),
        }

    @register(_spec)
    async def _run_brep_make_faces_compatible(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            fa = _parse_srf(a["face_a"], "face_a")
            fb = _parse_srf(a["face_b"], "face_b")
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        edge_dir_a = str(a.get("edge_dir_a", ""))
        edge_dir_b = str(a.get("edge_dir_b", ""))
        tol = float(a.get("tol", 1e-6))

        try:
            res = make_faces_compatible(
                fa, fb,
                edge_dir_a=edge_dir_a,
                edge_dir_b=edge_dir_b,
                tol=tol,
            )
        except Exception as exc:
            return err_payload(f"make_faces_compatible error: {exc}", "INTERNAL")

        if res.error:
            return err_payload(res.error, "NO_SHARED_EDGE")

        return ok_payload({
            "face_a_new": _srf_to_dict(res.face_a_new),
            "face_b_new": _srf_to_dict(res.face_b_new),
            "knots_inserted": res.knots_inserted,
            "shared_edge_dir_a": res.shared_edge_dir_a,
            "shared_edge_dir_b": res.shared_edge_dir_b,
            "degree_mismatch": res.degree_mismatch,
            "already_compatible": res.already_compatible,
        })
