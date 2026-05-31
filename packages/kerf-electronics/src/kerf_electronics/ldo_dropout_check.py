"""
LDO (Low-Dropout) linear regulator dropout and thermal compliance checker.

Verifies that an LDO operates correctly given input voltage range, output
voltage, load current, and the device's dropout voltage specification.
Reports headroom compliance, power dissipation, junction temperature estimate,
and efficiency.

Design equations — TI Power Reference Manual §3 + Sandler "Switch-Mode
Power Supplies" §4
---------------------------------------------------------------------------

  Headroom (worst-case = minimum V_in):
    headroom_mV = (V_in_min − V_out) × 1000

  Dropout compliance:
    dropout_compliant = headroom_mV > dropout_voltage_at_max_load_mV

  Power dissipation (worst-case = maximum V_in, all dissipated in pass element):
    P_diss = (V_in_max − V_out) × I_load  [W]

  Junction temperature estimate (Jedec JESD51 single-ambient thermal model):
    T_j = T_ambient + P_diss × R_θja  [°C]

  Thermal compliance:
    thermal_compliant = T_j < T_max_junction

  Efficiency (ignores quiescent current — see honest caveat):
    efficiency_pct = 100 × V_out × I_load / (V_in_max × I_load)
                   = 100 × V_out / V_in_max  [%]

HONEST CAVEATS (always reported)
---------------------------------
1. Quiescent current (I_Q) is NOT included in power dissipation or efficiency
   calculations. At light loads I_Q can dominate; use datasheet I_Q vs I_load
   curves for accurate idle-power budgeting (TI Power Ref §3.2.3).

2. Transient response / load-step headroom is NOT modelled. A marginal DC
   headroom (headroom ≈ dropout_voltage) will violate the output during fast
   load steps because of the PSRR roll-off and input capacitor droop. Add
   ≥ 100–200 mV of guard-band for dynamic operation (Sandler §4.4).

3. Output capacitor stability: most LDOs require a minimum ESR window
   (ESR_min to ESR_max) for stable operation. This tool does NOT verify
   capacitor-stability requirements — consult the datasheet stability curve
   (often plotted as ESR vs I_load).

4. Thermal model is a single-node (Jedec JESD51) steady-state estimate using
   θja (junction-to-ambient); real PCB layouts have θjb (junction-to-board)
   and θjc (junction-to-case) paths that reduce T_j. θja is the conservative
   (worst-case) thermal resistance.

5. Efficiency uses V_in_max (worst-case V_in for power), which yields the
   pessimistic (lowest) efficiency figure. At V_in_min the efficiency is
   100 × V_out / V_in_min (higher).

6. Absolute Maximum junction temperature varies by device (typically 125°C
   or 150°C for automotive-grade). Use T_max_junction from the specific device
   datasheet; the default 125°C is a common JEDEC limit but is NOT universal.

References
----------
Texas Instruments, "Power Management Reference Manual" §3 — LDO Regulators.
S. Sandler, "Switch-Mode Power Supplies Spice Simulations and Practical Designs",
    McGraw-Hill, §4 — LDO analysis.
Jedec JESD51-1: Integrated Circuit Thermal Measurement Method — Electrical
    Test Method (Single Semiconductor Device).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class LDOSpec:
    """Input specification for an LDO dropout and thermal compliance check.

    Attributes
    ----------
    V_out_V : float
        Regulated output voltage [V]. Must be > 0.
    V_in_min_V : float
        Minimum input supply voltage [V]. Used for worst-case headroom.
        Must be > V_out_V.
    V_in_max_V : float
        Maximum input supply voltage [V]. Used for worst-case power dissipation.
        Must be >= V_in_min_V.
    I_load_A : float
        Maximum load current [A]. Must be > 0.
    dropout_voltage_at_max_load_mV : float
        LDO dropout voltage specification at maximum load current [mV].
        From the device datasheet (V_DO or V_in_min − V_out at I_load_max).
        Must be > 0.
    junction_to_ambient_thermal_resistance_K_per_W : float
        Thermal resistance θja (junction-to-ambient) [K/W or °C/W].
        From the device datasheet for the specific package. Must be > 0.
    T_ambient_C : float
        Ambient temperature [°C]. Default 25.0.
    T_max_junction_C : float
        Maximum rated junction temperature [°C]. Default 125.0.
        Use 150.0 for automotive-grade (AEC-Q100 Grade 1) devices.
    """
    V_out_V: float
    V_in_min_V: float
    V_in_max_V: float
    I_load_A: float
    dropout_voltage_at_max_load_mV: float
    junction_to_ambient_thermal_resistance_K_per_W: float
    T_ambient_C: float = 25.0
    T_max_junction_C: float = 125.0


@dataclass
class LDODropoutReport:
    """Result of the LDO dropout and thermal compliance check.

    Attributes
    ----------
    headroom_min_mV : float
        Worst-case headroom: (V_in_min − V_out) × 1000 [mV].
        Positive means the input exceeds the output by this margin.
    dropout_compliant : bool
        True when headroom_min_mV > dropout_voltage_at_max_load_mV.
        Note: strict inequality — exact equality is considered marginal/non-compliant
        because real devices need guard-band above the datasheet dropout spec.
    power_dissipation_W : float
        Worst-case power dissipated in the pass element at V_in_max [W].
        P_diss = (V_in_max − V_out) × I_load.
    junction_temp_estimate_C : float
        Estimated junction temperature at worst-case power dissipation [°C].
        T_j = T_ambient + P_diss × R_θja.
    thermal_compliant : bool
        True when junction_temp_estimate_C < T_max_junction_C.
    efficiency_pct : float
        Theoretical efficiency at V_in_max (pessimistic) [%].
        efficiency = 100 × V_out / V_in_max (ignores quiescent current).
    honest_caveat : str
        Engineering caveats — quiescent current, transient headroom, capacitor
        stability, thermal model limits, and efficiency approximation.
    """
    headroom_min_mV: float
    dropout_compliant: bool
    power_dissipation_W: float
    junction_temp_estimate_C: float
    thermal_compliant: bool
    efficiency_pct: float
    honest_caveat: str


# ── Validation ─────────────────────────────────────────────────────────────────


def _validate_spec(spec: LDOSpec) -> str | None:
    """Return an error string or None if inputs are valid."""
    if not isinstance(spec, LDOSpec):
        return "spec must be an LDOSpec instance"
    if spec.V_out_V <= 0:
        return f"V_out_V must be > 0, got {spec.V_out_V}"
    if spec.V_in_min_V <= spec.V_out_V:
        return (
            f"V_in_min_V ({spec.V_in_min_V} V) must be > V_out_V ({spec.V_out_V} V); "
            "an LDO requires input voltage above output voltage"
        )
    if spec.V_in_max_V < spec.V_in_min_V:
        return (
            f"V_in_max_V ({spec.V_in_max_V} V) must be >= V_in_min_V ({spec.V_in_min_V} V)"
        )
    if spec.I_load_A <= 0:
        return f"I_load_A must be > 0, got {spec.I_load_A}"
    if spec.dropout_voltage_at_max_load_mV <= 0:
        return (
            f"dropout_voltage_at_max_load_mV must be > 0, "
            f"got {spec.dropout_voltage_at_max_load_mV}"
        )
    if spec.junction_to_ambient_thermal_resistance_K_per_W <= 0:
        return (
            f"junction_to_ambient_thermal_resistance_K_per_W must be > 0, "
            f"got {spec.junction_to_ambient_thermal_resistance_K_per_W}"
        )
    if spec.T_max_junction_C <= spec.T_ambient_C:
        return (
            f"T_max_junction_C ({spec.T_max_junction_C} °C) must be > "
            f"T_ambient_C ({spec.T_ambient_C} °C)"
        )
    return None


# ── Core calculation ───────────────────────────────────────────────────────────


def check_ldo_dropout(spec: LDOSpec) -> LDODropoutReport:
    """Check LDO dropout compliance, power dissipation, and thermal limits.

    Uses worst-case V_in_min for headroom and worst-case V_in_max for power.

    Parameters
    ----------
    spec : LDOSpec
        LDO and operating-condition specification.

    Returns
    -------
    LDODropoutReport
        All compliance flags, quantitative results, and honest engineering caveats.

    Raises
    ------
    ValueError
        On invalid or inconsistent inputs.
    """
    err = _validate_spec(spec)
    if err:
        raise ValueError(err)

    V_out = spec.V_out_V
    V_in_min = spec.V_in_min_V
    V_in_max = spec.V_in_max_V
    I_load = spec.I_load_A
    V_do_mV = spec.dropout_voltage_at_max_load_mV
    R_theta_ja = spec.junction_to_ambient_thermal_resistance_K_per_W
    T_amb = spec.T_ambient_C
    T_max_j = spec.T_max_junction_C

    # ── Headroom ──────────────────────────────────────────────────────────────
    # Worst case: minimum input voltage (TI Power Ref §3.1)
    headroom_mV = (V_in_min - V_out) * 1000.0

    # Strict inequality: headroom must EXCEED dropout spec (not merely equal it)
    dropout_compliant = headroom_mV > V_do_mV

    # ── Power dissipation ─────────────────────────────────────────────────────
    # Worst case: maximum input voltage (TI Power Ref §3.2 / Sandler §4.2)
    # P_diss = (V_in_max - V_out) * I_load
    P_diss = (V_in_max - V_out) * I_load

    # ── Junction temperature ──────────────────────────────────────────────────
    # Single-node Jedec JESD51 model: T_j = T_amb + P_diss * R_θja
    T_j = T_amb + P_diss * R_theta_ja

    thermal_compliant = T_j < T_max_j

    # ── Efficiency ────────────────────────────────────────────────────────────
    # Pessimistic (lowest) efficiency at V_in_max; ignores quiescent current
    efficiency_pct = 100.0 * V_out / V_in_max

    # ── Headroom margin relative to dropout spec ──────────────────────────────
    headroom_margin_mV = headroom_mV - V_do_mV  # negative = non-compliant

    # ── Assemble caveats ──────────────────────────────────────────────────────
    caveat_parts = []

    # Core result summary
    caveat_parts.append(
        f"LDO check: headroom={headroom_mV:.1f} mV vs dropout_spec={V_do_mV:.1f} mV "
        f"(margin={headroom_margin_mV:+.1f} mV); "
        f"P_diss={P_diss:.4f} W at V_in_max={V_in_max} V; "
        f"T_j={T_j:.1f} °C (limit {T_max_j} °C); "
        f"efficiency≈{efficiency_pct:.1f}% (at V_in_max, ignores I_Q)."
    )
    if not dropout_compliant:
        caveat_parts.append(
            f" FAIL — DROPOUT NOT MET: headroom {headroom_mV:.1f} mV <= "
            f"dropout spec {V_do_mV:.1f} mV at V_in_min={V_in_min} V. "
            "The LDO pass element will exit regulation; output voltage will fall "
            "below V_out. Increase V_in_min or choose an LDO with lower dropout."
        )
    if not thermal_compliant:
        caveat_parts.append(
            f" FAIL — THERMAL LIMIT EXCEEDED: T_j={T_j:.1f} °C >= {T_max_j} °C. "
            "Reduce power dissipation (lower V_in_max or I_load), improve "
            "heatsinking (lower θja), or choose a higher T_j-rated device."
        )

    # Mandatory honest caveats (TI Power Ref §3 / Sandler §4)
    caveat_parts.append(
        " HONEST: (1) Quiescent current I_Q NOT included — at light loads I_Q "
        "can dominate P_diss and degrade efficiency; use datasheet I_Q curve "
        "(TI Power Ref §3.2.3). "
        "(2) Transient response NOT modelled — marginal DC headroom will be "
        "violated during load steps (PSRR roll-off + input cap droop); add "
        "≥100–200 mV guard-band for dynamic operation (Sandler §4.4). "
        "(3) Output capacitor stability NOT verified — most LDOs have an "
        "ESR window requirement (ESR_min to ESR_max for stability); consult "
        "datasheet stability curve (ESR vs I_load). "
        "(4) Thermal model is Jedec JESD51 single-node θja (worst-case); "
        "actual PCB layout θjb+θjc paths may reduce T_j; use θjb for "
        "better accuracy in production layout analysis. "
        "(5) Efficiency = V_out/V_in_max (pessimistic at max V_in); true "
        "efficiency requires I_Q correction: η = V_out·I_load / (V_in·(I_load+I_Q))."
        " Refs: TI Power Ref §3; Sandler §4; Jedec JESD51-1."
    )

    return LDODropoutReport(
        headroom_min_mV=round(headroom_mV, 4),
        dropout_compliant=dropout_compliant,
        power_dissipation_W=round(P_diss, 6),
        junction_temp_estimate_C=round(T_j, 4),
        thermal_compliant=thermal_compliant,
        efficiency_pct=round(efficiency_pct, 4),
        honest_caveat="".join(caveat_parts),
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def check_ldo_dropout_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.
    """
    try:
        spec = LDOSpec(
            V_out_V=float(d["V_out_V"]),
            V_in_min_V=float(d["V_in_min_V"]),
            V_in_max_V=float(d["V_in_max_V"]),
            I_load_A=float(d["I_load_A"]),
            dropout_voltage_at_max_load_mV=float(d["dropout_voltage_at_max_load_mV"]),
            junction_to_ambient_thermal_resistance_K_per_W=float(
                d["junction_to_ambient_thermal_resistance_K_per_W"]
            ),
            T_ambient_C=float(d.get("T_ambient_C", 25.0)),
            T_max_junction_C=float(d.get("T_max_junction_C", 125.0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = check_ldo_dropout(spec)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "headroom_min_mV": report.headroom_min_mV,
        "dropout_compliant": report.dropout_compliant,
        "power_dissipation_W": report.power_dissipation_W,
        "junction_temp_estimate_C": report.junction_temp_estimate_C,
        "thermal_compliant": report.thermal_compliant,
        "efficiency_pct": report.efficiency_pct,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_LDO_DROPOUT_SPEC = ToolSpec(
    name="electronics_check_ldo_dropout",
    description=(
        "Verify that an LDO (Low-Dropout) linear regulator operates correctly "
        "given input voltage range, output voltage, load current, and LDO "
        "dropout voltage specification.\n\n"
        "Equations (TI Power Reference Manual §3 + Sandler 'Switch-Mode Power "
        "Supplies' §4):\n"
        "  headroom_mV        = (V_in_min − V_out) × 1000   [worst-case margin]\n"
        "  dropout_compliant  = headroom_mV > dropout_spec_mV\n"
        "  P_diss             = (V_in_max − V_out) × I_load  [worst-case power, W]\n"
        "  T_j                = T_ambient + P_diss × R_θja   [junction temp, °C]\n"
        "  thermal_compliant  = T_j < T_max_junction\n"
        "  efficiency_pct     = 100 × V_out / V_in_max       [pessimistic, ignores I_Q]\n\n"
        "HONEST: quiescent current NOT modelled; transient headroom NOT checked; "
        "output capacitor stability NOT verified; θja is worst-case single-node "
        "thermal model (Jedec JESD51). "
        "Refs: TI Power Ref §3; Sandler §4; Jedec JESD51-1.\n\n"
        "Input: { V_out_V, V_in_min_V, V_in_max_V, I_load_A, "
        "dropout_voltage_at_max_load_mV, "
        "junction_to_ambient_thermal_resistance_K_per_W, "
        "[T_ambient_C=25], [T_max_junction_C=125] }\n\n"
        "Returns: { ok, headroom_min_mV, dropout_compliant, power_dissipation_W, "
        "junction_temp_estimate_C, thermal_compliant, efficiency_pct, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "V_out_V": {
                "type": "number",
                "description": "Regulated output voltage [V]. Must be > 0.",
            },
            "V_in_min_V": {
                "type": "number",
                "description": (
                    "Minimum input supply voltage [V]. "
                    "Used for worst-case dropout headroom check. Must be > V_out_V."
                ),
            },
            "V_in_max_V": {
                "type": "number",
                "description": (
                    "Maximum input supply voltage [V]. "
                    "Used for worst-case power dissipation. Must be >= V_in_min_V."
                ),
            },
            "I_load_A": {
                "type": "number",
                "description": "Maximum load current [A]. Must be > 0.",
            },
            "dropout_voltage_at_max_load_mV": {
                "type": "number",
                "description": (
                    "LDO dropout voltage at maximum load current [mV]. "
                    "From device datasheet (V_DO at I_out_max). Must be > 0."
                ),
            },
            "junction_to_ambient_thermal_resistance_K_per_W": {
                "type": "number",
                "description": (
                    "Thermal resistance θja (junction-to-ambient) [K/W or °C/W]. "
                    "From device datasheet for the specific package. Must be > 0."
                ),
            },
            "T_ambient_C": {
                "type": "number",
                "description": "Ambient temperature [°C]. Default 25.0.",
            },
            "T_max_junction_C": {
                "type": "number",
                "description": (
                    "Maximum rated junction temperature [°C]. Default 125.0. "
                    "Use 150.0 for automotive-grade (AEC-Q100 Grade 1) devices."
                ),
            },
        },
        "required": [
            "V_out_V",
            "V_in_min_V",
            "V_in_max_V",
            "I_load_A",
            "dropout_voltage_at_max_load_mV",
            "junction_to_ambient_thermal_resistance_K_per_W",
        ],
    },
)


@register(_LDO_DROPOUT_SPEC, write=False)
async def electronics_check_ldo_dropout(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = check_ldo_dropout_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _LDO_DROPOUT_SPEC.name,
        _LDO_DROPOUT_SPEC,
        electronics_check_ldo_dropout,
    ),
]
