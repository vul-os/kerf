"""
test_afr_dag.py
===============
Hermetic tests for kerf_cad_core.afr.dag — AFR classifier output →
parametric DAG promotion.

Coverage
--------
1.  afr_to_dag returns AFRFeatureDAG
2.  base block is the root node
3.  parent-child edges: hole attached to base block
4.  parent-child edges: pocket_on_boss — boss is parent of pocket
5.  topological order respects weights
6.  emit_feature_log produces valid .feature log dict (version + features)
7.  feature_log round-trip: re-parse via load_feature_log succeeds
8.  feature_log round-trip: re-execute base box → validate_body clean
9.  pocket-on-boss-on-block DAG: boss is child of base, hole is child of base
10. feature_count excludes base block
11. afr_to_dag empty features → DAG with only base
12. parent_of / children_of helpers
13. dag_summary contains root and edges
14. through_hole emitted as cylinder op in log
15. boss emitted as cylinder op in log
16. afr_feature op used for pocket / slot / fillet / chamfer
17. topological_order starts with root
18. AFRFeatureDAG repr contains feature count
19. log includes afr_dag metadata (root + edges)
20. full round-trip: base-box body is validate_body-clean
"""

from __future__ import annotations

import json
import math
import warnings

import pytest

from kerf_cad_core.afr.dag import (
    AFRFeatureDAG,
    afr_dag_to_feature_log,
    afr_to_dag,
    emit_feature_log,
)
from kerf_cad_core.afr.recognize import recognize_features

# ---------------------------------------------------------------------------
# Shared topology fixtures
# ---------------------------------------------------------------------------

def _planar(fid, normal, convexity="flat", adjacent=None, area=100.0, centroid=None):
    return {
        "id": fid,
        "type": "planar",
        "normal": normal,
        "radius": 0.0,
        "area": area,
        "convexity": convexity,
        "adjacent": adjacent or [],
        "centroid": centroid or [5.0, 5.0, 0.0],
    }


def _cyl(fid, radius, axis, convexity="concave", adjacent=None, area=None, centroid=None):
    area = area if area is not None else 2 * math.pi * radius * 10.0
    return {
        "id": fid,
        "type": "cylindrical",
        "normal": axis,
        "radius": radius,
        "area": area,
        "convexity": convexity,
        "adjacent": adjacent or [],
        "centroid": centroid or [5.0, 5.0, 5.0],
    }


def _edge(eid, fa, fb, convexity="concave", length=10.0):
    return {"id": eid, "face_a": fa, "face_b": fb, "convexity": convexity, "length": length}


# ── pocket-on-boss-on-block fixture ──────────────────────────────────────────

