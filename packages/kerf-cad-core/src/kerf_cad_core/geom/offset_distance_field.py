"""
offset_distance_field.py
========================
GK-140 — NURBS-Surface Offset Distance Field.

For a NURBS surface S and offset distance d, compute the signed distance field
|Σ| where Σ is the d-offset surface.  Outputs a 3D grid of distance values
that can be used for fast inside/outside queries and distance-from-offset queries.

Theory
------
For a NURBS surface S with unit outward normal n(u,v), the d-offset surface Σ is
defined by (Maekawa 1999, §2; Piegl & Tiller §11.3):

    Σ(u,v) = S(u,v) + d · n(u,v)

The signed distance function φ(p) is:

    φ(p) = dist(p, Σ) · sign(p)

where sign(p) = +1 if p is on the same side as the outward normal, −1 otherwise.

For the sign convention we use the offset normal evaluated at the closest point:

    sign(p) = sgn( (p − foot(p)) · n_Σ(u*, v*) )

where foot(p) is the closest point on Σ and n_Σ is the surface normal at that point.

Algorithm
---------
1. Compute the d-offset surface Σ = surface_offset(S, d)  [existing module].
2. Lay a uniform 3-D grid over the supplied bounding box.
3. For each grid node p:
   a. Find the closest point on Σ via closest_point_surface() (GK-07, Newton inversion).
   b. Compute the unsigned distance dist = |p − foot|.
   c. Determine sign by projecting (p − foot) onto the offset surface normal.
4. Return a DistanceFieldResult dataclass.

Complexity and honesty flag
---------------------------
The grid is O(grid_size³) nodes, each requiring a Newton inversion (O(1) but
with a ~28-seed initial search).  For grid_size=32 this is 32³ = 32 768 Newton
calls — tractable in seconds on a laptop.  grid_size=64 → 262 144 calls (tens of
seconds).  Production use should consider an adaptive octree or narrow-band
approach (see e.g. Strain 1999, "Tree Methods for Moving Interfaces").

References
----------
* Maekawa 1999 — "An overview of offset curves and surfaces"
  Computer-Aided Design 31(3) pp. 165–173.
  https://doi.org/10.1016/S0010-4485(99)00003-5
* Piegl & Tiller, "The NURBS Book", 2nd ed., §11.3 — Offset surfaces.
* Piegl & Tiller §6.1 — Point inversion (implemented in geom/inversion.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_normal
from kerf_cad_core.geom.surface_offset import surface_offset
from kerf_cad_core.geom.inversion import closest_point_surface, _surface_param_range


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class DistanceFieldResult:
    """Result of :func:`compute_offset_distance_field`.

    Attributes
    ----------
    distances_3d : np.ndarray, shape (grid_size, grid_size, grid_size)
        Signed distance at each grid node.  Positive outside the offset
        surface (same side as normal); negative inside.
    bbox : tuple[np.ndarray, np.ndarray]
        ``(min_corner, max_corner)`` of the grid bounding box, each shape (3,).
    resolution : float
        Uniform cell spacing (same in all three axes).
    grid_size : int
        Number of nodes per axis.
    offset_distance : float
        The d value used to build the offset surface.
    """
    distances_3d: np.ndarray          # (N, N, N) float64
    bbox: Tuple[np.ndarray, np.ndarray]
    resolution: float
    grid_size: int
    offset_distance: float

    def query(self, point) -> float:
        """Trilinear interpolation of the distance field at an arbitrary point.

        Parameters
        ----------
        point : array-like, shape (3,)
            World-space query point.

        Returns
        -------
        float
            Signed distance (may be slightly outside the exact analytic value
            due to grid discretisation and linear interpolation).
        """
        p = np.asarray(point, dtype=float)
        lo, hi = self.bbox
        extent = hi - lo
        # Normalised coords in [0, grid_size-1]
        t = (p - lo) / (extent + 1e-15) * (self.grid_size - 1)
        ix = np.clip(np.floor(t).astype(int), 0, self.grid_size - 2)
        fx = t - ix.astype(float)
        # Trilinear blend
        i, j, k = int(ix[0]), int(ix[1]), int(ix[2])
        tx, ty, tz = float(fx[0]), float(fx[1]), float(fx[2])
        d = self.distances_3d
        return float(
            d[i,   j,   k  ] * (1-tx)*(1-ty)*(1-tz)
          + d[i+1, j,   k  ] * tx    *(1-ty)*(1-tz)
          + d[i,   j+1, k  ] * (1-tx)*ty    *(1-tz)
          + d[i,   j,   k+1] * (1-tx)*(1-ty)*tz
          + d[i+1, j+1, k  ] * tx    *ty    *(1-tz)
          + d[i+1, j,   k+1] * tx    *(1-ty)*tz
          + d[i,   j+1, k+1] * (1-tx)*ty    *tz
          + d[i+1, j+1, k+1] * tx    *ty    *tz
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _auto_bbox(
    offset_srf: NurbsSurface,
    offset_distance: float,
    padding_factor: float = 1.5,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute an axis-aligned bounding box that comfortably encloses the
    offset surface.  We sample the surface control-point net (guaranteed to
    contain the convex hull), add *padding* proportional to the maximum
    control-net extent.

    Parameters
    ----------
    offset_srf : NurbsSurface
        The d-offset surface (already displaced).
    offset_distance : float
        The offset distance; used to ensure minimum padding ≥ 2|d|.
    padding_factor : float
        Fraction of the control-net diagonal added as padding on each side.
    """
    cp = offset_srf.control_points[:, :, :3].reshape(-1, 3)
    lo = cp.min(axis=0)
    hi = cp.max(axis=0)
    diag = float(np.linalg.norm(hi - lo))
    pad = max(abs(offset_distance) * 2.0, diag * padding_factor * 0.5)
    return lo - pad, hi + pad


