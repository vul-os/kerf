"""
kerf_bim.family.library.plumbing
================================

Pre-populated parametric plumbing-fixture families for the BIM family
library.

Families:
    lavatory      — wash-hand basin / sink
    water_closet  — toilet (WC)
    bathtub       — bathtub
    shower        — shower enclosure / pan
    urinal        — wall-hung urinal
    water_heater  — storage water heater

All dimensions in mm (length kind).
"""
from __future__ import annotations

from kerf_bim.family.family import (
    FamilyDefinition,
    FamilyType,
    Parameter,
    make_family,
    make_type,
)

__all__ = [
    "lavatory",
    "water_closet",
    "bathtub",
    "shower",
    "urinal",
    "water_heater",
    "ALL_PLUMBING_FAMILIES",
]


lavatory: FamilyDefinition = make_family(
    name="Lavatory",
    category="PlumbingFixture",
    type_parameters=[
        Parameter("width",  "length", default=600.0, description="Basin width (mm)"),
        Parameter("depth",  "length", default=450.0, description="Basin depth (mm)"),
        Parameter("rim_height", "length", default=850.0, description="Rim height off floor (mm)"),
    ],
    instance_parameters=[
        Parameter("mount",    "string",   default="countertop", description="countertop/wall/pedestal/undermount"),
        Parameter("material", "material", default="vitreous_china", description="Bowl material id"),
    ],
    description="Wash-hand basin / lavatory sink.",
)
lavatory._library_types = [  # type: ignore[attr-defined]
    make_type(lavatory, "Compact",   {"width": 450.0, "depth": 360.0}),
    make_type(lavatory, "Standard",  {"width": 600.0, "depth": 450.0}),
    make_type(lavatory, "Vanity",    {"width": 900.0, "depth": 500.0}),
]


water_closet: FamilyDefinition = make_family(
    name="Water Closet",
    category="PlumbingFixture",
    type_parameters=[
        Parameter("width",  "length", default=370.0, description="Bowl width (mm)"),
        Parameter("length", "length", default=700.0, description="Front-to-wall projection (mm)"),
        Parameter("seat_height", "length", default=400.0, description="Seat height (mm)"),
    ],
    instance_parameters=[
        Parameter("mount",      "string",  default="floor", description="floor/wall-hung"),
        Parameter("flush_litres", "float", default=4.8,    description="Full-flush volume (L)"),
    ],
    description="Toilet / water closet.",
)
water_closet._library_types = [  # type: ignore[attr-defined]
    make_type(water_closet, "Close-coupled", {"length": 700.0, "seat_height": 400.0}),
    make_type(water_closet, "Wall-hung",     {"length": 540.0, "seat_height": 420.0}),
    make_type(water_closet, "ADA",           {"length": 720.0, "seat_height": 480.0}),
]


bathtub: FamilyDefinition = make_family(
    name="Bathtub",
    category="PlumbingFixture",
    type_parameters=[
        Parameter("length", "length", default=1700.0, description="Tub length (mm)"),
        Parameter("width",  "length", default=750.0,  description="Tub width (mm)"),
        Parameter("depth",  "length", default=560.0,  description="Tub depth (mm)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="acrylic", description="Tub material id"),
        Parameter("style",    "string",   default="alcove",  description="alcove/freestanding/drop-in"),
    ],
    description="Bathtub.",
)
bathtub._library_types = [  # type: ignore[attr-defined]
    make_type(bathtub, "1500", {"length": 1500.0}),
    make_type(bathtub, "1700", {"length": 1700.0}),
    make_type(bathtub, "1800 freestanding", {"length": 1800.0, "width": 850.0}),
]


shower: FamilyDefinition = make_family(
    name="Shower",
    category="PlumbingFixture",
    type_parameters=[
        Parameter("width",  "length", default=900.0,  description="Enclosure width (mm)"),
        Parameter("depth",  "length", default=900.0,  description="Enclosure depth (mm)"),
        Parameter("height", "length", default=2000.0, description="Enclosure height (mm)"),
    ],
    instance_parameters=[
        Parameter("pan_material", "material", default="acrylic", description="Pan material id"),
        Parameter("door_type",    "string",   default="hinged",  description="hinged/sliding/none"),
    ],
    description="Shower enclosure / pan.",
)
shower._library_types = [  # type: ignore[attr-defined]
    make_type(shower, "800 × 800",   {"width": 800.0,  "depth": 800.0}),
    make_type(shower, "900 × 900",   {"width": 900.0,  "depth": 900.0}),
    make_type(shower, "1200 × 900",  {"width": 1200.0, "depth": 900.0}),
]


urinal: FamilyDefinition = make_family(
    name="Urinal",
    category="PlumbingFixture",
    type_parameters=[
        Parameter("width",  "length", default=380.0, description="Urinal width (mm)"),
        Parameter("rim_height", "length", default=610.0, description="Rim height off floor (mm)"),
    ],
    instance_parameters=[
        Parameter("flush_litres", "float",  default=1.9,   description="Flush volume (L); 0 = waterless"),
        Parameter("material",     "material", default="vitreous_china", description="Bowl material id"),
    ],
    description="Wall-hung urinal.",
)
urinal._library_types = [  # type: ignore[attr-defined]
    make_type(urinal, "Standard",  {"rim_height": 610.0}),
    make_type(urinal, "ADA",       {"rim_height": 430.0}),
    make_type(urinal, "Waterless", {"rim_height": 610.0}),
]


water_heater: FamilyDefinition = make_family(
    name="Water Heater",
    category="PlumbingEquipment",
    type_parameters=[
        Parameter("capacity_litres", "float", default=190.0, description="Storage capacity (L)"),
        Parameter("diameter",        "length", default=560.0, description="Tank diameter (mm)"),
        Parameter("height",          "length", default=1470.0, description="Tank height (mm)"),
    ],
    instance_parameters=[
        Parameter("fuel", "string", default="electric", description="electric/gas/heat_pump"),
    ],
    description="Storage water heater.",
)
water_heater._library_types = [  # type: ignore[attr-defined]
    make_type(water_heater, "120 L", {"capacity_litres": 120.0, "height": 1100.0}),
    make_type(water_heater, "190 L", {"capacity_litres": 190.0, "height": 1470.0}),
    make_type(water_heater, "300 L", {"capacity_litres": 300.0, "height": 1800.0}),
]


ALL_PLUMBING_FAMILIES: list[FamilyDefinition] = [
    lavatory,
    water_closet,
    bathtub,
    shower,
    urinal,
    water_heater,
]
