"""
Signal-integrity closed-form solver for PCB transmission lines.

Formulas
--------
Microstrip single-ended Z0 — IPC-2141A (2004 edition), equations 1-1 / 1-2:
    Narrow trace (W_eff/H <= 1):
        Z0 = (87 / sqrt(er + 1.41)) * ln(5.98*H / (0.8*W + T))
    Wide trace (W_eff/H > 1) via Hammerstad (1975):
        er_eff = (er+1)/2 + (er-1)/2 * (1 + 12*H/W)^(-0.5)
        Z0 = 120*pi / (sqrt(er_eff) * (W/H + 1.393 + 0.667*ln(W/H + 1.444)))

Stripline single-ended Z0 — IPC-2141A (2004 edition), equation 2-1 (symmetric buried):
    Z0 = (60 / sqrt(er)) * ln(4*B / (0.67*pi*(0.8*W + T)))
    where B = total dielectric thickness between both reference planes.

Differential impedance — Wadell, "Transmission Line Design Handbook",
    Artech House (1991), §3.7 (microstrip) and §4.3 (stripline):
    Zdiff = 2 * Z0 * (1 - 0.347 * exp(-2.9 * S / H_or_B))
    where S = edge-to-edge gap between the two conductors.

Propagation delay:
    Td [ps/mm] = (1000 / c) * sqrt(er_eff)
    where c = 300 mm/ns = 3e5 mm/us.
    For microstrip, er_eff is computed from the Hammerstad approximation.
    For a conservative (maximum) estimate pass er directly (stripline).

Crosstalk (first-order lumped coupled-line model):
    Mutual capacitance and inductance coupling at the near end (NEXT) and
    far end (FEXT) grow with parallel run length and fall with spacing.
    The simplified "board-level" model used here is:
        Kb (backward / NEXT coupling factor):
            Kb = (1/4) * ((Cm / C0) + (Lm / L0))
        Kf (forward / FEXT coupling factor):
            Kf = (Td_coupled / 2) * ((Cm / C0) - (Lm / L0))
    For a homogeneous medium the inductive and capacitive coupling terms
    are approximately equal and Kf -> 0 (stripline).  On microstrip they
    differ due to the inhomogeneous dielectric.

    Simplified first-order proximity model used here (no field solver):
        coupling_ratio = 1 / (1 + (2*S / H)^2)
        Kb ≈ 0.5 * coupling_ratio          (NEXT)
        Kf ≈ 0.1 * coupling_ratio * Td_parallel [ps]  (FEXT, microstrip only)

    This model gives a monotonically decreasing estimate as spacing increases,
    consistent with the qualitative behaviour described in IPC-2141A §5.

Reflection coefficient:
    Gamma = (Z_load - Z0) / (Z_load + Z0)

Termination recommendation heuristic (industry practice):
    - Series: place R_s = Z0 - R_driver at source; suits point-to-point.
    - Parallel (to supply or GND): R_p = Z0; suits multiple-load busses.
    - Thevenin: R1 = R2 such that parallel = Z0; suits bus pull-up/pull-down.
    - AC (RC): R = Z0 in series with C to decouple DC; suits clock nets.

Author: imranparuk
"""

from __future__ import annotations

import math

# Speed of light in mm/ps
_C_MM_PS: float = 0.299792458  # 1 mm/ps = 1e-3 m / 1e-12 s


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers (mirrors diffpair.py helpers, compatible with import)
# ──────────────────────────────────────────────────────────────────────────────

def _clamp_positive(value: float, name: str) -> float:
    """Return value if > 0, else raise ValueError with a clear message."""
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number, got {value!r}")
    return float(value)


def _microstrip_er_eff(W: float, H: float, er: float) -> float:
    """Effective permittivity for microstrip (Hammerstad, 1975)."""
    ratio = W / H
    return (er + 1) / 2.0 + (er - 1) / 2.0 * (1 + 12.0 / ratio) ** (-0.5)


# ──────────────────────────────────────────────────────────────────────────────
# Public: impedance
# ──────────────────────────────────────────────────────────────────────────────

