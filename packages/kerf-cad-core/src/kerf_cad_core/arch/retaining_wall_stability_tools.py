"""
kerf_cad_core.arch.retaining_wall_stability_tools — LLM tool:
    arch_check_retaining_wall_stability

Registers one tool with the Kerf tool registry:

  arch_check_retaining_wall_stability — check overturning, sliding, and
    bearing stability of a cantilevered concrete retaining wall under
    Rankine active earth pressure (Bowles 5e §12.3; Das §13).

Returns {ok: true, ...} on success; {ok: false, errors: [...]} on bad input.
Never raises.

Scope: Rankine active pressure only; level backfill, cohesionless (c=0).
No surcharge, no seismic (Mononobe-Okabe), no passive resistance at toe.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False

from kerf_cad_core.arch.retaining_wall_stability import (
    RetainingWallSpec,
    SoilSpec,
    check_retaining_wall,
)


# ---------------------------------------------------------------------------
# Tool spec (only materialise when registry is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE:
    _rw_spec = ToolSpec(
        name="arch_check_retaining_wall_stability",
        description=(
            "Check overturning, sliding, and bearing stability of a cantilevered "
            "concrete retaining wall under Rankine active earth pressure "
            "(Bowles 'Foundation Engineering' 5e §12.3; Das 'Principles of "
            "Geotechnical Engineering' §13).\n\n"
            "Earth pressure:\n"
            "  Ka = tan²(45 − φ/2)\n"
            "  Pa = 0.5·γ_s·H²·Ka  (horizontal resultant, acts at H/3)\n\n"
            "Stability factors of safety:\n"
            "  FoS_overturning = ΣM_resist / ΣM_overt  ≥ 2.0\n"
            "  FoS_sliding     = ΣW·tan(δ) / Pa         ≥ 1.5\n"
            "  FoS_bearing     = q_a / q_max             ≥ 3.0\n"
            "    where q_max = (ΣW/B)·(1 + 6e/B), e = B/2 − x̄\n\n"
            "SCOPE LIMITATIONS:\n"
            "  - Rankine active pressure only (level backfill, cohesionless)\n"
            "  - NO surcharge load\n"
            "  - NO seismic (Mononobe-Okabe) component\n"
            "  - NO passive resistance from soil in front of toe\n"
            "  - NO hydrostatic pressure (free-draining assumed)\n\n"
            "All inputs in SI: metres, kN/m³, kPa, degrees.\n"
            "Returns Ka, Pa_kN_per_m, FoS_overturning, FoS_sliding, q_max_kPa, "
            "FoS_bearing, all_adequate, governing_failure_mode, honest_caveat."
        ),
        input_schema={
            "type": "object",
            "properties": {
                # Wall geometry
                "wall_height_H_m": {
                    "type": "number",
                    "description": (
                        "Total retained height H from top of stem to bottom of "
                        "base footing (m). Includes the base slab thickness. Must be > 0."
                    ),
                },
                "stem_thickness_t_m": {
                    "type": "number",
                    "description": (
                        "Thickness of the vertical concrete stem t (m). "
                        "Must be > 0. Typical range 0.2–0.5 m."
                    ),
                },
                "base_width_B_m": {
                    "type": "number",
                    "description": (
                        "Total base width B = toe_length + stem_thickness + heel_length (m). "
                        "Must equal the sum of the three components. "
                        "Typical range: 0.4H–0.7H."
                    ),
                },
                "base_thickness_h_m": {
                    "type": "number",
                    "description": (
                        "Thickness of the horizontal base slab h (m). "
                        "Must be > 0 and < H. Typical range 0.1H–0.15H."
                    ),
                },
                "heel_length_m": {
                    "type": "number",
                    "description": (
                        "Heel length — distance from back face of stem to the "
                        "back edge of the base slab (soil side), in metres. "
                        "Must be ≥ 0. Longer heel increases overturning resistance."
                    ),
                },
                "toe_length_m": {
                    "type": "number",
                    "description": (
                        "Toe length — distance from front face of stem to the "
                        "front edge of the base slab, in metres. "
                        "Must be ≥ 0. Typical: 0.1–0.25 m."
                    ),
                },
                "concrete_unit_weight_kN_m3": {
                    "type": "number",
                    "description": (
                        "Unit weight of concrete γ_c (kN/m³). Default 24.0. "
                        "Normal concrete: 24 kN/m³; lightweight: 16–20 kN/m³."
                    ),
                },
                # Soil properties
                "soil_unit_weight_kN_m3": {
                    "type": "number",
                    "description": (
                        "Moist unit weight of backfill γ_s (kN/m³). Must be > 0. "
                        "Typical: loose sand 16–18; dense sand 18–20; gravel 18–20."
                    ),
                },
                "friction_angle_phi_deg": {
                    "type": "number",
                    "description": (
                        "Effective friction angle of backfill φ (degrees). "
                        "Range (0, 50]. "
                        "Typical: loose sand 28–32°; medium sand 30–35°; "
                        "dense sand/gravel 35–42°."
                    ),
                },
                "base_friction_delta_deg": {
                    "type": "number",
                    "description": (
                        "Friction angle at the concrete base–soil interface δ (degrees). "
                        "Typically 0.5φ to 0.67φ for concrete on soil; "
                        "use φ for rough concrete poured on gravel. "
                        "Must be in [0, φ]."
                    ),
                },
                "allowable_bearing_q_a_kPa": {
                    "type": "number",
                    "description": (
                        "Allowable bearing capacity of the founding soil q_a (kPa). "
                        "Must come from a geotechnical investigation. "
                        "Typical: soft clay 50–100; medium clay 100–200; "
                        "dense sand 200–400; gravel 300–600; rock > 1000. "
                        "Must be > 0."
                    ),
                },
            },
            "required": [
                "wall_height_H_m",
                "stem_thickness_t_m",
                "base_width_B_m",
                "base_thickness_h_m",
                "heel_length_m",
                "toe_length_m",
                "soil_unit_weight_kN_m3",
                "friction_angle_phi_deg",
                "base_friction_delta_deg",
                "allowable_bearing_q_a_kPa",
            ],
        },
    )

    # -----------------------------------------------------------------------
    # Tool handler
    # -----------------------------------------------------------------------

    @register(_rw_spec, write=False)
    async def run_arch_check_retaining_wall_stability(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        required = [
            "wall_height_H_m", "stem_thickness_t_m", "base_width_B_m",
            "base_thickness_h_m", "heel_length_m", "toe_length_m",
            "soil_unit_weight_kN_m3", "friction_angle_phi_deg",
            "base_friction_delta_deg", "allowable_bearing_q_a_kPa",
        ]
        missing = [f for f in required if a.get(f) is None]
        if missing:
            return err_payload(f"Missing required fields: {missing}", "BAD_ARGS")

        try:
            wall = RetainingWallSpec(
                wall_height_H_m=float(a["wall_height_H_m"]),
                stem_thickness_t_m=float(a["stem_thickness_t_m"]),
                base_width_B_m=float(a["base_width_B_m"]),
                base_thickness_h_m=float(a["base_thickness_h_m"]),
                heel_length_m=float(a["heel_length_m"]),
                toe_length_m=float(a["toe_length_m"]),
                concrete_unit_weight_kN_m3=float(
                    a.get("concrete_unit_weight_kN_m3", 24.0)
                ),
            )
            soil = SoilSpec(
                unit_weight_kN_m3=float(a["soil_unit_weight_kN_m3"]),
                friction_angle_phi_deg=float(a["friction_angle_phi_deg"]),
                base_friction_delta_deg=float(a["base_friction_delta_deg"]),
                allowable_bearing_q_a_kPa=float(a["allowable_bearing_q_a_kPa"]),
            )
            report = check_retaining_wall(wall, soil)
        except (ValueError, TypeError) as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(
            {
                "Ka": round(report.Ka, 6),
                "Pa_kN_per_m": round(report.Pa_kN_per_m, 3),
                "FoS_overturning": round(report.FoS_overturning, 3),
                "FoS_sliding": round(report.FoS_sliding, 3),
                "q_max_kPa": round(report.q_max_kPa, 2),
                "FoS_bearing": round(report.FoS_bearing, 3),
                "all_adequate": report.all_adequate,
                "governing_failure_mode": report.governing_failure_mode,
                "honest_caveat": report.honest_caveat,
            }
        )
