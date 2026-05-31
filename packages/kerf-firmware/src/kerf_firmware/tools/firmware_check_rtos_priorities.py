"""LLM tool: firmware_check_rtos_priorities — Liu-Layland RM schedulability check.

Verifies that a set of periodic FreeRTOS / Zephyr / ChibiOS task definitions
satisfies the Liu-Layland (1973) rate-monotonic schedulability bound and that
task priorities are assigned in RM order (shorter period → higher priority).

Returns
-------
JSON payload with:
  total_utilization_pct    — Σ Cᵢ/Tᵢ × 100
  liu_layland_bound_pct    — n·(2^(1/n)−1) × 100
  rate_monotonic_schedulable — True iff U ≤ bound (sufficient condition)
  hyperbolic_bound_test    — Bini-Buttazzo 2001 tighter bound: Π(Uᵢ+1) ≤ 2
  priority_assignment_correct — True iff shorter period → higher priority
  num_tasks                — n
  schedule_recommendations — advisory list
  honest_caveat            — model scope disclaimer

HONEST CAVEAT
-------------
This tool implements ONLY the Liu-Layland 1973 classical RM model for
*independent periodic tasks*.  It does NOT model shared resources (PCP/PIP),
aperiodic/sporadic tasks, interrupt latency, context-switch overhead, or
deadlines ≠ periods.

References
----------
  Liu-Layland (1973) J. ACM 20(1) pp. 46-61.
  Bini-Buttazzo (2001) ECRTS — hyperbolic bound.
  ARM FreeRTOS Kernel Developer Docs — Task Priorities.
  Renesas FreeRTOS on RA MCU Group Application Note (R01AN5545).
  Zephyr Project Scheduling Docs.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.rtos_priority_check import RtosTaskSpec, check_rtos_priorities


# ── Tool specification ──────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_check_rtos_priorities",
    description=(
        "Verify RTOS task priority assignments for rate-monotonic (RM) schedulability "
        "using the Liu-Layland (1973) utilisation bound. "
        "For n independent periodic tasks: U = Σ Cᵢ/Tᵢ; "
        "schedulable if U ≤ n·(2^(1/n)−1). "
        "Also checks the tighter Bini-Buttazzo (2001) hyperbolic bound Π(Uᵢ+1)≤2 "
        "and verifies RM priority assignment (shorter period → higher priority integer). "
        "Supports FreeRTOS / Zephyr / ChibiOS — any RTOS using integer priorities "
        "where higher integer = higher urgency. "
        "Returns: total_utilization_pct, liu_layland_bound_pct, "
        "rate_monotonic_schedulable, hyperbolic_bound_test, "
        "priority_assignment_correct, num_tasks, schedule_recommendations, honest_caveat. "
        "HONEST CAVEAT: sufficient condition only for INDEPENDENT periodic tasks — "
        "does NOT model shared resources (PCP/PIP), aperiodic tasks, interrupt latency, "
        "context-switch overhead, or Di ≠ Ti deadlines. "
        "Refs: Liu-Layland (1973) J. ACM 20(1); Bini-Buttazzo (2001) ECRTS; "
        "ARM FreeRTOS Kernel Docs; Renesas R01AN5545; Zephyr Scheduling Docs."
    ),
    input_schema={
        "type": "object",
        "required": ["tasks"],
        "properties": {
            "tasks": {
                "type": "array",
                "description": (
                    "List of periodic RTOS task specifications. "
                    "Each entry describes one task with its period, WCET, and priority."
                ),
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["task_name", "period_ms", "wcet_ms", "priority"],
                    "properties": {
                        "task_name": {
                            "type": "string",
                            "description": (
                                "Unique task identifier, e.g. 'sensor_task', "
                                "'control_loop', 'comm_task'."
                            ),
                        },
                        "period_ms": {
                            "type": "number",
                            "description": (
                                "Task period in milliseconds. The task is invoked "
                                "once per period. Must be > 0."
                            ),
                            "exclusiveMinimum": 0,
                        },
                        "wcet_ms": {
                            "type": "number",
                            "description": (
                                "Worst-Case Execution Time in milliseconds. "
                                "The maximum time the task needs to complete one activation. "
                                "Must satisfy 0 < wcet_ms ≤ period_ms."
                            ),
                            "exclusiveMinimum": 0,
                        },
                        "priority": {
                            "type": "integer",
                            "description": (
                                "RTOS priority level (FreeRTOS/Zephyr/ChibiOS convention: "
                                "higher integer = higher urgency). "
                                "RM rule: shorter period task must receive higher priority integer."
                            ),
                            "minimum": 0,
                        },
                    },
                },
            },
        },
    },
)


# ── Tool handler ─────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_check_rtos_priorities(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute RTOS RM priority check and return a JSON payload."""
    raw_tasks = args.get("tasks")

    if not raw_tasks:
        return err_payload("'tasks' is required and must be non-empty", "BAD_ARGS")
    if not isinstance(raw_tasks, list):
        return err_payload("'tasks' must be a JSON array", "BAD_ARGS")

    parsed: list[RtosTaskSpec] = []
    for i, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            return err_payload(
                f"tasks[{i}] must be a JSON object", "BAD_ARGS"
            )
        try:
            parsed.append(RtosTaskSpec(
                task_name=str(item["task_name"]),
                period_ms=float(item["period_ms"]),
                wcet_ms=float(item["wcet_ms"]),
                priority=int(item["priority"]),
            ))
        except KeyError as exc:
            return err_payload(
                f"tasks[{i}] missing required field {exc}", "BAD_ARGS"
            )
        except (TypeError, ValueError) as exc:
            return err_payload(
                f"tasks[{i}] invalid value: {exc}", "BAD_ARGS"
            )

    try:
        report = check_rtos_priorities(parsed)
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Schedulability check error: {exc}", "CHECK_ERROR")

    result = {
        "total_utilization_pct": report.total_utilization_pct,
        "liu_layland_bound_pct": report.liu_layland_bound_pct,
        "rate_monotonic_schedulable": report.rate_monotonic_schedulable,
        "hyperbolic_bound_test": report.hyperbolic_bound_test,
        "priority_assignment_correct": report.priority_assignment_correct,
        "num_tasks": report.num_tasks,
        "schedule_recommendations": report.schedule_recommendations,
        "honest_caveat": report.honest_caveat,
    }
    return ok_payload(result)


# ── Async wrapper for plugin registration ────────────────────────────────────

async def run_firmware_check_rtos_priorities_async(
    ctx: object, args: bytes
) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_check_rtos_priorities(a, ctx)
