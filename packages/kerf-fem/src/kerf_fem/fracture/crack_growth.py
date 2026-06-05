"""
Fatigue crack growth: Paris law integrator + Erdogan-Sih kink-angle predictor.

Paris-law integration
---------------------
da/dN = C · ΔK^m    (Paris & Erdogan 1963, J. Basic Eng.)

Given an initial crack length a_0, the crack-length-vs-cycles a(N) is
obtained by numerical integration (4th-order Runge-Kutta or simple Euler)
of the ODE:

    da/dN = C · [ΔK(a)]^m

where ΔK(a) is the SIF range, typically computed from a geometry factor:
    ΔK = Δσ · √(πa) · F(a/W)

Stopping criterion: a ≥ a_crit  (fracture toughness K_Ic reached), or
                    N ≥ N_max.

Erdogan-Sih mixed-mode kink angle
-----------------------------------
Under mixed-mode (K_I, K_II) loading the crack kinks at angle θ_c that
maximises the circumferential stress σ_θθ (maximum hoop stress criterion,
Erdogan & Sih 1963, J. Basic Eng.):

    θ_c = 2 arctan[ (K_I - √(K_I² + 8 K_II²)) / (4 K_II) ]

Equivalent form avoiding division by zero when K_II ≈ 0:
    If K_II = 0 → θ_c = 0  (straight-ahead Mode-I)
    Else: solve 3 K_II cos(θ/2) - K_I sin(θ) = 0 numerically.

The effective SIF used in the Paris law for mixed-mode:
    K_eff = cos(θ_c/2) [K_I cos²(θ_c/2) - (3/2) K_II sin(θ_c)]
    (Erdogan & Sih 1963, eq. 25)

XFEM limit notice
-----------------
This module drives Paris-law crack growth using the existing SIF/J-integral
as input. Full XFEM enrichment (Moës-Dolbow-Belytschko 1999) — discontinuous
Heaviside basis functions, crack-tip J2 enrichment, partition-of-unity —
is a substantially larger undertaking (T-100-C deferred). What is implemented
here is the tractable, engineering-relevant core: given a stress-intensity
history from the existing FEM solution (or a geometry-factor formula),
integrate Paris law and predict crack path direction.

References
----------
  Paris, P. & Erdogan, F. (1963). "A critical analysis of crack propagation
      laws." J. Basic Eng. 85(4), 528-534. DOI: 10.1115/1.3656900
  Erdogan, F. & Sih, G. C. (1963). "On the crack extension in plates under
      plane loading and transverse shear." J. Basic Eng. 85(4), 519-527.
  Anderson, T. L. (2005). "Fracture Mechanics." 3rd ed., CRC Press. Ch. 10.
  Suresh, S. (1998). "Fatigue of Materials." 2nd ed., Cambridge. Ch. 4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Paris-law parameters dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParisLawParams:
    """Paris-law fatigue crack-growth parameters.

    da/dN = C · ΔK^m   [m/cycle]

    Parameters
    ----------
    C : float
        Paris coefficient [m/cycle / (Pa√m)^m].  Typical steel: 1e-12 to 1e-10.
    m : float
        Paris exponent (dimensionless).  Typical metals: 2 ≤ m ≤ 4.
    K_Ic : float
        Fracture toughness [Pa√m].  Propagation stops when K_max ≥ K_Ic.
    K_th : float
        Threshold SIF range [Pa√m].  Below K_th, da/dN ≈ 0.
        Default 0 (pure Paris law, no threshold).
    R_ratio : float
        Stress ratio R = K_min / K_max.  Used to compute K_max = ΔK/(1-R).
        Default 0 (fully reversed, R=0 → K_max = ΔK).
    """
    C: float = 3e-12    # m/cycle / (Pa√m)^m  (typical structural steel)
    m: float = 3.0      # Paris exponent
    K_Ic: float = 50e6  # Pa√m  (50 MPa√m typical steel)
    K_th: float = 0.0   # Pa√m  (threshold, default 0 = pure Paris)
    R_ratio: float = 0.0  # stress ratio R = K_min/K_max


@dataclass
class CrackGrowthResult:
    """Output from integrate_paris_law."""
    crack_lengths_m: np.ndarray       # a(N) at each stored cycle
    cycles: np.ndarray                # N values
    delta_K_history: np.ndarray       # ΔK(N) at each step [Pa√m]
    da_dN_history: np.ndarray         # da/dN [m/cycle] at each step
    N_final: float                    # total cycles to stop criterion
    a_final: float                    # final crack length [m]
    stop_reason: str                  # 'fracture' | 'N_max' | 'threshold'
    converged: bool
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geometry-factor / SIF-range function helpers
# ---------------------------------------------------------------------------

def sif_range_sent(
    delta_sigma: float,
    a: float,
    W: float,
) -> float:
    """ΔK for a Single-Edge Notched Tension (SENT) specimen.

    ΔK = Δσ · √(πa) · F(a/W)

    Boundary correction factor (Tada, Paris & Irwin 2000, p. 2.7):
        F(α) = 1.12 - 0.231α + 10.55α² - 21.72α³ + 30.39α⁴

    Parameters
    ----------
    delta_sigma : float  [Pa]
    a : float  crack length [m]
    W : float  plate width [m]
    """
    alpha = a / W
    alpha = min(alpha, 0.98)  # clamp for formula validity
    F = (
        1.12
        - 0.231 * alpha
        + 10.55 * alpha**2
        - 21.72 * alpha**3
        + 30.39 * alpha**4
    )
    return delta_sigma * math.sqrt(math.pi * a) * F


def sif_range_central_crack(
    delta_sigma: float,
    a: float,
    W: float,
) -> float:
    """ΔK for a central through-crack of half-length a in a wide plate.

    ΔK = Δσ · √(πa) · sec(πa/W)^½

    (Feddersen correction; Anderson 2005 §2.3)
    """
    ratio = math.pi * a / W
    ratio = min(ratio, 0.99 * math.pi / 2.0)
    sec_corr = math.sqrt(1.0 / math.cos(ratio))
    return delta_sigma * math.sqrt(math.pi * a) * sec_corr


def sif_range_ct_specimen(
    delta_sigma_n: float,
    a: float,
    W: float,
    B: float,
    P_delta: float,
) -> float:
    """ΔK for Compact Tension (CT) specimen per ASTM E399.

    ΔK = (ΔP / (B·√W)) · f(a/W)

    f(α) = (2+α)/(1-α)^{3/2} · (0.886 + 4.64α - 13.32α² + 14.72α³ - 5.6α⁴)
    """
    alpha = min(a / W, 0.95)
    poly = (0.886 + 4.64*alpha - 13.32*alpha**2 + 14.72*alpha**3 - 5.6*alpha**4)
    f = (2.0 + alpha) / (1.0 - alpha)**1.5 * poly
    return (P_delta / (B * math.sqrt(W))) * f


# ---------------------------------------------------------------------------
# Paris-law ODE integrator (4th-order Runge-Kutta)
# ---------------------------------------------------------------------------

def integrate_paris_law(
    params: ParisLawParams,
    sif_range_fn: Callable[[float], float],
    a_0: float,
    N_max: float = 1e8,
    store_every: int = 100,
    max_steps: int = 500_000,
    adaptive: bool = True,
    da_max_fraction: float = 0.02,
) -> CrackGrowthResult:
    """Integrate Paris law da/dN = C·ΔK^m forward in cycles.

    Uses an explicit adaptive step (Euler with optional sub-stepping) or
    4th-order Runge-Kutta for accuracy.

    Parameters
    ----------
    params : ParisLawParams
    sif_range_fn : callable
        ΔK(a) → float [Pa√m].  Must accept current crack length a [m].
    a_0 : float
        Initial crack length [m].
    N_max : float
        Maximum number of cycles (run to fracture or N_max, whichever first).
    store_every : int
        Store a(N) snapshot every `store_every` steps.
    max_steps : int
        Hard limit on integration steps (prevents infinite loops).
    adaptive : bool
        If True, use adaptive step: dN chosen so da < da_max_fraction · a.
    da_max_fraction : float
        Max allowed crack-length increment per step as fraction of a.

    Returns
    -------
    CrackGrowthResult
    """
    C = params.C
    m = params.m
    K_Ic = params.K_Ic
    K_th = params.K_th
    R = params.R_ratio

    a = float(a_0)
    N = 0.0
    warnings = []

    crack_lengths = [a]
    cycles_list = [0.0]
    dK_list = []
    dadN_list = []

    stop_reason = "N_max"

    step = 0
    while N < N_max and step < max_steps:
        dK = sif_range_fn(a)
        if dK < 0:
            dK = 0.0

        # Threshold check
        if dK <= K_th:
            stop_reason = "threshold"
            break

        # Fracture check: K_max = ΔK/(1-R) ≥ K_Ic
        K_max = dK / max(1.0 - R, 1e-10)
        if K_max >= K_Ic:
            stop_reason = "fracture"
            break

        # Paris rate
        da_dN = C * dK**m

        # Adaptive dN: limit crack growth to da_max_fraction * a per step
        if adaptive and da_dN > 0:
            da_target = da_max_fraction * a
            dN = da_target / da_dN
        else:
            dN = N_max / max(max_steps, 1)

        # 4th-order RK step (Runge-Kutta on da/dN = C·ΔK(a)^m)
        # k1 = da/dN at (N, a)
        k1 = C * sif_range_fn(a)**m
        a_mid = a + 0.5 * dN * k1
        # k2 = da/dN at (N+dN/2, a+k1·dN/2)
        dK2 = sif_range_fn(a_mid)
        k2 = C * max(dK2, 0)**m
        # k3
        a_mid2 = a + 0.5 * dN * k2
        dK3 = sif_range_fn(a_mid2)
        k3 = C * max(dK3, 0)**m
        # k4
        a_end = a + dN * k3
        dK4 = sif_range_fn(a_end)
        k4 = C * max(dK4, 0)**m
        da = (dN / 6.0) * (k1 + 2*k2 + 2*k3 + k4)

        dK_list.append(dK)
        dadN_list.append(da_dN)

        a = a + da
        N = N + dN
        step += 1

        if step % store_every == 0:
            crack_lengths.append(a)
            cycles_list.append(N)

        # Check fracture after step
        K_max_new = sif_range_fn(a) / max(1.0 - R, 1e-10)
        if K_max_new >= K_Ic:
            stop_reason = "fracture"
            break

    # Always append final point
    crack_lengths.append(a)
    cycles_list.append(N)
    if not dK_list:
        dK_list.append(sif_range_fn(a))
        dadN_list.append(C * sif_range_fn(a)**m)

    if step >= max_steps:
        warnings.append(
            f"Integration reached max_steps={max_steps} without stopping criterion. "
            "Increase max_steps or reduce N_max."
        )

    return CrackGrowthResult(
        crack_lengths_m=np.array(crack_lengths),
        cycles=np.array(cycles_list),
        delta_K_history=np.array(dK_list),
        da_dN_history=np.array(dadN_list),
        N_final=N,
        a_final=a,
        stop_reason=stop_reason,
        converged=(stop_reason in ("fracture", "threshold")),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Closed-form Paris-law analytic solution (constant ΔK, no geometry factor)
# ---------------------------------------------------------------------------

def paris_analytic_flat(
    C: float, m: float, dK: float, a_0: float, a_f: float,
) -> float:
    """Analytic cycles to failure for constant ΔK, no geometry factor.

    da/dN = C · dK^m  (constant)
    N = (a_f - a_0) / (C · dK^m)

    This is exact for a constant-amplitude crack with negligible geometry
    correction (a << W).  Used for oracle validation.
    """
    rate = C * dK**m
    if rate <= 0:
        raise ValueError("Paris rate C·dK^m must be positive")
    return (a_f - a_0) / rate


def paris_analytic_sent(
    C: float, m: float, delta_sigma: float, W: float,
    a_0: float, a_f: float,
) -> float:
    """Analytic Paris cycles for SENT with geometry correction F=1.12 (low α limit).

    For α << 1:  ΔK ≈ Δσ√(πa)·1.12  (Tada 2000 p. 2.7)
    da/dN = C (Δσ·1.12·√(πa))^m = C (1.12 Δσ)^m π^{m/2} a^{m/2}

    Separable ODE:
        ∫ a^{-m/2} da = C (1.12 Δσ)^m π^{m/2} ∫ dN

    Solution (m ≠ 2):
        N = [a_f^{1-m/2} - a_0^{1-m/2}] / [(1-m/2) C (1.12 Δσ)^m π^{m/2}]

    For m = 2:
        N = ln(a_f/a_0) / [C (1.12 Δσ)^2 π]

    Reference: Anderson (2005) §10.2.1.
    """
    beta = 1.12 * delta_sigma * math.sqrt(math.pi)
    factor = C * beta**m
    p = m / 2.0

    if abs(m - 2.0) < 1e-10:
        # m = 2 special case
        N = math.log(a_f / a_0) / factor
    else:
        q = 1.0 - p  # = 1 - m/2
        N = (a_f**q - a_0**q) / (q * factor)
    return N


# ---------------------------------------------------------------------------
# Erdogan-Sih mixed-mode kink angle
# ---------------------------------------------------------------------------

def kink_angle_erdogan_sih(K_I: float, K_II: float) -> float:
    """Mixed-mode crack kink angle θ_c (Erdogan & Sih 1963).

    Maximum hoop-stress criterion: the crack extends at the angle θ_c
    that maximises the circumferential stress σ_θθ around the tip.

    Governing equation (Erdogan & Sih 1963, eq. 14):
        K_I sin(θ) + K_II (3 cos(θ) - 1) = 0

    Solution (Erdogan & Sih 1963, eq. 17):
        θ_c = 2 arctan[ (K_I - √(K_I² + 8 K_II²)) / (4 K_II) ]

    Convention
    ----------
    θ_c ∈ (-π, π] measured from the current crack direction.
    Positive K_II → negative kink angle (crack kinks downward for a
    horizontal crack with positive K_I).

    Special cases
    -------------
    K_II = 0: Mode-I only → θ_c = 0 (straight ahead).
    K_I = 0: Mode-II only → θ_c = ±70.5° (Erdogan-Sih 1963).

    Parameters
    ----------
    K_I : float   Mode-I SIF [Pa√m].
    K_II : float  Mode-II SIF [Pa√m].

    Returns
    -------
    theta_c : float  Kink angle [radians].
    """
    if abs(K_II) < 1e-15 * max(abs(K_I), 1.0):
        return 0.0

    discriminant = K_I**2 + 8.0 * K_II**2
    num = K_I - math.sqrt(discriminant)
    den = 4.0 * K_II
    theta_c = 2.0 * math.atan(num / den)
    return theta_c


def effective_sif_mixed_mode(K_I: float, K_II: float) -> float:
    """Effective SIF for mixed-mode crack growth (Erdogan-Sih 1963).

    K_eff = cos(θ_c/2) · [K_I cos²(θ_c/2) - (3/2) K_II sin(θ_c)]

    This is the Mode-I component at the kink angle, which drives growth.

    Reference: Erdogan & Sih (1963), eq. 25.
               Anderson (2005) §10.3.
    """
    theta_c = kink_angle_erdogan_sih(K_I, K_II)
    tc2 = theta_c / 2.0
    K_eff = math.cos(tc2) * (K_I * math.cos(tc2)**2 - 1.5 * K_II * math.sin(theta_c))
    return K_eff


def sigma_theta_theta(
    K_I: float,
    K_II: float,
    theta: float,
    r: float = 1.0,
) -> float:
    """Circumferential stress σ_θθ around a mixed-mode crack tip.

    σ_θθ = (1 / √(2πr)) · cos(θ/2) · [K_I cos²(θ/2) - (3/2) K_II sin(θ)]

    Reference: Erdogan & Sih (1963), eq. 6; Williams (1957).

    Parameters
    ----------
    K_I, K_II : float  Stress intensity factors [Pa√m].
    theta : float      Angle [radians] from crack line.
    r : float          Radial distance from crack tip [m]. Default 1 m.
    """
    half = theta / 2.0
    factor = 1.0 / math.sqrt(2.0 * math.pi * r)
    return factor * math.cos(half) * (K_I * math.cos(half)**2 - 1.5 * K_II * math.sin(theta))


def crack_growth_direction(
    K_I: float,
    K_II: float,
    crack_angle_rad: float = 0.0,
) -> float:
    """Absolute crack growth angle from x-axis after a mixed-mode increment.

    Returns the angle of the new crack extension in the global frame.

    Parameters
    ----------
    K_I, K_II : float  Local SIFs at the crack tip.
    crack_angle_rad : float
        Current crack orientation (angle of crack with x-axis) [radians].

    Returns
    -------
    new_crack_angle : float  [radians]
    """
    theta_c = kink_angle_erdogan_sih(K_I, K_II)
    return crack_angle_rad + theta_c
