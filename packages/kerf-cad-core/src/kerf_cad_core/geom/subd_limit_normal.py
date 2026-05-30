"""subd_limit_normal.py
=====================
Stam exact limit-surface NORMAL evaluation for Catmull-Clark subdivision.

Implements §3.2 of Stam 1998: the normal at any (u, v) — including at
extraordinary vertices — is N = (∂S/∂u) × (∂S/∂v) normalised to unit
length, where ∂S/∂u and ∂S/∂v are the exact tangent vectors from the
eigendecomposition.

Public API
----------
evaluate_limit_normal(face_quad, u, v, n_irregular_vertex=4) -> ndarray (3,)
    Unit-length limit-surface normal at parameter (u, v).

evaluate_limit_normal_grid(face_quad, n_irregular_vertex=4,
                           n_samples=10) -> ndarray (n_samples, n_samples, 3)
    Grid of limit normals over [0,1]² — convenience for visualization.

compare_normal_methods(face_quad, n_irregular_vertex=4,
                       n_samples=20) -> dict
    Returns {method_name: max_deviation_vs_exact} comparing
    'finite_difference', 'stam_exact', and 'limit_neighborhood_average'.

References
----------
Stam, J. (1998). "Exact Evaluation of Catmull-Clark Subdivision Surfaces at
Arbitrary Parameter Values." SIGGRAPH 1998, pp. 395-404.
"""

from __future__ import annotations

from typing import Dict, Sequence, Union

import numpy as np

from kerf_cad_core.geom.subd_stam import stam_limit_tangents


# ---------------------------------------------------------------------------
# Core normal evaluation
# ---------------------------------------------------------------------------

def evaluate_limit_normal(
    face_quad: Union[np.ndarray, Sequence],
    u: float,
    v: float,
    n_irregular_vertex: int = 4,
) -> np.ndarray:
    """Evaluate the exact Catmull-Clark limit-surface unit normal at (u, v).

    Computes N = (∂S/∂u × ∂S/∂v) / |∂S/∂u × ∂S/∂v| using Stam's exact
    tangent vectors from the eigendecomposition (Stam 1998 §3.2).

    This is well-defined at extraordinary vertices (n ≠ 4) because the
    sub-dominant eigenpair gives non-zero, C¹-continuous tangent vectors
    at those points.

    Parameters
    ----------
    face_quad : array_like, shape (K, 3)
        2-ring control points in Stam ordering.
        K = 16 for regular patches (n=4), row-major 4×4 order.
        K = 2*n + 8 for irregular patches.
    u, v : float in [0, 1]
        Parameter values in the patch domain.
    n_irregular_vertex : int
        Valence of the extraordinary vertex. 4 = regular patch.

    Returns
    -------
    normal : ndarray, shape (3,)
        Unit-length surface normal.  In degenerate cases (zero cross product,
        e.g. collapsed geometry) a fallback of (0, 0, 1) is returned.

    References
    ----------
    Stam (1998) §3.2 — tangent-vector formulation for normals.
    """
    try:
        du, dv = stam_limit_tangents(
            face_quad,
            float(np.clip(u, 0.0, 1.0)),
            float(np.clip(v, 0.0, 1.0)),
            n_irregular_vertex=int(n_irregular_vertex),
        )
        normal = np.cross(du, dv)
        n_mag = float(np.linalg.norm(normal))
        if n_mag < 1e-14:
            # Degenerate tangent frame — return a sensible fallback.
            return np.array([0.0, 0.0, 1.0], dtype=float)
        return normal / n_mag
    except Exception:
        return np.array([0.0, 0.0, 1.0], dtype=float)


# ---------------------------------------------------------------------------
# Grid convenience
# ---------------------------------------------------------------------------

def evaluate_limit_normal_grid(
    face_quad: Union[np.ndarray, Sequence],
    n_irregular_vertex: int = 4,
    n_samples: int = 10,
) -> np.ndarray:
    """Evaluate the Stam-exact limit normal on an n_samples × n_samples grid.

    Useful for visualization, tessellation, and curvature analysis.

    Parameters
    ----------
    face_quad : array_like, shape (K, 3)
        2-ring control points (same convention as evaluate_limit_normal).
    n_irregular_vertex : int
        Valence of the extraordinary vertex.
    n_samples : int
        Number of samples along each parameter axis.  The grid spans
        [0, 1] × [0, 1] inclusive at the endpoints.

    Returns
    -------
    normals : ndarray, shape (n_samples, n_samples, 3)
        Unit normals at each grid point [i, j] corresponding to
        (u, v) = (i/(n_samples-1), j/(n_samples-1)).
        Edge cases with n_samples == 1 produce a single central sample.
    """
    pts = np.asarray(face_quad, dtype=float)
    n = int(n_samples)
    if n < 1:
        n = 1

    ts = np.linspace(0.0, 1.0, n) if n > 1 else np.array([0.5])
    result = np.zeros((n, n, 3), dtype=float)

    for i, u in enumerate(ts):
        for j, v in enumerate(ts):
            result[i, j] = evaluate_limit_normal(
                pts, float(u), float(v), n_irregular_vertex=n_irregular_vertex
            )

    return result


