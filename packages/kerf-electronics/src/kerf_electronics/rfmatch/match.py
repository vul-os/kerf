"""
RF impedance-matching network synthesis — closed-form pure-Python.

Distinct from:
  • kerf_electronics.si   — signal integrity (Z0, propagation, crosstalk)
  • kerf_electronics.eye  — eye-diagram modelling
  • kerf_electronics.emc  — radiated / conducted EMI pre-compliance

Capabilities
------------
L-section matching (both topologies: shunt-L + series-C, series-L + shunt-C)
    for complex source / load impedances at a given frequency.
    Returns component L/C values and the resulting loaded Q.

Pi-network and T-network synthesis for a target loaded-Q.

Reflection coefficient Γ, VSWR, return loss (dB), and mismatch loss (dB).

Quarter-wave transformer characteristic impedance Z0.

Single-stub matching: series and shunt stub electrical lengths (open/short).

Microstrip synthesis (Hammerstad closed-form):
    width-to-height ratio given Z0 and εr,
    effective permittivity εr_eff,
    impedance from geometry.

All functions return plain dicts {ok: bool, ...}.
Non-realizable / negative-component / high-Q cases are flagged via
warnings.warn; the dict still carries ok=True with a "warnings" list.
Functions never raise.

Physical constants
------------------
Speed of light: c = 2.998e8 m/s.

Author: imranparuk
"""
from __future__ import annotations

import cmath
import math
import warnings
from typing import Optional


# ── Physical constant ────────────────────────────────────────────────────────

_C = 2.998e8   # speed of light [m/s]

# Q threshold above which a "high_Q" warning is issued
_HIGH_Q_THRESHOLD = 50.0


# ── Input validation helpers ─────────────────────────────────────────────────

def _chk_pos(value, name: str) -> Optional[str]:
    """Return error string if value is not a positive real finite number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive real number, got {value!r}"
    return None


def _chk_nonneg(value, name: str) -> Optional[str]:
    """Return error string if value is negative or not a real finite number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _chk_complex(value, name: str) -> Optional[str]:
    """Return error string if value is not a finite complex or real number."""
    if isinstance(value, complex):
        if math.isnan(value.real) or math.isnan(value.imag):
            return f"{name} must be a finite complex number"
        return None
    if isinstance(value, (int, float)):
        if math.isnan(value):
            return f"{name} must be a finite number"
        return None
    return f"{name} must be a number (real or complex), got {type(value).__name__}"


# ── Reflection / VSWR / return-loss / mismatch-loss ─────────────────────────


def reflection_coefficient(
    z_load,
    z0: float = 50.0,
) -> dict:
    """
    Compute the complex reflection coefficient Γ = (Z_L - Z0) / (Z_L + Z0).

    Also computes:
      |Γ|, ∠Γ (degrees), VSWR, return loss [dB], mismatch loss [dB].

    Parameters
    ----------
    z_load : complex or float — load impedance [Ω]
    z0     : float           — reference (system) impedance [Ω] (default 50 Ω)

    Returns
    -------
    dict with keys:
        ok, gamma_re, gamma_im, gamma_mag, gamma_phase_deg,
        vswr, return_loss_db, mismatch_loss_db, z_load_re, z_load_im, z0
    """
    err = _chk_complex(z_load, "z_load")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(z0, "z0")
    if err:
        return {"ok": False, "reason": err}

    zl = complex(z_load)
    denom = zl + z0
    if abs(denom) == 0.0:
        return {"ok": False, "reason": "z_load + z0 == 0; Γ is undefined"}

    gamma = (zl - z0) / denom
    mag = abs(gamma)

    if mag >= 1.0:
        vswr = math.inf
    else:
        vswr = (1.0 + mag) / (1.0 - mag)

    if mag == 0.0:
        rl_db = math.inf
    else:
        rl_db = -20.0 * math.log10(mag)

    # Mismatch loss: fraction of incident power absorbed by load
    # ML [dB] = -10*log10(1 - |Γ|²)
    power_abs = 1.0 - mag ** 2
    if power_abs <= 0.0:
        ml_db = math.inf
    else:
        ml_db = -10.0 * math.log10(power_abs)

    return {
        "ok": True,
        "z_load_re": zl.real,
        "z_load_im": zl.imag,
        "z0": z0,
        "gamma_re": gamma.real,
        "gamma_im": gamma.imag,
        "gamma_mag": round(mag, 8),
        "gamma_phase_deg": round(math.degrees(cmath.phase(gamma)), 4),
        "vswr": round(vswr, 6) if not math.isinf(vswr) else None,
        "return_loss_db": round(rl_db, 4) if not math.isinf(rl_db) else None,
        "mismatch_loss_db": round(ml_db, 6) if not math.isinf(ml_db) else None,
    }


