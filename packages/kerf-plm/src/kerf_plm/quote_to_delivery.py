"""
kerf_plm.quote_to_delivery — Cimatron-style quote-to-delivery workflow tracker.

HONEST: A pure-Python state-machine for mold-making / injection-mold job tracking.
        Follows ANSI/ISA-95 Part 1 (Manufacturing Operations Management) work-order
        lifecycle states and APICS Operations Management 14e Chapter 16 shop-floor
        scheduling concepts.  Not a full ERP system — no persistence or messaging.

References
----------
  ANSI/ISA-95.01 (2010). "Enterprise-Control System Integration Part 1."
      ISA standard for Manufacturing Operations Management (MOM) work-order
      lifecycle and status transitions.
  APICS Operations Management Body of Knowledge 14th ed. (2013). Chapter 16:
      "Shop-Floor Control" — job routing, tracking, and on-time delivery metrics.
  Cimatron documentation (Cimatron Group). Mold-design + CAM workflow phases.

Author: imranparuk  — Wave 12B: Landscape + Quote-to-delivery + MicroFlo
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Status enumeration (ISA-95 work-order lifecycle + mold-specific phases)
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    """
    Mold-job lifecycle statuses.

    Reference: ANSI/ISA-95.01 §5.3.2 work-order state model extended with
    mold-specific phases per Cimatron workflow.

    Ordering (valid forward-direction transitions):
        QUOTED → QUOTE_ACCEPTED → DESIGN → MOLD_MAKING → SAMPLING
              → PRODUCTION → QC_HOLD ↔ PRODUCTION
              → SHIPPED → DELIVERED → INVOICED
    """
    QUOTED          = "quoted"
    QUOTE_ACCEPTED  = "quote_accepted"
    DESIGN          = "design"
    MOLD_MAKING     = "mold_making"
    SAMPLING        = "sampling"
    PRODUCTION      = "production"
    QC_HOLD         = "qc_hold"
    SHIPPED         = "shipped"
    DELIVERED       = "delivered"
    INVOICED        = "invoiced"


# ---------------------------------------------------------------------------
# Valid transitions graph
# ---------------------------------------------------------------------------
# Key = current status; Value = set of allowed next statuses.
# QC_HOLD can loop back to PRODUCTION (re-work release).
# QUOTED can be re-quoted (stays QUOTED) by same actor — not modelled here.

_VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUOTED:          {JobStatus.QUOTE_ACCEPTED},
    JobStatus.QUOTE_ACCEPTED:  {JobStatus.DESIGN},
    JobStatus.DESIGN:          {JobStatus.MOLD_MAKING},
    JobStatus.MOLD_MAKING:     {JobStatus.SAMPLING},
    JobStatus.SAMPLING:        {JobStatus.PRODUCTION, JobStatus.MOLD_MAKING},
    JobStatus.PRODUCTION:      {JobStatus.QC_HOLD, JobStatus.SHIPPED},
    JobStatus.QC_HOLD:         {JobStatus.PRODUCTION, JobStatus.SHIPPED},
    JobStatus.SHIPPED:         {JobStatus.DELIVERED},
    JobStatus.DELIVERED:       {JobStatus.INVOICED},
    JobStatus.INVOICED:        set(),  # terminal state
}


# ---------------------------------------------------------------------------
# Milestone + JobOrder dataclasses
# ---------------------------------------------------------------------------

@dataclass
class JobMilestone:
    """
    A single status-transition event in a job's audit trail.

    HONEST: timestamps are ISO-8601 strings; caller supplies them (for testability).
            In production these would be UTC-stamped server-side.

    Attributes
    ----------
    status        : JobStatus at the time of this milestone
    timestamp_iso : ISO-8601 UTC timestamp string (e.g. "2026-01-15T09:30:00Z")
    actor         : user_id who triggered the transition (ISA-95 §5.3.2 actor)
    notes         : optional free-text remarks
    """
    status: JobStatus
    timestamp_iso: str
    actor: str
    notes: str = ''


@dataclass
class JobOrder:
    """
    A mold-making job order in the quote-to-delivery workflow.

    Reference: ANSI/ISA-95.01 §5.3 work-order model;
               APICS OM 14e Ch 16 job-routing card.

    Attributes
    ----------
    job_id               : unique job identifier (e.g. "JOB-2026-001")
    customer_id          : customer reference
    quote_id             : associated quote number
    quoted_amount_usd    : job value in USD
    promised_delivery_iso: ISO-8601 date string of contracted delivery
    current_status       : current JobStatus
    history              : ordered list of JobMilestone (immutable audit trail)
    days_in_status       : calendar days in current status (from last milestone)
    is_overdue           : True if today > promised_delivery_iso and not DELIVERED/INVOICED
    """
    job_id: str
    customer_id: str
    quote_id: str
    quoted_amount_usd: float
    promised_delivery_iso: str
    current_status: JobStatus
    history: list[JobMilestone]
    days_in_status: int = 0
    is_overdue: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_iso_date(iso_str: str) -> datetime:
    """
    Parse an ISO-8601 date or datetime string to UTC datetime.

    Accepts "YYYY-MM-DD", "YYYY-MM-DDTHH:MM:SSZ", and "YYYY-MM-DDTHH:MM:SS+HH:MM".
    """
    iso_str = iso_str.strip()
    # Try full datetime with Z suffix
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(iso_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse ISO date: {iso_str!r}")


def _days_between(iso_a: str, iso_b: str) -> int:
    """Return |days| between two ISO date strings (always non-negative)."""
    da = _parse_iso_date(iso_a)
    db = _parse_iso_date(iso_b)
    return abs((db - da).days)


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recompute_derived(job: JobOrder, as_of_iso: Optional[str] = None) -> JobOrder:
    """
    Recompute days_in_status and is_overdue from history + current_status.

    is_overdue logic (APICS Ch 16 §16.4 on-time delivery):
      - A job is overdue if as_of_date > promised_delivery_iso
        AND current_status is not DELIVERED or INVOICED.
    """
    # days_in_status = days since last milestone timestamp
    as_of = as_of_iso or _now_iso()
    if job.history:
        last_ts = job.history[-1].timestamp_iso
        days = _days_between(last_ts, as_of)
    else:
        days = 0

    terminal = {JobStatus.DELIVERED, JobStatus.INVOICED}
    try:
        as_of_dt = _parse_iso_date(as_of)
        promised_dt = _parse_iso_date(job.promised_delivery_iso)
        overdue = (as_of_dt > promised_dt) and (job.current_status not in terminal)
    except ValueError:
        overdue = False

    return JobOrder(
        job_id=job.job_id,
        customer_id=job.customer_id,
        quote_id=job.quote_id,
        quoted_amount_usd=job.quoted_amount_usd,
        promised_delivery_iso=job.promised_delivery_iso,
        current_status=job.current_status,
        history=job.history,
        days_in_status=days,
        is_overdue=overdue,
    )


# ---------------------------------------------------------------------------
# Public API — transition
# ---------------------------------------------------------------------------

def transition_status(
    job: JobOrder,
    new_status: JobStatus,
    actor: str,
    notes: str = '',
    timestamp_iso: Optional[str] = None,
) -> JobOrder:
    """
    Advance a JobOrder to new_status.

    Validates the transition against the ISA-95 lifecycle graph, appends a
    JobMilestone to the audit trail, and recomputes days_in_status + is_overdue.

    HONEST: transition validation enforces the ISA-95 workflow graph only;
            business rules (e.g. "sampling requires approved design docs") would
            need an external BOM/document check.

    Reference: ANSI/ISA-95.01 §5.3.2 work-order state-machine.

    Parameters
    ----------
    job          : current JobOrder (immutable — returns a new instance)
    new_status   : target JobStatus
    actor        : user_id triggering the transition
    notes        : optional remarks appended to the milestone
    timestamp_iso: override timestamp (default: UTC now) — useful for testing

    Returns
    -------
    Updated JobOrder (new object; input is not mutated).

    Raises
    ------
    ValueError — if new_status is not a valid next state from current_status.
    """
    allowed = _VALID_TRANSITIONS.get(job.current_status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Invalid transition {job.current_status.value!r} → {new_status.value!r}. "
            f"Allowed next states: {[s.value for s in sorted(allowed, key=lambda x: x.value)]}"
        )

    ts = timestamp_iso or _now_iso()
    milestone = JobMilestone(
        status=new_status,
        timestamp_iso=ts,
        actor=actor,
        notes=notes,
    )
    new_history = list(job.history) + [milestone]

    updated = JobOrder(
        job_id=job.job_id,
        customer_id=job.customer_id,
        quote_id=job.quote_id,
        quoted_amount_usd=job.quoted_amount_usd,
        promised_delivery_iso=job.promised_delivery_iso,
        current_status=new_status,
        history=new_history,
        days_in_status=0,
        is_overdue=job.is_overdue,
    )
    return _recompute_derived(updated, as_of_iso=ts)


# ---------------------------------------------------------------------------
# Public API — status_report
# ---------------------------------------------------------------------------

def status_report(jobs: list[JobOrder]) -> dict:
    """
    Aggregate metrics across a portfolio of jobs.

    HONEST: cycle_days uses the span from the first to the last milestone;
            throughput_per_week is jobs delivered per 7-day rolling period
            (approximated as total DELIVERED / (total span in weeks)).

    Reference: APICS OM 14e Ch 16 shop-floor performance metrics.

    Parameters
    ----------
    jobs : list of JobOrder

    Returns
    -------
    dict with keys:
      by_status       : {status_value: count}
      overdue_count   : number of overdue jobs
      avg_cycle_days  : average days from QUOTED milestone to DELIVERED/INVOICED
                        (0.0 if no completed jobs)
      throughput_per_week : completed (DELIVERED+INVOICED) jobs per week
                            (0.0 if insufficient data)
    """
    by_status: dict[str, int] = {s.value: 0 for s in JobStatus}
    overdue_count = 0
    cycle_days_list: list[float] = []

    for job in jobs:
        by_status[job.current_status.value] += 1
        if job.is_overdue:
            overdue_count += 1

        # Cycle days: first milestone to last milestone (if ≥ 2 milestones)
        if len(job.history) >= 2:
            try:
                t_start = _parse_iso_date(job.history[0].timestamp_iso)
                t_end = _parse_iso_date(job.history[-1].timestamp_iso)
                days = abs((t_end - t_start).days)
                cycle_days_list.append(float(days))
            except ValueError:
                pass

    avg_cycle = sum(cycle_days_list) / len(cycle_days_list) if cycle_days_list else 0.0

    # Throughput: delivered + invoiced jobs per week
    completed_statuses = {JobStatus.DELIVERED, JobStatus.INVOICED}
    completed = [j for j in jobs if j.current_status in completed_statuses]
    throughput_per_week = 0.0
    if completed and len(completed) >= 1:
        # Use total span across all completed jobs
        all_ts: list[datetime] = []
        for j in completed:
            for m in j.history:
                try:
                    all_ts.append(_parse_iso_date(m.timestamp_iso))
                except ValueError:
                    pass
        if all_ts and len(all_ts) >= 2:
            span_weeks = (max(all_ts) - min(all_ts)).days / 7.0
            if span_weeks > 0:
                throughput_per_week = len(completed) / span_weeks
            else:
                throughput_per_week = float(len(completed))

    return {
        "by_status": by_status,
        "overdue_count": overdue_count,
        "avg_cycle_days": round(avg_cycle, 2),
        "throughput_per_week": round(throughput_per_week, 4),
    }


# ---------------------------------------------------------------------------
# Public API — on_time_delivery_rate
# ---------------------------------------------------------------------------

def on_time_delivery_rate(jobs: list[JobOrder]) -> float:
    """
    Fraction of DELIVERED jobs that reached DELIVERED status on or before
    promised_delivery_iso.

    HONEST: uses the timestamp of the DELIVERED milestone to determine delivery
            date — if the job was invoiced without a DELIVERED milestone the
            INVOICED milestone timestamp is used as a proxy.

    Reference: APICS OM 14e Ch 16 §16.4 — on-time delivery (OTD) KPI.

    Parameters
    ----------
    jobs : list of JobOrder

    Returns
    -------
    float in [0.0, 1.0]; 1.0 if all delivered jobs hit the promised date;
    0.0 if no delivered jobs exist.
    """
    delivered_statuses = {JobStatus.DELIVERED, JobStatus.INVOICED}
    delivered_jobs = [
        j for j in jobs
        if j.current_status in delivered_statuses
    ]
    if not delivered_jobs:
        return 0.0

    on_time_count = 0
    for job in delivered_jobs:
        # Find the DELIVERED (or INVOICED) milestone timestamp
        delivery_ts: Optional[str] = None
        for m in job.history:
            if m.status in delivered_statuses:
                delivery_ts = m.timestamp_iso
                break  # take first DELIVERED milestone

        if delivery_ts is None:
            # No matching milestone — fallback to last milestone
            if job.history:
                delivery_ts = job.history[-1].timestamp_iso
            else:
                continue

        try:
            dt_delivery = _parse_iso_date(delivery_ts)
            dt_promised = _parse_iso_date(job.promised_delivery_iso)
            if dt_delivery <= dt_promised:
                on_time_count += 1
        except ValueError:
            pass

    return on_time_count / len(delivered_jobs)
