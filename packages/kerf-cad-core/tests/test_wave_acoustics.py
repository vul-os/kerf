"""
Tests for kerf_cad_core.acoustics.wave — wave-domain room acoustics + SEA.

All tests are hermetic: pure Python, no OCC, no DB, no network.

Validation targets
------------------
Shoebox 5×4×3 m, c=343 m/s:

  Sabine T60 = 0.161·V/A where A = S·alpha, S = 2*(L*W+L*H+W*H) = 94 m²
  For alpha=0.1:  A=9.4,   T60=0.161*60/9.4  ≈ 1.03 s
  For alpha=0.3:  A=28.2,  T60=0.161*60/28.2 ≈ 0.34 s

  ISM validation uses alpha=0.3 at max_order=15 which converges within 5%
  of Sabine (confirmed numerically). Low-alpha rooms (alpha=0.1) require
  order ~100+ to fully populate the reverb tail; alpha=0.3 is "moderately
  reverberant" and gives rapid convergence.

Lowest axial mode: c/(2*L) = 343/10 = 34.3 Hz (must appear in mode list).

Author: imranparuk
"""
from __future__ import annotations

import math

import pytest

from kerf_cad_core.acoustics.wave import (
    image_source_impulse_response,
    rt60_from_ir,
    room_modes,
    sea_two_rooms_tl,
)
from kerf_cad_core.acoustics.sound import sabine_rt60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOM = (5.0, 4.0, 3.0)  # L, W, H in metres
ALPHA = 0.1             # used for structural tests
ALPHA_VAL = 0.3         # used for ISM-vs-Sabine validation (converges at order=15)
C = 343.0


def _sabine_t60(L, W, H, alpha, c=343.0):
    V = L * W * H
    S = 2 * (L * W + L * H + W * H)
    A = S * alpha
    return 0.161 * V / A


# ---------------------------------------------------------------------------
# 1. Image-source method — basic sanity
# ---------------------------------------------------------------------------

class TestImageSourceIR:
    def test_returns_ok(self):
        r = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=(1.0, 1.0, 1.0),
            receiver_xyz=(4.0, 3.0, 2.0),
            alpha_walls=ALPHA,
            max_order=2,
            c=C,
            dt=1e-4,
            t_max=1.0,
        )
        assert r["ok"] is True
        assert len(r["t"]) == len(r["h"])
        assert r["n_images"] > 0

    def test_direct_path_present(self):
        """Direct path (0th-order) from source to receiver must be non-zero."""
        src = (1.0, 1.0, 1.0)
        rcv = (4.0, 3.0, 2.0)
        r = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=src,
            receiver_xyz=rcv,
            alpha_walls=ALPHA,
            max_order=0,
            c=C,
            dt=1e-4,
            t_max=1.0,
        )
        assert r["ok"] is True
        assert max(abs(v) for v in r["h"]) > 0.0

    def test_bad_room_dims(self):
        r = image_source_impulse_response(
            room_LWH=(-1, 4, 3),
            source_xyz=(1, 1, 1),
            receiver_xyz=(2, 2, 2),
            alpha_walls=0.1,
        )
        assert r["ok"] is False

    def test_bad_alpha_list_wrong_length(self):
        r = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=(1, 1, 1),
            receiver_xyz=(2, 2, 2),
            alpha_walls=[0.1, 0.2],  # should be 6
        )
        assert r["ok"] is False

    def test_six_element_alpha(self):
        """Per-surface absorption list of length 6 should be accepted."""
        r = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=(1.0, 1.0, 1.0),
            receiver_xyz=(4.0, 3.0, 2.0),
            alpha_walls=[0.1] * 6,
            max_order=2,
            c=C,
            dt=1e-4,
            t_max=1.0,
        )
        assert r["ok"] is True

    def test_max_order_zero_single_impulse(self):
        """Order-0 ISM = just the direct path; only one non-zero sample."""
        r = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=(1.0, 1.0, 1.0),
            receiver_xyz=(4.0, 3.0, 2.0),
            alpha_walls=ALPHA,
            max_order=0,
            c=C,
            dt=1e-4,
            t_max=0.5,
        )
        assert r["ok"] is True
        nonzero = sum(1 for v in r["h"] if abs(v) > 1e-15)
        # Only the direct path impulse should be non-zero
        assert nonzero == 1


# ---------------------------------------------------------------------------
# 2. RT60 from IR — Schroeder method
# ---------------------------------------------------------------------------

