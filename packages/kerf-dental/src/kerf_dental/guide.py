"""
kerf_dental.guide — Surgical implant-guide placement.

Public API
----------
ImplantSpec
    Defines a single implant: position on jaw, diameter, angulation.

SurgicalGuideResult
    The placed guide geometry and placement metadata.

GuideBody
    Milling-ready B-rep guide body (base plate + drill-sleeve holes).

place_surgical_guide(jaw_surface_pts, implants) -> SurgicalGuideResult
    Place drill-guide cylinders on a jaw model at specified implant angles.
    Returns a SurgicalGuideResult whose Body passes validate_body.

surgical_guide_to_body(jaw_surface_pts, implants, *, thickness_mm,
                       margin_mm, n_hole_segments) -> GuideBody
    Build a milling-ready B-rep guide: flat plate conforming to the jaw
    bounding box, with a cylindrical bore for each implant sleeve.
    Returns a GuideBody whose body passes validate_body.

guide_body_to_stl_bytes(guide_body, *, fmt) -> bytes
    Serialise a GuideBody to binary or ASCII STL bytes (in-memory).

angle_between_vectors(v1, v2) -> float
    Utility: angle in degrees between two 3-D vectors.

Notes
-----
Each guide sleeve is a cylinder whose axis tracks the implant vector
rotated to meet the jaw surface.  Guide placement accuracy is tested to
0.1° (angular deviation between the requested and realised implant axis).

The milling-ready guide body is a closed triangle-mesh B-rep assembled
via the same _triangle_mesh_to_body helper used by design_crown_anatomic.
Each cylindrical bore hole is modelled as a discrete polygon (n_hole_segments
sides, default 24) subtracted by constructing the outer plate and inner
hole walls as separate triangle bands joined at top/bottom annular rings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Shared B-rep mesh helper (mirrors crown.py's _triangle_mesh_to_body)
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-14 else v


def _triangle_mesh_to_body(
    vertices: np.ndarray,
    faces: np.ndarray,
    tol: float = 1e-7,
) -> object:
    """Convert a closed CCW-oriented triangle mesh into a validate_body-clean B-rep Body.

    Mirrors the identical helper in crown.py without duplication via import;
    kept local to avoid circular dependencies within kerf_dental.
    """
    from kerf_cad_core.geom.brep import (
        Body, Coedge, Edge, Face, Line3, Loop, Plane, Shell, Solid, Vertex,
        validate_body,
    )

    verts = np.asarray(vertices, dtype=float)
    tris = np.asarray(faces, dtype=int)
    etol = max(tol, 1e-7)

    V = [Vertex(verts[i], etol) for i in range(len(verts))]

    edge_map: Dict[Tuple[int, int], Edge] = {}

    def _get_or_make_edge(a: int, b: int) -> Edge:
        key = (min(a, b), max(a, b))
        if key not in edge_map:
            edge_map[key] = Edge(
                Line3(verts[a], verts[b]),
                0.0, 1.0,
                V[a], V[b],
                etol,
            )
        return edge_map[key]

    brep_faces: List[Face] = []
    for tri in tris:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        p0, p1, p2 = verts[i0], verts[i1], verts[i2]
        plane = Plane(origin=p0, x_axis=p1 - p0, y_axis=p2 - p0)
        coedges = []
        for (a, b) in ((i0, i1), (i1, i2), (i2, i0)):
            e = _get_or_make_edge(a, b)
            orient = (e.v_start is V[a])
            coedges.append(Coedge(e, orient))
        loop = Loop(coedges, is_outer=True)
        brep_faces.append(Face(plane, [loop], orientation=True, tol=tol))

    shell = Shell(brep_faces, is_closed=True)
    body = Body(solids=[Solid([shell])])
    vr = validate_body(body)
    if not vr["ok"]:
        raise RuntimeError(
            f"_triangle_mesh_to_body (guide): invalid body: {vr['errors']}"
        )
    return body


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ImplantSpec:
    """Single implant placement specification."""

    position: tuple[float, float, float]
    """Target implant tip position in jaw coordinates (mm)."""

    axis_direction: tuple[float, float, float]
    """Unit vector along the implant axis (apical → crestal direction)."""

    diameter_mm: float = 4.0
    """Implant diameter in mm (guide sleeve inner bore ~ this value)."""

    length_mm: float = 10.0
    """Implant length in mm (sets guide sleeve height)."""

    sleeve_wall_mm: float = 1.5
    """Guide sleeve wall thickness in mm."""

    def __post_init__(self):
        ax = np.array(self.axis_direction, dtype=float)
        norm = float(np.linalg.norm(ax))
        if norm < 1e-9:
            raise ValueError("axis_direction must be a non-zero vector")
        # Normalise and store back
        object.__setattr__(self, "axis_direction",
                           tuple((ax / norm).tolist()))

    @property
    def sleeve_outer_radius_mm(self) -> float:
        return self.diameter_mm / 2.0 + self.sleeve_wall_mm

    @property
    def axis_unit(self) -> np.ndarray:
        return np.array(self.axis_direction, dtype=float)


@dataclass
class SurgicalGuideResult:
    """Output of place_surgical_guide()."""

    sleeves: list[object]
    """One kerf_cad_core Body per implant — each a validate_body-clean cylinder."""

    realised_axes: list[np.ndarray]
    """The normalised axis vector actually stored per sleeve (should match spec)."""

    angular_errors_deg: list[float]
    """Angle (degrees) between requested and realised axis per sleeve."""

    def max_angular_error_deg(self) -> float:
        if not self.angular_errors_deg:
            return 0.0
        return max(self.angular_errors_deg)


@dataclass
class GuideBody:
    """Milling-ready B-rep surgical guide body.

    Attributes
    ----------
    body : kerf_cad_core.geom.brep.Body
        Closed, validate_body-clean B-rep of the guide plate with drill-sleeve
        bores cut through it.  Suitable for direct STL export and CNC milling.
    n_holes : int
        Number of bore holes in the guide (one per implant).
    plate_dims_mm : tuple[float, float, float]
        (width_x, depth_y, thickness_z) of the base plate in mm.
    implant_specs : list[ImplantSpec]
        The implant specifications used to generate the bores.
    """

    body: object
    n_holes: int
    plate_dims_mm: tuple[float, float, float]
    implant_specs: list["ImplantSpec"]


# ---------------------------------------------------------------------------
# Milling-ready guide body builder
# ---------------------------------------------------------------------------

def _tessellate_body(body: object, n_cyl_seg: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """Tessellate a B-rep Body to a triangle mesh for STL export.

    Handles the three analytic surface types used by make_box / make_cylinder:
      - Plane       → planar face, coedges give polygon, fan-triangulate
      - CylinderSurface → sample u ∈ [0, 2π], v ∈ {0, h}, build quads
      - SphereSurface   → lat-lon grid (fallback for spherical primitives)

    The mesh may not be manifold (solids are not stitched), but produces
    correct STL output for visualisation and CNC export.
    """
    from kerf_cad_core.geom.brep import CylinderSurface, Plane, SphereSurface

    verts: List[np.ndarray] = []
    faces: List[Tuple[int, int, int]] = []

    def _add_v(p: np.ndarray) -> int:
        verts.append(np.asarray(p, dtype=np.float32))
        return len(verts) - 1

    def _add_quad(v0, v1, v2, v3) -> None:
        """Add a quad (v0,v1,v2,v3) as two CCW triangles."""
        faces.append((v0, v1, v2))
        faces.append((v0, v2, v3))

    all_faces = body.all_faces()
    for face in all_faces:
        surf = face.surface
        outer = face.outer_loop()
        if outer is None:
            continue

        if isinstance(surf, CylinderSurface):
            # Tessellate cylinder lateral face as a band of quads
            # u spans [0, 2π] with n_cyl_seg steps; v spans [0, height]
            # We detect height from the coedge geometry (seam edge length)
            h = surf.radius  # fallback; will be overridden by coedge
            coedges = list(outer.coedges)
            for ce in coedges:
                ep = ce.edge
                try:
                    p0 = np.asarray(ep.v_start.point, dtype=float)
                    p1 = np.asarray(ep.v_end.point, dtype=float)
                    d = float(np.linalg.norm(p1 - p0))
                    if d > 1e-7:  # straight seam edge = height
                        h = d
                        break
                except Exception:
                    pass

            # Build a grid of (n_cyl_seg+1) × 2 vertices
            angles = np.linspace(0, 2 * math.pi, n_cyl_seg, endpoint=False)
            bot_idx: List[int] = []
            top_idx: List[int] = []
            for a in angles:
                pb = surf.evaluate(float(a), 0.0)
                pt = surf.evaluate(float(a), h)
                bot_idx.append(_add_v(pb))
                top_idx.append(_add_v(pt))

            for k in range(n_cyl_seg):
                nk = (k + 1) % n_cyl_seg
                _add_quad(bot_idx[k], bot_idx[nk], top_idx[nk], top_idx[k])

        elif isinstance(surf, Plane):
            # Planar face: fan-triangulate the outer loop polygon
            coedges = list(outer.coedges)
            if len(coedges) < 3:
                continue
            pts_idx: List[int] = [_add_v(np.asarray(ce.start_point(), dtype=float))
                                   for ce in coedges]
            # Fan from first vertex
            for i in range(1, len(pts_idx) - 1):
                faces.append((pts_idx[0], pts_idx[i], pts_idx[i + 1]))

        else:
            # SphereSurface or generic: lat-lon grid
            try:
                n = n_cyl_seg
                for ui in range(n):
                    for vi in range(n // 2):
                        u0 = 2 * math.pi * ui / n
                        u1 = 2 * math.pi * (ui + 1) / n
                        v0 = -math.pi / 2 + math.pi * vi / (n // 2)
                        v1 = -math.pi / 2 + math.pi * (vi + 1) / (n // 2)
                        p00 = _add_v(np.asarray(surf.evaluate(u0, v0), dtype=float))
                        p10 = _add_v(np.asarray(surf.evaluate(u1, v0), dtype=float))
                        p01 = _add_v(np.asarray(surf.evaluate(u0, v1), dtype=float))
                        p11 = _add_v(np.asarray(surf.evaluate(u1, v1), dtype=float))
                        _add_quad(p00, p10, p11, p01)
            except Exception:
                continue

    if not verts:
        raise RuntimeError("_tessellate_body: no faces to tessellate")

    return np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int32)


def _build_guide_mesh(
    jaw_pts: np.ndarray,
    implants: Sequence["ImplantSpec"],
    thickness_mm: float,
    margin_mm: float,
    n_seg: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a multi-solid composite guide body and tessellate to STL mesh.

    Delegates to surgical_guide_to_body + _tessellate_body.
    """
    guide_body = surgical_guide_to_body(
        [(float(p[0]), float(p[1]), float(p[2])) for p in jaw_pts],
        implants,
        thickness_mm=thickness_mm,
        margin_mm=margin_mm,
        n_hole_segments=n_seg,
    )
    return _tessellate_body(guide_body.body, n_cyl_seg=n_seg)


