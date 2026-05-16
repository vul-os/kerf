"""
Tests for kerf_cad_core.procsim.am_residual

Coverage (>=25 hermetic tests):
  1-3   material_props — known values, unknown material, case-insensitivity
  4-6   stress_relief_soak — Arrhenius reduces stress, higher temp → more
          relaxation, zero-duration preserves stress
  7     more layers → monotonically increasing accumulated mean stress
  8     accumulated stress saturates (converges) at many layers
  9     warpage ∝ Δstrain × L² / t (Stoney-like, within 50% band)
  10    tall thin part curls more than squat wide part
  11    recoater-collision flag when curl > layer_thickness
  12    no recoater collision on thick-layer / short part
  13    support load ∝ overhang area
  14    zero overhang → zero support load
  15    orientation scan returns all angles
  16    orientation scan picks minimum tip-deflection angle
  17    orientation scan: 90° (built on side) changes curvature vs 0°
  18    DED gives less residual than LPBF (lower inherent strain)
  19    higher preheat → lower residual stress
  20    longer part → more tip deflection (same n_layers, t, material)
  21    bad material → ok=False, not raise
  22    n_layers=0 → ok=False
  23    layer_thickness ≤ 0 → ok=False
  24    stress_relief bad t_soak → ok=False
  25    orient_scan empty orientations → ok=False
  26    bimetallic-strip analogy: kappa ∝ 1/t² (Stoney scaling)
  27    recoater_collision_layer is the FIRST layer that exceeds threshold
  28    stress_relief fraction_remaining is in (0,1) for valid inputs
"""
from __future__ import annotations

import math
import sys
import os

# Ensure package is importable without install
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..", "src",
    ),
)

from kerf_cad_core.procsim.am_residual import (
    am_orient_scan,
    am_residual_1d,
    material_props,
    stress_relief_soak,
)


# ---------------------------------------------------------------------------
# material_props
# ---------------------------------------------------------------------------

def test_material_props_316l_ok():
    r = material_props("316l")
    assert r["ok"] is True
    assert r["E"] > 0
    assert r["nu"] > 0
    assert r["alpha"] > 0
    assert r["T_melt"] > 0
    assert r["sy"] > 0


def test_material_props_ti64_ok():
    r = material_props("ti64")
    assert r["ok"] is True
    assert r["E"] > 0


def test_material_props_unknown():
    r = material_props("unobtainium")
    assert r["ok"] is False
    assert "reason" in r


def test_material_props_case_insensitive():
    r = material_props("316L")
    assert r["ok"] is True
    r2 = material_props("IN625")
    assert r2["ok"] is True


# ---------------------------------------------------------------------------
# stress_relief_soak
# ---------------------------------------------------------------------------

def test_stress_relief_reduces_stress():
    sigma_0 = 400e6  # 400 MPa initial
    # 600°C soak for 2 hours for SS316L
    r = stress_relief_soak(sigma_0, T_soak_C=600.0, t_soak_s=7200.0, material="316l")
    assert r["ok"] is True
    assert r["sigma_final_Pa"] < sigma_0


def test_stress_relief_higher_temp_more_relaxation():
    sigma_0 = 300e6
    r_low = stress_relief_soak(sigma_0, T_soak_C=400.0, t_soak_s=3600.0, material="316l")
    r_high = stress_relief_soak(sigma_0, T_soak_C=700.0, t_soak_s=3600.0, material="316l")
    assert r_low["ok"] and r_high["ok"]
    assert r_high["sigma_final_Pa"] < r_low["sigma_final_Pa"]


def test_stress_relief_zero_duration():
    sigma_0 = 200e6
    r = stress_relief_soak(sigma_0, T_soak_C=600.0, t_soak_s=0.0)
    assert r["ok"] is True
    # Zero soak: sigma unchanged (exp(0)=1)
    assert abs(r["sigma_final_Pa"] - sigma_0) < 1.0


