"""
Microfluidic channel cross-section optimizer.

Optimizes rectangular, trapezoidal, and semicircular channel cross-sections for
a given flow rate and pressure-drop budget.

References
----------
Bruus, H. (2008). *Theoretical Microfluidics*. Oxford University Press.
  - Rectangular Poiseuille flow: §3 / eq. 3.27 (Fourier-series friction factor)
  - Trapezoidal DRIE cross-section: §3.4

Nguyen, N.-T. and Wereley, S.T. (2002). *Fundamentals and Applications of
Microfluidics*. Artech House.
  - Non-circular cross-section hydraulics: §2.3

DISCLAIMER
----------
Calculations are based on Bruus 2008 + Nguyen-Wereley 2002 published analytical
methods — NOT certified for regulatory, medical-device, or safety-critical use.
All results must be independently verified against fabricated device measurements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

_UL_MIN_TO_M3_S = 1e-9 / 60.0   # 1 µL/min = 1.667e-11 m³/s
_UM_TO_M = 1e-6


# ---------------------------------------------------------------------------
# Friction factor for rectangular cross-sections (Bruus eq. 3.27)
# ---------------------------------------------------------------------------

def _rect_friction_factor(alpha: float, n_terms: int = 10) -> float:
    """
    Dimensionless friction / correction factor for rectangular Poiseuille flow.

    For a rectangular channel of width *w* and height *h* (h ≤ w, α = h/w):

        f(α) = 1 - (192/π⁵) · α · Σ_{n=1,3,5,...} tanh(nπ/2α) / n⁵

    This is Bruus (2008) eq. 3.27.  The full ΔP formula is then:

        ΔP = 12μQL / (wh³ · f(α))

    Parameters
    ----------
    alpha : float
        Aspect ratio h/w (must be in (0, 1]).
    n_terms : int
        Number of odd-integer terms to accumulate in the series.

    Returns
    -------
    float
        Correction factor f ∈ (0, 1].  Equals 1 only in the thin-film limit α→0.
    """
    if not (0 < alpha <= 1.0):
        raise ValueError(f"alpha must be in (0, 1]; got {alpha}")

    series = 0.0
    for i in range(n_terms):
        n = 2 * i + 1  # 1, 3, 5, …
        series += math.tanh(n * math.pi / (2.0 * alpha)) / n**5

    return 1.0 - (192.0 / math.pi**5) * alpha * series


# ---------------------------------------------------------------------------
# Rectangular channel
# ---------------------------------------------------------------------------

def pressure_drop_rect(
    width_um: float,
    height_um: float,
    length_um: float,
    flow_rate_ul_min: float,
    viscosity_pa_s: float = 1e-3,
) -> float:
    """
    Pressure drop in a rectangular microchannel (Bruus 2008 §3 / eq. 3.27).

    Uses the full Fourier-series friction factor rather than the 0.63-coefficient
    approximation, giving convergence to the analytical series within 0.01% for
    any aspect ratio.

    Parameters
    ----------
    width_um : float
        Channel width [µm].  Must be ≥ height_um (larger cross-sectional dimension).
    height_um : float
        Channel height [µm].
    length_um : float
        Channel length [µm].
    flow_rate_ul_min : float
        Volumetric flow rate [µL/min].
    viscosity_pa_s : float
        Dynamic viscosity [Pa·s].  Default: 1e-3 (water at 20 °C).

    Returns
    -------
    float
        Pressure drop ΔP [Pa].

    Raises
    ------
    ValueError
        If any dimension or flow rate is non-positive, or width < height.
    """
    if width_um <= 0:
        raise ValueError(f"width_um must be positive; got {width_um}")
    if height_um <= 0:
        raise ValueError(f"height_um must be positive; got {height_um}")
    if length_um <= 0:
        raise ValueError(f"length_um must be positive; got {length_um}")
    if flow_rate_ul_min <= 0:
        raise ValueError(f"flow_rate_ul_min must be positive; got {flow_rate_ul_min}")
    if viscosity_pa_s <= 0:
        raise ValueError(f"viscosity_pa_s must be positive; got {viscosity_pa_s}")
    if height_um > width_um:
        raise ValueError(
            f"width_um ({width_um}) must be ≥ height_um ({height_um}). "
            "Swap so width is the larger dimension."
        )

    w = width_um * _UM_TO_M
    h = height_um * _UM_TO_M
    L = length_um * _UM_TO_M
    Q = flow_rate_ul_min * _UL_MIN_TO_M3_S
    mu = viscosity_pa_s

    alpha = h / w  # aspect ratio in (0, 1]
    f = _rect_friction_factor(alpha)

    # ΔP = 12μQL / (wh³ · f(α))
    return 12.0 * mu * Q * L / (w * h**3 * f)


# ---------------------------------------------------------------------------
# Trapezoidal channel (DRIE cross-section, Bruus §3.4)
# ---------------------------------------------------------------------------

def pressure_drop_trapezoidal(
    width_top_um: float,
    width_bottom_um: float,
    height_um: float,
    length_um: float,
    flow_rate_ul_min: float,
    viscosity_pa_s: float = 1e-3,
) -> float:
    """
    Pressure drop in a trapezoidal microchannel (DRIE-etched cross-section).

    Following Bruus (2008) §3.4: a trapezoidal cross-section is approximated by
    computing the hydraulic diameter from the trapezoidal area and wetted perimeter,
    then applying the Hagen-Poiseuille-generalised formula:

        ΔP = (32 μ Q L) / (π D_h⁴ / 8)   →   ΔP = 128 μ Q L / (π D_h⁴)

    where D_h = 4A/P_wet is the hydraulic diameter.

    This method is the standard engineering approximation for non-circular
    microchannels (Nguyen-Wereley 2002 §2.3) and is accurate to within ~5% for
    practical DRIE geometries (sidewall angle < 10° from vertical).

    Parameters
    ----------
    width_top_um : float
        Top (wider) opening width [µm].
    width_bottom_um : float
        Bottom (narrower) floor width [µm].
    height_um : float
        Channel depth / height [µm].
    length_um : float
        Channel length [µm].
    flow_rate_ul_min : float
        Volumetric flow rate [µL/min].
    viscosity_pa_s : float
        Dynamic viscosity [Pa·s].

    Returns
    -------
    float
        Pressure drop ΔP [Pa].
    """
    for name, val in [
        ("width_top_um", width_top_um),
        ("width_bottom_um", width_bottom_um),
        ("height_um", height_um),
        ("length_um", length_um),
        ("flow_rate_ul_min", flow_rate_ul_min),
        ("viscosity_pa_s", viscosity_pa_s),
    ]:
        if val <= 0:
            raise ValueError(f"{name} must be positive; got {val}")

    w_top = width_top_um * _UM_TO_M
    w_bot = width_bottom_um * _UM_TO_M
    h = height_um * _UM_TO_M
    L = length_um * _UM_TO_M
    Q = flow_rate_ul_min * _UL_MIN_TO_M3_S
    mu = viscosity_pa_s

    # Trapezoid geometry
    area = 0.5 * (w_top + w_bot) * h
    slant = math.sqrt(h**2 + ((w_top - w_bot) / 2.0) ** 2)
    wetted_perimeter = w_top + w_bot + 2.0 * slant

    D_h = 4.0 * area / wetted_perimeter

    # Generalised Hagen-Poiseuille via hydraulic diameter
    # R = 128μL / (πD_h⁴), ΔP = R·Q
    return 128.0 * mu * Q * L / (math.pi * D_h**4)


# ---------------------------------------------------------------------------
# Semicircular channel (Hagen-Poiseuille with D_h correction)
# ---------------------------------------------------------------------------

def pressure_drop_semicircular(
    radius_um: float,
    length_um: float,
    flow_rate_ul_min: float,
    viscosity_pa_s: float = 1e-3,
) -> float:
    """
    Pressure drop in a semicircular microchannel via hydraulic diameter.

    Semicircle: A = πr²/2, P_wet = πr + 2r = r(π+2)
    D_h = 4A/P_wet = 4·(πr²/2) / (r(π+2)) = 2πr/(π+2)

    Parameters
    ----------
    radius_um : float
        Radius of the semicircle [µm].
    length_um : float
        Channel length [µm].
    flow_rate_ul_min : float
        Volumetric flow rate [µL/min].
    viscosity_pa_s : float
        Dynamic viscosity [Pa·s].

    Returns
    -------
    float
        Pressure drop ΔP [Pa].
    """
    for name, val in [
        ("radius_um", radius_um),
        ("length_um", length_um),
        ("flow_rate_ul_min", flow_rate_ul_min),
        ("viscosity_pa_s", viscosity_pa_s),
    ]:
        if val <= 0:
            raise ValueError(f"{name} must be positive; got {val}")

    r = radius_um * _UM_TO_M
    L = length_um * _UM_TO_M
    Q = flow_rate_ul_min * _UL_MIN_TO_M3_S
    mu = viscosity_pa_s

    D_h = 2.0 * math.pi * r / (math.pi + 2.0)
    return 128.0 * mu * Q * L / (math.pi * D_h**4)


# ---------------------------------------------------------------------------
# Reynolds number
# ---------------------------------------------------------------------------

def reynolds_number(
    diameter_um: float,
    flow_rate_ul_min: float,
    density_kg_m3: float = 1000.0,
    viscosity_pa_s: float = 1e-3,
) -> float:
    """
    Reynolds number for flow in a microchannel.

        Re = ρ · V̄ · D / μ

    where V̄ = Q / A is the mean velocity and D is the hydraulic diameter.
    For a circular channel, A = π(D/2)² = πD²/4, so V̄ = 4Q/(πD²).

    Parameters
    ----------
    diameter_um : float
        Hydraulic diameter [µm].
    flow_rate_ul_min : float
        Volumetric flow rate [µL/min].
    density_kg_m3 : float
        Fluid density [kg/m³].  Default: 1000 (water).
    viscosity_pa_s : float
        Dynamic viscosity [Pa·s].  Default: 1e-3 (water at 20 °C).

    Returns
    -------
    float
        Dimensionless Reynolds number Re.
    """
    for name, val in [
        ("diameter_um", diameter_um),
        ("flow_rate_ul_min", flow_rate_ul_min),
        ("density_kg_m3", density_kg_m3),
        ("viscosity_pa_s", viscosity_pa_s),
    ]:
        if val <= 0:
            raise ValueError(f"{name} must be positive; got {val}")

    D = diameter_um * _UM_TO_M
    Q = flow_rate_ul_min * _UL_MIN_TO_M3_S
    rho = density_kg_m3
    mu = viscosity_pa_s

    A = math.pi * (D / 2.0) ** 2   # circular cross-section area
    V_mean = Q / A
    return rho * V_mean * D / mu


# ---------------------------------------------------------------------------
# Optimizer result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CrossSectionResult:
    """Result from ``optimize_cross_section``."""

    shape: str
    """Shape name: 'rectangular', 'trapezoidal', or 'semicircular'."""

    footprint_m2: float
    """Channel bounding-box cross-sectional footprint w × h [m²]."""

    pressure_drop_pa: float
    """Actual pressure drop at the given flow rate [Pa]."""

    dimensions: dict
    """Shape-specific dimensions in µm.  Keys depend on ``shape``."""

    aspect_ratio: float
    """Aspect ratio used (h/w for rect/trap; r/r=1 for semicircle)."""

    reynolds_number: float
    """Reynolds number based on hydraulic diameter."""


# ---------------------------------------------------------------------------
# Cross-section optimizer
# ---------------------------------------------------------------------------

def optimize_cross_section(
    flow_rate_ul_min: float,
    length_um: float,
    max_pressure_pa: float,
    candidate_shapes: list[Literal["rectangular", "trapezoidal", "semicircular"]],
    aspect_ratio_range: tuple[float, float] = (0.1, 1.0),
    n_aspect: int = 50,
    n_size: int = 200,
    size_range_um: tuple[float, float] = (5.0, 500.0),
    viscosity_pa_s: float = 1e-3,
) -> CrossSectionResult:
    """
    Grid-search for the minimum-footprint channel cross-section that satisfies a
    pressure-drop constraint at the specified flow rate.

    The optimizer iterates over:
    - ``candidate_shapes``: one or more of 'rectangular', 'trapezoidal', 'semicircular'
    - Aspect ratios in ``aspect_ratio_range`` (h/w for rect/trap, ignored for semicircular)
    - Characteristic sizes (width *w* for rect/trap, radius *r* for semicircular)

    For each (shape, aspect_ratio, size) triple it computes ΔP and records entries
    where ΔP ≤ max_pressure_pa.  Among feasible solutions the one with minimum
    footprint (w·h or π·r²/2 for semicircular) is returned.

    Parameters
    ----------
    flow_rate_ul_min : float
        Target volumetric flow rate [µL/min].
    length_um : float
        Channel length [µm].
    max_pressure_pa : float
        Maximum allowable pressure drop [Pa].
    candidate_shapes : list of str
        Shapes to evaluate.  Any subset of
        ['rectangular', 'trapezoidal', 'semicircular'].
    aspect_ratio_range : tuple of float
        (min_ar, max_ar) for h/w sweep (rectangular and trapezoidal).
        Both values must be in (0, 1].
    n_aspect : int
        Number of aspect-ratio grid points.
    n_size : int
        Number of size grid points (log-spaced over ``size_range_um``).
    size_range_um : tuple of float
        (min_size_um, max_size_um) for the characteristic dimension sweep.
    viscosity_pa_s : float
        Dynamic viscosity [Pa·s].

    Returns
    -------
    CrossSectionResult
        The feasible solution with the smallest cross-sectional footprint.

    Raises
    ------
    ValueError
        If no feasible cross-section is found within the search space.
    """
    if not candidate_shapes:
        raise ValueError("candidate_shapes must contain at least one shape.")
    if max_pressure_pa <= 0:
        raise ValueError(f"max_pressure_pa must be positive; got {max_pressure_pa}")

    ar_min, ar_max = aspect_ratio_range
    size_min, size_max = size_range_um
    aspect_ratios = np.linspace(ar_min, ar_max, n_aspect)
    sizes_um = np.logspace(math.log10(size_min), math.log10(size_max), n_size)

    best: CrossSectionResult | None = None

    for shape in candidate_shapes:
        if shape == "rectangular":
            for ar in aspect_ratios:
                for w_um in sizes_um:
                    h_um = w_um * ar
                    if h_um <= 0 or w_um < h_um:
                        continue
                    try:
                        dp = pressure_drop_rect(
                            w_um, h_um, length_um, flow_rate_ul_min, viscosity_pa_s
                        )
                    except ValueError:
                        continue
                    if dp <= max_pressure_pa:
                        footprint = (w_um * _UM_TO_M) * (h_um * _UM_TO_M)
                        if best is None or footprint < best.footprint_m2:
                            D_h_um = 2.0 * w_um * h_um / (w_um + h_um)
                            re = reynolds_number(
                                D_h_um, flow_rate_ul_min, viscosity_pa_s=viscosity_pa_s
                            )
                            best = CrossSectionResult(
                                shape="rectangular",
                                footprint_m2=footprint,
                                pressure_drop_pa=dp,
                                dimensions={
                                    "width_um": round(w_um, 4),
                                    "height_um": round(h_um, 4),
                                    "length_um": length_um,
                                },
                                aspect_ratio=ar,
                                reynolds_number=re,
                            )

        elif shape == "trapezoidal":
            for ar in aspect_ratios:
                for w_top_um in sizes_um:
                    h_um = w_top_um * ar
                    w_bot_um = w_top_um * 0.8  # typical DRIE 80% bottom/top ratio
                    if h_um <= 0 or w_bot_um <= 0:
                        continue
                    try:
                        dp = pressure_drop_trapezoidal(
                            w_top_um, w_bot_um, h_um, length_um,
                            flow_rate_ul_min, viscosity_pa_s
                        )
                    except ValueError:
                        continue
                    if dp <= max_pressure_pa:
                        footprint = (w_top_um * _UM_TO_M) * (h_um * _UM_TO_M)
                        if best is None or footprint < best.footprint_m2:
                            # hydraulic diameter for Reynolds
                            area = 0.5 * (w_top_um + w_bot_um) * h_um
                            slant = math.sqrt(h_um**2 + ((w_top_um - w_bot_um) / 2.0)**2)
                            P_wet = w_top_um + w_bot_um + 2.0 * slant
                            D_h_um = 4.0 * area / P_wet
                            re = reynolds_number(
                                D_h_um, flow_rate_ul_min, viscosity_pa_s=viscosity_pa_s
                            )
                            best = CrossSectionResult(
                                shape="trapezoidal",
                                footprint_m2=footprint,
                                pressure_drop_pa=dp,
                                dimensions={
                                    "width_top_um": round(w_top_um, 4),
                                    "width_bottom_um": round(w_bot_um, 4),
                                    "height_um": round(h_um, 4),
                                    "length_um": length_um,
                                },
                                aspect_ratio=ar,
                                reynolds_number=re,
                            )

        elif shape == "semicircular":
            for r_um in sizes_um:
                try:
                    dp = pressure_drop_semicircular(
                        r_um, length_um, flow_rate_ul_min, viscosity_pa_s
                    )
                except ValueError:
                    continue
                if dp <= max_pressure_pa:
                    footprint = math.pi * (r_um * _UM_TO_M) ** 2 / 2.0
                    if best is None or footprint < best.footprint_m2:
                        D_h_um = (
                            2.0 * math.pi * r_um / (math.pi + 2.0)
                        )
                        re = reynolds_number(
                            D_h_um, flow_rate_ul_min, viscosity_pa_s=viscosity_pa_s
                        )
                        best = CrossSectionResult(
                            shape="semicircular",
                            footprint_m2=footprint,
                            pressure_drop_pa=dp,
                            dimensions={
                                "radius_um": round(r_um, 4),
                                "length_um": length_um,
                            },
                            aspect_ratio=1.0,
                            reynolds_number=re,
                        )
        else:
            raise ValueError(
                f"Unknown shape '{shape}'. "
                "Must be one of: 'rectangular', 'trapezoidal', 'semicircular'."
            )

    if best is None:
        raise ValueError(
            f"No feasible cross-section found within the search space "
            f"(shapes={candidate_shapes}, ΔP_max={max_pressure_pa} Pa, "
            f"Q={flow_rate_ul_min} µL/min, L={length_um} µm). "
            "Try increasing max_pressure_pa or size_range_um."
        )

    return best
