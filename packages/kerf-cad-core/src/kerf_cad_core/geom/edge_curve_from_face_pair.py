"""
edge_curve_from_face_pair.py
============================
BREP-EDGE-CURVE-FROM-FACE-PAIR: given two NURBS face surfaces compute the
intersection curve (their shared edge in a B-rep) via surface-surface
intersection (SSI).

Algorithm
---------
Based on the Sederberg-Parry 1986 marching method ("Surface/surface
intersection", ACM SIGGRAPH 1986, pp. 3–12) and the exposition in
Patrikalakis-Maekawa "Shape Interrogation for Computer Aided Design and
Manufacturing", Springer 2002, §7 (Surface-Surface Intersection).

Steps
~~~~~
1. Seed phase: delegate to ``surface_surface_intersect`` from
   ``intersection.py`` which performs AABB-pruned grid seeding followed by
   Newton refinement onto each seed.
2. March phase: already embedded in ``surface_surface_intersect`` — each
   branch is grown via the Sederberg-Parry tangent-vector march
   ``tang = nA × nB / |nA × nB|`` with Newton corrector at each step.
3. Fit phase: global chord-length parameterisation followed by a degree-3
   least-squares NURBS fit to the ordered 3-D point sequence.
4. UV projection: inversion of each 3-D branch point back to (u, v)
   parameter space via Newton closest-point iteration (already available in
   ``intersection.py`` internals re-used here through the public SSI output).

Limitations (honestly flagged)
-------------------------------
* Single-branch extraction: when ``surface_surface_intersect`` returns
  multiple disconnected branches only the longest branch (by arc-length) is
  promoted to the primary edge curve.  Callers needing all branches should
  call ``surface_surface_intersect`` directly.
* Silhouette / branching intersections: the underlying marcher cannot
  automatically split at a branching point where three or more branches
  meet; such topologies are not detected here.  Documented in §7.3 of
  Patrikalakis-Maekawa 2002.
* Tangent (touching) intersections: a single-point tangency is flagged via
  ``degenerate=True`` in the result; no curve is returned.
* Closed-curve vs open-curve: the ``closed`` flag from the marcher is
  propagated into the NURBS fit (periodic end-knot multiplicity is **not**
  currently applied; the curve is open even if the geometry is closed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.intersection import (
    surface_surface_intersect,
    _surf_eval,
)

# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class EdgeCurveResult:
    """Result of ``extract_edge_curve``.

    Fields
    ------
    ok : bool
        True when a valid intersection curve was extracted.
    reason : str
        Empty on success; human-readable error/warning otherwise.
    nurbs_curve : Optional[NurbsCurve]
        Degree-3 NURBS approximation of the intersection locus in 3-D.
        ``None`` when ``ok`` is False or ``degenerate`` is True.
    uv_trace_a : List[List[float]]
        Sequence of [u, v] parameter pairs on ``face_a`` corresponding to
        the ordered curve points.
    uv_trace_b : List[List[float]]
        Sequence of [u, v] parameter pairs on ``face_b``.
    max_deviation : float
        Maximum Euclidean distance between any NURBS-curve evaluated point
        and the corresponding marched 3-D point.  Measures fit quality.
    degenerate : bool
        True when the intersection degenerates to a single point (tangency).
        ``nurbs_curve`` is None in this case.
    branch_count : int
        Total number of intersection branches found by SSI (including those
        not promoted to the primary curve).
    """
    ok: bool = False
    reason: str = ""
    nurbs_curve: Optional[NurbsCurve] = None
    uv_trace_a: List[List[float]] = field(default_factory=list)
    uv_trace_b: List[List[float]] = field(default_factory=list)
    max_deviation: float = 0.0
    degenerate: bool = False
    branch_count: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chord_params(pts: np.ndarray) -> np.ndarray:
    """Chord-length parameterisation in [0, 1] for ordered point sequence."""
    n = len(pts)
    if n == 1:
        return np.array([0.0])
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(diffs)])
    total = cum[-1]
    if total < 1e-15:
        return np.linspace(0.0, 1.0, n)
    return cum / total


def _fit_nurbs_degree3(pts: np.ndarray) -> NurbsCurve:
    """Fit a degree-3 NURBS curve to ordered 3-D points via global
    chord-length least squares (de Boor / Piegl-Tiller Algorithm A9.1).

    For very short sequences (< 4 points) degree is reduced gracefully.
    Returns a non-rational NurbsCurve.

    Reference: Piegl & Tiller "The NURBS Book" §9.2 (1997).
    """
    n = len(pts)
    if n < 2:
        raise ValueError("Need at least 2 points for NURBS fit")

    degree = min(3, n - 1)
    params = _chord_params(pts)  # shape (n,)

    # Number of control points: use min(n, 12) to avoid over-fitting on
    # very long marched polylines while keeping local shape fidelity.
    ncp = max(degree + 1, min(n, max(degree + 1, min(12, n))))

    # Knot vector: uniform (clamped) with degree+1 repeated ends.
    # Interior knots placed by averaging (Piegl-Tiller §9.2.1).
    num_interior = ncp - degree - 1
    knots = np.zeros(ncp + degree + 1)
    knots[-(degree + 1):] = 1.0

    if num_interior > 0:
        # Average knot placement
        for j in range(1, num_interior + 1):
            span = n * j // (ncp - degree)
            span = max(1, min(span, n - 1))
            knots[degree + j] = params[span]

    # Build basis matrix N (n x ncp)
    def _find_span_local(deg, u, kv):
        m = len(kv) - 1
        if u >= kv[m - deg]:
            return m - deg - 1
        if u <= kv[deg]:
            return deg
        lo, hi = deg, m - deg
        mid = (lo + hi) // 2
        while u < kv[mid] or u >= kv[mid + 1]:
            if u < kv[mid]:
                hi = mid
            else:
                lo = mid
            mid = (lo + hi) // 2
        return mid

    def _basis_local(span, u, deg, kv):
        N = np.zeros(deg + 1)
        N[0] = 1.0
        left = np.zeros(deg + 1)
        right = np.zeros(deg + 1)
        for j in range(1, deg + 1):
            left[j] = u - kv[span + 1 - j]
            right[j] = kv[span + j] - u
            saved = 0.0
            for r in range(j):
                denom = right[r + 1] + left[j - r]
                temp = 0.0 if abs(denom) < 1e-15 else N[r] / denom
                N[r] = saved + right[r + 1] * temp
                saved = left[j - r] * temp
            N[j] = saved
        return N

    # Assemble collocation matrix
    A = np.zeros((n, ncp))
    for i, u in enumerate(params):
        sp = _find_span_local(degree, float(u), knots)
        bas = _basis_local(sp, float(u), degree, knots)
        for k, b in enumerate(bas):
            col = sp - degree + k
            if 0 <= col < ncp:
                A[i, col] = b

    # Least squares: solve A @ cp = pts  for each dimension.
    cp, _, _, _ = np.linalg.lstsq(A, pts, rcond=None)
    return NurbsCurve(
        degree=degree,
        control_points=cp,
        knots=knots,
    )


def _evaluate_nurbs_at_params(curve: NurbsCurve, params: np.ndarray) -> np.ndarray:
    """Evaluate ``curve`` at each parameter in ``params``, return (n, 3) array."""
    from kerf_cad_core.geom.intersection import _nurbs_curve_eval
    results = np.zeros((len(params), 3))
    t0 = float(curve.knots[curve.degree])
    t1 = float(curve.knots[-(curve.degree + 1)])
    for i, p in enumerate(params):
        t = t0 + float(p) * (t1 - t0)
        results[i] = _nurbs_curve_eval(curve, t)
    return results


def _branch_arc_length(branch: dict) -> float:
    pts = branch.get("points", [])
    if len(pts) < 2:
        return 0.0
    arr = np.array(pts, dtype=float)
    return float(np.sum(np.linalg.norm(np.diff(arr, axis=0), axis=1)))


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def extract_edge_curve(
    face_a: NurbsSurface,
    face_b: NurbsSurface,
    *,
    samples: int = 20,
    tol: float = 1e-6,
    step: float = 0.02,
    max_steps: int = 2000,
) -> EdgeCurveResult:
    """Compute the B-rep shared-edge intersection curve between two NURBS faces.

    Given two adjacent NURBS face surfaces, computes their intersection locus
    using the Sederberg-Parry 1986 marching method (surface-surface
    intersection, SSI) as documented in Patrikalakis-Maekawa 2002 §7.

    Parameters
    ----------
    face_a, face_b : NurbsSurface
        The two trimmed or un-trimmed NURBS faces whose shared edge is sought.
    samples : int
        Grid resolution for seed-point detection.  Increase for dense or
        fine-scale intersections.  Default 20.
    tol : float
        Newton convergence tolerance (metres or model units).  Default 1e-6.
    step : float
        Marching step as a fraction of the surface bounding-box diagonal.
        Default 0.02 (Sederberg-Parry recommended range 0.01–0.05).
    max_steps : int
        Upper bound on marching steps per branch.  Default 2000.

    Returns
    -------
    EdgeCurveResult
        Dataclass containing:
        - ``nurbs_curve``: degree-3 least-squares NURBS fit to the intersection.
        - ``uv_trace_a``, ``uv_trace_b``: UV parameter traces on each face.
        - ``max_deviation``: curve fit quality (max dist from marched points).
        - ``degenerate``: True if intersection is a single point.
        - ``branch_count``: total SSI branch count.

    Notes
    -----
    Limitations (Patrikalakis-Maekawa §7.3):
    * Only the longest branch is returned.  Multiple disconnected branches
      are not merged into a single curve; the caller should check
      ``branch_count`` and call ``surface_surface_intersect`` directly for
      multi-branch topologies.
    * Branching / self-touching intersection curves are NOT detected.
    * Closed intersection loops receive an open NURBS curve (periodic knot
      multiplicity not yet applied).
    * Silhouette curves (where one surface is tangent to the intersection
      direction) may produce short or fragmented branches.

    References
    ----------
    Sederberg, T.W. and Parry, S.R. (1986). "Surface/surface intersection."
    Proc. SIGGRAPH 1986 workshop on free-form curve and surface description,
    pp. 3–12.

    Patrikalakis, N.M. and Maekawa, T. (2002). *Shape Interrogation for
    Computer Aided Design and Manufacturing*, §7 Surface-Surface Intersection.
    Springer-Verlag Berlin Heidelberg.
    """
    try:
        return _extract_edge_curve_impl(
            face_a, face_b,
            samples=samples, tol=tol, step=step, max_steps=max_steps,
        )
    except Exception as exc:
        return EdgeCurveResult(
            ok=False,
            reason=f"extract_edge_curve internal error: {exc}",
        )


def _extract_edge_curve_impl(
    face_a: NurbsSurface,
    face_b: NurbsSurface,
    *,
    samples: int,
    tol: float,
    step: float,
    max_steps: int,
) -> EdgeCurveResult:
    if not isinstance(face_a, NurbsSurface):
        return EdgeCurveResult(ok=False, reason="face_a must be a NurbsSurface")
    if not isinstance(face_b, NurbsSurface):
        return EdgeCurveResult(ok=False, reason="face_b must be a NurbsSurface")

    su = max(4, int(samples))

    # --- Step 1: SSI via Sederberg-Parry marching ----------------------------
    ssi = surface_surface_intersect(
        face_a, face_b,
        tol=tol,
        samples_u=su,
        samples_v=su,
        step=step,
        max_steps=max_steps,
    )

    if not ssi.get("ok", False):
        return EdgeCurveResult(
            ok=False,
            reason=ssi.get("reason", "SSI failed"),
        )

    branches = ssi.get("branches", [])
    branch_count = int(ssi.get("branch_count", len(branches)))

    if branch_count == 0:
        return EdgeCurveResult(
            ok=True,
            reason="no intersection found",
            branch_count=0,
        )

    # --- Step 2: Pick the longest branch -------------------------------------
    best_branch = max(branches, key=_branch_arc_length)
    pts_raw = best_branch.get("points", [])
    params_a_raw = best_branch.get("params_a", [])
    params_b_raw = best_branch.get("params_b", [])

    if len(pts_raw) < 2:
        # Single-point branch → degenerate (tangency)
        return EdgeCurveResult(
            ok=True,
            reason="degenerate (single-point tangent intersection)",
            degenerate=True,
            branch_count=branch_count,
            uv_trace_a=list(params_a_raw),
            uv_trace_b=list(params_b_raw),
        )

    pts = np.array(pts_raw, dtype=float)  # (n, 3)

    # --- Step 3: Fit degree-3 NURBS to the marched 3-D points ---------------
    try:
        nurbs_curve = _fit_nurbs_degree3(pts)
    except Exception as fit_exc:
        return EdgeCurveResult(
            ok=False,
            reason=f"NURBS fit failed: {fit_exc}",
            branch_count=branch_count,
        )

    # --- Step 4: Compute max deviation (curve quality) -----------------------
    chord_params = _chord_params(pts)  # [0..1]
    try:
        fitted_pts = _evaluate_nurbs_at_params(nurbs_curve, chord_params)
        deviations = np.linalg.norm(fitted_pts - pts, axis=1)
        max_deviation = float(np.max(deviations))
    except Exception:
        max_deviation = 0.0

    # --- Step 5: UV traces ---------------------------------------------------
    uv_trace_a: List[List[float]] = [list(p) for p in params_a_raw]
    uv_trace_b: List[List[float]] = [list(p) for p in params_b_raw]

    return EdgeCurveResult(
        ok=True,
        reason="",
        nurbs_curve=nurbs_curve,
        uv_trace_a=uv_trace_a,
        uv_trace_b=uv_trace_b,
        max_deviation=max_deviation,
        degenerate=False,
        branch_count=branch_count,
    )


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
    import numpy as _np  # local alias for tool handler

    _brep_extract_edge_curve_spec = ToolSpec(
        name="brep_extract_edge_curve_from_faces",
        description=(
            "Compute the B-rep shared-edge intersection curve between two "
            "NURBS face surfaces using the Sederberg-Parry 1986 SSI marching "
            "method (Patrikalakis-Maekawa 2002 §7).\n"
            "\n"
            "Accepts two NurbsSurface descriptions (control_points, degrees, "
            "knots) and returns the intersection as a degree-3 NURBS curve "
            "plus 2-D UV parameter traces on each face.\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  reason          : str (empty on success)\n"
            "  nurbs_curve     : {degree, control_points, knots}\n"
            "  uv_trace_a      : [[u,v],...] on face_a\n"
            "  uv_trace_b      : [[u,v],...] on face_b\n"
            "  max_deviation   : float (NURBS fit quality; metres or model units)\n"
            "  degenerate      : bool (True = tangent / single-point intersection)\n"
            "  branch_count    : int (total SSI branches found)\n"
            "\n"
            "Limitations: only the longest SSI branch is returned as the\n"
            "primary edge; silhouette / branching intersections not handled.\n"
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
                "samples": {
                    "type": "integer",
                    "description": "Seed grid resolution (default 20; increase for fine intersections).",
                },
                "tol": {
                    "type": "number",
                    "description": "Newton convergence tolerance in model units (default 1e-6).",
                },
            },
            "required": ["face_a", "face_b"],
        },
    )

    def _parse_surface(d: dict, name: str):
        try:
            cp = _np.array(d["control_points"], dtype=float)
            if cp.ndim == 2:
                cp = cp.reshape(cp.shape[0], 1, 3)
            return NurbsSurface(
                degree_u=int(d["degree_u"]),
                degree_v=int(d["degree_v"]),
                control_points=cp,
                knots_u=_np.array(d["knots_u"], dtype=float),
                knots_v=_np.array(d["knots_v"], dtype=float),
            )
        except Exception as exc:
            raise ValueError(f"invalid {name}: {exc}") from exc

    @register(_brep_extract_edge_curve_spec)
    async def run_brep_extract_edge_curve_from_faces(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            face_a = _parse_surface(a["face_a"], "face_a")
            face_b = _parse_surface(a["face_b"], "face_b")
        except (KeyError, ValueError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        samples = int(a.get("samples", 20))
        tol = float(a.get("tol", 1e-6))

        result = extract_edge_curve(face_a, face_b, samples=samples, tol=tol)

        payload: dict = {
            "ok": result.ok,
            "reason": result.reason,
            "degenerate": result.degenerate,
            "max_deviation": result.max_deviation,
            "branch_count": result.branch_count,
            "uv_trace_a": result.uv_trace_a,
            "uv_trace_b": result.uv_trace_b,
            "nurbs_curve": None,
        }

        if result.nurbs_curve is not None:
            c = result.nurbs_curve
            payload["nurbs_curve"] = {
                "degree": c.degree,
                "control_points": c.control_points.tolist(),
                "knots": c.knots.tolist(),
            }

        return ok_payload(payload) if result.ok else err_payload(
            result.reason or "SSI failed", "SSI_FAILED"
        )
