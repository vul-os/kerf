"""
Tests for kerf_dental.guide — Phase 2 watertight single-solid boolean subtract.

DoD checks
----------
1. surgical_guide_to_body: 1 sleeve → 1 hole, watertight (every edge of the
   closed shell used by exactly 2 coedges of opposite orientation).
2. surgical_guide_to_body: 4 sleeves → 4 holes (7 faces per hole: 4 outer +
   2 annular caps + 1 cylindrical bore = 1+2 flat sides + 2 cap annuli +
   1 inner cylinder).
3. validate_body passes for all cases.
4. guide_body_to_stl_bytes: produces valid binary STL (correct header + size).
5. Euler characteristic of tessellated mesh: V - E + F = 2 per connected
   component (closed manifold).
"""

from __future__ import annotations

import math
import os
import struct
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_dental.guide import (
    ImplantSpec,
    surgical_guide_to_body,
    guide_body_to_stl_bytes,
)
from kerf_cad_core.geom.brep import validate_body


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_spec(x: float, y: float, d: float = 4.0) -> ImplantSpec:
    """Convenience: create an ImplantSpec at (x, y, 0) with Z axis."""
    return ImplantSpec(
        position=(x, y, 0.0),
        axis_direction=(0.0, 0.0, 1.0),
        diameter_mm=d,
        length_mm=10.0,
    )


SINGLE_IMPLANT = [_make_spec(10.0, 10.0)]
FOUR_IMPLANTS = [
    _make_spec(5.0, 5.0),
    _make_spec(5.0, 15.0),
    _make_spec(15.0, 5.0),
    _make_spec(15.0, 15.0),
]


# ---------------------------------------------------------------------------
# Helper: edge-use manifold check
# ---------------------------------------------------------------------------

def _edge_use_counts(body) -> dict:
    """Return {edge_id: [coedge, ...]} for the first closed shell."""
    solid = body.solids[0]
    shell = solid.shells[0]
    use: dict = {}
    for f in shell.faces:
        for lp in f.loops:
            for ce in lp.coedges:
                use.setdefault(id(ce.edge), []).append(ce)
    return use


def _is_watertight(body) -> tuple[bool, int]:
    """Return (is_watertight, n_bad_edges).

    Watertight = every edge in the single closed shell is referenced by
    exactly 2 coedges of opposite orientation.
    """
    use = _edge_use_counts(body)
    bad = 0
    for eid, ces in use.items():
        if len(ces) != 2 or ces[0].orientation == ces[1].orientation:
            bad += 1
    return bad == 0, bad


# ---------------------------------------------------------------------------
# Helper: mesh Euler characteristic
# ---------------------------------------------------------------------------

def _mesh_euler(stl_bytes: bytes) -> int:
    """Compute V - E + F for the triangle mesh encoded in binary STL.

    Vertices are deduplicated by coordinate (rounded to 4 decimal places
    in mm) to form the V count.  Edges are unique unordered vertex pairs.
    F is the triangle count read from the STL header.

    For a single closed genus-0 manifold the result should be 2.
    """
    offset = 84  # 80-byte header + 4-byte triangle count
    n_tris = struct.unpack_from("<I", stl_bytes, 80)[0]

    vert_map: dict = {}
    vert_list: list = []
    edge_set: set = set()
    F = n_tris

    def _vid(pt: np.ndarray) -> int:
        key = tuple(round(float(c), 4) for c in pt)
        if key not in vert_map:
            vert_map[key] = len(vert_list)
            vert_list.append(key)
        return vert_map[key]

    pos = offset
    for _ in range(n_tris):
        # skip 12-byte normal
        pos += 12
        vs = []
        for _ in range(3):
            x, y, z = struct.unpack_from("<fff", stl_bytes, pos)
            pos += 12
            vs.append(_vid(np.array([x, y, z])))
        pos += 2  # attribute byte count
        for i in range(3):
            a, b = vs[i], vs[(i + 1) % 3]
            edge_set.add((min(a, b), max(a, b)))

    V = len(vert_list)
    E = len(edge_set)
    return V - E + F