def test_stress_relief_fraction_in_range():
    r = stress_relief_soak(300e6, T_soak_C=500.0, t_soak_s=7200.0, material="ti64")
    assert r["ok"] is True
    assert 0.0 < r["fraction_remaining"] < 1.0


def test_stress_relief_bad_t_soak():
    r = stress_relief_soak(300e6, T_soak_C=500.0, t_soak_s=-1.0)
    assert r["ok"] is False
    assert "reason" in r


# ---------------------------------------------------------------------------
# am_residual_1d — monotone and saturation behaviour
# ---------------------------------------------------------------------------

def test_more_layers_more_accumulated_stress_monotone():
    """More layers → mean accumulated stress is non-decreasing."""
    sigma_prev = 0.0
    for n in range(1, 30):
        r = am_residual_1d(
            n_layers=n,
            layer_thickness=30e-6,
            part_length=0.05,
            part_width=0.02,
            material="316l",
        )
        assert r["ok"] is True
        sigma_now = r["accumulated_stress"][-1]
        # Should not decrease (flat is OK, inherent strain is constant per layer)
        assert sigma_now >= sigma_prev - 1.0  # 1 Pa tolerance
        sigma_prev = sigma_now


def test_accumulated_stress_saturates():
    """The incremental change in accumulated mean stress diminishes (saturates)."""
    r10 = am_residual_1d(10, 30e-6, 0.05, 0.02)
    r100 = am_residual_1d(100, 30e-6, 0.05, 0.02)
    r1000 = am_residual_1d(1000, 30e-6, 0.05, 0.02)
    assert r10["ok"] and r100["ok"] and r1000["ok"]
    # Incremental change shrinks as n grows (logarithmic saturation)
    delta_10_to_100 = abs(r100["accumulated_stress"][-1] - r10["accumulated_stress"][-1])
    delta_100_to_1000 = abs(r1000["accumulated_stress"][-1] - r100["accumulated_stress"][-1])
    assert delta_100_to_1000 < delta_10_to_100 or delta_100_to_1000 < 1e6  # converging


# ---------------------------------------------------------------------------
# Stoney-like warpage scaling
# ---------------------------------------------------------------------------

def test_warpage_proportional_stoney():
    """delta ∝ eps * L^2 / t — doubling L^2/t should roughly double warpage."""
    t = 30e-6
    L1 = 0.05
    L2 = L1 * math.sqrt(2)  # L2^2 = 2*L1^2

    r1 = am_residual_1d(50, t, L1, 0.02)
    r2 = am_residual_1d(50, t, L2, 0.02)
    assert r1["ok"] and r2["ok"]

    ratio = r2["tip_deflection_m"] / r1["tip_deflection_m"]
    # Expected ratio ~2 (within 30% band)
    assert 1.4 < ratio < 2.6, f"Stoney ratio={ratio:.3f} out of expected band"


def test_warpage_proportional_to_length_squared():
    """Doubling part_length should quadruple (within band) tip deflection."""
    t = 30e-6
    r1 = am_residual_1d(50, t, 0.04, 0.02)
    r2 = am_residual_1d(50, t, 0.08, 0.02)
    assert r1["ok"] and r2["ok"]
    ratio = r2["tip_deflection_m"] / r1["tip_deflection_m"]
    # Stoney: delta ∝ L^2, so ratio should be ~4 (allow 50% band: 2–6)
    assert 2.0 < ratio < 6.0, f"L^2 scaling ratio={ratio:.3f}"


# ---------------------------------------------------------------------------
# Tall vs squat
# ---------------------------------------------------------------------------

def test_tall_thin_curls_more_than_squat():
    """Tall thin part (many layers, long length) curls more than squat."""
    r_tall = am_residual_1d(
        n_layers=200,
        layer_thickness=30e-6,
        part_length=0.10,
        part_width=0.02,
    )
    r_squat = am_residual_1d(
        n_layers=20,
        layer_thickness=30e-6,
        part_length=0.02,
        part_width=0.02,
    )
    assert r_tall["ok"] and r_squat["ok"]
    assert r_tall["tip_deflection_m"] > r_squat["tip_deflection_m"]


