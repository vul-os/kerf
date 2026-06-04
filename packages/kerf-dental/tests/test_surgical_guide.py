"""
Tests for kerf_dental.surgical_guide — Wave 11B: 3shape parity

Tests:
- design_surgical_guide produces sleeves matching implant axis directions
- DrillSleeve geometry and dimensions
- SurgicalGuide mesh properties

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

from kerf_dental.crown_bridge import ToothNumber
from kerf_dental.implant_plan_v2 import (
    ImplantSpec, ImplantPosition, ImplantPlan, plan_implant,
)
from kerf_dental.surgical_guide import (
    DrillSleeve, SurgicalGuide, design_surgical_guide, _build_sleeve_mesh,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_arch_mesh(n: int = 30) -> tuple:
    """Build a simple flat arch point cloud."""
    angles = np.linspace(math.pi, 0, n)
    verts = np.column_stack([
        35 * np.cos(angles),
        25 * np.sin(angles),
        np.zeros(n),
    ])
    tris = np.array([[i, (i+1)%n, (i+2)%n] for i in range(n-2)], dtype=int)
    return verts, tris


def _make_plan(axis: np.ndarray = None) -> ImplantPlan:
    if axis is None:
        axis = np.array([0.0, 0.0, 1.0])
    tooth = ToothNumber.from_universal(19)
    implant = ImplantSpec(brand="Straumann BLT", diameter_mm=4.1, length_mm=10.0, platform="RC")
    pos = ImplantPosition(
        fixture_tip=np.array([0.0, 0.0, -10.0]),
        platform_position=np.array([0.0, 0.0, 0.0]),
        axis_direction=axis,
        angulation_deg=(0.0, 0.0),
    )
    return ImplantPlan(
        tooth_position=tooth,
        implant=implant,
        position=pos,
        bone_density_HU=1000.0,
        distance_to_nerve_mm=5.0,
        distance_to_sinus_mm=10.0,
        is_prosthetic_driven=True,
        insertion_torque_estimate_n_cm=40.0,
        primary_stability_score=8,
    )


# ===========================================================================
# DrillSleeve
# ===========================================================================

class TestDrillSleeve:
    def test_construction_valid(self):
        plan = _make_plan()
        sleeve = DrillSleeve(
            inner_diameter_mm=4.1,
            outer_diameter_mm=7.1,
            length_mm=5.0,
            position=plan.position,
        )
        assert sleeve.wall_thickness_mm == pytest.approx(1.5, abs=1e-6)

    def test_outer_must_be_greater_than_inner_raises(self):
        plan = _make_plan()
        with pytest.raises(ValueError):
            DrillSleeve(inner_diameter_mm=5.0, outer_diameter_mm=4.0,
                        length_mm=5.0, position=plan.position)

    def test_zero_length_raises(self):
        plan = _make_plan()
        with pytest.raises(ValueError):
            DrillSleeve(inner_diameter_mm=4.0, outer_diameter_mm=7.0,
                        length_mm=0.0, position=plan.position)

    def test_axis_direction_from_position(self):
        plan = _make_plan(np.array([0.0, 0.0, 1.0]))
        sleeve = DrillSleeve(
            inner_diameter_mm=4.1, outer_diameter_mm=7.1,
            length_mm=5.0, position=plan.position,
        )
        ax = sleeve.axis_direction
        assert abs(np.linalg.norm(ax) - 1.0) < 1e-9


# ===========================================================================
# design_surgical_guide
# ===========================================================================

class TestDesignSurgicalGuide:
    """DoD: sleeves match implant axis directions."""

    def test_returns_surgical_guide_instance(self):
        plan = _make_plan()
        arch = _dummy_arch_mesh()
        guide = design_surgical_guide([plan], arch)
        assert isinstance(guide, SurgicalGuide)

    def test_sleeve_count_matches_plan_count(self):
        """DoD: one sleeve per implant plan."""
        plans = [_make_plan() for _ in range(3)]
        arch = _dummy_arch_mesh()
        guide = design_surgical_guide(plans, arch)
        assert len(guide.sleeves) == 3

    def test_sleeve_axis_matches_implant_axis(self):
        """DoD: sleeve axis_direction matches implant position axis."""
        for axis_vec in [
            np.array([0.0, 0.0, 1.0]),
            np.array([0.1, 0.0, 1.0]),
            np.array([0.0, 0.2, 1.0]),
        ]:
            plan = _make_plan(axis_vec / np.linalg.norm(axis_vec))
            arch = _dummy_arch_mesh()
            guide = design_surgical_guide([plan], arch)
            sleeve_ax = guide.sleeves[0].axis_direction
            plan_ax = plan.position.axis_direction
            dot = abs(float(np.dot(sleeve_ax, plan_ax)))
            assert dot > 0.999, (
                f"Sleeve axis dot product with plan axis = {dot:.4f}, expected ≈ 1.0"
            )

    def test_sleeve_inner_diameter_matches_implant(self):
        """Sleeve inner diameter should match implant diameter."""
        plan = _make_plan()
        arch = _dummy_arch_mesh()
        guide = design_surgical_guide([plan], arch)
        assert guide.sleeves[0].inner_diameter_mm == pytest.approx(
            plan.implant.diameter_mm, abs=1e-6
        )

    def test_arch_support_mesh_non_empty(self):
        plan = _make_plan()
        arch = _dummy_arch_mesh()
        guide = design_surgical_guide([plan], arch)
        verts, tris = guide.arch_support_mesh
        assert len(verts) > 0
        assert len(tris) > 0

    def test_fenestrations_produced(self):
        plan = _make_plan()
        arch = _dummy_arch_mesh()
        guide = design_surgical_guide([plan], arch, n_fenestrations=3)
        assert len(guide.fenestrations) == 3

    def test_material_default_resin(self):
        plan = _make_plan()
        arch = _dummy_arch_mesh()
        guide = design_surgical_guide([plan], arch)
        assert guide.material == "biocompatible_resin"

    def test_honest_caveat_present(self):
        plan = _make_plan()
        arch = _dummy_arch_mesh()
        guide = design_surgical_guide([plan], arch)
        assert len(guide.honest_caveat) > 0


# ===========================================================================
# Sleeve mesh geometry
# ===========================================================================

class TestSleeveMesh:
    def test_sleeve_mesh_non_empty(self):
        plan = _make_plan()
        sleeve = DrillSleeve(
            inner_diameter_mm=4.1, outer_diameter_mm=7.1,
            length_mm=5.0, position=plan.position,
        )
        verts, tris = _build_sleeve_mesh(sleeve)
        assert len(verts) > 0
        assert len(tris) > 0

    def test_sleeve_mesh_valid_indices(self):
        plan = _make_plan()
        sleeve = DrillSleeve(
            inner_diameter_mm=4.1, outer_diameter_mm=7.1,
            length_mm=5.0, position=plan.position,
        )
        verts, tris = _build_sleeve_mesh(sleeve)
        n_verts = len(verts)
        for tri in tris:
            for idx in tri:
                assert 0 <= idx < n_verts
