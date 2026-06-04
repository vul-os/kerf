"""
Tests for kerf_cad_core.afr.persistent_face_id.

References
----------
* Kripac (1997) — persistent naming in parametric solid models.
* Han et al. (1999) — feature-based face signatures.
"""

from __future__ import annotations

import copy
import pytest

from kerf_cad_core.afr.persistent_face_id import (
    FacePersistentId,
    assign_persistent_ids,
    reattach_face_ids_after_edit,
    detect_id_breaks,
    _canonical_signature,
    _body_centroid,
    _face_centroid,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic body representations
# ---------------------------------------------------------------------------

def _cube_body() -> dict:
    """A unit cube body with 6 planar faces."""
    return {
        "faces": [
            {"id": 0, "type": "planar", "normal": [0, 0, -1], "area": 1.0, "centroid": [0.5, 0.5, 0.0], "convexity": "flat"},
            {"id": 1, "type": "planar", "normal": [0, 0,  1], "area": 1.0, "centroid": [0.5, 0.5, 1.0], "convexity": "flat"},
            {"id": 2, "type": "planar", "normal": [0, -1, 0], "area": 1.0, "centroid": [0.5, 0.0, 0.5], "convexity": "flat"},
            {"id": 3, "type": "planar", "normal": [0,  1, 0], "area": 1.0, "centroid": [0.5, 1.0, 0.5], "convexity": "flat"},
            {"id": 4, "type": "planar", "normal": [-1, 0, 0], "area": 1.0, "centroid": [0.0, 0.5, 0.5], "convexity": "flat"},
            {"id": 5, "type": "planar", "normal": [ 1, 0, 0], "area": 1.0, "centroid": [1.0, 0.5, 0.5], "convexity": "flat"},
        ]
    }


def _cube_with_fillet_body() -> dict:
    """Unit cube + 2 fillet faces on top edges (simulates add-fillet operation)."""
    base = _cube_body()
    extra = [
        {"id": 6, "type": "toroidal", "normal": [0.707, 0, 0.707], "area": 0.1, "centroid": [1.0, 0.5, 1.0], "radius": 0.05, "convexity": "convex", "creating_feature_id": "fillet_1", "feature_role": "fillet_added"},
        {"id": 7, "type": "toroidal", "normal": [-0.707, 0, 0.707], "area": 0.1, "centroid": [0.0, 0.5, 1.0], "radius": 0.05, "convexity": "convex", "creating_feature_id": "fillet_1", "feature_role": "fillet_added"},
    ]
    result = copy.deepcopy(base)
    result["faces"].extend(extra)
    return result


def _cube_missing_top_body() -> dict:
    """Unit cube with top face removed (simulates a topology change)."""
    body = _cube_body()
    result = copy.deepcopy(body)
    result["faces"] = [f for f in result["faces"] if f["id"] != 1]  # remove top
    return result


# ---------------------------------------------------------------------------
# Test 1: Unit cube → 6 stable face IDs
# ---------------------------------------------------------------------------

def test_cube_6_face_ids():
    body = _cube_body()
    ids = assign_persistent_ids(body)
    assert len(ids) == 6, f"Expected 6 face IDs, got {len(ids)}"


# ---------------------------------------------------------------------------
# Test 2: Each face gets a non-empty UUID
# ---------------------------------------------------------------------------

def test_cube_face_ids_non_empty():
    body = _cube_body()
    ids = assign_persistent_ids(body)
    for i, fpid in ids.items():
        assert isinstance(fpid, FacePersistentId)
        assert len(fpid.face_uuid) == 32, f"UUID should be 32-char hex, got {fpid.face_uuid!r}"
        assert len(fpid.canonical_signature) == 64, f"Signature should be 64-char sha256"


# ---------------------------------------------------------------------------
# Test 3: Same body → same signatures (deterministic)
# ---------------------------------------------------------------------------

def test_deterministic_signatures():
    body = _cube_body()
    ids1 = assign_persistent_ids(body)
    ids2 = assign_persistent_ids(body)
    for i in range(6):
        assert ids1[i].canonical_signature == ids2[i].canonical_signature, \
            f"Signature changed between calls for face {i}"


# ---------------------------------------------------------------------------
# Test 4: Re-assignment preserves UUIDs for unchanged faces
# ---------------------------------------------------------------------------

def test_uuid_preserved_after_reassignment():
    body = _cube_body()
    ids_first = assign_persistent_ids(body)
    ids_second = assign_persistent_ids(body, prior_assignments=ids_first)
    for i in range(6):
        assert ids_first[i].face_uuid == ids_second[i].face_uuid, \
            f"UUID changed for face {i}: {ids_first[i].face_uuid} → {ids_second[i].face_uuid}"


# ---------------------------------------------------------------------------
# Test 5: Add fillet → original 6 IDs preserved, 2 new fillet IDs appear
# ---------------------------------------------------------------------------

def test_add_fillet_preserves_original_ids():
    cube = _cube_body()
    ids_before = assign_persistent_ids(cube)

    fillet_body = _cube_with_fillet_body()
    ids_after = assign_persistent_ids(fillet_body, prior_assignments=ids_before)

    assert len(ids_after) == 8, f"Expected 8 IDs after adding fillet, got {len(ids_after)}"

    # Original 6 faces (indices 0-5) should have same UUIDs
    for i in range(6):
        assert ids_after[i].face_uuid == ids_before[i].face_uuid, \
            f"UUID changed for original face {i}: {ids_before[i].face_uuid} → {ids_after[i].face_uuid}"

    # New fillet faces (indices 6-7) should have fresh UUIDs not in original set
    original_uuids = {fpid.face_uuid for fpid in ids_before.values()}
    for i in [6, 7]:
        assert ids_after[i].face_uuid not in original_uuids, \
            f"Fillet face {i} should have a new UUID, not one from original set"


# ---------------------------------------------------------------------------
# Test 6: detect_id_breaks — removing top face causes 1 break
# ---------------------------------------------------------------------------

def test_detect_id_breaks_remove_face():
    cube = _cube_body()
    ids_before = assign_persistent_ids(cube)

    cube_no_top = _cube_missing_top_body()
    breaks = detect_id_breaks(cube, cube_no_top, ids_before)

    # The top face (id=1, index=1 in original) should be reported as broken
    assert 1 in breaks, f"Expected face 1 (top) in id_breaks, got {breaks}"
    # Other faces should not be broken
    assert len(breaks) == 1, f"Expected exactly 1 break, got {len(breaks)}: {breaks}"


# ---------------------------------------------------------------------------
# Test 7: reattach_face_ids_after_edit round-trips
# ---------------------------------------------------------------------------

def test_reattach_after_edit_no_change():
    body = _cube_body()
    ids_before = assign_persistent_ids(body)
    ids_after = reattach_face_ids_after_edit(body, body, ids_before)
    for i in range(6):
        assert ids_after[i].face_uuid == ids_before[i].face_uuid


# ---------------------------------------------------------------------------
# Test 8: FacePersistentId dataclass fields
# ---------------------------------------------------------------------------

def test_face_persistent_id_fields():
    fpid = FacePersistentId(
        face_uuid="abc123",
        creating_feature_id="extrude_1",
        feature_role="top_of_extrude",
        canonical_signature="deadbeef" * 8,
    )
    assert fpid.face_uuid == "abc123"
    assert fpid.creating_feature_id == "extrude_1"
    assert fpid.feature_role == "top_of_extrude"


# ---------------------------------------------------------------------------
# Test 9: canonical_signature is stable for identical input
# ---------------------------------------------------------------------------

def test_canonical_signature_stable():
    face = {"type": "planar", "normal": [0.0, 0.0, 1.0], "area": 1.0}
    rel_c = [0.0, 0.0, 0.5]
    sig1 = _canonical_signature(face, rel_c)
    sig2 = _canonical_signature(face, rel_c)
    assert sig1 == sig2


# ---------------------------------------------------------------------------
# Test 10: canonical_signature differs for different normals
# ---------------------------------------------------------------------------

def test_canonical_signature_different_normals():
    face_top = {"type": "planar", "normal": [0.0, 0.0, 1.0], "area": 1.0}
    face_bot = {"type": "planar", "normal": [0.0, 0.0, -1.0], "area": 1.0}
    rel_c = [0.0, 0.0, 0.0]
    assert _canonical_signature(face_top, rel_c) != _canonical_signature(face_bot, rel_c)


# ---------------------------------------------------------------------------
# Test 11: Empty body → empty assignments
# ---------------------------------------------------------------------------

def test_empty_body():
    body = {"faces": []}
    ids = assign_persistent_ids(body)
    assert ids == {}


# ---------------------------------------------------------------------------
# Test 12: All 6 cube face UUIDs are distinct
# ---------------------------------------------------------------------------

def test_cube_face_uuids_distinct():
    body = _cube_body()
    ids = assign_persistent_ids(body)
    uuids = [fpid.face_uuid for fpid in ids.values()]
    assert len(set(uuids)) == 6, f"Expected 6 distinct UUIDs, got duplicates in {uuids}"
