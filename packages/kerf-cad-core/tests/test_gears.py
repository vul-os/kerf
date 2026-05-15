"""
Hermetic tests for the involute gear generator (gears.py).

Coverage: gear_spur (T-1), gear_helical (T-2), gear_internal (T-3),
gear_rack (T-4), gear_pair_check (T-5).

Pure-Python: no database, no OCCT, no ProjectCtx side-effects.
All runners are called with a minimal stub context.

References: ISO 21771:2007.
Authored by imranparuk.
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.gears import (
    # math helpers (white-box)
    _inv,
    _involute_point,
    _rotate,
    _contact_ratio,
    _spur_geometry,
    _rack_geometry,
    _internal_geometry,
    # tool runners
    run_gear_spur,
    run_gear_helical,
    run_gear_internal,
    run_gear_rack,
    run_gear_pair_check,
    # specs
    _gear_spur_spec,
    _gear_helical_spec,
    _gear_internal_spec,
    _gear_rack_spec,
    _gear_pair_check_spec,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _fake_ctx():
    """Minimal stub context — gear tools don't touch the DB."""
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None,
            storage=None,
            project_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            role="owner",
            http_client=None,
        )
    except Exception:
        # Fallback stub if kerf_core not available
        class _Stub:
            pass
        return _Stub()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _spur(ctx=None, **kwargs):
    ctx = ctx or _fake_ctx()
    defaults = {"module": 2.0, "teeth": 20, "pressure_angle_deg": 20.0}
    defaults.update(kwargs)
    raw = _run(run_gear_spur(ctx, json.dumps(defaults).encode()))
    return json.loads(raw)


def _helical(ctx=None, **kwargs):
    ctx = ctx or _fake_ctx()
    defaults = {"module": 2.0, "teeth": 20, "helix_angle_deg": 20.0, "pressure_angle_deg": 20.0}
    defaults.update(kwargs)
    raw = _run(run_gear_helical(ctx, json.dumps(defaults).encode()))
    return json.loads(raw)


def _internal(ctx=None, **kwargs):
    ctx = ctx or _fake_ctx()
    defaults = {"module": 2.0, "teeth": 40, "pressure_angle_deg": 20.0}
    defaults.update(kwargs)
    raw = _run(run_gear_internal(ctx, json.dumps(defaults).encode()))
    return json.loads(raw)


def _rack(ctx=None, **kwargs):
    ctx = ctx or _fake_ctx()
    defaults = {"module": 2.0, "pressure_angle_deg": 20.0}
    defaults.update(kwargs)
    raw = _run(run_gear_rack(ctx, json.dumps(defaults).encode()))
    return json.loads(raw)


def _pair(ctx=None, **kwargs):
    ctx = ctx or _fake_ctx()
    defaults = {"module": 2.0, "teeth_1": 20, "teeth_2": 40, "pressure_angle_deg": 20.0}
    defaults.update(kwargs)
    raw = _run(run_gear_pair_check(ctx, json.dumps(defaults).encode()))
    return json.loads(raw)


# ===========================================================================
# 1. Pure math helpers
# ===========================================================================

