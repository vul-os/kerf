"""
kerf_plm.change_log_export — ECN change-log export to CSV and HTML.

References
----------
- ISO 10007:2003 §6     — Change control (ECN lifecycle, approval records)
- PMI PMBOK 7th ed §4.6 — Integrated Change Control (change log artefact)

Public API
----------
    EcnLogEntry        — dataclass: one ECN row in the change log
    ChangeLogExportResult — dataclass: CSV + HTML outputs + summary stats
    export_change_log  — function: filter + sort + render
"""

from __future__ import annotations

import csv
import html
import io
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = frozenset({"draft", "approved", "in_progress", "closed", "cancelled"})
VALID_URGENCIES = frozenset({"emergency", "normal", "deferred"})

# Urgency sort key: emergency first, deferred last
_URGENCY_ORDER = {"emergency": 0, "normal": 1, "deferred": 2}

HONEST_CAVEAT = (
    "ISO 10007 §6 / PMBOK §4.6 change-log export — in-memory only: no DB "
    "pagination for large change-log sets; all entries must fit in RAM. "
    "Exported CSV/HTML represent a snapshot at export time; no live sync with "
    "a PLM or ERP back-end. Approval-date sorting uses lexicographic ISO 8601 "
    "comparison; UTC timezone normalisation is the caller's responsibility."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EcnLogEntry:
    """One Engineering Change Notice (ECN) entry in the change log.

    Parameters
    ----------
    ecn_id:
        Unique ECN identifier, e.g. ``"ECN-2026-001"``.
    summary:
        Short description of the change (free text; commas are escaped in CSV).
    approval_date:
        ISO 8601 date string (``"YYYY-MM-DD"``).  Use ``""`` for unapproved entries.
    status:
        Lifecycle state: one of ``draft | approved | in_progress | closed | cancelled``.
    affected_components:
        Part numbers / component IDs impacted by this ECN.
    urgency:
        Priority class: ``emergency | normal | deferred`` (ISO 10007 §6.3).
    requester:
        User or team that initiated the ECN.
    approver:
        User or team that approved the ECN (empty string if not yet approved).
    """

    ecn_id: str
    summary: str
    approval_date: str  # ISO 8601, e.g. "2026-03-15"
    status: str  # draft | approved | in_progress | closed | cancelled
    affected_components: list[str] = field(default_factory=list)
    urgency: str = "normal"  # emergency | normal | deferred
    requester: str = ""
    approver: str = ""

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"EcnLogEntry.status must be one of {sorted(VALID_STATUSES)}, "
                f"got {self.status!r}"
            )
        if self.urgency not in VALID_URGENCIES:
            raise ValueError(
                f"EcnLogEntry.urgency must be one of {sorted(VALID_URGENCIES)}, "
                f"got {self.urgency!r}"
            )


@dataclass
class ChangeLogExportResult:
    """Result of :func:`export_change_log`.

    Parameters
    ----------
    csv_content:
        RFC 4180 CSV string (header row + one row per entry).
    html_content:
        HTML string containing a ``<table>`` with ``<thead>`` and ``<tbody>``.
    num_entries:
        Number of ECN entries in the exported result (after date filtering).
    date_range_start:
        Effective start bound used for filtering (``""`` if unbounded).
    date_range_end:
        Effective end bound used for filtering (``""`` if unbounded).
    summary_stats:
        Dict with keys ``total``, ``by_status`` (dict), ``by_urgency`` (dict).
    honest_caveat:
        Honest statement of limitations per ISO 10007 §6 / PMBOK §4.6.
    """

    csv_content: str
    html_content: str
    num_entries: int
    date_range_start: str
    date_range_end: str
    summary_stats: dict
    honest_caveat: str


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

_CSV_HEADERS = [
    "ecn_id",
    "summary",
    "approval_date",
    "status",
    "urgency",
    "affected_components",
    "requester",
    "approver",
]


def _entry_to_csv_row(entry: EcnLogEntry) -> list[str]:
    """Convert one EcnLogEntry to a list of strings for csv.writer."""
    return [
        entry.ecn_id,
        entry.summary,  # csv.writer handles quoting/escaping
        entry.approval_date,
        entry.status,
        entry.urgency,
        "; ".join(entry.affected_components),
        entry.requester,
        entry.approver,
    ]


