"""
Tests for T-114: Toposolid IFC export and cut/fill earthwork report.

DoD: a TIN → toposolid + cut/fill volume report on a fixture site; pytest.
"""
from __future__ import annotations

import math
import pytest

from kerf_bim.site import Toposolid, BuildingPad, cut_fill_volume
from kerf_bim.site_ifc import (
    toposolid_to_ifc_dict,
    building_pad_to_ifc_dict,
    cut_fill_report,
    site_model_dict,
)


# ---------------------------------------------------------------------------
# Fixture terrain
# ---------------------------------------------------------------------------

def _flat_site(z: float = 10.0) -> Toposolid:
    boundary = [(0, 0), (100, 0), (100, 100), (0, 100)]
    pts = [(0, 0, z), (100, 0, z), (100, 100, z), (0, 100, z)]
    return Toposolid(boundary=boundary, points=pts, material="soil", thickness=1.0)


def _sloped_site() -> Toposolid:
    """Linear-slope site: z = 0.1*x over 100×100 m."""
    boundary = [(0, 0), (100, 0), (100, 100), (0, 100)]
    pts = [(0, 0, 0.0), (100, 0, 10.0), (100, 100, 10.0), (0, 100, 0.0)]
    return Toposolid(boundary=boundary, points=pts, material="soil", thickness=1.0)


# =============================================================================
# T-114.1: Toposolid IFC dict
# =============================================================================

