"""
test_freecad_e2e.py — T8 Integration test: .FCStd fixtures → route → project tree.

Uploads each fixture through the FastAPI TestClient for
POST /import-freecad-project and asserts the expected project file tree,
stats, and warning counts.

Fixtures are pre-built minimal .FCStd archives (no real BRep geometry — no
freecadcmd required).  The tests skip if the fixture files are missing.

Test plan per fixture:
  single_pad.FCStd:
    - 1 sketch file, 1 feature file, 0 assembly files.
    - stats.bodies == 1, stats.sketches == 1.

  pad_and_pocket.FCStd:
    - 2 sketch files, 1 feature file, 0 assembly files.
    - stats.bodies >= 1, stats.sketches == 2.

  two_bodies.FCStd:
    - 0 sketch files, 2 feature files, 1 assembly file.
    - stats.bodies == 2.
    - Assembly has 2 components.

  sketch_constraints.FCStd:
    - 1 sketch file.
    - constraints_translated >= 4 (Coincident, Distance, Angle, Tangent, Radius).
    - constraints_dropped == 0.

  unsupported_constraints.FCStd:
    - 1 sketch file.
    - constraints_translated == 0 (all three are drop-with-warning types).
    - constraints_dropped >= 3.
    - warnings list contains at least 3 entries.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# FastAPI TestClient
try:
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
except ImportError:
    pytest.skip("fastapi/httpx not installed", allow_module_level=True)

from kerf_imports.freecad.route import router

# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------

app = FastAPI()
app.include_router(router)
client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"

FIXTURES_AVAILABLE = FIXTURE_DIR.is_dir() and any(FIXTURE_DIR.glob("*.FCStd"))

skip_no_fixtures = pytest.mark.skipif(
    not FIXTURES_AVAILABLE,
    reason="FCStd fixture files not found in tests/freecad/fixtures/. "
           "Run: python scripts/generate_freecad_fixtures.py",
)


def _upload(name: str, import_folder: str = "/freecad_import") -> dict[str, Any]:
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"Fixture {name} not found")
    data = path.read_bytes()
    resp = client.post(
        f"/import-freecad-project?import_folder={import_folder}",
        files={"file": (name, data, "application/octet-stream")},
    )
    assert resp.status_code == 200, f"Route error {resp.status_code}: {resp.text[:300]}"
    return resp.json()


# ---------------------------------------------------------------------------
# single_pad.FCStd
# ---------------------------------------------------------------------------

@skip_no_fixtures
class TestSinglePadFixture:
    def test_returns_200(self):
        result = _upload("single_pad.FCStd")
        assert "created_files" in result

    def test_one_sketch_file(self):
        result = _upload("single_pad.FCStd")
        sketch_files = [f for f in result["created_files"] if f["kind"] == "sketch"]
        assert len(sketch_files) == 1

    def test_one_feature_file(self):
        result = _upload("single_pad.FCStd")
        feature_files = [f for f in result["created_files"] if f["kind"] == "feature"]
        assert len(feature_files) == 1

    def test_no_assembly_file(self):
        result = _upload("single_pad.FCStd")
        assembly_files = [f for f in result["created_files"] if f["kind"] == "assembly"]
        assert len(assembly_files) == 0

    def test_stats_bodies(self):
        result = _upload("single_pad.FCStd")
        assert result["stats"]["bodies"] >= 1

    def test_stats_sketches(self):
        result = _upload("single_pad.FCStd")
        assert result["stats"]["sketches"] == 1

    def test_import_folder_in_response(self):
        result = _upload("single_pad.FCStd", "/my_import")
        assert result["import_folder"] == "/my_import"

    def test_feature_payload_has_nodes(self):
        result = _upload("single_pad.FCStd")
        feat = next(f for f in result["created_files"] if f["kind"] == "feature")
        assert "nodes" in feat["payload"]

    def test_sketch_payload_has_entities(self):
        result = _upload("single_pad.FCStd")
        sk = next(f for f in result["created_files"] if f["kind"] == "sketch")
        assert "entities" in sk["payload"]
        assert len(sk["payload"]["entities"]) == 4  # rectangle: 4 lines

    def test_sketch_constraints_translated(self):
        result = _upload("single_pad.FCStd")
        # 4 Horizontal/Vertical constraints on the rectangle
        assert result["stats"]["constraints_translated"] >= 4


# ---------------------------------------------------------------------------
# pad_and_pocket.FCStd
# ---------------------------------------------------------------------------

@skip_no_fixtures
class TestPadAndPocketFixture:
    def test_two_sketch_files(self):
        result = _upload("pad_and_pocket.FCStd")
        sketch_files = [f for f in result["created_files"] if f["kind"] == "sketch"]
        assert len(sketch_files) == 2

    def test_one_feature_file(self):
        result = _upload("pad_and_pocket.FCStd")
        feature_files = [f for f in result["created_files"] if f["kind"] == "feature"]
        assert len(feature_files) == 1

    def test_no_assembly(self):
        result = _upload("pad_and_pocket.FCStd")
        assembly_files = [f for f in result["created_files"] if f["kind"] == "assembly"]
        assert len(assembly_files) == 0

    def test_stats_sketches(self):
        result = _upload("pad_and_pocket.FCStd")
        assert result["stats"]["sketches"] == 2

    def test_feature_has_pad_and_pocket_nodes(self):
        result = _upload("pad_and_pocket.FCStd")
        feat = next(f for f in result["created_files"] if f["kind"] == "feature")
        node_kinds = {n["kind"] for n in feat["payload"]["nodes"]}
        assert "pad" in node_kinds
        assert "pocket" in node_kinds


# ---------------------------------------------------------------------------
# two_bodies.FCStd
# ---------------------------------------------------------------------------

@skip_no_fixtures
class TestTwoBodiesFixture:
    def test_two_feature_files(self):
        result = _upload("two_bodies.FCStd")
        feature_files = [f for f in result["created_files"] if f["kind"] == "feature"]
        assert len(feature_files) == 2

    def test_one_assembly_file(self):
        result = _upload("two_bodies.FCStd")
        assembly_files = [f for f in result["created_files"] if f["kind"] == "assembly"]
        assert len(assembly_files) == 1

    def test_assembly_named_main(self):
        result = _upload("two_bodies.FCStd")
        asm = next(f for f in result["created_files"] if f["kind"] == "assembly")
        assert asm["name"] == "main.assembly"

    def test_assembly_two_components(self):
        result = _upload("two_bodies.FCStd")
        asm = next(f for f in result["created_files"] if f["kind"] == "assembly")
        assert len(asm["payload"]["components"]) == 2

    def test_stats_bodies(self):
        result = _upload("two_bodies.FCStd")
        assert result["stats"]["bodies"] == 2

    def test_assembly_components_have_transforms(self):
        result = _upload("two_bodies.FCStd")
        asm = next(f for f in result["created_files"] if f["kind"] == "assembly")
        for comp in asm["payload"]["components"]:
            assert "transform" in comp
            assert len(comp["transform"]) == 4

    def test_second_body_translated(self):
        """Body001 has Placement.Px=50 — check it's in the transform."""
        result = _upload("two_bodies.FCStd")
        asm = next(f for f in result["created_files"] if f["kind"] == "assembly")
        # Find component for Body001 (non-zero translation)
        translated = [
            c for c in asm["payload"]["components"]
            if abs(c["transform"][0][3]) > 1.0  # Px ≈ 50
        ]
        assert len(translated) >= 1


