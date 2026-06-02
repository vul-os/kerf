"""
kerf_bim.families.cabinet_base
================================

Parametric base cabinet (kitchen or bathroom).

Parameters
----------
width : number (mm)
    Cabinet width. Default 600 mm.
depth : number (mm)
    Cabinet depth (front to wall). Default 580 mm.
height : number (mm)
    Cabinet height (excluding countertop). Default 870 mm.
num_drawers : number
    Number of drawer fronts. Default 2.
num_shelves : number
    Number of interior shelves. Default 1.

Derived formulas
----------------
carcass_volume    (width * depth * height) / 1e9   (m³)
drawer_height     height / (num_drawers + 1)
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Base Cabinet",
    category="furniture",
    description=(
        "Floor-standing base cabinet with configurable drawers and shelves. "
        "Suitable for kitchen, bathroom or storage applications."
    ),
    parameters=[
        FamilyParameter(
            name="width",
            type="number",
            default=600.0,
            min=150.0,
            max=1200.0,
            units="mm",
            description="Cabinet width",
        ),
        FamilyParameter(
            name="depth",
            type="number",
            default=580.0,
            min=200.0,
            max=800.0,
            units="mm",
            description="Cabinet depth (front to wall)",
        ),
        FamilyParameter(
            name="height",
            type="number",
            default=870.0,
            min=400.0,
            max=1200.0,
            units="mm",
            description="Cabinet height (excluding countertop)",
        ),
        FamilyParameter(
            name="num_drawers",
            type="number",
            default=2.0,
            min=0.0,
            max=6.0,
            description="Number of drawer fronts",
        ),
        FamilyParameter(
            name="num_shelves",
            type="number",
            default=1.0,
            min=0.0,
            max=5.0,
            description="Number of interior shelves",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="carcass_volume",
            expression="(width * depth * height) / 1e9",
        ),
        FamilyFormula(
            name="drawer_height",
            expression="height / (num_drawers + 1)",
        ),
    ],
    geometry_script="""
result = {
    "family": "Base Cabinet",
    "category": "furniture",
    "dimensions": {
        "width_mm": width,
        "depth_mm": depth,
        "height_mm": height,
    },
    "drawers": {
        "count": int(num_drawers),
        "each_height_mm": drawer_height,
    },
    "shelves": {
        "count": int(num_shelves),
    },
    "carcass_volume_m3": carcass_volume,
    "bounding_box_mm": {
        "x": width,
        "y": depth,
        "z": height,
    },
}
""",
)
