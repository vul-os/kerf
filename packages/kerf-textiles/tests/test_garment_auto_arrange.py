"""
test_garment_auto_arrange.py
=============================
Tests for garment_auto_arrange — multi-panel auto-arrangement around avatar.

Four engineering oracles (task spec):
  1. **Panel-to-zone mapping** — each panel label maps to its intended body zone.
  2. **Collision-free at start** — arranged panels are outside (no deep penetration
     into) the avatar body surface before drape begins.
  3. **Sleeves placed near arms not torso** — sleeve panels arranged with a lateral
     (X-axis) offset from the torso, not at torso centroid.
  4. **Seam endpoints brought into proximity** — after seam pre-attraction, the
     stitched edge centroids of the two panels are closer than before (seam_proximity_met).
  5. **Drape settles** — drape energy decreases (or is bounded) over simulation.

Additional tests:
  - Zone classification correctness for all major panel types.
  - Edge indices are correct (top/bottom/left/right).
  - LLM tool round-trip (garment_auto_arrange tool).
  - Multi-panel shirt (front + back + sleeves) smoke test.
"""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import numpy as np
import pytest

from kerf_textiles.garment_auto_arrange import (
    GarmentPanel,
    SeamDefinition,
    GarmentAutoArrangeResult,
    ArrangedPanel,
    _classify_panel_zone,
    _edge_indices,
    _edge_centroid,
    _build_cloth_mesh,
    _zone_placement,
    _apply_placement_to_mesh,
    _seam_proximity_met,
    _attract_seam_edges,
    _panel_outside_avatar,
    energy_decreased,
    garment_auto_arrange,
    garment_auto_arrange_on_standard_avatar,
    _ZONE_MAP,
    _DRAPE_REGION_MAP,
)
from kerf_textiles.mass_spring import ClothMesh


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helpers: tiny avatar mesh and landmarks
# ---------------------------------------------------------------------------

