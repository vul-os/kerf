"""
Tests for kerf_cloud.plm.sysml_trace — SysML-light requirements trace.

All tests are hermetic (no DB, no filesystem).
"""
from __future__ import annotations

import json
import pytest

from kerf_cloud.plm.sysml_trace import (
    LINK_TYPES,
    PRIORITIES,
    VERIFICATION_METHODS,
    VERIFICATION_STATUSES,
    add_trace_link,
    add_verification,
    create_sysml_doc,
    sysml_from_content,
    trace,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _req(req_id, text, priority="shall"):
    return {"req_id": req_id, "text": text, "priority": priority}


def _make_doc(reqs=None):
    return create_sysml_doc("Test System", reqs)


# ---------------------------------------------------------------------------
# create_sysml_doc tests
# ---------------------------------------------------------------------------

class TestCreateSysmlDoc:
    def test_basic_creation(self):
        r = _make_doc()
        assert r["ok"] is True
        doc = r["doc"]
        assert doc["title"] == "Test System"
        assert doc["sysml_id"].startswith("sysml-")
        assert doc["requirements"] == []

    def test_empty_title_fails(self):
        r = create_sysml_doc("")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_with_requirements(self):
        r = create_sysml_doc("Drone", [_req("REQ-001", "Shall fly")])
        assert r["ok"] is True
        doc = r["doc"]
        assert len(doc["requirements"]) == 1
        assert doc["requirements"][0]["req_id"] == "REQ-001"

    def test_missing_req_id_fails(self):
        r = create_sysml_doc("Sys", [{"text": "some text", "priority": "shall"}])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_missing_req_text_fails(self):
        r = create_sysml_doc("Sys", [{"req_id": "REQ-001", "priority": "shall"}])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_invalid_priority_fails(self):
        r = create_sysml_doc("Sys", [_req("R1", "text", priority="must")])
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_all_priorities_accepted(self):
        for p in PRIORITIES:
            r = create_sysml_doc("Sys", [_req("R1", "text", priority=p)])
            assert r["ok"] is True, f"priority={p!r} should be accepted"

    def test_multiple_requirements(self):
        reqs = [_req(f"R{i}", f"Req text {i}") for i in range(3)]
        r = create_sysml_doc("Complex System", reqs)
        assert r["ok"] is True
        assert len(r["doc"]["requirements"]) == 3

    def test_timestamps_present(self):
        r = _make_doc()
        doc = r["doc"]
        assert doc["created_at"]
        assert doc["updated_at"]

    def test_req_defaults(self):
        r = create_sysml_doc("Sys", [{"req_id": "R1", "text": "text"}])
        req = r["doc"]["requirements"][0]
        assert req["priority"] == "shall"
        assert req["trace_links"] == []
        assert req["verification"] == []


# ---------------------------------------------------------------------------
# add_trace_link tests
# ---------------------------------------------------------------------------

class TestAddTraceLink:
    def _doc(self):
        r = create_sysml_doc("Sys", [_req("REQ-001", "System shall operate")])
        return r["doc"]

    def test_add_satisfies_link(self):
        doc = self._doc()
        r = add_trace_link(doc, "REQ-001", "fid-123", "CAD Model", "satisfies")
        assert r["ok"] is True
        req = r["doc"]["requirements"][0]
        assert len(req["trace_links"]) == 1
        link = req["trace_links"][0]
        assert link["file_id"] == "fid-123"
        assert link["link_type"] == "satisfies"

    def test_all_link_types_accepted(self):
        for lt in LINK_TYPES:
            doc = self._doc()
            r = add_trace_link(doc, "REQ-001", "fid", "file", lt)
            assert r["ok"] is True, f"link_type={lt!r} should be accepted"

    def test_invalid_link_type_fails(self):
        doc = self._doc()
        r = add_trace_link(doc, "REQ-001", "fid", "file", "invalid")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_unknown_req_id_fails(self):
        doc = self._doc()
        r = add_trace_link(doc, "NO-SUCH-REQ", "fid", "file")
        assert r["ok"] is False
        assert r["code"] == "NOT_FOUND"

    def test_duplicate_link_idempotent(self):
        doc = self._doc()
        r1 = add_trace_link(doc, "REQ-001", "fid-123", "CAD", "satisfies")
        r2 = add_trace_link(r1["doc"], "REQ-001", "fid-123", "CAD", "satisfies")
        assert r2["ok"] is True
        # Should not duplicate
        assert len(r2["doc"]["requirements"][0]["trace_links"]) == 1

    def test_original_doc_not_mutated(self):
        doc = self._doc()
        add_trace_link(doc, "REQ-001", "fid", "file")
        assert doc["requirements"][0]["trace_links"] == []


# ---------------------------------------------------------------------------
# add_verification tests
# ---------------------------------------------------------------------------

class TestAddVerification:
    def _doc(self):
        r = create_sysml_doc("Sys", [_req("REQ-001", "Shall be tested")])
        return r["doc"]

    def test_add_test_verification(self):
        doc = self._doc()
        r = add_verification(doc, "REQ-001", "test_motor_speed", "test", "pending")
        assert r["ok"] is True
        req = r["doc"]["requirements"][0]
        assert len(req["verification"]) == 1
        v = req["verification"][0]
        assert v["test_id"] == "test_motor_speed"
        assert v["method"] == "test"
        assert v["status"] == "pending"

    def test_all_methods_accepted(self):
        for m in VERIFICATION_METHODS:
            doc = self._doc()
            r = add_verification(doc, "REQ-001", "tid", m, "pending")
            assert r["ok"] is True, f"method={m!r} should be accepted"

    def test_all_statuses_accepted(self):
        for s in VERIFICATION_STATUSES:
            doc = self._doc()
            r = add_verification(doc, "REQ-001", "tid", "test", s)
            assert r["ok"] is True, f"status={s!r} should be accepted"

    def test_invalid_method_fails(self):
        doc = self._doc()
        r = add_verification(doc, "REQ-001", "tid", "robot", "pending")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_invalid_status_fails(self):
        doc = self._doc()
        r = add_verification(doc, "REQ-001", "tid", "test", "unknown")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_unknown_req_id_fails(self):
        doc = self._doc()
        r = add_verification(doc, "NOPE", "tid")
        assert r["ok"] is False
        assert r["code"] == "NOT_FOUND"

    def test_duplicate_test_idempotent(self):
        doc = self._doc()
        r1 = add_verification(doc, "REQ-001", "test_123")
        r2 = add_verification(r1["doc"], "REQ-001", "test_123")
        assert r2["ok"] is True
        assert len(r2["doc"]["requirements"][0]["verification"]) == 1


# ---------------------------------------------------------------------------
# trace tests
# ---------------------------------------------------------------------------

class TestTrace:
    def _full_doc(self):
        r = create_sysml_doc("Drone", [
            _req("REQ-001", "Shall achieve 120 kph"),
            _req("REQ-002", "Shall carry 500g payload"),
        ])
        doc = r["doc"]
        doc = add_trace_link(doc, "REQ-001", "cad-motor", "Motor CAD", "satisfies")["doc"]
        doc = add_trace_link(doc, "REQ-001", "cad-prop", "Propeller CAD", "satisfies")["doc"]
        doc = add_verification(doc, "REQ-001", "test_speed_sprint", "test", "pass")["doc"]
        doc = add_verification(doc, "REQ-001", "analysis_aero", "analysis", "pending")["doc"]
        return doc

    def test_trace_all_requirements(self):
        doc = self._full_doc()
        r = trace(doc)
        assert r["ok"] is True
        assert len(r["chains"]) == 2

    def test_trace_single_requirement(self):
        doc = self._full_doc()
        r = trace(doc, "REQ-001")
        assert r["ok"] is True
        assert len(r["chains"]) == 1
        chain = r["chains"][0]
        assert chain["req_id"] == "REQ-001"
        assert chain["implementation_count"] == 2
        assert chain["verification_count"] == 2

    def test_trace_unknown_req_fails(self):
        doc = self._full_doc()
        r = trace(doc, "NO-SUCH-REQ")
        assert r["ok"] is False
        assert r["code"] == "NOT_FOUND"

    def test_trace_coverage_fully_verified(self):
        """Req with impl + all pass → fully_verified."""
        r = create_sysml_doc("Sys", [_req("R1", "text")])
        doc = r["doc"]
        doc = add_trace_link(doc, "R1", "fid", "file")["doc"]
        doc = add_verification(doc, "R1", "t1", status="pass")["doc"]
        chain = trace(doc, "R1")["chains"][0]
        assert chain["coverage_status"] == "fully_verified"

    def test_trace_coverage_uncovered(self):
        r = create_sysml_doc("Sys", [_req("R1", "text")])
        doc = r["doc"]
        chain = trace(doc, "R1")["chains"][0]
        assert chain["coverage_status"] == "uncovered"

    def test_trace_coverage_implemented(self):
        r = create_sysml_doc("Sys", [_req("R1", "text")])
        doc = r["doc"]
        doc = add_trace_link(doc, "R1", "fid", "file")["doc"]
        chain = trace(doc, "R1")["chains"][0]
        assert chain["coverage_status"] == "implemented"

    def test_trace_implementations_list(self):
        r = create_sysml_doc("Sys", [_req("R1", "text")])
        doc = r["doc"]
        doc = add_trace_link(doc, "R1", "fid-1", "FileA")["doc"]
        doc = add_trace_link(doc, "R1", "fid-2", "FileB", "refines")["doc"]
        chains = trace(doc)["chains"]
        impls = chains[0]["implementations"]
        file_ids = {i["file_id"] for i in impls}
        assert "fid-1" in file_ids
        assert "fid-2" in file_ids

    def test_empty_doc_trace(self):
        r = create_sysml_doc("Empty System")
        doc = r["doc"]
        result = trace(doc)
        assert result["ok"] is True
        assert result["chains"] == []


# ---------------------------------------------------------------------------
# sysml_from_content tests
# ---------------------------------------------------------------------------

class TestSysmlFromContent:
    def test_valid_content(self):
        doc = {"sysml_id": "s1", "title": "T", "requirements": []}
        r = sysml_from_content(json.dumps(doc))
        assert r["ok"] is True
        assert r["doc"]["title"] == "T"

    def test_empty_content(self):
        r = sysml_from_content("")
        assert r["ok"] is False
        assert r["code"] == "BAD_ARGS"

    def test_bad_json(self):
        r = sysml_from_content("{bad json")
        assert r["ok"] is False
        assert r["code"] == "PARSE_ERROR"

    def test_non_object_fails(self):
        r = sysml_from_content("[1, 2]")
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# LLM tool wrappers
# ---------------------------------------------------------------------------

class TestPlmSysmlLlmTools:
    def test_create_sysml_doc_tool(self):
        from kerf_cloud.plm.llm_tools import plm_create_sysml_doc
        r = plm_create_sysml_doc("Motor Controller")
        assert r["ok"] is True
        assert r["doc"]["title"] == "Motor Controller"

    def test_create_with_reqs_tool(self):
        from kerf_cloud.plm.llm_tools import plm_create_sysml_doc
        reqs = [{"req_id": "R1", "text": "Shall spin at 3000 rpm", "priority": "shall"}]
        r = plm_create_sysml_doc("ESC", json.dumps(reqs))
        assert r["ok"] is True
        assert len(r["doc"]["requirements"]) == 1

    def test_add_trace_link_tool(self):
        from kerf_cloud.plm.llm_tools import plm_create_sysml_doc, plm_add_trace_link
        cr = plm_create_sysml_doc(
            "Sys",
            json.dumps([{"req_id": "R1", "text": "text", "priority": "shall"}]),
        )
        r = plm_add_trace_link(json.dumps(cr["doc"]), "R1", "fid-abc", "BracketCAD")
        assert r["ok"] is True
        assert len(r["doc"]["requirements"][0]["trace_links"]) == 1

    def test_add_verification_tool(self):
        from kerf_cloud.plm.llm_tools import plm_create_sysml_doc, plm_add_verification
        cr = plm_create_sysml_doc(
            "Sys",
            json.dumps([{"req_id": "R1", "text": "text", "priority": "shall"}]),
        )
        r = plm_add_verification(json.dumps(cr["doc"]), "R1", "test_integration")
        assert r["ok"] is True
        assert len(r["doc"]["requirements"][0]["verification"]) == 1

    def test_trace_tool(self):
        from kerf_cloud.plm.llm_tools import (
            plm_create_sysml_doc,
            plm_add_trace_link,
            plm_add_verification,
            plm_trace,
        )
        cr = plm_create_sysml_doc(
            "Sys",
            json.dumps([{"req_id": "R1", "text": "text", "priority": "shall"}]),
        )
        doc = cr["doc"]
        doc = plm_add_trace_link(json.dumps(doc), "R1", "fid", "FileA")["doc"]
        doc = plm_add_verification(json.dumps(doc), "R1", "test_01", status="pass")["doc"]
        r = plm_trace(json.dumps(doc), "R1")
        assert r["ok"] is True
        chain = r["chains"][0]
        assert chain["implementation_count"] == 1
        assert chain["verification_count"] == 1
        assert chain["coverage_status"] == "fully_verified"

    def test_tool_defs_complete(self):
        from kerf_cloud.plm.llm_tools import TOOL_DEFS
        names = {t["name"] for t in TOOL_DEFS}
        expected = {
            "plm_bom_150_percent", "plm_where_used",
            "plm_create_eco", "plm_validate_eco", "plm_compute_eco_impact",
            "plm_create_sysml_doc", "plm_add_trace_link", "plm_add_verification",
            "plm_trace",
        }
        assert expected <= names, f"Missing tool defs: {expected - names}"
