"""LLM tool: firmware_check_watchdog — firmware watchdog-kick gap verifier.

Verifies that the independent watchdog (IWDG/WWDG on STM32) is kicked
frequently enough across all execution paths of a firmware task schedule to
never time out, even on worst-case latency.

References
----------
  STM32F4 RM0383 Rev 3 §19 — IWDG.
  STM32F4 RM0383 Rev 3 §20 — WWDG.
  IEC 61508:2010 Part 2 §7.4.3.7 — Watchdog monitoring.
  ARM Keil AN259 — Using Watchdog Timers in Embedded Systems.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.watchdog_check import (
    FirmwareTask,
    WatchdogSpec,
    check_watchdog,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_check_watchdog",
    description=(
        "Verify that the firmware task schedule kicks the independent watchdog "
        "(IWDG/WWDG on STM32) frequently enough across ALL execution paths so "
        "that the watchdog never times out — even under worst-case task latency.\n\n"
        "Algorithm (RM0383 §19 IWDG + §20 WWDG + IEC 61508 §7.4.3.7):\n"
        "  1. Find the kicking task with the longest period (slowest kicker).\n"
        "  2. Add the WCET of all higher-priority non-kicking tasks (blocking time).\n"
        "  3. max_gap = slowest_kicker.period_ms + blocking_time_ms.\n"
        "  4. is_safe = max_gap < wdg.timeout_ms.\n"
        "  5. WWDG: also flag kicks earlier than window_min_ms (early-kick reset).\n\n"
        "Depth-bar oracle:\n"
        "  tasks=[{name='ctrl', period_ms=100, wcet_ms=10, priority=1, kicks=True}]\n"
        "  wdg={type='IWDG', timeout_ms=250}\n"
        "  → max_gap=100ms, margin=150ms, is_safe=True.\n\n"
        "  tasks=[{name='slow', period_ms=1000, wcet_ms=50, priority=1, kicks=True}]\n"
        "  wdg={type='IWDG', timeout_ms=500}\n"
        "  → max_gap=1000ms, margin=-500ms, is_safe=False.\n\n"
        "NOTE: Static schedule only — no IRQ latency or jitter model. "
        "IEC 61508 SIL-2+ requires a challenge-response watchdog in addition to this check."
    ),
    input_schema={
        "type": "object",
        "required": ["tasks", "wdg"],
        "properties": {
            "tasks": {
                "type": "array",
                "description": (
                    "List of firmware tasks in the schedule. Each task has: "
                    "name (str), period_ms (float > 0), wcet_ms (float > 0, "
                    "≤ period_ms), priority (int, higher = higher priority), "
                    "kicks_watchdog (bool, default false)."
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "period_ms", "wcet_ms", "priority"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Human-readable task name.",
                        },
                        "period_ms": {
                            "type": "number",
                            "description": "Task invocation period in milliseconds.",
                            "exclusiveMinimum": 0,
                        },
                        "wcet_ms": {
                            "type": "number",
                            "description": (
                                "Worst-case execution time in milliseconds. "
                                "Must be ≤ period_ms."
                            ),
                            "exclusiveMinimum": 0,
                        },
                        "priority": {
                            "type": "integer",
                            "description": (
                                "Scheduler priority. Higher integer = higher priority "
                                "(pre-empts tasks with lower priority values)."
                            ),
                        },
                        "kicks_watchdog": {
                            "type": "boolean",
                            "description": (
                                "True if this task issues a watchdog feed "
                                "(IWDG_KR = 0xAAAA on STM32) at least once per "
                                "execution. Default: false."
                            ),
                            "default": False,
                        },
                    },
                },
            },
            "wdg": {
                "type": "object",
                "description": "Watchdog peripheral specification.",
                "required": ["type", "timeout_ms"],
                "properties": {
                    "type": {
                        "type": "string",
                        "description": (
                            "'IWDG' — Independent Watchdog (simple timeout, RM0383 §19). "
                            "'WWDG' — Window Watchdog (timeout + open-window lower bound, §20)."
                        ),
                        "enum": ["IWDG", "WWDG"],
                    },
                    "timeout_ms": {
                        "type": "number",
                        "description": "Watchdog timeout in milliseconds.",
                        "exclusiveMinimum": 0,
                    },
                    "window_min_ms": {
                        "type": ["number", "null"],
                        "description": (
                            "WWDG only: minimum elapsed time between two consecutive "
                            "kicks (milliseconds). Kicks issued before this minimum have "
                            "elapsed trigger an early-kick reset. Required for WWDG."
                        ),
                        "default": None,
                    },
                },
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_check_watchdog(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute watchdog-kick gap analysis and return a JSON payload."""
    raw_tasks = args.get("tasks")
    raw_wdg = args.get("wdg")

    if not isinstance(raw_tasks, list):
        return err_payload("'tasks' is required and must be a JSON array", "BAD_ARGS")
    if not isinstance(raw_wdg, dict):
        return err_payload("'wdg' is required and must be a JSON object", "BAD_ARGS")

    # ── Parse tasks ────────────────────────────────────────────────────────────
    tasks = []
    for i, rt in enumerate(raw_tasks):
        if not isinstance(rt, dict):
            return err_payload(
                f"tasks[{i}] must be a JSON object", "BAD_ARGS"
            )
        try:
            t = FirmwareTask(
                name=str(rt["name"]),
                period_ms=float(rt["period_ms"]),
                wcet_ms=float(rt["wcet_ms"]),
                priority=int(rt["priority"]),
                kicks_watchdog=bool(rt.get("kicks_watchdog", False)),
            )
        except KeyError as exc:
            return err_payload(
                f"tasks[{i}] missing required field {exc}", "BAD_ARGS"
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"tasks[{i}] invalid value: {exc}", "BAD_ARGS")
        tasks.append(t)

    # ── Parse wdg ──────────────────────────────────────────────────────────────
    try:
        wdg = WatchdogSpec(
            type=str(raw_wdg["type"]),
            timeout_ms=float(raw_wdg["timeout_ms"]),
            window_min_ms=(
                float(raw_wdg["window_min_ms"])
                if raw_wdg.get("window_min_ms") is not None
                else None
            ),
        )
    except KeyError as exc:
        return err_payload(f"wdg missing required field {exc}", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(f"wdg invalid value: {exc}", "BAD_ARGS")

    try:
        report = check_watchdog(tasks, wdg)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Analysis error: {exc}", "ANALYSIS_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_check_watchdog_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_check_watchdog(a, ctx)
