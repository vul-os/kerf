"""
kerf_bim.roof_geometry — Parametric roof geometry generator (GK-P29).

Generates B-rep ``Body`` geometry for hip, gable, shed (lean-to), and
mono-pitch roof types from a rectangular footprint and pitch parameters.

Also emits a minimal IFC ``IfcRoof`` property dict for export.

Roof types
----------
``hip``
    Four sloped faces meeting at a ridge or apex.  Classic pyramid / hip.
``gable``
    Two sloped faces on opposite sides; vertical gable triangles at the ends.
``shed``
    Single sloped face (lean-to) sloping from high plate to low plate.
``mono``
    Alias for ``shed`` (mono-pitch).

Coordinate convention
---------------------
All dimensions in **mm**.  The footprint is an axis-aligned rectangle
``(x_min, y_min) – (x_max, y_max)`` in the XY plane at ``base_z``.
The ridge runs parallel to the longer dimension (or X-axis for a square plan).

IFC mapping
-----------
Emits ``{"type": "IfcRoof", "predefined_type": ..., ...}`` suitable for
embedding in an IFC project dict.

References
----------
ISO 16739-1:2018 (IFC4) — IfcRoof, IfcRoofTypeEnum.
NBCC 2020 — roof slope / pitch conventions (H:12 system).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

__all__ = [
    "RoofType",
    "RoofParams",
    "RoofGeometry",
    "make_roof",
]

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

RoofType = str  # "hip" | "gable" | "shed" | "mono"

_VALID_TYPES = frozenset({"hip", "gable", "shed", "mono"})

_IFC_TYPE_MAP = {
    "hip":   "HIP_ROOF",
    "gable": "GABLE_ROOF",
    "shed":  "SHED_ROOF",
    "mono":  "SHED_ROOF",
}


class RoofValidationError(ValueError):
    """Raised when roof parameters are invalid."""


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class RoofParams:
    """Parametric roof definition.

    Parameters
    ----------
    roof_type:
        One of ``"hip"``, ``"gable"``, ``"shed"``, ``"mono"``.
    x_min, y_min, x_max, y_max:
        Footprint extents in mm.
    base_z:
        Elevation of the top of the wall plate (mm).
    pitch_deg:
        Roof pitch angle in degrees (measured from horizontal).  Must be
        in [1°, 89°].  For ``shed``/``mono``, this is the single pitch angle.
    overhang:
        Horizontal overhang beyond the wall plate on all sides (mm).
    material:
        Roof material identifier.
    """
    roof_type: RoofType = "gable"
    x_min: float = 0.0
    y_min: float = 0.0
    x_max: float = 10_000.0
    y_max: float = 6_000.0
    base_z: float = 3_000.0
    pitch_deg: float = 30.0
    overhang: float = 600.0
    material: str = "roof_tile"

    def __post_init__(self) -> None:
        if self.roof_type not in _VALID_TYPES:
            raise RoofValidationError(
                f"roof_type must be one of {sorted(_VALID_TYPES)}, got '{self.roof_type}'"
            )
        if self.x_max <= self.x_min:
            raise RoofValidationError("x_max must be > x_min")
        if self.y_max <= self.y_min:
            raise RoofValidationError("y_max must be > y_min")
        if not (1.0 <= self.pitch_deg <= 89.0):
            raise RoofValidationError(
                f"pitch_deg must be in [1, 89]; got {self.pitch_deg}"
            )

    @property
    def width(self) -> float:
        return self.y_max - self.y_min

    @property
    def length(self) -> float:
        return self.x_max - self.x_min

    @property
    def half_width(self) -> float:
        return self.width / 2.0

    @property
    def rise(self) -> float:
        """Ridge height above plate (mm), derived from half-width and pitch."""
        return self.half_width * math.tan(math.radians(self.pitch_deg))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass
class RoofGeometry:
    """Computed roof geometry.

    Attributes
    ----------
    params:
        Input parameters.
    body:
        B-rep ``Body`` (from ``kerf_cad_core.geom.brep``).
    ifc_dict:
        Dict conforming to IfcRoof for IFC export.
    ridge_z:
        Elevation of the ridge (mm).
    ridge_pts:
        3-D endpoints of the ridge line (for gable/hip; single point for
        pyramid/mono).
    faces_count:
        Number of sloped/gable faces in the B-rep shell.
    """
    params: RoofParams
    body: object   # kerf_cad_core.geom.brep.Body
    ifc_dict: dict
    ridge_z: float
    ridge_pts: List[np.ndarray]
    faces_count: int


# ---------------------------------------------------------------------------
# B-rep helpers
# ---------------------------------------------------------------------------

def _import_brep():
    from kerf_cad_core.geom.brep import (  # type: ignore
        Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane,
    )
    return Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane


def _make_face(pts3d: List[np.ndarray], Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane) -> "Face":
    """Build a planar :class:`Face` from an ordered list of 3-D corner points."""
    n = len(pts3d)
    coedges = []
    for i in range(n):
        p0, p1 = pts3d[i], pts3d[(i + 1) % n]
        v0, v1 = Vertex(p0), Vertex(p1)
        line = Line3(p0=p0, p1=p1)
        edge = Edge(curve=line, t0=0.0, t1=1.0, v_start=v0, v_end=v1)
        coedges.append(Coedge(edge=edge, orientation=True))
    loop = Loop(coedges=coedges, is_outer=True)
    x_ax = pts3d[1] - pts3d[0]
    n_x = np.linalg.norm(x_ax)
    if n_x > 1e-14:
        x_ax = x_ax / n_x
    y_ax = pts3d[2] - pts3d[0]
    surf = Plane(origin=pts3d[0], x_axis=x_ax, y_axis=y_ax)
    return Face(surface=surf, loops=[loop], orientation=True)


def _body_from_faces(faces, Body, Solid, Shell) -> "Body":
    shell = Shell(faces=faces, is_closed=True)
    return Body(solids=[Solid(shells=[shell])])


# ---------------------------------------------------------------------------
# Roof generators
# ---------------------------------------------------------------------------

def _hip_roof(p: RoofParams, *brep_types) -> Tuple[List["Face"], float, List[np.ndarray]]:
    """Hip roof: 4 sloped faces (triangular at ends, trapezoidal at sides)."""
    Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane = brep_types

    x0 = p.x_min - p.overhang
    x1 = p.x_max + p.overhang
    y0 = p.y_min - p.overhang
    y1 = p.y_max + p.overhang
    z0 = p.base_z

    # Actual rise is from half of the (width + 2*overhang)
    half_w = (y1 - y0) / 2.0
    rise = half_w * math.tan(math.radians(p.pitch_deg))
    ridge_z = z0 + rise

    # Ridge centre and length
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    half_w_full = (y1 - y0) / 2.0

    # Hip offset along X: how far the ridge ends are from the gable ends
    # Ridge length = length - width (classic symmetric hip)
    ridge_len = max(0.0, (x1 - x0) - (y1 - y0))

    if ridge_len < 1e-6:
        # Square plan → pyramid (single apex)
        apex = np.array([cx, cy, ridge_z])
        ridge_pts = [apex]

        # 4 triangular faces
        c0 = np.array([x0, y0, z0])
        c1 = np.array([x1, y0, z0])
        c2 = np.array([x1, y1, z0])
        c3 = np.array([x0, y1, z0])

        faces = [
            _make_face([c0, c1, apex], *brep_types),
            _make_face([c1, c2, apex], *brep_types),
            _make_face([c2, c3, apex], *brep_types),
            _make_face([c3, c0, apex], *brep_types),
        ]
    else:
        r0 = np.array([cx - ridge_len / 2.0, cy, ridge_z])
        r1 = np.array([cx + ridge_len / 2.0, cy, ridge_z])
        ridge_pts = [r0, r1]

        # Corners at plate level
        c0 = np.array([x0, y0, z0])
        c1 = np.array([x1, y0, z0])
        c2 = np.array([x1, y1, z0])
        c3 = np.array([x0, y1, z0])

        # Front face (y=y0 side): trapezoid c0-c1-r1-r0
        # Back face  (y=y1 side): trapezoid c3-r0-r1-c2 (reversed)
        # Left end   (x=x0 side): triangle  c0-r0-c3
        # Right end  (x=x1 side): triangle  c1-c2-r1

        faces = [
            _make_face([c0, c1, r1, r0], *brep_types),  # front slope
            _make_face([c2, c3, r0, r1], *brep_types),  # back slope
            _make_face([c0, r0, c3], *brep_types),      # left hip
            _make_face([c1, c2, r1], *brep_types),      # right hip
        ]

    return faces, ridge_z, ridge_pts


def _gable_roof(p: RoofParams, *brep_types) -> Tuple[List["Face"], float, List[np.ndarray]]:
    """Gable roof: 2 sloped faces + 2 vertical triangular gable faces."""
    Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane = brep_types

    x0 = p.x_min - p.overhang
    x1 = p.x_max + p.overhang
    y0 = p.y_min - p.overhang
    y1 = p.y_max + p.overhang
    z0 = p.base_z

    half_w = (y1 - y0) / 2.0
    rise = half_w * math.tan(math.radians(p.pitch_deg))
    ridge_z = z0 + rise

    cy = (y0 + y1) / 2.0
    r0 = np.array([x0, cy, ridge_z])
    r1 = np.array([x1, cy, ridge_z])
    ridge_pts = [r0, r1]

    c0 = np.array([x0, y0, z0])
    c1 = np.array([x1, y0, z0])
    c2 = np.array([x1, y1, z0])
    c3 = np.array([x0, y1, z0])

    faces = [
        _make_face([c0, c1, r1, r0], *brep_types),  # front slope
        _make_face([c2, c3, r0, r1], *brep_types),  # back slope
        _make_face([c0, r0, c3], *brep_types),       # left gable
        _make_face([c1, c2, r1], *brep_types),       # right gable
    ]

    return faces, ridge_z, ridge_pts


def _shed_roof(p: RoofParams, *brep_types) -> Tuple[List["Face"], float, List[np.ndarray]]:
    """Shed (mono-pitch) roof: single sloped face."""
    Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane = brep_types

    x0 = p.x_min - p.overhang
    x1 = p.x_max + p.overhang
    y0 = p.y_min - p.overhang
    y1 = p.y_max + p.overhang
    z0 = p.base_z

    # High side at y=y1, low at y=y0
    width = y1 - y0
    rise = width * math.tan(math.radians(p.pitch_deg))
    ridge_z = z0 + rise

    c0 = np.array([x0, y0, z0])
    c1 = np.array([x1, y0, z0])
    c2 = np.array([x1, y1, ridge_z])
    c3 = np.array([x0, y1, ridge_z])

    ridge_pts = [c3, c2]

    faces = [
        _make_face([c0, c1, c2, c3], *brep_types),  # single slope
    ]

    return faces, ridge_z, ridge_pts


_GENERATORS = {
    "hip":   _hip_roof,
    "gable": _gable_roof,
    "shed":  _shed_roof,
    "mono":  _shed_roof,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_roof(params: RoofParams) -> RoofGeometry:
    """Generate B-rep geometry and IFC dict for the given roof parameters.

    Parameters
    ----------
    params:
        :class:`RoofParams` defining the roof type, footprint, and pitch.

    Returns
    -------
    :class:`RoofGeometry`
        ``body`` is a B-rep ``Body`` (valid closed solid when the roof has
        all faces including gable/hip ends).  ``ifc_dict`` is a minimal
        IfcRoof property dict.
    """
    brep_types = _import_brep()
    Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane = brep_types

    gen = _GENERATORS[params.roof_type]
    faces, ridge_z, ridge_pts = gen(params, *brep_types)

    body = _body_from_faces(faces, Body, Solid, Shell)

    ifc_dict = {
        "type": "IfcRoof",
        "predefined_type": _IFC_TYPE_MAP[params.roof_type],
        "name": f"Roof ({params.roof_type.capitalize()})",
        "pitch_deg": params.pitch_deg,
        "ridge_z_mm": ridge_z,
        "material": params.material,
        "overhang_mm": params.overhang,
        "footprint": {
            "x_min": params.x_min, "y_min": params.y_min,
            "x_max": params.x_max, "y_max": params.y_max,
        },
    }

    return RoofGeometry(
        params=params,
        body=body,
        ifc_dict=ifc_dict,
        ridge_z=ridge_z,
        ridge_pts=ridge_pts,
        faces_count=len(faces),
    )