# ---------------------------------------------------------------------------
# Comparison utility
# ---------------------------------------------------------------------------

def compare_normal_methods(
    face_quad: Union[np.ndarray, Sequence],
    n_irregular_vertex: int = 4,
    n_samples: int = 20,
) -> Dict[str, float]:
    """Compare normal-estimation methods against the Stam-exact normal.

    Evaluates three methods at a uniform (n_samples × n_samples) grid over
    the patch interior and returns the maximum angular deviation (in radians)
    of each method from the Stam-exact normal.

    Methods
    -------
    stam_exact
        Exact tangent-cross-product normal from stam_limit_tangents.
        Used as the reference; deviation is 0.0 by definition.
    finite_difference (h = 1e-5)
        FD approximation of ∂S/∂u and ∂S/∂v using stam_limit_position
        at (u ± h, v) and (u, v ± h).  Should match stam_exact to ~1e-5.
    limit_neighborhood_average
        Simple average of the normals at 4 parameter-neighbours of each
        sample point.  Baseline method; least accurate near extraordinary
        vertices.

    Parameters
    ----------
    face_quad : array_like, shape (K, 3)
        2-ring control points.
    n_irregular_vertex : int
        Valence of the extraordinary vertex.
    n_samples : int
        Grid density per axis.  Interior samples only (boundary excluded
        for finite-difference stability).

    Returns
    -------
    dict : {str: float}
        Keys: 'stam_exact', 'finite_difference', 'limit_neighborhood_average'.
        Values: maximum angular deviation (radians) from stam_exact over
        the interior sample grid.
    """
    from kerf_cad_core.geom.subd_stam import stam_limit_position

    pts = np.asarray(face_quad, dtype=float)
    n = int(n_irregular_vertex)

    # Interior samples only (avoid boundary singularities for FD)
    ts = np.linspace(0.05, 0.95, n_samples)

    max_dev_fd = 0.0
    max_dev_avg = 0.0

    for u in ts:
        for v in ts:
            # Stam-exact reference normal
            exact_n = evaluate_limit_normal(pts, u, v, n_irregular_vertex=n)

            # --- Finite-difference normal ---
            h = 1e-5
            p_u_fwd = np.asarray(
                stam_limit_position(pts, min(u + h, 1.0), v, n_irregular_vertex=n),
                dtype=float,
            )
            p_u_bwd = np.asarray(
                stam_limit_position(pts, max(u - h, 0.0), v, n_irregular_vertex=n),
                dtype=float,
            )
            p_v_fwd = np.asarray(
                stam_limit_position(pts, u, min(v + h, 1.0), n_irregular_vertex=n),
                dtype=float,
            )
            p_v_bwd = np.asarray(
                stam_limit_position(pts, u, max(v - h, 0.0), n_irregular_vertex=n),
                dtype=float,
            )
            fd_du = (p_u_fwd - p_u_bwd) / (2.0 * h)
            fd_dv = (p_v_fwd - p_v_bwd) / (2.0 * h)
            fd_cross = np.cross(fd_du, fd_dv)
            fd_mag = float(np.linalg.norm(fd_cross))
            fd_n = fd_cross / fd_mag if fd_mag > 1e-14 else np.array([0.0, 0.0, 1.0])

            dot_fd = float(np.clip(np.dot(exact_n, fd_n), -1.0, 1.0))
            dev_fd = float(np.arccos(abs(dot_fd)))
            max_dev_fd = max(max_dev_fd, dev_fd)

            # --- Neighbourhood-average normal ---
            delta = 0.05
            neighbours = [
                evaluate_limit_normal(pts, min(u + delta, 1.0), v, n_irregular_vertex=n),
                evaluate_limit_normal(pts, max(u - delta, 0.0), v, n_irregular_vertex=n),
                evaluate_limit_normal(pts, u, min(v + delta, 1.0), n_irregular_vertex=n),
                evaluate_limit_normal(pts, u, max(v - delta, 0.0), n_irregular_vertex=n),
            ]
            avg_n = np.mean(neighbours, axis=0)
            avg_mag = float(np.linalg.norm(avg_n))
            avg_n = avg_n / avg_mag if avg_mag > 1e-14 else np.array([0.0, 0.0, 1.0])

            dot_avg = float(np.clip(np.dot(exact_n, avg_n), -1.0, 1.0))
            dev_avg = float(np.arccos(abs(dot_avg)))
            max_dev_avg = max(max_dev_avg, dev_avg)

    return {
        "stam_exact": 0.0,
        "finite_difference": max_dev_fd,
        "limit_neighborhood_average": max_dev_avg,
    }