# ── L-section matching network ───────────────────────────────────────────────


def lsection_match(
    z_source,
    z_load,
    freq_hz: float,
) -> dict:
    """
    L-section impedance-matching network synthesis for complex source and load.

    Synthesises both canonical L-section topologies at the given frequency and
    returns component values for each realizable solution.

    Topology A — shunt element at source, series element toward load:
        source ─── X_series ───┬─── load
                               │
                             X_shunt (to ground)

    Topology B — series element at source, shunt element at load:
        source ─── X_series ───┬─── load
                                          │
                                        X_shunt (to ground)

    The method follows the classical real-part transformation:

        Q = sqrt(R_high / R_low − 1)
        X_shunt = R_high / Q
        X_series = Q × R_low

    where R_high = max(Re{Zs}, Re{Zl}) and R_low = min(Re{Zs}, Re{Zl}).

    The imaginary parts of source and load are absorbed into the series arm.

    Parameters
    ----------
    z_source : complex or float — source impedance [Ω]
    z_load   : complex or float — load impedance [Ω]
    freq_hz  : float            — operating frequency [Hz]

    Returns
    -------
    dict with keys:
        ok, freq_hz, z_source_re, z_source_im, z_load_re, z_load_im,
        Q, solutions (list of up to 2 solution dicts each containing:
            topology, X_shunt_ohm, X_series_ohm,
            component_type_shunt, component_value_shunt_f_or_h,
            component_type_series, component_value_series_f_or_h,
            realizable, warnings)
    """
    err = _chk_complex(z_source, "z_source")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_complex(z_load, "z_load")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}

    zs = complex(z_source)
    zl = complex(z_load)
    rs = zs.real
    rl = zl.real
    xs = zs.imag
    xl = zl.imag

    if rs <= 0.0 or rl <= 0.0:
        return {
            "ok": False,
            "reason": (
                "Real parts of source and load must be positive for L-section matching; "
                f"Re(Zs)={rs}, Re(Zl)={rl}"
            ),
        }

    omega = 2.0 * math.pi * freq_hz

    r_high = max(rs, rl)
    r_low = min(rs, rl)

    ratio = r_high / r_low - 1.0
    if ratio < 0.0:
        return {"ok": False, "reason": "Internal error: r_high/r_low < 1"}

    Q = math.sqrt(ratio)
    w = []

    if Q > _HIGH_Q_THRESHOLD:
        warnings.warn(
            f"lsection_match: Q={Q:.1f} exceeds {_HIGH_Q_THRESHOLD}; "
            "component sensitivities will be high.",
            stacklevel=2,
        )

    # Two solutions: +Q and −Q (shunt capacitor or shunt inductor)
    for sign in (+1.0, -1.0):
        sol_warnings = []
        q = sign * Q

        # ── Topology selection ────────────────────────────────────────────
        # If Rs > Rl: shunt element is on the source side
        # If Rl > Rs: shunt element is on the load side
        # In both cases X_shunt and X_series are the same magnitudes; only
        # the physical topology label changes.

        x_shunt_raw = r_high / q                   # shunt reactance [Ω]
        x_series_raw = q * r_low                   # series reactance [Ω]

        # Absorb source or load reactance into the series arm
        if rs > rl:
            # Shunt on source side → absorb load reactance into series
            x_series = x_series_raw - xl
            x_shunt = x_shunt_raw
            topology = "shunt-source / series-load"
        else:
            # Shunt on load side → absorb source reactance into series
            x_series = x_series_raw - xs
            x_shunt = x_shunt_raw
            topology = "series-source / shunt-load"

        # Determine component types from sign of reactance
        def _rx_type(x: float, label: str, sw: list):
            """Return (component_type, value_in_F_or_H, realizable)."""
            if x > 0.0:
                # Inductor: X = ω·L → L = X/ω
                val = x / omega
                return "L", val, True
            elif x < 0.0:
                # Capacitor: X = -1/(ω·C) → C = 1/(ω·|X|)
                val = 1.0 / (omega * abs(x))
                return "C", val, True
            else:
                sw.append(f"{label}: reactance == 0 (degenerate, short/open circuit)")
                return "short", 0.0, False

        shunt_type, shunt_val, shunt_real = _rx_type(x_shunt, "X_shunt", sol_warnings)
        series_type, series_val, series_real = _rx_type(x_series, "X_series", sol_warnings)

        realizable = shunt_real and series_real

        if shunt_val < 0 or series_val < 0:
            sol_warnings.append("Negative component value(s); solution may not be realizable.")
            realizable = False

        w.append({
            "topology": topology,
            "sign": "+" if sign > 0 else "−",
            "Q": round(abs(q), 6),
            "X_shunt_ohm": round(x_shunt, 6),
            "X_series_ohm": round(x_series, 6),
            "component_type_shunt": shunt_type,
            "component_value_shunt": shunt_val,
            "component_type_series": series_type,
            "component_value_series": series_val,
            "realizable": realizable,
            "warnings": sol_warnings,
        })

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "z_source_re": rs,
        "z_source_im": xs,
        "z_load_re": rl,
        "z_load_im": xl,
        "Q": round(Q, 6),
        "solutions": w,
    }