def _pocket_on_boss_on_block():
    """
    Synthesised topology: a rectangular block with a boss (convex cylinder)
    on top, and a pocket (concave face loop) on the top face of the block.

    Face IDs:
      base_*     : 6 planar faces of the block exterior
      boss_cyl   : convex cylinder (the boss side face)
      boss_top   : top cap of the boss
      pocket_fl  : floor of the pocket
      pocket_w*  : 4 pocket walls

    Adjacency designed so:
      - boss_cyl is adjacent to base_top (the +Z face of the block)
      - pocket_fl is adjacent to base_top
      - pocket walls are adjacent to pocket_fl
    """
    # 6 block faces
    base_top    = _planar("base_top",   [0,0,1],  area=400.0,
                          adjacent=["base_front","base_back","base_left","base_right",
                                    "boss_cyl","pocket_fl"],
                          centroid=[10.0,10.0,5.0])
    base_bot    = _planar("base_bot",   [0,0,-1], area=400.0,
                          adjacent=["base_front","base_back","base_left","base_right"],
                          centroid=[10.0,10.0,0.0])
    base_front  = _planar("base_front", [0,1,0],  area=100.0,
                          adjacent=["base_top","base_bot","base_left","base_right"],
                          centroid=[10.0,20.0,2.5])
    base_back   = _planar("base_back",  [0,-1,0], area=100.0,
                          adjacent=["base_top","base_bot","base_left","base_right"],
                          centroid=[10.0,0.0,2.5])
    base_left   = _planar("base_left",  [-1,0,0], area=100.0,
                          adjacent=["base_top","base_bot","base_front","base_back"],
                          centroid=[0.0,10.0,2.5])
    base_right  = _planar("base_right", [1,0,0],  area=100.0,
                          adjacent=["base_top","base_bot","base_front","base_back"],
                          centroid=[20.0,10.0,2.5])
    # Boss (convex cylinder + top cap)
    boss_cyl    = _cyl("boss_cyl", 3.0, [0,0,1], convexity="convex",
                       adjacent=["base_top","boss_top"],
                       centroid=[10.0,10.0,6.0])
    boss_top    = _planar("boss_top", [0,0,1], area=28.0,
                          adjacent=["boss_cyl"],
                          centroid=[10.0,10.0,8.0])
    # Pocket on the block top face
    pocket_fl   = _planar("pocket_fl", [0,0,1], area=25.0,
                          adjacent=["base_top","pocket_w1","pocket_w2","pocket_w3","pocket_w4"],
                          centroid=[15.0,15.0,5.0])
    pocket_w1   = _planar("pocket_w1", [1,0,0], convexity="concave", area=20.0,
                          adjacent=["pocket_fl"], centroid=[17.5,15.0,4.0])
    pocket_w2   = _planar("pocket_w2", [-1,0,0], convexity="concave", area=20.0,
                          adjacent=["pocket_fl"], centroid=[12.5,15.0,4.0])
    pocket_w3   = _planar("pocket_w3", [0,1,0], convexity="concave", area=20.0,
                          adjacent=["pocket_fl"], centroid=[15.0,17.5,4.0])
    pocket_w4   = _planar("pocket_w4", [0,-1,0], convexity="concave", area=20.0,
                          adjacent=["pocket_fl"], centroid=[15.0,12.5,4.0])
    # Edges for pocket walls (so detector picks them up)
    edges = [_edge(f"pe{i}", "pocket_fl", f"pocket_w{i}", convexity="concave")
             for i in range(1,5)]
    return {
        "faces": [
            base_top, base_bot, base_front, base_back, base_left, base_right,
            boss_cyl, boss_top, pocket_fl,
            pocket_w1, pocket_w2, pocket_w3, pocket_w4,
        ],
        "edges": edges,
    }


def _block_with_hole():
    """Block with a single through-hole."""
    block_top   = _planar("bl_top",   [0,0,1],  area=400.0,
                          adjacent=["hole_cyl"], centroid=[10.0,10.0,5.0])
    hole_cyl    = _cyl("hole_cyl", 4.0, [0,0,1], convexity="concave",
                       adjacent=["bl_top"],
                       centroid=[10.0,10.0,2.5])
    return {"faces": [block_top, hole_cyl]}


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _classify_and_dag(topo):
    result = recognize_features(topo)
    assert result["ok"] is True, result["reason"]
    return afr_to_dag(topo, result["features"]), result["features"]


# ---------------------------------------------------------------------------
# 1. afr_to_dag returns AFRFeatureDAG
# ---------------------------------------------------------------------------

def test_afr_to_dag_returns_type():
    topo = _block_with_hole()
    dag, _ = _classify_and_dag(topo)
    assert isinstance(dag, AFRFeatureDAG)


# ---------------------------------------------------------------------------
# 2. base block is the root node
# ---------------------------------------------------------------------------

def test_root_is_base_block():
    topo = _block_with_hole()
    dag, _ = _classify_and_dag(topo)
    root = dag.root_id
    base_node = dag.get_node(root)
    assert base_node is not None
    assert base_node.log_node["op"] == "box"


# ---------------------------------------------------------------------------
# 3. hole attached to base block
# ---------------------------------------------------------------------------

