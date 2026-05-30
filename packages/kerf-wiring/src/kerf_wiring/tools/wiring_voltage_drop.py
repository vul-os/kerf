"""
LLM tool: wiring_voltage_drop

Computes NEC 2023 voltage drop for a wire run carrying current I.

Formula:
  Single-phase (2-wire):  V_drop = 2 × I × L × R_per_foot
  Three-phase (LL):       V_drop = √3 × I × L × R_per_foot

Compares result to NEC §215.2 recommended limits:
  3% — branch-circuit maximum
  5% — total-system maximum

References:
  NEC 2023 Chapter 9 Table 8  — DC resistance of conductors.
  NEC 2023 §215.2(A)(1)(b)    — voltage-drop recommendations.

Schema:
  {
    "awg": "12",
    "material": "Cu",
    "run_length_ft": 100.0,
    "current_amps": 15.0,
    "voltage": 120.0,
    "phase": "single",
    "conductor_temp_c": 75.0
  }

Returns ok_payload with v_drop_volts, v_drop_percent, within_3_percent,
within_5_percent, and advisory notes; or err_payload on bad input.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_wiring._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore


wiring_voltage_drop_spec = ToolSpec(
    name="wiring_voltage_drop",
    description=(
        "Compute NEC 2023 voltage drop for a wire run.  "
        "Uses NEC Chapter 9 Table 8 DC resistance (Cu or Al, AWG 14–4/0 + kcmil 250–750).  "
        "Applies single-phase formula V_drop = 2·I·L·R or 3-phase V_drop = √3·I·L·R.  "
        "Reports v_drop_volts, v_drop_percent, and whether the run is within the "
        "NEC §215.2 3% branch-circuit and 5% total-system recommendations.  "
        "Optional temperature correction (NEC Ch9 Table 8 α coefficient).  "
        "LIMITATION: DC resistance only; AC inductive reactance ignored."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "awg": {
                "type": "string",
                "description": (
                    "Conductor size.  AWG: '14','12','10','8','6','4','3','2','1',"
                    "'1/0','2/0','3/0','4/0'.  kcmil: '250','300','350','400',"
                    "'500','600','700','750'."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["Cu", "Al"],
                "description": "'Cu' (default) or 'Al'.",
            },
            "run_length_ft": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "One-way run length in feet.",
            },
            "current_amps": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Load current in amperes.",
            },
            "voltage": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": (
                    "System voltage used to compute percent drop.  "
                    "Line-to-neutral for single-phase (e.g. 120, 277); "
                    "line-to-line for 3-phase (e.g. 208, 240, 480)."
                ),
            },
            "phase": {
                "type": "string",
                "enum": ["single", "three"],
                "description": (
                    "'single' (default) — 2-wire single-phase, V_drop = 2·I·L·R.  "
                    "'three' — 3-phase line-to-line, V_drop = √3·I·L·R."
                ),
            },
            "conductor_temp_c": {
                "type": "number",
                "description": (
                    "Estimated conductor operating temperature in °C.  "
                    "Default 75 °C (NEC 310.16 75°C column, conservative for THHN).  "
                    "Table 8 reference is 75 °F (≈24 °C)."
                ),
            },
        },
        "required": ["awg", "run_length_ft", "current_amps", "voltage"],
    },
)


@register(wiring_voltage_drop_spec, write=False)
async def wiring_voltage_drop(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args JSON: {e}", "BAD_ARGS")

    awg = a.get("awg")
    if awg is None:
        return err_payload("'awg' is required", "BAD_ARGS")

    run_length_ft = a.get("run_length_ft")
    if run_length_ft is None:
        return err_payload("'run_length_ft' is required", "BAD_ARGS")

    current_amps = a.get("current_amps")
    if current_amps is None:
        return err_payload("'current_amps' is required", "BAD_ARGS")

    voltage = a.get("voltage")
    if voltage is None:
        return err_payload("'voltage' is required", "BAD_ARGS")

    material = a.get("material", "Cu")
    phase = a.get("phase", "single")
    conductor_temp_c = float(a.get("conductor_temp_c", 75.0))

    if material not in ("Cu", "Al"):
        return err_payload(
            f"material must be 'Cu' or 'Al'; got '{material}'", "BAD_ARGS"
        )
    if phase not in ("single", "three"):
        return err_payload(
            f"phase must be 'single' or 'three'; got '{phase}'", "BAD_ARGS"
        )

    try:
        run_length_ft = float(run_length_ft)
        current_amps = float(current_amps)
        voltage = float(voltage)
    except (TypeError, ValueError) as e:
        return err_payload(f"numeric argument error: {e}", "BAD_ARGS")

    try:
        from kerf_wiring.voltage_drop import compute_voltage_drop
        result = compute_voltage_drop(
            awg=awg,
            material=material,
            run_length_ft=run_length_ft,
            current_amps=current_amps,
            voltage=voltage,
            phase=phase,
            conductor_temp_c=conductor_temp_c,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"voltage drop calculation failed: {exc}", "ERROR")

    return ok_payload({
        "awg": result.awg,
        "material": result.material,
        "run_length_ft": result.run_length_ft,
        "current_amps": result.current_amps,
        "voltage": result.voltage,
        "phase": result.phase,
        "conductor_temp_c": result.conductor_temp_c,
        "r_per_1000ft_at_ref": result.r_per_1000ft_at_ref,
        "r_per_1000ft_corrected": result.r_per_1000ft_corrected,
        "v_drop_volts": result.v_drop_volts,
        "v_drop_percent": result.v_drop_percent,
        "within_3_percent": result.within_3_percent,
        "within_5_percent": result.within_5_percent,
        "notes": result.notes,
    })
