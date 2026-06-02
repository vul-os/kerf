"""
kerf_bim.families.toilet_standard
====================================

Parametric close-coupled toilet / WC.

Parameters
----------
bowl_width : number (mm)
    Bowl / seat width. Default 370 mm.
tank_height : number (mm)
    Tank height above bowl rim. Default 350 mm.
ada_compliant : boolean
    ADA / accessible seat height (480 mm vs 400 mm). Default False.

Derived formulas
----------------
seat_height    480 if ada_compliant else 400
total_height   seat_height + tank_height
projection     bowl_width * 1.8
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Standard Toilet",
    category="fixture",
    description=(
        "Close-coupled toilet / WC. "
        "Toggle ada_compliant to switch between standard (400 mm) "
        "and ADA-accessible (480 mm) seat height."
    ),
    parameters=[
        FamilyParameter(
            name="bowl_width",
            type="number",
            default=370.0,
            min=300.0,
            max=500.0,
            units="mm",
            description="Bowl / seat width",
        ),
        FamilyParameter(
            name="tank_height",
            type="number",
            default=350.0,
            min=200.0,
            max=500.0,
            units="mm",
            description="Tank height above bowl rim",
        ),
        FamilyParameter(
            name="ada_compliant",
            type="boolean",
            default=False,
            description="Use ADA-accessible seat height (480 mm instead of 400 mm)",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="seat_height",
            expression="480 if ada_compliant else 400",
        ),
        FamilyFormula(
            name="total_height",
            expression="seat_height + tank_height",
        ),
        FamilyFormula(
            name="projection",
            expression="bowl_width * 1.8",
        ),
    ],
    geometry_script="""
result = {
    "family": "Standard Toilet",
    "category": "fixture",
    "bowl": {
        "width_mm": bowl_width,
        "seat_height_mm": seat_height,
        "projection_mm": projection,
    },
    "tank": {
        "height_mm": tank_height,
        "top_height_mm": total_height,
    },
    "ada_compliant": ada_compliant,
    "bounding_box_mm": {
        "x": bowl_width,
        "y": projection,
        "z": total_height,
    },
}
""",
)
