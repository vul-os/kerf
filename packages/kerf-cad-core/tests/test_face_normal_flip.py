"""
tests/test_face_normal_flip.py
==============================
Tests for BREP-EDGE-FACE-NORMAL-FLIP: kerf_cad_core.geom.face_normal_flip

NOTE on geometry: Adjacent faces of a unit cube have perpendicular normals
(dot=0), so a cube is NOT a suitable test geometry for this algorithm.
We use geometries where adjacent face normals are non-perpendicular:
  - flat panels (same normal) → trivial
  - pyramid fans (adjacent normals at ~45 deg angles, dot = cos45 ≈ 0.71)
  - sphere octants (adjacent normals at 60 deg, dot = cos60 = 0.5)
  - linear face strips (normals tilted 45 deg between neighbours)

Tests (16 total):
  1.  strip_one_inverted       — strip of 5 faces, 1 inverted → flips it
  2.  strip_all_correct        — strip of 5 all correct → 0 flips
  3.  all_same_direction       — all faces same normal (all "co-oriented") →
                                  algorithm propagates anti-parallel from seed
  4.  empty_input              — empty list → empty result
  5.  single_isolated_face     — 1 face, no neighbours → 0 flips
  6.  two_faces_co_oriented    — 2 adjacent faces with same normal → 1 flip
  7.  two_faces_anti_parallel  — 2 adjacent faces anti-parallel → 0 flips
  8.  consensus_score_good     — after fix, score ≥ 0.9
  9.  result_dataclass_fields  — all 5 required fields present + correct types
  10. flipped_indices_correct  — returned indices match actually-flipped faces
  11. normals_are_unit_vectors — unnormalised input → unit output
  12. disconnected_components  — two separate fans, each with one bad face → both fixed
  13. zero_normal_fallback     — face with (0,0,0) normal → no crash
  14. max_iter_one_no_crash    — max_iter=1 terminates cleanly
  15. ring_one_inverted        — ring of 4 faces, 1 inverted → flipped
  16. output_length_matches    — |face_normals_after| == |input|
"""

from __future__ import annotations

import math
from typing import List, Dict

import pytest

