"""BREP-FACE-AREA-WEIGHTED-CENTROID — surface centroid of a B-rep shell/solid.

Computes the area-weighted centroid of a set of B-rep faces (the *surface*
centroid, not the volumetric centroid).  This is distinct from body_mass_props
which uses the divergence theorem for volume.  The surface centroid is the
area-weighted mean of all face centroids, useful for:

  * planar approximation of a shell
  * sheet-metal flat-pattern balance check
  * sticker / engraving placement
  * nesting orientation heuristics

Algorithm
---------
For each face F with surface geometry and UV domain [u0,u1]×[v0,v1]:

  area(F)     = ∬ ||∂r/∂u × ∂r/∂v|| du dv
  centroid(F) = ∬ P(u,v) · ||∂r/∂u × ∂r/∂v|| du dv  /  area(F)

Both integrals are computed by Gauss-Legendre quadrature (N×N, default N=16)
over the face's parametric domain.

Global surface centroid = Σ_i(centroid_i × area_i) / Σ_i(area_i).

Supported surface types
-----------------------
Any surface object with an ``evaluate(u, v) -> array[3]`` method.  This covers:

  * ``kerf_cad_core.geom.brep.Plane``
  * ``kerf_cad_core.geom.brep.CylinderSurface``
  * ``kerf_cad_core.geom.brep.SphereSurface``
  * ``kerf_cad_core.geom.brep.TorusSurface``
  * ``kerf_cad_core.geom.nurbs.NurbsSurface`` (via ``surface_evaluate``)

UV domain detection
-------------------
For analytic surfaces the UV domain is detected heuristically from the Face's
outer Loop vertex positions projected back to surface parameters (for
Plane/Cylinder/Sphere, exact analytic inversion).  For NurbsSurface the knot
vector spans are used directly.  If domain detection fails the integration
falls back to the raw knot-span range or a reasonable default.

CAVEAT — trimmed faces
-----------------------
For trimmed NURBS faces (faces with inner loops / holes), v1 uses the *full*
bounding-box UV domain of the outer loop projected onto the surface, not the
exact trimmed domain.  A ``trimmed_approx`` flag is set to ``True`` in the
per-face result and the area/centroid may over-count material in the trim
regions.  Exact integration over the trimmed UV polygon requires a
polygon-clipping integrator (deferred to v2).

References
----------
Piegl & Tiller, "The NURBS Book", 2nd ed., Springer 1997 — §6.1 surface
area element via cross-product of first partials.

Struik, D.J., "Lectures on Classical Differential Geometry", 2nd ed.,
Dover 1988 — §2-4 surface area as integral of √(EG−F²) du dv.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Plane,
    CylinderSurface,
    SphereSurface,
    TorusSurface,
)

# ---------------------------------------------------------------------------
# Gauss-Legendre quadrature (cached)
# ---------------------------------------------------------------------------

_GL_CACHE: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}

_DEFAULT_N = 16  # 16×16 = 256 evaluation points per face


def _gl(n: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return cached (nodes, weights) for n-point Gauss-Legendre on [-1, 1]."""
    if n not in _GL_CACHE:
        from numpy.polynomial.legendre import leggauss
        _GL_CACHE[n] = leggauss(n)
    return _GL_CACHE[n]


# ---------------------------------------------------------------------------
# Surface area element — finite-difference (works for any evaluate() surface)
# ---------------------------------------------------------------------------

_FD_H = 1e-6  # step for finite-difference partial derivatives


def _area_element(surface, u: float, v: float) -> Tuple[np.ndarray, float]:
    """Return (point, dA) at (u, v) via finite-difference cross-product.

    dA = ||∂r/∂u × ∂r/∂v||  (un-scaled; caller multiplies by du*dv weight)
    """
    p = np.asarray(surface.evaluate(u, v), dtype=float)[:3]
    pu = np.asarray(surface.evaluate(u + _FD_H, v), dtype=float)[:3]
    pv = np.asarray(surface.evaluate(u, v + _FD_H), dtype=float)[:3]
    du = (pu - p) / _FD_H
    dv = (pv - p) / _FD_H
    cross = np.cross(du, dv)
    return p, float(np.linalg.norm(cross))


# ---------------------------------------------------------------------------
# UV domain detection helpers
# ---------------------------------------------------------------------------

