"""RTOS task priority assignment verifier — Liu-Layland rate-monotonic schedulability.

Checks that a set of periodic RTOS tasks satisfies the Liu-Layland (1973)
rate-monotonic (RM) utilisation bound and that task priorities are assigned
correctly (shorter period → higher priority, as required by RM theory).

Theory
------
Rate-Monotonic Scheduling (Liu-Layland 1973):
  For n independent periodic tasks with computation times Cᵢ and periods Tᵢ,
  the CPU utilisation is:

      U = Σᵢ Cᵢ / Tᵢ

  Under optimal RM priority assignment (shortest period = highest priority),
  the set is schedulable if:

      U ≤ n · (2^(1/n) − 1)       [Liu-Layland sufficient bound]

  As n → ∞, this bound converges to ln(2) ≈ 69.3%.  It is a *sufficient*
  condition — a task set that exceeds the bound may still be schedulable
  (exact analysis requires response-time analysis per Lehoczky-Sha-Ding 1989),
  but exceeding it guarantees the RM assignment is no longer safely proven.

  Hyperbolic bound (Bini-Buttazzo 2001):
      Πᵢ (Uᵢ + 1) ≤ 2
  This is tighter than the classic Liu-Layland bound and catches more
  schedulable sets, but is still a sufficient (not necessary) condition.

Priority assignment rule:
  Under Rate-Monotonic, the task with the shortest period must receive the
  *highest* priority.  In FreeRTOS/Zephyr/ChibiOS convention "higher integer
  = higher priority", so shorter period → larger priority integer.

HONEST CAVEAT — SCOPE LIMITATIONS
------------------------------------
This analyser implements ONLY the Liu-Layland 1973 classical RM model for
independent periodic tasks:

  * Does NOT model shared resources (Priority Ceiling Protocol / Priority
    Inheritance Protocol).  Tasks sharing mutexes require response-time
    analysis with blocking-time terms (Sha-Rajkumar-Lehoczky 1990).
  * Does NOT model aperiodic or sporadic tasks (server algorithms: Deferrable
    Server, Polling Server, Sporadic Server — Liu 2000 §6).
  * Does NOT model interrupt latency, context-switch overhead, or RTOS
    kernel jitter.
  * Does NOT verify deadlines ≠ periods (EDF or DM required for Tᵢ ≠ Dᵢ).
  * FreeRTOS priority inversion risk: use firmware_verify_interrupt_priorities
    for NVIC-level checking and Scheduler.analyse() for mutex-graph analysis.

References
----------
  Liu, C.L. and Layland, J.W. (1973). "Scheduling Algorithms for
    Multiprogramming in a Hard-Real-Time Environment." J. ACM 20(1), pp. 46-61.
  Bini, E. and Buttazzo, G.C. (2001). "A Hyperbolic Bound for the Rate
    Monotonic Algorithm." ECRTS 2001, pp. 59-67.
  Lehoczky, J., Sha, L. and Ding, Y. (1989). "The rate monotonic scheduling
    algorithm: exact characterization and average case behavior." RTSS 1989.
  ARM (2022). FreeRTOS Kernel Developer Docs — Task Priorities.
  Renesas (2023). FreeRTOS on RA MCU Group Application Note (R01AN5545).
  Zephyr Project (2024). Scheduling — Real-time Operating Systems.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ──────────────────────────────────────────────────────────────────────────────
# Public data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RtosTaskSpec:
    """Specification for a single periodic RTOS task.

    Attributes
    ----------
    task_name:
        Unique human-readable task name (e.g. ``"sensor_task"``,
        ``"control_loop"``).
    period_ms:
        Task period in milliseconds.  The task is invoked once per period.
        Must be > 0.
    wcet_ms:
        Worst-Case Execution Time in milliseconds.  Time the task needs
        *at most* to complete one activation.  Must satisfy
        ``0 < wcet_ms ≤ period_ms`` for a valid periodic task.
    priority:
        RTOS priority level.  Higher integer = higher priority
        (FreeRTOS/Zephyr/ChibiOS convention).  Must be ≥ 0.

    Notes
    -----
    The utilisation contribution of this task is ``wcet_ms / period_ms``.
    """
    task_name: str
    period_ms: float
    wcet_ms: float
    priority: int


@dataclass
class RtosPriorityReport:
    """Result of :func:`check_rtos_priorities`.

    Attributes
    ----------
    total_utilization_pct:
        Total CPU utilisation U = 100 · Σ Cᵢ/Tᵢ (percent).
    liu_layland_bound_pct:
        Liu-Layland sufficient schedulability bound in percent:
        100 · n · (2^(1/n) − 1).
    rate_monotonic_schedulable:
        ``True`` iff U ≤ liu_layland_bound_pct (sufficient condition).
        A ``False`` result does not prove *unschedulability* — use
        response-time analysis for definitive answer.
    hyperbolic_bound_test:
        ``True`` iff the tighter Bini-Buttazzo (2001) hyperbolic bound
        is satisfied: Πᵢ (Uᵢ + 1) ≤ 2.  Also a sufficient condition.
    priority_assignment_correct:
        ``True`` iff task priorities are assigned in RM order:
        for every pair (i, j), if ``period_ms[i] < period_ms[j]``
        then ``priority[i] > priority[j]``.
        Tasks with identical periods may share the same priority without
        violating this flag.
    num_tasks:
        Number of tasks analysed (n).
    schedule_recommendations:
        Human-readable advisory list.  Empty when everything is correct.
    honest_caveat:
        Fixed disclaimer string reminding users of model scope.
    """
    total_utilization_pct: float
    liu_layland_bound_pct: float
    rate_monotonic_schedulable: bool
    hyperbolic_bound_test: bool
    priority_assignment_correct: bool
    num_tasks: int
    schedule_recommendations: list[str] = field(default_factory=list)
    honest_caveat: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Liu-Layland bound
# ──────────────────────────────────────────────────────────────────────────────

def _liu_layland_bound(n: int) -> float:
    """Return Liu-Layland RM utilisation bound for *n* tasks (fraction, not %).

    For n tasks: U_bound = n · (2^(1/n) − 1).

    Parameters
    ----------
    n:
        Number of independent periodic tasks (must be ≥ 1).

    Returns
    -------
    float
        Bound as a fraction in [0, 1].  For n=1 → 1.0; n→∞ → ln(2) ≈ 0.6931.
    """
    if n <= 0:
        return 0.0
    return n * (math.pow(2.0, 1.0 / n) - 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Core analyser
# ──────────────────────────────────────────────────────────────────────────────

_HONEST_CAVEAT = (
    "Liu-Layland sufficient bound for independent periodic tasks only. "
    "Does NOT model: shared resources (PCP/PIP/blocking-time terms require "
    "Sha-Rajkumar-Lehoczky 1990 response-time analysis), aperiodic/sporadic "
    "tasks (Deferrable/Sporadic Server algorithms), interrupt latency, "
    "context-switch overhead, or deadline ≠ period (use EDF/DM for Di ≠ Ti). "
    "Refs: Liu-Layland (1973) J. ACM 20(1); Bini-Buttazzo (2001) ECRTS; "
    "ARM FreeRTOS Kernel Docs; Renesas R01AN5545; Zephyr Scheduling Docs."
)


def check_rtos_priorities(tasks: Sequence[RtosTaskSpec]) -> RtosPriorityReport:
    """Verify RTOS task priority assignments for rate-monotonic schedulability.

    Parameters
    ----------
    tasks:
        Sequence of :class:`RtosTaskSpec` objects describing each periodic task.

    Returns
    -------
    RtosPriorityReport
        Full report with utilisation, Liu-Layland bound, RM schedulability flag,
        hyperbolic bound result, priority correctness, and recommendations.

    Algorithm
    ---------
    1. Validate each task spec (period > 0, 0 < wcet ≤ period).
    2. Compute U = Σ Cᵢ/Tᵢ and the Liu-Layland bound U_bound = n·(2^(1/n)−1).
    3. Evaluate the Bini-Buttazzo hyperbolic bound: Π(Uᵢ+1) ≤ 2.
    4. Verify RM priority assignment: shorter period → strictly higher priority
       (tasks with equal periods may share priority).
    5. Generate human-readable recommendations for any issues found.

    Examples
    --------
    Two tasks, T1: period=10 ms, WCET=4 ms (priority=2);
               T2: period=20 ms, WCET=8 ms (priority=1):
        U = 4/10 + 8/20 = 0.40 + 0.40 = 0.80 = 80%
        bound = 2·(√2−1) ≈ 82.84%
        schedulable: True (80% ≤ 82.84%)
        priority_assignment_correct: True (T1 shorter period, higher priority)

    References
    ----------
    Liu-Layland (1973) J. ACM 20(1) pp. 46-61 — §3 Theorem 1.
    Bini-Buttazzo (2001) ECRTS — Theorem 1 (hyperbolic bound).
    """
    n = len(tasks)
    recommendations: list[str] = []

    if n == 0:
        return RtosPriorityReport(
            total_utilization_pct=0.0,
            liu_layland_bound_pct=0.0,
            rate_monotonic_schedulable=True,
            hyperbolic_bound_test=True,
            priority_assignment_correct=True,
            num_tasks=0,
            schedule_recommendations=["No tasks provided — nothing to analyse."],
            honest_caveat=_HONEST_CAVEAT,
        )

    # ── 1. Per-task validation ─────────────────────────────────────────────────
    for t in tasks:
        if t.period_ms <= 0:
            recommendations.append(
                f"Task '{t.task_name}': period_ms must be > 0 (got {t.period_ms})."
            )
        if t.wcet_ms <= 0:
            recommendations.append(
                f"Task '{t.task_name}': wcet_ms must be > 0 (got {t.wcet_ms})."
            )
        elif t.wcet_ms > t.period_ms:
            recommendations.append(
                f"Task '{t.task_name}': wcet_ms ({t.wcet_ms} ms) exceeds "
                f"period_ms ({t.period_ms} ms) — task cannot meet its own deadline."
            )
        if t.priority < 0:
            recommendations.append(
                f"Task '{t.task_name}': priority must be ≥ 0 (got {t.priority})."
            )

    # ── 2. Utilisation ────────────────────────────────────────────────────────
    utilizations: list[float] = []
    for t in tasks:
        if t.period_ms > 0:
            utilizations.append(t.wcet_ms / t.period_ms)
        else:
            utilizations.append(0.0)  # already flagged above

    total_u = sum(utilizations)
    total_u_pct = total_u * 100.0

    bound = _liu_layland_bound(n)
    bound_pct = bound * 100.0

    rm_schedulable = total_u <= bound

    # ── 3. Hyperbolic bound (Bini-Buttazzo 2001) ──────────────────────────────
    hyp_product = 1.0
    for ui in utilizations:
        hyp_product *= (ui + 1.0)
    hyperbolic_ok = hyp_product <= 2.0

    # ── 4. RM priority assignment check ───────────────────────────────────────
    # RM rule: shorter period → higher priority (higher integer).
    # For each pair where period_i < period_j, we require priority_i > priority_j.
    priority_ok = True
    for i, ti in enumerate(tasks):
        for j, tj in enumerate(tasks):
            if i == j:
                continue
            if ti.period_ms < tj.period_ms:
                if ti.priority <= tj.priority:
                    priority_ok = False
                    recommendations.append(
                        f"RM priority violation: task '{ti.task_name}' "
                        f"(period={ti.period_ms} ms) has priority {ti.priority} "
                        f"which is NOT higher than task '{tj.task_name}' "
                        f"(period={tj.period_ms} ms, priority={tj.priority}). "
                        f"Rate-monotonic requires shorter period → higher priority "
                        f"(Liu-Layland 1973 §3). "
                        f"Assign '{ti.task_name}' priority > {tj.priority}."
                    )
                    break  # one report per task pair direction is enough
            if priority_ok is False:
                break

    # ── 5. Advisory recommendations ──────────────────────────────────────────
    if not rm_schedulable:
        headroom = total_u_pct - bound_pct
        recommendations.append(
            f"Utilisation {total_u_pct:.2f}% exceeds Liu-Layland RM bound "
            f"{bound_pct:.2f}% by {headroom:.2f} percentage points. "
            f"Liu-Layland is a *sufficient* condition — the task set may still "
            f"be schedulable under exact response-time analysis "
            f"(Lehoczky-Sha-Ding 1989). "
            f"To bring utilisation below the bound: reduce WCET (tighter code, "
            f"hardware acceleration), lengthen period(s) where latency allows, "
            f"or offload tasks to a second core / co-processor."
        )
    elif not hyperbolic_ok:
        recommendations.append(
            f"Utilisation {total_u_pct:.2f}% is within the classic Liu-Layland "
            f"bound ({bound_pct:.2f}%) but fails the tighter Bini-Buttazzo (2001) "
            f"hyperbolic bound (Π(Uᵢ+1) = {hyp_product:.4f} > 2.0). "
            f"Consider using exact response-time analysis for confirmation."
        )

    if total_u_pct > 90.0:
        recommendations.append(
            f"Utilisation {total_u_pct:.2f}% leaves very little headroom for "
            f"interrupt latency, RTOS overhead, and aperiodic tasks. "
            f"Best practice (ARM FreeRTOS App Note) recommends keeping total "
            f"periodic-task utilisation ≤ 70–75% in practice."
        )

    # Largest contributor advisory
    if n > 1 and total_u > 0:
        max_u_idx = utilizations.index(max(utilizations))
        max_task = tasks[max_u_idx]
        max_u_pct = utilizations[max_u_idx] * 100.0
        if max_u_pct > 40.0:
            recommendations.append(
                f"Highest utilisation contributor: '{max_task.task_name}' "
                f"({max_u_pct:.2f}% = {max_task.wcet_ms} ms / {max_task.period_ms} ms). "
                f"Optimising or splitting this task would have the largest impact."
            )

    return RtosPriorityReport(
        total_utilization_pct=round(total_u_pct, 6),
        liu_layland_bound_pct=round(bound_pct, 6),
        rate_monotonic_schedulable=rm_schedulable,
        hyperbolic_bound_test=hyperbolic_ok,
        priority_assignment_correct=priority_ok,
        num_tasks=n,
        schedule_recommendations=recommendations,
        honest_caveat=_HONEST_CAVEAT,
    )
