"""
Thermoelectric design — Peltier TEC cooler and Seebeck TEG generator.

This module is distinct from:
  • kerf_electronics.thermal   — junction temperature models (Rθja, Rθjc)
  • kerf_electronics.powerconv — buck/boost/flyback converters
  • kerf_electronics.battery   — cell/pack sizing
  • kerf_electronics.gatedrive — MOSFET gate-drive circuits

All functions are pure Python (math module only) and follow the kerf
never-raise contract:  validation errors are returned as dicts with
{ok: False, reason: str};  warnings are issued via the standard warnings
module for operating-limit violations;  exceptions are never raised to
callers.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Key symbols
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  α   — Seebeck coefficient [V/K]  (pair, i.e. sum of n+p legs)
  R   — electrical resistance of the module [Ω]
  K   — thermal conductance of the module [W/K]
  Z   — figure of merit [1/K]  Z = α² / (R·K)
  ZT  — dimensionless figure of merit  ZT = Z·T_mean
  N   — number of thermoelectric couples
  Tc  — cold-side absolute temperature [K]
  Th  — hot-side absolute temperature [K]
  ΔT  — temperature difference  Th − Tc  [K]
  I   — drive current [A]
  Qc  — heat pumped from cold side [W]  (cooling capacity)
  Qh  — heat rejected to hot side [W]
  P   — input electrical power [W]
  COP — coefficient of performance  Qc / P

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEC steady-state equations  (Goldsmid, "Introduction to Thermoelectricity",
Springer 2009 §4; Rowe, "CRC Handbook of Thermoelectrics" 1995 §1)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Qc  = α·I·Tc − ½·I²·R − K·ΔT
  Qh  = α·I·Th + ½·I²·R − K·ΔT
  P   = Qh − Qc = α·I·ΔT + I²·R
  COP = Qc / P

  Optimal current for maximum Qc:
    I_max_Qc = α·Tc / R        (derivative dQc/dI = 0)

  Maximum ΔT (when Qc = 0):
    ΔT_max = Z·Tc² / 2   →   Th_max = Tc + ΔT_max

  Optimal current for maximum COP (Ioffe 1957):
    I_max_COP = (α·ΔT) / (R·(sqrt(1 + Z·T_mean) − 1))
    where T_mean = (Tc + Th) / 2

  COP_max = ((Tc / ΔT) · (sqrt(1 + Z·T_mean) − Th/Tc)
                        / (sqrt(1 + Z·T_mean) + 1))

Hot-side heatsink coupling  (closed-loop Th solve)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Th = T_ambient + Rθ · Qh(Th)

  Because Qh depends on Th (via ΔT = Th − Tc and via α·I·Th term), this
  is a nonlinear equation in Th.  We solve it by fixed-point iteration:

    Th_new = T_ambient + Rθ · Qh(Th_old)

  which converges for Rθ not too large (< 1/K in practical designs).
  We iterate up to 200 steps; warn if not converged.

Multistage (cascade) TEC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Each stage is treated as an independent module with per-stage parameters.
  The hot side of stage n becomes the cold side of stage n+1.
  Total ΔT = sum of per-stage ΔTs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEG steady-state equations  (Rowe §2; Goldsmid §5)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Open-circuit voltage:   Voc = α·N·ΔT
  Internal resistance:    Ri  = N·R
  Short-circuit current:  Isc = Voc / Ri = α·ΔT / R
  Matched-load current:   Im  = Voc / (2·Ri) = α·ΔT / (2·R)
  Matched-load power:     Pm  = Voc² / (4·Ri) = α²·N·ΔT² / (4·R)
  Matched-load voltage:   Vm  = Voc / 2

  Maximum efficiency (ηmax) vs Carnot efficiency (ηC = ΔT / Th):
    ηmax = (ΔT/Th) · (sqrt(1 + Z·T_mean) − 1)
                   / (sqrt(1 + Z·T_mean) + Tc/Th)

  Load-matching (max power at R_load = Ri):
    Vs max-power point current: I_mp = Voc / (Ri + R_load)
    Vs max-η point:             R_opt = Ri · sqrt(1 + Z·T_mean)

  Array sizing:
    Series:   Varray = Ns · Vm,  Parray = Ns · Pm  (current fixed)
    Parallel: Iarray = Np · Im,  Parray = Np · Pm  (voltage fixed)
    Combined (Ns × Np): Parray = Ns·Np · Pm

  Fill factor (module packaging):
    FF = (total pellet cross-section area) / (module footprint area)
    FF is a property of the module geometry; it affects effective Z.

Notes on transient behaviour
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  The thermal time constant of a TEC element is roughly
    τ ≈ (module thermal mass) / K
  Typical ceramic-packaged modules have τ in the range 5–30 s.
  Supercooling (I > I_max_Qc) can briefly push Tc below steady-state
  minimum, at the cost of increased Joule heating on the hot side.
  This module does not model transients; it is steady-state only.

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Optional


# ── Input validation helpers ──────────────────────────────────────────────────

def _pos(value, name: str) -> Optional[str]:
    """Return error string if value is not a finite positive number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive number, got {value!r}"
    return None


