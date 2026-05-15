"""
test_backfill_face_names.py — T7: migration script unit tests.

Tests for kerf_cad_core.scripts.backfill_face_names:

  1. migrate_feature_content: node with target_face_id but no target_face_name
     → synthetic name is written.
  2. migrate_feature_content: node that already has target_face_name → skipped
     (idempotency).
  3. migrate_feature_content: node with no target_face_id → skipped.
  4. migrate_feature_content: multiple ops in one file → only face-consuming
     ops are patched.
  5. migrate_feature_content: push_pull uses face_id / face_name keys.
  6. Idempotency proof: calling migrate twice produces the same result as
     calling it once (second call returns None, 0).

~6 test cases.
"""

import json

import pytest

from kerf_cad_core.scripts.backfill_face_names import (
    FACE_REF_OPS,
    migrate_feature_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_feature_content(nodes: list[dict]) -> str:
    return json.dumps({"features": nodes})


def parse_nodes(content: str) -> list[dict]:
    return json.loads(content)["features"]


# ---------------------------------------------------------------------------
# 1. node with target_face_id but no target_face_name → synthetic name written
# ---------------------------------------------------------------------------


def test_migrate_adds_synthetic_name_for_cut_from_sketch():
    nodes = [
        {
            "id": "cut-1",
            "op": "cut_from_sketch",
            "sketch_path": "s/sketch.json",
            "target_face_id": 3,
            "depth": 5.0,
        }
    ]
    content = make_feature_content(nodes)
    new_content, n = migrate_feature_content(content)
    assert n == 1
    assert new_content is not None
    result_nodes = parse_nodes(new_content)
    node = result_nodes[0]
    # synthetic name: "<nodeId>.face<id>"
    assert node["target_face_name"] == "cut-1.face3"
    # legacy id preserved
    assert node["target_face_id"] == 3


# ---------------------------------------------------------------------------
# 2. node that already has target_face_name → skipped (idempotent)
# ---------------------------------------------------------------------------


def test_migrate_skips_node_with_existing_name():
    nodes = [
        {
            "id": "cut-1",
            "op": "cut_from_sketch",
            "sketch_path": "s/sketch.json",
            "target_face_id": 3,
            "target_face_name": "Pad-A.TopCap",
            "depth": 5.0,
        }
    ]
    content = make_feature_content(nodes)
    new_content, n = migrate_feature_content(content)
    assert n == 0
    assert new_content is None, "Should return None when nothing changes"


# ---------------------------------------------------------------------------
# 3. node with no target_face_id → skipped
# ---------------------------------------------------------------------------


def test_migrate_skips_node_without_face_id():
    nodes = [
        {
            "id": "pad-1",
            "op": "pad",
            "sketch_path": "s/sketch.json",
            "distance": 10.0,
        }
    ]
    content = make_feature_content(nodes)
    new_content, n = migrate_feature_content(content)
    assert n == 0
    assert new_content is None


# ---------------------------------------------------------------------------
# 4. multiple ops in one file → only face-consuming ops are patched
# ---------------------------------------------------------------------------


def test_migrate_patches_only_face_consuming_ops():
    nodes = [
        {
            "id": "pad-1",
            "op": "pad",
            "sketch_path": "s/sketch.json",
            "distance": 10.0,
        },
        {
            "id": "cut-1",
            "op": "cut_from_sketch",
            "sketch_path": "s/cut.json",
            "target_face_id": 2,
            "depth": 3.0,
        },
        {
            "id": "fil-1",
            "op": "fillet",
            "radius": 1.0,
            "target_face_id": 5,
        },
        {
            "id": "rev-1",
            "op": "revolve",
            "sketch_path": "s/rev.json",
            "angle_deg": 360,
        },
    ]
    content = make_feature_content(nodes)
    new_content, n = migrate_feature_content(content)
    # Should patch cut_from_sketch (target_face_id=2) and fillet (target_face_id=5)
    assert n == 2
    result_nodes = parse_nodes(new_content)
    # pad-1 unchanged
    assert "target_face_name" not in result_nodes[0]
    # cut-1 patched
    assert result_nodes[1]["target_face_name"] == "cut-1.face2"
    # fillet patched
    assert result_nodes[2]["target_face_name"] == "fil-1.face5"
    # revolve unchanged
    assert "target_face_name" not in result_nodes[3]


# ---------------------------------------------------------------------------
# 5. push_pull uses face_id / face_name keys (different from cut_from_sketch)
# ---------------------------------------------------------------------------


def test_migrate_push_pull_uses_face_name_key():
    nodes = [
        {
            "id": "pp-1",
            "op": "push_pull",
            "face_id": 7,
            "distance": 4.0,
        }
    ]
    content = make_feature_content(nodes)
    new_content, n = migrate_feature_content(content)
    assert n == 1
    result_nodes = parse_nodes(new_content)
    # push_pull uses face_name (not target_face_name)
    assert result_nodes[0]["face_name"] == "pp-1.face7"
    assert result_nodes[0]["face_id"] == 7


# ---------------------------------------------------------------------------
# 6. Idempotency proof: calling migrate twice → second call returns (None, 0)
# ---------------------------------------------------------------------------


def test_migrate_is_idempotent():
    nodes = [
        {
            "id": "cut-1",
            "op": "cut_from_sketch",
            "sketch_path": "s/cut.json",
            "target_face_id": 2,
            "depth": 3.0,
        }
    ]
    content = make_feature_content(nodes)

    # First pass: should update 1 node
    new_content_1, n1 = migrate_feature_content(content)
    assert n1 == 1
    assert new_content_1 is not None

    # Second pass on already-migrated content: should skip (idempotent)
    new_content_2, n2 = migrate_feature_content(new_content_1)
    assert n2 == 0
    assert new_content_2 is None, (
        "Second migration pass should return (None, 0) — node already has face_name"
    )

    # The content produced by the first pass is stable
    result_nodes = parse_nodes(new_content_1)
    assert result_nodes[0]["target_face_name"] == "cut-1.face2"
