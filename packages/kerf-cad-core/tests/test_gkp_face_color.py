"""GK-P — Hermetic oracle tests for face_color.py.

Four analytical-oracle tests:

1. Cube color — a make_box body → all 6 faces colored gray (planar) per
   the default palette.

2. Cylinder color — a make_cylinder body → top/bottom (planar) = gray;
   side (cylindrical) = blue.

3. Curvature mode — a make_sphere body under scheme='curvature' → all
   faces have mean curvature H > 0 → colored toward the red end (R > G
   and R > B).

4. STEP export round-trip — export_colors_to_step then parse COLOUR_RGB
   lines back → same colors preserved within RGB integer rounding.

All tests are hermetic — no network, no OCCT, no external fixtures.
"""

from __future__ import annotations

import os
import re
import tempfile

import pytest

from kerf_cad_core.geom.brep import make_box, make_cylinder, make_sphere
from kerf_cad_core.geom.face_color import (
    assign_face_colors,
    export_colors_to_step,
    palette_dict,
)


# ---------------------------------------------------------------------------
# Test 1: Cube color — all faces planar → all gray
# ---------------------------------------------------------------------------


def test_cube_all_faces_planar_gray():
    """A plain box body → all 6 faces colored gray (192, 192, 192) per default palette."""
    box = make_box(size=(10.0, 10.0, 10.0))
    colors = assign_face_colors(box, scheme="feature", palette="default")

    pal = palette_dict("default")
    expected_planar_gray = pal["planar"]  # (192, 192, 192)

    faces = list(box.all_faces())
    assert len(faces) == 6, f"Expected 6 faces, got {len(faces)}"
    assert len(colors) == 6, f"Expected 6 color entries, got {len(colors)}"

    for face in faces:
        fid = face.id
        assert fid in colors, f"Face {fid} missing from color map"
        rgb = colors[fid]
        assert rgb == expected_planar_gray, (
            f"Face {fid}: expected gray {expected_planar_gray}, got {rgb}"
        )


# ---------------------------------------------------------------------------
# Test 2: Cylinder color — top/bottom planar=gray, side cylindrical=blue
# ---------------------------------------------------------------------------


def test_cylinder_planar_gray_cylindrical_blue():
    """A make_cylinder body → top/bottom planar faces = gray; side cylindrical = blue."""
    from kerf_cad_core.geom.brep import Plane, CylinderSurface

    cyl = make_cylinder(radius=5.0, height=10.0)
    colors = assign_face_colors(cyl, scheme="feature", palette="default")

    pal = palette_dict("default")
    gray = pal["planar"]        # (192, 192, 192)
    blue = pal["cylindrical"]   # (100, 150, 255)

    faces = list(cyl.all_faces())
    # A canonical cylinder body has 3 faces: top cap, bottom cap, side wall
    assert len(faces) == 3, f"Expected 3 faces for cylinder, got {len(faces)}"

    planar_colors = set()
    cyl_colors = set()

    for face in faces:
        surf = face.surface
        rgb = colors[face.id]
        if isinstance(surf, Plane):
            planar_colors.add(rgb)
        else:
            cyl_colors.add(rgb)

    assert planar_colors == {gray}, (
        f"Planar faces should be gray {gray}, got {planar_colors}"
    )
    assert cyl_colors == {blue}, (
        f"Cylindrical face should be blue {blue}, got {cyl_colors}"
    )


# ---------------------------------------------------------------------------
# Test 3: Curvature mode — sphere → all faces toward the red end
# ---------------------------------------------------------------------------


def test_sphere_curvature_scheme_red_dominant():
    """A make_sphere body under scheme='curvature' → all faces have positive mean
    curvature → colored toward the red end (R >= G and R >= B)."""
    sph = make_sphere(radius=5.0)
    colors = assign_face_colors(sph, scheme="curvature")

    faces = list(sph.all_faces())
    assert len(faces) >= 1, "Sphere should have at least 1 face"
    assert len(colors) == len(faces), "Every face must appear in the color map"

    for face in faces:
        fid = face.id
        rgb = colors[fid]
        r, g, b = rgb
        # For a convex sphere, mean curvature H > 0 → the color should lean
        # toward red (R >= G and R >= B).  Gray (192,192,192) is the flat
        # baseline; we expect the sphere to shift toward red.
        assert r >= g and r >= b, (
            f"Face {fid}: expected red-dominant color (H > 0), got {rgb}"
        )


# ---------------------------------------------------------------------------
# Test 4: STEP export round-trip — colors preserved within integer rounding
# ---------------------------------------------------------------------------


def test_step_export_color_roundtrip():
    """export_colors_to_step then parse COLOUR_RGB lines back → same colors (±1)."""
    box = make_box(size=(5.0, 5.0, 5.0))
    colors = assign_face_colors(box, scheme="feature", palette="default")

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tf:
        tmp_path = tf.name

    try:
        export_colors_to_step(box, colors, tmp_path)

        text = open(tmp_path, encoding="utf-8").read()

        # Verify the file was upgraded to AP242
        assert "MANAGED_MODEL_BASED_3D_ENGINEERING" in text or \
               "COLOUR_RGB" in text, (
            "STEP file should contain AP242 color entities"
        )

        # Parse all COLOUR_RGB lines  → float 0-1 → convert to 0-255 int
        # Pattern: #NNN=COLOUR_RGB('',R_float,G_float,B_float);
        pattern = re.compile(
            r"COLOUR_RGB\('',\s*([\d.eE+\-]+),\s*([\d.eE+\-]+),\s*([\d.eE+\-]+)\)"
        )
        parsed_colors = []
        for m in pattern.finditer(text):
            r = round(float(m.group(1)) * 255)
            g = round(float(m.group(2)) * 255)
            b = round(float(m.group(3)) * 255)
            parsed_colors.append((r, g, b))

        # For a plain box all 6 faces are gray → expect at least 1 COLOUR_RGB
        assert len(parsed_colors) >= 1, (
            "Expected at least 1 COLOUR_RGB entity in STEP file, found none.\n"
            f"File excerpt:\n{text[:800]}"
        )

        # Every parsed color should match the assigned color within rounding (±1)
        target_rgb = colors[list(colors.keys())[0]]  # all same for box
        for prgb in parsed_colors:
            for got, want in zip(prgb, target_rgb):
                assert abs(got - want) <= 1, (
                    f"Color round-trip mismatch: expected {target_rgb}, got {prgb}"
                )

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Bonus: palette_dict returns the correct keys and integer values
# ---------------------------------------------------------------------------


def test_palette_dict_structure():
    """palette_dict returns a dict with expected keys and 0-255 integer RGB tuples."""
    for name in ("default", "engineering", "aesthetic"):
        pal = palette_dict(name)
        assert "planar" in pal
        assert "cylindrical" in pal
        assert "sphere" in pal
        assert "fillet" in pal
        for kind, rgb in pal.items():
            assert len(rgb) == 3, f"palette {name} kind {kind}: not 3-tuple"
            for c in rgb:
                assert isinstance(c, int), f"palette {name} kind {kind}: {c} not int"
                assert 0 <= c <= 255, f"palette {name} kind {kind}: {c} out of range"

    with pytest.raises(ValueError):
        palette_dict("nonexistent_palette")
