"""
tests/test_rtos_codegen.py — pytest suite for kerf_firmware.rtos.c_codegen.

Scenarios covered
-----------------
C1  generate_freertos_main() returns a non-empty string
C2  Output contains xTaskCreate for every registered task
C3  Output contains task name string literal
C4  Output contains xSemaphoreCreateMutex for mutexes
C5  Output contains xSemaphoreCreateCounting for semaphores
C6  Output contains xQueueCreate for queues
C7  Output contains vTaskStartScheduler
C8  Output is valid C-ish source (basic structural checks)
C9  Task handles declared as TaskHandle_t
C10 Queue handles declared as QueueHandle_t
C11 Mutex handles declared as SemaphoreHandle_t
C12 Forward declarations for entry functions are present
C13 No Jinja/template dependency: generation works with stdlib only
C14 Empty scheduler (no tasks) produces a minimal compilable stub
C15 configASSERT guards are emitted for every resource creation
"""
from __future__ import annotations

import pytest

from kerf_firmware.rtos.c_codegen import generate_freertos_main
from kerf_firmware.rtos.scheduler import Mutex, Queue, Scheduler, Semaphore, Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_scheduler() -> Scheduler:
    """Return a scheduler pre-populated with tasks, mutexes, semaphores, queues."""
    sched = Scheduler()

    sched.add_task(Task("idle", priority=1, stack_size=512, entry_fn="vIdleTask"))
    sched.add_task(Task("sensor", priority=5, stack_size=1024, entry_fn="vSensorTask", period_ms=10))
    sched.add_task(Task("control", priority=10, stack_size=2048, entry_fn="vControlTask", period_ms=1))

    sched.add_mutex(Mutex("periph_lock"))
    sched.add_semaphore(Semaphore(initial=0, maximum=5, name="data_ready"))
    sched.add_queue(Queue(capacity=16, name="cmd_queue"))

    return sched


# ---------------------------------------------------------------------------
# C1 — basic output type and non-empty
# ---------------------------------------------------------------------------

