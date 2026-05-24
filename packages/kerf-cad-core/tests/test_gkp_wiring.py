"""GK-P Group W wiring tests.

Verifies that GK-P01..GK-P07 ToolSpecs are correctly wired:
  - New exports present in kerf_cad_core.geom
  - ToolSpec registered with correct name + required fields
  - Handler stores the correct op in the feature JSON node
  - Bad-args / missing-field paths return BAD_ARGS codes
  - GK-P07: include_g3_residuals flag stored + reflected in response

All tests are hermetic: no database, no OCCT, no network.
Uses FakePool/ProjectCtx pattern matching test_feature_surface_curvature_combs.py.

Payload convention (kerf_chat.tools.registry):
  ok_payload(d) → returns d directly (no 'ok' key)
  err_payload(msg, code) → {"error": msg, "code": code}
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctx(initial_content: str = "", kind: str = "feature"):
    """Return (ctx, store, file_id) with an in-memory fake pool."""
    store = {
        "content": initial_content or json.dumps({"version": 1, "features": []}),
        "kind": kind,
    }
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class FakePool:
        def fetchone(self, query, *args):
            if store["kind"] == "NOT_FOUND":
                return None
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


def run_tool(fn, ctx, file_id, **kwargs):
    args = {"file_id": str(file_id), **kwargs}
    raw = asyncio.new_event_loop().run_until_complete(
        fn(ctx, json.dumps(args).encode())
    )
    return json.loads(raw)


def is_ok(r: dict) -> bool:
    """ok_payload returns the data dict directly — no error key means success."""
    return "error" not in r


def is_err(r: dict, code: str | None = None) -> bool:
    if "error" not in r:
        return False
    if code is not None and r.get("code") != code:
        return False
    return True


def stored_node(store):
    """Extract the first feature node from the store."""
    doc = json.loads(store["content"])
    return doc["features"][0]


# ---------------------------------------------------------------------------
# GK-P01: geom exports
# ---------------------------------------------------------------------------

class TestGKP01Exports:
    def test_g3_blend_trim_sew_importable(self):
        from kerf_cad_core.geom import g3_blend_trim_sew
        assert callable(g3_blend_trim_sew)

    def test_blend_srf_g3_importable(self):
        from kerf_cad_core.geom import blend_srf_g3
        assert callable(blend_srf_g3)

    def test_curvature_rate_continuity_residual_importable(self):
        from kerf_cad_core.geom import curvature_rate_continuity_residual
        assert callable(curvature_rate_continuity_residual)


# ---------------------------------------------------------------------------
# GK-P01: feature_blend_srf_g3 ToolSpec + handler
# ---------------------------------------------------------------------------

class TestFeatureBlendSrfG3:
    def setup_method(self):
        from kerf_cad_core.surfacing import (
            feature_blend_srf_g3_spec,
            run_feature_blend_srf_g3,
        )
        self.spec = feature_blend_srf_g3_spec
        self.fn = run_feature_blend_srf_g3

    def test_spec_name(self):
        assert self.spec.name == "feature_blend_srf_g3"

    def test_spec_required_fields(self):
        req = self.spec.input_schema["required"]
        assert "file_id" in req
        assert "target_id" in req
        assert "edge1_id" in req
        assert "edge2_id" in req

    def test_happy_path_stores_node(self):
        ctx, store, fid = make_ctx()
        result = run_tool(self.fn, ctx, fid, target_id="sweep1-1", edge1_id=0, edge2_id=1)
        assert is_ok(result), f"expected ok, got: {result}"
        node = stored_node(store)
        assert node["op"] == "blend_srf_g3"
        assert node["continuity"] == "G3"
        assert node["edge1_id"] == 0
        assert node["edge2_id"] == 1

    def test_default_blend_dist(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="sweep1-1", edge1_id=0, edge2_id=1)
        assert stored_node(store)["blend_dist"] == 2.0

    def test_custom_blend_dist(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="sweep1-1", edge1_id=0, edge2_id=1, blend_dist=5.0)
        assert stored_node(store)["blend_dist"] == 5.0

    def test_trim_and_sew_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="sweep1-1", edge1_id=0, edge2_id=1, trim_and_sew=True)
        assert stored_node(store).get("trim_and_sew") is True

    def test_trim_and_sew_absent_by_default(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="sweep1-1", edge1_id=0, edge2_id=1)
        assert "trim_and_sew" not in stored_node(store)

    def test_missing_file_id(self):
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            self.fn(ctx, json.dumps({"target_id": "x", "edge1_id": 0, "edge2_id": 1}).encode())
        )
        r = json.loads(raw)
        assert is_err(r, "BAD_ARGS"), f"expected BAD_ARGS, got: {r}"

    def test_missing_target_id(self):
        ctx, store, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, edge1_id=0, edge2_id=1)
        assert is_err(r), f"expected error, got: {r}"

    def test_non_uuid_file_id(self):
        ctx, _, _ = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            self.fn(ctx, json.dumps({"file_id": "not-a-uuid", "target_id": "x", "edge1_id": 0, "edge2_id": 1}).encode())
        )
        r = json.loads(raw)
        assert is_err(r, "BAD_ARGS"), f"expected BAD_ARGS, got: {r}"

    def test_samples_clamped_to_min_8(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="t", edge1_id=0, edge2_id=1, samples=2)
        assert stored_node(store)["samples"] >= 8

    def test_auto_id_prefix(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="t", edge1_id=0, edge2_id=1)
        assert stored_node(store)["id"].startswith("blend_srf_g3-")

    def test_explicit_id(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="t", edge1_id=0, edge2_id=1,
                 options={"id": "my-g3-node"})
        assert stored_node(store)["id"] == "my-g3-node"


# ---------------------------------------------------------------------------
# GK-P02: geom exports + feature_zebra_analysis ToolSpec
# ---------------------------------------------------------------------------

class TestGKP02Exports:
    def test_zebra_stripe_continuity_analyser_importable(self):
        from kerf_cad_core.geom import zebra_stripe_continuity_analyser
        assert callable(zebra_stripe_continuity_analyser)

    def test_reflection_lines_importable(self):
        from kerf_cad_core.geom import reflection_lines
        assert callable(reflection_lines)


class TestFeatureZebraAnalysis:
    def setup_method(self):
        from kerf_cad_core.surfacing import (
            feature_zebra_analysis_spec,
            run_feature_zebra_analysis,
        )
        self.spec = feature_zebra_analysis_spec
        self.fn = run_feature_zebra_analysis

    _edge_pts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]

    def test_spec_name(self):
        assert self.spec.name == "feature_zebra_analysis"

    def test_spec_required_fields(self):
        req = self.spec.input_schema["required"]
        assert "file_id" in req
        assert "surface_a_ref" in req
        assert "surface_b_ref" in req
        assert "shared_edge_pts" in req

    def test_happy_path(self):
        ctx, store, fid = make_ctx()
        r = run_tool(
            self.fn, ctx, fid,
            surface_a_ref="sweep1-1",
            surface_b_ref="blend_srf-1",
            shared_edge_pts=self._edge_pts,
        )
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert node["op"] == "zebra_analysis"
        assert node["surface_a_ref"] == "sweep1-1"
        assert node["surface_b_ref"] == "blend_srf-1"

    def test_edge_pts_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid,
                 surface_a_ref="a", surface_b_ref="b",
                 shared_edge_pts=self._edge_pts)
        assert len(stored_node(store)["shared_edge_pts"]) == 2

    def test_missing_edge_pts(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, surface_a_ref="a", surface_b_ref="b")
        assert is_err(r, "BAD_ARGS"), f"expected BAD_ARGS, got: {r}"

    def test_single_edge_pt_rejected(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid,
                     surface_a_ref="a", surface_b_ref="b",
                     shared_edge_pts=[[0.0, 0.0, 0.0]])
        assert is_err(r), f"expected error, got: {r}"

    def test_auto_id_prefix(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid,
                 surface_a_ref="a", surface_b_ref="b",
                 shared_edge_pts=self._edge_pts)
        assert stored_node(store)["id"].startswith("zebra_analysis-")


# ---------------------------------------------------------------------------
# GK-P03: geom exports + feature_class_a_check ToolSpec
# ---------------------------------------------------------------------------

class TestGKP03Exports:
    def test_class_a_acceptance_harness_importable(self):
        from kerf_cad_core.geom import class_a_acceptance_harness
        assert callable(class_a_acceptance_harness)

    def test_run_leading_pass_importable(self):
        from kerf_cad_core.geom import run_leading_pass
        assert callable(run_leading_pass)

    def test_leading_report_importable(self):
        from kerf_cad_core.geom import LeadingReport
        assert LeadingReport is not None


class TestFeatureClassACheck:
    def setup_method(self):
        from kerf_cad_core.surfacing import (
            feature_class_a_check_spec,
            run_feature_class_a_check,
        )
        self.spec = feature_class_a_check_spec
        self.fn = run_feature_class_a_check

    _edge_pts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]

    def test_spec_name(self):
        assert self.spec.name == "feature_class_a_check"

    def test_spec_required_fields(self):
        req = self.spec.input_schema["required"]
        assert "file_id" in req
        assert "surface_a_ref" in req
        assert "surface_b_ref" in req
        assert "shared_edge_pts" in req

    def test_happy_path(self):
        ctx, store, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid,
                     surface_a_ref="sweep1-1", surface_b_ref="blend_srf-1",
                     shared_edge_pts=self._edge_pts)
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert node["op"] == "class_a_check"
        assert node["surface_a_ref"] == "sweep1-1"

    def test_run_leading_flag_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid,
                 surface_a_ref="a", surface_b_ref="b",
                 shared_edge_pts=self._edge_pts,
                 run_leading=True)
        assert stored_node(store).get("run_leading") is True

    def test_run_leading_absent_by_default(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid,
                 surface_a_ref="a", surface_b_ref="b",
                 shared_edge_pts=self._edge_pts)
        assert "run_leading" not in stored_node(store)

    def test_tolerance_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid,
                 surface_a_ref="a", surface_b_ref="b",
                 shared_edge_pts=self._edge_pts,
                 tolerance=1e-5)
        assert abs(stored_node(store)["tolerance"] - 1e-5) < 1e-12

    def test_missing_edge_pts(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, surface_a_ref="a", surface_b_ref="b")
        assert is_err(r), f"expected error, got: {r}"

    def test_auto_id_prefix(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid,
                 surface_a_ref="a", surface_b_ref="b",
                 shared_edge_pts=self._edge_pts)
        assert stored_node(store)["id"].startswith("class_a_check-")


# ---------------------------------------------------------------------------
# GK-P04: continuity_audit export + feature_global_continuity_audit ToolSpec
# ---------------------------------------------------------------------------

class TestGKP04Exports:
    def test_continuity_audit_importable(self):
        from kerf_cad_core.geom import continuity_audit
        assert callable(continuity_audit)


class TestFeatureGlobalContinuityAudit:
    def setup_method(self):
        from kerf_cad_core.surfacing import (
            feature_global_continuity_audit_spec,
            run_feature_global_continuity_audit,
        )
        self.spec = feature_global_continuity_audit_spec
        self.fn = run_feature_global_continuity_audit

    def test_spec_name(self):
        assert self.spec.name == "feature_global_continuity_audit"

    def test_spec_required_fields(self):
        req = self.spec.input_schema["required"]
        assert "file_id" in req
        assert "target_feature_ref" in req

    def test_happy_path(self):
        ctx, store, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, target_feature_ref="blend_srf_g3-1")
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert node["op"] == "global_continuity_audit"
        assert node["target_feature_ref"] == "blend_srf_g3-1"

    def test_default_tol(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_feature_ref="x")
        assert stored_node(store)["tol"] == 1e-4

    def test_custom_tol(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_feature_ref="x", tol=1e-6)
        assert abs(stored_node(store)["tol"] - 1e-6) < 1e-14

    def test_missing_target_ref(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid)
        assert is_err(r, "BAD_ARGS"), f"expected BAD_ARGS, got: {r}"

    def test_auto_id_prefix(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_feature_ref="x")
        assert stored_node(store)["id"].startswith("global_continuity_audit-")


# ---------------------------------------------------------------------------
# GK-P05: blend_edge_chain_g3 export + feature_g3_chain_blend ToolSpec
# ---------------------------------------------------------------------------

class TestGKP05Exports:
    def test_blend_edge_chain_g3_importable(self):
        from kerf_cad_core.geom import blend_edge_chain_g3
        assert callable(blend_edge_chain_g3)


class TestFeatureG3ChainBlend:
    def setup_method(self):
        from kerf_cad_core.surfacing import (
            feature_g3_chain_blend_spec,
            run_feature_g3_chain_blend,
        )
        self.spec = feature_g3_chain_blend_spec
        self.fn = run_feature_g3_chain_blend

    def test_spec_name(self):
        assert self.spec.name == "feature_g3_chain_blend"

    def test_spec_required_fields(self):
        req = self.spec.input_schema["required"]
        assert "file_id" in req
        assert "target_id" in req
        assert "edge_ids" in req
        assert "radius" in req

    def test_happy_path_single_edge(self):
        ctx, store, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, target_id="box-1", edge_ids=[3], radius=1.5)
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert node["op"] == "g3_chain_blend"
        assert node["continuity"] == "G3"
        assert node["radius"] == 1.5
        assert node["edge_ids"] == [3]

    def test_happy_path_multi_edge(self):
        ctx, store, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, target_id="box-1", edge_ids=[1, 2, 3], radius=2.0)
        assert is_ok(r), f"expected ok, got: {r}"
        assert r["edge_count"] == 3

    def test_zero_radius_rejected(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, target_id="box-1", edge_ids=[1], radius=0)
        assert is_err(r, "BAD_ARGS"), f"expected BAD_ARGS, got: {r}"

    def test_negative_radius_rejected(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, target_id="box-1", edge_ids=[1], radius=-1.0)
        assert is_err(r), f"expected error, got: {r}"

    def test_empty_edge_ids_rejected(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, target_id="box-1", edge_ids=[], radius=1.0)
        assert is_err(r), f"expected error, got: {r}"

    def test_non_integer_edge_ids_rejected(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, target_id="box-1", edge_ids=["a", "b"], radius=1.0)
        assert is_err(r), f"expected error, got: {r}"

    def test_auto_id_prefix(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, target_id="box-1", edge_ids=[1], radius=1.0)
        assert stored_node(store)["id"].startswith("g3_chain_blend-")


# ---------------------------------------------------------------------------
# GK-P06: fit_surface export + feature_fit_surface ToolSpec
# ---------------------------------------------------------------------------

class TestGKP06Exports:
    def test_fit_surface_importable(self):
        from kerf_cad_core.geom import fit_surface
        assert callable(fit_surface)


class TestFeatureFitSurface:
    def setup_method(self):
        from kerf_cad_core.surfacing import (
            feature_fit_surface_spec,
            run_feature_fit_surface,
        )
        self.spec = feature_fit_surface_spec
        self.fn = run_feature_fit_surface

    # 2×2 grid of 4 points (minimal valid input for degree 1)
    _pts_2x2 = [
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        [[0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
    ]

    def test_spec_name(self):
        assert self.spec.name == "feature_fit_surface"

    def test_spec_required_fields(self):
        req = self.spec.input_schema["required"]
        assert "file_id" in req
        assert "points_grid" in req

    def test_happy_path_stores_node(self):
        ctx, store, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, points_grid=self._pts_2x2)
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert node["op"] == "fit_surface"
        assert node["degree_u"] == 3
        assert node["degree_v"] == 3

    def test_custom_degrees(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, points_grid=self._pts_2x2, degree_u=2, degree_v=1)
        node = stored_node(store)
        assert node["degree_u"] == 2
        assert node["degree_v"] == 1

    def test_custom_tol(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, points_grid=self._pts_2x2, tol=1e-6)
        assert abs(stored_node(store)["tol"] - 1e-6) < 1e-14

    def test_points_grid_stored(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, points_grid=self._pts_2x2)
        node = stored_node(store)
        assert len(node["points_grid"]) == 2
        assert len(node["points_grid"][0]) == 2

    def test_missing_points_grid(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid)
        assert is_err(r, "BAD_ARGS"), f"expected BAD_ARGS, got: {r}"

    def test_empty_points_grid_rejected(self):
        ctx, _, fid = make_ctx()
        r = run_tool(self.fn, ctx, fid, points_grid=[])
        assert is_err(r), f"expected error, got: {r}"

    def test_degree_out_of_range_clamped_to_3(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, points_grid=self._pts_2x2, degree_u=9, degree_v=0)
        node = stored_node(store)
        assert node["degree_u"] == 3  # reset to default
        assert node["degree_v"] == 3

    def test_auto_id_prefix(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, points_grid=self._pts_2x2)
        assert stored_node(store)["id"].startswith("fit_surface-")

    def test_explicit_id(self):
        ctx, store, fid = make_ctx()
        run_tool(self.fn, ctx, fid, points_grid=self._pts_2x2, options={"id": "patch-1"})
        assert stored_node(store)["id"] == "patch-1"


# ---------------------------------------------------------------------------
# GK-P07: include_g3_residuals flag on feature_surface_curvature_combs
# ---------------------------------------------------------------------------

class TestGKP07G3Residuals:
    def setup_method(self):
        from kerf_cad_core.surfacing import (
            feature_surface_curvature_combs_spec,
            run_feature_surface_curvature_combs,
        )
        self.spec = feature_surface_curvature_combs_spec
        self.fn = run_feature_surface_curvature_combs

    def test_spec_has_include_g3_residuals(self):
        props = self.spec.input_schema["properties"]
        assert "include_g3_residuals" in props

    def test_g3_residuals_flag_stored_in_node(self):
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            self.fn(ctx, json.dumps({
                "file_id": str(fid),
                "target_feature_ref": "blend_srf_g3-1",
                "include_g3_residuals": True,
            }).encode())
        )
        r = json.loads(raw)
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert node.get("include_g3_residuals") is True

    def test_g3_residuals_response_flag(self):
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            self.fn(ctx, json.dumps({
                "file_id": str(fid),
                "target_feature_ref": "blend_srf_g3-1",
                "include_g3_residuals": True,
            }).encode())
        )
        r = json.loads(raw)
        assert r.get("g3_residuals_requested") is True

    def test_g3_residuals_absent_by_default(self):
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            self.fn(ctx, json.dumps({
                "file_id": str(fid),
                "target_feature_ref": "blend_srf_g3-1",
            }).encode())
        )
        r = json.loads(raw)
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert "include_g3_residuals" not in node

    def test_g3_residuals_false_not_stored(self):
        ctx, store, fid = make_ctx()
        raw = asyncio.new_event_loop().run_until_complete(
            self.fn(ctx, json.dumps({
                "file_id": str(fid),
                "target_feature_ref": "blend_srf_g3-1",
                "include_g3_residuals": False,
            }).encode())
        )
        r = json.loads(raw)
        assert is_ok(r), f"expected ok, got: {r}"
        node = stored_node(store)
        assert "include_g3_residuals" not in node
