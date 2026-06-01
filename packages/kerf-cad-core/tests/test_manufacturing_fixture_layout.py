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
    ContactPoint,
    FormClosureReport,
    ForceClosureReport,
    auto_fixture_layout,
    check_form_closure,
    check_force_closure_with_friction,
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


# ---------------------------------------------------------------------------
# 8. Asada-By §6 Form-closure analysis — helpers
# ---------------------------------------------------------------------------

def _make_contact(pos, normal, friction=False) -> ContactPoint:
    """Convenience factory for ContactPoint."""
    return ContactPoint(
        position_xyz_mm=pos,
        normal_xyz=normal,
        is_friction=friction,
    )


def _form_closed_contacts() -> list:
    """
    Nine frictionless contacts that are form-closed.

    We use a 3-2-1 layout (6 locators on 3 faces) PLUS 3 opposing clamp
    contacts (top, back, right).  The 6 locators push inward; the 3 clamps
    push from the opposite direction — together they positively span all 6
    wrench-space dimensions, giving a form-closed fixture.

    This mirrors the standard 3-2-1 + strap-clamp configuration from
    ASME B5.18-2018 §4.2 (analysed here frictionlessly for clarity).
    """
    bb = BoundingBox(0, 0, 0, 100, 50, 20)
    layout = auto_fixture_layout(bb)
    contacts = []
    for loc in layout.locators:
        contacts.append(_make_contact(
            tuple(loc.position), tuple(loc.normal), friction=False))
    # Add 3 opposing clamp contacts
    for clamp in layout.clamps:
        contacts.append(_make_contact(
            tuple(clamp.position), tuple(clamp.direction), friction=False))
    return contacts


# ---------------------------------------------------------------------------
# 8a. Form-closure: frictionless tests
# ---------------------------------------------------------------------------

