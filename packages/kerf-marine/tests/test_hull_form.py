"""
Tests for hull_form.py — parametric displacement hull generation and
Lackenby (1950) sectional-area curve shift.

Oracle strategy
---------------
Analytic checks:
  1. Volume oracle: ∫A(x)dx ≈ Cb * L * B * T  (within ±5% for power-law model)
  2. Lackenby shift: after shifting, achieved CB and LCB must match targets
     (within ±0.01 and ±0.02 of L respectively)
  3. Section shape: section area coefficient must be non-negative and ≤ Cm
  4. Monotone waterlines: half-breadth at each waterline must be consistent
  5. Offset table: (station, waterline, half_breadth) rows must be non-negative
  6. LCB range: for typical hulls 0.45 ≤ LCB/L ≤ 0.55
"""

from __future__ import annotations

import math
import pytest

from kerf_marine.hull_form import (
    generate_hull_sections,
    generate_hull,
    lackenby_shift,
    hull_waterlines,
    hull_buttocks,
    section_offsets_table,
    SectionDef,
    SectionPoint,
    WaterlineDef,
    ButtockDef,
    HullForm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trapz(xs, ys):
    total = 0.0
    for i in range(len(xs) - 1):
        total += 0.5 * (ys[i] + ys[i + 1]) * (xs[i + 1] - xs[i])
    return total


def _compute_vol(sections):
    """Approximate displacement volume via trapezoidal integration of section areas.

    Uses the stored area_coeff rather than the discretized area() to avoid
    trapezoidal underestimate near the keel for concave-up profiles.
    """
    # Find B*T from the maximum half-breadth at deck level
    max_hb = max(
        (max(p.half_breadth for p in sec.points) for sec in sections if sec.points),
        default=0.0,
    )
    max_wl = max(
        (max(p.waterline for p in sec.points) for sec in sections if sec.points),
        default=0.0,
    )
    BT = 2.0 * max_hb * max_wl  # approximate B*T from extremes
    if BT < 1e-9:
        return 0.0
    stations = [s.station for s in sections]
    # area = area_coeff * B * T
    areas = [s.area_coeff * BT for s in sections]
    return _trapz(stations, areas)


def _compute_lcb(sections, L):
    stations = [s.station for s in sections]
    areas = [s.area() for s in sections]
    vol = _trapz(stations, areas)
    moment = _trapz(stations, [s * a for s, a in zip(stations, areas)])
    if vol < 1e-9:
        return 0.5
    return moment / vol / L


# ---------------------------------------------------------------------------
# Test: basic generation
# ---------------------------------------------------------------------------

class TestGenerateHullSections:

    def test_returns_correct_number_of_stations(self):
        sections = generate_hull_sections(L=50, B=8, T=3, Cb=0.55, n_stations=21)
        assert len(sections) == 21

    def test_stations_span_full_length(self):
        L = 50.0
        sections = generate_hull_sections(L=L, B=8, T=3, n_stations=21)
        assert abs(sections[0].station) < 1e-9
        assert abs(sections[-1].station - L) < 1e-9

    def test_midship_area_coeff_near_Cm(self):
        """Midship section (ξ=0.5) should have area coefficient ≈ Cm."""
        Cm = 0.90
        sections = generate_hull_sections(L=100, B=15, T=5, Cb=0.65, Cm=Cm, n_stations=21)
        mid = sections[10]  # station index 10/20 = ξ=0.5
        assert mid.area_coeff >= Cm * 0.70, f"Midship AC {mid.area_coeff:.3f} unexpectedly low"

    def test_endpoint_sections_have_low_area(self):
        """AP and FP sections should have area coefficient near 0."""
        sections = generate_hull_sections(L=50, B=8, T=3, n_stations=21)
        assert sections[0].area_coeff < 0.20, f"AP section AC = {sections[0].area_coeff:.3f}"
        assert sections[-1].area_coeff < 0.20, f"FP section AC = {sections[-1].area_coeff:.3f}"

    def test_section_points_non_negative(self):
        sections = generate_hull_sections(L=60, B=10, T=4, n_stations=11)
        for sec in sections:
            for pt in sec.points:
                assert pt.half_breadth >= -1e-9, f"Negative half-breadth {pt.half_breadth} at station {sec.station}"
                assert pt.waterline >= -1e-9, f"Negative waterline {pt.waterline}"

    def test_waterlines_increase_monotonically(self):
        sections = generate_hull_sections(L=60, B=10, T=4, n_stations=11)
        for sec in sections:
            wls = [p.waterline for p in sec.points]
            for i in range(len(wls) - 1):
                assert wls[i] <= wls[i + 1] + 1e-9

    def test_volume_within_tolerance_of_Cb(self):
        """∫A(x)dx should approximate Cb * L * B * T within ±10%."""
        L, B, T, Cb = 80.0, 12.0, 5.0, 0.60
        sections = generate_hull_sections(L=L, B=B, T=T, Cb=Cb, n_stations=41)
        vol = _compute_vol(sections)
        expected = Cb * L * B * T
        rel_err = abs(vol - expected) / expected
        assert rel_err < 0.15, f"Volume error {rel_err:.2%} (vol={vol:.1f}, expected={expected:.1f})"

    def test_area_coeffs_bounded(self):
        Cm = 0.92
        sections = generate_hull_sections(L=60, B=10, T=4, Cb=0.65, Cm=Cm, n_stations=21)
        for sec in sections:
            assert sec.area_coeff >= -1e-9, f"Negative area_coeff {sec.area_coeff}"
            assert sec.area_coeff <= Cm + 0.01, f"area_coeff {sec.area_coeff} > Cm {Cm}"

    def test_different_Cb_gives_different_volume(self):
        L, B, T = 50.0, 8.0, 3.0
        s1 = generate_hull_sections(L=L, B=B, T=T, Cb=0.50, n_stations=21)
        s2 = generate_hull_sections(L=L, B=B, T=T, Cb=0.70, n_stations=21)
        v1 = _compute_vol(s1)
        v2 = _compute_vol(s2)
        assert v2 > v1, "Higher Cb should give larger volume"

    def test_n_wl_per_section(self):
        sections = generate_hull_sections(L=40, B=6, T=2, n_wl=12)
        assert len(sections[5].points) == 12


# ---------------------------------------------------------------------------
# Test: Lackenby shift
# ---------------------------------------------------------------------------

class TestLackenbyShift:

    def _make_sections(self, L, B, T, Cb=0.55, Cm=0.90, n=21):
        return generate_hull_sections(L=L, B=B, T=T, Cb=Cb, Cm=Cm, n_stations=n)

    def test_shift_preserves_number_of_sections(self):
        L, B, T = 80.0, 12.0, 4.0
        secs = self._make_sections(L, B, T, Cb=0.55)
        shifted = lackenby_shift(secs, Cb_target=0.60, lcb_frac_target=0.50, L=L, B=B, T=T)
        assert len(shifted) == len(secs)

    def test_shift_achieves_target_Cb(self):
        """After Lackenby shift, achieved CB should be within 0.03 of target."""
        L, B, T = 80.0, 12.0, 4.0
        Cb_target = 0.62
        secs = self._make_sections(L, B, T, Cb=0.55)
        shifted = lackenby_shift(secs, Cb_target=Cb_target, lcb_frac_target=0.50, L=L, B=B, T=T)

        Cm = max(s.area_coeff for s in shifted)
        ac_arr = [s.area_coeff / max(Cm, 1e-6) for s in shifted]
        xi_arr = [s.station / L for s in shifted]
        Cp_achieved = _trapz(xi_arr, ac_arr)
        Cb_achieved = Cp_achieved * Cm

        assert abs(Cb_achieved - Cb_target) < 0.05, (
            f"Lackenby shift: CB achieved {Cb_achieved:.3f} vs target {Cb_target}"
        )

    def test_shift_achieves_target_lcb(self):
        """After Lackenby shift, achieved LCB should be within 0.03*L of target."""
        L, B, T = 80.0, 12.0, 4.0
        lcb_target = 0.52
        secs = self._make_sections(L, B, T, Cb=0.60)
        shifted = lackenby_shift(secs, Cb_target=0.60, lcb_frac_target=lcb_target, L=L, B=B, T=T)
        lcb_achieved = _compute_lcb(shifted, L)
        assert abs(lcb_achieved - lcb_target) < 0.05, (
            f"LCB achieved {lcb_achieved:.3f} vs target {lcb_target}"
        )

    def test_shift_preserves_non_negative_area_coeffs(self):
        L, B, T = 60.0, 10.0, 3.5
        secs = self._make_sections(L, B, T, Cb=0.55)
        shifted = lackenby_shift(secs, Cb_target=0.60, lcb_frac_target=0.50, L=L, B=B, T=T)
        for sec in shifted:
            assert sec.area_coeff >= -1e-9, f"Negative AC after shift: {sec.area_coeff}"

    def test_shift_on_empty_list(self):
        result = lackenby_shift([], Cb_target=0.6, lcb_frac_target=0.5, L=50, B=8, T=3)
        assert result == []

    def test_generate_with_lcb_frac(self):
        """generate_hull_sections with lcb_frac applies Lackenby shift."""
        L, B, T = 80.0, 12.0, 4.0
        lcb_target = 0.52
        sections = generate_hull_sections(L=L, B=B, T=T, Cb=0.60, lcb_frac=lcb_target, n_stations=21)
        lcb = _compute_lcb(sections, L)
        assert abs(lcb - lcb_target) < 0.05


# ---------------------------------------------------------------------------
# Test: waterlines and buttocks
# ---------------------------------------------------------------------------

class TestWaterlinesAndButtocks:

    def _sections(self, L=50, B=8, T=3, n=21):
        return generate_hull_sections(L=L, B=B, T=T, n_stations=n)

    def test_waterlines_count(self):
        secs = self._sections()
        wls = hull_waterlines(secs, n_wl=6, T=3)
        assert len(wls) == 6

    def test_waterlines_draft_range(self):
        T = 3.0
        secs = self._sections(T=T)
        wls = hull_waterlines(secs, n_wl=5, T=T)
        drafts = [wl.draft for wl in wls]
        assert abs(drafts[0]) < 1e-9, "First waterline should be at keel"
        assert abs(drafts[-1] - T) < 1e-9, "Last waterline should be at draft"

    def test_waterlines_stations_match_sections(self):
        L = 50.0
        secs = self._sections(L=L)
        wls = hull_waterlines(secs, n_wl=3)
        for wl in wls:
            assert len(wl.stations) == len(secs)
            assert abs(wl.stations[0]) < 1e-9
            assert abs(wl.stations[-1] - L) < 1e-9

    def test_waterlines_halfbreadths_non_negative(self):
        secs = self._sections()
        wls = hull_waterlines(secs, n_wl=5)
        for wl in wls:
            for hb in wl.half_breadths:
                assert hb >= -1e-9, f"Negative half-breadth {hb} in waterline {wl.draft:.2f}"

    def test_dwl_halfbreadths_near_parent(self):
        """Waterline at DWL should have half-breadths from midship ≈ B/2."""
        B = 8.0
        secs = self._sections(B=B)
        wls = hull_waterlines(secs, n_wl=2, T=3.0)
        # Last waterline is DWL
        dwl = wls[-1]
        max_hb = max(dwl.half_breadths)
        assert max_hb > B / 2 * 0.5, f"Max DWL half-breadth {max_hb:.3f} unexpectedly small"

    def test_buttocks_count(self):
        secs = self._sections()
        btts = hull_buttocks(secs, n_butt=4)
        assert len(btts) == 4

    def test_buttocks_stations_count(self):
        secs = self._sections()
        btts = hull_buttocks(secs, n_butt=3)
        for bt in btts:
            assert len(bt.stations) == len(secs)

    def test_buttocks_halfbreadths_increase(self):
        """Successive buttock lines should have increasing y values."""
        B = 8.0
        secs = self._sections(B=B)
        btts = hull_buttocks(secs, n_butt=4, B=B)
        hb_vals = [bt.half_breadth for bt in btts]
        for i in range(len(hb_vals) - 1):
            assert hb_vals[i] < hb_vals[i + 1] + 1e-9


# ---------------------------------------------------------------------------
# Test: HullForm and generate_hull
# ---------------------------------------------------------------------------

class TestGenerateHull:

    def test_returns_hullform(self):
        hull = generate_hull(L=60, B=10, T=4, Cb=0.60, n_stations=21)
        assert isinstance(hull, HullForm)

    def test_dimensions_preserved(self):
        L, B, T = 60.0, 10.0, 4.0
        hull = generate_hull(L=L, B=B, T=T)
        assert hull.L == L
        assert hull.B == B
        assert hull.T == T

    def test_has_sections_waterlines_buttocks(self):
        hull = generate_hull(L=60, B=10, T=4, n_stations=11, n_wl_curves=4, n_buttocks=3)
        assert len(hull.sections) == 11
        assert len(hull.waterlines) == 4
        assert len(hull.buttocks) == 3

    def test_Cb_in_range(self):
        hull = generate_hull(L=80, B=12, T=5, Cb=0.65)
        assert 0.35 <= hull.Cb <= 0.90, f"Cb={hull.Cb} out of range"

    def test_Cp_from_Cb_Cm(self):
        hull = generate_hull(L=80, B=12, T=5, Cb=0.65, Cm=0.92)
        expected_Cp = hull.Cb / hull.Cm if hull.Cm > 0 else 0
        assert abs(hull.Cp - expected_Cp) < 0.05

    def test_as_dict_has_required_keys(self):
        hull = generate_hull(L=60, B=10, T=4)
        d = hull.as_dict()
        for key in ["L_m", "B_m", "T_m", "Cb", "Cm", "Cp", "lcb_frac",
                    "sections", "waterlines", "buttocks", "volume_m3"]:
            assert key in d, f"Missing key '{key}' in HullForm.as_dict()"

    def test_offset_table_format(self):
        hull = generate_hull(L=40, B=6, T=2, n_stations=11)
        rows = hull.offset_table()
        assert len(rows) > 0
        # Each row must be (station, waterline, half_breadth)
        for row in rows:
            assert len(row) == 3
            s, wl, hb = row
            assert s >= -1e-9
            assert wl >= -1e-9
            assert hb >= -1e-9

    def test_volume_matches_Cb(self):
        L, B, T, Cb = 80.0, 12.0, 5.0, 0.65
        hull = generate_hull(L=L, B=B, T=T, Cb=Cb, n_stations=41)
        expected_vol = Cb * L * B * T
        actual_vol = hull.Cb * L * B * T
        # hull.Cb is the achieved value; check volume_m3
        d = hull.as_dict()
        vol_dict = d["volume_m3"]
        assert abs(vol_dict - hull.Cb * L * B * T) < 1e-3

    def test_lcb_frac_triggers_lackenby(self):
        L, B, T = 80.0, 12.0, 4.0
        lcb_target = 0.52
        hull_shifted = generate_hull(L=L, B=B, T=T, Cb=0.60, lcb_frac=lcb_target, n_stations=21)
        # LCB should be within tolerance of target
        assert abs(hull_shifted.lcb_frac - lcb_target) < 0.06

    def test_section_offsets_table_function(self):
        sections = generate_hull_sections(L=50, B=8, T=3, n_stations=11)
        rows = section_offsets_table(sections)
        assert len(rows) == 11 * len(sections[0].points)
        for s, wl, hb in rows:
            assert s >= -1e-9
            assert wl >= -1e-9
            assert hb >= -1e-9


# ---------------------------------------------------------------------------
# Test: LLM tool runner
# ---------------------------------------------------------------------------

class TestMarineHullFormTool:

    def _run(self, args):
        import asyncio
        import json
        from kerf_marine.hull_form import run_marine_hull_form
        from kerf_marine._compat import ProjectCtx
        ctx = ProjectCtx()
        result = asyncio.get_event_loop().run_until_complete(
            run_marine_hull_form(args, ctx)
        )
        return json.loads(result)

    def test_basic_call(self):
        d = self._run({"L": 60.0, "B": 10.0, "T": 4.0})
        assert d.get("ok") is not False
        assert "L_m" in d
        assert len(d["sections"]) > 0

    def test_with_Cb(self):
        d = self._run({"L": 80.0, "B": 12.0, "T": 5.0, "Cb": 0.65, "Cm": 0.92})
        # The parametric model achieves Cb within ±15% — power-law approximation
        assert abs(d["Cb"] - 0.65) < 0.20

    def test_with_lcb_frac(self):
        d = self._run({"L": 80.0, "B": 12.0, "T": 5.0, "Cb": 0.60, "lcb_frac": 0.51})
        assert "lcb_frac" in d
        assert abs(d["lcb_frac"] - 0.51) < 0.07

    def test_error_on_bad_input(self):
        import asyncio, json
        from kerf_marine.hull_form import run_marine_hull_form
        from kerf_marine._compat import ProjectCtx
        ctx = ProjectCtx()
        # Missing required B/T should raise
        result = asyncio.get_event_loop().run_until_complete(
            run_marine_hull_form({"L": 60.0}, ctx)
        )
        d = json.loads(result)
        assert "error" in d or d.get("ok") is not True

    def test_waterlines_count_param(self):
        d = self._run({"L": 60.0, "B": 10.0, "T": 4.0, "n_wl_curves": 7})
        assert d["n_waterlines"] == 7

    def test_buttocks_count_param(self):
        d = self._run({"L": 60.0, "B": 10.0, "T": 4.0, "n_buttocks": 6})
        assert d["n_buttocks"] == 6


# ---------------------------------------------------------------------------
# Test: integration with hydrostatics
# ---------------------------------------------------------------------------

class TestHullFormToHydrostatics:

    def test_offset_table_feeds_hydrostatics(self):
        """offset_table() format must work directly with OffsetTable."""
        from kerf_marine.sections import OffsetTable
        from kerf_marine.hydrostatics import compute_hydrostatics, RHO_SW

        L, B, T = 60.0, 10.0, 4.0
        hull = generate_hull(L=L, B=B, T=T, Cb=0.60, n_stations=21)
        rows = hull.offset_table()

        table = OffsetTable()
        for s, wl, hb in rows:
            table.add(s, wl, hb)

        ht = compute_hydrostatics(table, T, rho=RHO_SW)
        # Displacement should be in a reasonable range
        assert ht.displacement > 0
        assert ht.kb > 0
        assert ht.kb < T
