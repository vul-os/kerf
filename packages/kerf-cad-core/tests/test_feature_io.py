"""test_feature_io.py — GK-61: .feature log ↔ in-proc DAG bridge.

Oracle contract:
  Loading an existing ``.feature`` fixture and regenerating produces the
  SAME Body that the worker (in-proc builder) produces — verified by:

    * identical Euler topology counts (V, E, F)
    * identical volume (divergence integral, abs difference ≤ 1e-6)
    * Hausdorff distance ≤ tol=1e-6 between the two bodies' vertex sets

All tests are hermetic: pure-Python, no database, no OCCT.

The ``surfacing.py`` public API must remain unchanged — these tests
import only from:
    kerf_cad_core.geom.history.feature_io
    kerf_cad_core.geom.history  (existing public API)
    kerf_cad_core.geom.brep
"""

from __future__ import annotations

import json
import math
import os
import warnings
from pathlib import Path
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.brep import Body, validate_body
from kerf_cad_core.geom.history import (
    BooleanFeature,
    BoxFeature,
    ChamferEdgeFeature,
    CylinderFeature,
    FeatureDAG,
    FeatureRef,
    FilletEdgeFeature,
    PersistentSelector,
    SphereFeature,
    register_default_evaluators,
)
from kerf_cad_core.geom.history.feature_io import (
    SUPPORTED_OPS,
    FeatureLogError,
    body_from_feature_log,
    dag_to_feature_log,
    load_feature_log,
)

# ---------------------------------------------------------------------------
# Fixtures directory
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Oracle helpers
# ---------------------------------------------------------------------------


def _body_volume(body: Body) -> float:
    """Estimate body volume via signed divergence over triangulated outer loops."""
    vol = 0.0
    for face in body.all_faces():
        outer = face.outer_loop()
        if outer is None or len(outer.coedges) < 3:
            continue
        pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
        p0 = pts[0]
        for i in range(1, len(pts) - 1):
            a = pts[i] - p0
            b = pts[i + 1] - p0
            cross = np.cross(a, b)
            vol += float(np.dot(p0, cross))
    return abs(vol) / 6.0


def _body_vertex_cloud(body: Body) -> np.ndarray:
    """Return (N, 3) array of all distinct vertex positions."""
    pts = [np.asarray(v.point, dtype=float) for v in body.all_vertices()]
    if not pts:
        return np.zeros((0, 3))
    return np.array(pts)


def _hausdorff(body_a: Body, body_b: Body) -> float:
    """One-sided Hausdorff distance between the two vertex clouds.

    Returns the maximum over each vertex of body_a of its nearest-neighbour
    distance in body_b, and vice versa; returns the larger of the two.
    """
    ca = _body_vertex_cloud(body_a)
    cb = _body_vertex_cloud(body_b)
    if ca.shape[0] == 0 or cb.shape[0] == 0:
        return 0.0

    def _one_sided(source: np.ndarray, target: np.ndarray) -> float:
        max_min = 0.0
        for p in source:
            dists = np.linalg.norm(target - p, axis=1)
            max_min = max(max_min, float(np.min(dists)))
        return max_min

    return max(_one_sided(ca, cb), _one_sided(cb, ca))


def _assert_bodies_equal(a: Body, b: Body, tol: float = 1e-6) -> None:
    """Assert two bodies are geometrically equivalent within *tol*."""
    ca = a.euler_counts()
    cb = b.euler_counts()
    assert ca == cb, f"Euler counts differ: loaded={ca} worker={cb}"
    va = _body_volume(a)
    vb = _body_volume(b)
    assert abs(va - vb) <= tol, (
        f"volume mismatch: loaded={va:.9f} worker={vb:.9f} diff={abs(va-vb):.2e}"
    )
    h = _hausdorff(a, b)
    assert h <= tol, f"Hausdorff distance {h:.2e} exceeds tol={tol}"


def _fresh_dag() -> FeatureDAG:
    dag = FeatureDAG()
    register_default_evaluators(dag)
    return dag


# ===========================================================================
# 1. Basic loading — box_simple fixture
# ===========================================================================