def _render_csv(entries: list[EcnLogEntry]) -> str:
    """Render entries to RFC 4180 CSV (header + rows)."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(_CSV_HEADERS)
    for entry in entries:
        writer.writerow(_entry_to_csv_row(entry))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_HTML_COLUMN_LABELS = [
    "ECN ID",
    "Summary",
    "Approval Date",
    "Status",
    "Urgency",
    "Affected Components",
    "Requester",
    "Approver",
]

_STATUS_CSS: dict[str, str] = {
    "draft": "color:#888",
    "approved": "color:#2a7a2a;font-weight:bold",
    "in_progress": "color:#b85c00",
    "closed": "color:#333",
    "cancelled": "color:#b00;text-decoration:line-through",
}

_URGENCY_CSS: dict[str, str] = {
    "emergency": "color:#b00;font-weight:bold",
    "normal": "",
    "deferred": "color:#888",
}


def _td(value: str, style: str = "") -> str:
    escaped = html.escape(value)
    if style:
        return f'<td style="{style}">{escaped}</td>'
    return f"<td>{escaped}</td>"


def _render_html(entries: list[EcnLogEntry]) -> str:
    """Render entries to an HTML table string."""
    lines: list[str] = []
    lines.append('<table border="1" cellpadding="4" cellspacing="0" '
                 'style="border-collapse:collapse;font-family:sans-serif;font-size:13px">')

    # thead
    lines.append("  <thead>")
    lines.append("    <tr>")
    for label in _HTML_COLUMN_LABELS:
        lines.append(f'      <th style="background:#f0f0f0">{html.escape(label)}</th>')
    lines.append("    </tr>")
    lines.append("  </thead>")

    # tbody
    lines.append("  <tbody>")
    for entry in entries:
        lines.append("    <tr>")
        lines.append("      " + _td(entry.ecn_id))
        lines.append("      " + _td(entry.summary))
        lines.append("      " + _td(entry.approval_date))
        lines.append("      " + _td(entry.status, _STATUS_CSS.get(entry.status, "")))
        lines.append("      " + _td(entry.urgency, _URGENCY_CSS.get(entry.urgency, "")))
        lines.append("      " + _td("; ".join(entry.affected_components)))
        lines.append("      " + _td(entry.requester))
        lines.append("      " + _td(entry.approver))
        lines.append("    </tr>")
    lines.append("  </tbody>")

    lines.append("</table>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

def _compute_summary_stats(entries: list[EcnLogEntry]) -> dict:
    by_status: dict[str, int] = {}
    by_urgency: dict[str, int] = {}
    for e in entries:
        by_status[e.status] = by_status.get(e.status, 0) + 1
        by_urgency[e.urgency] = by_urgency.get(e.urgency, 0) + 1
    return {
        "total": len(entries),
        "by_status": by_status,
        "by_urgency": by_urgency,
    }


# ---------------------------------------------------------------------------
# Sort key
# ---------------------------------------------------------------------------

def _sort_key(entry: EcnLogEntry, sort_by: str):
    if sort_by == "approval_date":
        # Lexicographic ISO 8601 sorts correctly; empty string sorts last
        return entry.approval_date if entry.approval_date else "\xff"
    if sort_by == "urgency":
        return _URGENCY_ORDER.get(entry.urgency, 99)
    if sort_by == "status":
        return entry.status
    if sort_by == "ecn_id":
        return entry.ecn_id
    # Default: approval_date
    return entry.approval_date if entry.approval_date else "\xff"


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def export_change_log(
    entries: list[EcnLogEntry],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort_by: str = "approval_date",
) -> ChangeLogExportResult:
    """Export a list of ECN entries as a structured CSV and HTML change log.

    Per ISO 10007 §6 (Change control) and PMI PMBOK §4.6 (Integrated Change
    Control), a change log must record each change's ID, description, status,
    and approval date.

    Parameters
    ----------
    entries:
        Input ECN entries.  Validation is performed by ``EcnLogEntry.__post_init__``.
    start_date:
        Optional ISO 8601 date string (inclusive lower bound on approval_date).
        Entries with an empty approval_date are excluded when a start_date is given.
    end_date:
        Optional ISO 8601 date string (inclusive upper bound on approval_date).
        Entries with an empty approval_date are excluded when an end_date is given.
    sort_by:
        Sort key.  One of: ``approval_date`` (default), ``urgency``, ``status``,
        ``ecn_id``.  For ``urgency``, emergency entries sort first.

    Returns
    -------
    ChangeLogExportResult
        ``csv_content``: RFC 4180 CSV (header + rows, commas in summary quoted).
        ``html_content``: HTML ``<table>`` with ``<thead>``/``<tbody>``.
        ``summary_stats``: ``{total, by_status, by_urgency}``.
        ``honest_caveat``: Honest statement of in-memory limitation.

    Notes
    -----
    - In-memory only; no DB pagination for large change-log sets.
    - CSV commas inside the ``summary`` field are escaped by the standard
      :mod:`csv` module (RFC 4180 double-quoting).
    """
    # --- Date filter ---
    filtered: list[EcnLogEntry] = []
    for e in entries:
        if start_date or end_date:
            d = e.approval_date
            if not d:
                # No date → exclude when any date bound is set
                continue
            if start_date and d < start_date:
                continue
            if end_date and d > end_date:
                continue
        filtered.append(e)

    # --- Sort ---
    filtered.sort(key=lambda e: _sort_key(e, sort_by))

    # --- Render ---
    csv_content = _render_csv(filtered)
    html_content = _render_html(filtered)
    summary_stats = _compute_summary_stats(filtered)

    return ChangeLogExportResult(
        csv_content=csv_content,
        html_content=html_content,
        num_entries=len(filtered),
        date_range_start=start_date or "",
        date_range_end=end_date or "",
        summary_stats=summary_stats,
        honest_caveat=HONEST_CAVEAT,
    )
