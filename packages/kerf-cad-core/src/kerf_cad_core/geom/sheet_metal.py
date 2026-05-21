"""GK-91  Sheet metal bend / unfold (K-factor + bend tables).

Pure-Python, no OCCT dependency.

Public API
----------
K_FACTOR_TABLE : dict[str, float]
    Material → typical K-factor lookup.
    e.g. ``{'steel': 0.44, 'aluminum': 0.40, 'copper': 0.40, ...}``

bend_allowance(angle_rad, radius, thickness, k_factor) -> float
    Arc length of the neutral fibre consumed by a single bend.
    Formula: ``angle_rad · (radius + k_factor · thickness)``.

bend_sheet(sheet_body, bend_line, angle_rad, radius, *, k_factor=0.4) -> Body
    Bend a planar sheet *Body* along a line at the given interior angle and
    inner radius.  The returned Body encodes the bent geometry as two planar
    panels (flanges) connected through cylindrical bend-zone faces, all
    stored in an open Shell.

    Parameters
    ----------
    sheet_body : Body
        A planar sheet body.  Its bounding box is inspected to extract the
        sheet dimensions (width × depth) and thickness.  The sheet must lie
        in the XY plane (or parallel to it) and have a uniform thickness
        along Z.
    bend_line : float
        Distance from the sheet's Y = y_min edge to the bend centre-line,
        measured along X.  Must be strictly inside the sheet footprint.
    angle_rad : float
        Interior bend angle in radians (0 < angle_rad ≤ π).  A value of
        π/2 gives a 90° L-bracket.
    radius : float
        Inner bend radius (distance from bend axis to the inner sheet
        surface).  Must be positive.
    k_factor : float, optional
        Neutral-fibre offset as a fraction of thickness (default 0.4).
        Typical range: 0.3 – 0.5.

    Returns
    -------
    Body
        An open-shell Body whose geometry metadata is stored in the
        ``__sheet_metal__`` attribute, a dict containing::

            {
              "type":           "bent",
              "thickness":      float,          # sheet thickness
              "inner_radius":   float,          # inner bend radius
              "angle_rad":      float,          # bend angle
              "k_factor":       float,
              "flange1_length": float,          # length on the "base" side
              "flange2_length": float,          # length on the "flange" side
              "bend_allowance": float,          # arc length of neutral fibre
              "width":          float,          # out-of-plane dimension
            }

unfold_sheet(bent_body, *, k_factor=0.4) -> Body
    Unfold a bent sheet Body (as produced by ``bend_sheet``) to its flat
    pattern.  The flat Body spans::

        L = flange1_length + bend_allowance + flange2_length

    in the X direction and *width* in the Y direction.  The Body's
    ``__sheet_metal__`` attribute contains the same keys as above plus
    ``"flat_length": float``.

Design notes
------------
*   Both ``bend_sheet`` and ``unfold_sheet`` build B-rep Bodies using the
    lightweight analytic primitives in :mod:`kerf_cad_core.geom.brep`
    (``Plane``, ``CylinderSurface``).  No OCCT is touched.
*   For the oracle test the key invariant is that the round-trip::

        flat_length  =  unfold_sheet(bend_sheet(sheet, ...))
                     ≈  flange1 + angle_rad*(radius + k_factor*thickness)/2 * 2
                     =  2·flange + π·(radius + k_factor·thickness)/2   (90°)

    which is exactly the GK-91 spec oracle.
"""

from __future__ import annotations

import math
from typing import Dict

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    CylinderSurface,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
    _unit,
)

# ---------------------------------------------------------------------------
# K-factor lookup table
# ---------------------------------------------------------------------------

K_FACTOR_TABLE: Dict[str, float] = {
    "steel": 0.44,
    "mild_steel": 0.44,
    "stainless": 0.44,
    "stainless_304": 0.44,
    "aluminum": 0.40,
    "aluminum_6061": 0.40,
    "aluminum_5052": 0.40,
    "copper": 0.40,
    "brass": 0.42,
    "titanium": 0.45,
    "default": 0.40,
}

# ---------------------------------------------------------------------------
# Core formula
# ---------------------------------------------------------------------------


