"""
tests/test_change_log_export.py
================================

Validation tests for kerf_plm.change_log_export.

References
----------
- ISO 10007:2003 §6     — Change control
- PMI PMBOK 7th ed §4.6 — Integrated Change Control (change log artefact)

Test matrix
-----------
CLE-01  5 entries → CSV has 6 rows (header + 5).
CLE-02  CSV header row contains all 8 column names.
CLE-03  Date filter: start_date excludes entries before it.
CLE-04  Date filter: end_date excludes entries after it.
CLE-05  Date filter: combined start+end range.
CLE-06  Date filter: entries with empty approval_date excluded when bounds given.
CLE-07  HTML contains <table>, <thead>, <tbody>.
CLE-08  HTML escapes special characters in summary (XSS check).
CLE-09  summary_stats: total count correct.
CLE-10  summary_stats: by_status counts correct.
CLE-11  summary_stats: by_urgency counts correct.
CLE-12  sort_by='urgency': emergency entries sort before normal, normal before deferred.
CLE-13  sort_by='approval_date': lexicographic ascending date order.
CLE-14  sort_by='ecn_id': alphabetical ECN ID order.
CLE-15  affected_components rendered as semicolon-separated in CSV row.
CLE-16  CSV commas in summary field are properly quoted (RFC 4180).
CLE-17  Re-export: EcnLogEntry, ChangeLogExportResult, export_change_log importable
        from kerf_plm top-level __init__.
CLE-18  Empty entries list → CSV has header only (1 row), HTML has empty tbody.
CLE-19  Invalid status raises ValueError on EcnLogEntry construction.
CLE-20  Invalid urgency raises ValueError on EcnLogEntry construction.
CLE-21  num_entries matches len(filtered entries).
CLE-22  date_range_start / date_range_end preserved in result.
CLE-23  honest_caveat is a non-empty string referencing ISO 10007 or PMBOK.
CLE-24  Empty start_date/end_date → no filtering applied.
"""

from __future__ import annotations

import csv
import io

import pytest

