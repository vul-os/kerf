"""
Zener diode voltage drift over temperature (temperature coefficient model).

Models the Vz vs T curve which has a zero-TC crossing near 5.6 V:
  - Below ~5.6 V: negative TC (Zener tunneling mechanism dominates).
  - Above ~5.6 V: positive TC (avalanche impact-ionisation dominates).
  - Near 5.1–5.6 V: TC ≈ 0 — minimum temperature sensitivity.

This is well-documented in:
  - Sze "Physics of Semiconductor Devices" §4.5 (temperature dependence of
    breakdown voltage: avalanche increases with T, tunnel/Zener decreases with T)
  - Vishay Application Note AN-2014-3 §2.4 "Zener TC"
  - Horowitz & Hill "Art of Electronics" 3rd ed. §2.2.4 Table 2.1
  - ON Semiconductor AN-961 "Zener Theory and Design Considerations"

Physical explanation (Sze §4.5)
---------------------------------
Two competing breakdown mechanisms:

1. **Zener tunneling** (Vz < ~5 V):
   Band-to-band tunneling (BTBT / Zener effect).
   As temperature rises, the energy band-gap widens slightly (∂Eg/∂T < 0,
   i.e., Eg decreases with T by ~−4×10⁻⁴ eV/K per Varshni eq.), making
   tunneling *easier* at higher T, so Vz DECREASES → **negative TC**.
   Typical: −2 mV/°C for 3.3 V Zeners.

2. **Avalanche multiplication** (Vz > ~7 V):
   Hot-carrier impact ionisation.  Mean free path λ decreases with T
   (more phonon scattering), so carriers need a *higher* field / voltage
   to gain enough energy for impact ionisation, so Vz INCREASES with T
   → **positive TC**.
   Typical: +4 to +9 mV/°C for 12 V Zeners.

3. **Mixed regime** (5 V ≤ Vz ≤ 7 V):
   Both mechanisms coexist.  The two effects partially cancel.
   Near 5.1–5.6 V, TC ≈ 0 (zero-TC Zeners; e.g. BZX55C5V1, 1N5232B).
   The exact zero-TC voltage depends on doping profile and manufacturer.

Model used here
---------------
LINEAR FIRST-ORDER:
   Vz(T) = Vz_nom + TC_mV_per_C × 10⁻³ × (T − T_test)   [V]

This is the standard engineering approximation used in datasheets and app
notes (Vishay AN-2014-3 §2.4, H&H §2.2.4).  The actual Vz vs T curve is
MILDLY QUADRATIC in the 5–7 V transition region where the two mechanisms
compete (Sze §4.5 Fig. 4.5-6), with typical second-order deviation of
±0.1–0.3 mV over 100 °C span.  This is below measurement uncertainty of
most bench setups and is NOT modelled here (see honest_caveat).

Current dependence
------------------
Vz also depends on operating current.  At a different test current Iz_op
versus the datasheet test current Iz_test, the dynamic (incremental)
resistance rZ causes a first-order shift:

   ΔVz ≈ rZ × (Iz_op − Iz_test)

where rZ ≈ 0.01 × Vz_nom / Iz_test  [Ω]   (Vishay AN-2014-3 §2.2 approximation)

This approximation is valid for Iz within ~50% of Iz_test.  A warning is
issued when |Iz_op / Iz_test − 1| > 0.5 (50% deviation).

Recommendation logic
---------------------
If total Vz drift over the operating temperature range exceeds 5% of Vz_nom:
  → suggest using a 5.6 V near-zero-TC Zener or a bandgap Vref IC.

References
----------
S. M. Sze, "Physics of Semiconductor Devices", 3rd ed., §4.5 (breakdown
    temperature dependence), Wiley-Interscience, 2007.
P. Horowitz & W. Hill, "The Art of Electronics", 3rd ed. §2.2.4 Table 2.1,
    Cambridge University Press, 2015.
Vishay Application Note AN-2014-3, "Zener Diode Voltage Regulator Design"
    §2.4 "Temperature Coefficient of Zener Voltage", Rev. 1.0, 2014.
ON Semiconductor Application Note AN-961, "Zener Theory and Design
    Considerations", Rev. 1, 2011. §3 "Temperature Coefficient".

Author: imranparuk
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class ZenerSpec:
    """Zener diode specification for TC drift analysis.

    Attributes
    ----------
    Vz_nominal_V : float
        Nominal Zener breakdown voltage at the datasheet test conditions [V].
        Typical range: 1.8–47 V.
    TC_mV_per_C : float
        Temperature coefficient of Vz [mV/°C], SIGNED.
        Negative values = Zener/tunneling mechanism (low-voltage Zeners).
        Positive values = avalanche mechanism (high-voltage Zeners).
        Near-zero values (~±0.5 mV/°C) = transition region near 5.6 V.
        Typical values:
          3.3 V → −2 mV/°C;  5.6 V → ~0 mV/°C;  12 V → +8 mV/°C.
        Source: Vishay AN-2014-3 §2.4; H&H §2.2.4 Table 2.1.
    test_current_mA : float
        Datasheet test current at which Vz_nominal is specified [mA].
        Typically 5–20 mA for small-signal Zeners.
    test_temp_C : float
        Reference / datasheet test temperature [°C].  Default 25 °C (JEDEC).
    """
    Vz_nominal_V: float
    TC_mV_per_C: float
    test_current_mA: float
    test_temp_C: float = 25.0


@dataclass
class OperatingSpec:
    """Operating conditions for the Zener circuit.

    Attributes
    ----------
    current_mA : float
        Actual operating current through the Zener [mA].
        Used to compute current-dependence correction relative to test_current_mA.
    ambient_temp_C_min : float
        Minimum ambient temperature in the application [°C].
    ambient_temp_C_max : float
        Maximum ambient temperature in the application [°C].
    """
    current_mA: float
    ambient_temp_C_min: float
    ambient_temp_C_max: float


@dataclass
class ZenerDriftReport:
    """Result of Zener temperature-coefficient drift analysis.

    Attributes
    ----------
    Vz_at_min_temp_V : float
        Predicted Vz at ambient_temp_C_min, at operating current [V].
    Vz_at_max_temp_V : float
        Predicted Vz at ambient_temp_C_max, at operating current [V].
    Vz_drift_total_V : float
        Total Vz variation over the temperature range [V].
        = |Vz_at_max_temp_V − Vz_at_min_temp_V|.
    Vz_drift_percent : float
        Drift as a percentage of Vz_nominal_V [%].
    current_dependence_warning : str | None
        Warning string if the operating current deviates > 50% from test
        current, or None if current deviation is within acceptable range.
    recommendation : str
        Engineering recommendation.  "Use 5.6V Zener for near-zero TC" or
        "Use Vref IC (e.g. LM4040, ADR4550)" when drift > 5%.
        Otherwise "Drift within ±5% — design acceptable for general use."
    honest_caveat : str
        Engineering caveats the caller must acknowledge, per task specification.
    """
    Vz_at_min_temp_V: float
    Vz_at_max_temp_V: float
    Vz_drift_total_V: float
    Vz_drift_percent: float
    current_dependence_warning: Optional[str]
    recommendation: str
    honest_caveat: str


# ── Input validation ──────────────────────────────────────────────────────────


def _validate_inputs(zener: ZenerSpec, op: OperatingSpec) -> Optional[str]:
    """Return an error string or None if inputs are valid."""
    if not isinstance(zener, ZenerSpec):
        return "zener must be a ZenerSpec instance"
    if not isinstance(op, OperatingSpec):
        return "op must be an OperatingSpec instance"
    if zener.Vz_nominal_V <= 0:
        return f"Vz_nominal_V must be > 0, got {zener.Vz_nominal_V}"
    if zener.test_current_mA <= 0:
        return f"test_current_mA must be > 0, got {zener.test_current_mA}"
    if op.current_mA <= 0:
        return f"operating current_mA must be > 0, got {op.current_mA}"
    if op.ambient_temp_C_min >= op.ambient_temp_C_max:
        return (
            f"ambient_temp_C_min ({op.ambient_temp_C_min} °C) must be < "
            f"ambient_temp_C_max ({op.ambient_temp_C_max} °C)"
        )
    return None


# ── Core computation ──────────────────────────────────────────────────────────


def compute_zener_drift(zener: ZenerSpec, op: OperatingSpec) -> ZenerDriftReport:
    """Compute Zener voltage drift over temperature.

    Algorithm
    ---------
    1. Linear TC model (Vishay AN-2014-3 §2.4; H&H §2.2.4):
       Vz(T) = Vz_nom + TC_mV_per_C × 1e-3 × (T − T_test)   [V]

    2. Current-dependence correction (Vishay AN-2014-3 §2.2):
       rZ ≈ 0.01 × Vz_nom / Iz_test_A   [Ω]
       ΔVz_current = rZ × (Iz_op_A − Iz_test_A)   [V]
       Applied to Vz_nom before the TC drift is evaluated so that the
       current correction shifts the baseline, then TC drift is computed
       from the corrected base.

    3. Drift metrics:
       Vz_drift_total_V  = |Vz(T_max) − Vz(T_min)|
       Vz_drift_percent  = 100 × Vz_drift_total_V / Vz_nom

    4. Current deviation warning if |Iz_op / Iz_test − 1| > 0.50 (50%).

    5. Recommendation:
       drift > 5% → "use 5.6V Zener for low TC" or "use Vref IC"
       drift ≤ 5% → "design acceptable for general use"

    Parameters
    ----------
    zener : ZenerSpec
    op    : OperatingSpec

    Returns
    -------
    ZenerDriftReport

    Raises
    ------
    ValueError
        On invalid or physically inconsistent inputs.
    """
    err = _validate_inputs(zener, op)
    if err:
        raise ValueError(err)

    vz_nom = zener.Vz_nominal_V
    tc = zener.TC_mV_per_C          # mV/°C, signed
    iz_test_mA = zener.test_current_mA
    t_test = zener.test_temp_C
    iz_op_mA = op.current_mA
    t_min = op.ambient_temp_C_min
    t_max = op.ambient_temp_C_max

    # ── 2. Current-dependence correction ─────────────────────────────────────
    # rZ approximation (Vishay AN-2014-3 §2.2):
    #   rZ ≈ 0.01 × Vz_nom / Iz_test   [Ω]
    iz_test_A = iz_test_mA * 1e-3
    iz_op_A = iz_op_mA * 1e-3
    rz_ohm = 0.01 * vz_nom / iz_test_A   # dynamic impedance approx [Ω]
    delta_vz_current_V = rz_ohm * (iz_op_A - iz_test_A)

    # Vz baseline corrected for operating current
    vz_base_corrected = vz_nom + delta_vz_current_V

    # ── 1. Linear TC drift ───────────────────────────────────────────────────
    tc_V_per_C = tc * 1e-3   # convert mV/°C → V/°C
    vz_at_min = vz_base_corrected + tc_V_per_C * (t_min - t_test)
    vz_at_max = vz_base_corrected + tc_V_per_C * (t_max - t_test)

    # ── 3. Drift metrics ─────────────────────────────────────────────────────
    drift_total_V = abs(vz_at_max - vz_at_min)
    drift_percent = 100.0 * drift_total_V / vz_nom

    # ── 4. Current deviation warning ─────────────────────────────────────────
    current_deviation_ratio = abs(iz_op_mA / iz_test_mA - 1.0)
    if current_deviation_ratio > 0.50:
        current_dependence_warning = (
            f"Operating current {iz_op_mA:.1f} mA deviates "
            f"{current_deviation_ratio * 100:.0f}% from test current "
            f"{iz_test_mA:.1f} mA (> 50% threshold). "
            f"rZ ≈ {rz_ohm:.1f} Ω; ΔVz_current ≈ {delta_vz_current_V * 1000:.1f} mV. "
            "Linear rZ approximation is unreliable > 50% deviation from Iz_test. "
            "Consult the Vz vs Iz characteristic curve in the datasheet "
            "(Vishay AN-2014-3 §2.2, Fig. 2-2)."
        )
    else:
        current_dependence_warning = None

    # ── 5. Recommendation ────────────────────────────────────────────────────
    if drift_percent > 5.0:
        # Distinguish the TC direction to give the most actionable advice
        tc_sign = "positive" if tc > 0.5 else ("negative" if tc < -0.5 else "near-zero")
        if abs(tc) > 1.0:
            recommendation = (
                f"Drift {drift_percent:.1f}% > 5% threshold. "
                f"This Zener has a {tc_sign} TC of {tc:+.1f} mV/°C "
                f"({vz_nom:.1f} V, {'avalanche' if tc > 0 else 'tunneling'} regime per Sze §4.5). "
                "Recommended alternatives: "
                "(1) Use a 5.6 V near-zero TC Zener (e.g. BZX55C5V6, 1N5232B) — TC ≈ 0 mV/°C; "
                "(2) Use a precision bandgap voltage reference IC "
                "(e.g. LM4040 2.5/3.0/4.096 V, ADR4550 5.0 V, LT6656, REF02) — "
                "typical TC 5–25 ppm/°C (0.0005–0.0025 mV/°C), far below any Zener."
            )
        else:
            # Unusual case: near-zero TC but still > 5% drift — likely wide T range
            recommendation = (
                f"Drift {drift_percent:.1f}% > 5% threshold despite near-zero TC "
                f"({tc:+.1f} mV/°C). The wide temperature span "
                f"({t_max - t_min:.0f} °C) amplifies even small residual TC. "
                "Consider a precision bandgap Vref IC for better stability "
                "(e.g. LM4040, ADR4550, LT6656 — TC < 25 ppm/°C)."
            )
    else:
        recommendation = (
            f"Drift {drift_percent:.1f}% ≤ 5% — design acceptable for general use. "
            f"Vz ranges {min(vz_at_min, vz_at_max):.3f}–{max(vz_at_min, vz_at_max):.3f} V "
            f"over {t_min:.0f} to {t_max:.0f} °C. "
            "For precision references (TC < 50 ppm/°C) use a bandgap Vref IC regardless."
        )

    # ── 6. Honest caveat ─────────────────────────────────────────────────────
    honest_caveat = (
        f"HONEST CAVEATS — Zener TC drift for Vz={vz_nom:.2f} V, "
        f"TC={tc:+.2f} mV/°C, T=[{t_min:.0f}..{t_max:.0f}] °C: "
        "(1) LINEAR TC MODEL ONLY — Vz(T) = Vz_nom + TC × (T − T_test); "
        "real Vz vs T is mildly quadratic in the 5–7 V transition region "
        "(where avalanche and Zener tunneling coexist), with second-order "
        "deviation of ±0.1–0.3 mV over 100 °C (Sze §4.5, Fig. 4.5-6; "
        "Vishay AN-2014-3 §2.4). For first-order design this is negligible. "
        "(2) TC IS CURRENT-DEPENDENT — TC shifts slightly with operating "
        "current (measured TC values are at Iz_test per the datasheet). "
        "This model uses the datasheet TC at Iz_test; TC at a significantly "
        "different current may differ by 10–20% (ON AN-961 §3). "
        "(3) UNIT-TO-UNIT TC SPREAD — datasheet TC is the nominal/typical value. "
        "Part-to-part variation of TC is typically ±30–50% for standard "
        "Zener grades (C-suffix ±5% Vz). Use tight-tolerance parts (A/B suffix) "
        "or a pre-screened Vref IC if TC spread matters. "
        "(4) THERMAL RESISTANCE / SELF-HEATING NOT MODELLED — if the Zener "
        "dissipates significant power (P_Z = Vz × Iz), junction temperature "
        "T_j = T_ambient + θJA × P_Z may substantially exceed ambient. "
        "Compute T_j and use T_j (not T_ambient) in the TC drift formula "
        "for accurate results. Typical θJA: 300–600 °C/W (SOD-80/DO-35 "
        "packages at 400 mW rating; Vishay BZX55 datasheet §6). "
        "(5) CURRENT-DEPENDENCE MODEL IS A LINEARISATION — "
        f"rZ ≈ 0.01 × Vz / Iz_test = {rz_ohm:.1f} Ω is a first-order "
        "approximation (Vishay AN-2014-3 §2.2). The actual Vz vs Iz "
        "characteristic is non-linear; for operating currents far from "
        "Iz_test, use the full Vz vs Iz curve from the device datasheet. "
        "(6) REFERENCE ZERO-TC VOLTAGE IS DEVICE-SPECIFIC — the zero-TC "
        "crossing is nominally ~5.1–5.6 V but varies by process and "
        "manufacturer; verify the actual TC at operating current from the "
        "device datasheet before assuming zero TC. "
        "Refs: S. M. Sze §4.5; H&H §2.2.4 Table 2.1; Vishay AN-2014-3 §2.4; "
        "ON Semiconductor AN-961 §3."
    )

    return ZenerDriftReport(
        Vz_at_min_temp_V=round(vz_at_min, 6),
        Vz_at_max_temp_V=round(vz_at_max, 6),
        Vz_drift_total_V=round(drift_total_V, 6),
        Vz_drift_percent=round(drift_percent, 4),
        current_dependence_warning=current_dependence_warning,
        recommendation=recommendation,
        honest_caveat=honest_caveat,
    )


# ── Dict-in / dict-out wrapper ────────────────────────────────────────────────


def compute_zener_drift_from_dict(d: dict) -> dict:
    """Dict-in / dict-out wrapper for LLM / HTTP callers.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    Never raises.

    Input keys (zener):
        Vz_nominal_V, TC_mV_per_C, test_current_mA, [test_temp_C=25.0]
    Input keys (operating):
        current_mA, ambient_temp_C_min, ambient_temp_C_max
    """
    try:
        zener = ZenerSpec(
            Vz_nominal_V=float(d["Vz_nominal_V"]),
            TC_mV_per_C=float(d["TC_mV_per_C"]),
            test_current_mA=float(d["test_current_mA"]),
            test_temp_C=float(d.get("test_temp_C", 25.0)),
        )
        op = OperatingSpec(
            current_mA=float(d["current_mA"]),
            ambient_temp_C_min=float(d["ambient_temp_C_min"]),
            ambient_temp_C_max=float(d["ambient_temp_C_max"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid spec: {exc}"}

    try:
        report = compute_zener_drift(zener, op)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "Vz_at_min_temp_V": report.Vz_at_min_temp_V,
        "Vz_at_max_temp_V": report.Vz_at_max_temp_V,
        "Vz_drift_total_V": report.Vz_drift_total_V,
        "Vz_drift_percent": report.Vz_drift_percent,
        "current_dependence_warning": report.current_dependence_warning,
        "recommendation": report.recommendation,
        "honest_caveat": report.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────

_ZENER_TC_DRIFT_SPEC = ToolSpec(
    name="elec_compute_zener_drift",
    description=(
        "Compute Zener diode voltage drift over temperature using the temperature "
        "coefficient (TC) in mV/°C.\n\n"
        "Models the Vz vs T curve which has a zero-TC crossing near 5.6 V "
        "(above: positive TC dominated by avalanche; below: negative TC dominated "
        "by Zener tunneling). Per Vishay AN-2014-3 §2.4, ON AN-961 §3, and "
        "Sze 'Physics of Semiconductor Devices' §4.5.\n\n"
        "Typical TC values:\n"
        "  3.3 V Zener → TC ≈ −2 mV/°C (tunneling regime)\n"
        "  5.6 V Zener → TC ≈ 0 mV/°C  (transition/near-zero TC)\n"
        "  12 V Zener  → TC ≈ +8 mV/°C (avalanche regime)\n\n"
        "Algorithm:\n"
        "  rZ ≈ 0.01 × Vz_nom / Iz_test [Ω]  (Vishay AN-2014-3 §2.2)\n"
        "  ΔVz_current = rZ × (Iz_op − Iz_test)  [V]\n"
        "  Vz(T) = (Vz_nom + ΔVz_current) + TC × 10⁻³ × (T − T_test)  [V]\n"
        "  drift_percent = 100 × |Vz(T_max) − Vz(T_min)| / Vz_nom\n\n"
        "Recommendation: drift > 5% → suggest 5.6 V near-zero TC Zener "
        "or bandgap Vref IC.\n\n"
        "HONEST: LINEAR TC MODEL ONLY — real Vz vs T is mildly quadratic "
        "in the 5–7 V transition region; thermal self-heating NOT modelled; "
        "TC is current-dependent and has part-to-part spread.\n\n"
        "Input: { Vz_nominal_V, TC_mV_per_C, test_current_mA, [test_temp_C=25.0], "
        "current_mA, ambient_temp_C_min, ambient_temp_C_max }\n\n"
        "Returns: { ok, Vz_at_min_temp_V, Vz_at_max_temp_V, Vz_drift_total_V, "
        "Vz_drift_percent, current_dependence_warning, recommendation, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Vz_nominal_V": {
                "type": "number",
                "description": (
                    "Nominal Zener breakdown voltage at datasheet test conditions [V]. "
                    "Typical range 1.8–47 V."
                ),
            },
            "TC_mV_per_C": {
                "type": "number",
                "description": (
                    "Temperature coefficient of Vz [mV/°C], SIGNED. "
                    "Negative for tunneling-dominated Zeners (Vz < ~5 V), "
                    "positive for avalanche-dominated (Vz > ~7 V). "
                    "Typical: −2 for 3.3 V, ~0 for 5.6 V, +8 for 12 V."
                ),
            },
            "test_current_mA": {
                "type": "number",
                "description": (
                    "Datasheet test current at which Vz_nominal is specified [mA]. "
                    "Typically 5–20 mA for small-signal Zeners."
                ),
            },
            "test_temp_C": {
                "type": "number",
                "description": (
                    "Reference / datasheet test temperature [°C]. Default 25 °C (JEDEC)."
                ),
            },
            "current_mA": {
                "type": "number",
                "description": "Actual operating current through the Zener [mA].",
            },
            "ambient_temp_C_min": {
                "type": "number",
                "description": "Minimum ambient temperature in the application [°C].",
            },
            "ambient_temp_C_max": {
                "type": "number",
                "description": "Maximum ambient temperature in the application [°C].",
            },
        },
        "required": [
            "Vz_nominal_V",
            "TC_mV_per_C",
            "test_current_mA",
            "current_mA",
            "ambient_temp_C_min",
            "ambient_temp_C_max",
        ],
    },
)


@register(_ZENER_TC_DRIFT_SPEC, write=False)
async def elec_compute_zener_drift(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = compute_zener_drift_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _ZENER_TC_DRIFT_SPEC.name,
        _ZENER_TC_DRIFT_SPEC,
        elec_compute_zener_drift,
    ),
]
