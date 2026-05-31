"""
Optocoupler isolation circuit analysis.

Given LED forward current IF, CTR (min/typ/max), pull-up resistor R_L,
supply Vcc, and load capacitance C_L, computes:

  - Output collector current IC (min / typ / max)
  - Saturation current IC_sat = Vcc / R_L
  - Whether IC_min >= IC_sat (output is saturated — valid logic-low)
  - Vout_low = Vce_sat, Vout_high = Vcc
  - Output rise/fall time via t ≈ 2.2 × R_L × C_L (RC charge/discharge)
    scaled by (R_L_actual / R_L_spec) when a datasheet value is supplied
  - Headroom factor = IC_min / IC_sat
  - Warnings for under-drive, over-drive, missing saturation

References
----------
Vishay VISHAY-OPT Application Note AN-38 "Optocoupler Output Response Time"
Avago/Broadcom Application Note 5078 "Using Optocouplers"
IEC 60747-5-5:2007 — Discrete semiconductor devices — Optoelectronic devices
    Part 5-5: Optocouplers for general purpose use

CTR definition (IEC 60747-5-5 §6.3):
    CTR [%] = 100 × IC [mA] / IF [mA]
    → IC = CTR/100 × IF

Saturation condition (Vishay AN-38 + Avago AN-5078):
    For the phototransistor output to be in saturation (producing valid
    logic-level LOW output), the collector current IC must exceed the
    saturation drive current IC_sat = (Vcc − Vce_sat) / R_L ≈ Vcc / R_L
    (Vce_sat << Vcc for typical 3.3–5 V systems).

    headroom_factor = IC_min / IC_sat
    saturated        = IC_min >= IC_sat

Rise / fall time estimation (Vishay AN-38 §3):
    The dominant time constant for the rising edge (output switching low
    to high, phototransistor turning ON) when the load is a simple RC:

        t_rise ≈ 2.2 × R_L × C_L   [RC charge to 90% of Vcc]

    For the falling edge (turning OFF) the time constant is the same in
    a simple R-C model; a true switching circuit may differ but the R_L·C_L
    product dominates at typical logic levels.

    When a datasheet rise-time spec is provided (t_rise_us, R_L_spec_ohm),
    scale linearly to the actual pull-up:

        t_rise_actual = t_rise_spec × (R_L_actual / R_L_spec)

    Using the larger of the RC-model value and the scaled datasheet value
    gives a conservative upper bound.

HONEST CAVEATS
--------------
1. LINEAR CTR MODEL ONLY.  CTR is modelled as constant over the operating
   current range: IC = CTR/100 × IF.  In reality CTR peaks at a moderate
   IF (~2–10 mA for most devices) and falls at both very low and very high
   IF (due to emitter recombination at low current and high-level injection
   at high current).  For precision design, use the full CTR vs IF curve from
   the datasheet.

2. TEMPERATURE DERATING NOT MODELLED.  Over device lifetime, LED forward
   voltage Vf rises and LED efficiency falls, reducing IF and hence CTR by
   30–50% over 10–15 years of continuous operation at elevated temperatures
   (Avago AN-5078 §4.3).  Always derate CTR by the manufacturer's de-rating
   factor (typically use CTR_min at the maximum rated temperature, not 25°C).

3. INPUT SIDE LED CURRENT APPROXIMATION.  The IF given to this function is
   taken as delivered to the LED.  The actual IF in circuit is:
       IF = (V_drive − Vf) / R_LED_series
   For precision, compute IF from the circuit and supply it explicitly.

4. Vce_sat IS A FIXED DATASHEET VALUE.  Real Vce_sat depends on IC
   (heavier saturation drive lowers Vce_sat) and temperature.  The value
   here is the datasheet worst-case spec at the tested operating point.

5. RISE/FALL TIME IS AN R·C ESTIMATE.  The actual switching speed depends
   on minority-carrier storage time in the phototransistor, which is NOT
   modelled here.  For high-speed designs (>100 kbaud) use the optocoupler's
   full propagation delay + transition-time datasheets (e.g. HCPL-2611
   t_PLH/t_PHL at the specified R_L and V_CC).

6. ISOLATION VOLTAGE NOT CHECKED.  IEC 60747-5-5 insulation requirements
   (V_IORM, V_test) are outside the scope of this tool; verify V_IORM >= peak
   working voltage plus the required CTI/creepage margins independently.

Refs:
- Vishay Application Note AN-38 "Optocoupler Output Response Time"
- Avago/Broadcom Application Note 5078 "Using Optocouplers"
- IEC 60747-5-5:2007 §6.3 (CTR definition)
- 4N35 datasheet (Vishay / Fairchild / ON Semi)
- PC817 datasheet (Sharp / Everlight)
- HCPL-2611 datasheet (Broadcom)

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, List, Optional

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class OptocouplerSpec:
    """Specification for an optocoupler device.

    Attributes
    ----------
    model : str
        Part number / model name for identification (e.g. "4N35", "PC817").
    IF_mA : float
        LED forward current actually delivered [mA].  This is the current
        through the LED in the actual circuit (not the rated maximum).
    CTR_min_percent : float
        Minimum current transfer ratio at IF_mA [%].
        IC_min = CTR_min/100 × IF_mA.
    CTR_typ_percent : float
        Typical current transfer ratio at IF_mA [%].
    CTR_max_percent : float
        Maximum current transfer ratio at IF_mA [%].
    Vce_sat_V : float
        Collector-emitter saturation voltage [V] (datasheet worst-case).
        Typical 0.1–0.3 V for low-speed devices; higher for high-speed.
    IF_max_mA : float
        Maximum rated LED forward current [mA].  Used to warn if IF_mA
        exceeds this limit.
    Vf_typ_V : float
        Typical LED forward voltage [V].  Default 1.2 V (infrared LED).
    t_rise_us_at_Rl : tuple[float, float]
        (t_rise_us, R_L_at_which_spec_taken_ohms): datasheet rise time
        [µs] measured at R_L = R_L_spec [Ω].  Default (2.0, 1000).
        Set t_rise_us = 0.0 to use only the RC model.
    """
    model: str
    IF_mA: float
    CTR_min_percent: float
    CTR_typ_percent: float
    CTR_max_percent: float
    Vce_sat_V: float
    IF_max_mA: float
    Vf_typ_V: float = 1.2
    t_rise_us_at_Rl: tuple = field(default_factory=lambda: (2.0, 1000.0))


@dataclass
class CircuitSpec:
    """Circuit-level specification around the optocoupler.

    Attributes
    ----------
    Vcc_out_V : float
        Output-side supply voltage [V] (collector pull-up supply).
    R_pullup_ohm : float
        Pull-up resistor from Vcc to optocoupler collector [Ω].
    C_load_pF : float
        Load capacitance at the collector node [pF].  Default 20 pF.
    R_LED_series_ohm : float
        Series resistor on the LED input side [Ω].  Used to compute IF
        for validation (not used in CTR calc when IF_mA is given directly).
    V_LED_drive_V : float
        Drive voltage applied to the LED + series resistor side [V].
    """
    Vcc_out_V: float
    R_pullup_ohm: float
    C_load_pF: float
    R_LED_series_ohm: float
    V_LED_drive_V: float


@dataclass
class OptocouplerReport:
    """Result of optocoupler isolation circuit analysis.

    Attributes
    ----------
    IC_min_mA : float
        Minimum collector current [mA] = CTR_min/100 × IF_mA.
    IC_typ_mA : float
        Typical collector current [mA] = CTR_typ/100 × IF_mA.
    IC_max_mA : float
        Maximum collector current [mA] = CTR_max/100 × IF_mA.
    IC_saturation_mA : float
        Current required to saturate output [mA] = Vcc / R_pullup.
        (Uses Vcc only; Vce_sat correction is small at 3.3–5 V).
    saturated_min_case : bool
        True if IC_min_mA >= IC_saturation_mA (worst-case is saturated).
    Vout_low_V : float
        Output voltage in the LOW state [V] = Vce_sat (datasheet spec).
    Vout_high_V : float
        Output voltage in the HIGH state [V] = Vcc (pull-up to Vcc).
    t_rise_us : float
        Estimated output rise time [µs] (output HIGH→LOW, opto turns ON).
    t_fall_us : float
        Estimated output fall time [µs] (output LOW→HIGH, opto turns OFF).
    headroom_factor_min : float
        Saturation headroom = IC_min_mA / IC_saturation_mA.
        > 1.0 means saturated in worst case; < 1.0 means NOT saturated.
    warnings : list[str]
        List of engineering warnings (IF over-limit, not saturated, etc.).
    honest_caveat : str
        Honest caveats about model limitations.
    """
    IC_min_mA: float
    IC_typ_mA: float
    IC_max_mA: float
    IC_saturation_mA: float
    saturated_min_case: bool
    Vout_low_V: float
    Vout_high_V: float
    t_rise_us: float
    t_fall_us: float
    headroom_factor_min: float
    warnings: List[str]
    honest_caveat: str


# ── Validation ─────────────────────────────────────────────────────────────────


def _validate(opto: OptocouplerSpec, circuit: CircuitSpec) -> Optional[str]:
    """Return an error string or None if inputs are valid."""
    if opto.IF_mA <= 0:
        return f"IF_mA must be > 0, got {opto.IF_mA}"
    if opto.CTR_min_percent < 0:
        return f"CTR_min_percent must be >= 0, got {opto.CTR_min_percent}"
    if opto.CTR_typ_percent < opto.CTR_min_percent:
        return (
            f"CTR_typ_percent ({opto.CTR_typ_percent}) must be >= "
            f"CTR_min_percent ({opto.CTR_min_percent})"
        )
    if opto.CTR_max_percent < opto.CTR_typ_percent:
        return (
            f"CTR_max_percent ({opto.CTR_max_percent}) must be >= "
            f"CTR_typ_percent ({opto.CTR_typ_percent})"
        )
    if opto.Vce_sat_V < 0:
        return f"Vce_sat_V must be >= 0, got {opto.Vce_sat_V}"
    if opto.IF_max_mA <= 0:
        return f"IF_max_mA must be > 0, got {opto.IF_max_mA}"
    if circuit.Vcc_out_V <= 0:
        return f"Vcc_out_V must be > 0, got {circuit.Vcc_out_V}"
    if circuit.R_pullup_ohm <= 0:
        return f"R_pullup_ohm must be > 0, got {circuit.R_pullup_ohm}"
    if circuit.C_load_pF < 0:
        return f"C_load_pF must be >= 0, got {circuit.C_load_pF}"
    if circuit.R_LED_series_ohm < 0:
        return f"R_LED_series_ohm must be >= 0, got {circuit.R_LED_series_ohm}"
    if circuit.V_LED_drive_V < 0:
        return f"V_LED_drive_V must be >= 0, got {circuit.V_LED_drive_V}"
    return None


# ── Core function ──────────────────────────────────────────────────────────────


def analyze_optocoupler(
    opto: OptocouplerSpec,
    circuit: CircuitSpec,
) -> OptocouplerReport:
    """Analyze an optocoupler isolation circuit.

    Algorithm
    ---------
    1. Collector currents (IEC 60747-5-5 §6.3):
         IC_min = CTR_min/100 × IF_mA   [mA]
         IC_typ = CTR_typ/100 × IF_mA   [mA]
         IC_max = CTR_max/100 × IF_mA   [mA]

    2. Saturation drive current:
         IC_sat = Vcc / R_pullup × 1000  [mA]
         (Conservative: ignores Vce_sat drop; Vce_sat << Vcc for 3.3–5 V)

    3. Saturation check:
         headroom = IC_min / IC_sat
         saturated_min_case = (IC_min >= IC_sat)

    4. Output voltages:
         Vout_low  = Vce_sat  (datasheet spec, worst-case)
         Vout_high = Vcc

    5. Timing — RC dominant pole (Vishay AN-38 §3):
         R_L = R_pullup
         C_L = C_load_pF × 1e-12
         t_RC_us = 2.2 × R_L × C_L × 1e6

       Datasheet scaling:
         t_rise_spec [µs], R_L_spec [Ω] from opto.t_rise_us_at_Rl
         t_rise_scaled = t_rise_spec × (R_L_actual / R_L_spec)

       Final rise/fall: max(t_RC_us, t_rise_scaled) — conservative upper bound.
       (Rise and fall are symmetric in the simple R-C model.)

    Parameters
    ----------
    opto : OptocouplerSpec
    circuit : CircuitSpec

    Returns
    -------
    OptocouplerReport

    Raises
    ------
    ValueError
        On invalid or physically inconsistent inputs.
    """
    err = _validate(opto, circuit)
    if err:
        raise ValueError(err)

    # ── 1. Collector currents ─────────────────────────────────────────────────
    IC_min_mA = opto.CTR_min_percent / 100.0 * opto.IF_mA
    IC_typ_mA = opto.CTR_typ_percent / 100.0 * opto.IF_mA
    IC_max_mA = opto.CTR_max_percent / 100.0 * opto.IF_mA

    # ── 2. Saturation threshold ───────────────────────────────────────────────
    # IC_sat = Vcc / R_L (in mA)
    # (Strictly: IC_sat = (Vcc - Vce_sat) / R_L but Vce_sat << Vcc; the
    # conservative formulation uses full Vcc to give a slightly higher bar.)
    IC_sat_mA = (circuit.Vcc_out_V / circuit.R_pullup_ohm) * 1000.0

    # ── 3. Saturation check ───────────────────────────────────────────────────
    saturated_min = IC_min_mA >= IC_sat_mA
    if IC_sat_mA > 0:
        headroom = IC_min_mA / IC_sat_mA
    else:
        headroom = float("inf")

    # ── 4. Output voltages ────────────────────────────────────────────────────
    Vout_low = opto.Vce_sat_V
    Vout_high = circuit.Vcc_out_V

    # ── 5. Rise / fall time ───────────────────────────────────────────────────
    R_L = circuit.R_pullup_ohm
    C_L_F = circuit.C_load_pF * 1e-12

    # RC model: 2.2τ to reach 90 % of final value
    t_RC_us = 2.2 * R_L * C_L_F * 1e6

    # Datasheet-specified rise time at a reference R_L
    t_rise_spec_us, R_L_spec_ohm = opto.t_rise_us_at_Rl
    if t_rise_spec_us > 0 and R_L_spec_ohm > 0:
        t_rise_scaled_us = t_rise_spec_us * (R_L / R_L_spec_ohm)
    else:
        t_rise_scaled_us = 0.0

    # Take the larger of the two estimates for a conservative bound
    t_rise_us = max(t_RC_us, t_rise_scaled_us)
    # Fall time symmetric in RC model
    t_fall_us = t_rise_us

    # ── 6. Warnings ───────────────────────────────────────────────────────────
    warnings: List[str] = []

    if opto.IF_mA > opto.IF_max_mA:
        warnings.append(
            f"IF_mA ({opto.IF_mA} mA) exceeds IF_max ({opto.IF_max_mA} mA) — "
            f"LED may be damaged; reduce IF or add series resistance."
        )

    if not saturated_min:
        warnings.append(
            f"NOT SATURATED in worst case (min CTR): IC_min = {IC_min_mA:.3f} mA < "
            f"IC_sat = {IC_sat_mA:.3f} mA "
            f"(headroom = {headroom:.3f}). "
            f"Output Vout_low will be ABOVE Vce_sat — "
            f"output may not reach a valid logic-LOW level. "
            f"Increase IF, increase CTR_min grade, or reduce R_L."
        )

    if IC_max_mA > IC_sat_mA * 10:
        warnings.append(
            f"IC_max ({IC_max_mA:.1f} mA) >> 10× IC_sat ({IC_sat_mA:.3f} mA) — "
            f"deep saturation; typical case, no action required unless "
            f"phototransistor absolute maximum IC is exceeded."
        )

    if headroom < 2.0 and saturated_min:
        warnings.append(
            f"Saturation headroom is low (headroom = {headroom:.2f}× < 2.0×). "
            f"CTR degrades with temperature and LED aging (30–50% over lifetime). "
            f"Recommend headroom ≥ 2–3× for robust production design "
            f"(Avago AN-5078 §4.3)."
        )

    # Verify the inferred IF from the LED drive circuit matches the spec
    if circuit.R_LED_series_ohm > 0 and circuit.V_LED_drive_V > 0:
        IF_circuit_mA = max(
            0.0,
            (circuit.V_LED_drive_V - opto.Vf_typ_V) / circuit.R_LED_series_ohm * 1000.0,
        )
        if abs(IF_circuit_mA - opto.IF_mA) > opto.IF_mA * 0.25:
            warnings.append(
                f"Circuit-derived IF = {IF_circuit_mA:.2f} mA "
                f"(= (V_drive={circuit.V_LED_drive_V}V − Vf={opto.Vf_typ_V}V) / "
                f"R_series={circuit.R_LED_series_ohm}Ω × 1000) "
                f"differs from spec IF_mA = {opto.IF_mA:.2f} mA by > 25%. "
                f"Verify series resistor and drive voltage values."
            )

    # ── 7. Honest caveat ──────────────────────────────────────────────────────
    caveat = (
        f"Optocoupler analysis ({opto.model}): "
        f"IF={opto.IF_mA} mA, CTR=[{opto.CTR_min_percent}..{opto.CTR_typ_percent}.."
        f"{opto.CTR_max_percent}]%, "
        f"IC=[{IC_min_mA:.3f}..{IC_typ_mA:.3f}..{IC_max_mA:.3f}] mA, "
        f"IC_sat={IC_sat_mA:.3f} mA (Vcc={circuit.Vcc_out_V}V / R_L={circuit.R_pullup_ohm}Ω), "
        f"headroom={headroom:.2f}x, "
        f"saturated_min_case={saturated_min}."
        " HONEST CAVEATS: "
        "(1) LINEAR CTR MODEL ONLY — IC = CTR/100 × IF; real CTR peaks at moderate IF "
        "and falls at both extremes (low-current recombination; high-current injection); "
        "for precision design use the full CTR-vs-IF curve from the datasheet. "
        "(2) TEMPERATURE AND LIFETIME DERATING NOT MODELLED — CTR degrades 30–50% over "
        "LED lifetime at elevated temperature (Avago AN-5078 §4.3); always derate CTR "
        "to the datasheet minimum at maximum rated temperature, not the 25 °C value. "
        "(3) Vce_sat is the fixed datasheet spec value; actual Vce_sat depends on IC "
        "(more saturation drive reduces Vce_sat) and junction temperature. "
        "(4) RISE/FALL TIME is an RC estimate (2.2 × R_L × C_L); minority-carrier "
        "storage time in the phototransistor is NOT modelled — for high-speed designs "
        "use the datasheet t_PLH/t_PHL at your exact R_L and V_CC. "
        "(5) ISOLATION VOLTAGE NOT CHECKED — verify V_IORM >= peak working voltage "
        "plus IEC 60747-5-5 creepage/clearance margins independently. "
        "(6) Input-side LED current is taken as given (IF_mA); circuit-level variation "
        "from Vf spread (±0.1–0.2 V typical) and resistor tolerance not propagated. "
        "Refs: Vishay AN-38; Avago AN-5078; IEC 60747-5-5:2007 §6.3."
    )

    return OptocouplerReport(
        IC_min_mA=round(IC_min_mA, 6),
        IC_typ_mA=round(IC_typ_mA, 6),
        IC_max_mA=round(IC_max_mA, 6),
        IC_saturation_mA=round(IC_sat_mA, 6),
        saturated_min_case=saturated_min,
        Vout_low_V=opto.Vce_sat_V,
        Vout_high_V=circuit.Vcc_out_V,
        t_rise_us=round(t_rise_us, 6),
        t_fall_us=round(t_fall_us, 6),
        headroom_factor_min=round(headroom, 6),
        warnings=warnings,
        honest_caveat=caveat,
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def analyze_optocoupler_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        t_rise_raw = d.get("t_rise_us_at_Rl", [2.0, 1000.0])
        if isinstance(t_rise_raw, (list, tuple)) and len(t_rise_raw) == 2:
            t_rise_tuple = (float(t_rise_raw[0]), float(t_rise_raw[1]))
        else:
            t_rise_tuple = (2.0, 1000.0)

        opto = OptocouplerSpec(
            model=str(d.get("model", "unknown")),
            IF_mA=float(d["IF_mA"]),
            CTR_min_percent=float(d["CTR_min_percent"]),
            CTR_typ_percent=float(d["CTR_typ_percent"]),
            CTR_max_percent=float(d["CTR_max_percent"]),
            Vce_sat_V=float(d.get("Vce_sat_V", 0.2)),
            IF_max_mA=float(d["IF_max_mA"]),
            Vf_typ_V=float(d.get("Vf_typ_V", 1.2)),
            t_rise_us_at_Rl=t_rise_tuple,
        )
        circuit = CircuitSpec(
            Vcc_out_V=float(d["Vcc_out_V"]),
            R_pullup_ohm=float(d["R_pullup_ohm"]),
            C_load_pF=float(d.get("C_load_pF", 20.0)),
            R_LED_series_ohm=float(d.get("R_LED_series_ohm", 0.0)),
            V_LED_drive_V=float(d.get("V_LED_drive_V", 0.0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = analyze_optocoupler(opto, circuit)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "IC_min_mA": report.IC_min_mA,
        "IC_typ_mA": report.IC_typ_mA,
        "IC_max_mA": report.IC_max_mA,
        "IC_saturation_mA": report.IC_saturation_mA,
        "saturated_min_case": report.saturated_min_case,
        "Vout_low_V": report.Vout_low_V,
        "Vout_high_V": report.Vout_high_V,
        "t_rise_us": report.t_rise_us,
        "t_fall_us": report.t_fall_us,
        "headroom_factor_min": report.headroom_factor_min,
        "warnings": report.warnings,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_OPTO_CTR_SPEC = ToolSpec(
    name="elec_analyze_optocoupler",
    description=(
        "Analyze an optocoupler isolation circuit: given LED forward current IF, "
        "CTR (min/typ/max), pull-up resistor R_L, supply Vcc, and load capacitance C_L, "
        "computes:\n"
        "  - IC_min/typ/max [mA] = CTR/100 × IF (IEC 60747-5-5 §6.3)\n"
        "  - IC_saturation_mA = Vcc / R_L (output saturation threshold)\n"
        "  - saturated_min_case: IC_min >= IC_sat (worst-case is saturated)\n"
        "  - Vout_low = Vce_sat (datasheet), Vout_high = Vcc\n"
        "  - t_rise/fall [µs] = max(2.2×R_L×C_L, datasheet spec scaled by R_L)\n"
        "  - headroom_factor_min = IC_min / IC_sat\n"
        "  - warnings (over-drive, under-drive, marginal headroom)\n\n"
        "References: Vishay AN-38; Avago AN-5078; IEC 60747-5-5:2007 §6.3.\n\n"
        "HONEST: LINEAR CTR MODEL ONLY — real CTR vs IF is non-linear; "
        "temperature derating and LED aging (30–50% CTR loss over lifetime) NOT modelled.\n\n"
        "Input: { model, IF_mA, CTR_min_percent, CTR_typ_percent, CTR_max_percent, "
        "IF_max_mA, Vcc_out_V, R_pullup_ohm, [Vce_sat_V=0.2], [Vf_typ_V=1.2], "
        "[C_load_pF=20.0], [R_LED_series_ohm=0], [V_LED_drive_V=0], "
        "[t_rise_us_at_Rl=[2.0, 1000]] }\n\n"
        "Returns: { ok, IC_min_mA, IC_typ_mA, IC_max_mA, IC_saturation_mA, "
        "saturated_min_case, Vout_low_V, Vout_high_V, t_rise_us, t_fall_us, "
        "headroom_factor_min, warnings, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Optocoupler part number / model name (e.g. '4N35', 'PC817').",
            },
            "IF_mA": {
                "type": "number",
                "description": "LED forward current delivered to the LED in circuit [mA].",
            },
            "CTR_min_percent": {
                "type": "number",
                "description": "Minimum current transfer ratio at IF_mA [%].",
            },
            "CTR_typ_percent": {
                "type": "number",
                "description": "Typical current transfer ratio at IF_mA [%].",
            },
            "CTR_max_percent": {
                "type": "number",
                "description": "Maximum current transfer ratio at IF_mA [%].",
            },
            "IF_max_mA": {
                "type": "number",
                "description": "Maximum rated LED forward current [mA] (for over-drive warning).",
            },
            "Vcc_out_V": {
                "type": "number",
                "description": "Output-side supply voltage [V] (collector pull-up supply).",
            },
            "R_pullup_ohm": {
                "type": "number",
                "description": "Pull-up resistor from Vcc to collector [Ω].",
            },
            "Vce_sat_V": {
                "type": "number",
                "description": "Collector-emitter saturation voltage [V]. Default 0.2 V.",
            },
            "Vf_typ_V": {
                "type": "number",
                "description": "Typical LED forward voltage [V]. Default 1.2 V.",
            },
            "C_load_pF": {
                "type": "number",
                "description": "Load capacitance at collector node [pF]. Default 20 pF.",
            },
            "R_LED_series_ohm": {
                "type": "number",
                "description": (
                    "Series resistor on the LED input side [Ω]. "
                    "Used with V_LED_drive_V to cross-check IF. Default 0."
                ),
            },
            "V_LED_drive_V": {
                "type": "number",
                "description": (
                    "Drive voltage applied to the LED + series resistor [V]. "
                    "Used with R_LED_series_ohm to cross-check IF. Default 0."
                ),
            },
            "t_rise_us_at_Rl": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "[t_rise_us, R_L_spec_ohm]: datasheet rise time [µs] at a "
                    "reference R_L [Ω]. Scaled linearly to actual R_pullup_ohm. "
                    "Default [2.0, 1000]. Set t_rise_us=0 to use RC model only."
                ),
            },
        },
        "required": [
            "IF_mA",
            "CTR_min_percent",
            "CTR_typ_percent",
            "CTR_max_percent",
            "IF_max_mA",
            "Vcc_out_V",
            "R_pullup_ohm",
        ],
    },
)


@register(_OPTO_CTR_SPEC, write=False)
async def elec_analyze_optocoupler(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = analyze_optocoupler_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _OPTO_CTR_SPEC.name,
        _OPTO_CTR_SPEC,
        elec_analyze_optocoupler,
    ),
]
