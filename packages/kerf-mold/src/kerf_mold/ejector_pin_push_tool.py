"""
kerf_mold.ejector_pin_push_tool — LLM tool wrapper for ejector pin push-force check.

Tool: mold_compute_ejector_pin_push
  Given a pin diameter, free length, material, and end condition, compute the
  Euler critical buckling load (SPI/ANSI B151.1 + Roark's 9e §15.2) and
  compare it against the required push force to determine whether the pin will
  buckle under the ejection load.

References:
  SPI/ANSI B151.1 — Ejector pin dimensional standards and load-capacity guidance.
  Roark R.J. & Young W.C. (2020). *Formulas for Stress and Strain*, 9th ed.,
    §15.2 (Euler columns), §15.3 (beam-column interaction).
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.ejector_pin_push import (
    EjectorPinPushSpec,
    compute_ejector_pin_push,
    SPI_EJECTOR_PIN_DIAMETERS_MM,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_compute_ejector_pin_push_spec = ToolSpec(
    name="mold_compute_ejector_pin_push",
    description=(
        "Compute the buckling-limited axial push force for an SPI-standard ejector "
        "pin using the Euler critical-load formula (SPI/ANSI B151.1 + Roark's 9e §15.2):\n\n"
        "  F_cr = π² · E · I / (K · L)²\n\n"
        "where:\n"
        "  E = 200 GPa (all supported tool-steel grades — M2, H13, S7, D2)\n"
        "  I = π·d⁴/64  [second moment of area for a solid round section]\n"
        "  K = end-condition coefficient\n"
        "      1.0 = pinned-pinned (SPI/ANSI B151.1 design default for guided pins)\n"
        "      0.7 = fixed-pinned  (rear end clamped, tip guided)\n"
        "      0.5 = fixed-fixed   (both ends fully clamped — rare)\n"
        "      2.0 = cantilever    (one free end — never use for ejector pins)\n"
        "  L = free (unsupported) pin length [mm]\n\n"
        "Returns:\n"
        "  buckling_force_N         — Euler critical load F_cr [N]\n"
        "  dcr                      — demand/capacity ratio = required_force / F_cr\n"
        "  adequate                 — True if dcr ≤ 1.0 (pin will not buckle)\n"
        "  recommended_min_diameter_mm — smallest SPI-standard diameter with\n"
        "                               F_cr ≥ 1.1 × required_push_force_N\n"
        "  recommended_pin_material — M2_tool_steel for high-load cases\n"
        "  honest_caveat            — Euler vs Johnson regime, bushing friction,\n"
        "                             short-column warning, fatigue advisory\n\n"
        "Inputs:\n"
        "  pin_diameter_mm      — pin shank diameter [mm] (> 0)\n"
        "  pin_length_L_mm      — free length between guides [mm] (> 0)\n"
        "  pin_material         — \"M2_tool_steel\"|\"H13\"|\"S7\"|\"D2\"\n"
        "  end_condition_K      — 1.0 pinned-pinned (default), 0.5 fixed-fixed,\n"
        "                         0.7 fixed-pinned, 2.0 cantilever\n"
        "  required_push_force_N — force the pin must transmit [N] (≥ 0)\n\n"
        "SPI standard diameters available: 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 16, 20 mm.\n\n"
        "Honest caveats: Euler formula is non-conservative for short/stout pins "
        "(K·L/d < 30); use Johnson parabolic formula in that regime. Bushing friction "
        "and eccentricity effects are NOT modelled. Dynamic impact and fatigue are "
        "NOT assessed."
    ),
    input_schema={
        "type": "object",
        "required": [
            "pin_diameter_mm",
            "pin_length_L_mm",
            "pin_material",
            "required_push_force_N",
        ],
        "properties": {
            "pin_diameter_mm": {
                "type": "number",
                "description": (
                    "Pin shank diameter [mm]. Must be > 0. "
                    "SPI/ANSI B151.1 standard sizes: 1, 1.5, 2, 2.5, 3, 4, 5, 6, "
                    "8, 10, 12, 16, 20 mm."
                ),
                "exclusiveMinimum": 0,
            },
            "pin_length_L_mm": {
                "type": "number",
                "description": (
                    "Free (unsupported) pin length between the guide bushing "
                    "and the ejector plate [mm]. Must be > 0. "
                    "Typical range: 50–300 mm."
                ),
                "exclusiveMinimum": 0,
            },
            "pin_material": {
                "type": "string",
                "description": (
                    "Pin material grade. All grades use E = 200 GPa. "
                    "M2_tool_steel — primary grade, HRC 60–62, highest wear resistance. "
                    "H13 — hot-work grade, HRC 48–52, good thermal shock resistance. "
                    "S7 — shock-resistant grade, HRC 54–56. "
                    "D2 — cold-work grade, HRC 58–60."
                ),
                "enum": ["M2_tool_steel", "H13", "S7", "D2"],
            },
            "end_condition_K": {
                "type": "number",
                "description": (
                    "Effective-length (end-condition) coefficient K. "
                    "K=1.0 pinned-pinned (SPI/ANSI B151.1 default — guided pin); "
                    "K=0.7 fixed-pinned (clamped rear, guided tip); "
                    "K=0.5 fixed-fixed (both ends clamped — rare); "
                    "K=2.0 cantilever (one free end). "
                    "Default 1.0."
                ),
                "exclusiveMinimum": 0,
                "default": 1.0,
            },
            "required_push_force_N": {
                "type": "number",
                "description": (
                    "Axial push force the pin must transmit [N]. "
                    "Typically = total ejection force / number of ejector pins. "
                    "Must be ≥ 0. Set to 0 to characterise buckling capacity only."
                ),
                "minimum": 0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_compute_ejector_pin_push(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute ejector pin push-force check and return a JSON string."""
    try:
        pin_diameter_mm = args.get("pin_diameter_mm")
        pin_length_L_mm = args.get("pin_length_L_mm")
        pin_material = args.get("pin_material")
        end_condition_K = args.get("end_condition_K", 1.0)
        required_push_force_N = args.get("required_push_force_N")

        # Validate required args
        if pin_diameter_mm is None:
            return err_payload("pin_diameter_mm is required", "BAD_ARGS")
        if pin_length_L_mm is None:
            return err_payload("pin_length_L_mm is required", "BAD_ARGS")
        if pin_material is None:
            return err_payload("pin_material is required", "BAD_ARGS")
        if required_push_force_N is None:
            return err_payload("required_push_force_N is required", "BAD_ARGS")

        try:
            pin_diameter_mm = float(pin_diameter_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"pin_diameter_mm must be a number, got {pin_diameter_mm!r}",
                "BAD_ARGS",
            )
        try:
            pin_length_L_mm = float(pin_length_L_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"pin_length_L_mm must be a number, got {pin_length_L_mm!r}",
                "BAD_ARGS",
            )
        try:
            end_condition_K = float(end_condition_K)
        except (TypeError, ValueError):
            return err_payload(
                f"end_condition_K must be a number, got {end_condition_K!r}",
                "BAD_ARGS",
            )
        try:
            required_push_force_N = float(required_push_force_N)
        except (TypeError, ValueError):
            return err_payload(
                f"required_push_force_N must be a number, got {required_push_force_N!r}",
                "BAD_ARGS",
            )

        spec = EjectorPinPushSpec(
            pin_diameter_mm=pin_diameter_mm,
            pin_length_L_mm=pin_length_L_mm,
            pin_material=str(pin_material),
            end_condition_K=end_condition_K,
            required_push_force_N=required_push_force_N,
        )

        report = compute_ejector_pin_push(spec)

        payload: dict[str, Any] = {
            "ok": True,
            "buckling_force_N": report.buckling_force_N,
            "dcr": report.dcr,
            "adequate": report.adequate,
            "recommended_min_diameter_mm": report.recommended_min_diameter_mm,
            "recommended_pin_material": report.recommended_pin_material,
            "honest_caveat": report.honest_caveat,
            "spi_standard_diameters_mm": list(SPI_EJECTOR_PIN_DIAMETERS_MM),
            "reference": (
                "SPI/ANSI B151.1 ejector pin standards; "
                "Roark R.J. & Young W.C. Formulas for Stress and Strain, 9th ed., "
                "§15.2 (Euler columns), §15.3 (beam-column interaction)."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "EJECTOR_PIN_PUSH_ERROR")