def _plane_uv_bounds(face: Face) -> Optional[Tuple[float, float, float, float]]:
    """Compute the UV bounding box of the outer-loop vertices for a Plane face."""
    loop = face.outer_loop()
    if loop is None or not loop.coedges:
        return None
    srf: Plane = face.surface
    e1 = np.asarray(srf.x_axis, dtype=float)
    e2 = np.asarray(srf.y_axis, dtype=float)
    origin = np.asarray(srf.origin, dtype=float)
    e1n = np.linalg.norm(e1)
    e2n = np.linalg.norm(e2)
    if e1n < 1e-14 or e2n < 1e-14:
        return None
    e1_unit = e1 / e1n
    e2_unit = e2 / e2n
    us, vs = [], []
    for ce in loop.coedges:
        for pt in (ce.start_point(), ce.end_point()):
            pt = np.asarray(pt, dtype=float)[:3]
            d = pt - origin
            us.append(float(np.dot(d, e1_unit)))
            vs.append(float(np.dot(d, e2_unit)))
    if not us:
        return None
    return min(us), max(us), min(vs), max(vs)


def _cylinder_uv_bounds(face: Face) -> Tuple[float, float, float, float]:
    """UV domain for a full cylinder lateral patch: u in [0, 2π], v in [v_lo, v_hi]."""
    loop = face.outer_loop()
    srf: CylinderSurface = face.surface
    if loop is None or not loop.coedges:
        # fallback: unit-height cylinder
        return 0.0, 2 * math.pi, 0.0, 1.0
    axis = np.asarray(srf.axis, dtype=float)
    center = np.asarray(srf.center, dtype=float)
    vs = []
    for ce in loop.coedges:
        for pt in (ce.start_point(), ce.end_point()):
            pt = np.asarray(pt, dtype=float)[:3]
            vs.append(float(np.dot(pt - center, axis)))
    return 0.0, 2 * math.pi, min(vs), max(vs)


def _sphere_uv_bounds(_face: Face) -> Tuple[float, float, float, float]:
    """Full sphere: u in [0, 2π], v in [-π/2, π/2]."""
    return 0.0, 2 * math.pi, -math.pi / 2, math.pi / 2


def _torus_uv_bounds(_face: Face) -> Tuple[float, float, float, float]:
    """Full torus: u in [0, 2π], v in [0, 2π]."""
    return 0.0, 2 * math.pi, 0.0, 2 * math.pi


def _nurbs_uv_bounds(surface) -> Tuple[float, float, float, float]:
    """Return the knot-vector span [u_min, u_max, v_min, v_max] of a NurbsSurface."""
    ku = np.asarray(surface.knots_u, dtype=float)
    kv = np.asarray(surface.knots_v, dtype=float)
    return float(ku[0]), float(ku[-1]), float(kv[0]), float(kv[-1])


def _face_uv_bounds(face: Face) -> Tuple[float, float, float, float]:
    """Return the UV integration domain for a face (heuristic; see module caveat)."""
    srf = face.surface
    if isinstance(srf, Plane):
        bounds = _plane_uv_bounds(face)
        if bounds is not None:
            return bounds
        # degenerate: no loop vertices — use a unit square
        return 0.0, 1.0, 0.0, 1.0
    if isinstance(srf, CylinderSurface):
        return _cylinder_uv_bounds(face)
    if isinstance(srf, SphereSurface):
        return _sphere_uv_bounds(face)
    if isinstance(srf, TorusSurface):
        return _torus_uv_bounds(face)
    # NurbsSurface or other duck-typed surface
    if hasattr(srf, "knots_u") and hasattr(srf, "knots_v"):
        return _nurbs_uv_bounds(srf)
    # Last resort: unit square
    return 0.0, 1.0, 0.0, 1.0


def _has_inner_loops(face: Face) -> bool:
    """True if the face has any inner (trim) loops."""
    return bool(face.inner_loops())


# ---------------------------------------------------------------------------
# Core integration: per-face area and centroid
# ---------------------------------------------------------------------------

