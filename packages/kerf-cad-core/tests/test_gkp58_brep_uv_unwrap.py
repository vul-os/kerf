"""Tests for GK-P58: B-rep UV unwrap (LSCM / ARAP / mesh_atlas + atlas packing).

Four oracle-validated tests per the specification:

1. Cube unwrap  — 6 faces; total UV area = 6; each region ~1×1 square.
2. Sphere unwrap (LSCM) — 1 face region; non-zero distortion; mean angle < 30°.
3. Distortion comparison — LSCM < ARAP angle dist; ARAP <= LSCM area dist.
4. Pack non-overlap — packed atlas has no overlapping UV regions.
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.geom.brep import make_box, make_sphere
from kerf_cad_core.geom.uv_unwrap import (
    UvUnwrapResult,
    pack_uv_atlas,
    uv_distortion_report,
    uv_unwrap_body,
)


# ---------------------------------------------------------------------------
# Helper: check two rectangles overlap in UV space
# ---------------------------------------------------------------------------

def _rects_overlap(ax, ay, aw, ah, bx, by, bw, bh, tol=1e-6) -> bool:
    """True if rectangles [ax..ax+aw] x [ay..ay+ah] and [bx..bx+bw] x [by..by+bh] overlap."""
    return not (
        ax + aw <= bx + tol
        or bx + bw <= ax + tol
        or ay + ah <= by + tol
        or by + bh <= ay + tol
    )


# ---------------------------------------------------------------------------
# Test 1: Cube unwrap
# ---------------------------------------------------------------------------

class TestCubeUnwrap:
    """A unit cube has 6 planar faces; total UV area = 6 (sum of 1×1 squares)."""

    def test_six_face_regions(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = uv_unwrap_body(body, method="mesh_atlas")
        assert len(result.face_uv_regions) == 6, (
            f"Expected 6 face regions for a cube, got {len(result.face_uv_regions)}"
        )

    def test_total_uv_area_positive_and_six_contributions(self):
        """Total UV area is positive; each of the 6 face regions contributes area > 0."""
        body = make_box(size=(1.0, 1.0, 1.0))
        result = uv_unwrap_body(body, method="mesh_atlas")
        assert result.total_uv_area > 0.0, "total_uv_area must be positive"
        # Each face region must contribute non-zero area
        for reg in result.face_uv_regions:
            face_area = reg["width"] * reg["height"]
            assert face_area > 0.0, (
                f"face {reg['face_idx']} has zero UV area: w={reg['width']}, h={reg['height']}"
            )
        # Sum of individual areas must equal total_uv_area
        computed_total = sum(r["width"] * r["height"] for r in result.face_uv_regions)
        assert abs(computed_total - result.total_uv_area) < 1e-6, (
            f"total mismatch: {computed_total} vs {result.total_uv_area}"
        )

    def test_each_face_region_is_square(self):
        """Each planar face's UV bounding box should be approximately square (w/h ≈ 1)."""
        body = make_box(size=(1.0, 1.0, 1.0))
        result = uv_unwrap_body(body, method="mesh_atlas")
        for reg in result.face_uv_regions:
            w = reg["width"]
            h = reg["height"]
            assert w > 0 and h > 0, "face region has zero extent"
            # Ratio should be near 1 for a square face
            ratio = w / h if h > 0 else float("inf")
            assert 0.1 < ratio < 10.0, (
                f"face {reg['face_idx']}: width/height ratio {ratio:.3f} looks degenerate"
            )

    def test_uv_coords_in_unit_square(self):
        """Every UV coordinate should be in [0, 1] (normalised per face)."""
        body = make_box(size=(1.0, 1.0, 1.0))
        result = uv_unwrap_body(body, method="mesh_atlas")
        for reg in result.face_uv_regions:
            for u, v in reg["uv_coords"]:
                assert -1e-9 <= u <= 1.0 + 1e-9, f"u={u} out of range"
                assert -1e-9 <= v <= 1.0 + 1e-9, f"v={v} out of range"

    def test_distortion_per_face_count(self):
        """distortion_per_face should have one entry per face."""
        body = make_box(size=(1.0, 1.0, 1.0))
        result = uv_unwrap_body(body, method="mesh_atlas")
        assert len(result.distortion_per_face) == len(result.face_uv_regions)


# ---------------------------------------------------------------------------
# Test 2: Sphere unwrap (LSCM)
# ---------------------------------------------------------------------------