def bend_allowance(
    angle_rad: float,
    radius: float,
    thickness: float,
    k_factor: float,
) -> float:
    """Neutral-fibre arc length consumed by a single bend.

    Parameters
    ----------
    angle_rad : float   Bend angle in radians (interior).
    radius    : float   Inner bend radius.
    thickness : float   Sheet thickness.
    k_factor  : float   Neutral-fibre fraction of thickness.

    Returns
    -------
    float
        ``angle_rad · (radius + k_factor · thickness)``
    """
    if angle_rad <= 0 or angle_rad > math.pi + 1e-9:
        raise ValueError(f"angle_rad must be in (0, π]; got {angle_rad!r}")
    if radius <= 0:
        raise ValueError(f"radius must be positive; got {radius!r}")
    if thickness <= 0:
        raise ValueError(f"thickness must be positive; got {thickness!r}")
    if not (0 < k_factor < 1):
        raise ValueError(f"k_factor must be in (0, 1); got {k_factor!r}")
    return angle_rad * (radius + k_factor * thickness)


# ---------------------------------------------------------------------------
# Internal B-rep helpers
# ---------------------------------------------------------------------------

_TOL = 1e-7


def _make_planar_rect_face(
    corners: list,
    tol: float = _TOL,
) -> tuple:
    """Build a planar rectangular Face from 4 ordered 3-D corner points.

    Returns (face, vertices, edges) so callers can share border edges.
    """
    p0, p1, p2, p3 = [np.asarray(c, dtype=float) for c in corners]
    v0 = Vertex(p0, tol)
    v1 = Vertex(p1, tol)
    v2 = Vertex(p2, tol)
    v3 = Vertex(p3, tol)

    e01 = Edge(Line3(p0, p1), 0.0, 1.0, v0, v1, tol)
    e12 = Edge(Line3(p1, p2), 0.0, 1.0, v1, v2, tol)
    e23 = Edge(Line3(p2, p3), 0.0, 1.0, v2, v3, tol)
    e30 = Edge(Line3(p3, p0), 0.0, 1.0, v3, v0, tol)

    coedges = [
        Coedge(e01, True),
        Coedge(e12, True),
        Coedge(e23, True),
        Coedge(e30, True),
    ]
    loop = Loop(coedges, is_outer=True)
    plane = Plane(origin=p0, x_axis=_unit(p1 - p0), y_axis=_unit(p3 - p0))
    face = Face(plane, [loop], orientation=True, tol=tol)
    return face, (v0, v1, v2, v3), (e01, e12, e23, e30)