# ── Pi-network synthesis ─────────────────────────────────────────────────────


def pi_network(
    r_source: float,
    r_load: float,
    freq_hz: float,
    q_loaded: float,
) -> dict:
    """
    Pi-network (π-network) synthesis for a target loaded-Q.

    A Pi-network is equivalent to two back-to-back L-sections through a
    virtual intermediate resistance R_virt = R_high / (Q² + 1).

    Component layout (all shunt elements to ground):

        source ─┬─── X_s1 ───┬─── X_s2 ───┬─── load
                │             │             │
              X_p1           (none)       X_p2

    X_p1, X_p2 are the two shunt arms; X_s1, X_s2 are the two series arms
    (in practice they are combined into a single series element X_series =
    X_s1 + X_s2).

    Parameters
    ----------
    r_source  : float — source resistance [Ω]
    r_load    : float — load resistance [Ω]
    freq_hz   : float — operating frequency [Hz]
    q_loaded  : float — target loaded-Q (must be > sqrt(R_high/R_low − 1))

    Returns
    -------
    dict with keys:
        ok, r_source, r_load, freq_hz, q_loaded, r_virtual,
        X_p1_ohm, X_series_ohm, X_p2_ohm,
        L_or_C_p1, value_p1, L_or_C_series, value_series,
        L_or_C_p2, value_p2, warnings
    """
    err = _chk_pos(r_source, "r_source")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(r_load, "r_load")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(q_loaded, "q_loaded")
    if err:
        return {"ok": False, "reason": err}

    r_high = max(r_source, r_load)
    r_low = min(r_source, r_load)
    q_min = math.sqrt(r_high / r_low - 1.0) if r_high > r_low else 0.0

    if q_loaded <= q_min:
        return {
            "ok": False,
            "reason": (
                f"q_loaded={q_loaded:.4f} must be > Q_min={q_min:.4f} "
                f"(= sqrt(R_high/R_low − 1) = sqrt({r_high}/{r_low} − 1))"
            ),
        }

    sol_warnings = []
    if q_loaded > _HIGH_Q_THRESHOLD:
        warnings.warn(
            f"pi_network: q_loaded={q_loaded:.1f} exceeds {_HIGH_Q_THRESHOLD}.",
            stacklevel=2,
        )
        sol_warnings.append(f"High Q ({q_loaded:.1f}); component sensitivities will be high.")

    omega = 2.0 * math.pi * freq_hz

    # Virtual intermediate resistance
    r_virt = r_high / (q_loaded ** 2 + 1.0)

    # Left L-section (source → r_virt): shunt on source side
    q1 = math.sqrt(r_source / r_virt - 1.0)
    x_p1 = r_source / q1          # shunt reactance on source side (capacitor, −)
    x_s1 = q1 * r_virt            # series reactance, left half (+inductor or −cap)

    # Right L-section (r_virt → load): shunt on load side
    q2 = math.sqrt(r_load / r_virt - 1.0)
    x_p2 = r_load / q2            # shunt reactance on load side
    x_s2 = q2 * r_virt            # series reactance, right half

    # Series arms combine (both are inductive for a band-pass Pi)
    x_series = x_s1 + x_s2

    # Standard Pi-topology: shunt arms are capacitors (negative reactance for HPF
    # or LPF depending on series element).  In a low-pass Pi: series = L, shunt = C.
    # We return raw reactances and let caller interpret.

    def _val(x: float, label: str, sw: list):
        if x > 0.0:
            return "L", x / omega
        elif x < 0.0:
            return "C", 1.0 / (omega * abs(x))
        else:
            sw.append(f"{label} reactance is zero (degenerate).")
            return "short", 0.0

    # Pi shunt arms are often made capacitive (−x_p1, −x_p2 for low-pass)
    # Return positive shunt reactances; the user/tool layer decides topology.
    type_p1, val_p1 = _val(x_p1, "X_p1", sol_warnings)
    type_s, val_s = _val(x_series, "X_series", sol_warnings)
    type_p2, val_p2 = _val(x_p2, "X_p2", sol_warnings)

    return {
        "ok": True,
        "r_source": r_source,
        "r_load": r_load,
        "freq_hz": freq_hz,
        "q_loaded": q_loaded,
        "q_min": round(q_min, 6),
        "r_virtual": round(r_virt, 6),
        "X_p1_ohm": round(x_p1, 6),
        "X_series_ohm": round(x_series, 6),
        "X_p2_ohm": round(x_p2, 6),
        "component_type_p1": type_p1,
        "component_value_p1": val_p1,
        "component_type_series": type_s,
        "component_value_series": val_s,
        "component_type_p2": type_p2,
        "component_value_p2": val_p2,
        "warnings": sol_warnings,
    }


