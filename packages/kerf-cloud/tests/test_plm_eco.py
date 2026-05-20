"""
Tests for kerf_cloud.plm.eco — Engineering Change Order / ECR.

All tests are hermetic (no DB, no filesystem).
"""
from __future__ import annotations

import json
import pytest

from kerf_cloud.plm.eco import (
    ECO_STATUSES,
    CHANGE_TYPES,
    approve_eco,
    compute_impact,
    create_eco,
    eco_from_content,
    validate_eco,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _part(fid, name):
    return {"id": fid, "name": name, "kind": "part", "content": "", "parent_id": None}


def _asm(fid, name, components):
    content = json.dumps({"components": components})
    return {"id": fid, "name": name, "kind": "assembly", "content": content, "parent_id": None}


def _comp(file_id, qty=1):
    return {"file_id": file_id, "quantity": qty}


def _affected_part(part_id, change_type="modify"):
    return {
        "part_id": part_id,
        "from_state": {"name": "Old", "content": "{}"},
        "to_state": {"name": "New", "content": "{}"},
        "change_type": change_type,
    }


# ---------------------------------------------------------------------------
# create_eco tests
# ---------------------------------------------------------------------------

class TestCreateEco:
    def test_basic_creation(self):
        r = create_eco(
            title="Fix bearing spec",
            description="Update bearing tolerance",
            requestor="alice",
            affected_parts=[_affected_part("p1")],
        )
        assert r["ok"] is True
        eco = r["eco"]
        assert eco["title"] == "Fix bearing spec"
        assert eco["status"] == "draft"
        assert eco["requestor"] == "alice"
        assert eco["eco_id"].startswith("eco-")

    def test_empty_title_fails(self):
        r = create_eco("", "desc", "alice", [_affected_part("p1")])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_empty_requestor_fails(self):
        r = create_eco("Title", "desc", "", [_affected_part("p1")])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_empty_affected_parts_fails(self):
        r = create_eco("Title", "desc", "alice", [])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_missing_part_id_fails(self):
        r = create_eco("Title", "desc", "alice", [{"from_state": {}, "to_state": {}, "change_type": "modify"}])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_invalid_change_type_fails(self):
        r = create_eco("T", "d", "alice", [{
            "part_id": "p1",
            "from_state": {},
            "to_state": {},
            "change_type": "invalid_type",
        }])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_all_change_types_accepted(self):
        for ct in CHANGE_TYPES:
            r = create_eco("T", "d", "alice", [_affected_part("p1", change_type=ct)])
            assert r["ok"] is True, f"change_type={ct!r} should be accepted"

    def test_impact_list_computed_from_project_files(self):
        p1 = _part("p1", "Shaft")
        asm = _asm("a1", "Motor", [_comp("p1")])
        r = create_eco(
            title="Change shaft",
            description="New material",
            requestor="bob",
            affected_parts=[_affected_part("p1")],
            project_files=[p1, asm],
        )
        assert r["ok"] is True
        assert len(r["eco"]["impact_list"]) == 1
        assert r["eco"]["impact_list"][0]["assembly_id"] == "a1"

    def test_empty_impact_when_no_project_files(self):
        r = create_eco("T", "d", "alice", [_affected_part("p1")])
        assert r["ok"] is True
        assert r["eco"]["impact_list"] == []

    def test_verification_tests_stored(self):
        r = create_eco(
            "T", "d", "alice",
            [_affected_part("p1")],
            verification_tests=["test_shaft_strength", "test_shaft_fatigue"],
        )
        assert r["ok"] is True
        assert "test_shaft_strength" in r["eco"]["verification_tests"]

    def test_linked_requirements_stored(self):
        r = create_eco(
            "T", "d", "alice",
            [_affected_part("p1")],
            linked_requirements=["REQ-001"],
        )
        assert r["ok"] is True
        assert "REQ-001" in r["eco"]["linked_requirements"]

    def test_timestamps_present(self):
        r = create_eco("T", "d", "alice", [_affected_part("p1")])
        eco = r["eco"]
        assert eco["created_at"]
        assert eco["updated_at"]


# ---------------------------------------------------------------------------
# validate_eco tests
# ---------------------------------------------------------------------------

class TestValidateEco:
    def _good_eco(self):
        r = create_eco("T", "d", "alice", [_affected_part("p1")])
        return r["eco"]

    def test_valid_eco_passes(self):
        r = validate_eco(self._good_eco())
        assert r["ok"] is True

    def test_missing_eco_id(self):
        eco = self._good_eco()
        del eco["eco_id"]
        r = validate_eco(eco)
        assert r["ok"] is False
        assert any("eco_id" in e for e in r["errors"])

    def test_invalid_status(self):
        eco = self._good_eco()
        eco["status"] = "invented"
        r = validate_eco(eco)
        assert r["ok"] is False

    def test_all_statuses_valid(self):
        for s in ECO_STATUSES:
            eco = self._good_eco()
            eco["status"] = s
            r = validate_eco(eco)
            assert r["ok"] is True, f"status={s!r} should pass validation"


# ---------------------------------------------------------------------------
# compute_impact tests
# ---------------------------------------------------------------------------

class TestComputeImpact:
    def test_recompute_adds_new_assembly(self):
        p1 = _part("p1", "Gear")
        asm = _asm("a1", "Gearbox", [_comp("p1")])
        r = create_eco("T", "d", "alice", [_affected_part("p1")])
        eco = r["eco"]
        assert eco["impact_list"] == []
        r2 = compute_impact(eco, [p1, asm])
        assert r2["ok"] is True
        assert len(r2["eco"]["impact_list"]) == 1

    def test_original_eco_not_mutated(self):
        p1 = _part("p1", "Gear")
        asm = _asm("a1", "Gearbox", [_comp("p1")])
        r = create_eco("T", "d", "alice", [_affected_part("p1")])
        eco = r["eco"]
        compute_impact(eco, [p1, asm])
        assert eco["impact_list"] == []


# ---------------------------------------------------------------------------
# approve_eco tests
# ---------------------------------------------------------------------------

class TestApproveEco:
    def _eco(self, status="draft"):
        r = create_eco("T", "d", "alice", [_affected_part("p1")])
        eco = r["eco"]
        eco["status"] = status
        return eco

    def test_approve_from_draft(self):
        r = approve_eco(self._eco("draft"))
        assert r["ok"] is True
        assert r["eco"]["status"] == "approved"

    def test_approve_from_in_review(self):
        r = approve_eco(self._eco("in_review"))
        assert r["ok"] is True
        assert r["eco"]["status"] == "approved"

    def test_cannot_approve_already_approved(self):
        r = approve_eco(self._eco("approved"))
        assert r["ok"] is False
        assert r["code"] == "INVALID_STATE"

    def test_cannot_approve_rejected(self):
        r = approve_eco(self._eco("rejected"))
        assert r["ok"] is False

    def test_original_not_mutated(self):
        eco = self._eco("draft")
        approve_eco(eco)
        assert eco["status"] == "draft"


# ---------------------------------------------------------------------------
# eco_from_content tests
# ---------------------------------------------------------------------------

class TestEcoFromContent:
    def test_valid_content(self):
        eco = {"eco_id": "eco-1", "title": "T", "status": "draft"}
        r = eco_from_content(json.dumps(eco))
        assert r["ok"] is True
        assert r["eco"]["eco_id"] == "eco-1"

    def test_empty_content(self):
        r = eco_from_content("")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_bad_json(self):
        r = eco_from_content("not json {")
        assert r["ok"] is False
        assert r["code"] == "PARSE_ERROR"

    def test_non_object_json(self):
        r = eco_from_content("[1, 2, 3]")
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# LLM tool wrapper
# ---------------------------------------------------------------------------

class TestPlmEcoLlmTools:
    def test_create_eco_tool(self):
        from kerf_cloud.plm.llm_tools import plm_create_eco
        r = plm_create_eco(
            title="Material upgrade",
            description="Upgrade alloy",
            requestor="eng01",
            affected_parts_json=json.dumps([_affected_part("p1")]),
        )
        assert r["ok"] is True
        assert r["eco"]["title"] == "Material upgrade"

    def test_validate_eco_tool(self):
        from kerf_cloud.plm.llm_tools import plm_validate_eco, plm_create_eco
        cr = plm_create_eco("T", "d", "alice", json.dumps([_affected_part("p1")]))
        eco_json = json.dumps(cr["eco"])
        r = plm_validate_eco(eco_json)
        assert r["ok"] is True

    def test_compute_impact_tool(self):
        from kerf_cloud.plm.llm_tools import plm_compute_eco_impact, plm_create_eco
        p1 = _part("p1", "Pin")
        asm = _asm("a1", "Axle", [_comp("p1")])
        cr = plm_create_eco("T", "d", "alice", json.dumps([_affected_part("p1")]))
        r = plm_compute_eco_impact(json.dumps(cr["eco"]), json.dumps([p1, asm]))
        assert r["ok"] is True
        assert len(r["eco"]["impact_list"]) == 1

    def test_dispatch_unknown_tool(self):
        from kerf_cloud.plm.llm_tools import dispatch
        r = dispatch("no_such_tool", {})
        assert r["ok"] is False
        assert r["code"] == "NOT_FOUND"
