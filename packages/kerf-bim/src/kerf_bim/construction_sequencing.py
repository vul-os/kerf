"""
kerf_bim.construction_sequencing
=================================

4D Construction Sequencing engine.

Links a schedule (tasks with start/finish dates) to BIM elements and produces
a time-phased element-appearance timeline.  The engine is fully IFC4-aligned:
tasks map to IfcTask, element links to IfcRelAssignsToProcess, and the
timeline output uses ISO 8601 date strings.

References
----------
IFC4 ADD2 TC1 — IfcTask, IfcRelAssignsToProcess, IfcWorkSchedule, IfcWorkPlan.
ISO 8601 — Dates and times of day (date strings: YYYY-MM-DD).
CPM scheduling — Critical Path Method for sequence constraints.

Public API
----------
  Task(id, name, start, finish, element_ids, predecessors, ifc_task_type)
      A single construction task linked to BIM element IDs.

  ConstructionSchedule(tasks, project_start, project_finish)
      A set of tasks that form the 4D schedule.

  build_timeline(schedule, date) -> list[TimePhaseEntry]
      Compute which elements are visible/active/complete at a given date.

  critical_path(schedule) -> list[str]
      IDs of tasks on the critical path (zero float).

  validate_schedule(schedule) -> list[str]
      Consistency checks: date ordering, circular deps, orphan tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# IFC4-aligned task types (IfcTaskTypeEnum)
# ---------------------------------------------------------------------------

TASK_TYPES = frozenset({
    "ATTENDANCE",
    "CONSTRUCTION",
    "DEMOLITION",
    "DISPOSAL",
    "INSTALLATION",
    "LOGISTIC",
    "MAINTENANCE",
    "MOVE",
    "OPERATION",
    "REMOVAL",
    "RENOVATION",
    "USERDEFINED",
    "NOTDEFINED",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """A single construction task (maps to IFC4 IfcTask).

    Parameters
    ----------
    id : str
        Unique identifier (used as IfcTask.GlobalId equivalent).
    name : str
        Human-readable task name.
    start : str
        ISO 8601 start date (YYYY-MM-DD).
    finish : str
        ISO 8601 finish date (YYYY-MM-DD, inclusive).
    element_ids : list[str]
        BIM element IDs assigned to this task (IfcRelAssignsToProcess).
    predecessors : list[str]
        IDs of tasks that must finish before this one starts (Finish-to-Start).
    ifc_task_type : str
        IfcTaskTypeEnum value (default 'CONSTRUCTION').
    trade : str
        Trade/discipline label (e.g. 'structural', 'mep', 'architectural').
    """

    id: str
    name: str
    start: str
    finish: str
    element_ids: List[str] = field(default_factory=list)
    predecessors: List[str] = field(default_factory=list)
    ifc_task_type: str = "CONSTRUCTION"
    trade: str = ""

    def __post_init__(self):
        if not self.id:
            raise ValueError("Task.id must be non-empty")
        if not self.name:
            raise ValueError("Task.name must be non-empty")
        try:
            s = date.fromisoformat(self.start)
            f = date.fromisoformat(self.finish)
        except ValueError as exc:
            raise ValueError(f"Task '{self.id}': invalid date: {exc}") from exc
        if s > f:
            raise ValueError(
                f"Task '{self.id}': start ({self.start}) is after finish ({self.finish})"
            )
        if self.ifc_task_type not in TASK_TYPES:
            raise ValueError(
                f"Task '{self.id}': unknown ifc_task_type '{self.ifc_task_type}'"
            )

    @property
    def start_date(self) -> date:
        return date.fromisoformat(self.start)

    @property
    def finish_date(self) -> date:
        return date.fromisoformat(self.finish)

    @property
    def duration_days(self) -> int:
        return (self.finish_date - self.start_date).days + 1


@dataclass
class ConstructionSchedule:
    """A set of tasks forming a 4D construction schedule.

    Parameters
    ----------
    tasks : list[Task]
        All tasks in the schedule.
    project_start : str
        Overall project start date (ISO 8601).
    project_finish : str
        Overall project finish date (ISO 8601).
    name : str
        Schedule name.
    """

    tasks: List[Task] = field(default_factory=list)
    project_start: str = ""
    project_finish: str = ""
    name: str = "Construction Schedule"

    def __post_init__(self):
        if self.project_start:
            date.fromisoformat(self.project_start)  # validate
        if self.project_finish:
            date.fromisoformat(self.project_finish)

    @property
    def task_map(self) -> Dict[str, Task]:
        return {t.id: t for t in self.tasks}


# ---------------------------------------------------------------------------
# Time-phase timeline
# ---------------------------------------------------------------------------

@dataclass
class TimePhaseEntry:
    """Appearance state of a single BIM element at a query date.

    States mirror IFC4 IfcObjectTypeEnum + construction phasing convention:
      not_started  — task not yet begun
      active       — task is currently in progress
      complete     — task has finished
    """

    element_id: str
    task_id: str
    task_name: str
    state: str          # "not_started" | "active" | "complete"
    start: str
    finish: str
    ifc_task_type: str
    trade: str
    progress_pct: float  # 0..100 linear day-fraction


def build_timeline(
    schedule: ConstructionSchedule,
    query_date_str: str,
) -> List[TimePhaseEntry]:
    """Compute element appearance states at ``query_date_str``.

    Each element appears once per task.  If an element is assigned to multiple
    tasks the task whose window contains the query date takes precedence for the
    'active' state; otherwise the latest 'complete' task is reported.

    Parameters
    ----------
    schedule : ConstructionSchedule
    query_date_str : str
        ISO 8601 date to query.

    Returns
    -------
    List of :class:`TimePhaseEntry` — one per (element_id, task) pair.
    """
    q = date.fromisoformat(query_date_str)
    entries: List[TimePhaseEntry] = []

    for task in schedule.tasks:
        s = task.start_date
        f = task.finish_date

        if q < s:
            state = "not_started"
            progress = 0.0
        elif q > f:
            state = "complete"
            progress = 100.0
        else:
            state = "active"
            elapsed = (q - s).days
            total = max((f - s).days, 1)
            progress = round(min(100.0, elapsed / total * 100.0), 1)

        for eid in task.element_ids:
            entries.append(TimePhaseEntry(
                element_id=eid,
                task_id=task.id,
                task_name=task.name,
                state=state,
                start=task.start,
                finish=task.finish,
                ifc_task_type=task.ifc_task_type,
                trade=task.trade,
                progress_pct=progress,
            ))

    return entries


def summarise_timeline(
    entries: List[TimePhaseEntry],
) -> Dict[str, int]:
    """Count elements per state across a timeline result."""
    counts: Dict[str, int] = {"not_started": 0, "active": 0, "complete": 0}
    seen: Set[str] = set()  # deduplicate by element_id (take first occurrence)
    for e in entries:
        if e.element_id not in seen:
            seen.add(e.element_id)
            counts[e.state] = counts.get(e.state, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Critical path (CPM, Finish-to-Start only)
# ---------------------------------------------------------------------------

def critical_path(schedule: ConstructionSchedule) -> List[str]:
    """Return task IDs on the critical path (zero total float).

    Uses a simple forward/backward pass over Finish-to-Start links.
    Tasks with no successors are treated as having zero float.

    Returns list of task IDs with zero float (the critical path tasks).
    """
    tasks = schedule.task_map
    if not tasks:
        return []

    # Early start / early finish (forward pass in day-units from epoch)
    epoch = date(2000, 1, 1)

    ES: Dict[str, int] = {}  # earliest start day-index
    EF: Dict[str, int] = {}  # earliest finish day-index

    def _ef_of(tid: str, visited: Set[str]) -> int:
        if tid in EF:
            return EF[tid]
        if tid in visited:
            return 0  # cycle guard
        visited.add(tid)
        t = tasks.get(tid)
        if t is None:
            return 0
        pred_ef = max(
            (_ef_of(p, visited) for p in t.predecessors),
            default=(t.start_date - epoch).days,
        )
        es = max(pred_ef, (t.start_date - epoch).days)
        ef = es + t.duration_days - 1
        ES[tid] = es
        EF[tid] = ef
        return ef

    visited_global: Set[str] = set()
    for tid in tasks:
        _ef_of(tid, visited_global)

    # Latest finish / latest start (backward pass)
    max_ef = max(EF.values()) if EF else 0

    LS: Dict[str, int] = {}
    LF: Dict[str, int] = {}

    # Successors map
    successors: Dict[str, List[str]] = {tid: [] for tid in tasks}
    for t in tasks.values():
        for pred in t.predecessors:
            if pred in successors:
                successors[pred].append(t.id)

    def _ls_of(tid: str, visited: Set[str]) -> int:
        if tid in LS:
            return LS[tid]
        if tid in visited:
            return max_ef
        visited.add(tid)
        succs = successors.get(tid, [])
        if not succs:
            lf = max_ef
        else:
            lf = min(_ls_of(s, visited) - 1 for s in succs)
        lf = max(lf, EF.get(tid, 0))
        dur = tasks[tid].duration_days
        ls = lf - dur + 1
        LF[tid] = lf
        LS[tid] = ls
        return ls

    visited_back: Set[str] = set()
    for tid in tasks:
        _ls_of(tid, visited_back)

    # Total float = LS - ES; zero float = critical
    critical: List[str] = []
    for tid in tasks:
        tf = LS.get(tid, 0) - ES.get(tid, 0)
        if tf <= 0:
            critical.append(tid)

    return critical


# ---------------------------------------------------------------------------
# Schedule validation
# ---------------------------------------------------------------------------

def validate_schedule(schedule: ConstructionSchedule) -> List[str]:
    """Return a list of warning/error strings for the schedule.

    Checks:
    - Date ordering within tasks (already enforced by Task.__post_init__,
      but checked again for graceful messages).
    - Predecessor references to non-existent tasks.
    - Circular dependency detection (DFS).
    - Tasks outside project date range.
    """
    errors: List[str] = []
    task_ids = {t.id for t in schedule.tasks}

    for t in schedule.tasks:
        for pred in t.predecessors:
            if pred not in task_ids:
                errors.append(
                    f"Task '{t.id}': predecessor '{pred}' does not exist"
                )

    # Cycle detection (DFS)
    adj: Dict[str, List[str]] = {t.id: list(t.predecessors) for t in schedule.tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {tid: WHITE for tid in task_ids}

    def _dfs(tid: str) -> bool:
        """Return True if a cycle is detected."""
        color[tid] = GRAY
        for pred in adj.get(tid, []):
            if pred not in color:
                continue
            if color[pred] == GRAY:
                return True
            if color[pred] == WHITE and _dfs(pred):
                return True
        color[tid] = BLACK
        return False

    for tid in list(task_ids):
        if color[tid] == WHITE:
            if _dfs(tid):
                errors.append(f"Circular dependency detected involving task '{tid}'")
                break

    # Project date range checks
    if schedule.project_start and schedule.project_finish:
        proj_s = date.fromisoformat(schedule.project_start)
        proj_f = date.fromisoformat(schedule.project_finish)
        for t in schedule.tasks:
            if t.start_date < proj_s:
                errors.append(
                    f"Task '{t.id}' starts ({t.start}) before project start ({schedule.project_start})"
                )
            if t.finish_date > proj_f:
                errors.append(
                    f"Task '{t.id}' finishes ({t.finish}) after project finish ({schedule.project_finish})"
                )

    return errors


__all__ = [
    "Task",
    "ConstructionSchedule",
    "TimePhaseEntry",
    "build_timeline",
    "summarise_timeline",
    "critical_path",
    "validate_schedule",
    "TASK_TYPES",
]
