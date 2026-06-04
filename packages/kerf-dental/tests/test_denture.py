"""
Tests for kerf_dental.denture_v2 — Wave 11B: 3shape parity

Tests:
- design_denture with Kennedy class I produces clasps on abutments
- DentureSpec validation
- Complete vs partial denture
- Kennedy classification

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
from kerf_dental.denture_v2 import (
    DentureSpec,
    DentureDesign,
    design_denture,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_arch_mesh(n: int = 20) -> tuple:
    angles = np.linspace(math.pi, 0, n)
    verts = np.column_stack([
        33 * np.cos(angles),
        25 * np.sin(angles),
        np.zeros(n),
    ])
    tris = np.array([[i, (i+1)%n, (i+2)%n] for i in range(n-2)], dtype=int)
    return verts, tris


def _make_kennedy_class_I_spec() -> DentureSpec:
    """Kennedy Class I: bilateral free-end saddles — both posterior areas missing."""
    # Mandibular missing 36, 37, 46, 47 (bilateral posteriors)
    teeth = [ToothNumber.from_fdi(f) for f in ["36", "37", "46", "47"]]
    # Abutments: 35 and 45
    abutments = [ToothNumber.from_fdi("35"), ToothNumber.from_fdi("45")]
    return DentureSpec(
        arch="mandibular",
        type="partial",
        teeth_to_replace=teeth,
        abutment_teeth=abutments,
        clasp_type="circumferential",
    )


# ===========================================================================
# DentureSpec
# ===========================================================================

class TestDentureSpec:
    def test_invalid_arch_raises(self):
        with pytest.raises(ValueError):
            DentureSpec(
                arch="upper",
                type="complete",
                teeth_to_replace=[ToothNumber.from_universal(1)],
            )

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            DentureSpec(
                arch="maxillary",
                type="fixed",
                teeth_to_replace=[ToothNumber.from_universal(1)],
            )

    def test_empty_teeth_raises(self):
        with pytest.raises(ValueError):
            DentureSpec(arch="maxillary", type="complete", teeth_to_replace=[])

    def test_invalid_clasp_type_raises(self):
        with pytest.raises(ValueError):
            DentureSpec(
                arch="mandibular",
                type="partial",
                teeth_to_replace=[ToothNumber.from_fdi("36")],
                clasp_type="spring_clasp",
            )


# ===========================================================================
# Kennedy classification
# ===========================================================================

class TestKennedyClassification:
    def test_class_I_bilateral_posterior(self):
        """Kennedy Class I: both sides, posterior missing."""
        teeth = [ToothNumber.from_fdi("36"), ToothNumber.from_fdi("46")]
        spec = DentureSpec(arch="mandibular", type="partial",
                           teeth_to_replace=teeth, abutment_teeth=[])
        assert spec.kennedy_class == "Class I"

    def test_class_II_unilateral_posterior(self):
        """Kennedy Class II: one side posterior missing."""
        teeth = [ToothNumber.from_fdi("36"), ToothNumber.from_fdi("37")]
        spec = DentureSpec(arch="mandibular", type="partial",
                           teeth_to_replace=teeth, abutment_teeth=[])
        assert spec.kennedy_class == "Class II"

    def test_complete_is_complete(self):
        teeth = [ToothNumber.from_universal(i) for i in range(17, 25)]
        spec = DentureSpec(arch="mandibular", type="complete",
                           teeth_to_replace=teeth)
        assert spec.kennedy_class == "complete"


# ===========================================================================
# design_denture
# ===========================================================================

class TestDesignDenture:
    """DoD: Kennedy class I denture produces clasps on abutments."""

    def test_returns_denture_design(self):
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert isinstance(result, DentureDesign)

    def test_base_mesh_non_empty(self):
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        verts, tris = result.base_mesh
        assert len(verts) > 0
        assert len(tris) > 0

    def test_class_I_produces_clasps(self):
        """DoD: Kennedy Class I RPD → clasps produced for abutments."""
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert len(result.clasps) >= 1, (
            f"Expected ≥1 clasp for Kennedy Class I RPD, got {len(result.clasps)}"
        )

    def test_class_I_clasp_meshes_non_empty(self):
        """Each clasp mesh must have vertices."""
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        for i, (cv, ct) in enumerate(result.clasps):
            assert len(cv) > 0, f"Clasp {i} has no vertices"

    def test_teeth_count_matches_spec(self):
        """Number of tooth meshes = number of teeth to replace."""
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert len(result.teeth) == len(spec.teeth_to_replace)

    def test_occlusal_contacts_non_empty(self):
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert len(result.occlusal_contacts) > 0

    def test_bite_height_positive(self):
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert result.bite_height_mm > 0.0

    def test_honest_caveat_present(self):
        spec = _make_kennedy_class_I_spec()
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert len(result.honest_caveat) > 0

    def test_complete_denture_no_clasps(self):
        """Complete denture has no clasps (no abutments)."""
        teeth = [ToothNumber.from_universal(i) for i in range(17, 25)]
        spec = DentureSpec(
            arch="mandibular",
            type="complete",
            teeth_to_replace=teeth,
        )
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert len(result.clasps) == 0

    def test_i_bar_clasp_type(self):
        """I-bar clasp type should still produce clasp meshes."""
        teeth = [ToothNumber.from_fdi("36"), ToothNumber.from_fdi("46")]
        abutments = [ToothNumber.from_fdi("35"), ToothNumber.from_fdi("45")]
        spec = DentureSpec(
            arch="mandibular",
            type="partial",
            teeth_to_replace=teeth,
            abutment_teeth=abutments,
            clasp_type="I_bar",
        )
        arch = _dummy_arch_mesh()
        result = design_denture(spec, arch, arch)
        assert len(result.clasps) >= 1
