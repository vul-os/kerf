"""
kerf_mold.color_concentrate_ratio_tool — LLM tool wrapper for color concentrate dosing.

Tool: mold_compute_color_concentrate_ratio
  Given a part shot weight, desired pigment loading, and masterbatch
  specification, computes the gravimetric let-down ratio, masterbatch mass
  per shot, masterbatch mass per kg of natural resin, a heuristic mixing-index
  estimate, and a color-streaking risk rating.

References:
  SPI (Society of the Plastics Industry) "Color Concentrates Handbook" 3rd ed.
    §3 (let-down ratio), §6 (mixing / dispersion quality), §8 (streaking /
    mottling troubleshooting), §11 (cost optimisation).
  Menges G., Kemper B., Klenk E. "Plastics Manufacturing" §10 (masterbatch
    dosing, colour mixing, processing additives).
  Tadmor Z. & Gogos C. "Principles of Polymer Processing" 2nd ed. Wiley 2006,
    §12.5 (distributive/dispersive mixing in single-screw extruders).
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.color_concentrate_ratio import (
    ColorConcentrateSpec,
    ShotSpec,
    compute_color_ratio,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_compute_color_concentrate_ratio_spec = ToolSpec(
    name="mold_compute_color_concentrate_ratio",
    description=(
        "Compute the gravimetric let-down ratio (LDR) and dosing parameters for "
        "a color concentrate (masterbatch) in injection moulding.  Returns:\n"
        "  • let_down_ratio_pct  — LDR = target_pigment_pct / masterbatch_pigment_pct × 100\n"
        "  • masterbatch_per_shot_g  — grams of masterbatch to add per shot\n"
        "  • masterbatch_per_kg_natural  — g MB per kg of natural (uncoloured) resin\n"
        "  • mixing_index_estimate  — heuristic [0–1] from barrel residence + L/D\n"
        "  • color_streaking_risk  — 'low' | 'moderate' | 'high'\n"
        "  • warnings  — advisory list\n\n"
        "LDR formula (SPI Color Concentrates Handbook 3rd ed. §3):\n"
        "  LDR (%) = target_pigment_loading_pct / pigment_loading_in_masterbatch_pct × 100\n"
        "  SPI recommended range: 1–5 %.\n"
        "  LDR < 0.5 % → HIGH streaking risk (concentration too low for shot-to-shot "
        "uniformity).\n"
        "  LDR > 8 % → HIGH streaking risk + cost waste (excess carrier dilutes "
        "mechanical properties, Menges Plastics Manufacturing §10.4).\n\n"
        "Mixing index (Menges §10.2; Tadmor & Gogos §12.5 proxy):\n"
        "  mixing_index = 1 − exp(−barrel_residence_time_s × screw_L_over_D / 200)\n"
        "  Values > 0.80 are adequate for standard masterbatches.\n\n"
        "Streaking-risk rules:\n"
        "  low      : LDR 1–5 % AND mixing_index > 0.80\n"
        "  moderate : LDR 0.5–1 % or 5–8 %, or mixing_index ≤ 0.80 with LDR 1–5 %\n"
        "  high     : LDR < 0.5 % or LDR > 8 %\n\n"
        "Inputs:\n"
        "  pigment_loading_in_masterbatch_pct  — pigment wt % in the masterbatch "
        "(e.g. 40 for 40 g pigment per 100 g masterbatch)\n"
        "  recommended_let_down_pct            — supplier-stated recommended LDR [%]\n"
        "  carrier_resin                       — carrier polymer (e.g. 'PP', 'LDPE', 'ABS')\n"
        "  melting_temp_C                      — masterbatch processing temperature [°C]\n"
        "  shot_weight_g                       — total shot weight [g] (part + runner + sprue)\n"
        "  target_pigment_loading_pct          — desired pigment in finished part [%]\n"
        "  barrel_residence_time_s             — melt residence time in barrel [s]\n"
        "  screw_L_over_D                      — screw L/D ratio (default 20.0)\n\n"
        "HONEST: Mixing index is a heuristic proxy — NOT a rigorous dispersive-mixing "
        "model; does not model screw geometry, back-pressure, melt-viscosity mismatch, "
        "pellet size ratio, or colorant particle size. Trial shots with L*a*b* "
        "colorimetric measurement (ISO 11664-4) are the only reliable acceptance test."
    ),
    input_schema={
        "type": "object",
        "required": [
            "pigment_loading_in_masterbatch_pct",
            "recommended_let_down_pct",
            "carrier_resin",
            "melting_temp_C",
            "shot_weight_g",
            "target_pigment_loading_pct",
            "barrel_residence_time_s",
        ],
        "properties": {
            "pigment_loading_in_masterbatch_pct": {
                "type": "number",
                "description": (
                    "Mass fraction of pigment in the masterbatch, in percent. "
                    "Example: 40 means 40 g pigment per 100 g masterbatch. "
                    "Typical range: 20–50 %. Must be in (0, 100)."
                ),
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 100,
            },
            "recommended_let_down_pct": {
                "type": "number",
                "description": (
                    "Supplier-stated recommended let-down ratio [%]. "
                    "Kerf uses this to check whether the computed LDR matches "
                    "the supplier specification. Typical range: 1–5 %."
                ),
                "exclusiveMinimum": 0,
            },
            "carrier_resin": {
                "type": "string",
                "description": (
                    "Carrier polymer of the masterbatch (e.g. 'PP', 'LDPE', "
                    "'ABS', 'universal'). Used to flag compatibility issues."
                ),
            },
            "melting_temp_C": {
                "type": "number",
                "description": (
                    "Processing temperature of the masterbatch carrier [°C]. "
                    "Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "shot_weight_g": {
                "type": "number",
                "description": (
                    "Total shot weight (part + runner + sprue) [g]. Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "target_pigment_loading_pct": {
                "type": "number",
                "description": (
                    "Desired pigment mass fraction in the final moulded part [%]. "
                    "Example: 1.0 means 1 g pigment per 100 g part. Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "barrel_residence_time_s": {
                "type": "number",
                "description": (
                    "Estimated barrel residence time (melt dwell from melting to "
                    "injection) [s]. Typical range: 5–120 s. Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "screw_L_over_D": {
                "type": "number",
                "description": (
                    "Screw length-to-diameter ratio (L/D). Higher L/D → more "
                    "mixing flights → better distributive mixing. Default: 20.0."
                ),
                "default": 20.0,
                "exclusiveMinimum": 0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_compute_color_concentrate_ratio(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute color concentrate ratio computation and return a JSON string."""
    try:
        pigment_mb = args.get("pigment_loading_in_masterbatch_pct")
        rec_ldr = args.get("recommended_let_down_pct")
        carrier = args.get("carrier_resin")
        melt_temp = args.get("melting_temp_C")
        shot_w = args.get("shot_weight_g")
        target_pct = args.get("target_pigment_loading_pct")
        residence = args.get("barrel_residence_time_s")
        l_over_d = args.get("screw_L_over_D", 20.0)

        # Required field validation
        required = {
            "pigment_loading_in_masterbatch_pct": pigment_mb,
            "recommended_let_down_pct": rec_ldr,
            "carrier_resin": carrier,
            "melting_temp_C": melt_temp,
            "shot_weight_g": shot_w,
            "target_pigment_loading_pct": target_pct,
            "barrel_residence_time_s": residence,
        }
        for name, val in required.items():
            if val is None:
                return err_payload(f"{name} is required", "BAD_ARGS")

        # Numeric coercions
        try:
            pigment_mb = float(pigment_mb)
        except (TypeError, ValueError):
            return err_payload(
                f"pigment_loading_in_masterbatch_pct must be a number, got {pigment_mb!r}",
                "BAD_ARGS",
            )
        try:
            rec_ldr = float(rec_ldr)
        except (TypeError, ValueError):
            return err_payload(
                f"recommended_let_down_pct must be a number, got {rec_ldr!r}",
                "BAD_ARGS",
            )
        try:
            melt_temp = float(melt_temp)
        except (TypeError, ValueError):
            return err_payload(
                f"melting_temp_C must be a number, got {melt_temp!r}", "BAD_ARGS"
            )
        try:
            shot_w = float(shot_w)
        except (TypeError, ValueError):
            return err_payload(
                f"shot_weight_g must be a number, got {shot_w!r}", "BAD_ARGS"
            )
        try:
            target_pct = float(target_pct)
        except (TypeError, ValueError):
            return err_payload(
                f"target_pigment_loading_pct must be a number, got {target_pct!r}",
                "BAD_ARGS",
            )
        try:
            residence = float(residence)
        except (TypeError, ValueError):
            return err_payload(
                f"barrel_residence_time_s must be a number, got {residence!r}",
                "BAD_ARGS",
            )
        try:
            l_over_d = float(l_over_d)
        except (TypeError, ValueError):
            return err_payload(
                f"screw_L_over_D must be a number, got {l_over_d!r}", "BAD_ARGS"
            )

        concentrate = ColorConcentrateSpec(
            pigment_loading_in_masterbatch_pct=pigment_mb,
            recommended_let_down_pct=rec_ldr,
            carrier_resin=str(carrier),
            melting_temp_C=melt_temp,
        )
        shot = ShotSpec(
            shot_weight_g=shot_w,
            target_pigment_loading_pct=target_pct,
            barrel_residence_time_s=residence,
            screw_L_over_D=l_over_d,
        )

        report = compute_color_ratio(concentrate, shot)

        payload: dict[str, Any] = {
            "ok": True,
            "let_down_ratio_pct": report.let_down_ratio_pct,
            "masterbatch_per_shot_g": report.masterbatch_per_shot_g,
            "masterbatch_per_kg_natural": report.masterbatch_per_kg_natural,
            "mixing_index_estimate": report.mixing_index_estimate,
            "color_streaking_risk": report.color_streaking_risk,
            "warnings": report.warnings,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "SPI Color Concentrates Handbook 3rd ed. §3 (LDR), §6 (mixing), "
                "§8 (streaking troubleshooting), §11 (cost); "
                "Menges G., Kemper B., Klenk E. Plastics Manufacturing §10; "
                "Tadmor Z. & Gogos C. Principles of Polymer Processing 2nd ed. §12.5."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "COLOR_CONCENTRATE_ERROR")
