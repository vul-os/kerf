"""
Tests for kerf_dental.crown_bridge — Wave 11B: 3shape parity

Tests:
- ToothNumber construction from universal + FDI
- MarginLine validation
- CrownDesignSpec defaults
- design_crown for tooth 19 (mandibular left first molar) → wall ≥ 0.5 mm
- design_bridge with 3 abutments + 1 pontic → 4 crowns

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_dental.crown_bridge import (
    ToothNumber,
    MarginLine,
    CrownDesignSpec,
    CrownDesign,
    design_crown,
    design_bridge,
    _build_crown_mesh,
    _build_intaglio_mesh,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_margin(n: int = 16, md: float = 10.5, bl: float = 10.0) -> np.ndarray:
    """Build an elliptical margin polygon for a molar."""
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.column_stack([
        (md / 2) * np.cos(angles),
        (bl / 2) * np.sin(angles),
        np.zeros(n),
    ])
    return pts


def _make_spec(universal: int = 19) -> CrownDesignSpec:
    """Build a CrownDesignSpec for tooth 19 (mandibular L1 molar)."""
    tooth = ToothNumber.from_universal(universal)
    margin_pts = _make_margin(16, md=10.5, bl=10.0)
    margin = MarginLine(points=margin_pts, type="chamfer", width_mm=0.8)
    return CrownDesignSpec(
        tooth_number=tooth,
        margin=margin,
        occlusal_clearance_mm=1.5,
        interproximal_contacts=[
            {"side": "mesial", "point": (0.0, -5.5, 0.0)},
            {"side": "distal", "point": (0.0, 5.5, 0.0)},
        ],
    )


# ===========================================================================
# ToothNumber
# ===========================================================================

class TestToothNumber:
    def test_from_universal_tooth_19(self):
        """Tooth 19 (mandibular L first molar) = FDI 36."""
        t = ToothNumber.from_universal(19)
        assert t.fdi == "36"
        assert t.quadrant == "LL"
        assert t.arch == "mandibular"
        assert t.tooth_type == "molar"
        assert t.n_cusps == 4

    def test_from_universal_tooth_8(self):
        """Tooth 8 = FDI 11 (upper right central incisor)."""
        t = ToothNumber.from_universal(8)
        assert t.fdi == "11"
        assert t.arch == "maxillary"
        assert t.tooth_type == "incisor"

    def test_from_universal_tooth_6(self):
        """Tooth 6 = FDI 13 (canine, maxillary right)."""
        t = ToothNumber.from_universal(6)
        assert t.arch == "maxillary"
        assert t.tooth_type == "canine"
        assert t.n_cusps == 1

    def test_from_universal_tooth_12(self):
        """Tooth 12 = FDI 24 (upper left first premolar)."""
        t = ToothNumber.from_universal(12)
        assert t.tooth_type == "premolar"
        assert t.n_cusps == 2

    def test_from_fdi_roundtrip(self):
        """from_fdi should reproduce the same tooth."""
        for univ in [1, 8, 16, 17, 24, 25, 32]:
            t1 = ToothNumber.from_universal(univ)
            t2 = ToothNumber.from_fdi(t1.fdi)
            assert t1.universal == t2.universal

    def test_from_universal_out_of_range_raises(self):
        with pytest.raises(ValueError):
            ToothNumber.from_universal(0)
        with pytest.raises(ValueError):
            ToothNumber.from_universal(33)

    def test_from_fdi_invalid_raises(self):
        with pytest.raises(ValueError):
            ToothNumber.from_fdi("99")


# ===========================================================================
# MarginLine
# ===========================================================================

class TestMarginLine:
    def test_valid_margin(self):
        pts = _make_margin(12)
        m = MarginLine(points=pts, type="chamfer", width_mm=0.8)
        assert m.perimeter_mm > 0.0
        assert len(m.centroid) == 3

    def test_invalid_type_raises(self):
        pts = _make_margin(12)
        with pytest.raises(ValueError):
            MarginLine(points=pts, type="slope", width_mm=0.8)

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError):
            MarginLine(points=np.array([[0, 0, 0], [1, 0, 0]]), type="chamfer", width_mm=0.5)

    def test_zero_width_raises(self):
        pts = _make_margin(8)
        with pytest.raises(ValueError):
            MarginLine(points=pts, type="shoulder", width_mm=0.0)

    def test_all_types_valid(self):
        pts = _make_margin(8)
        for t in ("chamfer", "shoulder", "feather", "knife"):
            m = MarginLine(points=pts, type=t, width_mm=0.5)
            assert m.type == t


# ===========================================================================
# CrownDesignSpec
# ===========================================================================

class TestCrownDesignSpec:
    def test_default_cement_gap(self):
        spec = _make_spec(19)
        assert spec.cement_gap_mm == pytest.approx(0.04, abs=1e-9)

    def test_default_material_zirconia(self):
        spec = _make_spec(19)
        assert spec.material == "zirconia"

    def test_invalid_material_raises(self):
        tooth = ToothNumber.from_universal(19)
        margin = MarginLine(points=_make_margin(8), type="chamfer", width_mm=0.8)
        with pytest.raises(ValueError):
            CrownDesignSpec(
                tooth_number=tooth,
                margin=margin,
                occlusal_clearance_mm=1.5,
                interproximal_contacts=[],
                material="wood",
            )

    def test_negative_clearance_raises(self):
        tooth = ToothNumber.from_universal(19)
        margin = MarginLine(points=_make_margin(8), type="chamfer", width_mm=0.8)
        with pytest.raises(ValueError):
            CrownDesignSpec(
                tooth_number=tooth,
                margin=margin,
                occlusal_clearance_mm=-0.1,
                interproximal_contacts=[],
            )


# ===========================================================================
# design_crown — tooth 19 (molar, mandibular)
# ===========================================================================

class TestDesignCrown:
    """DoD: design_crown for tooth 19 → min wall ≥ 0.5 mm."""

    def test_returns_crown_design_instance(self):
        spec = _make_spec(19)
        result = design_crown(spec)
        assert isinstance(result, CrownDesign)

    def test_outer_mesh_non_empty(self):
        spec = _make_spec(19)
        result = design_crown(spec)
        verts, tris = result.outer_surface_mesh
        assert len(verts) > 0
        assert len(tris) > 0

    def test_intaglio_mesh_non_empty(self):
        spec = _make_spec(19)
        result = design_crown(spec)
        verts, tris = result.intaglio_surface_mesh
        assert len(verts) > 0
        assert len(tris) > 0

    def test_wall_thickness_min_at_least_0_5mm(self):
        """DoD: min wall thickness ≥ 0.5 mm for molar crown."""
        spec = _make_spec(19)
        result = design_crown(spec)
        assert result.wall_thickness_min_mm >= 0.5, (
            f"Expected wall ≥ 0.5 mm, got {result.wall_thickness_min_mm:.3f} mm"
        )

    def test_margin_fit_um_positive(self):
        spec = _make_spec(19)
        result = design_crown(spec)
        assert result.margin_fit_um > 0.0

    def test_margin_fit_includes_machining_tolerance(self):
        """margin_fit_um = cement_gap_um + machining_tolerance/2 (ISO 4049 model).

        Zirconia machining tol = 20 µm → margin_fit = 40 + 10 = 50 µm.
        """
        spec = _make_spec(19)
        result = design_crown(spec)
        # cement_gap 40 µm + zirconia machining tol/2 = 10 µm → 50 µm
        assert result.margin_fit_um == pytest.approx(50.0, abs=1.0)

    def test_occlusal_contacts_from_spec(self):
        spec = _make_spec(19)
        result = design_crown(spec)
        assert len(result.occlusal_contacts) == 2

    def test_honest_caveat_present(self):
        spec = _make_spec(19)
        result = design_crown(spec)
        assert len(result.honest_caveat) > 0
        assert "NOT" in result.honest_caveat.upper() or "EDUCATIONAL" in result.honest_caveat.upper()

    def test_wall_thickness_incisor(self):
        """Incisor crown wall ≥ 0.5 mm."""
        spec = _make_spec(8)
        result = design_crown(spec)
        assert result.wall_thickness_min_mm >= 0.5

    def test_lithium_disilicate_material(self):
        tooth = ToothNumber.from_universal(19)
        margin = MarginLine(points=_make_margin(16), type="chamfer", width_mm=0.8)
        spec = CrownDesignSpec(
            tooth_number=tooth,
            margin=margin,
            occlusal_clearance_mm=1.0,
            interproximal_contacts=[],
            material="lithium_disilicate",
        )
        result = design_crown(spec)
        assert result.spec.material == "lithium_disilicate"


# ===========================================================================
# design_bridge — 3 abutments + 1 pontic → 4 designs
# ===========================================================================

class TestDesignBridge:
    """DoD: design_bridge with 3 abutments + 1 pontic → 4 crowns."""

    def _make_bridge_specs(self):
        """Create 3 abutment specs for teeth 14, 15, 16 (maxillary right premolar+molar)."""
        specs = []
        for univ in [13, 14, 15]:  # 3 abutments
            tooth = ToothNumber.from_universal(univ)
            margin_pts = _make_margin(16)
            # Offset each margin laterally
            margin_pts[:, 0] += (univ - 14) * 8.0  # 8mm apart
            margin = MarginLine(points=margin_pts, type="chamfer", width_mm=0.8)
            specs.append(CrownDesignSpec(
                tooth_number=tooth,
                margin=margin,
                occlusal_clearance_mm=1.5,
                interproximal_contacts=[],
            ))
        return specs

    def test_bridge_3_abutments_1_pontic_returns_4_crowns(self):
        """DoD: 3 abutments + 1 pontic → 4 CrownDesign objects."""
        spans = self._make_bridge_specs()
        results = design_bridge(spans, pontic_count=1)
        assert len(results) == 4, f"Expected 4 crowns (3 abutments + 1 pontic), got {len(results)}"

    def test_all_results_are_crown_designs(self):
        spans = self._make_bridge_specs()
        results = design_bridge(spans, pontic_count=1)
        for r in results:
            assert isinstance(r, CrownDesign)

    def test_bridge_no_pontic_returns_abutments_only(self):
        spans = self._make_bridge_specs()
        results = design_bridge(spans, pontic_count=0)
        assert len(results) == len(spans)

    def test_bridge_all_walls_valid(self):
        spans = self._make_bridge_specs()
        results = design_bridge(spans, pontic_count=1)
        for r in results:
            assert r.wall_thickness_min_mm >= 0.5

    def test_bridge_single_span_no_error(self):
        """Single abutment with 0 pontics is valid."""
        spec = _make_spec(19)
        results = design_bridge([spec], pontic_count=0)
        assert len(results) == 1

    def test_bridge_negative_pontic_count_raises(self):
        spans = self._make_bridge_specs()
        with pytest.raises(ValueError):
            design_bridge(spans, pontic_count=-1)

    def test_bridge_empty_spans_raises(self):
        with pytest.raises(ValueError):
            design_bridge([], pontic_count=1)
