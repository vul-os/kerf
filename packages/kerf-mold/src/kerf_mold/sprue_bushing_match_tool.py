"""
kerf_mold.sprue_bushing_match_tool — LLM tool wrapper for sprue bushing match check.

Tool: mold_check_sprue_bushing_match
  Given a SprueBushingSpec and a MachineNozzleSpec, verify that the sprue bushing
  nozzle seat radius and orifice diameter are correctly sized relative to the
  injection-moulding machine nozzle tip, following Beaumont 2007 §6.4 and the
  DME standard sprue bushing catalogue.

  Compliance rules:
    sprue_R = nozzle_r + 0.5 mm … nozzle_r + 1.0 mm   (seat radius excess)
    sprue_O = nozzle_O + 0.5 mm … nozzle_O + 1.0 mm   (orifice diameter excess)
    taper   = 1.5°/side … 3.0°/side                    (DME standard §3.2)

  HONEST SCOPE: standard cold-runner sprue bushings only.  Hot-runner bushings
  (DME hot-tip, valve-gate, edge-gate nozzles) follow different design rules
  and are NOT covered by this tool.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.,
    Hanser, §6.4 Sprue Bushing Design (pp. 127–138).
  DME Company LLC (2023). *Mold Components Catalogue*, Series SB/SBA/SBT
    Sprue Bushings, §3.2 Seat Radius and Taper Specifications.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.sprue_bushing_match import (
    SprueBushingSpec,
    MachineNozzleSpec,
    check_sprue_bushing_match,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_check_sprue_bushing_match_spec = ToolSpec(
    name="mold_check_sprue_bushing_match",
    description=(
        "Verify that a cold-runner sprue bushing nozzle seat radius (R) and "
        "orifice diameter (O) match the injection-moulding machine nozzle tip, "
        "per Beaumont 2007 §6.4 + DME standard sprue bushing catalogue §3.2.\n\n"
        "Compliance rules applied:\n"
        "  sprue_R = nozzle_r + 0.5 mm … +1.0 mm  (seat radius excess)\n"
        "  sprue_O = nozzle_O + 0.5 mm … +1.0 mm  (orifice diameter excess)\n"
        "  taper   = 1.5°/side … 3.0°/side         (DME standard §3.2)\n\n"
        "Returns: R_mismatch_mm, R_compliant, O_mismatch_mm, O_compliant, "
        "taper_compliant, recommendation, honest_caveat.\n\n"
        "IMPORTANT SCOPE: standard COLD-RUNNER sprue bushings only.  "
        "Hot-runner nozzle seats (DME hot-tip, valve-gate, edge-gate) follow "
        "different design rules (thermal expansion allowance, heater mass, "
        "gate-tip diameter) and are NOT covered by this tool."
    ),
    input_schema={
        "type": "object",
        "required": ["sprue_bushing", "machine_nozzle"],
        "properties": {
            "sprue_bushing": {
                "type": "object",
                "description": "Sprue bushing geometry.",
                "required": [
                    "nozzle_radius_R_mm",
                    "sprue_orifice_diameter_O_mm",
                    "total_length_mm",
                    "taper_per_side_deg",
                ],
                "properties": {
                    "nozzle_radius_R_mm": {
                        "type": "number",
                        "description": (
                            "Spherical concave seat radius of the sprue bushing [mm]. "
                            "Must be > 0.  Beaumont §6.4 target: nozzle_r + 0.5–1.0 mm."
                        ),
                        "exclusiveMinimum": 0,
                    },
                    "sprue_orifice_diameter_O_mm": {
                        "type": "number",
                        "description": (
                            "Sprue bore diameter at the nozzle contact face [mm]. "
                            "Must be > 0.  Beaumont §6.4 target: nozzle_O + 0.5–1.0 mm."
                        ),
                        "exclusiveMinimum": 0,
                    },
                    "total_length_mm": {
                        "type": "number",
                        "description": (
                            "Overall length of the sprue bushing from nozzle face to "
                            "parting plane [mm].  Must be > 0."
                        ),
                        "exclusiveMinimum": 0,
                    },
                    "taper_per_side_deg": {
                        "type": "number",
                        "description": (
                            "Half-included angle (taper per side) of the sprue bore "
                            "[degrees].  DME standard §3.2 range: 1.5°–3.0°.  "
                            "Must be > 0."
                        ),
                        "exclusiveMinimum": 0,
                    },
                },
            },
            "machine_nozzle": {
                "type": "object",
                "description": "Machine nozzle tip geometry.",
                "required": [
                    "nozzle_tip_radius_mm",
                    "nozzle_tip_orifice_diameter_mm",
                ],
                "properties": {
                    "nozzle_tip_radius_mm": {
                        "type": "number",
                        "description": (
                            "Convex spherical radius of the machine nozzle tip [mm]. "
                            "Must be > 0.  Measure with a radius gauge."
                        ),
                        "exclusiveMinimum": 0,
                    },
                    "nozzle_tip_orifice_diameter_mm": {
                        "type": "number",
                        "description": (
                            "Bore diameter of the machine nozzle orifice [mm]. "
                            "Must be > 0."
                        ),
                        "exclusiveMinimum": 0,
                    },
                },
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_check_sprue_bushing_match(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute sprue bushing match check and return a JSON string."""
    try:
        raw_sprue = args.get("sprue_bushing")
        if not raw_sprue:
            return err_payload("sprue_bushing is required", "BAD_ARGS")
        if not isinstance(raw_sprue, dict):
            return err_payload(
                f"sprue_bushing must be an object, got {type(raw_sprue).__name__}",
                "BAD_ARGS",
            )

        raw_nozzle = args.get("machine_nozzle")
        if not raw_nozzle:
            return err_payload("machine_nozzle is required", "BAD_ARGS")
        if not isinstance(raw_nozzle, dict):
            return err_payload(
                f"machine_nozzle must be an object, got {type(raw_nozzle).__name__}",
                "BAD_ARGS",
            )

        # --- Parse sprue fields ---
        def _float(obj: dict, key: str, parent: str) -> "float | str":
            val = obj.get(key)
            if val is None:
                return f"{parent}.{key} is required"
            try:
                return float(val)
            except (TypeError, ValueError):
                return f"{parent}.{key} must be a number, got {val!r}"

        r_R = _float(raw_sprue, "nozzle_radius_R_mm", "sprue_bushing")
        if isinstance(r_R, str):
            return err_payload(r_R, "BAD_ARGS")

        r_O = _float(raw_sprue, "sprue_orifice_diameter_O_mm", "sprue_bushing")
        if isinstance(r_O, str):
            return err_payload(r_O, "BAD_ARGS")

        r_len = _float(raw_sprue, "total_length_mm", "sprue_bushing")
        if isinstance(r_len, str):
            return err_payload(r_len, "BAD_ARGS")

        r_taper = _float(raw_sprue, "taper_per_side_deg", "sprue_bushing")
        if isinstance(r_taper, str):
            return err_payload(r_taper, "BAD_ARGS")

        # --- Parse nozzle fields ---
        n_r = _float(raw_nozzle, "nozzle_tip_radius_mm", "machine_nozzle")
        if isinstance(n_r, str):
            return err_payload(n_r, "BAD_ARGS")

        n_O = _float(raw_nozzle, "nozzle_tip_orifice_diameter_mm", "machine_nozzle")
        if isinstance(n_O, str):
            return err_payload(n_O, "BAD_ARGS")

        # --- Build dataclasses (may raise ValueError on non-positive dims) ---
        sprue = SprueBushingSpec(
            nozzle_radius_R_mm=r_R,
            sprue_orifice_diameter_O_mm=r_O,
            total_length_mm=r_len,
            taper_per_side_deg=r_taper,
        )
        nozzle = MachineNozzleSpec(
            nozzle_tip_radius_mm=n_r,
            nozzle_tip_orifice_diameter_mm=n_O,
        )

        report = check_sprue_bushing_match(sprue, nozzle)

        payload: dict[str, Any] = {
            "ok": True,
            "R_mismatch_mm": round(report.R_mismatch_mm, 4),
            "R_compliant": report.R_compliant,
            "O_mismatch_mm": round(report.O_mismatch_mm, 4),
            "O_compliant": report.O_compliant,
            "taper_compliant": report.taper_compliant,
            "fully_compliant": (
                report.R_compliant and report.O_compliant and report.taper_compliant
            ),
            "recommendation": report.recommendation,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., "
                "Hanser 2007, §6.4 Sprue Bushing Design; "
                "DME Company LLC Mold Components Catalogue 2023, §3.2 "
                "Seat Radius and Taper Specifications."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "SPRUE_BUSHING_ERROR")
