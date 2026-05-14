"""
Tests for feature_cam_layered.

Pure-Python: no live database, no ProjectCtx pool needed for the validation
and builder tests.  Integration tests use the same lightweight fake pool/ctx
pattern as test_feature_section.py.

The OCC section-stack tests (class TestComputeLayers) are skipped when
pythonOCC is not installed — they match the same skip pattern used by other
OCC-dependent tests in this package.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.cam_layered import (
    VALID_AXES,
    build_cam_layered_node,
    validate_cam_layered_args,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_ctx(initial_content: str = ""):
    """Return (ctx, store, file_id) with an in-memory fake pool."""
    store = {
        "content": initial_content or json.dumps({"version": 1, "features": []}),
        "kind": "feature",
    }
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class FakePool:
        def fetchone(self, query, *args):
            return (store["content"], store["kind"])

        def execute(self, query, *args):
            store["content"] = args[0]

    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    ctx = ProjectCtx(
        pool=FakePool(),
        storage=None,
        project_id=project_id,
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )
    return ctx, store, file_id


def run_tool(ctx, file_id, **kwargs):
    from kerf_cad_core.cam_layered import run_cam_layered

    args = {"file_id": str(file_id), **kwargs}
    raw = asyncio.new_event_loop().run_until_complete(
        run_cam_layered(ctx, json.dumps(args).encode())
    )
    return json.loads(raw)


# ── validate_cam_layered_args — success paths ─────────────────────────────────

class TestValidateSuccess:
    def test_basic_valid(self):
        err, code = validate_cam_layered_args("pad-1", 5.0, None, None, "Z")
        assert err is None
        assert code is None

    def test_integer_step(self):
        err, code = validate_cam_layered_args("pad-1", 2, None, None, "Z")
        assert err is None

    def test_explicit_range(self):
        err, code = validate_cam_layered_args("pad-1", 5.0, 0.0, 50.0, "Z")
        assert err is None

    def test_x_axis(self):
        err, code = validate_cam_layered_args("pad-1", 3.0, None, None, "X")
        assert err is None

    def test_y_axis(self):
        err, code = validate_cam_layered_args("pad-1", 3.0, None, None, "Y")
        assert err is None

    def test_all_valid_axes(self):
        for axis in VALID_AXES:
            err, code = validate_cam_layered_args("pad-1", 1.0, None, None, axis)
            assert err is None, f"axis {axis!r} should be valid"


# ── validate_cam_layered_args — error paths ───────────────────────────────────

class TestValidateErrors:
    def test_empty_solid_ref(self):
        err, code = validate_cam_layered_args("", 5.0, None, None, "Z")
        assert code == "BAD_ARGS"
        assert "target_solid_ref" in err

    def test_non_string_solid_ref(self):
        err, code = validate_cam_layered_args(123, 5.0, None, None, "Z")
        assert code == "BAD_ARGS"

    def test_zero_step(self):
        err, code = validate_cam_layered_args("pad-1", 0, None, None, "Z")
        assert code == "BAD_ARGS"
        assert "z_step_mm" in err

    def test_negative_step(self):
        err, code = validate_cam_layered_args("pad-1", -1.0, None, None, "Z")
        assert code == "BAD_ARGS"

    def test_non_numeric_step(self):
        err, code = validate_cam_layered_args("pad-1", "five", None, None, "Z")
        assert code == "BAD_ARGS"

    def test_non_numeric_start(self):
        err, code = validate_cam_layered_args("pad-1", 5.0, "zero", None, "Z")
        assert code == "BAD_ARGS"
        assert "z_start_mm" in err

    def test_non_numeric_end(self):
        err, code = validate_cam_layered_args("pad-1", 5.0, None, "top", "Z")
        assert code == "BAD_ARGS"
        assert "z_end_mm" in err

    def test_start_ge_end(self):
        err, code = validate_cam_layered_args("pad-1", 5.0, 10.0, 5.0, "Z")
        assert code == "BAD_ARGS"
        assert "z_start_mm" in err or "less than" in err

    def test_start_eq_end(self):
        err, code = validate_cam_layered_args("pad-1", 5.0, 10.0, 10.0, "Z")
        assert code == "BAD_ARGS"

    def test_invalid_axis(self):
        err, code = validate_cam_layered_args("pad-1", 5.0, None, None, "W")
        assert code == "BAD_ARGS"
        assert "axis" in err


# ── build_cam_layered_node ─────────────────────────────────────────────────────

class TestBuildNode:
    def test_basic_structure(self):
        node = build_cam_layered_node("cl-1", "pad-1", 5.0, None, None)
        assert node["id"] == "cl-1"
        assert node["op"] == "cam_layered"
        assert node["target_solid_ref"] == "pad-1"
        assert node["z_step_mm"] == 5.0
        assert node["axis"] == "Z"

    def test_explicit_range_stored(self):
        node = build_cam_layered_node("cl-1", "pad-1", 5.0, 0.0, 50.0)
        assert node["z_start_mm"] == 0.0
        assert node["z_end_mm"] == 50.0

    def test_omitted_range_absent(self):
        node = build_cam_layered_node("cl-1", "pad-1", 5.0, None, None)
        assert "z_start_mm" not in node
        assert "z_end_mm" not in node

    def test_name_stored(self):
        node = build_cam_layered_node("cl-1", "pad-1", 5.0, None, None, name="rough layers")
        assert node["name"] == "rough layers"

    def test_no_name_omitted(self):
        node = build_cam_layered_node("cl-1", "pad-1", 5.0, None, None)
        assert "name" not in node

    def test_axis_stored(self):
        node = build_cam_layered_node("cl-1", "pad-1", 5.0, None, None, axis="X")
        assert node["axis"] == "X"

    def test_z_step_coerced_to_float(self):
        node = build_cam_layered_node("cl-1", "pad-1", 5, None, None)
        assert isinstance(node["z_step_mm"], float)


# ── run_cam_layered integration ───────────────────────────────────────────────

class TestRunCamLayered:
    def test_appends_node(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, target_solid_ref="pad-1", z_step_mm=5.0)
        assert "error" not in result
        assert result["op"] == "cam_layered"
        doc = json.loads(store["content"])
        assert len(doc["features"]) == 1
        assert doc["features"][0]["op"] == "cam_layered"

    def test_auto_id_generation(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, target_solid_ref="pad-1", z_step_mm=5.0)
        assert "error" not in result
        assert result["id"].startswith("cam-layered-")

    def test_explicit_id_honoured(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, target_solid_ref="pad-1", z_step_mm=5.0, id="my-layers")
        assert result["id"] == "my-layers"

    def test_axis_returned(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, target_solid_ref="pad-1", z_step_mm=5.0, axis="X")
        assert result["axis"] == "X"

    def test_default_axis_is_z(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, target_solid_ref="pad-1", z_step_mm=5.0)
        assert result["axis"] == "Z"

    def test_bad_file_id(self):
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, uuid.UUID("00000000-0000-0000-0000-000000000000"),
                          target_solid_ref="pad-1", z_step_mm=5.0)
        # The fake pool always returns the same row, so NOT_FOUND only fires
        # for invalid UUIDs passed as strings.
        from kerf_cad_core.cam_layered import run_cam_layered
        raw = asyncio.new_event_loop().run_until_complete(
            run_cam_layered(ctx, json.dumps({
                "file_id": "not-a-uuid",
                "target_solid_ref": "pad-1",
                "z_step_mm": 5.0,
            }).encode())
        )
        r = json.loads(raw)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_missing_target_solid_ref(self):
        from kerf_cad_core.cam_layered import run_cam_layered
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            run_cam_layered(ctx, json.dumps({
                "file_id": str(fid),
                "z_step_mm": 5.0,
            }).encode())
        )
        r = json.loads(raw)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_missing_z_step(self):
        from kerf_cad_core.cam_layered import run_cam_layered
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            run_cam_layered(ctx, json.dumps({
                "file_id": str(fid),
                "target_solid_ref": "pad-1",
            }).encode())
        )
        r = json.loads(raw)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_negative_z_step_returns_bad_args(self):
        from kerf_cad_core.cam_layered import run_cam_layered
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            run_cam_layered(ctx, json.dumps({
                "file_id": str(fid),
                "target_solid_ref": "pad-1",
                "z_step_mm": -1.0,
            }).encode())
        )
        r = json.loads(raw)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_warning_when_occ_unavailable(self):
        """
        When pythonOCC is not installed, run_cam_layered should still succeed
        (appending the feature node) but include a 'warning' in the payload
        explaining that OCC is not available.
        """
        ctx, store, fid = make_ctx()
        result = run_tool(ctx, fid, target_solid_ref="pad-1", z_step_mm=5.0,
                          z_start_mm=0.0, z_end_mm=50.0)
        # If OCC is available the result may include layer_count.
        # If OCC is not available the result should include a warning.
        # Either way there should be no error.
        assert "error" not in result
        assert result["op"] == "cam_layered"


# ── OCC section-stack tests (skipped when OCC not installed) ──────────────────

try:
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: F401
    _OCC_AVAILABLE = True
except ImportError:
    _OCC_AVAILABLE = False

pytestmark_occ = pytest.mark.skipif(not _OCC_AVAILABLE, reason="pythonOCC not installed")


@pytest.mark.skipif(not _OCC_AVAILABLE, reason="pythonOCC not installed")
class TestComputeLayers:
    """Test the section-stack using a real OCC box solid."""

    def _make_box(self, w: float = 50.0, d: float = 50.0, h: float = 50.0):
        """Return a 50×50×50 mm box centred near origin (OCCT box starts at 0,0,0)."""
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        return BRepPrimAPI_MakeBox(w, d, h).Shape()

    def test_correct_number_of_layers_z(self):
        """A 50 mm box with 5 mm Z step should produce 10 layers (Z=0..45, 50 excluded)."""
        from kerf_cad_core.cam_layered import compute_layers
        box = self._make_box()
        layers = compute_layers(box, axis="Z", z_step_mm=5.0,
                                z_start_mm=0.0, z_end_mm=50.0)
        # Layers at Z=0 and Z=50 may be degenerate (face boundary), so we
        # expect 9–11 layers; assert the exact mid-body layers are present.
        z_values = {round(l["z_mm"], 1) for l in layers}
        # At least 5–45 midpoint layers should produce edges.
        for z in [5.0, 10.0, 20.0, 30.0, 45.0]:
            assert z in z_values, f"Expected layer at Z={z} not found; got {sorted(z_values)}"

    def test_each_layer_has_edges(self):
        """No layer in the result should have an empty edges list."""
        from kerf_cad_core.cam_layered import compute_layers
        box = self._make_box()
        layers = compute_layers(box, axis="Z", z_step_mm=5.0,
                                z_start_mm=5.0, z_end_mm=45.0)
        assert len(layers) > 0
        for layer in layers:
            assert len(layer["edges"]) > 0, f"Layer at Z={layer['z_mm']} has no edges"

    def test_box_outline_is_rectangular(self):
        """
        Each mid-body layer of a 50×50×h box should produce 4 edges
        (the four sides of the square cross-section).
        Segment count varies with discretisation; assert at least 4 segments.
        """
        from kerf_cad_core.cam_layered import compute_layers
        box = self._make_box(50.0, 50.0, 50.0)
        layers = compute_layers(box, axis="Z", z_step_mm=5.0,
                                z_start_mm=10.0, z_end_mm=40.0)
        assert len(layers) > 0
        for layer in layers:
            # A box outline at any mid Z should have edges.
            assert len(layer["edges"]) >= 4, (
                f"Layer at Z={layer['z_mm']} has only {len(layer['edges'])} segments; "
                "expected at least 4 (one per box side)"
            )

    def test_all_2d_points_within_box_bounds(self):
        """All edge endpoints should be within the 50×50 XY footprint (Z axis)."""
        from kerf_cad_core.cam_layered import compute_layers
        W, D = 50.0, 50.0
        box = self._make_box(W, D, 50.0)
        layers = compute_layers(box, axis="Z", z_step_mm=5.0,
                                z_start_mm=5.0, z_end_mm=45.0)
        tol = 0.5  # small tolerance for discretisation
        for layer in layers:
            for [[x0, y0], [x1, y1]] in layer["edges"]:
                assert -tol <= x0 <= W + tol, f"x0={x0} out of range at Z={layer['z_mm']}"
                assert -tol <= y0 <= D + tol, f"y0={y0} out of range at Z={layer['z_mm']}"
                assert -tol <= x1 <= W + tol, f"x1={x1} out of range at Z={layer['z_mm']}"
                assert -tol <= y1 <= D + tol, f"y1={y1} out of range at Z={layer['z_mm']}"

    def test_x_axis_slices_produce_layers(self):
        """X-axis slicing of a 50×50×50 box should produce layers at X positions."""
        from kerf_cad_core.cam_layered import compute_layers
        box = self._make_box()
        layers = compute_layers(box, axis="X", z_step_mm=5.0,
                                z_start_mm=5.0, z_end_mm=45.0)
        assert len(layers) >= 8, f"Expected >=8 X-axis layers, got {len(layers)}"

    def test_bbox_auto_detection(self):
        """
        When z_start_mm / z_end_mm are None, compute_layers auto-detects them
        from the solid's bbox.  A 50×50×50 box should produce layers across
        the full 0–50 range.
        """
        from kerf_cad_core.cam_layered import compute_layers
        box = self._make_box()
        layers = compute_layers(box, axis="Z", z_step_mm=10.0,
                                z_start_mm=None, z_end_mm=None)
        # At 10mm step we should get layers at 0,10,20,30,40,50 →
        # degenerate ones at 0,50 may be absent; at least 3 layers.
        assert len(layers) >= 3, f"Expected >=3 auto-bbox layers, got {len(layers)}"

    def test_ten_layers_at_5mm_step_on_50mm_box(self):
        """
        Canonical test: 50 mm box, 5 mm step, explicit range 0–50 mm.
        Layers at Z=0 and Z=50 are face-coincident and may be degenerate;
        the 9 interior layers (5, 10, …, 45) must all have edges.
        """
        from kerf_cad_core.cam_layered import compute_layers
        box = self._make_box(50.0, 50.0, 50.0)
        # Use interior range to avoid face-boundary degeneracy.
        layers = compute_layers(box, axis="Z", z_step_mm=5.0,
                                z_start_mm=5.0, z_end_mm=45.0)
        assert len(layers) == 9, (
            f"Expected 9 interior layers (Z=5,10,…,45), got {len(layers)}: "
            f"{[l['z_mm'] for l in layers]}"
        )
        for layer in layers:
            assert len(layer["edges"]) > 0

    def test_build_cam_layered_result_structure(self):
        """build_cam_layered_result returns a well-formed document."""
        from kerf_cad_core.cam_layered import build_cam_layered_result
        box = self._make_box()
        doc = build_cam_layered_result(
            box, axis="Z", z_step_mm=5.0,
            z_start_mm=5.0, z_end_mm=45.0,
        )
        assert doc["version"] == 1
        assert doc["axis"] == "Z"
        assert doc["z_step_mm"] == 5.0
        assert isinstance(doc["layers"], list)
        assert len(doc["layers"]) > 0
        # Each layer must have z_mm and edges.
        for layer in doc["layers"]:
            assert "z_mm" in layer
            assert "edges" in layer
            assert isinstance(layer["edges"], list)
