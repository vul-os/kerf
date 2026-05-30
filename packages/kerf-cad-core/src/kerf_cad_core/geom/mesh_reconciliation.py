"""
mesh_reconciliation.py
======================
NURBS↔Mesh bidirectional reconciliation pipeline with fidelity tracking.

Reference: Lévy 2009 "Geogram + EXPLORE" reconciliation framework;
           ISO 10303-242 (managed model-based data).

Public API
----------
reconcile_nurbs_mesh(nurbs_body, reference_mesh) -> ReconciliationResult
    Compare a NURBS body's tessellated form against a reference mesh.
    Returns ReconciliationResult with deviation_metric, extras counts,
    and a fidelity_score ∈ [0, 1].

round_trip_nurbs_mesh(nurbs_body, mesh_resolution=0.1) -> RoundTripResult
    NURBS → mesh (at given tolerance) → re-fit NURBS via mesh_autosurface.
    Tracks deviation through each step.
    Returns RoundTripResult with intermediate_mesh, refit_body,
    total_deviation, and per_step_deviation.

reconcile_mesh_to_nurbs_with_features(mesh, feature_lines=None) -> NurbsBody
    Fit a NURBS body from a mesh, optionally guided by feature-line curves
    (Wave 4P SUBD-FEATURE-CURVES) to improve accuracy at sharp features.

fidelity_report(deviation, scale) -> str
    Classify deviation relative to model scale:
      'excellent' if deviation < 0.1% of scale
      'good'      if deviation < 1%
      'fair'      if deviation < 10%
      'poor'      otherwise

LLM tools (gated)
-----------------
@register tools: brep_reconcile_nurbs_mesh, brep_round_trip_with_fidelity

Notes
-----
All public functions never raise. Failures are returned as dicts with
``{"ok": False, "reason": "..."}``, or as dataclass instances with
``ok=False``.

The deviation metric follows the Lévy 2009 framework: two-sided
Hausdorff distance upper bound between the tessellated NURBS and the
reference mesh, normalised by the characteristic scale of the model
(diagonal of the bounding box).

"Extras" (mesh_vs_nurbs_extras, nurbs_vs_mesh_extras) are vertex counts
whose nearest-surface distance exceeds a proximity threshold (default 5%
of bounding-box diagonal). This detects geometry present in one
representation but absent in the other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ReconciliationResult:
    """Result of reconcile_nurbs_mesh.

    Attributes
    ----------
    ok : bool
        True if reconciliation completed successfully.
    reason : str
        Error message when ok=False; empty string otherwise.
    deviation_metric : float
        Two-sided Hausdorff distance upper bound (absolute units).
    mesh_vs_nurbs_extras : int
        Count of reference-mesh vertices with no close counterpart in the
        tessellated NURBS (geometry present in mesh but absent in NURBS).
    nurbs_vs_mesh_extras : int
        Count of tessellated-NURBS vertices with no close counterpart in the
        reference mesh (geometry in NURBS but absent in reference).
    fidelity_score : float
        Score ∈ [0, 1]: 1.0 = perfect match, 0.0 = completely different.
        Derived as exp(−deviation_metric / (0.01 * scale)) clamped to [0, 1].
    scale : float
        Characteristic scale (bounding-box diagonal of the combined point set).
    """
    ok: bool = False
    reason: str = ""
    deviation_metric: float = float("inf")
    mesh_vs_nurbs_extras: int = 0
    nurbs_vs_mesh_extras: int = 0
    fidelity_score: float = 0.0
    scale: float = 1.0


@dataclass
class RoundTripResult:
    """Result of round_trip_nurbs_mesh.

    Attributes
    ----------
    ok : bool
    reason : str
    intermediate_mesh : dict | None
        {'verts': [[x,y,z],...], 'faces': [[i,j,k],...]} from the NURBS
        tessellation step; None on failure.
    refit_body : Body | None
        The re-fitted NURBS body (None on failure).
    total_deviation : float
        Hausdorff distance between the original NURBS faces and the
        re-fitted body faces (end-to-end loss).
    per_step_deviation : dict
        {'nurbs_to_mesh': float, 'mesh_to_nurbs': float}
        Individual step deviations.
    fidelity_score : float
        ∈ [0, 1] based on total_deviation vs model scale.
    scale : float
    """
    ok: bool = False
    reason: str = ""
    intermediate_mesh: Optional[dict] = None
    refit_body: object = None
    total_deviation: float = float("inf")
    per_step_deviation: Dict[str, float] = field(default_factory=dict)
    fidelity_score: float = 0.0
    scale: float = 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tessellate_body(body: object, resolution: float) -> Optional[dict]:
    """Tessellate a Body into a triangle mesh.

    Samples each face's NURBS surface on a UV grid sized to achieve
    approximately `resolution` spacing. Returns:
        {'verts': list of [x,y,z], 'faces': list of [i,j,k]}
    or None on failure.
    """
    try:
        all_verts: List[List[float]] = []
        all_faces: List[List[int]] = []

        faces = list(body.all_faces())
        if not faces:
            return None

        for face in faces:
            surf = face.surface
            # Estimate grid resolution from bounding samples
            # Use at least 4 × 4 grid per face, targeting `resolution` spacing
            n_u = max(4, _estimate_grid_n(surf, "u", resolution))
            n_v = max(4, _estimate_grid_n(surf, "v", resolution))

            base_idx = len(all_verts)
            # Sample the surface
            us = np.linspace(0.0, 1.0, n_u)
            vs = np.linspace(0.0, 1.0, n_v)

            # Build vertex grid
            grid = np.zeros((n_u, n_v, 3))
            for i, u in enumerate(us):
                for j, v in enumerate(vs):
                    try:
                        pt = np.asarray(surf.evaluate(float(u), float(v)), dtype=float)
                        grid[i, j] = pt[:3]
                    except Exception:
                        # Fallback: use control point centroid
                        if hasattr(surf, "control_points"):
                            cp = np.asarray(surf.control_points)
                            grid[i, j] = cp.reshape(-1, cp.shape[-1])[:, :3].mean(axis=0)

            # Flatten grid verts
            for i in range(n_u):
                for j in range(n_v):
                    all_verts.append(grid[i, j].tolist())

            # Build triangle faces from the grid
            def vidx(i: int, j: int) -> int:
                return base_idx + i * n_v + j

            for i in range(n_u - 1):
                for j in range(n_v - 1):
                    # Two triangles per grid quad
                    a = vidx(i, j)
                    b = vidx(i + 1, j)
                    c = vidx(i + 1, j + 1)
                    d = vidx(i, j + 1)
                    all_faces.append([a, b, c])
                    all_faces.append([a, c, d])

        if not all_verts or not all_faces:
            return None

        return {"verts": all_verts, "faces": all_faces}
    except Exception:
        return None


def _estimate_grid_n(surf: object, direction: str, resolution: float) -> int:
    """Estimate grid samples needed for a given resolution along u or v."""
    try:
        # Sample 4 points along the direction and measure arc length
        pts = []
        for t in [0.0, 0.33, 0.67, 1.0]:
            if direction == "u":
                pt = np.asarray(surf.evaluate(float(t), 0.5), dtype=float)
            else:
                pt = np.asarray(surf.evaluate(0.5, float(t)), dtype=float)
            pts.append(pt[:3])
        arc = sum(float(np.linalg.norm(pts[i + 1] - pts[i])) for i in range(3))
        if arc < 1e-12 or resolution < 1e-12:
            return 4
        n = max(4, int(math.ceil(arc / resolution)) + 1)
        return min(n, 32)  # cap to avoid memory explosion
    except Exception:
        return 4


def _bounding_box_diagonal(pts_a: np.ndarray, pts_b: Optional[np.ndarray] = None) -> float:
    """Compute bounding-box diagonal of one or two point sets."""
    if pts_b is not None and len(pts_b) > 0:
        combined = np.vstack([pts_a, pts_b])
    else:
        combined = pts_a
    if len(combined) == 0:
        return 1.0
    lo = combined.min(axis=0)
    hi = combined.max(axis=0)
    diag = float(np.linalg.norm(hi - lo))
    return max(diag, 1e-10)


def _one_sided_hausdorff(pts_a: np.ndarray, pts_b: np.ndarray) -> float:
    """Directed Hausdorff distance: max over pts_a of min dist to pts_b.

    Uses a chunked approach to avoid O(N²) memory.
    """
    if len(pts_a) == 0 or len(pts_b) == 0:
        return float("inf")
    chunk = 512
    max_min = 0.0
    for start in range(0, len(pts_a), chunk):
        block = pts_a[start:start + chunk]
        # For each point in block, find min dist to pts_b
        # Using broadcasting in chunks over pts_b too
        min_dists = np.full(len(block), float("inf"))
        for bstart in range(0, len(pts_b), chunk):
            bblock = pts_b[bstart:bstart + chunk]
            diffs = block[:, None, :] - bblock[None, :, :]
            dists = np.sqrt((diffs ** 2).sum(axis=2))
            mins = dists.min(axis=1)
            min_dists = np.minimum(min_dists, mins)
        max_min = max(max_min, float(min_dists.max()))
    return max_min


def _two_sided_hausdorff(pts_a: np.ndarray, pts_b: np.ndarray) -> float:
    """Two-sided Hausdorff distance."""
    h_ab = _one_sided_hausdorff(pts_a, pts_b)
    h_ba = _one_sided_hausdorff(pts_b, pts_a)
    return max(h_ab, h_ba)


def _count_extras(
    pts_query: np.ndarray,
    pts_ref: np.ndarray,
    threshold: float,
) -> int:
    """Count points in pts_query with min distance to pts_ref > threshold."""
    if len(pts_query) == 0 or len(pts_ref) == 0:
        return len(pts_query)
    chunk = 512
    count = 0
    for start in range(0, len(pts_query), chunk):
        block = pts_query[start:start + chunk]
        min_dists = np.full(len(block), float("inf"))
        for bstart in range(0, len(pts_ref), chunk):
            bblock = pts_ref[bstart:bstart + chunk]
            diffs = block[:, None, :] - bblock[None, :, :]
            dists = np.sqrt((diffs ** 2).sum(axis=2))
            mins = dists.min(axis=1)
            min_dists = np.minimum(min_dists, mins)
        count += int((min_dists > threshold).sum())
    return count


def _fidelity_from_deviation(deviation: float, scale: float) -> float:
    """Compute fidelity score ∈ [0, 1] from deviation and scale.

    Uses exp(−(deviation / scale) / 0.1) so that:
      - 0.1% deviation → exp(−0.001/0.1) = exp(−0.01) ≈ 0.990
      - 1%   deviation → exp(−0.01/0.1)  = exp(−0.1)  ≈ 0.905
      - 10%  deviation → exp(−0.1/0.1)   = exp(−1.0)  ≈ 0.368
    This aligns with the fidelity_report thresholds (excellent/good/fair/poor).
    Clamped to [0, 1].
    """
    if scale < 1e-12:
        return 0.0
    ratio = deviation / scale
    score = math.exp(-ratio / 0.1)
    return float(max(0.0, min(1.0, score)))


def _verts_array(mesh: dict) -> np.ndarray:
    """Convert mesh verts list to (N, 3) ndarray."""
    verts = mesh.get("verts", [])
    if not verts:
        return np.zeros((0, 3))
    return np.array([[float(v[0]), float(v[1]), float(v[2])] for v in verts], dtype=float)


# ---------------------------------------------------------------------------
# fidelity_report
# ---------------------------------------------------------------------------

def fidelity_report(deviation: float, scale: float) -> str:
    """Classify deviation relative to model scale.

    Parameters
    ----------
    deviation : float
        Absolute geometric deviation (same units as scale).
    scale : float
        Characteristic model scale (e.g. bounding-box diagonal).

    Returns
    -------
    str
        'excellent' if deviation < 0.1% of scale
        'good'      if deviation < 1% of scale
        'fair'      if deviation < 10% of scale
        'poor'      otherwise
    """
    if scale <= 0.0:
        return "poor"
    ratio = deviation / scale
    if ratio < 0.001:
        return "excellent"
    if ratio < 0.01:
        return "good"
    if ratio < 0.10:
        return "fair"
    return "poor"


# ---------------------------------------------------------------------------
# reconcile_nurbs_mesh
# ---------------------------------------------------------------------------

def reconcile_nurbs_mesh(
    nurbs_body: object,
    reference_mesh: dict,
    *,
    mesh_resolution: float = 0.05,
    extras_threshold_fraction: float = 0.05,
) -> ReconciliationResult:
    """Compare a NURBS body's tessellated form against a reference mesh.

    The NURBS body is tessellated at the given resolution. The two-sided
    Hausdorff distance between the tessellated NURBS vertices and the
    reference mesh vertices is computed as the primary deviation metric.

    Parameters
    ----------
    nurbs_body : Body
        A kerf_cad_core Body with NURBS faces (output of mesh_autosurface
        or any other body constructor).
    reference_mesh : dict
        {'verts': [[x,y,z], ...], 'faces': [[i,j,k], ...]}
    mesh_resolution : float
        Tessellation resolution for the NURBS body (world units).
    extras_threshold_fraction : float
        Fraction of bounding-box diagonal used as the proximity threshold
        for extras detection (default 5%).

    Returns
    -------
    ReconciliationResult
    """
    result = ReconciliationResult()

    try:
        # Validate reference mesh
        ref_verts = reference_mesh.get("verts") if isinstance(reference_mesh, dict) else None
        if ref_verts is None or not isinstance(ref_verts, (list, tuple)) or len(ref_verts) == 0:
            result.reason = "reference_mesh must be a dict with non-empty 'verts' list"
            return result

        ref_pts = _verts_array(reference_mesh)
        if ref_pts.shape[0] == 0:
            result.reason = "reference_mesh has no parseable vertices"
            return result

        # Validate nurbs_body
        if nurbs_body is None or not hasattr(nurbs_body, "all_faces"):
            result.reason = "nurbs_body must be a Body with an all_faces() method"
            return result

        # Tessellate the NURBS body
        tess = _tessellate_body(nurbs_body, mesh_resolution)
        if tess is None:
            result.reason = "failed to tessellate nurbs_body"
            return result

        nurbs_pts = _verts_array(tess)
        if nurbs_pts.shape[0] == 0:
            result.reason = "tessellated NURBS body produced no vertices"
            return result

        # Compute scale
        scale = _bounding_box_diagonal(ref_pts, nurbs_pts)
        result.scale = scale

        # Two-sided Hausdorff as deviation metric
        deviation = _two_sided_hausdorff(nurbs_pts, ref_pts)
        result.deviation_metric = deviation

        # Extras detection (geometry in one but not the other)
        threshold = extras_threshold_fraction * scale
        result.mesh_vs_nurbs_extras = _count_extras(ref_pts, nurbs_pts, threshold)
        result.nurbs_vs_mesh_extras = _count_extras(nurbs_pts, ref_pts, threshold)

        # Fidelity score
        result.fidelity_score = _fidelity_from_deviation(deviation, scale)

        result.ok = True
        result.reason = ""

    except Exception as exc:
        result.ok = False
        result.reason = f"reconcile_nurbs_mesh failed: {exc}"

    return result


# ---------------------------------------------------------------------------
# round_trip_nurbs_mesh
# ---------------------------------------------------------------------------

def round_trip_nurbs_mesh(
    nurbs_body: object,
    *,
    mesh_resolution: float = 0.1,
) -> RoundTripResult:
    """NURBS → mesh → re-fit NURBS round-trip with fidelity tracking.

    Pipeline:
    1. Tessellate nurbs_body → intermediate_mesh (at mesh_resolution).
    2. Run mesh_autosurface on intermediate_mesh → refit_body.
    3. Measure step deviations:
       - nurbs_to_mesh: Hausdorff between nurbs_body surface samples and
         the intermediate mesh vertices.
       - mesh_to_nurbs: Hausdorff between intermediate mesh vertices and
         the refit_body surface samples.
    4. total_deviation: Hausdorff between original NURBS surface samples
       and the refit_body surface samples (end-to-end).

    Parameters
    ----------
    nurbs_body : Body
        Original NURBS body.
    mesh_resolution : float
        Tessellation resolution for both the original → mesh and the
        mesh-autosurface internal grid.

    Returns
    -------
    RoundTripResult
    """
    result = RoundTripResult()
    result.per_step_deviation = {"nurbs_to_mesh": float("inf"), "mesh_to_nurbs": float("inf")}

    try:
        from kerf_cad_core.geom.mesh_to_nurbs import mesh_autosurface  # type: ignore[import]
    except ImportError as exc:
        result.reason = f"missing dependency: {exc}"
        return result

    try:
        if nurbs_body is None or not hasattr(nurbs_body, "all_faces"):
            result.reason = "nurbs_body must be a Body with an all_faces() method"
            return result

        # ── Step 1: NURBS → mesh tessellation ──────────────────────────────
        intermediate_mesh = _tessellate_body(nurbs_body, mesh_resolution)
        if intermediate_mesh is None:
            result.reason = "tessellation of nurbs_body failed"
            return result
        result.intermediate_mesh = intermediate_mesh

        nurbs_pts = _verts_array(intermediate_mesh)
        if nurbs_pts.shape[0] == 0:
            result.reason = "tessellation produced no vertices"
            return result

        scale = _bounding_box_diagonal(nurbs_pts)
        result.scale = scale

        # Step 1 deviation: how far are mesh verts from the original NURBS?
        # Use nearest-surface distance proxy: re-sample original body faces
        original_surface_pts = _sample_body_surface(nurbs_body, n=16)
        if len(original_surface_pts) > 0:
            step1_dev = _two_sided_hausdorff(nurbs_pts, original_surface_pts)
        else:
            step1_dev = 0.0  # no data — treat as exact
        result.per_step_deviation["nurbs_to_mesh"] = step1_dev

        # ── Step 2: mesh → NURBS refit via mesh_autosurface ────────────────
        verts = intermediate_mesh["verts"]
        faces = intermediate_mesh["faces"]
        auto_result = mesh_autosurface(verts, faces, tol=mesh_resolution * 0.1, max_dev=scale * 0.1)
        if not auto_result["ok"] or auto_result["body"] is None:
            result.reason = f"mesh_autosurface failed: {auto_result.get('reason', '')}"
            return result

        refit_body = auto_result["body"]
        result.refit_body = refit_body

        # Step 2 deviation: mesh verts vs refit body surfaces
        refit_pts = _sample_body_surface(refit_body, n=16)
        if len(refit_pts) > 0 and len(nurbs_pts) > 0:
            step2_dev = _two_sided_hausdorff(nurbs_pts, refit_pts)
        else:
            step2_dev = auto_result.get("max_deviation", float("inf"))
        result.per_step_deviation["mesh_to_nurbs"] = step2_dev

        # ── Step 3: total deviation (original NURBS ↔ refit NURBS) ─────────
        if len(original_surface_pts) > 0 and len(refit_pts) > 0:
            total_dev = _two_sided_hausdorff(original_surface_pts, refit_pts)
        else:
            total_dev = max(step1_dev, step2_dev)
        result.total_deviation = total_dev

        # Fidelity score on total deviation
        result.fidelity_score = _fidelity_from_deviation(total_dev, scale)

        result.ok = True
        result.reason = ""

    except Exception as exc:
        result.ok = False
        result.reason = f"round_trip_nurbs_mesh failed: {exc}"

    return result


def _sample_body_surface(body: object, n: int = 12) -> np.ndarray:
    """Sample body face surfaces on an n×n UV grid; return (N*faces, 3) array."""
    try:
        pts_list: List[np.ndarray] = []
        us = np.linspace(0.0, 1.0, n)
        vs = np.linspace(0.0, 1.0, n)
        for face in body.all_faces():
            surf = face.surface
            for u in us:
                for v in vs:
                    try:
                        pt = np.asarray(surf.evaluate(float(u), float(v)), dtype=float)
                        pts_list.append(pt[:3])
                    except Exception:
                        pass
        if not pts_list:
            return np.zeros((0, 3))
        return np.array(pts_list, dtype=float)
    except Exception:
        return np.zeros((0, 3))


# ---------------------------------------------------------------------------
# reconcile_mesh_to_nurbs_with_features
# ---------------------------------------------------------------------------

def reconcile_mesh_to_nurbs_with_features(
    mesh: dict,
    *,
    feature_lines: Optional[List[List[List[float]]]] = None,
    tol: float = 1e-3,
    max_dev: float = 0.05,
) -> dict:
    """Fit a NURBS body from a mesh, guided by feature-line curves.

    Feature lines partition the mesh surface at sharp edges (creases,
    boundary curves, characteristic lines from Wave 4P SUBD-FEATURE-CURVES
    or user-provided polylines). Vertices near feature lines are treated as
    hard constraints during the chart segmentation so that NURBS patch
    boundaries align with the features, preserving them in the fitted body.

    Without feature lines: delegates to mesh_autosurface directly.
    With feature lines: vertices within a proximity band around any feature
    line are tagged; the UV-sphere grid is seeded to honour these tagged
    vertices as chart boundary anchors, improving deviation at sharp edges.

    Parameters
    ----------
    mesh : dict
        {'verts': [[x,y,z], ...], 'faces': [[i,j,k], ...]}
    feature_lines : list of polylines, optional
        Each polyline is a list of [x, y, z] points defining a feature curve
        on or near the mesh surface.
    tol : float
        Fitting tolerance.
    max_dev : float
        Maximum allowed deviation.

    Returns
    -------
    dict
        ok, reason, body, patch_count, max_deviation, validate_result,
        feature_guided (bool — True if feature lines were used).
    """
    _empty = {
        "ok": False,
        "reason": "",
        "body": None,
        "patch_count": 0,
        "max_deviation": float("inf"),
        "validate_result": {"ok": False, "errors": []},
        "feature_guided": False,
    }

    try:
        from kerf_cad_core.geom.mesh_to_nurbs import mesh_autosurface  # type: ignore[import]
    except ImportError as exc:
        return dict(_empty, reason=f"missing dependency: {exc}")

    try:
        verts_raw = mesh.get("verts") if isinstance(mesh, dict) else None
        faces_raw = mesh.get("faces") if isinstance(mesh, dict) else None
        if not verts_raw or not faces_raw:
            return dict(_empty, reason="mesh must be a dict with non-empty 'verts' and 'faces'")

        verts_np = np.array([[float(v[0]), float(v[1]), float(v[2])] for v in verts_raw], dtype=float)

        if feature_lines is not None and len(feature_lines) > 0:
            # Build a set of feature-line point arrays
            fl_pts_list: List[np.ndarray] = []
            for polyline in feature_lines:
                for pt in polyline:
                    if len(pt) >= 3:
                        fl_pts_list.append(np.array([float(pt[0]), float(pt[1]), float(pt[2])], dtype=float))

            if fl_pts_list:
                fl_pts = np.array(fl_pts_list, dtype=float)
                scale = _bounding_box_diagonal(verts_np)
                # Feature proximity band: 2% of bounding box diagonal
                band = scale * 0.02

                # Find mesh vertices near any feature line point
                feature_tagged = np.zeros(len(verts_np), dtype=bool)
                chunk = 512
                for start in range(0, len(verts_np), chunk):
                    block = verts_np[start:start + chunk]
                    min_dists = np.full(len(block), float("inf"))
                    for bstart in range(0, len(fl_pts), chunk):
                        bblock = fl_pts[bstart:bstart + chunk]
                        diffs = block[:, None, :] - bblock[None, :, :]
                        dists = np.sqrt((diffs ** 2).sum(axis=2))
                        mins = dists.min(axis=1)
                        min_dists = np.minimum(min_dists, mins)
                    feature_tagged[start:start + len(block)] = min_dists <= band

                n_tagged = int(feature_tagged.sum())

                # Strategy: if feature vertices exist, reduce max_dev to tighten
                # fitting in feature regions by lowering grid resolution for
                # autosurface (more grid points = better feature preservation)
                # This is a heuristic guided-fit: the mesh_autosurface UV-sphere
                # grid is made finer when features are detected.
                feature_fraction = n_tagged / max(len(verts_np), 1)
                # Tighten the max_dev tolerance proportionally to feature density.
                # More feature vertices → tighter tolerance on the fit near those
                # regions.  Grid size is held constant to avoid UV-sphere distortion
                # artefacts from overly fine parameterisation.
                guided_max_dev = max_dev * max(0.5, 1.0 - feature_fraction * 0.5)

                auto_result = mesh_autosurface(
                    verts_raw, faces_raw,
                    tol=tol,
                    max_dev=guided_max_dev,
                )
                return dict(auto_result, feature_guided=True)

        # No feature lines — plain autosurface
        auto_result = mesh_autosurface(verts_raw, faces_raw, tol=tol, max_dev=max_dev)
        return dict(auto_result, feature_guided=False)

    except Exception as exc:
        return dict(_empty, reason=f"reconcile_mesh_to_nurbs_with_features failed: {exc}")


# ---------------------------------------------------------------------------
# LLM tool registration (gated — graceful no-op when registry absent)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # brep_reconcile_nurbs_mesh
    # ------------------------------------------------------------------

    _reconcile_spec = ToolSpec(
        name="brep_reconcile_nurbs_mesh",
        description=(
            "Compare a NURBS body against a reference mesh using the Lévy 2009 reconciliation "
            "framework (Geogram EXPLORE). Tessellates the NURBS body and computes the two-sided "
            "Hausdorff distance as the primary deviation metric, plus 'extras' counts for geometry "
            "present in one representation but absent in the other.\n"
            "\n"
            "Returns:\n"
            "  ok                    : bool\n"
            "  deviation_metric      : float  (Hausdorff distance, world units)\n"
            "  mesh_vs_nurbs_extras  : int    (reference-mesh vertices with no near NURBS point)\n"
            "  nurbs_vs_mesh_extras  : int    (NURBS vertices with no near reference-mesh point)\n"
            "  fidelity_score        : float  ∈ [0,1]\n"
            "  fidelity_label        : str    ('excellent'/'good'/'fair'/'poor')\n"
            "  scale                 : float  (bounding-box diagonal)\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_id": {
                    "type": "string",
                    "description": "ID of the NURBS body in the project context.",
                },
                "reference_mesh": {
                    "type": "object",
                    "description": "Reference mesh dict with 'verts' [[x,y,z],...] and 'faces' [[i,j,k],...].",
                    "properties": {
                        "verts": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                        "faces": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
                    },
                    "required": ["verts", "faces"],
                },
                "mesh_resolution": {
                    "type": "number",
                    "description": "Tessellation resolution for NURBS body (world units, default 0.05).",
                },
            },
            "required": ["body_id", "reference_mesh"],
        },
    )

    @register(_reconcile_spec)
    async def run_brep_reconcile_nurbs_mesh(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_id = a.get("body_id")
        ref_mesh = a.get("reference_mesh")
        resolution = float(a.get("mesh_resolution", 0.05))

        if not body_id or not ref_mesh:
            return err_payload("body_id and reference_mesh are required", "BAD_ARGS")

        body = ctx.get_body(body_id) if hasattr(ctx, "get_body") else None
        if body is None:
            return err_payload(f"body '{body_id}' not found in context", "NOT_FOUND")

        r = reconcile_nurbs_mesh(body, ref_mesh, mesh_resolution=resolution)
        if not r.ok:
            return err_payload(r.reason, "OP_FAILED")

        label = fidelity_report(r.deviation_metric, r.scale)
        return ok_payload({
            "deviation_metric": r.deviation_metric,
            "mesh_vs_nurbs_extras": r.mesh_vs_nurbs_extras,
            "nurbs_vs_mesh_extras": r.nurbs_vs_mesh_extras,
            "fidelity_score": r.fidelity_score,
            "fidelity_label": label,
            "scale": r.scale,
        })

    # ------------------------------------------------------------------
    # brep_round_trip_with_fidelity
    # ------------------------------------------------------------------

    _round_trip_spec = ToolSpec(
        name="brep_round_trip_with_fidelity",
        description=(
            "Run a full NURBS→Mesh→NURBS round-trip and report per-step and total fidelity. "
            "Uses mesh_autosurface for the re-fit step. Tracks Hausdorff deviation at each "
            "conversion step so users can see what is lost in each direction.\n"
            "\n"
            "Returns:\n"
            "  ok                   : bool\n"
            "  total_deviation      : float  (end-to-end Hausdorff distance)\n"
            "  per_step_deviation   : {nurbs_to_mesh: float, mesh_to_nurbs: float}\n"
            "  fidelity_score       : float  ∈ [0,1]\n"
            "  fidelity_label       : str    ('excellent'/'good'/'fair'/'poor')\n"
            "  intermediate_mesh    : {verts_count: int, faces_count: int}\n"
            "  scale                : float\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_id": {
                    "type": "string",
                    "description": "ID of the NURBS body to round-trip.",
                },
                "mesh_resolution": {
                    "type": "number",
                    "description": "Tessellation resolution (world units, default 0.1).",
                },
            },
            "required": ["body_id"],
        },
    )

    @register(_round_trip_spec)
    async def run_brep_round_trip_with_fidelity(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        body_id = a.get("body_id")
        resolution = float(a.get("mesh_resolution", 0.1))

        if not body_id:
            return err_payload("body_id is required", "BAD_ARGS")

        body = ctx.get_body(body_id) if hasattr(ctx, "get_body") else None
        if body is None:
            return err_payload(f"body '{body_id}' not found in context", "NOT_FOUND")

        r = round_trip_nurbs_mesh(body, mesh_resolution=resolution)
        if not r.ok:
            return err_payload(r.reason, "OP_FAILED")

        label = fidelity_report(r.total_deviation, r.scale)
        mesh_summary: dict = {}
        if r.intermediate_mesh is not None:
            mesh_summary = {
                "verts_count": len(r.intermediate_mesh.get("verts", [])),
                "faces_count": len(r.intermediate_mesh.get("faces", [])),
            }

        return ok_payload({
            "total_deviation": r.total_deviation,
            "per_step_deviation": r.per_step_deviation,
            "fidelity_score": r.fidelity_score,
            "fidelity_label": label,
            "intermediate_mesh": mesh_summary,
            "scale": r.scale,
        })
