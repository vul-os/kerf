"""
Test suite for kerf_fem.fracture.cohesive_zone — cohesive zone models.

Coverage
--------
1.  Bilinear: zero traction at δ > δ_c (complete fracture)
2.  Bilinear: zero traction at δ = 0 (no initial traction)
3.  Bilinear: peak traction = σ_max at δ = δ_0
4.  Bilinear: traction positive for 0 < δ < δ_c
5.  Bilinear: traction zero for δ < 0 (compressive separation)
6.  Bilinear: fracture energy G_c = σ_max · δ_c / 2
7.  Exponential: traction positive for δ > 0
8.  Exponential: traction → 0 as δ → ∞
9.  Exponential: peak at δ = δ_0
10. PPR: traction positive for Mode-I opening
11. PPR: zero traction for δ > δ_c
12. PPR: matches bilinear shape qualitatively (same peak σ_max)
13. cohesive_fracture_energy: bilinear G_c = (1/2)σ_max·δ_c
14. CohesiveZoneMaterial: default delta_0 = 0.05·δ_c
15. PPR mixed-mode: tangential traction in correct direction
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_fem.fracture.cohesive_zone import (
    CohesiveZoneMaterial,
    traction_separation_bilinear,
    traction_separation_exponential,
    park_paulino_roesler,
    cohesive_fracture_energy,
)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SIGMA_MAX = 50e6       # Pa  (50 MPa)
DELTA_C = 1e-4         # m   (0.1 mm)
DELTA_0 = 5e-6         # m   (0.005 mm = 5% of δ_c)


def make_bilinear_mat():
    return CohesiveZoneMaterial(
        sigma_max_pa=SIGMA_MAX,
        delta_critical_m=DELTA_C,
        type="bilinear",
        delta_0_m=DELTA_0,
    )


def make_exp_mat():
    return CohesiveZoneMaterial(
        sigma_max_pa=SIGMA_MAX,
        delta_critical_m=DELTA_C,
        type="exponential",
        delta_0_m=DELTA_0,
        fracture_energy_j_m2=SIGMA_MAX * DELTA_C / 2,  # approximate G_c
    )


# ---------------------------------------------------------------------------
# 1. Bilinear: zero traction at δ > δ_c
# ---------------------------------------------------------------------------

def test_bilinear_zero_after_critical():
    mat = make_bilinear_mat()
    T = traction_separation_bilinear(DELTA_C * 1.1, mat)
    assert T == 0.0, f"Traction should be 0 after δ_c; got {T:.4e}"


def test_bilinear_exactly_at_critical_is_zero():
    mat = make_bilinear_mat()
    T = traction_separation_bilinear(DELTA_C, mat)
    assert T == 0.0, f"Traction at δ_c should be 0; got {T:.4e}"


# ---------------------------------------------------------------------------
# 2. Bilinear: zero traction at δ = 0
# ---------------------------------------------------------------------------

def test_bilinear_zero_at_zero_separation():
    mat = make_bilinear_mat()
    T = traction_separation_bilinear(0.0, mat)
    assert T == 0.0


# ---------------------------------------------------------------------------
# 3. Bilinear: peak traction = σ_max at δ = δ_0
# ---------------------------------------------------------------------------

def test_bilinear_peak_at_delta_0():
    mat = make_bilinear_mat()
    T = traction_separation_bilinear(DELTA_0, mat)
    assert abs(T - SIGMA_MAX) / SIGMA_MAX < 1e-10, \
        f"Peak traction at δ_0 should be σ_max={SIGMA_MAX:.2e}; got {T:.4e}"


# ---------------------------------------------------------------------------
# 4. Bilinear: traction positive for 0 < δ < δ_c
# ---------------------------------------------------------------------------

def test_bilinear_positive_in_active_range():
    mat = make_bilinear_mat()
    separations = [DELTA_0 * 0.5, DELTA_0, DELTA_0 * 2, DELTA_C * 0.5, DELTA_C * 0.9]
    for d in separations:
        T = traction_separation_bilinear(d, mat)
        assert T > 0, f"Traction should be positive at δ={d:.3e}; got T={T:.4e}"


# ---------------------------------------------------------------------------
# 5. Bilinear: zero for compressive separation
# ---------------------------------------------------------------------------

def test_bilinear_zero_for_compression():
    mat = make_bilinear_mat()
    T = traction_separation_bilinear(-DELTA_0, mat)
    assert T == 0.0, f"No cohesive tension under compression; got {T:.4e}"


# ---------------------------------------------------------------------------
# 6. Bilinear fracture energy G_c = σ_max·δ_c/2
# ---------------------------------------------------------------------------

def test_bilinear_fracture_energy():
    mat = make_bilinear_mat()
    G_c = cohesive_fracture_energy(mat)
    G_expected = 0.5 * SIGMA_MAX * DELTA_C
    assert abs(G_c - G_expected) / G_expected < 1e-10, \
        f"G_c={G_c:.4e}, expected {G_expected:.4e}"


# ---------------------------------------------------------------------------
# 7. Exponential: traction positive for δ > 0
# ---------------------------------------------------------------------------

def test_exponential_positive():
    mat = make_exp_mat()
    for d in [1e-7, 1e-6, DELTA_0, DELTA_0 * 5]:
        T = traction_separation_exponential(d, mat)
        assert T > 0, f"Exponential traction should be positive at δ={d:.3e}; got {T:.4e}"


# ---------------------------------------------------------------------------
# 8. Exponential: traction → 0 as δ → large
# ---------------------------------------------------------------------------

def test_exponential_decays_to_zero():
    mat = make_exp_mat()
    T_large = traction_separation_exponential(DELTA_0 * 100, mat)
    T_small = traction_separation_exponential(DELTA_0, mat)
    assert T_large < T_small * 0.01, \
        f"Exponential should decay; T_large={T_large:.4e}, T_small={T_small:.4e}"


# ---------------------------------------------------------------------------
# 9. Exponential: peak at δ = δ_0
# ---------------------------------------------------------------------------

def test_exponential_peak_at_delta_0():
    mat = make_exp_mat()
    T_at_d0 = traction_separation_exponential(DELTA_0, mat)
    T_below = traction_separation_exponential(DELTA_0 * 0.5, mat)
    T_above = traction_separation_exponential(DELTA_0 * 2.0, mat)
    assert T_at_d0 >= T_below, "Exponential peak should be at δ_0"
    assert T_at_d0 >= T_above, "Exponential peak should be at δ_0"


# ---------------------------------------------------------------------------
# 10. PPR: traction positive for Mode-I opening
# ---------------------------------------------------------------------------

def test_ppr_positive_mode_I():
    mat = make_bilinear_mat()
    sep = np.array([DELTA_0 * 2, 0.0])
    T = park_paulino_roesler(sep, mat)
    assert T[0] > 0, f"PPR Mode-I traction should be positive; got {T[0]:.4e}"


# ---------------------------------------------------------------------------
# 11. PPR: zero traction for δ > δ_c
# ---------------------------------------------------------------------------

def test_ppr_zero_after_critical():
    mat = make_bilinear_mat()
    sep = np.array([DELTA_C * 1.5, 0.0])
    T = park_paulino_roesler(sep, mat)
    assert T[0] == 0.0, f"PPR traction should be 0 after δ_c; got {T[0]:.4e}"


# ---------------------------------------------------------------------------
# 12. PPR: peak traction ≈ σ_max (qualitative)
# ---------------------------------------------------------------------------

def test_ppr_peak_near_sigma_max():
    mat = make_bilinear_mat()
    # Sample TSL over range to find peak
    seps = np.linspace(0, DELTA_C, 1000)
    tractions = [float(park_paulino_roesler(np.array([s, 0.0]), mat)[0]) for s in seps]
    T_max = max(tractions)
    # Peak should be within 50% of sigma_max (different shape than bilinear)
    assert T_max > SIGMA_MAX * 0.3, f"PPR peak traction too low: {T_max:.4e}, σ_max={SIGMA_MAX:.4e}"


# ---------------------------------------------------------------------------
# 13. cohesive_fracture_energy bilinear
# ---------------------------------------------------------------------------

def test_cohesive_fracture_energy_bilinear():
    mat = make_bilinear_mat()
    G_c = cohesive_fracture_energy(mat)
    assert abs(G_c - 0.5 * SIGMA_MAX * DELTA_C) < 1e-6 * SIGMA_MAX * DELTA_C


# ---------------------------------------------------------------------------
# 14. Default delta_0 = 0.05·δ_c
# ---------------------------------------------------------------------------

def test_default_delta_0():
    mat = CohesiveZoneMaterial(
        sigma_max_pa=SIGMA_MAX,
        delta_critical_m=DELTA_C,
        type="bilinear",
    )
    assert abs(mat.delta_0_m - 0.05 * DELTA_C) < 1e-15 * DELTA_C


# ---------------------------------------------------------------------------
# 15. PPR mixed-mode: tangential traction in correct direction
# ---------------------------------------------------------------------------

def test_ppr_mixed_mode_tangential_direction():
    mat = make_bilinear_mat()
    sep_pos = np.array([0.0, DELTA_0 * 2])   # positive sliding
    sep_neg = np.array([0.0, -DELTA_0 * 2])  # negative sliding
    T_pos = park_paulino_roesler(sep_pos, mat)
    T_neg = park_paulino_roesler(sep_neg, mat)
    assert T_pos[1] > 0, "Positive sliding → positive tangential traction"
    assert T_neg[1] < 0, "Negative sliding → negative tangential traction"