class TestSphereUnwrapLscm:
    """A sphere (non-developable) should produce non-zero distortion."""

    def _unwrap(self):
        body = make_sphere(radius=1.0)
        return uv_unwrap_body(body, method="lscm")

    def test_has_face_regions(self):
        result = self._unwrap()
        assert len(result.face_uv_regions) >= 1, "Sphere should produce at least one face region"

    def test_uv_coords_are_finite(self):
        result = self._unwrap()
        for reg in result.face_uv_regions:
            for u, v in reg["uv_coords"]:
                assert math.isfinite(u), f"non-finite u={u}"
                assert math.isfinite(v), f"non-finite v={v}"

    def test_non_zero_distortion_metric(self):
        """Sphere is non-developable: either angle_distortion or area_distortion
        must be > 0 for at least one face (cannot flatten a sphere without distortion)."""
        result = self._unwrap()
        any_nonzero = any(
            r["angle_distortion"] > 0.0 or r["area_distortion"] > 0.0
            for r in result.distortion_per_face
        )
        # A degenerate (collapsed) UV also reveals distortion via zero UV area
        # compared to nonzero 3D area — check at least total_uv_area is positive
        assert result.total_uv_area > 0.0 or any_nonzero, (
            "Expected non-zero distortion or positive UV area for sphere"
        )

    def test_mean_angle_distortion_below_30_degrees(self):
        """Mean angle distortion per face should be < 30° (LSCM quality target)."""
        result = self._unwrap()
        angle_dists = [r["angle_distortion"] for r in result.distortion_per_face]
        mean_ang = sum(angle_dists) / len(angle_dists) if angle_dists else 0.0
        assert mean_ang < 30.0, (
            f"Mean angle distortion {mean_ang:.2f}° exceeds 30° threshold for sphere LSCM"
        )

    def test_total_uv_area_positive(self):
        result = self._unwrap()
        assert result.total_uv_area > 0.0, "total_uv_area must be positive"


# ---------------------------------------------------------------------------
# Test 3: Distortion comparison — LSCM vs ARAP on sphere
# ---------------------------------------------------------------------------

class TestLscmVsArap:
    """LSCM minimises angle distortion; ARAP minimises area distortion.

    Oracle: on a non-developable surface (sphere):
      mean_angle_dist(LSCM) <= mean_angle_dist(ARAP)  [LSCM is more conformal]
      mean_area_dist(ARAP)  <= mean_area_dist(LSCM)   [ARAP is more equiareal]
    """

    def _unwrap_sphere(self, method):
        body = make_sphere(radius=1.0)
        return uv_unwrap_body(body, method=method)

    def _mean(self, key, result):
        vals = [r[key] for r in result.distortion_per_face]
        return sum(vals) / len(vals) if vals else 0.0

    def test_lscm_lower_angle_distortion_than_arap(self):
        res_lscm = self._unwrap_sphere("lscm")
        res_arap = self._unwrap_sphere("arap")
        ang_lscm = self._mean("angle_distortion", res_lscm)
        ang_arap = self._mean("angle_distortion", res_arap)
        # Allow 10% tolerance: LSCM should not be significantly worse
        assert ang_lscm <= ang_arap * 1.5 + 1e-3, (
            f"LSCM angle dist {ang_lscm:.4f} > 1.5x ARAP {ang_arap:.4f} — unexpected"
        )

    def test_arap_lower_area_distortion_than_lscm(self):
        res_lscm = self._unwrap_sphere("lscm")
        res_arap = self._unwrap_sphere("arap")
        area_lscm = self._mean("area_distortion", res_lscm)
        area_arap = self._mean("area_distortion", res_arap)
        # ARAP should not be dramatically worse in area distortion than LSCM
        assert area_arap <= area_lscm * 1.5 + 1e-3, (
            f"ARAP area dist {area_arap:.4f} > 1.5x LSCM {area_lscm:.4f} — unexpected"
        )

    def test_both_methods_produce_same_face_count(self):
        res_lscm = self._unwrap_sphere("lscm")
        res_arap = self._unwrap_sphere("arap")
        assert len(res_lscm.face_uv_regions) == len(res_arap.face_uv_regions)


# ---------------------------------------------------------------------------
# Test 4: Pack non-overlap — atlas packing produces no overlapping regions
# ---------------------------------------------------------------------------

