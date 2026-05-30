"""GK-P-IV: Interference volume metric for assembly clearance and collision severity.

Reference: Stroud-Nagy 2011 §10 (boolean intersection volume);
           Cazals-Loriot 2008 (analytic volume of convex body intersection).

Three methods are provided for computing the exact/approximate volume of
intersection between two B-rep bodies:

  * ``'boolean'`` — exact analytic volume using the existing body_intersection +
    body_mass_props pipeline (GK-18 + GK-23). Exact for axis-aligned bodies;
    sub-tol for curved faces. This is the preferred method when bodies have
    simple analytic geometry.

  * ``'monte_carlo'`` — Monte-Carlo sampling. Draws *n_samples* uniform random
    points from body_a's bounding box; estimates the intersection volume as::

        V_int ≈ V_bbox_a × (fraction_in_both / fraction_in_a)

    Actually implemented as: sample in bbox_a, count points inside both bodies.
    Volume estimate = V_bbox_a × (#in_both / n_samples).  Standard error
    σ ≈ V_bbox_a × sqrt(p(1−p)/n) where p is the estimated fraction.

  * ``'voxel'`` — voxelise both bodies on a shared grid; count voxels where
    both SDF values are ≤ 0. Resolution controlled by *voxel_resolution*.

Returns an :class:`InterferenceVolume` dataclass with volume, method,
std_error, and interference_severity (fraction of the smaller body's volume).

Pure-Python / NumPy — no OCCT dependency beyond what ``body_intersection``
already requires.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from kerf_cad_core.geom.brep import Body
from kerf_cad_core.geom.boolean import body_intersection
from kerf_cad_core.geom.mass_props import body_mass_props
from kerf_cad_core.geom.sdf import body_sdf, sdf_sample, _body_bbox
from kerf_cad_core.geom.sdf import _face_signed_distance


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class InterferenceVolume:
    """Result of a body-body interference volume computation.

    Attributes
    ----------
    volume:
        Estimated volume of intersection (≥ 0).
    interference_severity:
        Score in [0, 1]: 0 = no overlap, 1 = one body fully contained in the
        other.  Computed as ``volume / min(vol_a, vol_b)`` when volumes are
        available, else ``0.0``.
    method:
        One of ``'boolean'``, ``'monte_carlo'``, or ``'voxel'``.
    std_error:
        Standard error of the volume estimate.  For ``'boolean'`` this is 0.0
        (exact, up to floating-point rounding).  For ``'monte_carlo'`` it is
        the statistical standard error.  For ``'voxel'`` it is half a voxel
        volume (discretisation error bound).
    """

    volume: float
    interference_severity: float
    method: str
    std_error: float

    @property
    def interferes(self) -> bool:
        """True when the intersection volume exceeds a small tolerance (1e-12)."""
        return self.volume > 1e-12


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _body_volume(body: Body) -> float:
    """Return the absolute volume of *body* via mass props (0.0 on empty body)."""
    if not body.all_faces():
        return 0.0
    props = body_mass_props(body)
    return abs(props["volume"])


def _point_in_body(body: Body, point: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> bool:
    """Test whether *point* is inside *body*.

    Fast path: if the point is outside the body's bounding box [lo, hi], it
    is definitely outside.  Otherwise, evaluate the per-face signed distance
    exactly; the point is inside when the closest-face SDF value is negative.
    """
    # Bounding-box early exit (exact, free)
    if (point[0] < lo[0] or point[0] > hi[0] or
            point[1] < lo[1] or point[1] > hi[1] or
            point[2] < lo[2] or point[2] > hi[2]):
        return False

    # Direct per-face SDF evaluation (exact for analytic surfaces)
    faces = body.all_faces()
    if not faces:
        return False

    # Find the face with smallest absolute SDF value (closest boundary face).
    # Its signed value indicates inside (negative) vs outside (positive).
    min_abs = float("inf")
    min_signed = float("inf")
    for face in faces:
        try:
            d = _face_signed_distance(face, point)
        except Exception:
            continue
        if abs(d) < min_abs:
            min_abs = abs(d)
            min_signed = d

    return min_signed <= 0.0


def _bbox_from_vertices(body: Body):
    """Return (lo, hi) bounding box of *body* using face surface sampling.

    Uses :func:`~kerf_cad_core.geom.sdf._body_bbox` which samples parametric
    UV grids over each face surface — accurate for all surface types including
    spheres, cylinders, and tori where the B-rep vertex set does not span the
    full geometric extent (e.g., a sphere has only 2 pole vertices).

    A 2% pad is added to ensure bounding-box containment tests don't
    accidentally clip points on the surface boundary.
    """
    lo, hi = _body_bbox(body, n_uv=12)
    pad = np.maximum((hi - lo) * 0.02, 1e-6)
    return lo - pad, hi + pad


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def _compute_boolean(body_a: Body, body_b: Body) -> InterferenceVolume:
    """Boolean-exact interference volume via body_intersection + body_mass_props."""
    region = body_intersection(body_a, body_b)

    if not region.all_faces():
        return InterferenceVolume(
            volume=0.0,
            interference_severity=0.0,
            method="boolean",
            std_error=0.0,
        )

    props = body_mass_props(region)
    vol = abs(props["volume"])

    if vol < 1e-12:
        return InterferenceVolume(
            volume=0.0,
            interference_severity=0.0,
            method="boolean",
            std_error=0.0,
        )

    vol_a = _body_volume(body_a)
    vol_b = _body_volume(body_b)
    min_vol = min(vol_a, vol_b) if (vol_a > 0 and vol_b > 0) else 0.0
    severity = min(1.0, vol / min_vol) if min_vol > 1e-15 else 0.0

    return InterferenceVolume(
        volume=vol,
        interference_severity=severity,
        method="boolean",
        std_error=0.0,
    )


def _compute_monte_carlo(
    body_a: Body,
    body_b: Body,
    n_samples: int,
    rng: Optional[np.random.Generator] = None,
) -> InterferenceVolume:
    """Monte-Carlo interference volume (Stroud-Nagy §10 sampling approach).

    Algorithm
    ---------
    1. Compute body_a's and body_b's axis-aligned bounding boxes.
    2. Early exit: if the two bounding boxes do not overlap, the intersection
       is empty (return 0).
    3. Sample n_samples uniform random points inside body_a's bounding box.
    4. For each sample, test membership in both body_a and body_b using the
       exact per-face SDF sign (with bounding-box early-exit to skip points
       trivially outside body_b).
    5. Volume_intersection ≈ V_bbox_a × (#in_both / n_samples).
    6. Standard error = V_bbox_a × sqrt(p*(1-p)/n_samples)  (binomial SE).

    Using direct per-face SDF evaluation avoids SDF-grid clamping artefacts.
    """
    if rng is None:
        rng = np.random.default_rng(42)

    lo_a, hi_a = _bbox_from_vertices(body_a)
    lo_b, hi_b = _bbox_from_vertices(body_b)

    # Bounding-box disjointness: if bboxes don't overlap, no intersection.
    if np.any(lo_a > hi_b) or np.any(lo_b > hi_a):
        return InterferenceVolume(
            volume=0.0,
            interference_severity=0.0,
            method="monte_carlo",
            std_error=0.0,
        )

    bbox_dims = hi_a - lo_a
    bbox_volume = float(np.prod(bbox_dims))

    if bbox_volume < 1e-30:
        return InterferenceVolume(
            volume=0.0,
            interference_severity=0.0,
            method="monte_carlo",
            std_error=0.0,
        )

    # Sample points uniformly in body_a's bounding box
    samples = rng.uniform(low=lo_a, high=hi_a, size=(n_samples, 3))

    n_in_both = 0
    for pt in samples:
        in_a = _point_in_body(body_a, pt, lo_a, hi_a)
        if in_a:
            in_b = _point_in_body(body_b, pt, lo_b, hi_b)
            if in_b:
                n_in_both += 1

    p_hat = n_in_both / n_samples  # fraction in both (relative to bbox_a)

    vol = bbox_volume * p_hat
    # Standard error of the proportion estimate, scaled to volume
    se = bbox_volume * math.sqrt(max(p_hat * (1.0 - p_hat), 0.0) / n_samples)

    # Severity: use boolean volumes when possible
    vol_a = _body_volume(body_a)
    vol_b = _body_volume(body_b)
    min_vol = min(vol_a, vol_b) if (vol_a > 0 and vol_b > 0) else 0.0
    severity = min(1.0, vol / min_vol) if min_vol > 1e-15 else 0.0

    return InterferenceVolume(
        volume=vol,
        interference_severity=severity,
        method="monte_carlo",
        std_error=se,
    )


def _compute_voxel(
    body_a: Body,
    body_b: Body,
    voxel_resolution: int = 32,
) -> InterferenceVolume:
    """Voxel-based interference volume.

    Algorithm
    ---------
    1. Compute the intersection bounding box of both bodies (the region that
       could possibly contain overlap).
    2. If bounding boxes are disjoint, return 0.
    3. Grid the intersection region at *voxel_resolution* per axis.
    4. For each voxel centre, test membership in both bodies using the exact
       per-face SDF (with bounding-box early exit).
    5. Volume_intersection ≈ n_overlap × voxel_volume.
    6. Standard error = 0.5 × voxel_volume (one-half voxel discretisation bound).
    """
    lo_a, hi_a = _bbox_from_vertices(body_a)
    lo_b, hi_b = _bbox_from_vertices(body_b)

    # Intersection bounding box (tightest possible region)
    lo = np.maximum(lo_a, lo_b)
    hi = np.minimum(hi_a, hi_b)

    # Bounding-box disjointness: if intersection bbox is empty, no overlap
    if np.any(lo >= hi):
        return InterferenceVolume(
            volume=0.0,
            interference_severity=0.0,
            method="voxel",
            std_error=0.0,
        )

    nx = ny = nz = voxel_resolution
    xs = np.linspace(lo[0], hi[0], nx + 1)[:-1] + (hi[0] - lo[0]) / (2 * nx)
    ys = np.linspace(lo[1], hi[1], ny + 1)[:-1] + (hi[1] - lo[1]) / (2 * ny)
    zs = np.linspace(lo[2], hi[2], nz + 1)[:-1] + (hi[2] - lo[2]) / (2 * nz)

    voxel_volume = float(
        ((hi[0] - lo[0]) / nx) *
        ((hi[1] - lo[1]) / ny) *
        ((hi[2] - lo[2]) / nz)
    )

    # All voxel centres within [lo, hi] are already inside both bboxes,
    # so we only need the per-face SDF check (no bbox early-exit needed here).
    n_overlap = 0
    faces_a = body_a.all_faces()
    faces_b = body_b.all_faces()

    for x in xs:
        for y in ys:
            for z in zs:
                pt = np.array([x, y, z], dtype=float)
                # Check body_a
                in_a = _in_faces(faces_a, pt)
                if in_a and _in_faces(faces_b, pt):
                    n_overlap += 1

    vol = n_overlap * voxel_volume
    se = 0.5 * voxel_volume  # half-voxel discretisation error

    vol_a = _body_volume(body_a)
    vol_b = _body_volume(body_b)
    min_vol = min(vol_a, vol_b) if (vol_a > 0 and vol_b > 0) else 0.0
    severity = min(1.0, vol / min_vol) if min_vol > 1e-15 else 0.0

    return InterferenceVolume(
        volume=vol,
        interference_severity=severity,
        method="voxel",
        std_error=se,
    )


def _in_faces(faces: list, point: np.ndarray) -> bool:
    """Return True if *point* is inside the closed solid described by *faces*.

    Uses the closest-face SDF sign (negative = inside).
    """
    if not faces:
        return False
    min_abs = float("inf")
    min_signed = float("inf")
    for face in faces:
        try:
            d = _face_signed_distance(face, point)
        except Exception:
            continue
        if abs(d) < min_abs:
            min_abs = abs(d)
            min_signed = d
    return min_signed <= 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_interference_volume(
    body_a: Body,
    body_b: Body,
    method: str = "monte_carlo",
    n_samples: int = 10000,
    voxel_resolution: int = 32,
    rng: Optional[np.random.Generator] = None,
) -> InterferenceVolume:
    """Compute the volume of the intersection between two B-rep bodies.

    Parameters
    ----------
    body_a, body_b:
        The two :class:`~kerf_cad_core.geom.brep.Body` objects.
    method:
        Computation strategy:

        ``'boolean'`` (exact, analytic)
            Use the existing :func:`body_intersection` + :func:`body_mass_props`
            pipeline (GK-18/GK-23).  Exact for axis-aligned analytic bodies.
            Recommended default when exact results are needed.

        ``'monte_carlo'`` (statistical)
            Monte-Carlo sampling of body_a's bounding box.  Unbiased for any
            body shape.  Accuracy improves as O(1/√n_samples).  Default.

        ``'voxel'`` (discretised)
            Voxelise both bodies and count overlapping voxels.  Accuracy
            proportional to *voxel_resolution*³.

    n_samples:
        Number of random samples for ``'monte_carlo'``.  Default 10 000.
        Larger values reduce std_error proportional to 1/√n.
    voxel_resolution:
        Grid resolution per axis for ``'voxel'``.  Default 32 (→ 32³ voxels).
    rng:
        Optional seeded :class:`numpy.random.Generator` for reproducibility.

    Returns
    -------
    :class:`InterferenceVolume`
        Contains ``volume``, ``interference_severity``, ``method``,
        ``std_error``.

    Notes
    -----
    * Reference: Stroud-Nagy 2011 §10 (boolean intersection volume);
      Cazals-Loriot 2008 (analytic convex intersection volume).
    * For high-accuracy results with complex NURBS bodies, use
      ``method='boolean'`` or increase ``n_samples`` / ``voxel_resolution``.
    * ``interference_severity = volume / min(vol_a, vol_b)``, clamped to [0, 1].
      Score of 1.0 means one body is fully enclosed in the other.
    """
    if method == "boolean":
        return _compute_boolean(body_a, body_b)
    elif method == "monte_carlo":
        return _compute_monte_carlo(body_a, body_b, n_samples=n_samples, rng=rng)
    elif method == "voxel":
        return _compute_voxel(body_a, body_b, voxel_resolution=voxel_resolution)
    else:
        raise ValueError(
            f"Unknown method {method!r}; must be one of 'boolean', 'monte_carlo', 'voxel'"
        )


def interference_severity_score(
    body_a: Body,
    body_b: Body,
    method: str = "boolean",
    max_acceptable_volume: Optional[float] = None,
    n_samples: int = 10000,
    rng: Optional[np.random.Generator] = None,
) -> dict:
    """Compute a normalised interference severity score for two bodies.

    The score is ``volume_of_intersection / min(volume_a, volume_b)``:

    * 0.0 — no overlap (bodies are disjoint or merely touching).
    * 1.0 — one body is fully inside the other (100% overlap).

    Parameters
    ----------
    body_a, body_b:
        The two :class:`~kerf_cad_core.geom.brep.Body` objects to compare.
    method:
        Passed to :func:`compute_interference_volume`.  Defaults to
        ``'boolean'`` for exact scores.
    max_acceptable_volume:
        Optional design-intent threshold.  If provided, the result will
        contain ``"acceptable": True/False``.
    n_samples:
        Sample count (``'monte_carlo'`` method only).
    rng:
        Optional seeded RNG for reproducibility.

    Returns
    -------
    dict with keys:

    ``"score"``
        Normalised severity in [0, 1].
    ``"volume"``
        Raw intersection volume.
    ``"volume_a"``
        Volume of body_a.
    ``"volume_b"``
        Volume of body_b.
    ``"min_body_volume"``
        ``min(vol_a, vol_b)`` — the denominator of the severity ratio.
    ``"method"``
        The method used.
    ``"interferes"``
        ``True`` when volume > 0.
    ``"acceptable"``
        Only present when *max_acceptable_volume* is provided.
    """
    result = compute_interference_volume(
        body_a, body_b, method=method, n_samples=n_samples, rng=rng
    )

    vol_a = _body_volume(body_a)
    vol_b = _body_volume(body_b)
    min_vol = min(vol_a, vol_b) if (vol_a > 0 and vol_b > 0) else 0.0

    out: dict = {
        "score": result.interference_severity,
        "volume": result.volume,
        "volume_a": vol_a,
        "volume_b": vol_b,
        "min_body_volume": min_vol,
        "method": result.method,
        "interferes": result.volume > 1e-12,
    }

    if max_acceptable_volume is not None:
        out["acceptable"] = result.volume <= max_acceptable_volume

    return out


def pairwise_interference_assembly(
    bodies: List[Body],
    method: str = "monte_carlo",
    n_samples: int = 10000,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Compute the all-pairs interference volume matrix for an assembly.

    Parameters
    ----------
    bodies:
        List of N :class:`~kerf_cad_core.geom.brep.Body` objects.
    method:
        Computation method (``'boolean'``, ``'monte_carlo'``, or ``'voxel'``).
        Default ``'monte_carlo'``.
    n_samples:
        Sample count per pair (``'monte_carlo'`` only).
    rng:
        Optional seeded :class:`numpy.random.Generator`.  If provided, the
        same generator is used for all pairs (sequence reproducible).

    Returns
    -------
    numpy.ndarray of shape (N, N), dtype float64.
        Entry [i, j] is the interference volume between bodies[i] and
        bodies[j].  The matrix is symmetric with 0.0 on the diagonal
        (self-intersection is not computed).

    Notes
    -----
    * The upper triangle is computed; the lower is filled by symmetry.
    * All-pairs complexity: O(N²/2) interference-volume calls.
    * For large assemblies (N > 20) consider ``method='boolean'`` for speed
      or pre-filtering with :func:`~kerf_cad_core.geom.assembly.clearance` to
      skip clearly disjoint pairs.
    """
    n = len(bodies)
    matrix = np.zeros((n, n), dtype=float)

    for i in range(n):
        for j in range(i + 1, n):
            result = compute_interference_volume(
                bodies[i], bodies[j],
                method=method,
                n_samples=n_samples,
                rng=rng,
            )
            matrix[i, j] = result.volume
            matrix[j, i] = result.volume

    return matrix