class TestToposolidIFCDict:
    def test_required_keys(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        for key in ("boundary", "thickness", "level", "name", "function",
                    "tin", "plan_area_m2", "surface_area_m2"):
            assert key in d, f"Missing key '{key}'"

    def test_function_is_baseslab(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        assert d["function"] == "BASESLAB"

    def test_boundary_at_least_4_points(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        assert len(d["boundary"]) >= 4

    def test_boundary_in_mm(self):
        """Bounding box coordinates should be in mm (× 1000 from metres)."""
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        # Flat site 0-100 m → 0-100,000 mm bounding box
        xs = [p[0] for p in d["boundary"]]
        assert max(xs) > 100.0  # must be mm scale

    def test_tin_structure(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        tin = d["tin"]
        assert "vertices" in tin
        assert "simplices" in tin
        assert "material" in tin
        assert tin["material"] == "soil"

    def test_tin_vertices_shape(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        verts = d["tin"]["vertices"]
        assert len(verts) >= 3
        assert all(len(v) == 3 for v in verts)

    def test_plan_area_positive(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        assert d["plan_area_m2"] > 0

    def test_surface_area_positive(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts)
        assert d["surface_area_m2"] > 0

    def test_named_toposolid(self):
        ts = _flat_site()
        d = toposolid_to_ifc_dict(ts, name="Existing Grade", level="Site")
        assert d["name"] == "Existing Grade"
        assert d["level"] == "Site"

    def test_thickness_mm(self):
        """Thickness must be in mm (1.0 m thickness → 1000.0 mm)."""
        ts = _flat_site(z=5.0)
        d = toposolid_to_ifc_dict(ts)
        assert d["thickness"] == pytest.approx(1000.0)


# =============================================================================
# T-114.2: BuildingPad IFC dict
# =============================================================================

class TestBuildingPadIFCDict:
    def _pad(self) -> BuildingPad:
        ts = _flat_site()
        footprint = [(10, 10), (30, 10), (30, 30), (10, 30)]
        return BuildingPad(toposolid=ts, footprint_curve=footprint, level=5.0)

    def test_required_keys(self):
        d = building_pad_to_ifc_dict(self._pad())
        for key in ("boundary", "thickness", "level", "name", "function",
                    "level_m", "side_slope", "pad_area_m2"):
            assert key in d, f"Missing key '{key}'"

    def test_function_is_baseslab(self):
        d = building_pad_to_ifc_dict(self._pad())
        assert d["function"] == "BASESLAB"

    def test_boundary_in_mm(self):
        d = building_pad_to_ifc_dict(self._pad())
        # Footprint at (10,10)…(30,30) metres → 10000…30000 mm
        xs = [p[0] for p in d["boundary"]]
        assert min(xs) == pytest.approx(10_000.0)
        assert max(xs) == pytest.approx(30_000.0)

    def test_pad_area_positive(self):
        d = building_pad_to_ifc_dict(self._pad())
        assert d["pad_area_m2"] > 0


# =============================================================================
# T-114.3: Cut/fill report (earthwork)
# =============================================================================

class TestCutFillReport:
    def test_report_keys(self):
        existing = _flat_site(z=5.0)
        proposed = _flat_site(z=5.0)
        r = cut_fill_report(existing, proposed, grid_spacing=5.0)
        for key in ("cut_m3", "fill_m3", "net_m3", "grid_spacing_m", "provenance"):
            assert key in r

    def test_identical_surfaces_zero_volumes(self):
        ts = _flat_site()
        r = cut_fill_report(ts, ts, grid_spacing=5.0)
        assert r["cut_m3"] < 1e-6
        assert r["fill_m3"] < 1e-6

    def test_net_is_fill_minus_cut(self):
        existing = _sloped_site()
        proposed = _flat_site(z=5.0)
        r = cut_fill_report(existing, proposed, grid_spacing=5.0)
        assert abs(r["net_m3"] - (r["fill_m3"] - r["cut_m3"])) < 1e-6

    def test_cut_positive_when_proposed_lower(self):
        existing = _flat_site(z=10.0)
        proposed = _flat_site(z=5.0)
        r = cut_fill_report(existing, proposed, grid_spacing=5.0)
        assert r["cut_m3"] > 0
        assert r["fill_m3"] < 1e-3

    def test_fill_positive_when_proposed_higher(self):
        existing = _flat_site(z=5.0)
        proposed = _flat_site(z=10.0)
        r = cut_fill_report(existing, proposed, grid_spacing=5.0)
        assert r["fill_m3"] > 0
        assert r["cut_m3"] < 1e-3

    def test_grid_spacing_stored(self):
        ts = _flat_site()
        r = cut_fill_report(ts, ts, grid_spacing=2.0)
        assert r["grid_spacing_m"] == 2.0

    def test_approximate_cut_volume(self):
        """Flat site at z=10 → flat proposed at z=5; 5 m depth over 100×100 m.
        Expected cut ≈ 5 * 10000 = 50,000 m³ (inner overlap)."""
        existing = _flat_site(z=10.0)
        proposed = _flat_site(z=5.0)
        r = cut_fill_report(existing, proposed, grid_spacing=2.0)
        # Allow 10% tolerance for grid discretisation
        expected = 5.0 * 100.0 * 100.0
        assert abs(r["cut_m3"] - expected) < expected * 0.10


# =============================================================================
# T-114.4: Site model dict
# =============================================================================

class TestSiteModelDict:
    def test_empty_site(self):
        d = site_model_dict(site_name="Test Site")
        assert d["site"]["name"] == "Test Site"
        assert d["toposolids"] == []
        assert d["building_pads"] == []
        assert d["slabs"] == []

    def test_with_toposolid(self):
        ts = _flat_site()
        d = site_model_dict(toposolids=[ts])
        assert len(d["toposolids"]) == 1
        assert len(d["slabs"]) == 1

    def test_with_pad(self):
        ts = _flat_site()
        pad = BuildingPad(
            toposolid=ts,
            footprint_curve=[(10, 10), (30, 10), (30, 30), (10, 30)],
            level=5.0,
        )
        d = site_model_dict(building_pads=[pad])
        assert len(d["building_pads"]) == 1
        assert len(d["slabs"]) == 1

    def test_slabs_merged(self):
        ts = _flat_site()
        pad = BuildingPad(
            toposolid=ts,
            footprint_curve=[(10, 10), (30, 10), (30, 30), (10, 30)],
            level=5.0,
        )
        d = site_model_dict(toposolids=[ts, ts], building_pads=[pad])
        assert len(d["slabs"]) == 3  # 2 toposolids + 1 pad

    def test_ifc_compatible_slab_list(self):
        """Slabs list must have boundary, thickness, and level for IFC writer."""
        ts = _flat_site()
        d = site_model_dict(toposolids=[ts])
        slab = d["slabs"][0]
        assert "boundary" in slab
        assert "thickness" in slab
        assert "level" in slab
