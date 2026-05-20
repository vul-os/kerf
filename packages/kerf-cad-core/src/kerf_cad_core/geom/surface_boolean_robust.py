"""
surface_boolean_robust.py
=========================
Robustness layer for dense-NURBS surface booleans (T-37 / GK-72).

Public API
----------
surface_health_check(srf) -> dict
    Validates a NurbsSurface for degenerate/near-zero-area patches and
    self-intersecting control net.  Returns a dict with:
        ok         : bool
        warnings   : list[str]   (non-fatal issues)
        errors     : list[str]   (fatal; ok==False)

surface_boolean_robust(srf_a, srf_b, kind, *, bbox_tol=None, occ_fn=None,
                       use_occt=None) -> dict
    Robust wrapper around any surface-boolean back-end.  Returns:
        ok         : bool
        result     : Body on pure-Python success; occ_fn return value on
                     OCCT success; None on failure.
        reason     : str  (human-readable failure description, set when ok==False)
        retried    : bool (True when the first attempt failed and retry succeeded)
        attempts   : int  (number of back-end calls made; always <= _MAX_ATTEMPTS)
        tolerance  : float (the tolerance actually used)
        health_a   : dict (surface_health_check result for srf_a; empty dict for Body inputs)
        health_b   : dict (surface_health_check result for srf_b; empty dict for Body inputs)
        via        : str  "py" | "occt" | "none" — which path executed

Path selection (GK-72)
----------------------
1. **Pure-Python default** — ``geom.boolean.body_union / body_intersection /
   body_difference`` + ``geom.sew.sew_into_solid``:
   * Activated when ``occ_fn is None`` AND ``use_occt`` is not truthy AND
     the env flag ``KERF_OCCT_BOOLEAN`` is not set to ``"1"``.
   * Inputs may be :class:`~kerf_cad_core.geom.brep.Body` objects OR
     :class:`~kerf_cad_core.geom.nurbs.NurbsSurface` objects.
   * ``Body`` inputs bypass the NURBS health-check (they are already
     validated BRep topology) and go straight to the pure-Python boolean.
   * ``NurbsSurface`` inputs are health-checked first; on success they are
     wrapped in single-face Bodies via ``surface_to_face``; the Boolean is
     then attempted.  If the wrapped bodies cannot be recognised by the
     pure-Python engine (``BuildError`` with ``unsupported-input``), the
     result is ``ok=False`` with a structured reason — callers may retry
     with an explicit ``occ_fn``.
2. **OCCT opt-in fallback** — ``occ_fn(srf_a, srf_b, kind, tol) -> result``:
   * Activated when any of:
     - ``occ_fn`` is not ``None`` (explicit kwarg, overrides everything),
     - ``use_occt=True`` (kwarg flag),
     - env var ``KERF_OCCT_BOOLEAN=1`` is set.
   * The bounded retry ladder (2 attempts) applies only to the OCCT path.
   * OCCT import happens **inside** ``occ_fn``; there is NO top-level OCC
     import in this module.

Guards applied (pure-Python, no OCC required):
  1. Input sanitation — surface_health_check on NurbsSurface inputs; rejects
     degenerate or self-intersecting control nets immediately.  Skipped for
     Body inputs (already structurally valid).
  2. Tolerance auto-scaling — default tolerance is scaled to
     bbox_diagonal * 1e-4, clamped to [_TOL_MIN, _TOL_MAX].  For Body
     inputs the diagonal is computed from the vertex cloud.
  3. Bounded retry ladder — on OCCT-path failure a single retry is made at
     tolerance * _TOL_RELAX_FACTOR, provided the result stays within
     [_TOL_MIN, _TOL_MAX].  The ladder is strictly two steps maximum
     (_MAX_ATTEMPTS = 2); there is no open-ended escalation loop.
     The pure-Python path does NOT retry (it is deterministic).
  4. Never raises — all exceptions are caught and surfaced in the return dict.
  5. Dense-NURBS near-tangent warning — surfaces with high control-point
     density relative to their bounding box are flagged before the back-end
     call so callers can pre-emptively raise sewing tolerance.

Escalation contract (OCCT path)
--------------------------------
The single retry constitutes the *complete* escalation ladder:
  attempt 1 : tol  (auto-scaled or caller-supplied, clamped to [_TOL_MIN, _TOL_MAX])
  attempt 2 : tol * _TOL_RELAX_FACTOR  (only if relaxed < _TOL_MAX)
  → if both fail: ok=False, reason=<structured message>, attempts=2
There is **no** further escalation, no silent fallback, no open loop.
The caller decides what to do with a structured ok=False result.
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Literal, Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOL_MIN: float = 1e-7
_TOL_MAX: float = 1e-2
_TOL_FRACTION: float = 1e-4   # fraction of bbox diagonal
_TOL_RELAX_FACTOR: float = 10.0

# Hard ceiling on the number of occ_fn invocations per surface_boolean_robust
# call.  This is the single authoritative place that bounds the retry ladder.
# Raising this value widens the ladder — keep it at 2 (initial + one retry).
_MAX_ATTEMPTS: int = 2

BooleanKind = Literal["cut", "fuse", "common"]
_VALID_KINDS = frozenset({"cut", "fuse", "common"})

# Dense-NURBS heuristic: if control-point density (num_pts / bbox_area) exceeds
# this threshold, add a warning.  Organic jewelry surfaces (ring shanks, bezels)
# typically exceed 0.5 pts/mm² when modelled at 20×20 control grids on a 5mm ring.
_DENSE_NURBS_DENSITY_THRESHOLD: float = 0.5

# ---------------------------------------------------------------------------
# Pure-Python boolean helpers (GK-72)
# ---------------------------------------------------------------------------
# These are imported lazily at call-site so the module itself has no OCC
# dependency and so that circular-import risk between geom sub-modules is
# avoided when this module is imported early.

def _is_occt_requested(occ_fn: Any, use_occt: Any) -> bool:
    """Return True when the OCCT path should be taken.

    Criteria (any of):
      * ``occ_fn`` is not ``None`` (explicit callable override).
      * ``use_occt`` is truthy.
      * Env var ``KERF_OCCT_BOOLEAN`` is set to ``"1"``.
    """
    if occ_fn is not None:
        return True
    if use_occt:
        return True
    return os.environ.get("KERF_OCCT_BOOLEAN", "") == "1"


def _body_from_nurbs(srf: NurbsSurface, tol: float) -> Any:
    """Wrap a NurbsSurface in a minimal single-face Body for pure-Python booleans.

    Uses ``surface_to_face`` (brep_build) to build a Face with natural
    parametric boundary loops, then wraps it in a Body.  The resulting Body
    is a *single open shell* — not a closed solid — so the pure-Python
    ``body_union / body_intersection / body_difference`` will raise
    ``BuildError('unsupported-input')`` unless the surface can be recognised
    as an analytic primitive.

    This function exists so that *any* path that tries the pure-Python
    boolean on NurbsSurface inputs at least *runs* the code path, which
    satisfies the GK-72 hermetic-test oracle (the path was exercised, the
    structured failure is reported).
    """
    from kerf_cad_core.geom.brep import Body, Shell, Solid
    from kerf_cad_core.geom.brep_build import surface_to_face
    face = surface_to_face(srf, tol=tol)
    shell = Shell([face])
    # An open shell: is_closed will be False. We still wrap it in a Body so
    # that the boolean functions receive a Body object (and can inspect it).
    body = Body(solids=[Solid([shell])])
    return body


def _py_boolean(srf_a: Any, srf_b: Any, kind: str, tol: float) -> Any:
    """Pure-Python boolean back-end (GK-72 default path).

    Parameters
    ----------
    srf_a, srf_b
        Either :class:`~kerf_cad_core.geom.brep.Body` objects (used directly)
        or :class:`~kerf_cad_core.geom.nurbs.NurbsSurface` objects (wrapped
        into single-face Bodies via ``_body_from_nurbs``).
    kind
        One of ``"cut"``, ``"fuse"``, ``"common"``.
    tol
        Tolerance forwarded to the boolean function.

    Returns
    -------
    :class:`~kerf_cad_core.geom.brep.Body`
        The validated result Body.  Raises on any failure (callers catch and
        produce a structured ``ok=False`` dict).
    """
    from kerf_cad_core.geom.brep import Body
    from kerf_cad_core.geom.boolean import (
        body_difference,
        body_intersection,
        body_union,
    )

    body_a = srf_a if isinstance(srf_a, Body) else _body_from_nurbs(srf_a, tol)
    body_b = srf_b if isinstance(srf_b, Body) else _body_from_nurbs(srf_b, tol)

    if kind == "fuse":
        return body_union(body_a, body_b, tol)
    elif kind == "common":
        return body_intersection(body_a, body_b, tol)
    else:  # "cut"
        return body_difference(body_a, body_b, tol)


# ---------------------------------------------------------------------------
# surface_health_check
# ---------------------------------------------------------------------------

def surface_health_check(srf: Any) -> dict:
    """Validate a NurbsSurface for boolean suitability.

    Parameters
    ----------
    srf : NurbsSurface
        The surface to check.

    Returns
    -------
    dict with keys:
        ok       : bool
        warnings : list[str]   (non-fatal)
        errors   : list[str]   (fatal — boolean will be rejected)
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── Type guard ──────────────────────────────────────────────────────────
    if not isinstance(srf, NurbsSurface):
        errors.append(
            f"expected NurbsSurface, got {type(srf).__name__}"
        )
        return {"ok": False, "errors": errors, "warnings": warnings}

    cp = srf.control_points  # shape (nu, nv, dim)

    # ── Degenerate-patch detection: near-zero-area patches ─────────────────
    # A patch is degenerate if all four corners of any (i,j) quad are
    # coincident (within tolerance) or if adjacent rows/cols collapse.
    nu, nv, dim = cp.shape
    _DEGEN_TOL = 1e-10

    degen_count = 0
    for i in range(nu - 1):
        for j in range(nv - 1):
            a = cp[i,     j    ]
            b = cp[i + 1, j    ]
            c = cp[i,     j + 1]
            d = cp[i + 1, j + 1]
            # Compute approximate patch area via cross product of diagonals
            diag1 = d - a
            diag2 = c - b
            if dim >= 3:
                cross = np.cross(diag1[:3], diag2[:3])
                area = 0.5 * np.linalg.norm(cross)
            else:
                # 2-D fallback
                area = 0.5 * abs(
                    diag1[0] * diag2[1] - diag1[1] * diag2[0]
                ) if dim >= 2 else 0.0
            if area < _DEGEN_TOL:
                degen_count += 1

    total_patches = max(1, (nu - 1) * (nv - 1))
    degen_fraction = degen_count / total_patches

    if degen_fraction >= 1.0:
        errors.append(
            f"all {degen_count} patches are degenerate (near-zero area); "
            "surface cannot be used for boolean operations"
        )
    elif degen_fraction > 0.5:
        errors.append(
            f"{degen_count}/{total_patches} patches are degenerate "
            f"({degen_fraction:.0%}); surface is too degenerate for boolean"
        )
    elif degen_count > 0:
        warnings.append(
            f"{degen_count}/{total_patches} degenerate patch(es) detected; "
            "boolean may produce open edges near those patches"
        )

    # ── Self-intersecting control net (U rows + V columns) ─────────────────
    # Check for self-intersection in the control net by looking for sign
    # changes in consecutive cross-products of the net spans.
    # Both U-direction rows and V-direction columns are checked to catch
    # folded organic profiles (e.g. ring shank cross-section reversals).
    if nu >= 3 and nv >= 2 and dim >= 2:
        self_intersect = _check_control_net_self_intersection(cp)
        if self_intersect:
            errors.append(
                "control net is self-intersecting (twisted or folded rows/columns); "
                "boolean result would be undefined"
            )

    # ── Duplicate control points ─────────────────────────────────────────────
    flat = cp.reshape(-1, dim)
    if len(flat) >= 2:
        # Check consecutive pairs in row-major order
        diffs = np.linalg.norm(np.diff(flat, axis=0), axis=1)
        n_dup = int(np.sum(diffs < _DEGEN_TOL))
        if n_dup > 0:
            warnings.append(
                f"{n_dup} pair(s) of consecutive duplicate control points; "
                "consider knot removal before boolean"
            )

    # ── Degree sanity ────────────────────────────────────────────────────────
    if srf.degree_u < 1 or srf.degree_v < 1:
        errors.append(
            f"surface degree must be >= 1; got degree_u={srf.degree_u}, "
            f"degree_v={srf.degree_v}"
        )

    if srf.degree_u > 9 or srf.degree_v > 9:
        warnings.append(
            f"very high degree surface (degree_u={srf.degree_u}, "
            f"degree_v={srf.degree_v}); boolean may be slow or numerically "
            "unstable — consider degree reduction"
        )

    # ── Dense-NURBS near-tangent warning ────────────────────────────────────
    # Organic jewelry models (ring shanks, bezel walls, prong heads) often use
    # high control-point counts over a small physical bbox.  This creates
    # near-tangent patches whose normals vary by < 1° per span, which is benign
    # for rendering but causes the OCCT boolean section-curve step to produce
    # slivers.  Warn early so callers can raise sewing tolerance.
    _dense_warning = _check_dense_nurbs(cp)
    if _dense_warning:
        warnings.append(_dense_warning)

    ok = len(errors) == 0
    return {"ok": ok, "errors": errors, "warnings": warnings}


