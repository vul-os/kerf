"""
Decoupling capacitor sizing for digital ICs.

Given a power rail's transient current demand, allowed voltage droop, and
signal bandwidth, recommend bulk + bypass capacitor values and quantity per
power rail.

Physics derivation (Howard Johnson "High-Speed Digital Design" §8.3 +
Henry Ott "Electromagnetic Compatibility Engineering" §13.3)
--------------------------------------------------------------------------

Target impedance (Howard Johnson §8.3):
    Z_t = ΔV / I_transient

    The PDN must present impedance ≤ Z_t from DC to the signal bandwidth.
    A smaller Z_t demands more decoupling capacitance.

Bulk capacitor (energy storage, covers slow VRM response):
    Charge balance: Q = I · t_rise  →  C_bulk = I · t_rise / ΔV

    This is the minimum bulk capacitance to supply the transient charge before
    the VRM replenishes it (Ott §13.3.3).  In practice round up to the nearest
    standard value.

Bypass capacitor (local high-frequency decoupling):
    100 nF per IC is the industry rule of thumb (Ott §13.3.2).  This value
    is capacitive through ~1 MHz and presents low impedance to fast switching
    transients for typical 0402/0603 MLCCs with 1–2 nH ESL.

    Count: 1 bypass cap per IC (minimum); increase if ESR/ESL budget requires it.

Maximum allowable ESL per bypass cap (ensures |Z_cap| ≤ Z_t at f_bw):
    Above the cap's self-resonant frequency (SRF) the cap behaves inductively:
    |Z| ≈ ω · L_esl.  For |Z| ≤ Z_t at f_bw:

        L_esl ≤ Z_t / (2π · f_bw)

    Equivalently: SRF of the bypass cap must be ≥ f_bw, or the cap is inductive
    at the bandwidth of interest and provides no benefit.

Maximum allowable ESR per bypass cap:
    At the SRF the cap looks purely resistive (reactive parts cancel).
    For minimum impedance at SRF: ESR ≤ Z_t.  Typically target ESR ≤ Z_t / 2
    to leave headroom for voltage divider effects with PCB plane inductance.

    max_ESR ≤ Z_t (Ott §13.3.4, practical limit: Z_t / 2 for margin)

Honest caveats
--------------
• Target-impedance heuristic only.  Full PDN validation requires AC impedance
  simulation (SPICE or pdn_wizard) across the entire frequency range with
  actual PCB stackup, via inductance, and plane spreading inductance.
• Bulk and bypass caps interact: anti-resonance (parallel resonance) between
  adjacent cap banks can create impedance spikes above Z_t.  Use
  `pdn_decap_wizard` for multi-bank PDN impedance sweep.
• 100 nF bypass rule of thumb assumes 0402/0603 MLCC at ≤50 MHz bandwidth.
  At bandwidth > 100 MHz use 10 nF ceramic in a 0201 footprint (lower ESL).
• VRM bandwidth (typically 50–500 kHz) is not modelled here; at frequencies
  below the VRM crossover, the VRM itself provides low impedance — bulk caps
  only need to cover the gap between VRM crossover and the first bypass cap SRF.

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
class PowerRailSpec:
    """Specification for a single power rail requiring decoupling.

    Attributes
    ----------
    voltage_V : float
        Rail voltage [V] (e.g. 3.3, 1.8, 1.2).
    max_transient_current_A : float
        Peak transient current step the IC(s) demand [A].
    transient_rise_time_ns : float
        Rise time of the current step [ns].  Controls bulk capacitor sizing.
    max_droop_mV : float
        Maximum allowed voltage droop at the IC pins [mV].
    signal_bandwidth_MHz : float
        Target PDN bandwidth [MHz] — the decoupling network must be effective
        up to this frequency.
    num_ICs : int
        Number of ICs sharing this power rail.  Drives bypass cap count.
    """
    voltage_V: float
    max_transient_current_A: float
    transient_rise_time_ns: float
    max_droop_mV: float
    signal_bandwidth_MHz: float
    num_ICs: int


@dataclass
class DecouplingRecommendation:
    """Recommended decoupling capacitor network for a single power rail.

    Attributes
    ----------
    bulk_cap_uF : float
        Minimum bulk capacitance [µF].  Derived from charge-balance:
        C = I · t_rise / ΔV.
    bypass_cap_uF : float
        Recommended bypass cap value per IC [µF].  Typically 0.1 µF (100 nF)
        for bandwidths ≤ 50 MHz; 0.01 µF (10 nF) for 50–500 MHz.
    bypass_count : int
        Minimum number of bypass capacitors (one per IC; may be increased for
        very tight Z_t or high-bandwidth rails).
    max_ESL_nH : float
        Maximum allowable equivalent-series inductance per bypass cap [nH],
        derived from Z_t / (2π · f_bw).  Select caps with ESL ≤ this value.
    max_ESR_mOhm : float
        Maximum allowable ESR per bypass cap [mΩ] — approximately Z_t for
        minimum impedance at SRF.
    target_impedance_mOhm : float
        Z_t = ΔV / I_transient [mΩ].  The PDN must present |Z| ≤ Z_t from
        DC to signal_bandwidth_MHz.
    honest_caveat : str
        Engineering limitation statement.
    """
    bulk_cap_uF: float
    bypass_cap_uF: float
    bypass_count: int
    max_ESL_nH: float
    max_ESR_mOhm: float
    target_impedance_mOhm: float
    honest_caveat: str


# ── Core calculation ────────────────────────────────────────────────────────────


def recommend_decoupling_caps(spec: PowerRailSpec) -> DecouplingRecommendation:
    """Recommend decoupling capacitors for a digital IC power rail.

    Parameters
    ----------
    spec : PowerRailSpec
        Rail specification.

    Returns
    -------
    DecouplingRecommendation

    Raises
    ------
    ValueError
        On physically invalid inputs (zero/negative current, droop, etc.).

    References
    ----------
    Howard Johnson "High-Speed Digital Design" §8.3 — target impedance.
    Henry Ott "Electromagnetic Compatibility Engineering" §13.3 — bulk + bypass.
    """
    # ── Input validation ─────────────────────────────────────────────────────
    if spec.voltage_V <= 0.0:
        raise ValueError(f"voltage_V must be > 0, got {spec.voltage_V}")
    if spec.max_transient_current_A <= 0.0:
        raise ValueError(
            f"max_transient_current_A must be > 0, got {spec.max_transient_current_A}"
        )
    if spec.transient_rise_time_ns <= 0.0:
        raise ValueError(
            f"transient_rise_time_ns must be > 0, got {spec.transient_rise_time_ns}"
        )
    if spec.max_droop_mV <= 0.0:
        raise ValueError(f"max_droop_mV must be > 0, got {spec.max_droop_mV}")
    if spec.signal_bandwidth_MHz <= 0.0:
        raise ValueError(
            f"signal_bandwidth_MHz must be > 0, got {spec.signal_bandwidth_MHz}"
        )
    if spec.num_ICs < 1:
        raise ValueError(f"num_ICs must be >= 1, got {spec.num_ICs}")

    # Validate droop does not exceed rail voltage
    droop_V = spec.max_droop_mV * 1e-3
    if droop_V >= spec.voltage_V:
        raise ValueError(
            f"max_droop_mV ({spec.max_droop_mV:.1f} mV) must be < voltage_V "
            f"({spec.voltage_V:.3f} V = {spec.voltage_V * 1000:.0f} mV)"
        )

    I = spec.max_transient_current_A
    t_rise_s = spec.transient_rise_time_ns * 1e-9
    delta_V = droop_V
    f_bw_hz = spec.signal_bandwidth_MHz * 1e6

    # ── Target impedance (Howard Johnson §8.3) ────────────────────────────────
    # Z_t = ΔV / I_transient  [Ω]
    Z_t_ohm = delta_V / I
    Z_t_mOhm = Z_t_ohm * 1e3

    # ── Bulk capacitor (Ott §13.3.3 charge balance) ───────────────────────────
    # C_bulk = I · t_rise / ΔV  [F]
    # Stores the charge needed during the VRM's response delay (= t_rise here).
    C_bulk_F = I * t_rise_s / delta_V
    C_bulk_uF = C_bulk_F * 1e6

    # ── Bypass capacitor value (Ott §13.3.2 rule of thumb) ────────────────────
    # 100 nF per IC for bandwidth ≤ 50 MHz.
    # 10 nF per IC for bandwidth > 50 MHz (lower ESL 0201 MLCC preferred).
    if f_bw_hz <= 50e6:
        bypass_cap_F = 100e-9   # 100 nF
    else:
        bypass_cap_F = 10e-9    # 10 nF
    bypass_cap_uF = bypass_cap_F * 1e6

    # ── Bypass count ──────────────────────────────────────────────────────────
    # Minimum: 1 per IC.  If Z_t is very tight (< 10 mΩ), add a second cap per
    # IC to halve the parallel ESR/ESL.
    if Z_t_mOhm < 10.0:
        bypass_count = spec.num_ICs * 2
    else:
        bypass_count = spec.num_ICs

    # ── Max ESL per bypass cap ────────────────────────────────────────────────
    # Above SRF the cap is inductive: |Z| ≈ 2π·f·L_esl.
    # For |Z| ≤ Z_t at f_bw:  L_esl ≤ Z_t / (2π · f_bw)
    # This is divided by bypass_count because count caps in parallel have
    # effective inductance L_esl / count.
    L_esl_max_H = Z_t_ohm / (2.0 * math.pi * f_bw_hz)
    # But this is the aggregate limit; each cap has ESL ≤ L_esl_max × bypass_count
    # (paralleling N identical L reduces to L/N)
    L_esl_per_cap_H = L_esl_max_H * bypass_count
    L_esl_per_cap_nH = L_esl_per_cap_H * 1e9

    # ── Max ESR per bypass cap ────────────────────────────────────────────────
    # At SRF, |Z| = ESR.  For |Z| ≤ Z_t at SRF: ESR ≤ Z_t.
    # With bypass_count parallel caps the effective ESR = ESR_single / bypass_count,
    # so each cap can have ESR ≤ Z_t × bypass_count.
    ESR_max_per_cap_ohm = Z_t_ohm * bypass_count
    ESR_max_per_cap_mOhm = ESR_max_per_cap_ohm * 1e3

    # ── Honest caveat ────────────────────────────────────────────────────────
    caveat = (
        "Target-impedance heuristic only (Howard Johnson §8.3 + Ott §13.3). "
        "Bulk cap = charge-balance estimate; does not account for VRM crossover "
        "frequency or ESL of board-level inductance. "
        "Bypass 100 nF/10 nF rule of thumb; actual ESL of chosen footprint "
        "(0201 ≈ 0.4 nH, 0402 ≈ 1 nH, 0603 ≈ 2 nH) must be verified against "
        f"max_ESL = {L_esl_per_cap_nH:.2f} nH. "
        "Anti-resonance between bulk and bypass bank is NOT modelled — use "
        "pdn_decap_wizard for full AC impedance sweep with bank interactions."
    )

    return DecouplingRecommendation(
        bulk_cap_uF=C_bulk_uF,
        bypass_cap_uF=bypass_cap_uF,
        bypass_count=bypass_count,
        max_ESL_nH=L_esl_per_cap_nH,
        max_ESR_mOhm=ESR_max_per_cap_mOhm,
        target_impedance_mOhm=Z_t_mOhm,
        honest_caveat=caveat,
    )


# ── Validated entry point (dict-in, dict-out) ─────────────────────────────────


def recommend_decoupling_caps_from_dict(d: dict) -> dict:
    """Dict-in, dict-out wrapper for LLM/HTTP callers.

    Returns {"ok": True, ...fields...} or {"ok": False, "reason": ...}.
    Never raises.
    """
    try:
        spec = PowerRailSpec(
            voltage_V=float(d["voltage_V"]),
            max_transient_current_A=float(d["max_transient_current_A"]),
            transient_rise_time_ns=float(d["transient_rise_time_ns"]),
            max_droop_mV=float(d["max_droop_mV"]),
            signal_bandwidth_MHz=float(d["signal_bandwidth_MHz"]),
            num_ICs=int(d["num_ICs"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid input: {exc}"}

    try:
        rec = recommend_decoupling_caps(spec)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "target_impedance_mOhm": rec.target_impedance_mOhm,
        "bulk_cap_uF": rec.bulk_cap_uF,
        "bypass_cap_uF": rec.bypass_cap_uF,
        "bypass_count": rec.bypass_count,
        "max_ESL_nH": rec.max_ESL_nH,
        "max_ESR_mOhm": rec.max_ESR_mOhm,
        "honest_caveat": rec.honest_caveat,
    }


# ── LLM tool ──────────────────────────────────────────────────────────────────


_DECOUPLING_SPEC = ToolSpec(
    name="electronics_recommend_decoupling_caps",
    description=(
        "Recommend bulk + bypass decoupling capacitors for a digital IC power rail.\n\n"
        "Uses Howard Johnson 'High-Speed Digital Design' §8.3 (target impedance) and "
        "Henry Ott 'Electromagnetic Compatibility Engineering' §13.3 (bulk charge "
        "balance + bypass rule of thumb).\n\n"
        "Key formulas:\n"
        "  Z_target = ΔV_droop / I_transient  (target PDN impedance)\n"
        "  C_bulk   = I · t_rise / ΔV_droop   (minimum bulk capacitance)\n"
        "  C_bypass = 100 nF per IC (≤50 MHz) / 10 nF per IC (>50 MHz)\n"
        "  L_esl_max = Z_target / (2π · f_bw) per parallel cap  (ESL constraint)\n\n"
        "HONEST: target-impedance heuristic only; PDN simulation (SPICE or "
        "pdn_decap_wizard) required for full anti-resonance and bank interaction "
        "validation.\n\n"
        "Input: { voltage_V, max_transient_current_A, transient_rise_time_ns, "
        "max_droop_mV, signal_bandwidth_MHz, num_ICs }\n\n"
        "Returns: { ok, target_impedance_mOhm, bulk_cap_uF, bypass_cap_uF, "
        "bypass_count, max_ESL_nH, max_ESR_mOhm, honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "voltage_V": {
                "type": "number",
                "description": "Rail voltage [V] (e.g. 3.3, 1.8, 1.2).",
            },
            "max_transient_current_A": {
                "type": "number",
                "description": "Peak transient current step [A].",
            },
            "transient_rise_time_ns": {
                "type": "number",
                "description": "Current step rise time [ns].",
            },
            "max_droop_mV": {
                "type": "number",
                "description": "Maximum allowed voltage droop at IC pins [mV].",
            },
            "signal_bandwidth_MHz": {
                "type": "number",
                "description": "Target PDN bandwidth [MHz].",
            },
            "num_ICs": {
                "type": "integer",
                "description": "Number of ICs sharing this power rail.",
            },
        },
        "required": [
            "voltage_V",
            "max_transient_current_A",
            "transient_rise_time_ns",
            "max_droop_mV",
            "signal_bandwidth_MHz",
            "num_ICs",
        ],
    },
)


@register(_DECOUPLING_SPEC, write=False)
async def electronics_recommend_decoupling_caps(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = recommend_decoupling_caps_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export (consumed by plugin._register_tools) ────────────────────────

TOOLS = [
    (
        _DECOUPLING_SPEC.name,
        _DECOUPLING_SPEC,
        electronics_recommend_decoupling_caps,
    ),
]
