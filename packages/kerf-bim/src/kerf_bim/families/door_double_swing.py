"""
kerf_bim.families.door_double_swing
=====================================

Parametric double-leaf hinged door pair.

Parameters
----------
width : number (mm)
    Total clear opening width (both leaves combined). Default 1800 mm.
height : number (mm)
    Opening height. Default 2100 mm.
frame_thickness : number (mm)
    Frame / jamb thickness. Default 70 mm.
gap : number (mm)
    Gap between the two door leaves at the meeting stile. Default 4 mm.
swing_angle : number (degrees)
    Opening angle for each leaf. Default 90.

Derived formulas
----------------
leaf_width       (width - 2 * frame_thickness - gap) / 2
panel_height     height - frame_thickness
"""
from __future__ import annotations

from kerf_bim.family_editor import FamilyDef, FamilyFormula, FamilyParameter

family_def: FamilyDef = FamilyDef(
    name="Double Swing Door",
    category="door",
    description=(
        "A pair of hinged door leaves sharing a single opening. "
        "Both leaves swing outward (or inward) symmetrically."
    ),
    parameters=[
        FamilyParameter(
            name="width",
            type="number",
            default=1800.0,
            min=1200.0,
            max=3000.0,
            units="mm",
            description="Total clear opening width",
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
            description="Frame / jamb thickness",
        ),
        FamilyParameter(
            name="gap",
            type="number",
            default=4.0,
            min=0.0,
            max=20.0,
            units="mm",
            description="Gap between the two leaves at the meeting stile",
        ),
        FamilyParameter(
            name="swing_angle",
            type="number",
            default=90.0,
            min=0.0,
            max=180.0,
            units="deg",
            description="Opening angle for each leaf",
        ),
    ],
    formulas=[
        FamilyFormula(
            name="leaf_width",
            expression="(width - 2 * frame_thickness - gap) / 2",
        ),
        FamilyFormula(
            name="panel_height",
            expression="height - frame_thickness",
        ),
    ],
    geometry_script="""
# math module is pre-bound in the execution namespace.
swing_rad = math.radians(swing_angle)

# Each leaf swings from its hinge.
# Left leaf hinge at x = frame_thickness, right at x = width - frame_thickness.
left_tip_x = frame_thickness + leaf_width * math.cos(swing_rad)
left_tip_y = leaf_width * math.sin(swing_rad)
right_tip_x = width - frame_thickness - leaf_width * math.cos(swing_rad)
right_tip_y = leaf_width * math.sin(swing_rad)

result = {
    "family": "Double Swing Door",
    "category": "door",
    "frame": {
        "width_mm": width,
        "height_mm": height,
        "frame_thickness_mm": frame_thickness,
        "gap_mm": gap,
    },
    "left_leaf": {
        "width_mm": leaf_width,
        "height_mm": panel_height,
        "swing_angle_deg": swing_angle,
        "tip_x_mm": left_tip_x,
        "tip_y_mm": left_tip_y,
    },
    "right_leaf": {
        "width_mm": leaf_width,
        "height_mm": panel_height,
        "swing_angle_deg": swing_angle,
        "tip_x_mm": right_tip_x,
        "tip_y_mm": right_tip_y,
    },
    "bounding_box_mm": {
        "x": width + 2 * leaf_width * abs(math.sin(swing_rad)),
        "y": leaf_width,
        "z": height,
    },
}
""",
)
