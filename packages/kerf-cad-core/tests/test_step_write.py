"""Tests for GK-48: pure-Python STEP AP214 B-rep writer (geom/io/step_write.py).

Oracle assertions
-----------------
1. write_step(body) returns a valid ISO 10303-21 string for box, cylinder,
   sphere bodies:
   - Starts with ISO-10303-21; ends with END-ISO-10303-21;
   - Contains AUTOMOTIVE_DESIGN schema
   - Contains expected entity types (MANIFOLD_SOLID_BREP, ADVANCED_FACE,
     CYLINDRICAL_SURFACE, SPHERICAL_SURFACE as applicable)

2. Write→read round-trip Hausdorff distance ≤ 1e-7 on:
   - box (all planar faces)
   - cylinder (1 cylindrical + 2 planar faces)
   - sphere (1 spherical face)

3. Determinism: two calls on the same body yield byte-identical output.

4. write_step raises StepWriteError on an empty (no-face) body.

5. Import paths — canonical geom.io.step_write and geom re-export.
"""
from __future__ import annotations

import math
import re
import tempfile
import os
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Canonical import paths (GK-48 deliverable)
# ---------------------------------------------------------------------------
from kerf_cad_core.geom.io.step_write import write_step, StepWriteError
from kerf_cad_core.geom.io.step_read import read_step
from kerf_cad_core.geom.brep import (
    make_box,
    make_cylinder,
    make_sphere,
    Body,
    Shell,
    Solid,
    validate_body,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_entity(text: str, name: str) -> int:
    """Count occurrences of '=NAME(' in DATA section."""
    data = text.split("DATA;", 1)[-1].split("ENDSEC;", 1)[0]
    return len(re.findall(rf"=\s*{re.escape(name)}\s*\(", data))


def _sample_face_points(body: Body, n_per_face: int = 30) -> np.ndarray:
    """Sample n_per_face vertex positions from all face loop coedges."""
    pts = []
    for face in body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                try:
                    pts.append(np.asarray(ce.start_point(), dtype=float))
                except Exception:
                    pass
    if not pts:
        return np.zeros((0, 3))
    return np.array(pts, dtype=float)


def _hausdorff(pts_a: np.ndarray, pts_b: np.ndarray) -> float:
    """One-sided Hausdorff: max over pts_a of min distance to pts_b."""
    if len(pts_a) == 0 or len(pts_b) == 0:
        return float("inf")
    # Use broadcasting for small point sets
    diffs = pts_a[:, None, :] - pts_b[None, :, :]  # (A, B, 3)
    dists = np.linalg.norm(diffs, axis=-1)  # (A, B)
    min_dists = dists.min(axis=1)  # (A,)
    return float(min_dists.max())


def _symmetric_hausdorff(pts_a: np.ndarray, pts_b: np.ndarray) -> float:
    return max(_hausdorff(pts_a, pts_b), _hausdorff(pts_b, pts_a))


# ---------------------------------------------------------------------------
# 1. Basic structure tests
# ---------------------------------------------------------------------------

def test_gk48_box_is_valid_part21():
    """write_step(box) must produce a valid ISO 10303-21 string."""
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    assert text.strip().startswith("ISO-10303-21;"), "Missing ISO-10303-21 opening"
    assert text.strip().endswith("END-ISO-10303-21;"), "Missing END-ISO-10303-21 closing"
    assert "DATA;" in text and "ENDSEC;" in text, "Missing DATA/ENDSEC sections"


def test_gk48_box_has_automotive_design_schema():
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    m = re.search(r"FILE_SCHEMA\s*\((.+?)\)\s*;", text, re.DOTALL)
    assert m, "No FILE_SCHEMA found"
    assert "AUTOMOTIVE_DESIGN" in m.group(1), (
        f"Expected AUTOMOTIVE_DESIGN in FILE_SCHEMA, got: {m.group(1)!r}"
    )


def test_gk48_box_has_6_advanced_faces():
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    count = _count_entity(text, "ADVANCED_FACE")
    assert count == 6, f"Expected 6 ADVANCED_FACE, got {count}"


def test_gk48_box_has_manifold_solid_brep():
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    count = _count_entity(text, "MANIFOLD_SOLID_BREP")
    assert count >= 1, "Expected at least 1 MANIFOLD_SOLID_BREP"


def test_gk48_box_has_planes():
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    count = _count_entity(text, "PLANE")
    assert count >= 6, f"Expected ≥6 PLANE entities for a box, got {count}"


def test_gk48_cylinder_has_3_advanced_faces():
    body = make_cylinder(radius=1.0, height=2.0)
    text = write_step(body)
    count = _count_entity(text, "ADVANCED_FACE")
    assert count == 3, f"Expected 3 ADVANCED_FACE for cylinder, got {count}"


def test_gk48_cylinder_has_cylindrical_surface():
    body = make_cylinder(radius=1.0, height=2.0)
    text = write_step(body)
    count = _count_entity(text, "CYLINDRICAL_SURFACE")
    assert count >= 1, "Expected CYLINDRICAL_SURFACE in cylinder export"


def test_gk48_sphere_has_spherical_surface():
    body = make_sphere(center=(0.0, 0.0, 0.0), radius=1.0)
    text = write_step(body)
    count = _count_entity(text, "SPHERICAL_SURFACE")
    assert count >= 1, "Expected SPHERICAL_SURFACE in sphere export"


def test_gk48_sphere_has_1_advanced_face():
    body = make_sphere(radius=1.0)
    text = write_step(body)
    count = _count_entity(text, "ADVANCED_FACE")
    assert count == 1, f"Expected 1 ADVANCED_FACE for sphere, got {count}"


# ---------------------------------------------------------------------------
# 2. Entity ID ordering
# ---------------------------------------------------------------------------

def test_gk48_entity_ids_ascending():
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    data = text.split("DATA;", 1)[-1].split("ENDSEC;", 1)[0]
    ids = [int(m.group(1)) for m in re.finditer(r"^#(\d+)\s*=", data, re.MULTILINE)]
    assert ids, "No entity IDs found"
    assert ids == sorted(ids), "Entity IDs not in ascending order"
    assert min(ids) >= 1, "Entity IDs must be ≥ 1"


def test_gk48_every_entity_line_ends_with_semicolon():
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    data = text.split("DATA;", 1)[-1].split("ENDSEC;", 1)[0]
    for line in data.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        assert line.endswith(";"), f"Entity line missing semicolon: {line!r}"


# ---------------------------------------------------------------------------
# 3. Determinism
# ---------------------------------------------------------------------------

def test_gk48_deterministic_box():
    body = make_box(size=(1.0, 1.0, 1.0))
    assert write_step(body) == write_step(body), "write_step is not deterministic"


def test_gk48_deterministic_cylinder():
    body = make_cylinder(radius=2.0, height=3.0)
    assert write_step(body) == write_step(body), "write_step is not deterministic for cylinder"


def test_gk48_deterministic_sphere():
    body = make_sphere(radius=5.0)
    assert write_step(body) == write_step(body), "write_step is not deterministic for sphere"


# ---------------------------------------------------------------------------
# 4. File write
# ---------------------------------------------------------------------------

def test_gk48_write_to_path_str():
    body = make_box(size=(1.0, 1.0, 1.0))
    text = write_step(body)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".step", delete=False) as fh:
        tmp_path = fh.name
    try:
        write_step(body, path=tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as fh:
            disk_text = fh.read()
        assert disk_text == text
    finally:
        os.unlink(tmp_path)


def test_gk48_write_to_path_pathlib():
    body = make_box(size=(2.0, 3.0, 4.0))
    text = write_step(body)
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as fh:
        tmp_path = Path(fh.name)
    try:
        write_step(body, path=tmp_path)
        assert tmp_path.read_text(encoding="utf-8") == text
    finally:
        tmp_path.unlink()


# ---------------------------------------------------------------------------
# 5. Error path
# ---------------------------------------------------------------------------

def test_gk48_raises_on_empty_body():
    """write_step must raise StepWriteError for a body with no faces."""
    empty = Body(solids=[], shells=[], wires=[])
    with pytest.raises(StepWriteError):
        write_step(empty)


# ---------------------------------------------------------------------------
# 6. Import paths
# ---------------------------------------------------------------------------

def test_gk48_import_from_geom_io():
    from kerf_cad_core.geom.io.step_write import write_step as _ws
    body = make_box()
    text = _ws(body)
    assert "ISO-10303-21;" in text


def test_gk48_import_via_geom():
    from kerf_cad_core.geom import write_step as _ws, StepWriteError as _e
    body = make_box()
    text = _ws(body)
    assert "ADVANCED_FACE" in text


# ---------------------------------------------------------------------------
# 7. Round-trip oracle: write → read → Hausdorff ≤ 1e-7
# ---------------------------------------------------------------------------

_HAUSDORFF_TOL = 1e-7


def _round_trip_hausdorff(body: Body) -> float:
    """Write body to STEP, read it back, return symmetric Hausdorff on vertices."""
    text = write_step(body)
    recovered = read_step(text, validate=False)
    pts_orig = _sample_face_points(body)
    pts_recv = _sample_face_points(recovered)
    return _symmetric_hausdorff(pts_orig, pts_recv)


def test_gk48_roundtrip_box_hausdorff():
    """Oracle: box write→read Hausdorff ≤ 1e-7."""
    body = make_box(size=(1.0, 1.0, 1.0))
    h = _round_trip_hausdorff(body)
    assert h <= _HAUSDORFF_TOL, f"Box round-trip Hausdorff {h:.3e} > {_HAUSDORFF_TOL}"


def test_gk48_roundtrip_box_non_unit():
    """Oracle: non-unit box (2x3x4) write→read Hausdorff ≤ 1e-7."""
    body = make_box(origin=(1.0, -2.0, 0.5), size=(2.0, 3.0, 4.0))
    h = _round_trip_hausdorff(body)
    assert h <= _HAUSDORFF_TOL, f"Non-unit box Hausdorff {h:.3e} > {_HAUSDORFF_TOL}"


def test_gk48_roundtrip_cylinder_hausdorff():
    """Oracle: cylinder write→read Hausdorff ≤ 1e-7 on vertex positions."""
    body = make_cylinder(radius=1.0, height=2.0)
    text = write_step(body)
    recovered = read_step(text, validate=False)
    # For cylinder: check vertex positions (2 seam vertices)
    orig_verts = {tuple(float(x) for x in v.point) for v in body.all_vertices()}
    recv_verts = [tuple(float(x) for x in v.point) for v in recovered.all_vertices()]
    for rv in recv_verts:
        min_dist = min(
            math.sqrt(sum((rv[i] - ov[i]) ** 2 for i in range(3)))
            for ov in orig_verts
        )
        assert min_dist <= _HAUSDORFF_TOL, (
            f"Cylinder vertex {rv} has min dist {min_dist:.3e} > {_HAUSDORFF_TOL}"
        )


def test_gk48_roundtrip_cylinder_has_cylindrical_surface():
    """Round-tripped cylinder must retain its CylinderSurface faces."""
    from kerf_cad_core.geom.brep import CylinderSurface
    body = make_cylinder(radius=1.5, height=3.0)
    text = write_step(body)
    recovered = read_step(text, validate=False)
    cyl_faces = [f for f in recovered.all_faces() if isinstance(f.surface, CylinderSurface)]
    assert len(cyl_faces) >= 1, "Round-tripped cylinder has no CylinderSurface faces"


def test_gk48_roundtrip_sphere_surface_retained():
    """Round-tripped sphere must retain its SphereSurface face."""
    from kerf_cad_core.geom.brep import SphereSurface
    body = make_sphere(radius=2.0)
    text = write_step(body)
    recovered = read_step(text, validate=False)
    sph_faces = [f for f in recovered.all_faces() if isinstance(f.surface, SphereSurface)]
    assert len(sph_faces) >= 1, "Round-tripped sphere has no SphereSurface face"


def test_gk48_roundtrip_sphere_center_and_radius():
    """Round-tripped sphere center and radius must match to 1e-7."""
    from kerf_cad_core.geom.brep import SphereSurface
    center = np.array([1.0, -2.0, 3.0])
    radius = 2.5
    body = make_sphere(center=center, radius=radius)
    text = write_step(body)
    recovered = read_step(text, validate=False)
    sph_faces = [f for f in recovered.all_faces() if isinstance(f.surface, SphereSurface)]
    assert sph_faces, "No SphereSurface in round-tripped sphere"
    sph = sph_faces[0].surface
    center_err = float(np.linalg.norm(sph.center - center))
    radius_err = abs(sph.radius - radius)
    assert center_err <= _HAUSDORFF_TOL, (
        f"Sphere center error {center_err:.3e} > {_HAUSDORFF_TOL}"
    )
    assert radius_err <= _HAUSDORFF_TOL, (
        f"Sphere radius error {radius_err:.3e} > {_HAUSDORFF_TOL}"
    )


def test_gk48_roundtrip_box_face_count():
    """Round-tripped box must have exactly 6 faces."""
    body = make_box()
    text = write_step(body)
    recovered = read_step(text, validate=False)
    assert len(recovered.all_faces()) == 6, (
        f"Round-tripped box has {len(recovered.all_faces())} faces, expected 6"
    )


def test_gk48_roundtrip_box_validate_body():
    """Round-tripped box must pass validate_body."""
    body = make_box()
    text = write_step(body)
    recovered = read_step(text, validate=False)
    result = validate_body(recovered)
    assert result["ok"], (
        "validate_body failed on round-tripped box:\n  " +
        "\n  ".join(result["errors"])
    )


def test_gk48_roundtrip_box_vertex_coords():
    """Oracle: all 8 vertex coordinates survive round-trip to ≤ 1e-7."""
    body = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
    orig_verts = {
        tuple(round(float(c), 12) for c in v.point)
        for v in body.all_vertices()
    }
    text = write_step(body)
    recovered = read_step(text, validate=False)
    recv_verts = [tuple(float(c) for c in v.point) for v in recovered.all_vertices()]
    tol = _HAUSDORFF_TOL
    for rv in recv_verts:
        matched = any(
            all(abs(rv[i] - ov[i]) <= tol for i in range(3))
            for ov in orig_verts
        )
        assert matched, f"Vertex {rv} not matched in original set to tol {tol}"


def test_gk48_roundtrip_cylinder_face_count():
    """Round-tripped cylinder must have exactly 3 faces."""
    body = make_cylinder(radius=1.0, height=2.0)
    text = write_step(body)
    recovered = read_step(text, validate=False)
    assert len(recovered.all_faces()) == 3, (
        f"Round-tripped cylinder has {len(recovered.all_faces())} faces, expected 3"
    )


def test_gk48_roundtrip_cylinder_radius():
    """Round-tripped cylinder must preserve radius to 1e-7."""
    from kerf_cad_core.geom.brep import CylinderSurface
    r = 1.234
    body = make_cylinder(radius=r, height=2.0)
    text = write_step(body)
    recovered = read_step(text, validate=False)
    cyl_faces = [f for f in recovered.all_faces() if isinstance(f.surface, CylinderSurface)]
    assert cyl_faces, "No CylinderSurface in round-tripped cylinder"
    err = abs(cyl_faces[0].surface.radius - r)
    assert err <= _HAUSDORFF_TOL, f"Cylinder radius error {err:.3e} > {_HAUSDORFF_TOL}"