# ---------------------------------------------------------------------------
# Recoater collision
# ---------------------------------------------------------------------------

def test_recoater_collision_flagged():
    """Very long part with thin layers should trigger recoater collision."""
    r = am_residual_1d(
        n_layers=500,
        layer_thickness=30e-6,
        part_length=0.20,
        part_width=0.05,
        material="316l",
    )
    assert r["ok"] is True
    assert r["recoater_collision"] is True
    assert r["recoater_collision_layer"] is not None
    assert r["recoater_collision_layer"] >= 1


def test_no_recoater_collision_short_part():
    """Very short/stubby part with very thick layers should NOT trigger recoater collision.

    3 layers of 2 mm on a 3mm × 3mm footprint: cumulative tip deflection
    (< 0.6 mm) is well below one layer thickness (2 mm).
    """
    r = am_residual_1d(
        n_layers=3,
        layer_thickness=2000e-6,   # 2 mm layers
        part_length=0.003,          # 3 mm footprint
        part_width=0.003,
    )
    assert r["ok"] is True
    assert r["recoater_collision"] is False
    assert r["recoater_collision_layer"] is None


def test_recoater_collision_layer_is_first_exceeding():
    """recoater_collision_layer is the FIRST layer where curl > t."""
    r = am_residual_1d(
        n_layers=500,
        layer_thickness=30e-6,
        part_length=0.20,
        part_width=0.05,
    )
    assert r["ok"] is True
    if r["recoater_collision"]:
        crit_layer = r["recoater_collision_layer"]
        t = 30e-6
        # The accumulated curvature at crit_layer-1 should give deflection <= t
        if crit_layer > 1:
            kappa_prev = r["accumulated_curvature"][crit_layer - 2]
            tip_prev = kappa_prev * 0.20 ** 2 / 2.0
            assert tip_prev <= t * 1.001  # not yet colliding


# ---------------------------------------------------------------------------
# Support load
# ---------------------------------------------------------------------------

def test_support_load_proportional_to_overhang():
    """Doubling overhang_fraction should double support load."""
    r1 = am_residual_1d(50, 30e-6, 0.05, 0.02, overhang_fraction=0.25)
    r2 = am_residual_1d(50, 30e-6, 0.05, 0.02, overhang_fraction=0.50)
    assert r1["ok"] and r2["ok"]
    assert r1["support_load_N"] > 0.0
    ratio = r2["support_load_N"] / r1["support_load_N"]
    assert abs(ratio - 2.0) < 0.01


def test_zero_overhang_zero_support_load():
    r = am_residual_1d(50, 30e-6, 0.05, 0.02, overhang_fraction=0.0)
    assert r["ok"] is True
    assert r["support_load_N"] == 0.0


# ---------------------------------------------------------------------------
# Orientation scan
# ---------------------------------------------------------------------------

def test_orient_scan_returns_all_angles():
    angles = [0.0, 30.0, 60.0, 90.0]
    r = am_orient_scan(
        n_layers=50,
        layer_thickness=30e-6,
        part_length=0.05,
        part_width=0.02,
        part_height=0.005,
        orientations=angles,
    )
    assert r["ok"] is True
    result_angles = [res["angle_deg"] for res in r["results"]]
    assert set(result_angles) == set(angles)


def test_orient_scan_picks_min_residual():
    """Orientation scan best_angle_deg matches the minimum tip deflection."""
    r = am_orient_scan(
        n_layers=50,
        layer_thickness=30e-6,
        part_length=0.10,
        part_width=0.02,
        part_height=0.005,
        orientations=[0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0],
    )
    assert r["ok"] is True
    # The best should be the actual minimum in results
    best = min(
        (res for res in r["results"] if res["tip_deflection_m"] is not None),
        key=lambda x: x["tip_deflection_m"],
    )
    assert r["best_angle_deg"] == best["angle_deg"]
    assert abs(r["best_tip_deflection_m"] - best["tip_deflection_m"]) < 1e-15