from kerf_cad_core.geom.face_normal_flip import (
    FaceNormalFlipResult,
    detect_and_flip_face_normals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(v):
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    mag = math.sqrt(x * x + y * y + z * z)
    if mag < 1e-14:
        return (0.0, 0.0, 1.0)
    return (x / mag, y / mag, z / mag)


def _dot(a, b):
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


# ---------------------------------------------------------------------------
# Test geometry helpers
# ---------------------------------------------------------------------------

def _pyramid_fan_faces(n: int = 5, invert_index: int = -1) -> List[Dict]:
    """Build a fan of n faces around a common apex, each pointing outward.

    Faces are like octants of a pyramid: normals fan around in the XY plane
    with a slight positive Z component, so adjacent normals have
    dot > threshold (non-perpendicular).

    For n=5, angles are: 0°, 36°, 72°, 108°, 144° → adjacent dot ≈ cos(36°) ≈ 0.81.
    Face i is adjacent to face (i-1) and face (i+1) (linear chain, not ring).

    If invert_index >= 0, that face's normal is negated.
    """
    faces = []
    angle_step = math.pi / max(n - 1, 1)
    for i in range(n):
        angle = i * angle_step
        # Fan outward in +Z hemisphere, spread in XY plane.
        nx = math.cos(angle)
        ny = math.sin(angle)
        nz = 0.5  # slight upward tilt
        norm = _unit((nx, ny, nz))
        if i == invert_index:
            norm = (-norm[0], -norm[1], -norm[2])
        adj = []
        if i > 0:
            adj.append(i - 1)
        if i < n - 1:
            adj.append(i + 1)
        faces.append({"normal": list(norm), "neighbor_face_indices": adj})
    return faces


def _linear_strip_faces(n: int = 5, invert_index: int = -1) -> List[Dict]:
    """Build a linear strip of n faces, each tilted 30° from the previous.

    Face i normal: (sin(i*30°), 0, cos(i*30°))
    Adjacent dot = cos(30°) ≈ 0.87.
    Linear adjacency: face i adjacent to i-1 and i+1.
    """
    faces = []
    tilt_step = math.radians(30.0)
    for i in range(n):
        angle = i * tilt_step
        norm = _unit((math.sin(angle), 0.0, math.cos(angle)))
        if i == invert_index:
            norm = (-norm[0], -norm[1], -norm[2])
        adj = []
        if i > 0:
            adj.append(i - 1)
        if i < n - 1:
            adj.append(i + 1)
        faces.append({"normal": list(norm), "neighbor_face_indices": adj})
    return faces


# ---------------------------------------------------------------------------
# Test 1: strip of 5 faces, 1 inverted → flips exactly that one
# ---------------------------------------------------------------------------

def test_strip_one_inverted_flips_exactly_one():
    """5-face linear strip, face 2 inverted → algorithm flips exactly face 2.

    The strip has normals tilted at 30° steps; adjacent correct-pair dot ≈ cos30° ≈ 0.87.
    When face 2 is inverted, dot(face1, face2_inverted) ≈ -0.87 < -threshold → detected.
    """
    faces = _linear_strip_faces(5, invert_index=2)

    # Verify the setup: after inversion, face 2 should be anti-parallel to face 1.
    d12 = _dot(faces[1]["normal"], faces[2]["normal"])
    assert d12 < -0.1, f"Setup error: inverted face 2 should be anti-parallel to face 1, got dot={d12}"

    result = detect_and_flip_face_normals(faces)

    assert isinstance(result, FaceNormalFlipResult)
    assert result.num_faces_flipped == 1, (
        f"Expected 1 flip, got {result.num_faces_flipped}. "
        f"Flipped: {result.flipped_face_indices}"
    )
    assert 2 in result.flipped_face_indices, (
        f"Face 2 should be flipped; flipped={result.flipped_face_indices}"
    )


# ---------------------------------------------------------------------------
# Test 2: strip all correct → 0 flips
# ---------------------------------------------------------------------------

def test_strip_all_correct_no_flips():
    """5-face linear strip, all correctly oriented → 0 flips."""
    faces = _linear_strip_faces(5, invert_index=-1)
    result = detect_and_flip_face_normals(faces)
    assert result.num_faces_flipped == 0, (
        f"Expected 0 flips, got {result.num_faces_flipped}. "
        f"Flipped: {result.flipped_face_indices}"
    )
    assert result.flipped_face_indices == []


# ---------------------------------------------------------------------------
# Test 3: all faces same direction (all "co-oriented") → algorithm propagates
#          from seed, flipping each face as it BFS to be anti-parallel to seed.
# ---------------------------------------------------------------------------

def test_all_same_direction_is_consistent_no_flips():
    """5 faces in a linear chain, all pointing (0,0,1) — an open flat mesh.

    With the convex-surface algorithm:
      - Adjacent dot = +1.0 > 0 → no flip (co-oriented is the CORRECT state for
        a flat mesh; the algorithm only flips when dot < -threshold).
    All 5 faces should remain at (0,0,1), 0 flips, consensus_score = 1.0.
    """
    faces = [
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [1]},
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [0, 2]},
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [1, 3]},
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [2, 4]},
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [3]},
    ]
    result = detect_and_flip_face_normals(faces)
    assert result.num_faces_flipped == 0, (
        f"Flat mesh with consistent normals should have 0 flips, "
        f"got {result.num_faces_flipped}"
    )
    assert result.consensus_score == 1.0


# ---------------------------------------------------------------------------
# Test 4: empty input → empty result
# ---------------------------------------------------------------------------

def test_empty_input():
    result = detect_and_flip_face_normals([])
    assert result.face_normals_after == []
    assert result.num_faces_flipped == 0
    assert result.flipped_face_indices == []
    assert result.consensus_score == 1.0
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 5: single isolated face → 0 flips, caveat mentions isolated
# ---------------------------------------------------------------------------

def test_single_isolated_face_no_flip():
    faces = [{"normal": (0, 0, 1), "neighbor_face_indices": []}]
    result = detect_and_flip_face_normals(faces)
    assert result.num_faces_flipped == 0
    assert result.flipped_face_indices == []
    assert len(result.face_normals_after) == 1
    assert "isolated" in result.honest_caveat.lower() or "Isolated" in result.honest_caveat


# ---------------------------------------------------------------------------
# Test 6: two adjacent faces, co-oriented → one gets flipped
# ---------------------------------------------------------------------------