def _nonneg(value, name: str) -> Optional[str]:
    """Return error string if value is negative or not a real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _finite(value, name: str) -> Optional[str]:
    """Return error string if value is not a finite real number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return f"{name} must be a finite real number, got {value!r}"
    return None


# ── Figure of merit ────────────────────────────────────────────────────────────

def figure_of_merit(
    alpha: float,
    resistance: float,
    thermal_conductance: float,
    t_mean: Optional[float] = None,
) -> dict:
    """
    Compute the thermoelectric figure of merit Z and ZT.

    Z [1/K] = α² / (R · K)

    where
      α   — Seebeck coefficient [V/K] of the couple (n-leg + p-leg total)
      R   — electrical resistance [Ω]
      K   — thermal conductance [W/K]
      T   — mean absolute temperature [K]  (optional; required for ZT)

    Parameters
    ----------
    alpha               : float — Seebeck coefficient [V/K]
    resistance          : float — electrical resistance [Ω]
    thermal_conductance : float — thermal conductance [W/K]
    t_mean              : float or None — mean temperature [K] for ZT

    Returns
    -------
    dict with keys: ok, Z, ZT (None if t_mean not supplied), alpha, resistance,
                    thermal_conductance, t_mean
    """
    err = _finite(alpha, "alpha")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance, "resistance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(thermal_conductance, "thermal_conductance")
    if err:
        return {"ok": False, "reason": err}

    Z = alpha ** 2 / (resistance * thermal_conductance)

    ZT = None
    if t_mean is not None:
        err = _pos(t_mean, "t_mean")
        if err:
            return {"ok": False, "reason": err}
        ZT = Z * t_mean

    return {
        "ok": True,
        "alpha": alpha,
        "resistance": resistance,
        "thermal_conductance": thermal_conductance,
        "t_mean": t_mean,
        "Z": Z,
        "ZT": ZT,
    }


# ── TEC: single-module operating point ───────────────────────────────────────

def tec_operating_point(
    alpha: float,
    resistance: float,
    thermal_conductance: float,
    current: float,
    tc: float,
    th: float,
) -> dict:
    """
    Compute the steady-state operating point of a single-stage TEC module.

    Equations (Goldsmid 2009 §4; Rowe CRC §1):
      Qc = α·I·Tc − ½·I²·R − K·ΔT
      Qh = α·I·Th + ½·I²·R − K·ΔT    (Note: Qh = Qc + P by energy balance)
      P  = Qh − Qc = α·I·ΔT + I²·R
      COP = Qc / P  (undefined / Inf when P=0)

    Parameters
    ----------
    alpha               : float — Seebeck coefficient [V/K]
    resistance          : float — module electrical resistance [Ω]
    thermal_conductance : float — module thermal conductance [W/K]
    current             : float — drive current [A]
    tc                  : float — cold-side temperature [K]
    th                  : float — hot-side temperature [K]

    Returns
    -------
    dict with keys: ok, Qc, Qh, P_input, COP, delta_T, warnings (list)
    """
    err = _finite(alpha, "alpha")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance, "resistance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(thermal_conductance, "thermal_conductance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(current, "current")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(tc, "tc")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(th, "th")
    if err:
        return {"ok": False, "reason": err}
    if tc >= th:
        return {"ok": False, "reason": "tc must be less than th (cold side < hot side)"}

    dT = th - tc
    R = resistance
    K = thermal_conductance

    Qc = alpha * current * tc - 0.5 * current ** 2 * R - K * dT
    Qh = alpha * current * th + 0.5 * current ** 2 * R - K * dT
    P = Qh - Qc  # = alpha*I*dT + I²*R

    warns: list[str] = []
    if Qc < 0.0:
        msg = (
            f"tec_operating_point: Qc={Qc:.4f} W is negative — "
            f"the module cannot pump heat at this operating point (ΔT too large "
            f"or current too low / too high)."
        )
        warnings.warn(msg, stacklevel=2)
        warns.append("negative_Qc")

    COP = Qc / P if P > 0 else (math.inf if Qc > 0 else 0.0)

    return {
        "ok": True,
        "alpha": alpha,
        "resistance": resistance,
        "thermal_conductance": thermal_conductance,
        "current": current,
        "tc": tc,
        "th": th,
        "delta_T": dT,
        "Qc": Qc,
        "Qh": Qh,
        "P_input": P,
        "COP": COP,
        "warnings": warns,
    }