# ── T-network synthesis ──────────────────────────────────────────────────────


def t_network(
    r_source: float,
    r_load: float,
    freq_hz: float,
    q_loaded: float,
) -> dict:
    """
    T-network synthesis for a target loaded-Q.

    A T-network is the dual of a Pi-network: two series arms and one shunt
    arm, synthesised as back-to-back L-sections through a virtual intermediate
    resistance R_virt = R_low × (Q² + 1).

    Component layout:

        source ─── X_s1 ───┬─── X_s2 ─── load
                           │
                          X_p (to ground)

    Parameters
    ----------
    r_source  : float — source resistance [Ω]
    r_load    : float — load resistance [Ω]
    freq_hz   : float — operating frequency [Hz]
    q_loaded  : float — target loaded-Q (must be > sqrt(R_high/R_low − 1))

    Returns
    -------
    dict with keys:
        ok, r_source, r_load, freq_hz, q_loaded, r_virtual,
        X_s1_ohm, X_p_ohm, X_s2_ohm,
        component_type_s1, component_value_s1,
        component_type_p,  component_value_p,
        component_type_s2, component_value_s2,
        warnings
    """
    err = _chk_pos(r_source, "r_source")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(r_load, "r_load")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(q_loaded, "q_loaded")
    if err:
        return {"ok": False, "reason": err}

    r_high = max(r_source, r_load)
    r_low = min(r_source, r_load)
    q_min = math.sqrt(r_high / r_low - 1.0) if r_high > r_low else 0.0

    if q_loaded <= q_min:
        return {
            "ok": False,
            "reason": (
                f"q_loaded={q_loaded:.4f} must be > Q_min={q_min:.4f}"
            ),
        }

    sol_warnings = []
    if q_loaded > _HIGH_Q_THRESHOLD:
        warnings.warn(
            f"t_network: q_loaded={q_loaded:.1f} exceeds {_HIGH_Q_THRESHOLD}.",
            stacklevel=2,
        )
        sol_warnings.append(f"High Q ({q_loaded:.1f}); component sensitivities will be high.")

    omega = 2.0 * math.pi * freq_hz

    # Virtual intermediate resistance (T-dual of Pi)
    r_virt = r_low * (q_loaded ** 2 + 1.0)

    # Left L-section (source → r_virt): series on source side
    q1 = math.sqrt(r_virt / r_source - 1.0)
    x_s1 = q1 * r_source          # series reactance, source side
    x_p1 = r_virt / q1            # shunt arm contribution from left section

    # Right L-section (r_virt → load): series on load side
    q2 = math.sqrt(r_virt / r_load - 1.0)
    x_s2 = q2 * r_load            # series reactance, load side
    x_p2 = r_virt / q2            # shunt arm contribution from right section

    # Shunt arms are in parallel → combine: 1/X_p = 1/X_p1 + 1/X_p2
    # (both capacitive for a bandpass T)
    # Equivalent shunt reactance
    if abs(x_p1) > 0 and abs(x_p2) > 0:
        x_p = (x_p1 * x_p2) / (x_p1 + x_p2)
    else:
        x_p = 0.0
        sol_warnings.append("Degenerate shunt arm (zero reactance).")

    def _val(x: float, label: str, sw: list):
        if x > 0.0:
            return "L", x / omega
        elif x < 0.0:
            return "C", 1.0 / (omega * abs(x))
        else:
            sw.append(f"{label} reactance is zero (degenerate).")
            return "short", 0.0

    type_s1, val_s1 = _val(x_s1, "X_s1", sol_warnings)
    type_p, val_p = _val(x_p, "X_p", sol_warnings)
    type_s2, val_s2 = _val(x_s2, "X_s2", sol_warnings)

    return {
        "ok": True,
        "r_source": r_source,
        "r_load": r_load,
        "freq_hz": freq_hz,
        "q_loaded": q_loaded,
        "q_min": round(q_min, 6),
        "r_virtual": round(r_virt, 6),
        "X_s1_ohm": round(x_s1, 6),
        "X_p_ohm": round(x_p, 6),
        "X_s2_ohm": round(x_s2, 6),
        "component_type_s1": type_s1,
        "component_value_s1": val_s1,
        "component_type_p": type_p,
        "component_value_p": val_p,
        "component_type_s2": type_s2,
        "component_value_s2": val_s2,
        "warnings": sol_warnings,
    }


