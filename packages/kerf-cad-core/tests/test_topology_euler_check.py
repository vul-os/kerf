"""Hermetic tests for topology_euler_check.py.

Oracle cases derived from Mantyla 1988 §6 and Hoffmann 1989 §5.

Tests
-----
 1. Closed cube (dict): V=8, E=12, F=6 → χ=2  ✓  (Mantyla §6 canonical example)
 2. Torus (dict with genus_hint=1, shells_hint=1): V=0, E=2, F=2 → χ=0  ✓
 3. Box with inner loops (H=2): expected_chi=2*(1-0)+2=4  ✓
 4. Disjoint cubes (dict, 2 disconnected sets): S=2 → χ=4  ✓
 5. Face with inner loop H=1: expected_chi=3; actual=2 → valid=False
 6. Invalid topology (wrong genus_hint) → valid=False with violation message
 7. EulerCheckReport flag semantics
 8. verify_euler_topology(Body) — cube Body object path  ✓
 9. verify_euler_topology(Body) — torus Body: formula self-consistent  ✓
10. Empty face list → valid=False, violations non-empty
11. Mantyla oracle: sphere topology-equivalent to cube → χ=2 ✓
12. Torus with explicit shells_hint=1, genus_hint=1 → expected_chi=0  ✓
13. union-find cube: 1 component
14. union-find disjoint cubes: 2 components
15. Disjoint cubes via Body object: S=2, χ=4
16. as_dict() contains all required keys
"""

from __future__ import annotations

import pytest

from kerf_cad_core.geom.topology_euler_check import (
    EulerCheckReport,
    _count_shells_union_find,
    _make_cube_body,
    _make_disjoint_cubes_body,
    _make_torus_body,
    verify_euler_topology,
    verify_euler_topology_from_dict,
)


# ---------------------------------------------------------------------------
# Helpers — dict-format face builders
# ---------------------------------------------------------------------------

def _cube_faces_dict():
    """Canonical 6-face cube: 8 vertices, 12 edges."""
    faces = [
        # bottom z=0
        {"face_id": "f_bot", "edges": [
            {"edge_id": "e_bot_0", "start": "v000", "end": "v100"},
            {"edge_id": "e_bot_1", "start": "v100", "end": "v110"},
            {"edge_id": "e_bot_2", "start": "v110", "end": "v010"},
            {"edge_id": "e_bot_3", "start": "v010", "end": "v000"},
        ]},
        # top z=1
        {"face_id": "f_top", "edges": [
            {"edge_id": "e_top_0", "start": "v001", "end": "v101"},
            {"edge_id": "e_top_1", "start": "v101", "end": "v111"},
            {"edge_id": "e_top_2", "start": "v111", "end": "v011"},
            {"edge_id": "e_top_3", "start": "v011", "end": "v001"},
        ]},
        # front y=0
        {"face_id": "f_front", "edges": [
            {"edge_id": "e_bot_0",   "start": "v000", "end": "v100"},
            {"edge_id": "e_front_1", "start": "v100", "end": "v101"},
            {"edge_id": "e_top_0",   "start": "v101", "end": "v001"},
            {"edge_id": "e_front_3", "start": "v001", "end": "v000"},
        ]},
        # back y=1
        {"face_id": "f_back", "edges": [
            {"edge_id": "e_bot_2",  "start": "v110", "end": "v010"},
            {"edge_id": "e_back_1", "start": "v010", "end": "v011"},
            {"edge_id": "e_top_2",  "start": "v011", "end": "v111"},
            {"edge_id": "e_back_3", "start": "v111", "end": "v110"},
        ]},
        # left x=0
        {"face_id": "f_left", "edges": [
            {"edge_id": "e_bot_3",   "start": "v010", "end": "v000"},
            {"edge_id": "e_front_3", "start": "v000", "end": "v001"},
            {"edge_id": "e_top_3",   "start": "v001", "end": "v011"},
            {"edge_id": "e_back_1",  "start": "v011", "end": "v010"},
        ]},
        # right x=1
        {"face_id": "f_right", "edges": [
            {"edge_id": "e_bot_1",   "start": "v100", "end": "v110"},
            {"edge_id": "e_back_3",  "start": "v110", "end": "v111"},
            {"edge_id": "e_top_1",   "start": "v111", "end": "v101"},
            {"edge_id": "e_front_1", "start": "v101", "end": "v100"},
        ]},
    ]
    return faces