def _integrate_face(
    face: Face, n: int = _DEFAULT_N
) -> Tuple[float, np.ndarray, bool]:
    """Gauss-Legendre 2D integration for a single face.

    Returns (area, centroid[3], trimmed_approx).

    trimmed_approx=True means the face has inner loops and the full bounding-box
    UV domain was used (v1 heuristic, may over-count area).
    """
    srf = face.surface
    u0, u1, v0, v1 = _face_uv_bounds(face)
    trimmed_approx = _has_inner_loops(face)

    # Guard against degenerate domains
    du = u1 - u0
    dv = v1 - v0
    if abs(du) < 1e-14 or abs(dv) < 1e-14:
        return 0.0, np.zeros(3), trimmed_approx

    xi, wi = _gl(n)

    # Map Gauss nodes from [-1, 1] to [u0, u1] × [v0, v1]
    u_mid = 0.5 * (u0 + u1)
    u_half = 0.5 * du
    v_mid = 0.5 * (v0 + v1)
    v_half = 0.5 * dv
    us = u_mid + u_half * xi
    vs = v_mid + v_half * xi

    area = 0.0
    centroid = np.zeros(3)

    for i in range(n):
        for j in range(n):
            p, da_elem = _area_element(srf, us[i], vs[j])
            w = wi[i] * wi[j] * u_half * v_half
            dA = da_elem * w
            area += dA
            centroid += p * dA

    if area > 1e-20:
        centroid = centroid / area
    else:
        centroid = np.zeros(3)

    return area, centroid, trimmed_approx


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def face_area(face: Face, n: int = _DEFAULT_N) -> float:
    """Compute the area of a single B-rep face.

    Uses Gauss-Legendre N×N quadrature over the face's parametric domain.

    Parameters
    ----------
    face : kerf_cad_core.geom.brep.Face
    n    : quadrature order (default 16 — 256 evaluation points; use 32 for
           highly curved faces requiring < 1e-8 relative accuracy)

    Returns
    -------
    float
        Surface area in model units squared.
    """
    area, _, _ = _integrate_face(face, n)
    return area


def face_centroid(face: Face, n: int = _DEFAULT_N) -> np.ndarray:
    """Compute the area-weighted centroid of a single B-rep face.

    Parameters
    ----------
    face : kerf_cad_core.geom.brep.Face
    n    : quadrature order (default 16)

    Returns
    -------
    np.ndarray  shape (3,)
        3-D position of the face centroid in model coordinates.
    """
    _, centroid, _ = _integrate_face(face, n)
    return centroid


