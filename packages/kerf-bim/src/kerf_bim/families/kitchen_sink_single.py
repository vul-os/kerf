"""
kerf_bim.families.kitchen_sink_single
=======================================

Parametric single-bowl kitchen sink (drop-in or undermount).

Parameters
----------
width : number (mm)
    Overall sink width (cabinet cut-out). Default 600 mm.
depth : number (mm)
    Front-to-back measurement. Default 500 mm.
depth_well : number (mm)
    Bowl depth (inside dimension). Default 200 mm.

Derived formulas
----------------
bowl_width     width - 80
bowl_depth     depth - 60
bowl_volume    (bowl_width * bowl_depth * depth_well) / 1e9   (litres approx)
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Single Kitchen Sink",
    category="fixture",
    description=(
        "Single-bowl kitchen sink suitable for drop-in or undermount installation."
    ),
    parameters=[
        FamilyParameter(
            name="width",
            type="number",
            default=600.0,
            min=400.0,
            max=900.0,
            units="mm",
            description="Overall sink / cabinet cut-out width",
        ),
        FamilyParameter(
            name="depth",
            type="number",
            default=500.0,
            min=350.0,
            max=700.0,
            units="mm",
            description="Front-to-back measurement",
        ),
        FamilyParameter(
            name="depth_well",
            type="number",
            default=200.0,
            min=130.0,
            max=300.0,
            units="mm",
            description="Bowl depth (inside dimension)",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="bowl_width",
            expression="width - 80",
        ),
        FamilyFormula(
            name="bowl_depth",
            expression="depth - 60",
        ),
        FamilyFormula(
            name="bowl_volume",
            expression="(bowl_width * bowl_depth * depth_well) / 1e9",
        ),
    ],
    geometry_script="""
result = {
    "family": "Single Kitchen Sink",
    "category": "fixture",
    "outer": {
        "width_mm": width,
        "depth_mm": depth,
    },
    "bowl": {
        "width_mm": bowl_width,
        "depth_mm": bowl_depth,
        "well_depth_mm": depth_well,
        "volume_litres": bowl_volume * 1000,
    },
    "bounding_box_mm": {
        "x": width,
        "y": depth,
        "z": depth_well + 50,
    },
}
""",
)