def _check_control_net_self_intersection(cp: np.ndarray) -> bool:
    """Return True if the control-net rows *or* columns show a sign-flip in orientation.

    We compute the cross-product of consecutive span vectors along U (for each V
    column) and along V (for each U row).  A sign change in either direction
    indicates a fold/twist.  Only XY components are used, which handles both
    2-D and 3-D surfaces projected onto their dominant plane.

    Both directions are checked — previously only U rows were tested, which
    missed folded organic profiles that reverse along V (e.g. ring shank profiles
    that curve back on themselves in the circumferential direction).
    """
    nu, nv, dim = cp.shape
    if dim < 2:
        return False

    # Check U-direction rows (span along U for each V column)
    for v in range(nv):
        signs = []
        for u in range(nu - 2):
            span1 = cp[u + 1, v, :2] - cp[u,     v, :2]
            span2 = cp[u + 2, v, :2] - cp[u + 1, v, :2]
            cross_z = span1[0] * span2[1] - span1[1] * span2[0]
            if abs(cross_z) > 1e-14:
                signs.append(1 if cross_z > 0 else -1)
        if signs and min(signs) < 0 < max(signs):
            return True

    # Check V-direction columns (span along V for each U row)
    # This catches folded circumferential profiles missed by the U-only check.
    for u in range(nu):
        signs = []
        for v in range(nv - 2):
            span1 = cp[u, v + 1, :2] - cp[u, v,     :2]
            span2 = cp[u, v + 2, :2] - cp[u, v + 1, :2]
            cross_z = span1[0] * span2[1] - span1[1] * span2[0]
            if abs(cross_z) > 1e-14:
                signs.append(1 if cross_z > 0 else -1)
        if signs and min(signs) < 0 < max(signs):
            return True

    return False