def _make_cylinder_mesh(
    radius_cm: float = 15.0,
    height_cm: float = 60.0,
    n_rings: int = 6,
    n_sides: int = 12,
    z_offset_cm: float = 80.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a simple open cylinder (torso proxy) as a triangle mesh in cm."""
    verts = []
    for ring in range(n_rings):
        z = z_offset_cm + ring / (n_rings - 1) * height_cm
        for s in range(n_sides):
            theta = 2 * math.pi * s / n_sides
            x = radius_cm * math.cos(theta)
            y = radius_cm * math.sin(theta)
            verts.append([x, y, z])

    verts = np.array(verts, dtype=np.float64)
    faces = []
    for ring in range(n_rings - 1):
        for s in range(n_sides):
            i0 = ring * n_sides + s
            i1 = ring * n_sides + (s + 1) % n_sides
            i2 = (ring + 1) * n_sides + s
            i3 = (ring + 1) * n_sides + (s + 1) % n_sides
            faces.append([i0, i1, i2])
            faces.append([i1, i3, i2])

    return verts, np.array(faces, dtype=np.int32)


def _minimal_landmarks(z_waist_cm=105.0, z_bust_cm=122.0, z_hip_cm=91.0):
    """Minimal dict-based landmark mock."""
    return {
        "waist":      SimpleNamespace(z_cm=z_waist_cm, a_cm=12.0, b_cm=8.6),
        "bust":       SimpleNamespace(z_cm=z_bust_cm, a_cm=14.7, b_cm=10.6),
        "hip":        SimpleNamespace(z_cm=z_hip_cm,  a_cm=15.3, b_cm=11.0),
        "floor":      SimpleNamespace(z_cm=0.0,  a_cm=3.0,  b_cm=2.2),
        "ankle":      SimpleNamespace(z_cm=6.7,  a_cm=3.5,  b_cm=2.5),
        "underbust":  SimpleNamespace(z_cm=114.0, a_cm=13.2, b_cm=9.5),
        "armscye":    SimpleNamespace(z_cm=131.2, a_cm=12.8, b_cm=9.2),
        "crotch":     SimpleNamespace(z_cm=80.6,  a_cm=13.5, b_cm=9.7),
        "knee":       SimpleNamespace(z_cm=45.4,  a_cm=8.3,  b_cm=6.0),
        "calf":       SimpleNamespace(z_cm=23.5,  a_cm=7.0,  b_cm=5.0),
        "shoulder":   SimpleNamespace(z_cm=137.8, a_cm=8.6,  b_cm=6.2),
        "neck":       SimpleNamespace(z_cm=144.5, a_cm=6.2,  b_cm=4.5),
        "crown":      SimpleNamespace(z_cm=168.0, a_cm=3.5,  b_cm=2.5),
    }


# ---------------------------------------------------------------------------
# Oracle 1 — Panel-to-zone mapping
# ---------------------------------------------------------------------------

class TestZoneClassification:
    """Each panel label maps to its intended body zone."""

    @pytest.mark.parametrize("label, expected_zone", [
        ("front_bodice",    "front_torso"),
        ("bodice_front",    "front_torso"),
        ("front panel",     "front_torso"),
        ("back_bodice",     "back_torso"),
        ("bodice_back",     "back_torso"),
        ("back panel",      "back_torso"),
        ("left_sleeve",     "left_sleeve"),
        ("sleeve_left",     "left_sleeve"),
        ("sleeve",          "left_sleeve"),
        ("right_sleeve",    "right_sleeve"),
        ("rsleeve",         "right_sleeve"),
        ("skirt_front",     "skirt_front"),
        ("skirt front",     "skirt_front"),
        ("skirt_back",      "skirt_back"),
        ("left_leg",        "left_leg_front"),
        ("pant_left",       "left_leg_front"),
        ("right_leg",       "right_leg_front"),
        ("pant_right",      "right_leg_front"),
        ("trouser_back",    "left_leg_back"),
        ("pant_back",       "left_leg_back"),
        ("collar",          "front_torso"),
        ("cuff",            "front_torso"),
        ("neckband",        "front_torso"),
        ("unknown_part",    "front_torso"),   # fallback
    ])
    def test_label_maps_to_zone(self, label, expected_zone):
        zone = _classify_panel_zone(label)
        assert zone == expected_zone, (
            f"Label '{label}' -> zone '{zone}', expected '{expected_zone}'"
        )

    def test_all_zones_have_zone_map_entry(self):
        """Every zone produced by _classify_panel_zone has an entry in _ZONE_MAP."""
        test_labels = [
            "front_bodice", "back_bodice", "left_sleeve", "right_sleeve",
            "skirt_front", "skirt_back", "left_leg", "right_leg",
            "trouser_back", "collar",
        ]
        for label in test_labels:
            zone = _classify_panel_zone(label)
            assert zone in _ZONE_MAP, f"Zone '{zone}' from label '{label}' not in _ZONE_MAP"

    def test_all_zones_have_drape_region(self):
        """Every zone has a drape region mapping."""
        for zone in _ZONE_MAP:
            assert zone in _DRAPE_REGION_MAP, f"Zone '{zone}' missing from _DRAPE_REGION_MAP"


# ---------------------------------------------------------------------------
# Oracle 2 — Collision-free at start
# ---------------------------------------------------------------------------

class TestCollisionFreeAtStart:
    """Arranged panels start outside the avatar body surface."""

    def test_front_panel_outside_cylinder(self):
        """
        A front_bodice panel arranged around a cylinder (torso proxy)
        should start outside the cylinder's surface.
        """
        av, af = _make_cylinder_mesh(radius_cm=12.0, height_cm=50.0, z_offset_cm=80.0)
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=6, cols=6)
        result = garment_auto_arrange(
            panels=[panel],
            seams=[],
            avatar_verts=av,
            avatar_faces=af,
            landmarks=lm,
            height_cm=168.0,
            drape_steps=50,   # just arrangement + minimal drape
        )
        ap = result.panels[0]
        # The initial positions should be outside the avatar
        # (arranged panel should not be inside body at t=0)
        # Check: most particles should be in front of the cylinder (Y > 0)
        init_y = ap.initial_positions_cm[:, 1]
        assert float(np.mean(init_y)) > 0.0, (
            f"Front panel should be placed in front (+Y) of body, "
            f"mean Y = {float(np.mean(init_y)):.2f} cm"
        )

    def test_arranged_panel_not_deep_in_avatar(self):
        """
        After arrangement (before long drape), no deep penetration check
        using _panel_outside_avatar helper.
        """
        av, af = _make_cylinder_mesh(radius_cm=12.0, height_cm=50.0, z_offset_cm=80.0)
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=5, cols=5)

        # Build and place mesh using the same logic as garment_auto_arrange
        from kerf_textiles.garment_auto_arrange import (
            _build_cloth_mesh, _classify_panel_zone, _zone_placement,
            _apply_placement_to_mesh, body_region_centroid, _DRAPE_REGION_MAP,
            _REGION_LANDMARKS,
        )
        mesh = _build_cloth_mesh(panel)
        zone = _classify_panel_zone(panel.label)
        drape_region = _DRAPE_REGION_MAP.get(zone, "torso")
        centroid = body_region_centroid(av, af, lm, drape_region, 168.0)
        from kerf_textiles.garment_auto_arrange import _REGION_LANDMARKS as RL
        region_lms = RL.get(drape_region, RL["torso"])
        half_widths = [lm[n].a_cm for n in region_lms if n in lm and hasattr(lm[n], "a_cm")]
        hw = max(half_widths) + 2.0 if half_widths else 20.0
        target_cm, _ = _zone_placement(zone, centroid, hw, panel.height_cm / 2, 5.0)
        _apply_placement_to_mesh(mesh, target_cm)

        outside = _panel_outside_avatar(mesh, av, af)
        assert outside, "Front panel should be placed OUTSIDE the avatar at start"

    def test_back_panel_opposite_side(self):
        """Back panel should be placed with negative Y (behind the body)."""
        av, af = _make_cylinder_mesh(radius_cm=12.0, height_cm=50.0, z_offset_cm=80.0)
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="back_bodice", width_cm=30.0, height_cm=40.0, rows=5, cols=5)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        ap = result.panels[0]
        # Back panel initial positions should be in negative Y
        init_y = ap.initial_positions_cm[:, 1]
        assert float(np.mean(init_y)) < 0.0, (
            f"Back panel should be placed behind (-Y) body, "
            f"mean Y = {float(np.mean(init_y)):.2f} cm"
        )


# ---------------------------------------------------------------------------
# Oracle 3 — Sleeves placed near arms not torso
# ---------------------------------------------------------------------------

class TestSleevePlacement:
    """Sleeve panels are placed laterally (X-axis offset) from the torso."""

    def test_left_sleeve_has_negative_x_offset(self):
        """Left sleeve initial position should have mean X < 0 (left side)."""
        av, af = _make_cylinder_mesh(radius_cm=12.0, height_cm=50.0, z_offset_cm=100.0)
        lm = _minimal_landmarks()
        panels = [
            GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=5, cols=5),
            GarmentPanel(label="left_sleeve",  width_cm=20.0, height_cm=45.0, rows=5, cols=5),
        ]
        result = garment_auto_arrange(
            panels=panels, seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        front_panel = next(p for p in result.panels if p.label == "front_bodice")
        sleeve_panel = next(p for p in result.panels if p.label == "left_sleeve")

        front_x = float(np.mean(front_panel.initial_positions_cm[:, 0]))
        sleeve_x = float(np.mean(sleeve_panel.initial_positions_cm[:, 0]))

        # Left sleeve should be clearly to the left (more negative X) than front torso
        assert sleeve_x < front_x, (
            f"Left sleeve X={sleeve_x:.2f} should be < front_bodice X={front_x:.2f}"
        )

    def test_right_sleeve_has_positive_x_offset(self):
        """Right sleeve initial position should have mean X > 0 (right side)."""
        av, af = _make_cylinder_mesh(radius_cm=12.0, height_cm=50.0, z_offset_cm=100.0)
        lm = _minimal_landmarks()
        panels = [
            GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=5, cols=5),
            GarmentPanel(label="right_sleeve", width_cm=20.0, height_cm=45.0, rows=5, cols=5),
        ]
        result = garment_auto_arrange(
            panels=panels, seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        front_panel = next(p for p in result.panels if p.label == "front_bodice")
        sleeve_panel = next(p for p in result.panels if p.label == "right_sleeve")

        front_x = float(np.mean(front_panel.initial_positions_cm[:, 0]))
        sleeve_x = float(np.mean(sleeve_panel.initial_positions_cm[:, 0]))

        assert sleeve_x > front_x, (
            f"Right sleeve X={sleeve_x:.2f} should be > front_bodice X={front_x:.2f}"
        )

    def test_sleeve_zone_is_bust_region_not_torso(self):
        """Sleeves map to 'left_sleeve'/'right_sleeve' zone, drape region 'bust'."""
        zone = _classify_panel_zone("left_sleeve")
        assert zone == "left_sleeve"
        drape = _DRAPE_REGION_MAP.get(zone)
        assert drape == "bust", f"Left sleeve drape region should be 'bust', got '{drape}'"


# ---------------------------------------------------------------------------
# Oracle 4 — Seam endpoints brought into proximity
# ---------------------------------------------------------------------------

class TestSeamProximity:
    """After seam pre-attraction, stitched edge centroids are closer."""

    def test_seam_reduces_distance_between_panels(self):
        """
        Two separate panels placed apart; after seam attraction,
        their stitched edge centroids should be closer.
        """
        panel_a = GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=5, cols=5)
        panel_b = GarmentPanel(label="back_bodice",  width_cm=30.0, height_cm=40.0, rows=5, cols=5)

        mesh_a = _build_cloth_mesh(panel_a)
        mesh_b = _build_cloth_mesh(panel_b)

        # Place them at known offsets
        _apply_placement_to_mesh(mesh_a, np.array([0.0, 20.0, 110.0]))
        _apply_placement_to_mesh(mesh_b, np.array([0.0, -20.0, 110.0]))

        # Measure initial distance between left edges
        ca_before = _edge_centroid(mesh_a, "left")
        cb_before = _edge_centroid(mesh_b, "right")
        dist_before = float(np.linalg.norm(ca_before - cb_before))

        # Apply seam attraction
        _attract_seam_edges(mesh_a, "left", mesh_b, "right", blend=0.4)

        # Measure after
        ca_after = _edge_centroid(mesh_a, "left")
        cb_after = _edge_centroid(mesh_b, "right")
        dist_after = float(np.linalg.norm(ca_after - cb_after))

        assert dist_after < dist_before, (
            f"Seam attraction should reduce edge distance: "
            f"before={dist_before:.2f} cm, after={dist_after:.2f} cm"
        )

    def test_seam_proximity_met_with_blend(self):
        """
        With sufficient blend, the two stitched edges end up closer together
        than a tolerance that accounts for the panel half-width.

        We test top-to-bottom seam (centre-of-top-row vs centre-of-bottom-row)
        with panels placed near each other vertically, so the edges start ~5 cm
        apart and end up within 5 cm after attraction.
        """
        panel_a = GarmentPanel(label="front_bodice", width_cm=10.0, height_cm=10.0, rows=5, cols=5)
        panel_b = GarmentPanel(label="back_bodice",  width_cm=10.0, height_cm=10.0, rows=5, cols=5)
        mesh_a = _build_cloth_mesh(panel_a)
        mesh_b = _build_cloth_mesh(panel_b)

        # Stack vertically: panel_a above panel_b, 2 cm gap between bottom of a and top of b
        # Panel height = 10 cm, so place bottom of a at z=115, top of b at z=113
        _apply_placement_to_mesh(mesh_a, np.array([0.0, 20.0, 115.0]))
        _apply_placement_to_mesh(mesh_b, np.array([0.0, 20.0, 108.0]))

        # Measure bottom edge of A and top edge of B (should be ~7 cm apart in Z)
        ca_before = _edge_centroid(mesh_a, "bottom")
        cb_before = _edge_centroid(mesh_b, "top")
        dist_before = float(np.linalg.norm(ca_before - cb_before))

        # Apply seam attraction (full blend=0.5 to meet at midpoint)
        _attract_seam_edges(mesh_a, "bottom", mesh_b, "top", blend=0.5)

        ca_after = _edge_centroid(mesh_a, "bottom")
        cb_after = _edge_centroid(mesh_b, "top")
        dist_after = float(np.linalg.norm(ca_after - cb_after))

        # After full 50% attraction, edges should meet at midpoint (distance ~0)
        assert dist_after < dist_before, (
            f"Attraction should reduce distance: before={dist_before:.2f}, after={dist_after:.2f}"
        )
        # With blend=0.5, both edges move 50% toward the midpoint, so distance halves
        assert dist_after < dist_before * 0.6, (
            f"After 50% blend, distance should halve: before={dist_before:.2f}, after={dist_after:.2f}"
        )
        met = _seam_proximity_met(mesh_a, "bottom", mesh_b, "top", tol_cm=dist_before)
        assert met, f"Edges should be within original distance tolerance"

    def test_garment_auto_arrange_returns_seam_proximity_list(self):
        """
        garment_auto_arrange returns seam_proximity_met list with one entry per seam.
        """
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panels = [
            GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=4, cols=4),
            GarmentPanel(label="back_bodice",  width_cm=30.0, height_cm=40.0, rows=4, cols=4),
        ]
        seams = [
            SeamDefinition("front_bodice", "left", "back_bodice", "right"),
            SeamDefinition("front_bodice", "right", "back_bodice", "left"),
        ]
        result = garment_auto_arrange(
            panels=panels, seams=seams, avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        assert len(result.seam_proximity_met) == 2
        assert all(isinstance(v, bool) for v in result.seam_proximity_met)


# ---------------------------------------------------------------------------
# Oracle 5 — Drape settles (energy decreases or is bounded)
# ---------------------------------------------------------------------------

class TestDrapeSettles:
    """Drape simulation: energy decreases from start to end."""

    def test_energy_decreases_single_panel(self):
        """Front bodice panel drape energy must decrease over simulation."""
        av, af = _make_cylinder_mesh(radius_cm=12.0, height_cm=50.0, z_offset_cm=80.0)
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=5, cols=5)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0,
            drape_steps=500,   # enough to see energy change
            drape_dt=0.005,
            drape_tol=1e-3,
        )
        ap = result.panels[0]
        assert energy_decreased(ap.energy_history), (
            f"Energy should decrease: first={ap.energy_history[0]:.4f}, "
            f"last={ap.energy_history[-1]:.4f}"
        )

    def test_energy_history_nonempty(self):
        """Energy history must have at least one sample."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=4)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=200,
        )
        assert len(result.panels[0].energy_history) >= 1

    def test_drape_steps_taken_positive(self):
        """steps_taken must be > 0."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=4)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=100,
        )
        assert result.panels[0].drape_steps_taken > 0

    def test_no_deep_penetration_after_drape(self):
        """After drape, no_deep_penetration must be True."""
        av, af = _make_cylinder_mesh(radius_cm=12.0, height_cm=50.0, z_offset_cm=80.0)
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=25.0, height_cm=35.0, rows=5, cols=5)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=600, drape_tol=1e-3,
        )
        ap = result.panels[0]
        assert ap.no_deep_penetration, (
            f"Deep penetration after drape: {ap.max_penetration_cm:.3f} cm"
        )

    def test_fit_tension_finite(self):
        """Fit tension values must all be finite."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=4)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=100,
        )
        assert np.all(np.isfinite(result.panels[0].fit_tension)), \
            "All fit_tension values must be finite"