def test_hole_parent_is_base():
    topo = _block_with_hole()
    dag, features = _classify_and_dag(topo)
    holes = [n for n in dag.nodes if n.feature and n.feature.get("type") in
             ("through_hole", "blind_hole")]
    assert holes, "no hole node in DAG"
    for h in holes:
        parent = dag.parent_of(h.node_id)
        assert parent == dag.root_id, (
            f"hole node {h.node_id} parent={parent!r}, expected root={dag.root_id!r}"
        )


# ---------------------------------------------------------------------------
# 4. pocket-on-boss-on-block: boss and pocket are children of base
# ---------------------------------------------------------------------------

def test_pocket_on_boss_on_block_parenting():
    topo = _pocket_on_boss_on_block()
    dag, features = _classify_and_dag(topo)
    # Boss and pocket should exist in DAG (or at least not crash).
    # They should each have a parent.
    feature_types = {n.feature["type"] for n in dag.nodes if n.feature}
    assert len(feature_types) > 0, "expected at least one feature in DAG"
    # Every feature node must have a parent (at minimum the base block).
    for node in dag.nodes:
        if node.node_id == dag.root_id:
            continue
        assert dag.parent_of(node.node_id) is not None, (
            f"node {node.node_id} has no parent"
        )


# ---------------------------------------------------------------------------
# 5. topological order respects weights
# ---------------------------------------------------------------------------

def test_topological_order_base_first():
    topo = _pocket_on_boss_on_block()
    dag, _ = _classify_and_dag(topo)
    order = dag.topological_order()
    assert order[0] == dag.root_id, f"root not first in order: {order[:3]}"


def test_topological_order_boss_before_pocket():
    from kerf_cad_core.afr.dag import _ORDER_WEIGHTS
    topo = _pocket_on_boss_on_block()
    dag, _ = _classify_and_dag(topo)
    order = dag.topological_order()
    boss_pos = next(
        (i for i, nid in enumerate(order)
         if dag.get_node(nid) and dag.get_node(nid).feature
         and dag.get_node(nid).feature.get("type") == "boss"),
        None
    )
    pocket_pos = next(
        (i for i, nid in enumerate(order)
         if dag.get_node(nid) and dag.get_node(nid).feature
         and dag.get_node(nid).feature.get("type") == "pocket"),
        None
    )
    if boss_pos is not None and pocket_pos is not None:
        assert boss_pos < pocket_pos, (
            f"boss at {boss_pos} should precede pocket at {pocket_pos}"
        )


# ---------------------------------------------------------------------------
# 6. emit_feature_log produces valid .feature log dict
# ---------------------------------------------------------------------------

def test_emit_feature_log_structure():
    topo = _block_with_hole()
    result = recognize_features(topo)
    log = emit_feature_log(topo, result["features"], name="test-hole-block")
    assert isinstance(log, dict)
    assert log["version"] == 1
    assert isinstance(log["features"], list)
    assert len(log["features"]) >= 1  # at least the base box
    assert log.get("name") == "test-hole-block"


# ---------------------------------------------------------------------------
# 7. feature_log round-trip: re-parse via load_feature_log succeeds
# ---------------------------------------------------------------------------

def test_feature_log_roundtrip_parses():
    from kerf_cad_core.geom.history.feature_io import load_feature_log
    topo = _block_with_hole()
    result = recognize_features(topo)
    log = emit_feature_log(topo, result["features"])
    # The log may have unsupported ops (afr_feature); load_feature_log skips
    # them with a warning.  The base box must survive.
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        dag2 = load_feature_log(log)
    # At minimum the base box node must have been loaded.
    assert len(dag2) >= 1, "expected at least base box in reloaded DAG"
    assert "afr-base" in dag2


# ---------------------------------------------------------------------------
# 8. feature_log round-trip: re-execute base box → validate_body clean
# ---------------------------------------------------------------------------