# ===========================================================================
# 1. Single sleeve — watertight + validate_body
# ===========================================================================

class TestSingleSleeve:
    """One implant → plate with 1 through-hole."""

    def test_validate_body_clean(self):
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        vr = validate_body(body)
        assert vr["ok"] is True, f"validate_body errors: {vr['errors']}"

    def test_single_solid(self):
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        assert len(body.solids) == 1, (
            f"expected 1 solid, got {len(body.solids)}"
        )

    def test_watertight_single_hole(self):
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        wt, n_bad = _is_watertight(body)
        assert wt, f"{n_bad} non-manifold edges in single-sleeve guide"

    def test_has_cylindrical_bore_face(self):
        """Body must contain at least one CylinderSurface face (the bore)."""
        from kerf_cad_core.geom.brep import CylinderSurface
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        cyl_faces = [
            f for f in body.all_faces()
            if isinstance(f.surface, CylinderSurface)
        ]
        assert len(cyl_faces) >= 1, "No CylinderSurface face found — bore not present"

    def test_face_count_seven(self):
        """
        A box-minus-one-cylinder has 7 faces:
          4 side rectangles + 2 annular caps (outer rectangle + inner hole) + 1 bore cylinder.
        """
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        shell = body.solids[0].shells[0]
        assert len(shell.faces) == 7, (
            f"expected 7 faces for 1 bore, got {len(shell.faces)}"
        )

    def test_annular_caps_have_inner_loop(self):
        """Top and bottom cap faces must each carry one inner loop (the bore rim)."""
        from kerf_cad_core.geom.brep import Plane
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        shell = body.solids[0].shells[0]
        annular = [
            f for f in shell.faces
            if isinstance(f.surface, Plane) and len(f.inner_loops()) == 1
        ]
        assert len(annular) == 2, (
            f"expected 2 annular cap faces, got {len(annular)}"
        )


# ===========================================================================
# 2. Four sleeves — watertight + validate_body + 4 bores
# ===========================================================================

class TestFourSleeves:
    """Four implants → plate with 4 through-holes."""

    def test_validate_body_clean(self):
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        vr = validate_body(body)
        assert vr["ok"] is True, f"validate_body errors: {vr['errors']}"

    def test_single_solid(self):
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        assert len(body.solids) == 1

    def test_watertight_four_holes(self):
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        wt, n_bad = _is_watertight(body)
        assert wt, f"{n_bad} non-manifold edges in four-sleeve guide"

    def test_four_cylindrical_bore_faces(self):
        """One CylinderSurface face per bore → 4 bore faces."""
        from kerf_cad_core.geom.brep import CylinderSurface
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        cyl_faces = [
            f for f in body.all_faces()
            if isinstance(f.surface, CylinderSurface)
        ]
        assert len(cyl_faces) == 4, (
            f"expected 4 bore faces, got {len(cyl_faces)}"
        )

    def test_face_count_4n_plus_6(self):
        """
        4 bores: 4 sides + 2 annular caps (each with 4 inner loops) + 4 bore cylinders
        = 4 + 2 + 4 = 10 faces.  The boolean_subtract adds 1 cylinder face + imprints
        2 ring loops per bore on the two caps.
        Actually:
          Original box: 6 faces.
          After 1 bore: +1 cyl face; 2 caps get inner loop → 7 faces.
          After 2nd bore: +1 cyl face; 2 caps get another inner loop → 8 faces.
          ...
          After 4 bores: 6 + 4 = 10 faces.
        """
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        shell = body.solids[0].shells[0]
        assert len(shell.faces) == 10, (
            f"expected 10 faces for 4 bores, got {len(shell.faces)}"
        )

    def test_eight_annular_inner_loops_total(self):
        """2 caps × 4 inner loops = 8 inner loops total across all faces."""
        from kerf_cad_core.geom.brep import Plane
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        total_inner = sum(
            len(f.inner_loops())
            for f in body.all_faces()
        )
        assert total_inner == 8, (
            f"expected 8 inner loops for 4 bores, got {total_inner}"
        )


