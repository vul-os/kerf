"""
kerf_cad_core.arch.bolt_shear_aisc_tools — LLM tool: arch_check_bolt_shear.

Registers one tool with the Kerf tool registry:

  arch_check_bolt_shear — check a bolted connection's shear capacity per
                           AISC 360-22 §J3.6 (bolt shear), §J3.10 (bearing
                           and tearout), and optionally §J3.8 (slip-critical).

References:
  AISC 360-22 §J3.6 (bolt shear), §J3.8 (slip-critical), §J3.10 (bearing/tearout)

All inputs: inches (dimensions), ksi (stress), kip (force) — matches
kerf_cad_core.arch.bolt_shear_aisc's imperial/AISC unit convention.
Returns {ok: true, ...} on success; {error, code: "BAD_ARGS"} on bad input.
Never raises.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.bolt_shear_aisc import (
    BoltSpec,
    ConnectionSpec,
    check_bolt_shear,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _bolt_shear_spec = ToolSpec(
        name="arch_check_bolt_shear",
        description=(
            "Check a bolted connection's shear capacity per AISC 360-22 §J3.6 "
            "(bolt shear), §J3.10 (bearing at bolt holes / tearout), and "
            "optionally §J3.8 (slip-critical). LRFD only.\n\n"
            "  1. Bolt shear (§J3.6):  φ·Rn = φ_v · Fnv · Ab · num_shear_planes\n"
            "  2. Bearing (§J3.10a):   φ·Rn = φ · 2.4 · d · t · Fu\n"
            "  3. Tearout (§J3.10b):   φ·Rn = φ · 1.2 · Lc · t · Fu\n"
            "  4. Slip-critical (§J3.8, if slip_critical=true):\n"
            "       Rn = μ · Du · hf · Tb · ns per bolt\n\n"
            "Governing mode per bolt is the minimum of shear/bearing/tearout.\n\n"
            "SCOPE: shear-lag (§J4.3), combined tension+shear (§J3.7), prying "
            "action, weld+bolt combined groups (§J8), eccentrically loaded "
            "groups, and block shear (§J4.3) are NOT modelled — see "
            "honest_caveat. AISC ASD (Ω-factor) not provided — LRFD only. "
            "All dimensions in inches; stresses in ksi; forces in kip."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "grade": {
                    "type": "string",
                    "description": (
                        "Bolt grade and thread condition: 'A325-N', 'A325-X', "
                        "'A490-N', 'A490-X', or 'A307'. -N = threads in shear "
                        "plane; -X = threads excluded (higher Fnv)."
                    ),
                },
                "diameter_in": {
                    "type": "number",
                    "description": (
                        "Nominal bolt diameter in inches. Must be > 0. "
                        "Common sizes: 0.5, 0.625, 0.75, 0.875, 1.0."
                    ),
                },
                "num_bolts": {
                    "type": "integer",
                    "description": "Total number of bolts in the group. Must be >= 1.",
                },
                "plate_thickness_in": {
                    "type": "number",
                    "description": (
                        "Thickness of the bearing/tearout plate (thinnest "
                        "element at the bolt hole), in inches. Must be > 0."
                    ),
                },
                "end_distance_in": {
                    "type": "number",
                    "description": (
                        "Clear distance from the centre of the nearest bolt "
                        "hole to the end of the connected part, along the "
                        "load direction, in inches. Must be > 0. Default 1.5."
                    ),
                },
                "num_shear_planes": {
                    "type": "integer",
                    "description": (
                        "Number of shear planes: 1 = single-shear, "
                        "2 = double-shear. Default 1."
                    ),
                },
                "threads_in_shear_plane": {
                    "type": "boolean",
                    "description": (
                        "Informational when grade already encodes N/X. "
                        "Default true."
                    ),
                },
                "plate_Fu_ksi": {
                    "type": "number",
                    "description": (
                        "Ultimate tensile strength of the bearing plate, ksi. "
                        "Default 58.0 (A36)."
                    ),
                },
                "spacing_in": {
                    "type": "number",
                    "description": (
                        "Centre-to-centre bolt spacing along the load "
                        "direction, in inches. AISC §J3.3 min = 2⅔d, "
                        "preferred = 3d. Default 3.0."
                    ),
                },
                "slip_critical": {
                    "type": "boolean",
                    "description": (
                        "If true, also compute slip-critical (§J3.8) design "
                        "strength. Default false."
                    ),
                },
                "faying_class": {
                    "type": "string",
                    "description": "Faying surface class: 'A' (μ=0.35, default) or 'B' (μ=0.50).",
                },
                "num_slip_planes": {
                    "type": "integer",
                    "description": "Number of slip (faying) planes. Default 1.",
                },
                "phi_v": {
                    "type": "number",
                    "description": "Bolt shear resistance factor φ_v. Default 0.75.",
                },
                "phi_br": {
                    "type": "number",
                    "description": "Bearing/tearout resistance factor φ. Default 0.75.",
                },
            },
            "required": [
                "grade",
                "diameter_in",
                "num_bolts",
                "plate_thickness_in",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_bolt_shear_spec, write=False)
    async def run_arch_check_bolt_shear(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required = ["grade", "diameter_in", "num_bolts", "plate_thickness_in"]
        missing = [f for f in required if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            bolt = BoltSpec(
                grade=str(a["grade"]),
                diameter_in=float(a["diameter_in"]),
                threads_in_shear_plane=bool(a.get("threads_in_shear_plane", True)),
                num_shear_planes=int(a.get("num_shear_planes", 1)),
            )
            conn_kwargs = dict(
                num_bolts=int(a["num_bolts"]),
                plate_thickness_in=float(a["plate_thickness_in"]),
            )
            if a.get("plate_Fu_ksi") is not None:
                conn_kwargs["plate_Fu_ksi"] = float(a["plate_Fu_ksi"])
            if a.get("end_distance_in") is not None:
                conn_kwargs["end_distance_in"] = float(a["end_distance_in"])
            if a.get("spacing_in") is not None:
                conn_kwargs["spacing_in"] = float(a["spacing_in"])
            if a.get("slip_critical") is not None:
                conn_kwargs["slip_critical"] = bool(a["slip_critical"])
            if a.get("faying_class") is not None:
                conn_kwargs["faying_class"] = str(a["faying_class"])
            if a.get("num_slip_planes") is not None:
                conn_kwargs["num_slip_planes"] = int(a["num_slip_planes"])
            conn = ConnectionSpec(**conn_kwargs)

            phi_v = float(a.get("phi_v", 0.75))
            phi_br = float(a.get("phi_br", 0.75))
            report = check_bolt_shear(bolt, conn, phi_v=phi_v, phi_br=phi_br)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "phi_Rn_per_bolt_kip": report.phi_Rn_per_bolt_kip,
                "phi_Rn_group_kip": report.phi_Rn_group_kip,
                "bearing_phi_Rn_kip": report.bearing_phi_Rn_kip,
                "tearout_phi_Rn_kip": report.tearout_phi_Rn_kip,
                "governing_mode": report.governing_mode,
                "slip_critical_phi_Rn_kip": report.slip_critical_phi_Rn_kip,
                "honest_caveat": report.honest_caveat,
            }
        )