from kerf_plm.change_log_export import (
    EcnLogEntry,
    ChangeLogExportResult,
    export_change_log,
    HONEST_CAVEAT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_entry(
    ecn_id: str = "ECN-001",
    summary: str = "Test change",
    approval_date: str = "2026-01-15",
    status: str = "approved",
    urgency: str = "normal",
    affected_components: list[str] | None = None,
    requester: str = "eng-team",
    approver: str = "mgr-jones",
) -> EcnLogEntry:
    return EcnLogEntry(
        ecn_id=ecn_id,
        summary=summary,
        approval_date=approval_date,
        status=status,
        urgency=urgency,
        affected_components=affected_components or [],
        requester=requester,
        approver=approver,
    )


def five_entries() -> list[EcnLogEntry]:
    return [
        make_entry("ECN-001", "First change", "2026-01-10", "approved", "normal", ["P-001"]),
        make_entry("ECN-002", "Second change", "2026-02-05", "approved", "deferred", ["P-002"]),
        make_entry("ECN-003", "Third change", "2026-03-20", "closed", "emergency", ["P-003", "P-004"]),
        make_entry("ECN-004", "Fourth change", "2026-04-01", "in_progress", "normal", ["P-005"]),
        make_entry("ECN-005", "Fifth change", "2026-05-15", "draft", "deferred", []),
    ]


def parse_csv(csv_content: str) -> list[list[str]]:
    """Parse CSV content into a list of rows."""
    reader = csv.reader(io.StringIO(csv_content))
    return list(reader)


# ===========================================================================
# CLE-01  5 entries → CSV has 6 rows (header + 5)
# ===========================================================================

def test_cle01_csv_row_count():
    """5 entries → CSV has 6 rows (header + 5 data rows)."""
    result = export_change_log(five_entries())
    rows = parse_csv(result.csv_content)
    assert len(rows) == 6, f"Expected 6 rows (1 header + 5 data), got {len(rows)}"


# ===========================================================================
# CLE-02  CSV header row contains all 8 column names
# ===========================================================================

def test_cle02_csv_header_columns():
    """CSV header row contains all 8 expected column names."""
    result = export_change_log(five_entries())
    rows = parse_csv(result.csv_content)
    header = rows[0]
    expected_columns = [
        "ecn_id", "summary", "approval_date", "status",
        "urgency", "affected_components", "requester", "approver",
    ]
    assert header == expected_columns, f"Header mismatch: {header}"


# ===========================================================================
# CLE-03  Date filter: start_date excludes entries before it
# ===========================================================================

def test_cle03_start_date_filter():
    """start_date='2026-03-01' excludes ECN-001 (Jan) and ECN-002 (Feb)."""
    entries = five_entries()
    result = export_change_log(entries, start_date="2026-03-01")
    rows = parse_csv(result.csv_content)
    ecn_ids = [r[0] for r in rows[1:]]
    assert "ECN-001" not in ecn_ids
    assert "ECN-002" not in ecn_ids
    assert "ECN-003" in ecn_ids
    assert result.num_entries == 3


# ===========================================================================
# CLE-04  Date filter: end_date excludes entries after it
# ===========================================================================

def test_cle04_end_date_filter():
    """end_date='2026-02-28' excludes ECN-003, ECN-004, ECN-005."""
    entries = five_entries()
    result = export_change_log(entries, end_date="2026-02-28")
    rows = parse_csv(result.csv_content)
    ecn_ids = [r[0] for r in rows[1:]]
    assert "ECN-001" in ecn_ids
    assert "ECN-002" in ecn_ids
    assert "ECN-003" not in ecn_ids
    assert result.num_entries == 2


# ===========================================================================
# CLE-05  Date filter: combined start+end range
# ===========================================================================

def test_cle05_combined_date_filter():
    """start='2026-02-01', end='2026-04-30' includes only ECN-002, ECN-003, ECN-004."""
    entries = five_entries()
    result = export_change_log(entries, start_date="2026-02-01", end_date="2026-04-30")
    rows = parse_csv(result.csv_content)
    ecn_ids = [r[0] for r in rows[1:]]
    assert ecn_ids == ["ECN-002", "ECN-003", "ECN-004"]
    assert result.num_entries == 3


# ===========================================================================
# CLE-06  Date filter: empty approval_date excluded when bounds given
# ===========================================================================

def test_cle06_empty_date_excluded_when_bounds_set():
    """Entry with empty approval_date is excluded when any date bound is set."""
    entries = [
        make_entry("ECN-100", approval_date=""),   # no date
        make_entry("ECN-101", approval_date="2026-06-01"),
    ]
    result = export_change_log(entries, start_date="2026-01-01")
    rows = parse_csv(result.csv_content)
    ecn_ids = [r[0] for r in rows[1:]]
    assert "ECN-100" not in ecn_ids
    assert "ECN-101" in ecn_ids
    assert result.num_entries == 1


# ===========================================================================
# CLE-07  HTML contains <table>, <thead>, <tbody>
# ===========================================================================

def test_cle07_html_structure():
    """HTML output contains <table>, <thead>, <tbody> tags."""
    result = export_change_log(five_entries())
    html = result.html_content
    assert "<table" in html
    assert "<thead>" in html
    assert "<tbody>" in html
    assert "</table>" in html


# ===========================================================================
# CLE-08  HTML escapes special characters in summary (XSS check)
# ===========================================================================

def test_cle08_html_escapes_summary():
    """Special characters in summary are HTML-escaped (<, >, &, \")."""
    evil_summary = '<script>alert("xss")</script> & "quotes"'
    entry = make_entry("ECN-XSS", summary=evil_summary)
    result = export_change_log([entry])
    html = result.html_content
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


# ===========================================================================
# CLE-09  summary_stats: total count correct
# ===========================================================================

def test_cle09_summary_stats_total():
    """summary_stats.total equals number of entries in result."""
    entries = five_entries()
    result = export_change_log(entries)
    assert result.summary_stats["total"] == 5


# ===========================================================================
# CLE-10  summary_stats: by_status counts correct
# ===========================================================================

def test_cle10_summary_stats_by_status():
    """by_status counts match known statuses in the 5-entry fixture."""
    entries = five_entries()
    result = export_change_log(entries)
    by_status = result.summary_stats["by_status"]
    assert by_status["approved"] == 2    # ECN-001, ECN-002
    assert by_status["closed"] == 1      # ECN-003
    assert by_status["in_progress"] == 1 # ECN-004
    assert by_status["draft"] == 1       # ECN-005


# ===========================================================================
# CLE-11  summary_stats: by_urgency counts correct
# ===========================================================================

def test_cle11_summary_stats_by_urgency():
    """by_urgency counts match known urgencies in the 5-entry fixture."""
    entries = five_entries()
    result = export_change_log(entries)
    by_urgency = result.summary_stats["by_urgency"]
    assert by_urgency["normal"] == 2    # ECN-001, ECN-004
    assert by_urgency["deferred"] == 2  # ECN-002, ECN-005
    assert by_urgency["emergency"] == 1 # ECN-003


# ===========================================================================
# CLE-12  sort_by='urgency': emergency first, deferred last
# ===========================================================================

def test_cle12_sort_by_urgency():
    """sort_by='urgency' puts emergency first, normal second, deferred last."""
    entries = five_entries()
    result = export_change_log(entries, sort_by="urgency")
    rows = parse_csv(result.csv_content)
    # urgency column index = 4
    urgencies = [r[4] for r in rows[1:]]
    expected_order = ["emergency", "normal", "normal", "deferred", "deferred"]
    assert urgencies == expected_order, f"Got urgency order: {urgencies}"


# ===========================================================================
# CLE-13  sort_by='approval_date': ascending date order
# ===========================================================================

def test_cle13_sort_by_approval_date():
    """sort_by='approval_date' produces ascending ISO 8601 date order."""
    # Shuffle the entries so we don't rely on insertion order
    entries = [
        make_entry("ECN-C", approval_date="2026-03-01"),
        make_entry("ECN-A", approval_date="2026-01-01"),
        make_entry("ECN-B", approval_date="2026-02-01"),
    ]
    result = export_change_log(entries, sort_by="approval_date")
    rows = parse_csv(result.csv_content)
    ecn_ids = [r[0] for r in rows[1:]]
    assert ecn_ids == ["ECN-A", "ECN-B", "ECN-C"]


# ===========================================================================
# CLE-14  sort_by='ecn_id': alphabetical order
# ===========================================================================

def test_cle14_sort_by_ecn_id():
    """sort_by='ecn_id' produces alphabetical ECN ID order."""
    entries = [
        make_entry("ECN-ZZZ"),
        make_entry("ECN-AAA"),
        make_entry("ECN-MMM"),
    ]
    result = export_change_log(entries, sort_by="ecn_id")
    rows = parse_csv(result.csv_content)
    ecn_ids = [r[0] for r in rows[1:]]
    assert ecn_ids == ["ECN-AAA", "ECN-MMM", "ECN-ZZZ"]


# ===========================================================================
# CLE-15  affected_components rendered as semicolon list in CSV
# ===========================================================================

def test_cle15_affected_components_csv():
    """affected_components rendered as '; '-separated string in CSV."""
    entry = make_entry("ECN-X", affected_components=["P-001", "P-002", "P-003"])
    result = export_change_log([entry])
    rows = parse_csv(result.csv_content)
    # affected_components is column index 5
    assert rows[1][5] == "P-001; P-002; P-003"


# ===========================================================================
# CLE-16  CSV commas in summary field are properly quoted (RFC 4180)
# ===========================================================================

def test_cle16_csv_comma_in_summary_quoted():
    """Comma in summary is RFC 4180-quoted, not treated as a delimiter."""
    entry = make_entry("ECN-COMMA", summary="Replace bolt, washer, nut")
    result = export_change_log([entry])
    rows = parse_csv(result.csv_content)
    # csv.reader transparently un-quotes — summary should be preserved intact
    assert rows[1][1] == "Replace bolt, washer, nut"
    # And the raw CSV should contain the field quoted
    assert '"Replace bolt, washer, nut"' in result.csv_content


# ===========================================================================
# CLE-17  Re-export from kerf_plm top-level __init__
# ===========================================================================

def test_cle17_top_level_re_export():
    """EcnLogEntry, ChangeLogExportResult, export_change_log importable from kerf_plm."""
    from kerf_plm import (
        EcnLogEntry as _EL,
        ChangeLogExportResult as _CLR,
        export_change_log as _fn,
    )
    assert _EL is EcnLogEntry
    assert _CLR is ChangeLogExportResult
    assert _fn is export_change_log


# ===========================================================================
# CLE-18  Empty entries list → CSV has header only, HTML has empty tbody
# ===========================================================================

def test_cle18_empty_entries():
    """Empty entries list → 1 CSV row (header only), HTML tbody is empty of data rows."""
    result = export_change_log([])
    rows = parse_csv(result.csv_content)
    assert len(rows) == 1, f"Expected 1 header row, got {len(rows)}"
    # Check HTML tbody is present but has no <tr> inside
    import re
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", result.html_content, re.DOTALL)
    assert tbody_match is not None
    tbody_content = tbody_match.group(1).strip()
    assert "<tr>" not in tbody_content
    assert result.num_entries == 0


# ===========================================================================
# CLE-19  Invalid status raises ValueError
# ===========================================================================

def test_cle19_invalid_status_raises():
    """EcnLogEntry with invalid status raises ValueError."""
    with pytest.raises(ValueError, match="status"):
        EcnLogEntry(
            ecn_id="ECN-BAD",
            summary="test",
            approval_date="2026-01-01",
            status="pending",  # invalid
            urgency="normal",
        )


# ===========================================================================
# CLE-20  Invalid urgency raises ValueError
# ===========================================================================

def test_cle20_invalid_urgency_raises():
    """EcnLogEntry with invalid urgency raises ValueError."""
    with pytest.raises(ValueError, match="urgency"):
        EcnLogEntry(
            ecn_id="ECN-BAD",
            summary="test",
            approval_date="2026-01-01",
            status="approved",
            urgency="critical",  # invalid
        )


# ===========================================================================
# CLE-21  num_entries matches len(filtered entries)
# ===========================================================================

def test_cle21_num_entries_after_filter():
    """num_entries equals the actual number of entries after date filtering."""
    entries = five_entries()
    result = export_change_log(entries, start_date="2026-03-01", end_date="2026-04-30")
    rows = parse_csv(result.csv_content)
    data_rows = rows[1:]
    assert result.num_entries == len(data_rows)
    assert result.num_entries == 2  # ECN-003, ECN-004


# ===========================================================================
# CLE-22  date_range_start / date_range_end preserved in result
# ===========================================================================

def test_cle22_date_range_preserved_in_result():
    """date_range_start and date_range_end are copied verbatim to the result."""
    result = export_change_log(
        five_entries(),
        start_date="2026-02-01",
        end_date="2026-05-31",
    )
    assert result.date_range_start == "2026-02-01"
    assert result.date_range_end == "2026-05-31"


# ===========================================================================
# CLE-23  honest_caveat references ISO 10007 or PMBOK
# ===========================================================================

def test_cle23_honest_caveat_content():
    """honest_caveat is non-empty and references ISO 10007 or PMBOK."""
    result = export_change_log(five_entries())
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 20
    caveat_upper = result.honest_caveat.upper()
    assert "ISO 10007" in caveat_upper or "PMBOK" in caveat_upper or "4.6" in result.honest_caveat


# ===========================================================================
# CLE-24  No bounds → no filtering applied
# ===========================================================================

def test_cle24_no_bounds_no_filtering():
    """Calling export_change_log with no date bounds includes all entries."""
    entries = five_entries()
    # Mix in an entry with empty approval_date
    entries.append(make_entry("ECN-NODDATE", approval_date=""))
    result = export_change_log(entries)
    assert result.num_entries == 6
    rows = parse_csv(result.csv_content)
    assert len(rows) == 7  # header + 6
