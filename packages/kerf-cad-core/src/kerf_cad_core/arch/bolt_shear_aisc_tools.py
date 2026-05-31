"""
kerf_cad_core.arch.bolt_shear_aisc_tools — LLM tool: arch_check_bolt_shear.

Registers one tool with the Kerf tool registry:

  arch_check_bolt_shear — AISC 360-22 §J3.6 bolt-group shear strength check
                          (single-shear / double-shear, bearing-type or
                          slip-critical).

Computes:
  • φ·Rn per bolt (shear) = φ_v · Fnv · Ab · n_planes   (φ_v=0.75)
  • φ·Rn_group             = φ·Rn_per_bolt × nb
  • Bearing §J3.10a:       φ·Rn_brg = φ·2.4·d·t·Fu
  • Tearout §J3.10b:       φ·Rn_to  = φ·1.2·Lc·t·Fu
  • Slip-critical §J3.8:   φ·Rn_slip = φ_sc·μ·Du·hf·Tb·ns·nb  (if requested)

Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

References:
  AISC 360-22 §J3.6, §J3.8, §J3.10.
  AISC Steel Construction Manual 16e Part 9.
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
            "AISC 360-22 §J3.6 bolt-group shear strength check (LRFD).\n\n"
            "Supports single-shear and double-shear, bearing-type and slip-critical "
            "connections.  Checks three limit states per bolt:\n"
            "  1. Bolt shear §J3.6: φ·Rn = φ_v·Fnv·Ab·n_planes (φ_v=0.75)\n"
            "  2. Bearing §J3.10a: φ·Rn = φ·2.4·d·t·Fu\n"
            "  3. Tearout §J3.10b: φ·Rn = φ·1.2·Lc·t·Fu (Lc = Le − dh/2)\n"
            "  4. Slip-critical §J3.8 (optional): "
            "Rn = μ·Du·hf·Tb·ns per bolt (φ_sc=1.00 std holes)\n\n"
            "Table J3.2 Fnv: A325-N=54 ksi, A325-X=68 ksi, A490-N=68 ksi, "
            "A490-X=84 ksi, A307=27 ksi.\n\n"
            "Returns phi_Rn_per_bolt_kip, phi_Rn_group_kip, bearing_phi_Rn_kip, "
            "tearout_phi_Rn_kip, governing_mode, slip_critical_phi_Rn_kip "
            "(null if bearing-type), and honest_caveat.\n\n"
            "SCOPE: LRFD only. Shear-lag (§J4.3), combined tension+shear (§J3.7), "
            "block shear (§J4.3), eccentric bolt groups (ICR), and weld+bolt "
            "combined groups (§J8) NOT checked. Fatigue NOT included. "
            "A307 not permitted for slip-critical connections."
        ),
        input_schema={
            "type": "object",
            "required": [
                "grade",
                "diameter_in",
                "num_bolts",
                "plate_thickness_in",
                "end_distance_in",
            ],
            "properties": {
                "grade": {
                    "type": "string",
                    "enum": ["A325-N", "A325-X", "A490-N", "A490-X", "A307"],
                    "description": (
                        "Bolt grade and thread condition. "
                        "-N = threads IN the shear plane; -X = threads EXCLUDED. "
                        "A307 = Grade A (threads in shear plane only)."
                    ),
                },
                "diameter_in": {
                    "type": "number",
                    "description": (
                        "Nominal bolt diameter (inches). "
                        "Common: 0.5, 0.625, 0.75, 0.875, 1.0. Must be > 0."
                    ),
                },
                "threads_in_shear_plane": {
                    "type": "boolean",
                    "description": (
                        "Informational: True if threads are in the shear plane "
                        "(already encoded in the grade suffix -N/-X). Default true."
                    ),
                },
                "num_shear_planes": {
                    "type": "integer",
                    "description": (
                        "Number of shear planes per bolt. "
                        "1 = single-shear (lap splice); "
                        "2 = double-shear (web connection). Default 1."
                    ),
                },
                "num_bolts": {
                    "type": "integer",
                    "description": "Total number of bolts in the group. Must be >= 1.",
                },
                "plate_thickness_in": {
                    "type": "number",
                    "description": (
                        "Thickness of the bearing/tearout plate — "
                        "thinnest element at the bolt hole (inches). Must be > 0."
                    ),
                },
                "plate_Fu_ksi": {
                    "type": "number",
                    "description": (
                        "Ultimate tensile strength of the bearing plate (ksi). "
                        "Default 58.0 ksi (A36 per AISC Table 2-4)."
                    ),
                },
                "end_distance_in": {
                    "type": "number",
                    "description": (
                        "Distance from bolt centre to the end of the connected part "
                        "in the direction of load (inches). Used for tearout Lc. "
                        "AISC §J3.4 minimum ≈ 1.25·d. Must be > 0."
                    ),
                },
                "spacing_in": {
                    "type": "number",
                    "description": (
                        "Centre-to-centre bolt spacing along load direction (inches). "
                        "AISC §J3.3 preferred = 3d. Default 3.0 in. Must be > 0."
                    ),
                },
                "slip_critical": {
                    "type": "boolean",
                    "description": (
                        "If true, also compute slip-critical design strength §J3.8. "
                        "Requires standard bolt diameter (Table J3.1). "
                        "NOT valid for A307. Default false."
                    ),
                },
                "faying_class": {
                    "type": "string",
                    "enum": ["A", "B"],
                    "description": (
                        "Faying surface class for slip-critical connections. "
                        "'A' = unpainted clean mill scale or hot-dip galvanised "
                        "(μ=0.35); "
                        "'B' = unpainted blast-cleaned (μ=0.50). Default 'A'."
                    ),
                },
                "num_slip_planes": {
                    "type": "integer",
                    "description": (
                        "Number of slip planes (faying surfaces). "
                        "Usually equals num_shear_planes. Default 1."
                    ),
                },
                "phi_v": {
                    "type": "number",
                    "description": (
                        "Resistance factor for bolt shear. "
                        "Default 0.75 per AISC 360-22 §J3.6."
                    ),
                },
                "phi_br": {
                    "type": "number",
                    "description": (
                        "Resistance factor for bearing and tearout. "
                        "Default 0.75 per AISC 360-22 §J3.10."
                    ),
                },
            },
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

        required_fields = [
            "grade", "diameter_in", "num_bolts",
            "plate_thickness_in", "end_distance_in",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            bolt = BoltSpec(
                grade=str(a["grade"]),
                diameter_in=float(a["diameter_in"]),
                threads_in_shear_plane=bool(a.get("threads_in_shear_plane", True)),
                num_shear_planes=int(a.get("num_shear_planes", 1)),
            )
            conn = ConnectionSpec(
                num_bolts=int(a["num_bolts"]),
                plate_thickness_in=float(a["plate_thickness_in"]),
                plate_Fu_ksi=float(a.get("plate_Fu_ksi", 58.0)),
                end_distance_in=float(a["end_distance_in"]),
                spacing_in=float(a.get("spacing_in", 3.0)),
                slip_critical=bool(a.get("slip_critical", False)),
                faying_class=str(a.get("faying_class", "A")),
                num_slip_planes=int(a.get("num_slip_planes", 1)),
            )
            phi_v = float(a.get("phi_v", 0.75))
            phi_br = float(a.get("phi_br", 0.75))
            report = check_bolt_shear(bolt, conn, phi_v=phi_v, phi_br=phi_br)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "phi_Rn_per_bolt_kip": round(report.phi_Rn_per_bolt_kip, 4),
                "phi_Rn_group_kip": round(report.phi_Rn_group_kip, 4),
                "bearing_phi_Rn_kip": round(report.bearing_phi_Rn_kip, 4),
                "tearout_phi_Rn_kip": round(report.tearout_phi_Rn_kip, 4),
                "governing_mode": report.governing_mode,
                "slip_critical_phi_Rn_kip": (
                    round(report.slip_critical_phi_Rn_kip, 4)
                    if report.slip_critical_phi_Rn_kip is not None
                    else None
                ),
                "honest_caveat": report.honest_caveat,
            }
        )