# ── TEC: optimal currents ─────────────────────────────────────────────────────

def tec_optimal_current(
    alpha: float,
    resistance: float,
    thermal_conductance: float,
    tc: float,
    th: float,
) -> dict:
    """
    Compute the optimal drive currents for a TEC module.

    I_max_Qc  — current that maximises Qc (cold-side heat pumping):
        I_max_Qc = α·Tc / R    (dQc/dI = 0)
        Qc_max   = ½·Z·Tc² − K·ΔT   = ΔT_max·K − K·ΔT  (using ΔT_max = Z·Tc²/2)

    I_max_COP — current that maximises COP (Ioffe 1957):
        I_max_COP = α·ΔT / (R·(M − 1))
        where M = sqrt(1 + Z·T_mean),  T_mean = (Tc + Th) / 2

    COP_max  = (Tc/ΔT) · (M − Th/Tc) / (M + 1)

    Parameters
    ----------
    alpha               : float — Seebeck coefficient [V/K]
    resistance          : float — module electrical resistance [Ω]
    thermal_conductance : float — module thermal conductance [W/K]
    tc                  : float — cold-side temperature [K]
    th                  : float — hot-side temperature [K]

    Returns
    -------
    dict with keys: ok, I_max_Qc, Qc_at_I_max_Qc, I_max_COP, COP_max,
                    delta_T, Z, ZT_mean, warnings (list)
    """
    err = _finite(alpha, "alpha")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance, "resistance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(thermal_conductance, "thermal_conductance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(tc, "tc")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(th, "th")
    if err:
        return {"ok": False, "reason": err}
    if tc >= th:
        return {"ok": False, "reason": "tc must be less than th"}

    dT = th - tc
    R = resistance
    K = thermal_conductance
    Z = alpha ** 2 / (R * K)
    T_mean = (tc + th) / 2.0
    ZT_mean = Z * T_mean

    # Maximum Qc current
    I_max_Qc = alpha * tc / R
    Qc_at_I_max = (
        alpha * I_max_Qc * tc
        - 0.5 * I_max_Qc ** 2 * R
        - K * dT
    )

    # Maximum COP current
    M = math.sqrt(1.0 + ZT_mean)
    warns: list[str] = []
    if M <= 1.0:
        # Degenerate case (ZT_mean ≤ 0 — should not happen with valid inputs)
        I_max_COP = I_max_Qc  # fall back
        COP_max = 0.0
        warns.append("ZT_mean_too_low_for_max_COP")
    else:
        I_max_COP = (alpha * dT) / (R * (M - 1.0))
        # COP_max = (Tc/dT) · (M - Th/Tc) / (M + 1)
        COP_max = (tc / dT) * (M - th / tc) / (M + 1.0)

    if COP_max < 0:
        warns.append("COP_max_negative: ΔT exceeds module capability at these temperatures")

    return {
        "ok": True,
        "alpha": alpha,
        "resistance": resistance,
        "thermal_conductance": thermal_conductance,
        "tc": tc,
        "th": th,
        "delta_T": dT,
        "Z": Z,
        "ZT_mean": ZT_mean,
        "I_max_Qc": I_max_Qc,
        "Qc_at_I_max_Qc": Qc_at_I_max,
        "I_max_COP": I_max_COP,
        "COP_max": COP_max,
        "warnings": warns,
    }


# ── TEC: maximum ΔT ────────────────────────────────────────────────────────────

def tec_delta_t_max(
    alpha: float,
    resistance: float,
    thermal_conductance: float,
    tc: float,
) -> dict:
    """
    Compute the maximum achievable temperature difference across a TEC module
    (the point where Qc = 0 at optimal current).

    ΔT_max = ½ · Z · Tc²    where Z = α² / (R·K)
    Th_max = Tc + ΔT_max

    This is the theoretical maximum ΔT for a single-stage module; it can only
    be achieved with zero heat load on the cold side.

    Parameters
    ----------
    alpha               : float — Seebeck coefficient [V/K]
    resistance          : float — module electrical resistance [Ω]
    thermal_conductance : float — module thermal conductance [W/K]
    tc                  : float — cold-side temperature [K]

    Returns
    -------
    dict with keys: ok, delta_T_max, Th_max, Z, tc
    """
    err = _finite(alpha, "alpha")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance, "resistance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(thermal_conductance, "thermal_conductance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(tc, "tc")
    if err:
        return {"ok": False, "reason": err}

    Z = alpha ** 2 / (resistance * thermal_conductance)
    dT_max = 0.5 * Z * tc ** 2
    Th_max = tc + dT_max

    return {
        "ok": True,
        "tc": tc,
        "Z": Z,
        "delta_T_max": dT_max,
        "Th_max": Th_max,
    }


