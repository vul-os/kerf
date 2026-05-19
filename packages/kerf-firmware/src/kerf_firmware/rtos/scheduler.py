"""
kerf_firmware.rtos.scheduler — pure-Python FreeRTOS-equivalent scheduler primitives.

Design notes
------------
- Priority is a non-negative integer; **higher number = higher priority**
  (mirrors FreeRTOS convention where configMAX_PRIORITIES-1 is highest).
- The scheduler simulator is *cooperative* within a tick but *preemptive*
  across ticks: each call to Scheduler.tick() runs the highest-priority
  ready task for that tick, then advances the clock.
- Tasks with equal priority are round-robin'd using a FIFO run queue so
  that every task eventually gets CPU time.
- Mutex/Semaphore/Queue operations are synchronous within the simulator;
  blocking is modelled by keeping a task in BLOCKED state until the
  resource becomes available.

Static analysis (Scheduler.analyse())
--------------------------------------
Priority inversion: task A (low priority) holds a mutex that task B
  (higher priority) is waiting for, while task A is not running.
Deadlock potential: a cycle exists in the mutex-wait graph
  (task A waits on mutex held by task B which waits on a mutex held by A).
"""

from __future__ import annotations

import collections
import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskState(enum.Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class AnalysisIssueKind(enum.Enum):
    PRIORITY_INVERSION = "priority_inversion"
    DEADLOCK_POTENTIAL = "deadlock_potential"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AnalysisIssue:
    kind: AnalysisIssueKind
    description: str
    tasks_involved: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class Task:
    """Represents a single RTOS task.

    Parameters
    ----------
    name : str
        Unique task name.
    priority : int
        FreeRTOS-style priority (higher = more urgent, >= 0).
    stack_size : int
        Stack size in bytes (used for codegen; not simulated in RAM).
    entry_fn : str
        Name of the C entry-point function (used for codegen).
    period_ms : int | None
        For periodic tasks, the period in milliseconds.  ``None`` means
        the task runs as fast as the scheduler allows (event-driven).
    """

    def __init__(
        self,
        name: str,
        priority: int,
        stack_size: int,
        entry_fn: str,
        period_ms: Optional[int] = None,
    ) -> None:
        if priority < 0:
            raise ValueError(f"Task priority must be >= 0, got {priority!r}")
        if stack_size <= 0:
            raise ValueError(f"stack_size must be > 0, got {stack_size!r}")
        self.name = name
        self.priority = priority
        self.stack_size = stack_size
        self.entry_fn = entry_fn
        self.period_ms = period_ms

        # Simulator state
        self.state: TaskState = TaskState.READY
        self._run_count: int = 0
        self._blocked_on: Optional[object] = None  # Mutex | Semaphore | Queue

    # ------------------------------------------------------------------
    # Internal helpers (used by Scheduler)
    # ------------------------------------------------------------------

    def _mark_running(self) -> None:
        self.state = TaskState.RUNNING
        self._run_count += 1

    def _mark_ready(self) -> None:
        if self.state not in (TaskState.DELETED, TaskState.SUSPENDED):
            self.state = TaskState.READY

    def _block_on(self, resource: object) -> None:
        self.state = TaskState.BLOCKED
        self._blocked_on = resource

    def _unblock(self) -> None:
        self._blocked_on = None
        self.state = TaskState.READY

    def __repr__(self) -> str:
        return (
            f"Task(name={self.name!r}, priority={self.priority}, "
            f"state={self.state.value})"
        )


class Mutex:
    """Binary mutex.  Tracks the holding task for priority-inversion analysis."""

    def __init__(self, name: str = "") -> None:
        self.name = name or f"mutex_{id(self):x}"
        self._holder: Optional[Task] = None
        self._waiters: collections.deque[Task] = collections.deque()

    # ------------------------------------------------------------------
    # Simulator API (called by Scheduler.run_step)
    # ------------------------------------------------------------------

    def acquire(self, task: Task) -> bool:
        """Try to acquire.  Returns True if acquired, False if blocked."""
        if self._holder is None:
            self._holder = task
            return True
        # Mutex held by someone else — block caller
        if task not in self._waiters:
            self._waiters.append(task)
        task._block_on(self)
        return False

    def release(self, task: Task) -> Optional[Task]:
        """Release the mutex.  Returns the next task that was unblocked, if any."""
        if self._holder is not task:
            raise RuntimeError(
                f"Task {task.name!r} tried to release mutex {self.name!r} "
                f"held by {self._holder!r}"
            )
        self._holder = None
        if self._waiters:
            # Hand off to highest-priority waiter
            next_task = max(self._waiters, key=lambda t: t.priority)
            self._waiters.remove(next_task)
            self._holder = next_task
            next_task._unblock()
            return next_task
        return None

    @property
    def holder(self) -> Optional[Task]:
        return self._holder

    @property
    def waiters(self) -> list[Task]:
        return list(self._waiters)

    def __repr__(self) -> str:
        holder_name = self._holder.name if self._holder else "None"
        return f"Mutex(name={self.name!r}, holder={holder_name!r})"


class Semaphore:
    """Counting semaphore.

    Parameters
    ----------
    initial : int
        Initial count (>= 0).
    maximum : int
        Maximum count.  Defaults to ``initial`` for a binary semaphore-like
        object, or can be set higher for a counting semaphore.
    """

    def __init__(self, initial: int = 1, maximum: int = 1, name: str = "") -> None:
        if initial < 0:
            raise ValueError("Semaphore initial count must be >= 0")
        if maximum < 1:
            raise ValueError("Semaphore maximum count must be >= 1")
        if initial > maximum:
            raise ValueError("Semaphore initial count must be <= maximum")
        self.name = name or f"sem_{id(self):x}"
        self._count = initial
        self._maximum = maximum
        self._waiters: collections.deque[Task] = collections.deque()

    def take(self, task: Task) -> bool:
        """Take (decrement) the semaphore.  Returns True if taken, False if blocked."""
        if self._count > 0:
            self._count -= 1
            return True
        if task not in self._waiters:
            self._waiters.append(task)
        task._block_on(self)
        return False

    def give(self) -> Optional[Task]:
        """Give (increment) the semaphore.  Returns unblocked task if any."""
        if self._waiters:
            next_task = self._waiters.popleft()
            next_task._unblock()
            return next_task
        if self._count < self._maximum:
            self._count += 1
        return None

    @property
    def count(self) -> int:
        return self._count

    def __repr__(self) -> str:
        return f"Semaphore(name={self.name!r}, count={self._count}/{self._maximum})"


class Queue:
    """A bounded FIFO message queue.

    Parameters
    ----------
    capacity : int
        Maximum number of items the queue can hold.
    """

    def __init__(self, capacity: int = 10, name: str = "") -> None:
        if capacity < 1:
            raise ValueError("Queue capacity must be >= 1")
        self.name = name or f"queue_{id(self):x}"
        self._capacity = capacity
        self._items: collections.deque[Any] = collections.deque()
        self._send_waiters: collections.deque[tuple[Task, Any]] = collections.deque()
        self._recv_waiters: collections.deque[Task] = collections.deque()

    # ------------------------------------------------------------------
    # Simulator API
    # ------------------------------------------------------------------

    def send(self, task: Task, item: Any) -> bool:
        """Send an item.  Returns True if sent, False if queue full (task blocked)."""
        if len(self._items) < self._capacity:
            self._items.append(item)
            # Unblock a waiting receiver if any
            if self._recv_waiters:
                recv_task = self._recv_waiters.popleft()
                recv_task._unblock()
            return True
        # Queue full — block sender
        if not any(t is task for t, _ in self._send_waiters):
            self._send_waiters.append((task, item))
        task._block_on(self)
        return False

    def receive(self, task: Task) -> tuple[bool, Any]:
        """Receive an item.  Returns (True, item) if available, (False, None) if empty."""
        if self._items:
            item = self._items.popleft()
            # Unblock a waiting sender if any
            if self._send_waiters:
                send_task, pending_item = self._send_waiters.popleft()
                self._items.append(pending_item)
                send_task._unblock()
            return True, item
        # Queue empty — block receiver
        if task not in self._recv_waiters:
            self._recv_waiters.append(task)
        task._block_on(self)
        return False, None

    @property
    def size(self) -> int:
        return len(self._items)

    @property
    def full(self) -> bool:
        return len(self._items) >= self._capacity

    @property
    def empty(self) -> bool:
        return len(self._items) == 0

    def __repr__(self) -> str:
        return (
            f"Queue(name={self.name!r}, size={self.size}/{self._capacity})"
        )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """Priority-based preemptive scheduler simulator.

    The scheduler maintains a set of registered tasks and a simulated clock.
    Each call to :meth:`tick` advances the clock by one unit and runs the
    highest-priority READY task for that tick.  Tasks with equal priority
    are served in round-robin order.

    Usage example::

        sched = Scheduler()
        t1 = Task("idle", priority=1, stack_size=512, entry_fn="vIdleTask")
        t2 = Task("sensor", priority=5, stack_size=1024, entry_fn="vSensorTask", period_ms=10)
        sched.add_task(t1)
        sched.add_task(t2)
        run_log = sched.run(ticks=20)
    """

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._mutexes: list[Mutex] = []
        self._semaphores: list[Semaphore] = []
        self._queues: list[Queue] = []
        self._tick: int = 0
        # Round-robin pointer per priority level (maps priority → deque index offset)
        self._rr_queues: dict[int, collections.deque[Task]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_task(self, task: Task) -> None:
        """Register a task with the scheduler."""
        if any(t.name == task.name for t in self._tasks):
            raise ValueError(f"Duplicate task name: {task.name!r}")
        self._tasks.append(task)
        prio = task.priority
        if prio not in self._rr_queues:
            self._rr_queues[prio] = collections.deque()
        self._rr_queues[prio].append(task)

    def add_mutex(self, mutex: Mutex) -> None:
        self._mutexes.append(mutex)

    def add_semaphore(self, sem: Semaphore) -> None:
        self._semaphores.append(sem)

    def add_queue(self, queue: Queue) -> None:
        self._queues.append(queue)

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def tick(self) -> Optional[Task]:
        """Advance one tick.  Runs the highest-priority READY task.

        Returns the task that ran this tick, or None if no task was ready.
        """
        # Mark any previously running task as ready again
        for t in self._tasks:
            if t.state == TaskState.RUNNING:
                t._mark_ready()

        chosen = self._pick_next()
        if chosen is not None:
            chosen._mark_running()
            # Rotate the round-robin deque for this priority so next equal-
            # priority task is first in line next time.
            prio_q = self._rr_queues.get(chosen.priority)
            if prio_q and prio_q[0] is chosen:
                prio_q.rotate(-1)

        self._tick += 1
        return chosen

    def run(self, ticks: int) -> list[Optional[Task]]:
        """Run the scheduler for *ticks* ticks.

        Returns a list of tasks (or None) that ran each tick.
        """
        log: list[Optional[Task]] = []
        for _ in range(ticks):
            log.append(self.tick())
        return log

    def _pick_next(self) -> Optional[Task]:
        """Return the highest-priority READY task using round-robin for ties."""
        ready = [t for t in self._tasks if t.state == TaskState.READY]
        if not ready:
            return None
        max_prio = max(t.priority for t in ready)
        # Use the round-robin deque for this priority level
        prio_q = self._rr_queues.get(max_prio, collections.deque())
        # Find first task in the RR deque that is READY
        for t in prio_q:
            if t.state == TaskState.READY:
                return t
        # Fallback (shouldn't normally reach here)
        return max(ready, key=lambda t: t.priority)

    # ------------------------------------------------------------------
    # Static analysis
    # ------------------------------------------------------------------

    def analyse(self) -> list[AnalysisIssue]:
        """Run static analysis on the current task/resource graph.

        Detects:
        - Priority inversion: a low-priority task holds a mutex that a
          higher-priority task is waiting for.
        - Deadlock potential: a cycle in the mutex-wait graph.

        Returns a list of :class:`AnalysisIssue` objects.
        """
        issues: list[AnalysisIssue] = []
        issues.extend(self._detect_priority_inversion())
        issues.extend(self._detect_deadlock_potential())
        return issues

    def _detect_priority_inversion(self) -> list[AnalysisIssue]:
        issues: list[AnalysisIssue] = []
        for mutex in self._mutexes:
            holder = mutex.holder
            if holder is None:
                continue
            for waiter in mutex.waiters:
                if waiter.priority > holder.priority:
                    issues.append(
                        AnalysisIssue(
                            kind=AnalysisIssueKind.PRIORITY_INVERSION,
                            description=(
                                f"Priority inversion: task '{waiter.name}' "
                                f"(priority {waiter.priority}) is waiting on "
                                f"mutex '{mutex.name}' held by task '{holder.name}' "
                                f"(priority {holder.priority})"
                            ),
                            tasks_involved=[waiter.name, holder.name],
                        )
                    )
        return issues

    def _detect_deadlock_potential(self) -> list[AnalysisIssue]:
        """Detect cycles in the mutex-wait graph using DFS."""
        # Build wait-for graph: task A → task B means A is waiting on a
        # mutex that is held by B.
        wait_for: dict[str, set[str]] = {t.name: set() for t in self._tasks}
        for mutex in self._mutexes:
            holder = mutex.holder
            if holder is None:
                continue
            for waiter in mutex.waiters:
                wait_for[waiter.name].add(holder.name)

        # DFS cycle detection
        visited: set[str] = set()
        in_stack: set[str] = set()
        cycles: list[list[str]] = []

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            in_stack.add(node)
            for neighbour in wait_for.get(node, set()):
                if neighbour not in visited:
                    dfs(neighbour, path + [neighbour])
                elif neighbour in in_stack:
                    # Found a cycle — extract it
                    cycle_start = path.index(neighbour)
                    cycle = path[cycle_start:]
                    cycles.append(cycle)
            in_stack.discard(node)

        for task_name in list(wait_for.keys()):
            if task_name not in visited:
                dfs(task_name, [task_name])

        issues: list[AnalysisIssue] = []
        # Deduplicate cycles (a cycle A→B→A and B→A→B are the same)
        seen_cycles: set[frozenset] = set()
        for cycle in cycles:
            key = frozenset(cycle)
            if key not in seen_cycles:
                seen_cycles.add(key)
                issues.append(
                    AnalysisIssue(
                        kind=AnalysisIssueKind.DEADLOCK_POTENTIAL,
                        description=(
                            f"Deadlock potential: cycle detected among tasks "
                            f"{cycle}"
                        ),
                        tasks_involved=cycle,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def tasks(self) -> list[Task]:
        return list(self._tasks)

    @property
    def tick_count(self) -> int:
        return self._tick

    def task_by_name(self, name: str) -> Task:
        for t in self._tasks:
            if t.name == name:
                return t
        raise KeyError(f"No task named {name!r}")

    def __repr__(self) -> str:
        return f"Scheduler(tasks={len(self._tasks)}, tick={self._tick})"
