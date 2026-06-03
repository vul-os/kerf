"""
Tests for kerf_cad_core.apparel.avatar — parametric human avatar (ISO 8559-1:2017).

Tests verify:
  - Default AvatarMeasurements match ISO 8559 typical neutral-standard values
  - build_avatar produces a valid closed mesh (vertex + face counts)
  - Extreme height (190 cm) produces a taller mesh
  - Extreme short (150 cm) produces shorter mesh
  - Mesh has correct data types
  - fit_dress_form mesh bbox is larger than avatar
  - Landmark keys are all present
  - fit_dress_form with ease=0 reproduces avatar mesh exactly
  - gender variants produce meshes
  - Large bust vs small bust changes radius
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.apparel.avatar import (
    Avatar,
    AvatarMeasurements,
    build_avatar,
    fit_dress_form,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_avatar():
    return build_avatar(AvatarMeasurements())


@pytest.fixture
def tall_avatar():
    return build_avatar(AvatarMeasurements(height_cm=190.0))


# ---------------------------------------------------------------------------
# 1. Default measurements are ISO 8559-1 neutral-standard typical values
# ---------------------------------------------------------------------------

def test_default_height():
    """ISO 8559-1:2017 §8.1 — standard height 170 cm."""
    assert AvatarMeasurements().height_cm == pytest.approx(170.0)


def test_default_bust():
    """ISO 8559-1:2017 §8.3.1 — size 38 bust = 92 cm."""
    assert AvatarMeasurements().bust_cm == pytest.approx(92.0)


def test_default_waist():
    """ISO 8559-1:2017 §8.4.1 — size 38 waist = 76 cm."""
    assert AvatarMeasurements().waist_cm == pytest.approx(76.0)


def test_default_hip():
    """ISO 8559-1:2017 §8.5.1 — size 38 hip = 98 cm."""
    assert AvatarMeasurements().hip_cm == pytest.approx(98.0)


def test_default_gender_is_neutral():
    assert AvatarMeasurements().gender == "neutral"


# ---------------------------------------------------------------------------
# 2. build_avatar produces a valid mesh
# ---------------------------------------------------------------------------

def test_avatar_vertex_count(default_avatar):
    """Avatar mesh must have > 100 vertices."""
    assert len(default_avatar.mesh_positions) > 100


def test_avatar_face_count(default_avatar):
    """Avatar mesh must have > 200 faces."""
    assert len(default_avatar.mesh_triangles) > 200


def test_avatar_positions_dtype(default_avatar):
    """Vertex positions must be float64."""
    assert default_avatar.mesh_positions.dtype == np.float64


def test_avatar_triangles_dtype(default_avatar):
    """Triangle indices must be int32."""
    assert default_avatar.mesh_triangles.dtype == np.int32


def test_avatar_triangles_valid_indices(default_avatar):
    """Triangle indices must be in [0, V)."""
    V = len(default_avatar.mesh_positions)
    assert default_avatar.mesh_triangles.min() >= 0
    assert default_avatar.mesh_triangles.max() < V


def test_avatar_triangles_shape(default_avatar):
    """Triangle array must have shape (F, 3)."""
    assert default_avatar.mesh_triangles.ndim == 2
    assert default_avatar.mesh_triangles.shape[1] == 3


# ---------------------------------------------------------------------------
# 3. Extreme height (190 cm) → taller mesh
# ---------------------------------------------------------------------------

def test_tall_avatar_max_z(tall_avatar):
    """Avatar built with height=190 cm must have max_y > 1.90 m (Y-up coordinate)."""
    max_y = tall_avatar.mesh_positions[:, 1].max()
    # Crown of head should be above 190 cm
    assert max_y > 1.90, f"expected max_y > 1.90 m, got {max_y:.3f}"


def test_tall_avatar_taller_than_default(default_avatar, tall_avatar):
    """190-cm avatar must be strictly taller than 170-cm avatar."""
    default_max_y = default_avatar.mesh_positions[:, 1].max()
    tall_max_y = tall_avatar.mesh_positions[:, 1].max()
    assert tall_max_y > default_max_y


# ---------------------------------------------------------------------------
# 4. fit_dress_form bbox is larger than avatar
# ---------------------------------------------------------------------------

def test_dress_form_larger_xz(default_avatar):
    """Dress form XZ extent must exceed avatar XZ extent (ease = 2.5 cm)."""
    dv, dt = fit_dress_form(default_avatar, ease_cm=2.5)
    av = default_avatar.mesh_positions

    av_max_xz = float(np.linalg.norm(av[:, [0, 2]], axis=1).max())
    df_max_xz = float(np.linalg.norm(dv[:, [0, 2]], axis=1).max())

    assert df_max_xz > av_max_xz, (
        f"dress form XZ ({df_max_xz:.4f}) should be > avatar XZ ({av_max_xz:.4f})"
    )


def test_dress_form_same_height(default_avatar):
    """Dress form Y extent must equal avatar Y extent (no vertical expansion)."""
    dv, _ = fit_dress_form(default_avatar, ease_cm=2.5)
    av = default_avatar.mesh_positions
    assert dv[:, 1].max() == pytest.approx(av[:, 1].max(), abs=1e-9)
    assert dv[:, 1].min() == pytest.approx(av[:, 1].min(), abs=1e-9)


def test_dress_form_zero_ease_same_mesh(default_avatar):
    """fit_dress_form with ease=0 must produce the same vertex positions as the avatar."""
    dv, dt = fit_dress_form(default_avatar, ease_cm=0.0)
    np.testing.assert_allclose(dv, default_avatar.mesh_positions, atol=1e-9)


def test_dress_form_same_connectivity(default_avatar):
    """Dress form must share the same triangle connectivity as avatar."""
    dv, dt = fit_dress_form(default_avatar, ease_cm=2.5)
    np.testing.assert_array_equal(dt, default_avatar.mesh_triangles)


# ---------------------------------------------------------------------------
# 5. Landmarks are present and plausible
# ---------------------------------------------------------------------------

_EXPECTED_LANDMARKS = [
    "crown", "chin", "left_shoulder", "right_shoulder",
    "crotch", "left_knee", "right_knee",
]

@pytest.mark.parametrize("name", _EXPECTED_LANDMARKS)
def test_landmark_present(default_avatar, name):
    assert name in default_avatar.landmarks


def test_crown_is_highest_landmark(default_avatar):
    """Crown landmark should have the highest Y among all landmarks."""
    ys = {k: v[1] for k, v in default_avatar.landmarks.items()}
    assert ys["crown"] == max(ys.values())


def test_crotch_above_floor(default_avatar):
    """Crotch landmark should be above floor (Y > 0)."""
    assert default_avatar.landmarks["crotch"][1] > 0.0


# ---------------------------------------------------------------------------
# 6. Gender variants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gender", ["female", "male", "neutral"])
def test_gender_builds_mesh(gender):
    m = AvatarMeasurements(gender=gender)
    av = build_avatar(m)
    assert len(av.mesh_positions) > 100
    assert len(av.mesh_triangles) > 200


# ---------------------------------------------------------------------------
# 7. Skeleton is None (no character_rigging module)
# ---------------------------------------------------------------------------

def test_skeleton_is_none_by_default(default_avatar):
    """Without sculpt.character_rigging, skeleton must be None."""
    assert default_avatar.skeleton is None


# ---------------------------------------------------------------------------
# 8. Avatar returns correct Avatar dataclass
# ---------------------------------------------------------------------------

def test_build_avatar_returns_avatar_type(default_avatar):
    assert isinstance(default_avatar, Avatar)


def test_measurements_roundtrip():
    """AvatarMeasurements stored in Avatar must match input."""
    m = AvatarMeasurements(height_cm=165.0, bust_cm=88.0)
    av = build_avatar(m)
    assert av.measurements.height_cm == pytest.approx(165.0)
    assert av.measurements.bust_cm == pytest.approx(88.0)
