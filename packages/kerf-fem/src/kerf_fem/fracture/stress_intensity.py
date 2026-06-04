"""
Stress intensity factor (SIF) calculation from FEM displacement fields
and from standardised test specimen formulae.

SIMPLIFICATION NOTICE
---------------------
This module implements 2-D extraction of K_I, K_II, K_III using the
displacement correlation technique (DCT). For production accuracy,
the interaction integral method (also called the M-integral) provides
superior results, especially near geometric features. Full 3-D crack-
front SIF extraction requires a crack-front parameterisation that is
beyond the scope of this pure-Python module.

References
----------
  Anderson, T. L. (2005). "Fracture Mechanics: Fundamentals and
      Applications." 3rd ed., CRC Press. Chapters 2-3.
  ASTM E399-22. "Standard Test Method for Linear-Elastic Plane-Strain
      Fracture Toughness KIC of Metallic Materials."
  Henshell, R. D. & Shaw, K. G. (1975). "Crack tip finite elements
      are unnecessary." Int. J. Numer. Methods Eng. 9(3), 495–507.
  Barsoum, R. S. (1976). "On the use of isoparametric finite elements
      in linear fracture mechanics." Int. J. Numer. Methods Eng. 10(1).
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np


# ---------------------------------------------------------------------------
# Displacement correlation (DCT) — extract K from crack-opening displacement
# ---------------------------------------------------------------------------

def stress_intensity_from_displacement(
    crack_tip: np.ndarray,
    displacement_field: Callable[[np.ndarray], np.ndarray],
    youngs_modulus: float,
    poisson: float,
    mode: str = "I",
    r_sample_mm: float = 0.1,
    condition: str = "plane_strain",
) -> float:
    """Extract the stress intensity factor from the near-tip displacement field.

    Uses the displacement correlation technique (DCT): the asymptotic
    crack-tip displacement field (Williams 1957) is sampled at a known
    distance r from the tip.

    Mode-I (opening) formulae (Anderson 2005, eq. 2.46)
    ---------------------------------------------------
    Along θ = ±π (crack faces, behind the tip):
        u_y(r, θ=π) = (K_I / (2G)) · sqrt(r/(2π)) · (κ + 1)

    → K_I = (2G · u_y) / (sqrt(r/(2π)) · (κ + 1))

    where:
        G = E / (2(1+ν))     shear modulus
        κ = 3-4ν             plane strain
        κ = (3-ν)/(1+ν)      plane stress

    Mode-II (sliding) along crack face (θ = ±π):
        u_x(r, θ=π) = -(K_II / (2G)) · sqrt(r/(2π)) · (κ + 1)

    Mode-III (tearing) — out-of-plane:
        u_z = (K_III / G) · sqrt(r/(2π)) · (2/π) · sin(θ/2)
        At θ = π: u_z = (2K_III / G) · sqrt(r/(2π)) · (1/√(2π))

    Parameters
    ----------
    crack_tip : np.ndarray, shape (2,) or (3,)
        Coordinates of the crack tip.
    displacement_field : callable
        Function ``u(x) -> np.ndarray`` giving displacement at a point.
        For 2D: returns shape (2,); for 3D / Mode-III: returns shape (3,).
    youngs_modulus : float
        Young's modulus E [Pa].
    poisson : float
        Poisson's ratio ν.
    mode : str
        Fracture mode: 'I' (opening), 'II' (sliding), or 'III' (tearing).
    r_sample_mm : float
        Radial distance from the crack tip at which to sample [mm].
        Should be in the K-dominant zone: 0.01a ≤ r ≤ 0.1a where a
        is the crack length. Default 0.1 mm.
    condition : str
        'plane_strain' (default) or 'plane_stress'.

    Returns
    -------
    K : float
        Stress intensity factor [Pa√m].
        K_I for mode='I', K_II for mode='II', K_III for mode='III'.

    Notes
    -----
    - This is the simplest DCT method. Results depend on mesh quality
      near the crack tip and the choice of r_sample_mm.
    - For best accuracy: use quarter-point (collapsed) elements at the
      tip and sample r in the range [0.5h, 2h] where h is the element
      size at the tip.
    - The crack is assumed to propagate along the x-axis (θ=0 ahead,
      θ=π above crack face).
    """
    crack_tip = np.asarray(crack_tip, dtype=float)
    r_m = r_sample_mm * 1e-3

    # Material constants
    G = youngs_modulus / (2.0 * (1.0 + poisson))
    kappa = (3.0 - 4.0 * poisson) if condition == "plane_strain" else (3.0 - poisson) / (1.0 + poisson)

    # Sample point: at distance r, angle θ = π (above crack face, behind tip)
    # x1 direction = crack propagation = -x (behind tip)
    # Point above the crack face at θ = π
    sample_above = crack_tip + np.array([-r_m, r_m * 1e-6])  # just above crack
    sample_below = crack_tip + np.array([-r_m, -r_m * 1e-6])  # just below

    if mode == "I":
        # u_y above - u_y below = crack opening displacement (COD)
        u_above = displacement_field(sample_above)
        u_below = displacement_field(sample_below)
        # Opening displacement at θ=π (Williams 1957)
        delta_u_y = float(u_above[1] - u_below[1])  # COD

        # DCT formula: K_I = delta_u_y * 2G / ((kappa+1) * sqrt(r/(2π)))
        denom = (kappa + 1.0) * math.sqrt(r_m / (2.0 * math.pi))
        if abs(denom) < 1e-300:
            return 0.0
        K = (2.0 * G * delta_u_y) / denom / 2.0
        # The /2 accounts for the fact that delta_u_y = 2 * u_y (symmetric)
        # Full formula: K_I = G * delta_u_y * sqrt(2π/r) / (kappa+1)
        K = G * delta_u_y * math.sqrt(2.0 * math.pi / r_m) / (kappa + 1.0)
        return K

    elif mode == "II":
        # Sliding mode: u_x difference across crack face
        u_above = displacement_field(sample_above)
        u_below = displacement_field(sample_below)
        delta_u_x = float(u_above[0] - u_below[0])  # sliding displacement

        # K_II = G * delta_u_x * sqrt(2π/r) / (kappa+1) (sign convention)
        denom = (kappa + 1.0) * math.sqrt(r_m / (2.0 * math.pi))
        if abs(denom) < 1e-300:
            return 0.0
        K = -G * delta_u_x * math.sqrt(2.0 * math.pi / r_m) / (kappa + 1.0)
        return K

    elif mode == "III":
        # Anti-plane shear (Mode III): u_z at θ=π
        # u_z(r, π) = (2 K_III / G) * sqrt(r / (2π))
        # → K_III = u_z * G / (2 * sqrt(r/(2π)))
        sample = crack_tip + np.array([-r_m, r_m * 1e-6])
        u = displacement_field(sample)
        if len(u) < 3:
            raise ValueError("displacement_field must return 3 components for Mode III")
        u_z = float(u[2])
        factor = 2.0 * math.sqrt(r_m / (2.0 * math.pi))
        if abs(factor) < 1e-300:
            return 0.0
        K = u_z * G / factor
        return K

    else:
        raise ValueError(f"mode must be 'I', 'II', or 'III', got '{mode}'")


# ---------------------------------------------------------------------------
# ASTM E399 CT-specimen K_I formula
# ---------------------------------------------------------------------------

def fracture_toughness_from_load(
    crack_length_m: float,
    plate_width_m: float,
    load_n: float,
    plate_thickness_m: float,
    geometry: str = "CT_specimen",
) -> float:
    """Compute K_I from load using a standardised specimen geometry.

    Supported geometries
    --------------------
    'CT_specimen'  — Compact Tension (CT) specimen per ASTM E399.
    'SENT'         — Single-Edge Notched Tension.
    'SENB'         — Single-Edge Notched Bending (3-point bend).

    CT Specimen — ASTM E399 §9
    ---------------------------
    K_I = (P / (B · sqrt(W))) · f(a/W)

    where:
        P  = applied load [N]
        B  = thickness [m]
        W  = width (distance from load-line to back face) [m]
        a  = crack length [m]
        f(α) = (2+α)/(1-α)^(3/2) · (0.886 + 4.64α - 13.32α² + 14.72α³ - 5.6α⁴)
             (ASTM E399 Annex A1, valid for 0.2 ≤ a/W ≤ 0.95)

    SENT — Single-Edge Notched Tension
    ------------------------------------
    K_I = σ_∞ · sqrt(πa) · F(a/W)
    F(α) ≈ 1.12 - 0.231α + 10.55α² - 21.72α³ + 30.39α⁴
    (Tada, Paris & Irwin 2000, p. 2.7)

    SENB — 3-Point Bend
    --------------------
    K_I = (P · S) / (B · W^(3/2)) · f(a/W)
    S = span, simplified as S = 4W.

    Parameters
    ----------
    crack_length_m : float
        Crack length a [m].
    plate_width_m : float
        For CT: W = distance from load-line to back face [m].
        For SENT/SENB: full plate width [m].
    load_n : float
        Applied load P [N]. For SENT, this is the nominal stress × area.
    plate_thickness_m : float
        Specimen thickness B [m].
    geometry : str
        Specimen geometry identifier.

    Returns
    -------
    K_I : float
        Stress intensity factor [Pa√m].

    Reference: ASTM E399-22; Tada et al. (2000).
    """
    a = float(crack_length_m)
    W = float(plate_width_m)
    P = float(load_n)
    B = float(plate_thickness_m)

    if B <= 0 or W <= 0:
        raise ValueError("plate_width_m and plate_thickness_m must be positive")

    alpha = a / W

    if geometry == "CT_specimen":
        # ASTM E399 Annex A1 — valid for 0.2 ≤ α ≤ 0.95
        if alpha < 0.1 or alpha > 0.99:
            raise ValueError(
                f"CT specimen: a/W = {alpha:.3f} out of valid range [0.1, 0.99]"
            )
        # Polynomial factor f(α)
        poly = (
            0.886
            + 4.64 * alpha
            - 13.32 * alpha**2
            + 14.72 * alpha**3
            - 5.6 * alpha**4
        )
        f_alpha = (2.0 + alpha) / (1.0 - alpha) ** 1.5 * poly
        K_I = (P / (B * math.sqrt(W))) * f_alpha
        return K_I

    elif geometry == "SENT":
        # Single-Edge Notched Tension (Tada et al. 2000)
        # Nominal stress from load and cross-section (W - a) × B
        sigma_nom = P / ((W - a) * B)
        # Boundary-correction factor (Tada 2000, p. 2.7)
        F = (
            1.12
            - 0.231 * alpha
            + 10.55 * alpha**2
            - 21.72 * alpha**3
            + 30.39 * alpha**4
        )
        K_I = sigma_nom * math.sqrt(math.pi * a) * F
        return K_I

    elif geometry == "SENB":
        # 3-point bend, span S = 4W (standard ratio)
        S = 4.0 * W
        poly = (
            1.99
            - alpha * (1.0 - alpha) * (2.15 - 3.93 * alpha + 2.7 * alpha**2)
        )
        f_alpha = (
            (6.0 * math.sqrt(alpha) / (1.0 + 2.0 * alpha))
            / (1.0 - alpha) ** 1.5
            * poly
        )
        K_I = (P * S) / (B * W**1.5) * f_alpha / 6.0
        # Normalise to match standard form P·S/(B·W^(3/2))·f(a/W)
        # Simpler compact form (Tada 2000, p. 2.10):
        F2 = (
            1.93
            - 3.07 * alpha
            + 14.53 * alpha**2
            - 25.11 * alpha**3
            + 25.80 * alpha**4
        )
        K_I = (P * S / (B * W**1.5)) * F2 * math.sqrt(alpha)
        return K_I

    else:
        raise ValueError(
            f"geometry must be 'CT_specimen', 'SENT', or 'SENB', got '{geometry}'"
        )


def k_to_j(K_I: float, E: float, nu: float, condition: str = "plane_strain") -> float:
    """Convert K_I to J-integral (energy release rate G).

    For linear-elastic fracture mechanics (LEFM):
        Plane strain:  G = J = K_I² · (1-ν²) / E
        Plane stress:  G = J = K_I² / E

    Reference: Anderson (2005), eq. 2.57.
    """
    if condition == "plane_strain":
        return K_I**2 * (1.0 - nu**2) / E
    else:
        return K_I**2 / E