# ── Quarter-wave transformer ─────────────────────────────────────────────────


def quarter_wave_transformer(
    r_source: float,
    r_load: float,
) -> dict:
    """
    Quarter-wave transformer characteristic impedance.

    For a lossless quarter-wave transmission-line transformer:
        Z0_transformer = sqrt(R_source × R_load)

    Valid only for real (resistive) source and load at the design frequency.
    At frequency f_design the transformer electrical length is 90° (λ/4).

    Parameters
    ----------
    r_source : float — source resistance [Ω]
    r_load   : float — load resistance [Ω]

    Returns
    -------
    dict with keys: ok, r_source, r_load, z0_transformer_ohm, formula
    """
    err = _chk_pos(r_source, "r_source")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(r_load, "r_load")
    if err:
        return {"ok": False, "reason": err}

    z0_t = math.sqrt(r_source * r_load)

    return {
        "ok": True,
        "r_source": r_source,
        "r_load": r_load,
        "z0_transformer_ohm": round(z0_t, 6),
        "formula": "Z0 = sqrt(R_source × R_load)",
    }


# ── Single-stub matching (electrical lengths) ─────────────────────────────────


def single_stub_match(
    z_load,
    z0: float = 50.0,
    stub_type: str = "shunt",
    termination: str = "short",
) -> dict:
    """
    Single-stub impedance matching: compute stub electrical length and
    feed-line distance-to-stub.

    Uses the classical single-stub matching algorithm (Pozar, "Microwave
    Engineering", 4th ed., §5.2):

        1. Normalise load: y_L = Z0 / Z_L = g + jb
        2. Find feed-line distance d such that Y_in has unit conductance:
               d = (1/(2β)) × arctan(...)  [two solutions]
        3. Choose stub length l to cancel the susceptance.

    Electrical lengths are returned in degrees and as fractions of wavelength.

    Parameters
    ----------
    z_load      : complex or float — load impedance [Ω]
    z0          : float            — system impedance [Ω] (default 50 Ω)
    stub_type   : str              — 'shunt' or 'series' (default 'shunt')
    termination : str              — 'short' or 'open' stub termination (default 'short')

    Returns
    -------
    dict with keys:
        ok, z_load_re, z_load_im, z0, stub_type, termination,
        solutions (list of up to 2 dicts each with:
            d_wavelength, d_degrees,
            stub_length_wavelength, stub_length_degrees,
            realizable, notes)
    """
    err = _chk_complex(z_load, "z_load")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(z0, "z0")
    if err:
        return {"ok": False, "reason": err}

    stub_type = stub_type.lower().strip()
    termination = termination.lower().strip()
    if stub_type not in ("shunt", "series"):
        return {"ok": False, "reason": "stub_type must be 'shunt' or 'series'"}
    if termination not in ("short", "open"):
        return {"ok": False, "reason": "termination must be 'short' or 'open'"}

    zl = complex(z_load)
    if abs(zl) == 0.0:
        return {"ok": False, "reason": "z_load == 0 (short circuit); stub matching undefined"}

    # Normalised load admittance
    y_L = z0 / zl          # = 1 / (Z_L/Z0)
    g_L = y_L.real
    b_L = y_L.imag

    solutions = []

    # For shunt-stub matching (Pozar §5.2):
    # Find t = tan(βd) such that g(d) = 1
    # g(d) = g_L / (g_L² + (b_L + t)²) × (1 + t²) ... expand using admittance formula
    #
    # Normalised input admittance of a lossless line terminated in y_L:
    #   y_in(d) = (y_L + j tan βd) / (1 + j y_L tan βd)
    #
    # We need Re{y_in} = 1 →
    #   g_L (1 + t²) = (g_L² + (b_L + t)²)   where t = tan(βd)
    #
    # Rearranging:
    #   g_L t² - 2 b_L t + (g_L - g_L² - b_L²) = 0
    # when g_L = 1: t = (b_L ± sqrt(b_L²+ 1 - 1)) / 1 which reduces to tan(βd) for matched case
    # General: solve quadratic in t

    if abs(g_L) < 1e-15:
        return {
            "ok": False,
            "reason": (
                f"Re{{Y_L/Y0}} ≈ 0 (g_L={g_L:.3e}); load is purely reactive, "
                "single-stub match requires g_L > 0."
            ),
        }

    # Quadratic: g_L × t² − 2 b_L × t + (g_L − g_L² − b_L²) = 0
    A = g_L
    B = -2.0 * b_L
    C = g_L - g_L ** 2 - b_L ** 2
    discriminant = B ** 2 - 4.0 * A * C

    if discriminant < 0.0:
        return {
            "ok": False,
            "reason": (
                f"No real solution for stub position (discriminant={discriminant:.3e}). "
                "Load may not be matchable with a single stub at this impedance level."
            ),
        }

    for sign in (+1.0, -1.0):
        t = (-B + sign * math.sqrt(discriminant)) / (2.0 * A)
        # βd = arctan(t) in [0, π)
        beta_d = math.atan(t)
        if beta_d < 0.0:
            beta_d += math.pi

        d_wl = beta_d / (2.0 * math.pi)   # fraction of wavelength
        d_deg = math.degrees(beta_d)

        # Susceptance at the stub location
        # y_in = y_L + j*t / (1 + j*y_L*t)  — use exact formula
        jt = complex(0, t)
        y_in_at_d = (y_L + jt) / (1.0 + jt * y_L)
        b_in = y_in_at_d.imag   # susceptance to cancel with stub

        # Stub susceptance needed: b_stub = −b_in
        b_stub = -b_in

        # Stub length for shunt short-circuit termination:
        #   b_stub_SC = −cot(βl)  → βl = arctan(−1/b_stub) ... = −acot(b_stub)
        # Stub length for shunt open-circuit termination:
        #   b_stub_OC = tan(βl)   → βl = arctan(b_stub)

        if termination == "short":
            # b = -cot(βl) → βl = arctan(-1/b_stub) + nπ
            if abs(b_stub) < 1e-15:
                beta_l = math.pi / 2.0  # quarter-wave
            else:
                beta_l = math.atan(-1.0 / b_stub)
                if beta_l < 0.0:
                    beta_l += math.pi
        else:
            # open: b = tan(βl) → βl = arctan(b_stub)
            beta_l = math.atan(b_stub)
            if beta_l < 0.0:
                beta_l += math.pi

        l_wl = beta_l / (2.0 * math.pi)
        l_deg = math.degrees(beta_l)

        notes = []
        realizable = True
        if d_wl < 0 or d_wl > 0.5:
            notes.append(f"d={d_wl:.4f}λ is outside [0, 0.5λ]; check solution branch.")
        if l_wl < 0 or l_wl > 0.5:
            notes.append(f"l={l_wl:.4f}λ is outside [0, 0.5λ]; check solution branch.")
            realizable = False

        solutions.append({
            "d_wavelength": round(d_wl, 6),
            "d_degrees": round(d_deg, 4),
            "stub_length_wavelength": round(l_wl, 6),
            "stub_length_degrees": round(l_deg, 4),
            "b_in_at_d": round(b_in, 8),
            "realizable": realizable,
            "notes": notes,
        })

    return {
        "ok": True,
        "z_load_re": zl.real,
        "z_load_im": zl.imag,
        "z0": z0,
        "stub_type": stub_type,
        "termination": termination,
        "solutions": solutions,
    }


