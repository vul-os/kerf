"""
Tests for IC package / substrate design tools.

Covers:
  - ic_package_create: basic creation, wire-bond, flip-chip, ball grid, net map
  - ic_package_drc:    bond-wire length/angle limits, bump pitch, ball pitch,
                       net-map integrity, substrate vs die size
"""

import json
import pytest

from kerf_electronics.ic_package.tools import ic_package_create, ic_package_drc


# ── helpers ───────────────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


def minimal_pkg():
    """Smallest valid ic_package as returned by ic_package_create."""
    return {
        "name": "TestPkg",
        "package_type": "wire_bond",
        "die": {
            "width_mm": 3.0,
            "height_mm": 3.0,
            "pad_pitch_um": 100.0,
            "pads": [
                {"id": "P1", "side": "top", "x_mm": 0.5, "y_mm": 1.5},
                {"id": "P2", "side": "top", "x_mm": 1.0, "y_mm": 1.5},
            ],
        },
        "substrate": {
            "width_mm": 6.0,
            "height_mm": 6.0,
            "layers": 4,
            "material": "BT resin",
        },
        "bonds": [],
        "ball_grid": {
            "rows": 2,
            "cols": 2,
            "pitch_mm": 0.5,
            "ball_diameter_mm": 0.3,
            "balls": [
                {"id": "A1", "row": 0, "col": 0, "net": "GND"},
                {"id": "A2", "row": 0, "col": 1, "net": "VCC"},
                {"id": "B1", "row": 1, "col": 0, "net": "P1_net"},
                {"id": "B2", "row": 1, "col": 1, "net": "P2_net"},
            ],
        },
        "net_map": {"P1": "B1", "P2": "B2"},
    }


# ── ic_package_create ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_minimal():
    r = await call(
        ic_package_create,
        name="BGA256",
        package_type="bga_only",
    )
    assert "ic_package" in r
    assert r["ic_package"]["name"] == "BGA256"
    assert r["ic_package"]["package_type"] == "bga_only"
    assert r["ic_package"]["net_map"] == {}


@pytest.mark.asyncio
async def test_create_wire_bond_with_bonds():
    r = await call(
        ic_package_create,
        name="WBPkg",
        package_type="wire_bond",
        die={"width_mm": 2.0, "height_mm": 2.0, "pads": [{"id": "P1", "x_mm": 0.5, "y_mm": 1.0}]},
        substrate={"width_mm": 5.0, "height_mm": 5.0, "layers": 2},
        bonds=[{"type": "wire_bond", "die_pad": "P1", "finger_id": "F1",
                "length_mm": 1.5, "angle_deg": 10.0, "wire_diameter_um": 25.0}],
        ball_grid={"rows": 4, "cols": 4, "pitch_mm": 0.5,
                   "balls": [{"id": "A1", "row": 0, "col": 0}]},
        net_map={},
    )
    assert r["ic_package"]["package_type"] == "wire_bond"
    assert len(r["ic_package"]["bonds"]) == 1
    assert r["ic_package"]["bonds"][0]["die_pad"] == "P1"


@pytest.mark.asyncio
async def test_create_net_map_correct():
    """Net map die-pad → ball-id must be consistent."""
    r = await call(
        ic_package_create,
        name="FCPkg",
        package_type="flip_chip",
        die={"width_mm": 2.0, "height_mm": 2.0,
             "pads": [{"id": "P1", "x_mm": 0.5, "y_mm": 0.5}]},
        ball_grid={"rows": 1, "cols": 1, "pitch_mm": 0.5,
                   "balls": [{"id": "A1", "row": 0, "col": 0}]},
        net_map={"P1": "A1"},
    )
    assert "ic_package" in r
    assert r["ic_package"]["net_map"]["P1"] == "A1"


@pytest.mark.asyncio
async def test_create_invalid_net_map_rejected():
    """Net map referencing non-existent die pad must be rejected."""
    r = await call(
        ic_package_create,
        name="Bad",
        package_type="flip_chip",
        die={"width_mm": 2.0, "height_mm": 2.0,
             "pads": [{"id": "P1", "x_mm": 0.5, "y_mm": 0.5}]},
        ball_grid={"rows": 1, "cols": 1, "pitch_mm": 0.5,
                   "balls": [{"id": "A1", "row": 0, "col": 0}]},
        net_map={"GHOST_PAD": "A1"},  # die pad 'GHOST_PAD' does not exist
    )
    assert "error" in r
    assert "die pad" in r["error"].lower()