def test_orient_scan_90deg_differs_from_0deg():
    """Building on side (90°) gives different tip deflection than upright (0°)."""
    r = am_orient_scan(
        n_layers=50,
        layer_thickness=30e-6,
        part_length=0.10,
        part_width=0.02,
        part_height=0.005,
        orientations=[0.0, 90.0],
    )
    assert r["ok"] is True
    tips = {res["angle_deg"]: res["tip_deflection_m"] for res in r["results"]}
    assert abs(tips[0.0] - tips[90.0]) > 1e-10


def test_orient_scan_empty_orientations():
    r = am_orient_scan(
        n_layers=50,
        layer_thickness=30e-6,
        part_length=0.05,
        part_width=0.02,
        part_height=0.005,
        orientations=[],
    )
    assert r["ok"] is False
    assert "reason" in r


# ---------------------------------------------------------------------------
# Process comparison
# ---------------------------------------------------------------------------

def test_ded_less_residual_than_lpbf():
    """DED process should give less inherent strain → lower residual stress."""
    r_lpbf = am_residual_1d(50, 30e-6, 0.05, 0.02, process="lpbf")
    r_ded = am_residual_1d(50, 30e-6, 0.05, 0.02, process="ded")
    assert r_lpbf["ok"] and r_ded["ok"]
    assert r_ded["max_sigma_Pa"] < r_lpbf["max_sigma_Pa"]
    assert r_ded["inherent_strain"] < r_lpbf["inherent_strain"]


# ---------------------------------------------------------------------------
# Temperature effect
# ---------------------------------------------------------------------------

def test_higher_preheat_lower_residual():
    """Higher preheat temperature reduces thermal gradient → lower residual."""
    r_low = am_residual_1d(50, 30e-6, 0.05, 0.02, T_preheat=20.0)
    r_high = am_residual_1d(50, 30e-6, 0.05, 0.02, T_preheat=200.0)
    assert r_low["ok"] and r_high["ok"]
    assert r_high["max_sigma_Pa"] < r_low["max_sigma_Pa"]


# ---------------------------------------------------------------------------
# Longer part → more deflection
# ---------------------------------------------------------------------------

def test_longer_part_more_deflection():
    r1 = am_residual_1d(50, 30e-6, 0.03, 0.02)
    r2 = am_residual_1d(50, 30e-6, 0.08, 0.02)
    assert r1["ok"] and r2["ok"]
    assert r2["tip_deflection_m"] > r1["tip_deflection_m"]


# ---------------------------------------------------------------------------
# Error paths — never raise
# ---------------------------------------------------------------------------

def test_bad_material_no_raise():
    r = am_residual_1d(10, 30e-6, 0.05, 0.02, material="vibranium")
    assert r["ok"] is False
    assert "reason" in r


def test_n_layers_zero_no_raise():
    r = am_residual_1d(0, 30e-6, 0.05, 0.02)
    assert r["ok"] is False


def test_layer_thickness_zero_no_raise():
    r = am_residual_1d(10, 0.0, 0.05, 0.02)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# Stoney curvature scaling: kappa ∝ 1/t² (film-thickness / substrate analogy)
# ---------------------------------------------------------------------------

def test_stoney_curvature_thinner_substrate_more_curvature():
    """With fewer layers (thinner substrate) the Stoney curvature should be larger."""
    # Stoney: kappa = 6*sigma_f*t_f / (E_s * t_s^2)
    # Halving t_s (fewer layers) → 4x curvature
    r_thick = am_residual_1d(100, 30e-6, 0.05, 0.02)
    r_thin = am_residual_1d(50, 30e-6, 0.05, 0.02)
    assert r_thick["ok"] and r_thin["ok"]
    # Fewer layers → smaller t_s → larger Stoney curvature
    assert r_thin["stoney_curvature"] > r_thick["stoney_curvature"]
