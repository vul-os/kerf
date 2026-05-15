"""
Battery-pack sizing and runtime estimator.

Distinct from kerf_electronics.pdn (board power-delivery network).  This module
operates at the *pack* level: sizing cells into series/parallel configurations
to meet a target voltage and capacity, then estimating runtime from a load
profile.

Physics summary
---------------
Pack configuration
  - Series cells raise terminal voltage:  V_pack = n_s * V_cell
  - Parallel cells raise capacity:        Q_pack = n_p * Q_cell  (Ah)

Peukert correction (empirical)
  - Standard Peukert equation:  t = C / I^k
    where C = rated capacity at 1 C (Ah), I = discharge current (A), k = Peukert
    exponent (typically 1.1–1.3 for Li-ion; 1.2–1.8 for lead-acid).
  - Effective capacity at current I:  Q_eff = Q_rated / I^(k−1)
  - When k == 1.0 there is no Peukert correction (ideal cell).

Depth-of-discharge (DoD) limit
  - Usable energy is restricted to DoD fraction of rated capacity, protecting
    the cell against over-discharge.

Thermal rise (first-order)
  - ΔT = I² × R_int × t_discharge / (mass_g * c_cell)
  - c_cell defaults to 900 J/(kg·°C) — representative for cylindrical Li-ion.

Charge time (CC-CV simple model)
  - CC phase: I_charge = C_rate_charge × Q_rated;  t_CC = (DoD × Q_rated) / I_charge
  - CV phase tail: approximately 20% additional time for full top-up.
  - Returns separate CC_h and CV_tail_h, plus total_h.

All public functions return a dict with {ok: True/False, ...}.  They NEVER raise.
Warnings (over-C-rate, under-capacity) are accumulated in a "warnings" list field.

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any

# Physical constant — representative specific heat for cylindrical Li-ion cell (J/(kg·°C))
_C_CELL_J_KG_C = 900.0


# ── Data validation helpers ───────────────────────────────────────────────────

def _require_positive(value: Any, name: str) -> tuple[float | None, str | None]:
    """Return (float, None) on success or (None, error_message) on failure."""
    if value is None:
        return None, f"{name} is required"
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return None, f"{name} must be a finite number, got {value!r}"
    if value <= 0:
        return None, f"{name} must be positive, got {value}"
    return float(value), None


def _require_nonneg(value: Any, name: str) -> tuple[float | None, str | None]:
    """Return (float, None) on success or (None, error_message) for non-negative."""
    if value is None:
        return None, f"{name} is required"
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return None, f"{name} must be a finite number, got {value!r}"
    if value < 0:
        return None, f"{name} must be >= 0, got {value}"
    return float(value), None


# ── Pack configuration ────────────────────────────────────────────────────────

def size_pack(
    target_voltage_v: float,
    target_capacity_ah: float,
    cell_voltage_v: float,
    cell_capacity_ah: float,
    cell_mass_g: float | None = None,
    cell_volume_cm3: float | None = None,
    cell_r_int_ohm: float | None = None,
    cell_max_discharge_c: float | None = None,
) -> dict:
    """
    Compute a series/parallel pack configuration to meet target voltage and capacity.

    Parameters
    ----------
    target_voltage_v:
        Desired pack nominal voltage (V).
    target_capacity_ah:
        Desired pack capacity (Ah).
    cell_voltage_v:
        Cell nominal voltage (V).
    cell_capacity_ah:
        Cell rated capacity at standard discharge rate (Ah).
    cell_mass_g:
        Single-cell mass (g). Optional; when given, pack_mass_g is returned.
    cell_volume_cm3:
        Single-cell volume (cm³). Optional; when given, pack_volume_cm3 is returned.
    cell_r_int_ohm:
        Cell internal resistance (Ω). Optional; pack internal resistance is computed.
    cell_max_discharge_c:
        Cell max continuous discharge C-rate. Optional; used for C-rate check.

    Returns
    -------
    dict with keys:
        ok                  : bool
        n_series            : int   — cells in series per parallel branch
        n_parallel          : int   — parallel branches
        n_total             : int   — total cell count
        pack_voltage_v      : float — actual pack voltage (n_s * V_cell)
        pack_capacity_ah    : float — actual pack capacity (n_p * Q_cell)
        pack_energy_wh      : float — pack energy (V × Ah)
        pack_mass_g         : float | None
        pack_volume_cm3     : float | None
        pack_r_int_ohm      : float | None — series R = n_s*R_cell; parallel divides by n_p
        warnings            : list[str]
        reason              : str   — present only on error (ok=False)
    """
    warnings: list[str] = []

    v_cell, e = _require_positive(cell_voltage_v, "cell_voltage_v")
    if e:
        return {"ok": False, "reason": e}
    q_cell, e = _require_positive(cell_capacity_ah, "cell_capacity_ah")
    if e:
        return {"ok": False, "reason": e}
    v_target, e = _require_positive(target_voltage_v, "target_voltage_v")
    if e:
        return {"ok": False, "reason": e}
    q_target, e = _require_positive(target_capacity_ah, "target_capacity_ah")
    if e:
        return {"ok": False, "reason": e}

    # Minimum cells to reach targets (round up)
    n_s = max(1, math.ceil(v_target / v_cell))
    n_p = max(1, math.ceil(q_target / q_cell))

    pack_v = n_s * v_cell
    pack_q = n_p * q_cell
    pack_energy = pack_v * pack_q

    pack_mass = n_s * n_p * float(cell_mass_g) if isinstance(cell_mass_g, (int, float)) and cell_mass_g > 0 else None
    pack_vol = n_s * n_p * float(cell_volume_cm3) if isinstance(cell_volume_cm3, (int, float)) and cell_volume_cm3 > 0 else None

    # Internal resistance: series adds; parallel divides
    pack_r: float | None = None
    if isinstance(cell_r_int_ohm, (int, float)) and cell_r_int_ohm > 0:
        pack_r = (n_s * float(cell_r_int_ohm)) / n_p

    result: dict = {
        "ok": True,
        "n_series": n_s,
        "n_parallel": n_p,
        "n_total": n_s * n_p,
        "pack_voltage_v": round(pack_v, 6),
        "pack_capacity_ah": round(pack_q, 6),
        "pack_energy_wh": round(pack_energy, 6),
        "pack_mass_g": round(pack_mass, 3) if pack_mass is not None else None,
        "pack_volume_cm3": round(pack_vol, 3) if pack_vol is not None else None,
        "pack_r_int_ohm": round(pack_r, 6) if pack_r is not None else None,
        "warnings": warnings,
    }
    return result


# ── Runtime estimation ────────────────────────────────────────────────────────

def estimate_runtime(
    pack_capacity_ah: float,
    pack_voltage_v: float,
    load_profile: list[dict],
    peukert_k: float = 1.1,
    dod_limit: float = 0.8,
    cell_max_discharge_c: float | None = None,
    pack_r_int_ohm: float | None = None,
    cell_mass_g: float | None = None,
    n_total: int | None = None,
) -> dict:
    """
    Estimate battery pack runtime given a multi-step load profile.

    Each load step is a dict: {"power_W": <float>, "duration_s": <float>}.
    Duration is the *requested* step duration; the estimator stops early if
    the usable capacity (DoD * Q_rated) is exhausted.

    Peukert correction is applied per step: effective capacity is reduced at
    higher discharge rates.  When k == 1.0 there is no correction.

    Parameters
    ----------
    pack_capacity_ah:
        Rated pack capacity (Ah) at standard discharge rate.
    pack_voltage_v:
        Pack nominal voltage (V).
    load_profile:
        List of dicts, each with 'power_W' (W) and 'duration_s' (s).
    peukert_k:
        Peukert exponent (default 1.1). Must be >= 1.0.
    dod_limit:
        Depth-of-discharge limit (0 < dod_limit <= 1.0; default 0.8).
    cell_max_discharge_c:
        Max cell C-rate; if exceeded in any step, a warning is added.
        Pass None to skip the check.
    pack_r_int_ohm:
        Pack internal resistance (Ω). When given, simple voltage drop is
        computed and included in the report.
    cell_mass_g:
        Individual cell mass (g); combined with n_total for thermal rise.
    n_total:
        Total number of cells; used for thermal rise calculation.

    Returns
    -------
    dict with keys:
        ok                  : bool
        runtime_s           : float — total usable runtime (s) across all steps
        runtime_min         : float — runtime in minutes
        energy_delivered_wh : float — energy actually delivered
        charge_consumed_ah  : float — charge drawn (Peukert-corrected equivalent)
        steps               : list of per-step result dicts
        exhausted           : bool  — True if pack was depleted before profile end
        warnings            : list[str]
        reason              : str   — present only on error (ok=False)
    """
    warnings: list[str] = []

    q_rated, e = _require_positive(pack_capacity_ah, "pack_capacity_ah")
    if e:
        return {"ok": False, "reason": e}
    v_pack, e = _require_positive(pack_voltage_v, "pack_voltage_v")
    if e:
        return {"ok": False, "reason": e}

    if not isinstance(load_profile, list) or len(load_profile) == 0:
        return {"ok": False, "reason": "load_profile must be a non-empty list"}

    pk, e = _require_positive(peukert_k, "peukert_k")
    if e:
        return {"ok": False, "reason": e}
    if pk < 1.0:
        return {"ok": False, "reason": "peukert_k must be >= 1.0"}

    dod, e = _require_positive(dod_limit, "dod_limit")
    if e:
        return {"ok": False, "reason": e}
    if dod > 1.0:
        return {"ok": False, "reason": "dod_limit must be <= 1.0"}

    usable_q_ah = q_rated * dod     # usable capacity in Ah
    remaining_q = usable_q_ah       # tracking remaining usable charge

    total_runtime_s = 0.0
    total_energy_wh = 0.0
    total_charge_ah = 0.0
    exhausted = False
    step_results: list[dict] = []

    for idx, step in enumerate(load_profile):
        if not isinstance(step, dict):
            return {"ok": False, "reason": f"load_profile[{idx}] must be a dict"}

        p_w = step.get("power_W")
        dur_s = step.get("duration_s")

        p_val, e = _require_nonneg(p_w, f"load_profile[{idx}].power_W")
        if e:
            return {"ok": False, "reason": e}
        d_val, e = _require_positive(dur_s, f"load_profile[{idx}].duration_s")
        if e:
            return {"ok": False, "reason": e}

        if remaining_q <= 0:
            exhausted = True
            break

        # Discharge current from pack terminal voltage
        i_a = p_val / v_pack if v_pack > 0 else 0.0

        # C-rate check
        if isinstance(cell_max_discharge_c, (int, float)) and cell_max_discharge_c > 0:
            step_c_rate = i_a / q_rated if q_rated > 0 else 0.0
            if step_c_rate > float(cell_max_discharge_c):
                warnings.append(
                    f"Step {idx}: discharge C-rate {step_c_rate:.2f}C exceeds "
                    f"cell max {cell_max_discharge_c}C at {p_val:.1f} W"
                )

        # Peukert-corrected effective capacity available at this current
        # Q_eff = Q_rated / I^(k-1)  when I > 0; else Q_rated
        if i_a > 0 and pk != 1.0:
            q_eff = q_rated / (i_a ** (pk - 1.0))
        else:
            q_eff = q_rated

        # Charge draw per second at this step (Ah/s)
        q_per_s = i_a / 3600.0  # Ah consumed per second of real time

        # How much effective charge does one real second consume?
        # Peukert: effective Ah/s = I * (I/1)^(k-1) / 3600 = I^k / 3600
        if i_a > 0:
            q_eff_per_s = (i_a ** pk) / 3600.0
        else:
            q_eff_per_s = 0.0

        # Time available at this step limited by remaining_q
        if q_eff_per_s > 0:
            t_available_s = (remaining_q / q_eff_per_s)
        else:
            t_available_s = d_val  # zero-load step: full duration available

        t_actual_s = min(d_val, t_available_s)

        if t_actual_s < d_val:
            exhausted = True

        # Energy and charge for this actual step
        energy_step_wh = p_val * t_actual_s / 3600.0
        charge_step_ah = q_eff_per_s * t_actual_s  # Peukert-corrected

        # Voltage drop (for reporting only; does not change the energy math here)
        v_drop = 0.0
        if isinstance(pack_r_int_ohm, (int, float)) and pack_r_int_ohm > 0 and i_a > 0:
            v_drop = i_a * float(pack_r_int_ohm)

        total_runtime_s += t_actual_s
        total_energy_wh += energy_step_wh
        total_charge_ah += charge_step_ah
        remaining_q -= charge_step_ah

        step_results.append({
            "step": idx,
            "power_W": p_val,
            "requested_duration_s": d_val,
            "actual_duration_s": round(t_actual_s, 3),
            "current_a": round(i_a, 4),
            "energy_wh": round(energy_step_wh, 6),
            "charge_ah": round(charge_step_ah, 6),
            "v_drop_v": round(v_drop, 4) if v_drop else None,
        })

    # Check under-capacity: if any step was truncated
    if exhausted:
        warnings.append(
            "Pack depleted before load profile ended (under-capacity for this profile)"
        )

    return {
        "ok": True,
        "runtime_s": round(total_runtime_s, 3),
        "runtime_min": round(total_runtime_s / 60.0, 4),
        "energy_delivered_wh": round(total_energy_wh, 6),
        "charge_consumed_ah": round(total_charge_ah, 6),
        "usable_capacity_ah": round(usable_q_ah, 6),
        "steps": step_results,
        "exhausted": exhausted,
        "warnings": warnings,
    }


# ── Charge time estimate (CC-CV simple model) ─────────────────────────────────

def estimate_charge_time(
    pack_capacity_ah: float,
    charge_c_rate: float = 0.5,
    dod_at_start: float = 0.8,
) -> dict:
    """
    Estimate pack charge time using a simplified CC-CV model.

    CC phase: constant current at charge_c_rate × Q_rated until ~80% SoC.
    CV phase: approximately 20% additional time for the remaining top-up.

    Parameters
    ----------
    pack_capacity_ah:
        Rated pack capacity (Ah).
    charge_c_rate:
        Charge C-rate (default 0.5C = C/2).
    dod_at_start:
        Depth of discharge at start of charging (default 0.8 = 80% depleted).

    Returns
    -------
    dict with keys:
        ok              : bool
        cc_current_a    : float — CC phase current (A)
        cc_time_h       : float — CC phase duration (h)
        cv_tail_h       : float — CV tail duration (h)  [approx 20% of CC time]
        total_time_h    : float — total charge time (h)
        total_time_min  : float — total in minutes
        warnings        : list[str]
    """
    warnings: list[str] = []

    q, e = _require_positive(pack_capacity_ah, "pack_capacity_ah")
    if e:
        return {"ok": False, "reason": e}
    c_rate, e = _require_positive(charge_c_rate, "charge_c_rate")
    if e:
        return {"ok": False, "reason": e}
    dod, e = _require_positive(dod_at_start, "dod_at_start")
    if e:
        return {"ok": False, "reason": e}
    if dod > 1.0:
        return {"ok": False, "reason": "dod_at_start must be <= 1.0"}

    if c_rate > 2.0:
        warnings.append(
            f"charge_c_rate {c_rate}C is high; fast-charge may reduce cycle life"
        )

    i_cc = c_rate * q  # CC phase current (A)
    # CC phase brings battery from DoD back to ~80% SoC target
    q_to_restore = dod * q  # Ah to restore in CC phase
    t_cc = q_to_restore / i_cc  # hours

    # CV tail: ~20% additional time
    t_cv = 0.2 * t_cc

    total_h = t_cc + t_cv

    return {
        "ok": True,
        "cc_current_a": round(i_cc, 4),
        "cc_time_h": round(t_cc, 4),
        "cv_tail_h": round(t_cv, 4),
        "total_time_h": round(total_h, 4),
        "total_time_min": round(total_h * 60.0, 2),
        "warnings": warnings,
    }


# ── Thermal rise estimate ──────────────────────────────────────────────────────

def estimate_thermal_rise(
    pack_r_int_ohm: float,
    discharge_current_a: float,
    discharge_time_s: float,
    pack_mass_g: float,
    specific_heat_j_kg_c: float = _C_CELL_J_KG_C,
) -> dict:
    """
    Estimate adiabatic temperature rise of the pack during discharge.

    Uses the first-order Joule heating model:
        ΔT = (I² × R × t) / (m × c)

    where m is pack mass in kg and c is specific heat in J/(kg·°C).

    This is an *adiabatic* (worst-case) estimate; actual rise is lower due to
    convection/conduction to the environment.

    Parameters
    ----------
    pack_r_int_ohm:
        Total pack internal resistance (Ω).
    discharge_current_a:
        Discharge current (A).
    discharge_time_s:
        Discharge duration (s).
    pack_mass_g:
        Total pack mass (g).
    specific_heat_j_kg_c:
        Specific heat capacity (J/(kg·°C)). Defaults to 900 J/(kg·°C) for Li-ion.

    Returns
    -------
    dict with keys:
        ok              : bool
        heat_generated_j: float — Joule heat (J)
        delta_T_c       : float — adiabatic temperature rise (°C)
        warnings        : list[str]
    """
    warnings: list[str] = []

    r_int, e = _require_positive(pack_r_int_ohm, "pack_r_int_ohm")
    if e:
        return {"ok": False, "reason": e}
    i_a, e = _require_nonneg(discharge_current_a, "discharge_current_a")
    if e:
        return {"ok": False, "reason": e}
    t_s, e = _require_positive(discharge_time_s, "discharge_time_s")
    if e:
        return {"ok": False, "reason": e}
    m_g, e = _require_positive(pack_mass_g, "pack_mass_g")
    if e:
        return {"ok": False, "reason": e}
    c_j, e = _require_positive(specific_heat_j_kg_c, "specific_heat_j_kg_c")
    if e:
        return {"ok": False, "reason": e}

    m_kg = m_g / 1000.0
    heat_j = i_a ** 2 * r_int * t_s
    delta_t = heat_j / (m_kg * c_j) if m_kg > 0 else 0.0

    if delta_t > 20.0:
        warnings.append(
            f"Adiabatic temperature rise {delta_t:.1f} °C is high; "
            "consider thermal management"
        )

    return {
        "ok": True,
        "heat_generated_j": round(heat_j, 4),
        "delta_T_c": round(delta_t, 4),
        "warnings": warnings,
    }


# ── Combined pack report ───────────────────────────────────────────────────────

def pack_report(
    target_voltage_v: float,
    target_capacity_ah: float,
    cell_voltage_v: float,
    cell_capacity_ah: float,
    load_profile: list[dict],
    peukert_k: float = 1.1,
    dod_limit: float = 0.8,
    charge_c_rate: float = 0.5,
    cell_mass_g: float | None = None,
    cell_volume_cm3: float | None = None,
    cell_r_int_ohm: float | None = None,
    cell_max_discharge_c: float | None = None,
) -> dict:
    """
    Combined sizing + runtime + charge-time + thermal report.

    Calls size_pack, estimate_runtime, estimate_charge_time (and
    estimate_thermal_rise when cell_r_int_ohm and cell_mass_g are given).

    Returns
    -------
    dict with keys:
        ok          : bool
        pack        : dict — output of size_pack
        runtime     : dict — output of estimate_runtime
        charge      : dict — output of estimate_charge_time
        thermal     : dict | None — output of estimate_thermal_rise
        warnings    : list[str] — combined warnings from all sub-calls
    """
    all_warnings: list[str] = []

    pack = size_pack(
        target_voltage_v=target_voltage_v,
        target_capacity_ah=target_capacity_ah,
        cell_voltage_v=cell_voltage_v,
        cell_capacity_ah=cell_capacity_ah,
        cell_mass_g=cell_mass_g,
        cell_volume_cm3=cell_volume_cm3,
        cell_r_int_ohm=cell_r_int_ohm,
        cell_max_discharge_c=cell_max_discharge_c,
    )
    if not pack["ok"]:
        return {"ok": False, "reason": pack["reason"]}
    all_warnings.extend(pack.get("warnings", []))

    runtime = estimate_runtime(
        pack_capacity_ah=pack["pack_capacity_ah"],
        pack_voltage_v=pack["pack_voltage_v"],
        load_profile=load_profile,
        peukert_k=peukert_k,
        dod_limit=dod_limit,
        cell_max_discharge_c=cell_max_discharge_c,
        pack_r_int_ohm=pack.get("pack_r_int_ohm"),
    )
    if not runtime["ok"]:
        return {"ok": False, "reason": runtime["reason"]}
    all_warnings.extend(runtime.get("warnings", []))

    charge = estimate_charge_time(
        pack_capacity_ah=pack["pack_capacity_ah"],
        charge_c_rate=charge_c_rate,
        dod_at_start=dod_limit,
    )
    if not charge["ok"]:
        return {"ok": False, "reason": charge["reason"]}
    all_warnings.extend(charge.get("warnings", []))

    thermal = None
    if pack.get("pack_r_int_ohm") is not None and pack.get("pack_mass_g") is not None:
        # Use worst-case current from profile
        if runtime["steps"]:
            max_i = max(s["current_a"] for s in runtime["steps"])
            thermal = estimate_thermal_rise(
                pack_r_int_ohm=pack["pack_r_int_ohm"],
                discharge_current_a=max_i,
                discharge_time_s=runtime["runtime_s"],
                pack_mass_g=pack["pack_mass_g"],
            )
            if thermal and thermal["ok"]:
                all_warnings.extend(thermal.get("warnings", []))

    return {
        "ok": True,
        "pack": pack,
        "runtime": runtime,
        "charge": charge,
        "thermal": thermal,
        "warnings": all_warnings,
    }
