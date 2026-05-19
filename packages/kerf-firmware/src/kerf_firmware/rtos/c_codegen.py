"""
kerf_firmware.rtos.c_codegen — FreeRTOS C code generator.

Emits a complete main.c file that creates all registered tasks, mutexes,
semaphores, and queues using the standard FreeRTOS API:

  xTaskCreate(pvTaskCode, pcName, usStackDepth, pvParameters, uxPriority, pxCreatedTask)
  xSemaphoreCreateMutex()
  xSemaphoreCreateCounting(uxMaxCount, uxInitialCount)
  xQueueCreate(uxQueueLength, uxItemSize)

The output is formatted C99-compatible source.  No external dependencies
are required — the template engine is stdlib string.Template.
"""

from __future__ import annotations

import string
import textwrap
from typing import TYPE_CHECKING

from .freertos_main_template import FREERTOS_MAIN_TEMPLATE

if TYPE_CHECKING:
    from .scheduler import Mutex, Queue, Scheduler, Semaphore, Task


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_freertos_main(scheduler: "Scheduler", item_size: int = 4) -> str:
    """Generate a FreeRTOS ``main.c`` string for *scheduler*.

    Parameters
    ----------
    scheduler : Scheduler
        The populated scheduler whose tasks/mutexes/semaphores/queues to emit.
    item_size : int
        Default ``sizeof(item)`` passed to ``xQueueCreate`` for all queues.
        Defaults to 4 (size of a ``uint32_t``).

    Returns
    -------
    str
        Complete C source for ``main.c``.
    """
    tasks = scheduler.tasks
    mutexes = scheduler._mutexes
    semaphores = scheduler._semaphores
    queues = scheduler._queues

    task_handle_lines = _task_handle_decls(tasks)
    mutex_handle_lines = _mutex_handle_decls(mutexes)
    semaphore_handle_lines = _semaphore_handle_decls(semaphores)
    queue_handle_lines = _queue_handle_decls(queues)
    task_proto_lines = _task_protos(tasks)
    main_body = _main_body(tasks, mutexes, semaphores, queues, item_size)

    tpl = string.Template(FREERTOS_MAIN_TEMPLATE)
    return tpl.substitute(
        INCLUDES="",
        TASK_HANDLES=_join_or_empty(task_handle_lines),
        MUTEX_HANDLES=_join_or_empty(mutex_handle_lines),
        SEMAPHORE_HANDLES=_join_or_empty(semaphore_handle_lines),
        QUEUE_HANDLES=_join_or_empty(queue_handle_lines),
        TASK_PROTOS=_join_or_empty(task_proto_lines),
        MAIN_BODY=main_body,
    )


# ---------------------------------------------------------------------------
# Declaration generators
# ---------------------------------------------------------------------------

def _task_handle_decls(tasks: list["Task"]) -> list[str]:
    return [f"static TaskHandle_t xHandle_{_safe(t.name)} = NULL;" for t in tasks]


def _mutex_handle_decls(mutexes: list["Mutex"]) -> list[str]:
    return [
        f"static SemaphoreHandle_t xMutex_{_safe(m.name)} = NULL;"
        for m in mutexes
    ]


def _semaphore_handle_decls(semaphores: list["Semaphore"]) -> list[str]:
    return [
        f"static SemaphoreHandle_t xSem_{_safe(s.name)} = NULL;"
        for s in semaphores
    ]


def _queue_handle_decls(queues: list["Queue"]) -> list[str]:
    return [
        f"static QueueHandle_t xQueue_{_safe(q.name)} = NULL;"
        for q in queues
    ]


def _task_protos(tasks: list["Task"]) -> list[str]:
    lines = []
    seen: set[str] = set()
    for t in tasks:
        fn = t.entry_fn
        if fn not in seen:
            seen.add(fn)
            lines.append(
                f"void {fn}(void *pvParameters); /* task: {t.name} */"
            )
    return lines


# ---------------------------------------------------------------------------
# main() body
# ---------------------------------------------------------------------------

def _main_body(
    tasks: list["Task"],
    mutexes: list["Mutex"],
    semaphores: list["Semaphore"],
    queues: list["Queue"],
    item_size: int,
) -> str:
    lines: list[str] = []

    # Create mutexes first — tasks may use them
    for m in mutexes:
        lines.append(
            f"    xMutex_{_safe(m.name)} = xSemaphoreCreateMutex();"
        )
        lines.append(
            f"    configASSERT(xMutex_{_safe(m.name)} != NULL);"
        )

    # Create counting semaphores
    for s in semaphores:
        lines.append(
            f"    xSem_{_safe(s.name)} = xSemaphoreCreateCounting"
            f"({s._maximum}U, {s._count}U);"
        )
        lines.append(
            f"    configASSERT(xSem_{_safe(s.name)} != NULL);"
        )

    # Create queues
    for q in queues:
        lines.append(
            f"    xQueue_{_safe(q.name)} = xQueueCreate"
            f"({q._capacity}U, sizeof(uint{item_size * 8}_t));"
        )
        lines.append(
            f"    configASSERT(xQueue_{_safe(q.name)} != NULL);"
        )

    # Create tasks
    for t in tasks:
        period_comment = (
            f" /* period: {t.period_ms} ms */" if t.period_ms is not None else ""
        )
        stack_words = max(1, t.stack_size // 4)  # FreeRTOS uses words, not bytes
        lines.append(
            f"    xTaskCreate({t.entry_fn}, \"{t.name}\","
            f" {stack_words}U, NULL, {t.priority}U,"
            f" &xHandle_{_safe(t.name)});{period_comment}"
        )
        lines.append(
            f"    configASSERT(xHandle_{_safe(t.name)} != NULL);"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(name: str) -> str:
    """Convert a name to a safe C identifier fragment."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _join_or_empty(lines: list[str]) -> str:
    if not lines:
        return "/* (none) */"
    return "\n".join(lines)
