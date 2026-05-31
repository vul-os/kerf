"""
kerf_mold.demold_force_check_tool — LLM tool wrapper for demolding force check.

Tool: mold_compute_demold_force
  Given a draft angle, contact surface area, and polymer grade, estimate the
  demolding (ejection) force per cavity using the Beaumont 2007 §9.3 formula
  and verify ejector pin capacity.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §9.3.
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., §7.4 + Table 7.6.
"""

from __future__ import annotations

import math
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.demold_force_check import (
    MoldedPartSpec,
    compute_demold_force,
    SHRINKAGE_STRESS_MPA,
    FRICTION_COEFF,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_compute_demold_force_spec = ToolSpec(
    name="mold_compute_demold_force",
    description=(
        "Estimate the demolding (ejection) force required to eject a molded part "
        "from the cavity, and verify that the ejector pin system has adequate "
        "capacity.\n\n"
        "Uses the Beaumont 2007 §9.3 cavity-ejection formula:\n"
        "  F = μ · σ_h · A_contact · cosα / (cosα + μ · sinα)\n"
        "  equivalently: F = μ · σ_h · A_contact / (1 + μ · tanα)\n\n"
        "where:\n"
        "  μ       — kinetic friction (polymer on mold steel), from finish class\n"
        "  σ_h     — polymer shrinkage contact stress [MPa], from Menges 2001 Table 7.6\n"
        "  A_contact — contact surface area [cm²] (faces that grip the mold)\n"
        "  α       — draft (relief) angle [degrees] — positive draft reduces force\n\n"
        "Shrinkage stress per polymer (Menges 2001 Table 7.6):\n"
        "  ABS=4.0 MPa | PC=3.0 MPa | PP=5.0 MPa | PA66=3.5 MPa | POM=4.5 MPa\n\n"
        "Friction coefficient per SPI finish class:\n"
        "  SPI_A1=0.15 (polished) | SPI_A2=0.18 | SPI_B1=0.25 |\n"
        "  SPI_C1=0.30 | SPI_D1=0.40 (textured)\n\n"
        "Ejector pin count = ceil(F / single_pin_capacity_N).\n\n"
        "Inputs:\n"
        "  polymer_grade              — \"ABS\"|\"PC\"|\"PP\"|\"PA66\"|\"POM\"\n"
        "  contact_area_cm2           — contact surface area [cm²] (> 0)\n"
        "  draft_angle_deg            — draft angle [degrees] (≥ 0)\n"
        "  mold_steel_finish_class    — \"SPI_A1\"|\"SPI_A2\"|\"SPI_B1\"|"
        "\"SPI_C1\"|\"SPI_D1\"\n"
        "  single_pin_capacity_N      — axial capacity of one ejector pin [N] "
        "(default 2500 N)\n\n"
        "Returns: {demold_force_N, contact_pressure_MPa, ejector_pin_count_required,\n"
        "          friction_coeff_used, polymer_shrinkage_stress_MPa, honest_caveat}.\n\n"
        "Honest caveat: empirical formula only. Does NOT model chemical adhesion "
        "(resin stick), undercut geometry, dynamic ejection forces, or cooling "
        "non-uniformity. Confirm by mold-trial load-cell measurement."
    ),
    input_schema={
        "type": "object",
        "required": [
            "polymer_grade",
            "contact_area_cm2",
            "draft_angle_deg",
            "mold_steel_finish_class",
        ],
        "properties": {
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer material grade. One of: "
                    "\"ABS\", \"PC\", \"PP\", \"PA66\", \"POM\"."
                ),
                "enum": ["ABS", "PC", "PP", "PA66", "POM"],
            },
            "contact_area_cm2": {
                "type": "number",
                "description": (
                    "Total contact surface area between part and mold steel [cm²]. "
                    "Typically the core-side / internal faces that grip the mold "
                    "during ejection. Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "draft_angle_deg": {
                "type": "number",
                "description": (
                    "Draft (taper) angle of the mold walls relative to the pull "
                    "direction [degrees]. Typical range: 0.5°–5°. Must be ≥ 0. "
                    "At 0° the formula reduces to F = μ·σ_h·A (maximum force, "
                    "no taper relief)."
                ),
                "minimum": 0,
            },
            "mold_steel_finish_class": {
                "type": "string",
                "description": (
                    "SPI mold finish class, which determines friction coefficient:\n"
                    "  SPI_A1 = 0.15 (diamond-polished, Ra < 0.025 µm)\n"
                    "  SPI_A2 = 0.18 (diamond-polished, Ra 0.025–0.05 µm)\n"
                    "  SPI_B1 = 0.25 (stone-polished, Ra 0.05–0.4 µm)\n"
                    "  SPI_C1 = 0.30 (paper-finish, Ra 0.4–1.6 µm)\n"
                    "  SPI_D1 = 0.40 (EDM/bead-blast, Ra 1.6–12.5 µm)"
                ),
                "enum": ["SPI_A1", "SPI_A2", "SPI_B1", "SPI_C1", "SPI_D1"],
            },
            "single_pin_capacity_N": {
                "type": "number",
                "description": (
                    "Axial load capacity of a single ejector pin [N]. "
                    "Default 2500 N (typical 5 mm diameter H13 pin at 15% yield "
                    "margin per Beaumont 2007 §9.4). Must be > 0."
                ),
                "exclusiveMinimum": 0,
                "default": 2500.0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_compute_demold_force(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute demolding force check and return a JSON string."""
    try:
        polymer_grade = args.get("polymer_grade")
        contact_area_cm2 = args.get("contact_area_cm2")
        draft_angle_deg = args.get("draft_angle_deg")
        mold_steel_finish_class = args.get("mold_steel_finish_class")
        single_pin_capacity_N = args.get("single_pin_capacity_N", 2500.0)

        # Validate required args
        if polymer_grade is None:
            return err_payload("polymer_grade is required", "BAD_ARGS")
        if contact_area_cm2 is None:
            return err_payload("contact_area_cm2 is required", "BAD_ARGS")
        if draft_angle_deg is None:
            return err_payload("draft_angle_deg is required", "BAD_ARGS")
        if mold_steel_finish_class is None:
            return err_payload("mold_steel_finish_class is required", "BAD_ARGS")

        try:
            contact_area_cm2 = float(contact_area_cm2)
        except (TypeError, ValueError):
            return err_payload(
                f"contact_area_cm2 must be a number, got {contact_area_cm2!r}",
                "BAD_ARGS",
            )
        try:
            draft_angle_deg = float(draft_angle_deg)
        except (TypeError, ValueError):
            return err_payload(
                f"draft_angle_deg must be a number, got {draft_angle_deg!r}",
                "BAD_ARGS",
            )
        try:
            single_pin_capacity_N = float(single_pin_capacity_N)
        except (TypeError, ValueError):
            return err_payload(
                f"single_pin_capacity_N must be a number, got {single_pin_capacity_N!r}",
                "BAD_ARGS",
            )

        spec = MoldedPartSpec(
            polymer_grade=str(polymer_grade),
            contact_area_cm2=contact_area_cm2,
            draft_angle_deg=draft_angle_deg,
            mold_steel_finish_class=str(mold_steel_finish_class),
        )

        report = compute_demold_force(spec, single_pin_capacity_N=single_pin_capacity_N)

        payload: dict[str, Any] = {
            "ok": True,
            "demold_force_N": report.demold_force_N,
            "contact_pressure_MPa": report.contact_pressure_MPa,
            "ejector_pin_count_required": report.ejector_pin_count_required,
            "friction_coeff_used": report.friction_coeff_used,
            "polymer_shrinkage_stress_MPa": report.polymer_shrinkage_stress_MPa,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., "
                "Hanser 2007, §9.3; "
                "Menges G., Michaeli W., Mohren P. How to Make Injection Molds, "
                "3rd ed., Hanser 2001, §7.4 + Table 7.6."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "DEMOLD_FORCE_ERROR")
