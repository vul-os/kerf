"""
Tests for kerf_mold.cooling_channel_conflict — cooling-channel conflict detection.

Oracle coverage (all analytic, no magic numbers):

  1. Parallel channels with adequate spacing -> zero CHANNEL_SPACING conflicts.
  2. Parallel channels too close -> CHANNEL_SPACING conflict with severity >= 3.
  3. Channel crossing ejector-pin path -> CHANNEL_EJECTOR conflict.
  4. Channel exiting mold-base bounds -> MOLD_BOUNDS conflict.
  5. Channel too close to cavity face -> WALL_CLEARANCE conflict.
  6. Channel co-located with another (overlap) -> severity 5.
  7. Multiple conflict types in one layout -> all types reported.
  8. Curved-channel flag -> scope_warning emitted, conflicts still reported.
  9. Channel well within mold bounds -> no MOLD_BOUNDS conflict.
 10. Channel far from cavity wall -> no WALL_CLEARANCE conflict.
 11. Segment-segment closest distance: parallel lines.
 12. Segment-segment closest distance: perpendicular crossing.
 13. Severity scale mapping.

References
----------
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001 — §6.5 Cooling-channel design rules.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_mold.cooling_channel_conflict import (
    CavityWall,
    CoolingChannel3D,
    EjectorPin3D,
    MoldBbox,
    verify_cooling_channels,
    _segment_segment_closest,
    _severity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bbox(size=200.0) -> MoldBbox:
    """Axis-aligned cube mold base: 0..size in each axis."""
    return MoldBbox(0, size, 0, size, 0, size)


# ---------------------------------------------------------------------------
# 1. Adequate spacing -> no conflict
# ---------------------------------------------------------------------------

def test_adequate_channel_spacing_no_conflict():
    """Two parallel channels with 3x diameter c-t-c -> no spacing conflict."""
    d = 10.0  # diameter mm
    # min_spacing_factor=2.0 -> min edge gap = 2.0 × (d/2) = d = 10 mm
    # place channels d/2 + gap + d/2 = 10 + 20 = 30 mm apart c-t-c -> gap = 20 mm
    ch1 = CoolingChannel3D(start=(0, 15, 50), end=(200, 15, 50), diameter_mm=d, label="ch1")
    ch2 = CoolingChannel3D(start=(0, 45, 50), end=(200, 45, 50), diameter_mm=d, label="ch2")
    # c-t-c = 30 mm, radii sum = 10 mm, edge gap = 20 mm >= required 10 mm
    report = verify_cooling_channels(
        [ch1, ch2], [], _bbox(), [], min_spacing_factor=2.0
    )
    spacing_conflicts = [c for c in report.conflicts if c.conflict_type == "CHANNEL_SPACING"]
    assert len(spacing_conflicts) == 0, (
        f"Expected no spacing conflicts, got: {spacing_conflicts}"
    )


# ---------------------------------------------------------------------------
# 2. Channels too close -> CHANNEL_SPACING conflict
# ---------------------------------------------------------------------------

def test_close_channels_spacing_conflict():
    """Two parallel channels at 1.5x diameter c-t-c -> CHANNEL_SPACING conflict."""
    d = 10.0
    # c-t-c = 15 mm -> edge gap = 15 - 5 - 5 = 5 mm
    # min required (factor=2) = 2 × 5 = 10 mm -> gap < required -> conflict
    ch1 = CoolingChannel3D(start=(0, 10, 50), end=(200, 10, 50), diameter_mm=d, label="ch1")
    ch2 = CoolingChannel3D(start=(0, 25, 50), end=(200, 25, 50), diameter_mm=d, label="ch2")
    # c-t-c = 15 mm
    report = verify_cooling_channels(
        [ch1, ch2], [], _bbox(), [], min_spacing_factor=2.0
    )
    spacing = [c for c in report.conflicts if c.conflict_type == "CHANNEL_SPACING"]
    assert len(spacing) == 1
    c = spacing[0]
    assert c.gap_mm == pytest.approx(5.0, abs=0.01)
    assert c.min_required_mm == pytest.approx(10.0, abs=0.01)
    assert c.severity >= 3
    assert "ch1" in c.channel_a or "ch2" in c.channel_a


# ---------------------------------------------------------------------------
# 3. Channel crosses ejector-pin path -> CHANNEL_EJECTOR conflict
# ---------------------------------------------------------------------------

def test_channel_ejector_intersection():
    """Horizontal channel and vertical ejector pin that intersect at (100, 50, 50)."""
    d_ch = 10.0   # channel diameter
    d_pin = 4.76  # typical SPI 3/16" pin
    # Channel: horizontal along x at y=50, z=50
    ch = CoolingChannel3D(
        start=(0, 50, 50), end=(200, 50, 50),
        diameter_mm=d_ch, label="ch1"
    )
    # Ejector pin: vertical along z at x=100, y=50 (passes right through channel axis)
    ep = EjectorPin3D(
        start=(100, 50, 0), end=(100, 50, 200),
        diameter_mm=d_pin, label="pin1"
    )
    report = verify_cooling_channels(
        [ch], [ep], _bbox(), [], min_spacing_factor=2.0
    )
    ejector_conflicts = [c for c in report.conflicts if c.conflict_type == "CHANNEL_EJECTOR"]
    assert len(ejector_conflicts) == 1
    ec = ejector_conflicts[0]
    # Centre-to-centre = 0, edge gap = -(r_ch + r_pin) -> severe overlap
    assert ec.gap_mm < 0, f"Expected overlap (gap < 0), got gap={ec.gap_mm}"
    assert ec.severity == 5


# ---------------------------------------------------------------------------
# 4. Channel exiting mold bounds -> MOLD_BOUNDS conflict
# ---------------------------------------------------------------------------

def test_channel_exits_mold_bounds():
    """Channel end point 20 mm outside the mold-base bounding box -> MOLD_BOUNDS."""
    bbox = MoldBbox(0, 100, 0, 100, 0, 100)
    # Channel runs from inside (10, 50, 50) to well outside (130, 50, 50)
    ch = CoolingChannel3D(
        start=(10, 50, 50), end=(130, 50, 50),
        diameter_mm=10.0, label="ch1"
    )
    report = verify_cooling_channels(
        [ch], [], bbox, [], min_spacing_factor=2.0
    )
    bounds_conflicts = [c for c in report.conflicts if c.conflict_type == "MOLD_BOUNDS"]
    assert len(bounds_conflicts) == 1
    bc = bounds_conflicts[0]
    assert bc.gap_mm < 0, f"Expected negative clearance (outside), got {bc.gap_mm}"
    assert bc.severity >= 4


# ---------------------------------------------------------------------------
# 5. Wall-clearance violation -> WALL_CLEARANCE conflict
# ---------------------------------------------------------------------------

def test_wall_clearance_violation():
    """Channel running 3 mm from cavity face with 10 mm diameter -> WALL_CLEARANCE."""
    # Cavity face at z=0, normal = (0,0,-1) -> outward pointing down
    wall = CavityWall(
        normal=(0.0, 0.0, -1.0),
        point_on_wall=(0.0, 0.0, 0.0),
        label="cavity_bottom",
    )
    d = 10.0  # channel diameter = 10 mm, radius = 5 mm
    # Channel at z=3 mm (centreline 3 mm from the cavity face plane z=0)
    # edge-of-bore clearance = 3 - 5 = -2 mm (channel cuts through the face!)
    # min required = factor × radius = 2.0 × 5 = 10 mm
    ch = CoolingChannel3D(
        start=(10, 50, 3), end=(190, 50, 3),
        diameter_mm=d, label="ch1"
    )
    report = verify_cooling_channels(
        [ch], [], _bbox(), [wall], min_spacing_factor=2.0
    )
    wall_conflicts = [c for c in report.conflicts if c.conflict_type == "WALL_CLEARANCE"]
    assert len(wall_conflicts) == 1
    wc = wall_conflicts[0]
    assert wc.gap_mm == pytest.approx(-2.0, abs=0.01)
    assert wc.severity == 5


# ---------------------------------------------------------------------------
# 6. Overlapping channels -> severity 5
# ---------------------------------------------------------------------------

def test_overlapping_channels_severity_5():
    """Two coincident channels -> gap < 0 -> severity 5."""
    ch1 = CoolingChannel3D(start=(0, 50, 50), end=(200, 50, 50), diameter_mm=10.0, label="ch1")
    ch2 = CoolingChannel3D(start=(0, 50, 50), end=(200, 50, 50), diameter_mm=10.0, label="ch2")
    report = verify_cooling_channels(
        [ch1, ch2], [], _bbox(), [], min_spacing_factor=2.0
    )
    spacing = [c for c in report.conflicts if c.conflict_type == "CHANNEL_SPACING"]
    assert len(spacing) >= 1
    assert spacing[0].severity == 5
    assert spacing[0].gap_mm < 0


# ---------------------------------------------------------------------------
# 7. Multiple conflict types in one layout
# ---------------------------------------------------------------------------

def test_multiple_conflict_types():
    """Spacing + bounds + ejector conflicts all reported in one call."""
    bbox = MoldBbox(0, 100, 0, 100, 0, 100)
    # Pair of channels too close (spacing conflict)
    ch1 = CoolingChannel3D(start=(0, 10, 50), end=(100, 10, 50), diameter_mm=10, label="ch1")
    ch2 = CoolingChannel3D(start=(0, 18, 50), end=(100, 18, 50), diameter_mm=10, label="ch2")
    # Channel that exits bounds
    ch3 = CoolingChannel3D(start=(0, 50, 50), end=(120, 50, 50), diameter_mm=10, label="ch3")
    # Ejector pin that intersects ch3
    pin = EjectorPin3D(start=(60, 50, 0), end=(60, 50, 100), diameter_mm=4.76, label="pin1")

    report = verify_cooling_channels(
        [ch1, ch2, ch3], [pin], bbox, [], min_spacing_factor=2.0
    )
    types_found = {c.conflict_type for c in report.conflicts}
    assert "CHANNEL_SPACING" in types_found
    assert "MOLD_BOUNDS" in types_found
    assert "CHANNEL_EJECTOR" in types_found


# ---------------------------------------------------------------------------
# 8. Curved-channel flag -> scope_warning
# ---------------------------------------------------------------------------

def test_curved_channel_scope_warning():
    """A curved=True channel emits a scope warning."""
    ch = CoolingChannel3D(
        start=(0, 50, 50), end=(200, 50, 50),
        diameter_mm=10.0, label="conf1", curved=True
    )
    report = verify_cooling_channels(
        [ch], [], _bbox(), [], min_spacing_factor=2.0
    )
    assert len(report.scope_warnings) >= 1
    assert any("conf1" in w for w in report.scope_warnings)
    assert any("curved" in w.lower() for w in report.scope_warnings)


# ---------------------------------------------------------------------------
# 9. Channel well inside bounds -> no MOLD_BOUNDS conflict
# ---------------------------------------------------------------------------

def test_channel_inside_bounds_no_conflict():
    """Channel fully inside the mold base -> no MOLD_BOUNDS conflict."""
    bbox = MoldBbox(0, 200, 0, 200, 0, 200)
    ch = CoolingChannel3D(
        start=(20, 100, 50), end=(180, 100, 50),
        diameter_mm=10.0, label="ch1"
    )
    report = verify_cooling_channels(
        [ch], [], bbox, [], min_spacing_factor=2.0
    )
    bounds = [c for c in report.conflicts if c.conflict_type == "MOLD_BOUNDS"]
    assert len(bounds) == 0


# ---------------------------------------------------------------------------
# 10. Channel far from cavity wall -> no WALL_CLEARANCE conflict
# ---------------------------------------------------------------------------

def test_channel_far_from_wall_no_conflict():
    """Channel at z=40 with d=10 and cavity face at z=0 -> gap = 35 mm >> 10 mm required."""
    wall = CavityWall(
        normal=(0.0, 0.0, -1.0),
        point_on_wall=(0.0, 0.0, 0.0),
        label="bottom",
    )
    ch = CoolingChannel3D(
        start=(10, 50, 40), end=(190, 50, 40),
        diameter_mm=10.0, label="ch1"
    )
    report = verify_cooling_channels(
        [ch], [], _bbox(), [wall], min_spacing_factor=2.0
    )
    wall_c = [c for c in report.conflicts if c.conflict_type == "WALL_CLEARANCE"]
    assert len(wall_c) == 0


# ---------------------------------------------------------------------------
# 11-12. Unit tests for internal geometry helpers
# ---------------------------------------------------------------------------

def test_segment_segment_closest_parallel():
    """Two parallel horizontal lines — closest point computation correct."""
    p1, p2 = (0.0, 0.0, 0.0), (10.0, 0.0, 0.0)
    p3, p4 = (0.0, 5.0, 0.0), (10.0, 5.0, 0.0)
    dist, cp1, cp2 = _segment_segment_closest(p1, p2, p3, p4)
    assert dist == pytest.approx(5.0, abs=1e-9)


def test_segment_segment_closest_perpendicular():
    """Two perpendicular segments crossing at origin — minimum distance = 0."""
    p1, p2 = (-5.0, 0.0, 0.0), (5.0, 0.0, 0.0)
    p3, p4 = (0.0, -5.0, 0.0), (0.0, 5.0, 0.0)
    dist, _, _ = _segment_segment_closest(p1, p2, p3, p4)
    assert dist == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 13. Severity scale mapping
# ---------------------------------------------------------------------------

def test_severity_scale():
    """Severity helper maps ratios to expected bands."""
    assert _severity(-1.0, 10.0) == 5         # overlap
    assert _severity(0.0, 10.0) == 5          # zero gap (boundary)
    assert _severity(3.0, 10.0) == 4          # < 0.5 × required
    assert _severity(7.0, 10.0) == 3          # < 1.0 × required
    assert _severity(12.0, 10.0) == 2         # < 1.5 × required
    assert _severity(20.0, 10.0) == 1         # >= 1.5 × required
