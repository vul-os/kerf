"""
kerf_bim.family.library.structural
==================================

Pre-populated parametric structural-member families for the BIM family
library.

Families:
    steel_column     — wide-flange / HSS steel column
    steel_beam       — wide-flange steel beam
    concrete_column  — reinforced-concrete column
    concrete_beam    — reinforced-concrete beam
    footing          — spread / pad footing
    brace            — diagonal brace member

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
    "steel_column",
    "steel_beam",
    "concrete_column",
    "concrete_beam",
    "footing",
    "brace",
    "ALL_STRUCTURAL_FAMILIES",
]


steel_column: FamilyDefinition = make_family(
    name="Steel Column",
    category="StructuralColumn",
    type_parameters=[
        Parameter("section",  "string", default="W250x73", description="Designation"),
        Parameter("depth",    "length", default=253.0,      description="Section depth (mm)"),
        Parameter("flange_width", "length", default=254.0,  description="Flange width (mm)"),
        Parameter("height",   "length", default=3600.0,     description="Unbraced height (mm)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="steel_s355", description="Steel grade id"),
        Parameter("base_plate", "boolean", default=True,        description="Has base plate"),
    ],
    description="Wide-flange or HSS steel column.",
)
steel_column._library_types = [  # type: ignore[attr-defined]
    make_type(steel_column, "W150x30", {"section": "W150x30", "depth": 157.0, "flange_width": 153.0}),
    make_type(steel_column, "W250x73", {"section": "W250x73", "depth": 253.0, "flange_width": 254.0}),
    make_type(steel_column, "W360x134", {"section": "W360x134", "depth": 356.0, "flange_width": 369.0}),
]


steel_beam: FamilyDefinition = make_family(
    name="Steel Beam",
    category="StructuralFraming",
    type_parameters=[
        Parameter("section", "string", default="W360x51", description="Designation"),
        Parameter("depth",   "length", default=355.0,      description="Section depth (mm)"),
        Parameter("span",    "length", default=7200.0,     description="Clear span (mm)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="steel_s355", description="Steel grade id"),
        Parameter("camber",   "length",   default=0.0,          description="Fabricated camber (mm)"),
    ],
    description="Wide-flange steel beam.",
)
steel_beam._library_types = [  # type: ignore[attr-defined]
    make_type(steel_beam, "W200x27", {"section": "W200x27", "depth": 207.0}),
    make_type(steel_beam, "W360x51", {"section": "W360x51", "depth": 355.0}),
    make_type(steel_beam, "W530x82", {"section": "W530x82", "depth": 528.0}),
]


concrete_column: FamilyDefinition = make_family(
    name="Concrete Column",
    category="StructuralColumn",
    type_parameters=[
        Parameter("width",  "length", default=400.0,  description="Section width (mm)"),
        Parameter("depth",  "length", default=400.0,  description="Section depth (mm)"),
        Parameter("height", "length", default=3600.0, description="Storey height (mm)"),
    ],
    instance_parameters=[
        Parameter("concrete_grade", "string", default="C30/37", description="Concrete grade"),
        Parameter("rebar",          "string", default="8T20",    description="Main bar arrangement"),
    ],
    description="Reinforced-concrete column.",
)
concrete_column._library_types = [  # type: ignore[attr-defined]
    make_type(concrete_column, "300 sq",  {"width": 300.0, "depth": 300.0}),
    make_type(concrete_column, "400 sq",  {"width": 400.0, "depth": 400.0}),
    make_type(concrete_column, "600 sq",  {"width": 600.0, "depth": 600.0}),
    make_type(concrete_column, "400×600", {"width": 400.0, "depth": 600.0}),
]


concrete_beam: FamilyDefinition = make_family(
    name="Concrete Beam",
    category="StructuralFraming",
    type_parameters=[
        Parameter("width",  "length", default=300.0,  description="Beam width (mm)"),
        Parameter("depth",  "length", default=600.0,  description="Beam depth (mm)"),
        Parameter("span",   "length", default=6000.0, description="Clear span (mm)"),
    ],
    instance_parameters=[
        Parameter("concrete_grade", "string", default="C30/37", description="Concrete grade"),
        Parameter("rebar",          "string", default="4T25",   description="Bottom bar arrangement"),
    ],
    description="Reinforced-concrete beam.",
)
concrete_beam._library_types = [  # type: ignore[attr-defined]
    make_type(concrete_beam, "300×500", {"width": 300.0, "depth": 500.0}),
    make_type(concrete_beam, "300×600", {"width": 300.0, "depth": 600.0}),
    make_type(concrete_beam, "400×800", {"width": 400.0, "depth": 800.0}),
]


footing: FamilyDefinition = make_family(
    name="Footing",
    category="StructuralFoundation",
    type_parameters=[
        Parameter("length",    "length", default=1500.0, description="Footing length (mm)"),
        Parameter("width",     "length", default=1500.0, description="Footing width (mm)"),
        Parameter("thickness", "length", default=400.0,  description="Footing thickness (mm)"),
    ],
    instance_parameters=[
        Parameter("concrete_grade", "string", default="C25/30", description="Concrete grade"),
        Parameter("type",           "string", default="pad",    description="pad/strip/raft"),
    ],
    description="Spread / pad footing.",
)
footing._library_types = [  # type: ignore[attr-defined]
    make_type(footing, "1000 sq", {"length": 1000.0, "width": 1000.0, "thickness": 300.0}),
    make_type(footing, "1500 sq", {"length": 1500.0, "width": 1500.0, "thickness": 400.0}),
    make_type(footing, "2500 sq", {"length": 2500.0, "width": 2500.0, "thickness": 600.0}),
]


brace: FamilyDefinition = make_family(
    name="Brace",
    category="StructuralFraming",
    type_parameters=[
        Parameter("section", "string", default="HSS127x127x6.4", description="Designation"),
        Parameter("length",  "length", default=4200.0,           description="Work-point length (mm)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="steel_s355", description="Steel grade id"),
        Parameter("config",   "string",   default="diagonal",   description="diagonal/chevron/X"),
    ],
    description="Diagonal lateral brace member.",
)
brace._library_types = [  # type: ignore[attr-defined]
    make_type(brace, "HSS89x89x6.4",   {"section": "HSS89x89x6.4"}),
    make_type(brace, "HSS127x127x6.4", {"section": "HSS127x127x6.4"}),
    make_type(brace, "HSS152x152x8.0", {"section": "HSS152x152x8.0"}),
]


ALL_STRUCTURAL_FAMILIES: list[FamilyDefinition] = [
    steel_column,
    steel_beam,
    concrete_column,
    concrete_beam,
    footing,
    brace,
]
