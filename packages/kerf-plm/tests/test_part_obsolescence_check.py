"""
tests/test_part_obsolescence_check.py
======================================

Validation tests for kerf_plm.part_obsolescence_check.

Per IEC 62402:2019 (Obsolescence management — Application guide) and the
US DoD DMSMS Handbook (2018) §2.3 + §4.1.

Test matrix
-----------
POC-01  All active parts → risk_score == 0.0, num_active == total, no alerts.
POC-02  All preferred parts → risk_score == 0.0.
POC-03  5-part mix (active, preferred, NRND, LTB, EOL) → risk_score correct.
POC-04  5-part mix with obsolete → risk_score correct per formula.
POC-05  Single obsolete part → risk_score == 100.0.
POC-06  Affected assemblies populated from BOM relationships.
POC-07  BOM relationship with no at-risk parts → affected_assemblies empty.
POC-08  Critical alerts include all EOL parts with alternative_pn.
POC-09  Critical alerts include all obsolete parts.
POC-10  NRND parts do NOT appear in critical_part_alerts.
POC-11  LTB parts do NOT appear in critical_part_alerts.
POC-12  Empty parts list → zero-risk report, all counts 0.
POC-13  bom_relationships=None → affected_assemblies empty.
POC-14  Invalid status raises ValueError.
POC-15  Empty part_number raises ValueError.
POC-16  Empty manufacturer raises ValueError.
POC-17  Re-export: all public names importable from kerf_plm.
POC-18  honest_caveat is non-empty string in every report.
POC-19  Multiple at-risk parts in same assembly → assembly appears once.
POC-20  PartLifecycleStatus constants match expected string values.
POC-21  num_at_risk = NRND + LTB + EOL count (not obsolete).
POC-22  num_obsolete correctly populated.
"""

from __future__ import annotations

import pytest