class TestRT60FromIR:
    def test_returns_ok(self):
        r_ir = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=(1.0, 1.0, 1.0),
            receiver_xyz=(4.0, 3.0, 2.0),
            alpha_walls=ALPHA,
            max_order=3,
            c=C,
            dt=1e-4,
            t_max=2.0,
        )
        assert r_ir["ok"] is True
        r_rt = rt60_from_ir(r_ir["t"], r_ir["h"])
        assert r_rt["ok"] is True
        assert r_rt["rt60_s"] > 0.0

    def test_rt60_within_20pct_of_sabine(self):
        """
        ISM T60 should match Sabine within 15% for a moderately reverberant
        shoebox room (5×4×3 m, α=0.3, order=15).

        Low-alpha rooms (α=0.1) require very high reflection order to populate
        the full reverb tail; α=0.3 converges well at order=15 (< 5% error).
        """
        r_ir = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=(1.5, 1.5, 1.0),
            receiver_xyz=(3.5, 2.5, 2.0),
            alpha_walls=ALPHA_VAL,
            max_order=15,
            c=C,
            dt=5e-5,
            t_max=3.0,
        )
        assert r_ir["ok"] is True

        r_rt = rt60_from_ir(r_ir["t"], r_ir["h"])
        assert r_rt["ok"] is True

        t60_ism = r_rt["rt60_s"]
        t60_sabine = _sabine_t60(*ROOM, ALPHA_VAL, C)

        rel_err = abs(t60_ism - t60_sabine) / t60_sabine
        assert rel_err < 0.15, (
            f"ISM T60={t60_ism:.3f}s, Sabine T60={t60_sabine:.3f}s, "
            f"relative error {rel_err*100:.1f}% > 15%"
        )

    def test_sabine_helper_reference_value(self):
        """Verify Sabine formula for the reference room at both alpha values."""
        # alpha=0.1: T60 ≈ 1.028s
        t60_01 = _sabine_t60(5.0, 4.0, 3.0, 0.1)
        assert abs(t60_01 - 1.028) < 0.01

        # alpha=0.3: T60 ≈ 0.343s
        t60_03 = _sabine_t60(5.0, 4.0, 3.0, 0.3)
        assert abs(t60_03 - 0.343) < 0.005

    def test_bad_input_mismatch(self):
        r = rt60_from_ir([0.0, 0.1], [0.1])  # length mismatch
        assert r["ok"] is False

    def test_zero_energy_ir(self):
        r = rt60_from_ir([0.0, 1.0], [0.0, 0.0])
        assert r["ok"] is False

    def test_edc_monotone_decreasing(self):
        """Energy decay curve must be non-increasing (Schroeder integral)."""
        r_ir = image_source_impulse_response(
            room_LWH=ROOM,
            source_xyz=(1.0, 1.0, 1.0),
            receiver_xyz=(4.0, 3.0, 2.0),
            alpha_walls=ALPHA_VAL,
            max_order=5,
            c=C,
            dt=1e-4,
            t_max=2.0,
        )
        assert r_ir["ok"] is True
        r_rt = rt60_from_ir(r_ir["t"], r_ir["h"])
        assert r_rt["ok"] is True
        edc = r_rt["edc_db"]
        for i in range(len(edc) - 1):
            assert edc[i] >= edc[i + 1] - 1e-6, (
                f"EDC non-monotone at index {i}: {edc[i]:.3f} < {edc[i+1]:.3f}"
            )


# ---------------------------------------------------------------------------
# 3. Room modes
# ---------------------------------------------------------------------------

