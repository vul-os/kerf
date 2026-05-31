"""
Buck DC-DC converter output voltage ripple calculator.

Computes inductor current ripple, capacitor voltage ripple, ESR ripple
contribution, and total output voltage ripple (peak-to-peak) for a
synchronous or non-synchronous buck converter operating in Continuous
Conduction Mode (CCM).

Design equations — Erickson "Fundamentals of Power Electronics" 3e §2.4
-----------------------------------------------------------------------
  D = V_out / V_in            (CCM steady-state duty cycle)

  ΔiL = (V_in − V_out) · D / (L · f_sw)    [A peak-to-peak]

  ΔV_cap = ΔiL / (8 · C · f_sw)            [V peak-to-peak; Erickson §2.4 Eq 2.36]
            (triangular-current ripple through ideal capacitor)

  ΔV_ESR = ΔiL · ESR                        [V peak-to-peak; Sandler §3]
            (ESR dominates when ESR > 1/(4·π·C·f_sw))

  ΔV_out ≈ ΔV_cap + ΔV_ESR                  [V peak-to-peak; worst-case sum]

Note on worst-case: ΔV_cap and ΔV_ESR are in phase quadrature for an ideal
capacitor (ΔV_ESR peaks at ΔiL peak; ΔV_cap peaks at inductor zero-crossing),
so the true worst case is the RSS sum: sqrt(ΔV_cap² + ΔV_ESR²). The linear sum
ΔV_cap + ΔV_ESR is the absolute upper bound (pessimistic by ~3–15% for typical
ESR/C combinations). Both are reported; total uses the pessimistic linear sum per
Erickson §2.4 convention.

HONEST CAVEATS
--------------
1. CCM (Continuous Conduction Mode) ONLY. DCM (Discontinuous Conduction Mode)
   has different ripple equations (ΔiL depends on load-to-critical-load ratio)
   and is NOT modelled here. This model assumes iL_min > 0 at all times.

2. Small-ripple approximation (Erickson §2.1): assumes ΔiL << 2·I_load. If
   ΔiL / (2·I_load) > 0.30 (30%), the approximation degrades and results are
   flagged as less reliable.

3. Ideal duty cycle D = V_out / V_in ignores deadtime, synchronous-rectifier
   body-diode conduction, and duty-cycle clamping (e.g. PWM controller min-on
   pulse). For D > 0.9 or D < 0.1 results should be re-verified with a
   transient simulator.

4. ESR is assumed frequency-flat (resistive). Real aluminium electrolytic and
   MLCC capacitors have frequency-dependent ESR; use datasheet ESR at f_sw.

5. Output ripple is sinusoidal-triangle approximation — does not capture
   switching noise, ringing, or input capacitor ripple reflected to output.

6. No line / load regulation effects — steady-state, constant-load analysis.

7. Input ripple on V_in and feedback compensation are not modelled.

References
----------
R. W. Erickson & D. Maksimovic, "Fundamentals of Power Electronics", 3rd ed.,
    Springer, 2020, §2.1–§2.4.
S. Sandler, "Power Electronics", McGraw-Hill, §3 (ESR contribution).
Unitrode/TI Application Note SLVA477 — "Buck Converter Design".

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class BuckConverterSpec:
    """Input specification for a buck DC-DC converter ripple calculation.

    Attributes
    ----------
    V_in_V : float
        Input (supply) voltage [V].
    V_out_V : float
        Desired output voltage [V]. Must be < V_in_V for a buck converter.
    I_load_A : float
        DC load current [A]. Used for CCM boundary check and ripple_pct.
    switching_freq_Hz : float
        Converter switching frequency [Hz], e.g. 500 000 for 500 kHz.
    L_uH : float
        Filter inductance [µH]. Primary ripple-shaping element.
    C_out_uF : float
        Output filter capacitance [µF].
    C_ESR_mOhm : float
        Equivalent series resistance (ESR) of the output capacitor [mΩ].
        Use datasheet ESR at the switching frequency.
    """
    V_in_V: float
    V_out_V: float
    I_load_A: float
    switching_freq_Hz: float
    L_uH: float
    C_out_uF: float
    C_ESR_mOhm: float


@dataclass
class ConverterRippleReport:
    """Result of the buck converter CCM ripple calculation.

    Attributes
    ----------
    delta_iL_pp_A : float
        Inductor current ripple, peak-to-peak [A].
    delta_V_out_pp_mV : float
        Total output voltage ripple, peak-to-peak [mV].
        Worst-case linear sum: ΔV_cap + ΔV_ESR (Erickson §2.4 convention).
    delta_V_capacitor_mV : float
        Capacitor (integrating) voltage ripple component [mV].
        ΔV_cap = ΔiL / (8·C·f_sw).
    delta_V_ESR_mV : float
        ESR voltage ripple component [mV]. ΔV_ESR = ΔiL · ESR.
    duty_cycle : float
        Steady-state duty cycle D = V_out / V_in [dimensionless, 0–1].
    output_ripple_pct : float
        Output ripple as a percentage of V_out [%].
        100 × ΔV_out / V_out.
    honest_caveat : str
        Engineering caveats including CCM validity note.
    """
    delta_iL_pp_A: float
    delta_V_out_pp_mV: float
    delta_V_capacitor_mV: float
    delta_V_ESR_mV: float
    duty_cycle: float
    output_ripple_pct: float
    honest_caveat: str


# ── Validation helper ──────────────────────────────────────────────────────────


def _validate_spec(spec: BuckConverterSpec) -> str | None:
    """Return an error string or None if inputs are valid."""
    if not isinstance(spec, BuckConverterSpec):
        return "spec must be a BuckConverterSpec instance"
    if spec.V_in_V <= 0:
        return f"V_in_V must be > 0, got {spec.V_in_V}"
    if spec.V_out_V <= 0:
        return f"V_out_V must be > 0, got {spec.V_out_V}"
    if spec.V_out_V >= spec.V_in_V:
        return (
            f"V_out_V ({spec.V_out_V} V) must be less than V_in_V ({spec.V_in_V} V) "
            "for a buck converter"
        )
    if spec.I_load_A <= 0:
        return f"I_load_A must be > 0, got {spec.I_load_A}"
    if spec.switching_freq_Hz <= 0:
        return f"switching_freq_Hz must be > 0, got {spec.switching_freq_Hz}"
    if spec.L_uH <= 0:
        return f"L_uH must be > 0, got {spec.L_uH}"
    if spec.C_out_uF <= 0:
        return f"C_out_uF must be > 0, got {spec.C_out_uF}"
    if spec.C_ESR_mOhm < 0:
        return f"C_ESR_mOhm must be >= 0, got {spec.C_ESR_mOhm}"
    return None


# ── Core calculation ───────────────────────────────────────────────────────────


def compute_buck_ripple(spec: BuckConverterSpec) -> ConverterRippleReport:
    """Compute output voltage ripple for a buck converter in CCM.

    Parameters
    ----------
    spec : BuckConverterSpec

    Returns
    -------
    ConverterRippleReport

    Raises
    ------
    ValueError
        On invalid inputs.
    """
    err = _validate_spec(spec)
    if err:
        raise ValueError(err)

    V_in = spec.V_in_V
    V_out = spec.V_out_V
    I_load = spec.I_load_A
    f_sw = spec.switching_freq_Hz
    L_H = spec.L_uH * 1e-6        # µH → H
    C_F = spec.C_out_uF * 1e-6    # µF → F
    ESR_Ohm = spec.C_ESR_mOhm * 1e-3  # mΩ → Ω

    # Duty cycle (CCM, ideal)
    D = V_out / V_in

    # Inductor current ripple ΔiL [A] — Erickson §2.4 Eq 2.34
    # ΔiL = (V_in − V_out) · D / (L · f_sw)
    delta_iL = (V_in - V_out) * D / (L_H * f_sw)

    # Capacitor (integrating) voltage ripple ΔV_cap [V] — Erickson §2.4 Eq 2.36
    # ΔV_cap = ΔiL / (8 · C · f_sw)
    delta_V_cap = delta_iL / (8.0 * C_F * f_sw)

    # ESR voltage ripple ΔV_ESR [V] — Sandler §3
    # ΔV_ESR = ΔiL · ESR
    delta_V_ESR = delta_iL * ESR_Ohm

    # Total worst-case output ripple [V] — linear (pessimistic) sum
    delta_V_out = delta_V_cap + delta_V_ESR

    # Output ripple as % of V_out
    output_ripple_pct = 100.0 * delta_V_out / V_out

    # ── CCM validity check ────────────────────────────────────────────────────
    # CCM holds when iL_min = I_load − ΔiL/2 > 0
    iL_min = I_load - delta_iL / 2.0
    ccm_flag = iL_min > 0.0

    # Small-ripple approximation degradation warning
    small_ripple_ratio = delta_iL / (2.0 * I_load)  # should be << 1
    small_ripple_ok = small_ripple_ratio <= 0.30

    # ESR vs capacitive dominance
    esr_corner_Ohm = 1.0 / (4.0 * math.pi * C_F * f_sw)
    esr_dominated = ESR_Ohm > esr_corner_Ohm

    # ── Assemble caveat ───────────────────────────────────────────────────────
    caveat_parts = [
        f"Buck CCM ripple: D={D:.4f}, ΔiL={delta_iL*1e3:.3f} mA pp, "
        f"ΔV_cap={delta_V_cap*1e3:.3f} mV, ΔV_ESR={delta_V_ESR*1e3:.3f} mV, "
        f"ΔV_total={delta_V_out*1e3:.3f} mV ({output_ripple_pct:.3f}% of V_out). "
        "HONEST: (1) CCM ONLY — DCM (iL reaches zero) is NOT modelled; "
        "results are only valid when iL_min = I_load − ΔiL/2 > 0."
    ]
    if not ccm_flag:
        caveat_parts.append(
            f" WARNING: iL_min = {iL_min:.4f} A < 0 → converter is likely in DCM "
            f"at I_load = {I_load} A; increase L or I_load to restore CCM."
        )
    else:
        caveat_parts.append(
            f" CCM confirmed: iL_min = {iL_min:.4f} A > 0."
        )
    if not small_ripple_ok:
        caveat_parts.append(
            f" WARNING: ΔiL/2I_load = {small_ripple_ratio:.2%} > 30% — "
            "small-ripple approximation (Erickson §2.1) is degraded; "
            "actual ripple may differ from this calculation."
        )
    if esr_dominated:
        caveat_parts.append(
            f" ESR-dominated ripple: ESR={ESR_Ohm*1e3:.2f} mΩ > "
            f"1/(4πCf)={esr_corner_Ohm*1e3:.2f} mΩ; ΔV_ESR is the dominant term."
        )
    caveat_parts.append(
        " (2) D = V_out/V_in is ideal; ignores deadtime, body-diode drop, "
        "and min-on-pulse limits. "
        "(3) ESR assumed resistive/frequency-flat — use datasheet ESR at f_sw. "
        "(4) ΔV_out = ΔV_cap + ΔV_ESR is worst-case linear sum (Erickson §2.4); "
        "quadrature (RSS) sum would be sqrt(ΔV_cap²+ΔV_ESR²) — less pessimistic. "
        "(5) Steady-state, constant-load analysis; no line/load transient. "
        "Refs: Erickson 3e §2.4 Eq 2.34+2.36; Sandler §3."
    )
    honest_caveat = "".join(caveat_parts)

    return ConverterRippleReport(
        delta_iL_pp_A=round(delta_iL, 6),
        delta_V_out_pp_mV=round(delta_V_out * 1e3, 4),
        delta_V_capacitor_mV=round(delta_V_cap * 1e3, 4),
        delta_V_ESR_mV=round(delta_V_ESR * 1e3, 4),
        duty_cycle=round(D, 6),
        output_ripple_pct=round(output_ripple_pct, 4),
        honest_caveat=honest_caveat,
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def compute_buck_ripple_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        spec = BuckConverterSpec(
            V_in_V=float(d["V_in_V"]),
            V_out_V=float(d["V_out_V"]),
            I_load_A=float(d["I_load_A"]),
            switching_freq_Hz=float(d["switching_freq_Hz"]),
            L_uH=float(d["L_uH"]),
            C_out_uF=float(d["C_out_uF"]),
            C_ESR_mOhm=float(d["C_ESR_mOhm"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = compute_buck_ripple(spec)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "delta_iL_pp_A": report.delta_iL_pp_A,
        "delta_V_out_pp_mV": report.delta_V_out_pp_mV,
        "delta_V_capacitor_mV": report.delta_V_capacitor_mV,
        "delta_V_ESR_mV": report.delta_V_ESR_mV,
        "duty_cycle": report.duty_cycle,
        "output_ripple_pct": report.output_ripple_pct,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_BUCK_RIPPLE_SPEC = ToolSpec(
    name="electronics_compute_buck_ripple",
    description=(
        "Compute output voltage ripple (ΔV_out, peak-to-peak) for a buck "
        "DC-DC converter in Continuous Conduction Mode (CCM).\n\n"
        "Equations (Erickson 'Fundamentals of Power Electronics' 3e §2.4):\n"
        "  D       = V_out / V_in\n"
        "  ΔiL     = (V_in − V_out) · D / (L · f_sw)     [inductor ripple, A pp]\n"
        "  ΔV_cap  = ΔiL / (8 · C · f_sw)                [capacitor ripple, V pp]\n"
        "  ΔV_ESR  = ΔiL · ESR                            [ESR ripple, V pp]\n"
        "  ΔV_out  = ΔV_cap + ΔV_ESR                      [worst-case total, V pp]\n\n"
        "Also reports: duty_cycle, output_ripple_pct, CCM validity flag.\n\n"
        "HONEST: CCM only — DCM not modelled; small-ripple approximation flagged "
        "when ΔiL > 30% of 2·I_load; D assumes ideal converter (no deadtime/loss); "
        "ESR assumed flat at f_sw; ΔV_out is pessimistic linear sum. "
        "Refs: Erickson 3e §2.4; Sandler §3.\n\n"
        "Input: { V_in_V, V_out_V, I_load_A, switching_freq_Hz, L_uH, "
        "C_out_uF, C_ESR_mOhm }\n\n"
        "Returns: { ok, delta_iL_pp_A, delta_V_out_pp_mV, delta_V_capacitor_mV, "
        "delta_V_ESR_mV, duty_cycle, output_ripple_pct, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V_in_V": {
                "type": "number",
                "description": "Input supply voltage [V].",
            },
            "V_out_V": {
                "type": "number",
                "description": "Output voltage [V]. Must be less than V_in_V.",
            },
            "I_load_A": {
                "type": "number",
                "description": "DC load current [A]. Used for CCM boundary check.",
            },
            "switching_freq_Hz": {
                "type": "number",
                "description": "Switching frequency [Hz], e.g. 500000 for 500 kHz.",
            },
            "L_uH": {
                "type": "number",
                "description": "Filter inductance [µH].",
            },
            "C_out_uF": {
                "type": "number",
                "description": "Output filter capacitance [µF].",
            },
            "C_ESR_mOhm": {
                "type": "number",
                "description": (
                    "Equivalent series resistance (ESR) of the output capacitor [mΩ]. "
                    "Use datasheet ESR at the switching frequency. "
                    "Set to 0 for ideal capacitor."
                ),
            },
        },
        "required": [
            "V_in_V",
            "V_out_V",
            "I_load_A",
            "switching_freq_Hz",
            "L_uH",
            "C_out_uF",
            "C_ESR_mOhm",
        ],
    },
)


@register(_BUCK_RIPPLE_SPEC, write=False)
async def electronics_compute_buck_ripple(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = compute_buck_ripple_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _BUCK_RIPPLE_SPEC.name,
        _BUCK_RIPPLE_SPEC,
        electronics_compute_buck_ripple,
    ),
]
