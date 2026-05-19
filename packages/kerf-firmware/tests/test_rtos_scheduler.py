"""
tests/test_rtos_scheduler.py — pytest suite for kerf_firmware.rtos.scheduler.

Scenarios covered
-----------------
T1  3-task scheduler — highest priority runs first every tick
T2  Round-robin — equal-priority tasks take turns in FIFO order
T3  Priority inversion detection via Scheduler.analyse()
T4  Queue full blocks the producer task
T5  Mutex acquire/release — basic sequencing
T6  Semaphore give/take — counting behaviour
T7  Deadlock potential detection (cycle in mutex-wait graph)
T8  Task blocked state is visible; unblocking restores READY state
T9  Scheduler.run() returns correct length log
T10 Duplicate task name raises ValueError
"""
from __future__ import annotations

import pytest

from kerf_firmware.rtos.scheduler import (
    AnalysisIssueKind,
    Mutex,
    Queue,
    Scheduler,
    Semaphore,
    Task,
    TaskState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_task(name: str, priority: int, period_ms=None) -> Task:
    return Task(
        name=name,
        priority=priority,
        stack_size=512,
        entry_fn=f"v{name.title()}Task",
        period_ms=period_ms,
    )


# ---------------------------------------------------------------------------
# T1 — highest priority runs first
# ---------------------------------------------------------------------------

class TestHighestPriorityFirst:
    def test_three_tasks_highest_runs_every_tick(self):
        """With three tasks at different priorities, the highest-priority task
        should be selected on every tick when all are READY."""
        sched = Scheduler()
        low = make_task("idle", priority=1)
        mid = make_task("sensor", priority=5)
        high = make_task("control", priority=10)
        for t in (low, mid, high):
            sched.add_task(t)

        log = sched.run(ticks=10)

        # Every tick the highest priority task should run
        for ran_task in log:
            assert ran_task is not None
            assert ran_task.name == "control", (
                f"Expected 'control' (prio 10) but got {ran_task!r}"
            )

    def test_high_priority_run_count_dominates(self):
        sched = Scheduler()
        low = make_task("low", priority=1)
        high = make_task("high", priority=9)
        sched.add_task(low)
        sched.add_task(high)

        sched.run(ticks=20)

        assert high._run_count == 20
        assert low._run_count == 0

    def test_highest_priority_task_selected_when_others_blocked(self):
        """When the highest-priority task is BLOCKED, the next one runs."""
        sched = Scheduler()
        low = make_task("low", priority=1)
        mid = make_task("mid", priority=5)
        high = make_task("high", priority=10)
        for t in (low, mid, high):
            sched.add_task(t)

        mutex = Mutex("lock")
        sched.add_mutex(mutex)
        # low acquires the mutex; high will block on it
        mutex.acquire(low)
        mutex.acquire(high)  # high is now BLOCKED

        ran = sched.tick()
        # high is blocked; mid (priority 5) should run
        assert ran is not None
        assert ran.name == "mid"


# ---------------------------------------------------------------------------
# T2 — round-robin at equal priority
# ---------------------------------------------------------------------------

class TestRoundRobin:
    def test_equal_priority_round_robin(self):
        """Three tasks at priority 5 should each run in turn (FIFO)."""
        sched = Scheduler()
        tasks = [make_task(f"t{i}", priority=5) for i in range(3)]
        for t in tasks:
            sched.add_task(t)

        log = sched.run(ticks=9)

        # Each task should appear in the log in round-robin order
        names = [t.name for t in log]
        # First rotation should be t0, t1, t2 (insertion order)
        assert names[:3] == ["t0", "t1", "t2"]
        # Second rotation should be t0, t1, t2 again
        assert names[3:6] == ["t0", "t1", "t2"]
        assert names[6:9] == ["t0", "t1", "t2"]

    def test_equal_priority_all_get_cpu_time(self):
        """No task at equal priority should be starved."""
        sched = Scheduler()
        tasks = [make_task(f"eq_{i}", priority=3) for i in range(4)]
        for t in tasks:
            sched.add_task(t)

        sched.run(ticks=40)

        run_counts = {t.name: t._run_count for t in tasks}
        # Each task should have run exactly 10 times (40 ticks / 4 tasks)
        for name, count in run_counts.items():
            assert count == 10, f"Task {name!r} ran {count} times, expected 10"

    def test_higher_priority_breaks_round_robin(self):
        """Adding a higher-priority task preempts the equal-priority round-robin."""
        sched = Scheduler()
        eq1 = make_task("eq1", priority=3)
        eq2 = make_task("eq2", priority=3)
        top = make_task("top", priority=7)
        for t in (eq1, eq2, top):
            sched.add_task(t)

        log = sched.run(ticks=6)
        names = [t.name for t in log]
        assert all(n == "top" for n in names)


# ---------------------------------------------------------------------------
# T3 — priority inversion detection
# ---------------------------------------------------------------------------

class TestPriorityInversion:
    def test_priority_inversion_detected(self):
        """Low-priority task holds mutex; high-priority task waits → inversion."""
        sched = Scheduler()
        low = make_task("low", priority=1)
        high = make_task("high", priority=10)
        sched.add_task(low)
        sched.add_task(high)

        mutex = Mutex("shared_resource")
        sched.add_mutex(mutex)

        # low acquires mutex; high tries and blocks
        mutex.acquire(low)
        mutex.acquire(high)  # high is now BLOCKED, waiting on mutex held by low

        issues = sched.analyse()
        inversion_issues = [
            i for i in issues if i.kind == AnalysisIssueKind.PRIORITY_INVERSION
        ]
        assert len(inversion_issues) >= 1, "Expected at least one priority inversion issue"

        issue = inversion_issues[0]
        assert "high" in issue.tasks_involved
        assert "low" in issue.tasks_involved
        assert "priority inversion" in issue.description.lower()

    def test_no_priority_inversion_when_equal_priority(self):
        """Equal-priority tasks waiting on a mutex is not a priority inversion."""
        sched = Scheduler()
        t1 = make_task("t1", priority=5)
        t2 = make_task("t2", priority=5)
        sched.add_task(t1)
        sched.add_task(t2)

        mutex = Mutex("eq_mutex")
        sched.add_mutex(mutex)

        mutex.acquire(t1)
        mutex.acquire(t2)  # t2 blocks; same priority → no inversion

        issues = sched.analyse()
        inversions = [i for i in issues if i.kind == AnalysisIssueKind.PRIORITY_INVERSION]
        assert inversions == []

    def test_no_inversion_when_mutex_free(self):
        sched = Scheduler()
        t1 = make_task("t1", priority=1)
        sched.add_task(t1)
        mutex = Mutex("free_mutex")
        sched.add_mutex(mutex)

        issues = sched.analyse()
        assert all(i.kind != AnalysisIssueKind.PRIORITY_INVERSION for i in issues)

    def test_inversion_description_mentions_tasks_and_mutex(self):
        sched = Scheduler()
        low = make_task("worker", priority=2)
        high = make_task("isr_handler", priority=8)
        sched.add_task(low)
        sched.add_task(high)

        mutex = Mutex("periph_lock")
        sched.add_mutex(mutex)

        mutex.acquire(low)
        mutex.acquire(high)

        issues = sched.analyse()
        issue = next(i for i in issues if i.kind == AnalysisIssueKind.PRIORITY_INVERSION)
        assert "periph_lock" in issue.description
        assert "isr_handler" in issue.description
        assert "worker" in issue.description


# ---------------------------------------------------------------------------
# T4 — queue full blocks producer
# ---------------------------------------------------------------------------

class TestQueueFullBlocksProducer:
    def test_send_to_full_queue_blocks_task(self):
        """Sending to a full queue puts the sender in BLOCKED state."""
        sched = Scheduler()
        producer = make_task("producer", priority=3)
        consumer = make_task("consumer", priority=3)
        sched.add_task(producer)
        sched.add_task(consumer)

        queue = Queue(capacity=2, name="data_q")
        sched.add_queue(queue)

        # Fill the queue
        ok1 = queue.send(producer, "item1")
        ok2 = queue.send(producer, "item2")
        assert ok1 is True
        assert ok2 is True
        assert queue.full

        # One more send should block the producer
        ok3 = queue.send(producer, "item3")
        assert ok3 is False
        assert producer.state == TaskState.BLOCKED

    def test_consuming_from_full_queue_unblocks_producer(self):
        """When a full queue has an item consumed, the blocked producer is unblocked."""
        sched = Scheduler()
        producer = make_task("producer", priority=3)
        consumer = make_task("consumer", priority=5)
        sched.add_task(producer)
        sched.add_task(consumer)

        queue = Queue(capacity=1, name="tiny_q")
        sched.add_queue(queue)

        # Fill queue and block producer
        queue.send(producer, "a")
        queue.send(producer, "b")  # blocks producer
        assert producer.state == TaskState.BLOCKED

        # Consumer receives — should unblock producer
        ok, item = queue.receive(consumer)
        assert ok is True
        assert item == "a"
        assert producer.state == TaskState.READY

    def test_receive_from_empty_queue_blocks_consumer(self):
        """Receiving from an empty queue blocks the consumer."""
        sched = Scheduler()
        consumer = make_task("consumer", priority=3)
        sched.add_task(consumer)

        queue = Queue(capacity=5, name="empty_q")
        sched.add_queue(queue)

        ok, item = queue.receive(consumer)
        assert ok is False
        assert item is None
        assert consumer.state == TaskState.BLOCKED

    def test_queue_size_tracked_correctly(self):
        queue = Queue(capacity=3, name="sized_q")
        producer = make_task("prod", priority=1)

        assert queue.size == 0
        queue.send(producer, 1)
        queue.send(producer, 2)
        assert queue.size == 2
        assert not queue.full
        queue.send(producer, 3)
        assert queue.size == 3
        assert queue.full


# ---------------------------------------------------------------------------
# T5 — mutex acquire/release sequencing
# ---------------------------------------------------------------------------

class TestMutexAcquireRelease:
    def test_acquire_free_mutex_succeeds(self):
        mutex = Mutex("m1")
        t = make_task("t", priority=1)
        ok = mutex.acquire(t)
        assert ok is True
        assert mutex.holder is t

    def test_release_hands_off_to_waiter(self):
        mutex = Mutex("m2")
        t1 = make_task("t1", priority=1)
        t2 = make_task("t2", priority=2)

        mutex.acquire(t1)
        mutex.acquire(t2)  # blocks t2

        assert t2.state == TaskState.BLOCKED
        unblocked = mutex.release(t1)
        assert unblocked is t2
        assert mutex.holder is t2
        assert t2.state == TaskState.READY

    def test_release_by_non_holder_raises(self):
        mutex = Mutex("m3")
        t1 = make_task("t1", priority=1)
        t2 = make_task("t2", priority=2)
        mutex.acquire(t1)
        with pytest.raises(RuntimeError):
            mutex.release(t2)

    def test_highest_priority_waiter_gets_mutex_first(self):
        """When multiple tasks wait, the highest-priority one is served first."""
        mutex = Mutex("m4")
        holder = make_task("holder", priority=1)
        low_waiter = make_task("low_w", priority=2)
        high_waiter = make_task("high_w", priority=9)

        mutex.acquire(holder)
        mutex.acquire(low_waiter)
        mutex.acquire(high_waiter)

        unblocked = mutex.release(holder)
        assert unblocked is high_waiter
        assert mutex.holder is high_waiter


# ---------------------------------------------------------------------------
# T6 — semaphore counting behaviour
# ---------------------------------------------------------------------------

class TestSemaphore:
    def test_take_decrements_count(self):
        sem = Semaphore(initial=3, maximum=3, name="s1")
        t = make_task("t", priority=1)
        sem.take(t)
        assert sem.count == 2

    def test_take_to_zero_then_block(self):
        sem = Semaphore(initial=1, maximum=1, name="s2")
        t1 = make_task("t1", priority=1)
        t2 = make_task("t2", priority=2)
        sem.take(t1)
        assert sem.count == 0
        ok = sem.take(t2)
        assert ok is False
        assert t2.state == TaskState.BLOCKED

    def test_give_unblocks_waiter(self):
        sem = Semaphore(initial=0, maximum=1, name="s3")
        t = make_task("t", priority=1)
        sem.take(t)  # will block immediately
        assert t.state == TaskState.BLOCKED
        unblocked = sem.give()
        assert unblocked is t
        assert t.state == TaskState.READY

    def test_give_increments_when_no_waiters(self):
        sem = Semaphore(initial=0, maximum=3, name="s4")
        sem.give()
        assert sem.count == 1
        sem.give()
        assert sem.count == 2

    def test_semaphore_invalid_args(self):
        with pytest.raises(ValueError):
            Semaphore(initial=-1)
        with pytest.raises(ValueError):
            Semaphore(initial=5, maximum=3)
        with pytest.raises(ValueError):
            Semaphore(maximum=0)


# ---------------------------------------------------------------------------
# T7 — deadlock potential detection
# ---------------------------------------------------------------------------

class TestDeadlockDetection:
    def test_deadlock_cycle_detected(self):
        """A→B→A cycle in the mutex-wait graph is flagged as deadlock potential."""
        sched = Scheduler()
        t_a = make_task("taskA", priority=5)
        t_b = make_task("taskB", priority=5)
        sched.add_task(t_a)
        sched.add_task(t_b)

        mutex1 = Mutex("lock1")
        mutex2 = Mutex("lock2")
        sched.add_mutex(mutex1)
        sched.add_mutex(mutex2)

        # taskA holds lock1, waits for lock2
        # taskB holds lock2, waits for lock1
        mutex1.acquire(t_a)
        mutex2.acquire(t_b)
        mutex2.acquire(t_a)  # taskA blocks waiting for lock2 (held by taskB)
        mutex1.acquire(t_b)  # taskB blocks waiting for lock1 (held by taskA)

        issues = sched.analyse()
        deadlocks = [i for i in issues if i.kind == AnalysisIssueKind.DEADLOCK_POTENTIAL]
        assert len(deadlocks) >= 1

    def test_no_deadlock_when_no_cycle(self):
        """A simple chain (A waits for B, B holds nothing) is not a deadlock."""
        sched = Scheduler()
        t_a = make_task("taskA", priority=3)
        t_b = make_task("taskB", priority=5)
        sched.add_task(t_a)
        sched.add_task(t_b)

        mutex = Mutex("single")
        sched.add_mutex(mutex)

        mutex.acquire(t_b)   # taskB holds the mutex
        mutex.acquire(t_a)   # taskA waits — but taskB is not waiting on anything

        issues = sched.analyse()
        deadlocks = [i for i in issues if i.kind == AnalysisIssueKind.DEADLOCK_POTENTIAL]
        assert deadlocks == []


# ---------------------------------------------------------------------------
# T8 — task state transitions
# ---------------------------------------------------------------------------

class TestTaskStateTransitions:
    def test_task_starts_in_ready_state(self):
        t = make_task("new_task", priority=3)
        assert t.state == TaskState.READY

    def test_tick_sets_chosen_task_to_running(self):
        sched = Scheduler()
        t = make_task("solo", priority=5)
        sched.add_task(t)
        sched.tick()
        # After tick, the task is marked RUNNING during the tick; at start of
        # next tick it is moved back to READY.  Check run_count instead.
        assert t._run_count == 1

    def test_blocked_task_is_not_scheduled(self):
        sched = Scheduler()
        t1 = make_task("blocked", priority=10)
        t2 = make_task("running", priority=1)
        sched.add_task(t1)
        sched.add_task(t2)

        mutex = Mutex("bk_mutex")
        sched.add_mutex(mutex)
        blocker = make_task("blocker", priority=5)
        sched.add_task(blocker)
        mutex.acquire(blocker)
        mutex.acquire(t1)  # t1 is now BLOCKED

        ran = sched.tick()
        # blocker (prio 5) > running (prio 1), and t1 is blocked
        assert ran is not None
        assert ran.name == "blocker"


# ---------------------------------------------------------------------------
# T9 — Scheduler.run() length
# ---------------------------------------------------------------------------

class TestSchedulerRun:
    def test_run_returns_correct_length(self):
        sched = Scheduler()
        t = make_task("t", priority=1)
        sched.add_task(t)
        log = sched.run(ticks=42)
        assert len(log) == 42

    def test_run_none_when_no_tasks(self):
        sched = Scheduler()
        log = sched.run(ticks=5)
        assert all(item is None for item in log)

    def test_tick_count_increments(self):
        sched = Scheduler()
        t = make_task("t", priority=1)
        sched.add_task(t)
        sched.run(ticks=7)
        assert sched.tick_count == 7


# ---------------------------------------------------------------------------
# T10 — duplicate task name rejected
# ---------------------------------------------------------------------------

class TestDuplicateName:
    def test_duplicate_task_name_raises(self):
        sched = Scheduler()
        t1 = make_task("dup", priority=1)
        t2 = make_task("dup", priority=2)
        sched.add_task(t1)
        with pytest.raises(ValueError, match="Duplicate task name"):
            sched.add_task(t2)

    def test_invalid_priority_raises(self):
        with pytest.raises(ValueError):
            Task("bad", priority=-1, stack_size=512, entry_fn="fn")

    def test_invalid_stack_size_raises(self):
        with pytest.raises(ValueError):
            Task("bad", priority=1, stack_size=0, entry_fn="fn")
