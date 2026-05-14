"""
Tests for feature_cut_from_sketch — pure logic, no DB required.

Exercises validate_cut_from_sketch_args and build_cut_from_sketch_node
directly so the suite runs without a live Postgres connection.
"""
import json
import sys
import os

# Ensure kerf-cad-core src is on the path (the conftest.py already does this
# for the packages/ monorepo layout, but make it explicit for direct pytest
# invocations from the package root).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kerf_cad_core.feature_cut_from_sketch import (
    validate_cut_from_sketch_args,
    build_cut_from_sketch_node,
)


# ── validate_cut_from_sketch_args ─────────────────────────────────────────────

def test_valid_args_basic():
    err, code = validate_cut_from_sketch_args(3, "/slot.sketch", 5.0, False)
    assert err is None and code is None


def test_valid_args_reverse_true():
    err, code = validate_cut_from_sketch_args(0, "/cut.sketch", 2.5, True)
    assert err is None and code is None


def test_valid_args_face_id_zero():
    err, code = validate_cut_from_sketch_args(0, "/profile.sketch", 1.0, False)
    assert err is None


def test_target_face_id_none_rejected():
    err, code = validate_cut_from_sketch_args(None, "/slot.sketch", 5.0, False)
    assert code == "BAD_ARGS"
    assert "target_face_id" in err


def test_target_face_id_negative_rejected():
    err, code = validate_cut_from_sketch_args(-1, "/slot.sketch", 5.0, False)
    assert code == "BAD_ARGS"
    assert ">= 0" in err


def test_target_face_id_float_rejected():
    err, code = validate_cut_from_sketch_args(3.5, "/slot.sketch", 5.0, False)
    assert code == "BAD_ARGS"
    assert "integer" in err


def test_sketch_path_empty_rejected():
    err, code = validate_cut_from_sketch_args(3, "", 5.0, False)
    assert code == "BAD_ARGS"
    assert "sketch_path" in err


def test_sketch_path_whitespace_rejected():
    err, code = validate_cut_from_sketch_args(3, "   ", 5.0, False)
    assert code == "BAD_ARGS"


def test_sketch_path_none_rejected():
    err, code = validate_cut_from_sketch_args(3, None, 5.0, False)
    assert code == "BAD_ARGS"


def test_depth_zero_rejected():
    err, code = validate_cut_from_sketch_args(3, "/slot.sketch", 0, False)
    assert code == "BAD_ARGS"
    assert "depth" in err


def test_depth_negative_rejected():
    err, code = validate_cut_from_sketch_args(3, "/slot.sketch", -1.0, False)
    assert code == "BAD_ARGS"


def test_depth_not_a_number_rejected():
    err, code = validate_cut_from_sketch_args(3, "/slot.sketch", "deep", False)
    assert code == "BAD_ARGS"


def test_reverse_not_bool_rejected():
    err, code = validate_cut_from_sketch_args(3, "/slot.sketch", 5.0, "yes")
    assert code == "BAD_ARGS"
    assert "reverse" in err


def test_small_positive_depth_accepted():
    err, code = validate_cut_from_sketch_args(0, "/p.sketch", 0.001, False)
    assert err is None


# ── build_cut_from_sketch_node ────────────────────────────────────────────────

def test_build_node_shape():
    node = build_cut_from_sketch_node("cut-1", "pad-1", 7, "/slot.sketch", 4.0, False)
    assert node["id"] == "cut-1"
    assert node["op"] == "cut_from_sketch"
    assert node["target_id"] == "pad-1"
    assert node["target_face_id"] == 7
    assert node["sketch_path"] == "/slot.sketch"
    assert node["depth"] == 4.0
    assert node["reverse"] is False


def test_build_node_reverse_true():
    node = build_cut_from_sketch_node("cut-2", "pad-1", 3, "/cut.sketch", 2.5, True)
    assert node["reverse"] is True


def test_build_node_optional_name_present():
    node = build_cut_from_sketch_node("cut-3", "pad-1", 5, "/p.sketch", 3.0, False, name="keyway")
    assert node.get("name") == "keyway"


def test_build_node_no_name_field_when_empty():
    node = build_cut_from_sketch_node("cut-4", "pad-1", 5, "/p.sketch", 3.0, False)
    assert "name" not in node


def test_node_is_json_serialisable():
    node = build_cut_from_sketch_node("cut-5", "pad-1", 7, "/slot.sketch", 4.0, False, name="slot")
    dumped = json.dumps(node)
    loaded = json.loads(dumped)
    assert loaded["op"] == "cut_from_sketch"
    assert loaded["depth"] == 4.0
    assert loaded["reverse"] is False


def test_build_node_face_id_zero():
    node = build_cut_from_sketch_node("cut-6", "revolve-1", 0, "/s.sketch", 1.0, True)
    assert node["target_face_id"] == 0


def test_build_node_target_id_stored():
    node = build_cut_from_sketch_node("cut-7", "sweep1-3", 2, "/s.sketch", 10.0, False)
    assert node["target_id"] == "sweep1-3"
