"""
Tests for extrude_sketch_to_jscad — pure logic + lightweight fake-pool
integration tests.  No live Postgres required.

Coverage:
- validate_params: all three ops, valid and invalid cases.
- _sketch_has_closed_loop: circle, ellipse, bspline, lines, empty sketch.
- generate_*: output shape matches canonical jscad.md pattern.
- run_extrude_sketch_to_jscad (async): happy path for all 3 ops, missing
  sketch, bad sketch kind, sketch with no closed loop, path collision,
  missing params, sweep with missing path sketch.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

import pytest

# Ensure src is on the path for direct `pytest packages/kerf-cad-core/` runs.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kerf_cad_core.extrude_sketch_to_jscad import (
    _object_id_from_path,
    _parse_sketch_json,
    _sketch_has_closed_loop,
    generate_extrude_linear,
    generate_extrude_rotate,
    generate_sweep_along_path,
    run_extrude_sketch_to_jscad,
    validate_params,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sketch_content(entities=None, has_circle=False):
    """Build minimal sketch JSON content."""
    if entities is None:
        if has_circle:
            entities = [
                {"id": "c1", "type": "circle", "cx": 0, "cy": 0, "radius": 5}
            ]
        else:
            entities = [
                {"id": "l1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0},
                {"id": "l2", "type": "line", "x1": 10, "y1": 0, "x2": 10, "y2": 10},
                {"id": "l3", "type": "line", "x1": 10, "y1": 10, "x2": 0, "y2": 0},
            ]
    doc = {
        "version": 1,
        "plane": {"type": "base", "name": "XY"},
        "entities": entities,
        "constraints": [],
        "visible_3d": [],
        "solved": {},
        "metadata": {},
    }
    return json.dumps(doc)


def _run(coro):
    """Run a coroutine synchronously (avoids pytest-asyncio dependency)."""
    return asyncio.get_event_loop().run_until_complete(coro)


class FakePool:
    """
    Minimal pool fake.

    files dict maps path -> {"content": str, "kind": str, "id": uuid}.
    Supports fetchrow, fetchval, execute.
    target_files accumulates INSERT results.
    """

    def __init__(self, files: dict | None = None):
        self._files = files or {}
        self.inserted = {}  # path -> {"id": uuid, "content": str, "kind": str}

    def _file_by_path(self, path: str, project_id=None):
        return self._files.get(path)

    async def fetchrow(self, query, *args):
        # SELECT content, kind FROM files WHERE project_id = $1 AND path = $2
        if "path = $2" in query or "path = $2" in query:
            path = args[1] if len(args) > 1 else None
            row = self._files.get(path)
            if row is None:
                return None
            # Return a dict-like object.
            return row
        # SELECT id, parent_id, name, kind FROM files ... path = $2
        if "path = $2" in query:
            path = args[1] if len(args) > 1 else None
            row = self._files.get(path)
            if row is None:
                return None
            return row
        return None

    async def fetchval(self, query, *args):
        # INSERT INTO files ... RETURNING id
        if "INSERT INTO files" in query:
            new_id = uuid.uuid4()
            # The extrude_sketch_to_jscad INSERT uses:
            #   INSERT INTO files(...) VALUES ($1, $2, $3, 'jscad', $4)
            # so args = (project_id, parent_id, leaf, content) — 4 items.
            # Other callers (scaffold.py) use 5 args with kind as $4.
            if len(args) >= 5:
                # 5-arg form: project_id, parent_id, name, kind, content
                name = args[2]
                kind = args[3]
                content = args[4]
                self.inserted[name] = {"id": new_id, "content": content, "kind": kind}
            elif len(args) >= 4:
                # 4-arg form: project_id, parent_id, name, content (kind hardcoded)
                name = args[2]
                content = args[3]
                # Extract hardcoded kind from query, e.g. VALUES ($1, $2, $3, 'jscad', $4)
                import re
                kind_match = re.search(r"'(\w+)',\s*\$4", query)
                kind = kind_match.group(1) if kind_match else "unknown"
                self.inserted[name] = {"id": new_id, "content": content, "kind": kind}
            elif len(args) >= 3:
                name = args[2]
                self.inserted[name] = {"id": new_id}
            return new_id
        # SELECT id FROM files WHERE ...
        path = args[1] if len(args) > 1 else None
        row = self._files.get(path)
        if row:
            return row.get("id")
        return None

    async def execute(self, query, *args):
        pass


def _make_ctx(files: dict | None = None):
    """Return (ctx, pool) with an in-memory fake pool."""
    pool = FakePool(files)
    from kerf_core.utils.context import ProjectCtx
    ctx = ProjectCtx(
        pool=pool,
        storage=None,
        project_id=uuid.uuid4(),
        user_id=uuid.UUID(int=0),
        role="owner",
        http_client=None,
        file_revisions_max=0,
    )
    return ctx, pool


# Patch _write_revision so tests don't hit DB.
import kerf_cad_core.extrude_sketch_to_jscad as _module

_orig_write_revision = _module._write_revision


async def _noop_write_revision(**kwargs):
    return None


_module._write_revision = _noop_write_revision


# ---------------------------------------------------------------------------
# validate_params
# ---------------------------------------------------------------------------

class TestValidateParams:
    def test_linear_height_mm_ok(self):
        assert validate_params("extrude_linear", {"height_mm": 10}) is None

    def test_linear_height_param_ok(self):
        assert validate_params("extrude_linear", {"height_param": "wall_h"}) is None

    def test_linear_missing_both(self):
        err = validate_params("extrude_linear", {})
        assert err is not None
        assert "height_mm" in err or "height_param" in err

    def test_linear_height_mm_zero(self):
        err = validate_params("extrude_linear", {"height_mm": 0})
        assert err is not None

    def test_linear_height_mm_negative(self):
        err = validate_params("extrude_linear", {"height_mm": -5})
        assert err is not None

    def test_linear_height_mm_non_number(self):
        err = validate_params("extrude_linear", {"height_mm": "ten"})
        assert err is not None

    def test_rotate_ok(self):
        assert validate_params("extrude_rotate", {"angle_deg": 180}) is None

    def test_rotate_full_circle_ok(self):
        assert validate_params("extrude_rotate", {"angle_deg": 360}) is None

    def test_rotate_with_segments(self):
        assert validate_params("extrude_rotate", {"angle_deg": 90, "segments": 16}) is None

    def test_rotate_missing_angle(self):
        err = validate_params("extrude_rotate", {})
        assert err is not None

    def test_rotate_angle_too_large(self):
        err = validate_params("extrude_rotate", {"angle_deg": 361})
        assert err is not None

    def test_rotate_angle_zero(self):
        err = validate_params("extrude_rotate", {"angle_deg": 0})
        assert err is not None

    def test_rotate_segments_too_small(self):
        err = validate_params("extrude_rotate", {"angle_deg": 90, "segments": 2})
        assert err is not None

    def test_sweep_ok(self):
        assert validate_params(
            "sweep_along_path", {"path_sketch_file_id": "/parts/rail.sketch"}
        ) is None

    def test_sweep_missing_path(self):
        err = validate_params("sweep_along_path", {})
        assert err is not None

    def test_sweep_relative_path(self):
        err = validate_params("sweep_along_path", {"path_sketch_file_id": "rail.sketch"})
        assert err is not None

    def test_params_not_dict(self):
        err = validate_params("extrude_linear", "height=10")
        assert err is not None


# ---------------------------------------------------------------------------
# _sketch_has_closed_loop
# ---------------------------------------------------------------------------

class TestSketchHasClosedLoop:
    def test_circle_is_closed(self):
        sketch = json.loads(_sketch_content(has_circle=True))
        assert _sketch_has_closed_loop(sketch) is True

    def test_three_lines_is_closed(self):
        sketch = json.loads(_sketch_content())
        assert _sketch_has_closed_loop(sketch) is True

    def test_two_lines_is_not_closed(self):
        entities = [
            {"id": "l1", "type": "line"},
            {"id": "l2", "type": "line"},
        ]
        sketch = json.loads(_sketch_content(entities=entities))
        assert _sketch_has_closed_loop(sketch) is False

    def test_empty_entities(self):
        sketch = json.loads(_sketch_content(entities=[]))
        assert _sketch_has_closed_loop(sketch) is False

    def test_construction_only_not_closed(self):
        entities = [
            {"id": "l1", "type": "line", "construction": True},
            {"id": "l2", "type": "line", "construction": True},
            {"id": "l3", "type": "line", "construction": True},
        ]
        sketch = json.loads(_sketch_content(entities=entities))
        assert _sketch_has_closed_loop(sketch) is False

    def test_ellipse_is_closed(self):
        entities = [{"id": "e1", "type": "ellipse"}]
        sketch = json.loads(_sketch_content(entities=entities))
        assert _sketch_has_closed_loop(sketch) is True

    def test_bspline_with_3_points(self):
        entities = [{"id": "b1", "type": "bspline", "points": [[0,0],[1,1],[2,0]]}]
        sketch = json.loads(_sketch_content(entities=entities))
        assert _sketch_has_closed_loop(sketch) is True

    def test_bspline_too_few_points(self):
        entities = [{"id": "b1", "type": "bspline", "points": [[0,0],[1,1]]}]
        sketch = json.loads(_sketch_content(entities=entities))
        assert _sketch_has_closed_loop(sketch) is False


# ---------------------------------------------------------------------------
# _parse_sketch_json
# ---------------------------------------------------------------------------

class TestParseSketchJson:
    def test_valid_json(self):
        doc, err = _parse_sketch_json(_sketch_content(has_circle=True))
        assert err is None
        assert isinstance(doc, dict)

    def test_empty_string(self):
        doc, err = _parse_sketch_json("")
        assert err is not None

    def test_invalid_json(self):
        doc, err = _parse_sketch_json("{not json}")
        assert err is not None

    def test_non_object(self):
        doc, err = _parse_sketch_json("[1,2,3]")
        assert err is not None


# ---------------------------------------------------------------------------
# _object_id_from_path
# ---------------------------------------------------------------------------

class TestObjectIdFromPath:
    def test_basic(self):
        assert _object_id_from_path("/parts/bracket.sketch") == "bracket"

    def test_hyphenated(self):
        assert _object_id_from_path("/parts/bracket-outline.sketch") == "bracket-outline"

    def test_no_extension(self):
        assert _object_id_from_path("/parts/plate") == "plate"

    def test_special_chars(self):
        oid = _object_id_from_path("/parts/my sketch!.sketch")
        assert "!" not in oid
        assert " " not in oid


# ---------------------------------------------------------------------------
# generate_extrude_linear
# ---------------------------------------------------------------------------

class TestGenerateExtrudeLinear:
    def test_height_mm(self):
        src = generate_extrude_linear(
            "/parts/p.sketch", "/parts/p.jscad", {"height_mm": 10}, "part"
        )
        assert "import profile from '/parts/p.sketch'" in src
        assert "export default function" in src
        assert "extrusions.extrudeLinear" in src
        assert "{ id: 'part', geom: body }" in src
        assert "10.0" in src
        # Must use ES import not require
        assert "require(" not in src

    def test_height_param(self):
        src = generate_extrude_linear(
            "/parts/p.sketch", "/parts/p.jscad", {"height_param": "wall_h"}, "wall"
        )
        assert "params.wall_h ?? 10" in src
        assert "{ id: 'wall', geom: body }" in src

    def test_no_params_defaults_to_10(self):
        src = generate_extrude_linear(
            "/parts/p.sketch", "/parts/p.jscad", {}, "body"
        )
        assert "const height = 10" in src

    def test_return_array_shape(self):
        src = generate_extrude_linear(
            "/parts/p.sketch", "/parts/p.jscad", {"height_mm": 5}, "base"
        )
        # Must return array of {id, geom} objects
        assert "return [" in src
        assert "id:" in src
        assert "geom:" in src


# ---------------------------------------------------------------------------
# generate_extrude_rotate
# ---------------------------------------------------------------------------

class TestGenerateExtrudeRotate:
    def test_full_circle(self):
        src = generate_extrude_rotate(
            "/parts/v.sketch", "/parts/v.jscad", {"angle_deg": 360, "segments": 32}, "vase"
        )
        assert "import profile from '/parts/v.sketch'" in src
        assert "extrusions.extrudeRotate(" in src
        assert "6.2831853072" in src  # 2*pi to 10 decimal places
        assert "segments: 32" in src
        assert "{ id: 'vase', geom: body }" in src
        assert "require(" not in src

    def test_half_circle(self):
        src = generate_extrude_rotate(
            "/parts/v.sketch", "/parts/v.jscad", {"angle_deg": 180}, "half"
        )
        import math
        expected_rad = round(math.pi, 10)
        assert str(expected_rad) in src

    def test_angle_comment(self):
        src = generate_extrude_rotate(
            "/parts/v.sketch", "/parts/v.jscad", {"angle_deg": 90}, "q"
        )
        assert "90.0 degrees" in src


# ---------------------------------------------------------------------------
# generate_sweep_along_path
# ---------------------------------------------------------------------------

class TestGenerateSweepAlongPath:
    def test_imports_both_sketches(self):
        src = generate_sweep_along_path(
            "/parts/profile.sketch",
            "/parts/rail.sketch",
            "/parts/sweep.jscad",
            {},
            "pipe",
        )
        assert "import profile from '/parts/profile.sketch'" in src
        assert "import railPath from '/parts/rail.sketch'" in src
        assert "export default function" in src
        assert "extrudeFromSlices" in src
        assert "{ id: 'pipe', geom: body }" in src
        assert "require(" not in src

    def test_no_sweepAlong(self):
        # There is no sweepAlong in @jscad/modeling 2.x; must not emit it.
        src = generate_sweep_along_path(
            "/p.sketch", "/r.sketch", "/s.jscad", {}, "s"
        )
        assert "sweepAlong" not in src

    def test_uses_extrudeFromSlices(self):
        src = generate_sweep_along_path(
            "/p.sketch", "/r.sketch", "/s.jscad", {}, "s"
        )
        assert "extrudeFromSlices" in src


# ---------------------------------------------------------------------------
# Integration: run_extrude_sketch_to_jscad
# ---------------------------------------------------------------------------

PROFILE_PATH = "/parts/profile.sketch"
RAIL_PATH = "/parts/rail.sketch"
TARGET_PATH = "/parts/output.jscad"


def _base_files():
    return {
        PROFILE_PATH: {
            "id": uuid.uuid4(),
            "content": _sketch_content(has_circle=True),
            "kind": "sketch",
            "name": "profile.sketch",
            "parent_id": None,
        },
        RAIL_PATH: {
            "id": uuid.uuid4(),
            "content": _sketch_content(),
            "kind": "sketch",
            "name": "rail.sketch",
            "parent_id": None,
        },
    }


class TestRunExtrudeSketchToJscad:

    # ── Happy path: extrude_linear ───────────────────────────────────────────

    def test_linear_happy_path(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 10},
            "object_id": "body",
        }).encode()))
        data = json.loads(result)
        assert "error" not in data
        assert data["path"] == TARGET_PATH
        assert data["operation"] == "extrude_linear"
        assert data["object_id"] == "body"
        # Check that the inserted content is valid JSCAD
        inserted = pool.inserted.get("output.jscad")
        assert inserted is not None
        assert "extrudeLinear" in inserted["content"]
        assert "import profile from" in inserted["content"]

    # ── Happy path: extrude_rotate ───────────────────────────────────────────

    def test_rotate_happy_path(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_rotate",
            "params": {"angle_deg": 360},
        }).encode()))
        data = json.loads(result)
        assert "error" not in data
        assert data["operation"] == "extrude_rotate"
        inserted = pool.inserted.get("output.jscad")
        assert "extrudeRotate" in inserted["content"]

    # ── Happy path: sweep_along_path ─────────────────────────────────────────

    def test_sweep_happy_path(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "sweep_along_path",
            "params": {"path_sketch_file_id": RAIL_PATH},
            "object_id": "pipe",
        }).encode()))
        data = json.loads(result)
        assert "error" not in data
        assert data["operation"] == "sweep_along_path"
        inserted = pool.inserted.get("output.jscad")
        assert "extrudeFromSlices" in inserted["content"]
        assert "import railPath" in inserted["content"]

    # ── Error: missing sketch ────────────────────────────────────────────────

    def test_missing_sketch(self):
        ctx, pool = _make_ctx({})  # no files at all
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "NOT_FOUND"
        assert PROFILE_PATH in data.get("error", "")

    # ── Error: sketch has wrong kind ─────────────────────────────────────────

    def test_sketch_wrong_kind(self):
        files = {
            PROFILE_PATH: {
                "id": uuid.uuid4(),
                "content": _sketch_content(has_circle=True),
                "kind": "jscad",  # wrong!
                "name": "profile.sketch",
                "parent_id": None,
            }
        }
        ctx, pool = _make_ctx(files)
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "BAD_KIND"

    # ── Error: sketch with no closed loop ────────────────────────────────────

    def test_sketch_no_closed_loop(self):
        no_loop_content = _sketch_content(entities=[
            {"id": "l1", "type": "line"},
            {"id": "l2", "type": "line"},
        ])
        files = {
            PROFILE_PATH: {
                "id": uuid.uuid4(),
                "content": no_loop_content,
                "kind": "sketch",
                "name": "profile.sketch",
                "parent_id": None,
            }
        }
        ctx, pool = _make_ctx(files)
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "NO_CLOSED_LOOP"

    # ── Error: malformed sketch JSON ─────────────────────────────────────────

    def test_malformed_sketch_json(self):
        files = {
            PROFILE_PATH: {
                "id": uuid.uuid4(),
                "content": "{bad json",
                "kind": "sketch",
                "name": "profile.sketch",
                "parent_id": None,
            }
        }
        ctx, pool = _make_ctx(files)
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "BAD_CONTENT"

    # ── Error: target path collision ─────────────────────────────────────────

    def test_target_path_collision(self):
        files = dict(_base_files())
        # Pre-populate the target path
        files[TARGET_PATH] = {
            "id": uuid.uuid4(),
            "content": "// existing",
            "kind": "jscad",
            "name": "output.jscad",
            "parent_id": None,
        }
        ctx, pool = _make_ctx(files)
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "EXISTS"

    # ── Error: missing params ────────────────────────────────────────────────

    def test_missing_height_param(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "BAD_ARGS"

    def test_missing_angle_param(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_rotate",
            "params": {},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "BAD_ARGS"

    # ── Error: sweep with missing path sketch ────────────────────────────────

    def test_sweep_missing_path_sketch(self):
        ctx, pool = _make_ctx(_base_files())  # no RAIL_PATH variant missing
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "sweep_along_path",
            "params": {"path_sketch_file_id": "/parts/nonexistent.sketch"},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "NOT_FOUND"

    # ── Error: non-absolute sketch_file_id ──────────────────────────────────

    def test_relative_sketch_path_rejected(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": "parts/profile.sketch",
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "BAD_ARGS"

    # ── Default object_id derivation ─────────────────────────────────────────

    def test_default_object_id_from_basename(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
            # no object_id
        }).encode()))
        data = json.loads(result)
        assert "error" not in data
        # basename of PROFILE_PATH without extension is "profile"
        assert data["object_id"] == "profile"

    # ── Auto-append .jscad extension ─────────────────────────────────────────

    def test_auto_append_jscad_extension(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": "/parts/noext",
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert "error" not in data
        assert data["path"].endswith(".jscad")

    # ── Invalid operation ────────────────────────────────────────────────────

    def test_invalid_operation(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "pocket",
            "params": {"height_mm": 5},
        }).encode()))
        data = json.loads(result)
        assert data.get("code") == "BAD_ARGS"

    # ── Invalid JSON args ────────────────────────────────────────────────────

    def test_invalid_args_json(self):
        ctx, pool = _make_ctx(_base_files())
        result = _run(run_extrude_sketch_to_jscad(ctx, b"{not json"))
        data = json.loads(result)
        assert data.get("code") == "BAD_ARGS"

    # ── Generated source is ES module (not CommonJS) ─────────────────────────

    def test_generated_source_is_es_module(self):
        ctx, pool = _make_ctx(_base_files())
        _run(run_extrude_sketch_to_jscad(ctx, json.dumps({
            "path": TARGET_PATH,
            "sketch_file_id": PROFILE_PATH,
            "operation": "extrude_linear",
            "params": {"height_mm": 10},
        }).encode()))
        inserted = pool.inserted.get("output.jscad")
        src = inserted["content"]
        # Must use ES import, not require
        assert "import profile from" in src
        assert "require(" not in src
        # Must use export default function
        assert "export default function" in src
        # Return shape must be array
        assert "return [" in src