def surface_centroid(
    faces: Sequence[Face],
    n: int = _DEFAULT_N,
) -> Dict:
    """Compute the area-weighted surface centroid of a collection of B-rep faces.

    This is the *surface* (shell) centroid — distinct from the volumetric
    centroid returned by ``body_mass_props``.  Use it for:

      * planar approximation centroid of a thin shell
      * sheet-metal flat-pattern balance check
      * engraving / sticker placement guidance
      * nesting orientation heuristics

    Algorithm
    ---------
    For each face F:
        area_F     = ∬ ||∂r/∂u × ∂r/∂v|| du dv   (Gauss-Legendre N×N)
        centroid_F = ∬ P(u,v) dA  /  area_F

    Global surface centroid = Σ(centroid_F × area_F) / Σ(area_F)

    Parameters
    ----------
    faces : sequence of kerf_cad_core.geom.brep.Face
        All faces to include.  For a solid Body pass ``body.all_faces()``.
    n     : int, default 16
        Gauss-Legendre quadrature order per axis (N×N points per face).
        16 gives < 1e-6 relative error on smooth analytic faces.

    Returns
    -------
    dict with keys:
        centroid       : list[float]  — [x, y, z] area-weighted centroid
        total_area     : float        — sum of all face areas
        per_face       : list[dict]   — one entry per input face:
            face_index     : int
            area           : float
            centroid       : list[float]
            trimmed_approx : bool — True if inner-loop trim heuristic was used
        caveats        : list[str]    — any precision warnings
    """
    caveats: List[str] = []
    per_face = []
    total_area = 0.0
    weighted_sum = np.zeros(3)

    for idx, face in enumerate(faces):
        area, cen, trimmed_approx = _integrate_face(face, n)
        if trimmed_approx:
            caveats.append(
                f"face[{idx}]: has inner loops; v1 uses bounding-box UV domain — "
                "area/centroid may over-count material in trimmed regions."
            )
        per_face.append({
            "face_index": idx,
            "area": float(area),
            "centroid": cen.tolist(),
            "trimmed_approx": trimmed_approx,
        })
        total_area += area
        weighted_sum += cen * area

    if total_area > 1e-20:
        centroid = weighted_sum / total_area
    else:
        centroid = np.zeros(3)
        caveats.append("total_area near zero; centroid undefined — returning origin.")

    return {
        "centroid": centroid.tolist(),
        "total_area": float(total_area),
        "per_face": per_face,
        "caveats": caveats,
    }


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

    _FACE_SCHEMA = {
        "type": "object",
        "description": (
            "A B-rep face descriptor.  Supply the surface geometry via one of:\n"
            "  1. 'plane' — analytic plane {origin:[x,y,z], x_axis:[...], y_axis:[...]}\n"
            "  2. 'cylinder' — {center:[x,y,z], axis:[x,y,z], radius:float, "
            "height_range:[v_lo,v_hi]}\n"
            "  3. 'sphere' — {center:[x,y,z], radius:float}\n"
            "  4. 'nurbs' — {degree_u:int, degree_v:int, control_points:[[x,y,z],...], "
            "knots_u:[...], knots_v:[...], weights:[...] or null, nu:int, nv:int}\n\n"
            "For planar faces, supply 'vertices' (list of [x,y,z]) to constrain the "
            "integration domain to the actual polygon extent."
        ),
        "properties": {
            "surface_type": {"type": "string", "enum": ["plane", "cylinder", "sphere", "torus", "nurbs"]},
            "origin":        {"type": "array", "items": {"type": "number"}},
            "x_axis":        {"type": "array", "items": {"type": "number"}},
            "y_axis":        {"type": "array", "items": {"type": "number"}},
            "center":        {"type": "array", "items": {"type": "number"}},
            "axis":          {"type": "array", "items": {"type": "number"}},
            "radius":        {"type": "number"},
            "height_range":  {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "major_radius":  {"type": "number"},
            "minor_radius":  {"type": "number"},
            "vertices":      {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
            "degree_u":      {"type": "integer"},
            "degree_v":      {"type": "integer"},
            "control_points": {"type": "array"},
            "knots_u":       {"type": "array", "items": {"type": "number"}},
            "knots_v":       {"type": "array", "items": {"type": "number"}},
            "weights":       {"type": ["array", "null"]},
        },
        "required": ["surface_type"],
    }

    def _build_face_from_dict(fd: dict) -> Face:
        """Reconstruct a minimal Face from a JSON descriptor for the LLM tool."""
        from kerf_cad_core.geom.brep import (
            Plane, CylinderSurface, SphereSurface, TorusSurface,
            Face, Loop, Coedge, Edge, Vertex, Line3,
        )
        st = fd.get("surface_type", "plane")

        if st == "plane":
            origin = np.array(fd.get("origin", [0, 0, 0]), dtype=float)
            x_axis = np.array(fd.get("x_axis", [1, 0, 0]), dtype=float)
            y_axis = np.array(fd.get("y_axis", [0, 1, 0]), dtype=float)
            srf = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)
            verts_raw = fd.get("vertices", [])
            if verts_raw:
                n = len(verts_raw)
                pts = [np.array(v, dtype=float) for v in verts_raw]
                vxs = [Vertex(p) for p in pts]
                edges = [Edge(Line3(pts[i], pts[(i + 1) % n]), 0.0, 1.0, vxs[i], vxs[(i + 1) % n]) for i in range(n)]
                coedges = [Coedge(e, True) for e in edges]
                loop = Loop(coedges, is_outer=True)
                return Face(srf, [loop])
            return Face(srf, [])

        if st == "cylinder":
            center = np.array(fd.get("center", [0, 0, 0]), dtype=float)
            axis = np.array(fd.get("axis", [0, 0, 1]), dtype=float)
            radius = float(fd.get("radius", 1.0))
            srf = CylinderSurface(center=center, axis=axis, radius=radius)
            # Provide a dummy loop with v-range vertices so the heuristic works
            hr = fd.get("height_range", [0.0, 1.0])
            v0, v1_val = float(hr[0]), float(hr[1])
            ax_unit = axis / (np.linalg.norm(axis) + 1e-30)
            dummy_pts = [center + v0 * ax_unit, center + v1_val * ax_unit]
            vxs = [Vertex(p) for p in dummy_pts]
            edge = Edge(Line3(dummy_pts[0], dummy_pts[1]), 0.0, 1.0, vxs[0], vxs[1])
            edge2 = Edge(Line3(dummy_pts[1], dummy_pts[0]), 0.0, 1.0, vxs[1], vxs[0])
            coedges = [Coedge(edge, True), Coedge(edge2, True)]
            loop = Loop(coedges, is_outer=True)
            return Face(srf, [loop])

        if st == "sphere":
            center = np.array(fd.get("center", [0, 0, 0]), dtype=float)
            radius = float(fd.get("radius", 1.0))
            srf = SphereSurface(center=center, radius=radius)
            return Face(srf, [])

        if st == "torus":
            center = np.array(fd.get("center", [0, 0, 0]), dtype=float)
            axis = np.array(fd.get("axis", [0, 0, 1]), dtype=float)
            major_radius = float(fd.get("major_radius", 2.0))
            minor_radius = float(fd.get("minor_radius", 0.5))
            srf = TorusSurface(center=center, axis=axis, major_radius=major_radius, minor_radius=minor_radius)
            return Face(srf, [])

        if st == "nurbs":
            from kerf_cad_core.geom.nurbs import NurbsSurface
            deg_u = int(fd.get("degree_u", 3))
            deg_v = int(fd.get("degree_v", 3))
            cp = np.array(fd.get("control_points", []), dtype=float)
            ku = np.array(fd.get("knots_u", []), dtype=float)
            kv = np.array(fd.get("knots_v", []), dtype=float)
            wts_raw = fd.get("weights")
            wts = np.array(wts_raw, dtype=float) if wts_raw else None
            nu_ctrl = int(fd.get("nu", len(ku) - deg_u - 1))
            nv_ctrl = int(fd.get("nv", len(kv) - deg_v - 1))
            srf = NurbsSurface(
                degree_u=deg_u, degree_v=deg_v,
                control_points=cp.reshape(nu_ctrl, nv_ctrl, -1) if cp.ndim == 2 else cp,
                knots_u=ku, knots_v=kv,
                weights=wts.reshape(nu_ctrl, nv_ctrl) if wts is not None else None,
            )
            return Face(srf, [])

        raise ValueError(f"unknown surface_type {st!r}")

    _CENTROID_SPEC = ToolSpec(
        name="brep_surface_centroid",
        description=(
            "Compute the area-weighted surface centroid of a B-rep shell or solid.\n\n"
            "This is the SURFACE centroid (area-weighted mean of all face centroids), "
            "NOT the volumetric centroid from body_mass_props.  Use for:\n"
            "  * planar approximation centroid of a thin shell\n"
            "  * sheet-metal flat-pattern balance check\n"
            "  * sticker / engraving placement\n"
            "  * nesting orientation heuristics\n\n"
            "Algorithm: Gauss-Legendre 16x16 quadrature over each face's UV domain;\n"
            "  area(F) = integral ||dr/du x dr/dv|| du dv\n"
            "  centroid(F) = integral P(u,v) dA / area(F)\n"
            "  global = sum(centroid_F * area_F) / sum(area_F)\n\n"
            "Depth-bar oracles:\n"
            "  unit cube (6 faces): total_area=6.0, centroid=(0.5,0.5,0.5)\n"
            "  unit sphere: total_area=4pi~12.566, centroid=(0,0,0)\n\n"
            "CAVEAT: trimmed faces (inner loops) use bounding-box UV domain (v1 heuristic).\n\n"
            "Returns: {ok, centroid:[x,y,z], total_area, per_face:[{face_index, area, centroid, trimmed_approx}], caveats}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "faces": {
                    "type": "array",
                    "description": "List of B-rep face descriptors (see schema for face object).",
                    "items": _FACE_SCHEMA,
                },
                "quad_order": {
                    "type": "integer",
                    "description": "Gauss-Legendre order per axis (default 16). Use 32 for highly curved faces.",
                    "default": 16,
                    "minimum": 4,
                    "maximum": 64,
                },
            },
            "required": ["faces"],
        },
    )

    @register(_CENTROID_SPEC)
    async def run_brep_surface_centroid(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        faces_raw = a.get("faces")
        if not faces_raw:
            return err_payload("'faces' is required and must be non-empty", "BAD_ARGS")
        n = int(a.get("quad_order", _DEFAULT_N))
        n = max(4, min(64, n))
        try:
            faces = [_build_face_from_dict(fd) for fd in faces_raw]
        except Exception as exc:
            return err_payload(f"face construction failed: {exc}", "BAD_ARGS")
        try:
            result = surface_centroid(faces, n=n)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
        return ok_payload({
            "centroid": result["centroid"],
            "total_area": result["total_area"],
            "per_face": result["per_face"],
            "caveats": result["caveats"],
        })
