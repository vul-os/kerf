"""
kerf_bim.families.window_casement
===================================

Parametric casement window (side-hinged, outward-opening).

Parameters
----------
width : number (mm)
    Rough-opening width. Default 900 mm.
height : number (mm)
    Rough-opening height. Default 1200 mm.
sill_height : number (mm)
    Height of sill above finished floor. Default 900 mm.
num_panes : choice
    Number of glazed panes: "1", "2", "3". Default "1".
frame_depth : number (mm)
    Frame / wall depth. Default 90 mm.

Derived formulas
----------------
pane_width    width / int(num_panes)
glass_area    (width * height) / 1e6   (m²)
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Casement Window",
    category="window",
    description=(
        "Side-hinged outward-opening casement window. "
        "Supports 1, 2 or 3 pane subdivisions."
    ),
    parameters=[
        FamilyParameter(
            name="width",
            type="number",
            default=900.0,
            min=400.0,
            max=2400.0,
            units="mm",
            description="Rough-opening width",
        ),
        FamilyParameter(
            name="height",
            type="number",
            default=1200.0,
            min=400.0,
            max=2400.0,
            units="mm",
            description="Rough-opening height",
        ),
        FamilyParameter(
            name="sill_height",
            type="number",
            default=900.0,
            min=0.0,
            max=2000.0,
            units="mm",
            description="Sill height above finished floor",
        ),
        FamilyParameter(
            name="num_panes",
            type="choice",
            default="1",
            choices=["1", "2", "3"],
            description="Number of glazed pane subdivisions",
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
            name="pane_width",
            expression="width / int(num_panes)",
        ),
        FamilyFormula(
            name="glass_area",
            expression="(width * height) / 1e6",
        ),
    ],
    geometry_script="""
result = {
    "family": "Casement Window",
    "category": "window",
    "rough_opening": {
        "width_mm": width,
        "height_mm": height,
        "frame_depth_mm": frame_depth,
    },
    "sill_height_mm": sill_height,
    "num_panes": int(num_panes),
    "pane_width_mm": pane_width,
    "glass_area_m2": glass_area,
    "bounding_box_mm": {
        "x": width,
        "y": frame_depth,
        "z": height,
    },
}
""",
)
