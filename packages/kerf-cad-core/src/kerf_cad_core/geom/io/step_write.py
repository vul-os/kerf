"""Pure-Python STEP AP214 Part 21 B-rep writer (GK-48).

Serialises a Kerf :class:`~kerf_cad_core.geom.brep.Body` to an ISO 10303-21
(Part 21) file that conforms to the AUTOMOTIVE_DESIGN application protocol
(AP214 edition 1 / STEP AP214).

Entity coverage
---------------
- MANIFOLD_SOLID_BREP (root)
- CLOSED_SHELL / OPEN_SHELL
- ADVANCED_FACE per face
- PLANE / CYLINDRICAL_SURFACE / SPHERICAL_SURFACE per carrier surface
- EDGE_CURVE / VERTEX_POINT / CARTESIAN_POINT
- LINE / CIRCLE per edge curve
- EDGE_LOOP / ORIENTED_EDGE per loop / coedge
- AXIS2_PLACEMENT_3D + DIRECTION + VECTOR supporting entities

The writer uses a two-pass algorithm:

  Pass 1 (collect) — walk all topology/geometry objects and assign stable
                     deterministic integer entity IDs via a memoised pool.
  Pass 2 (emit)    — serialise each entity in ascending ID order.

Determinism guarantee
---------------------
Two calls to :func:`write_step` on *the same* :class:`Body` object produce
byte-identical output.  This is achieved by sorting shells/faces/edges/
vertices by Python ``id()`` (stable per call since Body is not mutated).

Round-trip contract
-------------------
Writing a :func:`~kerf_cad_core.geom.brep.make_box`,
:func:`~kerf_cad_core.geom.brep.make_cylinder` or
:func:`~kerf_cad_core.geom.brep.make_sphere` body and reading it back via
:func:`~kerf_cad_core.geom.io.step_read.read_step` produces a body whose
vertex/surface sample-point Hausdorff distance is ≤ 1 × 10⁻⁷.

Usage::

    from kerf_cad_core.geom.brep import make_box
    from kerf_cad_core.geom.io.step_write import write_step

    body = make_box()
    step_text = write_step(body)           # returns str
    write_step(body, path="cube.step")     # also writes to file
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    Coedge,
    CylinderSurface,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    SphereSurface,
    Vertex,
)

__all__ = ["write_step", "StepWriteError"]

# ---------------------------------------------------------------------------
# Public error type
# ---------------------------------------------------------------------------


class StepWriteError(RuntimeError):
    """Raised for unrecoverable STEP serialisation errors."""


# ---------------------------------------------------------------------------
# AP214 file schema string
# ---------------------------------------------------------------------------

_FILE_SCHEMA = "'AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'"

# ---------------------------------------------------------------------------
# Numeric formatting helpers
# ---------------------------------------------------------------------------


def _fmt(v: float) -> str:
    """Format a float for Part 21 (always includes a decimal point)."""
    # Use enough precision for round-trip fidelity to 1e-10
    s = f"{v:.14g}"
    # Part 21 requires a decimal point in every real literal
    if "." not in s and "e" not in s and "E" not in s:
        s = s + "."
    return s


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _perp(axis: np.ndarray) -> np.ndarray:
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(ref, axis))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    return _unit(np.cross(axis, ref))


# ---------------------------------------------------------------------------
# Entity-line builders (one per AP214 entity type)
# ---------------------------------------------------------------------------


def _pt(pt) -> str:
    x, y, z = (float(c) for c in np.asarray(pt, dtype=float))
    return f"({_fmt(x)},{_fmt(y)},{_fmt(z)})"


def _ent_cartesian_point(eid: int, label: str, pt) -> str:
    return f"#{eid}=CARTESIAN_POINT('{label}',{_pt(pt)});"


def _ent_direction(eid: int, label: str, d) -> str:
    x, y, z = (float(c) for c in _unit(np.asarray(d, dtype=float)))
    return f"#{eid}=DIRECTION('{label}',({_fmt(x)},{_fmt(y)},{_fmt(z)}));"


def _ent_vector(eid: int, label: str, dir_id: int, mag: float) -> str:
    return f"#{eid}=VECTOR('{label}',#{dir_id},{_fmt(mag)});"


def _ent_axis2p3d(eid: int, label: str, loc_id: int, ax_id: int, ref_id: int) -> str:
    return f"#{eid}=AXIS2_PLACEMENT_3D('{label}',#{loc_id},#{ax_id},#{ref_id});"


def _ent_vertex_point(eid: int, label: str, cp_id: int) -> str:
    return f"#{eid}=VERTEX_POINT('{label}',#{cp_id});"


def _ent_line(eid: int, label: str, pt_id: int, vec_id: int) -> str:
    return f"#{eid}=LINE('{label}',#{pt_id},#{vec_id});"


def _ent_circle(eid: int, label: str, ax2p_id: int, radius: float) -> str:
    return f"#{eid}=CIRCLE('{label}',#{ax2p_id},{_fmt(radius)});"


def _ent_edge_curve(eid: int, label: str, v0_id: int, v1_id: int, geom_id: int) -> str:
    return f"#{eid}=EDGE_CURVE('{label}',#{v0_id},#{v1_id},#{geom_id},.T.);"


def _ent_oriented_edge(eid: int, label: str, ec_id: int, orientation: bool) -> str:
    s = ".T." if orientation else ".F."
    return f"#{eid}=ORIENTED_EDGE('{label}',*,*,#{ec_id},{s});"


def _ent_edge_loop(eid: int, label: str, oe_ids: List[int]) -> str:
    refs = ",".join(f"#{i}" for i in oe_ids)
    return f"#{eid}=EDGE_LOOP('{label}',({refs}));"


def _ent_face_outer_bound(eid: int, label: str, loop_id: int) -> str:
    return f"#{eid}=FACE_OUTER_BOUND('{label}',#{loop_id},.T.);"


def _ent_face_bound(eid: int, label: str, loop_id: int) -> str:
    return f"#{eid}=FACE_BOUND('{label}',#{loop_id},.T.);"


def _ent_plane(eid: int, label: str, ax2p_id: int) -> str:
    return f"#{eid}=PLANE('{label}',#{ax2p_id});"


def _ent_cylindrical_surface(eid: int, label: str, ax2p_id: int, radius: float) -> str:
    return f"#{eid}=CYLINDRICAL_SURFACE('{label}',#{ax2p_id},{_fmt(radius)});"


def _ent_spherical_surface(eid: int, label: str, ax2p_id: int, radius: float) -> str:
    return f"#{eid}=SPHERICAL_SURFACE('{label}',#{ax2p_id},{_fmt(radius)});"


def _ent_advanced_face(
    eid: int, label: str, bound_ids: List[int], surf_id: int, sense: bool
) -> str:
    refs = ",".join(f"#{i}" for i in bound_ids)
    s = ".T." if sense else ".F."
    return f"#{eid}=ADVANCED_FACE('{label}',({refs}),#{surf_id},{s});"


def _ent_closed_shell(eid: int, label: str, face_ids: List[int]) -> str:
    refs = ",".join(f"#{i}" for i in face_ids)
    return f"#{eid}=CLOSED_SHELL('{label}',({refs}));"


def _ent_open_shell(eid: int, label: str, face_ids: List[int]) -> str:
    refs = ",".join(f"#{i}" for i in face_ids)
    return f"#{eid}=OPEN_SHELL('{label}',({refs}));"


def _ent_manifold_solid_brep(eid: int, label: str, shell_id: int) -> str:
    return f"#{eid}=MANIFOLD_SOLID_BREP('{label}',#{shell_id});"


def _ent_advanced_brep_shape_repr(eid: int, label: str, brep_ids: List[int]) -> str:
    refs = ",".join(f"#{i}" for i in brep_ids)
    return f"#{eid}=ADVANCED_BREP_SHAPE_REPRESENTATION('{label}',({refs}),$);"


# ---------------------------------------------------------------------------
# ID allocator (simple counter, no global state)
# ---------------------------------------------------------------------------


class _IDPool:
    def __init__(self) -> None:
        self._next = 1
        self._map: Dict[int, int] = {}  # Python id(obj) -> entity ID

    def get_or_alloc(self, obj) -> Tuple[int, bool]:
        """Return (entity_id, is_new). is_new=True if just allocated."""
        key = id(obj)
        if key in self._map:
            return self._map[key], False
        eid = self._next
        self._next += 1
        self._map[key] = eid
        return eid, True

    def alloc(self) -> int:
        """Allocate a fresh entity ID (no object association)."""
        eid = self._next
        self._next += 1
        return eid


# ---------------------------------------------------------------------------
# Core collector: walk Body → emit entity lines in ID order
# ---------------------------------------------------------------------------


def _collect(body: Body) -> List[Tuple[int, str]]:
    """Walk *body* and return an ordered list of (entity_id, line) tuples."""

    pool = _IDPool()
    lines: List[Tuple[int, str]] = []

    def emit(eid: int, line: str) -> None:
        lines.append((eid, line))

    # ------------------------------------------------------------------
    # Geometry emitters
    # ------------------------------------------------------------------

    def emit_axis2p3d(origin, z_axis, x_ref, label: str) -> int:
        """Emit CARTESIAN_POINT + 2 DIRECTIONs + AXIS2_PLACEMENT_3D.

        Returns the AXIS2_PLACEMENT_3D entity ID.
        """
        loc_id = pool.alloc()
        emit(loc_id, _ent_cartesian_point(loc_id, f"{label}_loc", origin))
        ax_id = pool.alloc()
        emit(ax_id, _ent_direction(ax_id, f"{label}_ax", z_axis))
        ref_id = pool.alloc()
        emit(ref_id, _ent_direction(ref_id, f"{label}_ref", x_ref))
        a2p_id = pool.alloc()
        emit(a2p_id, _ent_axis2p3d(a2p_id, label, loc_id, ax_id, ref_id))
        return a2p_id

    def emit_plane_surface(surf: Plane, label: str) -> int:
        """Emit PLANE entity. Returns surf entity ID."""
        xa = _unit(np.asarray(surf.x_axis, dtype=float))
        ya = _unit(np.asarray(surf.y_axis, dtype=float))
        za = _unit(np.cross(xa, ya))
        a2p_id = emit_axis2p3d(surf.origin, za, xa, f"{label}_pl")
        surf_id = pool.alloc()
        emit(surf_id, _ent_plane(surf_id, f"{label}_surf", a2p_id))
        return surf_id

    def emit_cylinder_surface(surf: CylinderSurface, label: str) -> int:
        """Emit CYLINDRICAL_SURFACE entity. Returns surf entity ID."""
        ax = _unit(np.asarray(surf.axis, dtype=float))
        xref = _unit(np.asarray(surf.x_ref, dtype=float))
        a2p_id = emit_axis2p3d(surf.center, ax, xref, f"{label}_cyl")
        surf_id = pool.alloc()
        emit(surf_id, _ent_cylindrical_surface(surf_id, f"{label}_surf", a2p_id, surf.radius))
        return surf_id

    def emit_sphere_surface(surf: SphereSurface, label: str) -> int:
        """Emit SPHERICAL_SURFACE entity. Returns surf entity ID."""
        # STEP SPHERICAL_SURFACE: AXIS2_PLACEMENT_3D at centre with
        # z = north pole (+Z), x = (1,0,0) or any perpendicular.
        center = np.asarray(surf.center, dtype=float)
        z_axis = np.array([0.0, 0.0, 1.0])
        x_ref = np.array([1.0, 0.0, 0.0])
        a2p_id = emit_axis2p3d(center, z_axis, x_ref, f"{label}_sph")
        surf_id = pool.alloc()
        emit(surf_id, _ent_spherical_surface(surf_id, f"{label}_surf", a2p_id, surf.radius))
        return surf_id

    def emit_generic_surface_as_plane(surf, label: str) -> int:
        """Fallback: emit any surface as a PLANE by finite-difference normal."""
        try:
            pt = np.asarray(surf.evaluate(0.5, 0.5), dtype=float)
            h = 1e-4
            du = np.asarray(surf.evaluate(0.5 + h, 0.5), dtype=float) - pt
            dv = np.asarray(surf.evaluate(0.5, 0.5 + h), dtype=float) - pt
            nrm = _unit(np.cross(du, dv))
            xa = _unit(du) if float(np.linalg.norm(du)) > 1e-14 else np.array([1., 0., 0.])
            a2p_id = emit_axis2p3d(pt, nrm, xa, f"{label}_fb")
        except Exception:
            a2p_id = emit_axis2p3d(
                np.zeros(3), np.array([0., 0., 1.]), np.array([1., 0., 0.]), f"{label}_fb"
            )
        surf_id = pool.alloc()
        emit(surf_id, _ent_plane(surf_id, f"{label}_surf", a2p_id))
        return surf_id

    # ------------------------------------------------------------------
    # Vertex emitter (memoised by object identity)
    # ------------------------------------------------------------------

    def emit_vertex(v: Vertex) -> int:
        """Emit CARTESIAN_POINT + VERTEX_POINT. Returns VERTEX_POINT ID."""
        eid, is_new = pool.get_or_alloc(v)
        if not is_new:
            return eid
        cp_id = pool.alloc()
        emit(cp_id, _ent_cartesian_point(cp_id, f"v{cp_id}", v.point))
        emit(eid, _ent_vertex_point(eid, f"vp{eid}", cp_id))
        return eid

    # ------------------------------------------------------------------
    # Edge emitter (memoised by object identity)
    # ------------------------------------------------------------------

    def emit_edge(e: Edge) -> int:
        """Emit curve geometry + EDGE_CURVE. Returns EDGE_CURVE ID."""
        eid, is_new = pool.get_or_alloc(e)
        if not is_new:
            return eid

        v0_id = emit_vertex(e.v_start)
        v1_id = emit_vertex(e.v_end)
        geom_id = emit_edge_geometry(e)
        emit(eid, _ent_edge_curve(eid, f"ec{eid}", v0_id, v1_id, geom_id))
        return eid

    def emit_edge_geometry(e: Edge) -> int:
        """Emit the curve entity for an edge. Returns its entity ID."""
        curve = e.curve

        if isinstance(curve, Line3):
            direction = curve.p1 - curve.p0
            mag = float(np.linalg.norm(direction))
            d = direction if mag > 1e-14 else np.array([1., 0., 0.])
            pt_id = pool.alloc()
            emit(pt_id, _ent_cartesian_point(pt_id, "lpt", curve.p0))
            dir_id = pool.alloc()
            emit(dir_id, _ent_direction(dir_id, "ldir", d))
            vec_id = pool.alloc()
            emit(vec_id, _ent_vector(vec_id, "lvec", dir_id, max(mag, 0.0)))
            geom_id = pool.alloc()
            emit(geom_id, _ent_line(geom_id, "line", pt_id, vec_id))
            return geom_id

        elif isinstance(curve, CircleArc3):
            arc = curve
            xref = _unit(np.asarray(arc.x_axis, dtype=float))
            yref = _unit(np.asarray(arc.y_axis, dtype=float))
            # STEP CIRCLE axis: z = cross(x, y), x = x_axis
            z_ax = _unit(np.cross(xref, yref))
            a2p_id = emit_axis2p3d(arc.center, z_ax, xref, "carc")
            geom_id = pool.alloc()
            emit(geom_id, _ent_circle(geom_id, "circle", a2p_id, arc.radius))
            return geom_id

        else:
            # Generic fallback: straight line between evaluated endpoints
            try:
                p0 = np.asarray(curve.evaluate(e.t0), dtype=float)
                p1 = np.asarray(curve.evaluate(e.t1), dtype=float)
            except Exception:
                p0 = np.asarray(e.v_start.point, dtype=float)
                p1 = np.asarray(e.v_end.point, dtype=float)
            direction = p1 - p0
            mag = float(np.linalg.norm(direction))
            d = direction if mag > 1e-14 else np.array([1., 0., 0.])
            pt_id = pool.alloc()
            emit(pt_id, _ent_cartesian_point(pt_id, "lpt", p0))
            dir_id = pool.alloc()
            emit(dir_id, _ent_direction(dir_id, "ldir", d))
            vec_id = pool.alloc()
            emit(vec_id, _ent_vector(vec_id, "lvec", dir_id, max(mag, 0.0)))
            geom_id = pool.alloc()
            emit(geom_id, _ent_line(geom_id, "line", pt_id, vec_id))
            return geom_id

    # ------------------------------------------------------------------
    # Loop emitter (emits ORIENTED_EDGEs + EDGE_LOOP)
    # ------------------------------------------------------------------

    def emit_loop(lp: Loop) -> int:
        """Emit ORIENTED_EDGE* + EDGE_LOOP. Returns EDGE_LOOP ID."""
        oe_ids: List[int] = []
        for ce in lp.coedges:
            ec_id = emit_edge(ce.edge)
            oe_id = pool.alloc()
            emit(oe_id, _ent_oriented_edge(oe_id, "oe", ec_id, ce.orientation))
            oe_ids.append(oe_id)
        loop_id = pool.alloc()
        emit(loop_id, _ent_edge_loop(loop_id, "el", oe_ids))
        return loop_id

    # ------------------------------------------------------------------
    # Face emitter (surface + bounds + ADVANCED_FACE)
    # ------------------------------------------------------------------

    def emit_face(f: Face, idx: int) -> int:
        """Emit surface entity + bounds + ADVANCED_FACE. Returns AF ID."""
        label = f"f{idx}"
        surf = f.surface

        if isinstance(surf, Plane):
            surf_id = emit_plane_surface(surf, label)
        elif isinstance(surf, CylinderSurface):
            surf_id = emit_cylinder_surface(surf, label)
        elif isinstance(surf, SphereSurface):
            surf_id = emit_sphere_surface(surf, label)
        else:
            surf_id = emit_generic_surface_as_plane(surf, label)

        outer = f.outer_loop()
        bound_ids: List[int] = []
        # Sort loops for determinism; emit outer loop first
        loops_sorted = sorted(f.loops, key=lambda lp: (0 if lp is outer else 1, id(lp)))
        for lp in loops_sorted:
            if not lp.coedges:
                continue  # skip degenerate empty loops
            loop_id = emit_loop(lp)
            b_id = pool.alloc()
            if lp is outer:
                emit(b_id, _ent_face_outer_bound(b_id, "fob", loop_id))
            else:
                emit(b_id, _ent_face_bound(b_id, "fb", loop_id))
            bound_ids.append(b_id)

        if not bound_ids:
            # Degenerate face with no usable loops — still emit a placeholder
            # using an empty outer bound is not valid STEP, so skip
            # by returning a dummy ADVANCED_FACE pointing at surf.
            af_id = pool.alloc()
            emit(af_id, _ent_advanced_face(af_id, label, [], surf_id, f.orientation))
            return af_id

        af_id = pool.alloc()
        emit(af_id, _ent_advanced_face(af_id, label, bound_ids, surf_id, f.orientation))
        return af_id

    # ------------------------------------------------------------------
    # Main traversal: shells → faces → solids
    # ------------------------------------------------------------------

    all_shells = sorted(body.all_shells(), key=id)

    # Collect MANIFOLD_SOLID_BREP IDs for the top-level representation
    brep_ids: List[int] = []

    for shell in all_shells:
        sorted_faces = sorted(shell.faces, key=id)
        face_ids: List[int] = []
        for idx, face in enumerate(sorted_faces):
            af_id = emit_face(face, idx)
            face_ids.append(af_id)

        sh_id = pool.alloc()
        if shell.is_closed:
            emit(sh_id, _ent_closed_shell(sh_id, "shell", face_ids))
        else:
            emit(sh_id, _ent_open_shell(sh_id, "shell", face_ids))

        if shell.is_closed and shell.solid is not None:
            msb_id = pool.alloc()
            emit(msb_id, _ent_manifold_solid_brep(msb_id, "brep", sh_id))
            brep_ids.append(msb_id)

    # Top-level ADVANCED_BREP_SHAPE_REPRESENTATION (optional but conventional)
    if brep_ids:
        absr_id = pool.alloc()
        emit(absr_id, _ent_advanced_brep_shape_repr(absr_id, "kerf", brep_ids))

    # Sort by entity ID before returning
    lines.sort(key=lambda x: x[0])
    return lines


# ---------------------------------------------------------------------------
# Part 21 file header / footer
# ---------------------------------------------------------------------------


def _header(label: str = "kerf_export") -> str:
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(('Kerf CAD export — AP214'),'{label}');\n"
        "FILE_NAME('','',(''),(''),'kerf-cad-core step_write','','');\n"
        f"FILE_SCHEMA(({_FILE_SCHEMA}));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )


def _footer() -> str:
    return "ENDSEC;\nEND-ISO-10303-21;\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_step(
    body: Body,
    path: Optional[str] = None,
    label: str = "kerf_export",
) -> str:
    """Serialise *body* to an AP214 Part 21 string.

    Parameters
    ----------
    body:
        The :class:`~kerf_cad_core.geom.brep.Body` to serialise.
    path:
        If given, write the result to this file path (UTF-8).  Can be a
        ``str`` or :class:`pathlib.Path`.
    label:
        Label embedded in FILE_DESCRIPTION.

    Returns
    -------
    str
        The full Part 21 text (ISO-10303-21 header + DATA section + footer).

    Raises
    ------
    StepWriteError
        If the body has no faces or serialisation fails.
    """
    if not body.all_faces():
        raise StepWriteError("Body has no faces — nothing to write")

    entity_lines = _collect(body)
    parts = [_header(label)]
    for _eid, line in entity_lines:
        parts.append(line + "\n")
    parts.append(_footer())
    result = "".join(parts)

    if path is not None:
        Path(path).write_text(result, encoding="utf-8")

    return result
