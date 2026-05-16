"""
Magnetics design — power transformer & inductor (pure Python, math only).

Distinct from:
  kerf_electronics.powerconv   — converter topology (duty cycle, L, C values)
  kerf_electronics.gatedrive   — gate driver sizing
  kerf_electronics.pdn         — power distribution network
  kerf_electronics.motordrive  — motor & inverter drive

Capabilities
------------
core_select_ap
    Core selection by area-product Ap = Wa × Ae = P / (K × Bmax × J × fsw)
    Returns required Ap [m⁴] and identifies the smallest matching core from
    the built-in table (ferrite ETD/EE/PQ/toroid + powder toroid families).

core_select_kg
    Core selection by the geometric constant Kg = Ae² × Wa / MLT,
    which accounts for winding resistance targets directly.

transformer_primary_turns
    Faraday's law for a transformer:
        Np = V / (4.44 × f × Bmax × Ae)    (sinusoidal / full-bridge)
        Np = V / (4 × f × Bmax × Ae)       (square-wave / half-bridge)

inductor_turns
    Ampere's law for an inductor:
        N = L × I_peak / (Bmax × Ae)

turns_ratio
    Transformer turns ratio: n = Np / Ns = Vp / Vs  (ideal, lossless)

gap_length
    Air-gap length for a gapped inductor (energy storage):
        lg = μ0 × N² × Ae / L  (fringing neglected first pass)
    Iterates for fringing using lg_eff = lg × (1 + lg/sqrt(Ae) × ln(2×w/lg))
    Returns AL (inductance per turn²) = L / N² with gap.

awg_from_current
    Wire AWG selection from RMS current and current density J [A/m²].
    Returns AWG gauge, bare diameter, resistance per metre (at DC, 20 °C).

skin_depth
    δ = sqrt(ρ / (π × f × μ0 × μr))  [m]
    Default ρ = 1.72e-8 Ω·m (copper), μr = 1.

dowell_ac_factor
    Dowell's model for AC resistance factor Fr = Rac / Rdc:
        Fr = Δ/2 × [M1(Δ) + 2(m²−1)/3 × M2(Δ)]
    where Δ = d / (δ × sqrt(η)), m = number of layers, η = packing factor,
    d = bare wire diameter.
    Returns Fr, skin-proximity multiplier, and effective AC resistance factor.

steinmetz_core_loss
    Steinmetz equation for volumetric core loss:
        Pv [W/m³] = k × f^α × Bpk^β
    Material table included for common ferrites (N87, N97, 3C95, PC95, ML91S)
    and powder cores (Kool Mµ 40u, 60u, 90u, Mega Flux 60u, 26u).

copper_loss
    DC copper loss + AC (Dowell) copper loss for a winding:
        P_cu = I_dc_rms² × Rdc + I_ac_rms² × (Rdc × (Fr − 1))
    Returns DC component, AC component, and total.

total_loss
    Core loss + copper loss (all windings) → total transformer/inductor loss [W].

temperature_rise
    Temperature rise using surface-area thermal model:
        ΔT = P_total / (h × A_surface)   with h ≈ 10 W/(m²·K) (natural convection)
    or from an explicit thermal resistance Rth:
        ΔT = P_total × Rth
    Flags over-temperature if T_ambient + ΔT > T_max.

flyback_transformer
    Flyback transformer specifics: turns ratio, primary turns (discontinuous
    boundary / continuous), peak primary current, secondary peak, reflected
    voltage, leakage estimate, reset voltage, output diode stress.

forward_transformer
    Forward converter transformer: magnetising inductance, reset winding turns,
    primary/secondary turns, switch stress, core reset check.

push_pull_transformer
    Push-pull transformer: turns ratio, volts-per-turn, core flux swing,
    primary/secondary turns.  Uses Np = V / (2 × f × Bmax × Ae) (half cycle).

leakage_inductance_estimate
    First-order leakage inductance estimate:
        Llk = μ0 × Np² × lw / (3 × bw) × (hw_p + hw_s / 3 + hw_ins)
    where lw = mean turn length, bw = winding breadth, hw = winding heights,
    hw_ins = insulation gap height.

saturation_check
    Check that peak flux density stays below Bsat for the given core material.
    Returns B_peak, B_sat, margin, and a saturation flag.

window_utilization
    Window utilisation (fill factor):
        Ku = (sum of conductor cross-sections) / Wa
    Flags over-fill (Ku > K_max, typically 0.4 for transformers, 0.6 for inductors).

All functions are pure Python (math module only) and follow the kerf
never-raise contract: validation errors are returned as dicts with
{ok: False, reason: str}; condition flags and limit violations are issued
via warnings.warn; exceptions are never raised to callers.

References
----------
  McLyman, "Transformer and Inductor Design Handbook" (4th ed., CRC Press, 2011)
  Erickson & Maksimovic, "Fundamentals of Power Electronics" (3rd ed., 2020)
  Venkataraman, "Magnetics Design for Switching Power Supplies" (TI SLUP127, 2002)
  Dowell, "Effects of Eddy Currents in Transformer Windings" (Proc. IEE, 1966)
  Steinmetz, "On the Law of Hysteresis" (AIEE Trans., 1892; modern form)

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Dict, List, Optional, Tuple

# ── Physical constants ────────────────────────────────────────────────────────

_MU0 = 4.0 * math.pi * 1e-7       # vacuum permeability [H/m]
_RHO_CU = 1.72e-8                  # copper resistivity [Ω·m] at 20 °C
_H_CONV = 10.0                     # natural convection coefficient [W/(m²·K)]

# ── AWG table: (gauge, bare_dia_m, resistance_per_m_ohm) ─────────────────────
# Source: IEC 60228 / ASTM B258, values at 20 °C

_AWG_TABLE: List[Tuple[int, float, float]] = [
    # AWG, diameter [m], Rdc [Ω/m]
    (10, 2.588e-3, 3.277e-3),
    (12, 2.053e-3, 5.211e-3),
    (14, 1.628e-3, 8.286e-3),
    (16, 1.291e-3, 1.317e-2),
    (18, 1.024e-3, 2.094e-2),
    (20, 0.812e-3, 3.327e-2),
    (22, 0.644e-3, 5.292e-2),
    (24, 0.511e-3, 8.408e-2),
    (26, 0.405e-3, 1.335e-1),
    (28, 0.321e-3, 2.121e-1),
    (30, 0.255e-3, 3.368e-1),
    (32, 0.202e-3, 5.350e-1),
    (34, 0.160e-3, 8.503e-1),
    (36, 0.127e-3, 1.352),
    (38, 0.101e-3, 2.148),
    (40, 0.0799e-3, 3.415),
]

# ── Core material table ───────────────────────────────────────────────────────
# Keys: k [W/m³], alpha (frequency exponent), beta (flux exponent), Bsat [T]
# Steinmetz: Pv = k × f^alpha × Bpk^beta  (Pv in W/m³, f in Hz, Bpk in T)

CORE_MATERIALS: Dict[str, dict] = {
    # Ferrite — soft MnZn (100 kHz range)
    "N87": {
        "k": 16.9, "alpha": 1.36, "beta": 2.86,
        "Bsat": 0.39, "mu_i": 2200,
        "note": "TDK N87 MnZn ferrite, 25–500 kHz",
    },
    "N97": {
        "k": 7.0, "alpha": 1.36, "beta": 2.62,
        "Bsat": 0.45, "mu_i": 2300,
        "note": "TDK N97 MnZn ferrite, low-loss 100–500 kHz",
    },
    "3C95": {
        "k": 5.5, "alpha": 1.30, "beta": 2.90,
        "Bsat": 0.43, "mu_i": 3000,
        "note": "Ferroxcube 3C95 MnZn ferrite, 25–500 kHz",
    },
    "PC95": {
        "k": 4.0, "alpha": 1.46, "beta": 2.75,
        "Bsat": 0.47, "mu_i": 3300,
        "note": "TDK PC95 MnZn ferrite, 100 kHz–1 MHz",
    },
    "ML91S": {
        "k": 12.0, "alpha": 1.60, "beta": 2.80,
        "Bsat": 0.35, "mu_i": 10000,
        "note": "Hitachi ML91S MnZn power ferrite",
    },
    # Powder cores — higher Bsat, distributed gap, good DC bias
    "KOOL_MU_40": {
        "k": 150.0, "alpha": 1.20, "beta": 2.10,
        "Bsat": 1.05, "mu_i": 40,
        "note": "Magnetics Kool Mµ 40µ, DC-bias stable inductor",
    },
    "KOOL_MU_60": {
        "k": 200.0, "alpha": 1.20, "beta": 2.10,
        "Bsat": 1.05, "mu_i": 60,
        "note": "Magnetics Kool Mµ 60µ",
    },
    "KOOL_MU_90": {
        "k": 260.0, "alpha": 1.20, "beta": 2.10,
        "Bsat": 1.05, "mu_i": 90,
        "note": "Magnetics Kool Mµ 90µ",
    },
    "MEGA_FLUX_26": {
        "k": 60.0, "alpha": 1.25, "beta": 2.20,
        "Bsat": 1.50, "mu_i": 26,
        "note": "Chang Sung Mega Flux 26µ powder, high-Bsat",
    },
    "MEGA_FLUX_60": {
        "k": 90.0, "alpha": 1.25, "beta": 2.20,
        "Bsat": 1.40, "mu_i": 60,
        "note": "Chang Sung Mega Flux 60µ powder",
    },
}

# ── Core geometry catalogue ───────────────────────────────────────────────────
# Each entry: name, Ae [m²], Wa [m²], MLT [m], Vc [m³], As [m²]
# Ae = effective cross-section, Wa = window area, MLT = mean length of turn,
# Vc = core volume, As = surface area (for thermal model)
# Sources: Ferroxcube / TDK data sheets (nominal values)

CORE_CATALOGUE: List[dict] = [
    # ETD cores
    {"name": "ETD29", "Ae": 0.476e-4, "Wa": 0.94e-4,  "MLT": 0.057, "Vc": 3.46e-6,  "As": 24.2e-4},
    {"name": "ETD34", "Ae": 0.972e-4, "Wa": 1.23e-4,  "MLT": 0.064, "Vc": 7.7e-6,   "As": 35.0e-4},
    {"name": "ETD39", "Ae": 1.25e-4,  "Wa": 1.77e-4,  "MLT": 0.072, "Vc": 11.5e-6,  "As": 47.4e-4},
    {"name": "ETD44", "Ae": 1.73e-4,  "Wa": 2.13e-4,  "MLT": 0.082, "Vc": 18.0e-6,  "As": 60.8e-4},
    {"name": "ETD49", "Ae": 2.11e-4,  "Wa": 2.71e-4,  "MLT": 0.091, "Vc": 24.0e-6,  "As": 76.2e-4},
    # EE cores
    {"name": "EE25",  "Ae": 0.40e-4,  "Wa": 0.52e-4,  "MLT": 0.046, "Vc": 2.35e-6,  "As": 19.5e-4},
    {"name": "EE30",  "Ae": 0.60e-4,  "Wa": 0.90e-4,  "MLT": 0.056, "Vc": 4.80e-6,  "As": 28.0e-4},
    {"name": "EE40",  "Ae": 1.00e-4,  "Wa": 1.50e-4,  "MLT": 0.072, "Vc": 9.60e-6,  "As": 44.0e-4},
    # PQ cores
    {"name": "PQ20",  "Ae": 0.617e-4, "Wa": 0.566e-4, "MLT": 0.044, "Vc": 3.8e-6,   "As": 23.0e-4},
    {"name": "PQ26",  "Ae": 1.19e-4,  "Wa": 0.988e-4, "MLT": 0.055, "Vc": 7.9e-6,   "As": 34.5e-4},
    {"name": "PQ32",  "Ae": 1.61e-4,  "Wa": 1.61e-4,  "MLT": 0.069, "Vc": 13.5e-6,  "As": 47.0e-4},
    {"name": "PQ35",  "Ae": 1.98e-4,  "Wa": 1.98e-4,  "MLT": 0.076, "Vc": 17.8e-6,  "As": 55.5e-4},
    # Toroid
    {"name": "T60x32", "Ae": 2.50e-4, "Wa": 8.00e-4,  "MLT": 0.146, "Vc": 24.0e-6,  "As": 72.0e-4},
    {"name": "T80x40", "Ae": 4.00e-4, "Wa": 12.6e-4,  "MLT": 0.188, "Vc": 45.0e-6,  "As": 108.e-4},
]

# ── Input validation helpers ──────────────────────────────────────────────────


def _chk_pos(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive finite number, got {value!r}"
    return None


def _chk_nonneg(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _chk_frac(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0 or value >= 1:
        return f"{name} must be in (0, 1), got {value!r}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. core_select_ap — area-product core selection
# ═══════════════════════════════════════════════════════════════════════════════

def core_select_ap(
    power_va: float,
    freq_hz: float,
    bmax_t: float,
    j_am2: float = 4.0e6,
    kw: float = 0.4,
    kt: float = 1.0,
) -> dict:
    """
    Select a magnetic core using the area-product method.

    Area product:
        Ap = Wa × Ae = (power_va) / (kt × kw × Bmax × J × fsw)

    where:
        power_va — apparent power handled by the core [VA]
                   For a transformer use S = (Pin + Pout)/2 = Pout/η × (1 + η)/2
                   For an inductor use S = L × I_pk² × fsw / 2
        freq_hz  — switching frequency (or line frequency for mains transformer) [Hz]
        bmax_t   — peak flux density [T]
        j_am2    — current density [A/m²] (default 4 MA/m² = 4 A/mm²)
        kw       — window utilisation factor (default 0.4 for transformers,
                   0.6 for inductors)
        kt       — topology constant (default 1.0 for single-winding inductor;
                   use 0.5 for half-bridge, 0.25 for push-pull transformer)

    The smallest core from the built-in catalogue whose Ap ≥ required Ap is
    returned.  If no core is large enough, the largest available is returned
    with a warning.

    Returns
    -------
    dict: ok, ap_required_m4, ap_unit_cm4, selected_core (dict), all_candidates (list)
    """
    for name, val in [("power_va", power_va), ("freq_hz", freq_hz),
                      ("bmax_t", bmax_t), ("j_am2", j_am2), ("kw", kw)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    if kt <= 0:
        return {"ok": False, "reason": "kt must be positive"}

    ap_req = power_va / (kt * kw * bmax_t * j_am2 * freq_hz)

    # Find candidates
    candidates = []
    for core in CORE_CATALOGUE:
        ap_core = core["Ae"] * core["Wa"]
        if ap_core >= ap_req:
            candidates.append({**core, "Ap_m4": ap_core, "margin": (ap_core - ap_req) / ap_req})

    candidates.sort(key=lambda c: c["Ap_m4"])

    if candidates:
        selected = candidates[0]
    else:
        # All cores too small — return largest with warning
        biggest = max(CORE_CATALOGUE, key=lambda c: c["Ae"] * c["Wa"])
        selected = {**biggest, "Ap_m4": biggest["Ae"] * biggest["Wa"], "margin": None}
        warnings.warn(
            f"core_select_ap: no core in catalogue meets Ap_required = "
            f"{ap_req*1e8:.3f} cm⁴; returning largest available ({biggest['name']}). "
            "Consider a custom wound toroid or parallel cores.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "ap_required_m4": ap_req,
        "ap_required_cm4": round(ap_req * 1e8, 6),
        "bmax_t": bmax_t,
        "j_am2": j_am2,
        "kw": kw,
        "kt": kt,
        "selected_core": selected,
        "candidates": candidates[:5],  # top-5 smallest sufficient cores
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. core_select_kg — geometric-constant core selection
# ═══════════════════════════════════════════════════════════════════════════════

def core_select_kg(
    power_va: float,
    freq_hz: float,
    bmax_t: float,
    rho_cu: float = _RHO_CU,
    j_am2: float = 4.0e6,
    kw: float = 0.4,
    rdc_target_ohm: float = 0.1,
) -> dict:
    """
    Select a core using the geometric constant Kg = Ae² × Wa / MLT.

    Kg method (McLyman §3.4):
        Kg = (rho_cu × power_va²) / (2 × kw² × Bmax² × J² × P_cu_target)

    where P_cu_target = rdc_target_ohm × (power_va / Vp)² is approximated as
        P_cu_target ≈ power_va × (rdc_target_ohm × j_am2 / bmax_t)

    For a quick design guide the simplified form is:
        Kg_req ≈ rho_cu × power_va / (2 × kw × Bmax² × J × freq_hz × rdc_target_ohm)

    Returns the smallest core whose Kg ≥ Kg_required.

    Returns
    -------
    dict: ok, kg_required_m5, selected_core, all_candidates
    """
    for name, val in [("power_va", power_va), ("freq_hz", freq_hz),
                      ("bmax_t", bmax_t), ("j_am2", j_am2), ("kw", kw),
                      ("rdc_target_ohm", rdc_target_ohm)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    # Simplified Kg requirement (McLyman §3.4, equation adjusted for SI)
    kg_req = (rho_cu * power_va) / (2.0 * kw * bmax_t ** 2 * j_am2 * freq_hz * rdc_target_ohm)

    candidates = []
    for core in CORE_CATALOGUE:
        if core["MLT"] <= 0:
            continue
        kg_core = (core["Ae"] ** 2 * core["Wa"]) / core["MLT"]
        if kg_core >= kg_req:
            candidates.append({**core, "Kg_m5": kg_core, "margin": (kg_core - kg_req) / kg_req})

    candidates.sort(key=lambda c: c["Kg_m5"])

    if candidates:
        selected = candidates[0]
    else:
        biggest = max(CORE_CATALOGUE, key=lambda c: (c["Ae"] ** 2 * c["Wa"]) / c["MLT"])
        selected = {**biggest, "Kg_m5": (biggest["Ae"] ** 2 * biggest["Wa"]) / biggest["MLT"], "margin": None}
        warnings.warn(
            f"core_select_kg: no core meets Kg_required = {kg_req:.3e} m⁵; "
            f"returning largest ({biggest['name']}).",
            stacklevel=2,
        )

    return {
        "ok": True,
        "kg_required_m5": kg_req,
        "selected_core": selected,
        "candidates": candidates[:5],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. transformer_primary_turns
# ═══════════════════════════════════════════════════════════════════════════════

def transformer_primary_turns(
    v_primary: float,
    freq_hz: float,
    bmax_t: float,
    ae_m2: float,
    waveform: str = "square",
) -> dict:
    """
    Primary turns from Faraday's law.

    For a square-wave (half-bridge / full-bridge hard-switched):
        Np = V / (4 × f × Bmax × Ae)         [McLyman §4.2]

    For a sinusoidal waveform (mains transformer):
        Np = V / (4.44 × f × Bmax × Ae)      (4.44 = π/√2 × √2 = 4.44)

    Parameters
    ----------
    v_primary : float — primary RMS voltage [V]
    freq_hz   : float — frequency [Hz]
    bmax_t    : float — peak flux density [T] (use 80-90 % of Bsat for margin)
    ae_m2     : float — effective core cross-section [m²]
    waveform  : str   — 'square' or 'sine' (default 'square')

    Returns
    -------
    dict: ok, Np (float, round up), Np_exact, waveform, formula_constant
    """
    for name, val in [("v_primary", v_primary), ("freq_hz", freq_hz),
                      ("bmax_t", bmax_t), ("ae_m2", ae_m2)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    waveform = waveform.lower().strip()
    if waveform not in ("square", "sine"):
        return {"ok": False, "reason": "waveform must be 'square' or 'sine'"}

    k = 4.0 if waveform == "square" else 4.44

    np_exact = v_primary / (k * freq_hz * bmax_t * ae_m2)
    np_int = math.ceil(np_exact)

    return {
        "ok": True,
        "Np": np_int,
        "Np_exact": round(np_exact, 4),
        "waveform": waveform,
        "formula_constant": k,
        "formula": f"Np = V / ({k} × f × Bmax × Ae)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. inductor_turns
# ═══════════════════════════════════════════════════════════════════════════════

def inductor_turns(
    inductance_h: float,
    i_peak_a: float,
    bmax_t: float,
    ae_m2: float,
) -> dict:
    """
    Inductor turns from Ampere's law:

        N = L × I_peak / (Bmax × Ae)

    Parameters
    ----------
    inductance_h : float — required inductance [H]
    i_peak_a     : float — peak current (including ripple) [A]
    bmax_t       : float — peak allowable flux density [T]
    ae_m2        : float — effective core cross-section [m²]

    Returns
    -------
    dict: ok, N (int, ceil), N_exact
    """
    for name, val in [("inductance_h", inductance_h), ("i_peak_a", i_peak_a),
                      ("bmax_t", bmax_t), ("ae_m2", ae_m2)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    n_exact = (inductance_h * i_peak_a) / (bmax_t * ae_m2)
    n_int = math.ceil(n_exact)

    return {
        "ok": True,
        "N": n_int,
        "N_exact": round(n_exact, 4),
        "formula": "N = L × I_peak / (Bmax × Ae)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. turns_ratio
# ═══════════════════════════════════════════════════════════════════════════════

def turns_ratio(
    v_primary: float,
    v_secondary: float,
    np_actual: Optional[int] = None,
    ns_actual: Optional[int] = None,
) -> dict:
    """
    Ideal transformer turns ratio n = Np / Ns = Vp / Vs.

    If actual turns are provided the voltage regulation error is also computed.

    Returns
    -------
    dict: ok, n_ideal, n_actual (if turns provided), v_secondary_actual, reg_error_pct
    """
    for name, val in [("v_primary", v_primary), ("v_secondary", v_secondary)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    n_ideal = v_primary / v_secondary
    result: dict = {
        "ok": True,
        "n_ideal": round(n_ideal, 6),
        "Np_ideal_per_Ns1": round(n_ideal, 4),
    }

    if np_actual is not None and ns_actual is not None:
        if np_actual <= 0 or ns_actual <= 0:
            return {"ok": False, "reason": "np_actual and ns_actual must be positive integers"}
        n_actual = np_actual / ns_actual
        vs_actual = v_primary / n_actual
        reg_error = (vs_actual - v_secondary) / v_secondary * 100.0
        result["n_actual"] = round(n_actual, 6)
        result["v_secondary_actual_v"] = round(vs_actual, 4)
        result["turns_reg_error_pct"] = round(reg_error, 3)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. gap_length
# ═══════════════════════════════════════════════════════════════════════════════

def gap_length(
    inductance_h: float,
    n_turns: int,
    ae_m2: float,
    mu_i: float = 2200.0,
    fringing_iter: int = 3,
) -> dict:
    """
    Air-gap length for a gapped inductor.

    Ungapped formula (energy storage in gap, μ_core >> μ_gap):
        lg = μ0 × N² × Ae / L

    Fringing correction (Wheeler / McLyman §5.3):
        lg_eff = lg / (1 + (lg / sqrt(Ae)) × ln(2 × sqrt(Ae) / lg))
    Iterated fringing_iter times for convergence.

    AL (inductance factor):
        AL = μ0 × Ae / (lg + le/μi)

    where le = effective magnetic path length ≈ sqrt(Ae) × (π or typical for geometry);
    here we use le ≈ 10 × sqrt(Ae) as a typical approximation for gapped cores.

    Returns
    -------
    dict: ok, lg_m, lg_mm, AL_nH_per_turn2, inductance_check_h, fringing_factor
    """
    for name, val in [("inductance_h", inductance_h), ("ae_m2", ae_m2), ("mu_i", mu_i)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    if not isinstance(n_turns, int) or n_turns <= 0:
        return {"ok": False, "reason": "n_turns must be a positive integer"}

    # First-order gap
    lg = _MU0 * n_turns ** 2 * ae_m2 / inductance_h

    # Fringing factor iteration
    fringing_factor = 1.0
    lg_eff = lg
    for _ in range(fringing_iter):
        if lg_eff > 0:
            denom = 1.0 + (lg_eff / math.sqrt(ae_m2)) * math.log(2.0 * math.sqrt(ae_m2) / lg_eff)
            if denom > 0:
                fringing_factor = 1.0 / denom
                lg_eff = lg * fringing_factor
            else:
                break

    # Effective magnetic path length approximation
    le_approx = 10.0 * math.sqrt(ae_m2)
    al = _MU0 * ae_m2 / (lg_eff + le_approx / mu_i)
    l_check = al * n_turns ** 2

    return {
        "ok": True,
        "lg_m": round(lg, 9),
        "lg_mm": round(lg * 1e3, 4),
        "lg_eff_mm": round(lg_eff * 1e3, 4),
        "fringing_factor": round(fringing_factor, 5),
        "AL_nH_per_turn2": round(al * 1e9, 4),
        "inductance_check_h": round(l_check, 12),
        "note": "Fringing correction per Wheeler/McLyman §5.3; verify with measured AL.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 7. awg_from_current
# ═══════════════════════════════════════════════════════════════════════════════

def awg_from_current(
    i_rms_a: float,
    j_am2: float = 4.0e6,
) -> dict:
    """
    Select wire AWG from RMS current and current density.

    Required bare conductor cross-section:
        A_wire = I_rms / J  [m²]

    Returns the finest AWG (largest gauge number) whose cross-section ≥ A_wire.

    Returns
    -------
    dict: ok, awg, diameter_m, diameter_mm, area_m2, rdc_ohm_per_m,
          actual_j_am2, required_area_m2
    """
    for name, val in [("i_rms_a", i_rms_a), ("j_am2", j_am2)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    a_req = i_rms_a / j_am2

    selected = None
    for awg, dia, rdc in _AWG_TABLE:
        a_wire = math.pi * (dia / 2.0) ** 2
        if a_wire >= a_req:
            selected = (awg, dia, rdc, a_wire)
            break  # table is ordered finest (smallest area) to coarsest; we want first that fits

    # Reverse: table is coarse→fine; sort so smallest area is last
    # Actually, table above is ordered from largest to smallest diameter.
    # AWG 10 = 2.588mm (biggest) ... AWG 40 = 0.0799mm (smallest).
    # We want the SMALLEST wire that still fits (finest AWG = highest number).
    # Iterate in reverse to find largest AWG number whose area >= a_req.
    selected = None
    for awg, dia, rdc in reversed(_AWG_TABLE):
        a_wire = math.pi * (dia / 2.0) ** 2
        if a_wire >= a_req:
            selected = (awg, dia, rdc, a_wire)

    if selected is None:
        # Need larger than AWG 10
        awg10, dia10, rdc10 = _AWG_TABLE[0]
        a10 = math.pi * (dia10 / 2.0) ** 2
        selected = (awg10, dia10, rdc10, a10)
        warnings.warn(
            f"awg_from_current: required area {a_req*1e6:.4f} mm² exceeds AWG 10 "
            f"({a10*1e6:.4f} mm²); consider parallel conductors or litz wire.",
            stacklevel=2,
        )

    awg_n, dia_m, rdc_opm, a_actual = selected
    j_actual = i_rms_a / a_actual

    return {
        "ok": True,
        "awg": awg_n,
        "diameter_m": round(dia_m, 7),
        "diameter_mm": round(dia_m * 1e3, 4),
        "area_m2": round(a_actual, 12),
        "area_mm2": round(a_actual * 1e6, 5),
        "rdc_ohm_per_m": round(rdc_opm, 6),
        "required_area_m2": round(a_req, 12),
        "actual_j_am2": round(j_actual, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. skin_depth
# ═══════════════════════════════════════════════════════════════════════════════

def skin_depth(
    freq_hz: float,
    rho_ohm_m: float = _RHO_CU,
    mu_r: float = 1.0,
) -> dict:
    """
    Skin depth:
        δ = sqrt(ρ / (π × f × μ0 × μr))  [m]

    Parameters
    ----------
    freq_hz    : float — frequency [Hz]
    rho_ohm_m  : float — resistivity [Ω·m] (default: copper 1.72e-8)
    mu_r       : float — relative permeability (default 1.0 for copper)

    Returns
    -------
    dict: ok, delta_m, delta_mm, delta_um
    """
    for name, val in [("freq_hz", freq_hz), ("rho_ohm_m", rho_ohm_m), ("mu_r", mu_r)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    delta = math.sqrt(rho_ohm_m / (math.pi * freq_hz * _MU0 * mu_r))

    return {
        "ok": True,
        "delta_m": delta,
        "delta_mm": round(delta * 1e3, 6),
        "delta_um": round(delta * 1e6, 4),
        "formula": "δ = sqrt(ρ / (π × f × μ0 × μr))",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 9. dowell_ac_factor
# ═══════════════════════════════════════════════════════════════════════════════

def dowell_ac_factor(
    freq_hz: float,
    wire_dia_m: float,
    n_layers: int,
    packing_factor: float = 0.785,
    rho_ohm_m: float = _RHO_CU,
) -> dict:
    """
    Dowell's model for winding AC resistance factor Fr = Rac / Rdc.

    Reference: Dowell, "Effects of Eddy Currents in Transformer Windings",
    Proc. IEE vol. 113 no. 8 (1966); also McLyman §8.5.

    Dowell parameter:
        Δ = (d / δ) × sqrt(η_layer)
        where d = wire diameter, δ = skin depth, η_layer = packing factor
              (default 0.785 = π/4 for round wires in a layer)

    AC resistance factor:
        Fr = (Δ/2) × [M1 + 2(m²−1)/3 × M2]
        M1 = sinh(Δ) + sin(Δ) / (cosh(Δ) − cos(Δ))
        M2 = sinh(Δ) − sin(Δ) / (cosh(Δ) + cos(Δ))
        m = n_layers

    Parameters
    ----------
    freq_hz        : float — frequency [Hz]
    wire_dia_m     : float — bare wire diameter [m]
    n_layers       : int   — number of winding layers
    packing_factor : float — η, strand packing factor (default π/4 ≈ 0.785)
    rho_ohm_m      : float — conductor resistivity [Ω·m] (default copper)

    Returns
    -------
    dict: ok, Fr, delta, M1, M2, n_layers, skin_depth_m
    """
    for name, val in [("freq_hz", freq_hz), ("wire_dia_m", wire_dia_m),
                      ("packing_factor", packing_factor), ("rho_ohm_m", rho_ohm_m)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    if not isinstance(n_layers, int) or n_layers < 1:
        return {"ok": False, "reason": "n_layers must be a positive integer"}

    sd_res = skin_depth(freq_hz, rho_ohm_m=rho_ohm_m)
    if not sd_res["ok"]:
        return sd_res
    delta_skin = sd_res["delta_m"]

    # Dowell Δ parameter
    big_delta = (wire_dia_m / delta_skin) * math.sqrt(packing_factor)

    # Clamp to avoid overflow in sinh/cosh for very large Δ
    delta_c = min(big_delta, 20.0)

    sinh_d = math.sinh(delta_c)
    cosh_d = math.cosh(delta_c)
    sin_d = math.sin(delta_c)
    cos_d = math.cos(delta_c)

    denom1 = cosh_d - cos_d
    denom2 = cosh_d + cos_d
    if abs(denom1) < 1e-15:
        denom1 = 1e-15
    if abs(denom2) < 1e-15:
        denom2 = 1e-15

    m1 = (sinh_d + sin_d) / denom1
    m2 = (sinh_d - sin_d) / denom2

    m = float(n_layers)
    fr = (delta_c / 2.0) * (m1 + 2.0 * (m ** 2 - 1.0) / 3.0 * m2)

    # Fr must be >= 1 by physics; clamp numerical noise
    fr = max(fr, 1.0)

    return {
        "ok": True,
        "Fr": round(fr, 5),
        "delta": round(big_delta, 5),
        "M1": round(m1, 5),
        "M2": round(m2, 5),
        "n_layers": n_layers,
        "skin_depth_m": round(delta_skin, 9),
        "note": "Dowell (1966). Fr=1 indicates no significant AC effect.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 10. steinmetz_core_loss
# ═══════════════════════════════════════════════════════════════════════════════

def steinmetz_core_loss(
    freq_hz: float,
    b_peak_t: float,
    core_volume_m3: float,
    material: str = "N87",
) -> dict:
    """
    Steinmetz core loss:
        Pv [W/m³] = k × f^α × B_peak^β
        P_core [W] = Pv × Vc

    Parameters
    ----------
    freq_hz       : float — switching frequency [Hz]
    b_peak_t      : float — peak flux density [T] (half the total ΔB for AC excitation)
    core_volume_m3: float — effective core volume [m³]
    material      : str   — material key from CORE_MATERIALS (default 'N87')

    Returns
    -------
    dict: ok, p_volume_w_m3, p_core_w, material, Bsat, b_peak_t, saturation_flag
    """
    for name, val in [("freq_hz", freq_hz), ("b_peak_t", b_peak_t),
                      ("core_volume_m3", core_volume_m3)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    mat = CORE_MATERIALS.get(material)
    if mat is None:
        avail = list(CORE_MATERIALS.keys())
        return {"ok": False, "reason": f"Unknown material '{material}'. Available: {avail}"}

    k = mat["k"]
    alpha = mat["alpha"]
    beta = mat["beta"]
    bsat = mat["Bsat"]

    pv = k * (freq_hz ** alpha) * (b_peak_t ** beta)
    p_core = pv * core_volume_m3

    saturation_flag = b_peak_t >= bsat
    if saturation_flag:
        warnings.warn(
            f"steinmetz_core_loss: B_peak = {b_peak_t:.3f} T exceeds "
            f"Bsat = {bsat:.3f} T for material {material}. Core will saturate!",
            stacklevel=2,
        )

    return {
        "ok": True,
        "p_volume_w_m3": round(pv, 2),
        "p_core_w": round(p_core, 6),
        "material": material,
        "Bsat_t": bsat,
        "b_peak_t": b_peak_t,
        "saturation_flag": saturation_flag,
        "steinmetz_k": k,
        "steinmetz_alpha": alpha,
        "steinmetz_beta": beta,
        "formula": "Pv = k × f^α × Bpk^β",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 11. copper_loss
# ═══════════════════════════════════════════════════════════════════════════════

def copper_loss(
    i_rms_dc_a: float,
    rdc_ohm: float,
    fr: float = 1.0,
    i_rms_ac_a: Optional[float] = None,
) -> dict:
    """
    Winding copper loss (DC + AC Dowell component).

    P_cu_dc = I_dc_rms² × Rdc
    P_cu_ac = I_ac_rms² × Rdc × (Fr − 1)   [incremental AC above DC]
    P_cu_total = I_dc_rms² × Rdc × Fr       (simplified single-tone model)

    For multi-harmonic currents:
        Pass the RMS of the AC harmonic content as i_rms_ac_a and Fr separately.

    Parameters
    ----------
    i_rms_dc_a  : float — total RMS current (DC + AC) [A]
    rdc_ohm     : float — DC resistance of winding [Ω]
    fr          : float — Dowell AC factor Fr = Rac/Rdc (default 1.0 = DC only)
    i_rms_ac_a  : float or None — AC-only RMS current for separate Dowell calc.
                  If None, Fr is applied to i_rms_dc_a directly.

    Returns
    -------
    dict: ok, p_dc_w, p_ac_w, p_total_w, rac_ohm
    """
    for name, val in [("i_rms_dc_a", i_rms_dc_a), ("rdc_ohm", rdc_ohm)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    if fr < 1.0:
        return {"ok": False, "reason": f"fr must be >= 1.0, got {fr!r}"}

    p_dc = i_rms_dc_a ** 2 * rdc_ohm

    if i_rms_ac_a is not None:
        err = _chk_pos(i_rms_ac_a, "i_rms_ac_a")
        if err:
            return {"ok": False, "reason": err}
        p_ac = i_rms_ac_a ** 2 * rdc_ohm * (fr - 1.0)
        p_total = p_dc + p_ac
    else:
        p_total = i_rms_dc_a ** 2 * rdc_ohm * fr
        p_ac = p_total - p_dc

    rac = rdc_ohm * fr

    return {
        "ok": True,
        "p_dc_w": round(p_dc, 8),
        "p_ac_w": round(p_ac, 8),
        "p_total_w": round(p_total, 8),
        "rac_ohm": round(rac, 8),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 12. total_loss
# ═══════════════════════════════════════════════════════════════════════════════

def total_loss(
    p_core_w: float,
    winding_losses_w: List[float],
) -> dict:
    """
    Total transformer/inductor loss = core loss + sum of winding copper losses.

    Parameters
    ----------
    p_core_w          : float — core loss [W]
    winding_losses_w  : list  — list of per-winding copper losses [W]

    Returns
    -------
    dict: ok, p_core_w, p_copper_total_w, p_total_w, efficiency_approx
    """
    err = _chk_nonneg(p_core_w, "p_core_w")
    if err:
        return {"ok": False, "reason": err}
    if not isinstance(winding_losses_w, (list, tuple)) or len(winding_losses_w) == 0:
        return {"ok": False, "reason": "winding_losses_w must be a non-empty list of floats"}
    for i, v in enumerate(winding_losses_w):
        err = _chk_nonneg(v, f"winding_losses_w[{i}]")
        if err:
            return {"ok": False, "reason": err}

    p_copper = sum(winding_losses_w)
    p_total = p_core_w + p_copper

    return {
        "ok": True,
        "p_core_w": round(p_core_w, 6),
        "p_copper_total_w": round(p_copper, 6),
        "p_total_w": round(p_total, 6),
        "winding_losses_w": [round(v, 6) for v in winding_losses_w],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 13. temperature_rise
# ═══════════════════════════════════════════════════════════════════════════════

def temperature_rise(
    p_total_w: float,
    surface_area_m2: Optional[float] = None,
    rth_c_per_w: Optional[float] = None,
    t_ambient_c: float = 25.0,
    t_max_c: float = 100.0,
    h_conv: float = _H_CONV,
) -> dict:
    """
    Temperature rise of the magnetic component.

    Two models (use whichever parameter is provided):

    1. Surface-area (natural convection):
        ΔT = P / (h × A_surface)   with h ≈ 10 W/(m²·K)

    2. Explicit thermal resistance:
        ΔT = P × Rth

    If both are provided, the thermal-resistance model is used.
    A warning is issued when T_ambient + ΔT > T_max.

    Parameters
    ----------
    p_total_w       : float — total loss [W]
    surface_area_m2 : float — core+bobbin surface area [m²]
    rth_c_per_w     : float — thermal resistance [°C/W]
    t_ambient_c     : float — ambient temperature [°C] (default 25 °C)
    t_max_c         : float — maximum allowable temperature [°C] (default 100 °C)
    h_conv          : float — convection coefficient [W/(m²·K)] (default 10)

    Returns
    -------
    dict: ok, delta_t_k, t_total_c, t_margin_k, over_temp
    """
    err = _chk_pos(p_total_w, "p_total_w")
    if err:
        return {"ok": False, "reason": err}
    if surface_area_m2 is None and rth_c_per_w is None:
        return {"ok": False, "reason": "Provide either surface_area_m2 or rth_c_per_w"}

    if rth_c_per_w is not None:
        err = _chk_pos(rth_c_per_w, "rth_c_per_w")
        if err:
            return {"ok": False, "reason": err}
        delta_t = p_total_w * rth_c_per_w
        model = "thermal_resistance"
    else:
        err = _chk_pos(surface_area_m2, "surface_area_m2")
        if err:
            return {"ok": False, "reason": err}
        delta_t = p_total_w / (h_conv * surface_area_m2)
        model = "surface_area_convection"

    t_total = t_ambient_c + delta_t
    t_margin = t_max_c - t_total
    over_temp = t_total > t_max_c

    if over_temp:
        warnings.warn(
            f"temperature_rise: T = {t_total:.1f} °C > T_max = {t_max_c:.1f} °C "
            f"(margin = {t_margin:.1f} K). Increase surface area, add heatsinking, "
            "or reduce losses.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "delta_t_k": round(delta_t, 4),
        "t_total_c": round(t_total, 4),
        "t_max_c": t_max_c,
        "t_margin_k": round(t_margin, 4),
        "over_temp": over_temp,
        "model": model,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 14. flyback_transformer — magnetics-specific parameters
# ═══════════════════════════════════════════════════════════════════════════════

def flyback_transformer(
    v_in: float,
    v_out: float,
    i_out: float,
    fsw: float,
    duty: float,
    ae_m2: float,
    bmax_t: float,
    n_turns_ratio: Optional[float] = None,
    leakage_frac: float = 0.03,
) -> dict:
    """
    Flyback transformer magnetics: primary turns, turns ratio, peak currents,
    leakage inductance estimate, reset voltage, output diode stress.

    Primary turns (Faraday square-wave):
        Np = V_in × D / (f × Bmax × Ae × 2)   [square half-cycle]
        i.e. Np = V_in × D / (2 × f × Bmax × Ae)

    Turns ratio:
        n = Np / Ns = Vin × D / (Vout × (1−D))

    Primary magnetising current peak:
        I_mag_pk = Np × Bmax × Ae / Lm   (derived from Lm = Np² × AL)
        Simplified: I_mag_pk ≈ Vin × D / (Lm × fsw)
        Here we return an energy-storage estimate:
        I_pk_primary ≈ n × Iout / (1−D)   (referred primary, CCM)

    Leakage inductance:
        Llk ≈ leakage_frac × Lm

    Returns
    -------
    dict: ok, Np, Ns, n, i_pk_primary_a, i_pk_secondary_a,
          v_reset_v, v_diode_stress_v, leakage_est_h, warnings
    """
    sol_warnings: List[str] = []

    for name, val in [("v_in", v_in), ("v_out", v_out), ("i_out", i_out),
                      ("fsw", fsw), ("ae_m2", ae_m2), ("bmax_t", bmax_t)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    err = _chk_frac(duty, "duty")
    if err:
        return {"ok": False, "reason": err}

    d_prime = 1.0 - duty

    # Compute n if not given (CCM target D)
    if n_turns_ratio is None:
        n = v_in * duty / (v_out * d_prime)
    else:
        n = n_turns_ratio

    # Primary turns from Faraday (square-wave, half-cycle):
    # ΔB = V_on × t_on / (Np × Ae)  →  Np = Vin × D / (fsw × Bmax × Ae)
    np_exact = v_in * duty / (fsw * bmax_t * ae_m2)
    np_int = math.ceil(np_exact)
    ns_int = max(1, round(np_int / n))

    # Recalculate n from integer turns
    n_actual = np_int / ns_int

    i_pk_primary = n_actual * i_out / d_prime
    i_pk_secondary = i_out / d_prime  # secondary peak = i_out + ΔIs/2, approx

    # Magnetising inductance: Lm ≈ Vin × D / (fsw × ΔI_mag)
    # ΔI_mag ≈ 0.3 × I_pk_primary (30 % ripple assumption)
    lm_approx = v_in * duty / (fsw * 0.3 * i_pk_primary) if i_pk_primary > 0 else 0.0

    # Reset voltage (active-clamp / RCD):
    v_reset = v_in * duty / d_prime  # demagnetisation voltage on primary
    v_diode_stress = v_out + v_in / n_actual  # secondary diode: Vout + Vin/n

    leakage_est = leakage_frac * lm_approx if lm_approx > 0 else 0.0

    if i_pk_primary > 10.0:
        msg = f"high_primary_peak: I_pk_primary = {i_pk_primary:.2f} A; verify MOSFET rating."
        sol_warnings.append(msg)
        warnings.warn(f"flyback_transformer: {msg}", stacklevel=2)

    return {
        "ok": True,
        "Np": np_int,
        "Ns": ns_int,
        "n": round(n_actual, 4),
        "duty": duty,
        "i_pk_primary_a": round(i_pk_primary, 4),
        "i_pk_secondary_a": round(i_pk_secondary, 4),
        "lm_approx_h": round(lm_approx, 9) if lm_approx > 0 else None,
        "v_reset_v": round(v_reset, 4),
        "v_diode_stress_v": round(v_diode_stress, 4),
        "leakage_est_h": round(leakage_est, 11) if leakage_est > 0 else None,
        "warnings": sol_warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 15. forward_transformer
# ═══════════════════════════════════════════════════════════════════════════════

def forward_transformer(
    v_in: float,
    v_out: float,
    i_out: float,
    fsw: float,
    duty_max: float,
    ae_m2: float,
    bmax_t: float,
) -> dict:
    """
    Forward converter transformer magnetics.

    Primary turns (square-wave):
        Np = V_in × D_max / (fsw × ΔB × Ae)
        ΔB = 2 × Bmax (full swing from −Bmax to +Bmax assumed; for one-transistor
        forward the core resets and ΔB = Bmax per half cycle):
        Np = V_in × D_max / (fsw × Bmax × Ae)   (single-switch, reset to 0)

    Reset winding:
        Nr = Np × D_max / (1 − D_max)     (volt-second balance)
        For simple RCD-reset: Nr = Np is common (D ≤ 0.5).

    Switch voltage stress: Vds_max = 2 × Vin  (single-switch with reset winding)

    Returns
    -------
    dict: ok, Np, Ns, Nr, n, duty_max, v_switch_stress_v, warnings
    """
    sol_warnings: List[str] = []

    for name, val in [("v_in", v_in), ("v_out", v_out), ("i_out", i_out),
                      ("fsw", fsw), ("ae_m2", ae_m2), ("bmax_t", bmax_t)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    err = _chk_frac(duty_max, "duty_max")
    if err:
        return {"ok": False, "reason": err}

    if duty_max > 0.5:
        msg = "duty_max > 0.5 for a single-switch forward; reset winding may not provide sufficient flux reset. Consider active clamp."
        sol_warnings.append(msg)
        warnings.warn(f"forward_transformer: {msg}", stacklevel=2)

    np_exact = v_in * duty_max / (fsw * bmax_t * ae_m2)
    np_int = math.ceil(np_exact)

    n = v_in * duty_max / v_out  # ideal turns ratio for output voltage
    ns_int = max(1, round(np_int / n))
    n_actual = np_int / ns_int if ns_int > 0 else n

    # Reset winding (volt-second balance)
    nr_exact = np_int * duty_max / (1.0 - duty_max)
    nr_int = math.ceil(nr_exact)

    v_switch_stress = 2.0 * v_in  # worst case: Vin + reflected reset

    return {
        "ok": True,
        "Np": np_int,
        "Ns": ns_int,
        "Nr": nr_int,
        "n": round(n_actual, 4),
        "duty_max": duty_max,
        "v_switch_stress_v": round(v_switch_stress, 4),
        "warnings": sol_warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 16. push_pull_transformer
# ═══════════════════════════════════════════════════════════════════════════════

def push_pull_transformer(
    v_in: float,
    v_out: float,
    i_out: float,
    fsw: float,
    ae_m2: float,
    bmax_t: float,
) -> dict:
    """
    Push-pull transformer magnetics.

    Each half-cycle sees:  Np × ΔB × Ae = V_in × T/2  →  ΔB = 2 × Bmax
    Volts-per-turn = V_in / (2 × Np)  (for half the switching period)

    Primary turns (full flux swing ±Bmax):
        Np = V_in / (4 × fsw × Bmax × Ae)   [McLyman §4.3]
        (same form as sinusoidal 4.44×f×Bmax×Ae but with constant 4 for square)

    Switch voltage stress: Vds_max = 2 × Vin

    Returns
    -------
    dict: ok, Np, Ns, n, v_per_turn, v_switch_stress_v, warnings
    """
    sol_warnings: List[str] = []

    for name, val in [("v_in", v_in), ("v_out", v_out), ("i_out", i_out),
                      ("fsw", fsw), ("ae_m2", ae_m2), ("bmax_t", bmax_t)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    np_exact = v_in / (4.0 * fsw * bmax_t * ae_m2)
    np_int = math.ceil(np_exact)

    n = v_in / v_out  # turns ratio (no rectifier loss included)
    ns_int = max(1, round(np_int / n))
    n_actual = np_int / ns_int

    v_per_turn = v_in / (2.0 * np_int) if np_int > 0 else 0.0
    v_switch_stress = 2.0 * v_in

    # Saturation check: ΔB = V_in / (2 × Np × fsw × Ae) should be < 2×Bmax
    delta_b = v_in / (2.0 * np_int * fsw * ae_m2) if np_int > 0 and fsw > 0 and ae_m2 > 0 else 0.0
    if delta_b > 2.0 * bmax_t:
        msg = f"core_flux_swing: ΔB = {delta_b:.3f} T > 2×Bmax = {2*bmax_t:.3f} T; increase Np."
        sol_warnings.append(msg)
        warnings.warn(f"push_pull_transformer: {msg}", stacklevel=2)

    return {
        "ok": True,
        "Np": np_int,
        "Ns": ns_int,
        "n": round(n_actual, 4),
        "v_per_turn": round(v_per_turn, 6),
        "delta_b_t": round(delta_b, 5),
        "v_switch_stress_v": round(v_switch_stress, 4),
        "warnings": sol_warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 17. leakage_inductance_estimate
# ═══════════════════════════════════════════════════════════════════════════════

def leakage_inductance_estimate(
    np_turns: int,
    mean_turn_length_m: float,
    winding_breadth_m: float,
    height_primary_m: float,
    height_secondary_m: float,
    height_insulation_m: float = 0.0,
) -> dict:
    """
    First-order leakage inductance referred to primary.

    Model (Dowell / McLyman §9.2):
        Llk = μ0 × Np² × lw / (3 × bw) × (hw_p/3 + hw_ins + hw_s/3)

    where:
        lw  = mean turn length of the winding [m]
        bw  = winding breadth (width of winding window used) [m]
        hw_p, hw_s = primary/secondary winding heights [m]
        hw_ins = insulation layer height [m]

    Parameters
    ----------
    np_turns           : int   — primary turns
    mean_turn_length_m : float — mean turn length [m]
    winding_breadth_m  : float — winding breadth [m]
    height_primary_m   : float — primary winding height [m]
    height_secondary_m : float — secondary winding height [m]
    height_insulation_m: float — insulation gap height [m] (default 0)

    Returns
    -------
    dict: ok, leakage_h, leakage_uH
    """
    for name, val in [
        ("mean_turn_length_m", mean_turn_length_m),
        ("winding_breadth_m", winding_breadth_m),
        ("height_primary_m", height_primary_m),
        ("height_secondary_m", height_secondary_m),
    ]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    if not isinstance(np_turns, int) or np_turns <= 0:
        return {"ok": False, "reason": "np_turns must be a positive integer"}
    err = _chk_nonneg(height_insulation_m, "height_insulation_m")
    if err:
        return {"ok": False, "reason": err}

    llk = (
        _MU0 * np_turns ** 2 * mean_turn_length_m
        / (3.0 * winding_breadth_m)
        * (height_primary_m / 3.0 + height_insulation_m + height_secondary_m / 3.0)
    )

    return {
        "ok": True,
        "leakage_h": round(llk, 12),
        "leakage_uH": round(llk * 1e6, 6),
        "formula": "Llk = μ0 × Np² × lw / (3bw) × (hp/3 + h_ins + hs/3)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 18. saturation_check
# ═══════════════════════════════════════════════════════════════════════════════

def saturation_check(
    n_turns: int,
    i_peak_a: float,
    ae_m2: float,
    le_m: float,
    mu_i: float,
    material: Optional[str] = None,
    bsat_override_t: Optional[float] = None,
) -> dict:
    """
    Check peak flux density against saturation.

    Peak flux density (with gapped or ungapped core):
        B_peak = μ0 × μi × N × I_peak / le

    For a gapped core this is the ungapped estimate; use after gap_length for
    accurate post-gap B_peak.

    Parameters
    ----------
    n_turns         : int   — number of turns
    i_peak_a        : float — peak current (DC + ripple) [A]
    ae_m2           : float — effective cross-section [m²] (used for display only here)
    le_m            : float — effective magnetic path length [m]
    mu_i            : float — initial / effective permeability (use 1 for gapped, μ_gap)
    material        : str   — material key for Bsat lookup (optional)
    bsat_override_t : float — override Bsat [T] (if material not in table)

    Returns
    -------
    dict: ok, b_peak_t, bsat_t, margin_t, saturated, warnings
    """
    sol_warnings: List[str] = []

    for name, val in [("i_peak_a", i_peak_a), ("ae_m2", ae_m2),
                      ("le_m", le_m), ("mu_i", mu_i)]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}
    if not isinstance(n_turns, int) or n_turns <= 0:
        return {"ok": False, "reason": "n_turns must be a positive integer"}

    b_peak = _MU0 * mu_i * n_turns * i_peak_a / le_m

    bsat = None
    if bsat_override_t is not None:
        err = _chk_pos(bsat_override_t, "bsat_override_t")
        if err:
            return {"ok": False, "reason": err}
        bsat = bsat_override_t
    elif material is not None:
        mat = CORE_MATERIALS.get(material)
        if mat is None:
            return {"ok": False, "reason": f"Unknown material '{material}'"}
        bsat = mat["Bsat"]

    saturated = False
    margin = None
    if bsat is not None:
        margin = bsat - b_peak
        saturated = b_peak >= bsat
        if saturated:
            msg = f"saturation_check: B_peak = {b_peak:.3f} T >= Bsat = {bsat:.3f} T. Core saturates!"
            sol_warnings.append(msg)
            warnings.warn(f"saturation_check: {msg}", stacklevel=2)
        elif margin < 0.05 * bsat:
            msg = f"saturation_check: B_peak = {b_peak:.3f} T is within 5 % of Bsat = {bsat:.3f} T; marginal."
            sol_warnings.append(msg)
            warnings.warn(f"saturation_check: {msg}", stacklevel=2)

    return {
        "ok": True,
        "b_peak_t": round(b_peak, 6),
        "bsat_t": round(bsat, 4) if bsat is not None else None,
        "margin_t": round(margin, 6) if margin is not None else None,
        "saturated": saturated,
        "warnings": sol_warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 19. window_utilization
# ═══════════════════════════════════════════════════════════════════════════════

def window_utilization(
    winding_areas_m2: List[float],
    wa_m2: float,
    ku_max: float = 0.4,
) -> dict:
    """
    Window utilisation (fill factor):
        Ku = sum(conductor cross-sections) / Wa

    Flags over-fill when Ku > ku_max.  Typical:
        ku_max = 0.4 for transformers (4-layer insulation, margins)
        ku_max = 0.6 for inductors (simpler insulation)

    Parameters
    ----------
    winding_areas_m2 : list — list of per-winding total conductor cross-sections [m²]
                              (N × A_wire for each winding)
    wa_m2            : float — core window area [m²]
    ku_max           : float — maximum allowed utilisation (default 0.4)

    Returns
    -------
    dict: ok, ku, ku_max, over_fill, margin
    """
    if not isinstance(winding_areas_m2, (list, tuple)) or len(winding_areas_m2) == 0:
        return {"ok": False, "reason": "winding_areas_m2 must be a non-empty list"}
    for i, v in enumerate(winding_areas_m2):
        err = _chk_pos(v, f"winding_areas_m2[{i}]")
        if err:
            return {"ok": False, "reason": err}
    err = _chk_pos(wa_m2, "wa_m2")
    if err:
        return {"ok": False, "reason": err}
    if ku_max <= 0 or ku_max > 1:
        return {"ok": False, "reason": "ku_max must be in (0, 1]"}

    total_area = sum(winding_areas_m2)
    ku = total_area / wa_m2
    over_fill = ku > ku_max
    margin = ku_max - ku

    if over_fill:
        warnings.warn(
            f"window_utilization: Ku = {ku:.3f} > ku_max = {ku_max:.3f}. "
            "Winding does not fit. Use larger core, reduce turns, or use smaller wire.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "ku": round(ku, 5),
        "ku_max": ku_max,
        "over_fill": over_fill,
        "margin": round(margin, 5),
        "total_winding_area_m2": round(total_area, 12),
        "wa_m2": wa_m2,
    }
