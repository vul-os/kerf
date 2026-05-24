"""Tests for the extended TPMS / truss lattice library.

Covers:
- Fischer-Koch S, IWP, F-RD TPMS (lattice.py API + frep/sdf.py API)
- BCC, FCC truss lattices (lattice.py API)

Oracle properties tested
------------------------
TPMS:
  1. Field at origin equals the expected analytic value for the formula.
  2. Field is periodic with cell_size in all three axes.
  3. dict keys, kind, cell_size, thickness stored correctly.

Truss:
  1. Vertex / node count matches topology spec.
  2. Strut count matches topology spec.
  3. No duplicate struts.
  4. All strut endpoints within the cell bounding box (with tolerance).
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.geom.lattice import (
    fischer_koch_s,
    iwp,
    f_rd,
    bcc_lattice,
    fcc_lattice,
)
from kerf_cad_core.frep.sdf import (
    sdf_fischer_koch_s,
    sdf_iwp,
    sdf_f_rd,
)
# Also verify re-export via geom __init__
from kerf_cad_core.geom import (
    fischer_koch_s as geom_fks,
    iwp as geom_iwp,
    f_rd as geom_frd,
    bcc_lattice as geom_bcc,
    fcc_lattice as geom_fcc,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_tpms_dict(d, cell_size, thickness):
    assert set(d.keys()) >= {"f", "cell_size", "thickness", "kind"}
    assert d["kind"] == "tpms"
    assert d["cell_size"] == pytest.approx(cell_size)
    assert d["thickness"] == pytest.approx(thickness)
    assert callable(d["f"])


def _check_strut_dict(d, cell_size, expected_node_count, expected_strut_count):
    assert set(d.keys()) >= {"struts", "nodes", "cell_size", "strut_radius", "kind"}
    assert d["kind"] == "strut"
    assert d["cell_size"] == pytest.approx(cell_size)
    assert len(d["nodes"]) == expected_node_count
    assert len(d["struts"]) == expected_strut_count
    # No duplicate struts
    canonical = set()
    for a, b in d["struts"]:
        canonical.add((a, b) if a <= b else (b, a))
    assert len(canonical) == expected_strut_count
    # All endpoints within bounding box
    L = cell_size
    tol = 1e-9
    for a, b in d["struts"]:
        for pt in (a, b):
            assert -tol <= pt[0] <= L + tol
            assert -tol <= pt[1] <= L + tol
            assert -tol <= pt[2] <= L + tol


# ---------------------------------------------------------------------------
# Fischer-Koch S — lattice API
# ---------------------------------------------------------------------------

class TestFischerKochS:
    L = 10.0
    T = 0.5

    def test_dict_structure(self):
        _check_tpms_dict(fischer_koch_s(self.L, self.T), self.L, self.T)

    def test_invalid_cell_size(self):
        with pytest.raises(ValueError):
            fischer_koch_s(0.0, self.T)

    def test_invalid_thickness(self):
        with pytest.raises(ValueError):
            fischer_koch_s(self.L, -1.0)

    def test_known_value_at_origin(self):
        # At (0,0,0): cos(0)*sin(0)*cos(0)*3 = 0  → f(0,0,0) = 0
        d = fischer_koch_s(self.L, self.T)
        assert d["f"](0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-12)

    @pytest.mark.parametrize("axis", ["x", "y", "z"])
    def test_periodic(self, axis):
        d = fischer_koch_s(self.L, self.T)
        f = d["f"]
        points = [(1.1, 2.3, 0.7), (3.0, -1.0, 2.5)]
        for x, y, z in points:
            if axis == "x":
                assert f(x, y, z) == pytest.approx(f(x + self.L, y, z), abs=1e-10)
            elif axis == "y":
                assert f(x, y, z) == pytest.approx(f(x, y + self.L, z), abs=1e-10)
            else:
                assert f(x, y, z) == pytest.approx(f(x, y, z + self.L), abs=1e-10)

    def test_re_exported_from_geom(self):
        d = geom_fks(self.L, self.T)
        assert d["kind"] == "tpms"


# ---------------------------------------------------------------------------
# IWP — lattice API
# ---------------------------------------------------------------------------

class TestIWP:
    L = 10.0
    T = 0.5

    def test_dict_structure(self):
        _check_tpms_dict(iwp(self.L, self.T), self.L, self.T)

    def test_invalid_cell_size(self):
        with pytest.raises(ValueError):
            iwp(-1.0, self.T)

    def test_invalid_thickness(self):
        with pytest.raises(ValueError):
            iwp(self.L, 0.0)

    def test_known_value_at_origin(self):
        # At (0,0,0): 2*(1*1 + 1*1 + 1*1) - (1+1+1) = 6 - 3 = 3
        d = iwp(self.L, self.T)
        assert d["f"](0.0, 0.0, 0.0) == pytest.approx(3.0, abs=1e-12)

    @pytest.mark.parametrize("axis", ["x", "y", "z"])
    def test_periodic(self, axis):
        d = iwp(self.L, self.T)
        f = d["f"]
        points = [(1.1, 2.3, 0.7), (3.0, -1.0, 2.5)]
        for x, y, z in points:
            if axis == "x":
                assert f(x, y, z) == pytest.approx(f(x + self.L, y, z), abs=1e-10)
            elif axis == "y":
                assert f(x, y, z) == pytest.approx(f(x, y + self.L, z), abs=1e-10)
            else:
                assert f(x, y, z) == pytest.approx(f(x, y, z + self.L), abs=1e-10)

    def test_re_exported_from_geom(self):
        d = geom_iwp(self.L, self.T)
        assert d["kind"] == "tpms"


# ---------------------------------------------------------------------------
# F-RD — lattice API
# ---------------------------------------------------------------------------

class TestFRD:
    L = 10.0
    T = 0.5

    def test_dict_structure(self):
        _check_tpms_dict(f_rd(self.L, self.T), self.L, self.T)

    def test_invalid_cell_size(self):
        with pytest.raises(ValueError):
            f_rd(0.0, self.T)

    def test_invalid_thickness(self):
        with pytest.raises(ValueError):
            f_rd(self.L, -0.1)

    def test_known_value_at_origin(self):
        # At (0,0,0): 4*cos(0)*cos(0)*cos(0) - (cos(0)*cos(0)+cos(0)*cos(0)+cos(0)*cos(0))
        # = 4*1 - 3*1 = 1
        d = f_rd(self.L, self.T)
        assert d["f"](0.0, 0.0, 0.0) == pytest.approx(1.0, abs=1e-12)

    @pytest.mark.parametrize("axis", ["x", "y", "z"])
    def test_periodic(self, axis):
        d = f_rd(self.L, self.T)
        f = d["f"]
        points = [(1.1, 2.3, 0.7), (3.0, -1.0, 2.5)]
        for x, y, z in points:
            if axis == "x":
                assert f(x, y, z) == pytest.approx(f(x + self.L, y, z), abs=1e-10)
            elif axis == "y":
                assert f(x, y, z) == pytest.approx(f(x, y + self.L, z), abs=1e-10)
            else:
                assert f(x, y, z) == pytest.approx(f(x, y, z + self.L), abs=1e-10)

    def test_re_exported_from_geom(self):
        d = geom_frd(self.L, self.T)
        assert d["kind"] == "tpms"


# ---------------------------------------------------------------------------
# Fischer-Koch S — frep/sdf API
# ---------------------------------------------------------------------------

class TestSdfFischerKochS:
    def test_returns_callable(self):
        f = sdf_fischer_koch_s(period=1.0)
        assert callable(f)

    def test_returns_float(self):
        f = sdf_fischer_koch_s(period=1.0)
        assert isinstance(f(0.1, 0.2, 0.3), float)

    def test_known_value_at_origin(self):
        # f(0,0,0) = 0 - iso
        f = sdf_fischer_koch_s(period=1.0, iso=0.0)
        assert f(0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-12)

    def test_iso_shift(self):
        # With iso=1.0, value at origin should be -1.0
        f = sdf_fischer_koch_s(period=1.0, iso=1.0)
        assert f(0.0, 0.0, 0.0) == pytest.approx(-1.0, abs=1e-12)

    def test_periodic(self):
        period = 2.0
        f = sdf_fischer_koch_s(period=period, iso=0.0)
        x, y, z = 0.3, 0.7, 0.15
        assert f(x, y, z) == pytest.approx(f(x + period, y, z), abs=1e-10)
        assert f(x, y, z) == pytest.approx(f(x, y + period, z), abs=1e-10)
        assert f(x, y, z) == pytest.approx(f(x, y, z + period), abs=1e-10)


# ---------------------------------------------------------------------------
# IWP — frep/sdf API
# ---------------------------------------------------------------------------

class TestSdfIWP:
    def test_returns_callable(self):
        f = sdf_iwp(period=1.0)
        assert callable(f)

    def test_returns_float(self):
        f = sdf_iwp(period=1.0)
        assert isinstance(f(0.1, 0.2, 0.3), float)

    def test_known_value_at_origin(self):
        # At origin (iso=0): 2*(1+1+1) - (1+1+1) = 3
        f = sdf_iwp(period=1.0, iso=0.0)
        assert f(0.0, 0.0, 0.0) == pytest.approx(3.0, abs=1e-12)

    def test_iso_shift(self):
        f = sdf_iwp(period=1.0, iso=3.0)
        assert f(0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-12)

    def test_periodic(self):
        period = 2.0
        f = sdf_iwp(period=period, iso=0.0)
        x, y, z = 0.3, 0.7, 0.15
        assert f(x, y, z) == pytest.approx(f(x + period, y, z), abs=1e-10)
        assert f(x, y, z) == pytest.approx(f(x, y + period, z), abs=1e-10)
        assert f(x, y, z) == pytest.approx(f(x, y, z + period), abs=1e-10)


# ---------------------------------------------------------------------------
# F-RD — frep/sdf API
# ---------------------------------------------------------------------------

class TestSdfFRD:
    def test_returns_callable(self):
        f = sdf_f_rd(period=1.0)
        assert callable(f)

    def test_returns_float(self):
        f = sdf_f_rd(period=1.0)
        assert isinstance(f(0.1, 0.2, 0.3), float)

    def test_known_value_at_origin(self):
        # 4*1*1*1 - (1*1 + 1*1 + 1*1) = 4 - 3 = 1
        f = sdf_f_rd(period=1.0, iso=0.0)
        assert f(0.0, 0.0, 0.0) == pytest.approx(1.0, abs=1e-12)

    def test_iso_shift(self):
        f = sdf_f_rd(period=1.0, iso=1.0)
        assert f(0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-12)

    def test_periodic(self):
        period = 2.0
        f = sdf_f_rd(period=period, iso=0.0)
        x, y, z = 0.3, 0.7, 0.15
        assert f(x, y, z) == pytest.approx(f(x + period, y, z), abs=1e-10)
        assert f(x, y, z) == pytest.approx(f(x, y + period, z), abs=1e-10)
        assert f(x, y, z) == pytest.approx(f(x, y, z + period), abs=1e-10)


# ---------------------------------------------------------------------------
# BCC lattice
# ---------------------------------------------------------------------------

class TestBCCLattice:
    L = 10.0
    R = 0.3

    def test_dict_structure(self):
        _check_strut_dict(bcc_lattice(self.L, self.R), self.L, 9, 8)

    def test_kind(self):
        assert bcc_lattice(self.L, self.R)["kind"] == "strut"

    @pytest.mark.parametrize("L", [5.0, 10.0, 20.0])
    def test_strut_count_is_8(self, L):
        d = bcc_lattice(L, self.R)
        assert len(d["struts"]) == 8

    def test_node_count_is_9(self):
        d = bcc_lattice(self.L, self.R)
        assert len(d["nodes"]) == 9

    def test_invalid_cell_size(self):
        with pytest.raises(ValueError):
            bcc_lattice(0.0, self.R)

    def test_invalid_strut_radius(self):
        with pytest.raises(ValueError):
            bcc_lattice(self.L, 0.0)

    def test_cell_size_stored(self):
        d = bcc_lattice(7.5, self.R)
        assert d["cell_size"] == pytest.approx(7.5)

    def test_strut_radius_stored(self):
        d = bcc_lattice(self.L, 0.15)
        assert d["strut_radius"] == pytest.approx(0.15)

    def test_all_struts_connect_to_centre(self):
        """Every strut in BCC must touch the body centre (L/2, L/2, L/2)."""
        L = self.L
        h = L / 2.0
        centre = (h, h, h)
        d = bcc_lattice(L, self.R)
        for a, b in d["struts"]:
            assert a == centre or b == centre, (
                f"Strut ({a}, {b}) does not touch the body centre {centre}"
            )

    def test_re_exported_from_geom(self):
        d = geom_bcc(self.L, self.R)
        assert len(d["struts"]) == 8


# ---------------------------------------------------------------------------
# FCC lattice
# ---------------------------------------------------------------------------

class TestFCCLattice:
    L = 10.0
    R = 0.3

    def test_dict_structure(self):
        # 14 nodes (8 corners + 6 face centres), 24 struts (4 per face * 6 faces)
        _check_strut_dict(fcc_lattice(self.L, self.R), self.L, 14, 24)

    def test_kind(self):
        assert fcc_lattice(self.L, self.R)["kind"] == "strut"

    @pytest.mark.parametrize("L", [5.0, 10.0, 20.0])
    def test_strut_count_is_24(self, L):
        d = fcc_lattice(L, self.R)
        assert len(d["struts"]) == 24

    def test_node_count_is_14(self):
        d = fcc_lattice(self.L, self.R)
        assert len(d["nodes"]) == 14

    def test_invalid_cell_size(self):
        with pytest.raises(ValueError):
            fcc_lattice(-1.0, self.R)

    def test_invalid_strut_radius(self):
        with pytest.raises(ValueError):
            fcc_lattice(self.L, -0.1)

    def test_cell_size_stored(self):
        d = fcc_lattice(7.5, self.R)
        assert d["cell_size"] == pytest.approx(7.5)

    def test_re_exported_from_geom(self):
        d = geom_fcc(self.L, self.R)
        assert len(d["struts"]) == 24

    def test_all_strut_lengths_equal(self):
        """All FCC struts run from a face-centre to a corner of that face.

        Length = sqrt((L/2)^2 + (L/2)^2) = L/sqrt(2) = L*sqrt(2)/2.
        """
        L = self.L
        expected = L * math.sqrt(2.0) / 2.0
        d = fcc_lattice(L, self.R)
        for (x0, y0, z0), (x1, y1, z1) in d["struts"]:
            length = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)
            assert length == pytest.approx(expected, rel=1e-9)
