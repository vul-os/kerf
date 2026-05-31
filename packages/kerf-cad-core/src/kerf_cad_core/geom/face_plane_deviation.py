"""face_plane_deviation.py — BREP-FACE-PLANE-DEVIATION

Given a pre-sampled B-rep face (intended-planar or actual-NURBS surface)
expressed as a list of ``FaceSamplePoint`` objects, compute the max and RMS
deviation of those points from the algebraically best-fit plane (least-squares
orthogonal regression).  Returns a ``FacePlaneDeviationReport`` with:

  * the fitted ``PlaneFit`` (origin, unit normal, scalar d where n·p = d)
  * ``max_deviation_mm`` — worst-case perpendicular distance
  * ``rms_deviation_mm`` — root-mean-square perpendicular distance
  * ``is_planar``        — True if max_deviation < tolerance_mm
  * ``classification``   — "planar" | "near-planar" | "curved" | "highly-curved"
  * ``honest_caveat``    — hard disclaimer about algorithm limits

Algorithm
---------
1. Stack the N×3 sample matrix P.
2. Compute centroid c = mean(P, axis=0).
3. Centre: A = P − c.
4. Thin SVD: A = U Σ Vᵀ.  The column of V corresponding to the smallest
   singular value is the best-fit plane normal n̂ (Pratt 1987 §3; Eberly,
   "Geometric Tools for Computer Graphics" §6.6).
5. Plane equation: n̂·p = d, where d = n̂·c.
6. Signed deviations: dᵢ = n̂·pᵢ − d.
7. max_deviation = max|dᵢ|; rms_deviation = √(mean(dᵢ²)).

Classification thresholds (relative to tolerance_mm t):
  |max_dev| < t           → planar
  |max_dev| < 10·t        → near-planar
  |max_dev| < 100·t       → curved
  else                    → highly-curved

HONEST CAVEATS
--------------
1. **Least-squares fit only** — no robust outlier rejection (RANSAC / LMedS).
   A single far outlier inflates max_deviation and can tilt the normal.
   For noisy STEP imports consider pre-filtering obvious outlier points.
2. **Degenerate input** — fewer than 3 non-collinear points leaves the normal
   direction underdetermined; the function raises ``ValueError`` in that case.
3. **Sampling density** — quality depends entirely on the caller's sample grid.
   This module does NOT resample the underlying surface; it accepts whatever
   points are provided.
4. **Units** — all coordinates and tolerances are assumed to be in mm; no
   unit conversion is performed.

References
----------
Pratt, V. (1987). Direct least-squares fitting of algebraic surfaces.
    SIGGRAPH Computer Graphics, 21(4), 145–152.
Eberly, D. (2020). Geometric Tools for Computer Graphics, §6.6
    "Fitting a Plane to a Point Set (Orthogonal Regression)".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

__all__ = [
    "FaceSamplePoint",
    "PlaneFit",
    "FacePlaneDeviationReport",
    "compute_face_plane_deviation",
]

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FaceSamplePoint:
    """A single 3-D sample point on a B-rep face (in model mm coordinates)."""

    x_mm: float
    y_mm: float
    z_mm: float


@dataclass
class PlaneFit:
    """Best-fit plane returned by :func:`compute_face_plane_deviation`.

    The plane equation is ``normal_xyz · p = d``  (dot product).

    Attributes
    ----------
    origin_xyz_mm:
        A point on the plane (the centroid of the sample set).
    normal_xyz:
        Unit outward normal of the best-fit plane (smallest singular vector).
    d:
        Scalar such that ``n̂ · p = d`` for any point p on the plane.
        Equivalently ``d = n̂ · origin``.
    """

    origin_xyz_mm: Tuple[float, float, float]
    normal_xyz: Tuple[float, float, float]
    d: float


@dataclass
class FacePlaneDeviationReport:
    """Result of :func:`compute_face_plane_deviation`.

    Attributes
    ----------
    plane:
        Best-fit plane (origin, unit normal, scalar d).
    max_deviation_mm:
        Maximum absolute perpendicular distance from any sample point to the
        best-fit plane (mm).
    rms_deviation_mm:
        Root-mean-square perpendicular distance (mm).
    num_samples:
        Number of sample points used.
    is_planar:
        True if ``max_deviation_mm < tolerance_mm``.
    classification:
        One of ``"planar"``, ``"near-planar"``, ``"curved"``, or
        ``"highly-curved"`` based on the ratio max_dev / tolerance.
    honest_caveat:
        Human-readable caveat string describing algorithmic limits.
    """

    plane: PlaneFit
    max_deviation_mm: float
    rms_deviation_mm: float
    num_samples: int
    is_planar: bool
    classification: str  # "planar" | "near-planar" | "curved" | "highly-curved"
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Least-squares SVD plane fit; no robust outlier rejection — a single "
    "far outlier can tilt the normal and inflate max_deviation. "
    "Sampling density is caller-controlled; this function does NOT resample "
    "the underlying surface. Fewer than 3 non-collinear points raises "
    "ValueError. Classification thresholds are relative to tolerance_mm."
)


def _collinearity_check(pts: list) -> bool:
    """Return True if all points are (approximately) collinear.

    Uses the cross-product of the first two span vectors; if the longest
    has magnitude < 1e-14 in all combinations the set is collinear.
    """
    n = len(pts)
    # anchor on pts[0]
    p0 = pts[0]
    max_cross = 0.0
    for i in range(1, n - 1):
        dx1 = pts[i][0] - p0[0]
        dy1 = pts[i][1] - p0[1]
        dz1 = pts[i][2] - p0[2]
        for j in range(i + 1, n):
            dx2 = pts[j][0] - p0[0]
            dy2 = pts[j][1] - p0[1]
            dz2 = pts[j][2] - p0[2]
            cx = dy1 * dz2 - dz1 * dy2
            cy = dz1 * dx2 - dx1 * dz2
            cz = dx1 * dy2 - dy1 * dx2
            mag = math.sqrt(cx * cx + cy * cy + cz * cz)
            if mag > max_cross:
                max_cross = mag
    return max_cross < 1e-10


def _svd_3x3_sym(a: list) -> tuple:
    """Minimal thin SVD of an N×3 centred matrix via the 3×3 covariance AᵀA.

    Returns (singular_values, V) where V columns are right singular vectors
    sorted in descending order of singular value.  Uses numpy if available;
    falls back to a pure-Python Jacobi iteration for the 3×3 symmetric case.
    """
    try:
        import numpy as np  # type: ignore[import]
        A = np.array(a, dtype=float)
        # Full thin SVD
        _, s, Vt = np.linalg.svd(A, full_matrices=False)
        # Columns of V = rows of Vt; last row → smallest singular value
        V = Vt.T  # shape (3, 3)
        return list(s), V
    except ImportError:
        pass

    # Pure-Python fallback: compute 3×3 symmetric matrix C = AᵀA,
    # then find eigenvalues/vectors via Jacobi iteration.
    n = len(a)
    # C[i][j] = sum_k A[k][i] * A[k][j]
    C = [[0.0] * 3 for _ in range(3)]
    for row in a:
        for i in range(3):
            for j in range(3):
                C[i][j] += row[i] * row[j]

    # Jacobi eigendecomposition (symmetric 3×3, always converges)
    import copy
    V_mat = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    M = copy.deepcopy(C)
    for _ in range(100):
        # Find off-diagonal entry with largest absolute value
        p, q, max_val = 0, 1, abs(M[0][1])
        for ii in range(3):
            for jj in range(ii + 1, 3):
                if abs(M[ii][jj]) > max_val:
                    max_val = abs(M[ii][jj])
                    p, q = ii, jj
        if max_val < 1e-15:
            break
        # Compute Jacobi rotation angle
        theta = 0.5 * math.atan2(2.0 * M[p][q], M[q][q] - M[p][p])
        c = math.cos(theta)
        s = math.sin(theta)
        # Apply rotation to M
        M_new = copy.deepcopy(M)
        for i in range(3):
            if i != p and i != q:
                M_new[i][p] = c * M[i][p] + s * M[i][q]
                M_new[p][i] = M_new[i][p]
                M_new[i][q] = -s * M[i][p] + c * M[i][q]
                M_new[q][i] = M_new[i][q]
        M_new[p][p] = c * c * M[p][p] + 2 * s * c * M[p][q] + s * s * M[q][q]
        M_new[q][q] = s * s * M[p][p] - 2 * s * c * M[p][q] + c * c * M[q][q]
        M_new[p][q] = 0.0
        M_new[q][p] = 0.0
        # Apply rotation to V
        for i in range(3):
            vp = V_mat[i][p]
            vq = V_mat[i][q]
            V_mat[i][p] = c * vp + s * vq
            V_mat[i][q] = -s * vp + c * vq
        M = M_new

    eigenvalues = [M[i][i] for i in range(3)]
    # Sort descending by eigenvalue (eigenvalue = sigma²)
    order = sorted(range(3), key=lambda k: -eigenvalues[k])
    sorted_sv = [math.sqrt(max(0.0, eigenvalues[order[k]])) for k in range(3)]
    # V columns = eigenvectors; V_mat[row][col] — columns of V_mat are eigenvectors
    # since we accumulated rotations in V_mat column-wise
    V_sorted = [[V_mat[row][order[k]] for k in range(3)] for row in range(3)]
    return sorted_sv, V_sorted


def compute_face_plane_deviation(
    samples: List[FaceSamplePoint],
    tolerance_mm: float = 0.01,
) -> FacePlaneDeviationReport:
    """Compute max/RMS deviation of sample points from their best-fit plane.

    Parameters
    ----------
    samples:
        List of :class:`FaceSamplePoint` objects.  Must contain at least 3
        non-collinear points.
    tolerance_mm:
        Threshold for planarity classification (default 0.01 mm).

    Returns
    -------
    FacePlaneDeviationReport

    Raises
    ------
    ValueError
        If ``samples`` has fewer than 3 points or all points are collinear
        (plane normal is underdetermined).
    """
    if len(samples) < 3:
        raise ValueError(
            f"compute_face_plane_deviation requires at least 3 sample points; "
            f"got {len(samples)}."
        )

    # Build coordinate list
    pts = [(s.x_mm, s.y_mm, s.z_mm) for s in samples]

    if _collinearity_check(pts):
        raise ValueError(
            "All sample points are collinear — the best-fit plane normal is "
            "underdetermined.  Provide at least 3 non-collinear points."
        )

    n = len(pts)

    # Centroid
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    cz = sum(p[2] for p in pts) / n

    # Centred matrix
    centred = [(p[0] - cx, p[1] - cy, p[2] - cz) for p in pts]

    # SVD / eigendecomposition
    sv, V = _svd_3x3_sym(centred)

    # Smallest singular value → last column of V
    try:
        import numpy as np  # type: ignore[import]
        # V is a numpy array; last column = V[:, 2]
        normal = (float(V[0, 2]), float(V[1, 2]), float(V[2, 2]))
    except (ImportError, TypeError):
        # V is a list-of-lists; columns indexed as V[row][col]
        normal = (float(V[0][2]), float(V[1][2]), float(V[2][2]))

    # Normalise (should already be unit but guard against numerical drift)
    mag = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
    if mag < 1e-15:
        raise ValueError("SVD produced a zero-length normal vector.")
    normal = (normal[0] / mag, normal[1] / mag, normal[2] / mag)

    # Plane equation: n·p = d
    d = normal[0] * cx + normal[1] * cy + normal[2] * cz

    # Perpendicular distances
    devs = [abs(normal[0] * p[0] + normal[1] * p[1] + normal[2] * p[2] - d)
            for p in pts]

    max_dev = max(devs)
    rms_dev = math.sqrt(sum(di * di for di in devs) / n)

    # Classification
    if max_dev < tolerance_mm:
        cls = "planar"
    elif max_dev < 10.0 * tolerance_mm:
        cls = "near-planar"
    elif max_dev < 100.0 * tolerance_mm:
        cls = "curved"
    else:
        cls = "highly-curved"

    plane = PlaneFit(
        origin_xyz_mm=(cx, cy, cz),
        normal_xyz=normal,
        d=d,
    )

    return FacePlaneDeviationReport(
        plane=plane,
        max_deviation_mm=max_dev,
        rms_deviation_mm=rms_dev,
        num_samples=n,
        is_planar=(max_dev < tolerance_mm),
        classification=cls,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated — only when kerf_chat is installed)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


_SAMPLES_SCHEMA = {
    "type": "array",
    "description": (
        "List of 3-D sample points on the B-rep face (in mm). "
        "Each item is an object with 'x_mm', 'y_mm', 'z_mm' numeric fields. "
        "Minimum 3 non-collinear points required."
    ),
    "items": {
        "type": "object",
        "properties": {
            "x_mm": {"type": "number"},
            "y_mm": {"type": "number"},
            "z_mm": {"type": "number"},
        },
        "required": ["x_mm", "y_mm", "z_mm"],
    },
}

if _REGISTRY_AVAILABLE:

    _planarity_spec = ToolSpec(
        name="geom_check_face_planarity",
        description=(
            "Given a list of pre-sampled 3-D points on a B-rep face, fit the "
            "best-fit plane (least-squares SVD orthogonal regression; Pratt 1987 §3; "
            "Eberly §6.6) and return max/RMS perpendicular deviation, planarity "
            "classification, and the plane equation (n·p = d).\n\n"
            "Classification thresholds (relative to tolerance_mm t):\n"
            "  • max_dev < t        → planar\n"
            "  • max_dev < 10·t     → near-planar\n"
            "  • max_dev < 100·t    → curved\n"
            "  • max_dev ≥ 100·t    → highly-curved\n\n"
            "Use cases: STEP/IGES import validation, surface flatness QC, "
            "sheet-metal flat-pattern feasibility, machined-face quality.\n\n"
            "HONEST: least-squares only — no outlier rejection. "
            "Caller controls sampling density. "
            "Returns: {ok, plane_origin, plane_normal, d, max_deviation_mm, "
            "rms_deviation_mm, num_samples, is_planar, classification, honest_caveat}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "samples": _SAMPLES_SCHEMA,
                "tolerance_mm": {
                    "type": "number",
                    "description": (
                        "Planarity tolerance in mm (default 0.01). "
                        "max_deviation < tolerance_mm → classified as 'planar'."
                    ),
                },
            },
            "required": ["samples"],
        },
    )

    @register(_planarity_spec)
    async def run_geom_check_face_planarity(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        raw_samples = a.get("samples")
        if raw_samples is None:
            return err_payload("'samples' is required", "BAD_ARGS")
        if not isinstance(raw_samples, list):
            return err_payload("'samples' must be a JSON array", "BAD_ARGS")

        try:
            pts = [
                FaceSamplePoint(
                    x_mm=float(s["x_mm"]),
                    y_mm=float(s["y_mm"]),
                    z_mm=float(s["z_mm"]),
                )
                for s in raw_samples
            ]
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"malformed sample point: {exc}", "BAD_ARGS")

        tol = float(a.get("tolerance_mm", 0.01))

        try:
            report = compute_face_plane_deviation(pts, tolerance_mm=tol)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "plane_origin": list(report.plane.origin_xyz_mm),
            "plane_normal": list(report.plane.normal_xyz),
            "d": report.plane.d,
            "max_deviation_mm": report.max_deviation_mm,
            "rms_deviation_mm": report.rms_deviation_mm,
            "num_samples": report.num_samples,
            "is_planar": report.is_planar,
            "classification": report.classification,
            "honest_caveat": report.honest_caveat,
        })