def microstrip_z0(W: float, H: float, T: float, er: float) -> float:
    """
    Single-ended microstrip characteristic impedance Z0 [ohms].

    Parameters
    ----------
    W : float  — trace width [mm]
    H : float  — dielectric height between trace and ground plane [mm]
    T : float  — copper thickness [mm]
    er : float — substrate relative permittivity (e.g. FR4 ~ 4.3-4.8)

    Returns
    -------
    float — Z0 in ohms

    Raises
    ------
    ValueError on non-positive geometry parameters.

    Formula
    -------
    IPC-2141A (2004 edition), equations 1-1 (narrow) / 1-2 (wide).
    """
    W = _clamp_positive(W, "W")
    H = _clamp_positive(H, "H")
    er = _clamp_positive(er, "er")
    if not isinstance(T, (int, float)) or T < 0:
        T = 0.035
    T = max(float(T), 1e-6)

    # Effective width corrected for copper thickness
    We = W + (T / math.pi) * (1.0 + math.log(2.0 * H / T))
    ratio = We / H

    if ratio <= 1.0:
        # IPC-2141A narrow-trace approximation
        Z0 = (87.0 / math.sqrt(er + 1.41)) * math.log(5.98 * H / (0.8 * We + T))
    else:
        # Hammerstad wide-trace using effective permittivity
        er_eff = _microstrip_er_eff(We, H, er)
        Z0 = (120.0 * math.pi) / (
            math.sqrt(er_eff) * (ratio + 1.393 + 0.667 * math.log(ratio + 1.444))
        )
    return Z0


def stripline_z0(W: float, B: float, T: float, er: float) -> float:
    """
    Single-ended symmetric stripline characteristic impedance Z0 [ohms].

    Parameters
    ----------
    W : float  — trace width [mm]
    B : float  — total dielectric thickness between both reference planes [mm]
    T : float  — copper thickness [mm]
    er : float — substrate relative permittivity

    Returns
    -------
    float — Z0 in ohms

    Raises
    ------
    ValueError on non-positive geometry parameters.

    Formula
    -------
    IPC-2141A (2004 edition), equation 2-1 (symmetric buried trace).
    """
    W = _clamp_positive(W, "W")
    B = _clamp_positive(B, "B")
    er = _clamp_positive(er, "er")
    if not isinstance(T, (int, float)) or T < 0:
        T = 0.035
    T = max(float(T), 1e-6)

    Z0 = (60.0 / math.sqrt(er)) * math.log(4.0 * B / (0.67 * math.pi * (0.8 * W + T)))
    return Z0


def diff_z0(
    z0_single: float,
    S: float,
    H_or_B: float,
    structure: str = "microstrip",
) -> float:
    """
    Differential impedance from single-ended Z0 and coupling geometry.

    Parameters
    ----------
    z0_single : float  — single-ended Z0 [ohms]
    S         : float  — edge-to-edge gap between the two traces [mm]
    H_or_B    : float  — H (microstrip) or B (stripline) [mm]
    structure : str    — 'microstrip' or 'stripline'

    Returns
    -------
    float — Zdiff in ohms (always > z0_single because the pair is loosely coupled)

    Formula
    -------
    Wadell, "Transmission Line Design Handbook" (Artech House, 1991),
    §3.7 (microstrip) and §4.3 (stripline).
    """
    z0_single = _clamp_positive(z0_single, "z0_single")
    S = _clamp_positive(S, "S")
    H_or_B = _clamp_positive(H_or_B, "H_or_B")
    coupling = math.exp(-2.9 * S / H_or_B)
    return 2.0 * z0_single * (1.0 - 0.347 * coupling)


# ──────────────────────────────────────────────────────────────────────────────
# Public: propagation delay
# ──────────────────────────────────────────────────────────────────────────────

def propagation_delay_ps_per_mm(
    er: float,
    W: float = 0.0,
    H: float = 0.0,
    structure: str = "stripline",
) -> float:
    """
    Propagation delay in ps/mm.

    For stripline (homogeneous dielectric) use er directly:
        Td = sqrt(er) / c_mm_ps

    For microstrip use the effective permittivity (requires W and H).

    Parameters
    ----------
    er        : float  — substrate relative permittivity
    W         : float  — trace width [mm] (only used for microstrip)
    H         : float  — dielectric height [mm] (only used for microstrip)
    structure : str    — 'microstrip' or 'stripline' (default: 'stripline')

    Returns
    -------
    float — propagation delay in ps/mm
    """
    er = _clamp_positive(er, "er")
    if structure == "microstrip" and W > 0 and H > 0:
        er_eff = _microstrip_er_eff(float(W), float(H), er)
    else:
        er_eff = er
    return math.sqrt(er_eff) / _C_MM_PS


def flight_time_ps(length_mm: float, td_ps_per_mm: float) -> float:
    """
    Total one-way flight time for a net of given length.

    Parameters
    ----------
    length_mm    : float — trace length [mm]
    td_ps_per_mm : float — propagation delay [ps/mm] from propagation_delay_ps_per_mm()

    Returns
    -------
    float — total flight time [ps]
    """
    length_mm = _clamp_positive(length_mm, "length_mm")
    td_ps_per_mm = _clamp_positive(td_ps_per_mm, "td_ps_per_mm")
    return length_mm * td_ps_per_mm