def test_two_faces_co_oriented_no_flip():
    """Two adjacent faces with the same normal: both co-oriented → 0 flips.

    With the convex-surface algorithm: co-oriented is the EXPECTED state
    (dot > 0 → no flip triggered).  Two flat panels side-by-side with the
    same outward normal are correctly oriented for an open flat mesh.
    """
    faces = [
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [1]},
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [0]},
    ]
    result = detect_and_flip_face_normals(faces)
    assert result.num_faces_flipped == 0, (
        f"Expected 0 flips for co-oriented pair (flat mesh), got {result.num_faces_flipped}"
    )


# ---------------------------------------------------------------------------
# Test 7: two adjacent faces, already anti-parallel → 0 flips
# ---------------------------------------------------------------------------

def test_two_faces_anti_parallel_one_flip():
    """Two adjacent faces with opposite normals: anti-parallel → face 1 is inverted.

    With the convex-surface algorithm: dot(n0, n1) = -1.0 < -threshold → flip face 1.
    After fix: face 1 flipped to (0,0,1), both co-oriented.
    """
    faces = [
        {"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": [1]},
        {"normal": [0.0, 0.0, -1.0], "neighbor_face_indices": [0]},
    ]
    result = detect_and_flip_face_normals(faces)
    assert result.num_faces_flipped == 1, (
        f"Expected 1 flip for anti-parallel pair (face 1 inverted), got {result.num_faces_flipped}"
    )
    assert 1 in result.flipped_face_indices


# ---------------------------------------------------------------------------
# Test 8: consensus_score >= 0.9 after fixing a strip with one bad face
# ---------------------------------------------------------------------------

def test_consensus_score_high_after_fix():
    """After fixing a fan with one bad face, consensus_score should be >= 0.9."""
    faces = _pyramid_fan_faces(5, invert_index=3)
    result = detect_and_flip_face_normals(faces)
    assert result.consensus_score >= 0.9, (
        f"Expected high consensus after fix, got {result.consensus_score}. "
        f"Flipped: {result.flipped_face_indices}"
    )


# ---------------------------------------------------------------------------
# Test 9: FaceNormalFlipResult has all 5 required fields
# ---------------------------------------------------------------------------

def test_result_dataclass_fields():
    """The result dataclass must expose all 5 required fields with correct types."""
    faces = _linear_strip_faces(3)
    result = detect_and_flip_face_normals(faces)
    assert hasattr(result, "face_normals_after")
    assert hasattr(result, "num_faces_flipped")
    assert hasattr(result, "flipped_face_indices")
    assert hasattr(result, "consensus_score")
    assert hasattr(result, "honest_caveat")

    assert isinstance(result.face_normals_after, list)
    assert isinstance(result.num_faces_flipped, int)
    assert isinstance(result.flipped_face_indices, list)
    assert isinstance(result.consensus_score, float)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 10: flipped_face_indices correctly identifies which face was flipped
# ---------------------------------------------------------------------------

def test_flipped_indices_correct():
    """Inverting face 4 in a 5-face strip → 4 in flipped_face_indices."""
    faces = _linear_strip_faces(5, invert_index=4)
    result = detect_and_flip_face_normals(faces)
    assert 4 in result.flipped_face_indices, (
        f"Face 4 should be in flipped_face_indices, got {result.flipped_face_indices}"
    )
    assert result.num_faces_flipped == len(result.flipped_face_indices)


# ---------------------------------------------------------------------------
# Test 11: unnormalised input → unit-length output normals
# ---------------------------------------------------------------------------

def test_output_normals_are_unit_vectors():
    """Output normals must be unit vectors regardless of input magnitude."""
    faces = [
        {"normal": [10.0, 0.0, 0.0], "neighbor_face_indices": [1]},
        {"normal": [0.0, 0.0, -5.0], "neighbor_face_indices": [0]},
    ]
    result = detect_and_flip_face_normals(faces)
    for i, n in enumerate(result.face_normals_after):
        mag = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
        assert abs(mag - 1.0) < 1e-10, (
            f"Output normal {i} is not unit length: {n}, |n|={mag}"
        )


# ---------------------------------------------------------------------------
# Test 12: disconnected components — two separate fans, each with 1 bad face
# ---------------------------------------------------------------------------

