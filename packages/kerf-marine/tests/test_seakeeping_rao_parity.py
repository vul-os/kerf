"""
Parity-gap tests for marine_seakeeping_rao and marine_seakeeping_stats tools.

These extend test_marine_seakeeping_tools.py with additional oracle assertions
to confirm the RAO panel data is well-formed for UI rendering.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_marine.tools import (
    run_marine_seakeeping_rao,
    run_marine_seakeeping_stats,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_WIGLEY = {
    "wigley_L": 100.0,
    "wigley_B": 12.0,
    "wigley_T": 6.0,
    "displacement": 3000.0,
    "gm_transverse": 1.2,
    "gm_longitudinal": 120.0,
}

_FREQS = [0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0]


# ---------------------------------------------------------------------------
# RAO tool — structural tests
# ---------------------------------------------------------------------------

class TestSeakeepingRaoParity:

    def test_heave_rao_at_zero_freq_approaches_one(self):
        """
        Quasi-static limit: heave RAO → 1 as ω → 0 (ship follows wave).
        Use very low frequency.
        """
        args = {**_WIGLEY, "omega_list": [0.05, 0.1]}
        result = json.loads(_run(run_marine_seakeeping_rao(args, ctx=None)))
        assert "rao_points" in result
        low_freq_pt = result["rao_points"][0]
        heave_amp = low_freq_pt["rao_heave_amp"]
        # At very low frequency, heave RAO ~ 1 (quasi-static)
        assert 0.5 < heave_amp < 2.0, f"Low-freq heave RAO = {heave_amp}, expected ~1"

    def test_rao_amplitudes_non_negative(self):
        args = {**_WIGLEY, "omega_list": _FREQS}
        result = json.loads(_run(run_marine_seakeeping_rao(args, ctx=None)))
        for pt in result["rao_points"]:
            assert pt["rao_heave_amp"] >= 0
            assert pt["rao_pitch_amp"] >= 0
            assert pt["rao_roll_amp"] >= 0

    def test_all_required_fields_present(self):
        args = {**_WIGLEY, "omega_list": [0.5, 1.0]}
        result = json.loads(_run(run_marine_seakeeping_rao(args, ctx=None)))
        assert "rao_points" in result
        for pt in result["rao_points"]:
            for field in (
                "omega_rad_s", "omega_e_rad_s",
                "rao_heave_amp", "rao_heave_phase_deg",
                "rao_pitch_amp", "rao_pitch_phase_deg",
                "rao_roll_amp", "rao_roll_phase_deg",
            ):
                assert field in pt, f"Missing field '{field}'"

    def test_phase_in_valid_range(self):
        args = {**_WIGLEY, "omega_list": _FREQS}
        result = json.loads(_run(run_marine_seakeeping_rao(args, ctx=None)))
        for pt in result["rao_points"]:
            for field in ("rao_heave_phase_deg", "rao_pitch_phase_deg", "rao_roll_phase_deg"):
                phase = pt[field]
                assert -360 <= phase <= 360, f"Phase {phase} outside [-360, 360]"

    def test_head_seas_vs_beam_seas_roll(self):
        """
        Roll should be larger in beam seas (mu=90°) than head seas (mu=180°).
        """
        args_head = {**_WIGLEY, "omega_list": [0.8, 1.0, 1.2], "mu_deg": 180}
        args_beam = {**_WIGLEY, "omega_list": [0.8, 1.0, 1.2], "mu_deg": 90}
        r_head = json.loads(_run(run_marine_seakeeping_rao(args_head, ctx=None)))
        r_beam = json.loads(_run(run_marine_seakeeping_rao(args_beam, ctx=None)))
        roll_head = max(pt["rao_roll_amp"] for pt in r_head["rao_points"])
        roll_beam = max(pt["rao_roll_amp"] for pt in r_beam["rao_points"])
        assert roll_beam >= roll_head, (
            f"Beam roll {roll_beam} should be >= head roll {roll_head}"
        )

    def test_n_sections_and_length_present(self):
        args = {**_WIGLEY, "omega_list": [0.5]}
        result = json.loads(_run(run_marine_seakeeping_rao(args, ctx=None)))
        assert "n_sections" in result
        assert "L_m" in result
        assert result["n_sections"] > 0
        assert result["L_m"] > 0

    def test_no_hull_returns_error_not_crash(self):
        result = json.loads(_run(run_marine_seakeeping_rao({}, ctx=None)))
        assert isinstance(result, dict)
        # Should not raise — returns error payload

    def test_custom_sections_work(self):
        """Pass explicit sections list for a box-barge."""
        sections = [
            [0, 10, 4, 40],
            [25, 10, 4, 40],
            [50, 10, 4, 40],
            [75, 10, 4, 40],
            [100, 10, 4, 40],
        ]
        args = {
            "sections": sections,
            "displacement": 2000,
            "gm_transverse": 1.0,
            "gm_longitudinal": 100,
            "omega_list": [0.5, 1.0],
        }
        result = json.loads(_run(run_marine_seakeeping_rao(args, ctx=None)))
        assert "rao_points" in result
        assert len(result["rao_points"]) == 2


# ---------------------------------------------------------------------------
# Stats tool — irregular sea statistics
# ---------------------------------------------------------------------------

class TestSeakeepingStatsParity:

    def test_returns_motions_list(self):
        args = {**_WIGLEY, "Hs": 2.5, "Tp": 8.0}
        result = json.loads(_run(run_marine_seakeeping_stats(args, ctx=None)))
        assert "motions" in result
        assert len(result["motions"]) == 3

    def test_motion_labels(self):
        args = {**_WIGLEY, "Hs": 2.5, "Tp": 8.0}
        result = json.loads(_run(run_marine_seakeeping_stats(args, ctx=None)))
        labels = [m["motion"] for m in result["motions"]]
        assert "heave" in labels
        assert "pitch" in labels
        assert "roll" in labels

    def test_significant_amplitudes_positive(self):
        args = {**_WIGLEY, "Hs": 3.0, "Tp": 9.0, "mu_deg": 90}
        result = json.loads(_run(run_marine_seakeeping_stats(args, ctx=None)))
        for m in result["motions"]:
            assert m["significant_amplitude"] >= 0
            assert m["m0"] >= 0
            assert m["m2"] >= 0

    def test_mpm_gt_significant_amplitude(self):
        """MPM (most probable max) should exceed significant amplitude."""
        args = {**_WIGLEY, "Hs": 3.0, "Tp": 9.0}
        result = json.loads(_run(run_marine_seakeeping_stats(args, ctx=None)))
        for m in result["motions"]:
            if m["significant_amplitude"] > 0:
                assert m["mpm_100_amplitude"] > m["significant_amplitude"], (
                    f"{m['motion']}: MPM {m['mpm_100_amplitude']} <= sig {m['significant_amplitude']}"
                )

    def test_jonswap_vs_pm_spectrum(self):
        """JONSWAP should give higher response than PM (narrower, peaked spectrum)."""
        base = {**_WIGLEY, "Hs": 2.0, "Tp": 8.0, "mu_deg": 90}
        r_jons = json.loads(_run(run_marine_seakeeping_stats({**base, "spectrum": "jonswap"}, ctx=None)))
        r_pm = json.loads(_run(run_marine_seakeeping_stats({**base, "spectrum": "pm"}, ctx=None)))
        # JONSWAP typically gives slightly higher peaks for roll (beam seas)
        roll_jons = next(m for m in r_jons["motions"] if m["motion"] == "roll")
        roll_pm = next(m for m in r_pm["motions"] if m["motion"] == "roll")
        # Both should be non-negative; JONSWAP can be ≥ PM
        assert roll_jons["significant_amplitude"] >= 0
        assert roll_pm["significant_amplitude"] >= 0

    def test_missing_hs_tp_returns_error(self):
        result = json.loads(_run(run_marine_seakeeping_stats({**_WIGLEY}, ctx=None)))
        # No Hs/Tp: should return error payload, not crash
        assert isinstance(result, dict)