# ── Microstrip synthesis (Hammerstad closed-form) ────────────────────────────


def microstrip_synthesis(
    z0_target: float,
    er: float,
    h: float = 1.0,
    t: float = 0.0,
) -> dict:
    """
    Microstrip width synthesis using the Hammerstad & Jensen (1980) closed-form
    equations, as presented in Pozar "Microwave Engineering" (4th ed.) §3.8.

    Given a target characteristic impedance Z0 and substrate parameters,
    computes the trace width W and effective permittivity εr_eff.

    The synthesis covers two regimes:
        Narrow trace (W/H < 2):
            Z0 = (η0 / (2π sqrt(εr_eff))) × ln(8H/W + W/(4H))
        Wide trace (W/H ≥ 2):
            Z0 = η0 / (sqrt(εr_eff) × [W/H + 1.393 + 0.667 ln(W/H + 1.444)])

    Strip thickness correction for t > 0 (Hammerstad):
        W_eff = W + ΔW   where ΔW accounts for fringing from finite t.

    Parameters
    ----------
    z0_target : float — target characteristic impedance [Ω]
    er        : float — substrate relative permittivity (εr)
    h         : float — substrate height [same unit as returned W; default 1.0]
    t         : float — trace thickness [same unit as h; 0 = ideal thin trace]

    Returns
    -------
    dict with keys:
        ok, z0_target, er, h, t,
        width,               — trace width [same unit as h]
        width_to_height,     — W/H ratio
        er_eff,              — effective permittivity
        z0_achieved,         — Z0 recomputed from synthesised W/H (self-check)
        error_percent,       — |z0_achieved − z0_target| / z0_target × 100
        regime,              — 'narrow' or 'wide'
        warnings
    """
    err = _chk_pos(z0_target, "z0_target")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(er, "er")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(h, "h")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(t, "t")
    if err:
        return {"ok": False, "reason": err}

    sol_warnings = []
    eta0 = 376.73   # free-space wave impedance [Ω] = μ0 × c

    # ── Hammerstad synthesis equations ───────────────────────────────────────
    # A = (Z0/60) × sqrt((er+1)/2) + ((er-1)/(er+1)) × (0.23 + 0.11/er)
    # If A > pi/2 (narrow trace): W/H = 8*exp(A) / (exp(2A) - 2)
    # B = 377π / (2 × Z0 × sqrt(er))
    # If B < π (wide trace): W/H = (2/π) × [B - 1 - ln(2B-1) + (er-1)/(2er)×(ln(B-1)+0.39-0.61/er)]

    A = (z0_target / 60.0) * math.sqrt((er + 1.0) / 2.0) + (
        (er - 1.0) / (er + 1.0)
    ) * (0.23 + 0.11 / er)

    B = 377.0 * math.pi / (2.0 * z0_target * math.sqrt(er))

    # Try narrow solution first
    wh_narrow = 8.0 * math.exp(A) / (math.exp(2.0 * A) - 2.0)
    wh_wide = (2.0 / math.pi) * (
        B - 1.0 - math.log(2.0 * B - 1.0)
        + ((er - 1.0) / (2.0 * er)) * (math.log(B - 1.0) + 0.39 - 0.61 / er)
    )

    # Select regime
    if wh_narrow <= 2.0:
        wh = wh_narrow
        regime = "narrow"
    else:
        wh = max(wh_wide, 1e-6)
        regime = "wide"

    # Strip thickness correction (Hammerstad, t > 0)
    if t > 0.0:
        if wh <= 1.0 / (2.0 * math.pi):
            dw = (t / math.pi) * (1.0 + math.log(4.0 * math.e * h / t))
        else:
            dw = (t / math.pi) * (1.0 + math.log(2.0 * h / t))
        wh_eff = wh + dw / h
    else:
        wh_eff = wh

    # Effective permittivity (Hammerstad)
    er_eff = _microstrip_er_eff(er, wh_eff)

    # Recompute Z0 from synthesised W/H (self-consistency check)
    z0_check = _microstrip_z0_from_wh(wh_eff, er_eff)

    err_pct = abs(z0_check - z0_target) / z0_target * 100.0
    if err_pct > 1.0:
        sol_warnings.append(
            f"Self-check error {err_pct:.2f}% > 1%; iterative refinement may be needed."
        )

    return {
        "ok": True,
        "z0_target": z0_target,
        "er": er,
        "h": h,
        "t": t,
        "width": round(wh_eff * h, 8),
        "width_to_height": round(wh_eff, 8),
        "er_eff": round(er_eff, 6),
        "z0_achieved": round(z0_check, 4),
        "error_percent": round(err_pct, 4),
        "regime": regime,
        "warnings": sol_warnings,
    }


