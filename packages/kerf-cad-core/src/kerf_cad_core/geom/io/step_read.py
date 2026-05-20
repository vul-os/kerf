"""Pure-Python STEP Part 21 reader — AP203 / AP214 B-rep subset.  (GK-47)

Canonical location: ``kerf_cad_core.geom.io.step_read``.

Parses a STEP Part 21 file and constructs a Kerf :class:`~kerf_cad_core.geom.brep.Body`
from ``MANIFOLD_SOLID_BREP`` / ``CLOSED_SHELL`` entities as defined in
ADVANCED_BREP_SHAPE_REPRESENTATION.

Supported entity subset
-----------------------
Geometry primitives
    CARTESIAN_POINT, DIRECTION, VECTOR, AXIS2_PLACEMENT_3D,
    LINE, CIRCLE, B_SPLINE_CURVE_WITH_KNOTS (ignored — edges fall
    back to straight-line approximation)

Surfaces
    PLANE, CYLINDRICAL_SURFACE, SPHERICAL_SURFACE,
    CONICAL_SURFACE (treated as plane at apex), TOROIDAL_SURFACE

Topology
    VERTEX_POINT, EDGE_CURVE, ORIENTED_EDGE, EDGE_LOOP,
    FACE_OUTER_BOUND, FACE_BOUND, ADVANCED_FACE,
    CLOSED_SHELL, OPEN_SHELL, MANIFOLD_SOLID_BREP,
    ADVANCED_BREP_SHAPE_REPRESENTATION,
    BREP_WITH_VOIDS (outer shell only, voids skipped)

Everything else is silently ignored so that real AP214 files that
include product-structure, tolerance, colour, and material entities
still parse correctly.

Usage
-----
    from kerf_cad_core.geom.io.step_read import read_step

    body = read_step("path/to/part.step")
    # or
    body = read_step(pathlib.Path("part.step"))
    # or from a string
    body = read_step(step_text)

Returns a :class:`kerf_cad_core.geom.brep.Body`.
Raises :class:`StepReadError` on unrecoverable parse failures.

Deferred scope
--------------
* B-spline curve geometry: edges with B_SPLINE_CURVE_WITH_KNOTS fall
  back to a straight-line chord.  Full NURBS curve evaluation is deferred
  to GK-51 fidelity harness.
* BREP_WITH_VOIDS void shells: only the outer shell is imported; inner
  void shells are silently skipped.
* CONICAL_SURFACE and SURFACE_OF_REVOLUTION: approximated as a plane for
  topology purposes; parametric accuracy deferred.
"""

from __future__ import annotations

# Delegate to the full implementation in kerf_cad_core.io.step_reader.
# The geom.io sub-package is the *canonical* consumer-facing location
# (GK-47 roadmap entry); the implementation lives in io/step_reader.py
# so that the writer (step_writer.py) and reader share the same package
# boundary without a circular import.
#
# This shim keeps the public API at geom.io.step_read while the
# implementation is maintained in one place.

from kerf_cad_core.io.step_reader import (  # noqa: F401  (re-export)
    StepReadError,
    body_volume,
    read_step,
    _StepParser,  # exposed for advanced use / testing
    _build_shell,
    _build_face,
    _build_loop,
    _make_edge_curve,
)

__all__ = [
    "StepReadError",
    "read_step",
    "body_volume",
]
