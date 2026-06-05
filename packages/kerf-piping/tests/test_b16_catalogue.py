"""
Tests for kerf_piping.b16_catalogue — ASME B16.9/B16.5 fitting catalogue.

Validation oracles
------------------
1. lr_elbow_dims(100) → A = 152 mm  (ASME B16.9-2018 Table 1, NPS 4")
2. reducer_dims(200, 150) → H = 203 mm  (B16.9 Table 1, larger end DN200)
3. flange_rating(150, 100) → 285 psi at 100°F  (B16.5-2017 Table 2-1.1, Class 150 Group 1.1)
4. flange_rating(300, 100, 400) → derated below ambient (400°F derating)
5. select_fittings BOM has correct structure and counts.
6. piping_b16_fittings LLM tool — async round-trip.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_piping.b16_catalogue import (
    lr_elbow_dims, sr_elbow_dims, elbow_45_dims,
    reducer_dims, cap_dims, flange_rating, fitting_weight_kg,
    select_fittings,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeCtx:
    pass


# ===========================================================================
# Elbow dimensions
# ===========================================================================

class TestLrElbowDims:
    def test_dn100_center_to_face_152mm(self):
        """ASME B16.9-2018 Table 1: DN100 (NPS 4") LR elbow A = 152 mm."""
        dims = lr_elbow_dims(100)
        assert dims.center_to_face_mm == pytest.approx(152.0, abs=1.0)

    def test_dn150_center_to_face_229mm(self):
        """ASME B16.9-2018 Table 1: DN150 (NPS 6") LR elbow A = 229 mm."""
        dims = lr_elbow_dims(150)
        assert dims.center_to_face_mm == pytest.approx(229.0, abs=1.0)

    def test_dn200_center_to_face_305mm(self):
        """ASME B16.9-2018 Table 1: DN200 (NPS 8") LR elbow A = 305 mm."""
        dims = lr_elbow_dims(200)
        assert dims.center_to_face_mm == pytest.approx(305.0, abs=1.0)

    def test_angle_is_90(self):
        dims = lr_elbow_dims(50)
        assert dims.angle_deg == 90.0

    def test_radius_type_lr(self):
        dims = lr_elbow_dims(50)
        assert dims.radius_type == "LR"

    def test_unknown_dn_raises(self):
        with pytest.raises(KeyError):
            lr_elbow_dims(999)

    def test_ascending_dims_with_dn(self):
        """Larger DN should have larger A dimension."""
        a100 = lr_elbow_dims(100).center_to_face_mm
        a150 = lr_elbow_dims(150).center_to_face_mm
        a200 = lr_elbow_dims(200).center_to_face_mm
        assert a100 < a150 < a200


class TestElbow45Dims:
    def test_dn100_45_elbow_crane(self):
        """ASME B16.9-2018 Table 1: DN100 45° elbow A = 102 mm."""
        dims = elbow_45_dims(100)
        assert dims.center_to_face_mm == pytest.approx(102.0, abs=1.0)

    def test_angle_is_45(self):
        dims = elbow_45_dims(50)
        assert dims.angle_deg == 45.0


class TestSrElbowDims:
    def test_dn100_sr_center_to_face_102mm(self):
        """DN100 SR elbow: A = 102 mm (R = 1.0D = OD ≈ 114.3 mm, but dimension is A not R)."""
        dims = sr_elbow_dims(100)
        # B16.9 SR: A_SR = D (nominal diameter in mm) for each size
        assert dims.center_to_face_mm == pytest.approx(102.0, abs=2.0)

    def test_radius_type_sr(self):
        dims = sr_elbow_dims(50)
        assert dims.radius_type == "SR"


# ===========================================================================
# Reducer dimensions
# ===========================================================================

class TestReducerDims:
    def test_dn200_150_length_203mm(self):
        """ASME B16.9-2018 Table 1: DN200×150 reducer H = 203 mm."""
        dims = reducer_dims(200, 150)
        assert dims.overall_length_mm == pytest.approx(203.0, abs=2.0)

    def test_dn150_100_length_152mm(self):
        """ASME B16.9-2018 Table 1: DN150×100 reducer H = 152 mm."""
        dims = reducer_dims(150, 100)
        assert dims.overall_length_mm == pytest.approx(152.0, abs=2.0)

    def test_dn_small_must_be_smaller(self):
        with pytest.raises(ValueError, match="dn_small"):
            reducer_dims(100, 150)

    def test_dn_same_raises(self):
        with pytest.raises(ValueError):
            reducer_dims(100, 100)

    def test_concentric_flag(self):
        dims = reducer_dims(200, 150)
        assert dims.concentric is True


# ===========================================================================
# Cap dimensions
# ===========================================================================

class TestCapDims:
    def test_dn100_cap_102mm(self):
        """ASME B16.9-2018 Table 1: DN100 cap E = 102 mm."""
        e = cap_dims(100)
        assert e == pytest.approx(102.0, abs=2.0)

    def test_dn50_cap_67mm(self):
        e = cap_dims(50)
        assert e == pytest.approx(67.0, abs=2.0)

    def test_unknown_dn_raises(self):
        with pytest.raises(KeyError):
            cap_dims(999)


# ===========================================================================
# Flange rating — ASME B16.5
# ===========================================================================

class TestFlangeRating:
    def test_class150_group11_ambient_285psi(self):
        """ASME B16.5-2017 Table 2-1.1: Class 150, Group 1.1, 100°F = 285 psi."""
        fd = flange_rating(150, 100, temp_F=100.0)
        assert fd.rating_psi == pytest.approx(285.0, rel=0.01)

    def test_class300_group11_ambient_740psi(self):
        """ASME B16.5-2017 Table 2-1.1: Class 300, Group 1.1, 100°F = 740 psi."""
        fd = flange_rating(300, 100, temp_F=100.0)
        assert fd.rating_psi == pytest.approx(740.0, rel=0.01)

    def test_class600_ambient_1480psi(self):
        fd = flange_rating(600, 100)
        assert fd.rating_psi == pytest.approx(1480.0, rel=0.01)

    def test_class2500_ambient_6170psi(self):
        fd = flange_rating(2500, 100)
        assert fd.rating_psi == pytest.approx(6170.0, rel=0.01)

    def test_derated_at_elevated_temp(self):
        """At 700°F the rating must be lower than ambient."""
        fd_ambient = flange_rating(150, 100, temp_F=100.0)
        fd_hot     = flange_rating(150, 100, temp_F=700.0)
        assert fd_hot.rating_psi < fd_ambient.rating_psi

    def test_rating_in_bar_consistent(self):
        """rating_bar ≈ rating_psi × 0.0689476."""
        fd = flange_rating(300, 100, temp_F=100.0)
        assert fd.rating_bar == pytest.approx(fd.rating_psi * 0.0689476, rel=0.01)

    def test_invalid_class_raises(self):
        with pytest.raises(KeyError):
            flange_rating(200, 100)

    def test_temp_above_800f_raises(self):
        with pytest.raises(ValueError, match="exceed"):
            flange_rating(150, 100, temp_F=900.0)

    def test_unsupported_group_raises(self):
        """Material group != 1.1 raises NotImplementedError."""
        with pytest.raises((NotImplementedError, ValueError)):
            flange_rating(150, 100, material_group="2.1")

    def test_derating_note_nonempty(self):
        fd = flange_rating(150, 100)
        assert len(fd.derating_note) > 20


# ===========================================================================
# Fitting weight
# ===========================================================================

class TestFittingWeightKg:
    def test_90lr_dn100_approx_1_7kg(self):
        w = fitting_weight_kg("90lr_elbow", 100)
        assert 1.0 < w < 2.5

    def test_tee_dn150_approx_8kg(self):
        w = fitting_weight_kg("tee_equal", 150)
        assert 5.0 < w < 12.0

    def test_unknown_type_returns_zero(self):
        w = fitting_weight_kg("unknown_fitting_xyz", 100)
        assert w == 0.0

    def test_weight_increases_with_dn(self):
        w50  = fitting_weight_kg("90lr_elbow", 50)
        w100 = fitting_weight_kg("90lr_elbow", 100)
        w200 = fitting_weight_kg("90lr_elbow", 200)
        assert w50 < w100 < w200


# ===========================================================================
# select_fittings BOM
# ===========================================================================

class TestSelectFittings:
    def test_bom_structure(self):
        r = select_fittings(dn=100, elbows_90lr=2, tees_equal=1)
        assert "bom" in r
        assert "total_weight_kg" in r
        assert "disclaimer" in r

    def test_bom_count_matches_input(self):
        r = select_fittings(dn=100, elbows_90lr=2, elbows_45=1, tees_equal=1)
        types = [item["fitting_type"] for item in r["bom"] if "error" not in item]
        assert "90_LR_elbow" in types
        assert "45_elbow" in types
        assert "tee_equal" in types

    def test_total_weight_positive(self):
        r = select_fittings(dn=100, elbows_90lr=4, tees_equal=2)
        assert r["total_weight_kg"] > 0.0

    def test_flange_rating_in_result(self):
        r = select_fittings(dn=100, flanges=2, flange_class=150)
        assert r["flange_rating"] is not None
        assert r["flange_rating"]["rating_psi"] == pytest.approx(285.0, rel=0.01)

    def test_no_fittings_empty_bom(self):
        r = select_fittings(dn=100)
        assert r["bom"] == []
        assert r["total_weight_kg"] == 0.0

    def test_reducer_pair_in_bom(self):
        r = select_fittings(dn=200, reducers=[(200, 150)])
        types = [item["fitting_type"] for item in r["bom"] if "error" not in item]
        assert "reducer" in types

    def test_disclaimer_nonempty(self):
        r = select_fittings(dn=100, elbows_90lr=1)
        assert len(r["disclaimer"]) > 20


# ===========================================================================
# piping_b16_fittings LLM tool (async)
# ===========================================================================

class TestPipingB16FittingsTool:
    def _call(self, **kwargs):
        from kerf_piping.tools import run_piping_b16_fittings
        args = {"dn": 100, **kwargs}
        return json.loads(_run(run_piping_b16_fittings(args, FakeCtx())))

    def test_basic_call_ok(self):
        r = self._call(elbows_90lr=2, tees_equal=1)
        assert r.get("ok") is True

    def test_bom_present(self):
        r = self._call(elbows_90lr=2)
        assert "bom" in r
        assert len(r["bom"]) >= 1

    def test_flange_rating_returned(self):
        r = self._call(flanges=2, flange_class=150)
        assert r.get("flange_rating") is not None
        assert r["flange_rating"]["rating_psi"] == pytest.approx(285.0, rel=0.01)

    def test_class300_rating_higher_than_150(self):
        r150 = self._call(flanges=2, flange_class=150)
        r300 = self._call(flanges=2, flange_class=300)
        assert r300["flange_rating"]["rating_psi"] > r150["flange_rating"]["rating_psi"]

    def test_total_weight_positive(self):
        r = self._call(elbows_90lr=4, tees_equal=2)
        assert r["total_weight_kg"] > 0.0

    def test_disclaimer_present(self):
        r = self._call(elbows_90lr=1)
        assert "disclaimer" in r

    def test_dn_in_response(self):
        r = self._call(dn=150, elbows_90lr=1)
        assert r["dn"] == 150