def _microstrip_er_eff(er: float, wh: float) -> float:
    """Effective permittivity from W/H ratio (Hammerstad)."""
    f = 1.0 / math.sqrt(1.0 + 12.0 / wh)
    if wh < 1.0:
        f += 0.04 * (1.0 - wh) ** 2
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * f


def _microstrip_z0_from_wh(wh: float, er_eff: float) -> float:
    """Characteristic impedance from W/H and εr_eff (Hammerstad analysis)."""
    eta0 = 376.73
    if wh < 1.0:
        return (eta0 / (2.0 * math.pi * math.sqrt(er_eff))) * math.log(
            8.0 / wh + wh / 4.0
        )
    else:
        return eta0 / (
            math.sqrt(er_eff) * (wh + 1.393 + 0.667 * math.log(wh + 1.444))
        )


def microstrip_analysis(
    width: float,
    h: float,
    er: float,
    t: float = 0.0,
) -> dict:
    """
    Microstrip analysis: compute characteristic impedance and effective
    permittivity from physical dimensions.

    Parameters
    ----------
    width : float — trace width [same unit as h]
    h     : float — substrate height [same unit as width]
    er    : float — substrate relative permittivity
    t     : float — trace thickness (0 = ideal thin trace)

    Returns
    -------
    dict with keys:
        ok, width, h, er, t, width_to_height, er_eff, z0, wavelength_factor
    """
    err = _chk_pos(width, "width")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(h, "h")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(er, "er")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_nonneg(t, "t")
    if err:
        return {"ok": False, "reason": err}

    wh = width / h

    # Strip thickness correction
    if t > 0.0:
        if wh <= 1.0 / (2.0 * math.pi):
            dw = (t / math.pi) * (1.0 + math.log(4.0 * math.e * h / t))
        else:
            dw = (t / math.pi) * (1.0 + math.log(2.0 * h / t))
        wh_eff = wh + dw / h
    else:
        wh_eff = wh

    er_eff = _microstrip_er_eff(er, wh_eff)
    z0 = _microstrip_z0_from_wh(wh_eff, er_eff)

    # Phase velocity / wavelength scaling: v_p = c / sqrt(εr_eff)
    wl_factor = 1.0 / math.sqrt(er_eff)   # λ_guided / λ_free = 1/sqrt(εr_eff)

    return {
        "ok": True,
        "width": width,
        "h": h,
        "er": er,
        "t": t,
        "width_to_height": round(wh_eff, 6),
        "er_eff": round(er_eff, 6),
        "z0": round(z0, 4),
        "wavelength_factor": round(wl_factor, 6),
        "formula": "Hammerstad & Jensen (1980) / Pozar §3.8",
    }
