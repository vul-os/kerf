"""
Op-amp input offset voltage and temperature drift calculator.

Computes input-referred and output-referred total offset error over a
temperature range for precision instrumentation op-amp circuits.

Design equations — TI "Op Amp Errors" Application Report SLOA069 §3
and Analog Devices "Op Amp DC Errors" AN-580:
-----------------------------------------------------------------------
  Vos(T) = Vos_typ + Vos_drift × (T − T_ref)      [µV]

where T_ref is the reference temperature at which Vos_typ is specified
(datasheet typically at 25 °C), and Vos_drift is the offset-voltage
temperature coefficient (TC_Vos) in µV/°C.

  Vos_max_input_referred = max(|Vos(T_min)|, |Vos(T_max)|)   [µV]

  Vos_max_output_referred = gain × Vos_max_input_referred     [µV]
                          = gain × Vos_max_input_referred × 1e-3  [mV]

  error_pct_of_FS = 100 × (Vos_max_output_referred [V]) / signal_full_scale_V

Op-amp class thresholds (error budget vs signal full scale):
  - "standard"  : TC_Vos > 1 µV/°C  (general-purpose, e.g. LM741, TL071)
  - "precision"  : TC_Vos ≤ 1 µV/°C  (e.g. OPA227, AD8628, LT1012)
  - "zero-drift" : TC_Vos ≤ 0.1 µV/°C (e.g. OPA188, AD8551, LTC2050)
  - "chopper"    : TC_Vos ≤ 0.05 µV/°C (auto-zero/chopper-stabilised:
                   AD8551, ICL7650, MAX420)

Recommendation logic:
  error_pct >= 10 × budget  → recommend "chopper"  (order of magnitude over)
  error_pct >= budget        → recommend "precision" (over budget)
  TC_Vos > 1 µV/°C           → recommend "precision" regardless
  TC_Vos ≤ 0.05 µV/°C        → confirm "chopper"
  TC_Vos ≤ 0.1 µV/°C         → confirm "zero-drift"
  otherwise in-budget        → "standard"

HONEST CAVEATS
--------------
1. LINEAR drift model only: Vos(T) = Vos_typ + drift × ΔT assumes a
   constant TC_Vos over the temperature range. Real datasheets specify
   TC_Vos as a typical value; actual drift is non-linear and asymmetric
   (often larger drift from 25→−40 °C than 25→85 °C per TI SLOA069 Fig. 3-2).
   Always verify with the full-temperature Vos curve in the datasheet.

2. 1/f (flicker) noise contribution to DC offset is NOT modelled. At low
   bandwidths the low-frequency noise floor can contribute µV-level
   effective offset, particularly for BJT-input op-amps (e.g. OPA27).

3. PSRR and CMRR cross-talk effects are OUT OF SCOPE. Power-supply
   variations add Vos via PSRR (typically 80–120 dB for precision amps),
   and common-mode input range limits are not checked. Include PSRR
   contribution separately: ΔVos_PSRR = ΔVPS / PSRR.

4. Gain is assumed ideal (non-inverting or inverting gain magnitude;
   resistor tolerance errors are NOT included). Resistor TC mismatch
   introduces its own gain-drift term (Δgain/ΔT) that is not modelled.

5. Only the worst-case endpoint temperature determines the output offset.
   The reference temperature T_ref (25 °C by default) is the anchor;
   drift is evaluated at both T_min and T_max endpoints. If T_ref is not
   within [T_min, T_max] the entire range is one-sided.

6. Initial Vos_typ is used as the nominal offset at T_ref. Real parts
   have Vos within ±Vos_max (the guaranteed limit, typically 2–5 × Vos_typ).
   Use Vos_max for worst-case analysis, not Vos_typ.

References
----------
Texas Instruments, "Op Amp Errors," Application Report SLOA069, Nov 2002,
    §3 (Vos temperature drift, Eq. 3-1).
Analog Devices, "Op Amp DC Errors," Application Note AN-580, 2003,
    §1 (Vos drift model, recommended class boundaries).
OPA188 Datasheet (TI), "Ultra-Low Offset, Drift, and Bias Current Op Amp."
AD8551 Datasheet (Analog Devices), "Auto-Zero, Rail-to-Rail I/O Op Amp."
LT1012 Datasheet (Linear Technology), "Picoamp Input Current, Microvolt
    Offset Low Power Precision Op Amp."

Author: imranparuk
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class OpAmpSpec:
    """Input specification for an op-amp's DC offset error characteristics.

    Attributes
    ----------
    Vos_typ_uV : float
        Typical input offset voltage at T_reference_C [µV].
        Positive or negative; datasheet typically specifies ±|Vos|.
        Use the absolute-worst-case (|Vos_max|) for design margin,
        noting that this model uses the signed Vos_typ value as the
        anchor and adds the drift term on top. For worst-case analysis
        pass abs(Vos_max) with sign matching the worst drift direction.
    Vos_drift_uV_per_C : float
        Offset voltage temperature coefficient TC_Vos [µV/°C].
        Always positive (magnitude); the model evaluates both +drift
        and -drift directions and takes the worst case.
        Typical values: 0.05 µV/°C (chopper), 0.1–1 µV/°C (precision),
        1–10 µV/°C (general-purpose).
    T_ambient_min_C : float
        Minimum ambient temperature in the operating range [°C],
        e.g. 0.0 for commercial, -40.0 for industrial.
    T_ambient_max_C : float
        Maximum ambient temperature in the operating range [°C],
        e.g. 70.0 for commercial, 85.0 for industrial, 125.0 for
        automotive / military.
    T_reference_C : float
        Reference temperature at which Vos_typ is specified [°C].
        Default 25 °C per JEDEC/datasheet convention.
    """
    Vos_typ_uV: float
    Vos_drift_uV_per_C: float
    T_ambient_min_C: float
    T_ambient_max_C: float
    T_reference_C: float = 25.0


@dataclass
class CircuitSpec:
    """Circuit parameters for op-amp offset drift analysis.

    Attributes
    ----------
    gain_VV : float
        Closed-loop gain magnitude [V/V]. Must be ≥ 1.
        For a non-inverting amplifier with R_f and R_g:
            gain = 1 + R_f / R_g.
        For an inverting amplifier: gain = R_f / R_g.
        Pass the absolute gain magnitude (always positive).
    signal_full_scale_V : float
        Signal full-scale range [V]. Used to express the output offset
        error as a percentage of full scale (% FS). For a ±5 V ADC
        input range, use 10.0 V (peak-to-peak FS). For a 0–3.3 V
        unipolar range, use 3.3 V.
    """
    gain_VV: float
    signal_full_scale_V: float


@dataclass
class OpAmpOffsetReport:
    """Result of the op-amp offset voltage drift analysis.

    Attributes
    ----------
    Vos_at_T_min_uV : float
        Input-referred offset at T_ambient_min_C [µV].
        Vos(T_min) = Vos_typ + drift × (T_min − T_ref).
    Vos_at_T_max_uV : float
        Input-referred offset at T_ambient_max_C [µV].
        Vos(T_max) = Vos_typ + drift × (T_max − T_ref).
    Vos_max_input_referred_uV : float
        Worst-case (maximum magnitude) input-referred offset over the
        temperature range [µV]. max(|Vos(T_min)|, |Vos(T_max)|).
    Vos_max_output_referred_mV : float
        Output-referred offset at worst case [mV].
        = gain × Vos_max_input_referred_uV / 1000.
    error_pct_of_FS : float
        Output-referred offset as a percentage of signal full scale [%].
        = 100 × (Vos_max_output_referred_mV / 1000) / signal_full_scale_V.
    within_spec : bool
        True if error_pct_of_FS < error_budget_pct (the supplied budget).
    recommended_op_amp_class : str
        Recommended op-amp class to meet the error budget:
        "standard"  — TC_Vos > 1 µV/°C, in-budget general-purpose;
        "precision"  — TC_Vos ≤ 1 µV/°C (e.g. OPA227, AD8628, LT1012);
        "zero-drift" — TC_Vos ≤ 0.1 µV/°C (e.g. OPA188, LTC2050);
        "chopper"    — TC_Vos ≤ 0.05 µV/°C (e.g. AD8551, MAX420,
                       ICL7650); recommended when error >> budget.
    honest_caveat : str
        Engineering caveats: linear drift model, 1/f noise not modelled,
        PSRR/CMRR cross-talk out of scope, resistor TC not included.
    """
    Vos_at_T_min_uV: float
    Vos_at_T_max_uV: float
    Vos_max_input_referred_uV: float
    Vos_max_output_referred_mV: float
    error_pct_of_FS: float
    within_spec: bool
    recommended_op_amp_class: str
    honest_caveat: str


# ── Validation ────────────────────────────────────────────────────────────────


def _validate(op: OpAmpSpec, circuit: CircuitSpec) -> str | None:
    """Return an error string or None if inputs are valid."""
    if not isinstance(op, OpAmpSpec):
        return "op must be an OpAmpSpec instance"
    if not isinstance(circuit, CircuitSpec):
        return "circuit must be a CircuitSpec instance"
    if op.Vos_drift_uV_per_C < 0:
        return (
            f"Vos_drift_uV_per_C must be >= 0 (magnitude), "
            f"got {op.Vos_drift_uV_per_C}"
        )
    if op.T_ambient_min_C >= op.T_ambient_max_C:
        return (
            f"T_ambient_min_C ({op.T_ambient_min_C} °C) must be "
            f"< T_ambient_max_C ({op.T_ambient_max_C} °C)"
        )
    if circuit.gain_VV <= 0:
        return f"gain_VV must be > 0, got {circuit.gain_VV}"
    if circuit.signal_full_scale_V <= 0:
        return (
            f"signal_full_scale_V must be > 0, got {circuit.signal_full_scale_V}"
        )
    return None


# ── Core calculation ──────────────────────────────────────────────────────────


def compute_op_amp_drift(
    op: OpAmpSpec,
    circuit: CircuitSpec,
    error_budget_pct: float = 0.1,
) -> OpAmpOffsetReport:
    """Compute input- and output-referred op-amp offset over a temperature range.

    Parameters
    ----------
    op : OpAmpSpec
        Op-amp offset voltage specification.
    circuit : CircuitSpec
        Circuit gain and signal full-scale parameters.
    error_budget_pct : float
        Allowed output offset error as a percentage of signal full scale [%].
        Default 0.1 % (1 LSB of a 10-bit ADC at full scale).

    Returns
    -------
    OpAmpOffsetReport

    Raises
    ------
    ValueError
        On invalid inputs.

    Notes
    -----
    The drift model is signed: Vos(T) = Vos_typ + drift × (T − T_ref),
    where drift has a sign that depends on the device (positive for most
    op-amps, negative for some). To model worst-case, the implementation
    evaluates both the +drift and −drift directions and takes the maximum
    absolute offset. This ensures that a large positive Vos_typ combined
    with positive drift in the hot direction is captured, as is the case
    where Vos_typ is negative and drift reinforces it in the cold direction.

    References: TI SLOA069 §3 Eq. 3-1; Analog Devices AN-580 §1.
    """
    err = _validate(op, circuit)
    if err:
        raise ValueError(err)

    Vos_typ = op.Vos_typ_uV
    drift = op.Vos_drift_uV_per_C  # magnitude; always >= 0
    T_min = op.T_ambient_min_C
    T_max = op.T_ambient_max_C
    T_ref = op.T_reference_C
    gain = circuit.gain_VV
    FS = circuit.signal_full_scale_V

    # ── Vos(T) = Vos_typ + drift × (T − T_ref) ─────────────────────────────
    # Evaluate at both temperature endpoints with positive drift direction
    Vos_at_T_min_pos = Vos_typ + drift * (T_min - T_ref)
    Vos_at_T_max_pos = Vos_typ + drift * (T_max - T_ref)

    # Also evaluate with negative drift direction (worst case for negative Vos_typ)
    Vos_at_T_min_neg = Vos_typ - drift * (T_min - T_ref)
    Vos_at_T_max_neg = Vos_typ - drift * (T_max - T_ref)

    # Worst-case signed endpoints (most negative or most positive)
    # Use the sign convention that produces the largest absolute value
    # Report the canonical +drift direction values for T_min and T_max
    Vos_at_T_min = Vos_at_T_min_pos
    Vos_at_T_max = Vos_at_T_max_pos

    # Worst-case input-referred offset: max absolute over all combinations
    candidates = [
        abs(Vos_at_T_min_pos), abs(Vos_at_T_max_pos),
        abs(Vos_at_T_min_neg), abs(Vos_at_T_max_neg),
    ]
    Vos_max_input_uV = max(candidates)

    # ── Output-referred offset ────────────────────────────────────────────────
    # Vos_output [mV] = gain × Vos_max_input [µV] / 1000
    Vos_max_output_mV = gain * Vos_max_input_uV / 1000.0

    # ── Error as % of full scale ──────────────────────────────────────────────
    # error_pct = 100 × (Vos_max_output_V / FS_V)
    Vos_max_output_V = Vos_max_output_mV / 1000.0
    error_pct = 100.0 * Vos_max_output_V / FS

    # ── Within spec ──────────────────────────────────────────────────────────
    within_spec = error_pct < error_budget_pct

    # ── Op-amp class recommendation ───────────────────────────────────────────
    # Based on drift coefficient AND error budget headroom:
    #
    # If error is more than 10× over budget → strongly recommend chopper
    # If error is over budget → recommend precision (and possibly zero-drift/chopper)
    # If in-budget:
    #   TC_Vos ≤ 0.05 µV/°C → chopper (already there or better)
    #   TC_Vos ≤ 0.10 µV/°C → zero-drift
    #   TC_Vos ≤ 1.00 µV/°C → precision
    #   TC_Vos > 1.00 µV/°C → standard (within budget but marginal)
    if not within_spec:
        if error_pct >= 10.0 * error_budget_pct:
            recommended_class = "chopper"
        elif drift <= 0.05:
            # Already chopper-class drift but still over budget
            # (budget is very tight) — stay chopper
            recommended_class = "chopper"
        elif drift <= 0.1:
            recommended_class = "zero-drift"
        else:
            recommended_class = "precision"
    else:
        # Within budget — confirm or upgrade the classification
        if drift <= 0.05:
            recommended_class = "chopper"
        elif drift <= 0.1:
            recommended_class = "zero-drift"
        elif drift <= 1.0:
            recommended_class = "precision"
        else:
            recommended_class = "standard"

    # ── Assemble honest caveat ───────────────────────────────────────────────
    caveat_parts = [
        f"Op-amp offset drift: Vos_typ={Vos_typ:.1f} µV, "
        f"TC_Vos={drift:.4f} µV/°C, "
        f"T=[{T_min:.0f}..{T_max:.0f}] °C (Tref={T_ref:.0f} °C), "
        f"gain={gain:.1f}×, FS={FS:.2f} V. "
        f"Results: Vos(T_min)={Vos_at_T_min:.2f} µV, "
        f"Vos(T_max)={Vos_at_T_max:.2f} µV, "
        f"worst-case input-referred={Vos_max_input_uV:.2f} µV, "
        f"output-referred={Vos_max_output_mV:.4f} mV, "
        f"error={error_pct:.4f}% FS "
        f"({'WITHIN' if within_spec else 'EXCEEDS'} {error_budget_pct:.2f}% budget). "
        f"Recommended class: {recommended_class}. "
        "HONEST: "
        "(1) LINEAR drift model — Vos(T)=Vos_typ+TC_Vos×(T−Tref); real drift is "
        "non-linear and often asymmetric (TI SLOA069 Fig 3-2); verify against "
        "full-temperature Vos curve in the datasheet. "
        "(2) Vos_typ is the nominal (not guaranteed) offset; worst-case Vos_max is "
        "typically 2–5× larger — rerun with Vos_max for design margin. "
        "(3) 1/f (flicker) noise contribution to DC offset is NOT modelled — "
        "at sub-Hz bandwidths and low supply voltages this can add µV-level "
        "effective offset (dominant for BJT-input amps like OPA27). "
        "(4) PSRR / CMRR cross-talk effects are OUT OF SCOPE — power-supply "
        "variations add ΔVos = ΔVPS/PSRR; include separately for complete "
        "budget. "
        "(5) Resistor tolerance and TC mismatch in the feedback network add "
        "gain-drift error NOT captured here. "
        "Refs: TI SLOA069 §3 Eq. 3-1; Analog Devices AN-580 §1.",
    ]
    honest_caveat = "".join(caveat_parts)

    return OpAmpOffsetReport(
        Vos_at_T_min_uV=round(Vos_at_T_min, 4),
        Vos_at_T_max_uV=round(Vos_at_T_max, 4),
        Vos_max_input_referred_uV=round(Vos_max_input_uV, 4),
        Vos_max_output_referred_mV=round(Vos_max_output_mV, 6),
        error_pct_of_FS=round(error_pct, 6),
        within_spec=within_spec,
        recommended_op_amp_class=recommended_class,
        honest_caveat=honest_caveat,
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def compute_op_amp_drift_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        op = OpAmpSpec(
            Vos_typ_uV=float(d["Vos_typ_uV"]),
            Vos_drift_uV_per_C=float(d["Vos_drift_uV_per_C"]),
            T_ambient_min_C=float(d["T_ambient_min_C"]),
            T_ambient_max_C=float(d["T_ambient_max_C"]),
            T_reference_C=float(d.get("T_reference_C", 25.0)),
        )
        circuit = CircuitSpec(
            gain_VV=float(d["gain_VV"]),
            signal_full_scale_V=float(d["signal_full_scale_V"]),
        )
        error_budget_pct = float(d.get("error_budget_pct", 0.1))
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid input: {exc}"}

    try:
        report = compute_op_amp_drift(op, circuit, error_budget_pct)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "Vos_at_T_min_uV": report.Vos_at_T_min_uV,
        "Vos_at_T_max_uV": report.Vos_at_T_max_uV,
        "Vos_max_input_referred_uV": report.Vos_max_input_referred_uV,
        "Vos_max_output_referred_mV": report.Vos_max_output_referred_mV,
        "error_pct_of_FS": report.error_pct_of_FS,
        "within_spec": report.within_spec,
        "recommended_op_amp_class": report.recommended_op_amp_class,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_OP_AMP_OFFSET_DRIFT_SPEC = ToolSpec(
    name="electronics_compute_op_amp_drift",
    description=(
        "Compute op-amp input offset voltage drift and output-referred error "
        "over a temperature range for precision instrumentation design.\n\n"
        "Equations (TI 'Op Amp Errors' SLOA069 §3 + Analog Devices AN-580 §1):\n"
        "  Vos(T) = Vos_typ + TC_Vos × (T − T_ref)      [µV]\n"
        "  Vos_max_IR = max(|Vos(T_min)|, |Vos(T_max)|)  [µV, input-referred]\n"
        "  Vos_OR = gain × Vos_max_IR / 1000             [mV, output-referred]\n"
        "  error_pct = 100 × (Vos_OR / 1000) / FS_V     [% of full scale]\n\n"
        "Recommends op-amp class: 'standard' (TC>1 µV/°C), 'precision' "
        "(TC≤1 µV/°C), 'zero-drift' (TC≤0.1 µV/°C), 'chopper' (TC≤0.05 µV/°C).\n\n"
        "HONEST: linear drift model only — real drift is non-linear and "
        "asymmetric (TI SLOA069 Fig 3-2); 1/f noise NOT modelled; PSRR/CMRR "
        "cross-talk OUT OF SCOPE; resistor TC mismatch NOT included. "
        "Use Vos_max (not Vos_typ) for guaranteed worst-case analysis.\n\n"
        "Input: { Vos_typ_uV, Vos_drift_uV_per_C, T_ambient_min_C, "
        "T_ambient_max_C, [T_reference_C=25], gain_VV, signal_full_scale_V, "
        "[error_budget_pct=0.1] }\n\n"
        "Returns: { ok, Vos_at_T_min_uV, Vos_at_T_max_uV, "
        "Vos_max_input_referred_uV, Vos_max_output_referred_mV, "
        "error_pct_of_FS, within_spec, recommended_op_amp_class, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Vos_typ_uV": {
                "type": "number",
                "description": (
                    "Typical input offset voltage at T_reference_C [µV]. "
                    "Positive or negative per datasheet polarity. "
                    "Use |Vos_max| for worst-case design margin."
                ),
            },
            "Vos_drift_uV_per_C": {
                "type": "number",
                "description": (
                    "Offset voltage temperature coefficient TC_Vos [µV/°C], "
                    "magnitude (always ≥ 0). Typical: 0.05 (chopper), "
                    "0.1–1 (precision), 1–10 (general-purpose)."
                ),
            },
            "T_ambient_min_C": {
                "type": "number",
                "description": (
                    "Minimum ambient operating temperature [°C]. "
                    "e.g. 0 (commercial), -40 (industrial/automotive)."
                ),
            },
            "T_ambient_max_C": {
                "type": "number",
                "description": (
                    "Maximum ambient operating temperature [°C]. "
                    "e.g. 70 (commercial), 85 (industrial), 125 (automotive)."
                ),
            },
            "T_reference_C": {
                "type": "number",
                "description": (
                    "Reference temperature at which Vos_typ is specified [°C]. "
                    "Default 25 °C."
                ),
            },
            "gain_VV": {
                "type": "number",
                "description": (
                    "Closed-loop gain magnitude [V/V]. Must be ≥ 1. "
                    "For non-inverting: 1+Rf/Rg. For inverting: Rf/Rg."
                ),
            },
            "signal_full_scale_V": {
                "type": "number",
                "description": (
                    "Signal full-scale range [V] for % error calculation. "
                    "e.g. 10.0 for ±5V ADC range, 3.3 for 0–3.3V unipolar."
                ),
            },
            "error_budget_pct": {
                "type": "number",
                "description": (
                    "Allowable output offset error as % of full scale [%]. "
                    "Default 0.1% (approx 1 LSB of 10-bit ADC at FS)."
                ),
            },
        },
        "required": [
            "Vos_typ_uV",
            "Vos_drift_uV_per_C",
            "T_ambient_min_C",
            "T_ambient_max_C",
            "gain_VV",
            "signal_full_scale_V",
        ],
    },
)


@register(_OP_AMP_OFFSET_DRIFT_SPEC, write=False)
async def electronics_compute_op_amp_drift(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = compute_op_amp_drift_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ─────────────────────────

TOOLS = [
    (
        _OP_AMP_OFFSET_DRIFT_SPEC.name,
        _OP_AMP_OFFSET_DRIFT_SPEC,
        electronics_compute_op_amp_drift,
    ),
]
