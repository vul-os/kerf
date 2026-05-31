"""
kerf_mold.surface_finish_check_tool — LLM tool wrapper for SPI surface finish check.

Tool: mold_check_surface_finish
  Given a part's required SPI cosmetic surface finish grade (A1–D3) and resin,
  validates that the mold steel + hardness combination can achieve it; recommends
  steel grade, minimum HRC, and polishing method.

References:
  SPI/PLASTICS "Mold Finish Standards" 2017 edition — A1–D3 Ra bands and
    polishing methods.
  Menges G., Mohren P. "How to Make Injection Molds" 3rd ed. Hanser 2001,
    §11 — surface finish practice, glass-fiber print-through, resin-steel
    compatibility.
  Bryce D. M. "Plastic Injection Molding: Mold Design and Construction
    Fundamentals", SME 1998, Ch. 8.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.surface_finish_check import (
    SurfaceFinishSpec,
    MoldSpec,
    check_surface_finish,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_check_surface_finish_spec = ToolSpec(
    name="mold_check_surface_finish",
    description=(
        "Validate that a molded part's resin + mold-steel + hardness combination "
        "can achieve the requested SPI Mold Finish Standard grade, and recommend "
        "mold steel grade, minimum Rockwell hardness (HRC), and polishing method.\n\n"
        "SPI Finish Grades (2017 standard):\n"
        "  SPI-A1  Ra ≤ 0.012 µm  mirror / optical; diamond paste #3 on S136 ≥50 HRC\n"
        "  SPI-A2  Ra ≤ 0.025 µm  mirror; diamond buff #6 on S136/H13 ≥48 HRC\n"
        "  SPI-A3  Ra ≤ 0.050 µm  high gloss; diamond buff #15 on S136/H13 ≥44 HRC\n"
        "  SPI-B1  Ra ≤ 0.10 µm   semi-gloss; 600-grit stone on H13/P20 ≥38 HRC\n"
        "  SPI-B2  Ra ≤ 0.20 µm   semi-gloss; 400-grit stone on H13/P20 ≥32 HRC\n"
        "  SPI-B3  Ra ≤ 0.40 µm   low gloss; 320-grit stone on P20 ≥28 HRC\n"
        "  SPI-C1  Ra ≤ 0.80 µm   matte; 400-grit emery on P20 ≥28 HRC\n"
        "  SPI-C2  Ra ≤ 1.60 µm   matte; 320-grit emery on P20 ≥28 HRC\n"
        "  SPI-C3  Ra ≤ 3.20 µm   matte; 220-grit emery on P20 ≥20 HRC\n"
        "  SPI-D1  Ra ~ 3.2 µm    textured; dry blast #11 glass bead\n"
        "  SPI-D2  Ra ~ 6.4 µm    textured; dry blast #240 oxide\n"
        "  SPI-D3  Ra ~ 14.0 µm   industrial; dry blast #24 oxide\n\n"
        "Glass-fiber rule (Menges §11.4.2): glass-filled resins (≥10 wt% GF) "
        "produce fiber pull-out and print-through at the part surface — A-grade "
        "(A1/A2/A3) is NOT achievable on the molded part regardless of mold polish.\n\n"
        "Returns: achievable (bool), recommended_steel, recommended_hardness_HRC_min, "
        "recommended_polishing_method, Ra_target_um, Ra_achievable_um, "
        "glass_filled_warning (null if no GF issue), honest_caveat.\n\n"
        "HONEST: catalog-based checker only — does NOT model texture chemistry, "
        "etcher capability, polishing wear-life, part geometry effects, or process "
        "variables (mold temperature, hold pressure, cooling time)."
    ),
    input_schema={
        "type": "object",
        "required": [
            "required_finish",
            "resin",
            "mold_steel",
            "hardness_HRC",
        ],
        "properties": {
            "required_finish": {
                "type": "string",
                "description": (
                    "Required SPI finish grade, e.g. 'SPI-A1', 'SPI-B2', 'SPI-D3'. "
                    "Valid values: SPI-A1, SPI-A2, SPI-A3, SPI-B1, SPI-B2, SPI-B3, "
                    "SPI-C1, SPI-C2, SPI-C3, SPI-D1, SPI-D2, SPI-D3."
                ),
                "enum": [
                    "SPI-A1", "SPI-A2", "SPI-A3",
                    "SPI-B1", "SPI-B2", "SPI-B3",
                    "SPI-C1", "SPI-C2", "SPI-C3",
                    "SPI-D1", "SPI-D2", "SPI-D3",
                ],
            },
            "resin": {
                "type": "string",
                "description": (
                    "Resin or polymer grade, e.g. 'ABS', 'PC', 'PA66', 'PP', "
                    "'PMMA', 'TPU', 'glass-filled-PA'. Case-insensitive."
                ),
            },
            "mold_steel": {
                "type": "string",
                "description": (
                    "Mold cavity steel grade. Valid values: "
                    "'P20' (pre-hardened, B/C/D grade), "
                    "'H13' (hot-work tool steel, up to A3), "
                    "'S136' (stainless, up to A1), "
                    "'420SS' (corrosion-resistant, up to A2)."
                ),
                "enum": ["P20", "H13", "S136", "420SS"],
            },
            "hardness_HRC": {
                "type": "number",
                "description": (
                    "Actual Rockwell C hardness of the mold cavity steel. "
                    "Typical ranges: P20 28–36; H13 40–52; S136 48–58; 420SS 26–52. "
                    "Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "mold_finish_achieved": {
                "type": "string",
                "description": (
                    "The SPI finish grade already achieved on the mold cavity, "
                    "e.g. 'SPI-A2'. Leave blank if not yet polished or unknown. "
                    "If provided and coarser than required_finish, achievable=false."
                ),
                "default": "",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_check_surface_finish(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute surface finish check and return a JSON string."""
    try:
        req_finish = args.get("required_finish")
        resin = args.get("resin")
        mold_steel = args.get("mold_steel")
        hardness = args.get("hardness_HRC")
        mold_finish_achieved = args.get("mold_finish_achieved", "") or ""

        required = {
            "required_finish": req_finish,
            "resin": resin,
            "mold_steel": mold_steel,
            "hardness_HRC": hardness,
        }
        for name, val in required.items():
            if val is None:
                return err_payload(f"{name} is required", "BAD_ARGS")

        try:
            hardness = float(hardness)
        except (TypeError, ValueError):
            return err_payload(
                f"hardness_HRC must be a number, got {hardness!r}", "BAD_ARGS"
            )

        part = SurfaceFinishSpec(
            required_finish=str(req_finish),
            resin=str(resin),
        )
        mold = MoldSpec(
            mold_steel=str(mold_steel),
            hardness_HRC=hardness,
            mold_finish_achieved=str(mold_finish_achieved),
        )

        report = check_surface_finish(part, mold)

        payload: dict[str, Any] = {
            "ok": True,
            "achievable": report.achievable,
            "recommended_steel": report.recommended_steel,
            "recommended_hardness_HRC_min": report.recommended_hardness_HRC_min,
            "recommended_polishing_method": report.recommended_polishing_method,
            "Ra_target_um": report.Ra_target_um,
            "Ra_achievable_um": report.Ra_achievable_um,
            "glass_filled_warning": report.glass_filled_warning,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "SPI/PLASTICS Mold Finish Standards 2017; "
                "Menges G., Mohren P. How to Make Injection Molds 3rd ed. "
                "Hanser 2001 §11; "
                "Bryce D. M. Plastic Injection Molding: Mold Design and "
                "Construction Fundamentals, SME 1998 Ch. 8."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "SURFACE_FINISH_ERROR")
