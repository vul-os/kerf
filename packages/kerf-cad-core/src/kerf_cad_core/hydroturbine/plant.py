"""
kerf_cad_core.hydroturbine.plant — hydropower plant engineering calculations.

Pure Python (math only, no OCC dependency).

Conventions
-----------
- All functions return a dict with at minimum:
    {"ok": True/False, ..., "warnings": [...]}
- Errors set ok=False and add a "reason" key; never raise.
- Warnings (cavitation risk, water-hammer overpressure, wrong turbine type,
  runaway risk) are accumulated in the "warnings" list; ok stays True.
- SI units throughout (Pa, m, m³/s, W, kg/m³, etc.) unless otherwise noted.

Physical constants
------------------
g   = 9.81 m/s²
rho = 1000 kg/m³ (fresh water default)

References
----------
Warnick, C.C., "Hydropower Engineering", Prentice-Hall (1984)
Çengel & Cimbala, "Fluid Mechanics" 4th ed., Ch.14
IEC 60193:1999 — Hydraulic turbines, storage pumps and pump-turbines
Moody, L.F., "Hydraulic Machinery" — Thoma/draft-tube
Gordon, J.L. (1999), "Hydraulic Turbine Efficiency", Can. J. Civ. Eng. 26
ASME PTC 18-2011 — Hydraulic Turbines and Pump-Turbines

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any

_G = 9.81          # m/s²
_RHO_WATER = 1000.0  # kg/m³

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ok(**kw: Any) -> dict:
    d = dict(kw)
    d.setdefault("ok", True)
    d.setdefault("warnings", [])
    return d


def _err(reason: str) -> dict:
    return {"ok": False, "reason": reason, "warnings": []}


# ---------------------------------------------------------------------------
# 1. Gross/net head & hydraulic power  P = ρ·g·Q·H·η
# ---------------------------------------------------------------------------

def plant_power(
    Q: float,
    H_net: float,
    eta: float = 0.88,
    rho: float = _RHO_WATER,
) -> dict:
    """Compute turbine shaft power and hydraulic power.

    P_hydraulic = ρ·g·Q·H_net          (W)
    P_shaft     = ρ·g·Q·H_net·η        (W)

    Parameters
    ----------
    Q      : flow rate (m³/s), > 0
    H_net  : net head at turbine (m), > 0
    eta    : overall plant efficiency (turbine × generator), default 0.88
    rho    : water density (kg/m³), default 1000

    Returns
    -------
    ok, P_hydraulic_W, P_shaft_W, eta, specific_power_W_m3s, warnings
    """
    if Q <= 0:
        return _err("Q must be > 0")
    if H_net <= 0:
        return _err("H_net must be > 0")
    if not (0 < eta <= 1.0):
        return _err("eta must be in (0, 1]")
    if rho <= 0:
        return _err("rho must be > 0")

    P_hyd = rho * _G * Q * H_net
    P_shaft = P_hyd * eta
    warnings: list[str] = []
    if eta < 0.50:
        warnings.append(
            f"Very low overall efficiency eta={eta:.2f}; typical range 0.75–0.93."
        )
    return _ok(
        P_hydraulic_W=P_hyd,
        P_shaft_W=P_shaft,
        P_shaft_kW=P_shaft / 1e3,
        P_shaft_MW=P_shaft / 1e6,
        eta=eta,
        specific_power_W_m3s=P_shaft / Q,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 2. Turbine-type selection via specific speed Ns (dimensionless IEC)
# ---------------------------------------------------------------------------

# Specific speed bands (dimensionless IEC, Ns = n·√Q / H^(3/4), ω in rad/s)
# Source: Warnick (1984) Table 3-1 + IEC 60193 + engineering textbooks
#
# Note: "dimensionless" specific speed Ns uses ω(rad/s), Q(m³/s), H(m).
# The old US "Nq" or "Ns_US" (n_rpm × √Q_gpm / H_ft^(5/4)) differs; we use SI.
#
# SI dimensionless Ns ranges (approximate):
#   Pelton:    0.005–0.07
#   Turgo:     0.07–0.18
#   Crossflow: 0.04–0.20  (overlaps Pelton/Turgo; preferred micro-hydro)
#   Francis:   0.18–1.20
#   Kaplan:    0.70–3.50  (overlaps Francis at high end)
#   Bulb:      1.50–5.00  (tidal / run-of-river)

_TURBINE_BANDS = [
    ("Pelton",    0.005,  0.070),
    ("Turgo",     0.070,  0.180),
    ("Crossflow", 0.040,  0.200),
    ("Francis",   0.180,  1.200),
    ("Kaplan",    0.700,  3.500),
    ("Bulb",      1.500,  5.000),
]

# Head ranges (m) for sanity-check guidance
_HEAD_GUIDE = {
    "Pelton":    (40,   2000),
    "Turgo":     (30,    300),
    "Crossflow": (1,     200),
    "Francis":   (10,    700),
    "Kaplan":    (2,      60),
    "Bulb":      (1,      20),
}


def _specific_speed_si(n_rpm: float, Q: float, H: float) -> float:
    """IEC dimensionless specific speed Ns = ω·√Q / H^(3/4)."""
    omega = n_rpm * 2.0 * math.pi / 60.0
    return omega * math.sqrt(Q) / H ** 0.75


def turbine_type_selection(
    H_net: float,
    Q: float,
    n_rpm: float | None = None,
    P_kW: float | None = None,
) -> dict:
    """Select turbine type from net head, flow, and (optionally) runner speed.

    If n_rpm is not supplied, the function derives a target runner speed from
    Gordon's empirical formula for Francis turbines (starting point) and then
    classifies based on head range only.

    Parameters
    ----------
    H_net  : net head (m), > 0
    Q      : design flow (m³/s), > 0
    n_rpm  : runner speed (rpm), optional
    P_kW   : plant power (kW), optional (informational)

    Returns
    -------
    ok, turbine_type, Ns (if n_rpm given), head_range_ok, alternatives, warnings
    """
    if H_net <= 0:
        return _err("H_net must be > 0")
    if Q <= 0:
        return _err("Q must be > 0")

    warnings: list[str] = []
    candidates: list[str] = []

    # Classify purely by head range if no speed given
    if n_rpm is None:
        # Simple head-based classification
        if H_net >= 300:
            candidates = ["Pelton"]
        elif H_net >= 150:
            candidates = ["Pelton", "Francis"]
        elif H_net >= 60:
            candidates = ["Francis"]
        elif H_net >= 20:
            candidates = ["Francis", "Kaplan"]
        elif H_net >= 5:
            candidates = ["Kaplan", "Crossflow"]
        else:
            candidates = ["Kaplan", "Bulb", "Crossflow"]

        primary = candidates[0]
        alternatives = candidates[1:]
        return _ok(
            turbine_type=primary,
            Ns=None,
            head_range_ok=True,
            alternatives=alternatives,
            method="head_range",
            warnings=warnings,
        )

    # With n_rpm: compute specific speed and classify
    if n_rpm <= 0:
        return _err("n_rpm must be > 0")

    Ns = _specific_speed_si(n_rpm, Q, H_net)

    # Find matching turbine(s) in Ns bands
    matched = [t for t, lo, hi in _TURBINE_BANDS if lo <= Ns <= hi]

    if not matched:
        warnings.append(
            f"Ns={Ns:.4f} (SI dimensionless) is outside all standard turbine bands. "
            "Check runner speed or consider custom design."
        )
        primary = "Unknown"
        alternatives = []
    else:
        primary = matched[0]
        alternatives = matched[1:]

    # Head-range sanity check
    if primary != "Unknown":
        h_lo, h_hi = _HEAD_GUIDE.get(primary, (0, 9999))
        if not (h_lo <= H_net <= h_hi):
            warnings.append(
                f"Head H_net={H_net:.1f} m is outside typical range "
                f"{h_lo}–{h_hi} m for {primary} turbines. "
                "Verify design or reconsider turbine selection."
            )
            head_ok = False
        else:
            head_ok = True
    else:
        head_ok = False

    return _ok(
        turbine_type=primary,
        Ns=Ns,
        head_range_ok=head_ok,
        alternatives=alternatives,
        method="specific_speed",
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 3. Runner speed and synchronous-speed pole matching
# ---------------------------------------------------------------------------

def runner_speed(
    H_net: float,
    turbine_type: str = "Francis",
) -> dict:
    """Estimate runner design speed using empirical correlations.

    Uses Gordon (1999) formula for Francis/Kaplan:
        n = C / H^0.5   (rpm)  where C depends on turbine class

    For Pelton: n_ref = 37 × H^0.5 / D_runner  (requires D_runner).
    Here we use the simplified IEC runner-speed factor K:
        n = K × √H (rpm)  with approximate K:
            Pelton:    K ≈  30  (single-jet)
            Francis:   K ≈  50
            Kaplan:    K ≈ 150
            Crossflow: K ≈  25
            Turgo:     K ≈  60
            Bulb:      K ≈ 200

    Parameters
    ----------
    H_net         : net head (m), > 0
    turbine_type  : one of Pelton/Turgo/Crossflow/Francis/Kaplan/Bulb

    Returns
    -------
    ok, n_rpm_approx, K_used, warnings
    """
    if H_net <= 0:
        return _err("H_net must be > 0")

    _K = {
        "pelton": 30.0,
        "turgo": 60.0,
        "crossflow": 25.0,
        "francis": 50.0,
        "kaplan": 150.0,
        "bulb": 200.0,
    }
    key = turbine_type.lower()
    if key not in _K:
        return _err(
            f"turbine_type '{turbine_type}' not recognised. "
            "Use one of: Pelton, Turgo, Crossflow, Francis, Kaplan, Bulb."
        )

    K = _K[key]
    n_rpm = K * math.sqrt(H_net)
    warnings: list[str] = []
    if n_rpm < 60:
        warnings.append(
            f"Estimated runner speed {n_rpm:.1f} rpm is very low; verify design."
        )
    if n_rpm > 1500:
        warnings.append(
            f"Estimated runner speed {n_rpm:.1f} rpm may be high; check against "
            "manufacturer limits."
        )
    return _ok(n_rpm_approx=n_rpm, K_used=K, turbine_type=turbine_type, warnings=warnings)


def synchronous_speed_poles(
    n_runner_rpm: float,
    f_hz: float = 50.0,
) -> dict:
    """Find the nearest synchronous generator speed and number of poles.

    Synchronous speed: n_s = 120·f / p  (rpm)  where p is the number of poles
    (must be an even integer ≥ 2).

    The function returns the nearest n_s ≤ n_runner (for direct-drive) and the
    next higher n_s, as well as the exact pole pair count for each.

    Parameters
    ----------
    n_runner_rpm : runner/turbine speed (rpm), > 0
    f_hz         : grid frequency (Hz), 50 or 60. Default 50.

    Returns
    -------
    ok, poles_lower, n_sync_lower_rpm, poles_higher, n_sync_higher_rpm,
    speed_ratio_lower, speed_ratio_higher, warnings
    """
    if n_runner_rpm <= 0:
        return _err("n_runner_rpm must be > 0")
    if f_hz not in (50.0, 60.0, 50, 60):
        return _err("f_hz must be 50 or 60 Hz")

    # Minimum poles is 2 (one pole pair)
    # n_s = 120·f / p  → p = 120·f / n_s
    # For a given n_runner, we want smallest even p such that n_s ≤ n_runner
    p_exact = 120.0 * f_hz / n_runner_rpm
    p_lower = max(2, int(math.ceil(p_exact)))  # round up → lower speed
    if p_lower % 2 != 0:
        p_lower += 1  # must be even

    p_higher = max(2, int(math.floor(p_exact)))  # round down → higher speed
    if p_higher % 2 != 0:
        p_higher = max(2, p_higher - 1)

    # Guard: if p_higher == p_lower after rounding, step down by 2
    if p_higher >= p_lower:
        p_higher = max(2, p_lower - 2)

    n_lower = 120.0 * f_hz / p_lower   # ≤ n_runner
    n_higher = 120.0 * f_hz / p_higher  # > n_runner

    warnings: list[str] = []
    if abs(n_lower / n_runner_rpm - 1.0) > 0.15:
        warnings.append(
            f"Nearest synchronous speed {n_lower:.1f} rpm differs by "
            f"{abs(n_lower/n_runner_rpm-1.0)*100:.1f}% from runner speed "
            f"{n_runner_rpm:.1f} rpm; a gearbox may be required."
        )

    return _ok(
        poles_lower=p_lower,
        n_sync_lower_rpm=n_lower,
        poles_higher=p_higher,
        n_sync_higher_rpm=n_higher,
        speed_ratio_lower=n_lower / n_runner_rpm,
        speed_ratio_higher=n_higher / n_runner_rpm,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 4. Penstock diameter (economic velocity), friction head loss, wall thickness
# ---------------------------------------------------------------------------

def penstock_diameter(
    Q: float,
    V_economic: float = 3.0,
) -> dict:
    """Economic penstock diameter based on target flow velocity.

    The economic velocity (3–5 m/s for steel penstocks) balances pipe cost
    against friction losses.

    D = √(4·Q / (π·V))

    Parameters
    ----------
    Q            : flow rate (m³/s), > 0
    V_economic   : target velocity (m/s), default 3.0; typical 2.5–5.0 m/s

    Returns
    -------
    ok, D_m, A_m2, V_actual_m_s, warnings
    """
    if Q <= 0:
        return _err("Q must be > 0")
    if V_economic <= 0:
        return _err("V_economic must be > 0")

    A = Q / V_economic
    D = math.sqrt(4.0 * A / math.pi)
    warnings: list[str] = []
    if V_economic < 2.0:
        warnings.append(
            f"V_economic={V_economic:.1f} m/s is low (< 2 m/s); "
            "penstock may be uneconomically large."
        )
    if V_economic > 6.0:
        warnings.append(
            f"V_economic={V_economic:.1f} m/s is high (> 6 m/s); "
            "friction losses will be significant."
        )
    return _ok(D_m=D, A_m2=A, V_economic_m_s=V_economic, warnings=warnings)


def penstock_friction_loss(
    Q: float,
    D: float,
    L: float,
    f: float = 0.015,
) -> dict:
    """Darcy-Weisbach friction head loss in penstock.

    h_f = f·(L/D)·(V²/2g)    where V = Q / A

    Parameters
    ----------
    Q : flow rate (m³/s), > 0
    D : internal diameter (m), > 0
    L : penstock length (m), > 0
    f : Darcy friction factor (dimensionless), default 0.015 (smooth steel)

    Returns
    -------
    ok, h_f_m, V_m_s, Re_approx, warnings
    """
    if Q <= 0:
        return _err("Q must be > 0")
    if D <= 0:
        return _err("D must be > 0")
    if L <= 0:
        return _err("L must be > 0")
    if f <= 0:
        return _err("f must be > 0")

    A = math.pi * D ** 2 / 4.0
    V = Q / A
    h_f = f * (L / D) * V ** 2 / (2.0 * _G)

    # Approximate Reynolds number (water at 15°C, ν ≈ 1.14e-6 m²/s)
    nu = 1.14e-6
    Re = V * D / nu

    warnings: list[str] = []
    if h_f / (L * 1e-3 + 1e-9) > 10.0:  # crude guard
        pass
    if V > 6.0:
        warnings.append(
            f"Penstock velocity V={V:.2f} m/s > 6 m/s; consider larger diameter."
        )
    return _ok(h_f_m=h_f, V_m_s=V, Re_approx=Re, f_used=f, warnings=warnings)


def penstock_wall_thickness(
    D: float,
    P_internal_Pa: float,
    sigma_allow_Pa: float = 120e6,
    weld_efficiency: float = 0.85,
    corrosion_mm: float = 2.0,
) -> dict:
    """Minimum penstock wall thickness using thin-wall (Barlow) pressure formula.

    t = P·D / (2·σ_allow·e) + corrosion_allowance

    Parameters
    ----------
    D                : internal diameter (m), > 0
    P_internal_Pa    : design internal pressure (Pa), > 0
                       (usually P_static + water-hammer surge)
    sigma_allow_Pa   : allowable hoop stress (Pa), default 120 MPa (mild steel)
    weld_efficiency  : longitudinal weld joint efficiency, default 0.85
    corrosion_mm     : corrosion allowance added to calculated t (mm), default 2.0

    Returns
    -------
    ok, t_calc_mm, t_total_mm, hoop_stress_check_Pa, warnings
    """
    if D <= 0:
        return _err("D must be > 0")
    if P_internal_Pa <= 0:
        return _err("P_internal_Pa must be > 0")
    if sigma_allow_Pa <= 0:
        return _err("sigma_allow_Pa must be > 0")
    if not (0 < weld_efficiency <= 1.0):
        return _err("weld_efficiency must be in (0, 1]")
    if corrosion_mm < 0:
        return _err("corrosion_mm must be >= 0")

    t_calc_m = P_internal_Pa * D / (2.0 * sigma_allow_Pa * weld_efficiency)
    t_calc_mm = t_calc_m * 1000.0
    t_total_mm = t_calc_mm + corrosion_mm
    t_total_m = t_total_mm / 1000.0

    # Thin-wall validity check: D/t > 20
    warnings: list[str] = []
    if D / t_total_m < 20.0:
        warnings.append(
            f"D/t = {D/t_total_m:.1f} < 20; thin-wall assumption may not be valid. "
            "Use thick-wall Lamé equations."
        )
    # Minimum practical thickness
    if t_total_mm < 6.0:
        warnings.append(
            f"Calculated wall thickness {t_total_mm:.2f} mm is < 6 mm; "
            "adopt 6 mm as practical minimum."
        )

    hoop_stress = P_internal_Pa * D / (2.0 * t_total_m)
    return _ok(
        t_calc_mm=t_calc_mm,
        t_total_mm=t_total_mm,
        hoop_stress_Pa=hoop_stress,
        D_over_t=D / t_total_m,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 5. Water-hammer: Joukowsky & Allievi
# ---------------------------------------------------------------------------

def water_hammer_joukowsky(
    V: float,
    a_wave: float,
    rho: float = _RHO_WATER,
) -> dict:
    """Joukowsky (rapid valve closure) water-hammer pressure rise.

    ΔP = ρ·a·ΔV   (Joukowsky equation)

    For instantaneous complete closure: ΔV = V (full velocity change).

    Parameters
    ----------
    V       : initial flow velocity (m/s), > 0
    a_wave  : acoustic wave speed in pipe (m/s), typical 800–1400 m/s
    rho     : water density (kg/m³), default 1000

    Returns
    -------
    ok, dP_Pa, dP_bar, dH_m (head rise), warnings
    """
    if V <= 0:
        return _err("V must be > 0")
    if a_wave <= 0:
        return _err("a_wave must be > 0")
    if rho <= 0:
        return _err("rho must be > 0")

    dP = rho * a_wave * V
    dH = dP / (rho * _G)
    warnings: list[str] = []
    if a_wave < 700:
        warnings.append(
            f"Wave speed a={a_wave:.0f} m/s is low; verify pipe material and "
            "wall thickness (thin-wall HDPE ~300 m/s; steel ~1200 m/s)."
        )
    if dH > 500:
        warnings.append(
            f"Water-hammer head rise dH={dH:.1f} m is very large; "
            "consider slow-closing valve, surge tank, or pressure relief."
        )
    return _ok(dP_Pa=dP, dP_bar=dP / 1e5, dH_m=dH, warnings=warnings)


def water_hammer_allievi(
    H_static: float,
    V: float,
    a_wave: float,
    L: float,
    T_close: float,
    rho: float = _RHO_WATER,
) -> dict:
    """Allievi water-hammer analysis for finite valve closure time.

    The Allievi parameter:
        ρ_a = a·V / (2·g·H_static)     (dimensionless)

    Maximum head rise (Michaud / Allievi approximate):
        For slow closure (T_close > 2L/a, 'slow'):
            ΔH_max ≈ 2·L·V / (g·T_close)   (Michaud formula)
        For rapid closure (T_close ≤ 2L/a, 'fast'):
            ΔH_max = a·V / g                (Joukowsky limit)

    Parameters
    ----------
    H_static : static head (m), > 0
    V        : initial velocity (m/s), > 0
    a_wave   : wave speed (m/s), > 0
    L        : penstock length (m), > 0
    T_close  : valve closure time (s), > 0
    rho      : water density (kg/m³), default 1000

    Returns
    -------
    ok, T_critical_s, regime, dH_max_m, H_total_max_m,
    allievi_rho, overpressure_ratio, warnings
    """
    if H_static <= 0:
        return _err("H_static must be > 0")
    if V <= 0:
        return _err("V must be > 0")
    if a_wave <= 0:
        return _err("a_wave must be > 0")
    if L <= 0:
        return _err("L must be > 0")
    if T_close <= 0:
        return _err("T_close must be > 0")
    if rho <= 0:
        return _err("rho must be > 0")

    T_crit = 2.0 * L / a_wave  # critical closure time (s)
    allievi_rho = a_wave * V / (2.0 * _G * H_static)

    if T_close <= T_crit:
        regime = "rapid"
        dH_max = a_wave * V / _G  # Joukowsky limit (full pressure rise)
    else:
        regime = "slow"
        dH_max = 2.0 * L * V / (_G * T_close)  # Michaud formula

    H_total = H_static + dH_max
    overpressure_ratio = dH_max / H_static

    warnings: list[str] = []
    if overpressure_ratio > 0.5:
        warnings.append(
            f"Water-hammer overpressure ΔH/H_static={overpressure_ratio:.2f} > 0.5 "
            f"({overpressure_ratio*100:.0f}%); surge protection strongly recommended."
        )
    if regime == "rapid" and T_close < 5.0:
        warnings.append(
            f"Valve closure time T_close={T_close:.1f} s is in rapid regime "
            f"(T_crit={T_crit:.1f} s); use slow-closing actuator (T > {T_crit*1.5:.0f} s)."
        )

    return _ok(
        T_critical_s=T_crit,
        regime=regime,
        dH_max_m=dH_max,
        H_total_max_m=H_total,
        allievi_rho=allievi_rho,
        overpressure_ratio=overpressure_ratio,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 6. Surge-tank sizing (simple cylindrical, constant-area)
# ---------------------------------------------------------------------------

def surge_tank_area(
    Q: float,
    a_wave: float,
    L: float,
    H_net: float,
    D_penstock: float,
    max_upsurge_m: float | None = None,
) -> dict:
    """Size a simple (cylindrical, constant-area) surge tank.

    The tank cross-section area required to limit the upsurge to a specified
    value is derived from the Thoma stability criterion and the oscillation
    period:

    Thoma minimum area:
        A_T = L·A_pipe / (2·f_D·H_net)
        where f_D ≈ Darcy friction factor (≈ 0.015) and A_pipe is penstock area.
        This is the minimum for stable oscillations.

    If max_upsurge_m is given, a simplified energy-balance area is also computed:
        A_surge = Q² / (2·g·max_upsurge_m)

    Parameters
    ----------
    Q               : design flow (m³/s), > 0
    a_wave          : wave speed (m/s), > 0
    L               : tunnel/penstock length upstream of surge tank (m), > 0
    H_net           : net head (m), > 0
    D_penstock      : penstock internal diameter (m), > 0
    max_upsurge_m   : allowable upsurge above reservoir level (m), optional

    Returns
    -------
    ok, A_thoma_m2, D_thoma_m, oscillation_period_s, A_energy_m2 (if max_upsurge given),
    warnings
    """
    if Q <= 0:
        return _err("Q must be > 0")
    if a_wave <= 0:
        return _err("a_wave must be > 0")
    if L <= 0:
        return _err("L must be > 0")
    if H_net <= 0:
        return _err("H_net must be > 0")
    if D_penstock <= 0:
        return _err("D_penstock must be > 0")

    A_pipe = math.pi * D_penstock ** 2 / 4.0
    f_D = 0.015  # representative Darcy friction factor

    # Thoma criterion: A_T > A_pipe·L / (2·H_f_total) — use simplified form
    # with H_friction ≈ f_D * L/D * V²/(2g) evaluated at design V
    V = Q / A_pipe
    H_f = f_D * L / D_penstock * V ** 2 / (2.0 * _G)
    H_f_eff = max(H_f, 0.01 * H_net)  # at least 1% of H_net

    A_thoma = A_pipe * L / (2.0 * H_f_eff)
    D_thoma = math.sqrt(4.0 * A_thoma / math.pi)

    # Natural period of mass oscillation in surge tank
    T_osc = 2.0 * math.pi * math.sqrt(L * A_pipe / (_G * A_thoma))

    warnings: list[str] = []
    result: dict = _ok(
        A_thoma_m2=A_thoma,
        D_thoma_m=D_thoma,
        oscillation_period_s=T_osc,
        warnings=warnings,
    )

    if max_upsurge_m is not None:
        if max_upsurge_m <= 0:
            return _err("max_upsurge_m must be > 0")
        # Energy-balance estimate for upsurge: A_surge = Q²/(2g·z_max)
        A_energy = Q ** 2 / (2.0 * _G * max_upsurge_m)
        result["A_energy_m2"] = A_energy
        result["D_energy_m"] = math.sqrt(4.0 * A_energy / math.pi)
        # Design uses the larger of Thoma and energy-balance areas
        A_design = max(A_thoma, A_energy)
        result["A_design_m2"] = A_design
        result["D_design_m"] = math.sqrt(4.0 * A_design / math.pi)

    if A_thoma > 500:
        warnings.append(
            f"Thoma surge-tank area {A_thoma:.1f} m² is very large; "
            "consider differential or closed surge tank."
        )

    return result


# ---------------------------------------------------------------------------
# 7. Draft-tube & cavitation (Thoma sigma vs critical sigma)
# ---------------------------------------------------------------------------

def thoma_cavitation(
    H_net: float,
    H_s: float,
    turbine_type: str = "Francis",
    n_rpm: float | None = None,
    Q: float | None = None,
    P_vapor_Pa: float = 2338.0,
    P_atm_Pa: float = 101325.0,
    rho: float = _RHO_WATER,
    elevation_m: float = 0.0,
) -> dict:
    """Draft-tube cavitation analysis using Thoma cavitation number.

    Plant sigma (available):
        σ_plant = (H_atm − H_vapor − H_s) / H_net

    where:
        H_atm   = P_atm / (ρ·g)  adjusted for site elevation
        H_vapor = P_vapor / (ρ·g)
        H_s     = draft head (m), positive = runner above tailwater,
                  negative = runner submerged

    Critical sigma (Thoma, empirical, Gordon 1999 / IEC 60193):
        σ_crit ≈ 6.55e-6 × Ns^2.5    (SI Ns = dimensionless specific speed)
        or if Ns not available, falls back to turbine-type typical:
            Francis:  0.05–0.30  (σ_crit ≈ 0.10 at mid-range Ns)
            Kaplan:   0.20–0.60
            Propeller: 0.40–1.00
            Pelton:   not subject to draft-tube cavitation

    Cavitation risk if σ_plant < σ_crit.

    Parameters
    ----------
    H_net        : net head (m), > 0
    H_s          : draft head / setting height (m); positive above tailwater
    turbine_type : Pelton/Francis/Kaplan/Bulb/Crossflow/Turgo
    n_rpm        : runner speed (rpm), optional (improves σ_crit estimate)
    Q            : flow (m³/s), optional (with n_rpm gives Ns → better σ_crit)
    P_vapor_Pa   : vapour pressure (Pa), default 2338 (water 20°C)
    P_atm_Pa     : atmospheric pressure at site (Pa), default 101325
    rho          : water density (kg/m³), default 1000
    elevation_m  : site elevation (m a.s.l.) — adjusts P_atm if P_atm_Pa not overridden

    Returns
    -------
    ok, sigma_plant, sigma_crit, cavitation_risk, margin,
    H_atm_m, H_vapor_m, warnings
    """
    if H_net <= 0:
        return _err("H_net must be > 0")
    if rho <= 0:
        return _err("rho must be > 0")
    if P_atm_Pa <= P_vapor_Pa:
        return _err("P_atm_Pa must be > P_vapor_Pa")

    warnings: list[str] = []

    # Correct atmospheric pressure for elevation (barometric formula, -11.3 Pa/m)
    P_atm_site = P_atm_Pa * math.exp(-elevation_m / 8434.5)
    H_atm = P_atm_site / (rho * _G)
    H_vapor = P_vapor_Pa / (rho * _G)

    sigma_plant = (H_atm - H_vapor - H_s) / H_net

    # Estimate critical sigma
    sigma_crit: float
    if n_rpm is not None and Q is not None and n_rpm > 0 and Q > 0:
        Ns = _specific_speed_si(n_rpm, Q, H_net)
        # Gordon (1999) empirical fit:  σ_crit ≈ 6.55e-6 × Ns^2.5
        sigma_crit = 6.55e-6 * Ns ** 2.5
        sigma_crit = max(sigma_crit, 0.02)  # floor
    else:
        _sigma_defaults = {
            "pelton": 0.01,       # not a draft-tube concern
            "turgo": 0.05,
            "crossflow": 0.05,
            "francis": 0.10,
            "kaplan": 0.35,
            "bulb": 0.45,
        }
        sigma_crit = _sigma_defaults.get(turbine_type.lower(), 0.10)
        Ns = None

    cavitation_risk = sigma_plant < sigma_crit
    margin = sigma_plant - sigma_crit

    if cavitation_risk:
        warnings.append(
            f"CAVITATION RISK: σ_plant={sigma_plant:.4f} < σ_crit={sigma_crit:.4f}. "
            "Lower the runner (reduce H_s) or choose a higher-sigma turbine."
        )
    if H_s > 6.0:
        warnings.append(
            f"Draft head H_s={H_s:.1f} m > 6 m is high for most reaction turbines; "
            "cavitation risk increases significantly."
        )

    result = _ok(
        sigma_plant=sigma_plant,
        sigma_crit=sigma_crit,
        cavitation_risk=cavitation_risk,
        margin=margin,
        H_atm_m=H_atm,
        H_vapor_m=H_vapor,
        H_s_m=H_s,
        warnings=warnings,
    )
    if Ns is not None:
        result["Ns"] = Ns
    return result


# ---------------------------------------------------------------------------
# 8. Runaway speed
# ---------------------------------------------------------------------------

def runaway_speed(
    n_rpm: float,
    turbine_type: str = "Francis",
) -> dict:
    """Estimate runaway (no-load, maximum) speed from normal operating speed.

    Runaway speed occurs on sudden load rejection; the governor fails to close
    the wicket gates fast enough.  Empirical multipliers (Warnick 1984):

        Pelton:    1.7–1.9 × n_rated  (use 1.8)
        Francis:   1.6–2.2 × n_rated  (use 1.8)
        Kaplan:    2.0–2.7 × n_rated  (use 2.3)
        Crossflow: 1.8–2.0 × n_rated  (use 1.9)
        Turgo:     1.7–1.9 × n_rated  (use 1.8)
        Bulb:      2.0–2.5 × n_rated  (use 2.2)

    Parameters
    ----------
    n_rpm         : rated runner speed (rpm), > 0
    turbine_type  : turbine type string

    Returns
    -------
    ok, n_runaway_rpm, runaway_factor, warnings
    """
    if n_rpm <= 0:
        return _err("n_rpm must be > 0")

    _factors = {
        "pelton": 1.8,
        "turgo": 1.8,
        "crossflow": 1.9,
        "francis": 1.8,
        "kaplan": 2.3,
        "bulb": 2.2,
    }
    key = turbine_type.lower()
    if key not in _factors:
        return _err(
            f"turbine_type '{turbine_type}' not recognised. "
            "Use one of: Pelton, Turgo, Crossflow, Francis, Kaplan, Bulb."
        )

    factor = _factors[key]
    n_runaway = n_rpm * factor
    warnings: list[str] = []
    warnings.append(
        f"Runaway speed {n_runaway:.0f} rpm ({factor:.1f}× rated); "
        "all rotating components (generator, shaft, runner) must be rated for "
        "this speed. Verify with turbine manufacturer."
    )
    return _ok(
        n_runaway_rpm=n_runaway,
        runaway_factor=factor,
        n_rated_rpm=n_rpm,
        turbine_type=turbine_type,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 9. Flow-duration curve → annual energy, capacity factor, plant factor
# ---------------------------------------------------------------------------

def flow_duration_energy(
    flow_fractions: list[float],
    Q_design: float,
    H_net: float,
    eta: float = 0.88,
    rho: float = _RHO_WATER,
    hours_per_year: float = 8760.0,
) -> dict:
    """Annual energy from a discretised flow-duration curve (FDC).

    The FDC is provided as a list of flow fractions (Q/Q_design) for equal
    time intervals.  Flows > 1.0 (above design flow) are capped at Q_design
    (excess spills).  Flows ≤ 0 produce no power.

    E_annual = Σ_i [P_i × Δt]   where Δt = hours_per_year / n_intervals

    Capacity factor   = E_annual / (P_installed × hours_per_year)
    Plant factor      = E_actual / E_potential_at_design_flow_all_year

    Parameters
    ----------
    flow_fractions  : list of Q_i / Q_design values (dimensionless), n ≥ 2
    Q_design        : design (installed) flow (m³/s), > 0
    H_net           : net head (m), > 0  (assumed constant — run-of-river approx)
    eta             : overall efficiency, default 0.88
    rho             : water density (kg/m³), default 1000
    hours_per_year  : hours in one year, default 8760

    Returns
    -------
    ok, E_annual_MWh, P_installed_kW, capacity_factor, plant_factor,
    hours_generating, spill_fraction, warnings
    """
    if Q_design <= 0:
        return _err("Q_design must be > 0")
    if H_net <= 0:
        return _err("H_net must be > 0")
    if not (0 < eta <= 1.0):
        return _err("eta must be in (0, 1]")
    if rho <= 0:
        return _err("rho must be > 0")
    if len(flow_fractions) < 2:
        return _err("flow_fractions must have at least 2 entries")

    n = len(flow_fractions)
    dt_h = hours_per_year / n

    P_installed_W = rho * _G * Q_design * H_net * eta  # at design flow
    E_total_Wh = 0.0
    hours_gen = 0.0
    spill_intervals = 0

    for frac in flow_fractions:
        if frac <= 0:
            continue
        Q_i = Q_design * frac
        if frac > 1.0:
            Q_i = Q_design  # cap at design flow; excess spills
            spill_intervals += 1
        P_i = rho * _G * Q_i * H_net * eta
        E_total_Wh += P_i * dt_h
        hours_gen += dt_h

    E_annual_Wh = E_total_Wh
    E_annual_MWh = E_annual_Wh / 1e6

    capacity_factor = E_annual_Wh / (P_installed_W * hours_per_year) if P_installed_W > 0 else 0.0
    # Plant factor = E_annual / E_if_always_at_design_flow
    E_full_year = P_installed_W * hours_per_year
    plant_factor = E_annual_Wh / E_full_year if E_full_year > 0 else 0.0
    spill_fraction = spill_intervals / n

    warnings: list[str] = []
    if capacity_factor < 0.30:
        warnings.append(
            f"Capacity factor {capacity_factor:.2%} is low; "
            "consider smaller installed capacity to improve economics."
        )
    if spill_fraction > 0.10:
        warnings.append(
            f"Spill fraction {spill_fraction:.1%}; "
            "significant flow is above design Q — consider larger turbine."
        )

    return _ok(
        E_annual_MWh=E_annual_MWh,
        E_annual_GWh=E_annual_MWh / 1e3,
        P_installed_kW=P_installed_W / 1e3,
        P_installed_MW=P_installed_W / 1e6,
        capacity_factor=capacity_factor,
        plant_factor=plant_factor,
        hours_generating=hours_gen,
        spill_fraction=spill_fraction,
        n_intervals=n,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 10. Pelton jet & bucket sizing
# ---------------------------------------------------------------------------

def pelton_jet_sizing(
    H_net: float,
    Q: float,
    n_jets: int = 1,
    Cv: float = 0.97,
    D_runner_m: float | None = None,
    rho: float = _RHO_WATER,
) -> dict:
    """Size Pelton turbine jets and bucket parameters.

    Jet velocity:       V_jet = Cv × √(2·g·H_net)
    Jet area per jet:   A_jet = Q / (n_jets × V_jet)
    Jet diameter:       d_jet = √(4·A_jet / π)

    Bucket width (empirical): B ≈ 3.2 × d_jet  (Warnick)
    Bucket pitch (empirical): t ≈ 0.9 × d_jet  (approx, runner dependent)

    Optimal runner-to-jet velocity ratio:  u/V_jet ≈ 0.46
    Optimal runner tangential speed:       u_opt = 0.46 × V_jet

    If D_runner_m is given, optimal n_rpm is also computed:
        n_opt = 60·u_opt / (π·D_runner)

    Parameters
    ----------
    H_net       : net head (m), > 0
    Q           : total flow (m³/s), > 0
    n_jets      : number of jets, default 1 (max 6 for large Peltons)
    Cv          : velocity coefficient (default 0.97)
    D_runner_m  : runner pitch diameter (m), optional
    rho         : water density (kg/m³), default 1000

    Returns
    -------
    ok, V_jet_m_s, d_jet_m, A_jet_m2, B_bucket_m, u_opt_m_s,
    n_opt_rpm (if D_runner given), P_theoretical_W, warnings
    """
    if H_net <= 0:
        return _err("H_net must be > 0")
    if Q <= 0:
        return _err("Q must be > 0")
    if n_jets < 1 or n_jets > 6:
        return _err("n_jets must be 1–6")
    if not (0.5 < Cv <= 1.0):
        return _err("Cv must be in (0.5, 1.0]")

    V_jet = Cv * math.sqrt(2.0 * _G * H_net)
    A_jet = Q / (n_jets * V_jet)
    d_jet = math.sqrt(4.0 * A_jet / math.pi)
    B_bucket = 3.2 * d_jet  # empirical Warnick multiplier
    u_opt = 0.46 * V_jet    # optimal runner tangential speed

    P_theoretical = rho * _G * Q * H_net  # hydraulic power (η=1)

    warnings: list[str] = []
    if d_jet > 0.3:
        warnings.append(
            f"Jet diameter d_jet={d_jet*1000:.0f} mm is large; "
            "consider more jets or checking design flow."
        )
    result = _ok(
        V_jet_m_s=V_jet,
        d_jet_m=d_jet,
        d_jet_mm=d_jet * 1000.0,
        A_jet_m2=A_jet,
        B_bucket_m=B_bucket,
        B_bucket_mm=B_bucket * 1000.0,
        u_opt_m_s=u_opt,
        P_theoretical_W=P_theoretical,
        warnings=warnings,
    )
    if D_runner_m is not None:
        if D_runner_m <= 0:
            return _err("D_runner_m must be > 0")
        n_opt = 60.0 * u_opt / (math.pi * D_runner_m)
        result["n_opt_rpm"] = n_opt
        result["D_runner_m"] = D_runner_m
        # Check jet-to-runner diameter ratio (should be ≈ 0.05–0.20)
        ratio = d_jet / D_runner_m
        result["jet_runner_ratio"] = ratio
        if ratio > 0.25:
            warnings.append(
                f"d_jet/D_runner = {ratio:.3f} > 0.25; runner diameter may be too small."
            )
    return result


# ---------------------------------------------------------------------------
# 11. Micro-hydro quick sizing
# ---------------------------------------------------------------------------

def micro_hydro_quick(
    H_gross: float,
    Q: float,
    penstock_length: float = 0.0,
    eta_overall: float = 0.70,
    penstock_D: float | None = None,
    rho: float = _RHO_WATER,
) -> dict:
    """Quick-sizing utility for micro-hydro plants (< 100 kW).

    Estimates:
    1. Friction head loss (if penstock_length > 0 and D given or auto-sized)
    2. Net head
    3. Shaft power P = ρ·g·Q·H_net·η
    4. Turbine type recommendation
    5. Penstock diameter (economic velocity 2.5 m/s for micro-hydro)

    Parameters
    ----------
    H_gross         : gross (total available) head (m), > 0
    Q               : design flow (m³/s), > 0
    penstock_length : penstock length (m), default 0 (neglects friction)
    eta_overall     : overall efficiency (turbine+generator+transmission),
                      default 0.70 (micro-hydro)
    penstock_D      : penstock internal diameter (m), optional; auto-sized if None
    rho             : water density (kg/m³), default 1000

    Returns
    -------
    ok, H_gross_m, H_friction_m, H_net_m, P_shaft_kW, turbine_type,
    D_penstock_m, warnings
    """
    if H_gross <= 0:
        return _err("H_gross must be > 0")
    if Q <= 0:
        return _err("Q must be > 0")
    if not (0 < eta_overall <= 1.0):
        return _err("eta_overall must be in (0, 1]")

    warnings: list[str] = []

    # Size penstock if not given
    D_pen: float
    if penstock_D is None:
        res_d = penstock_diameter(Q, V_economic=2.5)
        D_pen = res_d["D_m"]
    else:
        if penstock_D <= 0:
            return _err("penstock_D must be > 0")
        D_pen = penstock_D

    # Friction head loss
    H_f = 0.0
    if penstock_length > 0:
        res_f = penstock_friction_loss(Q, D_pen, penstock_length, f=0.02)
        if res_f["ok"]:
            H_f = res_f["h_f_m"]
            warnings.extend(res_f["warnings"])
        else:
            warnings.append(f"Could not compute friction loss: {res_f.get('reason')}")

    H_net = H_gross - H_f
    if H_net <= 0:
        return _err(
            f"Net head is non-positive (H_net={H_net:.2f} m); "
            "reduce penstock length, increase diameter, or increase H_gross."
        )

    P_shaft_W = rho * _G * Q * H_net * eta_overall
    P_shaft_kW = P_shaft_W / 1e3

    # Turbine type
    res_t = turbine_type_selection(H_net, Q)
    turbine = res_t.get("turbine_type", "Unknown")
    warnings.extend(res_t.get("warnings", []))

    if P_shaft_kW > 100:
        warnings.append(
            f"Estimated power {P_shaft_kW:.1f} kW > 100 kW; "
            "this is no longer micro-hydro — use detailed plant design."
        )

    return _ok(
        H_gross_m=H_gross,
        H_friction_m=H_f,
        H_net_m=H_net,
        P_shaft_W=P_shaft_W,
        P_shaft_kW=P_shaft_kW,
        turbine_type=turbine,
        D_penstock_m=D_pen,
        eta_overall=eta_overall,
        warnings=warnings,
    )