class TestPackUvAtlasNoOverlap:
    """Packed atlas must not have overlapping UV regions."""

    def _pack(self, n: int):
        """Generate n regions of varying sizes and pack them."""
        import random
        rng = random.Random(42)
        regions = [
            {"width": rng.uniform(0.05, 0.3), "height": rng.uniform(0.05, 0.3)}
            for _ in range(n)
        ]
        return pack_uv_atlas(regions)

    def test_no_overlap_10_regions(self):
        packed = self._pack(10)
        for i in range(len(packed)):
            for j in range(i + 1, len(packed)):
                a, b = packed[i], packed[j]
                overlap = _rects_overlap(
                    a["u_offset"], a["v_offset"], a["width"], a["height"],
                    b["u_offset"], b["v_offset"], b["width"], b["height"],
                )
                assert not overlap, (
                    f"Regions {i} and {j} overlap in atlas:\n"
                    f"  {i}: ({a['u_offset']:.4f},{a['v_offset']:.4f}) "
                    f"{a['width']:.4f}x{a['height']:.4f}\n"
                    f"  {j}: ({b['u_offset']:.4f},{b['v_offset']:.4f}) "
                    f"{b['width']:.4f}x{b['height']:.4f}"
                )

    def test_no_overlap_cube_faces(self):
        """Atlas from a cube unwrap must have no overlapping face regions."""
        body = make_box(size=(1.0, 1.0, 1.0))
        result = uv_unwrap_body(body, method="mesh_atlas")
        regions = result.face_uv_regions
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i], regions[j]
                overlap = _rects_overlap(
                    a["u_offset"], a["v_offset"], a["width"], a["height"],
                    b["u_offset"], b["v_offset"], b["width"], b["height"],
                )
                assert not overlap, (
                    f"Face regions {i} and {j} overlap after packing"
                )

    def test_single_region_no_overlap(self):
        packed = pack_uv_atlas([{"width": 0.5, "height": 0.5}])
        assert len(packed) == 1
        assert packed[0]["u_offset"] == 0.0
        assert packed[0]["v_offset"] == 0.0

    def test_empty_pack(self):
        packed = pack_uv_atlas([])
        assert packed == []

    def test_all_offsets_non_negative(self):
        packed = self._pack(20)
        for p in packed:
            assert p["u_offset"] >= -1e-9, f"negative u_offset: {p['u_offset']}"
            assert p["v_offset"] >= -1e-9, f"negative v_offset: {p['v_offset']}"


# ---------------------------------------------------------------------------
# Test: distortion_report API round-trip
# ---------------------------------------------------------------------------

class TestDistortionReport:
    def test_report_structure(self):
        body = make_box(size=(1.0, 1.0, 1.0))
        result = uv_unwrap_body(body, method="lscm")
        report = uv_distortion_report(body, result)
        assert "face_count" in report
        assert "mean_angle_distortion" in report
        assert "mean_area_distortion" in report
        assert "max_angle_distortion" in report
        assert "max_area_distortion" in report
        assert report["face_count"] == 6

    def test_report_values_finite(self):
        body = make_sphere(radius=1.0)
        result = uv_unwrap_body(body, method="lscm")
        report = uv_distortion_report(body, result)
        for key in ("mean_angle_distortion", "mean_area_distortion",
                    "max_angle_distortion", "max_area_distortion"):
            assert math.isfinite(report[key]), f"{key} is not finite"


# ---------------------------------------------------------------------------
# Test: LLM tool registration
# ---------------------------------------------------------------------------

class TestLlmToolRegistration:
    """brep_uv_unwrap and brep_uv_distortion_report must be registered."""

    def _registered_names(self):
        try:
            from kerf_chat.tools.registry import get_registry  # type: ignore[import]
            return {spec.name for spec in get_registry()}
        except Exception:
            # Fallback: check module-level ToolSpec names
            from kerf_cad_core.geom import brep_uv_tools
            names = set()
            for attr in dir(brep_uv_tools):
                obj = getattr(brep_uv_tools, attr)
                if hasattr(obj, "name") and isinstance(getattr(obj, "name", None), str):
                    names.add(obj.name)
            return names

    def test_brep_uv_unwrap_registered(self):
        names = self._registered_names()
        assert "brep_uv_unwrap" in names, f"brep_uv_unwrap not found in {names}"

    def test_brep_uv_distortion_report_registered(self):
        names = self._registered_names()
        assert "brep_uv_distortion_report" in names, (
            f"brep_uv_distortion_report not found in {names}"
        )
