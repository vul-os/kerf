"""
kerf_cad_core.arch.opening_in_wall_tools — LLM tool: arch_check_opening_in_wall.

Registers one tool with the Kerf tool registry:

  arch_check_opening_in_wall — Check that a wall opening (door/window) satisfies
    code requirements: tributary load redistribution to jamb piers (IBC §2308.4),
    jamb axial capacity (ACI 318-19 §11.5.3.1 or TMS 402-22 §8.3), and lintel/
    header bending + deflection limits (AISC Table 3-23 / ACI 318-19 §9 / TMS 402-22 §5).

References:
  IBC 2021 §2308.4 (Wall openings).
  TMS 402-22 §5 (Lintel design); §8.3 (Bearing wall axial).
  ACI 318-19 §11.5.3.1 (Bearing walls empirical method).
  AISC 360-22 §F1/§G2 (Steel lintels via design_lintel).
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.opening_in_wall import (
    WallOpeningSpec,
    check_opening,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _opening_spec = ToolSpec(
        name="arch_check_opening_in_wall",
        description=(
            "Check that a wall opening (door or window) satisfies structural code requirements: "
            "tributary load redistribution to jamb piers (IBC §2308.4 prescriptive intent), "
            "jamb axial capacity (ACI 318-19 §11.5.3.1 or TMS 402-22 §8.3), and lintel/header "
            "bending moment and deflection limits (AISC Table 3-23 / ACI 318-19 §9 / TMS 402-22 §5). "
            "\n\nSupported materials: 'concrete' (RC pier, ACI §11.5.3.1), "
            "'masonry' (TMS 402-22 §8.3), 'wood_frame' (simplified bearing check). "
            "\n\nTributary width per jamb = opening_width/2 + jamb_width/2 + header_above_height. "
            "Factored jamb load = 1.2 × axial_load × trib_width + 0.5 × lateral × opening_area. "
            "\n\nReturns: tributary_load_on_jamb_kN, jamb_axial_capacity_kN, jamb_dcr, "
            "lintel_moment_dcr, lintel_deflection_mm, all_adequate, governing_check, honest_caveat. "
            "\n\nSCOPE: Simplified tributary method — full 2-D stress-concentration analysis "
            "around opening corners NOT modelled. Wood-frame: NDS 2018 Cp factor NOT computed. "
            "Lateral load combinations must be checked separately."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "wall_height_m": {
                    "type": "number",
                    "description": "Total clear storey height of the wall in metres. Must be > 0. Example: 3.0",
                },
                "wall_thickness_m": {
                    "type": "number",
                    "description": "Wall thickness in metres. Must be > 0. Example: 0.200 for 200mm CMU wall.",
                },
                "opening_width_m": {
                    "type": "number",
                    "description": "Clear opening width in metres. Must be > 0. Example: 1.2 for a 1.2m window.",
                },
                "opening_height_m": {
                    "type": "number",
                    "description": "Clear opening height in metres. Must be > 0 and < wall_height_m. Example: 1.5.",
                },
                "header_above_opening_height_m": {
                    "type": "number",
                    "description": (
                        "Height of wall panel above the lintel up to the next structural element "
                        "(floor slab, roof, bond beam) in metres. Used in tributary width and "
                        "masonry arching action. Must be >= 0. Example: 1.0."
                    ),
                },
                "lintel_depth_m": {
                    "type": "number",
                    "description": (
                        "Overall depth of the lintel/header cross-section in metres. Must be > 0. "
                        "Example: 0.300 for a 300mm deep lintel."
                    ),
                },
                "jamb_width_m": {
                    "type": "number",
                    "description": (
                        "Width of each jamb pier (measured along wall face) in metres. Must be > 0. "
                        "Example: 0.400 for a 400mm jamb pier."
                    ),
                },
                "material": {
                    "type": "string",
                    "enum": ["concrete", "masonry", "wood_frame"],
                    "description": (
                        "Wall/structural material. "
                        "'concrete' → ACI 318-19 §11.5.3.1 jamb capacity; RC lintel check. "
                        "'masonry' → TMS 402-22 §8.3 jamb capacity; RM lintel check. "
                        "'wood_frame' → simplified bearing area check; steel-proxy lintel check."
                    ),
                },
                "f_prime_or_fy_MPa": {
                    "type": "number",
                    "description": (
                        "Material strength in MPa. Must be > 0. "
                        "concrete → f'c (e.g. 25, 30 MPa). "
                        "masonry → f'm (e.g. 10, 14, 20 MPa). "
                        "wood_frame → Fc allowable compressive stress parallel to grain (e.g. 9 MPa for SPF #2)."
                    ),
                },
                "applied_axial_kN_per_m": {
                    "type": "number",
                    "description": (
                        "Service axial load from above (gravity + superimposed) per unit length of wall (kN/m). "
                        "Must be >= 0. Example: 30.0 kN/m for typical storey loading."
                    ),
                },
                "applied_lateral_kN_per_m2": {
                    "type": "number",
                    "description": (
                        "Uniform lateral pressure on the wall face (kN/m²), e.g. wind or seismic "
                        "equivalent uniform pressure. Must be >= 0. Example: 1.0 kN/m² for wind."
                    ),
                },
            },
            "required": [
                "wall_height_m",
                "wall_thickness_m",
                "opening_width_m",
                "opening_height_m",
                "header_above_opening_height_m",
                "lintel_depth_m",
                "jamb_width_m",
                "material",
                "f_prime_or_fy_MPa",
                "applied_axial_kN_per_m",
                "applied_lateral_kN_per_m2",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_opening_spec, write=False)
    async def run_arch_check_opening_in_wall(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required_fields = [
            "wall_height_m", "wall_thickness_m", "opening_width_m",
            "opening_height_m", "header_above_opening_height_m",
            "lintel_depth_m", "jamb_width_m", "material",
            "f_prime_or_fy_MPa", "applied_axial_kN_per_m",
            "applied_lateral_kN_per_m2",
        ]
        missing = [f for f in required_fields if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            spec = WallOpeningSpec(
                wall_height_m=float(a["wall_height_m"]),
                wall_thickness_m=float(a["wall_thickness_m"]),
                opening_width_m=float(a["opening_width_m"]),
                opening_height_m=float(a["opening_height_m"]),
                header_above_opening_height_m=float(a["header_above_opening_height_m"]),
                lintel_depth_m=float(a["lintel_depth_m"]),
                jamb_width_m=float(a["jamb_width_m"]),
                material=str(a["material"]),
                f_prime_or_fy_MPa=float(a["f_prime_or_fy_MPa"]),
                applied_axial_kN_per_m=float(a["applied_axial_kN_per_m"]),
                applied_lateral_kN_per_m2=float(a["applied_lateral_kN_per_m2"]),
            )
            report = check_opening(spec)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "tributary_load_on_jamb_kN": report.tributary_load_on_jamb_kN,
                "jamb_axial_capacity_kN": report.jamb_axial_capacity_kN,
                "jamb_dcr": report.jamb_dcr,
                "lintel_moment_dcr": report.lintel_moment_dcr,
                "lintel_deflection_mm": report.lintel_deflection_mm,
                "all_adequate": report.all_adequate,
                "governing_check": report.governing_check,
                "honest_caveat": report.honest_caveat,
            }
        )
