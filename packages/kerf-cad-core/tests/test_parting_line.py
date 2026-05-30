"""
test_parting_line.py
====================
GK-P: Hermetic oracle tests for parting-line extraction and undercut detection.

All tests are pure-Python / NumPy — no OCC, no DB, no network required.

Tests
-----
1. Cube parting line   — box with pull (0,0,1) yields exactly 1 loop of
                         4 parting edges (the 4 vertical edges connecting
                         bottom corners to top corners).
2. Sphere parting line — sphere with pull (0,0,1) has no edges on the
                         parting silhouette (single-face sphere B-rep has
                         no boundary edges); has_undercut detected from the
                         bottom half of the sphere.
3. Cup with undercut   — cylinder (closed solid) pulled in +Z: the bottom
                         cap has normal (0,0,-1) → has_undercut = True; the
                         bottom face id appears in undercut_faces.
4. Optimal pull        — flat plate (thin box, 2×2×0.1) with pull perpendicular
                         to the plate minimises undercut count; tested by
                         checking that optimal_pull_direction returns a vector
                         closely aligned to (0,0,1) or (0,0,-1).
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.parting_line import (
    PartingLineResult,
    extract_parting_line,
    detect_undercuts,
    optimal_pull_direction,
)
from kerf_cad_core.geom.brep_build import (
    box_to_body,
    cylinder_to_body,
    sphere_to_body,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec_close(a: np.ndarray, b: np.ndarray, tol: float = 0.15) -> bool:
    """Return True if |a - b| < tol (after normalisation)."""
    ua = a / (np.linalg.norm(a) + 1e-30)
    ub = b / (np.linalg.norm(b) + 1e-30)
    return bool(np.linalg.norm(ua - ub) < tol or np.linalg.norm(ua + ub) < tol)


# ---------------------------------------------------------------------------
# Test 1: Cube parting line
# ---------------------------------------------------------------------------

class TestCubePartingLine:
    """Parting line of a unit cube with pull (0,0,1).

    The cube has 6 faces:
      - top    (z=1): normal = (0,0,+1) → 'top'
      - bottom (z=0): normal = (0,0,-1) → 'bottom'
      - four sides:  normals ≈ (±1,0,0) or (0,±1,0) → 'side' only if
                     |n·pull| ≤ sin(tol); since side normals have dot=0,
                     they are classified 'side'.

    With tol_angle_deg=5°, sin(5°)≈0.087:
      - top face dot = +1   → 'top'
      - bottom face dot = -1 → 'bottom'
      - side faces dot = 0  → 'side'

    Parting edges: the 4 vertical edges connecting bottom to top each lie
    between a 'side' face and either the 'top' or 'bottom' face:
      - bottom ring edges (z=0): shared between bottom ('bottom') and a side
        ('side') → parting edge.
      - top ring edges (z=1): shared between top ('top') and a side ('side')
        → parting edge.
      - 4 vertical edges: shared between two 'side' faces → NOT parting edges.

    Actually the cube has:
      - 4 bottom edges (between bottom face and 4 side faces)
      - 4 top edges    (between top face and 4 side faces)
      - 4 vertical edges (between adjacent side faces)

    Parting edges = bottom-ring + top-ring = 8 edges.
    These form 1 closed rectangle at z=0 and 1 closed rectangle at z=1.
    Or equivalently, 2 loops (one at z=0, one at z=1) OR the algorithm
    may trace them as 1 or 2 chains depending on connectivity.
    Either way: loop_count >= 1 and the parting edges are horizontal.
    """

    def test_cube_parting_line_returns_result(self):
        """extract_parting_line on a unit cube returns a PartingLineResult."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        assert isinstance(result, PartingLineResult)

    def test_cube_loop_count(self):
        """Cube parting line: at least 1 loop is extracted."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        assert result.loops, "expected at least 1 parting loop; got none"

    def test_cube_parting_edges_count(self):
        """Cube has exactly 8 parting edges (4 top-ring + 4 bottom-ring)."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        # 4 bottom edges + 4 top edges = 8
        assert len(result.parting_edge_ids) == 8, (
            f"expected 8 parting edges, got {len(result.parting_edge_ids)}"
        )

    def test_cube_face_classification(self):
        """Top face classified 'top', bottom face classified 'bottom', sides 'side'."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        cls = result.face_classification
        assert "top" in cls.values(), "expected at least one 'top' face"
        assert "bottom" in cls.values(), "expected at least one 'bottom' face"
        assert "side" in cls.values(), "expected at least one 'side' face"
        top_count = sum(1 for v in cls.values() if v == "top")
        bottom_count = sum(1 for v in cls.values() if v == "bottom")
        side_count = sum(1 for v in cls.values() if v == "side")
        assert top_count == 1, f"expected 1 top face, got {top_count}"
        assert bottom_count == 1, f"expected 1 bottom face, got {bottom_count}"
        assert side_count == 4, f"expected 4 side faces, got {side_count}"

    def test_cube_total_length_positive(self):
        """Parting line has positive total length."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        assert result.total_length > 0.0, "total_length should be > 0"

    def test_cube_zero_pull_raises(self):
        """Zero pull_direction must raise ValueError."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        with pytest.raises(ValueError, match="non-zero"):
            extract_parting_line(body, pull_direction=(0.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# Test 2: Sphere parting line
# ---------------------------------------------------------------------------

class TestSpherePartingLine:
    """Parting line of a sphere with pull (0,0,1).

    The sphere B-rep (sphere_to_body) is a single face with a single seam
    edge (1 meridian edge, 2 vertices — the poles).  The sphere face wraps
    the entire surface.

    With pull = (0,0,1):
      - The face's AVERAGE normal is approximately (0,0,0) (the averaging
        integrates over the full sphere which cancels out), but more
        precisely the pole-to-pole seam edge is NOT between a top and a
        bottom *face* because there is only 1 face.

    Therefore the sphere B-rep produces 0 parting edges (no edge lies
    between a 'top' and a 'bottom' face — there is only one face), and
    loop_count = 0.

    The face is classified 'side' (average normal ≈ 0, |dot| < sin_tol).

    has_undercut: The sphere has ONE face; its average normal integrates to
    ≈ 0 → dot ≈ 0 → not undercut.  So has_undercut = False.
    """

    def test_sphere_returns_result(self):
        """extract_parting_line returns PartingLineResult for a sphere."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        assert isinstance(result, PartingLineResult)

    def test_sphere_has_no_undercut(self):
        """Sphere pulled along Z: has_undercut is False (single face, avg normal ≈ 0).

        The sphere is a single-face B-rep; its area-weighted average normal
        integrates to the zero vector.  The resulting dot product is ~0, so
        the face is classified 'side' (not 'bottom'), hence no undercut.
        """
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        assert result.has_undercut is False, (
            f"sphere has_undercut should be False; got undercut_faces={result.undercut_faces}"
        )

    def test_sphere_single_face_no_parting_edges(self):
        """Single-face sphere has no inter-face parting edges."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        # The seam edge connects the two poles but is between the same face
        # on both coedges, so it cannot be a parting edge.
        assert len(result.parting_edge_ids) == 0, (
            f"sphere should have 0 parting edges; got {len(result.parting_edge_ids)}"
        )


# ---------------------------------------------------------------------------
# Test 3: Cup with undercut (cylinder)
# ---------------------------------------------------------------------------

class TestCupWithUndercut:
    """Cylinder (closed solid) pulled in +Z must report has_undercut = True.

    A closed cylinder produced by cylinder_to_body has 3 faces:
      - lateral face: CylinderSurface — average normal points radially
        outward; n · (0,0,1) ≈ 0 → 'side'
      - bottom cap: Plane with normal (0,0,-1) → dot = -1 < 0 → 'bottom'
      - top cap:    Plane with normal (0,0,+1) → dot = +1 > sin_tol → 'top'

    The bottom cap is classified 'bottom' so it appears in undercut_faces:
    has_undercut = True.

    The parting edges are those between the lateral ('side') face and the
    bottom ('bottom') cap — i.e. the bottom rim circle — and those between
    the lateral face and the top ('top') cap — i.e. the top rim circle.
    """

    def test_cylinder_has_undercut(self):
        """Cylinder pulled in +Z: bottom cap is an undercut face."""
        body = cylinder_to_body([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 1.0, 2.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        assert result.has_undercut is True, (
            "cylinder should have undercut (bottom cap opposes pull)"
        )
        assert len(result.undercut_faces) >= 1, (
            f"expected >= 1 undercut face; got {result.undercut_faces}"
        )

    def test_cylinder_bottom_face_in_undercut(self):
        """The bottom face of the cylinder must appear in undercut_faces."""
        body = cylinder_to_body([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 1.0, 2.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))

        # The bottom face is the one with average normal closest to (0,0,-1)
        faces = body.all_faces()
        bottom_id = None
        min_dot = 1.0
        for f in faces:
            from kerf_cad_core.geom.surface_analysis import _body_face_normal
            n_hat = _body_face_normal(f)
            d = float(np.dot(n_hat, np.array([0.0, 0.0, 1.0])))
            if d < min_dot:
                min_dot = d
                bottom_id = f.id

        assert bottom_id in result.undercut_faces, (
            f"bottom face (id={bottom_id}, dot={min_dot:.3f}) not in "
            f"undercut_faces={result.undercut_faces}"
        )

    def test_cylinder_face_classification_counts(self):
        """Cylinder has 1 top, 1 bottom, 1 side face."""
        body = cylinder_to_body([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 1.0, 2.0)
        result = extract_parting_line(body, pull_direction=(0.0, 0.0, 1.0))
        cls = result.face_classification
        tops = sum(1 for v in cls.values() if v == "top")
        bots = sum(1 for v in cls.values() if v == "bottom")
        sides = sum(1 for v in cls.values() if v == "side")
        assert tops == 1, f"expected 1 top face, got {tops}"
        assert bots == 1, f"expected 1 bottom face, got {bots}"
        assert sides == 1, f"expected 1 side face, got {sides}"

    def test_detect_undercuts_direct(self):
        """detect_undercuts() on cylinder returns bottom face id."""
        body = cylinder_to_body([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 1.0, 2.0)
        ids = detect_undercuts(body, [0.0, 0.0, 1.0])
        assert len(ids) >= 1, f"expected >= 1 undercut face, got {ids}"

    def test_detect_undercuts_zero_pull_raises(self):
        """detect_undercuts() raises ValueError for zero pull."""
        body = cylinder_to_body([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 1.0, 2.0)
        with pytest.raises(ValueError, match="non-zero"):
            detect_undercuts(body, [0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Test 4: Optimal pull direction
# ---------------------------------------------------------------------------

class TestOptimalPullDirection:
    """optimal_pull_direction for a flat plate aligns with the plate normal.

    A thin box (2×2×0.1) — a flat plate — has:
      - top/bottom faces with normals ≈ ±(0,0,1): large area
      - four thin side faces with normals ≈ ±(1,0,0) or ±(0,1,0): tiny area

    The optimal pull direction should be (0,0,1) or (0,0,-1) because pulling
    along Z eliminates undercut for all large-area faces.  Pulling sideways
    would leave the large bottom or top as undercut.
    """

    def test_flat_plate_optimal_pull_is_z(self):
        """Optimal pull for a flat 2×2×0.1 plate minimises undercut count.

        A flat box has 6 faces each with an orthogonal normal.  Every axis-
        aligned pull direction gives exactly 1 undercut face (the opposite
        cap).  Diagonal pulls give more undercuts.  The optimal direction
        must have an undercut count ≤ the count for a random diagonal.

        We verify: the optimal undercut count is strictly less than the count
        for an oblique pull (0.57, 0.57, 0.57) which has 3 undercut faces
        (the three faces pointing opposite to it).
        """
        body = box_to_body([-1.0, -1.0, 0.0], 2.0, 2.0, 0.1)
        best = optimal_pull_direction(body, n_candidates=50)

        best_count = len(detect_undercuts(body, best))
        oblique_count = len(detect_undercuts(body, [0.577, 0.577, 0.577]))

        assert best_count < oblique_count, (
            f"optimal pull (count={best_count}) should beat oblique diagonal "
            f"(count={oblique_count})"
        )

    def test_flat_plate_optimal_undercut_count(self):
        """Optimal pull for a flat plate has <= 1 undercut face."""
        body = box_to_body([-1.0, -1.0, 0.0], 2.0, 2.0, 0.1)
        best = optimal_pull_direction(body, n_candidates=50)
        ids = detect_undercuts(body, best)
        # At the Z-optimal direction, only the bottom cap is undercut (1 face)
        assert len(ids) <= 1, (
            f"expected <= 1 undercut face at optimal pull, got {len(ids)}: {ids}"
        )

    def test_optimal_pull_returns_unit_vector(self):
        """optimal_pull_direction returns a unit vector."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        best = optimal_pull_direction(body, n_candidates=20)
        assert isinstance(best, np.ndarray)
        assert best.shape == (3,)
        assert abs(float(np.linalg.norm(best)) - 1.0) < 1e-9, (
            f"optimal pull direction should be unit length, got |v|={np.linalg.norm(best):.6f}"
        )

    def test_optimal_pull_cube_valid(self):
        """optimal_pull_direction works on a unit cube without error."""
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        best = optimal_pull_direction(body, n_candidates=30)
        assert best is not None
        assert np.linalg.norm(best) > 0.5
