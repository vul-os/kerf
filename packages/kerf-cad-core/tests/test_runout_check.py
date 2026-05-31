"""
Tests for kerf_cad_core.gdt.runout_check — ASME Y14.5-2018 §13 / ISO 1101 §18.

Pure-Python, hermetic — no OCC, no DB, no fixtures from disk.

Coverage:
  - Perfect cylinder (all R=nominal): runout=0, compliant
  - Eccentric cylinder (axis offset d): circular runout = 2d
  - Tapered cylinder: total_runout > circular_runout
  - Out-of-tolerance: compliant=False
  - FoM correctness
  - per_section_runout structure
  - Multi-section circular runout picks worst section
  - Single-point-per-section (degenerate: runout=0)
  - Total runout with single section
  - Dataclass validation errors
  - RunoutCheckSpec validation errors
  - check_runout errors on bad inputs
  - Re-export from gdt __init__
  - LLM tool wrapper (sync shim)
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.gdt.runout_check import (
    InspectionPoint,
    RunoutCheckSpec,
    RunoutCheckReport,
    check_runout,
)
# Also check re-export
from kerf_cad_core.gdt import (
    InspectionPoint as InspPt2,
    RunoutCheckSpec as Spec2,
    check_runout as cr2,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ctx():
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    return ProjectCtx(
        pool=None,
        storage=None,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert "error" not in d, f"Expected success payload, got error: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    assert "error" in d, f"Expected error payload, got: {d}"
    return d


def _circle_points(
    radius: float,
    z: float,
    n: int = 12,
    offset_x: float = 0.0,
) -> list[InspectionPoint]:
    """
    Generate n equally-spaced points on a circle of given radius at axial z.
    An optional x-offset simulates axis eccentricity (axis shifted by offset_x).
    """
    import math as _math
    pts = []
    for i in range(n):
        theta = 2 * _math.pi * i / n
        # Actual surface point is at (radius*cos, radius*sin, z) but datum axis
        # is shifted by offset_x in x. Measured radius from datum axis:
        x = radius * _math.cos(theta) - offset_x
        y = radius * _math.sin(theta)
        r_meas = _math.sqrt(x * x + y * y)
        pts.append(InspectionPoint(
            theta_deg=_math.degrees(theta),
            axial_z_mm=z,
            radius_measured_mm=r_meas,
        ))
    return pts


# ---------------------------------------------------------------------------
# Test 1: perfect cylinder — all points at exactly nominal radius
# ---------------------------------------------------------------------------

def test_perfect_cylinder_circular_runout_is_zero():
    """All points at R=10, circular: runout=0, compliant."""
    pts = [InspectionPoint(theta_deg=i * 30.0, axial_z_mm=0.0, radius_measured_mm=10.0)
           for i in range(12)]
    spec = RunoutCheckSpec(
        feature_id="shaft-OD",
        runout_tolerance_mm=0.05,
        runout_type="circular",
        nominal_radius_mm=10.0,
    )
    report = check_runout(spec, pts)
    assert report.max_runout_mm == 0.0
    assert report.compliant is True
    assert report.fom == 0.0
    assert report.mean_radius_mm == pytest.approx(10.0, abs=1e-9)


def test_perfect_cylinder_total_runout_is_zero():
    """All points at R=10, total: runout=0, compliant."""
    pts = [InspectionPoint(theta_deg=i * 30.0, axial_z_mm=float(i % 3), radius_measured_mm=10.0)
           for i in range(12)]
    spec = RunoutCheckSpec(
        feature_id="bore-1",
        runout_tolerance_mm=0.10,
        runout_type="total",
        nominal_radius_mm=10.0,
    )
    report = check_runout(spec, pts)
    assert report.max_runout_mm == 0.0
    assert report.compliant is True
    assert report.fom == 0.0


# ---------------------------------------------------------------------------
# Test 2: eccentric cylinder — axis offset 0.05 mm → circular runout = 0.10 mm
# ---------------------------------------------------------------------------

def test_eccentric_cylinder_circular_runout():
    """
    Shaft centred at (0.05, 0) with nominal R=10. From datum axis at origin,
    measured radii vary. For a small offset d << R:
      max(R_meas) ≈ R + d,  min(R_meas) ≈ R - d
      circular runout ≈ 2*d = 2*0.05 = 0.10 mm
    """
    offset = 0.05
    pts = _circle_points(radius=10.0, z=0.0, n=360, offset_x=offset)
    spec = RunoutCheckSpec(
        feature_id="eccentric-shaft",
        runout_tolerance_mm=0.12,
        runout_type="circular",
        nominal_radius_mm=10.0,
    )
    report = check_runout(spec, pts)
    # 2*d = 0.10 mm (within float precision with 360 points)
    assert report.max_runout_mm == pytest.approx(2 * offset, abs=1e-4)
    assert report.compliant is True


def test_eccentric_cylinder_circular_runout_exact():
    """Exact geometry: 2 points per circle at theta=0 and theta=pi."""
    # With offset d: R_max = R+d, R_min = R-d → runout = 2d
    R, d = 10.0, 0.05
    pts = [
        InspectionPoint(theta_deg=0.0,   axial_z_mm=0.0, radius_measured_mm=R + d),
        InspectionPoint(theta_deg=180.0, axial_z_mm=0.0, radius_measured_mm=R - d),
    ]
    spec = RunoutCheckSpec(
        feature_id="shaft",
        runout_tolerance_mm=0.20,
        runout_type="circular",
        nominal_radius_mm=R,
    )
    report = check_runout(spec, pts)
    assert report.max_runout_mm == pytest.approx(2 * d, abs=1e-12)
    assert report.compliant is True
    assert report.fom == pytest.approx(2 * d / 0.20, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 3: tapered cylinder — total_runout > circular_runout
# ---------------------------------------------------------------------------

def test_tapered_cylinder_total_gt_circular():
    """
    Cylinder with linear taper: R increases from 10.0 to 10.2 along Z.
    At each z-section, points are perfect circles (circular runout = 0 per section).
    Total runout = max(R) - min(R) = 0.2 > 0.
    """
    radii_at_z = {0.0: 10.00, 5.0: 10.10, 10.0: 10.20}
    pts = []
    for z, r in radii_at_z.items():
        for i in range(12):
            pts.append(InspectionPoint(
                theta_deg=i * 30.0,
                axial_z_mm=z,
                radius_measured_mm=r,
            ))

    spec_circ = RunoutCheckSpec("taper", 0.05, "circular", 10.0)
    spec_tot  = RunoutCheckSpec("taper", 0.05, "total",    10.0)

    r_circ = check_runout(spec_circ, pts)
    r_tot  = check_runout(spec_tot,  pts)

    assert r_circ.max_runout_mm == 0.0, "No variation within any section"
    assert r_tot.max_runout_mm == pytest.approx(0.20, abs=1e-10)
    assert r_tot.max_runout_mm > r_circ.max_runout_mm


# ---------------------------------------------------------------------------
# Test 4: out-of-tolerance → compliant=False
# ---------------------------------------------------------------------------

def test_out_of_tolerance():
    """Runout 0.15 mm > tolerance 0.10 mm → compliant=False."""
    pts = [
        InspectionPoint(theta_deg=0.0,   axial_z_mm=0.0, radius_measured_mm=10.15),
        InspectionPoint(theta_deg=180.0, axial_z_mm=0.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("shaft", 0.10, "circular", 10.0)
    report = check_runout(spec, pts)
    assert report.max_runout_mm == pytest.approx(0.15, abs=1e-12)
    assert report.compliant is False
    assert report.fom == pytest.approx(0.15 / 0.10, abs=1e-12)
    assert report.fom > 1.0


def test_out_of_tolerance_total():
    """Total runout 0.25 > tolerance 0.20 → compliant=False."""
    pts = [
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=10.25),
        InspectionPoint(theta_deg=90.0, axial_z_mm=5.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("bore", 0.20, "total", 10.0)
    report = check_runout(spec, pts)
    assert report.max_runout_mm == pytest.approx(0.25, abs=1e-12)
    assert report.compliant is False


# ---------------------------------------------------------------------------
# Test 5: FoM correctness
# ---------------------------------------------------------------------------

def test_fom_correctness():
    """FoM = max_runout / tolerance."""
    pts = [
        InspectionPoint(theta_deg=0.0,   axial_z_mm=0.0, radius_measured_mm=10.08),
        InspectionPoint(theta_deg=180.0, axial_z_mm=0.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("shaft", 0.10, "circular", 10.0)
    report = check_runout(spec, pts)
    assert report.max_runout_mm == pytest.approx(0.08, abs=1e-12)
    assert report.fom == pytest.approx(0.08 / 0.10, abs=1e-12)
    assert report.fom == pytest.approx(0.8, abs=1e-12)
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 6: per_section_runout structure
# ---------------------------------------------------------------------------

def test_per_section_runout_structure_circular():
    """per_section_runout is a list of dicts with correct keys."""
    pts = [
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=10.05),
        InspectionPoint(theta_deg=180.0, axial_z_mm=0.0, radius_measured_mm=10.00),
        InspectionPoint(theta_deg=0.0, axial_z_mm=5.0, radius_measured_mm=10.03),
        InspectionPoint(theta_deg=180.0, axial_z_mm=5.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("shaft", 0.10, "circular", 10.0)
    report = check_runout(spec, pts)
    assert len(report.per_section_runout) == 2  # two z-sections
    for section in report.per_section_runout:
        assert "z_mm" in section
        assert "n_points" in section
        assert "r_max_mm" in section
        assert "r_min_mm" in section
        assert "runout_mm" in section
        assert section["n_points"] == 2


def test_per_section_runout_structure_total():
    """Total runout has single per_section entry with z_range_mm."""
    pts = [
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=10.05),
        InspectionPoint(theta_deg=180.0, axial_z_mm=10.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("shaft", 0.10, "total", 10.0)
    report = check_runout(spec, pts)
    assert len(report.per_section_runout) == 1
    s = report.per_section_runout[0]
    assert "z_range_mm" in s
    assert s["z_range_mm"] == [0.0, 10.0]


# ---------------------------------------------------------------------------
# Test 7: multi-section circular picks worst section
# ---------------------------------------------------------------------------

def test_circular_picks_worst_section():
    """
    Section z=0: runout=0.04; section z=5: runout=0.10.
    max_runout should be 0.10 (from z=5).
    """
    pts = [
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=10.04),
        InspectionPoint(theta_deg=180.0, axial_z_mm=0.0, radius_measured_mm=10.00),
        InspectionPoint(theta_deg=0.0, axial_z_mm=5.0, radius_measured_mm=10.10),
        InspectionPoint(theta_deg=180.0, axial_z_mm=5.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("shaft", 0.20, "circular", 10.0)
    report = check_runout(spec, pts)
    assert report.max_runout_mm == pytest.approx(0.10, abs=1e-12)
    assert report.compliant is True
    # Worst section is z=5
    sections_by_z = {s["z_mm"]: s["runout_mm"] for s in report.per_section_runout}
    assert sections_by_z[0.0] == pytest.approx(0.04, abs=1e-12)
    assert sections_by_z[5.0] == pytest.approx(0.10, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 8: degenerate — single point per section (runout=0 for that section)
# ---------------------------------------------------------------------------

def test_single_point_per_section_circular():
    """One point per section → max(R)-min(R)=0 per section → runout=0."""
    pts = [
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=10.0),
        InspectionPoint(theta_deg=0.0, axial_z_mm=5.0, radius_measured_mm=10.0),
    ]
    spec = RunoutCheckSpec("bore", 0.05, "circular", 10.0)
    report = check_runout(spec, pts)
    assert report.max_runout_mm == 0.0
    assert report.compliant is True


# ---------------------------------------------------------------------------
# Test 9: mean_radius_mm correctness
# ---------------------------------------------------------------------------

def test_mean_radius_mm():
    """Mean radius is the arithmetic mean of all measured radii."""
    pts = [
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=10.10),
        InspectionPoint(theta_deg=90.0, axial_z_mm=0.0, radius_measured_mm=9.90),
        InspectionPoint(theta_deg=180.0, axial_z_mm=0.0, radius_measured_mm=10.00),
        InspectionPoint(theta_deg=270.0, axial_z_mm=0.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("shaft", 0.30, "circular", 10.0)
    report = check_runout(spec, pts)
    expected_mean = (10.10 + 9.90 + 10.00 + 10.00) / 4
    assert report.mean_radius_mm == pytest.approx(expected_mean, abs=1e-10)


# ---------------------------------------------------------------------------
# Test 10: RunoutCheckSpec dataclass validation
# ---------------------------------------------------------------------------

def test_spec_validation_bad_type():
    with pytest.raises(ValueError, match="runout_type"):
        RunoutCheckSpec("f", 0.1, "radial", 10.0)


def test_spec_validation_zero_tolerance():
    with pytest.raises(ValueError, match="runout_tolerance_mm"):
        RunoutCheckSpec("f", 0.0, "circular", 10.0)


def test_spec_validation_negative_radius():
    with pytest.raises(ValueError, match="nominal_radius_mm"):
        RunoutCheckSpec("f", 0.1, "circular", -5.0)


# ---------------------------------------------------------------------------
# Test 11: InspectionPoint dataclass validation
# ---------------------------------------------------------------------------

def test_inspection_point_zero_radius():
    with pytest.raises(ValueError, match="radius_measured_mm"):
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=0.0)


def test_inspection_point_negative_radius():
    with pytest.raises(ValueError, match="radius_measured_mm"):
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=-1.0)


# ---------------------------------------------------------------------------
# Test 12: check_runout errors on bad inputs
# ---------------------------------------------------------------------------

def test_check_runout_empty_points():
    spec = RunoutCheckSpec("s", 0.1, "circular", 10.0)
    with pytest.raises(ValueError, match="empty"):
        check_runout(spec, [])


def test_check_runout_single_point():
    spec = RunoutCheckSpec("s", 0.1, "circular", 10.0)
    with pytest.raises(ValueError, match="at least 2"):
        check_runout(spec, [InspectionPoint(0.0, 0.0, 10.0)])


# ---------------------------------------------------------------------------
# Test 13: re-export from gdt __init__
# ---------------------------------------------------------------------------

def test_reexport_from_gdt_init():
    """gdt package exports the runout check symbols."""
    assert InspPt2 is InspectionPoint
    assert Spec2 is RunoutCheckSpec
    assert cr2 is check_runout


# ---------------------------------------------------------------------------
# Test 14: to_dict round-trip
# ---------------------------------------------------------------------------

def test_report_to_dict():
    """RunoutCheckReport.to_dict() contains expected keys."""
    pts = [
        InspectionPoint(theta_deg=0.0, axial_z_mm=0.0, radius_measured_mm=10.05),
        InspectionPoint(theta_deg=180.0, axial_z_mm=0.0, radius_measured_mm=10.00),
    ]
    spec = RunoutCheckSpec("shaft", 0.10, "circular", 10.0)
    report = check_runout(spec, pts)
    d = report.to_dict()
    assert "max_runout_mm" in d
    assert "mean_radius_mm" in d
    assert "fom" in d
    assert "compliant" in d
    assert "per_section_runout" in d
    assert "honest_caveat" in d
    assert d["compliant"] is True
    assert d["max_runout_mm"] == pytest.approx(0.05, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 15: LLM tool wrapper (gated — only runs if kerf_chat available)
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.gdt.runout_check import run_gdt_check_runout
    _TOOL_AVAILABLE = True
except ImportError:
    _TOOL_AVAILABLE = False


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_ok():
    """LLM tool returns a successful payload for a valid request."""
    ctx = _make_ctx()
    payload = json.dumps({
        "feature_id": "shaft-OD",
        "runout_tolerance_mm": 0.05,
        "runout_type": "circular",
        "nominal_radius_mm": 10.0,
        "inspection_points": [
            {"theta_deg": 0.0, "axial_z_mm": 0.0, "radius_measured_mm": 10.02},
            {"theta_deg": 90.0, "axial_z_mm": 0.0, "radius_measured_mm": 10.00},
            {"theta_deg": 180.0, "axial_z_mm": 0.0, "radius_measured_mm": 9.99},
            {"theta_deg": 270.0, "axial_z_mm": 0.0, "radius_measured_mm": 10.01},
        ],
    }).encode()
    raw = _run(run_gdt_check_runout(ctx, payload))
    d = _ok(raw)
    assert "max_runout_mm" in d
    assert d["max_runout_mm"] == pytest.approx(0.03, abs=1e-10)
    assert d["compliant"] is True


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_bad_runout_type():
    """LLM tool returns error for invalid runout_type."""
    ctx = _make_ctx()
    payload = json.dumps({
        "feature_id": "x",
        "runout_tolerance_mm": 0.05,
        "runout_type": "radial",  # invalid
        "nominal_radius_mm": 10.0,
        "inspection_points": [
            {"theta_deg": 0.0, "axial_z_mm": 0.0, "radius_measured_mm": 10.0},
            {"theta_deg": 90.0, "axial_z_mm": 0.0, "radius_measured_mm": 10.0},
        ],
    }).encode()
    raw = _run(run_gdt_check_runout(ctx, payload))
    _err(raw)


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_missing_field():
    """LLM tool returns error when required field is missing."""
    ctx = _make_ctx()
    payload = json.dumps({
        "feature_id": "x",
        "runout_tolerance_mm": 0.05,
        # missing runout_type
        "nominal_radius_mm": 10.0,
        "inspection_points": [
            {"theta_deg": 0.0, "axial_z_mm": 0.0, "radius_measured_mm": 10.0},
            {"theta_deg": 90.0, "axial_z_mm": 0.0, "radius_measured_mm": 10.0},
        ],
    }).encode()
    raw = _run(run_gdt_check_runout(ctx, payload))
    _err(raw)


@pytest.mark.skipif(not _TOOL_AVAILABLE, reason="kerf_chat not installed")
def test_llm_tool_total_runout():
    """LLM tool handles total runout correctly."""
    ctx = _make_ctx()
    payload = json.dumps({
        "feature_id": "taper",
        "runout_tolerance_mm": 0.30,
        "runout_type": "total",
        "nominal_radius_mm": 10.0,
        "inspection_points": [
            {"theta_deg": 0.0, "axial_z_mm": 0.0,  "radius_measured_mm": 10.00},
            {"theta_deg": 0.0, "axial_z_mm": 5.0,  "radius_measured_mm": 10.10},
            {"theta_deg": 0.0, "axial_z_mm": 10.0, "radius_measured_mm": 10.20},
        ],
    }).encode()
    raw = _run(run_gdt_check_runout(ctx, payload))
    d = _ok(raw)
    assert d["max_runout_mm"] == pytest.approx(0.20, abs=1e-10)
    assert d["compliant"] is True
    assert len(d["per_section_runout"]) == 1  # total: single combined entry