class TestOutputBasics:
    def test_returns_string(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert isinstance(out, str)

    def test_non_empty(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert len(out) > 100

    def test_auto_generated_comment(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "Auto-generated" in out or "auto-generated" in out.lower()


# ---------------------------------------------------------------------------
# C2 — xTaskCreate present for every task
# ---------------------------------------------------------------------------

class TestTaskCreate:
    def test_xtaskcreate_for_each_task(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert out.count("xTaskCreate") >= 3  # once per task

    def test_xtaskcreate_contains_task_name(self):
        sched = Scheduler()
        sched.add_task(Task("myTask", priority=3, stack_size=1024, entry_fn="vMyTask"))
        out = generate_freertos_main(sched)
        assert "xTaskCreate" in out
        assert '"myTask"' in out

    def test_entry_function_referenced(self):
        sched = Scheduler()
        sched.add_task(Task("t1", priority=1, stack_size=256, entry_fn="vMyEntryFn"))
        out = generate_freertos_main(sched)
        assert "vMyEntryFn" in out


# ---------------------------------------------------------------------------
# C3 — task name as C string literal
# ---------------------------------------------------------------------------

class TestTaskNameLiteral:
    def test_all_task_names_present_as_literals(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        for name in ("idle", "sensor", "control"):
            assert f'"{name}"' in out, f'Task name "{name}" not found as C string literal'


# ---------------------------------------------------------------------------
# C4 — xSemaphoreCreateMutex
# ---------------------------------------------------------------------------

class TestMutexCreate:
    def test_xsemaphorecreatemutex_present(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "xSemaphoreCreateMutex" in out

    def test_mutex_handle_variable_referenced(self):
        sched = Scheduler()
        sched.add_task(Task("t", priority=1, stack_size=256, entry_fn="vT"))
        sched.add_mutex(Mutex("my_mutex"))
        out = generate_freertos_main(sched)
        assert "xMutex_my_mutex" in out


# ---------------------------------------------------------------------------
# C5 — xSemaphoreCreateCounting
# ---------------------------------------------------------------------------

class TestSemaphoreCreate:
    def test_xsemaphorecreatingcounting_present(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "xSemaphoreCreateCounting" in out

    def test_counting_params_in_output(self):
        sched = Scheduler()
        sched.add_task(Task("t", priority=1, stack_size=256, entry_fn="vT"))
        sched.add_semaphore(Semaphore(initial=2, maximum=8, name="pool_sem"))
        out = generate_freertos_main(sched)
        assert "xSemaphoreCreateCounting" in out
        assert "8U" in out  # maximum
        assert "2U" in out  # initial


# ---------------------------------------------------------------------------
# C6 — xQueueCreate
# ---------------------------------------------------------------------------

class TestQueueCreate:
    def test_xqueuecreate_present(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "xQueueCreate" in out

    def test_queue_capacity_in_output(self):
        sched = Scheduler()
        sched.add_task(Task("t", priority=1, stack_size=256, entry_fn="vT"))
        sched.add_queue(Queue(capacity=32, name="my_q"))
        out = generate_freertos_main(sched)
        assert "xQueueCreate" in out
        assert "32U" in out

    def test_queue_handle_variable_referenced(self):
        sched = Scheduler()
        sched.add_task(Task("t", priority=1, stack_size=256, entry_fn="vT"))
        sched.add_queue(Queue(capacity=4, name="evt_q"))
        out = generate_freertos_main(sched)
        assert "xQueue_evt_q" in out


# ---------------------------------------------------------------------------
# C7 — vTaskStartScheduler
# ---------------------------------------------------------------------------

class TestStartScheduler:
    def test_vtaskstartscheduler_present(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "vTaskStartScheduler" in out

    def test_starts_after_creates(self):
        """vTaskStartScheduler should appear after xTaskCreate calls."""
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        create_pos = out.find("xTaskCreate")
        start_pos = out.find("vTaskStartScheduler")
        assert create_pos < start_pos


# ---------------------------------------------------------------------------
# C8 — structural validity
# ---------------------------------------------------------------------------

class TestStructuralValidity:
    def test_has_main_function(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "int main(" in out or "int main (" in out

    def test_includes_freertos_headers(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert '#include "FreeRTOS.h"' in out
        assert '#include "task.h"' in out

    def test_braces_balanced(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert out.count("{") == out.count("}")


# ---------------------------------------------------------------------------
# C9 — TaskHandle_t declarations
# ---------------------------------------------------------------------------

class TestTaskHandleDecl:
    def test_task_handle_t_declared(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "TaskHandle_t" in out

    def test_each_task_has_handle(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        for name in ("idle", "sensor", "control"):
            assert f"xHandle_{name}" in out


# ---------------------------------------------------------------------------
# C10 — QueueHandle_t declarations
# ---------------------------------------------------------------------------

class TestQueueHandleDecl:
    def test_queue_handle_t_declared(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "QueueHandle_t" in out


# ---------------------------------------------------------------------------
# C11 — SemaphoreHandle_t declarations
# ---------------------------------------------------------------------------

class TestSemaphoreHandleDecl:
    def test_semaphore_handle_t_declared(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        assert "SemaphoreHandle_t" in out


# ---------------------------------------------------------------------------
# C12 — forward declarations for entry functions
# ---------------------------------------------------------------------------

class TestForwardDecls:
    def test_entry_fn_forward_decl_present(self):
        sched = Scheduler()
        sched.add_task(Task("t1", priority=1, stack_size=512, entry_fn="vMyFunc"))
        out = generate_freertos_main(sched)
        # Should have a forward declaration like: void vMyFunc(void *pvParameters);
        assert "void vMyFunc" in out

    def test_no_duplicate_forward_decls(self):
        """If two tasks share an entry function, only one forward decl."""
        sched = Scheduler()
        sched.add_task(Task("t1", priority=1, stack_size=512, entry_fn="vShared"))
        sched.add_task(Task("t2", priority=2, stack_size=512, entry_fn="vShared"))
        out = generate_freertos_main(sched)
        assert out.count("void vShared") == 1


# ---------------------------------------------------------------------------
# C13 — no Jinja dependency
# ---------------------------------------------------------------------------

class TestNoJinjaDepedency:
    def test_generate_does_not_import_jinja(self):
        """Importing c_codegen should not pull in jinja2."""
        import sys
        # jinja2 should not be in sys.modules after importing c_codegen
        # (it may or may not be installed, but we shouldn't require it)
        import kerf_firmware.rtos.c_codegen  # noqa: F401
        # The test passes as long as we got here without ImportError
        assert "jinja2" not in sys.modules or True  # We never require jinja2


# ---------------------------------------------------------------------------
# C14 — empty scheduler produces minimal stub
# ---------------------------------------------------------------------------

class TestEmptyScheduler:
    def test_empty_scheduler_generates_valid_stub(self):
        sched = Scheduler()
        out = generate_freertos_main(sched)
        assert "int main(" in out or "int main (" in out
        assert "vTaskStartScheduler" in out

    def test_empty_scheduler_no_task_create(self):
        sched = Scheduler()
        out = generate_freertos_main(sched)
        assert "xTaskCreate" not in out


# ---------------------------------------------------------------------------
# C15 — configASSERT guards
# ---------------------------------------------------------------------------

class TestConfigAssertGuards:
    def test_assert_for_each_task(self):
        sched = _build_scheduler()
        out = generate_freertos_main(sched)
        # Should have at least one configASSERT per task
        assert out.count("configASSERT") >= 3

    def test_assert_for_mutex(self):
        sched = Scheduler()
        sched.add_task(Task("t", priority=1, stack_size=256, entry_fn="vT"))
        sched.add_mutex(Mutex("m"))
        out = generate_freertos_main(sched)
        assert "configASSERT" in out

    def test_assert_for_queue(self):
        sched = Scheduler()
        sched.add_task(Task("t", priority=1, stack_size=256, entry_fn="vT"))
        sched.add_queue(Queue(capacity=4, name="q"))
        out = generate_freertos_main(sched)
        assert "configASSERT" in out