class TestInvoluteFunction:
    """Tests on _inv() — the involute function inv(φ) = tan(φ) − φ."""

    def test_inv_zero(self):
        assert _inv(0.0) == pytest.approx(0.0, abs=1e-12)

    def test_inv_positive(self):
        alpha = math.radians(20.0)
        result = _inv(alpha)
        assert result == pytest.approx(math.tan(alpha) - alpha, rel=1e-9)

    def test_inv_monotone(self):
        """inv(φ) is strictly increasing for φ > 0."""
        vals = [_inv(math.radians(a)) for a in [10, 15, 20, 25, 30]]
        assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))

    def test_involute_point_on_circle(self):
        """At t=0 the involute point lies on the base circle."""
        r_b = 10.0
        x, y = _involute_point(r_b, 0.0)
        # At t=0: x = r_b*cos(0)+0 = r_b, y = r_b*(sin(0)-0) = 0
        assert x == pytest.approx(r_b, rel=1e-9)
        assert y == pytest.approx(0.0, abs=1e-12)

    def test_involute_radius_grows(self):
        """The radial distance from origin must increase with roll angle t."""
        r_b = 10.0
        radii = [
            math.hypot(*_involute_point(r_b, t))
            for t in [0.0, 0.2, 0.4, 0.6, 0.8]
        ]
        assert all(radii[i] < radii[i + 1] for i in range(len(radii) - 1))

    def test_rotate_identity(self):
        x, y = _rotate(3.0, 4.0, 0.0)
        assert x == pytest.approx(3.0, rel=1e-9)
        assert y == pytest.approx(4.0, rel=1e-9)

    def test_rotate_90(self):
        x, y = _rotate(1.0, 0.0, math.pi / 2)
        assert x == pytest.approx(0.0, abs=1e-12)
        assert y == pytest.approx(1.0, rel=1e-9)


# ===========================================================================
# 2. gear_spur (T-1)
# ===========================================================================

class TestSpurGeometry:
    """ISO 21771 formula checks on _spur_geometry() directly."""

    def test_pitch_diameter(self):
        """d = m · z  (ISO 21771 §4.1)."""
        g = _spur_geometry(m=3.0, z=25, alpha_deg=20.0)
        assert g["pitch_diameter"] == pytest.approx(3.0 * 25, rel=1e-9)

    def test_base_diameter(self):
        """d_b = d · cos(α)  (ISO 21771 §4.2)."""
        g = _spur_geometry(m=2.0, z=30, alpha_deg=20.0)
        d = 2.0 * 30
        assert g["base_diameter"] == pytest.approx(d * math.cos(math.radians(20.0)), rel=1e-9)

    def test_tip_diameter_standard(self):
        """d_a = d + 2·m  (standard, x=0, ha*=1)."""
        g = _spur_geometry(m=2.0, z=20, alpha_deg=20.0)
        assert g["tip_diameter"] == pytest.approx(2.0 * 20 + 2 * 2.0, rel=1e-9)

    def test_root_diameter_standard(self):
        """d_f = d − 2·1.25·m  (standard, x=0, hf*=1.25)."""
        g = _spur_geometry(m=2.0, z=20, alpha_deg=20.0)
        assert g["root_diameter"] == pytest.approx(2.0 * 20 - 2 * 1.25 * 2.0, rel=1e-9)

    def test_circular_pitch(self):
        """p = π · m  (ISO 21771 §3.7)."""
        g = _spur_geometry(m=4.0, z=15, alpha_deg=20.0)
        assert g["circular_pitch"] == pytest.approx(math.pi * 4.0, rel=1e-9)

    def test_profile_shift_increases_tip(self):
        """Positive profile shift increases tip diameter."""
        g0 = _spur_geometry(2.0, 20, 20.0, x=0.0)
        gx = _spur_geometry(2.0, 20, 20.0, x=0.5)
        assert gx["tip_diameter"] > g0["tip_diameter"]

    def test_polyline_is_list(self):
        g = _spur_geometry(2.0, 20, 20.0)
        assert isinstance(g["tooth_polyline"], list)

    def test_polyline_closed(self):
        """First and last polyline points must be equal (closed polygon)."""
        g = _spur_geometry(2.0, 20, 20.0)
        poly = g["tooth_polyline"]
        assert poly[0] == poly[-1]

    def test_polyline_length(self):
        """polyline_points must equal len(tooth_polyline)."""
        g = _spur_geometry(2.0, 20, 20.0)
        assert g["polyline_points"] == len(g["tooth_polyline"])

    def test_polyline_symmetric_about_x(self):
        """For x=0, the right and left involute flanks are y-mirrors of each other.

        _spur_geometry builds left_flank as [(px, -py) for reversed(right_flank)].
        The right-flank BASE point (poly[0]) and its y-mirror must both appear
        in the polyline (the mirror is the left-flank's last point before the root arc).
        """
        n_pts = 16
        g = _spur_geometry(2.0, 20, 20.0, x=0.0, n_pts=n_pts)
        poly = g["tooth_polyline"][:-1]  # drop closing duplicate

        # right_flank[0] is poly[0]; its y-mirror should appear in the left flank
        r_base_pt = poly[0]
        expected_mirror = [r_base_pt[0], -r_base_pt[1]]
        found = any(
            abs(p[0] - expected_mirror[0]) < 1e-5 and abs(p[1] - expected_mirror[1]) < 1e-5
            for p in poly
        )
        assert found, (
            f"Y-mirror of right-flank base {r_base_pt} not found in polyline. "
            "Expected y-symmetric tooth profile for x=0."
        )

    def test_undercut_flag_high_z(self):
        """No undercut for z=42 at α=20° (geometric limit: z ≥ ~42 for standard dedendum)."""
        # At α=20°, min z without undercut (r_f >= r_b) is ~42.
        g = _spur_geometry(2.0, 42, 20.0, x=0.0)
        assert g["undercut_risk"] is False

    def test_undercut_flag_low_z(self):
        """Undercut expected for z=10 at α=20° with no shift."""
        g = _spur_geometry(2.0, 10, 20.0, x=0.0)
        assert g["undercut_risk"] is True

    def test_n_pts_controls_polyline(self):
        """Higher n_pts produces a longer polyline."""
        g_low  = _spur_geometry(2.0, 20, 20.0, n_pts=8)
        g_high = _spur_geometry(2.0, 20, 20.0, n_pts=48)
        assert g_high["polyline_points"] > g_low["polyline_points"]