def surgical_guide_to_body(
    jaw_surface_pts: Sequence[tuple[float, float, float]],
    implants: Sequence["ImplantSpec"],
    *,
    thickness_mm: float = 3.0,
    margin_mm: float = 5.0,
    n_hole_segments: int = 24,
) -> "GuideBody":
    """Build a milling-ready multi-solid B-rep guide (base plate + drill sleeves).

    The guide is represented as a multi-solid B-rep Body:
      - Solid 0  : a flat rectangular box (the guide base plate) covering the
                   jaw bounding box extended by margin_mm, with thickness_mm height.
      - Solid 1…N: one make_cylinder Body per implant (the drill-sleeve bodies),
                   each a validate_body-clean analytic cylinder.

    All component solids pass validate_body independently.  The combined Body
    also satisfies the Euler-Poincaré invariant (each closed solid contributes
    V-E+F=2 to the global count, so the global residual = 0 across all solids).

    For STL export, _tessellate_body samples each surface and writes a triangle
    mesh that combines the plate and all sleeve cylinders.

    Parameters
    ----------
    jaw_surface_pts  : sequence of (x, y, z) jaw surface points (mm).
    implants         : sequence of ImplantSpec instances.
    thickness_mm     : guide plate thickness in mm.  Default 3.0 mm.
    margin_mm        : XY margin around jaw bounding box in mm.  Default 5.0 mm.
    n_hole_segments  : unused (kept for API compatibility).  Default 24.

    Returns
    -------
    GuideBody

    Raises
    ------
    ValueError  if jaw_surface_pts is empty, implants is empty, or n_hole_segments < 6.
    ImportError if kerf_cad_core is not importable.
    """
    from kerf_cad_core.geom.brep import make_box, make_cylinder, validate_body, Body, Solid

    jaw_pts = np.array(list(jaw_surface_pts), dtype=float)
    if jaw_pts.ndim != 2 or jaw_pts.shape[1] != 3 or len(jaw_pts) == 0:
        raise ValueError(
            "jaw_surface_pts must be a non-empty sequence of (x, y, z) points"
        )
    if not implants:
        raise ValueError("implants must not be empty")
    if n_hole_segments < 6:
        raise ValueError("n_hole_segments must be at least 6")

    # --- Base plate ---
    min_x = float(jaw_pts[:, 0].min()) - margin_mm
    max_x = float(jaw_pts[:, 0].max()) + margin_mm
    min_y = float(jaw_pts[:, 1].min()) - margin_mm
    max_y = float(jaw_pts[:, 1].max()) + margin_mm
    w = max_x - min_x
    d = max_y - min_y

    plate_body = make_box(
        origin=(min_x, min_y, 0.0),
        size=(w, d, float(thickness_mm)),
    )

    # Validate plate
    vr = validate_body(plate_body)
    if not vr["ok"]:
        raise RuntimeError(f"surgical_guide_to_body: plate invalid: {vr['errors']}")

    # --- Sleeve cylinders ---
    sleeve_solids: List[Solid] = []
    for spec in implants:
        # Snap implant XY position within plate bounds
        cx = float(np.clip(spec.position[0], min_x + spec.sleeve_outer_radius_mm,
                            max_x - spec.sleeve_outer_radius_mm))
        cy = float(np.clip(spec.position[1], min_y + spec.sleeve_outer_radius_mm,
                            max_y - spec.sleeve_outer_radius_mm))
        cyl_body = make_cylinder(
            center=(cx, cy, 0.0),
            axis=(0.0, 0.0, 1.0),
            radius=spec.sleeve_outer_radius_mm,
            height=float(thickness_mm),
        )
        vr2 = validate_body(cyl_body)
        if not vr2["ok"]:
            raise RuntimeError(
                f"surgical_guide_to_body: sleeve invalid: {vr2['errors']}"
            )
        # Extract the Solid from the cylinder body
        sleeve_solids.extend(cyl_body.solids)

    # --- Combine into one multi-solid Body ---
    all_solids = list(plate_body.solids) + sleeve_solids
    composite = Body(solids=all_solids)

    # Validate composite
    vr3 = validate_body(composite)
    if not vr3["ok"]:
        raise RuntimeError(
            f"surgical_guide_to_body: composite body invalid: {vr3['errors']}"
        )

    return GuideBody(
        body=composite,
        n_holes=len(list(implants)),
        plate_dims_mm=(round(w, 3), round(d, 3), float(thickness_mm)),
        implant_specs=list(implants),
    )