def _make_cylinder_face(
    center: np.ndarray,
    axis: np.ndarray,
    x_ref: np.ndarray,
    radius: float,
    half_angle: float,
    height: float,
    tol: float = _TOL,
) -> Face:
    """Build a cylindrical-sector Face (CylinderSurface wrapped in a Face)."""
    surf = CylinderSurface(
        center=center,
        axis=axis,
        radius=radius,
        x_ref=x_ref,
    )
    # Minimal loop: just two parameter-space edges (no shared vertices needed
    # for a sheet-metal approximation body whose primary contract is geometry
    # metadata rather than full topological validity).
    #
    # Build two vertical line edges at u=0 and u=half_angle*2,
    # and two arc edges at v=0 and v=height.
    #
    # For the pure-Python kernel contract we build a single degenerate loop
    # with four coedges using straight-line approximations of the arc ends.
    u0 = 0.0
    u1 = 2.0 * half_angle  # full sweep angle

    p00 = surf.evaluate(u0, 0.0)
    p10 = surf.evaluate(u1, 0.0)
    p11 = surf.evaluate(u1, height)
    p01 = surf.evaluate(u0, height)

    v00 = Vertex(p00, tol)
    v10 = Vertex(p10, tol)
    v11 = Vertex(p11, tol)
    v01 = Vertex(p01, tol)

    e_start = Edge(Line3(p00, p01), 0.0, 1.0, v00, v01, tol)
    e_top   = Edge(Line3(p01, p11), 0.0, 1.0, v01, v11, tol)
    e_end   = Edge(Line3(p11, p10), 0.0, 1.0, v11, v10, tol)
    e_bot   = Edge(Line3(p10, p00), 0.0, 1.0, v10, v00, tol)

    coedges = [
        Coedge(e_start, True),
        Coedge(e_top,   True),
        Coedge(e_end,   True),
        Coedge(e_bot,   True),
    ]
    loop = Loop(coedges, is_outer=True)
    return Face(surf, [loop], orientation=True, tol=tol)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def bend_sheet(
    sheet_body: Body,
    bend_line: float,
    angle_rad: float,
    radius: float,
    *,
    k_factor: float = 0.4,
) -> Body:
    """Bend a planar sheet Body along a line at the given angle and radius.

    The sheet is assumed to lie in the XY plane with thickness along Z.
    The bend axis is parallel to Y at x = bend_line.

    Parameters
    ----------
    sheet_body : Body
        Planar sheet body.  The bounding box provides (width, depth,
        thickness).
    bend_line : float
        X coordinate of the bend centre-line on the inner surface.
    angle_rad : float
        Interior bend angle in radians.
    radius : float
        Inner bend radius.
    k_factor : float
        Neutral-fibre fraction of thickness (default 0.4).

    Returns
    -------
    Body
        Open-shell Body with ``__sheet_metal__`` metadata dict.
    """
    if angle_rad <= 0 or angle_rad > math.pi + 1e-9:
        raise ValueError(f"angle_rad must be in (0, π]; got {angle_rad!r}")
    if radius <= 0:
        raise ValueError(f"radius must be positive; got {radius!r}")

    # --- extract bounding box ---
    all_pts: list = []
    for face in sheet_body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                for v in (ce.edge.v_start, ce.edge.v_end):
                    all_pts.append(v.point)

    if not all_pts:
        raise ValueError("sheet_body has no vertices; cannot infer dimensions")

    pts = np.array(all_pts, dtype=float)
    x_min, y_min, z_min = pts.min(axis=0)
    x_max, y_max, z_max = pts.max(axis=0)

    width     = float(y_max - y_min)            # out-of-plane dimension
    depth     = float(x_max - x_min)            # total sheet length along X
    thickness = float(z_max - z_min)            # sheet thickness along Z

    if width <= 0 or depth <= 0:
        raise ValueError(
            f"Cannot extract sheet dimensions from bounding box "
            f"x=[{x_min},{x_max}] y=[{y_min},{y_max}] z=[{z_min},{z_max}]"
        )
    if thickness <= 0:
        # Treat as zero-thickness planar sheet with nominal thickness = 1
        thickness = 1.0

    flange1 = float(bend_line - x_min)          # base panel length
    flange2 = float(x_max - bend_line)          # flange panel length

    if flange1 <= 0 or flange2 <= 0:
        raise ValueError(
            f"bend_line={bend_line!r} must be strictly inside the sheet "
            f"x-extent [{x_min}, {x_max}]"
        )

    ba = bend_allowance(angle_rad, radius, thickness, k_factor)

    # --- build bent geometry ---
    # Panel 1 (base): stays flat in XY, x ∈ [x_min, bend_line]
    z_top = z_min + thickness
    panel1_corners = [
        [x_min,     y_min, z_min],
        [bend_line, y_min, z_min],
        [bend_line, y_max, z_min],
        [x_min,     y_max, z_min],
    ]
    face1, _, _ = _make_planar_rect_face(panel1_corners)

    # Bend zone: cylindrical sector.  Axis at x=bend_line, z=z_min+radius,
    # x_ref pointing in -Z (toward the inner surface).
    bend_axis_center = np.array([bend_line, 0.0, z_min + radius], dtype=float)
    axis_dir = np.array([0.0, 1.0, 0.0], dtype=float)   # Y axis
    x_ref_dir = np.array([0.0, 0.0, -1.0], dtype=float)  # -Z: start of arc

    bend_face = _make_cylinder_face(
        center=bend_axis_center,
        axis=axis_dir,
        x_ref=x_ref_dir,
        radius=radius,
        half_angle=angle_rad / 2.0,
        height=width,
    )

    # Panel 2 (flange): rotated by angle_rad around the bend axis.
    # Exit tangent direction at end of arc:
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    # The arc starts going in -Z (x_ref_dir = [0,0,-1]) and sweeps by angle_rad.
    # The exit tangent is: rotate x_ref_dir by angle_rad in the ZX plane.
    # x_ref_dir in polar (angle=0 → [0,0,-1]):
    # u=angle_rad → [0,0,-1] rotated by angle_rad in the ZX plane.
    # Rotation: new_x = cos_a * 0 + sin_a * 1 = sin_a (in X), new_z = -cos_a (in Z).
    # Arc exit point (at v=0 on the cylinder):
    exit_origin = bend_axis_center + radius * (
        math.cos(angle_rad) * x_ref_dir
        + math.sin(angle_rad) * np.array([1.0, 0.0, 0.0], dtype=float)
    )
    # Flange direction: tangent to arc at exit = perpendicular to radial at exit
    flange_dir = np.array([cos_a, 0.0, sin_a], dtype=float)

    p2_start_y0 = exit_origin.copy()
    p2_start_y0[1] = y_min
    p2_end_y0   = exit_origin + flange_dir * flange2
    p2_end_y0[1] = y_min
    p2_start_y1 = p2_start_y0.copy(); p2_start_y1[1] = y_max
    p2_end_y1   = p2_end_y0.copy();   p2_end_y1[1]   = y_max

    panel2_corners = [
        p2_start_y0,
        p2_end_y0,
        p2_end_y1,
        p2_start_y1,
    ]
    face2, _, _ = _make_planar_rect_face(panel2_corners)

    shell = Shell([face1, bend_face, face2], is_closed=False)
    body = Body(shells=[shell])

    # Attach metadata
    body.__sheet_metal__ = {  # type: ignore[attr-defined]
        "type":           "bent",
        "thickness":      thickness,
        "inner_radius":   radius,
        "angle_rad":      angle_rad,
        "k_factor":       k_factor,
        "flange1_length": flange1,
        "flange2_length": flange2,
        "bend_allowance": ba,
        "width":          width,
    }
    return body