def _torus_faces_dict():
    """Minimal torus dict: V=0, E=2, F=2 (no vertex labels on edges).

    A true Mantyla torus has no vertices — both seam curves are fully closed
    (no endpoints). Omitting 'start'/'end' from edge dicts makes V=0.
    """
    return [
        {"face_id": "f_torus_0", "edges": [
            {"edge_id": "e_longitude"},
        ]},
        {"face_id": "f_torus_1", "edges": [
            {"edge_id": "e_meridian"},
        ]},
    ]


def _disjoint_two_cubes_dict():
    """Two disconnected cubes: 16 vertices, 24 edges, 12 faces, S=2."""
    c1 = _cube_faces_dict()
    c2 = []
    for face in _cube_faces_dict():
        c2.append({
            "face_id": "B_" + face["face_id"],
            "edges": [
                {
                    "edge_id": "B_" + e["edge_id"],
                    "start": "B_" + e["start"],
                    "end": "B_" + e["end"],
                }
                for e in face["edges"]
            ],
        })
    return c1 + c2


# ---------------------------------------------------------------------------
# Test 1: Cube dict — V=8, E=12, F=6, S=1, G=0, H=0 → χ=2
# ---------------------------------------------------------------------------

def test_cube_dict_chi_equals_2():
    """Unit cube V-E+F = 8-12+6 = 2. (Mantyla §6 canonical example.)"""
    faces = _cube_faces_dict()
    r = verify_euler_topology_from_dict(faces)
    assert r.V == 8, f"Expected V=8, got {r.V}"
    assert r.E == 12, f"Expected E=12, got {r.E}"
    assert r.F == 6, f"Expected F=6, got {r.F}"
    assert r.actual_chi == 2, f"Expected χ=2, got {r.actual_chi}"
    assert r.S == 1, f"Expected S=1, got {r.S}"
    assert r.valid is True, f"Expected valid=True, violations={r.violations}"


# ---------------------------------------------------------------------------
# Test 2: Torus dict — V=0, E=2, F=2, S=1, G=1 → χ=0
# ---------------------------------------------------------------------------

def test_torus_dict_chi_equals_0():
    """Torus: V=0, E=2, F=2, S=1, G=1 → actual_chi = 0-2+2 = 0. (Hoffmann §5.)

    shells_hint=1 is required because the two faces share no edge in the
    dict (each has a distinct seam edge), so union-find would count 2 shells.
    """
    faces = _torus_faces_dict()
    r = verify_euler_topology_from_dict(faces, genus_hint=1, shells_hint=1)
    assert r.V == 0, f"Expected V=0, got {r.V}"
    assert r.E == 2, f"Expected E=2, got {r.E}"
    assert r.F == 2, f"Expected F=2, got {r.F}"
    assert r.G == 1, f"Expected G=1, got {r.G}"
    assert r.S == 1, f"Expected S=1, got {r.S}"
    assert r.actual_chi == 0, f"Expected actual_chi=0, got {r.actual_chi}"
    assert r.expected_chi == 0, f"Expected expected_chi=0, got {r.expected_chi}"
    assert r.valid is True, f"Expected valid=True, violations={r.violations}"


# ---------------------------------------------------------------------------
# Test 3: Box with inner loops H=2 — expected_chi = 2*(1-0)+2 = 4
# ---------------------------------------------------------------------------

def test_inner_loops_h2_expected_chi():
    """Cube dict + inner_loops_hint=2: expected_chi = 2*(1-0)+2 = 4.

    This models a box with two faces each containing an inner loop (e.g. a
    box with two blind holes on opposite faces), following Mantyla §6.2.
    The actual_chi is still 2 (cube V-E+F), so valid=False — the body needs
    more vertices/edges to be topologically consistent with 2 inner loops.
    """
    faces = _cube_faces_dict()
    r = verify_euler_topology_from_dict(faces, shells_hint=1, inner_loops_hint=2)
    assert r.H == 2
    assert r.expected_chi == 2 * (1 - 0) + 2  # = 4
    # actual_chi=2 ≠ 4 → invalid
    assert r.actual_chi == 2
    assert r.valid is False


