"""GK-116 -- Hermetic oracle test: lattice fill of a Body to target relative density.

Oracle (from spec):
  Filling a box at relative_density ~ 0.2 yields a body whose volume
  ~ 0.2 * box_volume +/- reasonable tolerance (+/-0.1).
"""

from __future__ import annotations

import pytest

from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.lattice import lattice_fill
from kerf_cad_core.geom import lattice_fill as geom_lattice_fill


def _make_box(dx=30.0, dy=30.0, dz=30.0):
    return box_to_body((0.0, 0.0, 0.0), dx, dy, dz)


class TestLatticeFillContract:
    def test_returns_dict_with_required_keys(self):
        body = _make_box()
        result = lattice_fill(body, cell_type="gyroid", relative_density=0.2)
        assert set(result.keys()) >= {"mesh", "body", "achieved_density"}

    def test_mesh_has_verts_and_faces(self):
        body = _make_box()
        result = lattice_fill(body, cell_type="gyroid", relative_density=0.2)
        mesh = result["mesh"]
        assert "verts" in mesh and "faces" in mesh

    def test_body_field_is_none(self):
        body = _make_box()
        result = lattice_fill(body, cell_type="gyroid", relative_density=0.2)
        assert result["body"] is None

    def test_achieved_density_is_float_in_range(self):
        body = _make_box()
        result = lattice_fill(body, cell_type="gyroid", relative_density=0.2)
        ad = result["achieved_density"]
        assert isinstance(ad, float)
        assert 0.0 <= ad <= 1.0

    def test_mesh_is_non_empty(self):
        body = _make_box()
        result = lattice_fill(body, cell_type="gyroid", relative_density=0.2)
        assert len(result["mesh"]["verts"]) > 0
        assert len(result["mesh"]["faces"]) > 0

    def test_invalid_cell_type_raises(self):
        body = _make_box()
        with pytest.raises(ValueError):
            lattice_fill(body, cell_type="banana")

    def test_invalid_relative_density_zero_raises(self):
        body = _make_box()
        with pytest.raises(ValueError):
            lattice_fill(body, relative_density=0.0)

    def test_invalid_relative_density_one_raises(self):
        body = _make_box()
        with pytest.raises(ValueError):
            lattice_fill(body, relative_density=1.0)

    def test_re_exported_from_geom(self):
        body = _make_box()
        result = geom_lattice_fill(body, cell_type="gyroid", relative_density=0.2)
        assert "achieved_density" in result

    def test_explicit_cell_size(self):
        body = _make_box()
        result = lattice_fill(body, cell_type="gyroid", relative_density=0.2, cell_size=8.0)
        assert "achieved_density" in result


class TestLatticeFillDensityOracle:
    """Spec oracle: box at rho=0.2 -> achieved density ~ 0.2 +/-0.1."""

    @pytest.mark.parametrize("cell_type", ["gyroid", "schwarz_p"])
    def test_tpms_density_oracle(self, cell_type):
        body = _make_box(30.0, 30.0, 30.0)
        target = 0.2
        result = lattice_fill(body, cell_type=cell_type, relative_density=target)
        ad = result["achieved_density"]
        assert abs(ad - target) <= 0.1, (
            "%s: achieved_density=%.4f not within 0.1 of target=%.2f" % (cell_type, ad, target)
        )

    def test_strut_octet_density_oracle(self):
        body = _make_box(30.0, 30.0, 30.0)
        target = 0.2
        result = lattice_fill(body, cell_type="octet_truss", relative_density=target)
        ad = result["achieved_density"]
        assert abs(ad - target) <= 0.1, (
            "octet_truss: achieved_density=%.4f not within 0.1 of target=%.2f" % (ad, target)
        )

    def test_strut_kelvin_density_oracle(self):
        body = _make_box(30.0, 30.0, 30.0)
        target = 0.2
        result = lattice_fill(body, cell_type="kelvin_cell", relative_density=target)
        ad = result["achieved_density"]
        assert abs(ad - target) <= 0.1, (
            "kelvin_cell: achieved_density=%.4f not within 0.1 of target=%.2f" % (ad, target)
        )

    def test_higher_density_yields_more_volume(self):
        body = _make_box(30.0, 30.0, 30.0)
        r1 = lattice_fill(body, cell_type="gyroid", relative_density=0.15)
        r2 = lattice_fill(body, cell_type="gyroid", relative_density=0.35)
        assert r2["achieved_density"] > r1["achieved_density"]
