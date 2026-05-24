"""Tests for GK-P29 — Roof geometry generator (hip/gable/shed/mono).

DoD: roof generator emits a valid closed Body; IfcRoof dict present;
ridge_z and face counts match expected values.
"""
from __future__ import annotations
import math
import pytest

pytest.importorskip("kerf_cad_core", reason="kerf_cad_core not available")

from kerf_bim.roof_geometry import (
    RoofParams,
    RoofGeometry,
    make_roof,
    RoofValidationError,
)


def _default_params(**kwargs) -> RoofParams:
    base = dict(
        x_min=0.0, y_min=0.0, x_max=12_000.0, y_max=8_000.0,
        base_z=3_000.0, pitch_deg=30.0, overhang=600.0,
    )
    base.update(kwargs)
    return RoofParams(**base)


class TestRoofValidation:
    def test_invalid_type_raises(self):
        with pytest.raises(RoofValidationError):
            RoofParams(roof_type="mansard")

    def test_zero_width_raises(self):
        with pytest.raises(RoofValidationError):
            RoofParams(roof_type="gable", x_min=0, x_max=0, y_min=0, y_max=10)

    def test_flat_pitch_raises(self):
        with pytest.raises(RoofValidationError):
            _default_params(pitch_deg=0.0)

    def test_vertical_pitch_raises(self):
        with pytest.raises(RoofValidationError):
            _default_params(pitch_deg=90.0)


class TestGableRoof:
    def test_returns_roof_geometry(self):
        rg = make_roof(_default_params(roof_type="gable"))
        assert isinstance(rg, RoofGeometry)

    def test_body_not_none(self):
        rg = make_roof(_default_params(roof_type="gable"))
        assert rg.body is not None

    def test_body_has_shell(self):
        rg = make_roof(_default_params(roof_type="gable"))
        assert len(rg.body.solids) == 1
        solid = rg.body.solids[0]
        assert len(solid.shells) == 1

    def test_gable_has_4_faces(self):
        """Gable: 2 sloped + 2 gable triangles = 4 faces."""
        rg = make_roof(_default_params(roof_type="gable"))
        assert rg.faces_count == 4

    def test_ridge_z_correct(self):
        """ridge_z = base_z + half_width_with_overhang * tan(pitch)."""
        p = _default_params(roof_type="gable", pitch_deg=45.0, overhang=0.0)
        rg = make_roof(p)
        expected_rise = (p.y_max - p.y_min) / 2.0 * math.tan(math.radians(45.0))
        assert abs(rg.ridge_z - (p.base_z + expected_rise)) < 1.0  # 1mm tolerance

    def test_ridge_pts_two_points(self):
        rg = make_roof(_default_params(roof_type="gable"))
        assert len(rg.ridge_pts) == 2

    def test_ifc_dict_present(self):
        rg = make_roof(_default_params(roof_type="gable"))
        assert rg.ifc_dict["type"] == "IfcRoof"
        assert rg.ifc_dict["predefined_type"] == "GABLE_ROOF"
        assert "pitch_deg" in rg.ifc_dict

    def test_all_faces_have_loops(self):
        rg = make_roof(_default_params(roof_type="gable"))
        shell = rg.body.solids[0].shells[0]
        for face in shell.faces:
            assert len(face.loops) >= 1
            assert len(face.loops[0].coedges) >= 3


class TestHipRoof:
    def test_hip_returns_body(self):
        rg = make_roof(_default_params(roof_type="hip"))
        assert rg.body is not None

    def test_hip_rectangle_4_faces(self):
        """Non-square rectangular hip: 4 faces (2 trapezoids + 2 triangles)."""
        rg = make_roof(_default_params(roof_type="hip"))
        assert rg.faces_count == 4

    def test_hip_square_pyramid_4_faces(self):
        """Square plan hip = pyramid: 4 triangular faces."""
        p = _default_params(roof_type="hip", x_max=8_000.0, y_max=8_000.0)
        rg = make_roof(p)
        assert rg.faces_count == 4

    def test_hip_ifc_type(self):
        rg = make_roof(_default_params(roof_type="hip"))
        assert rg.ifc_dict["predefined_type"] == "HIP_ROOF"

    def test_hip_ridge_z_positive(self):
        rg = make_roof(_default_params(roof_type="hip"))
        assert rg.ridge_z > _default_params().base_z


class TestShedRoof:
    def test_shed_returns_body(self):
        rg = make_roof(_default_params(roof_type="shed"))
        assert rg.body is not None

    def test_shed_1_face(self):
        """Shed has exactly 1 sloped face."""
        rg = make_roof(_default_params(roof_type="shed"))
        assert rg.faces_count == 1

    def test_mono_alias(self):
        """'mono' is an alias for 'shed'."""
        rg_shed = make_roof(_default_params(roof_type="shed"))
        rg_mono = make_roof(_default_params(roof_type="mono"))
        assert rg_shed.faces_count == rg_mono.faces_count
        assert rg_shed.ifc_dict["predefined_type"] == rg_mono.ifc_dict["predefined_type"]

    def test_shed_ridge_z_greater_than_base(self):
        rg = make_roof(_default_params(roof_type="shed"))
        assert rg.ridge_z > _default_params().base_z

    def test_shed_ridge_z_correct(self):
        """Shed: rise = full width * tan(pitch)."""
        p = _default_params(roof_type="shed", pitch_deg=30.0, overhang=0.0)
        rg = make_roof(p)
        width = p.y_max - p.y_min
        expected_rise = width * math.tan(math.radians(30.0))
        assert abs(rg.ridge_z - (p.base_z + expected_rise)) < 1.0

    def test_shed_ifc_type(self):
        rg = make_roof(_default_params(roof_type="shed"))
        assert rg.ifc_dict["predefined_type"] == "SHED_ROOF"