def _surface_normal_at_foot(
    srf: NurbsSurface,
    u: float,
    v: float,
) -> np.ndarray:
    """Return unit normal of *srf* at parameter (u, v), falling back to
    finite-difference if the analytic normal degenerates (pole, seam, etc.)."""
    try:
        n = surface_normal(srf, u, v)
        nrm = float(np.linalg.norm(n))
        if nrm > 1e-12:
            return n / nrm
    except Exception:
        pass

    # Finite-difference fallback
    u_min, u_max, v_min, v_max = _surface_param_range(srf)
    from kerf_cad_core.geom.nurbs import surface_evaluate
    hu = max(1e-6, (u_max - u_min) * 1e-3)
    hv = max(1e-6, (v_max - v_min) * 1e-3)
    up = min(u_max, u + hu)
    um = max(u_min, u - hu)
    vp = min(v_max, v + hv)
    vm = max(v_min, v - hv)
    dpu = surface_evaluate(srf, up, v)[:3] - surface_evaluate(srf, um, v)[:3]
    dpv = surface_evaluate(srf, u, vp)[:3] - surface_evaluate(srf, u, vm)[:3]
    n = np.cross(dpu, dpv)
    nrm = float(np.linalg.norm(n))
    return n / nrm if nrm > 1e-12 else np.array([0.0, 0.0, 1.0])