# ──────────────────────────────────────────────────────────────────────────────
# Public: crosstalk
# ──────────────────────────────────────────────────────────────────────────────

def _coupling_ratio(S: float, H: float) -> float:
    """
    First-order proximity coupling ratio.  Falls monotonically as S/H increases.
    Based on a simplified capacitive-coupling model:
        ratio = 1 / (1 + (2*S/H)^2)
    """
    return 1.0 / (1.0 + (2.0 * S / H) ** 2)


def crosstalk_next(
    S: float,
    H: float,
    aggressor_swing_mv: float = 1000.0,
) -> dict:
    """
    Near-end crosstalk (NEXT) estimate — first-order coupling model.

    The backward coupling coefficient Kb is estimated as:
        Kb ≈ 0.5 * coupling_ratio(S, H)
    and NEXT voltage = Kb * aggressor_swing.

    This is a conservative first-order model; actual NEXT depends on
    coupled length, rise time, and termination.  Consistent with the
    qualitative bounds in IPC-2141A §5.

    Parameters
    ----------
    S                : float — edge-to-edge spacing between aggressor and victim [mm]
    H                : float — dielectric height (microstrip H or stripline B/2) [mm]
    aggressor_swing_mv : float — aggressor signal voltage swing [mV] (default 1000 mV)

    Returns
    -------
    dict with keys: Kb (float), next_mv (float), next_pct (float)
    """
    S = _clamp_positive(S, "S")
    H = _clamp_positive(H, "H")
    aggressor_swing_mv = _clamp_positive(aggressor_swing_mv, "aggressor_swing_mv")
    Kb = 0.5 * _coupling_ratio(S, H)
    next_mv = Kb * aggressor_swing_mv
    next_pct = Kb * 100.0
    return {"Kb": Kb, "next_mv": round(next_mv, 4), "next_pct": round(next_pct, 4)}


def crosstalk_fext(
    S: float,
    H: float,
    length_mm: float,
    td_ps_per_mm: float,
    aggressor_swing_mv: float = 1000.0,
    structure: str = "microstrip",
) -> dict:
    """
    Far-end crosstalk (FEXT) estimate — first-order coupling model.

    For microstrip (inhomogeneous dielectric), the forward coupling Kf is non-zero:
        Kf ≈ 0.1 * coupling_ratio(S, H) * Td_total [ns]
    For stripline (homogeneous), Kf → 0 because inductive and capacitive
    coupling cancel; a small residual value is returned.

    Parameters
    ----------
    S                : float — edge-to-edge spacing [mm]
    H                : float — dielectric height [mm]
    length_mm        : float — parallel run (coupled) length [mm]
    td_ps_per_mm     : float — propagation delay [ps/mm]
    aggressor_swing_mv : float — aggressor voltage swing [mV]
    structure        : str   — 'microstrip' or 'stripline'

    Returns
    -------
    dict with keys: Kf (float), fext_mv (float), fext_pct (float)
    """
    S = _clamp_positive(S, "S")
    H = _clamp_positive(H, "H")
    length_mm = _clamp_positive(length_mm, "length_mm")
    td_ps_per_mm = _clamp_positive(td_ps_per_mm, "td_ps_per_mm")
    aggressor_swing_mv = _clamp_positive(aggressor_swing_mv, "aggressor_swing_mv")

    cr = _coupling_ratio(S, H)
    td_total_ns = (length_mm * td_ps_per_mm) / 1000.0  # ps -> ns

    if structure == "microstrip":
        Kf = 0.1 * cr * td_total_ns
    else:
        # Stripline: near-cancellation, small residual (~10% of microstrip)
        Kf = 0.01 * cr * td_total_ns

    fext_mv = Kf * aggressor_swing_mv
    fext_pct = Kf * 100.0
    return {"Kf": round(Kf, 6), "fext_mv": round(fext_mv, 4), "fext_pct": round(fext_pct, 4)}


# ──────────────────────────────────────────────────────────────────────────────
# Public: reflection + termination
# ──────────────────────────────────────────────────────────────────────────────

def reflection_coefficient(z_load: float, z0: float) -> float:
    """
    Voltage reflection coefficient at a load discontinuity.

        Gamma = (Z_load - Z0) / (Z_load + Z0)

    Parameters
    ----------
    z_load : float — load impedance [ohms]
    z0     : float — transmission line characteristic impedance [ohms]

    Returns
    -------
    float — Gamma in [-1, 1]  (0 = perfectly matched)
    """
    z_load = _clamp_positive(z_load, "z_load")
    z0 = _clamp_positive(z0, "z0")
    return (z_load - z0) / (z_load + z0)


