"""Hermetic tests for brep_edge_metrics.py — BREP-SUM-EDGE-LENGTHS.

Oracles
-------
1.  Rectangle 100×50  → total = 300 mm (4 edges: 100+50+100+50)
2.  Unit cube (1 mm)  → total = 12 mm  (12 distinct edges, each 1 mm)
3.  Sphere wireframe  → 12 great-circle arcs radius=50 → 12 × 2π×50 ≈ 3769.91 mm
4.  Mixed-edge model  → one linear + one circular + one freeform edge
5.  Empty B-rep       → 0
6.  Precision oracle  → Gauss-Legendre vs analytic for circular NURBS within 1e-9
7.  edge_length_by_kind: open box → boundary < total, manifold > 0
8.  edges_by_curve_type: classification round-trips
9.  compute_edge_metrics: all fields consistent
10. Duplicate coedge doesn't double-count length
11. Fallback to 'length' field
12. Re-export from geom.__init__
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep_edge_metrics import (
    EdgeKindMetrics,
    EdgeCurveTypeMetrics,
    EdgeMetricsReport,
    compute_edge_metrics,
    edge_length_by_kind,
    edges_by_curve_type,
    total_edge_length,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _rect_faces(w: float = 100.0, h: float = 50.0):
    """Single rectangular face with 4 linear edges (open — all boundary)."""
    coords = {
        "v0": [0.0, 0.0, 0.0],
        "v1": [w,   0.0, 0.0],
        "v2": [w,   h,   0.0],
        "v3": [0.0, h,   0.0],
    }
    edges = [
        {"edge_id": "e01", "start": "v0", "end": "v1",
         "vertex_coords": coords,
         "curve": {"degree": 1, "control_points": [coords["v0"], coords["v1"]], "knots": [0, 0, 1, 1]}},
        {"edge_id": "e12", "start": "v1", "end": "v2",
         "vertex_coords": coords,
         "curve": {"degree": 1, "control_points": [coords["v1"], coords["v2"]], "knots": [0, 0, 1, 1]}},
        {"edge_id": "e23", "start": "v2", "end": "v3",
         "vertex_coords": coords,
         "curve": {"degree": 1, "control_points": [coords["v2"], coords["v3"]], "knots": [0, 0, 1, 1]}},
        {"edge_id": "e30", "start": "v3", "end": "v0",
         "vertex_coords": coords,
         "curve": {"degree": 1, "control_points": [coords["v3"], coords["v0"]], "knots": [0, 0, 1, 1]}},
    ]
    return [{"face_id": "f0", "edges": edges}]


def _cube_faces(size: float = 1.0):
    """Closed-manifold cube with vertex_coords for precise linear edge lengths."""
    from kerf_cad_core.geom.brep_connect_inspector import _make_cube_faces
    raw = _make_cube_faces(size=size)
    s = size
    v_coords = {
        "v000": [0.0, 0.0, 0.0],
        "v100": [s,   0.0, 0.0],
        "v010": [0.0, s,   0.0],
        "v110": [s,   s,   0.0],
        "v001": [0.0, 0.0, s  ],
        "v101": [s,   0.0, s  ],
        "v011": [0.0, s,   s  ],
        "v111": [s,   s,   s  ],
    }
    enriched = []
    for face in raw:
        new_edges = [{**e, "vertex_coords": v_coords} for e in face["edges"]]
        enriched.append({"face_id": face["face_id"], "edges": new_edges})
    return enriched


def _make_circle_nurbs_90deg(radius: float, center, start_angle_deg: float):
    """Return an edge dict for a 90° arc of a circle in the XY plane.

    Uses the exact Piegl-Tiller §7.3 quadratic rational NURBS for a 90° arc:
      P0, P2 are on-curve endpoints; P1 is the tangent-intersection corner.
    weights = [1, cos(π/4), 1]
    """
    c = np.asarray(center, dtype=float)
    a0 = math.radians(start_angle_deg)
    a2 = a0 + math.pi / 2
    p0 = c + radius * np.array([math.cos(a0), math.sin(a0), 0.0])
    p2 = c + radius * np.array([math.cos(a2), math.sin(a2), 0.0])
    # Tangent-intersection corner (Piegl-Tiller §7.3)
    p1 = c + radius * np.array([math.cos(a0) + math.cos(a2), math.sin(a0) + math.sin(a2), 0.0])
    w_mid = math.cos(math.pi / 4)  # ≈ 0.7071
    return {
        "curve": {
            "degree": 2,
            "control_points": [p0.tolist(), p1.tolist(), p2.tolist()],
            "knots": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
            "weights": [1.0, w_mid, 1.0],
        },
        "circle_radius": radius,
        "arc_angle": math.pi / 2,
    }


def _sphere_wireframe_faces(radius: float = 50.0):
    """12 full great circles, each expressed as circle_radius + arc_angle=2π."""
    faces = []
    for i in range(1, 13):
        edge = {
            "edge_id": f"e{i}",
            "start": f"v{i}_s",
            "end":   f"v{i}_s",  # closed loop
            "circle_radius": radius,
            "arc_angle": 2 * math.pi,
        }
        faces.append({"face_id": f"f{i}", "edges": [edge]})
    return faces


# ---------------------------------------------------------------------------
# 1. Rectangle oracle: 100×50 → 300 mm
# ---------------------------------------------------------------------------

def test_rectangle_total_edge_length():
    assert abs(total_edge_length(_rect_faces(100.0, 50.0)) - 300.0) < 1e-9


def test_rectangle_curve_type_all_linear():
    ct = edges_by_curve_type(_rect_faces(100.0, 50.0))
    assert abs(ct.linear - 300.0) < 1e-9
    assert ct.circular == 0.0
    assert ct.freeform == 0.0
    assert abs(ct.total - 300.0) < 1e-9


def test_rectangle_all_boundary():
    km = edge_length_by_kind(_rect_faces(100.0, 50.0))
    assert abs(km.boundary - 300.0) < 1e-9
    assert km.manifold == 0.0
    assert km.nonmanifold == 0.0
    assert abs(km.total - 300.0) < 1e-9


# ---------------------------------------------------------------------------
# 2. Unit cube oracle: 12 edges → 12 mm
# ---------------------------------------------------------------------------

def test_unit_cube_total_edge_length():
    assert abs(total_edge_length(_cube_faces(1.0)) - 12.0) < 1e-9


def test_unit_cube_all_manifold():
    km = edge_length_by_kind(_cube_faces(1.0))
    assert abs(km.manifold - 12.0) < 1e-9
    assert km.boundary == 0.0
    assert km.nonmanifold == 0.0


def test_unit_cube_all_linear():
    ct = edges_by_curve_type(_cube_faces(1.0))
    assert abs(ct.linear - 12.0) < 1e-9
    assert ct.circular == 0.0
    assert ct.freeform == 0.0


# ---------------------------------------------------------------------------
# 3. Sphere wireframe oracle: 12 × 2π × 50 ≈ 3769.91 mm
# ---------------------------------------------------------------------------

def test_sphere_wireframe_total():
    analytic = 12 * 2 * math.pi * 50.0
    total = total_edge_length(_sphere_wireframe_faces(50.0))
    assert abs(total - analytic) < 1e-9, f"expected {analytic:.6f}, got {total:.6f}"


def test_sphere_wireframe_all_circular():
    ct = edges_by_curve_type(_sphere_wireframe_faces(50.0))
    assert abs(ct.circular - 12 * 2 * math.pi * 50.0) < 1e-9
    assert ct.linear == 0.0
    assert ct.freeform == 0.0


# ---------------------------------------------------------------------------
# 4. Mixed-edge model: linear + circular + freeform
# ---------------------------------------------------------------------------

def _make_freeform_nurbs_edge():
    """Degree-3 cubic B-spline (S-curve, 4 CPs), non-rational."""
    cp = [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [1.0, 0.0, 0.0]]
    knots = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    return {"curve": {"degree": 3, "control_points": cp, "knots": knots, "weights": None}}


def test_mixed_edge_types():
    coords = {"va": [0.0, 0.0, 0.0], "vb": [5.0, 0.0, 0.0]}
    linear_edge = {
        "edge_id": "lin1", "start": "va", "end": "vb",
        "vertex_coords": coords,
        "curve": {"degree": 1,
                  "control_points": [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]],
                  "knots": [0.0, 0.0, 1.0, 1.0]},
    }
    circ_edge = {
        "edge_id": "circ1", "start": "vc", "end": "vd",
        "circle_radius": 10.0,
        "arc_angle": math.pi,   # half circle = π × r
    }
    ff_edge = {
        "edge_id": "ff1", "start": "ve", "end": "vf",
        **_make_freeform_nurbs_edge(),
    }
    faces = [
        {"face_id": "fl", "edges": [linear_edge]},
        {"face_id": "fc", "edges": [circ_edge]},
        {"face_id": "ff", "edges": [ff_edge]},
    ]
    ct = edges_by_curve_type(faces)
    assert abs(ct.linear - 5.0) < 1e-9
    assert abs(ct.circular - 10.0 * math.pi) < 1e-9
    assert ct.freeform > 0.0
    assert abs(ct.total - (ct.linear + ct.circular + ct.freeform)) < 1e-12


# ---------------------------------------------------------------------------
# 5. Empty B-rep → 0
# ---------------------------------------------------------------------------

def test_empty_total():
    assert total_edge_length([]) == 0.0


def test_empty_by_kind():
    km = edge_length_by_kind([])
    assert km.total == 0.0
    assert km.boundary == km.manifold == km.nonmanifold == 0.0


def test_empty_by_curve_type():
    ct = edges_by_curve_type([])
    assert ct.total == 0.0


def test_empty_report():
    r = compute_edge_metrics([])
    assert r.total_length == 0.0
    assert r.edge_count == 0
    assert r.warnings == []


# ---------------------------------------------------------------------------
# 6. Precision oracle: Gauss-Legendre on NURBS 90° arc within 1e-9 of analytic
# ---------------------------------------------------------------------------

def test_nurbs_circle_arc_gl_precision():
    """Gauss-Legendre on rational deg-2 NURBS (Piegl-Tiller §7.3) vs analytic."""
    radius = 50.0
    analytic_quarter = 0.5 * math.pi * radius  # π×r/2 ≈ 78.5398

    arc_info = _make_circle_nurbs_90deg(radius=radius, center=[0.0, 0.0, 0.0], start_angle_deg=0.0)
    # Force GL path: remove shortcut fields, keep only curve dict
    arc_no_hint = {"curve": arc_info["curve"]}

    face = {"face_id": "f1", "edges": [{
        "edge_id": "arc1", "start": "v0", "end": "v1",
        **arc_no_hint,
    }]}

    total = total_edge_length([face])
    assert abs(total - analytic_quarter) < 1e-9, (
        f"GL={total:.12f}, analytic={analytic_quarter:.12f}, "
        f"err={abs(total - analytic_quarter):.3e}"
    )


# ---------------------------------------------------------------------------
# 7. edge_length_by_kind: open box (5 faces)
# ---------------------------------------------------------------------------

def test_open_box_by_kind():
    from kerf_cad_core.geom.brep_connect_inspector import _make_cube_faces
    raw = _make_cube_faces(size=1.0)[:5]  # drop top
    s = 1.0
    vc = {
        "v000": [0,0,0], "v100": [s,0,0], "v010": [0,s,0], "v110": [s,s,0],
        "v001": [0,0,s], "v101": [s,0,s], "v011": [0,s,s], "v111": [s,s,s],
    }
    enriched = [
        {"face_id": f["face_id"],
         "edges": [{**e, "vertex_coords": vc} for e in f["edges"]]}
        for f in raw
    ]
    km = edge_length_by_kind(enriched)
    assert km.boundary > 0.0
    assert km.manifold > 0.0
    assert km.nonmanifold == 0.0
    assert abs(km.total - (km.boundary + km.manifold + km.nonmanifold)) < 1e-12


# ---------------------------------------------------------------------------
# 8. edges_by_curve_type: total consistency
# ---------------------------------------------------------------------------

def test_curve_type_total_consistent():
    ct = edges_by_curve_type(_cube_faces(3.0))
    assert abs(ct.total - (ct.linear + ct.circular + ct.freeform)) < 1e-12
    assert abs(ct.total - 12 * 3.0) < 1e-9


# ---------------------------------------------------------------------------
# 9. compute_edge_metrics: all fields consistent
# ---------------------------------------------------------------------------

def test_compute_edge_metrics_consistency():
    r = compute_edge_metrics(_cube_faces(2.0))
    expected = 12 * 2.0
    assert abs(r.total_length - expected) < 1e-9
    assert r.edge_count == 12
    assert abs(r.by_kind.total - expected) < 1e-9
    assert abs(r.by_curve_type.total - expected) < 1e-9
    assert abs(r.total_length - r.by_kind.total) < 1e-12
    assert abs(r.total_length - r.by_curve_type.total) < 1e-12


# ---------------------------------------------------------------------------
# 10. Shared edge counted once (manifold)
# ---------------------------------------------------------------------------

def test_shared_edge_counted_once():
    coords = {"va": [0.0, 0.0, 0.0], "vb": [10.0, 0.0, 0.0], "vc": [5.0, 5.0, 0.0]}
    shared = {"edge_id": "shared", "start": "va", "end": "vb", "vertex_coords": coords}
    face1 = {"face_id": "f1", "edges": [
        shared,
        {"edge_id": "e1b", "start": "vb", "end": "vc", "vertex_coords": coords},
        {"edge_id": "e1c", "start": "vc", "end": "va", "vertex_coords": coords},
    ]}
    face2 = {"face_id": "f2", "edges": [
        shared,
        {"edge_id": "e2b", "start": "va", "end": "vc", "vertex_coords": coords},
        {"edge_id": "e2c", "start": "vc", "end": "vb", "vertex_coords": coords},
    ]}
    r = compute_edge_metrics([face1, face2])
    assert r.edge_count == 5   # shared + 4 others
    km = edge_length_by_kind([face1, face2])
    assert km.manifold > 0.0   # "shared" is manifold (valence 2)


# ---------------------------------------------------------------------------
# 11. Fallback: length field
# ---------------------------------------------------------------------------

def test_fallback_length_field():
    faces = [{"face_id": "f0", "edges": [
        {"edge_id": "e1", "start": "va", "end": "vb", "length": 7.5},
        {"edge_id": "e2", "start": "vb", "end": "vc", "length": 3.0},
    ]}]
    assert abs(total_edge_length(faces) - 10.5) < 1e-9


# ---------------------------------------------------------------------------
# 12. Re-export from geom.__init__
# ---------------------------------------------------------------------------

def test_reexport_from_geom_init():
    from kerf_cad_core.geom import (  # noqa: F401
        total_edge_length as _tel,
        edge_length_by_kind as _elk,
        edges_by_curve_type as _ect,
        compute_edge_metrics as _cem,
        EdgeMetricsReport as _EMR,
        EdgeKindMetrics as _EKM,
        EdgeCurveTypeMetrics as _ECTM,
    )
    assert callable(_tel)
    assert callable(_elk)
    assert callable(_ect)
    assert callable(_cem)