def test_disconnected_components_both_fixed():
    """Two disjoint 5-face fans, each with one inverted face → both fixed."""
    # Component A: faces 0..4 (pyramid fan, invert face 2)
    faces_a = _pyramid_fan_faces(5, invert_index=2)

    # Component B: faces 5..9 (shifted index, invert face 2 → absolute index 7)
    faces_b_raw = _pyramid_fan_faces(5, invert_index=2)
    faces_b = []
    for i, f in enumerate(faces_b_raw):
        new_adj = [j + 5 for j in f["neighbor_face_indices"]]
        faces_b.append({"normal": f["normal"], "neighbor_face_indices": new_adj})

    faces = faces_a + faces_b
    result = detect_and_flip_face_normals(faces)

    assert result.num_faces_flipped == 2, (
        f"Expected 2 flips (one per component), got {result.num_faces_flipped}. "
        f"Flipped: {result.flipped_face_indices}"
    )
    assert 2 in result.flipped_face_indices, "Face 2 in component A should be flipped"
    assert 7 in result.flipped_face_indices, "Face 7 in component B should be flipped"


# ---------------------------------------------------------------------------
# Test 13: zero-length normal → no crash, fallback to (0,0,1)
# ---------------------------------------------------------------------------

def test_zero_normal_no_crash():
    """Face with (0,0,0) normal must not crash; falls back to (0,0,1)."""
    faces = [
        {"normal": [0.0, 0.0, 0.0], "neighbor_face_indices": [1]},
        {"normal": [0.0, 0.0, -1.0], "neighbor_face_indices": [0]},
    ]
    result = detect_and_flip_face_normals(faces)
    assert len(result.face_normals_after) == 2
    assert isinstance(result.honest_caveat, str)


# ---------------------------------------------------------------------------
# Test 14: max_iter=1 terminates without crash
# ---------------------------------------------------------------------------

def test_max_iter_one_no_crash():
    """Algorithm with max_iter=1 must terminate without raising."""
    faces = _linear_strip_faces(5, invert_index=0)
    result = detect_and_flip_face_normals(faces, max_iter=1)
    assert isinstance(result, FaceNormalFlipResult)
    assert len(result.face_normals_after) == 5


# ---------------------------------------------------------------------------
# Test 15: ring of 4 faces, 1 inverted → detected and flipped
# ---------------------------------------------------------------------------

def test_ring_of_four_faces_one_inverted():
    """4 faces in a ring: 0↔1↔2↔3↔0.  Face 2 is inverted.

    Correct normals: all (0,0,1) — these are flat mesh tiles, all outward.
    Face 2 is inverted to (0,0,-1).

    BFS from seed=0:
      Adjacency: 0↔1, 1↔2, 2↔3, 3↔0
      Visit 1 (sorted first from 0): dot(n0=(0,0,1), n1=(0,0,1)) = +1 > 0 → no flip.
      Visit 3: dot(n0=(0,0,1), n3=(0,0,1)) = +1 > 0 → no flip.
      Visit 2 (from 1): dot(n1=(0,0,1), n2=(0,0,-1)) = -1 < -threshold → flip face 2.

    Result: 1 flip (face 2).  After fix all four faces are (0,0,1).
    """
    faces = [
        {"normal": [0.0, 0.0, 1.0],  "neighbor_face_indices": [1, 3]},   # 0 correct
        {"normal": [0.0, 0.0, 1.0],  "neighbor_face_indices": [0, 2]},   # 1 correct
        {"normal": [0.0, 0.0, -1.0], "neighbor_face_indices": [1, 3]},   # 2 INVERTED
        {"normal": [0.0, 0.0, 1.0],  "neighbor_face_indices": [2, 0]},   # 3 correct
    ]
    result = detect_and_flip_face_normals(faces)
    assert result.num_faces_flipped == 1, (
        f"Expected 1 flip for ring with one inverted face, "
        f"got {result.num_faces_flipped}. Flipped: {result.flipped_face_indices}"
    )
    assert 2 in result.flipped_face_indices, (
        f"Face 2 should be flipped; got {result.flipped_face_indices}"
    )
    # After fix, face 2 should point +Z.
    n2 = result.face_normals_after[2]
    assert n2[2] > 0, f"Face 2 should point +Z after fix, got {n2}"


# ---------------------------------------------------------------------------
# Test 16: output length == input length for various sizes
# ---------------------------------------------------------------------------

def test_output_length_matches_input():
    """face_normals_after must have same length as input faces."""
    for n in [1, 3, 5, 8, 12]:
        faces = [{"normal": [0.0, 0.0, 1.0], "neighbor_face_indices": []} for _ in range(n)]
        result = detect_and_flip_face_normals(faces)
        assert len(result.face_normals_after) == n, (
            f"Expected {n} normals in output, got {len(result.face_normals_after)}"
        )