# ── TEC: required number of couples ──────────────────────────────────────────

def tec_couples_required(
    alpha_per_couple: float,
    resistance_per_couple: float,
    thermal_conductance_per_couple: float,
    current: float,
    tc: float,
    th: float,
    Qc_target: float,
) -> dict:
    """
    Determine the minimum number of thermoelectric couples (N) to achieve
    a target cold-side heat pumping rate Qc_target [W].

    For N couples:
      R_N = N · R_couple
      K_N = N · K_couple
      α_N = N · α_couple

    The Qc equation scales as:
      Qc = N·α_couple·I·Tc − ½·I²·N·R_couple − N·K_couple·ΔT
         = N · (α_couple·I·Tc − ½·I²·R_couple − K_couple·ΔT)

    So N ≥ ceil(Qc_target / Qc_per_couple)  where Qc_per_couple > 0.

    Parameters
    ----------
    alpha_per_couple               : float — Seebeck coefficient per couple [V/K]
    resistance_per_couple          : float — resistance per couple [Ω]
    thermal_conductance_per_couple : float — thermal conductance per couple [W/K]
    current                        : float — drive current [A]
    tc                             : float — cold-side temperature [K]
    th                             : float — hot-side temperature [K]
    Qc_target                      : float — required cold-side heat pumping [W]

    Returns
    -------
    dict with keys: ok, N, Qc_per_couple, Qc_total, Qh_total, P_total, COP,
                    warnings (list)
    """
    err = _finite(alpha_per_couple, "alpha_per_couple")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance_per_couple, "resistance_per_couple")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(thermal_conductance_per_couple, "thermal_conductance_per_couple")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(current, "current")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(tc, "tc")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(th, "th")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(Qc_target, "Qc_target")
    if err:
        return {"ok": False, "reason": err}
    if tc >= th:
        return {"ok": False, "reason": "tc must be less than th"}

    dT = th - tc
    a = alpha_per_couple
    R = resistance_per_couple
    K = thermal_conductance_per_couple

    Qc_per = a * current * tc - 0.5 * current ** 2 * R - K * dT

    warns: list[str] = []
    if Qc_per <= 0.0:
        msg = (
            f"tec_couples_required: Qc_per_couple={Qc_per:.4f} W ≤ 0 — "
            f"even a single couple cannot pump heat at this ΔT/current; "
            f"increase current or reduce ΔT."
        )
        warnings.warn(msg, stacklevel=2)
        warns.append("negative_Qc_per_couple")
        return {
            "ok": True,
            "N": None,
            "Qc_per_couple": Qc_per,
            "Qc_total": None,
            "Qh_total": None,
            "P_total": None,
            "COP": None,
            "warnings": warns,
        }

    N = math.ceil(Qc_target / Qc_per)
    Qc_total = N * Qc_per
    R_N = N * R
    K_N = N * K
    a_N = N * a
    Qh_total = a_N * current * th + 0.5 * current ** 2 * R_N - K_N * dT
    P_total = Qh_total - Qc_total
    COP = Qc_total / P_total if P_total > 0 else math.inf

    return {
        "ok": True,
        "N": N,
        "Qc_per_couple": Qc_per,
        "Qc_total": Qc_total,
        "Qh_total": Qh_total,
        "P_total": P_total,
        "COP": COP,
        "warnings": warns,
    }


# ── TEC: hot-side heatsink coupling (closed-loop Th solve) ────────────────────