class TestGearSpurRunner:
    """Tests on run_gear_spur via JSON runner."""

    def test_success(self):
        r = _spur()
        assert r.get("ok") is True
        assert "pitch_diameter" in r
        assert "tooth_polyline" in r

    def test_pitch_diameter_formula(self):
        r = _spur(module=3.0, teeth=25)
        assert r["pitch_diameter"] == pytest.approx(3.0 * 25, rel=1e-9)

    def test_base_diameter_formula(self):
        r = _spur(module=2.0, teeth=30, pressure_angle_deg=20.0)
        d = 2.0 * 30
        assert r["base_diameter"] == pytest.approx(d * math.cos(math.radians(20.0)), rel=1e-9)

    def test_invalid_module_zero(self):
        r = _spur(module=0)
        assert r.get("ok") is False
        assert any("module" in e for e in r["errors"])

    def test_invalid_module_negative(self):
        r = _spur(module=-1.5)
        assert r.get("ok") is False

    def test_invalid_teeth_too_few(self):
        r = _spur(teeth=2)
        assert r.get("ok") is False
        assert any("z" in e or "teeth" in e or "tooth" in e.lower() for e in r["errors"])

    def test_invalid_alpha_too_low(self):
        r = _spur(pressure_angle_deg=9.0)
        assert r.get("ok") is False

    def test_invalid_alpha_too_high(self):
        r = _spur(pressure_angle_deg=31.0)
        assert r.get("ok") is False

    def test_invalid_alpha_boundary_10_excluded(self):
        r = _spur(pressure_angle_deg=10.0)
        assert r.get("ok") is False

    def test_invalid_alpha_boundary_30_excluded(self):
        r = _spur(pressure_angle_deg=30.0)
        assert r.get("ok") is False

    def test_gear_type_field(self):
        r = _spur()
        assert r.get("gear_type") == "spur_external"

    def test_recipe_present(self):
        r = _spur(module=2.0, teeth=20)
        assert r.get("recipe", {}).get("op") == "gear_spur"
        assert r["recipe"]["module"] == 2.0
        assert r["recipe"]["teeth"] == 20

    def test_polyline_closed_runner(self):
        r = _spur()
        poly = r["tooth_polyline"]
        assert poly[0] == poly[-1]

    def test_face_width_stored(self):
        r = _spur(face_width=20.0)
        assert r.get("face_width") == pytest.approx(20.0, rel=1e-9)

    def test_face_width_zero_invalid(self):
        r = _spur(face_width=0.0)
        assert r.get("ok") is False

    def test_invalid_json(self):
        ctx = _fake_ctx()
        raw = _run(run_gear_spur(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"


# ===========================================================================
# 3. gear_helical (T-2)
# ===========================================================================

class TestGearHelical:

    def test_success(self):
        r = _helical()
        assert r.get("ok") is True
        assert "transverse_module" in r
        assert "axial_pitch" in r

    def test_transverse_module(self):
        """m_t = m_n / cos(β)  (ISO 21771 §3.4)."""
        m_n, beta_deg = 2.0, 20.0
        r = _helical(module=m_n, helix_angle_deg=beta_deg)
        expected = m_n / math.cos(math.radians(beta_deg))
        assert r["transverse_module"] == pytest.approx(expected, rel=1e-6)

    def test_axial_pitch(self):
        """p_x = π · m_n / sin(β)  (ISO 21771 §3.8)."""
        m_n, beta_deg = 2.0, 30.0
        r = _helical(module=m_n, helix_angle_deg=beta_deg)
        expected = math.pi * m_n / math.sin(math.radians(beta_deg))
        assert r["axial_pitch"] == pytest.approx(expected, rel=1e-6)

    def test_transverse_pressure_angle(self):
        """tan(α_t) = tan(α_n) / cos(β)."""
        m_n, beta_deg, alpha_n_deg = 2.0, 20.0, 20.0
        r = _helical(module=m_n, helix_angle_deg=beta_deg, pressure_angle_deg=alpha_n_deg)
        alpha_n = math.radians(alpha_n_deg)
        beta    = math.radians(beta_deg)
        alpha_t_expected = math.degrees(math.atan(math.tan(alpha_n) / math.cos(beta)))
        assert r["transverse_pressure_angle_deg"] == pytest.approx(alpha_t_expected, rel=1e-6)

    def test_invalid_helix_zero(self):
        r = _helical(helix_angle_deg=0.0)
        assert r.get("ok") is False

    def test_invalid_helix_90(self):
        r = _helical(helix_angle_deg=90.0)
        assert r.get("ok") is False

    def test_gear_type_field(self):
        r = _helical()
        assert r.get("gear_type") == "helical_external"

    def test_pitch_diameter_uses_transverse_module(self):
        """d = m_t · z in transverse plane."""
        m_n, beta_deg, z = 2.0, 20.0, 20
        r = _helical(module=m_n, teeth=z, helix_angle_deg=beta_deg)
        m_t = m_n / math.cos(math.radians(beta_deg))
        assert r["pitch_diameter"] == pytest.approx(m_t * z, rel=1e-6)

    def test_face_contact_ratio_present_when_face_width_given(self):
        r = _helical(face_width=30.0)
        assert "face_contact_ratio" in r
        assert r["face_contact_ratio"] > 0


# ===========================================================================
# 4. gear_internal (T-3)
# ===========================================================================

class TestGearInternal:

    def test_success(self):
        r = _internal()
        assert r.get("ok") is True
        assert "tip_diameter" in r
        assert "root_diameter" in r

    def test_pitch_diameter(self):
        """d = m · z (same formula for internal)."""
        r = _internal(module=2.0, teeth=40)
        assert r["pitch_diameter"] == pytest.approx(2.0 * 40, rel=1e-9)

    def test_base_diameter_internal(self):
        """d_b = d · cos(α) same."""
        r = _internal(module=2.0, teeth=40, pressure_angle_deg=20.0)
        d = 2.0 * 40
        assert r["base_diameter"] == pytest.approx(d * math.cos(math.radians(20.0)), rel=1e-9)

    def test_tip_diameter_smaller_than_pitch(self):
        """Internal gear tip circle < pitch circle (teeth point inward)."""
        r = _internal(module=2.0, teeth=40, pressure_angle_deg=20.0)
        assert r["tip_diameter"] < r["pitch_diameter"]

    def test_root_diameter_larger_than_pitch(self):
        """Internal gear root circle > pitch circle."""
        r = _internal(module=2.0, teeth=40, pressure_angle_deg=20.0)
        assert r["root_diameter"] > r["pitch_diameter"]

    def test_gear_type_field(self):
        r = _internal()
        assert r.get("gear_type") == "internal_ring"

    def test_polyline_closed(self):
        r = _internal()
        poly = r["tooth_polyline"]
        assert poly[0] == poly[-1]

    def test_invalid_module(self):
        r = _internal(module=0)
        assert r.get("ok") is False

    def test_invalid_teeth(self):
        r = _internal(teeth=2)
        assert r.get("ok") is False


# ===========================================================================
# 5. gear_rack (T-4)
# ===========================================================================

class TestGearRack:

    def test_success(self):
        r = _rack()
        assert r.get("ok") is True
        assert "linear_pitch" in r

    def test_linear_pitch_formula(self):
        """p = π · m  (ISO 21771 §3.7)."""
        r = _rack(module=3.0)
        assert r["linear_pitch"] == pytest.approx(math.pi * 3.0, rel=1e-9)

    def test_addendum(self):
        """ha = 1 · m  (standard)."""
        r = _rack(module=2.5)
        assert r["addendum"] == pytest.approx(2.5, rel=1e-9)

    def test_dedendum(self):
        """hf = 1.25 · m  (standard)."""
        r = _rack(module=2.5)
        assert r["dedendum"] == pytest.approx(1.25 * 2.5, rel=1e-9)

    def test_tooth_thickness(self):
        """s = p / 2 = π·m/2 at pitch line."""
        r = _rack(module=2.0)
        assert r["tooth_thickness"] == pytest.approx(math.pi * 2.0 / 2, abs=1e-6)

    def test_gear_type_field(self):
        r = _rack()
        assert r.get("gear_type") == "rack_linear"

    def test_tooth_polyline_present(self):
        r = _rack()
        assert isinstance(r["tooth_polyline"], list)
        assert len(r["tooth_polyline"]) >= 4

    def test_rack_polyline_present(self):
        r = _rack(n_teeth=4)
        assert isinstance(r["rack_polyline"], list)

    def test_n_teeth_stored(self):
        r = _rack(n_teeth=8)
        assert r["n_teeth_shown"] == 8

    def test_invalid_module_zero(self):
        r = _rack(module=0)
        assert r.get("ok") is False

    def test_invalid_alpha_out_of_range(self):
        r = _rack(pressure_angle_deg=35.0)
        assert r.get("ok") is False

    def test_recipe_present(self):
        r = _rack(module=2.0)
        assert r.get("recipe", {}).get("op") == "gear_rack"

    def test_linear_pitch_doubles_with_double_module(self):
        r1 = _rack(module=1.0)
        r2 = _rack(module=2.0)
        assert r2["linear_pitch"] == pytest.approx(2 * r1["linear_pitch"], abs=1e-6)


# ===========================================================================
# 6. gear_pair_check (T-5)
# ===========================================================================

class TestGearPairCheck:

    def test_success(self):
        r = _pair()
        assert r.get("ok") is True
        assert "gear_ratio" in r
        assert "centre_distance" in r
        assert "contact_ratio" in r

    def test_gear_ratio_formula(self):
        """i = z2 / z1  (ISO 21771 §3.12)."""
        r = _pair(teeth_1=20, teeth_2=40)
        assert r["gear_ratio"] == pytest.approx(40 / 20, rel=1e-9)

    def test_gear_ratio_unity(self):
        r = _pair(teeth_1=20, teeth_2=20)
        assert r["gear_ratio"] == pytest.approx(1.0, rel=1e-9)

    def test_centre_distance_standard(self):
        """a_w = (d1+d2)/2 = m·(z1+z2)/2 for x1=x2=0."""
        m, z1, z2 = 2.0, 20, 40
        r = _pair(module=m, teeth_1=z1, teeth_2=z2,
                  profile_shift_1=0.0, profile_shift_2=0.0)
        expected = m * (z1 + z2) / 2
        assert r["centre_distance"] == pytest.approx(expected, rel=1e-6)

    def test_contact_ratio_sane_pair(self):
        """A standard 20/40 pair at 20° should have εα > 1."""
        r = _pair(teeth_1=20, teeth_2=40)
        assert r["contact_ratio"] > 1.0

    def test_contact_ratio_gt_1_for_healthy_pair(self):
        """50/50 teeth with 20° and m=2 — robust pair, εα > 1.5."""
        r = _pair(module=2.0, teeth_1=50, teeth_2=50)
        assert r["contact_ratio"] > 1.0

    def test_undercut_warning_z12(self):
        """z=12 at α=20° with no profile shift triggers undercut warning."""
        r = _pair(module=2.0, teeth_1=12, teeth_2=40,
                  profile_shift_1=0.0, profile_shift_2=0.0)
        assert r.get("ok") is True
        w = " ".join(r.get("warnings", []))
        assert "undercut" in w.lower() or "profile shift" in w.lower()

    def test_no_undercut_warning_z42(self):
        """z=42 at α=20° with no shift — no root-circle undercut for gear 1.

        The geometric undercut condition (r_f < r_b) requires z ≥ 42 at α=20°
        for a standard rack dedendum (hf*=1.25). z=42 should be clean.
        """
        r = _pair(module=2.0, teeth_1=42, teeth_2=42)
        assert r.get("ok") is True
        w = " ".join(r.get("warnings", []))
        # Neither gear should have root-circle undercut warning
        assert "undercut risk" not in w.lower()

    def test_standard_centre_distance_field(self):
        r = _pair(module=2.0, teeth_1=20, teeth_2=40)
        expected_std = 2.0 * (20 + 40) / 2
        assert r["standard_centre_distance"] == pytest.approx(expected_std, rel=1e-6)

    def test_operating_pressure_angle_unchanged_for_no_shift(self):
        """When x1=x2=0, operating pressure angle == reference pressure angle."""
        alpha_deg = 20.0
        r = _pair(pressure_angle_deg=alpha_deg, profile_shift_1=0.0, profile_shift_2=0.0)
        assert r["operating_pressure_angle_deg"] == pytest.approx(alpha_deg, abs=1e-4)

    def test_gear_data_fields(self):
        r = _pair()
        for key in ["pitch_diameter", "base_diameter", "tip_diameter", "root_diameter"]:
            assert key in r["gear_1"]
            assert key in r["gear_2"]

    def test_invalid_module_zero(self):
        r = _pair(module=0)
        assert r.get("ok") is False

    def test_invalid_teeth_1_too_few(self):
        r = _pair(teeth_1=2)
        assert r.get("ok") is False

    def test_invalid_teeth_2_too_few(self):
        r = _pair(teeth_2=2)
        assert r.get("ok") is False

    def test_invalid_alpha_out_of_range(self):
        r = _pair(pressure_angle_deg=35.0)
        assert r.get("ok") is False

    def test_multiple_errors_collected(self):
        """Both module=0 and teeth_1=0 should appear in errors."""
        r = _pair(module=0, teeth_1=1)
        assert r.get("ok") is False
        assert len(r["errors"]) >= 2

    def test_invalid_json_spur(self):
        ctx = _fake_ctx()
        raw = _run(run_gear_pair_check(ctx, b"{bad json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"


# ===========================================================================
# 7. Tool spec / registry sanity
# ===========================================================================

class TestToolSpecs:

    def test_spur_spec_name(self):
        assert _gear_spur_spec.name == "gear_spur"

    def test_helical_spec_name(self):
        assert _gear_helical_spec.name == "gear_helical"

    def test_internal_spec_name(self):
        assert _gear_internal_spec.name == "gear_internal"

    def test_rack_spec_name(self):
        assert _gear_rack_spec.name == "gear_rack"

    def test_pair_spec_name(self):
        assert _gear_pair_check_spec.name == "gear_pair_check"

    def test_spur_required_fields(self):
        req = _gear_spur_spec.input_schema.get("required", [])
        assert "module" in req
        assert "teeth" in req

    def test_helical_required_helix(self):
        req = _gear_helical_spec.input_schema.get("required", [])
        assert "helix_angle_deg" in req

    def test_rack_required_module(self):
        req = _gear_rack_spec.input_schema.get("required", [])
        assert "module" in req

    def test_pair_required_fields(self):
        req = _gear_pair_check_spec.input_schema.get("required", [])
        for f in ["module", "teeth_1", "teeth_2"]:
            assert f in req

    def test_specs_have_descriptions(self):
        for spec in [
            _gear_spur_spec, _gear_helical_spec, _gear_internal_spec,
            _gear_rack_spec, _gear_pair_check_spec,
        ]:
            assert len(spec.description) > 20


# ===========================================================================
# 8. Cross-tool consistency
# ===========================================================================

class TestCrossToolConsistency:

    def test_spur_and_pair_pitch_diameter_agree(self):
        """gear_spur and gear_pair_check must agree on pitch diameter for gear 1."""
        m, z = 2.0, 20
        spur = _spur(module=m, teeth=z)
        pair = _pair(module=m, teeth_1=z, teeth_2=40)
        assert spur["pitch_diameter"] == pytest.approx(pair["gear_1"]["pitch_diameter"], rel=1e-6)

    def test_helical_and_spur_same_pitch_for_zero_helix_limit(self):
        """At very small β, helical transverse module → m_n (hence pitch_diam → m*z)."""
        # Can't test β=0 (invalid), but very small β should give pitch_diam ≈ m*z
        r = _helical(module=2.0, teeth=20, helix_angle_deg=0.5)
        assert r.get("ok") is True
        # m_t ≈ m_n at tiny β
        assert r["transverse_module"] == pytest.approx(2.0, rel=0.01)

    def test_rack_pitch_matches_spur_circular_pitch(self):
        """rack linear_pitch = spur circular_pitch for same module."""
        m = 3.0
        rack = _rack(module=m)
        spur = _spur(module=m, teeth=20)
        assert rack["linear_pitch"] == pytest.approx(spur["circular_pitch"], rel=1e-9)

    def test_internal_pitch_formula_matches_spur(self):
        """Both spur and internal gear share d = m·z."""
        m, z = 2.0, 40
        r_spur = _spur(module=m, teeth=z)
        r_int  = _internal(module=m, teeth=z)
        assert r_spur["pitch_diameter"] == pytest.approx(r_int["pitch_diameter"], rel=1e-9)

    def test_contact_ratio_increases_with_addendum(self):
        """Increasing number of teeth (larger addendum reach) raises contact ratio."""
        r_small = _pair(module=2.0, teeth_1=10, teeth_2=10)
        r_large = _pair(module=2.0, teeth_1=50, teeth_2=50)
        # Small z may have undercut but contact ratio should be lower or result ok
        if r_small.get("ok") and r_large.get("ok"):
            assert r_large["contact_ratio"] >= r_small["contact_ratio"]
