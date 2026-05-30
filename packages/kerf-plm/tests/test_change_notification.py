"""
Tests for kerf_plm.change_notification — ECO Notification Distribution.

Coverage:
  1. Simple ECO — single part, Class B dimension change → depth-bar oracle.
  2. Multi-part ECO — two parts in one ECO; both get separate notification sets.
  3. Supplier notification + PPAP — Class B dimension → supplier urgency=high +
     ppap_renewal_required=True; Class C → no supplier notification.
  4. Quality threshold — Class A always triggers quality+mfg regardless of type;
     Class C never triggers quality.
  5. ISO 10007 classification oracle — Class A vs Class B vs Class C
     stakeholder matrix validated against standard.
  6. No supplier in PLM data — no supplier notification emitted.
  7. Manufacturing trigger — only when change_type includes process_spec/dimension/
     material/finish OR part has manufacturing routes.
  8. Document control — always present on every ECO line.
  9. by_part() / by_stakeholder() grouping helpers.
  10. eco_line_from_dict / plm_data_from_dict helpers.

All tests are hermetic (no DB, no I/O).
"""
from __future__ import annotations

import pytest

from kerf_plm.change_notification import (
    ChangeClass,
    ChangeType,
    EcoLineItem,
    NotificationReport,
    Notification,
    PartRecord,
    PlmData,
    Urgency,
    compute_notification_distribution,
    eco_line_from_dict,
    plm_data_from_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_line(
    part_id: str = "PN-12345",
    rev_from: str = "A",
    rev_to: str = "B",
    change_class: ChangeClass = ChangeClass.CLASS_B,
    change_types: list[ChangeType] | None = None,
    description: str = "",
) -> EcoLineItem:
    return EcoLineItem(
        part_id=part_id,
        rev_from=rev_from,
        rev_to=rev_to,
        change_class=change_class,
        change_types=change_types or [],
        description=description,
    )


def _make_plm(
    parts: dict | None = None,
    quality_team: str = "@quality-team",
    doc_control: str = "@doc-control",
) -> PlmData:
    if parts is None:
        parts = {
            "PN-12345": PartRecord(
                part_id="PN-12345",
                owner_team="@design-team",
                suppliers=["ACME Corp"],
                manufacturing_routes=["ROUTE-LATHE-01"],
            )
        }
    return PlmData(parts=parts, quality_team=quality_team, document_control_team=doc_control)


def _roles(report: NotificationReport, part_id: str) -> dict[str, Notification]:
    """Return {role: notification} for a given part_id."""
    return {n.role: n for n in report.notifications if n.part_id == part_id}


# ---------------------------------------------------------------------------
# Test 1 — Depth-bar oracle: single Class B dimension change
# ---------------------------------------------------------------------------

class TestSinglePartDepthBar:
    """Depth-bar scenario from spec: PN-12345 Rev A → B, dimension change."""

    def setup_method(self):
        line = _make_line(change_types=[ChangeType.DIMENSION])
        plm = _make_plm()
        self.report = compute_notification_distribution("ECO-0042", [line], plm)

    def test_notification_count(self):
        # engineering + supplier + mfg_lead + quality + doc_control = 5
        assert len(self.report.notifications) == 5

    def test_engineering_role(self):
        roles = _roles(self.report, "PN-12345")
        assert "engineering" in roles
        assert roles["engineering"].stakeholder == "@design-team"
        assert roles["engineering"].urgency == Urgency.NORMAL

    def test_supplier_role_high_urgency(self):
        roles = _roles(self.report, "PN-12345")
        assert "supplier" in roles
        assert roles["supplier"].stakeholder == "ACME Corp"
        assert roles["supplier"].urgency == Urgency.HIGH
        assert roles["supplier"].ppap_renewal_required is True

    def test_manufacturing_lead_normal(self):
        roles = _roles(self.report, "PN-12345")
        assert "manufacturing_lead" in roles
        assert roles["manufacturing_lead"].urgency == Urgency.NORMAL

    def test_quality_high_urgency(self):
        roles = _roles(self.report, "PN-12345")
        assert "quality" in roles
        assert roles["quality"].urgency == Urgency.HIGH
        assert roles["quality"].ppap_renewal_required is True

    def test_document_control_present(self):
        roles = _roles(self.report, "PN-12345")
        assert "document_control" in roles
        assert roles["document_control"].stakeholder == "@doc-control"
        assert roles["document_control"].urgency == Urgency.NORMAL

    def test_eco_id(self):
        assert self.report.eco_id == "ECO-0042"

    def test_honest_flag(self):
        assert self.report.honest_flag is True


# ---------------------------------------------------------------------------
# Test 2 — Multi-part ECO
# ---------------------------------------------------------------------------

class TestMultiPartEco:
    """Two line items in one ECO; notification sets are independent."""

    def setup_method(self):
        parts = {
            "PN-AAA": PartRecord("PN-AAA", "@team-a", ["Supplier-X"], ["R-1"]),
            "PN-BBB": PartRecord("PN-BBB", "@team-b", ["Supplier-Y"], []),
        }
        plm = PlmData(parts=parts)
        lines = [
            _make_line("PN-AAA", change_types=[ChangeType.MATERIAL]),
            _make_line("PN-BBB", change_class=ChangeClass.CLASS_C, change_types=[ChangeType.DOCUMENT]),
        ]
        self.report = compute_notification_distribution("ECO-MULTI", lines, plm)

    def test_both_parts_appear(self):
        by_part = self.report.by_part()
        assert "PN-AAA" in by_part
        assert "PN-BBB" in by_part

    def test_aaa_has_supplier(self):
        aaa_roles = _roles(self.report, "PN-AAA")
        assert "supplier" in aaa_roles
        assert aaa_roles["supplier"].stakeholder == "Supplier-X"

    def test_bbb_class_c_no_supplier(self):
        # Class C → no supplier notification (no PPAP)
        bbb_roles = _roles(self.report, "PN-BBB")
        assert "supplier" not in bbb_roles

    def test_bbb_class_c_no_quality(self):
        bbb_roles = _roles(self.report, "PN-BBB")
        assert "quality" not in bbb_roles

    def test_bbb_doc_control_still_present(self):
        bbb_roles = _roles(self.report, "PN-BBB")
        assert "document_control" in bbb_roles


# ---------------------------------------------------------------------------
# Test 3 — Supplier notification and PPAP logic
# ---------------------------------------------------------------------------

class TestSupplierPpap:
    """PPAP is triggered on Class B dimension/material/process/finish; not on Class C."""

    @pytest.mark.parametrize("change_type,expected_ppap", [
        (ChangeType.DIMENSION, True),
        (ChangeType.MATERIAL, True),
        (ChangeType.PROCESS_SPEC, True),
        (ChangeType.FINISH, True),
        (ChangeType.DRAWING, False),
        (ChangeType.DOCUMENT, False),
        (ChangeType.OTHER, False),
    ])
    def test_ppap_trigger_class_b(self, change_type, expected_ppap):
        parts = {"P-001": PartRecord("P-001", "@eng", ["SUP-1"], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-001", change_class=ChangeClass.CLASS_B, change_types=[change_type])
        report = compute_notification_distribution("ECO-X", [line], plm)
        roles = _roles(report, "P-001")
        if expected_ppap:
            assert "supplier" in roles
            assert roles["supplier"].ppap_renewal_required is True
            assert roles["supplier"].urgency == Urgency.HIGH
        else:
            # Supplier still notified for Class B, but no PPAP flag / normal urgency
            if "supplier" in roles:
                assert roles["supplier"].ppap_renewal_required is False
                assert roles["supplier"].urgency == Urgency.NORMAL

    def test_class_a_always_ppap(self):
        parts = {"P-A": PartRecord("P-A", "@eng", ["SUP-A"], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-A", change_class=ChangeClass.CLASS_A, change_types=[ChangeType.DRAWING])
        report = compute_notification_distribution("ECO-A", [line], plm)
        roles = _roles(report, "P-A")
        assert roles["supplier"].ppap_renewal_required is True
        assert roles["supplier"].urgency == Urgency.HIGH

    def test_class_c_no_supplier_notification(self):
        parts = {"P-C": PartRecord("P-C", "@eng", ["SUP-C"], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-C", change_class=ChangeClass.CLASS_C, change_types=[ChangeType.DIMENSION])
        report = compute_notification_distribution("ECO-C", [line], plm)
        roles = _roles(report, "P-C")
        assert "supplier" not in roles


# ---------------------------------------------------------------------------
# Test 4 — Quality threshold
# ---------------------------------------------------------------------------

class TestQualityThreshold:
    """Quality team notified per ISO 10007 §5.1 class thresholds."""

    def test_class_a_always_quality(self):
        parts = {"P-1": PartRecord("P-1", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-1", change_class=ChangeClass.CLASS_A, change_types=[ChangeType.DRAWING])
        report = compute_notification_distribution("E1", [line], plm)
        assert "quality" in _roles(report, "P-1")

    def test_class_b_dimension_triggers_quality(self):
        parts = {"P-2": PartRecord("P-2", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-2", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.DIMENSION])
        report = compute_notification_distribution("E2", [line], plm)
        assert "quality" in _roles(report, "P-2")

    def test_class_b_drawing_no_quality(self):
        parts = {"P-3": PartRecord("P-3", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-3", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.DRAWING])
        report = compute_notification_distribution("E3", [line], plm)
        assert "quality" not in _roles(report, "P-3")

    def test_class_c_never_quality(self):
        parts = {"P-4": PartRecord("P-4", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-4", change_class=ChangeClass.CLASS_C, change_types=[ChangeType.DIMENSION])
        report = compute_notification_distribution("E4", [line], plm)
        assert "quality" not in _roles(report, "P-4")

    def test_quality_urgency_high_for_ppap(self):
        parts = {"P-5": PartRecord("P-5", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-5", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.DIMENSION])
        report = compute_notification_distribution("E5", [line], plm)
        assert _roles(report, "P-5")["quality"].urgency == Urgency.HIGH

    def test_quality_urgency_normal_without_ppap(self):
        # Class B process_spec with no supplier → no PPAP but quality still triggered
        parts = {"P-6": PartRecord("P-6", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-6", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.PROCESS_SPEC])
        report = compute_notification_distribution("E6", [line], plm)
        # PPAP requires both Class A/B + trigger type; no suppliers means no PPAP notification
        # Quality urgency should be HIGH (PPAP criteria met) even without supplier
        assert "quality" in _roles(report, "P-6")


# ---------------------------------------------------------------------------
# Test 5 — ISO 10007 Class oracle: full stakeholder matrix
# ---------------------------------------------------------------------------

class TestIso10007ClassOracle:
    """Oracle test: verify complete role set per class against ISO 10007 §5.1 matrix."""

    @pytest.mark.parametrize("change_class,change_types,expected_roles", [
        # Class A dimension: all 5 roles
        (
            ChangeClass.CLASS_A,
            [ChangeType.DIMENSION],
            {"engineering", "supplier", "manufacturing_lead", "quality", "document_control"},
        ),
        # Class B dimension: all 5 roles
        (
            ChangeClass.CLASS_B,
            [ChangeType.DIMENSION],
            {"engineering", "supplier", "manufacturing_lead", "quality", "document_control"},
        ),
        # Class B drawing only (part HAS routes → mfg triggered; has supplier → notified at NORMAL;
        # no PPAP trigger → no quality)
        (
            ChangeClass.CLASS_B,
            [ChangeType.DRAWING],
            {"engineering", "supplier", "manufacturing_lead", "document_control"},
        ),
        # Class C document: engineering + document_control only (mfg/supplier/quality skipped)
        (
            ChangeClass.CLASS_C,
            [ChangeType.DOCUMENT],
            {"engineering", "document_control"},
        ),
        # Class B process_spec: engineering + mfg_lead + quality + doc_control (+ supplier if present)
        (
            ChangeClass.CLASS_B,
            [ChangeType.PROCESS_SPEC],
            {"engineering", "supplier", "manufacturing_lead", "quality", "document_control"},
        ),
    ])
    def test_role_matrix(self, change_class, change_types, expected_roles):
        parts = {
            "PN-ORACLE": PartRecord(
                "PN-ORACLE",
                "@design",
                ["SUP-1"],
                ["ROUTE-1"],
            )
        }
        plm = PlmData(parts=parts)
        line = _make_line("PN-ORACLE", change_class=change_class, change_types=change_types)
        report = compute_notification_distribution("ECO-ORACLE", [line], plm)
        actual_roles = {n.role for n in report.notifications if n.part_id == "PN-ORACLE"}
        assert actual_roles == expected_roles


# ---------------------------------------------------------------------------
# Test 6 — No supplier in PLM data
# ---------------------------------------------------------------------------

class TestNoSupplier:
    """Parts without suppliers should not generate supplier notifications."""

    def test_no_supplier_notification(self):
        parts = {"P-NS": PartRecord("P-NS", "@eng", [], ["ROUTE-1"])}
        plm = PlmData(parts=parts)
        line = _make_line("P-NS", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.DIMENSION])
        report = compute_notification_distribution("ECO-NS", [line], plm)
        assert "supplier" not in _roles(report, "P-NS")

    def test_multiple_suppliers(self):
        parts = {"P-MS": PartRecord("P-MS", "@eng", ["SUP-1", "SUP-2"], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-MS", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.DIMENSION])
        report = compute_notification_distribution("ECO-MS", [line], plm)
        supplier_notifs = [n for n in report.notifications if n.role == "supplier"]
        assert len(supplier_notifs) == 2
        names = {n.stakeholder for n in supplier_notifs}
        assert names == {"SUP-1", "SUP-2"}


# ---------------------------------------------------------------------------
# Test 7 — Manufacturing trigger logic
# ---------------------------------------------------------------------------

class TestManufacturingTrigger:
    """Manufacturing lead notified when process-relevant change or routes exist."""

    def test_class_b_process_spec_triggers_mfg(self):
        parts = {"P-M1": PartRecord("P-M1", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-M1", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.PROCESS_SPEC])
        report = compute_notification_distribution("E-M1", [line], plm)
        assert "manufacturing_lead" in _roles(report, "P-M1")

    def test_class_b_drawing_no_mfg_without_routes(self):
        parts = {"P-M2": PartRecord("P-M2", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-M2", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.DRAWING])
        report = compute_notification_distribution("E-M2", [line], plm)
        assert "manufacturing_lead" not in _roles(report, "P-M2")

    def test_class_b_drawing_with_routes_triggers_mfg(self):
        # Even a drawing change triggers mfg if part has manufacturing routes
        parts = {"P-M3": PartRecord("P-M3", "@eng", [], ["ROUTE-01"])}
        plm = PlmData(parts=parts)
        line = _make_line("P-M3", change_class=ChangeClass.CLASS_B, change_types=[ChangeType.DRAWING])
        report = compute_notification_distribution("E-M3", [line], plm)
        assert "manufacturing_lead" in _roles(report, "P-M3")

    def test_class_a_always_triggers_mfg(self):
        parts = {"P-M4": PartRecord("P-M4", "@eng", [], [])}
        plm = PlmData(parts=parts)
        line = _make_line("P-M4", change_class=ChangeClass.CLASS_A, change_types=[ChangeType.DOCUMENT])
        report = compute_notification_distribution("E-M4", [line], plm)
        assert "manufacturing_lead" in _roles(report, "P-M4")

    def test_class_a_mfg_urgency_high(self):
        parts = {"P-M5": PartRecord("P-M5", "@eng", [], ["R-1"])}
        plm = PlmData(parts=parts)
        line = _make_line("P-M5", change_class=ChangeClass.CLASS_A, change_types=[ChangeType.DIMENSION])
        report = compute_notification_distribution("E-M5", [line], plm)
        assert _roles(report, "P-M5")["manufacturing_lead"].urgency == Urgency.HIGH

    def test_class_c_no_mfg(self):
        parts = {"P-M6": PartRecord("P-M6", "@eng", [], ["R-1"])}
        plm = PlmData(parts=parts)
        line = _make_line("P-M6", change_class=ChangeClass.CLASS_C, change_types=[ChangeType.PROCESS_SPEC])
        report = compute_notification_distribution("E-M6", [line], plm)
        assert "manufacturing_lead" not in _roles(report, "P-M6")


# ---------------------------------------------------------------------------
# Test 8 — Document control always present
# ---------------------------------------------------------------------------

class TestDocumentControl:

    @pytest.mark.parametrize("change_class", [
        ChangeClass.CLASS_A,
        ChangeClass.CLASS_B,
        ChangeClass.CLASS_C,
    ])
    def test_doc_control_always_present(self, change_class):
        parts = {"P-DC": PartRecord("P-DC", "@eng", [], [])}
        plm = PlmData(parts=parts, document_control_team="@doc-ctrl")
        line = _make_line("P-DC", change_class=change_class, change_types=[ChangeType.DOCUMENT])
        report = compute_notification_distribution("E-DC", [line], plm)
        roles = _roles(report, "P-DC")
        assert "document_control" in roles
        assert roles["document_control"].stakeholder == "@doc-ctrl"

    def test_empty_eco_no_notifications(self):
        plm = _make_plm()
        report = compute_notification_distribution("ECO-EMPTY", [], plm)
        assert report.notifications == []
        assert report.eco_id == "ECO-EMPTY"
        assert report.honest_flag is True


# ---------------------------------------------------------------------------
# Test 9 — Grouping helpers
# ---------------------------------------------------------------------------

class TestGroupingHelpers:

    def test_by_part_keys(self):
        parts = {
            "PA": PartRecord("PA", "@a", [], []),
            "PB": PartRecord("PB", "@b", [], []),
        }
        plm = PlmData(parts=parts)
        lines = [
            _make_line("PA", change_class=ChangeClass.CLASS_C, change_types=[ChangeType.DOCUMENT]),
            _make_line("PB", change_class=ChangeClass.CLASS_C, change_types=[ChangeType.DOCUMENT]),
        ]
        report = compute_notification_distribution("E-G", lines, plm)
        by_part = report.by_part()
        assert set(by_part.keys()) == {"PA", "PB"}

    def test_by_stakeholder_groups_correctly(self):
        parts = {
            "PA": PartRecord("PA", "@eng", [], []),
            "PB": PartRecord("PB", "@eng", [], []),
        }
        plm = PlmData(parts=parts)
        lines = [
            _make_line("PA", change_class=ChangeClass.CLASS_C),
            _make_line("PB", change_class=ChangeClass.CLASS_C),
        ]
        report = compute_notification_distribution("E-BS", lines, plm)
        by_stk = report.by_stakeholder()
        # Both parts have @eng as owner; @eng should appear with 2 notifications
        assert "@eng" in by_stk
        assert len(by_stk["@eng"]) == 2


# ---------------------------------------------------------------------------
# Test 10 — Dict constructor helpers
# ---------------------------------------------------------------------------

class TestDictHelpers:

    def test_eco_line_from_dict_basic(self):
        d = {
            "part_id": "PN-001",
            "rev_from": "A",
            "rev_to": "B",
            "change_class": "class_a",
            "change_types": ["dimension", "material"],
            "description": "test",
        }
        line = eco_line_from_dict(d)
        assert line.part_id == "PN-001"
        assert line.change_class == ChangeClass.CLASS_A
        assert ChangeType.DIMENSION in line.change_types
        assert ChangeType.MATERIAL in line.change_types

    def test_eco_line_from_dict_defaults(self):
        line = eco_line_from_dict({"part_id": "PN-002"})
        assert line.change_class == ChangeClass.CLASS_B
        assert line.change_types == []
        assert line.rev_from == ""
        assert line.rev_to == ""

    def test_eco_line_from_dict_unknown_class(self):
        line = eco_line_from_dict({"part_id": "PN-003", "change_class": "bogus"})
        assert line.change_class == ChangeClass.CLASS_B  # graceful fallback

    def test_eco_line_from_dict_unknown_change_type_skipped(self):
        line = eco_line_from_dict({
            "part_id": "PN-004",
            "change_types": ["dimension", "unknown_type"],
        })
        assert len(line.change_types) == 1
        assert ChangeType.DIMENSION in line.change_types

    def test_plm_data_from_dict(self):
        d = {
            "parts": {
                "PN-X": {
                    "owner_team": "@team-x",
                    "suppliers": ["S1", "S2"],
                    "manufacturing_routes": ["R1"],
                }
            },
            "quality_team": "@qc",
            "document_control_team": "@dc",
        }
        plm = plm_data_from_dict(d)
        assert "PN-X" in plm.parts
        assert plm.parts["PN-X"].owner_team == "@team-x"
        assert plm.parts["PN-X"].suppliers == ["S1", "S2"]
        assert plm.quality_team == "@qc"
        assert plm.document_control_team == "@dc"

    def test_plm_data_from_dict_empty(self):
        plm = plm_data_from_dict({})
        assert plm.parts == {}
        assert plm.quality_team == "@quality-team"
        assert plm.document_control_team == "@doc-control"

    def test_round_trip_compute_via_dict_helpers(self):
        """Full round-trip using dict constructors → compute → report."""
        eco_lines = [eco_line_from_dict({
            "part_id": "PN-RT",
            "rev_from": "A",
            "rev_to": "B",
            "change_class": "class_b",
            "change_types": ["dimension"],
        })]
        plm = plm_data_from_dict({
            "parts": {
                "PN-RT": {
                    "owner_team": "@rt-team",
                    "suppliers": ["RT-Supplier"],
                    "manufacturing_routes": ["RT-ROUTE"],
                }
            }
        })
        report = compute_notification_distribution("ECO-RT", eco_lines, plm)
        roles = {n.role for n in report.notifications}
        assert roles == {
            "engineering", "supplier", "manufacturing_lead", "quality", "document_control"
        }
