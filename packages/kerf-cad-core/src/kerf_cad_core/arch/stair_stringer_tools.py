"""
kerf_cad_core.arch.stair_stringer_tools — LLM tool: arch_design_stair_stringer.

Registers one tool with the Kerf tool registry:

  arch_design_stair_stringer — Check stair stringer adequacy per
                                IBC 2021 §1011 (riser/tread geometry) +
                                AWC NDS-2018 §3.3 (sawn lumber bending) or
                                AISC 360-22 §F2 (steel channel/HSS bending).

Returns riser_compliant, tread_compliant, span_length_in, bending_dcr,
deflection_dcr, governing_dcr, status, warnings, honest_caveat.
Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

SCOPE: BENDING ONLY — shear, bearing at connections, and LTB NOT checked.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.stair_stringer import (
    StairGeometry,
    StringerSpec,
    design_stair_stringer,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _stair_stringer_spec = ToolSpec(
        name="arch_design_stair_stringer",
        description=(
            "Check a stair stringer (inclined beam) for IBC 2021 §1011 geometry "
            "code compliance (riser height 4–7 in, tread depth ≥ 11 in), and "
            "bending stress / deflection adequacy per AWC NDS-2018 §3.3 (sawn "
            "lumber) or AISC 360-22 §F2 (steel channel/HSS).\n\n"
            "Model: stringer treated as simply-supported inclined beam.\n"
            "  span L = √(total_run² + total_rise²)\n"
            "  tributary width per stringer = stair_width / num_stringers\n"
            "  w = (live_load_psf + dead_load_psf) × trib_width  [lb/in]\n"
            "  M_max = w·L²/8   (UDL, Roark 9e §8 Table 8.1 case 2)\n"
            "  δ_max = 5·w·L⁴/(384·E·I)\n"
            "  Deflection limit: L/360 (IBC Table 1604.3)\n\n"
            "Supported materials (material key):\n"
            "  'sawn-DF-No2'       DF-Larch No.2 2×12 (Fb=875 psi, E=1.6e6 psi)\n"
            "  'sawn-SP-No1'       Southern Pine No.1 2×12 (Fb=1500 psi, E=1.7e6 psi)\n"
            "  'steel-C10x15.3'   AISC C10×15.3 A36 (Sx=13.5 in³, Ix=67.4 in⁴)\n"
            "  'steel-HSS6x4x1/4' AISC HSS6×4×1/4 A500 Gr.B (Sx=8.53 in³, Ix=25.6 in⁴)\n\n"
            "Returns: riser_compliant, tread_compliant, span_length_in, "
            "max_moment_in_lb, max_deflection_in, bending_dcr, deflection_dcr, "
            "governing_dcr, status ('ok'|'oversize'|'fail-bending'|"
            "'fail-deflection'|'fail-code'), warnings, honest_caveat.\n\n"
            "SCOPE: BENDING ONLY — shear (NDS §4.4.3 / AISC §G2.1), bearing at "
            "connections, and lateral-torsional buckling NOT checked."
        ),
        input_schema={
            "type": "object",
            "required": [
                "num_treads",
                "riser_height_in",
                "tread_depth_in",
                "stair_width_in",
                "material",
            ],
            "properties": {
                "num_treads": {
                    "type": "integer",
                    "description": (
                        "Number of treads in the stair flight.  Must be ≥ 1.  "
                        "Example: 13 for a typical floor-to-floor flight."
                    ),
                },
                "riser_height_in": {
                    "type": "number",
                    "description": (
                        "Vertical riser height in inches.  "
                        "IBC §1011.5.2 commercial limit: 4–7 in.  "
                        "Typical: 6.5–7.0 in."
                    ),
                },
                "tread_depth_in": {
                    "type": "number",
                    "description": (
                        "Horizontal tread depth (nosing to nosing) in inches.  "
                        "IBC §1011.5.2 minimum: 11 in.  "
                        "Typical: 11–12 in."
                    ),
                },
                "stair_width_in": {
                    "type": "number",
                    "description": (
                        "Clear width of the stair in inches.  "
                        "Typical: 36–48 in (3–4 ft)."
                    ),
                },
                "material": {
                    "type": "string",
                    "enum": [
                        "sawn-DF-No2",
                        "sawn-SP-No1",
                        "steel-C10x15.3",
                        "steel-HSS6x4x1/4",
                    ],
                    "description": (
                        "Stringer material key.  "
                        "'sawn-DF-No2' / 'sawn-SP-No1' for wood (AWC NDS-2018 §3.3); "
                        "'steel-C10x15.3' / 'steel-HSS6x4x1/4' for steel (AISC 360-22 §F2)."
                    ),
                },
                "num_stringers": {
                    "type": "integer",
                    "description": (
                        "Number of stringers supporting the stair (default 2).  "
                        "Tributary load per stringer = total load / num_stringers."
                    ),
                },
                "live_load_psf": {
                    "type": "number",
                    "description": (
                        "Design live load in psf (default 100 psf per "
                        "ASCE 7-22 Table 4.3-1 assembly stair).  "
                        "Residential stairs may use 40 psf (Table 4.3-1)."
                    ),
                },
                "dead_load_psf": {
                    "type": "number",
                    "description": (
                        "Superimposed dead load in psf (default 15 psf — "
                        "typical tread/riser finish + stringer self-weight estimate)."
                    ),
                },
                "total_run_in": {
                    "type": "number",
                    "description": (
                        "Total horizontal run of the stair flight in inches.  "
                        "If omitted or 0, computed as num_treads × tread_depth_in."
                    ),
                },
                "total_rise_in": {
                    "type": "number",
                    "description": (
                        "Total vertical rise of the stair flight in inches.  "
                        "If omitted or 0, computed as num_treads × riser_height_in."
                    ),
                },
            },
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_stair_stringer_spec, write=False)
    async def run_arch_design_stair_stringer(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "num_treads",
            "riser_height_in",
            "tread_depth_in",
            "stair_width_in",
            "material",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            geom = StairGeometry(
                num_treads=int(a["num_treads"]),
                riser_height_in=float(a["riser_height_in"]),
                tread_depth_in=float(a["tread_depth_in"]),
                total_run_in=float(a.get("total_run_in", 0)),
                total_rise_in=float(a.get("total_rise_in", 0)),
                stair_width_in=float(a["stair_width_in"]),
            )
            stringer = StringerSpec(
                material=str(a["material"]),
            )
            report = design_stair_stringer(
                geom=geom,
                stringer=stringer,
                num_stringers=int(a.get("num_stringers", 2)),
                live_load_psf=float(a.get("live_load_psf", 100.0)),
                dead_load_psf=float(a.get("dead_load_psf", 15.0)),
            )
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "riser_compliant": report.riser_compliant,
                "tread_compliant": report.tread_compliant,
                "span_length_in": round(report.span_length_in, 3),
                "max_moment_in_lb": round(report.max_moment_in_lb, 2),
                "max_moment_conc_in_lb": round(report.max_moment_conc_in_lb, 2),
                "max_deflection_in": round(report.max_deflection_in, 6),
                "bending_dcr": round(report.bending_dcr, 4),
                "deflection_dcr": round(report.deflection_dcr, 4),
                "governing_dcr": round(report.governing_dcr, 4),
                "status": report.status,
                "warnings": report.warnings,
                "honest_caveat": report.honest_caveat,
            }
        )