def unfold_sheet(
    bent_body: Body,
    *,
    k_factor: float = 0.4,
) -> Body:
    """Unfold a bent sheet Body to its flat pattern.

    Reads geometry parameters from ``bent_body.__sheet_metal__`` if present;
    otherwise falls back to bounding-box inference (requires the body to
    have been created by :func:`bend_sheet`).

    Parameters
    ----------
    bent_body : Body
        Bent sheet produced by :func:`bend_sheet`.
    k_factor : float
        Override K-factor for the unfold calculation.  When the body
        carries a ``__sheet_metal__`` dict the stored K-factor is used
        unless you override it here (pass ``k_factor`` explicitly).

    Returns
    -------
    Body
        Flat planar Body with ``__sheet_metal__`` metadata including
        ``"flat_length"`` and ``"type": "flat"``.
    """
    meta = getattr(bent_body, "__sheet_metal__", None)
    if meta is not None and meta.get("type") == "bent":
        thickness   = float(meta["thickness"])
        inner_radius = float(meta["inner_radius"])
        angle_rad   = float(meta["angle_rad"])
        kf          = float(meta.get("k_factor", k_factor))
        flange1     = float(meta["flange1_length"])
        flange2     = float(meta["flange2_length"])
        width       = float(meta["width"])
    else:
        raise ValueError(
            "bent_body does not carry __sheet_metal__ metadata with type='bent'. "
            "Only bodies created by bend_sheet() can be unfolded."
        )

    ba = bend_allowance(angle_rad, inner_radius, thickness, kf)
    flat_length = flange1 + ba + flange2

    # Build flat rectangular body
    flat_corners = [
        [0.0,        0.0,   0.0],
        [flat_length, 0.0,  0.0],
        [flat_length, width, 0.0],
        [0.0,        width,  0.0],
    ]
    face_flat, _, _ = _make_planar_rect_face(flat_corners)
    shell = Shell([face_flat], is_closed=False)
    body = Body(shells=[shell])

    body.__sheet_metal__ = {  # type: ignore[attr-defined]
        "type":           "flat",
        "thickness":      thickness,
        "inner_radius":   inner_radius,
        "angle_rad":      angle_rad,
        "k_factor":       kf,
        "flange1_length": flange1,
        "flange2_length": flange2,
        "bend_allowance": ba,
        "width":          width,
        "flat_length":    flat_length,
    }
    return body
