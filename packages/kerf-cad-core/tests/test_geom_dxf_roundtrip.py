"""
Tests for GK-125: DXF read + write (2D).

Oracle: write→read round-trip preserves:
  - entity count
  - layer names
  - a circle's radius (to floating-point precision)
"""

import os
import tempfile
import math
import pytest

from kerf_cad_core.geom.io.dxf import (
    read_dxf,
    write_dxf,
    DxfReadError,
    DxfWriteError,
)
# Also verify top-level exports
from kerf_cad_core.geom import (
    read_dxf as geom_read_dxf,
    write_dxf as geom_write_dxf,
    DxfReadError as GeomDxfReadError,
    DxfWriteError as GeomDxfWriteError,
)
from kerf_cad_core.geom.io import (
    read_dxf as io_read_dxf,
    write_dxf as io_write_dxf,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MIXED_ENTITIES = [
    {
        "type": "LINE",
        "layer": "construction",
        "start": [0.0, 0.0, 0.0],
        "end": [10.0, 5.0, 0.0],
    },
    {
        "type": "CIRCLE",
        "layer": "geometry",
        "center": [5.0, 5.0, 0.0],
        "radius": 3.14159265358979,
    },
    {
        "type": "ARC",
        "layer": "geometry",
        "center": [0.0, 0.0, 0.0],
        "radius": 7.5,
        "start_angle": 30.0,
        "end_angle": 150.0,
    },
    {
        "type": "LWPOLYLINE",
        "layer": "outline",
        "vertices": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        "closed": True,
        "const_width": 0.0,
    },
    {
        "type": "SPLINE",
        "layer": "curves",
        "degree": 3,
        "knots": [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0],
        "control_points": [
            [0.0, 0.0, 0.0],
            [1.0, 2.0, 0.0],
            [3.0, 2.0, 0.0],
            [4.0, 0.0, 0.0],
        ],
        "closed": False,
    },
]

EXPECTED_LAYERS = {"construction", "geometry", "outline", "curves"}


# ---------------------------------------------------------------------------
# Core oracle tests
# ---------------------------------------------------------------------------

def test_roundtrip_entity_count():
    """write→read round-trip preserves entity count."""
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, MIXED_ENTITIES)
        result = read_dxf(path)
        assert len(result["entities"]) == len(MIXED_ENTITIES), (
            f"Expected {len(MIXED_ENTITIES)} entities, got {len(result['entities'])}"
        )
    finally:
        os.unlink(path)


def test_roundtrip_layer_names():
    """write→read round-trip preserves layer names."""
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, MIXED_ENTITIES)
        result = read_dxf(path)
        returned_layers = set(result["layers"])
        # All entity layers must be present
        assert EXPECTED_LAYERS.issubset(returned_layers), (
            f"Missing layers: {EXPECTED_LAYERS - returned_layers}"
        )
    finally:
        os.unlink(path)


