"""
kerf_bim.family.library.lighting
================================

Pre-populated parametric lighting-fixture families for the BIM family
library.

Families:
    recessed_downlight — recessed can / downlight
    pendant            — suspended pendant luminaire
    surface_mount      — ceiling surface-mount fixture
    track              — track lighting run
    wall_sconce        — wall-mounted sconce
    troffer            — recessed troffer (grid ceiling)

Dimensions in mm; power in W; flux in lm.
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
    "recessed_downlight",
    "pendant",
    "surface_mount",
    "track",
    "wall_sconce",
    "troffer",
    "ALL_LIGHTING_FAMILIES",
]


recessed_downlight: FamilyDefinition = make_family(
    name="Recessed Downlight",
    category="LightingFixture",
    type_parameters=[
        Parameter("aperture",  "length", default=150.0, description="Aperture diameter (mm)"),
        Parameter("power_w",   "float", default=12.0,  description="Rated power (W)"),
        Parameter("flux_lm",   "float", default=900.0, description="Luminous flux (lm)"),
        Parameter("cct_k",     "integer", default=3000, description="Correlated colour temperature (K)"),
    ],
    instance_parameters=[
        Parameter("dimmable", "boolean", default=True, description="Dimmable driver"),
        Parameter("ip_rating", "string", default="IP20", description="Ingress protection rating"),
    ],
    description="Recessed ceiling downlight.",
)
recessed_downlight._library_types = [  # type: ignore[attr-defined]
    make_type(recessed_downlight, "75 mm 8 W",  {"aperture": 75.0,  "power_w": 8.0,  "flux_lm": 650.0}),
    make_type(recessed_downlight, "150 mm 12 W", {"aperture": 150.0, "power_w": 12.0, "flux_lm": 900.0}),
    make_type(recessed_downlight, "200 mm 18 W", {"aperture": 200.0, "power_w": 18.0, "flux_lm": 1500.0}),
]


pendant: FamilyDefinition = make_family(
    name="Pendant",
    category="LightingFixture",
    type_parameters=[
        Parameter("diameter",   "length", default=300.0,  description="Shade diameter (mm)"),
        Parameter("drop",       "length", default=1000.0, description="Suspension drop (mm)"),
        Parameter("power_w",    "float", default=15.0,   description="Rated power (W)"),
    ],
    instance_parameters=[
        Parameter("material", "material", default="aluminum", description="Shade material id"),
    ],
    description="Suspended pendant luminaire.",
)
pendant._library_types = [  # type: ignore[attr-defined]
    make_type(pendant, "Small",  {"diameter": 200.0, "power_w": 9.0}),
    make_type(pendant, "Medium", {"diameter": 300.0, "power_w": 15.0}),
    make_type(pendant, "Large",  {"diameter": 500.0, "power_w": 25.0}),
]


surface_mount: FamilyDefinition = make_family(
    name="Surface Mount",
    category="LightingFixture",
    type_parameters=[
        Parameter("diameter", "length", default=350.0,  description="Fixture diameter (mm)"),
        Parameter("power_w",  "float", default=22.0,   description="Rated power (W)"),
        Parameter("flux_lm",  "float", default=1800.0, description="Luminous flux (lm)"),
    ],
    instance_parameters=[
        Parameter("shape", "string", default="round", description="round/square"),
    ],
    description="Ceiling surface-mount fixture.",
)
surface_mount._library_types = [  # type: ignore[attr-defined]
    make_type(surface_mount, "300 mm", {"diameter": 300.0, "power_w": 18.0}),
    make_type(surface_mount, "400 mm", {"diameter": 400.0, "power_w": 28.0}),
]


track: FamilyDefinition = make_family(
    name="Track Lighting",
    category="LightingFixture",
    type_parameters=[
        Parameter("length",   "length",  default=2000.0, description="Track length (mm)"),
        Parameter("heads",    "integer", default=4,      description="Number of track heads"),
        Parameter("power_w",  "float",  default=48.0,   description="Total rated power (W)"),
    ],
    instance_parameters=[
        Parameter("voltage", "string", default="line", description="line/low_voltage"),
    ],
    description="Track lighting run with adjustable heads.",
)
track._library_types = [  # type: ignore[attr-defined]
    make_type(track, "1 m 3-head", {"length": 1000.0, "heads": 3, "power_w": 36.0}),
    make_type(track, "2 m 4-head", {"length": 2000.0, "heads": 4, "power_w": 48.0}),
    make_type(track, "3 m 6-head", {"length": 3000.0, "heads": 6, "power_w": 72.0}),
]


wall_sconce: FamilyDefinition = make_family(
    name="Wall Sconce",
    category="LightingFixture",
    type_parameters=[
        Parameter("width",   "length", default=120.0, description="Fixture width (mm)"),
        Parameter("height",  "length", default=250.0, description="Fixture height (mm)"),
        Parameter("power_w", "float", default=10.0,  description="Rated power (W)"),
    ],
    instance_parameters=[
        Parameter("mount_height", "length", default=1800.0, description="Mounting height off floor (mm)"),
    ],
    description="Wall-mounted sconce.",
)
wall_sconce._library_types = [  # type: ignore[attr-defined]
    make_type(wall_sconce, "Up/Down", {"height": 250.0, "power_w": 10.0}),
    make_type(wall_sconce, "Reading", {"height": 300.0, "power_w": 7.0}),
]


troffer: FamilyDefinition = make_family(
    name="Troffer",
    category="LightingFixture",
    type_parameters=[
        Parameter("module_x", "length", default=600.0,  description="Module size X (mm)"),
        Parameter("module_y", "length", default=600.0,  description="Module size Y (mm)"),
        Parameter("power_w",  "float", default=36.0,   description="Rated power (W)"),
        Parameter("flux_lm",  "float", default=3600.0, description="Luminous flux (lm)"),
    ],
    instance_parameters=[
        Parameter("ceiling_grid", "string", default="600x600", description="Grid module the troffer drops into"),
    ],
    description="Recessed troffer for grid ceilings.",
)
troffer._library_types = [  # type: ignore[attr-defined]
    make_type(troffer, "600 × 600 36 W",  {"module_x": 600.0,  "module_y": 600.0,  "power_w": 36.0}),
    make_type(troffer, "1200 × 300 40 W", {"module_x": 1200.0, "module_y": 300.0, "power_w": 40.0}),
    make_type(troffer, "1200 × 600 50 W", {"module_x": 1200.0, "module_y": 600.0, "power_w": 50.0}),
]


ALL_LIGHTING_FAMILIES: list[FamilyDefinition] = [
    recessed_downlight,
    pendant,
    surface_mount,
    track,
    wall_sconce,
    troffer,
]
