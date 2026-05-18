"""kerf-interior: space-planning, FF&E, and ADA/ANSI clearance plugin for Kerf."""

from kerf_interior.clearance import (
    ADAViolation,
    check_turning_radius,
    check_knee_clearance,
    check_reach_range,
    check_corridor_clearance,
    turning_circle_diameter_mm,
)
from kerf_interior.furniture import (
    FurnitureItem,
    make_chair,
    make_desk,
    make_sofa,
    make_table,
)
from kerf_interior.space_planning import (
    RoomLayout,
    CirculationPath,
    PlacedItem,
    make_room,
)

__all__ = [
    # clearance
    "ADAViolation",
    "check_turning_radius",
    "check_knee_clearance",
    "check_reach_range",
    "check_corridor_clearance",
    "turning_circle_diameter_mm",
    # furniture
    "FurnitureItem",
    "make_chair",
    "make_desk",
    "make_sofa",
    "make_table",
    # space planning
    "RoomLayout",
    "CirculationPath",
    "PlacedItem",
    "make_room",
]
