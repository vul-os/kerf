"""
Tests for kerf_plm.quote_to_delivery — Cimatron quote-to-delivery workflow.

Covers:
  1.  QUOTED → QUOTE_ACCEPTED appends milestone
  2.  Invalid transition raises ValueError
  3.  Cannot skip from QUOTED to SHIPPED
  4.  status_report returns by_status counts
  5.  status_report overdue_count correct
  6.  on_time_delivery_rate = 1.0 when all delivered on time
  7.  on_time_delivery_rate = 0.0 when all late
  8.  on_time_delivery_rate = 0.0 with no delivered jobs
  9.  Full workflow walk-through QUOTED → INVOICED
  10. QC_HOLD → PRODUCTION re-work loop allowed

All tests hermetic (no DB / filesystem / network).
"""
from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_plm.quote_to_delivery import (
    JobOrder,
    JobMilestone,
    JobStatus,
    transition_status,
    status_report,
    on_time_delivery_rate,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_job(
    job_id: str = "JOB-001",
    customer_id: str = "CUST-1",
    quote_id: str = "Q-001",
    quoted_amount_usd: float = 15000.0,
    promised_delivery_iso: str = "2026-08-01",
    status: JobStatus = JobStatus.QUOTED,
    history: list[JobMilestone] | None = None,
) -> JobOrder:
    if history is None:
        history = [
            JobMilestone(
                status=JobStatus.QUOTED,
                timestamp_iso="2026-06-01T08:00:00Z",
                actor="sales_user",
                notes="Initial quote issued",
            )
        ]
    return JobOrder(
        job_id=job_id,
        customer_id=customer_id,
        quote_id=quote_id,
        quoted_amount_usd=quoted_amount_usd,
        promised_delivery_iso=promised_delivery_iso,
        current_status=status,
        history=history,
    )


def _advance_to(
    job: JobOrder,
    target: JobStatus,
    base_ts: str = "2026-06-01T08:00:00Z",
) -> JobOrder:
    """Walk job through every intermediate state to reach target."""
    pipeline = [
        JobStatus.QUOTED,
        JobStatus.QUOTE_ACCEPTED,
        JobStatus.DESIGN,
        JobStatus.MOLD_MAKING,
        JobStatus.SAMPLING,
        JobStatus.PRODUCTION,
        JobStatus.SHIPPED,
        JobStatus.DELIVERED,
        JobStatus.INVOICED,
    ]
    try:
        start_idx = pipeline.index(job.current_status)
        end_idx = pipeline.index(target)
    except ValueError:
        return job

    # Calculate a day offset per step for deterministic timestamps
    ts_day = int(base_ts[:10].split("-")[-1])
    for step_status in pipeline[start_idx + 1: end_idx + 1]:
        ts_day += 3
        ts = f"2026-06-{ts_day:02d}T12:00:00Z" if ts_day <= 30 else f"2026-07-{ts_day-30:02d}T12:00:00Z"
        job = transition_status(job, step_status, actor="system", timestamp_iso=ts)
    return job


# ---------------------------------------------------------------------------
# Test 1: QUOTED → QUOTE_ACCEPTED appends milestone
# ---------------------------------------------------------------------------

def test_transition_quoted_to_accepted_appends_milestone():
    job = _make_job()
    updated = transition_status(
        job,
        JobStatus.QUOTE_ACCEPTED,
        actor="mgr_alice",
        notes="Customer confirmed PO",
        timestamp_iso="2026-06-02T10:00:00Z",
    )
    # One initial + one new
    assert len(updated.history) == 2
    last = updated.history[-1]
    assert last.status == JobStatus.QUOTE_ACCEPTED
    assert last.actor == "mgr_alice"
    assert last.notes == "Customer confirmed PO"
    assert updated.current_status == JobStatus.QUOTE_ACCEPTED


# ---------------------------------------------------------------------------
# Test 2: Invalid transition raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_transition_raises():
    job = _make_job(status=JobStatus.DESIGN, history=[
        JobMilestone(JobStatus.QUOTED, "2026-06-01T08:00:00Z", "s"),
        JobMilestone(JobStatus.QUOTE_ACCEPTED, "2026-06-02T08:00:00Z", "s"),
        JobMilestone(JobStatus.DESIGN, "2026-06-03T08:00:00Z", "s"),
    ])
    with pytest.raises(ValueError, match="Invalid transition"):
        # DESIGN → SAMPLING is not a valid direct transition
        transition_status(job, JobStatus.SAMPLING, actor="eng")


# ---------------------------------------------------------------------------
# Test 3: Cannot skip from QUOTED to SHIPPED
# ---------------------------------------------------------------------------

def test_cannot_skip_quoted_to_shipped():
    job = _make_job()
    with pytest.raises(ValueError):
        transition_status(job, JobStatus.SHIPPED, actor="admin")


# ---------------------------------------------------------------------------
# Test 4: status_report returns by_status counts
# ---------------------------------------------------------------------------

def test_status_report_by_status_counts():
    jobs = [
        _make_job(job_id="J1", status=JobStatus.QUOTED),
        _make_job(job_id="J2", status=JobStatus.DESIGN, history=[
            JobMilestone(JobStatus.QUOTED, "2026-06-01T08:00:00Z", "s"),
            JobMilestone(JobStatus.QUOTE_ACCEPTED, "2026-06-02T08:00:00Z", "s"),
            JobMilestone(JobStatus.DESIGN, "2026-06-03T08:00:00Z", "s"),
        ]),
        _make_job(job_id="J3", status=JobStatus.QUOTED),
    ]
    report = status_report(jobs)
    assert "by_status" in report
    assert report["by_status"][JobStatus.QUOTED.value] == 2
    assert report["by_status"][JobStatus.DESIGN.value] == 1


# ---------------------------------------------------------------------------
# Test 5: status_report overdue_count correct
# ---------------------------------------------------------------------------

def test_status_report_overdue_count():
    # Create a job that is overdue: promised 2020-01-01, still DESIGN
    job_overdue = JobOrder(
        job_id="OD-1",
        customer_id="C1",
        quote_id="Q1",
        quoted_amount_usd=5000.0,
        promised_delivery_iso="2020-01-01",
        current_status=JobStatus.DESIGN,
        history=[
            JobMilestone(JobStatus.QUOTED, "2019-12-01T08:00:00Z", "s"),
            JobMilestone(JobStatus.QUOTE_ACCEPTED, "2019-12-05T08:00:00Z", "s"),
            JobMilestone(JobStatus.DESIGN, "2019-12-10T08:00:00Z", "s"),
        ],
        is_overdue=True,
    )
    job_ok = _make_job(job_id="OK-1", promised_delivery_iso="2030-01-01")
    report = status_report([job_overdue, job_ok])
    assert report["overdue_count"] == 1


# ---------------------------------------------------------------------------
# Test 6: on_time_delivery_rate = 1.0 when all delivered on time
# ---------------------------------------------------------------------------

def test_on_time_delivery_rate_all_on_time():
    job = _make_job(promised_delivery_iso="2026-07-01")
    job = _advance_to(job, JobStatus.DELIVERED)
    # Delivery milestone timestamp is 2026-06-19 (before 2026-07-01)
    rate = on_time_delivery_rate([job])
    assert rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Test 7: on_time_delivery_rate = 0.0 when all late
# ---------------------------------------------------------------------------

def test_on_time_delivery_rate_all_late():
    # Promised delivery in the past; delivery milestone after promised date
    history = [
        JobMilestone(JobStatus.QUOTED, "2025-01-01T08:00:00Z", "s"),
        JobMilestone(JobStatus.QUOTE_ACCEPTED, "2025-01-10T08:00:00Z", "s"),
        JobMilestone(JobStatus.DESIGN, "2025-01-20T08:00:00Z", "s"),
        JobMilestone(JobStatus.MOLD_MAKING, "2025-02-01T08:00:00Z", "s"),
        JobMilestone(JobStatus.SAMPLING, "2025-03-01T08:00:00Z", "s"),
        JobMilestone(JobStatus.PRODUCTION, "2025-04-01T08:00:00Z", "s"),
        JobMilestone(JobStatus.SHIPPED, "2025-05-15T08:00:00Z", "s"),
        JobMilestone(JobStatus.DELIVERED, "2025-06-01T08:00:00Z", "s"),  # LATE
    ]
    job = JobOrder(
        job_id="LATE-1",
        customer_id="C1",
        quote_id="Q1",
        quoted_amount_usd=8000.0,
        promised_delivery_iso="2025-04-01",  # promised April; delivered June
        current_status=JobStatus.DELIVERED,
        history=history,
        is_overdue=False,
    )
    rate = on_time_delivery_rate([job])
    assert rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 8: on_time_delivery_rate = 0.0 with no delivered jobs
# ---------------------------------------------------------------------------

def test_on_time_delivery_rate_no_delivered_jobs():
    jobs = [
        _make_job(job_id="J1"),
        _make_job(job_id="J2"),
    ]
    rate = on_time_delivery_rate(jobs)
    assert rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 9: Full workflow walk-through QUOTED → INVOICED
# ---------------------------------------------------------------------------

def test_full_workflow_quoted_to_invoiced():
    job = _make_job()
    steps = [
        (JobStatus.QUOTE_ACCEPTED, "2026-06-02T08:00:00Z"),
        (JobStatus.DESIGN,         "2026-06-05T08:00:00Z"),
        (JobStatus.MOLD_MAKING,    "2026-06-10T08:00:00Z"),
        (JobStatus.SAMPLING,       "2026-06-20T08:00:00Z"),
        (JobStatus.PRODUCTION,     "2026-06-25T08:00:00Z"),
        (JobStatus.SHIPPED,        "2026-07-01T08:00:00Z"),
        (JobStatus.DELIVERED,      "2026-07-03T08:00:00Z"),
        (JobStatus.INVOICED,       "2026-07-05T08:00:00Z"),
    ]
    for status, ts in steps:
        job = transition_status(job, status, actor="system", timestamp_iso=ts)

    assert job.current_status == JobStatus.INVOICED
    # history[0] = initial QUOTED, + 8 steps = 9 total
    assert len(job.history) == 9


# ---------------------------------------------------------------------------
# Test 10: QC_HOLD → PRODUCTION re-work loop allowed
# ---------------------------------------------------------------------------

def test_qc_hold_to_production_allowed():
    """
    QC hold can return to PRODUCTION for rework (ISA-95 rework loop).
    """
    job = _make_job(
        status=JobStatus.QC_HOLD,
        history=[
            JobMilestone(JobStatus.QUOTED, "2026-06-01T08:00:00Z", "s"),
            JobMilestone(JobStatus.QUOTE_ACCEPTED, "2026-06-02T08:00:00Z", "s"),
            JobMilestone(JobStatus.DESIGN, "2026-06-03T08:00:00Z", "s"),
            JobMilestone(JobStatus.MOLD_MAKING, "2026-06-05T08:00:00Z", "s"),
            JobMilestone(JobStatus.SAMPLING, "2026-06-10T08:00:00Z", "s"),
            JobMilestone(JobStatus.PRODUCTION, "2026-06-12T08:00:00Z", "s"),
            JobMilestone(JobStatus.QC_HOLD, "2026-06-15T08:00:00Z", "qc_inspector", "Dimensional failure"),
        ],
    )
    updated = transition_status(
        job,
        JobStatus.PRODUCTION,
        actor="eng_bob",
        notes="Rework complete",
        timestamp_iso="2026-06-18T08:00:00Z",
    )
    assert updated.current_status == JobStatus.PRODUCTION
    assert updated.history[-1].notes == "Rework complete"