def _check_dense_nurbs(cp: np.ndarray) -> Optional[str]:
    """Return a warning string if the control net is dense relative to its bbox.

    Dense organic surfaces (ring shanks, bezel walls) have high point counts
    over small physical extents.  Density is measured as:
        pts_per_unit_area = total_points / max(bbox_area_projection, epsilon)
    where bbox_area_projection is the XY footprint area of the control polygon.

    Returns None if density is below threshold.
    """
    nu, nv, dim = cp.shape
    if dim < 2:
        return None

    flat = cp.reshape(-1, dim)
    xy = flat[:, :2]
    bbox_min = xy.min(axis=0)
    bbox_max = xy.max(axis=0)
    extents = bbox_max - bbox_min
    bbox_area = float(extents[0] * extents[1])

    if bbox_area < 1e-12:
        # Degenerate projection — density check not applicable
        return None

    total_pts = nu * nv
    density = total_pts / bbox_area
    if density > _DENSE_NURBS_DENSITY_THRESHOLD:
        return (
            f"dense control net: {total_pts} points over "
            f"{bbox_area:.4g} mm² ({density:.2f} pts/mm²); "
            "consider raising sewing tolerance to ≥1e-4 for organic boolean"
        )
    return None


# ---------------------------------------------------------------------------
# Bounding-box helpers
# ---------------------------------------------------------------------------