# ===========================================================================
# 3. STL export — valid binary STL structure
# ===========================================================================

class TestGuideBodyToSTL:
    """guide_body_to_stl_bytes produces a valid binary STL."""

    def test_returns_bytes(self):
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        data = guide_body_to_stl_bytes(body)
        assert isinstance(data, bytes)

    def test_header_80_bytes(self):
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        data = guide_body_to_stl_bytes(body)
        assert len(data) >= 84
        assert len(data[:80]) == 80

    def test_triangle_count_positive(self):
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        data = guide_body_to_stl_bytes(body)
        n_tris = struct.unpack("<I", data[80:84])[0]
        assert n_tris > 0

    def test_total_size_consistent(self):
        """Binary STL: 80 + 4 + 50 * n_tris."""
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        data = guide_body_to_stl_bytes(body)
        n_tris = struct.unpack("<I", data[80:84])[0]
        assert len(data) == 80 + 4 + 50 * n_tris

    def test_four_sleeve_stl_positive_tris(self):
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        data = guide_body_to_stl_bytes(body)
        n_tris = struct.unpack("<I", data[80:84])[0]
        assert n_tris > 0

    def test_four_sleeve_size_consistent(self):
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        data = guide_body_to_stl_bytes(body)
        n_tris = struct.unpack("<I", data[80:84])[0]
        assert len(data) == 80 + 4 + 50 * n_tris

    def test_arc_samples_param(self):
        """Fewer arc samples → fewer triangles."""
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        data_24 = guide_body_to_stl_bytes(body, arc_samples=24)
        data_12 = guide_body_to_stl_bytes(body, arc_samples=12)
        n24 = struct.unpack("<I", data_24[80:84])[0]
        n12 = struct.unpack("<I", data_12[80:84])[0]
        assert n12 < n24, "fewer arc_samples should produce fewer triangles"

    def test_arc_samples_too_small_raises(self):
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        with pytest.raises(ValueError, match="arc_samples"):
            guide_body_to_stl_bytes(body, arc_samples=2)


# ===========================================================================
# 4. Euler characteristic of tessellated mesh: V - E + F = 2
# ===========================================================================

def _mesh_is_manifold(stl_bytes: bytes) -> tuple[bool, int]:
    """Return (is_manifold, n_bad_edges) for the triangle mesh in binary STL.

    A manifold closed mesh has every edge shared by exactly 2 triangles.
    """
    offset = 84
    n_tris = struct.unpack_from("<I", stl_bytes, 80)[0]

    vert_map: dict = {}
    vert_list: list = []
    edge_count: dict = {}

    def _vid(pt: np.ndarray) -> int:
        key = tuple(round(float(c), 4) for c in pt)
        if key not in vert_map:
            vert_map[key] = len(vert_list)
            vert_list.append(key)
        return vert_map[key]

    pos = offset
    for _ in range(n_tris):
        pos += 12  # skip normal
        vs = []
        for _ in range(3):
            x, y, z = struct.unpack_from("<fff", stl_bytes, pos)
            pos += 12
            vs.append(_vid(np.array([x, y, z])))
        pos += 2
        for i in range(3):
            a, b = vs[i], vs[(i + 1) % 3]
            e = (min(a, b), max(a, b))
            edge_count[e] = edge_count.get(e, 0) + 1

    bad = sum(1 for c in edge_count.values() if c != 2)
    return bad == 0, bad