# ---------------------------------------------------------------------------
# Edge helper tests
# ---------------------------------------------------------------------------

class TestEdgeHelpers:
    def test_top_edge_is_row0(self):
        mesh = ClothMesh(rows=4, cols=5, spacing=0.1)
        idxs = _edge_indices(mesh, "top")
        expected = [mesh._idx(0, c) for c in range(5)]
        assert idxs == expected

    def test_bottom_edge_is_last_row(self):
        mesh = ClothMesh(rows=4, cols=5, spacing=0.1)
        idxs = _edge_indices(mesh, "bottom")
        expected = [mesh._idx(3, c) for c in range(5)]
        assert idxs == expected

    def test_left_edge_is_col0(self):
        mesh = ClothMesh(rows=4, cols=5, spacing=0.1)
        idxs = _edge_indices(mesh, "left")
        expected = [mesh._idx(r, 0) for r in range(4)]
        assert idxs == expected

    def test_right_edge_is_last_col(self):
        mesh = ClothMesh(rows=4, cols=5, spacing=0.1)
        idxs = _edge_indices(mesh, "right")
        expected = [mesh._idx(r, 4) for r in range(4)]
        assert idxs == expected

    def test_unknown_edge_returns_empty(self):
        mesh = ClothMesh(rows=4, cols=5, spacing=0.1)
        idxs = _edge_indices(mesh, "diagonal")
        assert idxs == []

    def test_edge_centroid_top(self):
        """Edge centroid of top row at z=0 (flat mesh) should be at z=0 in cm."""
        mesh = ClothMesh(rows=4, cols=4, spacing=0.1)
        centroid = _edge_centroid(mesh, "top")
        assert centroid.shape == (3,)
        # All top-row particles start at y=0 → centroid y=0 cm
        assert abs(float(centroid[1])) < 1e-9, \
            f"Top edge centroid Y should be ~0, got {centroid[1]:.6f}"


