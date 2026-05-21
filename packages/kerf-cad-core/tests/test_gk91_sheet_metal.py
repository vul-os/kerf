"""GK-91 hermetic oracle tests: sheet metal bend / unfold (K-factor).

Pure-Python; no OCCT, no database, no ProjectCtx.

Oracle:
    bend a sheet 90° at r=1, t=2, K=0.4
    → BA = (π/2)·(1 + 0.4·2) = (π/2)·1.8
    → unfold flat length L = flange1 + BA + flange2
                           = 2·flange + π·(r + K·t)/2   (for 90°, two equal flanges)
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.sheet_metal import (
    K_FACTOR_TABLE,
    bend_allowance,
    bend_sheet,
    unfold_sheet,
)
from kerf_cad_core.geom.brep import make_box, Body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sheet(width: float, depth: float, thickness: float) -> Body:
    """Return a thin box (sheet) in XY plane: x ∈ [0,depth], y ∈ [0,width], z ∈ [0,t]."""
    return make_box(origin=(0.0, 0.0, 0.0), size=(depth, width, thickness))


# ---------------------------------------------------------------------------
# 1. bend_allowance formula
# ---------------------------------------------------------------------------

class TestBendAllowance:

    def test_90deg_formula(self):
        """BA = (π/2)·(r + K·t)."""
        r, t, k = 1.0, 2.0, 0.4
        expected = (math.pi / 2) * (r + k * t)
        assert abs(bend_allowance(math.pi / 2, r, t, k) - expected) < 1e-12

    def test_180deg_is_double_90(self):
        r, t, k = 2.0, 1.5, 0.44
        ba90  = bend_allowance(math.pi / 2, r, t, k)
        ba180 = bend_allowance(math.pi,     r, t, k)
        assert abs(ba180 - 2 * ba90) < 1e-12

    def test_k_factor_effect(self):
        """Higher K → larger BA."""
        ba_lo = bend_allowance(math.pi / 2, 1.0, 2.0, 0.3)
        ba_hi = bend_allowance(math.pi / 2, 1.0, 2.0, 0.5)
        assert ba_hi > ba_lo

    def test_radius_effect(self):
        """Larger radius → larger BA."""
        ba_small = bend_allowance(math.pi / 2, 1.0, 2.0, 0.4)
        ba_large = bend_allowance(math.pi / 2, 5.0, 2.0, 0.4)
        assert ba_large > ba_small

    def test_angle_zero_raises(self):
        with pytest.raises(ValueError, match="angle_rad"):
            bend_allowance(0.0, 1.0, 1.0, 0.4)

    def test_angle_negative_raises(self):
        with pytest.raises(ValueError, match="angle_rad"):
            bend_allowance(-0.1, 1.0, 1.0, 0.4)

    def test_angle_gt_pi_raises(self):
        with pytest.raises(ValueError, match="angle_rad"):
            bend_allowance(math.pi + 0.1, 1.0, 1.0, 0.4)

    def test_radius_zero_raises(self):
        with pytest.raises(ValueError, match="radius"):
            bend_allowance(math.pi / 2, 0.0, 1.0, 0.4)

    def test_thickness_zero_raises(self):
        with pytest.raises(ValueError, match="thickness"):
            bend_allowance(math.pi / 2, 1.0, 0.0, 0.4)

    def test_k_zero_raises(self):
        with pytest.raises(ValueError, match="k_factor"):
            bend_allowance(math.pi / 2, 1.0, 1.0, 0.0)

    def test_k_one_raises(self):
        with pytest.raises(ValueError, match="k_factor"):
            bend_allowance(math.pi / 2, 1.0, 1.0, 1.0)

    def test_small_angle_positive(self):
        ba = bend_allowance(math.radians(1.0), 1.0, 1.0, 0.4)
        assert ba > 0

    def test_returns_float(self):
        result = bend_allowance(math.pi / 4, 2.0, 1.5, 0.44)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# 2. K_FACTOR_TABLE
# ---------------------------------------------------------------------------

class TestKFactorTable:

    def test_steel_present(self):
        assert "steel" in K_FACTOR_TABLE

    def test_aluminum_present(self):
        assert "aluminum" in K_FACTOR_TABLE

    def test_copper_present(self):
        assert "copper" in K_FACTOR_TABLE

    def test_steel_value(self):
        assert 0.38 <= K_FACTOR_TABLE["steel"] <= 0.50

    def test_aluminum_value(self):
        assert 0.35 <= K_FACTOR_TABLE["aluminum"] <= 0.50

    def test_copper_value(self):
        assert 0.35 <= K_FACTOR_TABLE["copper"] <= 0.50

    def test_at_least_3_materials(self):
        assert len(K_FACTOR_TABLE) >= 3


# ---------------------------------------------------------------------------
# 3. bend_sheet — returns a Body with __sheet_metal__ metadata
# ---------------------------------------------------------------------------

class TestBendSheet:

    # sheet: width=5, depth=10, t=2; bend at x=4; 90° at r=1, K=0.4
    _W = 5.0
    _D = 10.0
    _T = 2.0
    _BL = 4.0   # bend_line
    _R = 1.0
    _K = 0.4
    _ANGLE = math.pi / 2

    def _sheet(self):
        return _make_sheet(self._W, self._D, self._T)

    def _bend(self):
        return bend_sheet(
            self._sheet(), self._BL, self._ANGLE, self._R, k_factor=self._K
        )

    def test_returns_body(self):
        assert isinstance(self._bend(), Body)

    def test_has_metadata(self):
        b = self._bend()
        assert hasattr(b, "__sheet_metal__")

    def test_metadata_type_bent(self):
        b = self._bend()
        assert b.__sheet_metal__["type"] == "bent"

    def test_metadata_thickness(self):
        b = self._bend()
        assert abs(b.__sheet_metal__["thickness"] - self._T) < 1e-9

    def test_metadata_inner_radius(self):
        b = self._bend()
        assert abs(b.__sheet_metal__["inner_radius"] - self._R) < 1e-9

    def test_metadata_angle(self):
        b = self._bend()
        assert abs(b.__sheet_metal__["angle_rad"] - self._ANGLE) < 1e-9

    def test_metadata_k_factor(self):
        b = self._bend()
        assert abs(b.__sheet_metal__["k_factor"] - self._K) < 1e-9

    def test_metadata_flange1(self):
        b = self._bend()
        # flange1 = bend_line - x_min = 4 - 0 = 4
        assert abs(b.__sheet_metal__["flange1_length"] - 4.0) < 1e-9

    def test_metadata_flange2(self):
        b = self._bend()
        # flange2 = x_max - bend_line = 10 - 4 = 6
        assert abs(b.__sheet_metal__["flange2_length"] - 6.0) < 1e-9

    def test_metadata_bend_allowance(self):
        b = self._bend()
        expected_ba = bend_allowance(self._ANGLE, self._R, self._T, self._K)
        assert abs(b.__sheet_metal__["bend_allowance"] - expected_ba) < 1e-12

    def test_metadata_width(self):
        b = self._bend()
        assert abs(b.__sheet_metal__["width"] - self._W) < 1e-9

    def test_invalid_bend_line_outside_raises(self):
        sheet = self._sheet()
        with pytest.raises(ValueError, match="bend_line"):
            bend_sheet(sheet, 11.0, self._ANGLE, self._R, k_factor=self._K)

    def test_invalid_bend_line_at_zero_raises(self):
        sheet = self._sheet()
        with pytest.raises(ValueError, match="bend_line"):
            bend_sheet(sheet, 0.0, self._ANGLE, self._R, k_factor=self._K)

    def test_angle_zero_raises(self):
        sheet = self._sheet()
        with pytest.raises(ValueError):
            bend_sheet(sheet, self._BL, 0.0, self._R)

    def test_radius_zero_raises(self):
        sheet = self._sheet()
        with pytest.raises(ValueError):
            bend_sheet(sheet, self._BL, self._ANGLE, 0.0)


# ---------------------------------------------------------------------------
# 4. unfold_sheet — GK-91 oracle
# ---------------------------------------------------------------------------

class TestUnfoldSheet:
    """
    Oracle: 90° bend at r=1, t=2, K=0.4
    BA = (π/2)·(1 + 0.4·2) = (π/2)·1.8
    flat length = flange1 + BA + flange2
                = 4 + (π/2)·1.8 + 6
    """
    _W = 5.0
    _D = 10.0
    _T = 2.0
    _BL = 4.0
    _R = 1.0
    _K = 0.4
    _ANGLE = math.pi / 2

    def _bent(self):
        sheet = _make_sheet(self._W, self._D, self._T)
        return bend_sheet(
            sheet, self._BL, self._ANGLE, self._R, k_factor=self._K
        )

    def _flat(self):
        return unfold_sheet(self._bent(), k_factor=self._K)

    def test_returns_body(self):
        assert isinstance(self._flat(), Body)

    def test_has_metadata(self):
        f = self._flat()
        assert hasattr(f, "__sheet_metal__")

    def test_metadata_type_flat(self):
        assert self._flat().__sheet_metal__["type"] == "flat"

    def test_flat_length_key_present(self):
        assert "flat_length" in self._flat().__sheet_metal__

    def test_oracle_flat_length(self):
        """GK-91 spec oracle: L = flange1 + BA + flange2."""
        ba = bend_allowance(self._ANGLE, self._R, self._T, self._K)
        expected_L = 4.0 + ba + 6.0
        flat = self._flat()
        assert abs(flat.__sheet_metal__["flat_length"] - expected_L) < 1e-9

    def test_oracle_symmetric_flanges(self):
        """For symmetric flanges: L = 2·flange + π·(r+K·t)/2."""
        # Use equal flanges (bend_line = half of depth = 5)
        sheet = _make_sheet(self._W, 10.0, self._T)
        bent = bend_sheet(sheet, 5.0, self._ANGLE, self._R, k_factor=self._K)
        flat = unfold_sheet(bent, k_factor=self._K)
        ba = bend_allowance(self._ANGLE, self._R, self._T, self._K)
        expected_L = 2 * 5.0 + ba   # 2·flange + BA
        # Also matches: 2·flange + π·(r+K·t)/2
        expected_L2 = 2 * 5.0 + math.pi * (self._R + self._K * self._T) / 2
        assert abs(flat.__sheet_metal__["flat_length"] - expected_L) < 1e-9
        assert abs(expected_L - expected_L2) < 1e-12  # both are equal

    def test_flat_length_positive(self):
        assert self._flat().__sheet_metal__["flat_length"] > 0

    def test_flat_has_faces(self):
        flat = self._flat()
        assert len(flat.all_faces()) > 0

    def test_roundtrip_bend_allowance(self):
        """bend_allowance in unfold result must equal the formula directly."""
        flat = self._flat()
        expected_ba = bend_allowance(self._ANGLE, self._R, self._T, self._K)
        assert abs(flat.__sheet_metal__["bend_allowance"] - expected_ba) < 1e-12

    def test_180deg_flat_length(self):
        sheet = _make_sheet(5.0, 12.0, self._T)
        bent = bend_sheet(sheet, 6.0, math.pi, self._R, k_factor=self._K)
        flat = unfold_sheet(bent, k_factor=self._K)
        ba = bend_allowance(math.pi, self._R, self._T, self._K)
        expected = 6.0 + ba + 6.0
        assert abs(flat.__sheet_metal__["flat_length"] - expected) < 1e-9

    def test_no_metadata_raises(self):
        """unfold_sheet on a plain Body (no metadata) should raise."""
        plain_body = make_box(size=(5.0, 5.0, 1.0))
        with pytest.raises(ValueError, match="__sheet_metal__"):
            unfold_sheet(plain_body)

    def test_geom_init_exports(self):
        """All 4 symbols are importable from kerf_cad_core.geom."""
        import kerf_cad_core.geom as geom
        assert hasattr(geom, "K_FACTOR_TABLE")
        assert hasattr(geom, "bend_allowance")
        assert hasattr(geom, "bend_sheet")
        assert hasattr(geom, "unfold_sheet")
