"""
kerf_bim.family_library_data
=============================

Curated parametric BIM family templates (T-110).

Each entry is a plain dict with keys:
    name             — unique family name
    category         — display category string
    parameters       — dict of param_name → {"type": kind, "range": [...], "default": value}
    generator_module — dotted reference to a family_authoring-compatible function

The ``CATALOG`` list is the single source of truth for the seeded library.
``FamilyTemplateEntry`` is the dataclass wrapper used by family_library.py.

Categories:
    Doors       (5): single-leaf, double-leaf, sliding, pivot, garage roll-up
    Windows     (6): casement, awning, double-hung, sliding, fixed, bay
    Walls       (6): stud 2×4, stud 2×6, CMU 8", CMU 12", brick veneer, curtain
    Stairs      (4): straight-run, L-shape, U-shape, spiral
    Furniture   (5): desk, chair, conference-table, file-cabinet, shelving
    Plumbing    (6): vanity sink, kitchen sink, toilet, urinal, shower, tub, water-heater
    HVAC        (4): VAV box, FCU, supply diffuser, return grille
    Lighting    (4): 2×4 LED panel, downlight, sconce, pendant

All length defaults are in mm.  Inch-based defaults noted in descriptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ParameterSpec",
    "FamilyTemplateEntry",
    "CATALOG",
    "CATALOG_BY_NAME",
    "CATALOG_BY_CATEGORY",
]

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterSpec:
    """Specification for a single family parameter."""

    type: str
    default: Any
    range: list | None = None          # [min, max] for numeric; None if unconstrained
    description: str = ""

    def as_dict(self) -> dict:
        d: dict = {"type": self.type, "default": self.default}
        if self.range is not None:
            d["range"] = list(self.range)
        if self.description:
            d["description"] = self.description
        return d


@dataclass
class FamilyTemplateEntry:
    """A single curated BIM family template."""

    name: str
    category: str
    parameters: dict[str, ParameterSpec]
    generator_module: str
    description: str = ""

    def param(self, name: str) -> ParameterSpec:
        """Return the ParameterSpec for *name*, raising KeyError if absent."""
        try:
            return self.parameters[name]
        except KeyError:
            raise KeyError(
                f"Family {self.name!r} has no parameter {name!r}"
            ) from None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _p(
    kind: str,
    default: Any,
    lo: float | None = None,
    hi: float | None = None,
    description: str = "",
) -> ParameterSpec:
    """Shorthand factory for a ParameterSpec."""
    rng: list | None = [lo, hi] if lo is not None and hi is not None else None
    return ParameterSpec(type=kind, default=default, range=rng, description=description)


def _entry(
    name: str,
    category: str,
    params: dict[str, ParameterSpec],
    generator: str,
    description: str = "",
) -> FamilyTemplateEntry:
    return FamilyTemplateEntry(
        name=name,
        category=category,
        parameters=params,
        generator_module=generator,
        description=description,
    )


# ---------------------------------------------------------------------------
# DOORS  (5)
# ---------------------------------------------------------------------------

_DOORS: list[FamilyTemplateEntry] = [
    _entry(
        "Single-Leaf Door",
        "Doors",
        {
            "width":           _p("length", 914.4,  508.0,  1219.2, "Clear opening width (mm); 20–48 in"),
            "height":          _p("length", 2032.0, 1828.8, 2743.2, "Clear opening height (mm); 72–108 in"),
            "panel_thickness": _p("length", 44.5,   35.0,   57.0,   "Door panel thickness (mm)"),
            "fire_rated":      _p("boolean", False,  description="Fire-rated assembly"),
        },
        "kerf_bim.authoring.doors.single_leaf",
        "Single-leaf hinged interior/exterior door.",
    ),
    _entry(
        "Double-Leaf Door",
        "Doors",
        {
            "width":           _p("length", 1828.8, 1219.2, 2438.4, "Total opening width (mm); 48–96 in"),
            "height":          _p("length", 2032.0, 1828.8, 2743.2, "Opening height (mm)"),
            "panel_thickness": _p("length", 44.5,   35.0,   57.0,   "Panel thickness (mm)"),
            "active_leaf":     _p("string",  "both", description="Active leaf(ves): left/right/both"),
        },
        "kerf_bim.authoring.doors.double_leaf",
        "Pair of hinged leaves sharing a single frame.",
    ),
    _entry(
        "Sliding Door",
        "Doors",
        {
            "width":       _p("length",  1524.0, 914.4,  3657.6, "Total opening width (mm); 36–144 in"),
            "height":      _p("length",  2032.0, 1828.8, 2743.2, "Opening height (mm)"),
            "panel_count": _p("integer", 2,      2,      4,      "Number of sliding panels"),
            "track_type":  _p("string",  "top_hung", description="top_hung or bottom_rolling"),
        },
        "kerf_bim.authoring.doors.sliding",
        "Horizontal sliding panel door on an overhead or floor track.",
    ),
    _entry(
        "Pivot Door",
        "Doors",
        {
            "width":           _p("length", 914.4,  609.6,  1828.8, "Panel width (mm); 24–72 in"),
            "height":          _p("length", 2438.4, 2032.0, 3048.0, "Panel height (mm); 80–120 in"),
            "panel_thickness": _p("length", 57.2,   44.5,   76.2,   "Panel thickness (mm)"),
            "pivot_offset":    _p("length", 101.6,  50.0,   304.8,  "Pivot point offset from hinge edge (mm)"),
        },
        "kerf_bim.authoring.doors.pivot",
        "Centre or off-centre pivot door.",
    ),
    _entry(
        "Garage Roll-Up Door",
        "Doors",
        {
            "width":         _p("length",  2438.4, 1828.8, 5486.4, "Opening width (mm); 72–216 in"),
            "height":        _p("length",  2133.6, 1828.8, 3048.0, "Opening height (mm); 72–120 in"),
            "section_count": _p("integer", 4,      3,      8,      "Number of horizontal sections"),
            "insulated":     _p("boolean", True,   description="Insulated panels"),
        },
        "kerf_bim.authoring.doors.garage_roll_up",
        "Overhead sectional / roll-up garage door.",
    ),
]


# ---------------------------------------------------------------------------
# WINDOWS  (6)
# ---------------------------------------------------------------------------

_WINDOWS: list[FamilyTemplateEntry] = [
    _entry(
        "Casement Window",
        "Windows",
        {
            "width":       _p("length",  609.6, 304.8, 1219.2, "Rough opening width (mm)"),
            "height":      _p("length", 1066.8, 457.2, 1828.8, "Rough opening height (mm)"),
            "hinge_side":  _p("string", "left",  description="left or right"),
            "glazing":     _p("string", "double", description="single/double/triple"),
            "screen":      _p("boolean", True,    description="Include insect screen"),
        },
        "kerf_bim.authoring.windows.casement",
        "Side-hinged outward-opening casement window.",
    ),
    _entry(
        "Awning Window",
        "Windows",
        {
            "width":   _p("length", 762.0, 457.2, 1524.0, "Rough opening width (mm)"),
            "height":  _p("length", 457.2, 304.8,  914.4, "Rough opening height (mm)"),
            "glazing": _p("string", "double", description="Glazing type"),
            "screen":  _p("boolean", True,    description="Include insect screen"),
        },
        "kerf_bim.authoring.windows.awning",
        "Top-hinged awning window, outswing.",
    ),
    _entry(
        "Double-Hung Window",
        "Windows",
        {
            "width":          _p("length",  762.0, 457.2, 1524.0, "Rough opening width (mm)"),
            "height":         _p("length", 1066.8, 609.6, 1828.8, "Rough opening height (mm)"),
            "glazing":        _p("string",  "double", description="Glazing type"),
            "tilt_in":        _p("boolean", True,     description="Tilt-in sashes for cleaning"),
            "grille_pattern": _p("string",  "none",   description="none/colonial/prairie"),
        },
        "kerf_bim.authoring.windows.double_hung",
        "Double hung window with both sashes operable.",
    ),
    _entry(
        "Sliding Window",
        "Windows",
        {
            "width":       _p("length",  1219.2, 609.6, 2438.4, "Rough opening width (mm)"),
            "height":      _p("length",   914.4, 457.2, 1524.0, "Rough opening height (mm)"),
            "panel_count": _p("integer",  2,     2,     3,      "Number of sash panels"),
            "glazing":     _p("string",   "double", description="Glazing type"),
        },
        "kerf_bim.authoring.windows.sliding",
        "Horizontal sliding sash window.",
    ),
    _entry(
        "Fixed Window",
        "Windows",
        {
            "width":   _p("length", 1219.2, 304.8, 3657.6, "Rough opening width (mm)"),
            "height":  _p("length", 1524.0, 304.8, 3048.0, "Rough opening height (mm)"),
            "glazing": _p("string", "double", description="Glazing type"),
            "shape":   _p("string", "rectangular", description="rectangular/arched/circular"),
        },
        "kerf_bim.authoring.windows.fixed",
        "Non-operable fixed-light window.",
    ),
    _entry(
        "Bay Window",
        "Windows",
        {
            "total_width":  _p("length", 1828.8, 1219.2, 3657.6, "Total projection width (mm)"),
            "height":       _p("length", 1219.2,  609.6, 2133.6, "Window height (mm)"),
            "depth":        _p("length",  457.2,  304.8,  914.4, "Projection depth (mm)"),
            "center_width": _p("length",  914.4,  457.2, 1828.8, "Center-panel width (mm)"),
            "glazing":      _p("string",  "double", description="Glazing type"),
        },
        "kerf_bim.authoring.windows.bay",
        "Three-panel angled bay projection window.",
    ),
]


# ---------------------------------------------------------------------------
# WALLS  (6)
# ---------------------------------------------------------------------------

_WALLS: list[FamilyTemplateEntry] = [
    _entry(
        "Stud Wall 2×4",
        "Walls",
        {
            "stud_depth":     _p("length",  88.9,  88.9,  88.9,   "Nominal stud depth (mm) — 3½ in"),
            "stud_width":     _p("length",  38.1,  38.1,  38.1,   "Nominal stud width (mm) — 1½ in"),
            "total_thickness":_p("length", 114.3, 114.3, 114.3,   "Wall assembly thickness (mm)"),
            "stud_spacing":   _p("length", 406.4, 304.8, 609.6,   "On-center stud spacing (mm); 12–24 in"),
            "sheathing":      _p("boolean", True,  description="Exterior sheathing panel"),
        },
        "kerf_bim.authoring.walls.stud_wall",
        "2×4 wood-stud framed wall (3½ in studs).",
    ),
    _entry(
        "Stud Wall 2×6",
        "Walls",
        {
            "stud_depth":      _p("length",  139.7, 139.7, 139.7, "Nominal stud depth (mm) — 5½ in"),
            "stud_width":      _p("length",   38.1,  38.1,  38.1, "Nominal stud width (mm) — 1½ in"),
            "total_thickness": _p("length",  165.1, 165.1, 165.1, "Wall assembly thickness (mm)"),
            "stud_spacing":    _p("length",  406.4, 406.4, 609.6, "On-center stud spacing (mm)"),
            "sheathing":       _p("boolean", True,  description="Exterior sheathing panel"),
        },
        "kerf_bim.authoring.walls.stud_wall",
        "2×6 wood-stud framed wall (5½ in studs) for extra insulation.",
    ),
    _entry(
        'CMU Wall 8"',
        "Walls",
        {
            "nominal_width":   _p("length", 203.2, 203.2, 203.2, "Nominal block width (mm) — 8 in"),
            "block_height":    _p("length", 193.7, 193.7, 193.7, "CMU unit height (mm)"),
            "block_length":    _p("length", 396.0, 396.0, 396.0, "CMU unit length (mm)"),
            "grouted":         _p("boolean", False, description="Fully grouted cores"),
            "reinforced":      _p("boolean", False, description="Vertical rebar in cores"),
        },
        "kerf_bim.authoring.walls.cmu_wall",
        '8-inch concrete masonry unit (CMU) wall.',
    ),
    _entry(
        'CMU Wall 12"',
        "Walls",
        {
            "nominal_width":   _p("length", 304.8, 304.8, 304.8, "Nominal block width (mm) — 12 in"),
            "block_height":    _p("length", 193.7, 193.7, 193.7, "CMU unit height (mm)"),
            "block_length":    _p("length", 396.0, 396.0, 396.0, "CMU unit length (mm)"),
            "grouted":         _p("boolean", True,  description="Fully grouted cores"),
            "reinforced":      _p("boolean", True,  description="Vertical rebar in cores"),
        },
        "kerf_bim.authoring.walls.cmu_wall",
        '12-inch CMU wall for load-bearing applications.',
    ),
    _entry(
        "Brick Veneer Wall",
        "Walls",
        {
            "brick_thickness":   _p("length",  92.0,  92.0,  92.0,  "Brick wythe thickness (mm)"),
            "air_gap":           _p("length",  25.4,  19.1,  50.8,  "Cavity / air gap (mm)"),
            "backup_thickness":  _p("length", 114.3,  88.9, 165.1,  "Backup wall thickness (mm)"),
            "total_thickness":   _p("length", 231.7, 200.0, 350.0,  "Overall assembly thickness (mm)"),
        },
        "kerf_bim.authoring.walls.brick_veneer",
        "Brick veneer over stud or CMU backup wall.",
    ),
    _entry(
        "Curtain Wall",
        "Walls",
        {
            "mullion_width":   _p("length",  50.0,  38.0, 100.0, "Mullion face width (mm)"),
            "mullion_depth":   _p("length", 150.0, 100.0, 250.0, "Mullion depth / frame depth (mm)"),
            "panel_width":     _p("length", 1524.0, 457.2, 3048.0, "Typical panel width (mm)"),
            "panel_height":    _p("length", 3048.0, 914.4, 6096.0, "Typical panel height / floor-to-floor (mm)"),
            "glazing":         _p("string", "double", description="Glazing type"),
        },
        "kerf_bim.authoring.walls.curtain_wall",
        "Stick-built aluminum curtain wall system.",
    ),
]


# ---------------------------------------------------------------------------
# STAIRS  (4)
# ---------------------------------------------------------------------------

_STAIRS: list[FamilyTemplateEntry] = [
    _entry(
        "Straight-Run Stair",
        "Stairs",
        {
            "width":       _p("length", 1066.8, 762.0, 1828.8, "Stair width (mm); 30–72 in"),
            "riser_height":_p("length",  177.8, 152.4,  196.9, "Riser height (mm); 6–7¾ in"),
            "tread_depth": _p("length",  279.4, 228.6,  355.6, "Tread depth (mm); 9–14 in"),
            "riser_count": _p("integer", 13,    3,      30,    "Number of risers"),
            "nosing":      _p("length",   25.4, 0.0,    38.1,  "Nosing projection (mm)"),
        },
        "kerf_bim.authoring.stairs.straight_run",
        "Single straight-run stair flight.",
    ),
    _entry(
        "L-Shape Stair",
        "Stairs",
        {
            "width":        _p("length", 1066.8, 762.0, 1828.8, "Stair width (mm)"),
            "riser_height": _p("length",  177.8, 152.4,  196.9, "Riser height (mm)"),
            "tread_depth":  _p("length",  279.4, 228.6,  355.6, "Tread depth (mm)"),
            "lower_risers": _p("integer",  7,    2,      20,    "Risers in lower flight"),
            "upper_risers": _p("integer",  6,    2,      20,    "Risers in upper flight"),
            "landing_depth":_p("length", 1066.8, 762.0, 1828.8, "Landing depth (mm)"),
        },
        "kerf_bim.authoring.stairs.l_shape",
        "L-shaped two-flight stair with intermediate landing.",
    ),
    _entry(
        "U-Shape Stair",
        "Stairs",
        {
            "width":        _p("length", 1066.8, 762.0, 1828.8, "Flight width (mm)"),
            "riser_height": _p("length",  177.8, 152.4,  196.9, "Riser height (mm)"),
            "tread_depth":  _p("length",  279.4, 228.6,  355.6, "Tread depth (mm)"),
            "flight_risers":_p("integer",  7,    3,      15,    "Risers per flight"),
            "well_width":   _p("length",  304.8, 0.0,   914.4,  "Well / void width between flights (mm)"),
        },
        "kerf_bim.authoring.stairs.u_shape",
        "U-shaped (switchback) two-flight stair with top landing.",
    ),
    _entry(
        "Spiral Stair",
        "Stairs",
        {
            "diameter":     _p("length", 1524.0, 1219.2, 2438.4, "Overall column diameter (mm); 48–96 in"),
            "riser_height": _p("length",  177.8,  152.4,  196.9, "Riser height (mm)"),
            "tread_depth":  _p("length",  279.4,  228.6,  355.6, "Tread depth at walk-line (mm)"),
            "riser_count":  _p("integer", 13,     3,      30,    "Total risers per 360°"),
            "column_dia":   _p("length",  152.4,  76.2,   304.8, "Centre column diameter (mm)"),
        },
        "kerf_bim.authoring.stairs.spiral",
        "Spiral stair around a central column.",
    ),
]


# ---------------------------------------------------------------------------
# FURNITURE  (5)
# ---------------------------------------------------------------------------

_FURNITURE: list[FamilyTemplateEntry] = [
    _entry(
        "Office Desk",
        "Furniture",
        {
            "width":      _p("length", 1524.0, 900.0, 2400.0, "Desktop width (mm)"),
            "depth":      _p("length",  762.0, 450.0, 1050.0, "Desktop depth (mm)"),
            "height":     _p("length",  736.6, 685.8,  812.8, "Work surface height (mm); 27–32 in"),
            "return_width":_p("length",  914.4, 0.0,  1524.0, "Return extension width, 0 = no return (mm)"),
        },
        "kerf_bim.authoring.furniture.desk",
        "Office or work desk with optional return.",
    ),
    _entry(
        "Task Chair",
        "Furniture",
        {
            "seat_width":  _p("length", 482.6, 406.4, 609.6, "Seat width (mm); 16–24 in"),
            "seat_height": _p("length", 457.2, 406.4, 457.2, "Seat height off floor (mm); 16–18 in"),
            "back_height": _p("length", 939.8, 812.8, 1168.4,"Top-of-back height (mm); 32–46 in"),
            "armrests":    _p("boolean", True,  description="Has adjustable armrests"),
        },
        "kerf_bim.authoring.furniture.chair",
        "Ergonomic task chair with height-adjustable seat.",
    ),
    _entry(
        "Conference Table",
        "Furniture",
        {
            "length": _p("length", 3048.0, 1524.0, 6096.0, "Table length (mm); 60–240 in"),
            "width":  _p("length", 1066.8,  762.0, 1524.0, "Table width (mm); 30–60 in"),
            "height": _p("length",  736.6,  685.8,  812.8, "Table height (mm); 27–32 in"),
            "seats":  _p("integer", 10,     4,      30,    "Nominal seating capacity"),
        },
        "kerf_bim.authoring.furniture.conference_table",
        "Boardroom / conference table.",
    ),
    _entry(
        "File Cabinet",
        "Furniture",
        {
            "width":        _p("length", 381.0, 381.0, 762.0, "Cabinet width (mm); 15–30 in"),
            "depth":        _p("length", 685.8, 533.4, 762.0, "Cabinet depth (mm); 21–30 in"),
            "height":       _p("length", 1320.8, 685.8, 1524.0,"Cabinet height (mm); 27–60 in"),
            "drawer_count": _p("integer", 4,  2,  5,   "Number of drawers"),
            "legal_size":   _p("boolean", False, description="Legal-size drawers (wider)"),
        },
        "kerf_bim.authoring.furniture.file_cabinet",
        "Lateral or vertical filing cabinet.",
    ),
    _entry(
        "Shelving Unit",
        "Furniture",
        {
            "width":         _p("length", 914.4,  304.8, 1828.8, "Unit width (mm)"),
            "depth":         _p("length", 304.8,  203.2,  609.6, "Unit depth (mm)"),
            "height":        _p("length", 1828.8, 609.6, 2438.4, "Unit height (mm)"),
            "shelf_count":   _p("integer", 5,     2,     10,     "Number of shelves"),
            "adjustable":    _p("boolean", True,  description="Shelves are height-adjustable"),
        },
        "kerf_bim.authoring.furniture.shelving",
        "Freestanding shelving / bookcase unit.",
    ),
]


# ---------------------------------------------------------------------------
# PLUMBING  (6)
# ---------------------------------------------------------------------------

_PLUMBING: list[FamilyTemplateEntry] = [
    _entry(
        "Vanity Sink",
        "Plumbing",
        {
            "width":      _p("length", 609.6, 304.8, 1219.2, "Basin width (mm)"),
            "depth":      _p("length", 482.6, 304.8,  609.6, "Basin depth (mm)"),
            "rim_height": _p("length", 863.6, 812.8,  914.4, "Rim height off floor (mm); 32–36 in"),
            "basins":     _p("integer", 1,    1,      2,     "Number of bowls"),
        },
        "kerf_bim.authoring.plumbing.vanity_sink",
        "Bathroom vanity sink / countertop lavatory.",
    ),
    _entry(
        "Kitchen Sink",
        "Plumbing",
        {
            "width":        _p("length", 812.8, 457.2, 1219.2, "Overall sink width (mm)"),
            "depth":        _p("length", 533.4, 381.0,  609.6, "Front-to-back depth (mm)"),
            "basin_depth":  _p("length", 203.2, 152.4,  254.0, "Basin interior depth (mm)"),
            "basins":       _p("integer", 2,    1,      3,     "Number of bowls"),
        },
        "kerf_bim.authoring.plumbing.kitchen_sink",
        "Kitchen sink, single or double bowl.",
    ),
    _entry(
        "Toilet",
        "Plumbing",
        {
            "width":       _p("length", 368.3, 355.6, 457.2, "Toilet width (mm); 14–18 in"),
            "length":      _p("length", 711.2, 635.0, 812.8, "Front-to-wall length (mm); 25–32 in"),
            "seat_height": _p("length", 406.4, 355.6, 482.6, "Seat height (mm); 14–19 in"),
            "flush_litres":_p("float",   4.8,  3.0,   6.0,   "Full-flush volume (L)"),
        },
        "kerf_bim.authoring.plumbing.toilet",
        "Floor-mounted or wall-hung toilet (water closet).",
    ),
    _entry(
        "Urinal",
        "Plumbing",
        {
            "width":      _p("length", 381.0, 304.8, 533.4, "Urinal width (mm)"),
            "rim_height": _p("length", 609.6, 431.8, 685.8, "Rim height off floor (mm)"),
            "flush_litres":_p("float",  1.9,  0.0,   3.8,   "Flush volume in L; 0 = waterless"),
        },
        "kerf_bim.authoring.plumbing.urinal",
        "Wall-hung urinal, standard or waterless.",
    ),
    _entry(
        "Shower Enclosure",
        "Plumbing",
        {
            "width":  _p("length",  914.4, 762.0, 1828.8, "Enclosure width (mm)"),
            "depth":  _p("length",  914.4, 762.0, 1524.0, "Enclosure depth (mm)"),
            "height": _p("length", 2133.6, 1828.8, 2438.4,"Enclosure height (mm)"),
            "door_type":_p("string", "hinged", description="hinged/sliding/none"),
        },
        "kerf_bim.authoring.plumbing.shower",
        "Shower stall enclosure with curb or zero-threshold.",
    ),
    _entry(
        "Bathtub",
        "Plumbing",
        {
            "length":     _p("length", 1524.0, 1219.2, 1828.8, "Tub length (mm)"),
            "width":      _p("length",  762.0,  609.6,  914.4, "Tub width (mm)"),
            "depth":      _p("length",  558.8,  431.8,  685.8, "Tub depth (mm)"),
            "style":      _p("string", "alcove", description="alcove/freestanding/drop-in/corner"),
        },
        "kerf_bim.authoring.plumbing.bathtub",
        "Standard or freestanding bathtub.",
    ),
    _entry(
        "Water Heater",
        "Plumbing",
        {
            "capacity_litres":_p("float",  189.3, 37.9, 378.5, "Storage capacity (L); 10–100 gal"),
            "diameter":       _p("length", 558.8, 381.0, 762.0, "Tank diameter (mm)"),
            "height":         _p("length", 1473.2, 838.2, 1828.8,"Tank height (mm)"),
            "fuel":           _p("string", "electric", description="electric/gas/heat_pump"),
        },
        "kerf_bim.authoring.plumbing.water_heater",
        "Storage water heater.",
    ),
]


# ---------------------------------------------------------------------------
# HVAC  (4)
# ---------------------------------------------------------------------------

_HVAC: list[FamilyTemplateEntry] = [
    _entry(
        "VAV Box",
        "HVAC",
        {
            "duct_width":   _p("length", 304.8, 152.4, 609.6, "Inlet duct width (mm)"),
            "duct_height":  _p("length", 203.2, 152.4, 406.4, "Inlet duct height (mm)"),
            "max_cfm":      _p("float",  500.0,  50.0, 3000.0,"Maximum airflow (CFM)"),
            "reheat":       _p("boolean", False, description="Has hot-water or electric reheat coil"),
        },
        "kerf_bim.authoring.hvac.vav_box",
        "Variable air volume (VAV) terminal box.",
    ),
    _entry(
        "Fan Coil Unit",
        "HVAC",
        {
            "width":        _p("length", 1219.2, 609.6, 2438.4, "Cabinet width (mm)"),
            "depth":        _p("length",  254.0, 152.4,  457.2, "Cabinet depth (mm)"),
            "height":       _p("length",  609.6, 304.8,  914.4, "Cabinet height (mm)"),
            "capacity_kw":  _p("float",    3.5,  1.0,   14.0,  "Cooling capacity (kW)"),
            "pipe_count":   _p("integer",  4,    2,      4,     "Number of pipes (2-pipe or 4-pipe)"),
        },
        "kerf_bim.authoring.hvac.fan_coil_unit",
        "Fan coil unit (FCU) for chilled/hot water systems.",
    ),
    _entry(
        "Supply Air Diffuser",
        "HVAC",
        {
            "neck_width":   _p("length", 304.8, 152.4, 609.6, "Neck width (mm)"),
            "neck_depth":   _p("length", 304.8, 152.4, 609.6, "Neck depth (mm)"),
            "face_size":    _p("length", 595.0, 300.0, 900.0, "Face tile size (mm)"),
            "pattern":      _p("string", "4-way", description="1-way/2-way/3-way/4-way/round"),
        },
        "kerf_bim.authoring.hvac.supply_diffuser",
        "Ceiling supply air diffuser, square or round.",
    ),
    _entry(
        "Return Grille",
        "HVAC",
        {
            "width":    _p("length", 609.6, 152.4, 1524.0, "Grille face width (mm)"),
            "height":   _p("length", 304.8, 152.4,  914.4, "Grille face height (mm)"),
            "blade_angle":_p("float", 45.0, 0.0,   90.0,  "Blade angle (degrees)"),
            "location": _p("string", "ceiling", description="ceiling/wall/floor"),
        },
        "kerf_bim.authoring.hvac.return_grille",
        "Return air grille — ceiling, wall, or floor mounted.",
    ),
]


# ---------------------------------------------------------------------------
# LIGHTING  (4)
# ---------------------------------------------------------------------------

_LIGHTING: list[FamilyTemplateEntry] = [
    _entry(
        "2x4 LED Troffer",
        "Lighting",
        {
            "module_x":  _p("length", 1219.2, 609.6, 1219.2, "Module length (mm); 2 ft or 4 ft"),
            "module_y":  _p("length",  609.6, 609.6,  609.6, "Module width (mm); 2 ft"),
            "power_w":   _p("float",   50.0,  30.0,   70.0,  "Rated power (W)"),
            "flux_lm":   _p("float",  5000.0, 2500.0, 8000.0,"Luminous flux (lm)"),
            "cct_k":     _p("integer", 4000,  2700,   6500,  "Colour temperature (K)"),
        },
        "kerf_bim.authoring.lighting.led_troffer",
        "2×4 (or 2×2) recessed LED troffer panel for grid ceilings.",
    ),
    _entry(
        "Recessed Downlight",
        "Lighting",
        {
            "aperture":  _p("length",  150.0, 75.0, 250.0,  "Aperture diameter (mm)"),
            "power_w":   _p("float",   12.0,  5.0,  30.0,   "Rated power (W)"),
            "flux_lm":   _p("float",   900.0, 400.0, 3000.0,"Luminous flux (lm)"),
            "cct_k":     _p("integer", 3000,  2700,  6500,  "Colour temperature (K)"),
            "dimmable":  _p("boolean", True,  description="Dimmable driver"),
        },
        "kerf_bim.authoring.lighting.downlight",
        "Recessed ceiling downlight / can light.",
    ),
    _entry(
        "Wall Sconce",
        "Lighting",
        {
            "width":         _p("length", 120.0, 75.0,  350.0, "Fixture width (mm)"),
            "height":        _p("length", 250.0, 150.0, 600.0, "Fixture height (mm)"),
            "power_w":       _p("float",  10.0,  3.0,   40.0,  "Rated power (W)"),
            "mount_height":  _p("length", 1828.8, 1524.0, 2133.6,"Mount height off floor (mm)"),
        },
        "kerf_bim.authoring.lighting.sconce",
        "Wall-mounted decorative sconce.",
    ),
    _entry(
        "Pendant Luminaire",
        "Lighting",
        {
            "diameter": _p("length", 304.8, 101.6, 762.0,  "Shade diameter (mm)"),
            "drop":     _p("length", 914.4, 304.8, 2438.4, "Suspension drop from ceiling (mm)"),
            "power_w":  _p("float",  15.0,  5.0,   60.0,   "Rated power (W)"),
        },
        "kerf_bim.authoring.lighting.pendant",
        "Suspended pendant luminaire.",
    ),
]


# ---------------------------------------------------------------------------
# Aggregate catalog
# ---------------------------------------------------------------------------

CATALOG: list[FamilyTemplateEntry] = (
    _DOORS
    + _WINDOWS
    + _WALLS
    + _STAIRS
    + _FURNITURE
    + _PLUMBING
    + _HVAC
    + _LIGHTING
)

CATALOG_BY_NAME: dict[str, FamilyTemplateEntry] = {e.name: e for e in CATALOG}

CATALOG_BY_CATEGORY: dict[str, list[FamilyTemplateEntry]] = {}
for _e in CATALOG:
    CATALOG_BY_CATEGORY.setdefault(_e.category, []).append(_e)
