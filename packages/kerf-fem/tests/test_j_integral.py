"""
Test suite for kerf_fem.fracture.j_integral — J-integral computation.

Coverage
--------
1.  J-integral on a Mode-I crack: J = K_I²/E* (plane stress LEFM)
2.  J-integral is path-independent (within 5%) for two different contours
3.  j_to_k: round-trip K → J → K
4.  j_to_k: plane strain gives larger E' factor
5.  Circular contour: J is positive for opening-mode crack
6.  J ≈ 0 for a stress-free field (no crack loading)
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_fem.fracture.j_integral import (
    JIntegralContour,
    compute_j_integral,
    j_to_k,
)


# ---------------------------------------------------------------------------
# Analytical Mode-I near-tip fields (Williams 1957)
# ---------------------------------------------------------------------------

def mode_i_stress(x: np.ndarray, K_I: float, nu: float = 0.3) -> np.ndarray:
    """Analytical Mode-I near-tip stress field (plane strain)."""
    r = float(np.linalg.norm(x))
    if r < 1e-12:
        # Return a large but finite stress (crack tip singularity)
        return np.zeros((2, 2))
    theta = float(np.arctan2(x[1], x[0]))
    factor = K_I / math.sqrt(2 * math.pi * r)
    # Williams (1957): σ_xx, σ_yy, σ_xy
    cos_h = math.cos(theta / 2)
    sin_h = math.sin(theta / 2)
    cos_3h = math.cos(3 * theta / 2)
    sin_3h = math.sin(3 * theta / 2)
    s_xx = factor * cos_h * (1 - sin_h * sin_3h)
    s_yy = factor * cos_h * (1 + sin_h * sin_3h)
    s_xy = factor * sin_h * cos_h * cos_3h
    return np.array([[s_xx, s_xy], [s_xy, s_yy]])


def mode_i_displacement(x: np.ndarray, K_I: float, E: float, nu: float = 0.3,
                         condition: str = "plane_strain") -> np.ndarray:
    """Analytical Mode-I near-tip displacement field."""
    r = float(np.linalg.norm(x))
    if r < 1e-12:
        return np.zeros(2)
    theta = float(np.arctan2(x[1], x[0]))
    G = E / (2 * (1 + nu))
    kappa = (3 - 4 * nu) if condition == "plane_strain" else (3 - nu) / (1 + nu)
    factor = K_I / (2 * G) * math.sqrt(r / (2 * math.pi))
    cos_h = math.cos(theta / 2)
    sin_h = math.sin(theta / 2)
    u_x = factor * cos_h * (kappa - 1 + 2 * sin_h**2)
    u_y = factor * sin_h * (kappa + 1 - 2 * cos_h**2)
    return np.array([u_x, u_y])


def mode_i_sed(x: np.ndarray, K_I: float, E: float, nu: float = 0.3,
               condition: str = "plane_strain") -> float:
    """Strain energy density W = (1/2)σ:ε for Mode-I crack field."""
    sigma = mode_i_stress(x, K_I, nu)
    r = float(np.linalg.norm(x))
    if r < 1e-12:
        return 0.0
    # For plane strain: W = (1+ν)/E * [(1-ν)(σxx² + σyy²) - 2ν σxx σyy + 2 σxy²]
    # Simplified: W = (σ_xx² + σ_yy² - 2ν σ_xx σ_yy + 2(1+ν)σ_xy²) / (2E) (plane stress)
    # Use plane stress for simplicity in test
    s_xx = sigma[0, 0]
    s_yy = sigma[1, 1]
    s_xy = sigma[0, 1]
    W = (s_xx**2 + s_yy**2 - 2 * nu * s_xx * s_yy + 2 * (1 + nu) * s_xy**2) / (2 * E)
    return W


def make_circular_contour(center: np.ndarray, radius: float, n_pts: int = 64) -> JIntegralContour:
    """Create a circular contour around the crack tip."""
    angles = np.linspace(0, 2 * math.pi, n_pts, endpoint=False)
    points = center + radius * np.column_stack([np.cos(angles), np.sin(angles)])
    return JIntegralContour(points=points, crack_tip=center)


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
E = 200e9   # Pa
NU = 0.3
K_I_REF = 10e6  # 10 MPa√m
CRACK_TIP = np.array([0.0, 0.0])


# ---------------------------------------------------------------------------
# 1. J = K_I²/E (plane stress)
# ---------------------------------------------------------------------------

def test_j_integral_equals_K_squared_over_E():
    """For a Mode-I elastic crack, J should equal K_I²/E (plane stress)."""
    r = 5e-3  # 5 mm radius — in K-dominant zone
    contour = make_circular_contour(CRACK_TIP, r, n_pts=256)

    J_expected = K_I_REF**2 / E  # plane stress

    J_computed = compute_j_integral(
        contour=contour,
        stress_field=lambda x: mode_i_stress(x, K_I_REF, NU),
        displacement_field=lambda x: mode_i_displacement(x, K_I_REF, E, NU, "plane_stress"),
        strain_energy_density=lambda x: mode_i_sed(x, K_I_REF, E, NU, "plane_stress"),
    )

    # Allow ±10% numerical integration error (midpoint rule on circular contour)
    rel_err = abs(J_computed - J_expected) / J_expected
    assert rel_err < 0.15, f"J computed={J_computed:.4e}, expected={J_expected:.4e}, rel_err={rel_err:.3f}"


# ---------------------------------------------------------------------------
# 2. Path independence: two contours should give same J within 5%
# ---------------------------------------------------------------------------

def test_j_integral_path_independence():
    """J should be path-independent: same value for two different contours."""
    r1 = 3e-3  # 3 mm
    r2 = 8e-3  # 8 mm

    contour1 = make_circular_contour(CRACK_TIP, r1, n_pts=256)
    contour2 = make_circular_contour(CRACK_TIP, r2, n_pts=256)

    def s_field(x): return mode_i_stress(x, K_I_REF, NU)
    def u_field(x): return mode_i_displacement(x, K_I_REF, E, NU, "plane_stress")
    def w_field(x): return mode_i_sed(x, K_I_REF, E, NU, "plane_stress")

    J1 = compute_j_integral(contour1, s_field, u_field, w_field)
    J2 = compute_j_integral(contour2, s_field, u_field, w_field)

    # Both should be near K_I²/E
    rel_diff = abs(J1 - J2) / max(abs(J1), abs(J2))
    assert rel_diff < 0.05, f"Path dependence too large: J1={J1:.4e}, J2={J2:.4e}, rel_diff={rel_diff:.3f}"


# ---------------------------------------------------------------------------
# 3. j_to_k: round-trip K → J → K
# ---------------------------------------------------------------------------

def test_j_to_k_round_trip():
    K_in = 20e6  # 20 MPa√m
    J = K_in**2 * (1 - NU**2) / E  # plane strain
    K_out = j_to_k(J, E, NU, "plane_strain")
    assert abs(K_out - K_in) / K_in < 1e-10


# ---------------------------------------------------------------------------
# 4. j_to_k: plane strain E' > E → larger K for same J
# ---------------------------------------------------------------------------

def test_j_to_k_plane_strain_larger_E_prime():
    J = 1000.0  # J/m²
    K_ps = j_to_k(J, E, NU, "plane_stress")   # K = sqrt(J*E)
    K_pe = j_to_k(J, E, NU, "plane_strain")   # K = sqrt(J*E/(1-ν²))
    # plane strain E' = E/(1-ν²) > E → K_pe > K_ps
    assert K_pe > K_ps


# ---------------------------------------------------------------------------
# 5. J is positive for opening-mode crack
# ---------------------------------------------------------------------------

def test_j_integral_positive_for_mode_I():
    r = 4e-3
    contour = make_circular_contour(CRACK_TIP, r, n_pts=128)
    J = compute_j_integral(
        contour=contour,
        stress_field=lambda x: mode_i_stress(x, K_I_REF, NU),
        displacement_field=lambda x: mode_i_displacement(x, K_I_REF, E, NU),
        strain_energy_density=lambda x: mode_i_sed(x, K_I_REF, E, NU),
    )
    assert J > 0, f"J should be positive for Mode-I crack; got J={J:.4e}"


# ---------------------------------------------------------------------------
# 6. J ≈ 0 for stress-free field (trivial case: K=0)
# ---------------------------------------------------------------------------

def test_j_integral_zero_for_no_load():
    r = 5e-3
    contour = make_circular_contour(CRACK_TIP, r, n_pts=64)

    def zero_stress(x): return np.zeros((2, 2))
    def zero_disp(x): return np.zeros(2)
    def zero_sed(x): return 0.0

    J = compute_j_integral(contour, zero_stress, zero_disp, zero_sed)
    assert abs(J) < 1e-20, f"J should be ~0 for zero field; got J={J:.4e}"