# ---------------------------------------------------------------------------
# Test 4: Disjoint cubes — S=2, χ=4
# ---------------------------------------------------------------------------

def test_disjoint_cubes_chi_equals_4():
    """Two disconnected cubes: S=2, V=16, E=24, F=12 → χ=4=2*2."""
    faces = _disjoint_two_cubes_dict()
    r = verify_euler_topology_from_dict(faces)
    assert r.V == 16, f"Expected V=16, got {r.V}"
    assert r.E == 24, f"Expected E=24, got {r.E}"
    assert r.F == 12, f"Expected F=12, got {r.F}"
    assert r.S == 2, f"Expected S=2, got {r.S}"
    assert r.actual_chi == 4, f"Expected χ=4, got {r.actual_chi}"
    assert r.expected_chi == 4, f"Expected expected_chi=4, got {r.expected_chi}"
    assert r.valid is True, f"Expected valid=True, violations={r.violations}"


# ---------------------------------------------------------------------------
# Test 5: H=1 causes mismatch → valid=False
# ---------------------------------------------------------------------------

def test_face_with_inner_loop_h1_invalid():
    """Cube + inner_loops_hint=1: expected_chi=3 but actual=2 → valid=False."""
    faces = _cube_faces_dict()
    r = verify_euler_topology_from_dict(faces, inner_loops_hint=1, shells_hint=1)
    assert r.H == 1
    assert r.expected_chi == 3
    assert r.actual_chi == 2
    assert r.valid is False


# ---------------------------------------------------------------------------
# Test 6: Wrong genus_hint → valid=False with violation message
# ---------------------------------------------------------------------------

def test_invalid_topology_violates_formula():
    """Cube with genus_hint=1 → expected=0 ≠ actual=2 → valid=False."""
    faces = _cube_faces_dict()
    r = verify_euler_topology_from_dict(faces, genus_hint=1)
    assert r.valid is False
    assert any("Euler-Poincaré violated" in v for v in r.violations), r.violations


# ---------------------------------------------------------------------------
# Test 7: EulerCheckReport flag semantics
# ---------------------------------------------------------------------------

def test_euler_check_report_valid_flag():
    """EulerCheckReport.valid is False when actual_chi != expected_chi."""
    r = EulerCheckReport(
        V=8, E=12, F=6, S=1, H=0, G=0,
        actual_chi=2, expected_chi=0,
        valid=False,
        violations=["Euler-Poincaré violated: V-E+F=2 but 2*(1-1)+0=0"],
    )
    assert r.valid is False
    assert len(r.violations) == 1

    r2 = EulerCheckReport(
        V=8, E=12, F=6, S=1, H=0, G=0,
        actual_chi=2, expected_chi=2,
        valid=True,
    )
    assert r2.valid is True
    assert r2.violations == []


# ---------------------------------------------------------------------------
# Test 8: verify_euler_topology(Body) — cube Body
# ---------------------------------------------------------------------------

def test_body_cube_euler():
    """Body cube: V=8, E=12, F=6 → χ=2. (Mantyla §6 canonical example.)"""
    body = _make_cube_body()
    r = verify_euler_topology(body)
    assert r.V == 8, f"V={r.V}"
    assert r.E == 12, f"E={r.E}"
    assert r.F == 6, f"F={r.F}"
    assert r.actual_chi == 2, f"χ={r.actual_chi}"
    assert r.valid is True, f"valid=False, violations={r.violations}"


# ---------------------------------------------------------------------------
# Test 9: verify_euler_topology(Body) — torus Body (formula self-consistent)
# ---------------------------------------------------------------------------

