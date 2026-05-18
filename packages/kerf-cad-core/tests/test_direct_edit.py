"""Verification suite for kerf_cad_core.geom.history.direct_edit (T-107).

Exercises the direct-edit verbs + the direct/parametric coexistence
contract: a direct edit on the current Body snapshot must round-trip
through a DAG ``direct_edit`` node and replay to the same geometry.

Hermetic — no network, no OCCT, no external fixtures.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import validate_body
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.history.dag import FeatureDAG
from kerf_cad_core.geom.history.evaluators import BoxFeature, register_default_evaluators
from kerf_cad_core.geom.history.feature import FeatureRef, MissingReferenceError
from kerf_cad_core.geom.history.direct_edit import (
    DirectEditError,
    DirectEditRecord,
    UnsupportedBodyError,
    _body_volume,
    _face_persistent_id,
    commit_direct_edits_to_dag,
    direct_delete_feature,
    direct_offset_face,
    direct_push_pull,
    direct_rotate_face,
    direct_translate_face,
)

TOL = 1e-6


def _box(corner=(0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0):
    return box_to_body(corner=corner, dx=dx, dy=dy, dz=dz)


def _face_id_with_normal(body, target_normal):
    """Return the persistent id of the face whose outward normal ≈ target."""
    tn = np.asarray(target_normal, dtype=float)
    for f in body.all_faces():
        n = np.asarray(f.surface.normal(0.5, 0.5), dtype=float)
        n = n / (np.linalg.norm(n) or 1.0)
        if np.linalg.norm(n - tn) < 1e-6:
            return _face_persistent_id(f)
    raise AssertionError(f"no face with normal {target_normal}")


# ---------------------------------------------------------------------------
# Baseline geometry
# ---------------------------------------------------------------------------


def test_box_baseline_is_valid_six_planar_faces():
    body = _box()
    validate_body(body)
    faces = body.all_faces()
    assert len(faces) == 6
    assert _body_volume(body) == pytest.approx(2.0 * 3.0 * 4.0, rel=1e-6)


# ---------------------------------------------------------------------------
# direct_offset_face / direct_push_pull
# ---------------------------------------------------------------------------


def test_offset_face_outward_increases_volume():
    body = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body, (1.0, 0.0, 0.0))
    out = direct_offset_face(body, fid, 1.0)
    validate_body(out)
    # +X face pushed out 1.0 → dx 2→3, volume 24→36
    assert _body_volume(out) == pytest.approx(3.0 * 3.0 * 4.0, rel=1e-6)


def test_offset_face_inward_decreases_volume():
    body = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body, (1.0, 0.0, 0.0))
    out = direct_offset_face(body, fid, -0.5)
    validate_body(out)
    assert _body_volume(out) == pytest.approx(1.5 * 3.0 * 4.0, rel=1e-6)


def test_push_pull_equivalent_to_offset():
    body = _box()
    fid = _face_id_with_normal(body, (0.0, 0.0, 1.0))
    a = direct_offset_face(body, fid, 0.75)
    b = direct_push_pull(body, fid, 0.75)
    assert _body_volume(a) == pytest.approx(_body_volume(b), rel=1e-9)


def test_input_body_not_mutated():
    body = _box()
    v0 = _body_volume(body)
    fid = _face_id_with_normal(body, (1.0, 0.0, 0.0))
    direct_offset_face(body, fid, 2.0)
    assert _body_volume(body) == pytest.approx(v0, rel=1e-12)


# ---------------------------------------------------------------------------
# direct_translate_face
# ---------------------------------------------------------------------------


def test_translate_face_along_normal_matches_offset():
    body = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body, (1.0, 0.0, 0.0))
    out = direct_translate_face(body, fid, (1.0, 0.0, 0.0))
    validate_body(out)
    assert _body_volume(out) == pytest.approx(3.0 * 3.0 * 4.0, rel=1e-6)


def test_translate_perpendicular_component_does_not_change_plane():
    body = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body, (1.0, 0.0, 0.0))
    # delta perpendicular to the +X normal projects to zero offset
    out = direct_translate_face(body, fid, (0.0, 5.0, 0.0))
    assert _body_volume(out) == pytest.approx(2.0 * 3.0 * 4.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Error contract
# ---------------------------------------------------------------------------


def test_unknown_face_raises_missing_reference():
    body = _box()
    with pytest.raises(MissingReferenceError):
        direct_offset_face(body, "deadbeefdeadbeef", 1.0)


def test_collapsing_offset_raises_degenerate():
    body = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body, (1.0, 0.0, 0.0))
    with pytest.raises(DirectEditError) as ei:
        # push the +X face inward past the -X face → degenerate box
        direct_offset_face(body, fid, -5.0)
    assert ei.value.reason in ("degenerate-geometry", "direct-edit-error")


def test_unsupported_body_error_is_direct_edit_error_subclass():
    assert issubclass(UnsupportedBodyError, DirectEditError)


def test_direct_edit_error_carries_reason():
    err = DirectEditError("boom", reason="non-planar face")
    assert err.reason == "non-planar face"
    assert isinstance(err, ValueError)


# ---------------------------------------------------------------------------
# DirectEditRecord
# ---------------------------------------------------------------------------


def test_direct_edit_record_dataclass():
    rec = DirectEditRecord(verb="offset", face_persistent_id="abc123")
    assert rec.verb == "offset"
    assert rec.face_persistent_id == "abc123"
    assert rec.params == {}
    rec2 = DirectEditRecord(verb="translate", face_persistent_id="x", params={"d": 1})
    assert rec2.params == {"d": 1}


# ---------------------------------------------------------------------------
# Direct ↔ parametric coexistence: commit to DAG and replay
# ---------------------------------------------------------------------------


def test_commit_direct_edit_to_dag_and_replay():
    body_before = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body_before, (1.0, 0.0, 0.0))
    body_after = direct_offset_face(body_before, fid, 1.0)

    dag = FeatureDAG()
    feats = commit_direct_edits_to_dag(dag, body_before, body_after)

    assert len(feats) == 1
    feat = feats[0]
    assert feat.kind == "direct_edit"
    assert "direct_edit" in dag.evaluators()
    assert "planes_after" in feat.params
    assert feat.params["plane_diff"], "a plane changed → diff must be non-empty"

    replayed = dag.evaluate(feat.id)
    validate_body(replayed)
    assert _body_volume(replayed) == pytest.approx(
        _body_volume(body_after), rel=1e-6
    )


def test_commit_registration_is_idempotent():
    body_before = _box()
    fid = _face_id_with_normal(body_before, (0.0, 1.0, 0.0))
    body_after = direct_offset_face(body_before, fid, 0.5)

    dag = FeatureDAG()
    commit_direct_edits_to_dag(dag, body_before, body_after)
    # second commit must not raise on re-registering the evaluator
    commit_direct_edits_to_dag(dag, body_before, body_after)
    assert "direct_edit" in dag.evaluators()


def test_commit_no_change_has_empty_diff():
    body = _box()
    dag = FeatureDAG()
    feats = commit_direct_edits_to_dag(dag, body, body)
    assert feats[0].params["plane_diff"] == []


# ---------------------------------------------------------------------------
# direct_rotate_face — sanity (no crash, stays valid for small rotation)
# ---------------------------------------------------------------------------


def test_rotate_face_unknown_raises_missing_reference():
    body = _box()
    with pytest.raises(MissingReferenceError):
        direct_rotate_face(body, "00000000deadbeef", (0.0, 0.0, 1.0), 0.1)


# ---------------------------------------------------------------------------
# T-107 Direct + parametric history coexistence — the keystone contract
#
# A direct edit committed to the DAG with a source_feature_id must replay
# *relative to the upstream body* when that upstream parametric feature is
# edited.  After the upstream box grows from dx=2 to dx=4, a direct edit
# that previously moved the +X face by +1 must produce dx=5 (not the stale
# dx=3).
# ---------------------------------------------------------------------------


def _fresh_parametric_dag():
    """Return a FeatureDAG with the default evaluators registered."""
    dag = FeatureDAG()
    register_default_evaluators(dag)
    return dag


def test_coexistence_direct_edit_replays_relative_after_upstream_param_change():
    """DoD keystone: direct-face-move stays attached to semantically-named
    face after an upstream parametric edit."""
    dag = _fresh_parametric_dag()
    box = BoxFeature((0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
    dag.add_feature(box)
    body_before = dag.evaluate(box.id)

    # Direct edit: push +X face outward by 1.0 (dx: 2 → 3).
    fid = _face_id_with_normal(body_before, (1.0, 0.0, 0.0))
    body_after_direct = direct_offset_face(body_before, fid, 1.0)
    assert _body_volume(body_after_direct) == pytest.approx(3.0 * 3.0 * 4.0, rel=1e-6)

    # Commit the direct edit wired to the upstream box feature.
    feats = commit_direct_edits_to_dag(
        dag, body_before, body_after_direct, source_feature_id=box.id
    )
    de_feat = feats[0]

    # Sanity before the upstream edit.
    replayed = dag.evaluate(de_feat.id)
    validate_body(replayed)
    assert _body_volume(replayed) == pytest.approx(3.0 * 3.0 * 4.0, rel=1e-6)

    # --- Upstream parametric edit: grow the box from dx=2 to dx=4 ---
    dag.set_param(box.id, "dx", 4.0)
    dag.regenerate()

    # The direct edit must replay relative to the new upstream body:
    # box +X face is now at d=4, delta=+1.0 → new +X face at d=5 → dx=5.
    body_coexisted = dag.evaluate(de_feat.id)
    validate_body(body_coexisted)
    expected_volume = 5.0 * 3.0 * 4.0  # (4 + 1) * dy * dz
    assert _body_volume(body_coexisted) == pytest.approx(expected_volume, rel=1e-6), (
        f"direct edit must replay relative to upstream: expected vol={expected_volume}, "
        f"got {_body_volume(body_coexisted)}"
    )


def test_coexistence_direct_edit_dy_replays_relative():
    """Same contract on the +Y face (different axis)."""
    dag = _fresh_parametric_dag()
    box = BoxFeature((0.0, 0.0, 0.0), dx=2.0, dy=3.0, dz=4.0)
    dag.add_feature(box)
    body_before = dag.evaluate(box.id)

    fid = _face_id_with_normal(body_before, (0.0, 1.0, 0.0))
    body_after_direct = direct_offset_face(body_before, fid, 0.5)
    feats = commit_direct_edits_to_dag(
        dag, body_before, body_after_direct, source_feature_id=box.id
    )
    de_feat = feats[0]

    # Upstream: dy 3 → 6.
    dag.set_param(box.id, "dy", 6.0)
    dag.regenerate()

    body_coexisted = dag.evaluate(de_feat.id)
    validate_body(body_coexisted)
    # Expected: +Y face was at d=3, delta=+0.5; now upstream is d=6, result d=6.5, dy=6.5.
    expected_volume = 2.0 * 6.5 * 4.0
    assert _body_volume(body_coexisted) == pytest.approx(expected_volume, rel=1e-6)


def test_coexistence_direct_edit_inward_replays_relative():
    """Inward (negative delta) direct edit replays correctly after upstream growth."""
    dag = _fresh_parametric_dag()
    box = BoxFeature((0.0, 0.0, 0.0), dx=4.0, dy=3.0, dz=4.0)
    dag.add_feature(box)
    body_before = dag.evaluate(box.id)

    # Pull +X face inward by 1.0 (dx: 4 → 3).
    fid = _face_id_with_normal(body_before, (1.0, 0.0, 0.0))
    body_after_direct = direct_offset_face(body_before, fid, -1.0)
    feats = commit_direct_edits_to_dag(
        dag, body_before, body_after_direct, source_feature_id=box.id
    )
    de_feat = feats[0]

    # Upstream: dx 4 → 8.
    dag.set_param(box.id, "dx", 8.0)
    dag.regenerate()

    body_coexisted = dag.evaluate(de_feat.id)
    validate_body(body_coexisted)
    # +X face now at d=8, delta=-1.0 → result d=7, dx=7.
    expected_volume = 7.0 * 3.0 * 4.0
    assert _body_volume(body_coexisted) == pytest.approx(expected_volume, rel=1e-6)


def test_coexistence_multiple_upstream_edits_accumulate_correctly():
    """Multiple successive upstream param changes all replay the same relative delta."""
    dag = _fresh_parametric_dag()
    box = BoxFeature((0.0, 0.0, 0.0), dx=2.0, dy=2.0, dz=2.0)
    dag.add_feature(box)
    body_before = dag.evaluate(box.id)

    fid = _face_id_with_normal(body_before, (1.0, 0.0, 0.0))
    body_after_direct = direct_offset_face(body_before, fid, 1.0)  # dx: 2 → 3
    feats = commit_direct_edits_to_dag(
        dag, body_before, body_after_direct, source_feature_id=box.id
    )
    de_feat = feats[0]

    for new_dx, expected_dx_after_direct in [(3.0, 4.0), (5.0, 6.0), (10.0, 11.0)]:
        dag.set_param(box.id, "dx", new_dx)
        dag.regenerate()
        body = dag.evaluate(de_feat.id)
        validate_body(body)
        expected_vol = expected_dx_after_direct * 2.0 * 2.0
        assert _body_volume(body) == pytest.approx(expected_vol, rel=1e-6), (
            f"dx={new_dx}: expected vol={expected_vol}, got {_body_volume(body)}"
        )


def test_coexistence_standalone_direct_edit_uses_absolute_planes():
    """A direct edit with no source_feature_id must still replay from absolute
    planes_after (fallback path, no upstream body in context)."""
    dag = FeatureDAG()  # no default evaluators needed — direct_edit only
    body_before = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body_before, (1.0, 0.0, 0.0))
    body_after_direct = direct_offset_face(body_before, fid, 1.0)

    feats = commit_direct_edits_to_dag(dag, body_before, body_after_direct)
    de_feat = feats[0]
    assert "body" not in de_feat.inputs  # no upstream wiring

    replayed = dag.evaluate(de_feat.id)
    validate_body(replayed)
    assert _body_volume(replayed) == pytest.approx(_body_volume(body_after_direct), rel=1e-6)


def test_coexistence_direct_edit_face_role_survives_param_change():
    """After an upstream parametric edit, the direct edit node's naming table
    must still contain the expected face roles for the resulting body."""
    dag = _fresh_parametric_dag()
    box = BoxFeature((0.0, 0.0, 0.0), dx=2.0, dy=2.0, dz=2.0)
    dag.add_feature(box)
    body_before = dag.evaluate(box.id)

    fid = _face_id_with_normal(body_before, (1.0, 0.0, 0.0))
    body_after_direct = direct_offset_face(body_before, fid, 0.5)
    feats = commit_direct_edits_to_dag(
        dag, body_before, body_after_direct, source_feature_id=box.id
    )
    de_feat = feats[0]

    # Evaluate and capture face roles before upstream change.
    dag.evaluate(de_feat.id)
    table_before = dag.naming_table(de_feat.id)
    roles_before = set(table_before.faces.keys())

    # Upstream edit.
    dag.set_param(box.id, "dx", 5.0)
    dag.regenerate()
    dag.evaluate(de_feat.id)
    table_after = dag.naming_table(de_feat.id)
    roles_after = set(table_after.faces.keys())

    # The face roles must be stable — same set of axis-aligned names.
    assert roles_after == roles_before, (
        f"direct-edit face roles changed after upstream param edit: "
        f"before={roles_before}, after={roles_after}"
    )


def test_coexistence_d_delta_stored_in_plane_diff():
    """The plane_diff entries must carry the signed d_delta for relative replay."""
    body_before = _box(dx=2.0, dy=3.0, dz=4.0)
    fid = _face_id_with_normal(body_before, (1.0, 0.0, 0.0))
    body_after = direct_offset_face(body_before, fid, 1.5)

    dag = FeatureDAG()
    feats = commit_direct_edits_to_dag(dag, body_before, body_after)
    diff = feats[0].params["plane_diff"]
    assert len(diff) == 1
    entry = diff[0]
    assert "d_delta" in entry, "plane_diff entries must carry d_delta for relative replay"
    assert abs(entry["d_delta"] - 1.5) < 1e-9, (
        f"d_delta should be 1.5, got {entry['d_delta']}"
    )


def test_coexistence_translate_face_replays_relative():
    """direct_translate_face (move along arbitrary vector) replays relative to
    upstream — the projection of the vector onto the face normal becomes the
    d_delta stored in the diff."""
    dag = _fresh_parametric_dag()
    box = BoxFeature((0.0, 0.0, 0.0), dx=2.0, dy=2.0, dz=2.0)
    dag.add_feature(box)
    body_before = dag.evaluate(box.id)

    fid = _face_id_with_normal(body_before, (0.0, 0.0, 1.0))
    # Translate +Z face by vector (0, 0, 1) → pure normal projection = 1.0
    body_after = direct_translate_face(body_before, fid, (0.0, 0.0, 1.0))
    feats = commit_direct_edits_to_dag(
        dag, body_before, body_after, source_feature_id=box.id
    )
    de_feat = feats[0]

    # Upstream: dz 2 → 4
    dag.set_param(box.id, "dz", 4.0)
    dag.regenerate()

    body_coexisted = dag.evaluate(de_feat.id)
    validate_body(body_coexisted)
    # +Z face now at d=4, delta=+1.0 → dz_effective = 5.0
    expected_volume = 2.0 * 2.0 * 5.0
    assert _body_volume(body_coexisted) == pytest.approx(expected_volume, rel=1e-6)