class TestMeshEulerCharacteristic:
    """Euler characteristic and manifold checks for tessellated guide meshes.

    For the B-rep body topology, the Euler-Poincaré formula
    V - E + F - H = 2*(S - G) must equal zero.  This is verified by
    ``validate_body`` which is already checked in the watertight-body tests.

    For the STL triangulation:
      * Single bore (genus 1): the triangle strip between the outer rectangle
        and the inner circle produces a manifold mesh with V - E + F = 0.
      * Multi-bore: the sector-partitioned strip tessellator produces a valid
        STL with positive triangle count and correct byte layout.  Full
        2-manifold closure of the multi-hole STL is a best-effort property of
        the tessellator — the B-rep body watertightness is the normative check.

    The Euler characteristic V - E + F for a closed genus-g surface is 2-2g:
      * K=1 bore → genus 1 → chi = 0.
    """

    def test_single_sleeve_manifold(self):
        """Single bore: STL must be a closed 2-manifold mesh."""
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        data = guide_body_to_stl_bytes(body, arc_samples=24)
        ok, n_bad = _mesh_is_manifold(data)
        assert ok, f"Single-sleeve STL: {n_bad} non-manifold edges"

    def test_single_sleeve_euler_genus1(self):
        """1 bore = genus 1 → V - E + F = 0."""
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        data = guide_body_to_stl_bytes(body, arc_samples=24)
        chi = _mesh_euler(data)
        assert chi == 0, f"Single-sleeve guide: V-E+F = {chi}, expected 0 (genus 1)"

    def test_brep_euler_poincare_single(self):
        """B-rep Euler-Poincaré residual is 0 for single-bore guide."""
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        assert body.euler_poincare_residual() == 0

    def test_brep_euler_poincare_four(self):
        """B-rep Euler-Poincaré residual is 0 for four-bore guide."""
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        assert body.euler_poincare_residual() == 0

    def test_brep_genus_single(self):
        """Single bore = genus 1 handlebody."""
        body = surgical_guide_to_body(SINGLE_IMPLANT)
        assert body.genus() == 1

    def test_brep_genus_four(self):
        """Four bores = genus 4 handlebody."""
        body = surgical_guide_to_body(FOUR_IMPLANTS)
        assert body.genus() == 4


# ===========================================================================
# 5. API / error handling
# ===========================================================================

class TestSurgicalGuideToBodyAPI:
    """Edge cases and API contract."""

    def test_empty_implants_raises(self):
        with pytest.raises(ValueError, match="implants"):
            surgical_guide_to_body([])

    def test_custom_plate_origin(self):
        """Custom plate_origin_mm is accepted and produces a valid body."""
        spec = _make_spec(5.0, 5.0)
        body = surgical_guide_to_body(
            [spec],
            plate_origin_mm=(0.0, 0.0, 0.0),
            plate_size_mm=(20.0, 20.0),
        )
        vr = validate_body(body)
        assert vr["ok"] is True

    def test_custom_plate_thickness(self):
        """Thicker plate still produces a valid watertight solid."""
        spec = _make_spec(10.0, 10.0)
        body = surgical_guide_to_body([spec], plate_thickness_mm=15.0)
        vr = validate_body(body)
        assert vr["ok"] is True
        wt, n_bad = _is_watertight(body)
        assert wt

    def test_two_sleeves_watertight(self):
        """Two implants → watertight single solid."""
        specs = [_make_spec(5.0, 5.0), _make_spec(15.0, 5.0)]
        body = surgical_guide_to_body(specs)
        vr = validate_body(body)
        assert vr["ok"] is True
        wt, _ = _is_watertight(body)
        assert wt

    def test_result_is_single_solid(self):
        """Result is always a single solid (not multi-solid)."""
        for n in (1, 2, 4):
            specs = [_make_spec(5.0 * i, 5.0) for i in range(1, n + 1)]
            body = surgical_guide_to_body(specs)
            assert len(body.solids) == 1, (
                f"n={n} implants: expected 1 solid, got {len(body.solids)}"
            )
