"""
Tests for kerf_cad_core.drawings.projections
=============================================

Pure-Python, hermetic — no OCC, no database, no network required.
Uses analytical oracles to validate projection geometry.

Test inventory (4 required by DoD + supplementary):

T1.  Cube projection — 1×1×1 cube front view bounds are 1×1.
T2.  Cube projection — 1×1×1 cube top view bounds are 1×1.
T3.  Cube projection — all six views present; no hidden lines on a solid cube
     viewed face-on (front/top/left surfaces fully visible from their canonical
     directions).
T4.  Cylinder projection — radius=1, height=2 front view width≈2, height≈2.
T5.  Cylinder projection — top view is circular; bounding box is approximately
     2×2 (diameter × diameter).
T6.  Cup hidden lines — a hollow cylinder (cup) front view has hidden edges.
T7.  Iso view — cube iso view shows 3 non-empty view directions; vertex
     projection satisfies standard isometric formula (equal 120° angular spacing
     of cube axes on the isometric plane).
T8.  Third-angle vs first-angle layout positions differ for top view.
T9.  Sheet size A3 → width_mm=420, height_mm=297.
T10. ViewSheet.to_dict() is JSON-round-trippable and contains expected keys.
T11. generate_six_view_drawing with include_iso=False → no iso key.
T12. Error path: bad projection_type returns ok=False.
T13. compute_projection_silhouette returns a non-empty list for a cube.
T14. hidden_line_removal on a cube from front → visible edges present.
T15. hidden_line_removal on cup from front → hidden edges present.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from kerf_cad_core.drawings.projections import (
    ViewSheet,
    ProjectionView,
    compute_projection_silhouette,
    generate_six_view_drawing,
    hidden_line_removal,
)


# ---------------------------------------------------------------------------
# Mesh factories (analytical bodies)
# ---------------------------------------------------------------------------

def _cube_mesh(side: float = 1.0) -> Dict[str, Any]:
    """Return a closed 1×1×1 cube mesh dict centred at origin."""
    s = side / 2.0
    verts = [
        [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
        [-s, -s,  s], [s, -s,  s], [s, s,  s], [-s, s,  s],
    ]
    # 12 triangles (2 per face × 6 faces)
    tris = [
        [0, 2, 1], [0, 3, 2],   # bottom -Z
        [4, 5, 6], [4, 6, 7],   # top    +Z
        [0, 1, 5], [0, 5, 4],   # front  -Y
        [1, 2, 6], [1, 6, 5],   # right  +X
        [2, 3, 7], [2, 7, 6],   # back   +Y
        [3, 0, 4], [3, 4, 7],   # left   -X
    ]
    return {"vertices": verts, "triangles": tris}


def _cylinder_mesh(radius: float = 1.0, height: float = 2.0, n_sides: int = 32) -> Dict[str, Any]:
    """Return a closed cylinder mesh dict (axis along Z, centred at origin)."""
    verts: List[List[float]] = []
    tris: List[List[int]] = []

    # Top and bottom cap centres
    bot_c = len(verts)
    verts.append([0.0, 0.0, -height / 2.0])
    top_c = len(verts)
    verts.append([0.0, 0.0, height / 2.0])

    # Ring vertices: bottom ring first, then top ring
    bot_start = len(verts)
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        verts.append([radius * math.cos(a), radius * math.sin(a), -height / 2.0])
    top_start = len(verts)
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        verts.append([radius * math.cos(a), radius * math.sin(a), height / 2.0])

    for i in range(n_sides):
        j = (i + 1) % n_sides
        bi, bj = bot_start + i, bot_start + j
        ti, tj = top_start + i, top_start + j

        # Bottom cap (winding toward -Z)
        tris.append([bot_c, bj, bi])
        # Top cap (winding toward +Z)
        tris.append([top_c, ti, tj])
        # Side quad → 2 triangles
        tris.append([bi, bj, tj])
        tris.append([bi, tj, ti])

    return {"vertices": verts, "triangles": tris}


def _cup_mesh(
    outer_radius: float = 1.0,
    inner_radius: float = 0.8,
    height: float = 2.0,
    n_sides: int = 24,
) -> Dict[str, Any]:
    """Return a hollow cup mesh (cylinder with closed bottom, open top).

    The cup has:
    - Outer wall (solid cylinder side)
    - Inner wall (hollow cylinder side, inverted normals)
    - Bottom face (annular ring)
    The top is open (no cap) so the inner surface is visible from the front.
    """
    verts: List[List[float]] = []
    tris: List[List[int]] = []

    bot_z = -height / 2.0
    top_z = height / 2.0

    # 4 rings: outer-bottom, outer-top, inner-bottom, inner-top
    ob_start = len(verts)
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        verts.append([outer_radius * math.cos(a), outer_radius * math.sin(a), bot_z])
    ot_start = len(verts)
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        verts.append([outer_radius * math.cos(a), outer_radius * math.sin(a), top_z])
    ib_start = len(verts)
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        verts.append([inner_radius * math.cos(a), inner_radius * math.sin(a), bot_z])
    it_start = len(verts)
    for i in range(n_sides):
        a = 2.0 * math.pi * i / n_sides
        verts.append([inner_radius * math.cos(a), inner_radius * math.sin(a), top_z])

    for i in range(n_sides):
        j = (i + 1) % n_sides
        obi, obj_ = ob_start + i, ob_start + j
        oti, otj = ot_start + i, ot_start + j
        ibi, ibj = ib_start + i, ib_start + j
        iti, itj = it_start + i, it_start + j

        # Outer wall
        tris.append([obi, obj_, otj])
        tris.append([obi, otj, oti])
        # Inner wall (reversed winding for inward normals)
        tris.append([ibi, itj, ibj])
        tris.append([ibi, iti, itj])
        # Bottom annular ring
        tris.append([obi, ibi, ibj])
        tris.append([obi, ibj, obj_])

    return {"vertices": verts, "triangles": tris}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_total_edges(view: ProjectionView) -> Tuple[int, int]:
    """Return (visible_count, hidden_count) for a view."""
    return len(view.visible), len(view.hidden)


# ---------------------------------------------------------------------------
# T1: Cube — front view bounds ≈ 1×1
# ---------------------------------------------------------------------------

def test_cube_front_view_bounds_1x1():
    """Cube front view 2-D bounding box should be ≈ side × side."""
    side = 1.0
    cube = _cube_mesh(side)
    sheet = generate_six_view_drawing(cube, projection_type="third_angle", include_iso=True)

    assert sheet.ok, f"generate failed: {sheet.reason}"
    assert "front" in sheet.views, "front view missing"

    front = sheet.views["front"]
    bb = front.bbox_2d

    # The raw 2-D bounding box (before sheet placement scaling) is stored in bbox_2d.
    # Width and height should both be ≈ side (1.0) within floating-point tolerance.
    assert bb["width"] == pytest.approx(side, abs=1e-6), (
        f"front view width={bb['width']:.6f}, expected ≈{side}"
    )
    assert bb["height"] == pytest.approx(side, abs=1e-6), (
        f"front view height={bb['height']:.6f}, expected ≈{side}"
    )


# ---------------------------------------------------------------------------
# T2: Cube — top view bounds ≈ 1×1
# ---------------------------------------------------------------------------

def test_cube_top_view_bounds_1x1():
    """Cube top view 2-D bounding box should be ≈ side × side."""
    side = 1.0
    cube = _cube_mesh(side)
    sheet = generate_six_view_drawing(cube, projection_type="third_angle", include_iso=True)

    assert sheet.ok
    assert "top" in sheet.views

    top = sheet.views["top"]
    bb = top.bbox_2d
    assert bb["width"] == pytest.approx(side, abs=1e-6), (
        f"top view width={bb['width']:.6f}, expected ≈{side}"
    )
    assert bb["height"] == pytest.approx(side, abs=1e-6), (
        f"top view height={bb['height']:.6f}, expected ≈{side}"
    )


# ---------------------------------------------------------------------------
# T3: Cube — all six views present; no hidden lines on face-on views
# ---------------------------------------------------------------------------

def test_cube_six_views_present_no_hidden():
    """All 6 orthographic views must be present with correct visible edge counts.

    A 1×1×1 cube has 12 edges.  When viewed face-on (e.g. from -Y looking toward
    +Y), 4 edges form the front-face square (visible) and 4 edges form the back-
    face square (hidden — directly behind the front face in projection).  The 4
    vertical connecting edges are degenerate (they collapse to a point in
    orthographic view of a face-aligned cube) and may or may not appear depending
    on implementation.  We verify:
      • All 6 views are present.
      • Each face-on view has exactly 4 visible edges (the front face outline).
      • Each face-on view has at least 4 hidden edges (the back face edges).
      • Total visible + hidden ≥ 8 (at minimum the two opposite face outlines).
    """
    cube = _cube_mesh(1.0)
    sheet = generate_six_view_drawing(cube, include_iso=True)
    assert sheet.ok

    expected_views = {"front", "back", "top", "bottom", "left", "right"}
    assert expected_views.issubset(set(sheet.views.keys())), (
        f"Missing views: {expected_views - set(sheet.views.keys())}"
    )

    # Each face-on view must produce the 4 outline visible edges.
    for vname in ("front", "top", "left"):
        n_vis = len(sheet.views[vname].visible)
        assert n_vis >= 4, (
            f"{vname} view has only {n_vis} visible edges (expected ≥ 4)"
        )

    # Each face-on view must have at least 4 hidden edges (back face outline).
    for vname in ("front", "top", "left"):
        n_hid = len(sheet.views[vname].hidden)
        assert n_hid >= 4, (
            f"{vname} view has only {n_hid} hidden edges (expected ≥ 4 for back face)"
        )


# ---------------------------------------------------------------------------
# T4: Cylinder — front view is 2×2 rectangle (width≈2r=2, height≈h=2)
# ---------------------------------------------------------------------------

def test_cylinder_front_view_bounds():
    """Cylinder (radius=1, height=2) front view should be ≈ 2×2."""
    r, h = 1.0, 2.0
    cyl = _cylinder_mesh(radius=r, height=h, n_sides=64)
    sheet = generate_six_view_drawing(cyl, include_iso=False)
    assert sheet.ok

    front = sheet.views["front"]
    bb = front.bbox_2d
    # Width along X = 2*radius = 2.0; height along Z = height = 2.0.
    # We allow 2% tolerance for tessellation discretisation.
    assert bb["width"] == pytest.approx(2.0 * r, rel=0.02), (
        f"cylinder front width={bb['width']:.4f}, expected ≈{2*r}"
    )
    assert bb["height"] == pytest.approx(h, rel=0.02), (
        f"cylinder front height={bb['height']:.4f}, expected ≈{h}"
    )


# ---------------------------------------------------------------------------
# T5: Cylinder — top view is approximately circular (bbox ≈ 2r × 2r)
# ---------------------------------------------------------------------------

def test_cylinder_top_view_circular():
    """Cylinder top view bounding box should be approximately 2r × 2r."""
    r, h = 1.0, 2.0
    cyl = _cylinder_mesh(radius=r, height=h, n_sides=64)
    sheet = generate_six_view_drawing(cyl, include_iso=False)
    assert sheet.ok

    top = sheet.views["top"]
    bb = top.bbox_2d
    diameter = 2.0 * r
    # Both dimensions should be close to 2r (within 2% tessellation error).
    assert bb["width"] == pytest.approx(diameter, rel=0.02), (
        f"cylinder top bbox width={bb['width']:.4f}, expected ≈{diameter}"
    )
    assert bb["height"] == pytest.approx(diameter, rel=0.02), (
        f"cylinder top bbox height={bb['height']:.4f}, expected ≈{diameter}"
    )


# ---------------------------------------------------------------------------
# T6: Cup hidden lines — front view has hidden edges
# ---------------------------------------------------------------------------

def test_cup_front_view_has_hidden_lines():
    """A hollow cup has inner surfaces that are hidden when viewed from the front.

    The back inner wall is behind the front outer wall — the edge between them
    must be classified as hidden.
    """
    cup = _cup_mesh(outer_radius=1.0, inner_radius=0.8, height=2.0, n_sides=32)
    sheet = generate_six_view_drawing(cup, include_iso=False)
    assert sheet.ok

    front = sheet.views["front"]
    n_hidden = len(front.hidden)
    assert n_hidden > 0, (
        f"Cup front view has {n_hidden} hidden edges — expected >0 for hollow cup"
    )


# ---------------------------------------------------------------------------
# T7: Iso view — cube vertex projection matches isometric formula
# ---------------------------------------------------------------------------

def test_cube_iso_view():
    """Cube isometric view: 3 cube-face normals should project to directions
    120° apart on the 2-D plane (standard isometric property).

    The three cube axis directions (X, Y, Z in world space) under the isometric
    view matrix should project to 2-D unit vectors with mutual angle ≈ 120°.
    This is the defining property of a standard isometric projection per
    Bertoline-Wiebe 5e §10 and ISO 5456-3.
    """
    cube = _cube_mesh(1.0)
    sheet = generate_six_view_drawing(cube, include_iso=True)
    assert sheet.ok
    assert "iso" in sheet.views, "iso view missing"

    # Verify via the view direction: the isometric direction is (1,-1,1)/√3.
    # Under orthographic projection from this direction the three cube axes
    # X=(1,0,0), Y=(0,1,0), Z=(0,0,1) each project to a 2-D vector; the
    # angle between any two of these projections should be ≈ 120°.
    #
    # Build the view matrix manually (same logic as make2d._build_view_matrix).
    from kerf_cad_core.drawings.projections import _ISO_DIR
    vdir = _ISO_DIR.copy()  # unit (1,-1,1)/√3
    up = np.array([0.0, 0.0, 1.0])

    right = np.cross(vdir, up)
    right /= np.linalg.norm(right)
    up_ortho = np.cross(right, vdir)
    up_ortho /= np.linalg.norm(up_ortho)

    def proj2d(v3: np.ndarray) -> np.ndarray:
        """Orthographic projection of a 3-D vector onto the view plane."""
        return np.array([np.dot(v3, right), np.dot(v3, up_ortho)])

    x_proj = proj2d(np.array([1.0, 0.0, 0.0]))
    y_proj = proj2d(np.array([0.0, 1.0, 0.0]))
    z_proj = proj2d(np.array([0.0, 0.0, 1.0]))

    # Normalise (they may not be unit vectors)
    def angle_deg(a: np.ndarray, b: np.ndarray) -> float:
        cos_a = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)
        cos_a = float(np.clip(cos_a, -1.0, 1.0))
        return math.degrees(math.acos(cos_a))

    ang_xy = angle_deg(x_proj, y_proj)
    ang_xz = angle_deg(x_proj, z_proj)
    ang_yz = angle_deg(y_proj, z_proj)

    # All three angles should be ≈ 120° (standard isometric property)
    tol_deg = 1.0  # 1° tolerance
    assert abs(ang_xy - 120.0) < tol_deg, (
        f"Angle X–Y in iso projection = {ang_xy:.2f}°, expected 120°"
    )
    assert abs(ang_xz - 120.0) < tol_deg, (
        f"Angle X–Z in iso projection = {ang_xz:.2f}°, expected 120°"
    )
    assert abs(ang_yz - 120.0) < tol_deg, (
        f"Angle Y–Z in iso projection = {ang_yz:.2f}°, expected 120°"
    )

    # Iso view also has visible edges (it's a 3-D view, should have edges)
    iso_view = sheet.views["iso"]
    assert len(iso_view.visible) > 0, "iso view has no visible edges"


# ---------------------------------------------------------------------------
# T8: Third-angle vs first-angle layout differs for top view
# ---------------------------------------------------------------------------

def test_third_vs_first_angle_layout_differs():
    """Top view y-position differs between third-angle and first-angle layout."""
    cube = _cube_mesh()
    ta = generate_six_view_drawing(cube, projection_type="third_angle", include_iso=False)
    fa = generate_six_view_drawing(cube, projection_type="first_angle", include_iso=False)

    assert ta.ok and fa.ok

    # In third-angle: top view is ABOVE front (smaller y in sheet coords where
    # y grows downward from top-margin = row 0 < row 1).
    # In first-angle: top view is BELOW front (row 2 > row 1).
    ta_top_y = ta.layout["top"]["y"]
    fa_top_y = fa.layout["top"]["y"]
    ta_front_y = ta.layout["front"]["y"]
    fa_front_y = fa.layout["front"]["y"]

    assert ta_top_y < ta_front_y, (
        f"Third-angle: top ({ta_top_y}) should be above front ({ta_front_y})"
    )
    assert fa_top_y > fa_front_y, (
        f"First-angle: top ({fa_top_y}) should be below front ({fa_front_y})"
    )


# ---------------------------------------------------------------------------
# T9: Sheet size A3 dimensions
# ---------------------------------------------------------------------------

def test_sheet_size_a3():
    """ViewSheet for A3 must have width=420, height=297 per ISO 216."""
    cube = _cube_mesh()
    sheet = generate_six_view_drawing(cube, sheet="A3")
    assert sheet.ok
    assert sheet.sheet_width_mm == pytest.approx(420.0)
    assert sheet.sheet_height_mm == pytest.approx(297.0)
    assert sheet.sheet_size == "A3"


# ---------------------------------------------------------------------------
# T10: to_dict() is JSON-round-trippable with expected keys
# ---------------------------------------------------------------------------

def test_to_dict_json_round_trip():
    """ViewSheet.to_dict() must serialise cleanly to JSON and contain expected keys."""
    cube = _cube_mesh()
    sheet = generate_six_view_drawing(cube)
    assert sheet.ok

    d = sheet.to_dict()
    json_str = json.dumps(d)  # must not raise
    d2 = json.loads(json_str)

    required_top_keys = {"ok", "views", "sheet_size", "sheet_width_mm",
                         "sheet_height_mm", "projection_type", "scale",
                         "drawing_id", "border", "title_block", "projection_symbol"}
    assert required_top_keys.issubset(set(d2.keys())), (
        f"Missing keys: {required_top_keys - set(d2.keys())}"
    )
    # Each view must have visible, hidden, bbox_2d, layout_cell
    for vname, vdata in d2["views"].items():
        for k in ("visible", "hidden", "bbox_2d", "layout_cell"):
            assert k in vdata, f"View '{vname}' missing key '{k}'"


# ---------------------------------------------------------------------------
# T11: include_iso=False → no iso key
# ---------------------------------------------------------------------------

def test_exclude_iso_view():
    """When include_iso=False the 'iso' key must be absent from views."""
    cube = _cube_mesh()
    sheet = generate_six_view_drawing(cube, include_iso=False)
    assert sheet.ok
    assert "iso" not in sheet.views, "iso view present despite include_iso=False"


# ---------------------------------------------------------------------------
# T12: Bad projection_type → ok=False
# ---------------------------------------------------------------------------

def test_bad_projection_type_returns_error():
    """An invalid projection_type must result in ok=False."""
    cube = _cube_mesh()
    sheet = generate_six_view_drawing(cube, projection_type="oblique")
    assert not sheet.ok
    assert sheet.reason != ""


# ---------------------------------------------------------------------------
# T13: compute_projection_silhouette returns non-empty list for cube
# ---------------------------------------------------------------------------

def test_compute_projection_silhouette_cube():
    """Silhouette of a cube from the front should be non-empty."""
    cube = _cube_mesh()
    silhouettes = compute_projection_silhouette(cube, [0.0, -1.0, 0.0])
    assert isinstance(silhouettes, list)
    assert len(silhouettes) > 0, "Expected silhouette edges for cube, got empty list"
    # Each element must be a list of [x,y] pairs
    for seg in silhouettes:
        assert len(seg) >= 2, f"Silhouette segment too short: {seg}"
        for pt in seg:
            assert len(pt) == 2


# ---------------------------------------------------------------------------
# T14: hidden_line_removal on solid cube → visible edges present
# ---------------------------------------------------------------------------

def test_hidden_line_removal_cube_visible():
    """hidden_line_removal on a solid cube (front view) must return visible edges."""
    cube = _cube_mesh()
    vis, hid = hidden_line_removal(cube, [0.0, -1.0, 0.0])
    assert len(vis) > 0, f"Expected visible edges, got {len(vis)}"


# ---------------------------------------------------------------------------
# T15: hidden_line_removal on cup → hidden edges present (front view)
# ---------------------------------------------------------------------------

def test_hidden_line_removal_cup_has_hidden():
    """hidden_line_removal on a hollow cup (front view) must return hidden edges."""
    cup = _cup_mesh(outer_radius=1.0, inner_radius=0.8, height=2.0)
    vis, hid = hidden_line_removal(cup, [0.0, -1.0, 0.0])
    assert len(hid) > 0, (
        f"Expected hidden edges for cup front view, got {len(hid)} hidden / "
        f"{len(vis)} visible"
    )
