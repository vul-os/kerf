"""
kerf_bim.families.desk_office
================================

Parametric office / work desk.

Parameters
----------
width : number (mm)
    Desk width. Default 1400 mm.
depth : number (mm)
    Desk depth. Default 700 mm.
height : number (mm)
    Work surface height. Default 740 mm.
with_drawer : boolean
    Include a pedestal drawer unit. Default True.

Derived formulas
----------------
top_area      (width * depth) / 1e6   (m²)
leg_height    height - 30
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Office Desk",
    category="furniture",
    description=(
        "Standard office / work desk with configurable dimensions and "
        "optional pedestal drawer unit."
    ),
    parameters=[
        FamilyParameter(
            name="width",
            type="number",
            default=1400.0,
            min=800.0,
            max=3000.0,
            units="mm",
            description="Desk width",
        ),
        FamilyParameter(
            name="depth",
            type="number",
            default=700.0,
            min=400.0,
            max=1200.0,
            units="mm",
            description="Desk depth",
        ),
        FamilyParameter(
            name="height",
            type="number",
            default=740.0,
            min=650.0,
            max=900.0,
            units="mm",
            description="Work-surface height",
        ),
        FamilyParameter(
            name="with_drawer",
            type="boolean",
            default=True,
            description="Include a pedestal drawer unit",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="top_area",
            expression="(width * depth) / 1e6",
        ),
        FamilyFormula(
            name="leg_height",
            expression="height - 30",
        ),
    ],
    geometry_script="""
result = {
    "family": "Office Desk",
    "category": "furniture",
    "top": {
        "width_mm": width,
        "depth_mm": depth,
        "area_m2": top_area,
    },
    "frame": {
        "height_mm": height,
        "leg_height_mm": leg_height,
    },
    "drawer_unit": with_drawer,
    "bounding_box_mm": {
        "x": width,
        "y": depth,
        "z": height,
    },
}
""",
)
