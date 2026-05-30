"""GK-P: test_wall_thickness_analysis.py
=========================================
Four oracle tests for the high-level wall-thickness analysis API:

1. Uniform thick wall (hollow cube) — analyze_wall_thickness reports
   global_min ≈ 1mm ± 5% for a 10×10×10 box with 1mm walls.

2. material_thickness_guideline — 'abs' returns 1.5; 'concrete' returns None.

3. Thin wall flag — 0.5mm walls + material='abs' (min 1.5mm) → flag_thin_walls
   returns at least one warning.

4. No false positive — 2mm walls + material='abs' → flag_thin_walls returns
   0 warnings.

References
----------
Stroud-Nagy 2011 "Solid Modelling and CAD Systems" §17.2
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.brep import make_box
from kerf_cad_core.geom.solid_features import shell_body
from kerf_cad_core.geom.wall_thickness import (
    ThicknessReport,
    ThinWallWarning,
    analyze_wall_thickness,
    flag_thin_walls,
    material_thickness_guideline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hollow_box(side: float = 10.0, wall_t: float = 1.0):
    """Return a hollow cube Body with known uniform wall thickness."""
    box = make_box(origin=(0.0, 0.0, 0.0), size=(side, side, side))
    result = shell_body(box, wall_t)
    assert result["ok"], f"shell_body failed: {result.get('reason')}"
    return result["body"]


_REL_TOL = 0.05   # 5% relative tolerance for ray-sampling noise


# ---------------------------------------------------------------------------
# Test 1: Uniform thick wall — global_min ≈ 1mm for a 10mm cube, 1mm walls
# ---------------------------------------------------------------------------

class TestUniformThickWallCube:
    """analyze_wall_thickness reports global_min ≈ 1mm within 5% on a hollow
    10×10×10 cube with 1mm walls (the canonical oracle from §17.2)."""

    def setup_method(self):
        self.wall_t = 1.0
        self.body = _hollow_box(side=10.0, wall_t=self.wall_t)

    def test_returns_thickness_report(self):
        report = analyze_wall_thickness(self.body, n_samples=300, seed=42)
        assert isinstance(report, ThicknessReport)

    def test_global_min_approx_1mm(self):
        """global_min ≈ 1 mm ± 5% (main analytic oracle)."""
        report = analyze_wall_thickness(
            self.body, n_samples=1000, ray_count_per_sample=20, seed=42
        )
        g_min = report.global_min
        assert g_min > 0.0, "global_min must be positive"
        rel_err = abs(g_min - self.wall_t) / self.wall_t
        assert rel_err < _REL_TOL, (
            f"global_min={g_min:.4f} mm expected ≈ {self.wall_t} mm "
            f"(rel_err={rel_err:.3f} > {_REL_TOL})"
        )

    def test_per_face_min_keys_present(self):
        report = analyze_wall_thickness(self.body, n_samples=200, seed=7)
        assert len(report.per_face_min_thickness) > 0

    def test_sample_locations_non_empty(self):
        report = analyze_wall_thickness(self.body, n_samples=100, seed=1)
        assert len(report.sample_locations) > 0

    def test_recommend_min_populated_when_material_given(self):
        report = analyze_wall_thickness(
            self.body, n_samples=50, material_name="abs", seed=1
        )
        assert report.recommend_min_for_material == pytest.approx(1.5, rel=1e-6)

    def test_recommend_min_none_when_no_material(self):
        report = analyze_wall_thickness(self.body, n_samples=50, seed=1)
        assert report.recommend_min_for_material is None

    def test_global_max_gte_global_min(self):
        report = analyze_wall_thickness(self.body, n_samples=200, seed=2)
        assert report.global_max >= report.global_min


# ---------------------------------------------------------------------------
# Test 2: material_thickness_guideline
# ---------------------------------------------------------------------------

class TestMaterialThicknessGuideline:

    # Core table values
    @pytest.mark.parametrize("material,expected", [
        ("abs",          1.5),
        ("ABS",          1.5),
        ("pp",           0.8),
        ("PP",           0.8),
        ("polypropylene", 0.8),
        ("pe",           1.0),
        ("PC",           1.2),
        ("polycarbonate", 1.2),
        ("Nylon-6",      1.5),
        ("nylon6",       1.5),
        ("PVC",          2.0),
        ("pvc",          2.0),
        ("pom",          0.8),
        ("acetal",       0.8),
        ("ps",           1.0),
        ("lcp",          0.5),
    ])
    def test_known_mouldable_material(self, material, expected):
        result = material_thickness_guideline(material)
        assert result == pytest.approx(expected, rel=1e-6), (
            f"material_thickness_guideline({material!r}) = {result}, expected {expected}"
        )

    # Non-mouldable / unsuitable materials → None
    @pytest.mark.parametrize("material", [
        "concrete",
        "ceramic",
        "glass",
        "glass-flat",
        "steel",
        "aluminium",
        "aluminum",
        "copper",
        "titanium",
        "granite",
    ])
    def test_non_mouldable_returns_none(self, material):
        assert material_thickness_guideline(material) is None, (
            f"material_thickness_guideline({material!r}) should return None"
        )

    def test_unknown_material_returns_none(self):
        assert material_thickness_guideline("unobtainium") is None

    def test_case_insensitive(self):
        assert material_thickness_guideline("ABS") == material_thickness_guideline("abs")
        assert material_thickness_guideline("Polycarbonate") == material_thickness_guideline("polycarbonate")


# ---------------------------------------------------------------------------
# Test 3: Thin wall flag — 0.5mm walls, ABS (min 1.5mm) → warnings issued
# ---------------------------------------------------------------------------

class TestFlagThinWalls:

    def test_thin_wall_triggers_warning(self):
        """A 10×10×10 cube with 0.5mm walls is below ABS guideline (1.5mm)."""
        body = _hollow_box(side=10.0, wall_t=0.5)
        warnings = flag_thin_walls(body, material_name="abs", n_samples=500, seed=42)
        assert len(warnings) > 0, (
            "flag_thin_walls must return at least one ThinWallWarning for "
            "0.5mm walls with ABS guideline of 1.5mm"
        )

    def test_warning_has_correct_type(self):
        body = _hollow_box(side=10.0, wall_t=0.5)
        warnings = flag_thin_walls(body, material_name="abs", n_samples=300, seed=42)
        for w in warnings:
            assert isinstance(w, ThinWallWarning)

    def test_warning_fields_consistent(self):
        body = _hollow_box(side=10.0, wall_t=0.5)
        warnings = flag_thin_walls(body, material_name="abs", n_samples=300, seed=42)
        for w in warnings:
            assert w.required_min_mm == pytest.approx(1.5, rel=1e-6)
            assert w.measured_min_mm < w.required_min_mm
            assert w.deficit_mm == pytest.approx(
                w.required_min_mm - w.measured_min_mm, rel=1e-6
            )
            assert w.deficit_mm > 0

    def test_non_mouldable_material_returns_empty(self):
        """concrete is not mouldable → flag_thin_walls returns []."""
        body = _hollow_box(side=10.0, wall_t=0.5)
        warnings = flag_thin_walls(body, material_name="concrete", n_samples=100, seed=42)
        assert warnings == []

    def test_thin_pp_walls_flagged(self):
        """0.3mm walls < PP minimum 0.8mm."""
        body = _hollow_box(side=10.0, wall_t=0.3)
        warnings = flag_thin_walls(body, material_name="pp", n_samples=300, seed=42)
        assert len(warnings) > 0


# ---------------------------------------------------------------------------
# Test 4: No false positive — 2mm walls, ABS (min 1.5mm) → 0 warnings
# ---------------------------------------------------------------------------

class TestNoFalsePositive:

    def test_2mm_abs_no_warnings(self):
        """A 10×10×10 cube with 2mm walls should pass ABS (1.5mm) without warnings."""
        body = _hollow_box(side=10.0, wall_t=2.0)
        warnings = flag_thin_walls(body, material_name="abs", n_samples=800, seed=42)
        assert len(warnings) == 0, (
            f"flag_thin_walls returned {len(warnings)} warnings for 2mm walls "
            f"with ABS guideline of 1.5mm — expected 0\n"
            f"warnings: {warnings}"
        )

    def test_3mm_pvc_no_warnings(self):
        """3mm walls should clear PVC guideline (2.0mm)."""
        body = _hollow_box(side=10.0, wall_t=3.0)
        warnings = flag_thin_walls(body, material_name="pvc", n_samples=500, seed=42)
        assert len(warnings) == 0, (
            f"flag_thin_walls returned {len(warnings)} warnings for 3mm walls "
            f"with PVC guideline of 2.0mm — expected 0"
        )

    def test_1mm_pp_no_warnings(self):
        """1mm walls exceed PP minimum (0.8mm)."""
        body = _hollow_box(side=10.0, wall_t=1.0)
        warnings = flag_thin_walls(body, material_name="pp", n_samples=500, seed=42)
        assert len(warnings) == 0, (
            f"flag_thin_walls returned {len(warnings)} warnings for 1mm walls "
            f"with PP guideline of 0.8mm — expected 0"
        )

    def test_reproducible_no_false_positive(self):
        """Two runs with same seed must agree on zero warnings."""
        body = _hollow_box(side=10.0, wall_t=2.0)
        w1 = flag_thin_walls(body, material_name="abs", n_samples=300, seed=99)
        w2 = flag_thin_walls(body, material_name="abs", n_samples=300, seed=99)
        assert len(w1) == len(w2)


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------

class TestImports:

    def test_importable_from_wall_thickness_module(self):
        from kerf_cad_core.geom.wall_thickness import (  # noqa: F401
            ThicknessReport,
            ThinWallWarning,
            analyze_wall_thickness,
            flag_thin_walls,
            material_thickness_guideline,
        )

    def test_importable_from_geom_package(self):
        from kerf_cad_core.geom import (  # noqa: F401
            ThicknessReport,
            ThinWallWarning,
            analyze_wall_thickness,
            flag_thin_walls,
            material_thickness_guideline,
        )
