"""Firmware watchdog-kick gap analyser.

Verifies that the independent watchdog (IWDG/WWDG on STM32) is being kicked
frequently enough across *all* execution paths of a firmware task schedule so
that the watchdog never times out — even on worst-case task latency.

Architecture references
-----------------------
STM32F4 Reference Manual RM0383 Rev 3, §19 — Independent Watchdog (IWDG):
  * Clock source: LSI RC oscillator, typically 32 kHz (±10–15% temperature/
    process variance — RM0383 Table 54 min/typ/max).
  * IWDG counter counts DOWN from reload to 0, then resets the MCU if no
    feed (IWDG_KR = 0xAAAA) was issued.
  * Timeout formula: t = (prescaler × (reload + 1)) / f_LSI.

STM32F4 Reference Manual RM0383 Rev 3, §20 — Window Watchdog (WWDG):
  * WWDG adds an open-window lower bound: kicks issued *before* the counter
    falls below the window register (W[6:0]) are treated as errors and also
    reset the MCU.
  * Constraint: window_min_ms ≤ kick_interval ≤ timeout_ms.
  * This module checks both bounds when wdg.type == "WWDG".

IEC 61508:2010 Part 2, §7.4.3.7 — Watchdog monitoring guidance:
  * The watchdog must not expire during any legitimate execution path.
  * For safety-critical applications (SIL-2+) a window watchdog or challenge-
    response scheme is preferred over a simple independent watchdog.

Algorithm
---------
Given a list of ``FirmwareTask`` objects each with:
  * period_ms  — how often the task runs (milliseconds),
  * wcet_ms    — worst-case execution time (milliseconds),
  * priority   — scheduler priority (higher number = higher priority),
  * kicks_watchdog — True if this task issues a watchdog feed.

The **worst-case gap** between two consecutive watchdog kicks is:

1. Find the *lowest-rate kicker*: the kicking task with the **longest period**
   (i.e., the kicker that waits the longest before issuing its next kick).

2. Add the **blocking time** from higher-priority tasks: in the worst case, the
   kicking task's execution is delayed by the WCET of every higher-priority
   non-kicker task that can preempt it before its kick is issued.

3. max_gap = period of slowest kicker + sum of WCET of all higher-priority tasks
   that do NOT kick the watchdog.

If **no task kicks the watchdog**, the gap is infinite (max_gap = +inf) and
the schedule is definitionally unsafe.

Honest caveats
--------------
* STATIC SCHEDULE ONLY — no IRQ latency, DMA, or jitter model.  Real
  worst-case includes nested ISR preemption (each Cortex-M exception frame
  = 8 × 4 B = 32 B, ARM Generic UG §B1.5.6) and RTOS tick overhead.
* Assumes an idealised fixed-priority preemptive scheduler where every
  higher-priority task can preempt the kicker exactly once per kicker period.
* WWDG window-minimum check uses the kick interval of the lowest-rate kicker
  as a proxy.  If the same task kicks multiple times per period, the actual
  inter-kick time may be shorter — verify on real hardware with a logic analyser.
* IEC 61508 SIL-2 applications should use a challenge-response watchdog (not
  modelled here) in addition to time-gap analysis.

References
----------
  STM32F4 RM0383 Rev 3 §19 — IWDG.
  STM32F4 RM0383 Rev 3 §20 — WWDG.
  IEC 61508:2010 Part 2 §7.4.3.7 — Watchdog monitoring.
  ARM Cortex-M Generic User Guide §B1.5 — Exception model.
  ARM Keil Application Note AN259 — Using Watchdog Timers in Embedded Systems.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class FirmwareTask:
    """A single firmware task in the schedule.

    Attributes
    ----------
    name:
        Human-readable task name (e.g. ``"control_loop"``, ``"sensor_read"``).
    period_ms:
        Task invocation period in milliseconds.  For a periodic task this is the
        time between successive activations (e.g. 10.0 for a 100 Hz task).
    wcet_ms:
        Worst-case execution time in milliseconds.  Must satisfy wcet_ms ≤
        period_ms for a schedulable periodic task.
    priority:
        Scheduler priority.  Higher integer = higher priority (pre-empts lower
        values).  Ties in priority are treated as same-priority — no
        additional blocking is modelled for equal-priority tasks.
    kicks_watchdog:
        True if this task issues a watchdog feed (IWDG_KR = 0xAAAA on STM32)
        at least once per execution.  Default: False.
    """
    name: str
    period_ms: float
    wcet_ms: float
    priority: int
    kicks_watchdog: bool = False

    def __post_init__(self) -> None:
        if self.period_ms <= 0:
            raise ValueError(
                f"FirmwareTask '{self.name}': period_ms must be > 0, "
                f"got {self.period_ms}"
            )
        if self.wcet_ms <= 0:
            raise ValueError(
                f"FirmwareTask '{self.name}': wcet_ms must be > 0, "
                f"got {self.wcet_ms}"
            )
        if self.wcet_ms > self.period_ms:
            raise ValueError(
                f"FirmwareTask '{self.name}': wcet_ms ({self.wcet_ms}) must be "
                f"<= period_ms ({self.period_ms})"
            )


@dataclass
class WatchdogSpec:
    """Watchdog peripheral specification.

    Attributes
    ----------
    type:
        ``"IWDG"`` — Independent Watchdog (simple timeout; RM0383 §19).
        ``"WWDG"`` — Window Watchdog (timeout + open-window lower bound; §20).
    timeout_ms:
        Watchdog timeout in milliseconds.  The MCU resets if no kick is
        received within this window (measured from the last kick or from
        startup).
    window_min_ms:
        WWDG only: minimum time that must elapse between two consecutive kicks.
        Kicks issued *before* ``window_min_ms`` has elapsed since the previous
        kick are treated as errors (early kick → reset).  ``None`` for IWDG.
    """
    type: str  # "IWDG" | "WWDG"
    timeout_ms: float
    window_min_ms: Optional[float] = None

    def __post_init__(self) -> None:
        if self.type not in ("IWDG", "WWDG"):
            raise ValueError(
                f"WatchdogSpec: type must be 'IWDG' or 'WWDG', got {self.type!r}"
            )
        if self.timeout_ms <= 0:
            raise ValueError(
                f"WatchdogSpec: timeout_ms must be > 0, got {self.timeout_ms}"
            )
        if self.type == "WWDG":
            if self.window_min_ms is None:
                raise ValueError(
                    "WatchdogSpec: window_min_ms is required for WWDG"
                )
            if self.window_min_ms < 0:
                raise ValueError(
                    f"WatchdogSpec: window_min_ms must be >= 0, "
                    f"got {self.window_min_ms}"
                )
            if self.window_min_ms >= self.timeout_ms:
                raise ValueError(
                    f"WatchdogSpec: window_min_ms ({self.window_min_ms}) must be "
                    f"< timeout_ms ({self.timeout_ms})"
                )


@dataclass
class WatchdogCheckReport:
    """Result of :func:`check_watchdog`.

    Attributes
    ----------
    max_gap_between_kicks_ms:
        Computed worst-case gap between two consecutive watchdog kicks,
        in milliseconds.  ``math.inf`` when no task kicks the watchdog.
    timeout_margin_ms:
        Safety margin: ``timeout_ms - max_gap_between_kicks_ms``.
        Negative (or -inf) when the schedule is unsafe.
    is_safe:
        True iff ``max_gap_between_kicks_ms < timeout_ms``.  False when the
        watchdog can expire before the next kick arrives.
    violating_paths:
        Human-readable list of execution-path descriptions that exceed the
        watchdog timeout.  Empty when ``is_safe`` is True.
    wwdg_window_violations:
        WWDG only: list of paths where the inter-kick interval is shorter than
        ``window_min_ms`` (early-kick reset risk).  Empty for IWDG or when no
        violation occurs.
    recommendation:
        Plain-text recommendation when ``is_safe`` is False (or when WWDG
        window violations exist).  Empty string when everything is safe.
    honest_caveat:
        Plain-text description of what this analysis does NOT model.
    """
    max_gap_between_kicks_ms: float
    timeout_margin_ms: float
    is_safe: bool
    violating_paths: List[str]
    wwdg_window_violations: List[str]
    recommendation: str
    honest_caveat: str

    def as_dict(self) -> dict:
        mgap = (
            self.max_gap_between_kicks_ms
            if math.isfinite(self.max_gap_between_kicks_ms)
            else None  # JSON-serialisable sentinel for infinity
        )
        margin = (
            self.timeout_margin_ms
            if math.isfinite(self.timeout_margin_ms)
            else None
        )
        return {
            "max_gap_between_kicks_ms": mgap,
            "timeout_margin_ms": margin,
            "is_safe": self.is_safe,
            "violating_paths": self.violating_paths,
            "wwdg_window_violations": self.wwdg_window_violations,
            "recommendation": self.recommendation,
            "honest_caveat": self.honest_caveat,
        }


# ── Caveat constant ────────────────────────────────────────────────────────────

_HONEST_CAVEAT: str = (
    "STATIC SCHEDULE ONLY — no IRQ latency, DMA burst, or scheduling-jitter model. "
    "Real worst-case inter-kick gap is larger when nested ISR preemption, RTOS tick "
    "overhead, or bus-stall latency is present (each Cortex-M exception frame = 32 B; "
    "nested ISRs multiply this; ARM Cortex-M Generic UG §B1.5.6). "
    "Assumes an ideal fixed-priority preemptive scheduler; shared-resource blocking "
    "(PCP/PIP, Sha-Rajkumar-Lehoczky 1990) is NOT modelled. "
    "WWDG window-minimum check uses the kick period of the lowest-rate kicker as "
    "a proxy — verify actual inter-kick timing on real hardware with a logic analyser. "
    "IEC 61508 SIL-2+ applications require a challenge-response watchdog in addition "
    "to this static time-gap analysis (IEC 61508:2010 Part 2 §7.4.3.7). "
    "STM32 LSI oscillator accuracy: ±10–15% over temperature/process (RM0383 Table 54); "
    "subtract ≥10% from timeout_ms before passing it to this tool for a conservative check."
)


# ── Core computation ───────────────────────────────────────────────────────────

def check_watchdog(
    tasks: List[FirmwareTask],
    wdg: WatchdogSpec,
) -> WatchdogCheckReport:
    """Verify that the watchdog is kicked frequently enough on all execution paths.

    Algorithm
    ---------
    1. Filter to kicker tasks (``kicks_watchdog=True``).
    2. If no kicker tasks exist: gap = +inf → unsafe.
    3. Otherwise, find the kicker with the *longest period* (slowest kicker).
    4. Compute blocking time: sum of WCET of all non-kicker tasks whose
       priority is strictly higher than the slowest kicker's priority.
       (In the worst case the kicker is preempted by every higher-priority task
       exactly once before it can issue its kick.)
    5. max_gap = slowest_kicker.period_ms + blocking_time_ms.
    6. is_safe = max_gap < wdg.timeout_ms.
    7. For WWDG: also check that max_gap > window_min_ms (i.e., the kicker does
       not kick too early on any path).  Since the fastest kicker determines the
       shortest possible inter-kick interval, use min(kicker.period_ms) as the
       proxy for the tightest inter-kick gap.

    Parameters
    ----------
    tasks:
        List of :class:`FirmwareTask` objects describing the firmware schedule.
    wdg:
        :class:`WatchdogSpec` describing the watchdog peripheral configuration.

    Returns
    -------
    WatchdogCheckReport
        Full report including gap, margin, safety flag, and violation paths.

    Examples
    --------
    Simple safe case — 100 ms kicker, 250 ms IWDG timeout:

    >>> tasks = [FirmwareTask("ctrl", 100.0, 10.0, priority=1, kicks_watchdog=True)]
    >>> wdg   = WatchdogSpec("IWDG", timeout_ms=250.0)
    >>> r = check_watchdog(tasks, wdg)
    >>> r.is_safe
    True
    >>> r.timeout_margin_ms
    150.0

    Unsafe case — 1 000 ms kicker, 500 ms IWDG timeout:

    >>> tasks = [FirmwareTask("slow", 1000.0, 50.0, priority=1, kicks_watchdog=True)]
    >>> wdg   = WatchdogSpec("IWDG", timeout_ms=500.0)
    >>> r = check_watchdog(tasks, wdg)
    >>> r.is_safe
    False

    References
    ----------
    STM32F4 RM0383 Rev 3 §19 — IWDG.
    STM32F4 RM0383 Rev 3 §20 — WWDG.
    IEC 61508:2010 Part 2 §7.4.3.7 — Watchdog monitoring.
    ARM Keil AN259 — Using Watchdog Timers in Embedded Systems.
    """
    kickers = [t for t in tasks if t.kicks_watchdog]

    # ── No kicker tasks ───────────────────────────────────────────────────────
    if not kickers:
        path_label = "no-kick-task (no task has kicks_watchdog=True)"
        return WatchdogCheckReport(
            max_gap_between_kicks_ms=math.inf,
            timeout_margin_ms=-math.inf,
            is_safe=False,
            violating_paths=[path_label],
            wwdg_window_violations=[],
            recommendation=(
                "Assign kicks_watchdog=True to at least one periodic task. "
                "Recommend a dedicated watchdog-kick task with period_ms < "
                f"{wdg.timeout_ms * 0.5:.1f} ms (< 50% of timeout)."
            ),
            honest_caveat=_HONEST_CAVEAT,
        )

    # ── Find slowest kicker (longest period) ──────────────────────────────────
    slowest_kicker = max(kickers, key=lambda t: t.period_ms)

    # ── Blocking time from higher-priority non-kickers ────────────────────────
    # All non-kicker tasks with strictly higher priority than the slowest kicker
    # can preempt it before it issues the kick.
    blocking_tasks = [
        t for t in tasks
        if (not t.kicks_watchdog) and t.priority > slowest_kicker.priority
    ]
    blocking_time_ms: float = sum(t.wcet_ms for t in blocking_tasks)

    # ── Worst-case kick gap ────────────────────────────────────────────────────
    max_gap = slowest_kicker.period_ms + blocking_time_ms

    # ── Safety check ──────────────────────────────────────────────────────────
    timeout_margin = wdg.timeout_ms - max_gap
    is_safe = max_gap < wdg.timeout_ms

    # ── Violating path description ────────────────────────────────────────────
    violating_paths: List[str] = []
    if not is_safe:
        parts = [f"slowest-kicker '{slowest_kicker.name}' period {slowest_kicker.period_ms:.1f} ms"]
        if blocking_tasks:
            blocker_names = ", ".join(
                f"'{t.name}' WCET {t.wcet_ms:.1f} ms" for t in blocking_tasks
            )
            parts.append(f"blocked by [{blocker_names}] = {blocking_time_ms:.1f} ms")
        parts.append(f"→ max_gap {max_gap:.1f} ms ≥ timeout {wdg.timeout_ms:.1f} ms")
        violating_paths.append(" | ".join(parts))

    # ── WWDG window-minimum check ─────────────────────────────────────────────
    wwdg_window_violations: List[str] = []
    if wdg.type == "WWDG" and wdg.window_min_ms is not None:
        # The fastest kicker determines the shortest possible inter-kick interval.
        fastest_kicker = min(kickers, key=lambda t: t.period_ms)
        shortest_interval = fastest_kicker.period_ms
        if shortest_interval <= wdg.window_min_ms:
            wwdg_window_violations.append(
                f"fastest-kicker '{fastest_kicker.name}' period {shortest_interval:.1f} ms "
                f"< WWDG window_min {wdg.window_min_ms:.1f} ms "
                f"→ early-kick reset risk (RM0383 §20)"
            )

    # ── Recommendation ────────────────────────────────────────────────────────
    recommendation_parts: List[str] = []
    if not is_safe:
        safe_period = wdg.timeout_ms * 0.4  # 40% of timeout gives 60% margin
        recommendation_parts.append(
            f"Add a watchdog-kick task with period_ms ≤ {safe_period:.1f} ms "
            f"(≤ 40% of timeout {wdg.timeout_ms:.1f} ms) or reduce blocking time "
            f"from higher-priority tasks (currently {blocking_time_ms:.1f} ms)."
        )
    if wwdg_window_violations:
        recommendation_parts.append(
            f"Increase kick interval to > {wdg.window_min_ms:.1f} ms (WWDG window_min) "
            "to avoid early-kick resets (RM0383 §20)."
        )
    recommendation = " ".join(recommendation_parts)

    return WatchdogCheckReport(
        max_gap_between_kicks_ms=max_gap,
        timeout_margin_ms=timeout_margin,
        is_safe=is_safe,
        violating_paths=violating_paths,
        wwdg_window_violations=wwdg_window_violations,
        recommendation=recommendation,
        honest_caveat=_HONEST_CAVEAT,
    )