from kerf_plm.part_obsolescence_check import (
    PartLifecycleStatus,
    PartLifecycleEntry,
    ObsolescenceReport,
    check_part_obsolescence,
    HONEST_CAVEAT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_entry(
    part_number: str = "PN-001",
    manufacturer: str = "ACME",
    status: str = "active",
    last_buy_date: str | None = None,
    alternative_pn: str | None = None,
) -> PartLifecycleEntry:
    return PartLifecycleEntry(
        part_number=part_number,
        manufacturer=manufacturer,
        status=status,
        last_buy_date=last_buy_date,
        alternative_pn=alternative_pn,
    )


def make_bom_rel(parent_pn: str, child_pn: str) -> dict:
    return {"parent_pn": parent_pn, "child_pn": child_pn}


# ---------------------------------------------------------------------------
# POC-01 — all active → risk_score == 0.0
# ---------------------------------------------------------------------------

def test_poc01_all_active_zero_risk():
    parts = [make_entry(f"PN-{i:03d}", status="active") for i in range(5)]
    report = check_part_obsolescence(parts)
    assert report.risk_score == pytest.approx(0.0)
    assert report.num_active == 5
    assert report.num_at_risk == 0
    assert report.num_obsolete == 0
    assert report.critical_part_alerts == []
    assert report.total_parts == 5


# ---------------------------------------------------------------------------
# POC-02 — all preferred → risk_score == 0.0
# ---------------------------------------------------------------------------

def test_poc02_all_preferred_zero_risk():
    parts = [make_entry(f"PN-{i:03d}", status="preferred") for i in range(3)]
    report = check_part_obsolescence(parts)
    assert report.risk_score == pytest.approx(0.0)
    assert report.num_active == 3
    assert report.num_at_risk == 0
    assert report.num_obsolete == 0


# ---------------------------------------------------------------------------
# POC-03 — 5-part mix (active, preferred, NRND, LTB, EOL)
#           risk_score = (0 + 0 + 1 + 3 + 5) / 5 * 10 = 18.0
# ---------------------------------------------------------------------------

def test_poc03_five_part_mix_no_obsolete():
    parts = [
        make_entry("A-001", status="active"),
        make_entry("A-002", status="preferred"),
        make_entry("A-003", status="NRND"),
        make_entry("A-004", status="LTB", last_buy_date="2025-12-31"),
        make_entry("A-005", status="EOL"),
    ]
    report = check_part_obsolescence(parts)
    # (0+0+1+3+5) / 5 * 10 = 9/5*10 = 18.0
    assert report.risk_score == pytest.approx(18.0)
    assert report.total_parts == 5
    assert report.num_active == 2   # active + preferred
    assert report.num_at_risk == 3  # NRND + LTB + EOL
    assert report.num_obsolete == 0


# ---------------------------------------------------------------------------
# POC-04 — 5-part mix with obsolete
#           Parts: active, NRND, LTB, EOL, obsolete
#           weights: 0, 1, 3, 5, 10  sum=19
#           risk_score = 19 / 5 * 10 = 38.0
# ---------------------------------------------------------------------------

def test_poc04_five_part_mix_with_obsolete():
    parts = [
        make_entry("P1", status="active"),
        make_entry("P2", status="NRND"),
        make_entry("P3", status="LTB", last_buy_date="2025-06-30"),
        make_entry("P4", status="EOL"),
        make_entry("P5", status="obsolete", alternative_pn="P5-ALT"),
    ]
    report = check_part_obsolescence(parts)
    # (0 + 1 + 3 + 5 + 10) / 5 * 10 = 19/5*10 = 38.0
    assert report.risk_score == pytest.approx(38.0)
    assert report.num_active == 1
    assert report.num_at_risk == 3   # NRND + LTB + EOL
    assert report.num_obsolete == 1
    assert report.total_parts == 5


# ---------------------------------------------------------------------------
# POC-05 — single obsolete → risk_score == 100.0
# ---------------------------------------------------------------------------

def test_poc05_single_obsolete_max_score():
    parts = [make_entry("OBS-001", status="obsolete")]
    report = check_part_obsolescence(parts)
    # 10 / 1 * 10 = 100.0
    assert report.risk_score == pytest.approx(100.0)
    assert report.num_obsolete == 1
    assert report.num_active == 0
    assert report.num_at_risk == 0


# ---------------------------------------------------------------------------
# POC-06 — affected assemblies populated correctly from BOM relationships
# ---------------------------------------------------------------------------

def test_poc06_affected_assemblies_populated():
    parts = [
        make_entry("C-001", status="active"),
        make_entry("C-002", status="EOL"),
        make_entry("C-003", status="obsolete"),
    ]
    bom = [
        make_bom_rel("ASSY-TOP", "C-001"),   # active — should not trigger
        make_bom_rel("ASSY-TOP", "C-002"),   # EOL — triggers
        make_bom_rel("SUB-ASSY", "C-003"),   # obsolete — triggers
        make_bom_rel("OTHER", "C-999"),      # unknown part — no match
    ]
    report = check_part_obsolescence(parts, bom)
    assert "ASSY-TOP" in report.affected_assemblies
    assert "SUB-ASSY" in report.affected_assemblies
    assert "OTHER" not in report.affected_assemblies
    assert len(report.affected_assemblies) == 2


# ---------------------------------------------------------------------------
# POC-07 — no at-risk parts → affected_assemblies empty even with BOM rels
# ---------------------------------------------------------------------------

def test_poc07_no_at_risk_assemblies_empty():
    parts = [
        make_entry("G-001", status="active"),
        make_entry("G-002", status="preferred"),
    ]
    bom = [
        make_bom_rel("ASSY-GOOD", "G-001"),
        make_bom_rel("ASSY-GOOD", "G-002"),
    ]
    report = check_part_obsolescence(parts, bom)
    assert report.affected_assemblies == []


# ---------------------------------------------------------------------------
# POC-08 — critical alerts include EOL parts with alternative_pn
# ---------------------------------------------------------------------------

def test_poc08_critical_alerts_include_eol():
    parts = [
        make_entry("E-001", status="EOL", alternative_pn="E-001-NEW"),
        make_entry("E-002", status="EOL", alternative_pn=None),
        make_entry("G-001", status="active"),
    ]
    report = check_part_obsolescence(parts)
    alert_pns = [a["part_number"] for a in report.critical_part_alerts]
    assert "E-001" in alert_pns
    assert "E-002" in alert_pns
    assert "G-001" not in alert_pns

    # Check alternative_pn is threaded through
    e001_alert = next(a for a in report.critical_part_alerts if a["part_number"] == "E-001")
    assert e001_alert["alternative_pn"] == "E-001-NEW"

    e002_alert = next(a for a in report.critical_part_alerts if a["part_number"] == "E-002")
    assert e002_alert["alternative_pn"] is None


# ---------------------------------------------------------------------------
# POC-09 — critical alerts include obsolete parts
# ---------------------------------------------------------------------------

def test_poc09_critical_alerts_include_obsolete():
    parts = [
        make_entry("OB-001", status="obsolete", alternative_pn="OB-001-REV"),
        make_entry("AC-001", status="active"),
    ]
    report = check_part_obsolescence(parts)
    alert_pns = [a["part_number"] for a in report.critical_part_alerts]
    assert "OB-001" in alert_pns
    assert "AC-001" not in alert_pns

    ob_alert = next(a for a in report.critical_part_alerts if a["part_number"] == "OB-001")
    assert ob_alert["status"] == "obsolete"
    assert ob_alert["alternative_pn"] == "OB-001-REV"


# ---------------------------------------------------------------------------
# POC-10 — NRND parts do NOT appear in critical_part_alerts
# ---------------------------------------------------------------------------

def test_poc10_nrnd_not_in_critical_alerts():
    parts = [
        make_entry("N-001", status="NRND"),
        make_entry("N-002", status="NRND"),
    ]
    report = check_part_obsolescence(parts)
    alert_pns = [a["part_number"] for a in report.critical_part_alerts]
    assert "N-001" not in alert_pns
    assert "N-002" not in alert_pns
    assert report.num_at_risk == 2


# ---------------------------------------------------------------------------
# POC-11 — LTB parts do NOT appear in critical_part_alerts
# ---------------------------------------------------------------------------

def test_poc11_ltb_not_in_critical_alerts():
    parts = [
        make_entry("L-001", status="LTB", last_buy_date="2024-06-30"),
    ]
    report = check_part_obsolescence(parts)
    alert_pns = [a["part_number"] for a in report.critical_part_alerts]
    assert "L-001" not in alert_pns
    assert report.num_at_risk == 1
    # LTB weight = 3; 3/1*10 = 30
    assert report.risk_score == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# POC-12 — empty parts list → zero-risk report
# ---------------------------------------------------------------------------

def test_poc12_empty_parts_list():
    report = check_part_obsolescence([])
    assert report.total_parts == 0
    assert report.num_active == 0
    assert report.num_at_risk == 0
    assert report.num_obsolete == 0
    assert report.risk_score == pytest.approx(0.0)
    assert report.critical_part_alerts == []
    assert report.affected_assemblies == []


# ---------------------------------------------------------------------------
# POC-13 — bom_relationships=None → affected_assemblies empty
# ---------------------------------------------------------------------------

def test_poc13_bom_relationships_none():
    parts = [make_entry("X-001", status="EOL")]
    report = check_part_obsolescence(parts, bom_relationships=None)
    assert report.affected_assemblies == []


# ---------------------------------------------------------------------------
# POC-14 — invalid status raises ValueError
# ---------------------------------------------------------------------------

def test_poc14_invalid_status_raises():
    with pytest.raises(ValueError, match="status"):
        make_entry("BAD-001", status="discontinued")


def test_poc14b_empty_status_raises():
    with pytest.raises(ValueError, match="status"):
        make_entry("BAD-002", status="")


# ---------------------------------------------------------------------------
# POC-15 — empty part_number raises ValueError
# ---------------------------------------------------------------------------

def test_poc15_empty_part_number_raises():
    with pytest.raises(ValueError, match="part_number must be a non-empty string"):
        make_entry("", status="active")


def test_poc15b_whitespace_part_number_raises():
    with pytest.raises(ValueError, match="part_number must be a non-empty string"):
        make_entry("   ", status="active")


# ---------------------------------------------------------------------------
# POC-16 — empty manufacturer raises ValueError
# ---------------------------------------------------------------------------

def test_poc16_empty_manufacturer_raises():
    with pytest.raises(ValueError, match="manufacturer must be a non-empty string"):
        PartLifecycleEntry(
            part_number="P-001",
            manufacturer="",
            status="active",
            last_buy_date=None,
            alternative_pn=None,
        )


# ---------------------------------------------------------------------------
# POC-17 — re-export from kerf_plm
# ---------------------------------------------------------------------------

def test_poc17_re_export_from_kerf_plm():
    from kerf_plm import PartLifecycleStatus as PLS
    from kerf_plm import PartLifecycleEntry as PLE
    from kerf_plm import ObsolescenceReport as OR_
    from kerf_plm import check_part_obsolescence as cpo

    assert PLS is PartLifecycleStatus
    assert PLE is PartLifecycleEntry
    assert OR_ is ObsolescenceReport
    assert cpo is check_part_obsolescence


# ---------------------------------------------------------------------------
# POC-18 — honest_caveat is non-empty in every report
# ---------------------------------------------------------------------------

def test_poc18_honest_caveat_always_present():
    scenarios = [
        [],
        [make_entry("P1", status="active")],
        [make_entry("P2", status="obsolete")],
        [make_entry("P3", status="NRND"), make_entry("P4", status="LTB")],
    ]
    for parts in scenarios:
        report = check_part_obsolescence(parts)
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 20, (
            f"honest_caveat too short: {report.honest_caveat!r}"
        )


# ---------------------------------------------------------------------------
# POC-19 — multiple at-risk parts in same assembly → assembly appears once
# ---------------------------------------------------------------------------

def test_poc19_deduplication_of_assembly():
    parts = [
        make_entry("C-A", status="EOL"),
        make_entry("C-B", status="obsolete"),
        make_entry("C-C", status="NRND"),
    ]
    bom = [
        make_bom_rel("ASSY-X", "C-A"),
        make_bom_rel("ASSY-X", "C-B"),  # same parent
        make_bom_rel("ASSY-X", "C-C"),  # same parent again
    ]
    report = check_part_obsolescence(parts, bom)
    assert report.affected_assemblies.count("ASSY-X") == 1
    assert len(report.affected_assemblies) == 1


# ---------------------------------------------------------------------------
# POC-20 — PartLifecycleStatus constants are correct string values
# ---------------------------------------------------------------------------

def test_poc20_lifecycle_status_constants():
    assert PartLifecycleStatus.ACTIVE == "active"
    assert PartLifecycleStatus.PREFERRED == "preferred"
    assert PartLifecycleStatus.NRND == "NRND"
    assert PartLifecycleStatus.LTB == "LTB"
    assert PartLifecycleStatus.EOL == "EOL"
    assert PartLifecycleStatus.OBSOLETE == "obsolete"

    assert PartLifecycleStatus.is_valid("active")
    assert PartLifecycleStatus.is_valid("NRND")
    assert not PartLifecycleStatus.is_valid("discontinued")


# ---------------------------------------------------------------------------
# POC-21 — num_at_risk counts only NRND + LTB + EOL (not obsolete)
# ---------------------------------------------------------------------------

def test_poc21_num_at_risk_excludes_obsolete():
    parts = [
        make_entry("R1", status="NRND"),
        make_entry("R2", status="LTB"),
        make_entry("R3", status="EOL"),
        make_entry("R4", status="obsolete"),
        make_entry("R5", status="active"),
    ]
    report = check_part_obsolescence(parts)
    assert report.num_at_risk == 3   # NRND + LTB + EOL
    assert report.num_obsolete == 1
    assert report.num_active == 1    # active + preferred


# ---------------------------------------------------------------------------
# POC-22 — num_obsolete correctly counted across multiple obsolete parts
# ---------------------------------------------------------------------------

def test_poc22_num_obsolete_correct():
    parts = [
        make_entry("O1", status="obsolete"),
        make_entry("O2", status="obsolete"),
        make_entry("O3", status="obsolete"),
        make_entry("A1", status="active"),
    ]
    report = check_part_obsolescence(parts)
    assert report.num_obsolete == 3
    assert report.num_active == 1
    assert report.total_parts == 4
    # (10+10+10+0) / 4 * 10 = 30/4*10 = 75.0
    assert report.risk_score == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# Additional: risk_score formula — 10 mixed parts
# ---------------------------------------------------------------------------

def test_risk_score_ten_parts():
    # 2 NRND, 3 LTB, 2 EOL, 1 obsolete, 2 active
    parts = [
        make_entry("N1", status="NRND"),
        make_entry("N2", status="NRND"),
        make_entry("L1", status="LTB"),
        make_entry("L2", status="LTB"),
        make_entry("L3", status="LTB"),
        make_entry("E1", status="EOL"),
        make_entry("E2", status="EOL"),
        make_entry("OB1", status="obsolete"),
        make_entry("A1", status="active"),
        make_entry("A2", status="active"),
    ]
    report = check_part_obsolescence(parts)
    # weights: NRND*2*1 + LTB*3*3 + EOL*2*5 + obs*1*10 + act*2*0
    # = 2 + 9 + 10 + 10 = 31
    # risk_score = 31/10*10 = 31.0
    assert report.risk_score == pytest.approx(31.0)
    assert report.num_at_risk == 7   # 2+3+2
    assert report.num_obsolete == 1
    assert report.num_active == 2


# ---------------------------------------------------------------------------
# Additional: last_buy_date is threaded through to the alert dict
# ---------------------------------------------------------------------------

def test_last_buy_date_in_alert():
    parts = [
        make_entry("LB-001", status="EOL", last_buy_date="2024-03-31"),
    ]
    report = check_part_obsolescence(parts)
    assert len(report.critical_part_alerts) == 1
    alert = report.critical_part_alerts[0]
    assert alert["last_buy_date"] == "2024-03-31"
    assert alert["manufacturer"] == "ACME"
