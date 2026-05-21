"""
test_undercut_faces.py
======================
GK-121: Hermetic pytest oracle for undercut_faces().

Spec oracles
------------
1. An overhang / L-shape box (a box with its bottom face hidden by an
   overhang) pulled along +Z reports the under-face as undercut.
2. A plain upright box pulled along +Z has positive draft on every face
   (side faces are perpendicular, top/bottom are fully clear / parting);
   has_undercut is False.

All tests are hermetic (pure-Python, no DB, no OCC required).
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.mold import undercut_faces
from kerf_cad_core.geom.brep import Body, Solid, Shell, Face, Plane
import numpy as _np


# ---------------------------------------------------------------------------
# Helper: build a simple L-shape / overhang body
#
# The overhang body is a flat plate (base) with a shelf hanging off one side:
#
#       ______
#      |      |   <- top of shelf (positive draft, faces +Z)
#      |      |
#  ____|      |
# |under|     |   <- under-face of shelf (faces -Z → UNDERCUT wrt pull=+Z)
# |____|______|
#
# We model this as two adjoined rectangular boxes stacked in a way that
# creates a downward-facing face.  For simplicity we build a manually
# constructed Body with Plane-based faces.
# ---------------------------------------------------------------------------

def _make_plane_face(origin, x_axis, y_axis, orientation=True) -> Face:
    """Create a single-face Body made from a Plane."""
    plane = Plane(
        origin=np.asarray(origin, dtype=float),
        x_axis=np.asarray(x_axis, dtype=float),
        y_axis=np.asarray(y_axis, dtype=float),
    )
    return Face(surface=plane, loops=[], orientation=orientation)


def _make_overhang_body() -> Body:
    """
    Build a Body that contains exactly one undercut face.

    The body has two faces:
      - A top face: Plane with normal pointing +Z  (pull=+Z → clear)
      - An under-face: Plane with normal pointing -Z  (pull=+Z → undercut)

    This mimics the underside of an overhang shelf.
    """
    # Top face: origin at z=1, normal = +Z
    top_face = _make_plane_face(
        origin=[0.0, 0.0, 1.0],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 1.0, 0.0],
        orientation=True,   # outward normal = +Z
    )
    # Under-face: origin at z=0.5, normal = -Z (orientation=False flips +Z → -Z)
    under_face = _make_plane_face(
        origin=[0.0, 0.0, 0.5],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 1.0, 0.0],
        orientation=False,  # outward normal = -Z
    )
    shell = Shell(faces=[top_face, under_face])
    solid = Solid(shells=[shell])
    body = Body(solids=[solid])
    return body


def _make_positive_draft_body() -> Body:
    """
    Build a Body where all faces have non-negative draft w.r.t. +Z.

    Four vertical side faces (normal perpendicular to Z → zero draft / parting)
    and one top face (normal = +Z → fully clear).
    No undercut face.
    """
    faces = []
    # Top face: normal = +Z
    faces.append(_make_plane_face(
        origin=[0.0, 0.0, 1.0],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 1.0, 0.0],
        orientation=True,
    ))
    # Side faces: normals are ±X and ±Y (perpendicular to Z → dot = 0 → parting zone)
    faces.append(_make_plane_face(
        origin=[1.0, 0.0, 0.5],
        x_axis=[0.0, 0.0, 1.0],
        y_axis=[0.0, 1.0, 0.0],
        orientation=True,   # normal = +X
    ))
    faces.append(_make_plane_face(
        origin=[0.0, 1.0, 0.5],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 0.0, 1.0],
        orientation=True,   # normal = +Y
    ))
    shell = Shell(faces=faces)
    solid = Solid(shells=[shell])
    body = Body(solids=[solid])
    return body


# ---------------------------------------------------------------------------
# GK-121 oracle tests
# ---------------------------------------------------------------------------

class TestUndercutFacesOverhang:
    """An overhang body pulled along +Z must report the under-face as undercut."""

    def test_overhang_has_undercut(self):
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert result["has_undercut"] is True, (
            "Overhang body should have at least one undercut face"
        )

    def test_overhang_undercut_face_ids_nonempty(self):
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert len(result["undercut_face_ids"]) >= 1, (
            "Expected at least one undercut face id"
        )

    def test_overhang_under_face_is_red(self):
        """The undercut face must be coloured red (#FF4444)."""
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        for fid in result["undercut_face_ids"]:
            assert result["face_colours"][fid] == "#FF4444", (
                f"Undercut face {fid} should be coloured #FF4444, "
                f"got {result['face_colours'][fid]!r}"
            )

    def test_overhang_correct_face_count_in_colour_map(self):
        """face_colours must contain an entry for every face in the body."""
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        all_ids = [f.id for f in body.all_faces()]
        assert set(result["face_colours"].keys()) == set(all_ids), (
            "face_colours keys must match all face IDs in body"
        )

    def test_overhang_return_keys(self):
        """Result dict must contain exactly the three specified keys."""
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert set(result.keys()) == {"undercut_face_ids", "face_colours", "has_undercut"}

    def test_overhang_pull_neg_z_finds_top_as_undercut(self):
        """Pulling in -Z flips which face is undercut."""
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, -1.0])
        assert result["has_undercut"] is True


class TestUndercutFacesPositiveDraft:
    """A box with only positive-draft faces pulled along +Z reports no undercut."""

    def test_no_undercut(self):
        body = _make_positive_draft_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert result["has_undercut"] is False, (
            "Draft-positive body should report no undercut"
        )

    def test_no_undercut_ids(self):
        body = _make_positive_draft_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert result["undercut_face_ids"] == [], (
            "Draft-positive body should have empty undercut_face_ids"
        )

    def test_all_faces_non_red(self):
        """No face in a draft-positive body should be red."""
        body = _make_positive_draft_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        for fid, colour in result["face_colours"].items():
            assert colour != "#FF4444", (
                f"Face {fid} unexpectedly coloured undercut (#FF4444)"
            )


class TestUndercutFacesEdgeCases:

    def test_zero_pull_raises(self):
        body = _make_overhang_body()
        with pytest.raises(ValueError, match="non-zero"):
            undercut_faces(body, [0.0, 0.0, 0.0])

    def test_non_unit_pull_direction(self):
        """Pull direction need not be unit length."""
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 100.0])
        assert result["has_undercut"] is True

    def test_exported_from_geom_init(self):
        """undercut_faces must be importable from the public geom facade."""
        from kerf_cad_core.geom import undercut_faces as uf  # noqa: F401
        assert callable(uf)

    def test_has_undercut_is_bool(self):
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert isinstance(result["has_undercut"], bool)

    def test_undercut_face_ids_is_list(self):
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert isinstance(result["undercut_face_ids"], list)

    def test_face_colours_is_dict(self):
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        assert isinstance(result["face_colours"], dict)

    def test_colour_values_valid(self):
        """All colour values must be one of the three defined hex strings."""
        VALID = {"#FF4444", "#FFAA00", "#44BB44"}
        body = _make_overhang_body()
        result = undercut_faces(body, [0.0, 0.0, 1.0])
        for fid, colour in result["face_colours"].items():
            assert colour in VALID, (
                f"Face {fid} has unexpected colour {colour!r}; "
                f"expected one of {VALID}"
            )