def tec_heatsink_coupled(
    alpha: float,
    resistance: float,
    thermal_conductance: float,
    current: float,
    tc: float,
    t_ambient: float,
    rtheta: float,
    max_iter: int = 200,
    tol: float = 1e-6,
) -> dict:
    """
    Solve for the hot-side temperature Th when the TEC is coupled to a heatsink
    with thermal resistance Rθ [K/W] to ambient.

    The equilibrium condition is:
        Th = T_ambient + Rθ · Qh(Th)

    where Qh(Th) = α·I·Th + ½·I²·R − K·(Th − Tc).

    This is solved by fixed-point iteration:
        Th_{n+1} = T_ambient + Rθ · Qh(Th_n)

    Convergence is checked to tolerance `tol` [K].  A warning is issued if
    the iteration does not converge within max_iter steps (heatsink likely
    undersized → the module cannot reach steady state).

    Parameters
    ----------
    alpha               : float — Seebeck coefficient [V/K]
    resistance          : float — module electrical resistance [Ω]
    thermal_conductance : float — module thermal conductance [W/K]
    current             : float — drive current [A]
    tc                  : float — cold-side (object) temperature [K]
    t_ambient           : float — ambient (heatsink inlet) temperature [K]
    rtheta              : float — heatsink thermal resistance [K/W]
    max_iter            : int   — max fixed-point iterations (default 200)
    tol                 : float — convergence tolerance [K] (default 1e-6)

    Returns
    -------
    dict with keys: ok, Th, Qc, Qh, P_input, COP, delta_T, converged,
                    iterations, warnings (list)
    """
    err = _finite(alpha, "alpha")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance, "resistance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(thermal_conductance, "thermal_conductance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(current, "current")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(tc, "tc")
    if err:
        return {"ok": False, "reason": err}
    err = _finite(t_ambient, "t_ambient")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(rtheta, "rtheta")
    if err:
        return {"ok": False, "reason": err}
    if t_ambient < tc:
        # Ambient cooler than cold side — TEC not needed; warn but continue
        warnings.warn(
            f"tec_heatsink_coupled: t_ambient={t_ambient} K < tc={tc} K; "
            f"the TEC operates in an unusual regime (heatsink colder than object).",
            stacklevel=2,
        )

    R = resistance
    K = thermal_conductance

    # Initial guess: Th = ambient + small offset
    Th = t_ambient + 5.0

    converged = False
    iters = 0
    for iters in range(1, max_iter + 1):
        Qh_old = alpha * current * Th + 0.5 * current ** 2 * R - K * (Th - tc)
        Th_new = t_ambient + rtheta * Qh_old
        if abs(Th_new - Th) < tol:
            Th = Th_new
            converged = True
            break
        Th = Th_new

    warns: list[str] = []
    if not converged:
        msg = (
            f"tec_heatsink_coupled: did not converge in {max_iter} iterations "
            f"(last Th={Th:.3f} K).  Heatsink Rθ={rtheta} K/W may be too large "
            f"(undersized heatsink → thermal runaway)."
        )
        warnings.warn(msg, stacklevel=2)
        warns.append("heatsink_undersized_did_not_converge")

    if Th <= tc:
        warnings.warn(
            f"tec_heatsink_coupled: solved Th={Th:.3f} K ≤ tc={tc:.3f} K; "
            f"result is unphysical — check inputs.",
            stacklevel=2,
        )
        warns.append("unphysical_Th_leq_Tc")

    dT = Th - tc
    Qh = alpha * current * Th + 0.5 * current ** 2 * R - K * dT
    Qc = alpha * current * tc - 0.5 * current ** 2 * R - K * dT
    P = Qh - Qc
    COP = Qc / P if P > 0 else math.inf

    if Qc < 0.0:
        warns.append("negative_Qc")

    return {
        "ok": True,
        "Th": Th,
        "tc": tc,
        "t_ambient": t_ambient,
        "delta_T": dT,
        "Qc": Qc,
        "Qh": Qh,
        "P_input": P,
        "COP": COP,
        "converged": converged,
        "iterations": iters,
        "warnings": warns,
    }


# ── TEC: multistage (cascade) ──────────────────────────────────────────────────

