"""
Passive LC / RC EMI filter design for power lines.

Computes corner frequency, component values (L, C, R), and attenuation at a
target conducted-emission frequency for three filter topologies:

  LC_low_pass  — classic 2nd-order series-L shunt-C low-pass (−40 dB/decade
                 above f_c); standard power-line EMI filter topology.
  PI_LC_L      — π (pi) section: shunt-C, series-L, shunt-C; 3rd-order
                 (−60 dB/decade); recommended values split the capacitance
                 equally across input/output shunt caps, keeps same f_c as the
                 equivalent 2nd-order (L, Ctotal) pair.
  RC_low_pass  — 1st-order resistive-capacitive low-pass (−20 dB/decade);
                 suitable for low-current signal-line or bypass filtering only.

Design equations (Ott, "EMC Engineering", §15.3)
-------------------------------------------------
For LC_low_pass (2nd order, −40 dB/decade):
    f_c = 1 / (2π·√(L·C))

Given a desired attenuation A_dB at target frequency f_t, and assuming the
roll-off applies from f_c, the corner must satisfy:
    A_dB = 40·log10(f_t / f_c)    →   f_c = f_t / 10^(A_dB/40)

Then choosing a standard L (e.g. 100 µH) the required C is:
    C = 1 / ((2π·f_c)² · L)

For PI_LC_L (3rd order, −60 dB/decade):
    f_c is chosen as for the LC case (same design formula).
    L and Ctotal = C are chosen identically; each shunt cap = Ctotal / 2.
    Attenuation of the π section: −60·log10(f_t / f_c) above f_c.

For RC_low_pass (1st order, −20 dB/decade):
    f_c = 1 / (2π·R·C)
    A_dB = 20·log10(f_t / f_c)    →   f_c = f_t / 10^(A_dB/20)
    If load_resistance_ohm is given, R = load_resistance_ohm.
    Otherwise a 50 Ω source is assumed and C is derived.

X2-rated capacitor recommendation (CISPR 22 / EN 55022 §6.2)
-------------------------------------------------------------
X2 capacitors (275 VAC, 0.01–4.7 µF) are used across-the-line for
differential-mode filtering. Recommended X2 values are chosen from the
E12 series nearest to the computed C.

HONEST CAVEATS
--------------
1. Ideal passive components assumed — no parasitic series resistance (ESR),
   no winding self-capacitance, no parasitic inductance of capacitors.
2. Common-mode (CM) and differential-mode (DM) are NOT differentiated.
   A real LISN-measured conducted-emission problem almost always has both CM
   and DM components; this calculator addresses DM only (series L, shunt C).
3. Source and load impedances are assumed ideal (0 Ω source, ∞ Ω load for the
   LC topology). Insertion-loss in a real 50 Ω LISN environment will differ.
4. CISPR 22 / EN 55022 conducted-emission limits (Class B: 66–56 dBµV in
   0.15–0.50 MHz, 56 dBµV in 0.50–5 MHz, 60 dBµV in 5–30 MHz) are cited for
   context only.  Compliance requires measurement in an accredited EMC lab.
5. Core saturation not checked — verify L carries dc_current_A below its rated
   saturation current.

References
----------
H. Ott, "Electromagnetic Compatibility Engineering", Wiley, 2009, §15.3.
CISPR 22 / EN 55022 (IEC, 4th ed. 2003, Class B conducted limits §9).
M. J. Nave, "Power Line Filter Design for Switched-Mode Power Supplies",
    Van Nostrand Reinhold, 1991.

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, List, Optional

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── E12 X2 series (275 VAC, common values in µF) ──────────────────────────────
# IEC 60384-14 X2 class; range 0.01 µF – 4.7 µF (standard capacitor decade).
_X2_E12_UF: list[float] = [
    0.010, 0.012, 0.015, 0.018, 0.022, 0.027, 0.033, 0.039, 0.047,
    0.056, 0.068, 0.082,
    0.10,  0.12,  0.15,  0.18,  0.22,  0.27,  0.33,  0.39,  0.47,
    0.56,  0.68,  0.82,
    1.0,   1.2,   1.5,   1.8,   2.2,   2.7,   3.3,   3.9,   4.7,
]

# Default L value used when no L is given [H]
_DEFAULT_L_H: float = 100e-6       # 100 µH

# Default R for RC filter when no load_resistance_ohm is supplied [Ω]
_DEFAULT_R_OHM: float = 50.0


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class EmiFilterSpec:
    """Input specification for an EMI power-line filter design.

    Attributes
    ----------
    dc_voltage_V : float
        DC bus voltage the filter must handle [V].  Used for caveats and
        headroom checks; not consumed in the core calculation.
    dc_current_A : float
        DC (or peak AC) current through the series element [A].  Checked
        against a minimum positivity requirement.
    target_attenuation_dB : float
        Required insertion loss at the target conducted-emission frequency
        [dB], e.g. 30 dB to push CISPR Class B limit down to margin.
    target_freq_kHz : float
        Target conducted-emission frequency [kHz], e.g. 150 kHz (lower edge
        of the CISPR 22 conducted-emission test range).
    filter_topology : str
        One of:
        - "LC_low_pass"  2nd-order series-L / shunt-C (−40 dB/decade).
        - "PI_LC_L"      3rd-order π-section (−60 dB/decade); each shunt cap
                         = C/2.
        - "RC_low_pass"  1st-order (−20 dB/decade); only for low-current /
                         signal-line use.
    load_resistance_ohm : float | None
        Load resistance [Ω].  Only used by RC_low_pass to set R.  If None,
        50 Ω is assumed for RC; ignored for LC/PI topologies.
    """
    dc_voltage_V: float
    dc_current_A: float
    target_attenuation_dB: float
    target_freq_kHz: float
    filter_topology: str  # "LC_low_pass" | "PI_LC_L" | "RC_low_pass"
    load_resistance_ohm: Optional[float] = None


@dataclass
class EmiFilterReport:
    """Result of the EMI power-line filter design calculation.

    Attributes
    ----------
    cutoff_freq_Hz : float
        Designed corner (−3 dB) frequency [Hz].
    L_uH : float | None
        Series inductance [µH].  None for RC_low_pass.
    C_uF : float | None
        Total shunt capacitance [µF].  For PI_LC_L each shunt cap = C_uF/2.
        None for RC_low_pass when C is implicit.
    R_ohm : float | None
        Series resistance [Ω].  Only set for RC_low_pass.
    attenuation_at_target_dB : float
        Computed insertion loss at target_freq_kHz [dB] using the ideal
        roll-off slope for the selected topology.
    recommended_caps_X2_uF : list[float]
        Nearest E12 X2 capacitor values (up to 3) bracketing C_uF.
    honest_caveat : str
        Engineering caveats the caller must acknowledge.
    """
    cutoff_freq_Hz: float
    L_uH: Optional[float]
    C_uF: Optional[float]
    R_ohm: Optional[float]
    attenuation_at_target_dB: float
    recommended_caps_X2_uF: List[float]
    honest_caveat: str


# ── Helpers ────────────────────────────────────────────────────────────────────


def _nearest_x2_caps(c_uf: float, n: int = 3) -> list[float]:
    """Return up to *n* E12 X2 values closest to c_uf."""
    if c_uf <= 0:
        return []
    scored = sorted(_X2_E12_UF, key=lambda v: abs(math.log(v / c_uf)))
    return scored[:n]


def _validate_spec(spec: EmiFilterSpec) -> Optional[str]:
    """Return an error string or None if inputs are valid."""
    if not isinstance(spec, EmiFilterSpec):
        return "spec must be an EmiFilterSpec instance"
    if spec.dc_voltage_V <= 0:
        return f"dc_voltage_V must be > 0, got {spec.dc_voltage_V}"
    if spec.dc_current_A <= 0:
        return f"dc_current_A must be > 0, got {spec.dc_current_A}"
    if spec.target_attenuation_dB <= 0:
        return f"target_attenuation_dB must be > 0, got {spec.target_attenuation_dB}"
    if spec.target_freq_kHz <= 0:
        return f"target_freq_kHz must be > 0, got {spec.target_freq_kHz}"
    if spec.filter_topology not in ("LC_low_pass", "PI_LC_L", "RC_low_pass"):
        return (
            f"filter_topology must be one of 'LC_low_pass', 'PI_LC_L', "
            f"'RC_low_pass'; got {spec.filter_topology!r}"
        )
    if spec.load_resistance_ohm is not None and spec.load_resistance_ohm <= 0:
        return f"load_resistance_ohm must be > 0, got {spec.load_resistance_ohm}"
    return None


# ── Core design function ───────────────────────────────────────────────────────


def design_emi_filter(spec: EmiFilterSpec) -> EmiFilterReport:
    """Design a passive LC / RC power-line EMI filter.

    Algorithm
    ---------
    Let f_t = spec.target_freq_kHz × 1000 [Hz].

    LC_low_pass / PI_LC_L (2nd / 3rd order):
        Roll-off slope: −40 dB/decade (LC) or −60 dB/decade (PI).
        f_c = f_t / 10^(A_dB / slope_decades_per_40dB)
            where slope_decades_per_40dB = 1 for LC, 1.5 for PI
            (so 40×1=40 or 40×1.5=60 dB/decade respectively —
             equivalently f_c = f_t / 10^(A_dB/40) for LC,
             f_c = f_t / 10^(A_dB/60) for PI)
        L = _DEFAULT_L_H (100 µH), C = 1 / ((2π·f_c)² · L)
        Attenuation check:
            A_check = 40·log10(f_t/f_c) for LC
            A_check = 60·log10(f_t/f_c) for PI

    RC_low_pass (1st order):
        f_c = f_t / 10^(A_dB / 20)
        R = load_resistance_ohm if provided else 50 Ω
        C = 1 / (2π·f_c·R)
        A_check = 20·log10(f_t/f_c)

    Parameters
    ----------
    spec : EmiFilterSpec

    Returns
    -------
    EmiFilterReport

    Raises
    ------
    ValueError
        On invalid inputs.
    """
    err = _validate_spec(spec)
    if err:
        raise ValueError(err)

    f_t_hz = spec.target_freq_kHz * 1e3
    A = spec.target_attenuation_dB

    # ── LC_low_pass (2nd order, −40 dB/decade) ────────────────────────────────
    if spec.filter_topology == "LC_low_pass":
        # f_c = f_t / 10^(A/40)
        f_c = f_t_hz / (10.0 ** (A / 40.0))
        L_h = _DEFAULT_L_H
        omega_c = 2.0 * math.pi * f_c
        C_f = 1.0 / (omega_c ** 2 * L_h)
        L_uh = L_h * 1e6
        C_uf = C_f * 1e6
        # Verify attenuation (should equal A by construction; recompute for report)
        atten_check = 40.0 * math.log10(f_t_hz / f_c)
        R_ohm = None
        x2_caps = _nearest_x2_caps(C_uf)
        caveat = (
            f"LC_low_pass: f_c = {f_c:.1f} Hz, L = {L_uh:.2f} µH, "
            f"C = {C_uf:.4f} µF. "
            "Attenuation formula: −40 dB/decade above f_c (Ott §15.3). "
            "HONEST: (1) Ideal components assumed — no ESR, no winding stray "
            "capacitance, no lead inductance; real roll-off flattens above the "
            "LC self-resonance of each component. "
            "(2) Differential-mode (DM) filter only — add a common-mode choke "
            "for CM emission (CISPR 22 §6). "
            "(3) Assumes ideal 0 Ω source / ∞ Ω load; insertion loss in a "
            "50 Ω LISN environment will be lower than predicted. "
            "(4) Verify L saturates above dc_current_A = "
            f"{spec.dc_current_A:.2f} A (rated I_sat of the inductor core). "
            f"(5) CISPR 22 Class B conducted-emission limit: 66–56 dBµV "
            "(0.15–0.50 MHz) / 56 dBµV (0.50–5 MHz) — verify in accredited EMC lab."
        )
        return EmiFilterReport(
            cutoff_freq_Hz=round(f_c, 3),
            L_uH=round(L_uh, 4),
            C_uF=round(C_uf, 6),
            R_ohm=R_ohm,
            attenuation_at_target_dB=round(atten_check, 2),
            recommended_caps_X2_uF=x2_caps,
            honest_caveat=caveat,
        )

    # ── PI_LC_L (3rd order, −60 dB/decade) ───────────────────────────────────
    if spec.filter_topology == "PI_LC_L":
        # f_c = f_t / 10^(A/60)
        f_c = f_t_hz / (10.0 ** (A / 60.0))
        L_h = _DEFAULT_L_H
        omega_c = 2.0 * math.pi * f_c
        C_f = 1.0 / (omega_c ** 2 * L_h)   # total shunt capacitance
        L_uh = L_h * 1e6
        C_uf = C_f * 1e6
        C_shunt_each_uf = C_uf / 2.0   # each of the two π shunt caps
        atten_check = 60.0 * math.log10(f_t_hz / f_c)
        R_ohm = None
        x2_caps = _nearest_x2_caps(C_shunt_each_uf)
        caveat = (
            f"PI_LC_L (π-section): f_c = {f_c:.1f} Hz, L = {L_uh:.2f} µH, "
            f"C_total = {C_uf:.4f} µF (each shunt cap = {C_shunt_each_uf:.4f} µF). "
            "Attenuation formula: −60 dB/decade above f_c (3rd-order; Ott §15.3). "
            "HONEST: (1) Ideal components — no ESR/stray; real π response peaks "
            "near L–C resonances. "
            "(2) recommended_caps_X2_uF refers to each shunt capacitor, not total. "
            "(3) DM-only; add CM choke for common-mode emission. "
            "(4) Verify L I_sat ≥ dc_current_A = "
            f"{spec.dc_current_A:.2f} A. "
            "(5) CISPR 22 Class B conducted limits cited for context — accredited "
            "EMC lab measurement required for compliance."
        )
        return EmiFilterReport(
            cutoff_freq_Hz=round(f_c, 3),
            L_uH=round(L_uh, 4),
            C_uF=round(C_uf, 6),
            R_ohm=R_ohm,
            attenuation_at_target_dB=round(atten_check, 2),
            recommended_caps_X2_uF=x2_caps,
            honest_caveat=caveat,
        )

    # ── RC_low_pass (1st order, −20 dB/decade) ────────────────────────────────
    # filter_topology == "RC_low_pass"
    f_c = f_t_hz / (10.0 ** (A / 20.0))
    R = (
        float(spec.load_resistance_ohm)
        if spec.load_resistance_ohm is not None
        else _DEFAULT_R_OHM
    )
    C_f = 1.0 / (2.0 * math.pi * f_c * R)
    C_uf = C_f * 1e6
    atten_check = 20.0 * math.log10(f_t_hz / f_c)
    x2_caps = _nearest_x2_caps(C_uf)
    caveat = (
        f"RC_low_pass: f_c = {f_c:.1f} Hz, R = {R:.1f} Ω, C = {C_uf:.4f} µF. "
        "Attenuation formula: −20 dB/decade above f_c (1st order). "
        "HONEST: (1) RC filters dissipate power in R — NOT suitable for high-current "
        "power bus filtering; use only for signal lines or low-current bypass. "
        "(2) No inductance — reduced suppression vs LC for conducted emissions. "
        "(3) R introduces a DC voltage drop of R × dc_current_A = "
        f"{R * spec.dc_current_A:.2f} V — verify this is acceptable. "
        "(4) Ideal components assumed. "
        "(5) CISPR 22 Class B conducted limits cited for context — accredited "
        "EMC lab measurement required for compliance."
    )
    return EmiFilterReport(
        cutoff_freq_Hz=round(f_c, 3),
        L_uH=None,
        C_uF=round(C_uf, 6),
        R_ohm=round(R, 4),
        attenuation_at_target_dB=round(atten_check, 2),
        recommended_caps_X2_uF=x2_caps,
        honest_caveat=caveat,
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def design_emi_filter_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        spec = EmiFilterSpec(
            dc_voltage_V=float(d["dc_voltage_V"]),
            dc_current_A=float(d["dc_current_A"]),
            target_attenuation_dB=float(d["target_attenuation_dB"]),
            target_freq_kHz=float(d["target_freq_kHz"]),
            filter_topology=str(d["filter_topology"]),
            load_resistance_ohm=(
                float(d["load_resistance_ohm"])
                if d.get("load_resistance_ohm") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = design_emi_filter(spec)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "cutoff_freq_Hz": report.cutoff_freq_Hz,
        "L_uH": report.L_uH,
        "C_uF": report.C_uF,
        "R_ohm": report.R_ohm,
        "attenuation_at_target_dB": report.attenuation_at_target_dB,
        "recommended_caps_X2_uF": report.recommended_caps_X2_uF,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_EMI_FILTER_SPEC = ToolSpec(
    name="electronics_design_emi_filter",
    description=(
        "Design a passive LC or RC power-line EMI filter.\n\n"
        "Computes the corner frequency, inductance, capacitance (or resistance), "
        "and attenuation at a target conducted-emission frequency for one of three "
        "topologies:\n"
        "  • LC_low_pass  — 2nd-order series-L / shunt-C (−40 dB/decade; Ott §15.3)\n"
        "  • PI_LC_L      — π-section: shunt-C, series-L, shunt-C (−60 dB/decade)\n"
        "  • RC_low_pass  — 1st-order RC (−20 dB/decade; signal/bypass lines only)\n\n"
        "Design equations:\n"
        "  LC: f_c = f_t / 10^(A/40);  C = 1/((2π·f_c)²·L) for L=100 µH\n"
        "  PI: f_c = f_t / 10^(A/60);  same C formula; each shunt cap = C/2\n"
        "  RC: f_c = f_t / 10^(A/20);  C = 1/(2π·f_c·R)\n\n"
        "Also returns nearest E12 X2 (275 VAC) capacitor values from CISPR 22 §6.2.\n\n"
        "HONEST: ideal passive components only — no ESR, no parasitic inductance "
        "of capacitors, no winding stray capacitance; DM-only (add separate CM choke "
        "for common-mode); source/load assumed ideal; CISPR 22 Class B conducted "
        "limits cited for context only — compliance requires accredited EMC lab "
        "measurement (CISPR 22 / EN 55022).\n\n"
        "Input: { dc_voltage_V, dc_current_A, target_attenuation_dB, "
        "target_freq_kHz, filter_topology, [load_resistance_ohm] }\n\n"
        "Returns: { ok, cutoff_freq_Hz, L_uH, C_uF, R_ohm, "
        "attenuation_at_target_dB, recommended_caps_X2_uF, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dc_voltage_V": {
                "type": "number",
                "description": "DC bus voltage the filter must handle [V].",
            },
            "dc_current_A": {
                "type": "number",
                "description": "DC (or peak AC) current through the series element [A].",
            },
            "target_attenuation_dB": {
                "type": "number",
                "description": (
                    "Required insertion loss at the target conducted-emission "
                    "frequency [dB], e.g. 30 dB for 30 dB of suppression."
                ),
            },
            "target_freq_kHz": {
                "type": "number",
                "description": (
                    "Target conducted-emission frequency [kHz]; "
                    "CISPR 22 range starts at 150 kHz."
                ),
            },
            "filter_topology": {
                "type": "string",
                "enum": ["LC_low_pass", "PI_LC_L", "RC_low_pass"],
                "description": (
                    "Filter topology: 'LC_low_pass' (2nd-order, −40 dB/dec), "
                    "'PI_LC_L' (π-section, −60 dB/dec), or "
                    "'RC_low_pass' (1st-order, −20 dB/dec; signal lines only)."
                ),
            },
            "load_resistance_ohm": {
                "type": "number",
                "description": (
                    "Load resistance [Ω]. Only used for RC_low_pass (sets R). "
                    "Default 50 Ω if omitted."
                ),
            },
        },
        "required": [
            "dc_voltage_V",
            "dc_current_A",
            "target_attenuation_dB",
            "target_freq_kHz",
            "filter_topology",
        ],
    },
)


@register(_EMI_FILTER_SPEC, write=False)
async def electronics_design_emi_filter(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = design_emi_filter_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _EMI_FILTER_SPEC.name,
        _EMI_FILTER_SPEC,
        electronics_design_emi_filter,
    ),
]
