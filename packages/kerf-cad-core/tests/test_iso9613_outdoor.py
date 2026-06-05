"""
Tests for ISO 9613-2:1996 outdoor sound propagation engine.

All assertions backed by hand-calculations per the standard.

References
----------
ISO 9613-2:1996  — Attenuation of sound during propagation outdoors
ISO 9613-1:1993  — Atmospheric absorption coefficients
Maekawa (1968)   — Noise reduction by screens

Author: kerf agent
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.acoustics.sound import (
    iso9613_outdoor_spl,
    iso9613_outdoor_octave_bands,
)
from kerf_cad_core.acoustics.tools import (
    run_acoustics_iso9613_outdoor,
    run_acoustics_iso9613_octave_bands,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


# ---------------------------------------------------------------------------
# iso9613_outdoor_spl — geometric divergence
# ---------------------------------------------------------------------------

class TestGeometricDivergence:
    """
    Validate A_div using the ISO 9613-2 §7.1 formula:
        A_div = 20·log₁₀(r) + 11 − 10·log₁₀(Q)

    For r = 100 m, Q = 2 (hemispherical):
        A_div = 20·log₁₀(100) + 11 − 10·log₁₀(2)
              = 40 + 11 − 3.01 = 47.99 dB
    """

    def test_adiv_100m_Q2(self):
        # Source and receiver at same height → r_s ≈ d_h = 100 m
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0, receiver_h=0,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=1000,
        )
        assert r["ok"]
        expected_adiv = 20 * math.log10(100) + 11 - 10 * math.log10(2)
        assert abs(r["A_div_db"] - expected_adiv) < 0.05, (
            f"A_div_db={r['A_div_db']:.3f}, expected≈{expected_adiv:.3f}"
        )

    def test_adiv_Q1_free_field(self):
        """Q=1 free field: A_div = 20·log₁₀(r) + 11."""
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0, receiver_h=0,
            horizontal_dist=50, Q=1,
            ground_type="hard", freq_hz=500,
        )
        assert r["ok"]
        expected = 20 * math.log10(50) + 11 - 10 * math.log10(1)
        assert abs(r["A_div_db"] - expected) < 0.05

    def test_adiv_slant_distance(self):
        """When source and receiver heights differ, slant distance > horizontal distance."""
        r = iso9613_outdoor_spl(
            Lw=80, source_h=0, receiver_h=10,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
        )
        assert r["ok"]
        slant = math.sqrt(100**2 + 10**2)
        assert abs(r["slant_dist_m"] - slant) < 0.01

    def test_lp_decreases_with_distance(self):
        """SPL must decrease monotonically with increasing distance."""
        lp_prev = None
        for d in [10, 20, 50, 100, 200]:
            r = iso9613_outdoor_spl(
                Lw=90, source_h=1, receiver_h=1.5,
                horizontal_dist=d, Q=2,
                ground_type="hard", freq_hz=500,
            )
            assert r["ok"]
            if lp_prev is not None:
                assert r["lp_db"] < lp_prev, (
                    f"Lp did not decrease: {r['lp_db']:.2f} >= {lp_prev:.2f} at d={d}"
                )
            lp_prev = r["lp_db"]

    def test_6db_per_doubling(self):
        """
        For hard ground (A_gr=0) and no barrier, SPL drops ~6 dB per doubling
        of distance (inverse-square law).
        A_div doubles by 6 dB per doubling of r.
        """
        r1 = iso9613_outdoor_spl(
            Lw=90, source_h=0, receiver_h=0,
            horizontal_dist=50, Q=1,
            ground_type="hard", freq_hz=250,
        )
        r2 = iso9613_outdoor_spl(
            Lw=90, source_h=0, receiver_h=0,
            horizontal_dist=100, Q=1,
            ground_type="hard", freq_hz=250,
        )
        # A_atm difference is small at 250 Hz over 50m
        delta_lp = r1["lp_db"] - r2["lp_db"]
        assert abs(delta_lp - 6.0) < 0.5, (
            f"Expected ~6 dB per doubling, got {delta_lp:.2f} dB"
        )


# ---------------------------------------------------------------------------
# Atmospheric absorption
# ---------------------------------------------------------------------------

class TestAtmosphericAbsorption:
    """
    From ISO 9613-1:1993 Table 1 (10°C, 70% RH):
        63 Hz:   0.1 dB/km
        500 Hz:  1.9 dB/km
        8000 Hz: 117 dB/km
    """

    def test_atm_500hz_100m(self):
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0, receiver_h=0,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
        )
        assert r["ok"]
        # A_atm = 1.9 dB/km × 0.1 km = 0.19 dB
        assert abs(r["A_atm_db"] - 0.19) < 0.02

    def test_atm_8khz_higher_absorption(self):
        """High-frequency atmospheric absorption should be much larger."""
        r_lf = iso9613_outdoor_spl(
            Lw=90, source_h=0, receiver_h=0,
            horizontal_dist=500, Q=2,
            ground_type="hard", freq_hz=63,
        )
        r_hf = iso9613_outdoor_spl(
            Lw=90, source_h=0, receiver_h=0,
            horizontal_dist=500, Q=2,
            ground_type="hard", freq_hz=8000,
        )
        assert r_lf["ok"] and r_hf["ok"]
        # At 500m: 63 Hz = 0.05 dB, 8 kHz = 58.5 dB
        assert r_hf["A_atm_db"] > r_lf["A_atm_db"] * 100


# ---------------------------------------------------------------------------
# Ground effect
# ---------------------------------------------------------------------------

class TestGroundEffect:
    """
    Hard ground: A_gr = 0.
    Soft ground (ISO 9613-2 Eq. 10):
        A_gr = 4.8 - (2hm/d)*(17 + 300/d)
    Clamped to [-3, +10] dB.
    """

    def test_hard_ground_zero(self):
        r = iso9613_outdoor_spl(
            Lw=90, source_h=1, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
        )
        assert r["ok"]
        assert r["A_gr_db"] == 0.0

    def test_soft_ground_positive_for_close_low_source(self):
        """Soft ground with low source/receiver should give positive A_gr (more attenuation)."""
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0.1, receiver_h=1.5,
            horizontal_dist=50, Q=2,
            ground_type="soft", freq_hz=500,
        )
        assert r["ok"]
        # hm ≈ 0.8 m, d = 50 m → A_gr = 4.8 - (1.6/50)*(17 + 300/50) = positive
        assert r["A_gr_db"] > 0.0

    def test_soft_ground_clamped_max(self):
        """A_gr must not exceed +10 dB per ISO 9613-2 §7.3.2."""
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0.01, receiver_h=0.01,
            horizontal_dist=5, Q=2,
            ground_type="soft", freq_hz=500,
        )
        assert r["ok"]
        assert r["A_gr_db"] <= 10.0

    def test_soft_ground_clamped_min(self):
        """A_gr must not go below -3 dB per ISO 9613-2 §7.3.2."""
        r = iso9613_outdoor_spl(
            Lw=90, source_h=20, receiver_h=20,
            horizontal_dist=100, Q=2,
            ground_type="soft", freq_hz=500,
        )
        assert r["ok"]
        assert r["A_gr_db"] >= -3.0


# ---------------------------------------------------------------------------
# Barrier diffraction (Maekawa)
# ---------------------------------------------------------------------------

class TestBarrierDiffraction:
    """
    Maekawa (1968) insertion loss:
        A_bar = 10·log₁₀(3 + 20·N)  for N >= 0
    where N = 2·delta/lambda, delta = d1 + d2 - d_direct.
    """

    def test_no_barrier_zero(self):
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
            barrier_h=0,
        )
        assert r["ok"]
        assert r["A_bar_db"] == 0.0

    def test_barrier_adds_attenuation(self):
        """Barrier must produce A_bar > 0 when it blocks line of sight."""
        r_no = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
        )
        r_bar = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
            barrier_h=4, barrier_dist_source=30,
        )
        assert r_no["ok"] and r_bar["ok"]
        assert r_bar["A_bar_db"] > 0.0
        assert r_bar["lp_db"] < r_no["lp_db"]

    def test_barrier_higher_more_attenuation(self):
        """Taller barrier must give more insertion loss than shorter."""
        r_low = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2, ground_type="hard", freq_hz=1000,
            barrier_h=2, barrier_dist_source=20,
        )
        r_high = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2, ground_type="hard", freq_hz=1000,
            barrier_h=6, barrier_dist_source=20,
        )
        assert r_low["ok"] and r_high["ok"]
        assert r_high["A_bar_db"] > r_low["A_bar_db"]

    def test_barrier_maekawa_formula(self):
        """
        Hand-check Maekawa formula for specific geometry:
        source_h=0.5, receiver_h=1.5, d_h=100m, barrier_h=4m at 20m from source.
        At 500 Hz (lambda = 340/500 = 0.68 m):
          d1 = sqrt(20^2 + (4-0.5)^2) = sqrt(400 + 12.25) = 20.302 m
          d2 = sqrt(80^2 + (4-1.5)^2) = sqrt(6400 + 6.25) = 80.039 m
          d_direct ≈ sqrt(100^2 + (0.5-1.5)^2) = sqrt(10001) = 100.005 m
          delta = 20.302 + 80.039 - 100.005 = 0.336 m
          N = 2*0.336/0.68 = 0.988
          A_bar = 10*log10(3 + 20*0.988) = 10*log10(22.76) = 13.57 dB
        """
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
            barrier_h=4, barrier_dist_source=20,
        )
        assert r["ok"]
        # compute expected
        d1 = math.sqrt(20**2 + (4 - 0.5)**2)
        d2 = math.sqrt(80**2 + (4 - 1.5)**2)
        d_direct = math.sqrt(100**2 + (0.5 - 1.5)**2)
        delta = d1 + d2 - d_direct
        lam = 340.0 / 500.0
        N = 2 * delta / lam
        expected_abar = 10 * math.log10(3 + 20 * N)
        assert abs(r["A_bar_db"] - expected_abar) < 0.5, (
            f"A_bar={r['A_bar_db']:.2f}, expected={expected_abar:.2f}"
        )

    def test_barrier_requires_dist(self):
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
            barrier_h=4,  # no barrier_dist_source
        )
        assert not r["ok"]
        assert "barrier_dist_source" in r["reason"].lower()

    def test_barrier_dist_out_of_range(self):
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard", freq_hz=500,
            barrier_h=4, barrier_dist_source=100,  # must be < 100
        )
        assert not r["ok"]


# ---------------------------------------------------------------------------
# Combined A_total and Lp
# ---------------------------------------------------------------------------

class TestCombined:
    def test_A_total_sum(self):
        r = iso9613_outdoor_spl(
            Lw=90, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="soft", freq_hz=500,
            barrier_h=4, barrier_dist_source=30,
        )
        assert r["ok"]
        A_sum = r["A_div_db"] + r["A_atm_db"] + r["A_gr_db"] + r["A_bar_db"]
        assert abs(r["A_total_db"] - A_sum) < 1e-9

    def test_lp_equals_lw_minus_total(self):
        r = iso9613_outdoor_spl(
            Lw=80, source_h=1, receiver_h=2,
            horizontal_dist=200, Q=1,
            ground_type="hard", freq_hz=1000,
        )
        assert r["ok"]
        assert abs(r["lp_db"] - (r["Lw_db"] - r["A_total_db"])) < 1e-9

    def test_bad_inputs(self):
        # negative dist
        assert not iso9613_outdoor_spl(Lw=90, source_h=0, receiver_h=0,
                                        horizontal_dist=-1, Q=2, ground_type="hard")["ok"]
        # bad ground type
        assert not iso9613_outdoor_spl(Lw=90, source_h=0, receiver_h=0,
                                        horizontal_dist=100, Q=2, ground_type="mud")["ok"]
        # Q<=0
        assert not iso9613_outdoor_spl(Lw=90, source_h=0, receiver_h=0,
                                        horizontal_dist=100, Q=0, ground_type="hard")["ok"]


# ---------------------------------------------------------------------------
# iso9613_outdoor_octave_bands
# ---------------------------------------------------------------------------

class TestOctaveBands:
    def test_basic_returns_per_band_and_total(self):
        Lw_bands = {63: 85, 125: 88, 250: 90, 500: 90, 1000: 87, 2000: 84, 4000: 79, 8000: 73}
        r = iso9613_outdoor_octave_bands(
            Lw_bands=Lw_bands,
            source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard",
        )
        assert r["ok"]
        assert len(r["per_band"]) == 8
        assert "Lp_total_db" in r
        assert "LpA_total_db" in r

    def test_total_dominated_by_peak_band(self):
        """When one band is much louder, total Lp ≈ that band's Lp."""
        # 500 Hz much louder than all others
        Lw_bands = {63: 50, 125: 50, 250: 50, 500: 90, 1000: 50, 2000: 50}
        r = iso9613_outdoor_octave_bands(
            Lw_bands=Lw_bands,
            source_h=1, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard",
        )
        assert r["ok"]
        lp_500 = next(b["lp_db"] for b in r["per_band"] if b["freq_hz"] == 500)
        # total should be within 1 dB of the dominant band
        assert abs(r["Lp_total_db"] - lp_500) < 1.0

    def test_a_weighted_lower_for_low_freq_dominated(self):
        """Low-frequency dominated spectra: LpA < Lp_total (A weighting penalises LF)."""
        # Heavy low-frequency content
        Lw_bands = {63: 100, 125: 95, 250: 90, 500: 75, 1000: 60}
        r = iso9613_outdoor_octave_bands(
            Lw_bands=Lw_bands,
            source_h=1, receiver_h=1.5,
            horizontal_dist=50, Q=2,
            ground_type="hard",
        )
        assert r["ok"]
        assert r["LpA_total_db"] < r["Lp_total_db"]

    def test_empty_bands_error(self):
        r = iso9613_outdoor_octave_bands(
            Lw_bands={},
            source_h=1, receiver_h=1.5,
            horizontal_dist=100, Q=2,
            ground_type="hard",
        )
        assert not r["ok"]

    def test_barrier_affects_all_bands(self):
        """Barrier must reduce SPL in every band."""
        Lw_bands = {250: 90, 500: 90, 1000: 90, 2000: 90}
        r_no = iso9613_outdoor_octave_bands(
            Lw_bands=Lw_bands, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2, ground_type="hard",
        )
        r_bar = iso9613_outdoor_octave_bands(
            Lw_bands=Lw_bands, source_h=0.5, receiver_h=1.5,
            horizontal_dist=100, Q=2, ground_type="hard",
            barrier_h=4, barrier_dist_source=30,
        )
        assert r_no["ok"] and r_bar["ok"]
        assert r_bar["Lp_total_db"] < r_no["Lp_total_db"]
        # Check each band
        for b_no, b_bar in zip(r_no["per_band"], r_bar["per_band"]):
            assert b_bar["lp_db"] < b_no["lp_db"], (
                f"Band {b_bar['freq_hz']} Hz: barrier did not reduce Lp"
            )