def test_roundtrip_circle_radius():
    """A circle's radius survives write→read to full float precision."""
    radius = 3.14159265358979
    entities = [
        {
            "type": "CIRCLE",
            "layer": "test",
            "center": [1.0, 2.0, 0.0],
            "radius": radius,
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, entities)
        result = read_dxf(path)
        assert len(result["entities"]) == 1
        circle = result["entities"][0]
        assert circle["type"] == "CIRCLE"
        assert abs(circle["radius"] - radius) < 1e-6, (
            f"Radius changed: expected {radius}, got {circle['radius']}"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Per-entity type round-trip tests
# ---------------------------------------------------------------------------

def test_roundtrip_line():
    entities = [
        {
            "type": "LINE",
            "layer": "L1",
            "start": [1.0, 2.0, 0.0],
            "end": [3.0, 4.0, 0.0],
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, entities)
        result = read_dxf(path)
        ent = result["entities"][0]
        assert ent["type"] == "LINE"
        assert ent["layer"] == "L1"
        assert abs(ent["start"][0] - 1.0) < 1e-6
        assert abs(ent["end"][1] - 4.0) < 1e-6
    finally:
        os.unlink(path)


def test_roundtrip_arc():
    entities = [
        {
            "type": "ARC",
            "layer": "arcs",
            "center": [0.0, 0.0, 0.0],
            "radius": 5.0,
            "start_angle": 45.0,
            "end_angle": 270.0,
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, entities)
        result = read_dxf(path)
        ent = result["entities"][0]
        assert ent["type"] == "ARC"
        assert abs(ent["radius"] - 5.0) < 1e-6
        assert abs(ent["start_angle"] - 45.0) < 1e-6
        assert abs(ent["end_angle"] - 270.0) < 1e-6
    finally:
        os.unlink(path)


def test_roundtrip_lwpolyline():
    verts = [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0]]
    entities = [
        {
            "type": "LWPOLYLINE",
            "layer": "poly",
            "vertices": verts,
            "closed": True,
            "const_width": 0.0,
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, entities)
        result = read_dxf(path)
        ent = result["entities"][0]
        assert ent["type"] == "LWPOLYLINE"
        assert ent["closed"] is True
        assert len(ent["vertices"]) == 3
        assert abs(ent["vertices"][1][0] - 5.0) < 1e-6
    finally:
        os.unlink(path)


def test_roundtrip_spline():
    knots = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    cps = [[0.0, 0.0, 0.0], [1.0, 2.0, 0.0], [3.0, 2.0, 0.0], [4.0, 0.0, 0.0]]
    entities = [
        {
            "type": "SPLINE",
            "layer": "splines",
            "degree": 3,
            "knots": knots,
            "control_points": cps,
            "closed": False,
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, entities)
        result = read_dxf(path)
        ent = result["entities"][0]
        assert ent["type"] == "SPLINE"
        assert ent["degree"] == 3
        assert len(ent["knots"]) == len(knots)
        assert len(ent["control_points"]) == len(cps)
        assert ent["closed"] is False
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Layer table tests
# ---------------------------------------------------------------------------

def test_layer_table_written_and_read():
    """Layer attributes are stored and layer names survive round-trip."""
    entities = [
        {"type": "LINE", "layer": "red_layer", "start": [0, 0, 0], "end": [1, 0, 0]},
    ]
    layer_attrs = {
        "red_layer": {"color": 1, "linetype": "CONTINUOUS"},
    }
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, entities, layers=layer_attrs)
        result = read_dxf(path)
        assert "red_layer" in result["layers"]
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Export symbol tests
# ---------------------------------------------------------------------------

def test_top_level_geom_exports():
    """Symbols are accessible from kerf_cad_core.geom directly."""
    assert geom_read_dxf is read_dxf
    assert geom_write_dxf is write_dxf
    assert GeomDxfReadError is DxfReadError
    assert GeomDxfWriteError is DxfWriteError


def test_io_package_exports():
    """Symbols are accessible from kerf_cad_core.geom.io directly."""
    assert io_read_dxf is read_dxf
    assert io_write_dxf is write_dxf


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_read_missing_file_raises():
    with pytest.raises(DxfReadError):
        read_dxf("/nonexistent/path/file.dxf")


def test_write_unsupported_entity_raises():
    entities = [{"type": "UNKNOWN_ENTITY", "layer": "0"}]
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        with pytest.raises(DxfWriteError):
            write_dxf(path, entities)
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_entities():
    """write→read with empty entity list returns empty list."""
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, [])
        result = read_dxf(path)
        assert result["entities"] == []
        assert "0" in result["layers"]
    finally:
        os.unlink(path)


def test_default_layer_zero():
    """Entity without explicit layer defaults to '0'."""
    entities = [
        {
            "type": "CIRCLE",
            "center": [0.0, 0.0, 0.0],
            "radius": 1.0,
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
        path = f.name
    try:
        write_dxf(path, entities)
        result = read_dxf(path)
        assert result["entities"][0].get("layer", "0") == "0"
    finally:
        os.unlink(path)
