"""
Electronics reliability prediction — MIL-HDBK-217F, Telcordia SR-332, and
related models.

This module is distinct from:
  • kerf_core.reliability   — general systems reliability (different package)
  • kerf_electronics.protection — overvoltage/ESD protection design
  • kerf_electronics.thermal    — thermal resistance / junction temperature

All functions are pure Python (math module only) and follow the kerf
never-raise contract: validation errors are returned as dicts with
{ok: False, reason: str}; over-stress and very-low-MTBF conditions are
flagged via warnings.warn; exceptions are never raised to callers.

References
----------
MIL-HDBK-217F Notice 2 (1995), "Reliability Prediction of Electronic
  Equipment", US DoD.

Telcordia SR-332 Issue 4 (2016), "Reliability Prediction Procedure for
  Electronic Equipment", Ericsson.  (Note: this module provides a
  black-box note only; SR-332 Method I/II require vendor burn-in data not
  available in a pure-Python implementation.)

Coffin-Manson solder-joint fatigue:
  Norris & Landzberg (1969); Solomon (1986).

Peck humidity acceleration:
  Peck, D.S. (1986) "Comprehensive model for humidity testing correlation",
  24th IRPS.

IEC 61709 / IEC TR 62380 for reference temperature (Tref = 40 °C).

Chi-square MTBF confidence bounds:
  MIL-HDBK-781A, Annex A / O'Connor & Kleyner (2012).
"""
from __future__ import annotations

import math
import warnings
from typing import Any

# ── Reference temperature for Arrhenius πT ────────────────────────────────────
_T_REF_K = 313.15  # 40 °C — IEC 61709 reference
_K_B = 8.617333e-5  # Boltzmann constant [eV/K]

# ── MIL-217F environment multipliers πE ───────────────────────────────────────
#   Key: environment code  Value: πE (conservative mid-range of 217F Table 3-1)
_PI_E: dict[str, float] = {
    "GB":  1.0,   # Ground Benign
    "GF":  2.0,   # Ground Fixed
    "GM":  5.0,   # Ground Mobile
    "NS":  4.0,   # Naval Sheltered
    "NU":  6.0,   # Naval Unsheltered
    "AIC": 4.0,   # Airborne Inhabited Cargo
    "AIF": 4.0,   # Airborne Inhabited Fighter
    "AUC": 5.0,   # Airborne Uninhabited Cargo
    "AUF": 6.0,   # Airborne Uninhabited Fighter
    "ARW": 7.0,   # Airborne Rotary Wing
    "SF":  0.5,   # Space Flight
    "MF":  10.0,  # Missile Flight
    "ML":  11.0,  # Missile Launch
    "CL":  14.0,  # Cannon Launch
}

# ── MIL-217F quality factors πQ ───────────────────────────────────────────────
#   Simplified two-tier: MIL-SPEC / class S/B → 1.0; commercial → 8.0
_PI_Q: dict[str, float] = {
    "S":          0.5,
    "B":          1.0,
    "B-1":        1.0,
    "C":          2.0,
    "D":          3.0,
    "commercial": 8.0,
    "lower":      15.0,
}

# ── Base failure rates λg [FIT] for parts-count (MIL-217F Table 3-1 excerpts) ─
#   FIT = failures per 10^9 operating hours
_LAMBDA_G: dict[str, float] = {
    "resistor":        0.0023,   # fixed composition (RC) at +25 °C GB
    "capacitor":       0.0052,   # ceramic (CC) at +25 °C GB
    "ic_digital":      0.0095,   # TTL/CMOS SSI/MSI
    "ic_linear":       0.0095,   # op-amp
    "ic_memory":       0.012,    # SRAM/Flash (per device)
    "transistor_bjt":  0.0026,   # Si NPN/PNP general purpose
    "transistor_fet":  0.0030,   # MOSFET
    "diode_signal":    0.0019,   # signal/rectifier
    "diode_zener":     0.0022,   # zener/TVS
    "connector":       0.0005,   # per contact (Table 15-1 contact rate)
    "inductor":        0.0082,   # fixed wound (Table 16-1)
    "transformer":     0.0096,   # low-power audio/signal
    "crystal":         0.022,    # quartz (Table 18-1)
    "relay":           0.13,     # electromagnetic (Table 19-1 at 60 % duty)
    "switch":          0.14,     # toggle/push-button (Table 20-1)
    "solder_joint":    0.00001,  # per joint (approximate, stress method only)
}

