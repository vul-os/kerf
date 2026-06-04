"""
Test suite for kerf_fem.fracture.stress_intensity — K_I extraction.

Coverage
--------
1.  CT specimen K_I: increases with crack length (for fixed load)
2.  CT specimen K_I matches ASTM E399 formula at a/W=0.5
3.  k_to_j round-trip: J → K → J
4.  k_to_j: plane stress vs plane strain
5.  stress_intensity_from_displacement: Mode-I gives positive K
6.  stress_intensity_from_displacement: Mode-I K ≈ reference K_I
7.  SENT geometry: K_I formula returns positive value
8.  CT specimen: a/W < 0.1 raises ValueError
9.  Zero load → K_I = 0
10. CT specimen: K_I scales linearly with load P
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_fem.fracture.stress_intensity import (
    fracture_toughness_from_load,
    stress_intensity_from_displacement,
    k_to_j,
)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

E = 200e9    # Pa
NU = 0.3
W = 0.05     # 50 mm width
B = 0.025    # 25 mm thickness


# ---------------------------------------------------------------------------
# 1. CT K_I increases with crack length
# ---------------------------------------------------------------------------

def test_CT_K_increases_with_crack_length():
    load = 10000.0  # N
    crack_lengths = [0.25 * W, 0.4 * W, 0.5 * W, 0.6 * W, 0.7 * W]
    Ks = [
        fracture_toughness_from_load(a, W, load, B, "CT_specimen")
        for a in crack_lengths
    ]
    for i in range(len(Ks) - 1):
        assert Ks[i + 1] > Ks[i], \
            f"K should increase with a: K[{i}]={Ks[i]:.3e} > K[{i+1}]={Ks[i+1]:.3e}"


# ---------------------------------------------------------------------------
# 2. CT specimen ASTM E399 formula at a/W=0.5
# ---------------------------------------------------------------------------

def test_CT_K_at_half_width():
    """Check ASTM E399 formula at a/W=0.5 against a known reference value."""
    a = 0.5 * W
    P = 20000.0   # 20 kN
    K_I = fracture_toughness_from_load(a, W, P, B, "CT_specimen")
    # ASTM E399 at α=0.5: f(0.5) ≈ 9.66 (standard value)
    # K_I = (P/(B·sqrt(W))) · f(0.5) = 20000/(0.025·sqrt(0.05)) · 9.66
    alpha = 0.5
    poly = (0.886 + 4.64*alpha - 13.32*alpha**2 + 14.72*alpha**3 - 5.6*alpha**4)
    f_alpha = (2.0 + alpha) / (1.0 - alpha)**1.5 * poly
    K_expected = (P / (B * math.sqrt(W))) * f_alpha
    assert abs(K_I - K_expected) / K_expected < 1e-8


# ---------------------------------------------------------------------------
# 3. k_to_j round-trip
# ---------------------------------------------------------------------------

def test_k_to_j_round_trip():
    K_in = 30e6  # 30 MPa√m
    J = k_to_j(K_in, E, NU, "plane_strain")
    # J = K² (1-ν²)/E → K = sqrt(J·E/(1-ν²))
    K_out = math.sqrt(J * E / (1.0 - NU**2))
    assert abs(K_out - K_in) / K_in < 1e-10


# ---------------------------------------------------------------------------
# 4. k_to_j: plane stress vs plane strain
# ---------------------------------------------------------------------------

def test_k_to_j_plane_stress_vs_plane_strain():
    K_I = 20e6
    J_ps = k_to_j(K_I, E, NU, "plane_stress")    # K²/E
    J_pe = k_to_j(K_I, E, NU, "plane_strain")    # K²(1-ν²)/E
    # plane strain J is smaller (more constrained)
    assert J_pe < J_ps
    assert abs(J_ps / J_pe - 1.0 / (1.0 - NU**2)) < 1e-8


# ---------------------------------------------------------------------------
# 5. stress_intensity_from_displacement: Mode-I gives positive K
# ---------------------------------------------------------------------------

def _mode_i_disp(x, K_I, E, nu, cond="plane_strain"):
    r = float(np.linalg.norm(x))
    if r < 1e-12:
        return np.zeros(2)
    theta = float(np.arctan2(x[1], x[0]))
    G = E / (2 * (1 + nu))
    kappa = (3 - 4*nu) if cond == "plane_strain" else (3 - nu) / (1 + nu)
    fac = K_I / (2 * G) * math.sqrt(r / (2 * math.pi))
    cos_h = math.cos(theta / 2)
    sin_h = math.sin(theta / 2)
    u_x = fac * cos_h * (kappa - 1 + 2 * sin_h**2)
    u_y = fac * sin_h * (kappa + 1 - 2 * cos_h**2)
    return np.array([u_x, u_y])


def test_stress_intensity_mode_I_positive():
    K_ref = 10e6  # 10 MPa√m
    crack_tip = np.array([0.0, 0.0])
    K_I = stress_intensity_from_displacement(
        crack_tip=crack_tip,
        displacement_field=lambda x: _mode_i_disp(x, K_ref, E, NU),
        youngs_modulus=E,
        poisson=NU,
        mode="I",
        r_sample_mm=0.5,
        condition="plane_strain",
    )
    assert K_I > 0, f"K_I should be positive; got {K_I:.4e}"


# ---------------------------------------------------------------------------
# 6. stress_intensity_from_displacement: K ≈ K_ref
# ---------------------------------------------------------------------------

def test_stress_intensity_mode_I_accurate():
    K_ref = 10e6
    crack_tip = np.array([0.0, 0.0])
    K_I = stress_intensity_from_displacement(
        crack_tip=crack_tip,
        displacement_field=lambda x: _mode_i_disp(x, K_ref, E, NU),
        youngs_modulus=E,
        poisson=NU,
        mode="I",
        r_sample_mm=0.5,
        condition="plane_strain",
    )
    rel_err = abs(K_I - K_ref) / K_ref
    # DCT accuracy: within 10% for ideal Williams field
    assert rel_err < 0.10, f"K_I={K_I:.4e}, K_ref={K_ref:.4e}, rel_err={rel_err:.3f}"


# ---------------------------------------------------------------------------
# 7. SENT geometry returns positive K_I
# ---------------------------------------------------------------------------

def test_SENT_K_positive():
    K_I = fracture_toughness_from_load(
        crack_length_m=0.02,   # 20 mm crack
        plate_width_m=0.1,     # 100 mm width
        load_n=50000.0,        # 50 kN
        plate_thickness_m=0.01,
        geometry="SENT",
    )
    assert K_I > 0


# ---------------------------------------------------------------------------
# 8. CT specimen with a/W < 0.1 raises ValueError
# ---------------------------------------------------------------------------

def test_CT_invalid_a_over_W():
    with pytest.raises(ValueError, match="CT specimen"):
        fracture_toughness_from_load(
            crack_length_m=0.005,  # a/W = 0.1 → boundary
            plate_width_m=0.1,
            load_n=10000.0,
            plate_thickness_m=0.01,
            geometry="CT_specimen",
        )


# ---------------------------------------------------------------------------
# 9. Zero load → K_I = 0
# ---------------------------------------------------------------------------

def test_zero_load_zero_K():
    K_I = fracture_toughness_from_load(
        crack_length_m=0.025,
        plate_width_m=0.05,
        load_n=0.0,
        plate_thickness_m=0.025,
        geometry="CT_specimen",
    )
    assert K_I == 0.0


# ---------------------------------------------------------------------------
# 10. CT specimen K_I is linear in P
# ---------------------------------------------------------------------------

def test_CT_K_linear_in_load():
    a = 0.5 * W
    K1 = fracture_toughness_from_load(a, W, 10000.0, B, "CT_specimen")
    K2 = fracture_toughness_from_load(a, W, 20000.0, B, "CT_specimen")
    assert abs(K2 / K1 - 2.0) < 1e-8, f"K should double with doubled load; ratio={K2/K1:.6f}"
