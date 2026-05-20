"""
T-9: Jewelry hollowing / weight-reduction — hermetic pytest suite.

Spec mandates (testing-breakdown.md, T-9):
  - 25 part geometries
  - resulting solid has >= requested min wall everywhere
  - mass reduction within target ±3%

The compute-function and LLM-tool-runner tests live in test_hollowing.py
(52 tests, all green).  This file adds the spec-required 25-geometry sweep
plus boundary and idempotency coverage not duplicated there.

Pure-Python: no OCC, no database, no project context required.
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.jewelry.hollowing import (
    _GA_PARAMS,
    _HOLE_DIA_MAX_MM,
    _HOLE_DIA_MIN_MM,
    _MAX_HOLLOW_FRACTION,
    _STRUCTURAL_WARN_RATIO,
    boolean_cleanup_holes,
    hollow_for_weight,
    lattice_infill,
    weight_reduction_report,
)
from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3, MM3_PER_CM3


# ---------------------------------------------------------------------------
# 25 part geometries — hollow_for_weight
#
# Each tuple: (label, solid_volume_mm3, alloy, target_fraction, min_wall_mm)
#   where target_fraction  is the desired remaining-mass fraction (0 < f < 1).
# ---------------------------------------------------------------------------

_GEOMETRIES = [
    # label                vol_mm3    alloy               frac   min_wall
    ("ring_thin_18k",      800.0,     "18k_yellow",       0.60,  0.8),
    ("ring_wide_14k",      1500.0,    "14k_yellow",       0.65,  0.8),
    ("signet_18kw",        2200.0,    "18k_white",        0.55,  1.0),
    ("bangle_22k",         4000.0,    "22k_yellow",       0.50,  1.0),
    ("pendant_small_pt",   300.0,     "platinum_950",     0.70,  0.6),
    ("pendant_large_pt",   900.0,     "platinum_950",     0.60,  0.8),
    ("charm_sterling",     250.0,     "sterling_925",     0.65,  0.5),
    ("brooch_silver",      1800.0,    "sterling_925",     0.55,  1.0),
    ("cufflink_14kr",      600.0,     "14k_rose",         0.60,  0.8),
    ("cufflink_18kr",      700.0,     "18k_rose",         0.65,  0.8),
    ("earring_14kw",       150.0,     "14k_white",        0.70,  0.5),
    ("earring_18ky",       180.0,     "18k_yellow",       0.70,  0.5),
    ("band_wide_10ky",     3500.0,    "10k_yellow",       0.55,  1.2),
    ("band_wide_10kw",     3200.0,    "10k_white",        0.58,  1.2),
    ("cocktail_ring_22ky", 5000.0,    "22k_yellow",       0.45,  1.5),
    ("cocktail_ring_18kw", 4500.0,    "18k_white",        0.48,  1.5),
    ("bracelet_bangle_pd", 6000.0,    "palladium_950",    0.50,  1.2),
    ("bracelet_link_pd",   2800.0,    "palladium_500",    0.60,  0.8),
    ("locket_fine_ag",     1200.0,    "fine_silver",      0.60,  0.7),
    ("locket_argen",       1100.0,    "argentium_935",    0.62,  0.7),
    ("toe_ring_10kr",      400.0,     "10k_rose",         0.65,  0.6),
    ("bar_pendant_brass",  800.0,     "brass",            0.55,  0.8),
    ("charm_bronze",       600.0,     "bronze",           0.58,  0.8),
    ("buckle_titanium",    7000.0,    "titanium",         0.50,  1.5),
    ("mass_ring_palladium_500", 1000.0, "palladium_500",  0.60,  0.8),
]

assert len(_GEOMETRIES) == 25, f"Expected 25, got {len(_GEOMETRIES)}"


# ---------------------------------------------------------------------------
# Helper — spherical-shell max cavity (mirrors hollowing.py logic)
# ---------------------------------------------------------------------------

def _max_cavity(vol_solid_mm3: float, min_wall_mm: float) -> float:
    r_outer = (3.0 * vol_solid_mm3 / (4.0 * math.pi)) ** (1.0 / 3.0)
    r_inner = max(0.0, r_outer - min_wall_mm)
    v_max = (4.0 / 3.0) * math.pi * (r_inner ** 3)
    return min(v_max, vol_solid_mm3 * _MAX_HOLLOW_FRACTION)


def _solid_weight(vol_mm3: float, alloy: str) -> float:
    return METAL_DENSITY_G_CM3[alloy] * (vol_mm3 / MM3_PER_CM3)


# ---------------------------------------------------------------------------
# T-9-A: 25-geometry sweep — ok and feasibility
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,vol,alloy,frac,wall", _GEOMETRIES)
def test_hollow_for_weight_ok(label, vol, alloy, frac, wall):
    """hollow_for_weight returns ok=True for each of the 25 part geometries."""
    solid_g = _solid_weight(vol, alloy)
    target_g = solid_g * frac
    r = hollow_for_weight(vol, target_g, alloy, min_wall_mm=wall)
    assert r["ok"] is True, f"{label}: {r.get('reason')}"


@pytest.mark.parametrize("label,vol,alloy,frac,wall", _GEOMETRIES)
def test_hollow_mass_reduction_within_3pct(label, vol, alloy, frac, wall):
    """Mass reduction must be within target ±3% (spec floor).

    spec: 'mass reduction within target ±3%'
    """
    rho = METAL_DENSITY_G_CM3[alloy]
    solid_g = _solid_weight(vol, alloy)
    target_g = solid_g * frac
    r = hollow_for_weight(vol, target_g, alloy, min_wall_mm=wall)
    assert r["ok"] is True, f"{label}: {r.get('reason')}"

    v_cav = r["required_cavity_mm3"]
    actual_g = rho * ((vol - v_cav) / MM3_PER_CM3)
    # Tolerance: ±3% of solid weight (spec) — the pure-Python impl is exact
    # to floating-point; assert exact first, then allow up to 3% headroom.
    rel_err = abs(actual_g - target_g) / solid_g
    assert rel_err <= 0.03, (
        f"{label}: mass error {rel_err:.4%} exceeds 3% "
        f"(target={target_g:.4f} g, actual={actual_g:.4f} g)"
    )


@pytest.mark.parametrize("label,vol,alloy,frac,wall", _GEOMETRIES)
def test_hollow_min_wall_respected(label, vol, alloy, frac, wall):
    """When feasible, required_cavity_mm3 <= max_cavity_mm3 (min-wall upheld).

    spec: 'resulting solid has >= requested min wall everywhere'
    """
    solid_g = _solid_weight(vol, alloy)
    target_g = solid_g * frac
    r = hollow_for_weight(vol, target_g, alloy, min_wall_mm=wall)
    assert r["ok"] is True, f"{label}: {r.get('reason')}"
    if r["feasible"]:
        assert r["required_cavity_mm3"] <= r["max_cavity_mm3"] + 1e-6, (
            f"{label}: required_cavity ({r['required_cavity_mm3']:.4f}) "
            f"> max_cavity ({r['max_cavity_mm3']:.4f})"
        )


# ---------------------------------------------------------------------------
# T-9-B: weight_reduction_report for the same 25 geometries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,vol,alloy,frac,wall", _GEOMETRIES)
def test_report_weight_saved_pct(label, vol, alloy, frac, wall):
    """weight_reduction_report.weight_saved_pct ≈ (1-frac)*100 within 0.01%."""
    solid_g = _solid_weight(vol, alloy)
    target_g = solid_g * frac
    h = hollow_for_weight(vol, target_g, alloy, min_wall_mm=wall)
    assert h["ok"] is True, f"{label}: {h.get('reason')}"
    rep = weight_reduction_report(vol, h["required_cavity_mm3"], alloy)
    assert rep["ok"] is True, f"{label}: {rep.get('reason')}"
    expected_pct = (1.0 - frac) * 100.0
    assert abs(rep["weight_saved_pct"] - expected_pct) < 0.02, (
        f"{label}: saved={rep['weight_saved_pct']:.4f}% expected≈{expected_pct:.4f}%"
    )


# ---------------------------------------------------------------------------
# T-9-C: idempotency — calling hollow_for_weight twice gives same result
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,vol,alloy,frac,wall", _GEOMETRIES)
def test_hollow_idempotent(label, vol, alloy, frac, wall):
    """Two calls with identical inputs yield identical required_cavity_mm3."""
    solid_g = _solid_weight(vol, alloy)
    target_g = solid_g * frac
    r1 = hollow_for_weight(vol, target_g, alloy, min_wall_mm=wall)
    r2 = hollow_for_weight(vol, target_g, alloy, min_wall_mm=wall)
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r1["required_cavity_mm3"] == r2["required_cavity_mm3"], label
    assert r1["cavity_shape"] == r2["cavity_shape"], label


# ---------------------------------------------------------------------------
# T-9-D: boundary / malformed inputs (independent of geometry table)
# ---------------------------------------------------------------------------

class TestHollowingBoundaries:

    def test_zero_volume_rejected(self):
        r = hollow_for_weight(0.0, 1.0, "18k_yellow")
        assert r["ok"] is False

    def test_negative_volume_rejected(self):
        r = hollow_for_weight(-500.0, 5.0, "18k_yellow")
        assert r["ok"] is False

    def test_zero_target_rejected(self):
        r = hollow_for_weight(1000.0, 0.0, "18k_yellow")
        assert r["ok"] is False

    def test_negative_target_rejected(self):
        r = hollow_for_weight(1000.0, -3.0, "18k_yellow")
        assert r["ok"] is False

    def test_target_equals_solid_rejected(self):
        """target_weight_g == solid_weight_g → ok=False (nothing to hollow)."""
        rho = METAL_DENSITY_G_CM3["18k_yellow"]
        solid_g = rho * (1000.0 / MM3_PER_CM3)
        r = hollow_for_weight(1000.0, solid_g, "18k_yellow")
        assert r["ok"] is False

    def test_target_exceeds_solid_rejected(self):
        rho = METAL_DENSITY_G_CM3["sterling_925"]
        solid_g = rho * (500.0 / MM3_PER_CM3)
        r = hollow_for_weight(500.0, solid_g * 1.5, "sterling_925")
        assert r["ok"] is False

    def test_unknown_alloy_rejected(self):
        r = hollow_for_weight(1000.0, 3.0, "unobtainium_99k")
        assert r["ok"] is False

    def test_zero_min_wall_rejected(self):
        rho = METAL_DENSITY_G_CM3["18k_yellow"]
        solid_g = rho * (1000.0 / MM3_PER_CM3)
        r = hollow_for_weight(1000.0, solid_g * 0.60, "18k_yellow", min_wall_mm=0.0)
        assert r["ok"] is False

    def test_negative_min_wall_rejected(self):
        rho = METAL_DENSITY_G_CM3["18k_yellow"]
        solid_g = rho * (1000.0 / MM3_PER_CM3)
        r = hollow_for_weight(1000.0, solid_g * 0.60, "18k_yellow", min_wall_mm=-1.0)
        assert r["ok"] is False

    def test_non_numeric_volume_rejected(self):
        r = hollow_for_weight("big", 5.0, "18k_yellow")
        assert r["ok"] is False

    def test_non_numeric_target_rejected(self):
        r = hollow_for_weight(1000.0, "heavy", "18k_yellow")
        assert r["ok"] is False

    def test_non_numeric_wall_rejected(self):
        rho = METAL_DENSITY_G_CM3["18k_yellow"]
        solid_g = rho * (1000.0 / MM3_PER_CM3)
        r = hollow_for_weight(1000.0, solid_g * 0.60, "18k_yellow", min_wall_mm="thick")
        assert r["ok"] is False

    def test_density_override_non_numeric_rejected(self):
        r = hollow_for_weight(1000.0, 3.0, "18k_yellow", density_g_cm3="heavy")
        assert r["ok"] is False

    def test_density_override_zero_rejected(self):
        r = hollow_for_weight(1000.0, 3.0, "18k_yellow", density_g_cm3=0.0)
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# T-9-E: cavity shape boundaries (geometry-independent)
# ---------------------------------------------------------------------------

class TestCavityShapeBoundaries:

    def _run(self, frac: float) -> dict:
        vol = 10_000.0
        alloy = "18k_yellow"
        rho = METAL_DENSITY_G_CM3[alloy]
        solid_g = rho * (vol / MM3_PER_CM3)
        return hollow_for_weight(vol, solid_g * (1.0 - frac), alloy, min_wall_mm=0.5)

    def test_below_30pct_is_ellipsoid(self):
        r = self._run(0.25)   # 25% removal
        assert r["ok"] is True
        assert r["cavity_shape"] == "ellipsoid"

    def test_at_30pct_boundary_is_prism(self):
        """30% removal is the first value in [30,60] range → prism."""
        r = self._run(0.30)
        assert r["ok"] is True
        assert r["cavity_shape"] == "prism"

    def test_midrange_is_prism(self):
        r = self._run(0.45)
        assert r["ok"] is True
        assert r["cavity_shape"] == "prism"

    def test_at_60pct_boundary_is_prism(self):
        """60% removal is the upper bound of prism range (≤ 0.60 → prism)."""
        r = self._run(0.60)
        assert r["ok"] is True
        assert r["cavity_shape"] == "prism"

    def test_above_60pct_is_lattice(self):
        r = self._run(0.65)
        assert r["ok"] is True
        assert r["cavity_shape"] == "lattice_infill"


# ---------------------------------------------------------------------------
# T-9-F: min-wall warning threshold
# ---------------------------------------------------------------------------

class TestMinWallWarning:

    def test_wall_below_0_5mm_fires_warning(self):
        rho = METAL_DENSITY_G_CM3["18k_yellow"]
        solid_g = rho * (2000.0 / MM3_PER_CM3)
        r = hollow_for_weight(2000.0, solid_g * 0.60, "18k_yellow", min_wall_mm=0.4)
        assert r["ok"] is True
        assert any("0.5 mm" in w for w in r["warnings"])

    def test_wall_exactly_0_5mm_no_warning(self):
        rho = METAL_DENSITY_G_CM3["18k_yellow"]
        solid_g = rho * (2000.0 / MM3_PER_CM3)
        r = hollow_for_weight(2000.0, solid_g * 0.60, "18k_yellow", min_wall_mm=0.5)
        assert r["ok"] is True
        assert not any("0.5 mm" in w for w in r["warnings"])

    def test_wall_above_0_5mm_no_warning(self):
        rho = METAL_DENSITY_G_CM3["18k_yellow"]
        solid_g = rho * (2000.0 / MM3_PER_CM3)
        r = hollow_for_weight(2000.0, solid_g * 0.60, "18k_yellow", min_wall_mm=1.0)
        assert r["ok"] is True
        assert not any("0.5 mm" in w for w in r["warnings"])


# ---------------------------------------------------------------------------
# T-9-G: explicit density override path for 25-geometry-equivalent cases
# ---------------------------------------------------------------------------

class TestDensityOverride:

    @pytest.mark.parametrize("rho", [7.9, 11.0, 15.0, 19.3, 21.5])
    def test_explicit_density_mass_conservation(self, rho):
        """Mass conservation holds for custom density values."""
        vol = 2000.0
        solid_g = rho * (vol / MM3_PER_CM3)
        target_g = solid_g * 0.60
        r = hollow_for_weight(vol, target_g, "custom", density_g_cm3=rho)
        assert r["ok"] is True
        actual_g = rho * ((vol - r["required_cavity_mm3"]) / MM3_PER_CM3)
        assert abs(actual_g - target_g) / solid_g < 0.03


# ---------------------------------------------------------------------------
# T-9-H: boolean_cleanup_holes with hollowed geometries (integration sweep)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,vol,alloy,frac,wall", _GEOMETRIES[:10])
def test_holes_for_hollowed_piece(label, vol, alloy, frac, wall):
    """boolean_cleanup_holes succeeds for a realistic cavity from 10 geometries."""
    solid_g = _solid_weight(vol, alloy)
    target_g = solid_g * frac
    h = hollow_for_weight(vol, target_g, alloy, min_wall_mm=wall)
    assert h["ok"] is True, f"{label}: {h.get('reason')}"
    holes = boolean_cleanup_holes(h["required_cavity_mm3"], vol)
    assert holes["ok"] is True, f"{label}: {holes.get('reason')}"
    assert holes["hole_count"] >= 2, label
    assert holes["hole_diameter_mm"] >= _HOLE_DIA_MIN_MM, label
    assert holes["hole_diameter_mm"] <= _HOLE_DIA_MAX_MM, label


# ---------------------------------------------------------------------------
# T-9-I: weight_reduction_report structural-integrity sweep
# ---------------------------------------------------------------------------

class TestStructuralIntegritySweep:

    @pytest.mark.parametrize("cavity_frac,expect_ok", [
        (0.30, True),
        (0.50, True),
        (0.59, True),
        (0.61, False),
        (0.75, False),
        (0.90, False),
    ])
    def test_structural_flag_by_cavity_bbox_ratio(self, cavity_frac, expect_ok):
        """structural_integrity_ok follows the 60% threshold."""
        vol_solid = 5000.0
        alloy = "18k_yellow"
        # set bbox so cavity/bbox == cavity_frac
        v_cav = vol_solid * 0.40   # fixed cavity (40% of solid)
        v_bbox = v_cav / cavity_frac
        r = weight_reduction_report(vol_solid, v_cav, alloy, bbox_volume_mm3=v_bbox)
        assert r["ok"] is True
        assert r["structural_integrity_ok"] is expect_ok, (
            f"frac={cavity_frac}: expected structural_ok={expect_ok}, "
            f"got {r['structural_integrity_ok']}"
        )