@pytest.mark.asyncio
async def test_create_invalid_package_type():
    r = await call(ic_package_create, name="X", package_type="laser_bond")
    assert "error" in r


@pytest.mark.asyncio
async def test_create_missing_name():
    r = await call(ic_package_create, name="", package_type="bga_only")
    assert "error" in r


# ── ic_package_drc ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drc_clean_package_passes():
    r = await call(ic_package_drc, ic_package=minimal_pkg())
    assert r["pass"] is True
    assert r["error_count"] == 0


@pytest.mark.asyncio
async def test_drc_wire_bond_too_long():
    pkg = minimal_pkg()
    pkg["bonds"] = [{"type": "wire_bond", "die_pad": "P1", "finger_id": "F1",
                     "length_mm": 8.0, "angle_deg": 5.0}]  # > 6 mm limit
    r = await call(ic_package_drc, ic_package=pkg)
    assert r["pass"] is False
    assert any("WIRE_LENGTH_MAX" in v["rule"] for v in r["violations"])


@pytest.mark.asyncio
async def test_drc_wire_bond_too_short():
    pkg = minimal_pkg()
    pkg["bonds"] = [{"type": "wire_bond", "die_pad": "P1", "finger_id": "F1",
                     "length_mm": 0.05, "angle_deg": 0.0}]  # < 0.1 mm limit
    r = await call(ic_package_drc, ic_package=pkg)
    assert r["pass"] is False
    assert any("WIRE_LENGTH_MIN" in v["rule"] for v in r["violations"])


@pytest.mark.asyncio
async def test_drc_wire_angle_exceeded():
    pkg = minimal_pkg()
    pkg["bonds"] = [{"type": "wire_bond", "die_pad": "P1", "finger_id": "F1",
                     "length_mm": 1.5, "angle_deg": 60.0}]  # > 45° limit
    r = await call(ic_package_drc, ic_package=pkg)
    assert r["pass"] is False
    assert any("WIRE_ANGLE_MAX" in v["rule"] for v in r["violations"])


@pytest.mark.asyncio
async def test_drc_bump_pitch_too_small():
    pkg = minimal_pkg()
    pkg["package_type"] = "flip_chip"
    pkg["bonds"] = [{"type": "bump", "die_pad": "P1", "ball_id": "A1",
                     "pitch_um": 20.0, "diameter_um": 15.0}]  # < 40 µm limit
    r = await call(ic_package_drc, ic_package=pkg)
    assert r["pass"] is False
    assert any("BUMP_PITCH_MIN" in v["rule"] for v in r["violations"])


@pytest.mark.asyncio
async def test_drc_bga_ball_pitch_too_small():
    pkg = minimal_pkg()
    pkg["ball_grid"]["pitch_mm"] = 0.15  # < 0.3 mm JEDEC JEP95 limit
    r = await call(ic_package_drc, ic_package=pkg)
    assert r["pass"] is False
    assert any("BGA_BALL_PITCH_MIN" in v["rule"] for v in r["violations"])


@pytest.mark.asyncio
async def test_drc_valid_bga_pitch_passes():
    pkg = minimal_pkg()
    pkg["ball_grid"]["pitch_mm"] = 0.5  # well above limit
    r = await call(ic_package_drc, ic_package=pkg)
    # Should have no ball-pitch violations (may still pass clean)
    ball_viols = [v for v in r["violations"] if v["rule"] == "BGA_BALL_PITCH_MIN"]
    assert ball_viols == []


@pytest.mark.asyncio
async def test_drc_substrate_smaller_than_die():
    pkg = minimal_pkg()
    pkg["substrate"]["width_mm"] = 1.0  # smaller than die 3.0 mm
    r = await call(ic_package_drc, ic_package=pkg)
    assert r["pass"] is False
    assert any("SUBSTRATE_SMALLER_THAN_DIE" in v["rule"] for v in r["violations"])


@pytest.mark.asyncio
async def test_drc_net_map_invalid_ball():
    pkg = minimal_pkg()
    pkg["net_map"]["P1"] = "GHOST_BALL"  # ball 'GHOST_BALL' does not exist
    r = await call(ic_package_drc, ic_package=pkg)
    assert r["pass"] is False
    assert any("NET_MAP_INTEGRITY" in v["rule"] for v in r["violations"])
