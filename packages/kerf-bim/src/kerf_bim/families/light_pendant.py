"""
kerf_bim.families.light_pendant
==================================

Parametric suspended pendant luminaire.

Parameters
----------
bulb_diameter : number (mm)
    Diameter of the bulb or light source. Default 80 mm.
drop_height : number (mm)
    Suspension cable / rod length from ceiling. Default 1000 mm.
shade_diameter : number (mm)
    Outer diameter of the shade. Default 300 mm.

Derived formulas
----------------
shade_radius      shade_diameter / 2
bottom_clearance  drop_height + shade_diameter * 0.5
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Pendant Light",
    category="fixture",
    description=(
        "Suspended pendant luminaire with configurable shade and drop height."
    ),
    parameters=[
        FamilyParameter(
            name="bulb_diameter",
            type="number",
            default=80.0,
            min=30.0,
            max=200.0,
            units="mm",
            description="Bulb / light-source diameter",
        ),
        FamilyParameter(
            name="drop_height",
            type="number",
            default=1000.0,
            min=200.0,
            max=3000.0,
            units="mm",
            description="Suspension drop from ceiling",
        ),
        FamilyParameter(
            name="shade_diameter",
            type="number",
            default=300.0,
            min=100.0,
            max=800.0,
            units="mm",
            description="Shade outer diameter",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="shade_radius",
            expression="shade_diameter / 2",
        ),
        FamilyFormula(
            name="bottom_clearance",
            expression="drop_height + shade_diameter * 0.5",
        ),
    ],
    geometry_script="""
result = {
    "family": "Pendant Light",
    "category": "fixture",
    "shade": {
        "diameter_mm": shade_diameter,
        "radius_mm": shade_radius,
    },
    "suspension": {
        "drop_mm": drop_height,
        "bottom_clearance_mm": bottom_clearance,
    },
    "bulb": {
        "diameter_mm": bulb_diameter,
    },
    "bounding_box_mm": {
        "x": shade_diameter,
        "y": shade_diameter,
        "z": bottom_clearance,
    },
}
""",
)