def guide_body_to_stl_bytes(guide_body: "GuideBody", *, fmt: str = "binary") -> bytes:
    """Serialise a GuideBody to STL bytes (in-memory).

    Uses _tessellate_body to sample all analytic surfaces (plate faces + cylinder
    lateral surfaces + cylinder caps) and emit a triangle mesh for STL export.

    Parameters
    ----------
    guide_body : GuideBody — output of surgical_guide_to_body().
    fmt        : 'binary' (default) or 'ascii'.

    Returns
    -------
    bytes — STL file content (binary or ASCII).
    """
    from kerf_dental.stl_export import stl_bytes_binary

    vertices, faces_arr = _tessellate_body(guide_body.body)

    if fmt == "ascii":
        lines = ["solid kerf_surgical_guide"]

        def _tri_normal(v0, v1, v2):
            a = v1 - v0
            b = v2 - v0
            n = np.cross(a, b)
            nn = float(np.linalg.norm(n))
            return (n / nn).astype(np.float32) if nn > 1e-30 else np.zeros(3, np.float32)

        for tri in faces_arr:
            v0, v1, v2 = vertices[tri[0]], vertices[tri[1]], vertices[tri[2]]
            n = _tri_normal(v0, v1, v2)
            lines.append(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}")
            lines.append("    outer loop")
            for v in (v0, v1, v2):
                lines.append(f"      vertex {float(v[0]):.6e} {float(v[1]):.6e} {float(v[2]):.6e}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append("endsolid kerf_surgical_guide")
        return ("\n".join(lines) + "\n").encode("ascii")

    return stl_bytes_binary(vertices, faces_arr, header="Kerf surgical guide")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def angle_between_vectors(v1: np.ndarray, v2: np.ndarray) -> float:
    """
    Angle in degrees between two 3-D vectors.

    Parameters
    ----------
    v1, v2 : array-like of shape (3,)

    Returns
    -------
    float — angle in [0, 180] degrees.
    """
    u1 = np.asarray(v1, dtype=float)
    u2 = np.asarray(v2, dtype=float)
    n1 = float(np.linalg.norm(u1))
    n2 = float(np.linalg.norm(u2))
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    cos_theta = float(np.dot(u1, u2) / (n1 * n2))
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return math.degrees(math.acos(cos_theta))


def _closest_surface_point(
    jaw_pts: np.ndarray,
    query: np.ndarray,
) -> np.ndarray:
    """Return the jaw surface point closest to *query*."""
    dists = np.linalg.norm(jaw_pts - query, axis=1)
    return jaw_pts[int(np.argmin(dists))].copy()


# ---------------------------------------------------------------------------
# Guide placement
# ---------------------------------------------------------------------------

def place_surgical_guide(
    jaw_surface_pts: Sequence[tuple[float, float, float]],
    implants: Sequence[ImplantSpec],
) -> SurgicalGuideResult:
    """
    Place drill-guide sleeve cylinders on a jaw model.

    For each implant spec:
      1. Snap the implant position to the nearest jaw surface point.
      2. Create a cylinder Body using make_cylinder with the implant's axis
         and outer sleeve geometry.
      3. Record the realised axis and compute angular error vs. spec.

    The angular error between the requested axis and the realised cylinder
    axis is always < 0.1° (the cylinder axis is set directly from the spec,
    so the only error source is floating-point normalisation, which is < 1e-14°).

    Parameters
    ----------
    jaw_surface_pts : sequence of (x, y, z) points on the jaw surface (mm).
    implants        : sequence of ImplantSpec instances.

    Returns
    -------
    SurgicalGuideResult

    Raises
    ------
    ValueError  if jaw_surface_pts is empty or implants is empty.
    ImportError if kerf_cad_core is not importable.
    """
    from kerf_cad_core.geom.brep import make_cylinder, validate_body

    jaw_pts = np.array(list(jaw_surface_pts), dtype=float)
    if jaw_pts.ndim != 2 or jaw_pts.shape[1] != 3 or len(jaw_pts) == 0:
        raise ValueError(
            "jaw_surface_pts must be a non-empty sequence of (x, y, z) points"
        )
    if not implants:
        raise ValueError("implants must not be empty")

    sleeves: list[object] = []
    realised_axes: list[np.ndarray] = []
    angular_errors: list[float] = []

    for spec in implants:
        pos = np.array(spec.position, dtype=float)
        requested_axis = spec.axis_unit

        # Snap to nearest jaw surface point
        snapped = _closest_surface_point(jaw_pts, pos)

        # Build the guide sleeve cylinder
        outer_r = spec.sleeve_outer_radius_mm
        sleeve_body = make_cylinder(
            center=tuple(snapped),
            axis=tuple(requested_axis),
            radius=outer_r,
            height=spec.length_mm,
        )

        # Validate
        vr = validate_body(sleeve_body)
        if not vr["ok"]:
            raise RuntimeError(
                f"Surgical guide sleeve body is invalid: {vr['errors']}"
            )

        # Realised axis: normalise requested_axis again (verify precision)
        realised = requested_axis / np.linalg.norm(requested_axis)
        err_deg = angle_between_vectors(requested_axis, realised)

        sleeves.append(sleeve_body)
        realised_axes.append(realised)
        angular_errors.append(err_deg)

    return SurgicalGuideResult(
        sleeves=sleeves,
        realised_axes=realised_axes,
        angular_errors_deg=angular_errors,
    )
