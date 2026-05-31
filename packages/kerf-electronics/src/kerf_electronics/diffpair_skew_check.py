"""
Intra-pair length-matching skew checker for PCB differential pairs.

Given routed trace lengths (P and N conductors) and substrate dielectric
constant, computes propagation-velocity-aware time skew in picoseconds and
verifies compliance against industry-standard protocol budgets.

Physics
-------
Propagation velocity in a PCB medium with effective dielectric constant εr:

    v = c / √εr   [mm/ps]   where c = 0.3 mm/ps (speed of light in free space)

Intra-pair time skew:

    Δt = |L_pos − L_neg| / v   [ps]

Protocol skew budgets (Howard Johnson "High-Speed Digital Design" §12.4;
IPC-2141A §6; each protocol's PHY specification):

    HDMI 2.1   — 15 ps  (HDMI 2.1 Specification §10.4.5)
    USB 3.0    — 20 ps  (USB 3.0 Specification §6.9)
    PCIe 4.0   — 2 ps   (PCI Express CEM 4.0 §3.2.1)
    DDR5       — 5 ps   (JEDEC JESD79-5 §8.1)
    SATA III   — 15 ps  (SATA Revision 3.0 §8.2.2)

Recommended maximum length mismatch:

    ΔL_max = budget_ps × v   [mm]

HONEST CAVEATS (always reported)
----------------------------------
1. Uses a single effective εr for the whole trace path.  In practice the
   dielectric constant varies with frequency (dispersion), copper roughness,
   glass-weave geometry, and moisture absorption; the actual propagation
   velocity will differ from this estimate by ±5–15% (IPC-2141A §6.2).
2. Serpentine (meander) tuning segments do not propagate at the same velocity
   as straight segments due to mode coupling between adjacent meander legs —
   the so-called "meander delay" described in Johnson §12.4.  The skew
   contribution of each meander is not modelled here; only the net length
   difference is used.
3. Jitter and skew from connector/via transitions, stub-resonance, and
   dielectric discontinuities are NOT included.
4. All budgets are intra-pair only.  Inter-pair skew (lane-to-lane) is a
   separate constraint and is NOT checked here.

References
----------
Howard Johnson & Martin Graham, "High-Speed Digital Design", Prentice Hall
1993, §12.4 "Differential Signaling Skew".

IPC-2141A, "Controlled Impedance Circuit Boards and High Frequency
Considerations", IPC 2004, §6 "Dielectric Properties and Signal Propagation".

HDMI 2.1 Specification, HDMI Forum 2017, §10.4.5.
USB 3.0 Specification Rev 1.0, USB-IF 2008, §6.9.
PCI Express Card Electromechanical Specification Rev 4.0 §3.2.1.
JEDEC JESD79-5B (DDR5 SDRAM Specification) §8.1.
SATA Revision 3.0 Specification §8.2.2.

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Speed of light in free space expressed in mm/ps (0.299 792 458 mm/ps).
_C_MM_PER_PS: float = 0.3  # mm/ps  (exact per task spec, matches Johnson §12.4)

# Protocol skew budgets in picoseconds (intra-pair, P-to-N).
_PROTOCOL_BUDGETS_PS: dict[str, float] = {
    "hdmi_21": 15.0,
    "usb_30": 20.0,
    "pcie_40": 2.0,
    "ddr5": 5.0,
    "sata_iii": 15.0,
}

_KNOWN_PROTOCOLS = frozenset(_PROTOCOL_BUDGETS_PS) | {"custom"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DiffPairSpec:
    """Input specification for a differential pair skew check.

    Attributes
    ----------
    signal_name : str
        Human-readable label for this pair (e.g. "USB_DP").
    pos_length_mm : float
        Routed length of the positive (P) conductor in mm.
    neg_length_mm : float
        Routed length of the negative (N) conductor in mm.
    dielectric_constant_er : float
        Effective relative permittivity εr of the substrate.
        FR4 typical = 4.5 (IPC-2141A §6.2 mid-frequency value).
    protocol : str
        One of: "hdmi_21", "usb_30", "pcie_40", "ddr5", "sata_iii", "custom".
    custom_skew_budget_ps : float | None
        Required when protocol == "custom"; ignored otherwise.
    """
    signal_name: str
    pos_length_mm: float
    neg_length_mm: float
    dielectric_constant_er: float = 4.5
    protocol: str = "hdmi_21"
    custom_skew_budget_ps: float | None = None


@dataclass
class DiffPairSkewReport:
    """Result of a differential pair intra-pair skew check.

    Attributes
    ----------
    length_skew_mm : float
        Absolute length mismatch |L_pos − L_neg| in mm.
    time_skew_ps : float
        Propagation time skew Δt = length_skew_mm / v in picoseconds.
    skew_budget_ps : float
        Protocol-defined maximum allowable intra-pair skew in ps.
    compliant : bool
        True if time_skew_ps ≤ skew_budget_ps.
    recommended_max_length_mismatch_mm : float
        Maximum length mismatch that keeps Δt within budget:
        ΔL_max = skew_budget_ps × v.
    propagation_velocity_mm_per_ps : float
        v = c / √εr in mm/ps used for the computation.
    honest_caveat : str
        Engineering limitation statement; always present.
    """
    length_skew_mm: float
    time_skew_ps: float
    skew_budget_ps: float
    compliant: bool
    recommended_max_length_mismatch_mm: float
    propagation_velocity_mm_per_ps: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------


def check_diffpair_skew(spec: DiffPairSpec) -> DiffPairSkewReport:
    """Compute intra-pair length-matching skew and verify against protocol budget.

    Parameters
    ----------
    spec : DiffPairSpec
        Pair specification — trace lengths, dielectric, protocol.

    Returns
    -------
    DiffPairSkewReport

    Raises
    ------
    ValueError
        On physically invalid inputs.

    References
    ----------
    Howard Johnson "High-Speed Digital Design" §12.4.
    IPC-2141A §6.
    """
    # ── Input validation ─────────────────────────────────────────────────────
    if not isinstance(spec.signal_name, str) or not spec.signal_name.strip():
        raise ValueError("signal_name must be a non-empty string")
    if not isinstance(spec.pos_length_mm, (int, float)) or spec.pos_length_mm < 0:
        raise ValueError(f"pos_length_mm must be >= 0, got {spec.pos_length_mm}")
    if not isinstance(spec.neg_length_mm, (int, float)) or spec.neg_length_mm < 0:
        raise ValueError(f"neg_length_mm must be >= 0, got {spec.neg_length_mm}")
    if not isinstance(spec.dielectric_constant_er, (int, float)) or spec.dielectric_constant_er <= 0:
        raise ValueError(
            f"dielectric_constant_er must be > 0, got {spec.dielectric_constant_er}"
        )
    if spec.protocol not in _KNOWN_PROTOCOLS:
        raise ValueError(
            f"protocol must be one of {sorted(_KNOWN_PROTOCOLS)}, got {spec.protocol!r}"
        )
    if spec.protocol == "custom":
        if spec.custom_skew_budget_ps is None:
            raise ValueError(
                "custom_skew_budget_ps must be provided when protocol == 'custom'"
            )
        if (
            not isinstance(spec.custom_skew_budget_ps, (int, float))
            or spec.custom_skew_budget_ps <= 0
        ):
            raise ValueError(
                f"custom_skew_budget_ps must be > 0, got {spec.custom_skew_budget_ps}"
            )

    # ── Propagation velocity (Howard Johnson §12.4) ───────────────────────────
    # v = c / √εr   [mm/ps]
    v_mm_per_ps: float = _C_MM_PER_PS / math.sqrt(spec.dielectric_constant_er)

    # ── Length mismatch ───────────────────────────────────────────────────────
    delta_length_mm: float = abs(spec.pos_length_mm - spec.neg_length_mm)

    # ── Time skew ─────────────────────────────────────────────────────────────
    # Δt = ΔL / v   [ps]
    time_skew_ps: float = delta_length_mm / v_mm_per_ps

    # ── Skew budget ───────────────────────────────────────────────────────────
    if spec.protocol == "custom":
        skew_budget_ps = float(spec.custom_skew_budget_ps)  # type: ignore[arg-type]
    else:
        skew_budget_ps = _PROTOCOL_BUDGETS_PS[spec.protocol]

    # ── Compliance ────────────────────────────────────────────────────────────
    compliant: bool = time_skew_ps <= skew_budget_ps

    # ── Recommended maximum length mismatch ───────────────────────────────────
    # ΔL_max = budget_ps × v   [mm]
    recommended_max_mismatch_mm: float = skew_budget_ps * v_mm_per_ps

    # ── Honest caveat ─────────────────────────────────────────────────────────
    caveat = (
        "Assumes a uniform effective εr = {er:.2f} for the full trace path. "
        "Actual propagation velocity varies ±5–15% due to frequency dispersion, "
        "copper surface roughness, glass-weave geometry, and moisture absorption "
        "(IPC-2141A §6.2). "
        "Serpentine (meander) tuning segments introduce additional skew beyond "
        "simple length-mismatch due to mode coupling between adjacent legs "
        "(Howard Johnson §12.4 'meander delay'); this is NOT modelled. "
        "Via and connector transition skew, stub resonance, and dielectric "
        "discontinuities are NOT included. "
        "Budget is intra-pair only; inter-pair (lane-to-lane) skew is a separate "
        "constraint and is NOT checked here."
    ).format(er=spec.dielectric_constant_er)

    return DiffPairSkewReport(
        length_skew_mm=round(delta_length_mm, 6),
        time_skew_ps=round(time_skew_ps, 4),
        skew_budget_ps=skew_budget_ps,
        compliant=compliant,
        recommended_max_length_mismatch_mm=round(recommended_max_mismatch_mm, 6),
        propagation_velocity_mm_per_ps=round(v_mm_per_ps, 6),
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# Dict-in, dict-out wrapper (for LLM / HTTP callers)
# ---------------------------------------------------------------------------


def check_diffpair_skew_from_dict(d: dict) -> dict:
    """Validated dict-in, dict-out wrapper.  Never raises.

    Returns ``{"ok": True, ...fields...}`` or ``{"ok": False, "reason": ...}``.
    """
    try:
        spec = DiffPairSpec(
            signal_name=str(d.get("signal_name", "")),
            pos_length_mm=float(d["pos_length_mm"]),
            neg_length_mm=float(d["neg_length_mm"]),
            dielectric_constant_er=float(d.get("dielectric_constant_er", 4.5)),
            protocol=str(d.get("protocol", "hdmi_21")),
            custom_skew_budget_ps=(
                float(d["custom_skew_budget_ps"])
                if d.get("custom_skew_budget_ps") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid input: {exc}"}

    try:
        report = check_diffpair_skew(spec)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"unexpected error: {exc}"}

    return {
        "ok": True,
        "signal_name": spec.signal_name,
        "pos_length_mm": spec.pos_length_mm,
        "neg_length_mm": spec.neg_length_mm,
        "dielectric_constant_er": spec.dielectric_constant_er,
        "protocol": spec.protocol,
        "length_skew_mm": report.length_skew_mm,
        "time_skew_ps": report.time_skew_ps,
        "skew_budget_ps": report.skew_budget_ps,
        "compliant": report.compliant,
        "recommended_max_length_mismatch_mm": report.recommended_max_length_mismatch_mm,
        "propagation_velocity_mm_per_ps": report.propagation_velocity_mm_per_ps,
        "honest_caveat": report.honest_caveat,
    }


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

_DIFFPAIR_SKEW_SPEC = ToolSpec(
    name="electronics_check_diffpair_skew",
    description=(
        "Check intra-pair length-matching skew for a PCB differential pair.\n\n"
        "Computes propagation-velocity-aware time skew (mm and ps) from trace "
        "lengths and substrate dielectric constant, then verifies against the "
        "protocol skew budget.\n\n"
        "Physics (Howard Johnson 'High-Speed Digital Design' §12.4 + IPC-2141A §6):\n"
        "  v = c / √εr   (propagation velocity, c = 0.3 mm/ps)\n"
        "  Δt = |L_pos − L_neg| / v\n\n"
        "Protocol budgets (intra-pair):\n"
        "  hdmi_21  → 15 ps  (HDMI 2.1 Spec §10.4.5)\n"
        "  usb_30   → 20 ps  (USB 3.0 Spec §6.9)\n"
        "  pcie_40  →  2 ps  (PCIe CEM 4.0 §3.2.1)\n"
        "  ddr5     →  5 ps  (JEDEC JESD79-5 §8.1)\n"
        "  sata_iii → 15 ps  (SATA Rev 3.0 §8.2.2)\n"
        "  custom   → supply custom_skew_budget_ps\n\n"
        "HONEST: assumes single uniform εr; meander-delay skew NOT modelled; "
        "via/connector transitions NOT included; inter-pair skew NOT checked.\n\n"
        "Input: { signal_name, pos_length_mm, neg_length_mm, "
        "[dielectric_constant_er=4.5], [protocol='hdmi_21'], "
        "[custom_skew_budget_ps] }\n\n"
        "Returns: { ok, length_skew_mm, time_skew_ps, skew_budget_ps, compliant, "
        "recommended_max_length_mismatch_mm, propagation_velocity_mm_per_ps, "
        "honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "signal_name": {
                "type": "string",
                "description": "Pair label, e.g. 'USB_DP'.",
            },
            "pos_length_mm": {
                "type": "number",
                "description": "Routed length of positive (P) conductor [mm].",
            },
            "neg_length_mm": {
                "type": "number",
                "description": "Routed length of negative (N) conductor [mm].",
            },
            "dielectric_constant_er": {
                "type": "number",
                "description": (
                    "Effective relative permittivity εr of the substrate. "
                    "FR4 typical = 4.5; Rogers 4350B ≈ 3.66; air = 1.0. Default: 4.5."
                ),
            },
            "protocol": {
                "type": "string",
                "enum": ["hdmi_21", "usb_30", "pcie_40", "ddr5", "sata_iii", "custom"],
                "description": (
                    "Protocol to check against. Use 'custom' and supply "
                    "custom_skew_budget_ps for non-standard interfaces."
                ),
            },
            "custom_skew_budget_ps": {
                "type": "number",
                "description": (
                    "Custom intra-pair skew budget [ps]. "
                    "Required when protocol == 'custom'; ignored otherwise."
                ),
            },
        },
        "required": ["signal_name", "pos_length_mm", "neg_length_mm"],
    },
)


@register(_DIFFPAIR_SKEW_SPEC, write=False)
async def electronics_check_diffpair_skew(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = check_diffpair_skew_from_dict(d)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# TOOLS export (consumed by plugin._register_tools)
# ---------------------------------------------------------------------------

TOOLS = [
    (
        _DIFFPAIR_SKEW_SPEC.name,
        _DIFFPAIR_SKEW_SPEC,
        electronics_check_diffpair_skew,
    ),
]
