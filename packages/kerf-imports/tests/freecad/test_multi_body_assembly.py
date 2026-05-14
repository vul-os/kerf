"""
test_multi_body_assembly.py — T5 Multi-Body .FCStd → .assembly tests.

Tests:
  - Single-body document returns None (no assembly needed).
  - Two-body document emits two Components.
  - Component feature_path is resolved from FeaturePayload labels.
  - Placement → 4×4 matrix conversion (identity, pure translation, quaternion rotation).
  - Three-body document emits three Components.
  - freecad_ref provenance is correct.
"""
from __future__ import annotations

import math
import pytest

from kerf_imports.freecad.types import FCStdDocument, FCStdObject
from kerf_imports.freecad.brep_importer import FeaturePayload, FeatureNode
from kerf_imports.freecad.assembly import build_assembly, _placement_to_matrix


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(*objects, brep_blobs=None):
    return FCStdDocument(
        schema_version=4,
        program_version="0.21R3",
        objects=list(objects),
        properties={},
        brep_blobs=brep_blobs or {},
        raw_xml={},
    )


def _body(name, label=None, placement=None):
    props = {}
    if placement is not None:
        props["Placement"] = placement
    return FCStdObject(
        name=name,
        type="PartDesign::Body",
        label=label or name,
        properties=props,
    )


def _fp(body_name, body_label=None):
    """Minimal FeaturePayload for testing."""
    return FeaturePayload(
        body_name=body_name,
        body_label=body_label or body_name,
        nodes=[FeatureNode(kind="import_brep", params={"asset_id": None})],
    )


def _placement(px=0, py=0, pz=0, qw=1, qx=0, qy=0, qz=0):
    return {"Px": px, "Py": py, "Pz": pz, "Q0": qw, "Q1": qx, "Q2": qy, "Q3": qz}


# ---------------------------------------------------------------------------
# Single-body: no assembly
# ---------------------------------------------------------------------------

class TestSingleBody:
    def test_single_body_returns_none(self):
        doc = _make_doc(_body("Body"))
        result = build_assembly(doc)
        assert result is None

    def test_empty_doc_returns_none(self):
        doc = _make_doc()
        result = build_assembly(doc)
        assert result is None


# ---------------------------------------------------------------------------
# Two-body: assembly emitted
# ---------------------------------------------------------------------------

class TestTwoBodies:
    def _build(self, placements=None):
        b1 = _body("Body", "BodyOne", placements[0] if placements else None)
        b2 = _body("Body001", "BodyTwo", placements[1] if placements else None)
        doc = _make_doc(b1, b2)
        fps = [_fp("Body", "BodyOne"), _fp("Body001", "BodyTwo")]
        return build_assembly(doc, fps)

    def test_returns_dict(self):
        result = self._build()
        assert isinstance(result, dict)

    def test_has_components_key(self):
        result = self._build()
        assert "components" in result

    def test_two_components(self):
        result = self._build()
        assert len(result["components"]) == 2

    def test_component_names(self):
        result = self._build()
        names = {c["name"] for c in result["components"]}
        assert names == {"BodyOne", "BodyTwo"}

    def test_component_feature_paths(self):
        result = self._build()
        paths = {c["feature_path"] for c in result["components"]}
        assert "/BodyOne.feature" in paths
        assert "/BodyTwo.feature" in paths

    def test_component_ids_unique(self):
        result = self._build()
        ids = [c["id"] for c in result["components"]]
        assert len(set(ids)) == 2

    def test_freecad_ref_bodies_list(self):
        result = self._build()
        ref = result["freecad_ref"]
        assert "Body" in ref["bodies"]
        assert "Body001" in ref["bodies"]

    def test_freecad_ref_program_version(self):
        result = self._build()
        assert result["freecad_ref"]["program_version"] == "0.21R3"


# ---------------------------------------------------------------------------
# Three-body document
# ---------------------------------------------------------------------------

class TestThreeBodies:
    def test_three_bodies_three_components(self):
        b1 = _body("Body")
        b2 = _body("Body001")
        b3 = _body("Body002")
        doc = _make_doc(b1, b2, b3)
        result = build_assembly(doc)
        assert result is not None
        assert len(result["components"]) == 3


# ---------------------------------------------------------------------------
# Transform / placement tests
# ---------------------------------------------------------------------------