class TestFormClosure:
    """Asada-By (1985) §6 frictionless form-closure tests."""

    def test_returns_form_closure_report(self):
        contacts = _form_closed_contacts()
        result = check_form_closure(contacts)
        assert isinstance(result, FormClosureReport)

    def test_3_2_1_plus_clamps_is_form_closed(self):
        """
        3-2-1 locators (6 contacts) PLUS 3 opposing clamp contacts (9 total)
        positively span R^6: the fixture is form-closed (Asada-By §6).
        """
        contacts = _form_closed_contacts()
        result = check_form_closure(contacts)
        assert result.form_closed is True, (
            f"Expected form-closed, missing: {result.missing_dof_directions}"
        )

    def test_form_closed_positive_margin(self):
        """Form-closed set must have margin ≥ 0."""
        contacts = _form_closed_contacts()
        result = check_form_closure(contacts)
        assert result.margin >= -1e-9  # allow tiny numerical noise

    def test_colinear_contacts_not_form_closed(self):
        """
        3 colinear contacts with parallel normals (all pointing +Z)
        cannot resist -Z forces, nor any torque about X or Y.
        The fixture is NOT form-closed (missing at least 3 DoF).
        """
        contacts = [
            _make_contact((10.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
            _make_contact((50.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
            _make_contact((90.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
        ]
        result = check_form_closure(contacts)
        assert result.form_closed is False

    def test_colinear_contacts_missing_directions(self):
        """Parallel-normal contacts must flag specific missing DoF."""
        contacts = [
            _make_contact((10.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
            _make_contact((50.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
            _make_contact((90.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
        ]
        result = check_form_closure(contacts)
        # At minimum -Z force is not resistible (no contact can push in -Z)
        assert "-Fz" in result.missing_dof_directions

    def test_colinear_contacts_missing_count_ge_3(self):
        """3 parallel-normal contacts miss at least 3 of 12 directions."""
        contacts = [
            _make_contact((10.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
            _make_contact((50.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
            _make_contact((90.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
        ]
        result = check_form_closure(contacts)
        assert len(result.missing_dof_directions) >= 3

    def test_empty_contacts_not_closed(self):
        """Empty contact list must return not-closed with all directions missing."""
        result = check_form_closure([])
        assert result.form_closed is False
        assert result.n_contacts == 0
        assert len(result.missing_dof_directions) == 12

    def test_single_contact_not_closed(self):
        """A single contact can resist only one force direction."""
        result = check_form_closure([
            _make_contact((50.0, 25.0, 0.0), (0.0, 0.0, 1.0)),
        ])
        assert result.form_closed is False
        assert result.n_contacts == 1

    def test_n_contacts_reported_correctly(self):
        """n_contacts in report must match input length."""
        contacts = _form_closed_contacts()
        result = check_form_closure(contacts)
        assert result.n_contacts == len(contacts)

    def test_not_form_closed_negative_margin(self):
        """Non-form-closed fixture must have margin < 0 or == 0."""
        contacts = [
            _make_contact((10.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
            _make_contact((50.0, 10.0, 0.0), (0.0, 0.0, 1.0)),
        ]
        result = check_form_closure(contacts)
        assert result.form_closed is False
        # margin must be non-positive for an infeasible direction
        assert result.margin <= 1e-9

    def test_honest_caveat_present(self):
        """FormClosureReport must carry a non-empty honest_caveat."""
        result = check_form_closure(_form_closed_contacts())
        assert isinstance(result.honest_caveat, str)
        assert len(result.honest_caveat) > 20

    def test_3_2_1_locators_alone_not_form_closed(self):
        """
        A 3-2-1 locator set (6 frictionless contacts, all pushing inward)
        is NOT form-closed by itself: the wrench set lacks opposing generators
        needed to resist forces in the outward directions.  Adding the 3 strap
        clamps (opposing contacts) closes the fixture — see
        test_3_2_1_plus_clamps_is_form_closed above.
        """
        bb = BoundingBox(0, 0, 0, 100, 50, 20)
        layout = auto_fixture_layout(bb)
        contacts = [
            ContactPoint(
                position_xyz_mm=tuple(loc.position),
                normal_xyz=tuple(loc.normal),
                is_friction=False,
            )
            for loc in layout.locators
        ]
        result = check_form_closure(contacts)
        # 6 one-sided locators cannot positively span all of R^6 —
        # there are always directions not resisted without the clamps.
        assert result.form_closed is False

    def test_two_parallel_opposite_contacts_only_one_axis(self):
        """
        Two opposing contacts (one +Z, one -Z) resist Fz but nothing else.
        """
        contacts = [
            _make_contact((50.0, 25.0, 0.0),  (0.0, 0.0,  1.0)),
            _make_contact((50.0, 25.0, 20.0), (0.0, 0.0, -1.0)),
        ]
        result = check_form_closure(contacts)
        assert result.form_closed is False
        # Fx, Fy directions should be missing
        assert "+Fx" in result.missing_dof_directions
        assert "+Fy" in result.missing_dof_directions


# ---------------------------------------------------------------------------
# 8b. Force-closure with friction tests
# ---------------------------------------------------------------------------

class TestForceClosureWithFriction:
    """Asada-By (1985) §6 force-closure (Coulomb friction) tests."""

    def test_returns_force_closure_report(self):
        contacts = _form_closed_contacts()
        result = check_force_closure_with_friction(contacts, mu=0.3)
        assert isinstance(result, ForceClosureReport)

    def test_four_frictional_contacts_mu03_force_closed(self):
        """
        4 frictional contacts μ=0.3 arranged on 4 faces of a cube — classic
        Mishra et al. 1987 force-closure configuration.  With μ=0.3 and
        well-spread normals the fixture should be force-closed.
        """
        # 4 contacts on a 100×50×20 box: bottom, top, front, back
        contacts = [
            _make_contact((25.0, 25.0, 0.0),  (0.0, 0.0,  1.0), friction=True),
            _make_contact((75.0, 25.0, 20.0), (0.0, 0.0, -1.0), friction=True),
            _make_contact((50.0, 0.0, 10.0),  (0.0, 1.0,  0.0), friction=True),
            _make_contact((50.0, 50.0, 10.0), (0.0, -1.0, 0.0), friction=True),
        ]
        result = check_force_closure_with_friction(contacts, mu=0.3)
        assert result.force_closed is True, (
            f"Expected force-closed, missing: {result.missing_dof_directions}"
        )

    def test_mu_stored_in_report(self):
        """mu used must be reflected in the report."""
        contacts = _form_closed_contacts()
        result = check_force_closure_with_friction(contacts, mu=0.5)
        assert result.mu == pytest.approx(0.5)

    def test_mu_zero_frictionless_colinear_not_closed(self):
        """
        4 contacts, μ=0 (frictionless): parallel-normal contacts are still
        not force-closed without the friction boost.
        """
        contacts = [
            _make_contact((10.0, 10.0, 0.0), (0.0, 0.0, 1.0), friction=True),
            _make_contact((90.0, 10.0, 0.0), (0.0, 0.0, 1.0), friction=True),
            _make_contact((10.0, 40.0, 0.0), (0.0, 0.0, 1.0), friction=True),
            _make_contact((90.0, 40.0, 0.0), (0.0, 0.0, 1.0), friction=True),
        ]
        result = check_force_closure_with_friction(contacts, mu=0.0)
        assert result.force_closed is False

    def test_mu_zero_equals_frictionless(self):
        """
        With μ=0 force-closure should agree with check_form_closure for
        the same set of contacts (regardless of is_friction flag).
        """
        contacts = _form_closed_contacts()
        fc_result = check_form_closure(contacts)
        ff_result = check_force_closure_with_friction(contacts, mu=0.0)
        assert fc_result.form_closed == ff_result.force_closed

    def test_friction_improves_closure(self):
        """
        4 frictional contacts on 4 faces of the workpiece (top, bottom, front,
        back) — frictionless each face alone cannot span R^6; with μ=0.3
        the 4-edge friction-cone expansion adds tangential generators that
        collectively span all 6 wrench dimensions.

        This matches the classic Mishra et al. (1987) result: 4 frictional
        contacts can achieve force-closure in 3D when placed on opposing faces.
        """
        # 4 contacts on 4 faces of a 100×50×20 workpiece
        contacts = [
            _make_contact((25.0, 25.0, 0.0),  (0.0, 0.0,  1.0), friction=True),
            _make_contact((75.0, 25.0, 20.0), (0.0, 0.0, -1.0), friction=True),
            _make_contact((50.0, 0.0, 10.0),  (0.0, 1.0,  0.0), friction=True),
            _make_contact((50.0, 50.0, 10.0), (0.0, -1.0, 0.0), friction=True),
        ]
        # Frictionless: NOT form-closed (missing X-force and several torques)
        fc = check_form_closure(contacts)
        assert fc.form_closed is False

        # With friction μ=0.3: force-closed (same configuration as
        # test_four_frictional_contacts_mu03_force_closed)
        ff = check_force_closure_with_friction(contacts, mu=0.3)
        assert ff.force_closed is True, (
            f"4-face frictional contacts (μ=0.3) should be force-closed. "
            f"Missing: {ff.missing_dof_directions}"
        )

    def test_n_wrench_generators_with_friction(self):
        """
        4 frictional contacts → 4×4 = 16 generators.
        """
        contacts = [
            _make_contact((25.0, 25.0, 0.0),  (0.0, 0.0, 1.0),  friction=True),
            _make_contact((75.0, 25.0, 20.0), (0.0, 0.0, -1.0), friction=True),
            _make_contact((50.0, 0.0, 10.0),  (0.0, 1.0, 0.0),  friction=True),
            _make_contact((50.0, 50.0, 10.0), (0.0, -1.0, 0.0), friction=True),
        ]
        result = check_force_closure_with_friction(contacts, mu=0.3)
        assert result.n_wrench_generators == 16

    def test_n_wrench_generators_without_friction(self):
        """
        Frictionless contacts (is_friction=False): generator count == n_contacts
        regardless of mu, because no friction-cone expansion is applied.
        """
        contacts = _form_closed_contacts()  # all is_friction=False, 9 contacts
        result = check_force_closure_with_friction(contacts, mu=0.3)
        assert result.n_wrench_generators == len(contacts)

    def test_empty_contacts_not_closed(self):
        """Empty contacts → not force-closed, 12 missing directions."""
        result = check_force_closure_with_friction([], mu=0.3)
        assert result.force_closed is False
        assert result.n_contacts == 0
        assert len(result.missing_dof_directions) == 12

    def test_honest_caveat_present(self):
        """ForceClosureReport must carry a non-empty honest_caveat."""
        contacts = _form_closed_contacts()
        result = check_force_closure_with_friction(contacts, mu=0.3)
        assert isinstance(result.honest_caveat, str)
        assert len(result.honest_caveat) > 20

    def test_mixed_friction_frictionless(self):
        """
        Mix of frictional and frictionless contacts: only frictional contacts
        get 4-edge cone expansion.  Generator count = 4*n_fric + n_no_fric.
        """
        contacts = [
            _make_contact((25.0, 25.0, 0.0),  (0.0, 0.0, 1.0),  friction=True),
            _make_contact((75.0, 25.0, 0.0),  (0.0, 0.0, 1.0),  friction=False),
        ]
        result = check_force_closure_with_friction(contacts, mu=0.3)
        # 1 frictional × 4 + 1 frictionless × 1 = 5
        assert result.n_wrench_generators == 5

    def test_negative_mu_clamped_to_zero(self):
        """Negative mu is equivalent to μ=0 (frictionless)."""
        contacts = _form_closed_contacts()
        result_neg = check_force_closure_with_friction(contacts, mu=-0.5)
        result_zero = check_force_closure_with_friction(contacts, mu=0.0)
        assert result_neg.force_closed == result_zero.force_closed
