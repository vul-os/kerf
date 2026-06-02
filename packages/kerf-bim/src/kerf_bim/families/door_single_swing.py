"""
kerf_bim.families.door_single_swing
====================================

Parametric single-leaf hinged door.

Parameters
----------
width : number (mm)
    Clear opening width. Default 900 mm.
height : number (mm)
    Clear opening height. Default 2100 mm.
frame_thickness : number (mm)
    Door frame / jamb thickness. Default 70 mm.
swing_angle : number (degrees)
    Panel opening angle (0 = closed, 90 = full open). Default 90.

Derived formulas
----------------
panel_width      width - 2 * frame_thickness
panel_height     height - frame_thickness
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Single Swing Door",
    category="door",
    description=(
        "Single-leaf hinged interior or exterior door. "
        "The panel swings through swing_angle degrees from the hinge side."
    ),
    parameters=[
        FamilyParameter(
            name="width",
            type="number",
            default=900.0,
            min=600.0,
            max=1200.0,
            units="mm",
            description="Clear opening width",
        ),
        FamilyParameter(
            name="height",
            type="number",
            default=2100.0,
            min=1800.0,
            max=2700.0,
            units="mm",
            description="Clear opening height",
        ),
        FamilyParameter(
            name="frame_thickness",
            type="number",
            default=70.0,
            min=40.0,
            max=120.0,
            units="mm",
            description="Door-frame / jamb thickness",
        ),
        FamilyParameter(
            name="swing_angle",
            type="number",
            default=90.0,
            min=0.0,
            max=180.0,
            units="deg",
            description="Panel opening angle (0 = closed, 90 = full open)",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="panel_width",
            expression="width - 2 * frame_thickness",
        ),
        FamilyFormula(
            name="panel_height",
            expression="height - frame_thickness",
        ),
    ],
    geometry_script="""
# Geometry summary — bounding-box representation.
# math module is pre-bound in the execution namespace.
# A full B-rep would import kerf_cad_core and build two bodies:
#   1. The frame opening (extruded rectangular void in the host wall).
#   2. The door panel positioned at swing_angle from the hinge side.

swing_rad = math.radians(swing_angle)
panel_tip_x = panel_width * math.cos(swing_rad)
panel_tip_y = panel_width * math.sin(swing_rad)

result = {
    "family": "Single Swing Door",
    "category": "door",
    "frame": {
        "width_mm": width,
        "height_mm": height,
        "frame_thickness_mm": frame_thickness,
    },
    "panel": {
        "width_mm": panel_width,
        "height_mm": panel_height,
        "swing_angle_deg": swing_angle,
        "tip_offset_x_mm": panel_tip_x,
        "tip_offset_y_mm": panel_tip_y,
    },
    "bounding_box_mm": {
        "x": width + panel_width * abs(math.sin(swing_rad)),
        "y": panel_width,
        "z": height,
    },
}
""",
)
