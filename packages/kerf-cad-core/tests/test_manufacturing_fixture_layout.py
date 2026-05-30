"""
Hermetic tests for kerf_cad_core.manufacturing_fixture_layout.

Coverage:
  BoundingBox.validate              — dimensions, degenerate detection
  auto_fixture_layout               — rectangular workpiece → valid 3-2-1
  auto_fixture_layout               — degenerate (1D) workpiece → ValueError
  _build_wrench_matrix              — shape and content
  _matrix_rank                      — known rank-6 matrix, rank-deficient matrix
  FixtureLayout.to_dict             — serialisation round-trip
  clamp-force scaling               — harder material → larger force
  operations scaling                — milling > drilling > grinding
  LLM tool wrapper                  — happy path + bad args + degenerate bbox

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References
----------
Asada, H. & By, A.B. (1985). "Kinematics analysis of workpart fixturing for
flexible assembly with automatically reconfigurable fixtures."
IEEE J. Robot. Autom., 1(2), 86-94.

ASME B5.18-2018, §4.2 3-2-1 layout requirements.
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.manufacturing_fixture_layout import (
    BoundingBox,
    FixtureLayout,
    Locator,
    auto_fixture_layout,
    _build_wrench_matrix,
    _matrix_rank,
    _estimate_clamp_force,
    _yield_mpa,
    _op_factor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rect_bbox(dx=100.0, dy=50.0, dz=20.0) -> BoundingBox:
    """Standard 100 × 50 × 20 mm workpiece aligned to origin."""
    return BoundingBox(0, 0, 0, dx, dy, dz)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


# ---------------------------------------------------------------------------
# 1. BoundingBox validation
# ---------------------------------------------------------------------------

class TestBoundingBox:

    def test_valid_box(self):
        bb = _rect_bbox()
        assert bb.validate() is None

    def test_zero_dx(self):
        bb = BoundingBox(0, 0, 0, 0, 50, 20)
        assert "dx" in bb.validate()

    def test_zero_dy(self):
        bb = BoundingBox(0, 0, 0, 100, 0, 20)
        assert "dy" in bb.validate()

    def test_zero_dz(self):
        bb = BoundingBox(0, 0, 0, 100, 50, 0)
        assert "dz" in bb.validate()

    def test_negative_dimension(self):
        bb = BoundingBox(0, 0, 0, -10, 50, 20)
        assert bb.validate() is not None

    def test_dimensions(self):
        bb = _rect_bbox(100, 50, 20)
        assert bb.dx == pytest.approx(100.0)
        assert bb.dy == pytest.approx(50.0)
        assert bb.dz == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 2. Constraint matrix rank
# ---------------------------------------------------------------------------

class TestMatrixRank:

    def test_identity_rank_6(self):
        """6×6 identity → rank 6."""
        I = [[1.0 if i == j else 0.0 for j in range(6)] for i in range(6)]
        assert _matrix_rank(I) == 6

    def test_rank_deficient(self):
        """Two identical rows → rank 5."""
        A = [[1.0 if i == j else 0.0 for j in range(6)] for i in range(6)]
        A[1] = list(A[0])   # duplicate row 0
        assert _matrix_rank(A) <= 5

    def test_all_zeros(self):
        """All-zero matrix → rank 0."""
        Z = [[0.0] * 6 for _ in range(6)]
        assert _matrix_rank(Z) == 0

    def test_rank_1(self):
        """All rows are the same non-zero vector → rank 1."""
        v = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        A = [list(v) for _ in range(6)]
        assert _matrix_rank(A) == 1


# ---------------------------------------------------------------------------
# 3. Wrench matrix construction
# ---------------------------------------------------------------------------

class TestBuildWrenchMatrix:

    def test_shape(self):
        layout = auto_fixture_layout(_rect_bbox())
        W = _build_wrench_matrix(layout.locators)
        assert len(W) == 6
        assert all(len(row) == 6 for row in W)

    def test_normal_columns(self):
        """First three columns are the locator normals."""
        layout = auto_fixture_layout(_rect_bbox())
        W = _build_wrench_matrix(layout.locators)
        # P1-P3 normal = (0,0,1)
        for i in range(3):
            assert W[i][2] == pytest.approx(1.0)
        # P4-P5 normal = (0,1,0)
        for i in range(3, 5):
            assert W[i][1] == pytest.approx(1.0)
        # P6 normal = (1,0,0)
        assert W[5][0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. auto_fixture_layout — happy path
# ---------------------------------------------------------------------------

class TestAutoFixtureLayout:

    def test_returns_fixture_layout(self):
        layout = auto_fixture_layout(_rect_bbox())
        assert isinstance(layout, FixtureLayout)

    def test_six_locators(self):
        layout = auto_fixture_layout(_rect_bbox())
        assert len(layout.locators) == 6

    def test_three_clamps(self):
        layout = auto_fixture_layout(_rect_bbox())
        assert len(layout.clamps) == 3

    def test_locator_names(self):
        layout = auto_fixture_layout(_rect_bbox())
        names = [loc.name for loc in layout.locators]
        assert names == ["P1", "P2", "P3", "P4", "P5", "P6"]

    def test_face_assignments(self):
        layout = auto_fixture_layout(_rect_bbox())
        locs = {loc.name: loc for loc in layout.locators}
        for name in ("P1", "P2", "P3"):
            assert locs[name].face == "primary"
        for name in ("P4", "P5"):
            assert locs[name].face == "secondary"
        assert locs["P6"].face == "tertiary"

    def test_valid_flag(self):
        """Standard 100×50×20 workpiece must yield a valid 3-2-1 layout."""
        layout = auto_fixture_layout(_rect_bbox())
        assert layout.valid is True
        assert layout.constraint_rank == 6

    def test_primary_on_bottom_face(self):
        """P1-P3 must lie on Z=0 plane."""
        bb = _rect_bbox()
        layout = auto_fixture_layout(bb)
        locs = {loc.name: loc for loc in layout.locators}
        for name in ("P1", "P2", "P3"):
            assert locs[name].position[2] == pytest.approx(bb.zmin)

    def test_secondary_on_front_face(self):
        """P4-P5 must lie on Y=0 plane."""
        bb = _rect_bbox()
        layout = auto_fixture_layout(bb)
        locs = {loc.name: loc for loc in layout.locators}
        for name in ("P4", "P5"):
            assert locs[name].position[1] == pytest.approx(bb.ymin)

    def test_tertiary_on_left_face(self):
        """P6 must lie on X=0 plane."""
        bb = _rect_bbox()
        layout = auto_fixture_layout(bb)
        locs = {loc.name: loc for loc in layout.locators}
        assert locs["P6"].position[0] == pytest.approx(bb.xmin)

    def test_primary_normals(self):
        layout = auto_fixture_layout(_rect_bbox())
        locs = {loc.name: loc for loc in layout.locators}
        for name in ("P1", "P2", "P3"):
            assert locs[name].normal == pytest.approx((0.0, 0.0, 1.0))

    def test_secondary_normals(self):
        layout = auto_fixture_layout(_rect_bbox())
        locs = {loc.name: loc for loc in layout.locators}
        for name in ("P4", "P5"):
            assert locs[name].normal == pytest.approx((0.0, 1.0, 0.0))

    def test_tertiary_normal(self):
        layout = auto_fixture_layout(_rect_bbox())
        locs = {loc.name: loc for loc in layout.locators}
        assert locs["P6"].normal == pytest.approx((1.0, 0.0, 0.0))

    def test_primary_positions_non_collinear(self):
        """P1-P3 must not be collinear (needed for rank-6 constraint matrix)."""
        layout = auto_fixture_layout(_rect_bbox())
        locs = {loc.name: loc for loc in layout.locators}
        p1 = locs["P1"].position
        p2 = locs["P2"].position
        p3 = locs["P3"].position
        # Cross product of (p2-p1) and (p3-p1) must be non-zero
        v1 = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
        v2 = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])
        cross = (
            v1[1] * v2[2] - v1[2] * v2[1],
            v1[2] * v2[0] - v1[0] * v2[2],
            v1[0] * v2[1] - v1[1] * v2[0],
        )
        mag = math.sqrt(sum(c * c for c in cross))
        assert mag > 1e-6, "P1-P3 are collinear — cannot constrain Rx and Ry"

    def test_secondary_positions_distinct(self):
        """P4-P5 must be distinct (needed to constrain Rz)."""
        layout = auto_fixture_layout(_rect_bbox())
        locs = {loc.name: loc for loc in layout.locators}
        p4 = locs["P4"].position
        p5 = locs["P5"].position
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(p4, p5)))
        assert dist > 1e-6, "P4 and P5 are co-located — cannot constrain Rz"

    def test_notes_present(self):
        layout = auto_fixture_layout(_rect_bbox())
        assert len(layout.notes) >= 4
        asada_ref = any("Asada" in n or "ASME" in n for n in layout.notes)
        assert asada_ref

    def test_material_stored(self):
        layout = auto_fixture_layout(_rect_bbox(), material="steel")
        assert layout.material == "steel"

    def test_operations_stored(self):
        layout = auto_fixture_layout(_rect_bbox(), operations=["drilling"])
        assert "drilling" in layout.operations

    def test_to_dict_round_trip(self):
        layout = auto_fixture_layout(_rect_bbox())
        d = layout.to_dict()
        assert d["valid"] is True
        assert d["constraint_rank"] == 6
        assert len(d["locators"]) == 6
        assert len(d["clamps"]) == 3
        # JSON-serialisable
        raw = json.dumps(d)
        d2 = json.loads(raw)
        assert d2["valid"] is True

    def test_offset_bbox(self):
        """Non-origin bbox should also produce a valid layout."""
        bb = BoundingBox(100, 200, 50, 200, 250, 70)
        layout = auto_fixture_layout(bb)
        assert layout.valid is True
        assert layout.constraint_rank == 6


# ---------------------------------------------------------------------------
# 5. Degenerate workpiece → ValueError
# ---------------------------------------------------------------------------

class TestDegenerateWorkpiece:

    def test_1d_zero_dy(self):
        bb = BoundingBox(0, 0, 0, 100, 0, 20)
        with pytest.raises(ValueError, match="dy"):
            auto_fixture_layout(bb)

    def test_1d_zero_dz(self):
        bb = BoundingBox(0, 0, 0, 100, 50, 0)
        with pytest.raises(ValueError, match="dz"):
            auto_fixture_layout(bb)

    def test_1d_zero_dx(self):
        bb = BoundingBox(0, 0, 0, 0, 50, 20)
        with pytest.raises(ValueError, match="dx"):
            auto_fixture_layout(bb)

    def test_inverted_bbox(self):
        bb = BoundingBox(100, 50, 20, 0, 0, 0)  # min > max
        with pytest.raises(ValueError):
            auto_fixture_layout(bb)


# ---------------------------------------------------------------------------
# 6. Clamp-force scaling
# ---------------------------------------------------------------------------

class TestClampForceScaling:

    def test_titanium_harder_than_aluminum(self):
        bb = _rect_bbox()
        f_al = _estimate_clamp_force(bb, "aluminum", ["milling"])
        f_ti = _estimate_clamp_force(bb, "titanium", ["milling"])
        assert f_ti > f_al, "Titanium should require higher clamp force than aluminum"

    def test_steel_harder_than_polymer(self):
        bb = _rect_bbox()
        f_poly = _estimate_clamp_force(bb, "polymer", ["milling"])
        f_steel = _estimate_clamp_force(bb, "steel", ["milling"])
        assert f_steel > f_poly

    def test_milling_greater_than_grinding(self):
        bb = _rect_bbox()
        f_mill = _estimate_clamp_force(bb, "aluminum", ["milling"])
        f_grind = _estimate_clamp_force(bb, "aluminum", ["grinding"])
        assert f_mill > f_grind

    def test_drilling_greater_than_grinding(self):
        bb = _rect_bbox()
        f_drill = _estimate_clamp_force(bb, "aluminum", ["drilling"])
        f_grind = _estimate_clamp_force(bb, "aluminum", ["grinding"])
        assert f_drill > f_grind

    def test_larger_bbox_larger_force(self):
        bb_small = _rect_bbox(50, 25, 10)
        bb_large = _rect_bbox(200, 100, 40)
        f_small = _estimate_clamp_force(bb_small, "aluminum", ["milling"])
        f_large = _estimate_clamp_force(bb_large, "aluminum", ["milling"])
        assert f_large > f_small

    def test_clamp_forces_in_layout(self):
        """C1 clamp force should be positive."""
        layout = auto_fixture_layout(_rect_bbox(), material="steel",
                                     operations=["milling"])
        assert layout.clamps[0].force_n > 0
        assert layout.clamps[1].force_n > 0
        assert layout.clamps[2].force_n > 0

    def test_material_yield_lookup(self):
        assert _yield_mpa("aluminum") == pytest.approx(270.0)
        assert _yield_mpa("titanium") == pytest.approx(880.0)
        assert _yield_mpa("polymer") == pytest.approx(60.0)

    def test_op_factor_milling(self):
        assert _op_factor(["milling"]) == pytest.approx(2.5)

    def test_op_factor_multi_takes_max(self):
        """Multiple operations → highest-force governs."""
        f_multi = _op_factor(["grinding", "milling"])
        f_mill = _op_factor(["milling"])
        assert f_multi == pytest.approx(f_mill)


# ---------------------------------------------------------------------------
# 7. LLM tool wrapper
# ---------------------------------------------------------------------------

class TestLLMTool:

    def _try_import(self):
        try:
            from kerf_cad_core.manufacturing_fixture_layout import (
                run_manufacturing_auto_fixture_layout,
            )
            return run_manufacturing_auto_fixture_layout
        except ImportError:
            pytest.skip("kerf_chat not installed — skipping LLM tool tests")

    def test_happy_path_rectangular(self):
        fn = self._try_import()
        raw = _run(fn(None, _args(
            xmin=0, ymin=0, zmin=0,
            xmax=100, ymax=50, zmax=20,
            material="aluminum",
            operations=["milling"],
        )))
        d = json.loads(raw)
        # ok_payload returns the dict directly (no envelope)
        assert d.get("ok") is not False, f"Expected success, got: {d}"
        # happy path: either direct result dict or {ok:true, result:...}
        result = d.get("result", d)
        assert result.get("valid") is True
        assert result.get("constraint_rank") == 6
        assert len(result.get("locators", [])) == 6

    def test_bad_json(self):
        fn = self._try_import()
        raw = _run(fn(None, b"not json"))
        d = json.loads(raw)
        assert d.get("ok") is False or "error" in d

    def test_degenerate_bbox(self):
        fn = self._try_import()
        raw = _run(fn(None, _args(
            xmin=0, ymin=0, zmin=0,
            xmax=0, ymax=50, zmax=20,   # zero dx
        )))
        d = json.loads(raw)
        assert d.get("ok") is False or "error" in d

    def test_missing_required_fields(self):
        fn = self._try_import()
        raw = _run(fn(None, _args(xmin=0, ymin=0, zmin=0)))
        # xmax/ymax/zmax missing → defaults to 0 → degenerate
        d = json.loads(raw)
        assert d.get("ok") is False or "error" in d

    def test_material_steel_drilling(self):
        fn = self._try_import()
        raw = _run(fn(None, _args(
            xmin=0, ymin=0, zmin=0,
            xmax=200, ymax=100, zmax=50,
            material="steel",
            operations=["drilling"],
        )))
        d = json.loads(raw)
        assert d.get("ok") is not False, f"Expected success, got: {d}"
        result = d.get("result", d)
        assert result.get("material") == "steel"

    def test_operations_not_list(self):
        fn = self._try_import()
        raw = _run(fn(None, _args(
            xmin=0, ymin=0, zmin=0,
            xmax=100, ymax=50, zmax=20,
            operations="milling",   # string, not list
        )))
        d = json.loads(raw)
        assert d.get("ok") is False or "error" in d