def test_body_torus_euler_self_consistent():
    """Body torus: V=1, E=2, F=1, G=1 → actual_chi = 0. (Mantyla §6.2.)

    The canonical Mantyla torus has ONE face bounded by the commutator loop
    a·b·a⁻¹·b⁻¹.  Counts: V=1, E=2, F=1, S=1, G=1, H=0.

    actual_chi  = V-E+F = 1-2+1 = 0
    expected_chi = 2*(S-G)+H = 2*(1-1)+0 = 0   ✓ valid=True
    """
    body = _make_torus_body()
    r = verify_euler_topology(body)
    assert r.V == 1, f"V={r.V}"
    assert r.E == 2, f"E={r.E}"
    assert r.F == 1, f"F={r.F}"
    assert r.G == 1, f"G={r.G}"
    assert r.actual_chi == 0, f"actual_chi={r.actual_chi}"
    assert r.expected_chi == 0, f"expected_chi={r.expected_chi}"
    assert r.valid is True, (
        f"Torus body Euler check failed: V={r.V} E={r.E} F={r.F} "
        f"G={r.G} H={r.H} S={r.S} actual={r.actual_chi} "
        f"expected={r.expected_chi} violations={r.violations}"
    )


# ---------------------------------------------------------------------------
# Test 10: Empty face list → valid=False
# ---------------------------------------------------------------------------

def test_empty_faces_invalid():
    """Empty face list must return valid=False with a non-empty violations list."""
    r = verify_euler_topology_from_dict([])
    assert r.valid is False
    assert len(r.violations) > 0


# ---------------------------------------------------------------------------
# Test 11: Sphere topology-equivalent to cube (Mantyla §6.1)
# ---------------------------------------------------------------------------

def test_sphere_topology_equivalent_to_cube():
    """A sphere and a cube are topologically identical: χ=2.

    All genus-0 closed solids satisfy χ=2 (Mantyla 1988 §6.1).
    """
    faces = _cube_faces_dict()
    r = verify_euler_topology_from_dict(faces)
    assert r.actual_chi == 2
    assert r.G == 0
    assert r.S == 1
    assert r.valid is True


# ---------------------------------------------------------------------------
# Test 12: Torus with shells_hint=1, genus_hint=1 (Hoffmann §5)
# ---------------------------------------------------------------------------

def test_torus_dict_explicit_hints():
    """Torus dict: shells_hint=1, genus_hint=1 → expected_chi=0. (Hoffmann §5.)"""
    faces = _torus_faces_dict()
    r = verify_euler_topology_from_dict(faces, genus_hint=1, shells_hint=1)
    assert r.S == 1
    assert r.G == 1
    assert r.expected_chi == 0
    assert r.valid is True, f"violations={r.violations}"


# ---------------------------------------------------------------------------
# Tests 13-14: _count_shells_union_find
# ---------------------------------------------------------------------------

def test_count_shells_union_find_cube():
    """Union-find identifies 1 shell component for a cube."""
    faces = _cube_faces_dict()
    s = _count_shells_union_find(faces, len(faces))
    assert s == 1


def test_count_shells_union_find_disjoint():
    """Union-find identifies 2 components for two disjoint cubes."""
    faces = _disjoint_two_cubes_dict()
    s = _count_shells_union_find(faces, len(faces))
    assert s == 2


# ---------------------------------------------------------------------------
# Test 15: Disjoint cubes via Body object
# ---------------------------------------------------------------------------

def test_body_disjoint_cubes():
    """Two disjoint cubes Body: S=2, χ=4=2*S."""
    body = _make_disjoint_cubes_body()
    r = verify_euler_topology(body)
    assert r.S == 2, f"S={r.S}"
    assert r.actual_chi == 4, f"χ={r.actual_chi}"
    assert r.valid is True, f"violations={r.violations}"


# ---------------------------------------------------------------------------
# Test 16: as_dict() serialisation
# ---------------------------------------------------------------------------

def test_euler_check_report_as_dict():
    """EulerCheckReport.as_dict() contains all required keys."""
    faces = _cube_faces_dict()
    r = verify_euler_topology_from_dict(faces)
    d = r.as_dict()
    required_keys = (
        "V", "E", "F", "S", "H", "G",
        "actual_chi", "expected_chi", "valid",
        "violations", "degenerate_vertices_hint",
    )
    for key in required_keys:
        assert key in d, f"Missing key '{key}' in as_dict()"
