"""
test_afr.py
===========
Hermetic tests for kerf_cad_core.afr.recognize (Automatic Feature Recognition).

All tests use synthetic topology fixtures — no OCC, no network, no database.

Coverage
--------
1.  block_with_one_through_hole  — exactly 1 through-hole, correct dia/axis
2.  through_hole_diameter        — diameter matches 2*radius
3.  through_hole_axis_z          — axis is [0,0,1]
4.  through_hole_axis_x          — axis is [1,0,0] (non-default axis)
5.  blind_hole_floor_face        — single floor → blind_hole, not through_hole
6.  blind_hole_has_depth         — depth > 0
7.  through_hole_two_caps        — cylinder + 2 cap faces → still through_hole
8.  counterbore_detected         — two coaxial cylinders + step → counterbore
9.  counterbore_bore_gt_drill    — bore_diameter > drill_diameter
10. countersink_detected         — conical face → countersink
11. pocket_detected              — concave wall loop + floor → pocket
12. pocket_wall_count            — wall_count matches fixture
13. slot_detected                — high-aspect floor → slot
14. slot_aspect                  — slot length >= SLOT_ASPECT_RATIO * width
15. boss_detected                — convex cylinder → boss
16. boss_vs_pocket_by_convexity  — convex=boss, concave=hole (not boss)
17. fillet_toroidal              — toroidal face → fillet with correct radius
18. fillet_radius                — fillet radius matches fixture
19. chamfer_detected             — 45° bevel face → chamfer
20. chamfer_vs_fillet            — chamfer is planar, fillet is curved
21. rib_detected                 — convex planar strip + 2 concave base edges → rib
22. step_detected                — two coplanar faces + riser → step
23. empty_topology_no_features   — empty faces list → ok=True, 0 features
24. garbage_topology_graceful    — non-dict → ok=False, 0 features, no raise
25. feature_tree_ordering        — base features (step) before subtractive (hole)
26. multiple_features_no_overlap — shared faces not double-counted in used set
27. mesh_cluster_input           — face_clusters key accepted as faces
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.afr.recognize import recognize_features, _SLOT_ASPECT_RATIO


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _cyl(fid, radius, axis, convexity="concave", adjacent=None, area=None, centroid=None):
    area = area if area is not None else 2 * math.pi * radius * 10.0  # depth=10
    return {
        "id": fid,
        "type": "cylindrical",
        "normal": axis,
        "radius": radius,
        "area": area,
        "convexity": convexity,
        "adjacent": adjacent or [],
        "centroid": centroid or [0.0, 0.0, 0.0],
    }


def _planar(fid, normal, convexity="flat", adjacent=None, area=100.0, centroid=None, bbox=None):
    f = {
        "id": fid,
        "type": "planar",
        "normal": normal,
        "radius": 0.0,
        "area": area,
        "convexity": convexity,
        "adjacent": adjacent or [],
        "centroid": centroid or [0.0, 0.0, 0.0],
    }
    if bbox is not None:
        f["bbox"] = bbox
    return f


def _toroidal(fid, radius, adjacent=None, centroid=None):
    return {
        "id": fid,
        "type": "toroidal",
        "normal": [0.0, 0.0, 1.0],
        "radius": radius,
        "area": 2 * math.pi * radius * 5.0,
        "convexity": "concave",
        "adjacent": adjacent or [],
        "centroid": centroid or [0.0, 0.0, 0.0],
    }


def _conical(fid, radius, half_angle=45.0, axis=None, adjacent=None, centroid=None):
    return {
        "id": fid,
        "type": "conical",
        "normal": axis or [0.0, 0.0, 1.0],
        "radius": radius,
        "half_angle": half_angle,
        "area": math.pi * radius * radius,
        "convexity": "concave",
        "adjacent": adjacent or [],
        "centroid": centroid or [0.0, 0.0, 0.0],
    }


def _edge(eid, fa, fb, convexity="concave", length=10.0):
    return {
        "id": eid,
        "face_a": fa,
        "face_b": fb,
        "convexity": convexity,
        "length": length,
    }


# ── Fixture: single through-hole (cylinder, no caps) ──────────────────────
def _through_hole_topo(radius=5.0, axis=None):
    axis = axis or [0.0, 0.0, 1.0]
    return {
        "faces": [
            _cyl("cyl1", radius=radius, axis=axis, convexity="concave", adjacent=[]),
        ]
    }


# ── Fixture: blind hole (cylinder + floor cap) ────────────────────────────
def _blind_hole_topo(radius=5.0, depth=15.0):
    area = 2 * math.pi * radius * depth
    cyl = {
        "id": "cyl1",
        "type": "cylindrical",
        "normal": [0.0, 0.0, 1.0],
        "radius": radius,
        "area": area,
        "convexity": "concave",
        "adjacent": ["floor1"],
        "centroid": [0.0, 0.0, 0.0],
    }
    floor = _planar("floor1", normal=[0.0, 0.0, 1.0], adjacent=["cyl1"])
    return {"faces": [cyl, floor]}


# ── Fixture: counterbore ──────────────────────────────────────────────────
def _counterbore_topo(r_bore=10.0, r_drill=5.0):
    step = _planar("step1", normal=[0.0, 0.0, 1.0], adjacent=["bore1", "drill1"])
    bore = _cyl("bore1", radius=r_bore, axis=[0, 0, 1], convexity="concave",
                adjacent=["step1"])
    drill = _cyl("drill1", radius=r_drill, axis=[0, 0, 1], convexity="concave",
                 adjacent=["step1"])
    return {"faces": [step, bore, drill]}


# ── Fixture: countersink ──────────────────────────────────────────────────
def _countersink_topo():
    cone = _conical("cone1", radius=8.0, half_angle=45.0, axis=[0, 0, 1],
                    adjacent=["inner1"])
    inner = _cyl("inner1", radius=3.0, axis=[0, 0, 1], convexity="concave",
                 adjacent=["cone1"])
    return {"faces": [cone, inner]}


# ── Fixture: pocket ───────────────────────────────────────────────────────
def _pocket_topo():
    floor = _planar("fl", normal=[0, 0, 1], area=100.0,
                    adjacent=["w1", "w2", "w3", "w4"])
    walls = [
        _planar(f"w{i}", normal=[math.cos(a), math.sin(a), 0], convexity="concave",
                area=50.0, adjacent=["fl"])
        for i, a in enumerate([0, math.pi/2, math.pi, 3*math.pi/2], 1)
    ]
    edges = [
        _edge(f"e{i}", "fl", f"w{i}", convexity="concave")
        for i in range(1, 5)
    ]
    return {"faces": [floor] + walls, "edges": edges}


# ── Fixture: slot ─────────────────────────────────────────────────────────
def _slot_topo():
    # Floor has bbox with high aspect ratio.
    floor = _planar("fl", normal=[0, 0, 1], area=50.0,
                    adjacent=["w1", "w2"],
                    bbox=[0.0, 0.0, 5.0, 40.0])  # width=5, length=40 → ratio=8
    walls = [
        _planar("w1", normal=[1, 0, 0], convexity="concave", area=40.0, adjacent=["fl"]),
        _planar("w2", normal=[-1, 0, 0], convexity="concave", area=40.0, adjacent=["fl"]),
    ]
    edges = [
        _edge("e1", "fl", "w1", convexity="concave"),
        _edge("e2", "fl", "w2", convexity="concave"),
    ]
    return {"faces": [floor] + walls, "edges": edges}


# ── Fixture: boss ─────────────────────────────────────────────────────────
def _boss_topo(radius=6.0):
    cyl = _cyl("boss_cyl", radius=radius, axis=[0, 0, 1], convexity="convex",
               adjacent=["top1"])
    top = _planar("top1", normal=[0, 0, 1], adjacent=["boss_cyl"])
    return {"faces": [cyl, top]}


# ── Fixture: fillet (toroidal) ────────────────────────────────────────────
def _fillet_toroidal_topo(radius=3.0):
    t = _toroidal("tor1", radius=radius, adjacent=["p1", "p2"])
    p1 = _planar("p1", normal=[0, 0, 1], adjacent=["tor1"])
    p2 = _planar("p2", normal=[1, 0, 0], adjacent=["tor1"])
    return {"faces": [t, p1, p2]}


# ── Fixture: fillet (cylindrical tangent) ────────────────────────────────
def _fillet_cyl_topo(radius=2.0):
    cyl = {
        "id": "fil_cyl",
        "type": "cylindrical",
        "normal": [0.0, 1.0, 0.0],
        "radius": radius,
        # small area: arc_len * cyl_len — keep well below 4*pi*r^2
        "area": 0.5 * math.pi * radius * radius,
        "convexity": "concave",
        "adjacent": ["pa", "pb"],
        "centroid": [0.0, 0.0, 0.0],
    }
    pa = _planar("pa", normal=[0, 0, 1], adjacent=["fil_cyl"])
    pb = _planar("pb", normal=[1, 0, 0], adjacent=["fil_cyl"])
    edges = [
        _edge("e1", "fil_cyl", "pa", convexity="tangent"),
        _edge("e2", "fil_cyl", "pb", convexity="tangent"),
    ]
    return {"faces": [cyl, pa, pb], "edges": edges}


# ── Fixture: chamfer ──────────────────────────────────────────────────────
def _chamfer_topo():
    # 45° bevel between a Z-normal face and an X-normal face
    bevel = _planar("bev", normal=[1/math.sqrt(2), 0, 1/math.sqrt(2)],
                    convexity="flat", adjacent=["top", "side"])
    top = _planar("top", normal=[0, 0, 1], adjacent=["bev"])
    side = _planar("side", normal=[1, 0, 0], adjacent=["bev"])
    return {"faces": [bevel, top, side]}


# ── Fixture: rib ──────────────────────────────────────────────────────────
def _rib_topo():
    rib_face = _planar("rib1", normal=[1, 0, 0], convexity="convex",
                       area=20.0, adjacent=["base1", "base2"])
    base1 = _planar("base1", normal=[0, 0, 1], adjacent=["rib1"])
    base2 = _planar("base2", normal=[0, 0, -1], adjacent=["rib1"])
    edges = [
        _edge("e1", "rib1", "base1", convexity="concave"),
        _edge("e2", "rib1", "base2", convexity="concave"),
    ]
    return {"faces": [rib_face, base1, base2], "edges": edges}


# ── Fixture: step ─────────────────────────────────────────────────────────
def _step_topo():
    # Two Z-normal planars connected by a riser (X-normal planar).
    upper = _planar("up", normal=[0, 0, 1], adjacent=["riser"])
    riser = _planar("riser", normal=[1, 0, 0], adjacent=["up", "lower"])
    lower = _planar("lower", normal=[0, 0, 1], adjacent=["riser"])
    return {"faces": [upper, riser, lower]}


# ── Fixture: combined (step + hole) for tree ordering ────────────────────
def _combined_step_and_hole_topo():
    upper = _planar("up", normal=[0, 0, 1], adjacent=["riser"])
    riser = _planar("riser", normal=[1, 0, 0], adjacent=["up", "lower"])
    lower = _planar("lower", normal=[0, 0, 1], adjacent=["riser"])
    cyl = _cyl("hole_cyl", radius=3.0, axis=[0, 0, 1], convexity="concave", adjacent=[])
    return {"faces": [upper, riser, lower, cyl]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# 1. Block with one through-hole
def test_block_with_one_through_hole():
    result = recognize_features(_through_hole_topo())
    assert result["ok"] is True
    holes = [f for f in result["features"] if f["type"] == "through_hole"]
    assert len(holes) == 1


# 2. Through-hole diameter
def test_through_hole_diameter():
    result = recognize_features(_through_hole_topo(radius=7.5))
    hole = next(f for f in result["features"] if f["type"] == "through_hole")
    assert abs(hole["params"]["diameter"] - 15.0) < 0.01


# 3. Through-hole axis Z
def test_through_hole_axis_z():
    result = recognize_features(_through_hole_topo(radius=5.0, axis=[0.0, 0.0, 1.0]))
    hole = next(f for f in result["features"] if f["type"] == "through_hole")
    ax = hole["params"]["axis"]
    assert abs(ax[0]) < 0.01 and abs(ax[1]) < 0.01 and abs(ax[2]) - 1.0 < 0.01


# 4. Through-hole axis X
def test_through_hole_axis_x():
    result = recognize_features(_through_hole_topo(radius=4.0, axis=[1.0, 0.0, 0.0]))
    hole = next(f for f in result["features"] if f["type"] == "through_hole")
    ax = hole["params"]["axis"]
    assert abs(ax[0]) - 1.0 < 0.01 and abs(ax[1]) < 0.01 and abs(ax[2]) < 0.01


# 5. Blind hole detected when floor cap present
def test_blind_hole_floor_face():
    result = recognize_features(_blind_hole_topo())
    blind = [f for f in result["features"] if f["type"] == "blind_hole"]
    through = [f for f in result["features"] if f["type"] == "through_hole"]
    assert len(blind) == 1
    assert len(through) == 0


# 6. Blind hole has positive depth
def test_blind_hole_has_depth():
    result = recognize_features(_blind_hole_topo(depth=15.0))
    blind = next(f for f in result["features"] if f["type"] == "blind_hole")
    assert blind["params"]["depth"] > 0.0


# 7. Cylinder with 2 cap faces → through-hole (entry/exit caps)
def test_through_hole_two_caps():
    r = 5.0
    area = 2 * math.pi * r * 10.0
    cyl = {
        "id": "c1", "type": "cylindrical", "normal": [0, 0, 1],
        "radius": r, "area": area, "convexity": "concave",
        "adjacent": ["cap_top", "cap_bot"], "centroid": [0, 0, 0],
    }
    cap_top = _planar("cap_top", normal=[0, 0, 1], adjacent=["c1"])
    cap_bot = _planar("cap_bot", normal=[0, 0, -1], adjacent=["c1"])
    result = recognize_features({"faces": [cyl, cap_top, cap_bot]})
    through = [f for f in result["features"] if f["type"] == "through_hole"]
    assert len(through) == 1


# 8. Counterbore detected
def test_counterbore_detected():
    result = recognize_features(_counterbore_topo())
    cb = [f for f in result["features"] if f["type"] == "counterbore"]
    assert len(cb) == 1


# 9. Counterbore bore_diameter > drill_diameter
def test_counterbore_bore_gt_drill():
    result = recognize_features(_counterbore_topo(r_bore=10.0, r_drill=5.0))
    cb = next(f for f in result["features"] if f["type"] == "counterbore")
    assert cb["params"]["bore_diameter"] > cb["params"]["drill_diameter"]


# 10. Countersink detected from conical face
def test_countersink_detected():
    result = recognize_features(_countersink_topo())
    cs = [f for f in result["features"] if f["type"] == "countersink"]
    assert len(cs) == 1


# 11. Pocket detected
def test_pocket_detected():
    result = recognize_features(_pocket_topo())
    pockets = [f for f in result["features"] if f["type"] == "pocket"]
    assert len(pockets) >= 1


# 12. Pocket wall count matches fixture (4 walls)
def test_pocket_wall_count():
    result = recognize_features(_pocket_topo())
    pocket = next(f for f in result["features"] if f["type"] == "pocket")
    assert pocket["params"]["wall_count"] == 4


# 13. Slot detected for high-aspect floor
def test_slot_detected():
    result = recognize_features(_slot_topo())
    slots = [f for f in result["features"] if f["type"] == "slot"]
    assert len(slots) >= 1


# 14. Slot length >= SLOT_ASPECT_RATIO * width
def test_slot_aspect():
    result = recognize_features(_slot_topo())
    slot = next(f for f in result["features"] if f["type"] == "slot")
    w = slot["params"]["width"]
    l = slot["params"]["length"]
    assert w > 0
    assert l / w >= _SLOT_ASPECT_RATIO - 0.01


# 15. Boss detected for convex cylinder
def test_boss_detected():
    result = recognize_features(_boss_topo())
    bosses = [f for f in result["features"] if f["type"] == "boss"]
    assert len(bosses) == 1


# 16. Convex cylinder → boss, concave cylinder → hole (not boss)
def test_boss_vs_pocket_by_convexity():
    boss_r = recognize_features(_boss_topo())
    hole_r = recognize_features(_through_hole_topo())
    assert any(f["type"] == "boss" for f in boss_r["features"])
    assert not any(f["type"] == "boss" for f in hole_r["features"])
    assert any(f["type"] == "through_hole" for f in hole_r["features"])
    assert not any(f["type"] == "through_hole" for f in boss_r["features"])


# 17. Toroidal face → fillet
def test_fillet_toroidal():
    result = recognize_features(_fillet_toroidal_topo(radius=3.0))
    fillets = [f for f in result["features"] if f["type"] == "fillet"]
    assert len(fillets) >= 1


# 18. Fillet radius matches fixture
def test_fillet_radius():
    result = recognize_features(_fillet_toroidal_topo(radius=4.5))
    fillet = next(f for f in result["features"] if f["type"] == "fillet")
    assert abs(fillet["params"]["radius"] - 4.5) < 0.01


# 19. Chamfer detected
def test_chamfer_detected():
    result = recognize_features(_chamfer_topo())
    chamfers = [f for f in result["features"] if f["type"] == "chamfer"]
    assert len(chamfers) >= 1


# 20. Chamfer vs fillet distinguished (chamfer has no radius param; fillet does)
def test_chamfer_vs_fillet():
    ch = recognize_features(_chamfer_topo())
    fi = recognize_features(_fillet_toroidal_topo())
    chamfer_feat = next((f for f in ch["features"] if f["type"] == "chamfer"), None)
    fillet_feat = next((f for f in fi["features"] if f["type"] == "fillet"), None)
    assert chamfer_feat is not None
    assert fillet_feat is not None
    # Fillet has radius; chamfer does not.
    assert "radius" in fillet_feat["params"]
    assert "radius" not in chamfer_feat["params"]


# 21. Rib detected
def test_rib_detected():
    result = recognize_features(_rib_topo())
    ribs = [f for f in result["features"] if f["type"] == "rib"]
    assert len(ribs) >= 1


# 22. Step detected
def test_step_detected():
    result = recognize_features(_step_topo())
    steps = [f for f in result["features"] if f["type"] == "step"]
    assert len(steps) >= 1


# 23. Empty topology → ok=True, 0 features
def test_empty_topology_no_features():
    result = recognize_features({"faces": []})
    assert result["ok"] is True
    assert result["features"] == []


# 24. Garbage topology → ok=False, no exception
def test_garbage_topology_graceful():
    result = recognize_features("not a dict")
    assert result["ok"] is False
    assert result["features"] == []
    assert isinstance(result["reason"], str)


# 25. Feature tree: steps ordered before holes
def test_feature_tree_ordering():
    result = recognize_features(_combined_step_and_hole_topo())
    tree = result["feature_tree"]
    assert len(tree) >= 2
    types = [t["type"] for t in tree]
    # Step should appear before through_hole in the ordered tree.
    if "step" in types and "through_hole" in types:
        assert types.index("step") < types.index("through_hole")


# 26. Multiple features — used set prevents double-counting
def test_multiple_features_no_overlap():
    # Two independent through-holes.
    topo = {
        "faces": [
            _cyl("h1", radius=3.0, axis=[0, 0, 1], convexity="concave", adjacent=[]),
            _cyl("h2", radius=5.0, axis=[0, 0, 1], convexity="concave", adjacent=[]),
        ]
    }
    result = recognize_features(topo)
    holes = [f for f in result["features"] if f["type"] == "through_hole"]
    assert len(holes) == 2
    # No face_id appears in more than one feature.
    all_ids = [fid for f in result["features"] for fid in f["face_ids"]]
    assert len(all_ids) == len(set(all_ids))


# 27. Mesh-cluster input accepted via face_clusters key
def test_mesh_cluster_input():
    topo = {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        "triangles": [[0, 1, 2]],
        "face_clusters": [
            _cyl(0, radius=4.0, axis=[0, 0, 1], convexity="concave", adjacent=[]),
        ],
    }
    result = recognize_features(topo)
    assert result["ok"] is True
    holes = [f for f in result["features"] if f["type"] == "through_hole"]
    assert len(holes) == 1
