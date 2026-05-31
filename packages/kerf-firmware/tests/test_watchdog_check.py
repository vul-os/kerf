"""Tests for kerf_firmware.watchdog_check + LLM tool firmware_check_watchdog.

Coverage
--------
WC01  100 ms kicker, IWDG 250 ms: safe, margin = 150 ms.
WC02  1 000 ms kicker, IWDG 500 ms: violated, violating_paths non-empty.
WC03  No tasks kick watchdog: max_gap=inf, violating_paths includes "no-kick-task".
WC04  WWDG kick at 50 ms in window 60–100 ms: window_violation present.
WC05  WWDG kick at 70 ms in window 60–100 ms: no window violation, and is_safe.
WC06  Blocking time adds higher-priority non-kicker WCET to gap.
WC07  Two kickers — slowest determines worst-case gap.
WC08  Higher-priority kicker does not contribute blocking time (it already kicks).
WC09  Kicker with priority below non-kicker non-kicker gets blocked correctly.
WC10  FirmwareTask validates period_ms > 0.
WC11  FirmwareTask validates wcet_ms > 0.
WC12  FirmwareTask validates wcet_ms <= period_ms.
WC13  WatchdogSpec validates type must be IWDG or WWDG.
WC14  WatchdogSpec validates timeout_ms > 0.
WC15  WatchdogSpec WWDG requires window_min_ms.
WC16  WatchdogSpec WWDG window_min_ms must be < timeout_ms.
WC17  as_dict() keys match expected schema.
WC18  honest_caveat mentions IEC 61508 and static schedule.
WC19  LLM tool: valid round-trip IWDG 250 ms, kicker 100 ms → is_safe=True.
WC20  LLM tool: invalid JSON → BAD_ARGS.
WC21  LLM tool: tasks not a list → BAD_ARGS.
WC22  LLM tool: task missing period_ms → BAD_ARGS.
WC23  LLM tool: async wrapper matches sync handler.
WC24  No-kicker case: recommendation mentions assign kicks_watchdog.
WC25  Unsafe case: recommendation mentions add watchdog-kick task.
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_firmware.watchdog_check import (
    FirmwareTask,
    WatchdogSpec,
    WatchdogCheckReport,
    check_watchdog,
)
from kerf_firmware.tools.firmware_check_watchdog import (
    run_firmware_check_watchdog,
    run_firmware_check_watchdog_async,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_task(
    name: str = "t",
    period_ms: float = 100.0,
    wcet_ms: float = 10.0,
    priority: int = 1,
    kicks_watchdog: bool = False,
) -> FirmwareTask:
    return FirmwareTask(
        name=name,
        period_ms=period_ms,
        wcet_ms=wcet_ms,
        priority=priority,
        kicks_watchdog=kicks_watchdog,
    )


def _iwdg(timeout_ms: float) -> WatchdogSpec:
    return WatchdogSpec("IWDG", timeout_ms=timeout_ms)


def _wwdg(timeout_ms: float, window_min_ms: float) -> WatchdogSpec:
    return WatchdogSpec("WWDG", timeout_ms=timeout_ms, window_min_ms=window_min_ms)


# ── WC01: 100 ms kicker, IWDG 250 ms → safe, margin 150 ms ────────────────────

def test_wc01_safe_100ms_kicker_250ms_timeout():
    tasks = [_make_task("ctrl", period_ms=100.0, wcet_ms=10.0, kicks_watchdog=True)]
    r = check_watchdog(tasks, _iwdg(250.0))
    assert r.is_safe is True
    assert r.max_gap_between_kicks_ms == pytest.approx(100.0)
    assert r.timeout_margin_ms == pytest.approx(150.0)
    assert r.violating_paths == []
    assert r.wwdg_window_violations == []


# ── WC02: 1 000 ms kicker, IWDG 500 ms → violated ────────────────────────────

def test_wc02_violated_1000ms_kicker_500ms_timeout():
    tasks = [_make_task("slow", period_ms=1000.0, wcet_ms=50.0, kicks_watchdog=True)]
    r = check_watchdog(tasks, _iwdg(500.0))
    assert r.is_safe is False
    assert r.max_gap_between_kicks_ms == pytest.approx(1000.0)
    assert r.timeout_margin_ms == pytest.approx(-500.0)
    assert len(r.violating_paths) >= 1
    assert "slow" in r.violating_paths[0]


# ── WC03: No tasks kick → max_gap=inf, violating_paths includes "no-kick-task" ─

def test_wc03_no_kicker_tasks():
    tasks = [
        _make_task("a", period_ms=100.0, wcet_ms=10.0, kicks_watchdog=False),
        _make_task("b", period_ms=50.0, wcet_ms=5.0, kicks_watchdog=False),
    ]
    r = check_watchdog(tasks, _iwdg(250.0))
    assert r.is_safe is False
    assert math.isinf(r.max_gap_between_kicks_ms)
    assert any("no-kick-task" in p for p in r.violating_paths)


# ── WC04: WWDG kick at 50 ms in window 60–100 ms → window violation ───────────

def test_wc04_wwdg_window_violation():
    # kicker period 50 ms < window_min 60 ms → early-kick reset risk
    tasks = [_make_task("kicker", period_ms=50.0, wcet_ms=5.0, kicks_watchdog=True)]
    r = check_watchdog(tasks, _wwdg(timeout_ms=100.0, window_min_ms=60.0))
    assert len(r.wwdg_window_violations) >= 1
    assert "early-kick" in r.wwdg_window_violations[0]


# ── WC05: WWDG kick at 70 ms in window 60–100 ms → no violation, safe ─────────

def test_wc05_wwdg_no_window_violation():
    tasks = [_make_task("kicker", period_ms=70.0, wcet_ms=5.0, kicks_watchdog=True)]
    r = check_watchdog(tasks, _wwdg(timeout_ms=100.0, window_min_ms=60.0))
    assert r.wwdg_window_violations == []
    assert r.is_safe is True


# ── WC06: Blocking time adds higher-priority non-kicker WCET ──────────────────

def test_wc06_blocking_from_higher_priority_non_kicker():
    kicker = _make_task("kicker", period_ms=100.0, wcet_ms=10.0, priority=1, kicks_watchdog=True)
    blocker = _make_task("isr", period_ms=100.0, wcet_ms=30.0, priority=5, kicks_watchdog=False)
    r = check_watchdog([kicker, blocker], _iwdg(250.0))
    # max_gap = 100 + 30 = 130 ms  (<250 ms → still safe)
    assert r.max_gap_between_kicks_ms == pytest.approx(130.0)
    assert r.timeout_margin_ms == pytest.approx(120.0)
    assert r.is_safe is True


# ── WC06b: blocking pushes gap over timeout → unsafe ─────────────────────────

def test_wc06b_blocking_causes_violation():
    kicker = _make_task("kicker", period_ms=100.0, wcet_ms=10.0, priority=1, kicks_watchdog=True)
    blocker = _make_task("heavy", period_ms=200.0, wcet_ms=180.0, priority=5, kicks_watchdog=False)
    # max_gap = 100 + 180 = 280 ms > 250 ms → unsafe
    r = check_watchdog([kicker, blocker], _iwdg(250.0))
    assert r.is_safe is False
    assert r.max_gap_between_kicks_ms == pytest.approx(280.0)


# ── WC07: Two kickers — slowest determines worst-case gap ─────────────────────

def test_wc07_two_kickers_slowest_determines_gap():
    fast = _make_task("fast_kick", period_ms=50.0, wcet_ms=5.0, priority=2, kicks_watchdog=True)
    slow = _make_task("slow_kick", period_ms=200.0, wcet_ms=20.0, priority=1, kicks_watchdog=True)
    r = check_watchdog([fast, slow], _iwdg(500.0))
    # slowest kicker period = 200 ms; no non-kicker blocking tasks
    assert r.max_gap_between_kicks_ms == pytest.approx(200.0)
    assert r.is_safe is True


# ── WC08: Higher-priority kicker does NOT contribute blocking time ─────────────

def test_wc08_higher_priority_kicker_no_blocking():
    slow_kicker = _make_task("slow_kick", period_ms=200.0, wcet_ms=20.0, priority=1, kicks_watchdog=True)
    fast_kicker = _make_task("fast_kick", period_ms=50.0, wcet_ms=5.0, priority=5, kicks_watchdog=True)
    r = check_watchdog([slow_kicker, fast_kicker], _iwdg(500.0))
    # fast_kicker has kicks_watchdog=True, so it should NOT count as a blocker
    # max_gap = 200 ms (only slow_kick considered; fast_kick is also a kicker)
    assert r.max_gap_between_kicks_ms == pytest.approx(200.0)


# ── WC09: Non-kicker lower-priority does NOT contribute blocking ───────────────

def test_wc09_lower_priority_non_kicker_no_blocking():
    kicker = _make_task("kicker", period_ms=100.0, wcet_ms=10.0, priority=5, kicks_watchdog=True)
    low_pri = _make_task("low", period_ms=100.0, wcet_ms=40.0, priority=1, kicks_watchdog=False)
    r = check_watchdog([kicker, low_pri], _iwdg(250.0))
    # low_pri priority (1) < kicker priority (5) → does NOT block kicker
    assert r.max_gap_between_kicks_ms == pytest.approx(100.0)
    assert r.is_safe is True


# ── WC10: FirmwareTask validates period_ms > 0 ───────────────────────────────

def test_wc10_firmware_task_period_validation():
    with pytest.raises(ValueError, match="period_ms"):
        FirmwareTask("t", period_ms=0.0, wcet_ms=1.0, priority=1)


# ── WC11: FirmwareTask validates wcet_ms > 0 ─────────────────────────────────

def test_wc11_firmware_task_wcet_validation():
    with pytest.raises(ValueError, match="wcet_ms"):
        FirmwareTask("t", period_ms=100.0, wcet_ms=0.0, priority=1)


# ── WC12: FirmwareTask validates wcet_ms <= period_ms ────────────────────────

def test_wc12_firmware_task_wcet_exceeds_period():
    with pytest.raises(ValueError, match="wcet_ms.*period_ms"):
        FirmwareTask("t", period_ms=10.0, wcet_ms=20.0, priority=1)


# ── WC13: WatchdogSpec validates type ────────────────────────────────────────

def test_wc13_watchdog_spec_bad_type():
    with pytest.raises(ValueError, match="type"):
        WatchdogSpec("WDT", timeout_ms=100.0)


# ── WC14: WatchdogSpec validates timeout_ms > 0 ──────────────────────────────

def test_wc14_watchdog_spec_zero_timeout():
    with pytest.raises(ValueError, match="timeout_ms"):
        WatchdogSpec("IWDG", timeout_ms=0.0)


# ── WC15: WatchdogSpec WWDG requires window_min_ms ───────────────────────────

def test_wc15_wwdg_requires_window_min():
    with pytest.raises(ValueError, match="window_min_ms"):
        WatchdogSpec("WWDG", timeout_ms=100.0, window_min_ms=None)


# ── WC16: WatchdogSpec WWDG window_min_ms must be < timeout_ms ───────────────

def test_wc16_wwdg_window_min_ge_timeout():
    with pytest.raises(ValueError, match="window_min_ms"):
        WatchdogSpec("WWDG", timeout_ms=100.0, window_min_ms=100.0)


# ── WC17: as_dict() keys match expected schema ────────────────────────────────

def test_wc17_as_dict_keys():
    tasks = [_make_task("ctrl", kicks_watchdog=True)]
    r = check_watchdog(tasks, _iwdg(250.0))
    d = r.as_dict()
    assert "max_gap_between_kicks_ms" in d
    assert "timeout_margin_ms" in d
    assert "is_safe" in d
    assert "violating_paths" in d
    assert "wwdg_window_violations" in d
    assert "recommendation" in d
    assert "honest_caveat" in d


# ── WC18: honest_caveat mentions IEC 61508 and static schedule ────────────────

def test_wc18_honest_caveat_content():
    tasks = [_make_task("ctrl", kicks_watchdog=True)]
    r = check_watchdog(tasks, _iwdg(250.0))
    assert "IEC 61508" in r.honest_caveat
    assert "STATIC" in r.honest_caveat.upper()


# ── WC19: LLM tool valid round-trip → is_safe=True ───────────────────────────

def test_wc19_llm_tool_valid_roundtrip():
    args = {
        "tasks": [
            {"name": "ctrl", "period_ms": 100.0, "wcet_ms": 10.0, "priority": 1, "kicks_watchdog": True}
        ],
        "wdg": {"type": "IWDG", "timeout_ms": 250.0},
    }
    raw = run_firmware_check_watchdog(args)
    result = json.loads(raw)
    assert result.get("is_safe") is True
    assert result.get("max_gap_between_kicks_ms") == pytest.approx(100.0)
    assert result.get("timeout_margin_ms") == pytest.approx(150.0)


# ── WC20: LLM tool invalid JSON → BAD_ARGS via async wrapper ─────────────────

def test_wc20_llm_tool_invalid_json():
    result = json.loads(asyncio.run(run_firmware_check_watchdog_async({}, b"not-json")))
    assert result.get("code") == "BAD_ARGS"


# ── WC21: LLM tool tasks not a list → BAD_ARGS ───────────────────────────────

def test_wc21_llm_tool_tasks_not_list():
    args = {"tasks": "not-a-list", "wdg": {"type": "IWDG", "timeout_ms": 250.0}}
    result = json.loads(run_firmware_check_watchdog(args))
    assert result.get("code") == "BAD_ARGS"


# ── WC22: LLM tool task missing period_ms → BAD_ARGS ─────────────────────────

def test_wc22_llm_tool_task_missing_period_ms():
    args = {
        "tasks": [{"name": "ctrl", "wcet_ms": 10.0, "priority": 1}],
        "wdg": {"type": "IWDG", "timeout_ms": 250.0},
    }
    result = json.loads(run_firmware_check_watchdog(args))
    assert result.get("code") == "BAD_ARGS"


# ── WC23: async wrapper matches sync handler ──────────────────────────────────

def test_wc23_async_wrapper_matches_sync():
    args = {
        "tasks": [
            {"name": "ctrl", "period_ms": 100.0, "wcet_ms": 10.0, "priority": 1, "kicks_watchdog": True}
        ],
        "wdg": {"type": "IWDG", "timeout_ms": 250.0},
    }
    sync_result = json.loads(run_firmware_check_watchdog(args))
    async_result = json.loads(
        asyncio.run(run_firmware_check_watchdog_async({}, json.dumps(args).encode()))
    )
    assert sync_result == async_result


# ── WC24: No-kicker case recommendation mentions kicks_watchdog ───────────────

def test_wc24_no_kicker_recommendation():
    tasks = [_make_task("only_task", period_ms=100.0, wcet_ms=10.0, kicks_watchdog=False)]
    r = check_watchdog(tasks, _iwdg(250.0))
    assert "kicks_watchdog" in r.recommendation


# ── WC25: Unsafe case recommendation mentions add watchdog-kick task ──────────

def test_wc25_unsafe_recommendation():
    tasks = [_make_task("slow", period_ms=1000.0, wcet_ms=50.0, kicks_watchdog=True)]
    r = check_watchdog(tasks, _iwdg(500.0))
    assert not r.is_safe
    assert r.recommendation != ""
    # Recommendation should mention adding a task or reducing blocking
    assert "watchdog" in r.recommendation.lower() or "kick" in r.recommendation.lower()


# ── WC26: WWDG exact edge: kick period == window_min → still violation ─────────

def test_wc26_wwdg_kick_exactly_at_window_min():
    # kick period 60 ms is NOT strictly > window_min 60 ms → violation
    tasks = [_make_task("kicker", period_ms=60.0, wcet_ms=5.0, kicks_watchdog=True)]
    r = check_watchdog(tasks, _wwdg(timeout_ms=100.0, window_min_ms=60.0))
    assert len(r.wwdg_window_violations) >= 1


# ── WC27: Empty task list → no kicker → unsafe ────────────────────────────────

def test_wc27_empty_task_list():
    r = check_watchdog([], _iwdg(250.0))
    assert r.is_safe is False
    assert math.isinf(r.max_gap_between_kicks_ms)


# ── WC28: as_dict() max_gap is None when infinite ─────────────────────────────

def test_wc28_as_dict_inf_is_none():
    r = check_watchdog([], _iwdg(250.0))
    d = r.as_dict()
    assert d["max_gap_between_kicks_ms"] is None
    assert d["timeout_margin_ms"] is None