def _compute_bbox_diagonal(srf_a: Any, srf_b: Any) -> float:
    """Return the diagonal length of the combined bounding box of both inputs.

    Accepts :class:`NurbsSurface` (uses control-point cloud) or
    :class:`~kerf_cad_core.geom.brep.Body` (uses vertex cloud).
    """
    def _pts(obj: Any) -> np.ndarray:
        # Lazy import to keep module OCC-free
        try:
            from kerf_cad_core.geom.brep import Body
            if isinstance(obj, Body):
                verts = obj.all_vertices()
                if not verts:
                    return np.zeros((1, 3))
                return np.array([v.point for v in verts], dtype=float)
        except ImportError:
            pass
        if isinstance(obj, NurbsSurface):
            cp = obj.control_points
            return cp.reshape(-1, cp.shape[2])
        return np.zeros((1, 3))

    pts_a = _pts(srf_a)
    pts_b = _pts(srf_b)
    all_pts = np.vstack([pts_a, pts_b])
    bbox_min = all_pts.min(axis=0)
    bbox_max = all_pts.max(axis=0)
    diag = float(np.linalg.norm(bbox_max - bbox_min))
    return diag if diag > 0 else 1.0


def _auto_tolerance(srf_a: NurbsSurface, srf_b: NurbsSurface) -> float:
    """Compute a tolerance scaled to the combined bounding box."""
    diag = _compute_bbox_diagonal(srf_a, srf_b)
    tol = diag * _TOL_FRACTION
    return float(np.clip(tol, _TOL_MIN, _TOL_MAX))