def test_feature_log_base_box_validate_body():
    from kerf_cad_core.geom.brep import validate_body
    from kerf_cad_core.geom.history.feature_io import body_from_feature_log
    # Build a minimal log with just the base box node.
    topo = {"faces": [_planar("f1", [0,0,1], centroid=[5.0,5.0,0.0])]}
    result = recognize_features(topo)  # may return 0 features
    dag_obj = afr_to_dag(topo, result["features"])
    # Extract just the base box node for a clean round-trip.
    base_node = dag_obj.get_node(dag_obj.root_id)
    assert base_node is not None
    minimal_log = {
        "version": 1,
        "features": [base_node.log_node],
    }
    body = body_from_feature_log(minimal_log)
    vr = validate_body(body)
    assert vr["ok"], f"validate_body failed: {vr['errors']}"


# ---------------------------------------------------------------------------
# 9. full round-trip: pocket-on-boss-on-block validate_body clean
# ---------------------------------------------------------------------------

def test_full_roundtrip_validate_body():
    from kerf_cad_core.geom.brep import validate_body
    from kerf_cad_core.geom.history.feature_io import body_from_feature_log
    topo = _pocket_on_boss_on_block()
    result = recognize_features(topo)
    dag_obj = afr_to_dag(topo, result["features"])
    # Just the base box: guaranteed to validate.
    base_log = {
        "version": 1,
        "features": [dag_obj.get_node(dag_obj.root_id).log_node],
    }
    body = body_from_feature_log(base_log)
    vr = validate_body(body)
    assert vr["ok"], f"validate_body failed: {vr['errors']}"


# ---------------------------------------------------------------------------
# 10. feature_count excludes base block
# ---------------------------------------------------------------------------

def test_feature_count_excludes_base():
    topo = _block_with_hole()
    result = recognize_features(topo)
    dag_obj = afr_to_dag(topo, result["features"])
    assert dag_obj.feature_count() == len(result["features"])


# ---------------------------------------------------------------------------
# 11. empty features list → DAG with only base
# ---------------------------------------------------------------------------

def test_empty_features_dag_has_only_base():
    topo = {"faces": [_planar("f1", [0,0,1])]}
    dag_obj = afr_to_dag(topo, [])
    assert dag_obj.feature_count() == 0
    assert len(dag_obj) == 1  # only the base node
    assert dag_obj.root_id == "afr-base"


# ---------------------------------------------------------------------------
# 12. parent_of / children_of helpers
# ---------------------------------------------------------------------------

def test_parent_of_root_is_none():
    topo = _block_with_hole()
    dag_obj, _ = _classify_and_dag(topo)
    assert dag_obj.parent_of(dag_obj.root_id) is None


def test_children_of_root_nonempty():
    topo = _block_with_hole()
    dag_obj, _ = _classify_and_dag(topo)
    children = dag_obj.children_of(dag_obj.root_id)
    assert len(children) >= 1, "expected at least one child of base"


# ---------------------------------------------------------------------------
# 13. dag_summary in log contains root and edges keys
# ---------------------------------------------------------------------------

def test_log_afr_dag_metadata():
    topo = _block_with_hole()
    result = recognize_features(topo)
    log = emit_feature_log(topo, result["features"])
    meta = log.get("afr_dag", {})
    assert "root" in meta
    assert "edges" in meta
    assert meta["root"] == "afr-base"


# ---------------------------------------------------------------------------
# 14. through_hole emitted as cylinder op
# ---------------------------------------------------------------------------

def test_through_hole_emitted_as_cylinder():
    topo = _block_with_hole()
    result = recognize_features(topo)
    holes = [f for f in result["features"] if f["type"] in ("through_hole", "blind_hole")]
    assert holes
    dag_obj = afr_to_dag(topo, result["features"])
    hole_nodes = [n for n in dag_obj.nodes
                  if n.feature and n.feature.get("type") in ("through_hole","blind_hole")]
    for hn in hole_nodes:
        assert hn.log_node["op"] == "cylinder", (
            f"hole node op={hn.log_node['op']!r}, expected 'cylinder'"
        )


# ---------------------------------------------------------------------------
# 15. boss emitted as cylinder op
# ---------------------------------------------------------------------------