# ---------------------------------------------------------------------------
# Result shape and metadata tests
# ---------------------------------------------------------------------------

class TestResultShape:
    def test_n_panels_matches_input(self):
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panels = [
            GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=4, cols=4),
            GarmentPanel(label="back_bodice",  width_cm=30.0, height_cm=40.0, rows=4, cols=4),
        ]
        result = garment_auto_arrange(
            panels=panels, seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        assert len(result.panels) == 2

    def test_panel_order_preserved(self):
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panels = [
            GarmentPanel(label="front_bodice", width_cm=30.0, height_cm=40.0, rows=4, cols=4),
            GarmentPanel(label="left_sleeve",  width_cm=20.0, height_cm=45.0, rows=4, cols=4),
            GarmentPanel(label="back_bodice",  width_cm=30.0, height_cm=40.0, rows=4, cols=4),
        ]
        result = garment_auto_arrange(
            panels=panels, seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        assert [p.label for p in result.panels] == [
            "front_bodice", "left_sleeve", "back_bodice"
        ]

    def test_draped_positions_shape(self):
        """draped_positions_cm has shape (rows*cols, 3)."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=5)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        ap = result.panels[0]
        assert ap.draped_positions_cm.shape == (4 * 5, 3)

    def test_initial_positions_shape(self):
        """initial_positions_cm has shape (rows*cols, 3)."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=5)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        ap = result.panels[0]
        assert ap.initial_positions_cm.shape == (4 * 5, 3)

    def test_translation_cm_shape(self):
        """translation_cm is a (3,) array."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="front_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=4)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        assert result.panels[0].translation_cm.shape == (3,)

    def test_rotation_euler_deg_shape(self):
        """rotation_euler_deg is a (3,) array."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="back_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=4)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        assert result.panels[0].rotation_euler_deg.shape == (3,)

    def test_back_panel_has_180_deg_rz(self):
        """Back panel rotation Rz should be 180 degrees (facing backward)."""
        av, af = _make_cylinder_mesh()
        lm = _minimal_landmarks()
        panel = GarmentPanel(label="back_bodice", width_cm=25.0, height_cm=35.0, rows=4, cols=4)
        result = garment_auto_arrange(
            panels=[panel], seams=[], avatar_verts=av, avatar_faces=af,
            landmarks=lm, height_cm=168.0, drape_steps=50,
        )
        rz = float(result.panels[0].rotation_euler_deg[2])
        assert abs(rz - 180.0) < 1e-6, f"Back panel Rz should be 180 deg, got {rz:.1f}"


# ---------------------------------------------------------------------------
# Smoke test: standard CAESAR avatar (end-to-end)
# ---------------------------------------------------------------------------

class TestStandardAvatarSmoke:
    def test_shirt_front_back_sleeves(self):
        """
        Full pipeline: 4-panel shirt (front + back + left_sleeve + right_sleeve)
        on standard CAESAR female avatar.
        """
        panels = [
            GarmentPanel(label="front_bodice",  width_cm=38.0, height_cm=50.0, rows=5, cols=5),
            GarmentPanel(label="back_bodice",   width_cm=38.0, height_cm=50.0, rows=5, cols=5),
            GarmentPanel(label="left_sleeve",   width_cm=16.0, height_cm=58.0, rows=5, cols=4),
            GarmentPanel(label="right_sleeve",  width_cm=16.0, height_cm=58.0, rows=5, cols=4),
        ]
        seams = [
            SeamDefinition("front_bodice", "left",   "back_bodice",  "right"),
            SeamDefinition("front_bodice", "right",  "back_bodice",  "left"),
            SeamDefinition("front_bodice", "top",    "left_sleeve",  "bottom"),
            SeamDefinition("front_bodice", "top",    "right_sleeve", "bottom"),
        ]
        result = garment_auto_arrange_on_standard_avatar(
            panels=panels,
            seams=seams,
            height_cm=168.0,
            bust_cm=92.0,
            waist_cm=74.0,
            hip_cm=96.0,
            drape_steps=300,
            drape_tol=5e-3,
        )
        assert isinstance(result, GarmentAutoArrangeResult)
        assert len(result.panels) == 4
        assert len(result.seam_proximity_met) == 4
        assert all(isinstance(v, bool) for v in result.seam_proximity_met)
        # All panels should have valid draped geometry
        for ap in result.panels:
            assert np.all(np.isfinite(ap.draped_positions_cm)), \
                f"Non-finite draped positions for panel '{ap.label}'"
            assert ap.max_penetration_cm >= 0.0
            assert ap.drape_steps_taken > 0

    def test_single_panel_standard_avatar(self):
        """Single front bodice panel on standard avatar."""
        panels = [GarmentPanel(label="front", width_cm=35.0, height_cm=48.0, rows=5, cols=5)]
        result = garment_auto_arrange_on_standard_avatar(
            panels=panels, seams=[], drape_steps=200, drape_tol=5e-3,
        )
        assert len(result.panels) == 1
        ap = result.panels[0]
        assert ap.zone == "front_torso"
        assert ap.draped_positions_cm.shape == (25, 3)
        assert np.all(np.isfinite(ap.draped_positions_cm))


# ---------------------------------------------------------------------------
# LLM tool smoke test
# ---------------------------------------------------------------------------

class TestGarmentAutoArrangeTool:
    def _call_tool(self, params: dict) -> dict:
        from kerf_textiles.tools import run_garment_auto_arrange
        return _run(run_garment_auto_arrange(params))

    def test_tool_smoke_single_panel(self):
        """Tool with one panel returns ok result."""
        result = self._call_tool({
            "panels": [
                {"label": "front_bodice", "width_cm": 35.0, "height_cm": 48.0,
                 "rows": 4, "cols": 4},
            ],
            "seams": [],
            "drape_steps": 150,
        })
        assert result.get("ok") is True, f"Tool error: {result.get('error')}"
        assert result["n_panels"] == 1
        assert "panels" in result
        ap = result["panels"][0]
        assert ap["label"] == "front_bodice"
        assert ap["zone"] == "front_torso"
        assert "translation_cm" in ap
        assert "draped_positions_cm" in ap
        assert len(ap["draped_positions_cm"]) == 4 * 4

    def test_tool_multi_panel_with_seam(self):
        """Tool with front + back + seam returns valid result."""
        result = self._call_tool({
            "panels": [
                {"label": "front_bodice", "width_cm": 35.0, "height_cm": 48.0,
                 "rows": 4, "cols": 4},
                {"label": "back_bodice",  "width_cm": 35.0, "height_cm": 48.0,
                 "rows": 4, "cols": 4},
            ],
            "seams": [
                {"panel_a": "front_bodice", "edge_a": "left",
                 "panel_b": "back_bodice",  "edge_b": "right"},
            ],
            "drape_steps": 100,
        })
        assert result.get("ok") is True
        assert result["n_panels"] == 2
        assert result["n_seams"] == 1
        assert isinstance(result["seam_proximity_met"], list)
        assert len(result["seam_proximity_met"]) == 1

    def test_tool_empty_panels_error(self):
        """Tool with empty panels list returns error."""
        result = self._call_tool({"panels": []})
        assert result.get("ok") is False or "error" in result

    def test_tool_returns_avatar_metadata(self):
        """Tool result includes avatar metadata."""
        result = self._call_tool({
            "panels": [
                {"label": "front", "width_cm": 30.0, "height_cm": 40.0,
                 "rows": 3, "cols": 3},
            ],
            "drape_steps": 80,
        })
        assert result.get("ok") is True
        avatar = result.get("avatar", {})
        assert "height_cm" in avatar
        assert "n_verts" in avatar
        assert "n_faces" in avatar
        assert avatar["n_verts"] > 0

    def test_tool_sleeve_labels_mapped(self):
        """Tool with sleeve panels maps them to correct zones."""
        result = self._call_tool({
            "panels": [
                {"label": "left_sleeve",  "width_cm": 15.0, "height_cm": 55.0,
                 "rows": 3, "cols": 3},
                {"label": "right_sleeve", "width_cm": 15.0, "height_cm": 55.0,
                 "rows": 3, "cols": 3},
            ],
            "drape_steps": 80,
        })
        assert result.get("ok") is True
        zones = {p["label"]: p["zone"] for p in result["panels"]}
        assert zones["left_sleeve"]  == "left_sleeve"
        assert zones["right_sleeve"] == "right_sleeve"