# ── Activation energies Ea [eV] for Arrhenius πT ─────────────────────────────
_EA: dict[str, float] = {
    "resistor":       0.15,
    "capacitor":      0.35,
    "ic_digital":     0.35,
    "ic_linear":      0.35,
    "ic_memory":      0.40,
    "transistor_bjt": 0.40,
    "transistor_fet": 0.40,
    "diode_signal":   0.40,
    "diode_zener":    0.40,
    "connector":      0.15,
    "inductor":       0.15,
    "transformer":    0.15,
    "crystal":        0.25,
    "relay":          0.15,
    "switch":         0.15,
    "solder_joint":   0.50,
}

# ── Derating limits (voltage/power/temperature) by category ──────────────────
#   Format: {category: {param: limit_fraction_or_absolute}}
#   All fractions are recommended derated value / rated value.
_DERATING_LIMITS: dict[str, dict[str, float]] = {
    "resistor":        {"power": 0.50, "temperature": 0.80},
    "capacitor":       {"voltage": 0.50, "temperature": 0.75},
    "ic_digital":      {"voltage": 0.90, "temperature": 0.80},
    "ic_linear":       {"voltage": 0.90, "temperature": 0.80},
    "ic_memory":       {"voltage": 0.90, "temperature": 0.80},
    "transistor_bjt":  {"voltage": 0.70, "power": 0.50, "temperature": 0.80},
    "transistor_fet":  {"voltage": 0.70, "power": 0.50, "temperature": 0.80},
    "diode_signal":    {"voltage": 0.70, "power": 0.50},
    "diode_zener":     {"power": 0.50},
    "connector":       {"voltage": 0.50},
    "inductor":        {"current": 0.80},
    "relay":           {"voltage": 0.75, "current": 0.75},
    "switch":          {"voltage": 0.75, "current": 0.75},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _celsius_to_kelvin(t_c: float) -> float:
    return t_c + 273.15


def _pi_t(part_type: str, tj_c: float, tref_c: float = 40.0) -> float:
    """Arrhenius temperature factor relative to reference temperature."""
    ea = _EA.get(part_type, 0.40)
    tj_k = _celsius_to_kelvin(tj_c)
    tref_k = _celsius_to_kelvin(tref_c)
    return math.exp(ea / _K_B * (1.0 / tref_k - 1.0 / tj_k))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MIL-HDBK-217F Parts-Count Method
# ═══════════════════════════════════════════════════════════════════════════════

def mil217f_parts_count(
    parts: list[dict[str, Any]],
    environment: str = "GF",
    quality: str = "commercial",
) -> dict[str, Any]:
    """Compute board FIT using the MIL-HDBK-217F parts-count method.

    λ_pred = Σ Ni · λg · πQ

    Parameters
    ----------
    parts : list of dicts, each with:
        - "type"     : str  — part category (see _LAMBDA_G keys)
        - "count"    : int  — quantity on board (default 1)
        - "quality"  : str  — override per-part quality (optional)
    environment : str
        Environment code (default "GF").  See _PI_E for valid codes.
    quality : str
        Default quality for all parts (default "commercial").

    Returns
    -------
    dict with ok, fit_total, mtbf_hours, environment, quality, part_breakdown,
    warnings
    """
    if not isinstance(parts, list) or len(parts) == 0:
        return {"ok": False, "reason": "parts must be a non-empty list"}

    pi_e = _PI_E.get(environment)
    if pi_e is None:
        return {"ok": False, "reason": f"unknown environment '{environment}'; "
                f"valid codes: {sorted(_PI_E)}"}

    default_pi_q = _PI_Q.get(quality)
    if default_pi_q is None:
        return {"ok": False, "reason": f"unknown quality '{quality}'; "
                f"valid: {sorted(_PI_Q)}"}

    warn_list: list[str] = []
    breakdown: list[dict] = []
    fit_total = 0.0

    for i, p in enumerate(parts):
        ptype = p.get("type", "")
        if ptype not in _LAMBDA_G:
            return {"ok": False, "reason": f"part[{i}]: unknown type '{ptype}'; "
                    f"valid: {sorted(_LAMBDA_G)}"}

        count = float(p.get("count", 1))
        if count <= 0:
            return {"ok": False, "reason": f"part[{i}]: count must be > 0"}

        part_quality = p.get("quality", quality)
        pi_q = _PI_Q.get(part_quality)
        if pi_q is None:
            return {"ok": False, "reason": f"part[{i}]: unknown quality '{part_quality}'"}

        lambda_g = _LAMBDA_G[ptype]
        # parts-count: πE is applied at board level (GB baseline adjusted by πE)
        fit = count * lambda_g * pi_q * pi_e
        fit_total += fit
        breakdown.append({
            "type": ptype,
            "count": count,
            "lambda_g_fit": lambda_g,
            "pi_q": pi_q,
            "pi_e": pi_e,
            "fit_contribution": fit,
        })

    mtbf_hours = 1e9 / fit_total if fit_total > 0 else float("inf")

    if mtbf_hours < 1000:
        msg = f"Very low MTBF ({mtbf_hours:.0f} h); review design"
        warnings.warn(msg)
        warn_list.append(msg)

    return {
        "ok": True,
        "method": "MIL-HDBK-217F parts-count",
        "fit_total": fit_total,
        "mtbf_hours": mtbf_hours,
        "environment": environment,
        "pi_e": pi_e,
        "quality": quality,
        "part_breakdown": breakdown,
        "warnings": warn_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MIL-HDBK-217F Part-Stress Method
# ═══════════════════════════════════════════════════════════════════════════════

def mil217f_part_stress(
    part_type: str,
    tj_c: float,
    voltage_stress: float = 0.5,
    power_stress: float = 0.5,
    environment: str = "GF",
    quality: str = "commercial",
    pi_a: float = 1.0,
) -> dict[str, Any]:
    """Compute per-part FIT using the MIL-HDBK-217F part-stress method.

    λ_p = λ_b · πT · πS · πE · πQ · πA

    where:
      λ_b   = base failure rate at reference temperature [FIT]
      πT    = Arrhenius temperature factor
      πS    = electrical stress factor (V_applied/V_rated or P_applied/P_rated)
      πE    = environment multiplier
      πQ    = quality multiplier
      πA    = application multiplier (caller-supplied, default 1.0)

    Parameters
    ----------
    part_type : str
        One of the categories in _LAMBDA_G.
    tj_c : float
        Junction / case temperature [°C].
    voltage_stress : float
        Applied voltage / rated voltage (0–1, default 0.5).
    power_stress : float
        Applied power / rated power (0–1, default 0.5).
    environment : str
        Environment code (default "GF").
    quality : str
        Quality level (default "commercial").
    pi_a : float
        Application multiplier (default 1.0).

    Returns
    -------
    dict with ok, fit, lambda_b, pi_t, pi_s, pi_e, pi_q, pi_a, warnings
    """
    if part_type not in _LAMBDA_G:
        return {"ok": False, "reason": f"unknown part_type '{part_type}'; "
                f"valid: {sorted(_LAMBDA_G)}"}

    pi_e = _PI_E.get(environment)
    if pi_e is None:
        return {"ok": False, "reason": f"unknown environment '{environment}'"}

    pi_q = _PI_Q.get(quality)
    if pi_q is None:
        return {"ok": False, "reason": f"unknown quality '{quality}'"}

    if not (0.0 < voltage_stress <= 1.5):
        return {"ok": False, "reason": "voltage_stress must be in (0, 1.5]"}
    if not (0.0 < power_stress <= 1.5):
        return {"ok": False, "reason": "power_stress must be in (0, 1.5]"}
    if tj_c < -273.15:
        return {"ok": False, "reason": "tj_c below absolute zero"}
    if pi_a <= 0:
        return {"ok": False, "reason": "pi_a must be > 0"}

    warn_list: list[str] = []

    # Temperature factor
    pi_t = _pi_t(part_type, tj_c)

    # Electrical stress factor: use higher of voltage or power stress
    #   πS = (stress_ratio)^n; exponent n=3 for capacitors/diodes,
    #   n=2 for resistors, n=1 for most others (conservative approximation)
    _stress_exp: dict[str, float] = {
        "capacitor": 3.0,
        "diode_signal": 3.0,
        "diode_zener": 3.0,
        "transistor_bjt": 2.0,
        "transistor_fet": 2.0,
        "resistor": 2.0,
    }
    n = _stress_exp.get(part_type, 1.0)
    stress_ratio = max(voltage_stress, power_stress)
    pi_s = stress_ratio ** n

    lambda_b = _LAMBDA_G[part_type]
    fit = lambda_b * pi_t * pi_s * pi_e * pi_q * pi_a

    # Derating warnings
    limits = _DERATING_LIMITS.get(part_type, {})
    if "voltage" in limits and voltage_stress > limits["voltage"]:
        msg = (f"{part_type}: voltage stress {voltage_stress:.2f} exceeds "
               f"derating limit {limits['voltage']:.2f}")
        warnings.warn(msg)
        warn_list.append(msg)
    if "power" in limits and power_stress > limits["power"]:
        msg = (f"{part_type}: power stress {power_stress:.2f} exceeds "
               f"derating limit {limits['power']:.2f}")
        warnings.warn(msg)
        warn_list.append(msg)
    if fit > 1e6:
        msg = f"Extremely high part FIT ({fit:.0f}); design risk"
        warnings.warn(msg)
        warn_list.append(msg)

    return {
        "ok": True,
        "method": "MIL-HDBK-217F part-stress",
        "part_type": part_type,
        "fit": fit,
        "lambda_b_fit": lambda_b,
        "pi_t": pi_t,
        "pi_s": pi_s,
        "pi_e": pi_e,
        "pi_q": pi_q,
        "pi_a": pi_a,
        "tj_c": tj_c,
        "warnings": warn_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Board-Level FIT and MTBF (aggregated stress method)
# ═══════════════════════════════════════════════════════════════════════════════

def board_fit_and_mtbf(
    parts: list[dict[str, Any]],
    environment: str = "GF",
) -> dict[str, Any]:
    """Aggregate part-stress FIT across all board components.

    Each part dict may specify:
      type, count, quality (default "commercial"),
      tj_c (default 50), voltage_stress (default 0.5),
      power_stress (default 0.5), pi_a (default 1.0)

    Note
    ----
    Telcordia SR-332 Issue 4 provides an alternative black-box method
    (Method I/II) that incorporates field failure data and burn-in.
    That method requires vendor-supplied λ_SS and burn-in hours not
    available in a pure-calculation context; use the SR-332 model when
    vendor data is available.

    Returns
    -------
    dict with ok, fit_total, mtbf_hours, part_breakdown, warnings
    """
    if not isinstance(parts, list) or len(parts) == 0:
        return {"ok": False, "reason": "parts must be a non-empty list"}

    warn_list: list[str] = []
    breakdown: list[dict] = []
    fit_total = 0.0

    for i, p in enumerate(parts):
        ptype = p.get("type", "")
        count = int(p.get("count", 1))
        if count <= 0:
            return {"ok": False, "reason": f"part[{i}]: count must be > 0"}

        r = mil217f_part_stress(
            part_type=ptype,
            tj_c=float(p.get("tj_c", 50.0)),
            voltage_stress=float(p.get("voltage_stress", 0.5)),
            power_stress=float(p.get("power_stress", 0.5)),
            environment=environment,
            quality=str(p.get("quality", "commercial")),
            pi_a=float(p.get("pi_a", 1.0)),
        )
        if not r.get("ok"):
            return {"ok": False, "reason": f"part[{i}]: {r.get('reason')}"}

        part_fit = r["fit"] * count
        fit_total += part_fit
        warn_list.extend(r.get("warnings", []))
        breakdown.append({
            "type": ptype,
            "count": count,
            "fit_per_unit": r["fit"],
            "fit_contribution": part_fit,
            "pi_t": r["pi_t"],
            "pi_s": r["pi_s"],
        })

    mtbf_hours = 1e9 / fit_total if fit_total > 0 else float("inf")

    if mtbf_hours < 1000:
        msg = f"Very low board MTBF ({mtbf_hours:.0f} h)"
        warnings.warn(msg)
        warn_list.append(msg)

    return {
        "ok": True,
        "method": "MIL-HDBK-217F part-stress (board aggregate)",
        "fit_total": fit_total,
        "mtbf_hours": mtbf_hours,
        "environment": environment,
        "part_breakdown": breakdown,
        "warnings": warn_list,
        "telcordia_note": (
            "For Telcordia SR-332 (Method I/II), supply vendor λ_SS + burn-in hours "
            "not available in this pure-Python implementation."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Arrhenius Acceleration Factor & Activation Energy
# ═══════════════════════════════════════════════════════════════════════════════

def arrhenius_acceleration_factor(
    t_use_c: float,
    t_test_c: float,
    ea_ev: float = 0.7,
) -> dict[str, Any]:
    """Compute Arrhenius acceleration factor AF = exp(Ea/k × (1/T_use − 1/T_test)).

    A factor > 1 means the test is more stressful (hotter) than use; the
    equivalent use-hours = test_hours × AF.

    Parameters
    ----------
    t_use_c  : use-condition temperature [°C]
    t_test_c : accelerated-test temperature [°C]
    ea_ev    : activation energy [eV] (default 0.7 eV — typical for ICs)

    Returns
    -------
    dict with ok, acceleration_factor, ea_ev, t_use_c, t_test_c
    """
    if ea_ev <= 0:
        return {"ok": False, "reason": "ea_ev must be > 0"}
    t_use_k = _celsius_to_kelvin(t_use_c)
    t_test_k = _celsius_to_kelvin(t_test_c)
    if t_use_k <= 0 or t_test_k <= 0:
        return {"ok": False, "reason": "temperatures must be above absolute zero"}
    if t_test_k <= t_use_k:
        warnings.warn(
            "t_test_c ≤ t_use_c: acceleration factor < 1 (use is more stressful)"
        )
    af = math.exp(ea_ev / _K_B * (1.0 / t_use_k - 1.0 / t_test_k))
    return {
        "ok": True,
        "acceleration_factor": af,
        "ea_ev": ea_ev,
        "t_use_c": t_use_c,
        "t_test_c": t_test_c,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Coffin-Manson Thermal-Cycling Solder-Joint Fatigue
# ═══════════════════════════════════════════════════════════════════════════════

def coffin_manson_nf(
    delta_t_c: float,
    c_f: float = 0.005,
    m: float = 2.0,
    f_cyc_per_day: float = 1.0,
) -> dict[str, Any]:
    """Estimate solder-joint cycles-to-failure using the Coffin-Manson model.

    Norris-Landzberg variant (Solomon 1986):
      Nf = C_f / (ΔT)^m

    Parameters
    ----------
    delta_t_c     : thermal cycle amplitude ΔT [°C]
    c_f           : fatigue ductility coefficient (default 0.005 — eutectic SnPb;
                    use ~0.003 for SAC305 lead-free)
    m             : Coffin-Manson exponent (default 2.0; SAC305 often 2.65)
    f_cyc_per_day : cycling frequency [cycles/day] for converting Nf to years

    Returns
    -------
    dict with ok, nf_cycles, lifetime_years, delta_t_c
    """
    if delta_t_c <= 0:
        return {"ok": False, "reason": "delta_t_c must be > 0"}
    if c_f <= 0:
        return {"ok": False, "reason": "c_f must be > 0"}
    if m <= 0:
        return {"ok": False, "reason": "m must be > 0"}
    if f_cyc_per_day <= 0:
        return {"ok": False, "reason": "f_cyc_per_day must be > 0"}

    nf = c_f / (delta_t_c ** m)
    lifetime_years = nf / (f_cyc_per_day * 365.25)
    warn_list: list[str] = []
    if lifetime_years < 1.0:
        msg = f"Solder-joint lifetime {lifetime_years:.2f} yr < 1 yr; review thermal design"
        warnings.warn(msg)
        warn_list.append(msg)
    return {
        "ok": True,
        "nf_cycles": nf,
        "lifetime_years": lifetime_years,
        "delta_t_c": delta_t_c,
        "c_f": c_f,
        "m": m,
        "f_cyc_per_day": f_cyc_per_day,
        "warnings": warn_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Peck Humidity Acceleration
# ═══════════════════════════════════════════════════════════════════════════════

def peck_humidity_acceleration(
    rh_use: float,
    rh_test: float,
    t_use_c: float,
    t_test_c: float,
    ea_ev: float = 0.9,
    n_rh: float = 2.7,
) -> dict[str, Any]:
    """Compute Peck model humidity + temperature acceleration factor.

    AF = (RH_test / RH_use)^n_rh × exp(Ea/k × (1/T_use − 1/T_test))

    Peck (1986) originally proposed n_rh = 2.7 and Ea = 0.9 eV for
    moisture-driven failures in plastic-encapsulated ICs.

    Parameters
    ----------
    rh_use   : use-condition relative humidity [%RH] (0–100)
    rh_test  : test relative humidity [%RH] (0–100)
    t_use_c  : use temperature [°C]
    t_test_c : test temperature [°C]
    ea_ev    : activation energy [eV] (default 0.9)
    n_rh     : humidity exponent (default 2.7)

    Returns
    -------
    dict with ok, acceleration_factor, humidity_factor, thermal_factor
    """
    if not (0 < rh_use <= 100):
        return {"ok": False, "reason": "rh_use must be in (0, 100]"}
    if not (0 < rh_test <= 100):
        return {"ok": False, "reason": "rh_test must be in (0, 100]"}
    if ea_ev <= 0:
        return {"ok": False, "reason": "ea_ev must be > 0"}
    if n_rh <= 0:
        return {"ok": False, "reason": "n_rh must be > 0"}

    t_use_k = _celsius_to_kelvin(t_use_c)
    t_test_k = _celsius_to_kelvin(t_test_c)
    if t_use_k <= 0 or t_test_k <= 0:
        return {"ok": False, "reason": "temperatures must be above absolute zero"}

    humidity_factor = (rh_test / rh_use) ** n_rh
    thermal_factor = math.exp(ea_ev / _K_B * (1.0 / t_use_k - 1.0 / t_test_k))
    af = humidity_factor * thermal_factor
    return {
        "ok": True,
        "acceleration_factor": af,
        "humidity_factor": humidity_factor,
        "thermal_factor": thermal_factor,
        "rh_use": rh_use,
        "rh_test": rh_test,
        "ea_ev": ea_ev,
        "n_rh": n_rh,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Voltage Acceleration
# ═══════════════════════════════════════════════════════════════════════════════

def voltage_acceleration(
    v_use: float,
    v_test: float,
    beta: float = 2.5,
) -> dict[str, Any]:
    """Compute voltage acceleration factor (inverse power law).

    AF = (V_test / V_use)^β

    Used for capacitor dielectric breakdown (β ≈ 2–5 for ceramic,
    β ≈ 3 for electrolytic) and oxide wear-out in ICs.

    Parameters
    ----------
    v_use  : use voltage [V] (> 0)
    v_test : test (stressed) voltage [V] (> 0)
    beta   : voltage exponent (default 2.5)

    Returns
    -------
    dict with ok, acceleration_factor, v_use, v_test, beta
    """
    if v_use <= 0:
        return {"ok": False, "reason": "v_use must be > 0"}
    if v_test <= 0:
        return {"ok": False, "reason": "v_test must be > 0"}
    if beta <= 0:
        return {"ok": False, "reason": "beta must be > 0"}
    af = (v_test / v_use) ** beta
    warn_list: list[str] = []
    if v_test / v_use > 2.0:
        msg = "Voltage over-stress ratio > 2×; verify component ratings"
        warnings.warn(msg)
        warn_list.append(msg)
    return {
        "ok": True,
        "acceleration_factor": af,
        "v_use": v_use,
        "v_test": v_test,
        "beta": beta,
        "warnings": warn_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Derating-Curve Check
# ═══════════════════════════════════════════════════════════════════════════════

def derating_check(
    part_type: str,
    voltage_ratio: float | None = None,
    power_ratio: float | None = None,
    temperature_ratio: float | None = None,
    current_ratio: float | None = None,
) -> dict[str, Any]:
    """Check applied stress ratios against standard derating curves.

    Parameters
    ----------
    part_type         : str — one of the categories in _DERATING_LIMITS
    voltage_ratio     : applied / rated voltage (optional)
    power_ratio       : applied / rated power (optional)
    temperature_ratio : applied / rated temperature in consistent units (optional)
    current_ratio     : applied / rated current (optional)

    Returns
    -------
    dict with ok, compliant, violations, limits, warnings
    """
    if part_type not in _DERATING_LIMITS and part_type not in _LAMBDA_G:
        return {"ok": False, "reason": f"unknown part_type '{part_type}'"}

    limits = _DERATING_LIMITS.get(part_type, {})
    supplied = {
        "voltage": voltage_ratio,
        "power": power_ratio,
        "temperature": temperature_ratio,
        "current": current_ratio,
    }
    violations: list[dict] = []
    warn_list: list[str] = []

    for param, limit in limits.items():
        value = supplied.get(param)
        if value is None:
            continue
        if value < 0:
            return {"ok": False, "reason": f"{param}_ratio must be ≥ 0"}
        if value > limit:
            msg = (f"{part_type}: {param} ratio {value:.3f} exceeds "
                   f"derating limit {limit:.3f}")
            warnings.warn(msg)
            warn_list.append(msg)
            violations.append({"param": param, "applied": value, "limit": limit})

    return {
        "ok": True,
        "compliant": len(violations) == 0,
        "part_type": part_type,
        "violations": violations,
        "limits": limits,
        "warnings": warn_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Bathtub Hazard Rate λ(t)
# ═══════════════════════════════════════════════════════════════════════════════

def bathtub_hazard_rate(
    t_hours: float,
    lambda_early: float = 100.0,
    lambda_random: float = 10.0,
    lambda_wearout: float = 1.0,
    t_infant: float = 168.0,
    t_wearout: float = 87600.0,
    beta_early: float = 0.5,
    beta_wearout: float = 4.0,
) -> dict[str, Any]:
    """Return instantaneous hazard rate λ(t) from a three-region bathtub model.

    The model superimposes three Weibull phases:
      Infant-mortality:  λ_early  × (β_early/t_infant)  × (t/t_infant)^(β_early-1)
      Random failures:   λ_random  (constant, exponential, β=1)
      Wear-out:          λ_wearout × (β_wearout/t_wearout) × (t/t_wearout)^(β_wearout-1)

    Parameters
    ----------
    t_hours      : operating time [h]
    lambda_early : scale for infant-mortality region [FIT]
    lambda_random: constant random failure rate [FIT]
    lambda_wearout: scale for wear-out region [FIT]
    t_infant     : infant-mortality characteristic life [h] (default 168 h = 1 week)
    t_wearout    : wear-out characteristic life [h] (default 87600 h = 10 yr)
    beta_early   : Weibull shape for infant mortality (< 1, default 0.5)
    beta_wearout : Weibull shape for wear-out (> 1, default 4.0)

    Returns
    -------
    dict with ok, t_hours, lambda_fit, phase
    """
    if t_hours < 0:
        return {"ok": False, "reason": "t_hours must be ≥ 0"}
    if t_hours == 0:
        return {
            "ok": True, "t_hours": 0.0, "lambda_fit": lambda_early + lambda_random,
            "phase": "infant_mortality"
        }

    h_early = (lambda_early * (beta_early / t_infant)
               * (t_hours / t_infant) ** (beta_early - 1))
    h_random = lambda_random
    h_wearout = (lambda_wearout * (beta_wearout / t_wearout)
                 * (t_hours / t_wearout) ** (beta_wearout - 1))
    h_total = h_early + h_random + h_wearout

    if t_hours < t_infant:
        phase = "infant_mortality"
    elif t_hours < t_wearout:
        phase = "random"
    else:
        phase = "wearout"

    return {
        "ok": True,
        "t_hours": t_hours,
        "lambda_fit": h_total,
        "lambda_early": h_early,
        "lambda_random": h_random,
        "lambda_wearout": h_wearout,
        "phase": phase,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Redundancy MTBF (Active / Standby)
# ═══════════════════════════════════════════════════════════════════════════════

def redundancy_mtbf(
    fit_per_unit: float,
    n_active: int = 2,
    redundancy_type: str = "active",
    switch_reliability: float = 0.99,
) -> dict[str, Any]:
    """Compute system MTBF for active (parallel) or standby redundancy.

    Active (parallel) n-of-m:
      MTBF_sys = MTBF_unit × Σ(k=1..n) 1/k   (for n identical units, all active)

    Standby (cold) 1-of-2 with switch reliability Rs:
      MTBF_sys = MTBF_unit × (2 - 1/(1 + Rs))   (approximate first-order)
      The exact formula for a perfect switch is MTBF_sys = 2 × MTBF_unit.
      Switch unreliability reduces this: MTBF_sys ≈ MTBF_unit × (1 + Rs)

    Parameters
    ----------
    fit_per_unit      : failure rate of each unit [FIT]
    n_active          : number of units (default 2)
    redundancy_type   : "active" or "standby" (default "active")
    switch_reliability: reliability of the switchover mechanism (0–1, standby only)

    Returns
    -------
    dict with ok, mtbf_unit_hours, mtbf_system_hours, redundancy_type, n
    """
    if fit_per_unit <= 0:
        return {"ok": False, "reason": "fit_per_unit must be > 0"}
    if n_active < 1:
        return {"ok": False, "reason": "n_active must be ≥ 1"}
    if not (0.0 <= switch_reliability <= 1.0):
        return {"ok": False, "reason": "switch_reliability must be in [0, 1]"}
    if redundancy_type not in ("active", "standby"):
        return {"ok": False, "reason": "redundancy_type must be 'active' or 'standby'"}

    mtbf_unit = 1e9 / fit_per_unit

    if redundancy_type == "active":
        # Harmonic series formula for n active parallel identical units
        mtbf_sys = mtbf_unit * sum(1.0 / k for k in range(1, n_active + 1))
    else:
        # Standby: 1+2+...+n units available sequentially with switch
        # MTBF_sys = MTBF_unit × n × Rs  (simplified; n units, switch Rs)
        mtbf_sys = mtbf_unit * n_active * switch_reliability

    return {
        "ok": True,
        "mtbf_unit_hours": mtbf_unit,
        "mtbf_system_hours": mtbf_sys,
        "redundancy_type": redundancy_type,
        "n": n_active,
        "switch_reliability": switch_reliability,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Chi-Square MTBF Confidence Bound from Demonstration Test
# ═══════════════════════════════════════════════════════════════════════════════

def mtbf_confidence_bound(
    total_hours: float,
    n_failures: int,
    confidence: float = 0.90,
    bound: str = "lower",
) -> dict[str, Any]:
    """Compute one-sided MTBF confidence bound from time-terminated test data.

    MIL-HDBK-781A, Annex A:
      Lower bound: MTBF_lower = 2 × T / χ²(2f+2, α)   (f = failures, α = 1 − CL)
      Upper bound: MTBF_upper = 2 × T / χ²(2f, 1−α)   (f > 0)

    Chi-square is approximated via the Wilson-Hilferty normal approximation
    (accurate to < 0.1 % for df > 5; conservative for small df).

    Parameters
    ----------
    total_hours : accumulated test time [h]
    n_failures  : number of observed failures (≥ 0)
    confidence  : confidence level (0–1, default 0.90)
    bound       : "lower" or "upper" (default "lower")

    Returns
    -------
    dict with ok, mtbf_bound_hours, confidence, bound, n_failures, total_hours
    """
    if total_hours <= 0:
        return {"ok": False, "reason": "total_hours must be > 0"}
    if n_failures < 0:
        return {"ok": False, "reason": "n_failures must be ≥ 0"}
    if not (0 < confidence < 1):
        return {"ok": False, "reason": "confidence must be in (0, 1)"}
    if bound not in ("lower", "upper"):
        return {"ok": False, "reason": "bound must be 'lower' or 'upper'"}
    if bound == "upper" and n_failures == 0:
        return {"ok": False, "reason": "upper bound undefined for zero failures"}

    alpha = 1.0 - confidence

    def _chi2_ppf(p: float, df: float) -> float:
        """Wilson-Hilferty chi-square quantile approximation."""
        if df <= 0:
            return 0.0
        # Normal quantile via rational approximation (Abramowitz & Stegun 26.2.17)
        def _norm_ppf(pp: float) -> float:
            if pp <= 0:
                return -1e38
            if pp >= 1:
                return 1e38
            t = math.sqrt(-2.0 * math.log(min(pp, 1.0 - pp)))
            c = [2.515517, 0.802853, 0.010328]
            d = [1.432788, 0.189269, 0.001308]
            z = t - (c[0] + c[1]*t + c[2]*t*t) / (1 + d[0]*t + d[1]*t*t + d[2]*t*t*t)
            return -z if pp < 0.5 else z

        z = _norm_ppf(p)
        h = 2.0 / (9.0 * df)
        x = df * ((1.0 - h + z * math.sqrt(h)) ** 3)
        return max(x, 0.0)

    if bound == "lower":
        df = 2 * n_failures + 2
        chi2 = _chi2_ppf(1.0 - alpha, df)
    else:
        df = 2 * n_failures
        chi2 = _chi2_ppf(alpha, df)

    if chi2 <= 0:
        return {"ok": False, "reason": "chi-square quantile degenerate; increase failures"}

    mtbf_bound = 2.0 * total_hours / chi2
    warn_list: list[str] = []
    if mtbf_bound < 1000:
        msg = f"Demonstrated MTBF {bound} bound {mtbf_bound:.0f} h is low"
        warnings.warn(msg)
        warn_list.append(msg)
    return {
        "ok": True,
        "mtbf_bound_hours": mtbf_bound,
        "confidence": confidence,
        "bound": bound,
        "n_failures": n_failures,
        "total_hours": total_hours,
        "chi2": chi2,
        "df": df,
        "warnings": warn_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Duty-Cycle & Power-On-Hours Adjusted FIT
# ═══════════════════════════════════════════════════════════════════════════════

def duty_cycle_adjusted_fit(
    fit_rated: float,
    duty_cycle: float,
    calendar_hours_per_year: float = 8760.0,
) -> dict[str, Any]:
    """Adjust FIT and MTBF for duty cycle (power-on-hours vs calendar time).

    The MIL-217F base FIT applies to powered (operating) hours.  For a device
    powered only a fraction of calendar time, the calendar-time failure rate is:

      λ_calendar = λ_rated × duty_cycle
      MTBF_calendar = 1e9 / λ_calendar  [calendar hours]

    Parameters
    ----------
    fit_rated              : nominal (100 % duty) FIT [FIT]
    duty_cycle             : fraction of calendar time powered (0–1)
    calendar_hours_per_year: calendar hours per year (default 8760)

    Returns
    -------
    dict with ok, fit_adjusted, mtbf_calendar_hours, mtbf_calendar_years,
    duty_cycle, power_on_hours_per_year
    """
    if fit_rated <= 0:
        return {"ok": False, "reason": "fit_rated must be > 0"}
    if not (0 < duty_cycle <= 1.0):
        return {"ok": False, "reason": "duty_cycle must be in (0, 1]"}
    if calendar_hours_per_year <= 0:
        return {"ok": False, "reason": "calendar_hours_per_year must be > 0"}

    fit_adj = fit_rated * duty_cycle
    mtbf_cal = 1e9 / fit_adj
    poh_per_year = duty_cycle * calendar_hours_per_year
    warn_list: list[str] = []
    if mtbf_cal < 1000:
        msg = f"Adjusted MTBF {mtbf_cal:.0f} h is very low"
        warnings.warn(msg)
        warn_list.append(msg)
    return {
        "ok": True,
        "fit_adjusted": fit_adj,
        "mtbf_calendar_hours": mtbf_cal,
        "mtbf_calendar_years": mtbf_cal / calendar_hours_per_year,
        "duty_cycle": duty_cycle,
        "power_on_hours_per_year": poh_per_year,
        "warnings": warn_list,
    }