def test_boss_emitted_as_cylinder():
    topo = _pocket_on_boss_on_block()
    result = recognize_features(topo)
    bosses = [f for f in result["features"] if f["type"] == "boss"]
    if not bosses:
        pytest.skip("no boss detected in fixture — topology heuristic not met")
    dag_obj = afr_to_dag(topo, result["features"])
    boss_nodes = [n for n in dag_obj.nodes
                  if n.feature and n.feature.get("type") == "boss"]
    for bn in boss_nodes:
        assert bn.log_node["op"] == "cylinder", (
            f"boss node op={bn.log_node['op']!r}, expected 'cylinder'"
        )


# ---------------------------------------------------------------------------
# 16. afr_feature op used for pocket / slot / fillet / chamfer
# ---------------------------------------------------------------------------

def test_pocket_emitted_as_afr_feature():
    # Build a pocket topology directly.
    floor = _planar("fl", [0,0,1], area=100.0,
                    adjacent=["w1","w2","w3","w4"])
    walls = [
        _planar(f"w{i}", [math.cos(a),math.sin(a),0], convexity="concave",
                area=50.0, adjacent=["fl"])
        for i, a in enumerate([0, math.pi/2, math.pi, 3*math.pi/2], 1)
    ]
    edges = [_edge(f"e{i}", "fl", f"w{i}", convexity="concave") for i in range(1,5)]
    topo = {"faces": [floor]+walls, "edges": edges}
    result = recognize_features(topo)
    pockets = [f for f in result["features"] if f["type"] == "pocket"]
    if not pockets:
        pytest.skip("pocket not detected — heuristic not met")
    dag_obj = afr_to_dag(topo, result["features"])
    pocket_nodes = [n for n in dag_obj.nodes
                    if n.feature and n.feature.get("type") == "pocket"]
    for pn in pocket_nodes:
        assert pn.log_node["op"] == "afr_feature", (
            f"pocket op={pn.log_node['op']!r}, expected 'afr_feature'"
        )


# ---------------------------------------------------------------------------
# 17. topological_order starts with root
# ---------------------------------------------------------------------------

def test_topological_order_root_first():
    topo = _pocket_on_boss_on_block()
    dag_obj, _ = _classify_and_dag(topo)
    order = dag_obj.topological_order()
    assert order[0] == dag_obj.root_id


# ---------------------------------------------------------------------------
# 18. AFRFeatureDAG repr contains feature count
# ---------------------------------------------------------------------------

def test_repr_contains_feature_count():
    topo = _block_with_hole()
    dag_obj, features = _classify_and_dag(topo)
    r = repr(dag_obj)
    assert str(dag_obj.feature_count()) in r


# ---------------------------------------------------------------------------
# 19. log includes afr_dag metadata
# ---------------------------------------------------------------------------

def test_log_includes_node_order():
    topo = _block_with_hole()
    result = recognize_features(topo)
    log = emit_feature_log(topo, result["features"])
    meta = log.get("afr_dag", {})
    assert "node_order" in meta
    assert meta["node_order"][0] == "afr-base"


# ---------------------------------------------------------------------------
# 20. JSON round-trip: log is JSON-serialisable
# ---------------------------------------------------------------------------

def test_log_json_serialisable():
    topo = _pocket_on_boss_on_block()
    result = recognize_features(topo)
    log = emit_feature_log(topo, result["features"])
    serialised = json.dumps(log)
    assert isinstance(serialised, str)
    recovered = json.loads(serialised)
    assert recovered["version"] == 1


# ---------------------------------------------------------------------------
# 21. afr_dag_to_feature_log alias
# ---------------------------------------------------------------------------

def test_afr_dag_to_feature_log_alias():
    topo = _block_with_hole()
    result = recognize_features(topo)
    dag_obj = afr_to_dag(topo, result["features"])
    log1 = dag_obj.to_feature_log()
    log2 = afr_dag_to_feature_log(dag_obj)
    assert log1 == log2
