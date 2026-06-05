"""
Tests for kerf_bim.construction_sequencing — 4D construction sequencing.

Coverage
--------
- Task creation: valid + invalid (date ordering, bad ifc_task_type)
- ConstructionSchedule: task_map, date range
- build_timeline: not_started / active / complete states + progress_pct
- summarise_timeline: deduplication, correct counts
- critical_path: simple chain, parallel tasks
- validate_schedule: circular deps, missing predecessor, out-of-range dates
- LLM tool: bim_4d_build_timeline round-trip
- LLM tool: bim_4d_critical_path
- LLM tool: bim_4d_validate_schedule
- LLM tool: bim_4d_summarise_date
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_bim.construction_sequencing import (
    ConstructionSchedule,
    Task,
    TimePhaseEntry,
    build_timeline,
    critical_path,
    summarise_timeline,
    validate_schedule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _task(id, start, finish, preds=None, elements=None, trade="", ifc_type="CONSTRUCTION"):
    return Task(
        id=id,
        name=f"Task {id}",
        start=start,
        finish=finish,
        element_ids=elements or [],
        predecessors=preds or [],
        ifc_task_type=ifc_type,
        trade=trade,
    )


def _schedule(*tasks, ps="2025-01-01", pf="2025-12-31"):
    return ConstructionSchedule(tasks=list(tasks), project_start=ps, project_finish=pf)


# ---------------------------------------------------------------------------
# 1. Task creation
# ---------------------------------------------------------------------------

class TestTaskCreation:
    def test_valid_task(self):
        t = _task("T1", "2025-01-01", "2025-01-10")
        assert t.id == "T1"
        assert t.duration_days == 10

    def test_invalid_start_after_finish(self):
        with pytest.raises(ValueError, match="start.*after finish"):
            _task("T1", "2025-01-10", "2025-01-01")

    def test_invalid_ifc_task_type(self):
        with pytest.raises(ValueError, match="unknown ifc_task_type"):
            Task(id="T1", name="X", start="2025-01-01", finish="2025-01-05", ifc_task_type="INVALID")

    def test_empty_id_raises(self):
        with pytest.raises(ValueError):
            Task(id="", name="X", start="2025-01-01", finish="2025-01-05")

    def test_duration_days_single_day(self):
        t = _task("T1", "2025-06-01", "2025-06-01")
        assert t.duration_days == 1

    def test_all_ifc_task_types_accepted(self):
        from kerf_bim.construction_sequencing import TASK_TYPES
        for tt in TASK_TYPES:
            Task(id="TX", name="X", start="2025-01-01", finish="2025-01-02", ifc_task_type=tt)


# ---------------------------------------------------------------------------
# 2. Build timeline
# ---------------------------------------------------------------------------

class TestBuildTimeline:
    def _sched(self):
        return _schedule(
            _task("T1", "2025-01-01", "2025-01-10", elements=["wall-001", "wall-002"]),
            _task("T2", "2025-01-15", "2025-01-25", elements=["col-001"]),
        )

    def test_not_started(self):
        entries = build_timeline(self._sched(), "2024-12-31")
        states = {e.element_id: e.state for e in entries}
        assert states["wall-001"] == "not_started"
        assert states["col-001"] == "not_started"

    def test_active_first_day(self):
        entries = build_timeline(self._sched(), "2025-01-01")
        states = {e.element_id: e.state for e in entries}
        assert states["wall-001"] == "active"
        assert states["col-001"] == "not_started"

    def test_active_progress_midpoint(self):
        entries = build_timeline(self._sched(), "2025-01-05")
        wall = next(e for e in entries if e.element_id == "wall-001")
        assert wall.state == "active"
        assert 30 < wall.progress_pct < 70

    def test_complete_after_finish(self):
        entries = build_timeline(self._sched(), "2025-01-11")
        states = {e.element_id: e.state for e in entries}
        assert states["wall-001"] == "complete"
        assert states["wall-002"] == "complete"

    def test_complete_progress_100(self):
        entries = build_timeline(self._sched(), "2025-02-01")
        for e in entries:
            assert e.progress_pct == 100.0

    def test_empty_schedule(self):
        entries = build_timeline(ConstructionSchedule(), "2025-01-01")
        assert entries == []

    def test_task_with_no_elements(self):
        sched = _schedule(_task("T1", "2025-01-01", "2025-01-10"))
        entries = build_timeline(sched, "2025-01-05")
        assert len(entries) == 0

    def test_multiple_elements_per_task(self):
        sched = _schedule(_task("T1", "2025-01-01", "2025-01-10", elements=["a", "b", "c"]))
        entries = build_timeline(sched, "2025-01-05")
        assert len(entries) == 3
        assert all(e.task_id == "T1" for e in entries)


# ---------------------------------------------------------------------------
# 3. Summarise timeline
# ---------------------------------------------------------------------------

class TestSummariseTimeline:
    def test_counts_unique_elements(self):
        sched = _schedule(
            _task("T1", "2025-01-01", "2025-01-10", elements=["a", "b"]),
            _task("T2", "2025-01-15", "2025-01-20", elements=["c"]),
        )
        entries = build_timeline(sched, "2025-01-05")
        summary = summarise_timeline(entries)
        assert summary["active"] == 2
        assert summary["not_started"] == 1

    def test_deduplicates_element_with_two_tasks(self):
        # Same element in two tasks — should count once
        sched = _schedule(
            _task("T1", "2025-01-01", "2025-01-10", elements=["a"]),
            _task("T2", "2025-01-05", "2025-01-15", elements=["a"]),
        )
        entries = build_timeline(sched, "2025-01-07")
        summary = summarise_timeline(entries)
        total = sum(summary.values())
        assert total == 1

    def test_all_complete(self):
        sched = _schedule(
            _task("T1", "2025-01-01", "2025-01-05", elements=["x"]),
            _task("T2", "2025-01-01", "2025-01-05", elements=["y"]),
        )
        entries = build_timeline(sched, "2025-02-01")
        summary = summarise_timeline(entries)
        assert summary["complete"] == 2
        assert summary["active"] == 0
        assert summary["not_started"] == 0


# ---------------------------------------------------------------------------
# 4. Critical path
# ---------------------------------------------------------------------------

class TestCriticalPath:
    def test_simple_chain(self):
        sched = _schedule(
            _task("T1", "2025-01-01", "2025-01-10"),
            _task("T2", "2025-01-11", "2025-01-20", preds=["T1"]),
            _task("T3", "2025-01-21", "2025-01-31", preds=["T2"]),
        )
        cp = critical_path(sched)
        assert "T3" in cp  # T3 has no successors

    def test_empty_schedule(self):
        cp = critical_path(ConstructionSchedule())
        assert cp == []

    def test_single_task(self):
        sched = _schedule(_task("T1", "2025-01-01", "2025-01-10"))
        cp = critical_path(sched)
        assert "T1" in cp

    def test_parallel_tasks_one_critical(self):
        sched = _schedule(
            _task("T1", "2025-01-01", "2025-01-05"),          # short
            _task("T2", "2025-01-01", "2025-01-20"),          # long (critical)
            _task("T3", "2025-01-21", "2025-01-31", preds=["T1", "T2"]),
        )
        cp = critical_path(sched)
        assert "T3" in cp


# ---------------------------------------------------------------------------
# 5. Validate schedule
# ---------------------------------------------------------------------------

class TestValidateSchedule:
    def test_valid_schedule_no_errors(self):
        sched = _schedule(
            _task("T1", "2025-01-01", "2025-01-10"),
            _task("T2", "2025-01-11", "2025-01-20", preds=["T1"]),
        )
        errors = validate_schedule(sched)
        assert errors == []

    def test_missing_predecessor(self):
        sched = _schedule(
            _task("T1", "2025-01-01", "2025-01-10", preds=["T99"]),
        )
        errors = validate_schedule(sched)
        assert any("T99" in e for e in errors)

    def test_out_of_range_start(self):
        sched = ConstructionSchedule(
            tasks=[_task("T1", "2024-01-01", "2024-01-10")],
            project_start="2025-01-01",
            project_finish="2025-12-31",
        )
        errors = validate_schedule(sched)
        assert any("before project start" in e for e in errors)

    def test_circular_dependency(self):
        # T1 → T2 → T1 (cycle)
        sched = ConstructionSchedule(
            tasks=[
                _task("T1", "2025-01-01", "2025-01-10", preds=["T2"]),
                _task("T2", "2025-01-05", "2025-01-15", preds=["T1"]),
            ],
        )
        errors = validate_schedule(sched)
        assert any("circular" in e.lower() for e in errors)

    def test_out_of_range_finish(self):
        sched = ConstructionSchedule(
            tasks=[_task("T1", "2025-01-01", "2026-06-01")],
            project_start="2025-01-01",
            project_finish="2025-12-31",
        )
        errors = validate_schedule(sched)
        assert any("after project finish" in e for e in errors)


# ---------------------------------------------------------------------------
# 6. LLM tool: bim_4d_build_timeline
# ---------------------------------------------------------------------------

class TestLLMBuildTimeline:
    def _call(self, **kwargs) -> dict:
        from kerf_bim.tools.construction_sequencing import run_bim_4d_build_timeline
        return json.loads(_run(run_bim_4d_build_timeline(kwargs, None)))

    def _make_schedule(self):
        return {
            "tasks": [
                {"id": "T1", "name": "Foundations", "start": "2025-01-01", "finish": "2025-01-10", "element_ids": ["found-001"], "predecessors": []},
                {"id": "T2", "name": "Frame",       "start": "2025-01-15", "finish": "2025-01-25", "element_ids": ["col-001"],   "predecessors": ["T1"]},
            ],
            "project_start": "2025-01-01",
            "project_finish": "2025-12-31",
        }

    def test_active_element(self):
        result = self._call(schedule=self._make_schedule(), date="2025-01-05")
        assert result["ok"] is True
        timeline = result["timeline"]
        found = next(e for e in timeline if e["element_id"] == "found-001")
        assert found["state"] == "active"

    def test_not_started_element(self):
        result = self._call(schedule=self._make_schedule(), date="2025-01-01")
        timeline = result["timeline"]
        col = next(e for e in timeline if e["element_id"] == "col-001")
        assert col["state"] == "not_started"

    def test_summary_present(self):
        result = self._call(schedule=self._make_schedule(), date="2025-01-20")
        assert "summary" in result
        assert isinstance(result["summary"], dict)

    def test_missing_date_returns_error(self):
        result = self._call(schedule=self._make_schedule())
        assert "error" in result

    def test_invalid_date_returns_error(self):
        result = self._call(schedule=self._make_schedule(), date="not-a-date")
        # ValueError from date.fromisoformat propagates to error payload
        assert "error" in result


# ---------------------------------------------------------------------------
# 7. LLM tool: bim_4d_critical_path
# ---------------------------------------------------------------------------

class TestLLMCriticalPath:
    def _call(self, schedule) -> dict:
        from kerf_bim.tools.construction_sequencing import run_bim_4d_critical_path
        return json.loads(_run(run_bim_4d_critical_path({"schedule": schedule}, None)))

    def test_returns_critical_ids(self):
        sched = {
            "tasks": [
                {"id": "T1", "name": "A", "start": "2025-01-01", "finish": "2025-01-10", "predecessors": []},
                {"id": "T2", "name": "B", "start": "2025-01-11", "finish": "2025-01-20", "predecessors": ["T1"]},
            ]
        }
        result = self._call(sched)
        assert result["ok"] is True
        assert isinstance(result["critical_task_ids"], list)

    def test_ok_flag(self):
        result = self._call({"tasks": []})
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# 8. LLM tool: bim_4d_validate_schedule
# ---------------------------------------------------------------------------

class TestLLMValidateSchedule:
    def _call(self, schedule) -> dict:
        from kerf_bim.tools.construction_sequencing import run_bim_4d_validate_schedule
        return json.loads(_run(run_bim_4d_validate_schedule({"schedule": schedule}, None)))

    def test_valid_schedule(self):
        sched = {"tasks": [{"id": "T1", "name": "A", "start": "2025-01-01", "finish": "2025-01-05", "predecessors": []}]}
        result = self._call(sched)
        assert result["ok"] is True
        assert result["valid"] is True
        assert result["errors"] == []

    def test_invalid_predecessor(self):
        sched = {"tasks": [{"id": "T1", "name": "A", "start": "2025-01-01", "finish": "2025-01-05", "predecessors": ["T99"]}]}
        result = self._call(sched)
        assert result["valid"] is False
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# 9. LLM tool: bim_4d_summarise_date
# ---------------------------------------------------------------------------

class TestLLMSummariseDate:
    def _call(self, schedule, date) -> dict:
        from kerf_bim.tools.construction_sequencing import run_bim_4d_summarise_date
        return json.loads(_run(run_bim_4d_summarise_date({"schedule": schedule, "date": date}, None)))

    def test_basic_summary(self):
        sched = {
            "tasks": [
                {"id": "T1", "name": "A", "start": "2025-01-01", "finish": "2025-01-10",
                 "element_ids": ["x"], "predecessors": []},
            ]
        }
        result = self._call(sched, "2025-01-05")
        assert result["ok"] is True
        assert "active" in result
        assert result["active"] == 1

    def test_all_complete(self):
        sched = {
            "tasks": [
                {"id": "T1", "name": "A", "start": "2025-01-01", "finish": "2025-01-10",
                 "element_ids": ["x"], "predecessors": []},
            ]
        }
        result = self._call(sched, "2025-02-01")
        assert result["complete"] == 1
