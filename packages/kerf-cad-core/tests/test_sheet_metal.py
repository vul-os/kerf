"""
Tests for the sheet_metal_flange (T-1), sheet_metal_unfold (T-2), and
sheet_metal_flat_pattern (T-3) tools.

Pure-Python: no database, no OCCT, no ProjectCtx required for validation /
schema tests.  The integration tests that actually write a feature node use a
lightweight in-memory fake pool, identical to the pattern in test_feature_loft.py.
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.sheet_metal import (
    validate_flange_args,
    run_sheet_metal_flange,
    sheet_metal_flange_spec,
    compute_unfold,
    run_sheet_metal_unfold,
    sheet_metal_unfold_spec,
    _flat_pattern_dxf_r12,
    run_sheet_metal_flat_pattern,
    sheet_metal_flat_pattern_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(initial_content: str = ""):
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


def _run_tool(ctx, file_id, **kwargs):
    a = {"file_id": str(file_id), **kwargs}
    raw = asyncio.new_event_loop().run_until_complete(
        run_sheet_metal_flange(ctx, json.dumps(a).encode())
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# validate_flange_args — pure validation, no DB, no OCCT
# ---------------------------------------------------------------------------

class TestValidateFlangeArgs:
    """Unit-test the validation helper in isolation."""

    VALID = dict(
        edge_ref="top-front",
        flange_length=25.0,
        bend_angle_deg=90.0,
        bend_radius=2.0,
        thickness=1.5,
        k_factor=0.44,
        base_width=100.0,
        base_depth=80.0,
    )

    def _call(self, **overrides):
        kw = {**self.VALID, **overrides}
        return validate_flange_args(**kw)

    # --- Happy path ---

    def test_valid_90deg(self):
        err, code = self._call()
        assert err is None and code is None

    def test_valid_135deg(self):
        err, code = self._call(bend_angle_deg=135.0)
        assert err is None and code is None

    def test_valid_180deg_boundary(self):
        err, code = self._call(bend_angle_deg=180.0)
        assert err is None and code is None

    def test_k_factor_boundary_lo(self):
        # 0.01 is the practical minimum
        err, code = self._call(k_factor=0.01)
        assert err is None and code is None

    def test_k_factor_boundary_hi(self):
        err, code = self._call(k_factor=0.99)
        assert err is None and code is None

    # --- k_factor out of range ---

    def test_k_factor_zero_rejected(self):
        err, code = self._call(k_factor=0.0)
        assert err is not None
        assert code == "BAD_ARGS"
        assert "k_factor" in err

    def test_k_factor_one_rejected(self):
        err, code = self._call(k_factor=1.0)
        assert err is not None
        assert code == "BAD_ARGS"
        assert "k_factor" in err

    def test_k_factor_negative_rejected(self):
        err, code = self._call(k_factor=-0.1)
        assert err is not None
        assert code == "BAD_ARGS"

    def test_k_factor_gt_1_rejected(self):
        err, code = self._call(k_factor=1.5)
        assert err is not None
        assert code == "BAD_ARGS"

    # --- bend_angle_deg out of range ---

    def test_angle_zero_rejected(self):
        err, code = self._call(bend_angle_deg=0.0)
        assert err is not None
        assert code == "BAD_ARGS"
        assert "bend_angle_deg" in err

    def test_angle_negative_rejected(self):
        err, code = self._call(bend_angle_deg=-45.0)
        assert err is not None
        assert code == "BAD_ARGS"

    def test_angle_181_rejected(self):
        err, code = self._call(bend_angle_deg=181.0)
        assert err is not None
        assert code == "BAD_ARGS"

    # --- edge_ref required ---

    def test_empty_edge_ref_rejected(self):
        err, code = self._call(edge_ref="")
        assert err is not None
        assert code == "BAD_ARGS"
        assert "edge_ref" in err

    def test_whitespace_edge_ref_rejected(self):
        err, code = self._call(edge_ref="   ")
        assert err is not None
        assert code == "BAD_ARGS"

    # --- positive length / thickness / radius ---

    def test_flange_length_zero_rejected(self):
        err, code = self._call(flange_length=0.0)
        assert err is not None and code == "BAD_ARGS"
        assert "flange_length" in err

    def test_flange_length_negative_rejected(self):
        err, code = self._call(flange_length=-5.0)
        assert err is not None and code == "BAD_ARGS"

    def test_thickness_zero_rejected(self):
        err, code = self._call(thickness=0.0)
        assert err is not None and code == "BAD_ARGS"
        assert "thickness" in err

    def test_bend_radius_zero_rejected(self):
        err, code = self._call(bend_radius=0.0)
        assert err is not None and code == "BAD_ARGS"
        assert "bend_radius" in err

    def test_base_width_zero_rejected(self):
        err, code = self._call(base_width=0.0)
        assert err is not None and code == "BAD_ARGS"
        assert "base_width" in err

    def test_base_depth_negative_rejected(self):
        err, code = self._call(base_depth=-10.0)
        assert err is not None and code == "BAD_ARGS"
        assert "base_depth" in err


# ---------------------------------------------------------------------------
# ToolSpec schema check
# ---------------------------------------------------------------------------

class TestToolSpec:
    def test_name(self):
        assert sheet_metal_flange_spec.name == "sheet_metal_flange"

    def test_required_fields(self):
        req = sheet_metal_flange_spec.input_schema.get("required", [])
        for field in ["file_id", "edge_ref", "flange_length", "bend_angle_deg",
                      "bend_radius", "thickness", "base_width", "base_depth"]:
            assert field in req, f"'{field}' missing from required"

    def test_k_factor_in_properties(self):
        props = sheet_metal_flange_spec.input_schema.get("properties", {})
        assert "k_factor" in props

    def test_description_mentions_unfold_deferred(self):
        assert "T-2" in sheet_metal_flange_spec.description or \
               "unfold" in sheet_metal_flange_spec.description.lower()


# ---------------------------------------------------------------------------
# run_sheet_metal_flange — integration tests with fake DB
# ---------------------------------------------------------------------------

class TestRunSheetMetalFlange:

    def _make(self, **kw):
        ctx, store, fid = _make_ctx()
        result = _run_tool(
            ctx, fid,
            edge_ref=kw.get("edge_ref", "top-front"),
            flange_length=kw.get("flange_length", 25.0),
            bend_angle_deg=kw.get("bend_angle_deg", 90.0),
            bend_radius=kw.get("bend_radius", 2.0),
            thickness=kw.get("thickness", 1.5),
            k_factor=kw.get("k_factor", 0.44),
            base_width=kw.get("base_width", 100.0),
            base_depth=kw.get("base_depth", 80.0),
        )
        return result, store

    def test_success_minimal(self):
        result, store = self._make()
        # ok_payload returns the dict directly (no "ok" key);
        # absence of "error" key signals success.
        assert "error" not in result
        assert "op" in result

    def test_node_appended_to_file(self):
        result, store = self._make()
        assert "error" not in result
        doc = json.loads(store["content"])
        features = doc.get("features", [])
        assert len(features) == 1
        assert features[0]["op"] == "sheet_metal_flange"

    def test_node_id_auto_generated(self):
        _, store = self._make()
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["id"].startswith("sheet_metal_flange-")

    def test_all_params_stored(self):
        result, store = self._make(
            edge_ref="top-back",
            flange_length=30.0,
            bend_angle_deg=120.0,
            bend_radius=3.0,
            thickness=2.0,
            k_factor=0.38,
            base_width=150.0,
            base_depth=100.0,
        )
        assert "error" not in result
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["edge_ref"] == "top-back"
        assert node["flange_length"] == 30.0
        assert node["bend_angle_deg"] == 120.0
        assert node["bend_radius"] == 3.0
        assert node["thickness"] == 2.0
        assert abs(node["k_factor"] - 0.38) < 1e-9
        assert node["base_width"] == 150.0
        assert node["base_depth"] == 100.0

    def test_explicit_id(self):
        ctx, store, fid = _make_ctx()
        result = _run_tool(
            ctx, fid,
            id="my-flange-42",
            edge_ref="top-left",
            flange_length=10.0,
            bend_angle_deg=90.0,
            bend_radius=1.0,
            thickness=1.0,
            k_factor=0.44,
            base_width=60.0,
            base_depth=40.0,
        )
        assert "error" not in result
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"] == "my-flange-42"

    def test_bad_file_id(self):
        ctx, _, _ = _make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            run_sheet_metal_flange(ctx, json.dumps({
                "file_id": "not-a-uuid",
                "edge_ref": "top-front",
                "flange_length": 10.0,
                "bend_angle_deg": 90.0,
                "bend_radius": 1.0,
                "thickness": 1.0,
                "k_factor": 0.44,
                "base_width": 50.0,
                "base_depth": 50.0,
            }).encode())
        )
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_k_factor_one_rejected_via_runner(self):
        ctx, _, fid = _make_ctx()
        result = _run_tool(
            ctx, fid,
            edge_ref="top-front",
            flange_length=10.0,
            bend_angle_deg=90.0,
            bend_radius=1.0,
            thickness=1.0,
            k_factor=1.0,  # invalid
            base_width=50.0,
            base_depth=50.0,
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_angle_0_rejected_via_runner(self):
        ctx, _, fid = _make_ctx()
        result = _run_tool(
            ctx, fid,
            edge_ref="top-front",
            flange_length=10.0,
            bend_angle_deg=0.0,  # invalid
            bend_radius=1.0,
            thickness=1.0,
            k_factor=0.44,
            base_width=50.0,
            base_depth=50.0,
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_empty_edge_ref_rejected_via_runner(self):
        ctx, _, fid = _make_ctx()
        result = _run_tool(
            ctx, fid,
            edge_ref="",  # invalid
            flange_length=10.0,
            bend_angle_deg=90.0,
            bend_radius=1.0,
            thickness=1.0,
            k_factor=0.44,
            base_width=50.0,
            base_depth=50.0,
        )
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_second_node_gets_incremented_id(self):
        ctx, store, fid = _make_ctx()
        _run_tool(ctx, fid, edge_ref="top-front", flange_length=10.0,
                  bend_angle_deg=90.0, bend_radius=1.0, thickness=1.0,
                  k_factor=0.44, base_width=50.0, base_depth=50.0)
        _run_tool(ctx, fid, edge_ref="top-back", flange_length=10.0,
                  bend_angle_deg=90.0, bend_radius=1.0, thickness=1.0,
                  k_factor=0.44, base_width=50.0, base_depth=50.0)
        doc = json.loads(store["content"])
        ids = [f["id"] for f in doc["features"]]
        assert ids[0] == "sheet_metal_flange-1"
        assert ids[1] == "sheet_metal_flange-2"

    def test_response_contains_k_factor(self):
        result, _ = self._make(k_factor=0.33)
        assert "error" not in result
        assert abs(result["k_factor"] - 0.33) < 1e-9

    def test_response_note_mentions_unfold(self):
        result, _ = self._make()
        note = result.get("note", "")
        assert "unfold" in note.lower() or "T-2" in note


# ===========================================================================
# T-2: compute_unfold — pure math, no DB
# ===========================================================================

class TestComputeUnfold:
    """Unit-test the bend-allowance unfold solver in isolation."""

    # Known-good values: 90° bend, R=2, t=1.5, k=0.44
    # angle_rad = π/2 ≈ 1.5707963268
    # BA = (π/2) × (2 + 0.44 × 1.5) = (π/2) × 2.66 ≈ 4.178…
    _R = 2.0
    _T = 1.5
    _K = 0.44
    _BASE = 50.0
    _FLANGE = 25.0

    def _ba_expected(self, angle_deg=90.0, r=_R, t=_T, k=_K):
        return math.radians(angle_deg) * (r + k * t)

    def test_90deg_ba_value(self):
        result = compute_unfold(
            base_length=self._BASE,
            flange_length=self._FLANGE,
            bend_angle_deg=90.0,
            bend_radius=self._R,
            thickness=self._T,
            k_factor=self._K,
        )
        expected_ba = self._ba_expected()
        assert abs(result["bend_allowance"] - expected_ba) < 1e-4

    def test_90deg_developed_length(self):
        result = compute_unfold(
            base_length=self._BASE,
            flange_length=self._FLANGE,
            bend_angle_deg=90.0,
            bend_radius=self._R,
            thickness=self._T,
            k_factor=self._K,
        )
        ba = self._ba_expected()
        expected_dl = self._BASE + ba + self._FLANGE
        assert abs(result["developed_length"] - expected_dl) < 1e-4

    def test_180deg_ba_double_90(self):
        """BA at 180° must be exactly 2× the BA at 90° (same R/t/k)."""
        r90 = compute_unfold(50, 25, 90.0, 2.0, 1.5, 0.44)
        r180 = compute_unfold(50, 25, 180.0, 2.0, 1.5, 0.44)
        assert abs(r180["bend_allowance"] - 2 * r90["bend_allowance"]) < 1e-6

    def test_bend_lines_count(self):
        result = compute_unfold(50, 25, 90.0, 2.0, 1.5, 0.44)
        assert len(result["bend_lines"]) == 2

    def test_bend_line_labels(self):
        result = compute_unfold(50, 25, 90.0, 2.0, 1.5, 0.44)
        labels = {bl["label"] for bl in result["bend_lines"]}
        assert labels == {"bend-start", "bend-end"}

    def test_bend_start_position(self):
        """bend-start is at base_length from the origin."""
        result = compute_unfold(50, 25, 90.0, 2.0, 1.5, 0.44)
        start_pos = next(bl["position"] for bl in result["bend_lines"] if bl["label"] == "bend-start")
        assert abs(start_pos - 50.0) < 1e-6

    def test_bend_end_position(self):
        """bend-end = base_length + BA."""
        result = compute_unfold(50, 25, 90.0, 2.0, 1.5, 0.44)
        ba = result["bend_allowance"]
        end_pos = next(bl["position"] for bl in result["bend_lines"] if bl["label"] == "bend-end")
        assert abs(end_pos - (50.0 + ba)) < 1e-6

    def test_small_angle_ba_positive(self):
        """Even a 1° bend must produce a positive BA."""
        result = compute_unfold(50, 25, 1.0, 2.0, 1.5, 0.44)
        assert result["bend_allowance"] > 0

    def test_k_factor_effect(self):
        """Higher k_factor → larger BA (more material to the outside)."""
        r_low  = compute_unfold(50, 25, 90.0, 2.0, 1.5, 0.33)
        r_high = compute_unfold(50, 25, 90.0, 2.0, 1.5, 0.50)
        assert r_high["bend_allowance"] > r_low["bend_allowance"]

    def test_larger_radius_larger_ba(self):
        r_small = compute_unfold(50, 25, 90.0, 1.0, 1.5, 0.44)
        r_large = compute_unfold(50, 25, 90.0, 5.0, 1.5, 0.44)
        assert r_large["bend_allowance"] > r_small["bend_allowance"]


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

class TestUnfoldSpec:
    def test_name(self):
        assert sheet_metal_unfold_spec.name == "sheet_metal_unfold"

    def test_required_fields(self):
        req = sheet_metal_unfold_spec.input_schema.get("required", [])
        for field in ["base_length", "flange_length", "bend_angle_deg",
                      "bend_radius", "thickness"]:
            assert field in req, f"'{field}' missing from required"

    def test_k_factor_optional(self):
        """k_factor should NOT be in required (has a default)."""
        req = sheet_metal_unfold_spec.input_schema.get("required", [])
        assert "k_factor" not in req

    def test_description_mentions_ba_formula(self):
        desc = sheet_metal_unfold_spec.description
        assert "BA" in desc or "bend_allowance" in desc or "bend-allowance" in desc.lower()


# ---------------------------------------------------------------------------
# run_sheet_metal_unfold — integration runner tests
# ---------------------------------------------------------------------------

class TestRunSheetMetalUnfold:

    def _run(self, **kwargs):
        ctx, _, _ = _make_ctx()
        defaults = {
            "base_length": 50.0,
            "flange_length": 25.0,
            "bend_angle_deg": 90.0,
            "bend_radius": 2.0,
            "thickness": 1.5,
            "k_factor": 0.44,
        }
        defaults.update(kwargs)
        raw = asyncio.new_event_loop().run_until_complete(
            run_sheet_metal_unfold(ctx, json.dumps(defaults).encode())
        )
        return json.loads(raw)

    def test_success(self):
        result = self._run()
        assert "error" not in result
        assert "bend_allowance" in result
        assert "developed_length" in result
        assert "bend_lines" in result

    def test_90deg_ba_correct(self):
        result = self._run(bend_radius=2.0, thickness=1.5, k_factor=0.44)
        expected_ba = math.radians(90) * (2.0 + 0.44 * 1.5)
        assert abs(result["bend_allowance"] - expected_ba) < 1e-4

    def test_bad_base_length_zero(self):
        result = self._run(base_length=0)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_bad_k_factor_one(self):
        result = self._run(k_factor=1.0)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_bad_angle_181(self):
        result = self._run(bend_angle_deg=181.0)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_default_k_factor_applies(self):
        """Omitting k_factor should use 0.44 default, not fail."""
        ctx, _, _ = _make_ctx()
        payload = {
            "base_length": 50.0,
            "flange_length": 25.0,
            "bend_angle_deg": 90.0,
            "bend_radius": 2.0,
            "thickness": 1.5,
        }
        raw = asyncio.new_event_loop().run_until_complete(
            run_sheet_metal_unfold(ctx, json.dumps(payload).encode())
        )
        result = json.loads(raw)
        assert "error" not in result


# ===========================================================================
# T-3: _flat_pattern_dxf_r12 and run_sheet_metal_flat_pattern
# ===========================================================================

class TestFlatPatternDxfR12:
    """Structural / syntax tests for the self-contained DXF R12 emitter."""

    def _dxf(self, width=100.0, developed_length=80.0, positions=None):
        if positions is None:
            positions = [50.0, 54.18]
        return _flat_pattern_dxf_r12(width, developed_length, positions)

    def test_returns_string(self):
        assert isinstance(self._dxf(), str)

    def test_contains_acadver(self):
        assert "AC1009" in self._dxf()

    def test_contains_header_section(self):
        dxf = self._dxf()
        assert "SECTION" in dxf
        assert "HEADER" in dxf

    def test_contains_entities_section(self):
        dxf = self._dxf()
        assert "ENTITIES" in dxf

    def test_ends_with_eof(self):
        dxf = self._dxf()
        assert "EOF" in dxf

    def test_outline_polyline_present(self):
        dxf = self._dxf()
        assert "POLYLINE" in dxf

    def test_closed_flag_present(self):
        """POLYLINE entity must have 70 group code (closed flag)."""
        dxf = self._dxf()
        lines = dxf.splitlines()
        # Find "70" group code after POLYLINE
        found_poly = False
        for i, line in enumerate(lines):
            if line.strip() == "POLYLINE":
                found_poly = True
            if found_poly and line.strip() == "70":
                assert lines[i + 1].strip() == "1"  # closed=1
                break

    def test_vertex_count(self):
        """Outline rectangle must have exactly 4 VERTEXes."""
        dxf = self._dxf()
        assert dxf.count("VERTEX") == 4

    def test_seqend_present(self):
        assert "SEQEND" in self._dxf()

    def test_bend_lines_on_bend_layer(self):
        dxf = self._dxf(positions=[50.0, 54.18])
        assert "BEND" in dxf

    def test_bend_line_count(self):
        """Two bend positions → two LINE entities on BEND layer."""
        dxf = self._dxf(positions=[50.0, 54.18])
        # Count standalone "LINE" entity records (not POLYLINE).
        # In DXF R12 each entity starts with group code 0 followed by entity name.
        line_entities = [ln.strip() for ln in dxf.splitlines() if ln.strip() == "LINE"]
        assert len(line_entities) == 2

    def test_zero_bend_lines(self):
        dxf = self._dxf(positions=[])
        line_entities = [ln.strip() for ln in dxf.splitlines() if ln.strip() == "LINE"]
        assert len(line_entities) == 0

    def test_developed_length_in_vertices(self):
        """The developed_length value must appear in the DXF vertex data."""
        dl = 79.1234
        dxf = _flat_pattern_dxf_r12(100.0, dl, [])
        assert f"{dl:.6f}" in dxf

    def test_width_in_vertices(self):
        w = 123.456
        dxf = _flat_pattern_dxf_r12(w, 80.0, [])
        assert f"{w:.6f}" in dxf

    def test_no_external_imports(self):
        """The function must be importable without kerf-imports installed."""
        # This is guaranteed by the import at the top of this file succeeding;
        # if kerf-imports were required the import would fail with ImportError.
        assert callable(_flat_pattern_dxf_r12)


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

class TestFlatPatternSpec:
    def test_name(self):
        assert sheet_metal_flat_pattern_spec.name == "sheet_metal_flat_pattern"

    def test_required_fields(self):
        req = sheet_metal_flat_pattern_spec.input_schema.get("required", [])
        for f in ["base_length", "width", "flange_length",
                  "bend_angle_deg", "bend_radius", "thickness"]:
            assert f in req, f"'{f}' missing from required"

    def test_k_factor_optional(self):
        req = sheet_metal_flat_pattern_spec.input_schema.get("required", [])
        assert "k_factor" not in req


# ---------------------------------------------------------------------------
# run_sheet_metal_flat_pattern — integration runner tests
# ---------------------------------------------------------------------------

class TestRunFlatPattern:

    def _run(self, **kwargs):
        ctx, _, _ = _make_ctx()
        defaults = {
            "base_length": 50.0,
            "width": 100.0,
            "flange_length": 25.0,
            "bend_angle_deg": 90.0,
            "bend_radius": 2.0,
            "thickness": 1.5,
            "k_factor": 0.44,
        }
        defaults.update(kwargs)
        raw = asyncio.new_event_loop().run_until_complete(
            run_sheet_metal_flat_pattern(ctx, json.dumps(defaults).encode())
        )
        return json.loads(raw)

    def test_success(self):
        result = self._run()
        assert "error" not in result

    def test_dxf_key_present(self):
        result = self._run()
        assert "dxf" in result
        assert isinstance(result["dxf"], str)

    def test_dxf_is_r12(self):
        result = self._run()
        assert "AC1009" in result["dxf"]

    def test_developed_length_returned(self):
        result = self._run()
        assert "developed_length" in result
        assert result["developed_length"] > 0

    def test_bend_allowance_returned(self):
        result = self._run()
        assert "bend_allowance" in result

    def test_bend_lines_returned(self):
        result = self._run()
        assert "bend_lines" in result
        assert len(result["bend_lines"]) == 2

    def test_90deg_developed_length_matches_unfold(self):
        """flat_pattern developed_length must match compute_unfold."""
        r_fp = self._run(
            base_length=50.0, flange_length=25.0,
            bend_angle_deg=90.0, bend_radius=2.0,
            thickness=1.5, k_factor=0.44,
        )
        r_unfold = compute_unfold(50.0, 25.0, 90.0, 2.0, 1.5, 0.44)
        assert abs(r_fp["developed_length"] - r_unfold["developed_length"]) < 1e-6

    def test_dxf_contains_bend_layer(self):
        result = self._run()
        assert "BEND" in result["dxf"]

    def test_bad_width_zero(self):
        result = self._run(width=0)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_bad_k_factor_zero(self):
        result = self._run(k_factor=0.0)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_dxf_note_mentions_no_cross_package_dep(self):
        result = self._run()
        note = result.get("dxf_note", "")
        assert "kerf-imports" in note or "cross-package" in note