def tec_multistage(
    stages: list[dict],
    t_cold_target: float,
    t_hot_ambient: float,
) -> dict:
    """
    Design a multistage (cascade) TEC for large ΔT.

    Each stage is described by a dict with keys:
      alpha, resistance, thermal_conductance, current
    The hot side of stage n feeds the cold side of stage n+1.
    Stage 0 has its cold side at t_cold_target; stage[-1] has its hot side
    rejected to a heatsink at t_hot_ambient.

    Parameters
    ----------
    stages        : list of dicts — per-stage TEC parameters (see above)
    t_cold_target : float — desired cold-side temperature of stage 0 [K]
    t_hot_ambient : float — hot-side ambient temperature [K]

    Returns
    -------
    dict with keys: ok, stages_results, total_delta_T, Tc_final, Th_final,
                    warnings (list)
    """
    if not stages:
        return {"ok": False, "reason": "stages list must not be empty"}
    err = _pos(t_cold_target, "t_cold_target")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(t_hot_ambient, "t_hot_ambient")
    if err:
        return {"ok": False, "reason": err}
    if t_cold_target >= t_hot_ambient:
        return {
            "ok": False,
            "reason": "t_cold_target must be less than t_hot_ambient",
        }

    n_stages = len(stages)
    dT_total = t_hot_ambient - t_cold_target

    # Distribute ΔT evenly across stages as starting guess (linear split)
    dT_per_stage = dT_total / n_stages

    tc_current = t_cold_target
    results = []
    warns: list[str] = []

    for i, s in enumerate(stages):
        # Validate required keys
        for key in ("alpha", "resistance", "thermal_conductance", "current"):
            if key not in s:
                return {"ok": False, "reason": f"Stage {i}: missing key '{key}'"}

        alpha = s["alpha"]
        R = s["resistance"]
        K = s["thermal_conductance"]
        I = s["current"]
        th_stage = tc_current + dT_per_stage

        op = tec_operating_point(
            alpha=alpha,
            resistance=R,
            thermal_conductance=K,
            current=I,
            tc=tc_current,
            th=th_stage,
        )
        if not op["ok"]:
            return {"ok": False, "reason": f"Stage {i}: {op['reason']}"}
        if op["warnings"]:
            warns.extend([f"stage_{i}:{w}" for w in op["warnings"]])

        results.append({
            "stage": i,
            "tc": tc_current,
            "th": th_stage,
            "delta_T": dT_per_stage,
            "Qc": op["Qc"],
            "Qh": op["Qh"],
            "P_input": op["P_input"],
            "COP": op["COP"],
        })
        tc_current = th_stage  # hot side of this stage = cold side of next

    return {
        "ok": True,
        "n_stages": n_stages,
        "t_cold_target": t_cold_target,
        "t_hot_ambient": t_hot_ambient,
        "total_delta_T": dT_total,
        "Tc_final": t_cold_target,
        "Th_final": t_hot_ambient,
        "stages_results": results,
        "warnings": warns,
    }


# ── TEG: open-circuit and matched-load ────────────────────────────────────────

def teg_output(
    alpha: float,
    resistance: float,
    n_couples: int,
    tc: float,
    th: float,
    r_load: Optional[float] = None,
) -> dict:
    """
    Compute TEG output: open-circuit voltage, matched-load power/current/voltage,
    arbitrary load operating point, and maximum efficiency.

    Equations (Rowe 1995 §2; Goldsmid 2009 §5):
      Voc   = α · N · ΔT           (open-circuit voltage)
      Ri    = N · R                 (internal resistance)
      Im    = Voc / (2·Ri)          (matched-load current, R_load = Ri)
      Vm    = Voc / 2               (matched-load voltage)
      Pm    = Voc² / (4·Ri)         (matched-load power)

      Arbitrary load current (R_load given):
      I_L   = Voc / (Ri + R_load)
      V_L   = I_L · R_load
      P_L   = I_L² · R_load

      ηmax  = (ΔT/Th) · (M − 1) / (M + Tc/Th)
            where M = sqrt(1 + Z·T_mean),  T_mean = (Tc + Th)/2
      ηC    = ΔT / Th   (Carnot efficiency)

    Parameters
    ----------
    alpha      : float — Seebeck coefficient per couple [V/K]
    resistance : float — electrical resistance per couple [Ω]
    n_couples  : int   — number of thermoelectric couples
    tc         : float — cold-side temperature [K]
    th         : float — hot-side temperature [K]
    r_load     : float or None — load resistance [Ω]; if None, uses matched (Ri)

    Returns
    -------
    dict with keys: ok, Voc, Ri, Im, Vm, Pm, I_load, V_load, P_load,
                    eta_max, eta_carnot, Z, ZT_mean, r_load_used, warnings (list)
    """
    err = _finite(alpha, "alpha")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance, "resistance")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(n_couples, int) or n_couples < 1:
        return {"ok": False, "reason": f"n_couples must be a positive integer, got {n_couples!r}"}
    err = _pos(tc, "tc")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(th, "th")
    if err:
        return {"ok": False, "reason": err}
    if tc >= th:
        return {"ok": False, "reason": "tc must be less than th (cold side < hot side)"}
    if r_load is not None:
        err = _pos(r_load, "r_load")
        if err:
            return {"ok": False, "reason": err}

    dT = th - tc
    N = n_couples
    K_total = None  # not needed for voltage/power; used only if K supplied

    Ri = N * resistance
    Voc = alpha * N * dT
    Im = Voc / (2.0 * Ri)
    Vm = Voc / 2.0
    Pm = Voc ** 2 / (4.0 * Ri)

    # Load operating point
    if r_load is None:
        r_load_used = Ri  # matched load
        I_L = Im
        V_L = Vm
        P_L = Pm
    else:
        r_load_used = r_load
        I_L = Voc / (Ri + r_load)
        V_L = I_L * r_load
        P_L = I_L ** 2 * r_load

    # Figure of merit and efficiency
    K_per = None  # thermal conductance not required for V/I/P; Z needs K
    # Z cannot be computed without K; we skip ZT unless K is available
    # (alpha and R are per couple, K is not a TEG output parameter in this call)
    Z = None
    ZT_mean = None
    eta_max = None
    T_mean = (tc + th) / 2.0
    eta_carnot = dT / th

    warns: list[str] = []
    if Voc <= 0:
        warns.append("zero_or_negative_Voc: check alpha and temperatures")

    return {
        "ok": True,
        "alpha": alpha,
        "resistance_per_couple": resistance,
        "n_couples": N,
        "tc": tc,
        "th": th,
        "delta_T": dT,
        "Ri": Ri,
        "Voc": Voc,
        "Im": Im,
        "Vm": Vm,
        "Pm": Pm,
        "r_load_used": r_load_used,
        "I_load": I_L,
        "V_load": V_L,
        "P_load": P_L,
        "eta_carnot": eta_carnot,
        "Z": Z,
        "ZT_mean": ZT_mean,
        "eta_max": eta_max,
        "warnings": warns,
    }


