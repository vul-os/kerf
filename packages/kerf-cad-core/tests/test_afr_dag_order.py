"""
test_afr_dag_order.py
=====================
Tests for kerf_cad_core.afr.dag_order — AFR Topology DAG Ordering.

All tests are hermetic (pure Python + numpy, no OCC, no DB, no network).

Coverage
--------
 1.  single_base_feature              — 1-node DAG, no edges
 2.  base_plus_boss_plus_fillet       — fillet depends on boss, boss depends on base
 3.  base_plus_boss_plus_hole_through_boss — hole depends on boss
 4.  disjoint_pockets_same_base       — two pockets only depend on base, not each other
 5.  replay_order_base_first          — base feature is first in replay_order()
 6.  replay_order_additive_before_subtractive — bosses before holes in same level
 7.  replay_order_fillets_last        — fillet/chamfer IDs appear after all others
 8.  cycle_detection_raises           — forced cycle → ValueError with useful message
 9.  is_additive_boss                 — is_additive(BOSS) is True
10.  is_additive_extrude              — is_additive(EXTRUDE) is True
11.  is_additive_rib                  — is_additive(RIB) is True
12.  is_additive_hole_false           — is_additive(THROUGH_HOLE) is False
13.  is_subtractive_through_hole      — is_subtractive(THROUGH_HOLE) is True
14.  is_subtractive_pocket            — is_subtractive(POCKET) is True
15.  is_subtractive_boss_false        — is_subtractive(BOSS) is False
16.  intersects_overlapping_bboxes    — overlapping AABBs → True
17.  intersects_disjoint_bboxes       — disjoint AABBs → False
18.  intersects_touching_bboxes       — edge-touching AABBs → True (not strictly exclusive)
19.  empty_feature_list               — order_features_to_dag([]) → empty DAG
20.  dag_nodes_in_topological_order   — every node's parents appear before it in nodes list
21.  ten_feature_complex_assembly     — 10-feature model: correct edge count, topological order
22.  depth_in_tree_single_chain       — 3-deep chain: depths are 0, 1, 2
23.  duplicate_feature_id_raises      — duplicate IDs → ValueError
24.  replay_order_all_ids_present     — replay_order() returns all feature IDs exactly once
25.  recognized_feature_from_dict     — round-trip conversion from recognize.py dict
"""

from __future__ import annotations

