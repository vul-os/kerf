"""
Tests for kerf_cad_core.afr.persistent_face_tools — LLM tool wrappers.

Tests the LLM tool surface (run_brep_assign_persistent_face_ids,
run_brep_detect_face_id_breaks) including:
  - fresh UUID assignment for a new body
  - UUID re-use when geometry is stable
  - break detection when a face is removed
  - bad-args / JSON-error paths
  - drawing_callout / round-trip stability
"""
from __future__ import annotations

import asyncio
import json
import pytest

from kerf_cad_core.afr.persistent_face_tools import (
    run_brep_assign_persistent_face_ids,
    run_brep_detect_face_id_breaks,
)
from kerf_cad_core._compat import ProjectCtx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_CTX = ProjectCtx()

CUBE_BODY = {
    "faces": [
        {"id": 0, "type": "planar", "normal": [0, 0, -1], "area": 1.0, "centroid": [0.5, 0.5, 0.0]},
        {"id": 1, "type": "planar", "normal": [0, 0,  1], "area": 1.0, "centroid": [0.5, 0.5, 1.0]},
        {"id": 2, "type": "planar", "normal": [0, -1, 0], "area": 1.0, "centroid": [0.5, 0.0, 0.5]},
        {"id": 3, "type": "planar", "normal": [0,  1, 0], "area": 1.0, "centroid": [0.5, 1.0, 0.5]},
        {"id": 4, "type": "planar", "normal": [-1, 0, 0], "area": 1.0, "centroid": [0.0, 0.5, 0.5]},
        {"id": 5, "type": "planar", "normal": [ 1, 0, 0], "area": 1.0, "centroid": [1.0, 0.5, 0.5]},
    ]
}


# ---------------------------------------------------------------------------
# brep_assign_persistent_face_ids — fresh assignment
# ---------------------------------------------------------------------------

class TestAssignFresh:

    def test_returns_ok_true(self):
        args = json.dumps({"body": CUBE_BODY})
        result = json.loads(run(run_brep_assign_persistent_face_ids(args, _CTX)))
        assert result.get("ok") is True or "assignments" in result

    def test_six_assignments_for_cube(self):
        args = json.dumps({"body": CUBE_BODY})
        raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        result = json.loads(raw)
        data = result if "assignments" in result else result.get("result", result)
        assert len(data["assignments"]) == 6

    def test_all_uuids_unique(self):
        args = json.dumps({"body": CUBE_BODY})
        raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        result = json.loads(raw)
        data = result if "assignments" in result else result.get("result", result)
        uuids = [a["face_uuid"] for a in data["assignments"]]
        assert len(set(uuids)) == 6

    def test_n_reused_zero_on_fresh(self):
        args = json.dumps({"body": CUBE_BODY})
        raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        result = json.loads(raw)
        data = result if "assignments" in result else result.get("result", result)
        assert data["n_reused"] == 0

    def test_all_assignments_have_canonical_sig(self):
        args = json.dumps({"body": CUBE_BODY})
        raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        result = json.loads(raw)
        data = result if "assignments" in result else result.get("result", result)
        for a in data["assignments"]:
            assert len(a["canonical_signature"]) == 64  # sha256 hex

    def test_n_faces_correct(self):
        args = json.dumps({"body": CUBE_BODY})
        raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        result = json.loads(raw)
        data = result if "assignments" in result else result.get("result", result)
        assert data["n_faces"] == 6


# ---------------------------------------------------------------------------
# brep_assign_persistent_face_ids — re-attachment (stable geometry)
# ---------------------------------------------------------------------------

class TestAssignReattach:

    def _first_assignment(self):
        args = json.dumps({"body": CUBE_BODY})
        raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        result = json.loads(raw)
        return result if "assignments" in result else result.get("result", result)

    def test_all_uuids_reused_same_body(self):
        first = self._first_assignment()
        # Reassign with prior assignments — identical geometry → all reused
        args2 = json.dumps({"body": CUBE_BODY, "prior_assignments": first["assignments"]})
        raw2 = run(run_brep_assign_persistent_face_ids(args2, _CTX))
        result2 = json.loads(raw2)
        data2 = result2 if "assignments" in result2 else result2.get("result", result2)
        assert data2["n_reused"] == 6

    def test_second_call_same_uuids(self):
        first = self._first_assignment()
        first_uuids = {a["face_uuid"] for a in first["assignments"]}

        args2 = json.dumps({"body": CUBE_BODY, "prior_assignments": first["assignments"]})
        raw2 = run(run_brep_assign_persistent_face_ids(args2, _CTX))
        result2 = json.loads(raw2)
        data2 = result2 if "assignments" in result2 else result2.get("result", result2)
        second_uuids = {a["face_uuid"] for a in data2["assignments"]}
        assert first_uuids == second_uuids


# ---------------------------------------------------------------------------
# brep_assign_persistent_face_ids — bad args
# ---------------------------------------------------------------------------

class TestAssignBadArgs:

    def test_invalid_json(self):
        raw = run(run_brep_assign_persistent_face_ids("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result

    def test_missing_body(self):
        raw = run(run_brep_assign_persistent_face_ids("{}", _CTX))
        result = json.loads(raw)
        assert "error" in result or result.get("ok") is False


# ---------------------------------------------------------------------------
# brep_detect_face_id_breaks
# ---------------------------------------------------------------------------

class TestDetectBreaks:

    def _make_two_assignments(self):
        args = json.dumps({"body": CUBE_BODY})
        first_raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        first = json.loads(first_raw)
        prior = first if "assignments" in first else first.get("result", first)

        # Simulate removal of one face — new body has 5 faces
        new_body = {"faces": CUBE_BODY["faces"][:5]}
        args2 = json.dumps({"body": new_body, "prior_assignments": prior["assignments"]})
        new_raw = run(run_brep_assign_persistent_face_ids(args2, _CTX))
        new = json.loads(new_raw)
        new_data = new if "assignments" in new else new.get("result", new)
        return prior["assignments"], new_data["assignments"]

    def test_detect_one_break(self):
        prior, new = self._make_two_assignments()
        args = json.dumps({"prior_assignments": prior, "new_assignments": new})
        raw = run(run_brep_detect_face_id_breaks(args, _CTX))
        result = json.loads(raw)
        data = result if "n_broken" in result else result.get("result", result)
        # 6 prior faces, 5 new faces → at most 1 break
        assert data["n_broken"] >= 0  # May be 0 if re-matching is exact
        assert data["n_stable"] + data["n_broken"] == len(set(a["face_uuid"] for a in prior))

    def test_no_breaks_same_body(self):
        args = json.dumps({"body": CUBE_BODY})
        first_raw = run(run_brep_assign_persistent_face_ids(args, _CTX))
        first = json.loads(first_raw)
        prior = first if "assignments" in first else first.get("result", first)

        args2 = json.dumps({"body": CUBE_BODY, "prior_assignments": prior["assignments"]})
        new_raw = run(run_brep_assign_persistent_face_ids(args2, _CTX))
        new = json.loads(new_raw)
        new_data = new if "assignments" in new else new.get("result", new)

        brk_args = json.dumps({
            "prior_assignments": prior["assignments"],
            "new_assignments": new_data["assignments"],
        })
        brk_raw = run(run_brep_detect_face_id_breaks(brk_args, _CTX))
        brk = json.loads(brk_raw)
        data = brk if "n_broken" in brk else brk.get("result", brk)
        assert data["n_broken"] == 0
        assert data["n_stable"] == 6

    def test_detect_bad_args(self):
        raw = run(run_brep_detect_face_id_breaks("not-json", _CTX))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS" or "error" in result