# ---------------------------------------------------------------------------
# LLM tool wrappers
# ---------------------------------------------------------------------------

class TestLLMToolOutdoor:
    def test_tool_ok(self):
        raw = _run(run_acoustics_iso9613_outdoor(
            _ctx(),
            _args(Lw=90, source_h=0.5, receiver_h=1.5,
                  horizontal_dist=100, Q=2, ground_type="hard", freq_hz=500),
        ))
        d = _ok(raw)
        assert abs(d["lp_db"] - 41.8) < 1.0

    def test_tool_missing_field(self):
        raw = _run(run_acoustics_iso9613_outdoor(
            _ctx(),
            _args(source_h=0.5, receiver_h=1.5, horizontal_dist=100),
        ))
        d = json.loads(raw)
        assert d.get("ok") is False or "error" in d

    def test_tool_bad_json(self):
        raw = _run(run_acoustics_iso9613_outdoor(_ctx(), b"{bad json}"))
        d = json.loads(raw)
        is_err = d.get("ok") is False or "error" in d
        assert is_err


class TestLLMToolOctaveBands:
    def test_tool_ok(self):
        Lw_bands = {63: 85, 125: 88, 250: 90, 500: 90, 1000: 87, 2000: 84, 4000: 79, 8000: 73}
        raw = _run(run_acoustics_iso9613_octave_bands(
            _ctx(),
            _args(Lw_bands=Lw_bands, source_h=0.5, receiver_h=1.5,
                  horizontal_dist=100, Q=2, ground_type="soft"),
        ))
        d = _ok(raw)
        assert "Lp_total_db" in d
        assert "LpA_total_db" in d
        assert len(d["per_band"]) == 8

    def test_tool_with_barrier(self):
        Lw_bands = {250: 90, 500: 90, 1000: 90}
        raw = _run(run_acoustics_iso9613_octave_bands(
            _ctx(),
            _args(Lw_bands=Lw_bands, source_h=0.5, receiver_h=1.5,
                  horizontal_dist=100, Q=2, ground_type="hard",
                  barrier_h=4, barrier_dist_source=30),
        ))
        d = _ok(raw)
        for b in d["per_band"]:
            assert b["A_bar_db"] > 0