import pytest
from kerf_cad_core.afr.dag_order import (
    FeatureKind,
    FeatureNode,
    ParametricDAG,
    RecognizedFeature,
    intersects,
    is_additive,
    is_subtractive,
    order_features_to_dag,
    recognized_feature_from_dict,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bbox(
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    hx: float = 5.0,
    hy: float = 5.0,
    hz: float = 5.0,
):
    """Return an AABB tuple centred at (cx,cy,cz) with half-extents hx,hy,hz."""
    return (
        (cx - hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz + hz),
    )


def _feat(
    fid: str,
    kind: FeatureKind,
    *,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    hx: float = 5.0,
    hy: float = 5.0,
    hz: float = 5.0,
    axis=None,
    face_ids=None,
    parameters=None,
) -> RecognizedFeature:
    return RecognizedFeature(
        feature_id=fid,
        kind=kind,
        face_ids=face_ids or [],
        extent_bbox=_bbox(cx, cy, cz, hx, hy, hz),
        axis=axis,
        parameters=parameters or {},
    )


# ---------------------------------------------------------------------------
# Test 1: single base feature
# ---------------------------------------------------------------------------

def test_single_base_feature():
    """A single EXTRUDE feature → 1-node DAG, no edges."""
    features = [_feat("base", FeatureKind.EXTRUDE)]
    dag = order_features_to_dag(features)
    assert len(dag.nodes) == 1
    assert dag.nodes[0].feature.feature_id == "base"
    assert dag.edges == []
    assert dag.nodes[0].depends_on == []
    assert dag.nodes[0].depth_in_tree == 0


# ---------------------------------------------------------------------------
# Test 2: base + boss + fillet
# ---------------------------------------------------------------------------

def test_base_plus_boss_plus_fillet():
    """Base → boss → fillet: fillet depends on boss, boss depends on base."""
    features = [
        _feat("base", FeatureKind.EXTRUDE, cx=0, cy=0, cz=0, hx=20, hy=20, hz=5),
        _feat("boss1", FeatureKind.BOSS, cx=0, cy=0, cz=5, hx=3, hy=3, hz=4),
        _feat("fillet1", FeatureKind.FILLET, cx=0, cy=0, cz=5, hx=3, hy=3, hz=4),
    ]
    dag = order_features_to_dag(features)
    assert len(dag.nodes) == 3

    node_by_id = {n.feature.feature_id: n for n in dag.nodes}
    # base comes before boss
    boss_node = node_by_id["boss1"]
    fillet_node = node_by_id["fillet1"]

    assert "base" in boss_node.depends_on
    # fillet must depend on boss (both in same bbox, lower layer → higher layer)
    assert "boss1" in fillet_node.depends_on or "base" in fillet_node.depends_on

    replay = dag.replay_order()
    assert replay.index("base") < replay.index("boss1")
    assert replay.index("boss1") < replay.index("fillet1")


# ---------------------------------------------------------------------------
# Test 3: hole through boss
# ---------------------------------------------------------------------------

def test_hole_through_boss():
    """A through-hole whose axis passes through the boss's bbox depends on the boss."""
    # Boss centred at (0,0,10), height 8, radius 5
    boss = _feat("boss1", FeatureKind.BOSS,
                 cx=0, cy=0, cz=10, hx=5, hy=5, hz=4)
    # Through-hole coaxial with boss, centred at same xy, Z axis
    hole = _feat("hole1", FeatureKind.THROUGH_HOLE,
                 cx=0, cy=0, cz=10, hx=2, hy=2, hz=4,
                 axis=(0.0, 0.0, 1.0))
    base = _feat("base", FeatureKind.EXTRUDE, hx=20, hy=20, hz=20)
    dag = order_features_to_dag([base, boss, hole])

    node_by_id = {n.feature.feature_id: n for n in dag.nodes}
    hole_node = node_by_id["hole1"]
    # Hole must depend on boss (R3) and/or base (R1)
    assert "boss1" in hole_node.depends_on

    replay = dag.replay_order()
    assert replay.index("boss1") < replay.index("hole1")


# ---------------------------------------------------------------------------
# Test 4: disjoint pockets on same base
# ---------------------------------------------------------------------------

def test_disjoint_pockets_same_base():
    """Two pockets far apart on the same base depend on base only, not each other."""
    base = _feat("base", FeatureKind.EXTRUDE, cx=0, cy=0, cz=0, hx=50, hy=50, hz=5)
    # pockets are far apart — no bbox overlap between them
    pocket_a = _feat("pkt_a", FeatureKind.POCKET, cx=-30, cy=0, cz=0, hx=5, hy=5, hz=3)
    pocket_b = _feat("pkt_b", FeatureKind.POCKET, cx=30, cy=0, cz=0, hx=5, hy=5, hz=3)

    dag = order_features_to_dag([base, pocket_a, pocket_b])
    node_by_id = {n.feature.feature_id: n for n in dag.nodes}

    # Each pocket depends on base only
    assert "base" in node_by_id["pkt_a"].depends_on
    assert "base" in node_by_id["pkt_b"].depends_on
    # Pockets do not depend on each other
    assert "pkt_b" not in node_by_id["pkt_a"].depends_on
    assert "pkt_a" not in node_by_id["pkt_b"].depends_on


# ---------------------------------------------------------------------------
# Test 5: replay_order — base first
# ---------------------------------------------------------------------------

def test_replay_order_base_first():
    """Base EXTRUDE or REVOLVE must be the first feature in replay_order()."""
    features = [
        _feat("pocket1", FeatureKind.POCKET, cx=5, cy=0, cz=0, hx=4, hy=4, hz=3),
        _feat("base", FeatureKind.EXTRUDE, hx=30, hy=30, hz=10),
        _feat("boss1", FeatureKind.BOSS, cx=-5, cy=0, cz=0, hx=3, hy=3, hz=4),
    ]
    dag = order_features_to_dag(features)
    assert dag.replay_order()[0] == "base"


# ---------------------------------------------------------------------------
# Test 6: replay_order — additive before subtractive within same depth
# ---------------------------------------------------------------------------

def test_replay_order_additive_before_subtractive():
    """Additive features (BOSS) must appear before subtractive (THROUGH_HOLE) when both
    depend only on the base and their bboxes do not overlap each other."""
    base = _feat("base", FeatureKind.EXTRUDE, hx=50, hy=50, hz=5)
    boss = _feat("boss1", FeatureKind.BOSS, cx=-20, cy=0, cz=5, hx=3, hy=3, hz=4)
    hole = _feat("hole1", FeatureKind.THROUGH_HOLE,
                 cx=20, cy=0, cz=0, hx=2, hy=2, hz=5, axis=(0, 0, 1))
    dag = order_features_to_dag([base, boss, hole])
    replay = dag.replay_order()
    assert replay.index("boss1") < replay.index("hole1")


# ---------------------------------------------------------------------------
# Test 7: replay_order — fillets last
# ---------------------------------------------------------------------------

def test_replay_order_fillets_last():
    """FILLET and CHAMFER must appear after all non-finishing features."""
    base = _feat("base", FeatureKind.EXTRUDE, hx=20, hy=20, hz=5)
    pocket = _feat("pkt1", FeatureKind.POCKET, cx=0, cy=0, cz=0, hx=4, hy=4, hz=3)
    fillet = _feat("fill1", FeatureKind.FILLET, cx=0, cy=0, cz=0, hx=4, hy=4, hz=3)
    chamfer = _feat("chm1", FeatureKind.CHAMFER, cx=0, cy=0, cz=0, hx=4, hy=4, hz=3)

    dag = order_features_to_dag([base, pocket, fillet, chamfer])
    replay = dag.replay_order()
    finishing_indices = [replay.index("fill1"), replay.index("chm1")]
    non_finishing_indices = [replay.index("base"), replay.index("pkt1")]
    assert max(non_finishing_indices) < min(finishing_indices)


# ---------------------------------------------------------------------------
# Test 8: cycle detection raises ValueError
# ---------------------------------------------------------------------------

def test_cycle_detection_raises():
    """A forced cycle in features should raise ValueError describing the cycle."""
    # We can't inject a cycle via inferred edges alone (they're acyclic by construction),
    # so we test via a subclass that forces a cycle by monkey-patching _infer_edges.
    from kerf_cad_core.afr import dag_order as mod

    original = mod._infer_edges

    def _cyclic_edges(features):
        ids = [f.feature_id for f in features]
        if len(ids) >= 2:
            return [(ids[0], ids[1]), (ids[1], ids[0])]  # force cycle
        return []

    mod._infer_edges = _cyclic_edges
    try:
        features = [
            _feat("a", FeatureKind.EXTRUDE),
            _feat("b", FeatureKind.POCKET),
        ]
        with pytest.raises(ValueError, match="[Cc]ycle"):
            order_features_to_dag(features)
    finally:
        mod._infer_edges = original


# ---------------------------------------------------------------------------
# Tests 9–12: is_additive
# ---------------------------------------------------------------------------

def test_is_additive_boss():
    assert is_additive(FeatureKind.BOSS) is True


def test_is_additive_extrude():
    assert is_additive(FeatureKind.EXTRUDE) is True


def test_is_additive_rib():
    assert is_additive(FeatureKind.RIB) is True


def test_is_additive_hole_false():
    assert is_additive(FeatureKind.THROUGH_HOLE) is False


# ---------------------------------------------------------------------------
# Tests 13–15: is_subtractive
# ---------------------------------------------------------------------------

def test_is_subtractive_through_hole():
    assert is_subtractive(FeatureKind.THROUGH_HOLE) is True


def test_is_subtractive_pocket():
    assert is_subtractive(FeatureKind.POCKET) is True


def test_is_subtractive_boss_false():
    assert is_subtractive(FeatureKind.BOSS) is False


# ---------------------------------------------------------------------------
# Tests 16–18: intersects
# ---------------------------------------------------------------------------

def test_intersects_overlapping_bboxes():
    a = _feat("a", FeatureKind.BOSS, cx=0, cy=0, cz=0, hx=5, hy=5, hz=5)
    b = _feat("b", FeatureKind.POCKET, cx=3, cy=3, cz=3, hx=5, hy=5, hz=5)
    assert intersects(a, b) is True


def test_intersects_disjoint_bboxes():
    a = _feat("a", FeatureKind.BOSS, cx=-10, cy=0, cz=0, hx=2, hy=2, hz=2)
    b = _feat("b", FeatureKind.POCKET, cx=10, cy=0, cz=0, hx=2, hy=2, hz=2)
    assert intersects(a, b) is False


def test_intersects_touching_bboxes():
    """Edge-touching (shared face) must be detected as intersecting."""
    a = RecognizedFeature("a", FeatureKind.BOSS, [],
                          ((0.0, 0.0, 0.0), (5.0, 5.0, 5.0)), None)
    b = RecognizedFeature("b", FeatureKind.POCKET, [],
                          ((5.0, 0.0, 0.0), (10.0, 5.0, 5.0)), None)
    # Touching at x=5; bxmax==axmin so axmax >= bxmin (5>=5) and bxmax >= axmin (10>=0)
    assert intersects(a, b) is True


# ---------------------------------------------------------------------------
# Test 19: empty feature list
# ---------------------------------------------------------------------------

def test_empty_feature_list():
    dag = order_features_to_dag([])
    assert dag.nodes == []
    assert dag.edges == []
    assert dag.replay_order() == []


# ---------------------------------------------------------------------------
# Test 20: topological order invariant
# ---------------------------------------------------------------------------

def test_dag_nodes_in_topological_order():
    """For every node, all its parents appear earlier in dag.nodes."""
    base = _feat("base", FeatureKind.EXTRUDE, hx=30, hy=30, hz=5)
    boss = _feat("boss1", FeatureKind.BOSS, cx=0, cy=0, cz=5, hx=4, hy=4, hz=4)
    hole = _feat("hole1", FeatureKind.THROUGH_HOLE, cx=0, cy=0, cz=5, hx=2, hy=2, hz=4,
                 axis=(0.0, 0.0, 1.0))
    fillet = _feat("fillet1", FeatureKind.FILLET, cx=0, cy=0, cz=5, hx=4, hy=4, hz=4)

    dag = order_features_to_dag([base, boss, hole, fillet])
    seen: set = set()
    for node in dag.nodes:
        for parent_id in node.depends_on:
            assert parent_id in seen, (
                f"Parent '{parent_id}' of '{node.feature.feature_id}' "
                f"has not appeared yet in dag.nodes order"
            )
        seen.add(node.feature.feature_id)


# ---------------------------------------------------------------------------
# Test 21: 10-feature complex assembly
# ---------------------------------------------------------------------------

def test_ten_feature_complex_assembly():
    """10-feature model: correct count of nodes, valid topological order, fillets last."""
    base = _feat("base", FeatureKind.EXTRUDE, hx=50, hy=50, hz=10)
    boss_a = _feat("boss_a", FeatureKind.BOSS, cx=-20, cy=0, cz=10, hx=5, hy=5, hz=5)
    boss_b = _feat("boss_b", FeatureKind.BOSS, cx=20, cy=0, cz=10, hx=5, hy=5, hz=5)
    rib1 = _feat("rib1", FeatureKind.RIB, cx=0, cy=0, cz=5, hx=2, hy=20, hz=4)
    pocket_a = _feat("pkt_a", FeatureKind.POCKET, cx=-20, cy=0, cz=0, hx=4, hy=4, hz=3)
    hole_a = _feat("hole_a", FeatureKind.THROUGH_HOLE,
                   cx=-20, cy=0, cz=10, hx=2, hy=2, hz=5, axis=(0, 0, 1))
    hole_b = _feat("hole_b", FeatureKind.BLIND_HOLE,
                   cx=20, cy=0, cz=10, hx=2, hy=2, hz=5, axis=(0, 0, 1))
    slot1 = _feat("slot1", FeatureKind.SLOT, cx=0, cy=-20, cz=0, hx=2, hy=5, hz=3)
    fillet_a = _feat("flt_a", FeatureKind.FILLET, cx=-20, cy=0, cz=10, hx=5, hy=5, hz=5)
    chamfer_a = _feat("chm_a", FeatureKind.CHAMFER, cx=20, cy=0, cz=10, hx=5, hy=5, hz=5)

    all_features = [base, boss_a, boss_b, rib1, pocket_a,
                    hole_a, hole_b, slot1, fillet_a, chamfer_a]
    dag = order_features_to_dag(all_features)

    assert len(dag.nodes) == 10

    # Topological order invariant
    seen: set = set()
    for node in dag.nodes:
        for parent_id in node.depends_on:
            assert parent_id in seen, f"Order violation: {parent_id} not before {node.feature.feature_id}"
        seen.add(node.feature.feature_id)

    replay = dag.replay_order()
    assert len(replay) == 10

    # Base first
    assert replay[0] == "base"

    # Fillets/chamfers must be after all subtractive and additive
    finishing = {"flt_a", "chm_a"}
    non_finishing_max = max(
        replay.index(fid) for fid in replay if fid not in finishing
    )
    finishing_min = min(replay.index(fid) for fid in finishing)
    assert non_finishing_max < finishing_min

    # Hole through boss: hole_a bbox overlaps boss_a bbox, axis passes through
    node_by_id = {n.feature.feature_id: n for n in dag.nodes}
    assert "boss_a" in node_by_id["hole_a"].depends_on


# ---------------------------------------------------------------------------
# Test 22: depth_in_tree for a single chain
# ---------------------------------------------------------------------------

def test_depth_in_tree_single_chain():
    """base→boss→fillet chain: depths should be 0, 1, ≥2."""
    base = _feat("base", FeatureKind.EXTRUDE, hx=30, hy=30, hz=5)
    boss = _feat("boss1", FeatureKind.BOSS, cx=0, cy=0, cz=5, hx=4, hy=4, hz=4)
    fillet = _feat("flt1", FeatureKind.FILLET, cx=0, cy=0, cz=5, hx=4, hy=4, hz=4)

    dag = order_features_to_dag([base, boss, fillet])
    node_by_id = {n.feature.feature_id: n for n in dag.nodes}

    assert node_by_id["base"].depth_in_tree == 0
    assert node_by_id["boss1"].depth_in_tree == 1
    # Fillet depends on boss (layer 5 > boss layer 1) and base (layer 5 > 0),
    # so depth should be >= 2 (longest chain through boss).
    assert node_by_id["flt1"].depth_in_tree >= 2


# ---------------------------------------------------------------------------
# Test 23: duplicate feature_id raises ValueError
# ---------------------------------------------------------------------------

def test_duplicate_feature_id_raises():
    a = _feat("dup", FeatureKind.BOSS)
    b = _feat("dup", FeatureKind.POCKET)
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        order_features_to_dag([a, b])


# ---------------------------------------------------------------------------
# Test 24: replay_order returns all IDs exactly once
# ---------------------------------------------------------------------------

def test_replay_order_all_ids_present():
    features = [
        _feat("base", FeatureKind.EXTRUDE, hx=30, hy=30, hz=5),
        _feat("boss1", FeatureKind.BOSS, cx=5, cy=0, cz=5, hx=3, hy=3, hz=4),
        _feat("hole1", FeatureKind.THROUGH_HOLE, cx=5, cy=0, cz=5, hx=2, hy=2, hz=4,
              axis=(0.0, 0.0, 1.0)),
        _feat("flt1", FeatureKind.FILLET, cx=5, cy=0, cz=5, hx=3, hy=3, hz=4),
    ]
    dag = order_features_to_dag(features)
    replay = dag.replay_order()
    assert sorted(replay) == sorted(["base", "boss1", "hole1", "flt1"])
    assert len(set(replay)) == len(replay)  # no duplicates


# ---------------------------------------------------------------------------
# Test 25: recognized_feature_from_dict round-trip
# ---------------------------------------------------------------------------

def test_recognized_feature_from_dict():
    """Conversion from recognize.py output dict format."""
    d = {
        "type": "through_hole",
        "params": {
            "diameter": 10.0,
            "axis": [0.0, 0.0, 1.0],
            "depth": 20.0,
            "position": [5.0, 5.0, 0.0],
        },
        "face_ids": [1, 2],
        "confidence": 0.85,
    }
    feat = recognized_feature_from_dict("fid_01", d)
    assert feat.feature_id == "fid_01"
    assert feat.kind == FeatureKind.THROUGH_HOLE
    assert feat.axis is not None
    assert abs(feat.axis[2] - 1.0) < 1e-9
    assert feat.face_ids == [1, 2]
    # bbox lo <= center <= hi
    lo, hi = feat.extent_bbox
    assert lo[0] <= 5.0 <= hi[0]
    assert lo[1] <= 5.0 <= hi[1]
    assert lo[2] <= 0.0 <= hi[2]
    # depth extends the bbox along Z axis
    assert hi[2] > lo[2]


# ---------------------------------------------------------------------------
# Extra: is_additive covers REVOLVE
# ---------------------------------------------------------------------------

def test_is_additive_revolve():
    assert is_additive(FeatureKind.REVOLVE) is True


# Extra: is_subtractive covers SLOT, STEP, COUNTERBORE, COUNTERSINK, BLIND_HOLE
def test_is_subtractive_all_kinds():
    for kind in (FeatureKind.SLOT, FeatureKind.STEP,
                 FeatureKind.COUNTERBORE, FeatureKind.COUNTERSINK,
                 FeatureKind.BLIND_HOLE):
        assert is_subtractive(kind) is True, f"{kind} should be subtractive"