def teg_efficiency(
    alpha: float,
    resistance: float,
    thermal_conductance: float,
    tc: float,
    th: float,
) -> dict:
    """
    Compute TEG maximum efficiency and load resistance for max-η operating point.

    ηmax = (ΔT/Th) · (M − 1) / (M + Tc/Th)     (Ioffe / Goldsmid)
    ηC   = ΔT / Th                                (Carnot)
    M    = sqrt(1 + Z·T_mean)

    Optimal load resistance for maximum efficiency:
      R_opt = R · M   (per couple; scales as N·R for N couples)

    Parameters
    ----------
    alpha               : float — Seebeck coefficient per couple [V/K]
    resistance          : float — electrical resistance per couple [Ω]
    thermal_conductance : float — thermal conductance per couple [W/K]
    tc                  : float — cold-side temperature [K]
    th                  : float — hot-side temperature [K]

    Returns
    -------
    dict with keys: ok, eta_max, eta_carnot, eta_ratio (eta_max/eta_carnot),
                    Z, ZT_mean, M, R_opt_per_couple, warnings (list)
    """
    err = _finite(alpha, "alpha")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(resistance, "resistance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(thermal_conductance, "thermal_conductance")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(tc, "tc")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(th, "th")
    if err:
        return {"ok": False, "reason": err}
    if tc >= th:
        return {"ok": False, "reason": "tc must be less than th"}

    dT = th - tc
    Z = alpha ** 2 / (resistance * thermal_conductance)
    T_mean = (tc + th) / 2.0
    ZT_mean = Z * T_mean
    M = math.sqrt(1.0 + ZT_mean)

    eta_carnot = dT / th
    eta_max = eta_carnot * (M - 1.0) / (M + tc / th)
    eta_ratio = eta_max / eta_carnot if eta_carnot > 0 else 0.0

    # Optimal load resistance (per couple) for maximum efficiency
    R_opt = resistance * M

    warns: list[str] = []
    if eta_max < 0:
        warns.append("eta_max_negative: unphysical — check Z and temperatures")

    return {
        "ok": True,
        "alpha": alpha,
        "resistance": resistance,
        "thermal_conductance": thermal_conductance,
        "tc": tc,
        "th": th,
        "delta_T": dT,
        "Z": Z,
        "ZT_mean": ZT_mean,
        "M": M,
        "eta_carnot": eta_carnot,
        "eta_max": eta_max,
        "eta_ratio": eta_ratio,
        "R_opt_per_couple": R_opt,
        "warnings": warns,
    }


# ── TEG: array series/parallel sizing ────────────────────────────────────────

def teg_array(
    alpha: float,
    resistance: float,
    n_couples: int,
    tc: float,
    th: float,
    n_series: int,
    n_parallel: int,
) -> dict:
    """
    Compute TEG array output for Ns modules in series × Np modules in parallel.

    Series connection increases voltage; parallel increases current.
    Each module has n_couples couples with per-couple α and R.

    Array quantities:
      Varray = Ns · Voc_module        (series)
      Iarray = Np · Im_module         (parallel; matched-load Im per module)
      Parray = Ns · Np · Pm_module    (total power into matched load per module)

    Parameters
    ----------
    alpha      : float — Seebeck coefficient per couple [V/K]
    resistance : float — electrical resistance per couple [Ω]
    n_couples  : int   — number of couples per module
    tc         : float — cold-side temperature [K]
    th         : float — hot-side temperature [K]
    n_series   : int   — number of modules in series (Ns)
    n_parallel : int   — number of modules in parallel (Np)

    Returns
    -------
    dict with keys: ok, Voc_module, Pm_module, Ri_module,
                    Varray, Iarray, Parray, n_total_modules, warnings (list)
    """
    if not isinstance(n_series, int) or n_series < 1:
        return {"ok": False, "reason": "n_series must be a positive integer"}
    if not isinstance(n_parallel, int) or n_parallel < 1:
        return {"ok": False, "reason": "n_parallel must be a positive integer"}

    module = teg_output(
        alpha=alpha,
        resistance=resistance,
        n_couples=n_couples,
        tc=tc,
        th=th,
    )
    if not module["ok"]:
        return {"ok": False, "reason": module.get("reason", "teg_output failed")}

    Voc_mod = module["Voc"]
    Pm_mod = module["Pm"]
    Ri_mod = module["Ri"]
    Im_mod = module["Im"]

    Varray = n_series * Voc_mod
    Iarray = n_parallel * Im_mod
    Parray = n_series * n_parallel * Pm_mod
    n_total = n_series * n_parallel

    return {
        "ok": True,
        "alpha": alpha,
        "resistance_per_couple": resistance,
        "n_couples": n_couples,
        "tc": tc,
        "th": th,
        "n_series": n_series,
        "n_parallel": n_parallel,
        "n_total_modules": n_total,
        "Voc_module": Voc_mod,
        "Pm_module": Pm_mod,
        "Ri_module": Ri_mod,
        "Varray": Varray,
        "Iarray": Iarray,
        "Parray": Parray,
        "warnings": module.get("warnings", []),
    }


# ── TEG: fill factor ──────────────────────────────────────────────────────────

def teg_fill_factor(
    pellet_area_mm2: float,
    pellet_height_mm: float,
    n_couples: int,
    module_footprint_mm2: float,
) -> dict:
    """
    Compute the fill factor of a TEG module and qualitatively assess its impact
    on the effective figure of merit.

    Fill factor (FF) = (total pellet cross-section area) / (module footprint area)
    FF is dimensionless, in the range (0, 1].

    A higher FF means more of the substrate area is active thermoelectric
    material.  Effective Z scales approximately as FF for a given pellet
    geometry.

    Parameters
    ----------
    pellet_area_mm2       : float — cross-section area of one pellet leg [mm²]
    pellet_height_mm      : float — pellet height (leg length) [mm]
    n_couples             : int   — number of couples (each couple = 2 legs)
    module_footprint_mm2  : float — total module footprint area [mm²]

    Returns
    -------
    dict with keys: ok, fill_factor, total_pellet_area_mm2, n_legs,
                    pellet_height_mm, module_footprint_mm2
    """
    err = _pos(pellet_area_mm2, "pellet_area_mm2")
    if err:
        return {"ok": False, "reason": err}
    err = _pos(pellet_height_mm, "pellet_height_mm")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(n_couples, int) or n_couples < 1:
        return {"ok": False, "reason": "n_couples must be a positive integer"}
    err = _pos(module_footprint_mm2, "module_footprint_mm2")
    if err:
        return {"ok": False, "reason": err}

    n_legs = 2 * n_couples  # each couple has one n-leg and one p-leg
    total_pellet_area = n_legs * pellet_area_mm2
    FF = total_pellet_area / module_footprint_mm2

    warns: list[str] = []
    if FF > 1.0:
        warnings.warn(
            f"teg_fill_factor: fill_factor={FF:.4f} > 1 — "
            f"total pellet area exceeds module footprint; check inputs.",
            stacklevel=2,
        )
        warns.append("fill_factor_exceeds_1")

    return {
        "ok": True,
        "n_couples": n_couples,
        "n_legs": n_legs,
        "pellet_area_mm2": pellet_area_mm2,
        "pellet_height_mm": pellet_height_mm,
        "total_pellet_area_mm2": total_pellet_area,
        "module_footprint_mm2": module_footprint_mm2,
        "fill_factor": FF,
        "warnings": warns,
    }