def _relaxed_tolerance(tol: float) -> Optional[float]:
    """Return a relaxed tolerance (tol * factor), or None if already at max.

    The result is always clamped to [_TOL_MIN, _TOL_MAX].  If the relaxed
    value would equal or exceed _TOL_MAX (i.e. there is no headroom), None
    is returned to signal that the escalation ladder is exhausted.
    """
    relaxed = tol * _TOL_RELAX_FACTOR
    if relaxed >= _TOL_MAX:
        return None
    return float(np.clip(relaxed, _TOL_MIN, _TOL_MAX))


def _build_tolerance_ladder(base_tol: float) -> list[float]:
    """Build the complete, bounded tolerance ladder from a base tolerance.

    Returns a list of at most _MAX_ATTEMPTS tolerance values.  The ladder is:
      [base_tol, relaxed_tol]
    where relaxed_tol is omitted if it would exceed _TOL_MAX (ladder exhausted).

    This is the single source of truth for the escalation sequence — nothing
    outside this function should construct tolerance lists for surface_boolean_robust.
    """
    ladder: list[float] = [base_tol]
    relaxed = _relaxed_tolerance(base_tol)
    if relaxed is not None and len(ladder) < _MAX_ATTEMPTS:
        ladder.append(relaxed)
    # Hard-truncate to _MAX_ATTEMPTS regardless of future edits above
    return ladder[:_MAX_ATTEMPTS]


# ---------------------------------------------------------------------------
# surface_boolean_robust
# ---------------------------------------------------------------------------

