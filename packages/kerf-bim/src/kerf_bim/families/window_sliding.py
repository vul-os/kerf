"""
kerf_bim.families.window_sliding
==================================

Parametric horizontal sliding window.

Parameters
----------
width : number (mm)
    Overall frame width. Default 1200 mm.
height : number (mm)
    Overall frame height. Default 1000 mm.
slider_ratio : number
    Fraction of total width occupied by the sliding panel (0–1).
    Default 0.5 (equal halves).
frame_depth : number (mm)
    Frame depth. Default 90 mm.

Derived formulas
----------------
slider_width     width * slider_ratio
fixed_width      width * (1 - slider_ratio)
glass_area       (width * height) / 1e6   (m²)
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Sliding Window",
    category="window",
    description=(
        "Horizontal sliding window with one fixed panel and one sliding panel. "
        "slider_ratio controls the proportion of the sliding leaf."
    ),
    parameters=[
        FamilyParameter(
            name="width",
            type="number",
            default=1200.0,
            min=600.0,
            max=3000.0,
            units="mm",
            description="Overall frame width",
        ),
        FamilyParameter(
            name="height",
            type="number",
            default=1000.0,
            min=400.0,
            max=2000.0,
            units="mm",
            description="Overall frame height",
        ),
        FamilyParameter(
            name="slider_ratio",
            type="number",
            default=0.5,
            min=0.2,
            max=0.8,
            description="Fraction of width occupied by the sliding panel",
        ),
        FamilyParameter(
            name="frame_depth",
            type="number",
            default=90.0,
            min=50.0,
            max=200.0,
            units="mm",
            description="Frame depth (wall thickness)",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="slider_width",
            expression="width * slider_ratio",
        ),
        FamilyFormula(
            name="fixed_width",
            expression="width * (1 - slider_ratio)",
        ),
        FamilyFormula(
            name="glass_area",
            expression="(width * height) / 1e6",
        ),
    ],
    geometry_script="""
result = {
    "family": "Sliding Window",
    "category": "window",
    "frame": {
        "width_mm": width,
        "height_mm": height,
        "depth_mm": frame_depth,
    },
    "slider_panel": {
        "width_mm": slider_width,
        "height_mm": height,
    },
    "fixed_panel": {
        "width_mm": fixed_width,
        "height_mm": height,
    },
    "glass_area_m2": glass_area,
    "bounding_box_mm": {
        "x": width,
        "y": frame_depth,
        "z": height,
    },
}
""",
)