class TestLoadBoxSimpleFixture:
    def test_dag_has_one_feature(self):
        dag = load_feature_log(FIXTURES_DIR / "box_simple.feature")
        assert len(dag) == 1

    def test_feature_kind_is_box(self):
        dag = load_feature_log(FIXTURES_DIR / "box_simple.feature")
        fid = dag.feature_ids()[0]
        f = dag.get_feature(fid)
        assert f.kind == "box"

    def test_params_preserved(self):
        dag = load_feature_log(FIXTURES_DIR / "box_simple.feature")
        fid = dag.feature_ids()[0]
        f = dag.get_feature(fid)
        assert f.params["dx"] == pytest.approx(10.0)
        assert f.params["dy"] == pytest.approx(5.0)
        assert f.params["dz"] == pytest.approx(3.0)

    def test_id_preserved(self):
        dag = load_feature_log(FIXTURES_DIR / "box_simple.feature")
        assert "box-1" in dag

    def test_validate_body(self):
        body = body_from_feature_log(FIXTURES_DIR / "box_simple.feature")
        vr = validate_body(body)
        assert vr["ok"], f"validate_body errors: {vr['errors']}"

    def test_oracle_euler_counts(self):
        """Box (dx=10, dy=5, dz=3): V=8 E=12 F=6."""
        body = body_from_feature_log(FIXTURES_DIR / "box_simple.feature")
        c = body.euler_counts()
        assert c["V"] == 8
        assert c["E"] == 12
        assert c["F"] == 6

    def test_oracle_volume(self):
        """Volume = 10 * 5 * 3 = 150."""
        body = body_from_feature_log(FIXTURES_DIR / "box_simple.feature")
        vol = _body_volume(body)
        assert abs(vol - 150.0) < 1e-9

    def test_oracle_matches_worker(self):
        """Loaded fixture must produce the SAME Body as the worker."""
        loaded = body_from_feature_log(FIXTURES_DIR / "box_simple.feature")
        dag = _fresh_dag()
        worker_box = BoxFeature((0, 0, 0), 10.0, 5.0, 3.0)
        dag.add_feature(worker_box)
        worker = dag.evaluate(worker_box.id)
        _assert_bodies_equal(loaded, worker)


# ===========================================================================
# 2. Chamfer fixture
# ===========================================================================


class TestLoadBoxChamferFixture:
    def test_dag_has_two_features(self):
        dag = load_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        assert len(dag) == 2

    def test_chamfer_feature_kind(self):
        dag = load_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        f = dag.get_feature("chamfer-1")
        assert f.kind == "chamfer_edge"

    def test_chamfer_inputs_wired(self):
        dag = load_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        f = dag.get_feature("chamfer-1")
        assert isinstance(f.inputs["body"], FeatureRef)
        assert f.inputs["body"].feature_id == "box-1"
        assert isinstance(f.inputs["edge"], PersistentSelector)
        assert f.inputs["edge"].role == "+Z/-Y"
        assert f.inputs["edge"].entity_kind == "edge"

    def test_validate_body(self):
        body = body_from_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        vr = validate_body(body)
        assert vr["ok"], f"validate_body errors: {vr['errors']}"

    def test_oracle_euler_topology(self):
        """Box (4x4x4) + 1 chamfer: V=10, E=15, F=7."""
        body = body_from_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        c = body.euler_counts()
        assert c["V"] == 10
        assert c["E"] == 15
        assert c["F"] == 7

    def test_oracle_matches_worker(self):
        """Loaded chamfer fixture must match the worker's chamfer body."""
        loaded = body_from_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        # Build via worker
        dag = _fresh_dag()
        box = BoxFeature((0, 0, 0), 4.0, 4.0, 4.0)
        dag.add_feature(box)
        dag.evaluate(box.id)
        sel = PersistentSelector(box.id, "edge", "+Z/-Y")
        chamf = ChamferEdgeFeature(
            body=FeatureRef(box.id), edge=sel, width=0.5
        )
        dag.add_feature(chamf)
        worker = dag.evaluate(chamf.id)
        _assert_bodies_equal(loaded, worker)


# ===========================================================================
# 3. Boolean union fixture
# ===========================================================================