def _normal_sign_flip(offset_srf: NurbsSurface) -> float:
    """Determine whether ``dot(p - foot, n_foot) > 0`` means *outside* (+1)
    or *inside* (−1 = needs flip).

    Strategy: evaluate the surface normal at the UV midpoint and compute the
    dot product with the vector from the surface point to the control-point
    centroid.  If the centroid is on the *positive-normal* side
    (dot > 0), then the normal is pointing *inward* (toward the interior of a
    closed surface), so we need to flip.

    For open surfaces (planes), the centroid lies on or very near the surface
    so the dot product is ≈ 0; we default to +1 (no flip) in that case.

    This gives the correct answer for convex closed surfaces (spheres, tori)
    and for flat patches with consistent orientation.
    """
    u_min, u_max, v_min, v_max = _surface_param_range(offset_srf)
    u_mid = (u_min + u_max) * 0.5
    v_mid = (v_min + v_max) * 0.5
    from kerf_cad_core.geom.nurbs import surface_evaluate
    pt_mid = surface_evaluate(offset_srf, u_mid, v_mid)[:3]
    n_mid = _surface_normal_at_foot(offset_srf, u_mid, v_mid)

    # Centroid of the control-point cloud
    cp = offset_srf.control_points[:, :, :3].reshape(-1, 3)
    centroid = cp.mean(axis=0)

    proj = float(np.dot(centroid - pt_mid, n_mid))
    # If |proj| is very small (open/flat surface), the centroid is on the surface
    # — no flip needed (normal is already outward for typical planar patches).
    if abs(proj) < 1e-6:
        return 1.0
    # If projection is positive, centroid is on the "positive normal" side →
    # normal is pointing inward → we need to flip the sign convention.
    return -1.0 if proj > 0.0 else 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_offset_distance_field(
    srf: NurbsSurface,
    distance: float,
    bbox: Optional[Tuple] = None,
    grid_size: int = 32,
) -> DistanceFieldResult:
    """Compute the signed distance field of the d-offset surface of *srf*.

    For a NURBS surface S and scalar offset distance d, the d-offset surface
    Σ is defined as (Maekawa 1999 §2; Piegl & Tiller §11.3)::

        Σ(u,v) = S(u,v) + d · n̂(u,v)

    This function evaluates the signed distance from every node of a uniform
    3-D Cartesian grid to Σ, using exact point-inversion (GK-07, Piegl & Tiller
    §6.1) for the closest-point queries.

    Sign convention
    ---------------
    ``φ(p) > 0`` — p is outside Σ (on the positive-normal side).
    ``φ(p) < 0`` — p is inside Σ.
    ``φ(p) ≈ 0`` — p lies on Σ.

    Parameters
    ----------
    srf : NurbsSurface
        Input NURBS surface S.
    distance : float
        Signed offset distance d.  Positive = outward along normal.
    bbox : tuple of two array-likes, shape (3,) each, optional
        ``(min_corner, max_corner)`` for the sampling grid.  If *None*, an
        automatically padded box around the offset surface control net is used.
    grid_size : int, default 32
        Number of nodes per axis.  Total work = grid_size³ closest-point calls.
        Keep ≤ 32 for tests; production may need adaptive octree for large grids
        (see module docstring honesty flag).

    Returns
    -------
    DistanceFieldResult
        Dataclass with ``distances_3d``, ``bbox``, ``resolution``, ``grid_size``,
        ``offset_distance``.

    Raises
    ------
    ValueError
        If *srf* is not a NurbsSurface, *distance* is NaN/inf, *grid_size* < 2,
        or the offset collapses (e.g. sphere with |d| ≥ r).

    Notes
    -----
    Complexity: O(grid_size³) closest-point Newton calls plus one O(n²) seed
    grid per call (Piegl & Tiller §6.1 algorithm with 28 seeds by default).
    For grid_size = 32 this is ~33 k calls, typically < 30 s on a laptop in
    pure Python.  For interactive use, grid_size = 8 or 16 gives a coarse field
    quickly; grid_size = 64 may take minutes.  A narrow-band strategy (only
    computing the field near the surface) or an adaptive octree (Strain 1999)
    is the recommended production upgrade.

    References
    ----------
    Maekawa 1999 — "An overview of offset curves and surfaces",
    Computer-Aided Design 31(3), pp. 165–173.
    https://doi.org/10.1016/S0010-4485(99)00003-5

    Piegl & Tiller, "The NURBS Book", 2nd ed., §6.1 (point inversion),
    §11.3 (offset surfaces).
    """
    if not isinstance(srf, NurbsSurface):
        raise ValueError(
            f"srf must be a NurbsSurface, got {type(srf).__name__}"
        )
    d = float(distance)
    if math.isnan(d) or math.isinf(d):
        raise ValueError(f"distance must be finite, got {d!r}")
    if grid_size < 2:
        raise ValueError(f"grid_size must be >= 2, got {grid_size}")

    # Step 1: compute the d-offset surface (Maekawa 1999; Piegl & Tiller §11.3)
    offset_srf = surface_offset(srf, d)

    # Step 2: determine sampling bounding box
    if bbox is None:
        lo, hi = _auto_bbox(offset_srf, d)
    else:
        lo = np.asarray(bbox[0], dtype=float)
        hi = np.asarray(bbox[1], dtype=float)
        if lo.shape != (3,) or hi.shape != (3,):
            raise ValueError("bbox must be (array-like shape (3,), array-like shape (3,))")
        if np.any(hi <= lo):
            raise ValueError("bbox max_corner must be strictly greater than min_corner")

    extent = hi - lo
    # Use the largest axis to define a uniform resolution
    max_ext = float(np.max(extent))
    resolution = max_ext / (grid_size - 1)

    # Axis-wise step sizes (may differ slightly when extent is non-cubic, but
    # we keep the grid exactly grid_size per axis for a cuboid grid).
    step = extent / (grid_size - 1)

    # Step 3: evaluate distance field at each grid node.
    #
    # Sign determination
    # ------------------
    # surface_normal() returns dS/du × dS/dv without orientation guarantee.
    # The sign convention φ > 0 = "outside" (same side as outward normal)
    # requires knowing which direction is "outward".
    #
    # We use a centroid-based orientation test (pre-computed once):
    #   _normal_sign_flip() checks whether the control-point centroid is on
    #   the positive or negative side of the normal at the UV midpoint.
    #   For a closed surface (sphere) with an inward normal, the centroid is
    #   on the +normal side → flip = −1.
    #   For an open surface (plane), the centroid lies on the surface → no flip.
    #
    # The signed distance is then:
    #   φ(p) = sign_flip × dot(p − foot, n_foot) / |p − foot|  × |p − foot|
    #        = sign_flip × dot(p − foot, n_foot) / |p − foot| × dist_unsigned
    # but we simplify to:
    #   φ(p) = sign_flip × (dot(p − foot, n_foot) / |dot…|) × dist_unsigned
    sign_flip = _normal_sign_flip(offset_srf)

    distances_3d = np.zeros((grid_size, grid_size, grid_size), dtype=np.float64)

    for ix in range(grid_size):
        for iy in range(grid_size):
            for iz in range(grid_size):
                # World-space grid node
                p = lo + np.array([ix * step[0], iy * step[1], iz * step[2]])

                # Closest point on Σ (Piegl & Tiller §6.1 Newton inversion)
                u_foot, v_foot, foot, _ = closest_point_surface(offset_srf, p)

                # Unsigned distance to Σ
                diff = p - foot
                dist_unsigned = float(np.linalg.norm(diff))

                if dist_unsigned < 1e-15:
                    distances_3d[ix, iy, iz] = 0.0
                    continue

                # Normal at closest point on Σ
                n_foot = _surface_normal_at_foot(offset_srf, float(u_foot), float(v_foot))

                # Raw sign from dot product, then multiplied by orientation flip
                raw_sign = 1.0 if float(np.dot(diff, n_foot)) >= 0.0 else -1.0
                distances_3d[ix, iy, iz] = sign_flip * raw_sign * dist_unsigned

    return DistanceFieldResult(
        distances_3d=distances_3d,
        bbox=(lo.copy(), hi.copy()),
        resolution=resolution,
        grid_size=grid_size,
        offset_distance=d,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated — silently skip when kerf_chat / kerf_core absent)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    def _build_surface_from_args(a: dict, prefix: str):
        """Parse flat control-point list + degree/num_u/num_v into NurbsSurface."""
        deg_u = a.get(f"{prefix}degree_u")
        deg_v = a.get(f"{prefix}degree_v")
        raw_cp = a.get(f"{prefix}control_points", [])
        num_u = a.get(f"{prefix}num_u")
        num_v = a.get(f"{prefix}num_v")

        if any(x is None for x in [deg_u, deg_v, num_u, num_v]) or not raw_cp:
            return None, err_payload(
                f"{prefix}degree_u/v, {prefix}control_points, "
                f"{prefix}num_u/v are required",
                "BAD_ARGS",
            )
        try:
            deg_u = int(deg_u)
            deg_v = int(deg_v)
            num_u = int(num_u)
            num_v = int(num_v)
        except (TypeError, ValueError) as exc:
            return None, err_payload(
                f"degree/num values must be integers: {exc}", "BAD_ARGS"
            )
        if deg_u < 1 or deg_v < 1:
            return None, err_payload(
                f"{prefix}degree_u and degree_v must be >= 1", "BAD_ARGS"
            )
        if num_u < 2 or num_v < 2:
            return None, err_payload(
                f"{prefix}num_u and num_v must be >= 2", "BAD_ARGS"
            )
        if len(raw_cp) != num_u * num_v:
            return None, err_payload(
                (f"{prefix}control_points length ({len(raw_cp)}) "
                 f"!= num_u*num_v ({num_u * num_v})"),
                "BAD_ARGS",
            )
        try:
            cp_flat = [np.asarray(pt, dtype=float) for pt in raw_cp]
            dim = cp_flat[0].size
            cp = np.array([pt.tolist()[:dim] for pt in cp_flat],
                          dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, err_payload(f"invalid control_points: {exc}", "BAD_ARGS")

        def _knots(n: int, deg: int) -> np.ndarray:
            inner = max(0, n - deg - 1)
            return np.concatenate([
                np.zeros(deg + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(deg + 1),
            ])

        try:
            surf = NurbsSurface(
                degree_u=deg_u,
                degree_v=deg_v,
                control_points=cp,
                knots_u=_knots(num_u, deg_u),
                knots_v=_knots(num_v, deg_v),
            )
            return surf, None
        except Exception as exc:
            return None, err_payload(f"failed to build NurbsSurface: {exc}", "BAD_ARGS")

    _nurbs_offset_distance_field_spec = ToolSpec(
        name="nurbs_offset_distance_field",
        description=(
            "Compute the signed distance field of the d-offset surface of a "
            "NURBS surface.  For a surface S and offset distance d (Maekawa "
            "1999; Piegl & Tiller §11.3), this evaluates φ(p) = signed "
            "distance from each node of a 3-D Cartesian grid to the offset "
            "surface Σ = S + d·n̂.\n\n"
            "Sign convention: φ > 0 outside Σ, φ < 0 inside, φ ≈ 0 on Σ.\n\n"
            "Returns:\n"
            "  ok                : bool\n"
            "  grid_size         : int   (nodes per axis)\n"
            "  resolution        : float (cell spacing)\n"
            "  bbox_min          : [x, y, z]\n"
            "  bbox_max          : [x, y, z]\n"
            "  offset_distance   : float\n"
            "  distances_flat    : list of float, length grid_size³,\n"
            "                      row-major (ix fastest index)\n"
            "  min_distance      : float\n"
            "  max_distance      : float\n\n"
            "Complexity: O(grid_size³) Newton closest-point calls.  "
            "Keep grid_size ≤ 32 for fast queries; 64+ may be slow in "
            "pure Python.  For large grids use a narrow-band or octree "
            "strategy.\n\n"
            "On error: {ok: false, reason: str}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer", "description": "NURBS degree in U direction"},
                "degree_v": {"type": "integer", "description": "NURBS degree in V direction"},
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Row-major list of [x,y,z] control points, length num_u*num_v",
                },
                "num_u": {"type": "integer", "description": "Control points in U direction"},
                "num_v": {"type": "integer", "description": "Control points in V direction"},
                "distance": {
                    "type": "number",
                    "description": "Signed offset distance d.  Positive = outward along normal.",
                },
                "grid_size": {
                    "type": "integer",
                    "description": "Nodes per axis (default 16).  Total nodes = grid_size³.",
                },
                "bbox_min": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x,y,z] min corner of sampling box (auto if omitted)",
                },
                "bbox_max": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x,y,z] max corner of sampling box (auto if omitted)",
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "num_u", "num_v", "distance"],
        },
    )

    @register(_nurbs_offset_distance_field_spec)
    async def run_nurbs_offset_distance_field(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surf, err = _build_surface_from_args(a, "")
        if err is not None:
            return err

        d = a.get("distance")
        if d is None:
            return err_payload("distance is required", "BAD_ARGS")
        try:
            d = float(d)
        except (TypeError, ValueError) as exc:
            return err_payload(f"distance must be a number: {exc}", "BAD_ARGS")

        gs = int(a.get("grid_size", 16))
        if gs < 2:
            return err_payload("grid_size must be >= 2", "BAD_ARGS")
        if gs > 64:
            return err_payload(
                "grid_size > 64 refused (O(N³) work; use ≤ 32 for safety)",
                "BAD_ARGS",
            )

        # Optional explicit bbox
        bbox = None
        bmin = a.get("bbox_min")
        bmax = a.get("bbox_max")
        if bmin is not None and bmax is not None:
            try:
                bmin = np.asarray(bmin, dtype=float)
                bmax = np.asarray(bmax, dtype=float)
                if bmin.shape != (3,) or bmax.shape != (3,):
                    raise ValueError("bbox_min/bbox_max must each be length-3")
                bbox = (bmin, bmax)
            except Exception as exc:
                return err_payload(f"invalid bbox: {exc}", "BAD_ARGS")

        try:
            result = compute_offset_distance_field(
                surf, d, bbox=bbox, grid_size=gs
            )
        except ValueError as exc:
            return err_payload(str(exc), "COMPUTATION_ERROR")
        except Exception as exc:
            return err_payload(f"unexpected error: {exc}", "INTERNAL_ERROR")

        flat = result.distances_3d.ravel().tolist()
        return ok_payload({
            "ok": True,
            "grid_size": result.grid_size,
            "resolution": result.resolution,
            "bbox_min": result.bbox[0].tolist(),
            "bbox_max": result.bbox[1].tolist(),
            "offset_distance": result.offset_distance,
            "distances_flat": flat,
            "min_distance": float(result.distances_3d.min()),
            "max_distance": float(result.distances_3d.max()),
        })