class TestPlacementToMatrix:
    def test_none_placement_is_identity(self):
        m = _placement_to_matrix(None)
        identity = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        for r in range(4):
            for c in range(4):
                assert abs(m[r][c] - identity[r][c]) < 1e-9

    def test_pure_translation(self):
        p = _placement(px=10, py=20, pz=30)
        m = _placement_to_matrix(p)
        assert abs(m[0][3] - 10.0) < 1e-9
        assert abs(m[1][3] - 20.0) < 1e-9
        assert abs(m[2][3] - 30.0) < 1e-9
        # Rotation part should be identity
        assert abs(m[0][0] - 1.0) < 1e-9
        assert abs(m[1][1] - 1.0) < 1e-9
        assert abs(m[2][2] - 1.0) < 1e-9

    def test_identity_quaternion(self):
        """Identity quaternion (w=1, x=y=z=0) → identity rotation."""
        p = _placement(qw=1, qx=0, qy=0, qz=0)
        m = _placement_to_matrix(p)
        assert abs(m[0][0] - 1.0) < 1e-9
        assert abs(m[1][1] - 1.0) < 1e-9
        assert abs(m[2][2] - 1.0) < 1e-9
        assert abs(m[0][1]) < 1e-9
        assert abs(m[0][2]) < 1e-9

    def test_90_degree_z_rotation(self):
        """90° rotation around Z: quaternion (w=cos45°, x=0, y=0, z=sin45°)."""
        angle = math.pi / 2
        qw = math.cos(angle / 2)
        qz = math.sin(angle / 2)
        p = _placement(qw=qw, qx=0, qy=0, qz=qz)
        m = _placement_to_matrix(p)
        # Column 0 of rotation should point in ~-Y direction after 90° Z rotation
        # R * [1,0,0] should give ~[0,1,0]
        assert abs(m[0][0] - 0.0) < 1e-9  # x' = 0
        assert abs(m[1][0] - 1.0) < 1e-9  # y' = 1
        assert abs(m[2][0] - 0.0) < 1e-9  # z' = 0

    def test_matrix_is_4x4(self):
        m = _placement_to_matrix(None)
        assert len(m) == 4
        for row in m:
            assert len(row) == 4

    def test_last_row_is_0001(self):
        """Affine transform: last row must be [0, 0, 0, 1]."""
        p = _placement(px=5, py=3, pz=1, qw=0.707, qx=0, qy=0.707, qz=0)
        m = _placement_to_matrix(p)
        assert abs(m[3][0]) < 1e-6
        assert abs(m[3][1]) < 1e-6
        assert abs(m[3][2]) < 1e-6
        assert abs(m[3][3] - 1.0) < 1e-6

    def test_axis_angle_form(self):
        """Axis + angle placement form (FreeCAD older files)."""
        p = {"Px": 0, "Py": 0, "Pz": 0, "Ax": 0, "Ay": 0, "Az": 1, "A": math.pi / 2}
        m = _placement_to_matrix(p)
        # Should be 90° Z rotation
        assert abs(m[0][0] - 0.0) < 1e-9
        assert abs(m[1][0] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Component structure / freecad_ref per component
# ---------------------------------------------------------------------------

class TestComponentStructure:
    def test_each_component_has_freecad_ref(self):
        b1 = _body("Body")
        b2 = _body("Body001")
        doc = _make_doc(b1, b2)
        result = build_assembly(doc)
        for c in result["components"]:
            assert "freecad_ref" in c
            assert c["freecad_ref"]["type"] == "PartDesign::Body"

    def test_each_component_has_transform(self):
        b1 = _body("Body", placement=_placement(px=5))
        b2 = _body("Body001", placement=_placement(px=15))
        doc = _make_doc(b1, b2)
        result = build_assembly(doc)
        for c in result["components"]:
            assert "transform" in c
            assert len(c["transform"]) == 4

    def test_translation_preserved_in_component(self):
        b1 = _body("Body", placement=_placement(px=10, py=20, pz=30))
        b2 = _body("Body001")
        doc = _make_doc(b1, b2)
        result = build_assembly(doc)
        c1 = next(c for c in result["components"] if c["freecad_ref"]["name"] == "Body")
        assert abs(c1["transform"][0][3] - 10.0) < 1e-9
        assert abs(c1["transform"][1][3] - 20.0) < 1e-9
        assert abs(c1["transform"][2][3] - 30.0) < 1e-9
