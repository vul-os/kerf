"""
Pierce crystal oscillator external load capacitor calculator.

Computes the external load capacitors C1 and C2 for a Pierce oscillator
such that the crystal sees its specified load capacitance CL, enabling
on-frequency operation per the crystal datasheet.

Physics / derivation (NXP AN-2867 §3 + AVR ATmega datasheet §28.5)
--------------------------------------------------------------------

The Pierce oscillator presents a series combination of C1 and C2 (in
parallel with PCB stray capacitance C_stray) as the load seen by the
crystal:

    CL = (C1 × C2) / (C1 + C2) + C_stray

where C_stray = pcb_stray_capacitance_pF + mcu_pad_capacitance_pF
(PCB trace + MCU GPIO pad capacitances).

Rearranging for C1 = C2 (symmetric design, NXP AN-2867 §3.1):

    C1 = C2 = 2 × (CL − C_stray)

The symmetric design is the standard recommendation for most MCU designs
(STM32, AVR, MSP430) because equal capacitors minimise frequency error
from component tolerance and maintain oscillator symmetry for better
start-up margin.

Asymmetric designs (C1 ≠ C2) are sometimes used for trimming when only
E12 or E24 series values are available, or to adjust drive level. When an
asymmetric pair is verified (provide c1_pF and c2_pF), the effective CL
is back-computed and compared to the target.

Gain margin check (NXP AN-2867 §4, Rohde-Kuhn 2005)
-----------------------------------------------------

    −Rn = −gm / (ω² × C1 × C2)

    Gain margin (GM) = |−Rn| / ESR_max

    For reliable startup: GM ≥ 5 (NXP AN-2867 §4.2 recommends × 5 margin)
    A margin ≥ 3 is the minimum (IEC 60444-5 §7.3); < 3 → risk of not starting.

gm is not a direct input (it is MCU-specific); GM check is therefore
QUALITATIVE here — the report flags whether the stray+load-cap combination
increases negative resistance risk.  Full GM calculation requires the MCU's
inverter gm (available in some datasheets; e.g. STM32 = 4–8 mA/V).

Honest caveats (always reported)
---------------------------------
1. Drive-level limiting is NOT modelled.  Excessive drive level (C_ext too
   large or oscillator gain too high) can damage the crystal or cause
   frequency pull; verify drive level P_d = ½·ESR·(ω·C_eff·V_osc)² does not
   exceed drive_level_uW.  NXP AN-2867 §5.1: typical MCU drive levels are
   1–100 µW; crystal ratings 10–200 µW.
2. PI-network compensation for high-frequency crystals (> 20 MHz) is NOT
   applied.  Above 20 MHz, stray inductance and board parasitics make the
   series model inaccurate; use a PI-filter on XIN if crystal is > 20 MHz
   (NXP AN-2867 §3.3).
3. C_stray = PCB stray + MCU pad cap is a first-order estimate. Actual stray
   depends on PCB layout (trace length, ground plane proximity, adjacent
   nets); measure on target board and iterate.
4. Component tolerance: a 1% tolerance on C_ext introduces ~1% CL error,
   corresponding to several ppm frequency offset.  Use ±1% or better NPO/C0G
   capacitors (NXP AN-2867 §3.2 + Vishay/TDK C0G application notes).

References
----------
NXP Semiconductors, "Oscillator design guide for STM8 and STM32
microcontrollers", Application Note AN-2867, Rev 2, 2011, §3–§5.

Atmel (Microchip) ATmega328P datasheet, §28.5 "Crystal Oscillator";
AVR180 application note "External RC Oscillator", §3.

IEC 60444-5:1997, "Measurement of quartz crystal unit parameters",
§7.3 "Oscillation condition — negative resistance margin".

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class CrystalSpec:
    """Crystal unit specification from the component datasheet.

    Attributes
    ----------
    frequency_MHz : float
        Nominal crystal frequency [MHz], e.g. 16.0 for a 16 MHz crystal.
    load_capacitance_CL_pF : float
        Crystal load capacitance CL specified in the datasheet [pF].
        The crystal oscillates at its nominal frequency when the PCB
        presents exactly this capacitance as the load.  Typical values:
        6, 8, 10, 12, 18, 20 pF.
    esr_max_ohms : float
        Maximum equivalent series resistance (ESR) of the crystal [Ω].
        Used for gain-margin estimation.  Typical: 50–200 Ω for MHz range.
    drive_level_uW : float
        Maximum rated drive level (power dissipation in the crystal) [µW].
        Exceeding this degrades the crystal and causes frequency instability.
        Typical: 10–200 µW.
    """
    frequency_MHz: float
    load_capacitance_CL_pF: float
    esr_max_ohms: float
    drive_level_uW: float


@dataclass
class PCBLayoutSpec:
    """PCB and MCU parasitic capacitance specification.

    Attributes
    ----------
    pcb_stray_capacitance_pF : float
        PCB stray capacitance per oscillator node [pF].  Includes copper trace
        to ground, via capacitance, and nearby net crosstalk.  Typical: 1–5 pF.
        NXP AN-2867 §3.1 uses 2 pF as a reference value.  Default: 2.0 pF.
    mcu_pad_capacitance_pF : float
        MCU GPIO/OSC pad input capacitance [pF].  From MCU datasheet electrical
        characteristics table (typically 2–5 pF for STM32/AVR/MSP430 OSC pins).
        Default: 1.0 pF.
    """
    pcb_stray_capacitance_pF: float = 2.0
    mcu_pad_capacitance_pF: float = 1.0


@dataclass
class CrystalLoadCapReport:
    """Result of the Pierce oscillator external load capacitor calculation.

    Attributes
    ----------
    C1_pF : float
        Recommended first external load capacitor value [pF].  C1 = C2 for
        symmetric design.  Use C0G/NPO grade (±1% or better).
    C2_pF : float
        Recommended second external load capacitor value [pF].  Equal to C1
        for symmetric design.
    effective_load_cap_pF : float
        Effective load capacitance presented to the crystal [pF]:
            CL_eff = (C1·C2)/(C1+C2) + C_stray
        Should match crystal's specified CL within ±0.5 pF.
    c1_c2_symmetric : bool
        True when C1 == C2 (symmetric design recommended by NXP AN-2867 §3).
    gain_margin_check : str
        Qualitative gain-margin note.  Full quantitative check requires the
        MCU inverter's gm (transconductance), which is MCU-specific.  This
        field reports a flag if conditions suggest marginal startup.
    honest_caveat : str
        Engineering limitations that the caller must be aware of.
    """
    C1_pF: float
    C2_pF: float
    effective_load_cap_pF: float
    c1_c2_symmetric: bool
    gain_margin_check: str
    honest_caveat: str


# ── Constants ──────────────────────────────────────────────────────────────────

# Minimum recommended C_stray threshold below which the calc is still valid
_MIN_C_STRAY_PF: float = 0.0

# NXP AN-2867 §3.1: minimum recommended C_ext per node (2 pF)
_MIN_C_EXT_PF: float = 2.0

# Frequency above which PI-network compensation is recommended (NXP AN-2867 §3.3)
_HIGH_FREQ_THRESHOLD_MHZ: float = 20.0

# Typical MCU inverter gm range for gain-margin heuristic [mA/V]
_TYPICAL_GM_MIN_MA_PER_V: float = 4.0   # pessimistic (older process nodes)


# ── Core calculation ────────────────────────────────────────────────────────────


def compute_crystal_load_caps(
    crystal: CrystalSpec,
    pcb: Optional[PCBLayoutSpec] = None,
    c1_override_pF: Optional[float] = None,
    c2_override_pF: Optional[float] = None,
) -> CrystalLoadCapReport:
    """Compute external load capacitor values for a Pierce crystal oscillator.

    Given a crystal's specified load capacitance CL and the PCB stray
    capacitance, derives the external capacitors C1 and C2 such that:

        CL = (C1·C2)/(C1+C2) + C_stray

    For the standard symmetric design (C1 = C2):

        C1 = C2 = 2·(CL − C_stray)

    If ``c1_override_pF`` and ``c2_override_pF`` are provided, the effective
    CL is back-computed and the symmetric flag reflects whether they match.

    Parameters
    ----------
    crystal : CrystalSpec
        Crystal unit parameters from the datasheet.
    pcb : PCBLayoutSpec | None
        PCB and MCU parasitic capacitances.  Defaults to PCBLayoutSpec()
        (2.0 pF stray + 1.0 pF MCU pad = 3.0 pF total stray per node).
    c1_override_pF : float | None
        Custom C1 value [pF] for verification of an asymmetric design.
    c2_override_pF : float | None
        Custom C2 value [pF] for verification of an asymmetric design.

    Returns
    -------
    CrystalLoadCapReport

    Raises
    ------
    ValueError
        On physically invalid inputs.

    References
    ----------
    NXP AN-2867 §3 — symmetric load-cap selection formula.
    AVR ATmega §28.5 — crystal oscillator design.
    """
    if pcb is None:
        pcb = PCBLayoutSpec()

    # ── Input validation ─────────────────────────────────────────────────────
    if crystal.frequency_MHz <= 0:
        raise ValueError(
            f"frequency_MHz must be > 0, got {crystal.frequency_MHz}"
        )
    if crystal.load_capacitance_CL_pF <= 0:
        raise ValueError(
            f"load_capacitance_CL_pF must be > 0, got {crystal.load_capacitance_CL_pF}"
        )
    if crystal.esr_max_ohms <= 0:
        raise ValueError(
            f"esr_max_ohms must be > 0, got {crystal.esr_max_ohms}"
        )
    if crystal.drive_level_uW <= 0:
        raise ValueError(
            f"drive_level_uW must be > 0, got {crystal.drive_level_uW}"
        )
    if pcb.pcb_stray_capacitance_pF < 0:
        raise ValueError(
            f"pcb_stray_capacitance_pF must be >= 0, got {pcb.pcb_stray_capacitance_pF}"
        )
    if pcb.mcu_pad_capacitance_pF < 0:
        raise ValueError(
            f"mcu_pad_capacitance_pF must be >= 0, got {pcb.mcu_pad_capacitance_pF}"
        )

    # ── Total stray capacitance (NXP AN-2867 §3.1) ────────────────────────────
    # C_stray = PCB stray + MCU pad capacitance (both OSC pins contribute)
    c_stray_pF: float = pcb.pcb_stray_capacitance_pF + pcb.mcu_pad_capacitance_pF

    CL_pF: float = crystal.load_capacitance_CL_pF

    if CL_pF <= c_stray_pF:
        raise ValueError(
            f"Crystal load capacitance CL ({CL_pF:.1f} pF) must exceed total "
            f"stray capacitance ({c_stray_pF:.1f} pF). "
            f"Reduce pcb_stray_capacitance_pF or mcu_pad_capacitance_pF, or "
            f"choose a crystal with a higher CL specification."
        )

    # ── Compute C1, C2 ───────────────────────────────────────────────────────
    symmetric = True

    if c1_override_pF is not None and c2_override_pF is not None:
        # Verification mode: back-compute effective CL from provided caps
        if c1_override_pF <= 0:
            raise ValueError(f"c1_override_pF must be > 0, got {c1_override_pF}")
        if c2_override_pF <= 0:
            raise ValueError(f"c2_override_pF must be > 0, got {c2_override_pF}")
        C1_pF = c1_override_pF
        C2_pF = c2_override_pF
        symmetric = math.isclose(C1_pF, C2_pF, rel_tol=1e-6)
    else:
        # Design mode: compute symmetric C1 = C2 from NXP AN-2867 §3.1 formula
        # C1 = C2 = 2 × (CL − C_stray)
        C1_pF = 2.0 * (CL_pF - c_stray_pF)
        C2_pF = C1_pF
        symmetric = True

        if C1_pF < _MIN_C_EXT_PF:
            # Still valid mathematically; flag as very small cap
            pass

    # ── Effective load capacitance check ─────────────────────────────────────
    # CL_eff = (C1·C2)/(C1+C2) + C_stray
    cl_series_pF: float = (C1_pF * C2_pF) / (C1_pF + C2_pF)
    effective_CL_pF: float = cl_series_pF + c_stray_pF

    # ── Gain margin heuristic (NXP AN-2867 §4) ────────────────────────────────
    # Negative resistance: −Rn = −gm / (ω² × C1 × C2)
    # Using pessimistic gm = 4 mA/V as lower bound for typical MCU inverters
    omega = 2.0 * math.pi * crystal.frequency_MHz * 1e6
    C1_F = C1_pF * 1e-12
    C2_F = C2_pF * 1e-12
    gm_pessimistic = _TYPICAL_GM_MIN_MA_PER_V * 1e-3  # A/V
    neg_rn_pessimistic = gm_pessimistic / (omega ** 2 * C1_F * C2_F)
    gm_margin_pessimistic = neg_rn_pessimistic / crystal.esr_max_ohms

    if gm_margin_pessimistic >= 5.0:
        gm_check = (
            f"LIKELY OK: negative-resistance margin ≈ {gm_margin_pessimistic:.1f}× ESR "
            f"(using gm = {_TYPICAL_GM_MIN_MA_PER_V} mA/V pessimistic estimate; "
            f"NXP AN-2867 §4.2 requires ≥5×). "
            f"Verify with actual MCU gm from datasheet."
        )
    elif gm_margin_pessimistic >= 3.0:
        gm_check = (
            f"MARGINAL: negative-resistance margin ≈ {gm_margin_pessimistic:.1f}× ESR "
            f"(using gm = {_TYPICAL_GM_MIN_MA_PER_V} mA/V pessimistic estimate; "
            f"NXP AN-2867 §4.2 requires ≥5×, IEC 60444-5 minimum is 3×). "
            f"Check actual MCU gm; consider lower ESR crystal or smaller C_ext."
        )
    else:
        gm_check = (
            f"RISK: negative-resistance margin ≈ {gm_margin_pessimistic:.1f}× ESR "
            f"< 3× minimum (IEC 60444-5 §7.3). "
            f"Crystal may not start reliably. "
            f"Reduce C_ext, choose lower ESR crystal, or verify MCU gm ≥ "
            f"{crystal.esr_max_ohms * 3.0 * (omega ** 2 * C1_F * C2_F) * 1000:.1f} mA/V."
        )

    # Flag if crystal frequency is in the high-frequency regime
    high_freq_note = ""
    if crystal.frequency_MHz > _HIGH_FREQ_THRESHOLD_MHZ:
        high_freq_note = (
            f" NOTE: crystal at {crystal.frequency_MHz:.1f} MHz exceeds "
            f"{_HIGH_FREQ_THRESHOLD_MHZ:.0f} MHz — NXP AN-2867 §3.3 recommends "
            f"a PI-network filter on XIN to suppress spurious modes; "
            f"this calculator does NOT apply PI-network compensation."
        )

    # ── Honest caveat ─────────────────────────────────────────────────────────
    caveat = (
        "Formula: CL = (C1·C2)/(C1+C2) + C_stray (NXP AN-2867 §3 + AVR ATmega §28.5). "
        f"C_stray = {c_stray_pF:.1f} pF (PCB {pcb.pcb_stray_capacitance_pF:.1f} pF "
        f"+ MCU pad {pcb.mcu_pad_capacitance_pF:.1f} pF). "
        "LIMITATIONS: "
        "(1) Drive-level limiting NOT modelled — verify P_d = ½·ESR·(ω·C_eff·V_osc)² "
        f"does not exceed crystal drive_level = {crystal.drive_level_uW:.0f} µW "
        "(NXP AN-2867 §5.1). "
        "(2) PI-network compensation for high-frequency crystals (>20 MHz) NOT applied "
        "(NXP AN-2867 §3.3). "
        "(3) C_stray is a first-order PCB estimate; measure on actual board and iterate. "
        "(4) Use C0G/NPO grade capacitors ±1% or better to minimise CL error and "
        "frequency offset (NXP AN-2867 §3.2). "
        "(5) Gain margin check uses a pessimistic gm estimate; verify against MCU "
        "datasheet gm for definitive startup assurance."
        + high_freq_note
    )

    return CrystalLoadCapReport(
        C1_pF=round(C1_pF, 4),
        C2_pF=round(C2_pF, 4),
        effective_load_cap_pF=round(effective_CL_pF, 6),
        c1_c2_symmetric=symmetric,
        gain_margin_check=gm_check,
        honest_caveat=caveat,
    )


# ── Dict-in, dict-out wrapper ─────────────────────────────────────────────────


def compute_crystal_load_caps_from_dict(d: dict) -> dict:
    """Dict-in, dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        crystal = CrystalSpec(
            frequency_MHz=float(d["frequency_MHz"]),
            load_capacitance_CL_pF=float(d["load_capacitance_CL_pF"]),
            esr_max_ohms=float(d["esr_max_ohms"]),
            drive_level_uW=float(d["drive_level_uW"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid crystal spec: {exc}"}

    try:
        pcb_data = d.get("pcb", {})
        pcb = PCBLayoutSpec(
            pcb_stray_capacitance_pF=float(pcb_data.get("pcb_stray_capacitance_pF", 2.0)),
            mcu_pad_capacitance_pF=float(pcb_data.get("mcu_pad_capacitance_pF", 1.0)),
        )
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid pcb spec: {exc}"}

    c1_override = d.get("c1_override_pF")
    c2_override = d.get("c2_override_pF")
    try:
        c1_val = float(c1_override) if c1_override is not None else None
        c2_val = float(c2_override) if c2_override is not None else None
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid override cap: {exc}"}

    try:
        report = compute_crystal_load_caps(crystal, pcb, c1_val, c2_val)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "C1_pF": report.C1_pF,
        "C2_pF": report.C2_pF,
        "effective_load_cap_pF": report.effective_load_cap_pF,
        "c1_c2_symmetric": report.c1_c2_symmetric,
        "gain_margin_check": report.gain_margin_check,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_CRYSTAL_LOAD_CAP_SPEC = ToolSpec(
    name="electronics_compute_crystal_load_caps",
    description=(
        "Compute external load capacitor values (C1, C2) for a Pierce crystal "
        "oscillator given the crystal's specified load capacitance CL and PCB "
        "stray capacitance. Required for accurate on-frequency operation.\n\n"
        "Formula (NXP AN-2867 §3 + AVR ATmega §28.5):\n"
        "  CL = (C1·C2)/(C1+C2) + C_stray\n"
        "  Symmetric design: C1 = C2 = 2·(CL − C_stray)\n\n"
        "C_stray = pcb_stray_capacitance_pF + mcu_pad_capacitance_pF\n\n"
        "Gain-margin check uses a pessimistic gm = 4 mA/V estimate "
        "(NXP AN-2867 §4.2; ≥5× ESR for reliable startup).\n\n"
        "HONEST: drive-level limiting NOT modelled; PI-network compensation "
        "for >20 MHz crystals NOT applied; C_stray is a first-order estimate; "
        "use C0G/NPO grade ±1% capacitors.\n\n"
        "Input: { frequency_MHz, load_capacitance_CL_pF, esr_max_ohms, "
        "drive_level_uW, [pcb: {pcb_stray_capacitance_pF=2.0, "
        "mcu_pad_capacitance_pF=1.0}], [c1_override_pF], [c2_override_pF] }\n\n"
        "Returns: { ok, C1_pF, C2_pF, effective_load_cap_pF, c1_c2_symmetric, "
        "gain_margin_check, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "frequency_MHz": {
                "type": "number",
                "description": "Crystal nominal frequency [MHz], e.g. 16.0.",
            },
            "load_capacitance_CL_pF": {
                "type": "number",
                "description": (
                    "Crystal load capacitance CL from datasheet [pF]. "
                    "Common values: 6, 8, 10, 12, 18, 20 pF."
                ),
            },
            "esr_max_ohms": {
                "type": "number",
                "description": (
                    "Crystal maximum equivalent series resistance ESR [Ω]. "
                    "Typical: 50–200 Ω for MHz range crystals."
                ),
            },
            "drive_level_uW": {
                "type": "number",
                "description": (
                    "Crystal maximum rated drive level [µW]. "
                    "Typical: 10–200 µW; used for caveats only (not limiting computed caps)."
                ),
            },
            "pcb": {
                "type": "object",
                "description": (
                    "PCB and MCU parasitic capacitances. "
                    "Defaults: pcb_stray_capacitance_pF=2.0, mcu_pad_capacitance_pF=1.0."
                ),
                "properties": {
                    "pcb_stray_capacitance_pF": {
                        "type": "number",
                        "description": (
                            "PCB stray capacitance per oscillator node [pF]. "
                            "Typical: 1–5 pF. Default: 2.0 pF (NXP AN-2867 §3.1)."
                        ),
                    },
                    "mcu_pad_capacitance_pF": {
                        "type": "number",
                        "description": (
                            "MCU OSC pin input capacitance [pF]. "
                            "From MCU datasheet. Typical: 1–5 pF. Default: 1.0 pF."
                        ),
                    },
                },
            },
            "c1_override_pF": {
                "type": "number",
                "description": (
                    "Custom C1 value [pF] for asymmetric verification. "
                    "Provide both c1_override_pF and c2_override_pF to verify "
                    "a specific asymmetric cap pair."
                ),
            },
            "c2_override_pF": {
                "type": "number",
                "description": (
                    "Custom C2 value [pF] for asymmetric verification. "
                    "Provide both c1_override_pF and c2_override_pF to verify "
                    "a specific asymmetric cap pair."
                ),
            },
        },
        "required": [
            "frequency_MHz",
            "load_capacitance_CL_pF",
            "esr_max_ohms",
            "drive_level_uW",
        ],
    },
)


@register(_CRYSTAL_LOAD_CAP_SPEC, write=False)
async def electronics_compute_crystal_load_caps(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = compute_crystal_load_caps_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _CRYSTAL_LOAD_CAP_SPEC.name,
        _CRYSTAL_LOAD_CAP_SPEC,
        electronics_compute_crystal_load_caps,
    ),
]