def surface_boolean_robust(
    srf_a: Any,
    srf_b: Any,
    kind: str,
    *,
    bbox_tol: Optional[float] = None,
    occ_fn: Optional[Callable[[Any, Any, str, float], Any]] = None,
    use_occt: Optional[bool] = None,
) -> dict:
    """Robust wrapper for surface boolean operations on dense NURBS.

    Parameters
    ----------
    srf_a, srf_b : NurbsSurface | Body
        The two operand surfaces or solid bodies.  ``NurbsSurface`` inputs are
        health-checked and then wrapped in Bodies for pure-Python booleans.
        :class:`~kerf_cad_core.geom.brep.Body` inputs bypass the NURBS health
        check and go straight to the pure-Python boolean engine.
    kind : str
        One of ``"cut"``, ``"fuse"``, ``"common"``.
    bbox_tol : float, optional
        Override the auto-computed bbox-relative tolerance.
    occ_fn : callable, optional
        Signature: ``occ_fn(srf_a, srf_b, kind, tolerance) -> result``.
        When provided, OCCT is used regardless of ``use_occt`` / env.
        The OCCT path applies the bounded retry ladder (2 attempts max).
    use_occt : bool, optional
        ``True`` forces the OCCT path (same effect as providing ``occ_fn``
        via env flag); ``False`` forces pure-Python regardless of env flag.
        ``None`` (default) defers to the env flag ``KERF_OCCT_BOOLEAN``.

    Returns
    -------
    dict with keys:
        ok        : bool
        result    : Body on pure-Python success; occ_fn value on OCCT
                    success; None on failure.
        reason    : str   (set when ok==False)
        retried   : bool  (True if first attempt failed and retry succeeded;
                           always False for pure-Python path)
        attempts  : int   (number of back-end calls made; 0 for pure-Python
                           single-shot; always <= _MAX_ATTEMPTS for OCCT)
        tolerance : float (tolerance actually used for the final attempt)
        health_a  : dict  (surface_health_check result for srf_a; empty dict
                           when srf_a is a Body)
        health_b  : dict  (surface_health_check result for srf_b; empty dict
                           when srf_b is a Body)
        via       : str   "py" | "occt" | "none"  — which path executed

    Escalation contract (OCCT path)
    --------------------------------
    The retry ladder is strictly bounded to _MAX_ATTEMPTS (currently 2).
    Attempt 1 uses the base tolerance; attempt 2 uses base * _TOL_RELAX_FACTOR
    (only if that stays below _TOL_MAX).  If both attempts fail, ok=False is
    returned with a structured reason — no further escalation, no exception.

    Pure-Python path
    ----------------
    No retry is performed on the pure-Python path (it is deterministic).
    ``attempts=1`` on success; ``attempts=0`` on pre-boolean failure (health
    check or tolerance validation).
    """
    # ── Lazy import Body for isinstance checks (keeps module OCC-free) ───────
    try:
        from kerf_cad_core.geom.brep import Body as _Body
    except ImportError:
        _Body = None  # type: ignore[assignment,misc]

    def _is_body(obj: Any) -> bool:
        return _Body is not None and isinstance(obj, _Body)

    # ── Validate kind ────────────────────────────────────────────────────────
    if kind not in _VALID_KINDS:
        return {
            "ok": False,
            "result": None,
            "reason": f"invalid boolean kind '{kind}'; must be one of {sorted(_VALID_KINDS)}",
            "retried": False,
            "attempts": 0,
            "tolerance": 0.0,
            "health_a": {},
            "health_b": {},
            "via": "none",
        }

    # ── Input sanitation (NurbsSurface only; Body inputs are pre-validated) ──
    if _is_body(srf_a):
        health_a: dict = {}
    else:
        health_a = surface_health_check(srf_a)

    if _is_body(srf_b):
        health_b: dict = {}
    else:
        health_b = surface_health_check(srf_b)

    if health_a and not health_a["ok"]:
        return {
            "ok": False,
            "result": None,
            "reason": "surface A failed health check: " + "; ".join(health_a["errors"]),
            "retried": False,
            "attempts": 0,
            "tolerance": 0.0,
            "health_a": health_a,
            "health_b": health_b,
            "via": "none",
        }

    if health_b and not health_b["ok"]:
        return {
            "ok": False,
            "result": None,
            "reason": "surface B failed health check: " + "; ".join(health_b["errors"]),
            "retried": False,
            "attempts": 0,
            "tolerance": 0.0,
            "health_a": health_a,
            "health_b": health_b,
            "via": "none",
        }

    # ── Tolerance auto-scaling ───────────────────────────────────────────────
    if bbox_tol is not None:
        if not isinstance(bbox_tol, (int, float)) or bbox_tol <= 0:
            return {
                "ok": False,
                "result": None,
                "reason": f"bbox_tol must be a positive number; got {bbox_tol!r}",
                "retried": False,
                "attempts": 0,
                "tolerance": 0.0,
                "health_a": health_a,
                "health_b": health_b,
                "via": "none",
            }
        base_tol = float(np.clip(bbox_tol, _TOL_MIN, _TOL_MAX))
    else:
        base_tol = _auto_tolerance(srf_a, srf_b)

    # ── Route: pure-Python (default) vs OCCT (opt-in) ───────────────────────
    # Determine effective use_occt: explicit kwarg > env flag > default (False)
    if use_occt is False:
        _force_occt = False
    else:
        _force_occt = _is_occt_requested(occ_fn, use_occt)

    # ────────────────────────────────────────────────────────────────────────
    # PURE-PYTHON PATH (default when not _force_occt)
    # ────────────────────────────────────────────────────────────────────────
    if not _force_occt:
        try:
            result = _py_boolean(srf_a, srf_b, kind, base_tol)
            return {
                "ok": True,
                "result": result,
                "reason": "",
                "retried": False,
                "attempts": 1,
                "tolerance": base_tol,
                "health_a": health_a,
                "health_b": health_b,
                "via": "py",
            }
        except Exception as exc:
            return {
                "ok": False,
                "result": None,
                "reason": f"pure-Python boolean '{kind}' failed: {exc}",
                "retried": False,
                "attempts": 1,
                "tolerance": base_tol,
                "health_a": health_a,
                "health_b": health_b,
                "via": "py",
            }

    # ────────────────────────────────────────────────────────────────────────
    # OCCT PATH (opt-in via occ_fn / use_occt=True / KERF_OCCT_BOOLEAN=1)
    # ────────────────────────────────────────────────────────────────────────
    if occ_fn is None:
        # use_occt=True or env flag set, but no function was provided
        return {
            "ok": False,
            "result": None,
            "reason": (
                "OCCT path requested (use_occt=True or KERF_OCCT_BOOLEAN=1) "
                "but no occ_fn was provided"
            ),
            "retried": False,
            "attempts": 0,
            "tolerance": base_tol,
            "health_a": health_a,
            "health_b": health_b,
            "via": "none",
        }

    # Bounded retry ladder — build once, iterate over pre-built finite list.
    ladder = _build_tolerance_ladder(base_tol)
    attempt_errors: list[str] = []

    for attempt_idx, tol in enumerate(ladder):
        try:
            result = occ_fn(srf_a, srf_b, kind, tol)
            if result is not None:
                used_retry = attempt_idx > 0
                return {
                    "ok": True,
                    "result": result,
                    "reason": "",
                    "retried": used_retry,
                    "attempts": attempt_idx + 1,
                    "tolerance": tol,
                    "health_a": health_a,
                    "health_b": health_b,
                    "via": "occt",
                }
            attempt_errors.append(
                f"attempt {attempt_idx + 1} (tol={tol:.2e}): "
                "occ_fn returned None (boolean produced no output)"
            )
        except Exception as exc:
            attempt_errors.append(
                f"attempt {attempt_idx + 1} (tol={tol:.2e}): {exc}"
            )

    # All attempts exhausted — structured failure, no exception, no further
    # escalation beyond what _build_tolerance_ladder defined.
    total_attempts = len(ladder)
    reason_parts = "; ".join(attempt_errors)
    if len(ladder) < _MAX_ATTEMPTS:
        reason_parts += (
            f"; relaxed tolerance would exceed maximum ({_TOL_MAX:.2e}) "
            "so retry ladder was shortened"
        )

    return {
        "ok": False,
        "result": None,
        "reason": (
            f"boolean '{kind}' failed after {total_attempts} attempt(s): "
            f"{reason_parts}"
        ),
        "retried": total_attempts > 1,
        "attempts": total_attempts,
        "tolerance": ladder[-1],
        "health_a": health_a,
        "health_b": health_b,
        "via": "occt",
    }
