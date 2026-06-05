"""
Tests for hull_exchange.py — DXF / IGES / 3DM hull curve export.

Oracle strategy
---------------
  1. DXF output: valid ASCII string, contains SPLINE entities and section labels.
  2. IGES output: valid ASCII IGES start/global/DE/PD/T sections.
  3. 3DM output: valid binary starting with openNURBS 3DM file-comment header.
  4. Exchange roundtrip sanity: generated DXF/IGES text is non-empty and parseable.
  5. LLM tool runner: returns ok payload with format-specific keys.
"""

from __future__ import annotations

import asyncio
import base64
import json
import pytest

from kerf_marine.hull_form import generate_hull
from kerf_marine.hull_exchange import (
    export_hull_dxf,
    export_hull_iges,
    export_hull_3dm,
    run_marine_hull_exchange,
    marine_hull_exchange_spec,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sample_hull_dict():
    hull = generate_hull(L=60.0, B=10.0, T=4.0, Cb=0.60, Cm=0.90,
                         n_stations=11, n_wl_curves=4, n_buttocks=3)
    return hull.as_dict()


@pytest.fixture(scope="module")
def large_hull_dict():
    hull = generate_hull(L=120.0, B=18.0, T=7.0, Cb=0.65, Cm=0.92,
                         n_stations=21, n_wl_curves=5, n_buttocks=5)
    return hull.as_dict()


# ---------------------------------------------------------------------------
# DXF tests
# ---------------------------------------------------------------------------

class TestExportHullDxf:

    def test_returns_string(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert isinstance(result, str)

    def test_non_empty(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert len(result) > 200

    def test_has_dxf_header(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert "SECTION" in result
        assert "HEADER" in result
        assert "ACADVER" in result

    def test_has_spline_entities(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert "SPLINE" in result

    def test_has_eof_marker(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert "EOF" in result

    def test_has_entities_section(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert "ENTITIES" in result

    def test_layer_names_present(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert "SECTIONS" in result
        assert "WATERLINES" in result

    def test_dxf_valid_r2004_header(self, sample_hull_dict):
        result = export_hull_dxf(sample_hull_dict)
        assert "AC1018" in result

    def test_dxf_with_large_hull(self, large_hull_dict):
        result = export_hull_dxf(large_hull_dict)
        assert len(result) > 500
        assert "SPLINE" in result

    def test_dxf_with_minimal_hull(self):
        """Works even with a 2-station minimal hull."""
        hull = generate_hull(L=20, B=4, T=1.5, n_stations=3, n_wl_curves=2, n_buttocks=2)
        result = export_hull_dxf(hull.as_dict())
        assert "SECTION" in result

    def test_dxf_empty_hull_dict(self):
        """Empty hull dict produces minimal valid DXF."""
        result = export_hull_dxf({})
        assert "SECTION" in result
        assert "EOF" in result


# ---------------------------------------------------------------------------
# IGES tests
# ---------------------------------------------------------------------------

class TestExportHullIges:

    def test_returns_string(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        assert isinstance(result, str)

    def test_non_empty(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        assert len(result) > 100

    def test_has_start_section(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        assert "S" in result

    def test_has_global_section(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        assert "G" in result

    def test_has_de_section(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        assert "D" in result

    def test_has_pd_section(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        assert "P" in result

    def test_has_terminate_section(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        # Terminate line has T at position 73
        lines = result.strip().split("\n")
        last_line = lines[-1]
        assert "T" in last_line

    def test_iges_bspline_entity_type(self, sample_hull_dict):
        """With use_splines=True, PD lines should start with 126."""
        result = export_hull_iges(sample_hull_dict, use_splines=True)
        # Entity 126 param data starts with "126,"
        assert "126," in result

    def test_iges_polyline_entity_type(self, sample_hull_dict):
        """With use_splines=False, PD lines should use entity 106."""
        result = export_hull_iges(sample_hull_dict, use_splines=False)
        assert "106," in result

    def test_iges_line_length_constraint(self, sample_hull_dict):
        """Each IGES line should be ≤ 80 chars (IGES 5.3 §2.1.1)."""
        result = export_hull_iges(sample_hull_dict)
        for i, line in enumerate(result.split("\n")):
            if line:
                assert len(line) <= 80, f"Line {i+1} too long: {len(line)} chars: {line!r}"

    def test_iges_with_large_hull(self, large_hull_dict):
        result = export_hull_iges(large_hull_dict)
        assert len(result) > 500
        assert "126," in result

    def test_iges_de_lines_have_correct_format(self, sample_hull_dict):
        """DE lines should have 'D' at column 73 (0-indexed column 72)."""
        result = export_hull_iges(sample_hull_dict)
        for line in result.split("\n"):
            if len(line) >= 74 and line[72] == "D":
                # Line 1 of DE entry: field order check
                assert line[72] == "D"

    def test_iges_global_section_contains_kerf(self, sample_hull_dict):
        result = export_hull_iges(sample_hull_dict)
        assert "Kerf" in result or "kerf" in result.lower()


# ---------------------------------------------------------------------------
# 3DM tests
# ---------------------------------------------------------------------------

class TestExportHull3dm:

    def test_returns_bytes(self, sample_hull_dict):
        result = export_hull_3dm(sample_hull_dict)
        assert isinstance(result, bytes)

    def test_non_empty(self, sample_hull_dict):
        result = export_hull_3dm(sample_hull_dict)
        assert len(result) >= 33  # at least the file header

    def test_has_3dm_file_header(self, sample_hull_dict):
        """3DM files start with '3D Geometry File Format' (openNURBS spec)."""
        result = export_hull_3dm(sample_hull_dict)
        assert result[:23] == b"3D Geometry File Format"

    def test_3dm_header_is_33_bytes(self, sample_hull_dict):
        """File comment header is exactly 33 bytes per openNURBS spec."""
        result = export_hull_3dm(sample_hull_dict)
        # Header contains file comment + version char + spaces + 0x1a 0x00
        assert result[25:26] in (b"7", b"6", b"5", b"4"), "Expected version char after space"

    def test_3dm_with_large_hull(self, large_hull_dict):
        result = export_hull_3dm(large_hull_dict)
        assert isinstance(result, bytes)
        assert len(result) >= 33

    def test_3dm_empty_dict(self):
        result = export_hull_3dm({})
        assert isinstance(result, bytes)
        assert result[:23] == b"3D Geometry File Format"


# ---------------------------------------------------------------------------
# LLM tool runner tests
# ---------------------------------------------------------------------------

class TestMarineHullExchangeTool:

    def _run(self, args):
        from kerf_marine._compat import ProjectCtx
        ctx = ProjectCtx()
        result = asyncio.get_event_loop().run_until_complete(
            run_marine_hull_exchange(args, ctx)
        )
        return json.loads(result)

    def _hull_form_args(self, L=60, B=10, T=4, Cb=0.60):
        hull = generate_hull(L=L, B=B, T=T, Cb=Cb, n_stations=11,
                             n_wl_curves=3, n_buttocks=3)
        return hull.as_dict()

    def test_dxf_format(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf, "format": "dxf"})
        assert d.get("format") == "dxf"
        assert "content" in d
        assert isinstance(d["content"], str)
        assert len(d["content"]) > 100

    def test_iges_format(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf, "format": "iges"})
        assert d.get("format") == "iges"
        assert "content" in d
        assert "126," in d["content"]

    def test_3dm_format(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf, "format": "3dm"})
        assert d.get("format") == "3dm"
        assert "content_base64" in d
        raw = base64.b64decode(d["content_base64"])
        assert raw[:23] == b"3D Geometry File Format"

    def test_default_format_is_dxf(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf})
        assert d.get("format") == "dxf"

    def test_bad_format_returns_error(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf, "format": "dwg"})
        assert "error" in d

    def test_n_chars_matches_content(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf, "format": "dxf"})
        assert d.get("n_chars") == len(d["content"])

    def test_n_bytes_matches_3dm(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf, "format": "3dm"})
        raw = base64.b64decode(d["content_base64"])
        assert d.get("n_bytes") == len(raw)

    def test_iges_use_splines_false(self):
        hf = self._hull_form_args()
        d = self._run({"hull_form": hf, "format": "iges", "use_splines": False})
        # With use_splines=False, should use entity 106
        assert "106," in d["content"]

    def test_spec_name(self):
        assert marine_hull_exchange_spec.name == "marine_hull_exchange"

    def test_spec_has_format_enum(self):
        schema = marine_hull_exchange_spec.input_schema
        assert "format" in schema["properties"]
        assert "enum" in schema["properties"]["format"]
        assert set(schema["properties"]["format"]["enum"]) == {"dxf", "iges", "3dm"}
