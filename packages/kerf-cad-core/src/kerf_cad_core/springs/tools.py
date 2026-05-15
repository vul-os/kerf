"""
kerf_cad_core.springs.tools — LLM tool wrappers for mechanical spring design.

Registers four tools with the Kerf tool registry:

  spring_compression    — helical compression spring (rate, solid height, buckling,
                          Wahl factor, shear stress, Goodman fatigue check)
  spring_extension      — helical extension spring (rate, initial tension, hook stress)
  spring_torsion        — helical torsion spring (angular rate, bending stress)
  spring_belleville     — Belleville disc spring (Almen-László load-deflection + stress)

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Shigley's Mechanical Engineering Design, 10th ed., Chapter 10
Wahl, A.M. "Mechanical Springs", 2nd ed. (1963)
Almen & László, Trans. ASME 58 (1936) p. 305

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.springs.design import (
    helical_compression,
    helical_compression_with_free_length,
    helical_extension,
    torsion_spring,
    belleville_washer,
)


# ---------------------------------------------------------------------------
# Tool: spring_compression
# ---------------------------------------------------------------------------

_spring_compression_spec = ToolSpec(
    name="spring_compression",
    description=(
        "Design a helical compression spring.\n"
        "\n"
        "Computes:\n"
        "  - Spring rate:           k = G d⁴ / (8 D³ N)  [N/m]\n"
        "  - Spring index C = D/d and Wahl correction factor Kw\n"
        "  - Solid height Ls (depends on end_type)\n"
        "  - Slenderness λ = L_free / D and buckling-risk flag "
        "(when free_length_m is supplied)\n"
        "  - Peak shear stress τ = Kw × 8 F D / (π d³) "
        "(when Fa or Fm supplied)\n"
        "  - Goodman fatigue ratio τa/Sse + τm/Ssu "
        "(when Sut, Se, Fa, Fm supplied)\n"
        "\n"
        "Returns warnings list; flags over-stress and buckling risk.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "d": {
                "type": "number",
                "description": "Wire diameter (m). Must be > 0.",
            },
            "D": {
                "type": "number",
                "description": "Mean coil diameter (m). Must be > 0.",
            },
            "N": {
                "type": "number",
                "description": "Number of active coils. Must be > 0.",
            },
            "G": {
                "type": "number",
                "description": (
                    "Shear modulus (Pa). Must be > 0. "
                    "Steel ≈ 79.3e9 Pa."
                ),
            },
            "Sut": {
                "type": "number",
                "description": (
                    "Tensile strength (Pa). Required for Goodman fatigue check. "
                    "Pass 0 to skip."
                ),
            },
            "Se": {
                "type": "number",
                "description": (
                    "Shear endurance limit (Pa). Required for Goodman check. "
                    "Pass 0 to skip."
                ),
            },
            "Fa": {
                "type": "number",
                "description": "Alternating force amplitude (N). Must be >= 0.",
            },
            "Fm": {
                "type": "number",
                "description": "Mean force (N). Must be >= 0.",
            },
            "end_type": {
                "type": "string",
                "enum": ["plain", "plain_ground", "squared", "squared_ground"],
                "description": (
                    "End condition: 'squared_ground' (default), 'squared', "
                    "'plain_ground', or 'plain'."
                ),
            },
            "free_length_m": {
                "type": "number",
                "description": (
                    "Free (unloaded) spring length (m). If provided, slenderness "
                    "λ = L_free/D is computed and buckling risk is flagged for λ > 4."
                ),
            },
            "set_removed": {
                "type": "boolean",
                "description": (
                    "True if the spring has been preset (shot-peened / set removed). "
                    "Default false. Noted in warnings."
                ),
            },
        },
        "required": ["d", "D", "N", "G"],
    },
)


@register(_spring_compression_spec, write=False)
async def run_spring_compression(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("d", "D", "N", "G"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("E", "Sut", "Se", "Fa", "Fm", "end_type", "set_removed"):
        if opt in a:
            kwargs[opt] = a[opt]

    free_length = a.get("free_length_m")
    if free_length is not None:
        result = helical_compression_with_free_length(
            a["d"], a["D"], a["N"], a["G"], free_length, **kwargs
        )
    else:
        result = helical_compression(a["d"], a["D"], a["N"], a["G"], **kwargs)

    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spring_extension
# ---------------------------------------------------------------------------

_spring_extension_spec = ToolSpec(
    name="spring_extension",
    description=(
        "Design a helical extension spring.\n"
        "\n"
        "Computes:\n"
        "  - Spring rate: k = G d⁴ / (8 D³ N)  [N/m]\n"
        "  - Spring index C and Wahl shear stress factor Kw\n"
        "  - Hook bending stress concentration KB = (4C²−C−1)/(4C(C−1))\n"
        "  - Shear stress in coil body at max force\n"
        "  - Hook bending stress: σ = KB × 16 F D / (π d³)\n"
        "  - Goodman fatigue ratio (when Sut, Se, Fa, Fm supplied)\n"
        "\n"
        "Warns if initial_tension exceeds mean force (spring may not open).\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "d": {
                "type": "number",
                "description": "Wire diameter (m). Must be > 0.",
            },
            "D": {
                "type": "number",
                "description": "Mean coil diameter (m). Must be > 0.",
            },
            "N": {
                "type": "number",
                "description": "Number of active coils. Must be > 0.",
            },
            "G": {
                "type": "number",
                "description": "Shear modulus (Pa). Must be > 0. Steel ≈ 79.3e9 Pa.",
            },
            "Sut": {
                "type": "number",
                "description": "Tensile strength (Pa). 0 to skip Goodman check.",
            },
            "Se": {
                "type": "number",
                "description": "Shear endurance limit (Pa). 0 to skip Goodman check.",
            },
            "Fa": {
                "type": "number",
                "description": "Alternating force amplitude (N). Must be >= 0.",
            },
            "Fm": {
                "type": "number",
                "description": "Mean force (N). Must be >= 0.",
            },
            "initial_tension_N": {
                "type": "number",
                "description": (
                    "Initial tension built into closed coils (N). Must be >= 0. "
                    "Spring does not extend until applied force > initial_tension."
                ),
            },
        },
        "required": ["d", "D", "N", "G"],
    },
)


@register(_spring_extension_spec, write=False)
async def run_spring_extension(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("d", "D", "N", "G"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("Sut", "Se", "Fa", "Fm", "initial_tension_N"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = helical_extension(a["d"], a["D"], a["N"], a["G"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spring_torsion
# ---------------------------------------------------------------------------

_spring_torsion_spec = ToolSpec(
    name="spring_torsion",
    description=(
        "Design a helical torsion spring.\n"
        "\n"
        "Primary stress is bending (not torsion) along the coil wire.\n"
        "\n"
        "Computes:\n"
        "  - Angular rate: k = E d⁴ / (64 D N)   [N·m/rev]\n"
        "  - Angular rate in N·m/rad\n"
        "  - Inner-fiber curvature correction Ki = (4C²−C−1)/(4C(C−1))\n"
        "  - Bending stress: σ = Ki × 32 T / (π d³)  (when torque supplied)\n"
        "  - Torque from angular deflection (when angular_deflection_deg supplied)\n"
        "\n"
        "Warns on inconsistency between supplied torque and deflection.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "d": {
                "type": "number",
                "description": "Wire diameter (m). Must be > 0.",
            },
            "D": {
                "type": "number",
                "description": "Mean coil diameter (m). Must be > 0.",
            },
            "N": {
                "type": "number",
                "description": "Number of active coils. Must be > 0.",
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa). Must be > 0. Steel ≈ 200e9 Pa.",
            },
            "torque_Nm": {
                "type": "number",
                "description": "Applied torque (N·m). Must be >= 0.",
            },
            "angular_deflection_deg": {
                "type": "number",
                "description": "Angular deflection (degrees). Must be >= 0.",
            },
        },
        "required": ["d", "D", "N", "E"],
    },
)


@register(_spring_torsion_spec, write=False)
async def run_spring_torsion(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("d", "D", "N", "E"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("torque_Nm", "angular_deflection_deg"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = torsion_spring(a["d"], a["D"], a["N"], a["E"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: spring_belleville
# ---------------------------------------------------------------------------

_spring_belleville_spec = ToolSpec(
    name="spring_belleville",
    description=(
        "Design a Belleville (disc) spring per Almen-László theory.\n"
        "\n"
        "Computes:\n"
        "  - Load to flatten disc: P(δ=h0) via Almen-László eq.\n"
        "  - Stress at inner edge at δ=h0/2 (largest compressive stress)\n"
        "  - Load at a specified deflection delta_target\n"
        "  - Deflection at a specified load P_target (bisection)\n"
        "  - Geometric constants α, β\n"
        "\n"
        "Warns on snap-through risk (h0/t > 1.5) and out-of-range P_target.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "De": {
                "type": "number",
                "description": "Outer diameter (m). Must be > 0.",
            },
            "Di": {
                "type": "number",
                "description": "Inner diameter (m). Must be > 0 and < De.",
            },
            "t": {
                "type": "number",
                "description": "Disc thickness (m). Must be > 0.",
            },
            "h0": {
                "type": "number",
                "description": (
                    "Free cone height (m): axial height before disc is flat. "
                    "Must be > 0.  Optimal fatigue: h0/t ∈ [0.4, 0.75]."
                ),
            },
            "E": {
                "type": "number",
                "description": "Young's modulus (Pa). Must be > 0. Steel ≈ 200e9 Pa.",
            },
            "nu": {
                "type": "number",
                "description": "Poisson's ratio. Must be in (0, 0.5]. Steel ≈ 0.3.",
            },
            "P_target": {
                "type": "number",
                "description": (
                    "Optional: find deflection at this load (N). "
                    "Returns delta_at_P_target_m."
                ),
            },
            "delta_target": {
                "type": "number",
                "description": (
                    "Optional: find load at this deflection (m). "
                    "Returns P_at_delta_target_N."
                ),
            },
        },
        "required": ["De", "Di", "t", "h0", "E", "nu"],
    },
)


@register(_spring_belleville_spec, write=False)
async def run_spring_belleville(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("De", "Di", "t", "h0", "E", "nu"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("P_target", "delta_target"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = belleville_washer(
        a["De"], a["Di"], a["t"], a["h0"], a["E"], a["nu"], **kwargs
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)
