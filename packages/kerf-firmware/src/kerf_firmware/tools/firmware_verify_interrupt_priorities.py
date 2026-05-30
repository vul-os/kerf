"""LLM tool: firmware_verify_interrupt_priorities — verify STM32 NVIC priority assignments.

Checks that each peripheral's NVIC_IPR priority assignment is valid and
consistent with Cortex-M priority rules and recommended application-level
priority bands.  Detects:

  * **OUT_OF_RANGE** — priority value outside [0, 15] for STM32F4xx (4-bit field).
  * **SAME_PREEMPT_PRIORITY** — two peripherals share a preemption level;
    Cortex-M hardware tie-breaks by IRQ number, creating non-deterministic
    scheduling if ordering matters.
  * **RT_IN_LOW_BAND** — a real-time peripheral (TIM, EXTI) assigned to the
    LOW-priority band (9..15) where NORMAL-band interrupts will pre-empt it.
  * **NON_RT_IN_RT_BAND** — a non-real-time peripheral (USB, ADC, RTC) in
    the RT band (0..3), unnecessarily occupying high-priority slots.
  * **UNKNOWN_PERIPHERAL** — peripheral name not in the chip's IRQ table.
  * **BASEPRI_MISCONFIGURED** — BASEPRI = 0 (masking disabled) or above max.

HONEST DISCLAIMER
-----------------
Static analysis only.  This tool does NOT model WCET, ISR stack usage,
FreeRTOS priority inheritance, BASEPRI write/restore sequences, or actual
interrupt latency.  Use Tracealyzer / ARM DS-5 for runtime profiling.

Supported chips
---------------
  "STM32F411" (+ aliases stm32f411ce / stm32f411re / stm32f411ve)
  "STM32F407" (+ aliases stm32f407vg / stm32f407ig)

References
----------
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §B3.3 — NVIC_IPR + PRIGROUP.
  ARM Cortex-M Generic User Guide §B1.5.4 — BASEPRI.
  RM0383 Rev 3 §10 — STM32F411 NVIC, 62 maskable IRQs.
  RM0090 Rev 19 §10 — STM32F407 NVIC, 82 maskable IRQs.
"""
from __future__ import annotations

