"""
kerf_bim.family.library.furniture
=================================

Pre-populated parametric furniture families for the BIM family library.

Families:
    desk          — work / office desk
    chair         — task / side chair
    table         — dining / conference table
    sofa          — multi-seat sofa
    bed           — bed frame
    storage       — cabinet / shelving unit

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
    "desk",
    "chair",
    "table",
    "sofa",
    "bed",
    "storage",
    "ALL_FURNITURE_FAMILIES",
]


desk: FamilyDefinition = make_family(
    name="Desk",
    category="Furniture",
    type_parameters=[
        Parameter("width",  "length", default=1400.0, description="Desktop width (mm)"),
        Parameter("depth",  "length", default=700.0,  description="Desktop depth (mm)"),
        Parameter("height", "length", default=740.0,  description="Work surface height (mm)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="laminate", description="Top material id"),
        Parameter("leg_style", "string",  default="panel",    description="Leg style: panel/a-frame/cantilever"),
    ],
    description="Office or work desk.",
)
desk._library_types = [  # type: ignore[attr-defined]
    make_type(desk, "1200 × 600", {"width": 1200.0, "depth": 600.0}),
    make_type(desk, "1400 × 700", {"width": 1400.0, "depth": 700.0}),
    make_type(desk, "1600 × 800", {"width": 1600.0, "depth": 800.0}),
    make_type(desk, "1800 × 800", {"width": 1800.0, "depth": 800.0}),
]


chair: FamilyDefinition = make_family(
    name="Chair",
    category="Furniture",
    type_parameters=[
        Parameter("seat_width",  "length", default=460.0, description="Seat width (mm)"),
        Parameter("seat_height", "length", default=460.0, description="Seat height off floor (mm)"),
        Parameter("back_height", "length", default=860.0, description="Top-of-back height (mm)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="fabric", description="Upholstery material id"),
        Parameter("armrests", "boolean",  default=False,    description="Has armrests"),
    ],
    description="Task or side chair.",
)
chair._library_types = [  # type: ignore[attr-defined]
    make_type(chair, "Side",  {"seat_height": 460.0, "back_height": 860.0}),
    make_type(chair, "Task",  {"seat_height": 480.0, "back_height": 980.0}),
    make_type(chair, "Stool", {"seat_height": 660.0, "back_height": 760.0}),
]


table: FamilyDefinition = make_family(
    name="Table",
    category="Furniture",
    type_parameters=[
        Parameter("length", "length",  default=1800.0, description="Tabletop length (mm)"),
        Parameter("width",  "length",  default=900.0,  description="Tabletop width (mm)"),
        Parameter("height", "length",  default=740.0,  description="Tabletop height (mm)"),
        Parameter("seats",  "integer", default=6,      description="Nominal seating capacity"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="oak", description="Top material id"),
        Parameter("shape",    "string",   default="rectangular", description="rectangular/round/oval"),
    ],
    description="Dining or conference table.",
)
table._library_types = [  # type: ignore[attr-defined]
    make_type(table, "4-seat",  {"length": 1200.0, "width": 800.0,  "seats": 4}),
    make_type(table, "6-seat",  {"length": 1800.0, "width": 900.0,  "seats": 6}),
    make_type(table, "8-seat",  {"length": 2400.0, "width": 1000.0, "seats": 8}),
    make_type(table, "12-seat", {"length": 3600.0, "width": 1200.0, "seats": 12}),
]


sofa: FamilyDefinition = make_family(
    name="Sofa",
    category="Furniture",
    type_parameters=[
        Parameter("length", "length",  default=2000.0, description="Overall length (mm)"),
        Parameter("depth",  "length",  default=900.0,  description="Overall depth (mm)"),
        Parameter("height", "length",  default=850.0,  description="Back height (mm)"),
        Parameter("seats",  "integer", default=3,      description="Seat count"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="fabric", description="Upholstery material id"),
    ],
    description="Multi-seat sofa.",
)
sofa._library_types = [  # type: ignore[attr-defined]
    make_type(sofa, "2-seat", {"length": 1600.0, "seats": 2}),
    make_type(sofa, "3-seat", {"length": 2000.0, "seats": 3}),
    make_type(sofa, "4-seat", {"length": 2600.0, "seats": 4}),
]


bed: FamilyDefinition = make_family(
    name="Bed",
    category="Furniture",
    type_parameters=[
        Parameter("mattress_width",  "length", default=1530.0, description="Mattress width (mm)"),
        Parameter("mattress_length", "length", default=2030.0, description="Mattress length (mm)"),
        Parameter("frame_height",    "length", default=400.0,  description="Frame height (mm)"),
    ],
    instance_parameters=[
        Parameter("material",  "material", default="wood", description="Frame material id"),
        Parameter("headboard", "boolean",  default=True,   description="Has headboard"),
    ],
    description="Bed frame.",
)
bed._library_types = [  # type: ignore[attr-defined]
    make_type(bed, "Twin",  {"mattress_width": 990.0,  "mattress_length": 1900.0}),
    make_type(bed, "Full",  {"mattress_width": 1370.0, "mattress_length": 1900.0}),
    make_type(bed, "Queen", {"mattress_width": 1530.0, "mattress_length": 2030.0}),
    make_type(bed, "King",  {"mattress_width": 1930.0, "mattress_length": 2030.0}),
]


storage: FamilyDefinition = make_family(
    name="Storage Unit",
    category="Furniture",
    type_parameters=[
        Parameter("width",  "length",  default=900.0,  description="Unit width (mm)"),
        Parameter("depth",  "length",  default=450.0,  description="Unit depth (mm)"),
        Parameter("height", "length",  default=1800.0, description="Unit height (mm)"),
        Parameter("shelves", "integer", default=4,     description="Shelf count"),
        Parameter("doors",   "boolean", default=False, description="Has doors (type-defining)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="melamine", description="Carcass material id"),
    ],
    description="Cabinet or shelving storage unit.",
)
storage._library_types = [  # type: ignore[attr-defined]
    make_type(storage, "Bookcase 3-shelf", {"height": 1200.0, "shelves": 3, "doors": False}),
    make_type(storage, "Bookcase 5-shelf", {"height": 1800.0, "shelves": 5, "doors": False}),
    make_type(storage, "Base cabinet",     {"height": 900.0,  "shelves": 2, "doors": True}),
    make_type(storage, "Tall cabinet",     {"height": 2100.0, "shelves": 6, "doors": True}),
]


ALL_FURNITURE_FAMILIES: list[FamilyDefinition] = [
    desk,
    chair,
    table,
    sofa,
    bed,
    storage,
]
