"""
kerf_mold.tunnel_gate_design_tool — LLM tool wrapper for tunnel gate design.

Tool: mold_design_tunnel_gate
  Design a tunnel (submarine) gate for an injection mold given part weight
  and polymer grade.  Returns gate diameter, length, angle, break-off force,
  shear rate, and freeze time.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.,
    Hanser, §7.4 (Tunnel / Submarine Gates) + §4.2 (fill-time thumb rule).
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., Hanser, §6.6.5 (Tunnel Gate) + Table 6.3 (shear strength)
    + Table 7.3 (thermal diffusivity) + §7.3.3 (freeze time).
  Chen, C.-C. & Chiang, C.-H. (1985). "Injection Mold Cooling Time
    Analysis", ANTEC, pp. 432–436.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.tunnel_gate_design import TunnelGateSpec, design_tunnel_gate


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_design_tunnel_gate_spec = ToolSpec(
    name="mold_design_tunnel_gate",
    description=(
        "Design a tunnel (submarine) gate for an injection mold given part "
        "weight and polymer grade.  Returns gate diameter, land length, "
        "recommended angle, break-off force, shear rate, and gate freeze "
        "time.\n\n"
        "Tunnel gate diameter (Beaumont 2007 §7.4):\n"
        "  D_gate = 0.5 × wall_thickness_at_gate_mm\n"
        "  High-viscosity correction (+10 %): PC, PA66, PMMA, POM, PEI, PPO\n"
        "  Lower bound: 0.8 mm (machining floor)\n"
        "  Upper cap: D ≤ 2/3 × wall_thickness (Menges 2001 §6.6.5)\n\n"
        "Break-off force: shear_strength_MPa × π/4 × D²\n"
        "  Shear strengths (Menges 2001 Table 6.3): ABS=30, PC=45, PP=22,\n"
        "  PA66=40, POM=38, PMMA=42, PEI=50, PPO=45 MPa\n\n"
        "Shear rate (Hagen-Poiseuille): γ̇ = 4Q/(π·r³)\n"
        "  Limit: 50 000 s⁻¹ (Beaumont §7.4)\n\n"
        "Gate freeze time: 1-D Fourier (Chen-Chiang / Menges §7.3.3)\n\n"
        "Angle recommendation (Menges §6.6.5): 30° soft/flexible → 45° stiff/glassy\n\n"
        "Inputs:\n"
        "  part_weight_g             — total shot weight [g] (> 0)\n"
        "  wall_thickness_at_gate_mm — local wall at gate attachment [mm] (> 0)\n"
        "  polymer_grade             — e.g. \"ABS\", \"PC\", \"PP\", \"PA66\"\n"
        "  melt_temp_C               — melt injection temperature [°C] (> 0)\n"
        "  gate_angle_deg            — gate entry angle [°] (default 30.0)\n"
        "  gate_length_mm            — gate land length [mm] (default 1.5)\n\n"
        "Returns: {gate_diameter_mm, gate_length_mm, gate_angle_deg, "
        "gate_break_off_force_N, gate_freeze_time_s, shear_rate_at_gate_per_s, "
        "shear_within_limit, recommended_angle_deg, honest_caveat, reference}.\n\n"
        "HONEST: diameter is a start-point Beaumont heuristic.  Complex "
        "multi-cavity timing and filling balance require Moldflow/Moldex3D "
        "full 3-D fill simulation.  Confirm by mold trial."
    ),
    input_schema={
        "type": "object",
        "required": [
            "part_weight_g",
            "wall_thickness_at_gate_mm",
            "polymer_grade",
            "melt_temp_C",
        ],
        "properties": {
            "part_weight_g": {
                "type": "number",
                "description": "Total shot weight of the part [g]. Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "wall_thickness_at_gate_mm": {
                "type": "number",
                "description": (
                    "Local wall thickness at the gate attachment point [mm]. "
                    "Beaumont §7.4: D_gate = 0.5 × wall_thickness. Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer / material grade (case-insensitive). "
                    "Supported: ABS, PC, PP, PA66, POM, PMMA, PE-LD, PE-HD, "
                    "PS, PEI, PPO, TPE. Unknown grades fall back to ABS "
                    "baseline properties with a caveat."
                ),
            },
            "melt_temp_C": {
                "type": "number",
                "description": (
                    "Melt injection temperature [°C]. Used for gate freeze-time "
                    "calculation. Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "gate_angle_deg": {
                "type": "number",
                "description": (
                    "Gate entry angle relative to the parting-line direction [°]. "
                    "Menges §6.6.5 recommended range: 30°–45°. "
                    "Default: 30.0."
                ),
                "default": 30.0,
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 90,
            },
            "gate_length_mm": {
                "type": "number",
                "description": (
                    "Gate land (tunnel) length [mm]. Beaumont §7.4 typical: "
                    "1.0–2.0 mm. Default: 1.5."
                ),
                "default": 1.5,
                "exclusiveMinimum": 0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_design_tunnel_gate(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute tunnel gate design and return a JSON string."""
    try:
        part_weight_g = args.get("part_weight_g")
        wall_thickness_mm = args.get("wall_thickness_at_gate_mm")
        polymer_grade = args.get("polymer_grade")
        melt_temp_C = args.get("melt_temp_C")
        gate_angle_deg = args.get("gate_angle_deg", 30.0)
        gate_length_mm = args.get("gate_length_mm", 1.5)

        # Validate required args
        if part_weight_g is None:
            return err_payload("part_weight_g is required", "BAD_ARGS")
        if wall_thickness_mm is None:
            return err_payload("wall_thickness_at_gate_mm is required", "BAD_ARGS")
        if polymer_grade is None:
            return err_payload("polymer_grade is required", "BAD_ARGS")
        if melt_temp_C is None:
            return err_payload("melt_temp_C is required", "BAD_ARGS")

        try:
            part_weight_g = float(part_weight_g)
        except (TypeError, ValueError):
            return err_payload(
                f"part_weight_g must be a number, got {part_weight_g!r}", "BAD_ARGS"
            )

        try:
            wall_thickness_mm = float(wall_thickness_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"wall_thickness_at_gate_mm must be a number, "
                f"got {wall_thickness_mm!r}",
                "BAD_ARGS",
            )

        try:
            melt_temp_C = float(melt_temp_C)
        except (TypeError, ValueError):
            return err_payload(
                f"melt_temp_C must be a number, got {melt_temp_C!r}", "BAD_ARGS"
            )

        try:
            gate_angle_deg = float(gate_angle_deg)
        except (TypeError, ValueError):
            return err_payload(
                f"gate_angle_deg must be a number, got {gate_angle_deg!r}", "BAD_ARGS"
            )

        try:
            gate_length_mm = float(gate_length_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"gate_length_mm must be a number, got {gate_length_mm!r}", "BAD_ARGS"
            )

        spec = TunnelGateSpec(
            part_weight_g=part_weight_g,
            wall_thickness_at_gate_mm=wall_thickness_mm,
            polymer_grade=str(polymer_grade),
            melt_temp_C=melt_temp_C,
            gate_angle_deg=gate_angle_deg,
            gate_length_mm=gate_length_mm,
        )

        report = design_tunnel_gate(spec)

        payload: dict[str, Any] = {
            "ok": True,
            "gate_diameter_mm": report.gate_diameter_mm,
            "gate_length_mm": spec.gate_length_mm,
            "gate_angle_deg": spec.gate_angle_deg,
            "gate_break_off_force_N": report.gate_break_off_force_N,
            "gate_freeze_time_s": report.gate_freeze_time_s,
            "shear_rate_at_gate_per_s": report.shear_rate_at_gate_per_s,
            "shear_within_limit": report.shear_within_limit,
            "recommended_angle_deg": report.recommended_angle_deg,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook 2nd ed. "
                "Hanser 2007 §7.4 + §4.2; "
                "Menges G., Michaeli W., Mohren P. How to Make Injection Molds "
                "3rd ed. Hanser 2001 §6.6.5 + Table 6.3 + §7.3.3; "
                "Chen-Chiang ANTEC 1985"
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "TUNNEL_GATE_ERROR")