import json
from typing import Any, Optional

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.interrupt_priority_verify import IRQAssignment, verify_interrupt_priorities


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_verify_interrupt_priorities",
    description=(
        "Verify Cortex-M NVIC interrupt priority assignments for STM32 microcontrollers. "
        "Checks each peripheral's NVIC_IPR priority value against hardware constraints and "
        "recommended priority bands. "
        "Detects: OUT_OF_RANGE (priority outside [0,15] for STM32F4xx), "
        "SAME_PREEMPT_PRIORITY (two peripherals share a preemption level — non-deterministic "
        "tie-break by IRQ number when both pending), "
        "RT_IN_LOW_BAND (TIM/EXTI in low-priority band; will be pre-empted by NORMAL IRQs), "
        "NON_RT_IN_RT_BAND (USB/ADC/RTC in RT band; wastes high-priority slots), "
        "UNKNOWN_PERIPHERAL (name not in chip IRQ table), "
        "BASEPRI_MISCONFIGURED (BASEPRI=0 disables masking; value above max). "
        "Priority bands (4-bit field): RT=0..3, NORMAL=4..8, LOW=9..15. "
        "Lower priority number = higher actual priority (Cortex-M §B3.3). "
        "Supported chips: STM32F411, STM32F407. "
        "NOTE: static checks only — no WCET, RTOS, or runtime latency model."
    ),
    input_schema={
        "type": "object",
        "required": ["chip", "assignments"],
        "properties": {
            "chip": {
                "type": "string",
                "description": (
                    "Chip family. One of: 'STM32F411', 'STM32F407', "
                    "or aliases 'stm32f411ce', 'stm32f411re', 'stm32f407vg', etc."
                ),
            },
            "assignments": {
                "type": "array",
                "description": (
                    "List of NVIC priority assignments to verify. "
                    "Each entry specifies a peripheral and its NVIC_IPR priority value."
                ),
                "items": {
                    "type": "object",
                    "required": ["peripheral", "priority"],
                    "properties": {
                        "peripheral": {
                            "type": "string",
                            "description": (
                                "Peripheral/IRQ name, e.g. 'TIM2', 'EXTI0', 'USART1', "
                                "'OTG_FS', 'ADC'. Case-insensitive. "
                                "Aliases like 'TIM2_IRQn' or 'tim2' are accepted."
                            ),
                        },
                        "priority": {
                            "type": "integer",
                            "description": (
                                "NVIC_IPR priority value. For STM32F4xx (4-bit field): "
                                "0 = highest priority, 15 = lowest priority. "
                                "ARM Cortex-M Generic UG §B3.3: lower number wins."
                            ),
                            "minimum": 0,
                            "maximum": 255,
                        },
                        "label": {
                            "type": "string",
                            "description": (
                                "Optional human-readable label for this assignment "
                                "(e.g. a variable name). Used only in violation messages."
                            ),
                            "default": "",
                        },
                    },
                },
                "minItems": 1,
            },
            "prigroup": {
                "type": "integer",
                "description": (
                    "AIRCR.PRIGROUP value (3..7). Controls the split between preemption "
                    "priority bits and sub-priority bits. "
                    "STM32 HAL default: 4 (3 preempt bits + 1 sub bit). "
                    "PRIGROUP=3: 4 preempt bits + 0 sub bits = 16 preemption levels. "
                    "(ARM Cortex-M Generic UG §B3.3 Table B3-2) "
                    "If omitted, the chip default is used."
                ),
                "minimum": 0,
                "maximum": 7,
            },
            "basepri_threshold": {
                "type": "integer",
                "description": (
                    "Optional BASEPRI value used for critical-section masking. "
                    "BASEPRI=0 disables masking (all IRQs fire). "
                    "BASEPRI=N masks interrupts with priority >= N. "
                    "(ARM Cortex-M Generic UG §B1.5.4)"
                ),
                "minimum": 0,
                "maximum": 255,
            },
            "allow_same_preempt": {
                "type": "boolean",
                "description": (
                    "If true, suppress SAME_PREEMPT_PRIORITY violations. "
                    "Use when you intentionally share preemption levels and "
                    "accept IRQ-number tie-breaking. Default: false."
                ),
                "default": False,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_verify_interrupt_priorities(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute interrupt priority verification and return a JSON payload."""
    chip = args.get("chip", "")
    raw_assignments = args.get("assignments")

    if not chip:
        return err_payload("'chip' is required", "BAD_ARGS")
    if not raw_assignments:
        return err_payload("'assignments' is required and must be non-empty", "BAD_ARGS")
    if not isinstance(raw_assignments, list):
        return err_payload("'assignments' must be a JSON array", "BAD_ARGS")

    # Parse assignment dicts
    parsed: list[IRQAssignment] = []
    for i, item in enumerate(raw_assignments):
        if not isinstance(item, dict):
            return err_payload(
                f"assignments[{i}] must be a JSON object", "BAD_ARGS"
            )
        try:
            parsed.append(IRQAssignment(
                peripheral=str(item["peripheral"]),
                priority=int(item["priority"]),
                label=str(item.get("label", "")),
            ))
        except KeyError as exc:
            return err_payload(
                f"assignments[{i}] missing required field {exc}", "BAD_ARGS"
            )
        except (TypeError, ValueError) as exc:
            return err_payload(
                f"assignments[{i}] invalid value: {exc}", "BAD_ARGS"
            )

    # Optional parameters
    prigroup: Optional[int] = None
    if "prigroup" in args and args["prigroup"] is not None:
        try:
            prigroup = int(args["prigroup"])
        except (TypeError, ValueError) as exc:
            return err_payload(f"'prigroup' invalid: {exc}", "BAD_ARGS")

    basepri: Optional[int] = None
    if "basepri_threshold" in args and args["basepri_threshold"] is not None:
        try:
            basepri = int(args["basepri_threshold"])
        except (TypeError, ValueError) as exc:
            return err_payload(f"'basepri_threshold' invalid: {exc}", "BAD_ARGS")

    allow_same = bool(args.get("allow_same_preempt", False))

    try:
        report = verify_interrupt_priorities(
            chip,
            parsed,
            prigroup=prigroup,
            basepri_threshold=basepri,
            allow_same_preempt=allow_same,
        )
    except KeyError as exc:
        return err_payload(str(exc), "UNKNOWN_CHIP")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Verification error: {exc}", "VERIFY_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_verify_interrupt_priorities_async(
    ctx: object, args: bytes
) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_verify_interrupt_priorities(a, ctx)
