"""
kerf_mold.ejector_stroke_verify_tool
=====================================
LLM tool wrapper for ejector stroke and pin system verification.

Registers:
  mold_verify_ejector_stroke — verify stroke adequacy, force capacity,
                                pin deflection, and knockout bar contact.

Errors returned as {"ok": false, "reason": "..."} — tool never raises.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", Hanser 2007, §9.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", Hanser 2001,
§7.4.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.ejector_stroke_verify import (
    EjectorPinSpec,
    verify_ejector_stroke,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_verify_ejector_stroke_spec = ToolSpec(
    name="mold_verify_ejector_stroke",
    description=(
        "Verify the ejector stroke and pin system for an injection mold "
        "(Beaumont 2007 §9 + Menges 2001 §7.4). Performs four checks:\n\n"
        "1. **Stroke adequacy** — required_stroke (part_depth + safety_margin) "
        "≤ machine_stroke.\n"
        "2. **Force capacity** — pin_count × force_per_pin_max ≥ ejection_force.\n"
        "3. **Pin deflection** — δ = F·L³/(3·E·I) ≤ allowable (default 0.05 mm).\n"
        "4. **Knockout bar contact** — ejector plate ≥ knockout bar diameter "
        "(if both are supplied).\n\n"
        "Returns: {ok, stroke_adequate, required_stroke_mm, stroke_clearance_mm, "
        "force_adequate, force_per_pin_N, deflection_ok, max_deflection_mm, "
        "knockout_bar_ok, violations, warnings, honest_flag}.\n\n"
        "Honest flag: static load analysis only — does not model dynamic "
        "ejection forces, shrinkage grip, thermal expansion, or pin fatigue."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_depth_mm": {
                "type": "number",
                "description": "Depth of the part in the cavity (mm). Required.",
            },
            "machine_stroke_mm": {
                "type": "number",
                "description": "Machine-rated maximum ejector stroke (mm). Required.",
            },
            "ejection_force_N": {
                "type": "number",
                "description": (
                    "Total required ejection force (N). "
                    "Obtain from mold_plan_ejector_pins result or "
                    "Menges §7.4 Eq. 7-9. Required."
                ),
            },
            "pins": {
                "type": "array",
                "description": (
                    "Ejector pin groups. Each: "
                    "{diameter_mm, free_length_mm, count?}. Required."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "diameter_mm": {"type": "number"},
                        "free_length_mm": {"type": "number"},
                        "count": {"type": "integer", "minimum": 1},
                    },
                    "required": ["diameter_mm", "free_length_mm"],
                },
            },
            "safety_margin_mm": {
                "type": "number",
                "description": "Stroke safety margin above part depth (mm). Default 5.0.",
            },
            "force_per_pin_max_N": {
                "type": "number",
                "description": "Maximum allowable force per pin (N). Default 500.",
            },
            "allowable_deflection_mm": {
                "type": "number",
                "description": (
                    "Allowable tip deflection per pin (mm). "
                    "Default 0.05 (Beaumont 2007 §9.3 Table 9.1)."
                ),
            },
            "steel_E_N_mm2": {
                "type": "number",
                "description": (
                    "Young's modulus of pin material (N/mm²). "
                    "Default 200000 (P20/H13 tool steel)."
                ),
            },
            "ejector_plate_thickness_mm": {
                "type": "number",
                "description": "Ejector plate thickness (mm). Optional; for knockout bar check.",
            },
            "knockout_bar_diameter_mm": {
                "type": "number",
                "description": (
                    "Knockout bar diameter (mm). Optional; triggers "
                    "Beaumont §9.5 plate contact check."
                ),
            },
        },
        "required": ["part_depth_mm", "machine_stroke_mm", "ejection_force_N", "pins"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_verify_ejector_stroke(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # Required scalar fields
    try:
        part_depth_mm = float(a["part_depth_mm"])
        machine_stroke_mm = float(a["machine_stroke_mm"])
        ejection_force_N = float(a["ejection_force_N"])
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"required field error: {exc}", "BAD_ARGS")

    # Parse pin specs
    raw_pins = a.get("pins", [])
    if not isinstance(raw_pins, list) or len(raw_pins) == 0:
        return err_payload("pins must be a non-empty list", "BAD_ARGS")

    pins = []
    for i, rp in enumerate(raw_pins):
        try:
            pins.append(EjectorPinSpec(
                diameter_mm=float(rp["diameter_mm"]),
                free_length_mm=float(rp["free_length_mm"]),
                count=int(rp.get("count", 1)),
            ))
        except Exception as exc:
            return err_payload(f"pins[{i}]: {exc}", "BAD_ARGS")

    # Optional fields
    kwargs: dict = {}
    for key, cast in [
        ("safety_margin_mm", float),
        ("force_per_pin_max_N", float),
        ("allowable_deflection_mm", float),
        ("steel_E_N_mm2", float),
        ("ejector_plate_thickness_mm", float),
        ("knockout_bar_diameter_mm", float),
    ]:
        if key in a and a[key] is not None:
            try:
                kwargs[key] = cast(a[key])
            except (TypeError, ValueError) as exc:
                return err_payload(f"{key}: {exc}", "BAD_ARGS")

    try:
        report = verify_ejector_stroke(
            part_depth_mm=part_depth_mm,
            machine_stroke_mm=machine_stroke_mm,
            pins=pins,
            ejection_force_N=ejection_force_N,
            **kwargs,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    return ok_payload({
        "ok": report.ok,
        "stroke_adequate": report.stroke_adequate,
        "required_stroke_mm": report.required_stroke_mm,
        "machine_stroke_mm": report.machine_stroke_mm,
        "stroke_clearance_mm": report.stroke_clearance_mm,
        "force_adequate": report.force_adequate,
        "total_pin_count": report.total_pin_count,
        "force_per_pin_N": report.force_per_pin_N,
        "force_capacity_N": report.force_capacity_N,
        "deflection_ok": report.deflection_ok,
        "max_deflection_mm": report.max_deflection_mm,
        "pin_deflections": [
            {
                "diameter_mm": r.diameter_mm,
                "free_length_mm": r.free_length_mm,
                "force_per_pin_N": r.force_per_pin_N,
                "deflection_mm": r.deflection_mm,
                "allowable_mm": r.allowable_mm,
                "passes": r.passes,
            }
            for r in report.pin_deflections
        ],
        "knockout_bar_ok": report.knockout_bar_ok,
        "knockout_bar_checked": report.knockout_bar_checked,
        "violations": report.violations,
        "warnings": report.warnings,
        "honest_flag": report.honest_flag,
    })
