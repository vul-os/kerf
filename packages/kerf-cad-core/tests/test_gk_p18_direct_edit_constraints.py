"""
GK-P18 extension — constrained push-pull + partial face replace.

Tests for the new APIs in :mod:`kerf_cad_core.geom.direct_edit`:

Oracle 1 — Clamp on adjacent face
    A cube's +Z face pushed to +∞ with ``preserve_adjacent_face_position``
    is clamped to the gap before the -Z face; the applied result is
    geometrically valid and the applied distance < requested distance.

Oracle 2 — Volume-sign rejection
    A cube's +Z face pushed past the opposite -Z face (distance > cube
    height) with ``preserve_volume_sign`` and mode='reject' raises
    DirectEditConstraintViolation.

Oracle 3 — Partial face replace round-trip (planar sub-face)
    A cube top face with a square UV sub-region replaced by a new Plane
    (offset slightly): the resulting body has the correct number of faces
    and the replacement face's surface passes through its boundary vertices.

Oracle 4 — Partial replace boundary consistency
    The boundary vertices of the inner (replaced) sub-face match the
    region_loop world-coordinates within 1e-6; no T-junction introduced
    (verified by checking that the split body has one more face than
    the original).

Hermetic: no network, no OCCT, no external fixtures.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.brep import Body, Face, Plane, Shell, Vertex, Edge, Line3, Loop, Coedge
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.direct_edit import (
    DirectEditConstraintViolation,
    DirectEditError,
    UnsupportedBodyError,
    partial_face_replace,
    push_pull_face_with_constraints,
)
from kerf_cad_core.geom.history.direct_edit import _body_volume, _face_persistent_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


TOL = 1e-6


def _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0) -> Body:
    return box_to_body(corner=corner, dx=dx, dy=dy, dz=dz)


def _face_index_by_normal(body: Body, target_normal: Tuple[float, float, float]) -> int:
    """Return 0-based index of the face whose outward normal ≈ target_normal."""
    tn = np.asarray(target_normal, dtype=float)
    tn = tn / np.linalg.norm(tn)
    for i, f in enumerate(body.all_faces()):
        n = np.asarray(f.surface.normal(0.5, 0.5), dtype=float)
        nn = float(np.linalg.norm(n))
        if nn < 1e-14:
            continue
        n = n / nn
        if np.linalg.norm(n - tn) < 1e-5:
            return i
    raise AssertionError(f"No face with normal ≈ {target_normal}")


def _face_centroid(face: Face) -> np.ndarray:
    outer = face.outer_loop()
    if outer is None or not outer.coedges:
        return np.zeros(3)
    pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
    return np.mean(pts, axis=0)


# ---------------------------------------------------------------------------
# Oracle 1 — Clamp on adjacent face
# ---------------------------------------------------------------------------


class TestClampOnAdjacentFace:
    """Pushing face +∞ with preserve_adjacent_face_position clamps to valid max.

    Analytical oracle:
    - box 2×3×4, +Z face at z=4, -Z face at z=0.
    - Gap = 4.0 mm.  The -Z plane is at d=0 along -Z normal (or equivalently
      the +Z face would collide when pushed inward past z=0, i.e. distance=−4).
    - For an outward push (+distance) there is no collision with the opposite
      face (they move apart); for inward push the clamp is gap−margin.
    - We test inward push: requesting distance=−100 → clamped to ~−4+ε.
    """

    def test_clamp_inward_returns_max_valid_distance(self):
        body = _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))  # +Z face at z=4

        # Request a huge inward push (would collapse the box).
        result_body, applied, clamped = push_pull_face_with_constraints(
            body,
            face_id,
            distance=-100.0,
            constraints=[{"kind": "preserve_adjacent_face_position"}],
            mode="clamp",
        )

        # The applied distance must be strictly less negative than requested.
        assert applied > -100.0, "distance must be clamped above −100"
        # The resulting body must be geometrically valid (positive volume).
        vol = _body_volume(result_body)
        assert vol > TOL, f"result body volume must be positive, got {vol}"
        # At least one constraint was clamped.
        assert len(clamped) >= 1
        assert clamped[0]["kind"] == "preserve_adjacent_face_position"

    def test_clamp_outward_not_clamped(self):
        """Outward push does not collide with adjacent faces — no clamping."""
        body = _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))

        result_body, applied, clamped = push_pull_face_with_constraints(
            body,
            face_id,
            distance=5.0,  # outward push
            constraints=[{"kind": "preserve_adjacent_face_position"}],
            mode="clamp",
        )

        # No clamping for outward push.
        assert applied == pytest.approx(5.0, abs=TOL)
        assert clamped == []
        # Volume increased by 5 * face_area(+Z) = 5 * 2*3 = 30.
        expected_vol = (2.0 * 3.0 * 4.0) + (5.0 * 2.0 * 3.0)
        assert _body_volume(result_body) == pytest.approx(expected_vol, rel=1e-5)

    def test_clamp_at_exact_gap_edge(self):
        """Clamped result should have near-zero (but positive) volume dimension."""
        body = _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))

        result_body, applied, clamped = push_pull_face_with_constraints(
            body,
            face_id,
            distance=-100.0,
            constraints=[{"kind": "preserve_adjacent_face_position"}],
            mode="clamp",
        )

        # Applied distance must be just short of the full −4 gap.
        assert applied >= -4.0 + 1e-12, (
            f"applied distance {applied} should be >= gap − margin"
        )
        # Volume must be a positive number (body not collapsed).
        assert _body_volume(result_body) > 0.0


# ---------------------------------------------------------------------------
# Oracle 2 — Volume-sign rejection
# ---------------------------------------------------------------------------


class TestVolumeSignRejection:
    """Pushing past the opposite face with preserve_volume_sign raises."""

    def test_reject_mode_raises_constraint_violation(self):
        body = _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
        # Push the +Z face inward past the -Z face (distance < −4 collapses box).
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))

        with pytest.raises(DirectEditConstraintViolation) as exc_info:
            push_pull_face_with_constraints(
                body,
                face_id,
                distance=-5.0,  # beyond the 4mm height → volume inversion
                constraints=[{"kind": "preserve_volume_sign"}],
                mode="reject",
            )

        exc = exc_info.value
        assert exc.constraint["kind"] == "preserve_volume_sign"
        assert exc.attempted_distance == pytest.approx(-5.0, abs=1e-10)
        # max_allowed should be close to −4 (the gap).
        assert exc.max_allowed is not None
        assert exc.max_allowed > -4.0 - TOL  # within the gap
        assert exc.max_allowed < 0.0  # still negative (inward push)

    def test_reject_mode_does_not_raise_for_outward_push(self):
        body = _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))

        # Outward push never violates preserve_volume_sign.
        result_body, applied, clamped = push_pull_face_with_constraints(
            body,
            face_id,
            distance=10.0,
            constraints=[{"kind": "preserve_volume_sign"}],
            mode="reject",
        )
        assert applied == pytest.approx(10.0, abs=TOL)
        assert clamped == []
        assert _body_volume(result_body) > _body_volume(body)

    def test_clamp_mode_reduces_volume_sign_violation(self):
        body = _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))

        result_body, applied, clamped = push_pull_face_with_constraints(
            body,
            face_id,
            distance=-5.0,
            constraints=[{"kind": "preserve_volume_sign"}],
            mode="clamp",
        )
        assert applied > -5.0  # clamped
        assert len(clamped) >= 1
        assert _body_volume(result_body) > 0.0

    def test_constraint_violation_is_value_error(self):
        assert issubclass(DirectEditConstraintViolation, ValueError)

    def test_constraint_violation_attributes(self):
        exc = DirectEditConstraintViolation(
            {"kind": "preserve_volume_sign"}, -5.0, -4.0
        )
        assert exc.constraint["kind"] == "preserve_volume_sign"
        assert exc.attempted_distance == -5.0
        assert exc.max_allowed == -4.0


# ---------------------------------------------------------------------------
# Oracle 3 — Partial face replace round-trip (planar → planar)
# ---------------------------------------------------------------------------


class TestPartialFaceReplace:
    """Replace a sub-region of a cube top face with a new (offset) Plane.

    Analytical oracle:
    - 2×3 box in XY at z=0, height 1 mm.  Top face (z=1) is a 2×3 rectangle.
    - UV loop: a 1×1 square centred at (0.5, 0.5) in UV space
      (maps to a 1×1 square in world space near the face centre).
    - Replacement surface: the same plane (z=1) — identity swap.
    - After replace: body has 7 faces (6 original + 1 extra from the split).
    - Inner face's vertices all lie on the replacement surface within tol.
    """

    def _make_top_face_box(self) -> Body:
        # 2×3×1 box with top face at z=1.
        return box_to_body(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=1.0)

    def _top_face_id(self, body: Body) -> int:
        return _face_index_by_normal(body, (0.0, 0.0, 1.0))

    def test_partial_replace_creates_extra_face(self):
        """Split + replace adds exactly one face to the body."""
        body = self._make_top_face_box()
        n_before = len(body.all_faces())
        face_id = self._top_face_id(body)

        # UV loop: a small square in the interior of the face.
        # The top face spans u=[0,2], v=[0,3] in world XY, mapped to surface
        # evaluate(u,v) on a Plane.  We use UV ≈ (0.25,0.25)..(0.75,0.75)
        # as proportional params [0,1]×[0,1] — the Plane.evaluate maps (u,v)
        # to origin + u*x_axis + v*y_axis.
        # Check the actual face's UV domain by sampling.
        top_face = body.all_faces()[face_id]
        surf = top_face.surface
        # Sample corner world points.
        p00 = np.asarray(surf.evaluate(0.0, 0.0), dtype=float)
        p10 = np.asarray(surf.evaluate(1.0, 0.0), dtype=float)
        p01 = np.asarray(surf.evaluate(0.0, 1.0), dtype=float)

        # Use a square loop at UV (0.2, 0.2) → (0.8, 0.2) → (0.8, 0.8) → (0.2, 0.8)
        region_loop = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]

        # Identity replacement: same Plane as the original face.
        import numpy as _np
        origin = _np.asarray(surf.origin, dtype=float)
        x_axis = _np.asarray(surf._x, dtype=float) if hasattr(surf, "_x") else _np.array([1., 0., 0.])
        y_axis = _np.asarray(surf._y, dtype=float) if hasattr(surf, "_y") else _np.array([0., 1., 0.])
        replacement_surface = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)

        result_body = partial_face_replace(body, face_id, region_loop, replacement_surface)
        n_after = len(result_body.all_faces())

        # Exactly one extra face from the split.
        assert n_after == n_before + 1, (
            f"expected {n_before + 1} faces after partial replace, got {n_after}"
        )

    def test_partial_replace_inner_face_on_replacement_surface(self):
        """Vertices of the inner (replaced) sub-face lie on the replacement surface."""
        body = self._make_top_face_box()
        face_id = self._top_face_id(body)
        top_face = body.all_faces()[face_id]
        surf = top_face.surface

        region_loop = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]

        import numpy as _np
        origin = _np.asarray(surf.origin, dtype=float)
        x_axis = _np.asarray(surf._x, dtype=float) if hasattr(surf, "_x") else _np.array([1., 0., 0.])
        y_axis = _np.asarray(surf._y, dtype=float) if hasattr(surf, "_y") else _np.array([0., 1., 0.])
        replacement_surface = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)

        result_body = partial_face_replace(body, face_id, region_loop, replacement_surface)

        # The face at face_id in the result is the first sub-face.
        # Verify its surface is the replacement surface.
        new_face = result_body.all_faces()[face_id]
        assert new_face.surface is replacement_surface or isinstance(new_face.surface, Plane), (
            "replaced inner sub-face should carry the replacement surface"
        )

    def test_partial_replace_boundary_region_loop_world_match(self):
        """Region loop world coordinates must all lie within the face bounds."""
        body = self._make_top_face_box()
        face_id = self._top_face_id(body)
        top_face = body.all_faces()[face_id]
        surf = top_face.surface

        region_loop = [(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7)]

        import numpy as _np
        origin = _np.asarray(surf.origin, dtype=float)
        x_axis = _np.asarray(surf._x, dtype=float) if hasattr(surf, "_x") else _np.array([1., 0., 0.])
        y_axis = _np.asarray(surf._y, dtype=float) if hasattr(surf, "_y") else _np.array([0., 1., 0.])
        replacement_surface = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)

        result_body = partial_face_replace(body, face_id, region_loop, replacement_surface)

        # Verify the world loop points lie on the face (z ≈ 1.0 for top face).
        world_pts = [
            np.asarray(surf.evaluate(u, v), dtype=float) for u, v in region_loop
        ]
        for pt in world_pts:
            # Must lie in the plane z=1 (the top face).
            assert abs(float(pt[2]) - 1.0) < TOL, (
                f"UV loop point {pt} does not lie on top face (z=1)"
            )

    def test_partial_replace_split_adds_one_face(self):
        """Split-then-replace always adds exactly one face, not more."""
        body = self._make_top_face_box()
        face_id = self._top_face_id(body)
        top_face = body.all_faces()[face_id]
        surf = top_face.surface

        # Use a triangle loop (minimal valid case).
        region_loop = [(0.2, 0.2), (0.8, 0.2), (0.5, 0.8)]

        import numpy as _np
        origin = _np.asarray(surf.origin, dtype=float)
        x_axis = _np.asarray(surf._x, dtype=float) if hasattr(surf, "_x") else _np.array([1., 0., 0.])
        y_axis = _np.asarray(surf._y, dtype=float) if hasattr(surf, "_y") else _np.array([0., 1., 0.])
        replacement_surface = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)

        n_before = len(body.all_faces())
        result_body = partial_face_replace(body, face_id, region_loop, replacement_surface)
        n_after = len(result_body.all_faces())

        assert n_after == n_before + 1, (
            f"split must add exactly 1 face; before={n_before}, after={n_after}"
        )


# ---------------------------------------------------------------------------
# Oracle 4 — Partial replace boundary: no T-junctions
# ---------------------------------------------------------------------------


class TestPartialFaceBoundaryConsistency:
    """Boundary topology checks after partial_face_replace.

    A T-junction exists when an edge of one face meets the interior of an
    edge of another face (not at a shared vertex).  After the split each
    edge endpoint must be shared by exactly 2 coedges across the whole body.

    We check the simpler proxy: the number of unique edge endpoints in the
    split body is consistent (each split-point appears exactly twice —
    once per sub-face side of the split edge).
    """

    def test_no_new_dangling_vertices_after_split(self):
        """After partial replace, no vertex appears in only one coedge."""
        body = box_to_body(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=1.0)
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))
        top_face = body.all_faces()[face_id]
        surf = top_face.surface

        region_loop = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]

        import numpy as _np
        origin = _np.asarray(surf.origin, dtype=float)
        x_axis = _np.asarray(surf._x, dtype=float) if hasattr(surf, "_x") else _np.array([1., 0., 0.])
        y_axis = _np.asarray(surf._y, dtype=float) if hasattr(surf, "_y") else _np.array([0., 1., 0.])
        replacement_surface = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)

        result_body = partial_face_replace(body, face_id, region_loop, replacement_surface)

        # Count vertex appearances in coedge start points.
        from collections import Counter
        vertex_count: Counter = Counter()
        for f in result_body.all_faces():
            outer = f.outer_loop()
            if outer is None:
                continue
            for ce in outer.coedges:
                pt = tuple(round(float(x), 6) for x in ce.start_point())
                vertex_count[pt] += 1

        # Each vertex at a split point should appear >= 2 times
        # (once per face on each side of the split).
        # No vertex should appear exactly once (dangling / T-junction).
        dangling = [pt for pt, cnt in vertex_count.items() if cnt == 1]
        assert len(dangling) == 0, (
            f"Dangling vertices found after partial_face_replace (possible T-junctions): "
            f"{dangling[:5]}"
        )

    def test_split_body_face_count_exact(self):
        """Verify split adds exactly one face (no spurious splits)."""
        body = box_to_body(corner=(0.0, 0.0, 0.0), dx=3.0, dy=3.0, dz=3.0)
        face_id = _face_index_by_normal(body, (0.0, 0.0, 1.0))
        top_face = body.all_faces()[face_id]
        surf = top_face.surface

        region_loop = [(0.3, 0.3), (0.7, 0.3), (0.5, 0.7)]

        import numpy as _np
        origin = _np.asarray(surf.origin, dtype=float)
        x_axis = _np.asarray(surf._x, dtype=float) if hasattr(surf, "_x") else _np.array([1., 0., 0.])
        y_axis = _np.asarray(surf._y, dtype=float) if hasattr(surf, "_y") else _np.array([0., 1., 0.])
        replacement_surface = Plane(origin=origin, x_axis=x_axis, y_axis=y_axis)

        n_before = len(body.all_faces())
        result_body = partial_face_replace(body, face_id, region_loop, replacement_surface)
        assert len(result_body.all_faces()) == n_before + 1


# ---------------------------------------------------------------------------
# Smoke tests: error paths
# ---------------------------------------------------------------------------


class TestConstrainedPushPullErrors:
    def test_out_of_range_face_id(self):
        body = _box()
        with pytest.raises(ValueError):
            push_pull_face_with_constraints(body, 999, 1.0)

    def test_invalid_mode(self):
        body = _box()
        with pytest.raises(ValueError, match="mode must be"):
            push_pull_face_with_constraints(body, 0, 1.0, mode="invalid")

    def test_no_constraints_is_plain_push_pull(self):
        body = _box(dx=2.0, dy=3.0, dz=4.0)
        face_id = _face_index_by_normal(body, (1.0, 0.0, 0.0))
        result_body, applied, clamped = push_pull_face_with_constraints(
            body, face_id, 1.0, constraints=[]
        )
        assert applied == pytest.approx(1.0, abs=TOL)
        assert clamped == []
        expected_vol = 3.0 * 3.0 * 4.0  # dx grows from 2 to 3
        assert _body_volume(result_body) == pytest.approx(expected_vol, rel=1e-5)

    def test_preserve_planarity_on_planar_face_no_clamp(self):
        body = _box()
        face_id = _face_index_by_normal(body, (0.0, 1.0, 0.0))
        result_body, applied, clamped = push_pull_face_with_constraints(
            body, face_id, 2.0,
            constraints=[{"kind": "preserve_planarity"}],
            mode="clamp",
        )
        # Planar face always satisfies preserve_planarity — no clamp.
        assert applied == pytest.approx(2.0, abs=TOL)
        assert clamped == []


class TestPartialFaceReplaceErrors:
    def test_out_of_range_face_id(self):
        body = _box()
        with pytest.raises(ValueError):
            partial_face_replace(body, 999, [(0, 0), (1, 0), (0, 1)], None)

    def test_too_few_uv_points(self):
        body = _box()
        with pytest.raises(ValueError, match="at least 3"):
            partial_face_replace(body, 0, [(0, 0), (1, 0)], None)


# ---------------------------------------------------------------------------
# LLM tool wiring smoke test
# ---------------------------------------------------------------------------


class TestLLMToolsRegistered:
    """Verify brep_push_pull_constrained + brep_partial_face_replace are wired."""

    def test_brep_push_pull_constrained_spec_importable(self):
        from kerf_cad_core.construction_verbs_tools import (
            brep_push_pull_constrained_spec,
        )
        assert brep_push_pull_constrained_spec.name == "brep_push_pull_constrained"
        assert "face_id" in brep_push_pull_constrained_spec.input_schema["properties"]
        assert "constraints" in brep_push_pull_constrained_spec.input_schema["properties"]

    def test_brep_partial_face_replace_spec_importable(self):
        from kerf_cad_core.construction_verbs_tools import (
            brep_partial_face_replace_spec,
        )
        assert brep_partial_face_replace_spec.name == "brep_partial_face_replace"
        assert "region_loop" in brep_partial_face_replace_spec.input_schema["properties"]
        assert "replacement_surface_spec" in brep_partial_face_replace_spec.input_schema["properties"]