# ---------------------------------------------------------------------------
# sketch_constraints.FCStd
# ---------------------------------------------------------------------------

@skip_no_fixtures
class TestSketchConstraintsFixture:
    def test_one_sketch_file(self):
        result = _upload("sketch_constraints.FCStd")
        sketch_files = [f for f in result["created_files"] if f["kind"] == "sketch"]
        assert len(sketch_files) == 1

    def test_constraints_translated(self):
        result = _upload("sketch_constraints.FCStd")
        # 5 constraints: Coincident, Distance, Angle, Tangent, Radius
        assert result["stats"]["constraints_translated"] >= 4

    def test_no_constraints_dropped(self):
        result = _upload("sketch_constraints.FCStd")
        assert result["stats"]["constraints_dropped"] == 0

    def test_no_warnings_for_valid_constraints(self):
        result = _upload("sketch_constraints.FCStd")
        # Warnings from geometry (arc is ok) but no constraint warnings
        constraint_warnings = [
            w for w in result["warnings"]
            if "Snell" in w or "Weight" in w or "InternalAlignment" in w
        ]
        assert constraint_warnings == []

    def test_sketch_has_correct_entity_types(self):
        result = _upload("sketch_constraints.FCStd")
        sk = next(f for f in result["created_files"] if f["kind"] == "sketch")
        entity_types = {e["type"] for e in sk["payload"]["entities"]}
        assert "line" in entity_types
        assert "arc" in entity_types


# ---------------------------------------------------------------------------
# unsupported_constraints.FCStd
# ---------------------------------------------------------------------------

@skip_no_fixtures
class TestUnsupportedConstraintsFixture:
    def test_one_sketch_file(self):
        result = _upload("unsupported_constraints.FCStd")
        sketch_files = [f for f in result["created_files"] if f["kind"] == "sketch"]
        assert len(sketch_files) == 1

    def test_all_constraints_dropped(self):
        """All 3 constraints are drop-with-warning types (SnellsLaw, Weight, InternalAlignment)."""
        result = _upload("unsupported_constraints.FCStd")
        assert result["stats"]["constraints_translated"] == 0
        assert result["stats"]["constraints_dropped"] == 3

    def test_warnings_emitted(self):
        result = _upload("unsupported_constraints.FCStd")
        # Should have at least 3 warnings (one per dropped constraint)
        # plus possibly geometry warnings for the B-spline
        assert len(result["warnings"]) >= 3

    def test_snells_law_warning_present(self):
        result = _upload("unsupported_constraints.FCStd")
        assert any("Snell" in w for w in result["warnings"])

    def test_weight_warning_present(self):
        result = _upload("unsupported_constraints.FCStd")
        assert any("weight" in w.lower() or "Weight" in w for w in result["warnings"])

    def test_internal_alignment_warning_present(self):
        result = _upload("unsupported_constraints.FCStd")
        assert any("InternalAlignment" in w for w in result["warnings"])

    def test_bspline_entity_is_construction(self):
        result = _upload("unsupported_constraints.FCStd")
        sk = next(f for f in result["created_files"] if f["kind"] == "sketch")
        bsplines = [e for e in sk["payload"]["entities"] if e.get("type") == "bspline"]
        assert len(bsplines) == 1
        assert bsplines[0].get("construction") is True
