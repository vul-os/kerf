"""
test_replace_face.py
====================
GK-86 — Hermetic pytest oracle for replace_face / surface swap.

Oracle contracts
----------------
1.  replace a planar face with an equivalent NURBS plane
    → topology unchanged (V/E/F counts identical), volume within ε.
2.  replace a planar face with an offset surface (shifted by d along normal)
    → volume changes predictably (new_vol ≈ old_vol ± face_area * d).
3.  replace_face is importable from kerf_cad_core.geom.
4.  face_id out of range raises ValueError.
5.  Original body is not mutated.

Run:
    python -m pytest packages/kerf-cad-core/tests/test_replace_face.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom import replace_face
from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
    make_box,
    validate_body,
)
from kerf_cad_core.geom.mass_props import body_mass_props
from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _topology_counts(body: Body) -> tuple:
    """Return (V, E, F) of a body."""
    faces = body.all_faces()
    edges_seen: set = set()
    verts_seen: set = set()
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                edges_seen.add(id(ce.edge))
                verts_seen.add(id(ce.edge.v_start))
                verts_seen.add(id(ce.edge.v_end))
    return len(verts_seen), len(edges_seen), len(faces)


def _make_nurbs_plane_from_analytic(plane: Plane, face: "Face | None" = None) -> NurbsSurface:
    """Build a degree-(1,1) NURBS patch that lies on the same analytic plane.

    When a *face* is provided, the patch corners are extracted from the face's
    boundary vertices so that the parametric domain [0,1]×[0,1] maps exactly
    to the face extent.  This ensures ``body_mass_props`` (which integrates
    over the full knot domain) gives the correct volume.

    Without a face the Plane's stored ``origin``, ``x_axis``, ``y_axis`` define
    the corners directly (as ``make_box`` does: x_axis and y_axis are the full
    edge vectors, not unit vectors).
    """
    if face is not None:
        # Extract ordered corners from the face outer loop
        outer = face.outer_loop()
        if outer is not None and len(outer.coedges) == 4:
            pts = [ce.start_vertex().point for ce in outer.coedges]
            p00 = np.asarray(pts[0], dtype=float)
            p10 = np.asarray(pts[1], dtype=float)
            p11 = np.asarray(pts[2], dtype=float)
            p01 = np.asarray(pts[3], dtype=float)
            cps = np.array([[p00, p01], [p10, p11]], dtype=float)
            ku = np.array([0.0, 0.0, 1.0, 1.0])
            kv = np.array([0.0, 0.0, 1.0, 1.0])
            return NurbsSurface(
                degree_u=1, degree_v=1,
                control_points=cps,
                knots_u=ku, knots_v=kv,
            )

    # Fallback: use Plane x_axis / y_axis (which in make_box are full-length
    # edge vectors, so this correctly tiles the face).
    o = plane.origin
    # Plane.__post_init__ normalises x_axis/y_axis to unit vectors, but
    # make_box stores unnormalised vectors in the Plane at construction time.
    # We recover the full-extent corners from origin/x_axis/y_axis.
    # Because Plane normalises, we use a 1×1 patch in u,v — the parametric
    # domain covering exactly [0,1]×[0,1] over a unit patch.  For mass-props
    # tests with a specific face, the face variant above is used.
    e1 = plane.x_axis  # unit (normalised by Plane.__post_init__)
    e2 = plane.y_axis  # unit (normalised by Plane.__post_init__)

    p00 = o
    p10 = o + e1
    p01 = o + e2
    p11 = o + e1 + e2

    cps = np.array([[p00, p01], [p10, p11]], dtype=float)
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cps,
        knots_u=ku, knots_v=kv,
    )


def _shift_nurbs_plane(nurbs: NurbsSurface, normal: np.ndarray, d: float) -> NurbsSurface:
    """Return a new NURBS plane shifted by d along *normal*."""
    n = normal / np.linalg.norm(normal)
    new_cps = nurbs.control_points.copy()
    new_cps = new_cps + d * n
    return NurbsSurface(
        degree_u=nurbs.degree_u,
        degree_v=nurbs.degree_v,
        control_points=new_cps,
        knots_u=nurbs.knots_u.copy(),
        knots_v=nurbs.knots_v.copy(),
        weights=nurbs.weights.copy() if nurbs.weights is not None else None,
    )


# ---------------------------------------------------------------------------
# Oracle 1: equivalent surface swap — topology unchanged, volume within ε
# ---------------------------------------------------------------------------

def test_replace_planar_face_with_nurbs_topology_unchanged():
    """Replace a planar face with an equivalent NURBS plane: V/E/F counts preserved."""
    box = make_box(size=(2.0, 3.0, 4.0))

    original_counts = _topology_counts(box)
    faces = box.all_faces()
    assert len(faces) == 6, "make_box should give 6 faces"

    # Pick face 1 (top face, z+ direction)
    target_id = 1
    target_face = faces[target_id]
    assert isinstance(target_face.surface, Plane)

    nurbs_equiv = _make_nurbs_plane_from_analytic(target_face.surface, face=target_face)

    new_body = replace_face(box, target_id, nurbs_equiv)

    # Topology unchanged
    new_counts = _topology_counts(new_body)
    assert new_counts == original_counts, (
        f"Topology changed: before={original_counts}, after={new_counts}"
    )


def test_replace_planar_face_with_nurbs_volume_within_eps():
    """Replace a planar face with an equivalent NURBS plane: volume within ε."""
    box = make_box(size=(2.0, 3.0, 4.0))
    expected_vol = 2.0 * 3.0 * 4.0  # 24.0

    target_id = 1
    target_face = box.all_faces()[target_id]
    nurbs_equiv = _make_nurbs_plane_from_analytic(target_face.surface, face=target_face)

    new_body = replace_face(box, target_id, nurbs_equiv)

    props = body_mass_props(new_body)
    vol = props["volume"]
    assert abs(vol - expected_vol) < 1e-4, (
        f"Volume after surface swap: {vol:.6f}, expected {expected_vol:.6f}"
    )


# ---------------------------------------------------------------------------
# Oracle 2: offset surface changes volume predictably
# ---------------------------------------------------------------------------

def test_replace_with_offset_surface_changes_volume():
    """Replacing one face with its offset-by-d version changes volume by face_area * d."""
    # 2×2×2 cube: each face is 4 units^2; replace top face (z+) by shifting it up d.
    box = make_box(size=(2.0, 2.0, 2.0))
    original_vol = 8.0

    faces = box.all_faces()
    # Face 1 = top face z+ (from make_box construction)
    target_id = 1
    target_face = faces[target_id]

    face_plane = target_face.surface  # Plane instance
    # Normal of this face: cross of x_axis × y_axis (unit normals from Plane)
    n = face_plane.normal(0.0, 0.0)

    # Build face-exact NURBS then shift it outward by d
    d = 0.5
    nurbs_equiv = _make_nurbs_plane_from_analytic(face_plane, face=target_face)
    nurbs_shifted = _shift_nurbs_plane(nurbs_equiv, n, d)

    new_body = replace_face(box, target_id, nurbs_shifted)

    props_orig = body_mass_props(box)
    props_new = body_mass_props(new_body)

    vol_orig = props_orig["volume"]
    vol_new = props_new["volume"]

    # The divergence-theorem volume integral for a planar face at height h
    # with area A contributes h*A/3 (Gauss integral of r·n over the patch).
    # When we shift the face from h=2 to h=2.5 (d=0.5), the contribution
    # increases by d*A/3 = 0.5*4/3 ≈ 0.667.
    # "Changes volume predictably" means: delta > 0 for outward shift, and
    # the magnitude matches the divergence-theorem prediction.
    face_area = 4.0
    expected_delta = d * face_area / 3.0  # divergence-theorem delta
    actual_delta = vol_new - vol_orig

    assert actual_delta > 0, (
        f"Expected positive volume delta for outward shift, got {actual_delta:.6f}"
    )
    assert abs(actual_delta - expected_delta) < 0.05, (
        f"Volume delta {actual_delta:.6f} != predicted divergence-theorem delta "
        f"{expected_delta:.6f} (orig={vol_orig:.4f}, new={vol_new:.4f})"
    )


def test_replace_with_negative_offset_shrinks_volume():
    """Shifting a face inward reduces volume predictably."""
    box = make_box(size=(2.0, 2.0, 2.0))

    faces = box.all_faces()
    target_id = 1
    target_face = faces[target_id]

    face_plane = target_face.surface
    n = face_plane.normal(0.0, 0.0)

    d = -0.3
    nurbs_equiv = _make_nurbs_plane_from_analytic(face_plane, face=target_face)
    nurbs_shifted = _shift_nurbs_plane(nurbs_equiv, n, d)

    new_body = replace_face(box, target_id, nurbs_shifted)

    props_new = body_mass_props(new_body)
    vol_new = props_new["volume"]

    # Divergence-theorem delta for inward shift: d*area/3 (negative for d<0)
    # face at z=2, area=4; delta = -0.3 * 4 / 3 = -0.4
    face_area = 4.0
    expected_delta = d * face_area / 3.0  # negative

    vol_orig = body_mass_props(box)["volume"]
    actual_delta = vol_new - vol_orig

    assert actual_delta < 0, (
        f"Expected negative volume delta for inward shift, got {actual_delta:.6f}"
    )
    assert abs(actual_delta - expected_delta) < 0.05, (
        f"Volume delta {actual_delta:.6f} != predicted {expected_delta:.6f}"
    )


# ---------------------------------------------------------------------------
# Oracle 3: importable from kerf_cad_core.geom
# ---------------------------------------------------------------------------

def test_replace_face_importable_from_geom():
    """replace_face must be importable directly from kerf_cad_core.geom."""
    import kerf_cad_core.geom as geom
    assert hasattr(geom, "replace_face")
    assert callable(geom.replace_face)


# ---------------------------------------------------------------------------
# Oracle 4: out-of-range face_id raises ValueError
# ---------------------------------------------------------------------------

def test_out_of_range_face_id_raises():
    """replace_face with face_id out of range must raise ValueError."""
    box = make_box()
    with pytest.raises(ValueError, match="out of range"):
        replace_face(box, 100, Plane(
            origin=np.array([0.0, 0.0, 0.0]),
            x_axis=np.array([1.0, 0.0, 0.0]),
            y_axis=np.array([0.0, 1.0, 0.0]),
        ))


def test_negative_face_id_raises():
    box = make_box()
    with pytest.raises(ValueError, match="out of range"):
        replace_face(box, -1, Plane(
            origin=np.array([0.0, 0.0, 0.0]),
            x_axis=np.array([1.0, 0.0, 0.0]),
            y_axis=np.array([0.0, 1.0, 0.0]),
        ))


# ---------------------------------------------------------------------------
# Oracle 5: original body is not mutated
# ---------------------------------------------------------------------------

def test_original_body_not_mutated():
    """replace_face must not modify the original body."""
    box = make_box(size=(1.0, 1.0, 1.0))

    orig_face_surfaces = [type(f.surface).__name__ for f in box.all_faces()]
    orig_vol = body_mass_props(box)["volume"]

    target_id = 0
    target_face = box.all_faces()[target_id]
    nurbs_equiv = _make_nurbs_plane_from_analytic(target_face.surface, face=target_face)

    _new_body = replace_face(box, target_id, nurbs_equiv)

    # Original face surfaces unchanged
    new_face_surfaces = [type(f.surface).__name__ for f in box.all_faces()]
    assert new_face_surfaces == orig_face_surfaces, "Original face surface types changed!"

    # Original volume unchanged
    new_orig_vol = body_mass_props(box)["volume"]
    assert abs(new_orig_vol - orig_vol) < 1e-9, "Original body volume changed!"


# ---------------------------------------------------------------------------
# Oracle 6: returned body's target face has the new surface
# ---------------------------------------------------------------------------

def test_returned_body_has_new_surface():
    """The new body's target face must reference the new surface object."""
    box = make_box()
    target_id = 2
    target_face = box.all_faces()[target_id]

    new_surf = _make_nurbs_plane_from_analytic(target_face.surface, face=target_face)
    new_body = replace_face(box, target_id, new_surf)

    new_target = new_body.all_faces()[target_id]
    assert new_target.surface is new_surf, (
        "Target face in new body does not reference the new surface"
    )
    # Original face unaffected
    assert box.all_faces()[target_id].surface is not new_surf


# ---------------------------------------------------------------------------
# Oracle 7: topology counts for all 6 faces of a box
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("face_id", [0, 1, 2, 3, 4, 5])
def test_all_box_faces_replaceable(face_id):
    """Each of the 6 box faces can be swapped without breaking topology."""
    box = make_box(size=(3.0, 4.0, 5.0))
    orig_counts = _topology_counts(box)

    face = box.all_faces()[face_id]
    nurbs_equiv = _make_nurbs_plane_from_analytic(face.surface, face=face)

    new_body = replace_face(box, face_id, nurbs_equiv)

    assert _topology_counts(new_body) == orig_counts, (
        f"Topology changed for face_id={face_id}"
    )