class TestLoadBooleanUnionFixture:
    def test_dag_has_three_features(self):
        dag = load_feature_log(FIXTURES_DIR / "boolean_union.feature")
        assert len(dag) == 3

    def test_boolean_kind_is_boolean(self):
        dag = load_feature_log(FIXTURES_DIR / "boolean_union.feature")
        f = dag.get_feature("bool-1")
        assert f.kind == "boolean"
        assert f.params["op"] == "union"

    def test_refs_wired(self):
        dag = load_feature_log(FIXTURES_DIR / "boolean_union.feature")
        f = dag.get_feature("bool-1")
        assert f.inputs["a"].feature_id == "box-a"
        assert f.inputs["b"].feature_id == "box-b"

    def test_validate_body(self):
        body = body_from_feature_log(FIXTURES_DIR / "boolean_union.feature")
        vr = validate_body(body)
        assert vr["ok"], f"validate_body errors: {vr['errors']}"

    def test_oracle_volume(self):
        """Two disjoint boxes (5x5x5 each): total volume = 250."""
        body = body_from_feature_log(FIXTURES_DIR / "boolean_union.feature")
        vol = _body_volume(body)
        assert abs(vol - 250.0) < 1e-9

    def test_oracle_matches_worker(self):
        """Loaded union fixture must match the worker's union body."""
        loaded = body_from_feature_log(FIXTURES_DIR / "boolean_union.feature")
        dag = _fresh_dag()
        a = BoxFeature((0, 0, 0), 5.0, 5.0, 5.0)
        b = BoxFeature((10, 0, 0), 5.0, 5.0, 5.0)
        dag.add_feature(a)
        dag.add_feature(b)
        uni = BooleanFeature("union", FeatureRef(a.id), FeatureRef(b.id))
        dag.add_feature(uni)
        worker = dag.evaluate(uni.id)
        _assert_bodies_equal(loaded, worker)


# ===========================================================================
# 4. Cylinder+sphere fixture (two independent features — no boolean possible
#    between cylinder and sphere in the pure-Python kernel)
# ===========================================================================


class TestLoadCylinderSphereFixture:
    def test_dag_has_two_features(self):
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        assert len(dag) == 2

    def test_cylinder_kind(self):
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        f = dag.get_feature("cyl-1")
        assert f.kind == "cylinder"
        assert f.params["radius"] == pytest.approx(2.0)
        assert f.params["height"] == pytest.approx(6.0)

    def test_sphere_kind(self):
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        f = dag.get_feature("sph-1")
        assert f.kind == "sphere"
        assert f.params["radius"] == pytest.approx(3.0)

    def test_cylinder_validate_body(self):
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        dag.regenerate()
        body = dag.evaluate("cyl-1")
        vr = validate_body(body)
        assert vr["ok"], f"validate_body errors: {vr['errors']}"

    def test_sphere_validate_body(self):
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        dag.regenerate()
        body = dag.evaluate("sph-1")
        vr = validate_body(body)
        assert vr["ok"], f"validate_body errors: {vr['errors']}"

    def test_cylinder_euler_counts(self):
        """Cylinder: F=3 (lateral + 2 caps), V and E as per kernel."""
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        dag.regenerate()
        body = dag.evaluate("cyl-1")
        c = body.euler_counts()
        assert c["F"] == 3

    def test_oracle_cylinder_matches_worker(self):
        """Loaded cylinder must match the worker's cylinder body."""
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        dag.regenerate()
        loaded_cyl = dag.evaluate("cyl-1")
        dag2 = _fresh_dag()
        cyl = CylinderFeature((0, 0, 0), (0, 0, 1), 2.0, 6.0)
        dag2.add_feature(cyl)
        worker = dag2.evaluate(cyl.id)
        _assert_bodies_equal(loaded_cyl, worker)

    def test_oracle_sphere_matches_worker(self):
        """Loaded sphere must match the worker's sphere body."""
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        dag.regenerate()
        loaded_sph = dag.evaluate("sph-1")
        dag2 = _fresh_dag()
        sph = SphereFeature((20, 0, 0), 3.0)
        dag2.add_feature(sph)
        worker = dag2.evaluate(sph.id)
        _assert_bodies_equal(loaded_sph, worker)


# ===========================================================================
# 5. JSON string / bytes / dict source variants
# ===========================================================================


class TestSourceVariants:
    _LOG = {
        "version": 1,
        "features": [
            {
                "id": "box-1",
                "op": "box",
                "corner": [0, 0, 0],
                "dx": 2.0,
                "dy": 2.0,
                "dz": 2.0,
            }
        ],
    }

    def test_dict_source(self):
        body = body_from_feature_log(self._LOG)
        assert _body_volume(body) == pytest.approx(8.0)

    def test_str_source(self):
        body = body_from_feature_log(json.dumps(self._LOG))
        assert _body_volume(body) == pytest.approx(8.0)

    def test_bytes_source(self):
        body = body_from_feature_log(json.dumps(self._LOG).encode())
        assert _body_volume(body) == pytest.approx(8.0)

    def test_path_source(self, tmp_path):
        p = tmp_path / "test.feature"
        p.write_text(json.dumps(self._LOG), encoding="utf-8")
        body = body_from_feature_log(p)
        assert _body_volume(body) == pytest.approx(8.0)

    def test_str_path_source(self, tmp_path):
        p = tmp_path / "test2.feature"
        p.write_text(json.dumps(self._LOG), encoding="utf-8")
        body = body_from_feature_log(str(p))
        assert _body_volume(body) == pytest.approx(8.0)


