"""
LLM tool: electronics_check_fuse_i2t

Fuse I²t (melting energy) verification — IEC 60269 + Cooper Bussmann selection guide.

Given a fuse's pre-arcing I²t rating and a fault current waveform (square-pulse
approximation: peak current + duration), verifies:
  1. Applied I²t vs fuse pre-arcing I²t — does the fuse clear the fault?
  2. Available short-circuit current vs fuse breaking capacity.

TOOLS exported:
  electronics_check_fuse_i2t

All handlers follow the kerf never-raise contract: errors → {"ok": false, ...}.
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.fuse_i2t_check import (
    FuseSpec,
    FaultSpec,
    check_fuse_i2t,
)

# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_FUSE_I2T_SPEC = ToolSpec(
    name="electronics_check_fuse_i2t",
    description=(
        "Verify that a fuse's pre-arcing I²t (melting energy) rating is consistent "
        "with a fault current waveform — does the fuse clear the fault, and is its "
        "breaking capacity adequate?\n\n"
        "Algorithm (square-wave approximation):\n"
        "  applied_I2t = peak_current_A² × (duration_ms / 1000)   [A²·s]\n"
        "  clears_safely       = applied_I2t ≥ fuse_pre_arc_I2t\n"
        "  breaking_cap_ok     = available_SCC_kA ≤ fuse.breaking_capacity_kA\n\n"
        "References:\n"
        "  • IEC 60269-1:2020 — Low-voltage fuses — General requirements\n"
        "  • IEC 60269-2:2013 — Fuses for industrial applications\n"
        "  • Cooper Bussmann 'Selecting Protective Devices' (SPD 2014 ed.) §2–§4\n"
        "  • IEC 60909-0:2016 §11 — Short-circuit asymmetry correction\n\n"
        "Fuse classes:\n"
        "  F  — fast blow (ANSI/UL 248 class F, melts in <1s at 200% rated)\n"
        "  FF — very fast blow (semiconductor protection)\n"
        "  M  — medium / semi-time-delay\n"
        "  T  — slow blow / time-delay (motor + transformer inrush)\n"
        "  gG — IEC general-purpose full-range (cable protection)\n"
        "  aR — IEC back-up current-limiting (semiconductor / motor protection)\n\n"
        "Honest caveats:\n"
        "  • Square-wave fault current only — sinusoidal AC or exponentially decaying "
        "DC NOT modelled; for AC apply I_rms² × t with IEC 60909 asymmetry correction.\n"
        "  • Arcing I²t NOT included in applied I²t — total clearing I²t is higher; "
        "downstream equipment rating must account for the arcing phase.\n"
        "  • Pre-arcing I²t is the 25°C rated value; derate for higher ambient per "
        "manufacturer temperature correction curve.\n"
        "  • Fuse co-ordination (selectivity between series fuses) is NOT checked.\n\n"
        "Input: { nominal_current_A, voltage_rating_V, I_squared_t_pre_arc_A2_s, "
        "breaking_capacity_kA, fuse_class, peak_current_A, duration_ms, "
        "available_short_circuit_current_kA }\n"
        "Returns: { ok, applied_I2t_A2s, fuse_pre_arc_I2t_A2s, ratio_pct, "
        "clears_safely, breaking_capacity_adequate, recommended_fuse_class, "
        "honest_caveat }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nominal_current_A": {
                "type": "number",
                "description": "Fuse nominal (rated) current [A], e.g. 5, 10, 16, 32.",
            },
            "voltage_rating_V": {
                "type": "number",
                "description": "Fuse maximum voltage rating [V], e.g. 250, 400, 690.",
            },
            "I_squared_t_pre_arc_A2_s": {
                "type": "number",
                "description": (
                    "Fuse pre-arcing I²t rating [A²·s] from the manufacturer datasheet "
                    "(IEC 60269-1 Table II).  Example: a 5 A gG fuse may have ~10 A²·s; "
                    "a 32 A gG fuse ~800 A²·s."
                ),
            },
            "breaking_capacity_kA": {
                "type": "number",
                "description": (
                    "Maximum prospective short-circuit current the fuse can safely "
                    "interrupt [kA rms symmetrical].  Common values: 1.5, 6, 10, 16, "
                    "20, 50, 100, 200 kA."
                ),
            },
            "fuse_class": {
                "type": "string",
                "enum": ["F", "M", "T", "FF", "gG", "aR"],
                "description": (
                    "Fuse utilisation class per IEC 60269-1 / ANSI UL 248: "
                    "F=fast, M=medium, T=slow/time-delay, FF=very fast, "
                    "gG=IEC general-purpose, aR=IEC back-up semiconductor."
                ),
            },
            "peak_current_A": {
                "type": "number",
                "description": (
                    "Peak fault current amplitude [A] (or RMS for a rectangular "
                    "approximation).  Applied I²t = peak_current_A² × (duration_ms/1000)."
                ),
            },
            "duration_ms": {
                "type": "number",
                "description": (
                    "Duration of the fault current pulse [ms].  Must be > 0. "
                    "Example: 1 ms for a very fast short-circuit, 100 ms for "
                    "a sustained overload event."
                ),
            },
            "available_short_circuit_current_kA": {
                "type": "number",
                "description": (
                    "Maximum prospective short-circuit current available at the fuse "
                    "installation point [kA rms symmetrical].  Must not exceed the "
                    "fuse's breaking_capacity_kA for safe operation."
                ),
            },
        },
        "required": [
            "nominal_current_A",
            "voltage_rating_V",
            "I_squared_t_pre_arc_A2_s",
            "breaking_capacity_kA",
            "fuse_class",
            "peak_current_A",
            "duration_ms",
            "available_short_circuit_current_kA",
        ],
    },
)


@register(_FUSE_I2T_SPEC, write=False)
async def electronics_check_fuse_i2t(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        fuse = FuseSpec(
            nominal_current_A=float(a["nominal_current_A"]),
            voltage_rating_V=float(a["voltage_rating_V"]),
            I_squared_t_pre_arc_A2_s=float(a["I_squared_t_pre_arc_A2_s"]),
            breaking_capacity_kA=float(a["breaking_capacity_kA"]),
            fuse_class=str(a["fuse_class"]),
        )
        fault = FaultSpec(
            peak_current_A=float(a["peak_current_A"]),
            duration_ms=float(a["duration_ms"]),
            available_short_circuit_current_kA=float(
                a["available_short_circuit_current_kA"]
            ),
        )
        report = check_fuse_i2t(fuse, fault)
    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"internal error: {exc}", "INTERNAL")

    return ok_payload({
        "ok": True,
        "applied_I2t_A2s": report.applied_I2t_A2s,
        "fuse_pre_arc_I2t_A2s": report.fuse_pre_arc_I2t_A2s,
        "ratio_pct": report.ratio_pct,
        "clears_safely": report.clears_safely,
        "breaking_capacity_adequate": report.breaking_capacity_adequate,
        "recommended_fuse_class": report.recommended_fuse_class,
        "honest_caveat": report.honest_caveat,
    })


# ---------------------------------------------------------------------------
# TOOLS export — consumed by plugin._register_tools
# ---------------------------------------------------------------------------

TOOLS = [
    (_FUSE_I2T_SPEC.name, _FUSE_I2T_SPEC, electronics_check_fuse_i2t),
]