def termination_recommendation(
    driver_z_ohms: float,
    line_z0_ohms: float,
    topology: str = "point_to_point",
    vcc_mv: float = 3300.0,
) -> dict:
    """
    Recommend a termination scheme and resistor value(s).

    Parameters
    ----------
    driver_z_ohms : float — driver output impedance [ohms] (typical 25-50 ohms)
    line_z0_ohms  : float — transmission line characteristic impedance [ohms]
    topology      : str   — one of:
                            'point_to_point'  — single driver, single receiver
                            'bus'             — one driver, multiple receivers
                            'clock'           — clock distribution, AC coupling preferred
    vcc_mv        : float — supply voltage [mV] (for Thevenin resistor calculation, default 3300 mV)

    Returns
    -------
    dict with keys:
        scheme        : str   — recommended termination type
        description   : str   — brief rationale
        gamma_unterminated : float — reflection coefficient without termination
        resistor_ohms : float | None — primary resistor value
        r1_ohms / r2_ohms : float | None — Thevenin or AC-RC components
        matched        : bool  — True if driver_z already matches z0

    Notes
    -----
    Heuristics follow common PCB SI practice:
      - Series termination is preferred for point-to-point when the driver
        impedance is lower than Z0 (most CMOS/LVDS drivers).
      - Parallel (to GND or to supply) is preferred for bus topologies.
      - AC (RC) is preferred for high-speed clock nets to avoid DC loading.
      - Thevenin is appropriate for bus pull-up/pull-down termination.
    """
    driver_z_ohms = _clamp_positive(driver_z_ohms, "driver_z_ohms")
    line_z0_ohms = _clamp_positive(line_z0_ohms, "line_z0_ohms")
    vcc_mv = _clamp_positive(vcc_mv, "vcc_mv")

    gamma_open = reflection_coefficient(1e9, line_z0_ohms)   # open-end
    gamma_unterminated = gamma_open  # for open-ended unterminated load

    matched = abs(driver_z_ohms - line_z0_ohms) / line_z0_ohms < 0.05

    if matched:
        return {
            "scheme": "none",
            "description": "Driver impedance already matches Z0; no termination required.",
            "gamma_unterminated": round(gamma_unterminated, 4),
            "resistor_ohms": None,
            "matched": True,
        }

    if topology == "clock":
        # AC termination: R = Z0 in series with C (C typically 47-100 pF)
        r_ac = round(line_z0_ohms, 1)
        return {
            "scheme": "AC",
            "description": (
                f"AC (RC) termination: place {r_ac} Ω in series with C (47–100 pF) at receiver. "
                "Decouples DC loading while absorbing incident energy at the receiver end."
            ),
            "gamma_unterminated": round(gamma_unterminated, 4),
            "resistor_ohms": r_ac,
            "capacitor_pf_range": [47, 100],
            "matched": False,
        }

    if topology == "bus":
        # Parallel Thevenin: R1 (to VCC) || R2 (to GND) = Z0
        # Equal-arm Thevenin: R1 = R2 = 2 * Z0
        r_thevenin = round(2.0 * line_z0_ohms, 1)
        return {
            "scheme": "Thevenin",
            "description": (
                f"Thevenin termination: R1 = {r_thevenin} Ω to VCC, R2 = {r_thevenin} Ω to GND "
                f"(parallel combination = {round(line_z0_ohms, 1)} Ω = Z0). "
                "Suitable for multi-drop bus topologies."
            ),
            "gamma_unterminated": round(gamma_unterminated, 4),
            "r1_ohms": r_thevenin,
            "r2_ohms": r_thevenin,
            "resistor_ohms": round(line_z0_ohms, 1),
            "matched": False,
        }

    # Default: point_to_point — series termination at source
    # R_series = Z0 - R_driver  (clamp to 0 if driver already >= Z0)
    r_series = max(0.0, round(line_z0_ohms - driver_z_ohms, 1))
    if r_series == 0.0:
        # Parallel to GND as fallback if series would be zero
        return {
            "scheme": "parallel",
            "description": (
                f"Parallel termination: place {round(line_z0_ohms, 1)} Ω to GND at receiver end. "
                "Driver Z >= Z0; series termination would add 0 Ω."
            ),
            "gamma_unterminated": round(gamma_unterminated, 4),
            "resistor_ohms": round(line_z0_ohms, 1),
            "matched": False,
        }

    return {
        "scheme": "series",
        "description": (
            f"Series termination: place {r_series} Ω in series at source "
            f"(driver Z {driver_z_ohms} Ω + {r_series} Ω ≈ Z0 {line_z0_ohms} Ω). "
            "Absorbs reflections at the source on the return trip."
        ),
        "gamma_unterminated": round(gamma_unterminated, 4),
        "resistor_ohms": r_series,
        "matched": False,
    }