# ===========================================================================
# 6. Error paths
# ===========================================================================


class TestErrorPaths:
    def test_invalid_json_raises(self):
        # String starting with '{' but not valid JSON.
        with pytest.raises(FeatureLogError, match="invalid JSON"):
            load_feature_log("{not-valid-json")

    def test_missing_id_raises(self):
        doc = {"version": 1, "features": [{"op": "box", "dx": 1, "dy": 1, "dz": 1, "corner": [0, 0, 0]}]}
        with pytest.raises(FeatureLogError, match="'id'"):
            load_feature_log(doc)

    def test_missing_op_raises(self):
        doc = {"version": 1, "features": [{"id": "b1", "dx": 1, "dy": 1, "dz": 1, "corner": [0, 0, 0]}]}
        with pytest.raises(FeatureLogError, match="'op'"):
            load_feature_log(doc)

    def test_missing_box_field_raises(self):
        doc = {"version": 1, "features": [{"id": "b1", "op": "box", "corner": [0, 0, 0], "dx": 1, "dy": 1}]}
        # missing "dz"
        with pytest.raises(FeatureLogError, match="dz"):
            load_feature_log(doc)

    def test_boolean_unknown_kind_raises(self):
        doc = {
            "version": 1,
            "features": [
                {"id": "a", "op": "box", "corner": [0, 0, 0], "dx": 1, "dy": 1, "dz": 1},
                {"id": "b", "op": "box", "corner": [2, 0, 0], "dx": 1, "dy": 1, "dz": 1},
                {"id": "c", "op": "boolean", "kind": "xor", "target_a_id": "a", "target_b_id": "b"},
            ],
        }
        with pytest.raises(FeatureLogError, match="xor"):
            load_feature_log(doc)

    def test_boolean_unknown_reference_raises(self):
        doc = {
            "version": 1,
            "features": [
                {"id": "a", "op": "box", "corner": [0, 0, 0], "dx": 1, "dy": 1, "dz": 1},
                {"id": "c", "op": "boolean", "kind": "union", "target_a_id": "a", "target_b_id": "MISSING"},
            ],
        }
        with pytest.raises(FeatureLogError, match="MISSING"):
            load_feature_log(doc)

    def test_empty_log_body_raises(self):
        with pytest.raises(FeatureLogError, match="no supported features"):
            body_from_feature_log({"version": 1, "features": []})

    def test_missing_file_raises(self):
        with pytest.raises(FeatureLogError, match="cannot open file"):
            load_feature_log("/tmp/__does_not_exist_gk61__.feature")

    def test_top_level_not_object_raises(self):
        with pytest.raises(FeatureLogError, match="top-level"):
            load_feature_log(json.dumps([1, 2, 3]))

    def test_features_not_array_raises(self):
        doc = {"version": 1, "features": "oops"}
        with pytest.raises(FeatureLogError, match="array"):
            load_feature_log(doc)

    def test_unsupported_op_skipped_with_warning(self):
        """Cloud-side ops like 'sweep1' are skipped with a warning, not an error."""
        doc = {
            "version": 1,
            "features": [
                {"id": "box-1", "op": "box", "corner": [0, 0, 0], "dx": 1, "dy": 1, "dz": 1},
                {"id": "sweep-1", "op": "sweep1", "profile_sketch_path": "/p.sketch", "path_sketch_path": "/r.sketch"},
            ],
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            dag = load_feature_log(doc)
        # Only the box was loaded (sweep1 skipped)
        assert len(dag) == 1
        assert "box-1" in dag
        assert len(caught) == 1
        assert "sweep1" in str(caught[0].message)


# ===========================================================================
# 7. Boolean op alias handling
# ===========================================================================


class TestBooleanOpAliases:
    _BOXES = [
        {"id": "a", "op": "box", "corner": [0, 0, 0], "dx": 5, "dy": 5, "dz": 5},
        {"id": "b", "op": "box", "corner": [10, 0, 0], "dx": 5, "dy": 5, "dz": 5},
    ]

    def _make_doc(self, kind: str) -> dict:
        return {
            "version": 1,
            "features": self._BOXES + [
                {"id": "c", "op": "boolean", "kind": kind,
                 "target_a_id": "a", "target_b_id": "b"}
            ],
        }

    def test_fuse_alias(self):
        dag = load_feature_log(self._make_doc("fuse"))
        f = dag.get_feature("c")
        assert f.params["op"] == "union"

    def test_cut_alias(self):
        dag = load_feature_log(self._make_doc("cut"))
        f = dag.get_feature("c")
        assert f.params["op"] == "difference"

    def test_common_alias(self):
        dag = load_feature_log(self._make_doc("common"))
        f = dag.get_feature("c")
        assert f.params["op"] == "intersection"

    def test_union_canonical(self):
        dag = load_feature_log(self._make_doc("union"))
        f = dag.get_feature("c")
        assert f.params["op"] == "union"

    def test_difference_canonical(self):
        dag = load_feature_log(self._make_doc("difference"))
        f = dag.get_feature("c")
        assert f.params["op"] == "difference"

    def test_intersection_canonical(self):
        dag = load_feature_log(self._make_doc("intersection"))
        f = dag.get_feature("c")
        assert f.params["op"] == "intersection"


# ===========================================================================
# 8. SUPPORTED_OPS sentinel
# ===========================================================================


class TestSupportedOps:
    def test_supported_ops_is_frozenset(self):
        assert isinstance(SUPPORTED_OPS, frozenset)

    def test_box_in_supported(self):
        assert "box" in SUPPORTED_OPS

    def test_cylinder_in_supported(self):
        assert "cylinder" in SUPPORTED_OPS

    def test_sphere_in_supported(self):
        assert "sphere" in SUPPORTED_OPS

    def test_boolean_in_supported(self):
        assert "boolean" in SUPPORTED_OPS

    def test_chamfer_in_supported(self):
        assert "chamfer_edge" in SUPPORTED_OPS

    def test_fillet_in_supported(self):
        assert "fillet_edge" in SUPPORTED_OPS

    def test_sweep1_not_supported(self):
        assert "sweep1" not in SUPPORTED_OPS


# ===========================================================================
# 9. DAG → .feature log round-trip (write direction)
# ===========================================================================


class TestDagToFeatureLog:
    def test_box_roundtrip(self):
        dag = _fresh_dag()
        box = BoxFeature((1.0, 2.0, 3.0), 4.0, 5.0, 6.0, id="my-box")
        dag.add_feature(box)
        doc = dag_to_feature_log(dag)
        assert doc["version"] == 1
        nodes = doc["features"]
        assert len(nodes) == 1
        n = nodes[0]
        assert n["op"] == "box"
        assert n["id"] == "my-box"
        assert n["corner"] == pytest.approx([1.0, 2.0, 3.0])
        assert n["dx"] == pytest.approx(4.0)

    def test_cylinder_roundtrip(self):
        dag = _fresh_dag()
        cyl = CylinderFeature((0, 0, 0), (0, 0, 1), 3.0, 8.0, id="my-cyl")
        dag.add_feature(cyl)
        doc = dag_to_feature_log(dag)
        n = doc["features"][0]
        assert n["op"] == "cylinder"
        assert n["radius"] == pytest.approx(3.0)
        assert n["height"] == pytest.approx(8.0)

    def test_sphere_roundtrip(self):
        dag = _fresh_dag()
        sph = SphereFeature((5.0, 5.0, 5.0), 2.0, id="my-sph")
        dag.add_feature(sph)
        doc = dag_to_feature_log(dag)
        n = doc["features"][0]
        assert n["op"] == "sphere"
        assert n["centre"] == pytest.approx([5.0, 5.0, 5.0])

    def test_boolean_roundtrip(self):
        dag = _fresh_dag()
        a = BoxFeature((0, 0, 0), 1, 1, 1, id="a")
        b = BoxFeature((2, 0, 0), 1, 1, 1, id="b")
        dag.add_feature(a)
        dag.add_feature(b)
        uni = BooleanFeature("union", FeatureRef(a.id), FeatureRef(b.id), id="u")
        dag.add_feature(uni)
        doc = dag_to_feature_log(dag)
        bool_node = next(n for n in doc["features"] if n["id"] == "u")
        assert bool_node["op"] == "boolean"
        assert bool_node["kind"] == "union"
        assert bool_node["target_a_id"] == "a"
        assert bool_node["target_b_id"] == "b"

    def test_chamfer_roundtrip(self):
        dag = _fresh_dag()
        box = BoxFeature((0, 0, 0), 2, 2, 2, id="box1")
        dag.add_feature(box)
        dag.evaluate(box.id)
        sel = PersistentSelector(box.id, "edge", "+Z/-Y")
        chamf = ChamferEdgeFeature(FeatureRef(box.id), sel, 0.1, id="ch1")
        dag.add_feature(chamf)
        doc = dag_to_feature_log(dag)
        cn = next(n for n in doc["features"] if n["id"] == "ch1")
        assert cn["op"] == "chamfer_edge"
        assert cn["target_id"] == "box1"
        assert cn["edge_role"] == "+Z/-Y"
        assert cn["width"] == pytest.approx(0.1)

    def test_full_roundtrip_load_back(self):
        """Serialise DAG → log → reload → same Body."""
        dag = _fresh_dag()
        box = BoxFeature((0, 0, 0), 3.0, 3.0, 3.0)
        dag.add_feature(box)
        body_orig = dag.evaluate(box.id)

        doc = dag_to_feature_log(dag)
        dag2 = load_feature_log(doc)
        dag2.regenerate()
        body_rt = dag2.evaluate(dag2.feature_ids()[0])
        _assert_bodies_equal(body_orig, body_rt)


# ===========================================================================
# 10. DAG load → set_param → regenerate (parametric edit round-trip)
# ===========================================================================


class TestParametricEditAfterLoad:
    def test_set_param_and_regenerate(self):
        """Load the box fixture, change dx, regenerate — volume scales correctly."""
        dag = load_feature_log(FIXTURES_DIR / "box_simple.feature")
        dag.regenerate()
        dag.set_param("box-1", "dx", 20.0)
        dag.regenerate()
        body = dag.evaluate("box-1")
        vol = _body_volume(body)
        # New volume: dx=20, dy=5, dz=3 = 300
        assert abs(vol - 300.0) < 1e-9

    def test_chamfer_survives_box_edit(self):
        """Load chamfer fixture, edit box dimension, chamfer must re-apply."""
        dag = load_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        dag.regenerate()
        dag.set_param("box-1", "dx", 8.0)
        dag.regenerate()
        body = dag.evaluate("chamfer-1")
        vr = validate_body(body)
        assert vr["ok"], f"validate_body errors after parametric edit: {vr['errors']}"
        # Topology must still be the chamfered pattern: V=10, E=15, F=7
        c = body.euler_counts()
        assert c["V"] == 10
        assert c["E"] == 15
        assert c["F"] == 7


# ===========================================================================
# 11. Fillet edge feature round-trip (from dict, not a fixture file)
# ===========================================================================


class TestFilletEdgeRoundTrip:
    def test_fillet_load_and_oracle(self):
        """Build a box-fillet DAG, serialise to log, reload, verify same body."""
        dag = _fresh_dag()
        box = BoxFeature((0, 0, 0), 4.0, 4.0, 4.0, id="box-f")
        dag.add_feature(box)
        dag.evaluate(box.id)
        sel = PersistentSelector(box.id, "edge", "+Z/-Y")
        fillet = FilletEdgeFeature(FeatureRef(box.id), sel, radius=0.3, id="fillet-f")
        dag.add_feature(fillet)
        body_orig = dag.evaluate(fillet.id)
        vr = validate_body(body_orig)
        assert vr["ok"]

        # Serialise → reload → re-evaluate
        doc = dag_to_feature_log(dag)
        dag2 = load_feature_log(doc)
        dag2.regenerate()
        body_rt = dag2.evaluate("fillet-f")
        _assert_bodies_equal(body_orig, body_rt)


# ===========================================================================
# 12. Topological order preserved
# ===========================================================================


class TestTopologicalOrder:
    def test_topo_order_respects_dependencies(self):
        """The loaded DAG evaluates features in dependency order."""
        dag = load_feature_log(FIXTURES_DIR / "boolean_union.feature")
        order = dag.topological_order()
        assert order.index("box-a") < order.index("bool-1")
        assert order.index("box-b") < order.index("bool-1")

    def test_chamfer_after_box_in_topo(self):
        dag = load_feature_log(FIXTURES_DIR / "box_chamfer.feature")
        order = dag.topological_order()
        assert order.index("box-1") < order.index("chamfer-1")

    def test_cylinder_sphere_independent_order(self):
        """Cylinder and sphere have no dependencies — both appear in the order."""
        dag = load_feature_log(FIXTURES_DIR / "cylinder_sphere.feature")
        order = dag.topological_order()
        assert "cyl-1" in order
        assert "sph-1" in order
