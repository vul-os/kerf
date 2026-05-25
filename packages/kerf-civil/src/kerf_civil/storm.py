"""
kerf_civil.storm — Rational method + HDS-5 culvert inlet-control capacity.

Rational Method
---------------
    Q = C · i · A / 360         (SI: Q in m³/s, A in ha, i in mm/hr)
    Reference: ASCE/EWRI 77-17 "Design and Construction of Urban Stormwater
    Management Systems", §3.2.
    Also: Rational Method, Kuichling (1889). Trans. ASCE, 20, 1–56.

    Q = C · i · A               when A is in m² and i is in m/s (dimensionless-C form)
    This module uses: Q [m³/s] = C · (i [mm/hr] / 3600000) · (A [m²])
    (equivalent to dividing by 3 600 000 to convert mm/hr·m² → m³/s)

HDS-5 Culvert Inlet Control
----------------------------
    Reference: Federal Highway Administration (2012). "Hydraulic Design of
    Highway Culverts", Hydraulic Design Series No. 5, Third Edition.
    HDS-5, FHWA-HIF-12-026. Publication date: April 2012.

    Unsubmerged inlet control (Form 1 – square-edge headwall):
        H/D = K · (Q / (A · D^0.5))^M + K_s    when  Q/(A·D^0.5) ≤ 3.5
        (HDS-5 Table 3-1, concrete box culverts:
            K = 0.0098, M = 2.0 for square-edge wingwall
            K = 0.0078, M = 2.0 for 30–75° wingwall)

    Submerged inlet control (Form 2):
        H/D = c · (Q/(A·D^0.5))^2 + Y - 0.5S    when Q/(A·D^0.5) > 4.0
        (HDS-5 Table 3-1:
            c = 0.0433, Y = 0.82 for square-edge concrete circular)

    Between 3.5 and 4.0, linear interpolation is used.

    The inlet-control head H is the headwater depth above the invert of the
    pipe at the inlet face (m).

Public API
----------
rational_method(C, i_mm_hr, area_ha) -> float (m³/s)
    Rational formula Q = C · i · A / 360   (A in ha, i in mm/hr → m³/s)

rational_method_si(C, i_m_s, area_m2) -> float (m³/s)
    Rational formula with SI base units.

culvert_inlet_control(Q, d, area, slope, K=0.0098, M=2.0, c=0.0433, Y=0.82) -> dict
    HDS-5 inlet-control head H above inlet invert (m).
    Returns: {'H_m': float, 'HW_D': float, 'regime': str}
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Rational method
# ---------------------------------------------------------------------------

def rational_method(C: float, i_mm_hr: float, area_ha: float) -> float:
    """
    Rational method peak runoff.

    Q = C · i · A / 360

    Parameters
    ----------
    C        : float — runoff coefficient (0–1)
    i_mm_hr  : float — rainfall intensity (mm/hr)
    area_ha  : float — drainage area (hectares)

    Returns
    -------
    float — peak discharge Q (m³/s)

    Reference: Kuichling (1889); ASCE Manual of Engineering Practice No. 36.
    """
    if not (0.0 <= C <= 1.0):
        raise ValueError(f"C must be in [0, 1], got {C!r}")
    if i_mm_hr < 0:
        raise ValueError(f"i_mm_hr must be ≥ 0, got {i_mm_hr!r}")
    if area_ha < 0:
        raise ValueError(f"area_ha must be ≥ 0, got {area_ha!r}")
    return C * i_mm_hr * area_ha / 360.0


def rational_method_si(C: float, i_m_s: float, area_m2: float) -> float:
    """
    Rational method in SI base units.

    Q = C · i [m/s] · A [m²]

    Returns
    -------
    float — peak discharge Q (m³/s)
    """
    if not (0.0 <= C <= 1.0):
        raise ValueError(f"C must be in [0, 1], got {C!r}")
    return C * i_m_s * area_m2


# ---------------------------------------------------------------------------
# HDS-5 Inlet control
# ---------------------------------------------------------------------------

# HDS-5 Table 3-1 default coefficients for concrete circular culverts,
# square-edge headwall (most conservative / common design).
_HDS5_UNSUBMERGED_K = 0.0098   # Table 3-1: square-edge wingwall
_HDS5_UNSUBMERGED_M = 2.0
_HDS5_SUBMERGED_c   = 0.0433   # Table 3-1: concrete circular, square-edge
_HDS5_SUBMERGED_Y   = 0.82
_HDS5_TRANSITION_LO = 3.5      # Q/(A·D^0.5) lower transition
_HDS5_TRANSITION_HI = 4.0      # Q/(A·D^0.5) upper transition


def culvert_inlet_control(
    Q: float,
    d: float,
    area: float | None = None,
    slope: float = 0.01,
    K: float = _HDS5_UNSUBMERGED_K,
    M: float = _HDS5_UNSUBMERGED_M,
    c: float = _HDS5_SUBMERGED_c,
    Y: float = _HDS5_SUBMERGED_Y,
) -> dict:
    """
    HDS-5 inlet-control headwater depth for a circular culvert.

    Parameters
    ----------
    Q     : float — discharge (m³/s)
    d     : float — culvert inside diameter (m)
    area  : float | None — culvert cross-sectional area (m²);
            defaults to π·(d/2)²
    slope : float — culvert barrel slope (m/m); used only in submerged form
    K, M  : HDS-5 unsubmerged coefficients (Table 3-1)
    c, Y  : HDS-5 submerged coefficients (Table 3-1)

    Returns
    -------
    dict:
        H_m    : float — inlet-control headwater depth above inlet invert (m)
        HW_D   : float — headwater-to-diameter ratio H/D
        regime : str   — 'unsubmerged', 'submerged', or 'transition'

    Notes
    -----
    HDS-5 Equations (3-1a / 3-1b / 3-1c):
        Unsubmerged (Q/(A·√D) ≤ 3.5):
            Hw/D = K·(Q/(A·√D))^M + K_s
            K_s = 0.5·S for concrete (approx 0 for most uses; we use 0)
        Submerged (Q/(A·√D) > 4.0):
            Hw/D = c·(Q/(A·√D))² + Y − 0.5·S
        Transition: linear interpolation between the two forms.

    Reference: FHWA (2012) HDS-5, Third Edition, Chapter 3, p. 3-6 to 3-9.
    """
    if Q < 0:
        raise ValueError("Q must be ≥ 0")
    if d <= 0:
        raise ValueError("d must be > 0")

    A = area if area is not None else math.pi * (d / 2.0) ** 2

    if A <= 0:
        raise ValueError("area must be > 0")

    # Dimensionless discharge parameter (HDS-5 §3.2.1)
    x = Q / (A * math.sqrt(d))  # units: (m³/s) / (m² · m^0.5) = m^0.5/s ... dimensionless in design charts when Q in cfs/ft

    # In HDS-5, the parameter is Q/(A·D^0.5) in mixed customary units
    # (Q in cfs, A in ft², D in ft). For SI we apply a scaling factor:
    #   Q_cfs = Q_m3s * 35.3147
    #   A_ft2 = A_m2 * 10.7639
    #   D_ft  = D_m  * 3.28084
    # Scaled dimensionless param:
    Q_cfs = Q * 35.3147
    A_ft2 = A * 10.7639
    D_ft  = d * 3.28084
    x_us  = Q_cfs / (A_ft2 * math.sqrt(D_ft))

    K_s = 0.5 * slope  # embankment correction term (HDS-5 §3.2.1)

    def unsubmerged_HWD(x: float) -> float:
        return K * x ** M + K_s

    def submerged_HWD(x: float) -> float:
        return c * x ** 2 + Y - 0.5 * slope

    if x_us <= _HDS5_TRANSITION_LO:
        hw_d = unsubmerged_HWD(x_us)
        regime = "unsubmerged"
    elif x_us >= _HDS5_TRANSITION_HI:
        hw_d = submerged_HWD(x_us)
        regime = "submerged"
    else:
        # Linear interpolation
        hw_lo = unsubmerged_HWD(_HDS5_TRANSITION_LO)
        hw_hi = submerged_HWD(_HDS5_TRANSITION_HI)
        t = (x_us - _HDS5_TRANSITION_LO) / (_HDS5_TRANSITION_HI - _HDS5_TRANSITION_LO)
        hw_d = hw_lo + t * (hw_hi - hw_lo)
        regime = "transition"

    H_m = hw_d * d  # convert H/D ratio → metres

    return {
        "H_m": round(H_m, 6),
        "HW_D": round(hw_d, 6),
        "regime": regime,
        "x_us": round(x_us, 4),
    }


def culvert_capacity(
    d: float,
    HW: float,
    slope: float = 0.01,
    K: float = _HDS5_UNSUBMERGED_K,
    M: float = _HDS5_UNSUBMERGED_M,
    c: float = _HDS5_SUBMERGED_c,
    Y: float = _HDS5_SUBMERGED_Y,
    tol: float = 1e-6,
    max_iter: int = 50,
) -> dict:
    """
    Invert HDS-5 inlet-control equation: given headwater depth HW, solve for Q.

    Parameters
    ----------
    d    : float — culvert diameter (m)
    HW   : float — headwater depth above inlet invert (m)
    slope, K, M, c, Y : as for culvert_inlet_control

    Returns
    -------
    dict: Q_m3s, HW_D, regime
    """
    if HW <= 0:
        return {"Q_m3s": 0.0, "HW_D": 0.0, "regime": "dry"}
    if d <= 0:
        raise ValueError("d must be > 0")

    A = math.pi * (d / 2.0) ** 2
    A_ft2 = A * 10.7639
    D_ft  = d * 3.28084

    hw_d = HW / d

    # Determine regime by checking both equations at HW
    K_s = 0.5 * slope

    def unsubmerged_x(hw_d: float) -> float:
        # K * x^M + K_s = hw_d → x = ((hw_d - K_s)/K)^(1/M)
        val = (hw_d - K_s) / max(K, 1e-30)
        if val <= 0:
            return 0.0
        return val ** (1.0 / M)

    def submerged_x(hw_d: float) -> float:
        # c*x^2 + Y - 0.5*S = hw_d → x = sqrt((hw_d - Y + 0.5S)/c)
        val = (hw_d - Y + 0.5 * slope) / max(c, 1e-30)
        if val <= 0:
            return 0.0
        return math.sqrt(val)

    x_lo = unsubmerged_x(hw_d)
    x_hi = submerged_x(hw_d)

    # Use the appropriate regime
    if x_lo <= _HDS5_TRANSITION_LO:
        x_us = x_lo
        regime = "unsubmerged"
    elif x_hi >= _HDS5_TRANSITION_HI:
        x_us = x_hi
        regime = "submerged"
    else:
        # Transition: pick midpoint
        x_us = (x_lo + x_hi) / 2.0
        regime = "transition"

    # Convert back to SI
    Q_cfs = x_us * A_ft2 * math.sqrt(D_ft)
    Q_m3s = Q_cfs / 35.3147

    return {
        "Q_m3s": round(max(Q_m3s, 0.0), 6),
        "HW_D": round(hw_d, 6),
        "regime": regime,
    }
