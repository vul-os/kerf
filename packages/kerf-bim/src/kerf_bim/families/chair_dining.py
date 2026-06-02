"""
kerf_bim.families.chair_dining
================================

Parametric dining / side chair.

Parameters
----------
seat_width : number (mm)
    Seat width. Default 460 mm.
seat_height : number (mm)
    Seat height above floor. Default 460 mm.
back_height : number (mm)
    Top of back above floor. Default 900 mm.

Derived formulas
----------------
back_net_height   back_height - seat_height
seat_depth        seat_width * 0.9
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Dining Chair",
    category="furniture",
    description=(
        "Dining or side chair with configurable seat dimensions and back height."
    ),
    parameters=[
        FamilyParameter(
            name="seat_width",
            type="number",
            default=460.0,
            min=350.0,
            max=600.0,
            units="mm",
            description="Seat width",
        ),
        FamilyParameter(
            name="seat_height",
            type="number",
            default=460.0,
            min=380.0,
            max=550.0,
            units="mm",
            description="Seat height above floor",
        ),
        FamilyParameter(
            name="back_height",
            type="number",
            default=900.0,
            min=600.0,
            max=1200.0,
            units="mm",
            description="Top of back above floor",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="back_net_height",
            expression="back_height - seat_height",
        ),
        FamilyFormula(
            name="seat_depth",
            expression="seat_width * 0.9",
        ),
    ],
    geometry_script="""
result = {
    "family": "Dining Chair",
    "category": "furniture",
    "seat": {
        "width_mm": seat_width,
        "depth_mm": seat_depth,
        "height_mm": seat_height,
    },
    "back": {
        "net_height_mm": back_net_height,
        "total_height_mm": back_height,
    },
    "bounding_box_mm": {
        "x": seat_width,
        "y": seat_depth,
        "z": back_height,
    },
}
""",
)