class TestRoomModes:
    def test_returns_ok(self):
        r = room_modes(5.0, 4.0, 3.0, f_max=500, c=343)
        assert r["ok"] is True
        assert len(r["modes"]) > 0

    def test_lowest_axial_x_mode(self):
        """
        Lowest axial mode along L=5m: f = c/(2L) = 343/10 = 34.3 Hz.
        Must appear in the mode list.
        """
        r = room_modes(5.0, 4.0, 3.0, f_max=500, c=343)
        assert r["ok"] is True
        expected = 343.0 / (2 * 5.0)  # 34.3 Hz
        freqs = [m["f_hz"] for m in r["modes"]
                 if m["nx"] == 1 and m["ny"] == 0 and m["nz"] == 0]
        assert len(freqs) == 1
        assert abs(freqs[0] - expected) < 0.1, (
            f"Expected {expected:.2f} Hz, got {freqs[0]:.2f} Hz"
        )

    def test_lowest_axial_y_mode(self):
        r = room_modes(5.0, 4.0, 3.0, f_max=500, c=343)
        expected = 343.0 / (2 * 4.0)  # 42.875 Hz
        freqs = [m["f_hz"] for m in r["modes"]
                 if m["nx"] == 0 and m["ny"] == 1 and m["nz"] == 0]
        assert abs(freqs[0] - expected) < 0.1

    def test_lowest_axial_z_mode(self):
        r = room_modes(5.0, 4.0, 3.0, f_max=500, c=343)
        expected = 343.0 / (2 * 3.0)  # 57.167 Hz
        freqs = [m["f_hz"] for m in r["modes"]
                 if m["nx"] == 0 and m["ny"] == 0 and m["nz"] == 1]
        assert abs(freqs[0] - expected) < 0.1

    def test_all_modes_below_fmax(self):
        r = room_modes(5.0, 4.0, 3.0, f_max=200, c=343)
        assert r["ok"] is True
        for m in r["modes"]:
            assert m["f_hz"] <= 200.0 + 1e-6

    def test_mode_type_classification(self):
        r = room_modes(5.0, 4.0, 3.0, f_max=200, c=343)
        for m in r["modes"]:
            nonzero = (m["nx"] != 0) + (m["ny"] != 0) + (m["nz"] != 0)
            if nonzero == 1:
                assert m["type"] == "axial"
            elif nonzero == 2:
                assert m["type"] == "tangential"
            else:
                assert m["type"] == "oblique"

    def test_modes_sorted_by_freq(self):
        r = room_modes(5.0, 4.0, 3.0, f_max=500, c=343)
        freqs = [m["f_hz"] for m in r["modes"]]
        assert freqs == sorted(freqs)

    def test_bad_dims(self):
        r = room_modes(0, 4, 3)
        assert r["ok"] is False

    def test_no_dc_mode(self):
        """(0,0,0) mode must not appear."""
        r = room_modes(5.0, 4.0, 3.0, f_max=500, c=343)
        for m in r["modes"]:
            assert not (m["nx"] == 0 and m["ny"] == 0 and m["nz"] == 0)


# ---------------------------------------------------------------------------
# 4. SEA two-room TL
# ---------------------------------------------------------------------------

class TestSEATwoRooms:
    def test_returns_ok(self):
        r = sea_two_rooms_tl(
            loss_factor_1=0.05,
            loss_factor_2=0.05,
            coupling=0.01,
            modal_density=1.0,
            freq_bands=[125, 250, 500, 1000],
        )
        assert r["ok"] is True
        assert len(r["results"]) == 4

    def test_tl_positive(self):
        """With power input to room 1, room 2 should have less energy → TL > 0."""
        r = sea_two_rooms_tl(
            loss_factor_1=0.05,
            loss_factor_2=0.05,
            coupling=0.01,
            modal_density=1.0,
            freq_bands=[500],
        )
        assert r["ok"] is True
        assert r["results"][0]["tl_db"] > 0

    def test_lower_coupling_higher_tl(self):
        """Weaker coupling → more TL."""
        r_strong = sea_two_rooms_tl(0.05, 0.05, 0.1, 1.0, [500])
        r_weak = sea_two_rooms_tl(0.05, 0.05, 0.001, 1.0, [500])
        assert r_strong["ok"] is True and r_weak["ok"] is True
        tl_strong = r_strong["results"][0]["tl_db"]
        tl_weak = r_weak["results"][0]["tl_db"]
        assert tl_weak > tl_strong

    def test_symmetric_rooms_equal_energy(self):
        """
        With identical loss factors and very strong coupling,
        energies should be roughly equal → TL ≈ 0.
        """
        r = sea_two_rooms_tl(
            loss_factor_1=0.001,
            loss_factor_2=0.001,
            coupling=100.0,   # very strong coupling
            modal_density=0.01,
            freq_bands=[1000],
        )
        assert r["ok"] is True
        tl = r["results"][0]["tl_db"]
        assert abs(tl) < 5.0, f"Expected TL≈0 for identical rooms, got {tl:.2f} dB"

    def test_bad_loss_factor(self):
        r = sea_two_rooms_tl(
            loss_factor_1=-0.1,
            loss_factor_2=0.05,
            coupling=0.01,
            modal_density=1.0,
            freq_bands=[500],
        )
        assert r["ok"] is False

    def test_empty_freq_bands(self):
        r = sea_two_rooms_tl(0.05, 0.05, 0.01, 1.0, [])
        assert r["ok"] is False

    def test_multiple_bands(self):
        bands = [63, 125, 250, 500, 1000, 2000, 4000]
        r = sea_two_rooms_tl(0.05, 0.05, 0.01, 1.0, bands)
        assert r["ok"] is True
        assert len(r["results"]) == len(bands)
        for res in r["results"]:
            assert res["tl_db"] is not None