# ---------------------------------------------------------------------------
# LLM tool: subd_evaluate_limit_normal
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811

    _subd_eval_limit_normal_spec = ToolSpec(
        name="subd_evaluate_limit_normal",
        description=(
            "Evaluate the exact Catmull-Clark limit-surface UNIT NORMAL at "
            "arbitrary parameter (u, v) using Stam's eigenstructure method "
            "(Stam 1998 §3.2, SIGGRAPH).\n"
            "\n"
            "Unlike finite-difference approximations, this computes the exact "
            "C¹-continuous normal N = (∂S/∂u) × (∂S/∂v) / |...| directly "
            "from the eigendecomposition of the Catmull-Clark subdivision matrix. "
            "The normal is well-defined — no singularity — even at extraordinary "
            "vertices (valence ≠ 4).\n"
            "\n"
            "Inputs:\n"
            "  control_points  : [[x,y,z], ...]  2-ring control points.\n"
            "                    16 points for regular (n=4) patches; 2n+8 for valence-n.\n"
            "  u, v            : float in [0,1]  parameter values.\n"
            "  valence         : int  valence of the extraordinary vertex (default 4).\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  normal          : [x, y, z]  unit-length limit-surface normal\n"
            "  tangent_du      : [x, y, z]  ∂S/∂u (unnormalised)\n"
            "  tangent_dv      : [x, y, z]  ∂S/∂v (unnormalised)\n"
            "  is_regular      : bool  true if all vertices have valence 4\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "description": (
                        "2-ring control points as [[x,y,z], ...].  "
                        "16 points for regular patches; 2n+8 for valence-n."
                    ),
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 4,
                },
                "u": {
                    "type": "number",
                    "description": "Parameter u in [0, 1].",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "v": {
                    "type": "number",
                    "description": "Parameter v in [0, 1].",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "valence": {
                    "type": "integer",
                    "description": (
                        "Valence of the extraordinary vertex (default 4 = regular). "
                        "Use n≠4 for irregular patches with one extraordinary vertex."
                    ),
                    "default": 4,
                    "minimum": 3,
                },
            },
            "required": ["control_points", "u", "v"],
        },
    )

    @register(_subd_eval_limit_normal_spec)
    async def run_subd_evaluate_limit_normal(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_pts = a.get("control_points", [])
        u_val = a.get("u")
        v_val = a.get("v")
        valence = int(a.get("valence", 4))

        if not raw_pts:
            return err_payload("control_points is required", "BAD_ARGS")
        if u_val is None or v_val is None:
            return err_payload("u and v are required", "BAD_ARGS")
        if not isinstance(u_val, (int, float)) or not isinstance(v_val, (int, float)):
            return err_payload("u and v must be numbers", "BAD_ARGS")
        if valence < 3:
            return err_payload("valence must be >= 3", "BAD_ARGS")

        expected_k = 16 if valence == 4 else 2 * valence + 8
        if len(raw_pts) < 4:
            return err_payload(
                f"control_points too short: got {len(raw_pts)}, expected {expected_k}",
                "BAD_ARGS",
            )

        try:
            pts = np.array([[float(c) for c in row] for row in raw_pts], dtype=float)
            if pts.ndim != 2 or pts.shape[1] != 3:
                return err_payload("each control point must be [x, y, z]", "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"invalid control_points: {exc}", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.subd_stam import stam_limit_tangents

            du, dv = stam_limit_tangents(
                pts, float(u_val), float(v_val), n_irregular_vertex=valence
            )
            normal = evaluate_limit_normal(pts, float(u_val), float(v_val),
                                           n_irregular_vertex=valence)

            return ok_payload({
                "ok": True,
                "normal": normal.tolist(),
                "tangent_du": du.tolist(),
                "tangent_dv": dv.tolist(),
                "is_regular": valence == 4,
            })
        except Exception as exc:
            return err_payload(f"evaluation failed: {exc}", "EVAL_ERROR")
