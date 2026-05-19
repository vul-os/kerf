"""
kerf_firmware.rtos — FreeRTOS-equivalent RTOS scheduler primitives.

Public API
----------
Task        — represents an RTOS task (name, priority, stack_size, entry_fn, period_ms)
Mutex       — binary mutex primitive; tracks holder for priority-inversion analysis
Semaphore   — counting semaphore primitive
Queue       — typed message queue with capacity limit
Scheduler   — priority-based preemptive scheduler simulator + static analyser
"""

from .scheduler import Task, Mutex, Semaphore, Queue, Scheduler
from .c_codegen import generate_freertos_main

__all__ = [
    "Task",
    "Mutex",
    "Semaphore",
    "Queue",
    "Scheduler",
    "generate_freertos_main",
]
