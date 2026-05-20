"""
kerf_textiles.sublimation
=========================
Dye-sublimation art-alignment pipeline — continuous-tone path.

Workflow
--------
1. ``unwrap_cylinder``       — unwrap a parametric cylinder to a flat UV panel
2. ``project_artwork``       — map a RGBA artwork image onto the UV panel
3. ``add_bleed``             — extend panel edges by a bleed margin (mm)
4. ``add_registration_marks``— overlay press-registration crosshairs onto the image
5. ``render_panel_png``      — composite all of the above into a print-ready PIL Image

All geometry uses numpy arrays; raster ops use Pillow (PIL).  No external
dependencies beyond numpy + Pillow.

Units
-----
Dimensions are expressed in millimetres unless noted.  DPI is used only when
converting to pixels (``mm_to_px``).

Cylinder unwrap geometry
------------------------
A cylinder of radius R and height H unwraps to a flat rectangle:
    width  = 2π·R          (circumference)
    height = H

Area is preserved exactly:
    cylinder_area = 2π·R·H
    flat_area     = (2π·R) · H   ✓

The UV coordinates map linearly:
    u = θ / (2π)            (azimuth angle → horizontal position)
    v = z / H               (height → vertical position)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    raise ImportError("Pillow is required for sublimation: pip install Pillow") from exc


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_DPI = 150           # print resolution for raster output
DEFAULT_BLEED_MM = 3.0      # industry standard bleed margin
REG_MARK_SIZE_MM = 8.0      # registration cross size


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mm_to_px(mm: float, dpi: float = DEFAULT_DPI) -> int:
    """Convert millimetres to pixels at the given DPI.  Returns 0 for mm=0."""
    if mm == 0.0:
        return 0
    return max(1, round(mm * dpi / 25.4))


def px_to_mm(px: int, dpi: float = DEFAULT_DPI) -> float:
    """Convert pixels to millimetres at the given DPI."""
    return px * 25.4 / dpi


# ---------------------------------------------------------------------------
# Cylinder mesh unwrap
# ---------------------------------------------------------------------------

@dataclass
class CylinderPanel:
    """
    Flat unwrapped panel derived from a cylinder.

    Attributes
    ----------
    radius_mm:    cylinder radius in mm
    height_mm:    cylinder height in mm
    width_mm:     flat panel width = 2π·radius (circumference)
    height_mm:    flat panel height = cylinder height (identical field name)
    area_mm2:     panel area (== cylinder lateral surface area)
    dpi:          raster resolution
    width_px:     panel width in pixels
    height_px:    panel height in pixels
    uv_grid:      (height_px, width_px, 2) float32 array of (u, v) ∈ [0,1]²
    """
    radius_mm: float
    height_mm: float
    width_mm: float
    area_mm2: float
    dpi: float
    width_px: int
    height_px: int
    uv_grid: np.ndarray          # shape (height_px, width_px, 2)


def unwrap_cylinder(
    radius_mm: float,
    height_mm: float,
    dpi: float = DEFAULT_DPI,
) -> CylinderPanel:
    """
    Unwrap a cylinder of given radius and height to a flat rectangular panel.

    The lateral surface area is preserved:
        area = 2π·radius·height

    Parameters
    ----------
    radius_mm:   cylinder radius in millimetres (> 0)
    height_mm:   cylinder height in millimetres (> 0)
    dpi:         raster resolution for the output panel

    Returns
    -------
    CylinderPanel with a (u, v) grid covering [0, 1] in both axes.
    """
    if radius_mm <= 0:
        raise ValueError(f"radius_mm must be > 0, got {radius_mm}")
    if height_mm <= 0:
        raise ValueError(f"height_mm must be > 0, got {height_mm}")

    width_mm = 2.0 * math.pi * radius_mm
    area_mm2 = width_mm * height_mm  # == 2π·r·h

    width_px = mm_to_px(width_mm, dpi)
    height_px = mm_to_px(height_mm, dpi)

    # Build UV grid: uv[row, col] = (u, v) where u = col/(W-1), v = row/(H-1)
    u_lin = np.linspace(0.0, 1.0, width_px, dtype=np.float32)
    v_lin = np.linspace(0.0, 1.0, height_px, dtype=np.float32)
    uu, vv = np.meshgrid(u_lin, v_lin)
    uv_grid = np.stack([uu, vv], axis=-1)

    return CylinderPanel(
        radius_mm=radius_mm,
        height_mm=height_mm,
        width_mm=width_mm,
        area_mm2=area_mm2,
        dpi=dpi,
        width_px=width_px,
        height_px=height_px,
        uv_grid=uv_grid,
    )


# ---------------------------------------------------------------------------
# Artwork projection
# ---------------------------------------------------------------------------

def project_artwork(
    panel: CylinderPanel,
    artwork: Image.Image,
) -> Image.Image:
    """
    Map a PIL artwork image onto the UV panel by bilinear sampling.

    The artwork's (0,0) → (1,1) UV space is mapped over the entire panel.
    If the artwork aspect ratio differs from the panel's, the image is
    stretched to fit (full coverage) — callers should pre-crop/scale as needed.

    Parameters
    ----------
    panel:    unwrapped cylinder panel (defines output dimensions)
    artwork:  RGBA source image; will be converted to RGBA if needed

    Returns
    -------
    RGBA PIL Image of size (panel.width_px, panel.height_px).
    """
    art = artwork.convert("RGBA")
    art_w, art_h = art.size

    # Fast path: just resize the artwork to panel dimensions.
    # This is equivalent to bilinear UV remapping when the panel is rectangular
    # (which it always is for an unwrapped cylinder).
    projected = art.resize(
        (panel.width_px, panel.height_px),
        resample=Image.BILINEAR,
    )
    return projected


# ---------------------------------------------------------------------------
# Bleed margin
# ---------------------------------------------------------------------------

@dataclass
class BleedResult:
    """Output of add_bleed."""
    image: Image.Image          # full image with bleed border
    bleed_px: int               # bleed width in pixels
    bleed_mm: float             # bleed width in mm (actual, may differ from requested)
    content_box: tuple[int, int, int, int]  # (left, top, right, bottom) of content area


def add_bleed(
    image: Image.Image,
    bleed_mm: float = DEFAULT_BLEED_MM,
    dpi: float = DEFAULT_DPI,
) -> BleedResult:
    """
    Extend a print panel by mirroring edges to produce the bleed margin.

    The bleed region is filled by reflecting/wrapping the edge pixels so
    that the printing substrate is covered even with slight mis-registration.

    Parameters
    ----------
    image:     source panel (RGBA or RGB)
    bleed_mm:  bleed width in millimetres (standard: 3 mm)
    dpi:       raster resolution (must match panel DPI)

    Returns
    -------
    BleedResult with the extended image and the content bounding box.
    """
    if bleed_mm < 0:
        raise ValueError(f"bleed_mm must be >= 0, got {bleed_mm}")

    bleed_px = mm_to_px(bleed_mm, dpi)
    src = image.convert("RGBA")
    sw, sh = src.size

    new_w = sw + 2 * bleed_px
    new_h = sh + 2 * bleed_px

    out = Image.new("RGBA", (new_w, new_h), (255, 255, 255, 255))

    # Paste content into centre
    out.paste(src, (bleed_px, bleed_px))

    # Mirror left edge
    if bleed_px > 0:
        left_strip = src.crop((0, 0, bleed_px, sh)).transpose(Image.FLIP_LEFT_RIGHT)
        out.paste(left_strip, (0, bleed_px))

        # Mirror right edge
        right_strip = src.crop((sw - bleed_px, 0, sw, sh)).transpose(Image.FLIP_LEFT_RIGHT)
        out.paste(right_strip, (bleed_px + sw, bleed_px))

        # Mirror top edge
        top_strip = src.crop((0, 0, sw, bleed_px)).transpose(Image.FLIP_TOP_BOTTOM)
        out.paste(top_strip, (bleed_px, 0))

        # Mirror bottom edge
        bottom_strip = src.crop((0, sh - bleed_px, sw, sh)).transpose(Image.FLIP_TOP_BOTTOM)
        out.paste(bottom_strip, (bleed_px, bleed_px + sh))

        # Fill corners by reflecting the corner pixels
        out.paste(src.crop((0, 0, bleed_px, bleed_px))
                  .transpose(Image.FLIP_LEFT_RIGHT)
                  .transpose(Image.FLIP_TOP_BOTTOM),
                  (0, 0))
        out.paste(src.crop((sw - bleed_px, 0, sw, bleed_px))
                  .transpose(Image.FLIP_LEFT_RIGHT)
                  .transpose(Image.FLIP_TOP_BOTTOM),
                  (bleed_px + sw, 0))
        out.paste(src.crop((0, sh - bleed_px, bleed_px, sh))
                  .transpose(Image.FLIP_LEFT_RIGHT)
                  .transpose(Image.FLIP_TOP_BOTTOM),
                  (0, bleed_px + sh))
        out.paste(src.crop((sw - bleed_px, sh - bleed_px, sw, sh))
                  .transpose(Image.FLIP_LEFT_RIGHT)
                  .transpose(Image.FLIP_TOP_BOTTOM),
                  (bleed_px + sw, bleed_px + sh))

    content_box = (bleed_px, bleed_px, bleed_px + sw, bleed_px + sh)
    actual_bleed_mm = px_to_mm(bleed_px, dpi)

    return BleedResult(
        image=out,
        bleed_px=bleed_px,
        bleed_mm=actual_bleed_mm,
        content_box=content_box,
    )


# ---------------------------------------------------------------------------
# Registration marks
# ---------------------------------------------------------------------------

@dataclass
class RegMarkResult:
    """Output of add_registration_marks."""
    image: Image.Image           # panel with registration marks drawn on it
    mark_positions: list[tuple[int, int]]   # (cx, cy) pixel centres of each mark


def add_registration_marks(
    image: Image.Image,
    mark_size_mm: float = REG_MARK_SIZE_MM,
    dpi: float = DEFAULT_DPI,
    colour: tuple[int, int, int, int] = (0, 0, 0, 255),
    n_marks: int = 4,
) -> RegMarkResult:
    """
    Draw registration crosshair marks at the corners of the panel.

    Marks are placed just *outside* the trim-box (within the bleed area if
    add_bleed was called first, or at the corners otherwise).  Each mark is
    a cross (+) with a surrounding circle.

    Parameters
    ----------
    image:        RGBA panel (should already have bleed applied)
    mark_size_mm: diameter of the registration circle in mm
    dpi:          raster resolution
    colour:       RGBA fill colour for the marks (default: opaque black)
    n_marks:      number of marks; 4 = one per corner (only 4 supported)

    Returns
    -------
    RegMarkResult with a copy of the image with marks drawn.
    """
    if n_marks != 4:
        raise ValueError("Only n_marks=4 (one per corner) is supported")

    mark_px = mm_to_px(mark_size_mm, dpi)
    half = mark_px // 2
    thickness = max(1, mark_px // 8)

    out = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size

    # Corner centres: inset by half mark size
    offset = half + 2
    corners = [
        (offset, offset),
        (w - offset, offset),
        (offset, h - offset),
        (w - offset, h - offset),
    ]

    for cx, cy in corners:
        # Circle
        bbox = [cx - half, cy - half, cx + half, cy + half]
        draw.ellipse(bbox, outline=colour, width=thickness)
        # Horizontal bar
        draw.line([(cx - half, cy), (cx + half, cy)], fill=colour, width=thickness)
        # Vertical bar
        draw.line([(cx, cy - half), (cx, cy + half)], fill=colour, width=thickness)

    return RegMarkResult(image=out, mark_positions=corners)


# ---------------------------------------------------------------------------
# Convenience: full dye-sub render pipeline
# ---------------------------------------------------------------------------

@dataclass
class SubliResult:
    """
    Complete output of the dye-sublimation pipeline for one panel.

    Attributes
    ----------
    panel:          cylinder panel geometry
    projected:      artwork projected onto panel (no bleed)
    bleed:          BleedResult (panel + bleed margin)
    final:          RegMarkResult (bleed + registration marks) — the print-ready image
    dpi:            raster resolution
    bleed_mm:       actual bleed margin in mm
    area_ratio:     flat_area / cylinder_area (should be ≈ 1.0 for area preservation)
    """
    panel: CylinderPanel
    projected: Image.Image
    bleed: BleedResult
    final: RegMarkResult
    dpi: float
    bleed_mm: float
    area_ratio: float


def render_panel_png(
    radius_mm: float,
    height_mm: float,
    artwork: Image.Image,
    bleed_mm: float = DEFAULT_BLEED_MM,
    dpi: float = DEFAULT_DPI,
) -> SubliResult:
    """
    Full dye-sublimation pipeline for a cylindrical garment panel.

    Steps
    -----
    1. Unwrap cylinder → flat panel geometry
    2. Project artwork onto panel (resize to fit)
    3. Add bleed margin (mirror-edge fill)
    4. Add registration marks at corners

    Parameters
    ----------
    radius_mm:   cylinder radius in mm
    height_mm:   cylinder height in mm
    artwork:     source artwork PIL Image (any mode; converted to RGBA internally)
    bleed_mm:    bleed margin in mm (default: 3 mm)
    dpi:         raster resolution (default: 150 dpi)

    Returns
    -------
    SubliResult containing all intermediate and final images.
    """
    panel = unwrap_cylinder(radius_mm, height_mm, dpi=dpi)

    projected = project_artwork(panel, artwork)

    bleed_result = add_bleed(projected, bleed_mm=bleed_mm, dpi=dpi)

    reg_result = add_registration_marks(bleed_result.image, dpi=dpi)

    # Area ratio: should be exactly 1.0 for a cylinder (flat = cylinder surface)
    flat_area = panel.width_mm * panel.height_mm
    cylinder_area = 2.0 * math.pi * radius_mm * height_mm
    area_ratio = flat_area / cylinder_area if cylinder_area > 0 else 0.0

    return SubliResult(
        panel=panel,
        projected=projected,
        bleed=bleed_result,
        final=reg_result,
        dpi=dpi,
        bleed_mm=bleed_result.bleed_mm,
        area_ratio=area_ratio,
    )
