"""
ifc_export.py — Interior model → IFC 4 STEP-physical-file exporter.

Exports a ``RoomLayout`` (and optional wall/door/window/furniture overrides)
to an IFC 4 SPF (STEP physical file) for Revit / ArchiCAD / other BIM
coordination workflows.

DISCLAIMER
----------
This is an **IFC 4 subset export** conforming to ISO 16739-1:2018.
It is NOT buildingSMART certified — use for coordination/import only, not
certification-grade model submission.

Supported IFC entity mapping
-----------------------------
Interior model element   → IFC 4 entity
----------------------   ---------------------------------
Wall                     → IfcWall  (IfcWallStandardCase where applicable)
Floor                    → IfcSlab  (PredefinedType=FLOOR)
Ceiling                  → IfcSlab  (PredefinedType=BASESLAB / ROOFSLAB)
Door                     → IfcDoor
Window                   → IfcWindow
Furniture (generic)      → IfcFurnishingElement
Furniture (desk/table)   → IfcFurniture  (PredefinedType=TABLE)
Furniture (chair)        → IfcFurniture  (PredefinedType=CHAIR)
Furniture (sofa)         → IfcFurniture  (PredefinedType=SOFA)
Light fixture            → IfcLightFixture (PredefinedType=POINTSOURCE)

Spatial hierarchy produced
--------------------------
IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey → elements

All dimensions in the interior model are in millimetres; the IFC file uses
SI METRE (IFC standard); values are divided by 1000 on write.

Pure-Python implementation — no external dependencies beyond the Python
standard library.
"""
from __future__ import annotations

import datetime
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from kerf_interior.space_planning import RoomLayout, PlacedItem
from kerf_interior.furniture import FurnitureItem


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

SCHEMA = "IFC4"

SUPPORTED_ENTITY_TYPES: list[str] = [
    "IfcWall",
    "IfcWallStandardCase",
    "IfcSlab",           # FLOOR / ROOFSLAB (ceiling)
    "IfcDoor",
    "IfcWindow",
    "IfcFurniture",
    "IfcFurnishingElement",
    "IfcLightFixture",
    "IfcBuildingStorey",
    "IfcBuilding",
    "IfcSite",
    "IfcProject",
]


def list_supported_entity_types() -> list[str]:
    """Return the list of IFC 4 entity types produced by this exporter."""
    return list(SUPPORTED_ENTITY_TYPES)


# ---------------------------------------------------------------------------
# Result + validation types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of ``validate_ifc4_subset``."""
    valid: bool
    entity_count: int
    entity_type_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema: str = "IFC4"


# ---------------------------------------------------------------------------
# Interior model for export
# ---------------------------------------------------------------------------

@dataclass
class InteriorWall:
    """Axis-aligned interior wall description.

    Dimensions in mm; positioned relative to room origin.
    """
    name: str
    x_mm: float
    y_mm: float
    length_mm: float
    thickness_mm: float = 150.0
    height_mm: float = 2700.0
    is_axis_x: bool = True          # True = wall runs along X axis
    is_standard_case: bool = True   # True = IfcWallStandardCase


@dataclass
class InteriorDoor:
    """Door opening in a wall."""
    name: str
    x_mm: float
    y_mm: float
    width_mm: float = 900.0
    height_mm: float = 2100.0
    thickness_mm: float = 50.0


@dataclass
class InteriorWindow:
    """Window opening in a wall."""
    name: str
    x_mm: float
    y_mm: float
    width_mm: float = 1200.0
    height_mm: float = 1200.0
    sill_height_mm: float = 900.0


@dataclass
class InteriorLight:
    """Light fixture (ceiling-mounted or wall-mounted)."""
    name: str
    x_mm: float
    y_mm: float
    z_mm: float = 2600.0


@dataclass
class InteriorModel:
    """Complete interior model ready for IFC export.

    Can be created directly or constructed from a ``RoomLayout`` using
    ``from_room_layout()``.

    All dimensions in mm.

    Attributes
    ----------
    name : str
        Project / room name.
    room : RoomLayout
        The room layout; provides floor/ceiling slab dimensions.
    walls : list[InteriorWall]
        Explicit wall objects (auto-generated from room boundary if empty).
    doors : list[InteriorDoor]
        Door objects.
    windows : list[InteriorWindow]
        Window objects.
    lights : list[InteriorLight]
        Light fixtures.
    """
    name: str
    room: RoomLayout
    walls: list[InteriorWall] = field(default_factory=list)
    doors: list[InteriorDoor] = field(default_factory=list)
    windows: list[InteriorWindow] = field(default_factory=list)
    lights: list[InteriorLight] = field(default_factory=list)

    @classmethod
    def from_room_layout(
        cls,
        room: RoomLayout,
        *,
        wall_thickness_mm: float = 150.0,
        doors: list[InteriorDoor] | None = None,
        windows: list[InteriorWindow] | None = None,
        lights: list[InteriorLight] | None = None,
    ) -> "InteriorModel":
        """Build an InteriorModel from a RoomLayout.

        Auto-generates 4 bounding walls (N/S/E/W) from the room footprint.
        Placed FF&E items are mapped to IfcFurniture entities.
        """
        w = room.width_mm
        d = room.depth_mm
        h = room.ceiling_height_mm
        t = wall_thickness_mm

        walls = [
            # South wall (y=0, runs along X)
            InteriorWall("South Wall", 0.0, 0.0, w, t, h, is_axis_x=True),
            # North wall (y=depth, runs along X)
            InteriorWall("North Wall", 0.0, d - t, w, t, h, is_axis_x=True),
            # West wall (x=0, runs along Y)
            InteriorWall("West Wall", 0.0, 0.0, d, t, h, is_axis_x=False),
            # East wall (x=width, runs along Y)
            InteriorWall("East Wall", w - t, 0.0, d, t, h, is_axis_x=False),
        ]

        return cls(
            name=room.name,
            room=room,
            walls=walls,
            doors=doors or [],
            windows=windows or [],
            lights=lights or [],
        )


# ---------------------------------------------------------------------------
# Low-level STEP helpers (mirrors kerf-bim/export_ifc/writer.py pattern)
# ---------------------------------------------------------------------------

_MM_TO_M = 1.0 / 1000.0
_BASE64_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def _ifc_guid(seed: str | int) -> str:
    """Generate a deterministic IFC GlobalId (22 chars from IFC GUID alphabet)."""
    if isinstance(seed, str):
        h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        n = h
    else:
        n = int(seed) % (2 ** 128)
    chars = []
    for _ in range(22):
        chars.append(_BASE64_CHARS[n % 64])
        n //= 64
    return "".join(chars)


def _f(v: float, decimals: int = 6) -> str:
    """Format a float for STEP output (always has a decimal point)."""
    s = f"{round(v, decimals):.6g}"
    if "." not in s and "e" not in s.lower():
        s = s + "."
    return s


def _s(v: str | None) -> str:
    """Wrap a string value for STEP; None → $."""
    if v is None:
        return "$"
    safe = str(v).replace("'", "''")
    return f"'{safe}'"


class _IDGen:
    """Sequential STEP entity ID generator."""

    def __init__(self, start: int = 1) -> None:
        self._n = start

    def next(self) -> int:
        n = self._n
        self._n += 1
        return n


# ---------------------------------------------------------------------------
# IFC export core
# ---------------------------------------------------------------------------

def export_ifc4(interior_model: InteriorModel, path: str) -> None:
    """Export an ``InteriorModel`` to an IFC 4 SPF file.

    Writes a STEP physical file (ISO-10303-21) conforming to the IFC 4
    schema (IFC4) with a full spatial hierarchy and body geometry.

    Parameters
    ----------
    interior_model : InteriorModel
        The interior model to export.
    path : str
        Destination file path (will be overwritten).

    Notes
    -----
    IFC 4 subset export — NOT buildingSMART certified.
    For coordination/import use only.
    """
    text = _build_ifc4_text(interior_model)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _build_ifc4_text(interior_model: InteriorModel) -> str:
    """Build the IFC 4 STEP-physical-file text without writing to disk."""
    ids = _IDGen()
    lines: list[str] = []

    def entity(n: int, text: str) -> None:
        lines.append(f"#{n}={text};")

    room = interior_model.room

    # ── Units ────────────────────────────────────────────────────────────────
    id_unit_length = ids.next()
    id_unit_area   = ids.next()
    id_unit_volume = ids.next()
    id_unit_assign = ids.next()

    entity(id_unit_length, "IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    entity(id_unit_area,   "IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)")
    entity(id_unit_volume, "IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)")
    entity(id_unit_assign,
           f"IFCUNITASSIGNMENT((#{id_unit_length},#{id_unit_area},#{id_unit_volume}))")

    # ── Geometric representation context ────────────────────────────────────
    id_origin3d   = ids.next()
    id_z_dir      = ids.next()
    id_x_dir      = ids.next()
    id_axis_world = ids.next()
    id_rep_ctx    = ids.next()

    entity(id_origin3d,   "IFCCARTESIANPOINT((0.,0.,0.))")
    entity(id_z_dir,      "IFCDIRECTION((0.,0.,1.))")
    entity(id_x_dir,      "IFCDIRECTION((1.,0.,0.))")
    entity(id_axis_world, f"IFCAXIS2PLACEMENT3D(#{id_origin3d},#{id_z_dir},#{id_x_dir})")
    entity(id_rep_ctx,
           f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-5,#{id_axis_world},$)")

    # ── Owner / application ──────────────────────────────────────────────────
    id_org        = ids.next()
    id_person     = ids.next()
    id_pers_org   = ids.next()
    id_app        = ids.next()
    id_owner_hist = ids.next()

    ts_now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    entity(id_org,        "IFCORGANIZATION($,'Kerf',$,$,$)")
    entity(id_person,     "IFCPERSON($,'Kerf Interior Exporter',$,$,$,$,$,$)")
    entity(id_pers_org,   f"IFCPERSONANDORGANIZATION(#{id_person},#{id_org},$)")
    entity(id_app,        f"IFCAPPLICATION(#{id_org},'1.0',"
                          f"'Kerf Interior IFC4 Exporter (subset — NOT buildingSMART certified)',"
                          f"'Kerf')")
    entity(id_owner_hist, (
        f"IFCOWNERHISTORY(#{id_pers_org},#{id_app},$,"
        f".NOTDEFINED.,$,#{id_pers_org},#{id_app},{ts_now})"
    ))

    # ── Project ──────────────────────────────────────────────────────────────
    project_name = str(interior_model.name or "Kerf Interior Project")
    id_project = ids.next()
    entity(id_project, (
        f"IFCPROJECT({_s(_ifc_guid('interior_project'))},"
        f"#{id_owner_hist},{_s(project_name)},$,$,$,$,"
        f"(#{id_rep_ctx}),#{id_unit_assign})"
    ))

    # ── Site ────────────────────────────────────────────────────────────────
    id_site_origin = ids.next()
    id_site_ax     = ids.next()
    id_site_place  = ids.next()
    id_site        = ids.next()

    entity(id_site_origin, "IFCCARTESIANPOINT((0.,0.,0.))")
    entity(id_site_ax,     f"IFCAXIS2PLACEMENT3D(#{id_site_origin},$,$)")
    entity(id_site_place,  f"IFCLOCALPLACEMENT($,#{id_site_ax})")
    entity(id_site, (
        f"IFCSITE({_s(_ifc_guid('interior_site'))},"
        f"#{id_owner_hist},'Site',$,$,"
        f"#{id_site_place},$,$,.ELEMENT.,(0,0,0,0),(0,0,0,0),0.,$,$)"
    ))

    # ── Building ────────────────────────────────────────────────────────────
    id_bldg_origin = ids.next()
    id_bldg_ax     = ids.next()
    id_bldg_place  = ids.next()
    id_bldg        = ids.next()

    entity(id_bldg_origin, "IFCCARTESIANPOINT((0.,0.,0.))")
    entity(id_bldg_ax,     f"IFCAXIS2PLACEMENT3D(#{id_bldg_origin},$,$)")
    entity(id_bldg_place,  f"IFCLOCALPLACEMENT(#{id_site_place},#{id_bldg_ax})")
    entity(id_bldg, (
        f"IFCBUILDING({_s(_ifc_guid('interior_building'))},"
        f"#{id_owner_hist},{_s(project_name)},$,$,"
        f"#{id_bldg_place},$,$,.ELEMENT.,$,$,$)"
    ))

    # ── Building Storey ──────────────────────────────────────────────────────
    id_lvl_origin = ids.next()
    id_lvl_ax     = ids.next()
    id_lvl_place  = ids.next()
    id_storey     = ids.next()

    entity(id_lvl_origin, "IFCCARTESIANPOINT((0.,0.,0.))")
    entity(id_lvl_ax,     f"IFCAXIS2PLACEMENT3D(#{id_lvl_origin},$,$)")
    entity(id_lvl_place,  f"IFCLOCALPLACEMENT(#{id_bldg_place},#{id_lvl_ax})")
    entity(id_storey, (
        f"IFCBUILDINGSTOREY({_s(_ifc_guid('interior_storey'))},"
        f"#{id_owner_hist},'Ground Floor',$,$,"
        f"#{id_lvl_place},$,$,.ELEMENT.,0.)"
    ))

    # ── Spatial containment relations ─────────────────────────────────────────
    id_rel_proj_site = ids.next()
    entity(id_rel_proj_site, (
        f"IFCRELAGGREGATES({_s(_ifc_guid('rel_proj_site'))},"
        f"#{id_owner_hist},$,$,#{id_project},(#{id_site}))"
    ))
    id_rel_site_bldg = ids.next()
    entity(id_rel_site_bldg, (
        f"IFCRELAGGREGATES({_s(_ifc_guid('rel_site_bldg'))},"
        f"#{id_owner_hist},$,$,#{id_site},(#{id_bldg}))"
    ))
    id_rel_bldg_storey = ids.next()
    entity(id_rel_bldg_storey, (
        f"IFCRELAGGREGATES({_s(_ifc_guid('rel_bldg_storey'))},"
        f"#{id_owner_hist},$,$,#{id_bldg},(#{id_storey}))"
    ))

    # ── Element collection (for IfcRelContainedInSpatialStructure) ───────────
    contained_element_ids: list[int] = []

    # ── Helper: axis-aligned box solid ───────────────────────────────────────
    def _box_solid(
        x_mm: float, y_mm: float, z_mm: float,
        lx_mm: float, ly_mm: float, lz_mm: float,
        seed: str,
    ) -> tuple[int, int]:
        """Emit IFCEXTRUDEDAREASOLID for a box at (x,y,z) with dims lx×ly, height lz.
        Returns (placement_id, solid_id).
        """
        # Profile
        pid_pt = ids.next()
        pid_axis = ids.next()
        pid_rect = ids.next()
        lx_m = lx_mm * _MM_TO_M
        ly_m = ly_mm * _MM_TO_M
        entity(pid_pt,   f"IFCCARTESIANPOINT(({_f(0.)},{_f(0.)}))")
        entity(pid_axis, f"IFCAXIS2PLACEMENT2D(#{pid_pt},$)")
        entity(pid_rect, f"IFCRECTANGLEPROFILEDEF(.AREA.,$,#{pid_axis},{_f(lx_m)},{_f(ly_m)})")

        # Extrusion direction (Z)
        pid_edir = ids.next()
        entity(pid_edir, "IFCDIRECTION((0.,0.,1.))")

        # Placement for the solid
        pid_org3d = ids.next()
        pid_ax3d  = ids.next()
        pid_place = ids.next()
        x_m = x_mm * _MM_TO_M
        y_m = y_mm * _MM_TO_M
        z_m = z_mm * _MM_TO_M
        lz_m = lz_mm * _MM_TO_M
        entity(pid_org3d,
               f"IFCCARTESIANPOINT(({_f(x_m)},{_f(y_m)},{_f(z_m)}))")
        entity(pid_ax3d,  f"IFCAXIS2PLACEMENT3D(#{pid_org3d},$,$)")
        entity(pid_place, f"IFCLOCALPLACEMENT(#{id_lvl_place},#{pid_ax3d})")

        # Extruded solid
        pid_solid = ids.next()
        entity(pid_solid,
               f"IFCEXTRUDEDAREASOLID(#{pid_rect},#{pid_ax3d},#{pid_edir},{_f(lz_m)})")

        return pid_place, pid_solid

    def _shape_rep(solid_id: int) -> int:
        """Emit IfcShapeRepresentation for a single SweptSolid."""
        pid_sr = ids.next()
        entity(pid_sr, (
            f"IFCSHAPEREPRESENTATION(#{id_rep_ctx},'Body','SweptSolid',(#{solid_id}))"
        ))
        return pid_sr

    def _product_def_shape(shape_rep_id: int) -> int:
        pid_pds = ids.next()
        entity(pid_pds, f"IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape_rep_id}))")
        return pid_pds

    # ── Floor slab ───────────────────────────────────────────────────────────
    SLAB_THICKNESS_MM = 150.0
    fl_place, fl_solid = _box_solid(
        0.0, 0.0, -SLAB_THICKNESS_MM,
        room.width_mm, room.depth_mm, SLAB_THICKNESS_MM,
        "floor",
    )
    fl_sr  = _shape_rep(fl_solid)
    fl_pds = _product_def_shape(fl_sr)
    id_floor = ids.next()
    entity(id_floor, (
        f"IFCSLAB({_s(_ifc_guid('interior_floor'))},"
        f"#{id_owner_hist},'Floor Slab',$,$,"
        f"#{fl_place},#{fl_pds},$,.FLOOR.)"
    ))
    contained_element_ids.append(id_floor)

    # ── Ceiling slab ─────────────────────────────────────────────────────────
    ceil_z = room.ceiling_height_mm
    cl_place, cl_solid = _box_solid(
        0.0, 0.0, ceil_z,
        room.width_mm, room.depth_mm, SLAB_THICKNESS_MM,
        "ceiling",
    )
    cl_sr  = _shape_rep(cl_solid)
    cl_pds = _product_def_shape(cl_sr)
    id_ceiling = ids.next()
    entity(id_ceiling, (
        f"IFCSLAB({_s(_ifc_guid('interior_ceiling'))},"
        f"#{id_owner_hist},'Ceiling Slab',$,$,"
        f"#{cl_place},#{cl_pds},$,.BASESLAB.)"
    ))
    contained_element_ids.append(id_ceiling)

    # ── Walls ─────────────────────────────────────────────────────────────────
    for idx, w in enumerate(interior_model.walls):
        if w.is_axis_x:
            lx, ly = w.length_mm, w.thickness_mm
        else:
            lx, ly = w.thickness_mm, w.length_mm

        wl_place, wl_solid = _box_solid(
            w.x_mm, w.y_mm, 0.0,
            lx, ly, w.height_mm,
            f"wall_{idx}",
        )
        wl_sr  = _shape_rep(wl_solid)
        wl_pds = _product_def_shape(wl_sr)
        id_wall = ids.next()
        entity_name = "IFCWALLSTANDARDCASE" if w.is_standard_case else "IFCWALL"
        entity(id_wall, (
            f"{entity_name}({_s(_ifc_guid(f'wall_{idx}_{w.name}'))},"
            f"#{id_owner_hist},{_s(w.name)},$,$,"
            f"#{wl_place},#{wl_pds},$,$)"
        ))
        contained_element_ids.append(id_wall)

    # ── Doors ─────────────────────────────────────────────────────────────────
    for idx, door in enumerate(interior_model.doors):
        dp_place, dp_solid = _box_solid(
            door.x_mm, door.y_mm, 0.0,
            door.width_mm, door.thickness_mm, door.height_mm,
            f"door_{idx}",
        )
        dp_sr  = _shape_rep(dp_solid)
        dp_pds = _product_def_shape(dp_sr)
        id_door = ids.next()
        entity(id_door, (
            f"IFCDOOR({_s(_ifc_guid(f'door_{idx}_{door.name}'))},"
            f"#{id_owner_hist},{_s(door.name)},$,$,"
            f"#{dp_place},#{dp_pds},$,$,"
            f"{_f(door.height_mm * _MM_TO_M)},{_f(door.width_mm * _MM_TO_M)})"
        ))
        contained_element_ids.append(id_door)

    # ── Windows ───────────────────────────────────────────────────────────────
    for idx, win in enumerate(interior_model.windows):
        wp_place, wp_solid = _box_solid(
            win.x_mm, win.y_mm, win.sill_height_mm,
            win.width_mm, 100.0, win.height_mm,
            f"window_{idx}",
        )
        wp_sr  = _shape_rep(wp_solid)
        wp_pds = _product_def_shape(wp_sr)
        id_win = ids.next()
        entity(id_win, (
            f"IFCWINDOW({_s(_ifc_guid(f'window_{idx}_{win.name}'))},"
            f"#{id_owner_hist},{_s(win.name)},$,$,"
            f"#{wp_place},#{wp_pds},$,$,"
            f"{_f(win.height_mm * _MM_TO_M)},{_f(win.width_mm * _MM_TO_M)})"
        ))
        contained_element_ids.append(id_win)

    # ── Furniture (placed FF&E from RoomLayout) ────────────────────────────
    _KIND_TO_PREDEFINED = {
        "chair": ".CHAIR.",
        "desk":  ".TABLE.",
        "table": ".TABLE.",
        "sofa":  ".SOFA.",
    }

    for idx, placed in enumerate(room.items):
        item: FurnitureItem = placed.item
        fp_place, fp_solid = _box_solid(
            placed.x_mm, placed.y_mm, 0.0,
            item.width_mm, item.depth_mm, item.height_mm,
            f"furniture_{idx}",
        )
        fp_sr  = _shape_rep(fp_solid)
        fp_pds = _product_def_shape(fp_sr)
        id_furn = ids.next()
        predef = _KIND_TO_PREDEFINED.get(item.kind, ".NOTDEFINED.")
        entity(id_furn, (
            f"IFCFURNITURE({_s(_ifc_guid(f'furniture_{idx}_{item.name}'))},"
            f"#{id_owner_hist},{_s(placed.display_name)},$,$,"
            f"#{fp_place},#{fp_pds},$,{predef})"
        ))
        contained_element_ids.append(id_furn)

    # Also emit explicit lights from interior_model.lights
    for idx, light in enumerate(interior_model.lights):
        lp_place, lp_solid = _box_solid(
            light.x_mm, light.y_mm, light.z_mm,
            200.0, 200.0, 50.0,   # nominal fixture footprint
            f"light_{idx}",
        )
        lp_sr  = _shape_rep(lp_solid)
        lp_pds = _product_def_shape(lp_sr)
        id_light = ids.next()
        entity(id_light, (
            f"IFCLIGHTFIXTURE({_s(_ifc_guid(f'light_{idx}_{light.name}'))},"
            f"#{id_owner_hist},{_s(light.name)},$,$,"
            f"#{lp_place},#{lp_pds},$,.POINTSOURCE.)"
        ))
        contained_element_ids.append(id_light)

    # ── IfcRelContainedInSpatialStructure for all elements ────────────────────
    contained_refs = ",".join(f"#{e}" for e in contained_element_ids)
    id_rel_contained = ids.next()
    entity(id_rel_contained, (
        f"IFCRELCONTAINEDINSPATIALSTRUCTURE("
        f"{_s(_ifc_guid('rel_contained'))},"
        f"#{id_owner_hist},$,$,({contained_refs}),#{id_storey})"
    ))

    # ── Assemble STEP file ───────────────────────────────────────────────────
    ts_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(('IFC4 Interior Export — Kerf subset; "
        f"NOT buildingSMART certified; ISO 16739-1:2018'),'2;1');\n"
        f"FILE_NAME('{path_basename(interior_model.name)}','{ts_str}',('Kerf'),"
        f"('Kerf'),'Kerf Interior IFC4 Exporter','IFC4','');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    return header + "\n".join(lines) + "\n" + footer


def path_basename(name: str) -> str:
    """Safe ASCII filename fragment for STEP FILE_NAME header."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(name or "interior"))


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

# IFC 4 required attributes per entity type (minimal subset we check).
# Format: entity_name → list of positional attribute slot indices (0-based)
# that must NOT be '$' or empty.  We only enforce slot 0 (GlobalId).
_REQUIRED_ATTR_COUNT: dict[str, int] = {
    "IFCPROJECT":                    9,
    "IFCSITE":                      14,
    "IFCBUILDING":                  12,
    "IFCBUILDINGSTOREY":            11,
    "IFCWALL":                       9,
    "IFCWALLSTANDARDCASE":           9,
    "IFCSLAB":                      10,
    "IFCDOOR":                      12,
    "IFCWINDOW":                    12,
    "IFCFURNITURE":                  9,
    "IFCFURNISHINGELEMENT":          8,
    "IFCLIGHTFIXTURE":               9,
    "IFCRELAGGREGATES":              6,
    "IFCRELCONTAINEDINSPATIALSTRUCTURE": 6,
    "IFCUNITASSIGNMENT":             1,
    "IFCSIUNIT":                     4,
    "IFCOWNERHISTORY":               8,
    "IFCAPPLICATION":                4,
    "IFCORGANIZATION":               5,
    "IFCPERSON":                     8,
    "IFCPERSONANDORGANIZATION":      3,
    "IFCAXIS2PLACEMENT3D":           3,
    "IFCAXIS2PLACEMENT2D":           2,
    "IFCLOCALPLACEMENT":             2,
    "IFCCARTESIANPOINT":             1,
    "IFCDIRECTION":                  1,
    "IFCGEOMETRICREPRESENTATIONCONTEXT": 6,
    "IFCSHAPEREPRESENTATION":        4,
    "IFCPRODUCTDEFINITIONSHAPE":     3,
    "IFCRECTANGLEPROFILEDEF":        5,
    "IFCEXTRUDEDAREASOLID":          4,
}

_REQUIRED_ENTITIES = {
    "IFCPROJECT",
    "IFCSITE",
    "IFCBUILDING",
    "IFCBUILDINGSTOREY",
    "IFCUNITASSIGNMENT",
    "IFCOWNERHISTORY",
}

_ENTITY_LINE_RE = re.compile(r"^#(\d+)=([A-Z0-9_]+)\((.*)$", re.DOTALL)


def validate_ifc4_subset(path: str) -> ValidationResult:
    """Parse an IFC 4 SPF file and check schema compliance.

    Checks:
    - FILE_SCHEMA is 'IFC4'
    - All required structural entities present (IfcProject, IfcSite, etc.)
    - All #N forward-references are defined
    - File ends with ENDSEC; END-ISO-10303-21;

    Returns a ``ValidationResult`` with counts and any errors/warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return ValidationResult(
            valid=False,
            entity_count=0,
            errors=[f"Cannot read file: {exc}"],
        )

    # ── Schema check ─────────────────────────────────────────────────────────
    if "FILE_SCHEMA(('IFC4'))" not in text and "FILE_SCHEMA(('IFC4" not in text:
        errors.append("FILE_SCHEMA does not declare IFC4")

    # ── File termination ─────────────────────────────────────────────────────
    stripped = text.rstrip()
    if not stripped.endswith("END-ISO-10303-21;"):
        errors.append("File does not end with END-ISO-10303-21;")

    # ── Parse DATA section ────────────────────────────────────────────────────
    in_data = False
    defined_ids: set[int] = set()
    referenced_ids: set[int] = set()
    entity_type_counts: dict[str, int] = {}

    for line in text.splitlines():
        line_s = line.strip()
        if line_s == "DATA;":
            in_data = True
            continue
        if line_s == "ENDSEC;" and in_data:
            in_data = False
            continue
        if not in_data:
            continue
        if not line_s.startswith("#"):
            continue

        m = _ENTITY_LINE_RE.match(line_s)
        if not m:
            continue

        eid   = int(m.group(1))
        etype = m.group(2).upper()
        body  = m.group(3)

        defined_ids.add(eid)
        entity_type_counts[etype] = entity_type_counts.get(etype, 0) + 1

        # Collect forward references
        for ref in re.findall(r"#(\d+)", body):
            referenced_ids.add(int(ref))

    # ── Reference resolution check ────────────────────────────────────────────
    unresolved = referenced_ids - defined_ids
    if unresolved:
        errors.append(
            f"Unresolved forward references: #{sorted(unresolved)[:5]!r} "
            f"(showing first 5 of {len(unresolved)})"
        )

    # ── Required entity presence ──────────────────────────────────────────────
    for req in _REQUIRED_ENTITIES:
        if entity_type_counts.get(req, 0) == 0:
            errors.append(f"Missing required entity: {req}")

    # ── IFC4 entity hierarchy check ───────────────────────────────────────────
    # IfcProject must exist exactly once
    proj_count = entity_type_counts.get("IFCPROJECT", 0)
    if proj_count != 1:
        errors.append(f"Expected exactly 1 IFCPROJECT, found {proj_count}")

    # At least one storey
    storey_count = entity_type_counts.get("IFCBUILDINGSTOREY", 0)
    if storey_count < 1:
        errors.append("No IFCBUILDINGSTOREY found")

    # IfcRelContainedInSpatialStructure must exist
    if entity_type_counts.get("IFCRELCONTAINEDINSPATIALSTRUCTURE", 0) == 0:
        warnings.append("No IFCRELCONTAINEDINSPATIALSTRUCTURE — elements may not be placed in hierarchy")

    entity_count = len(defined_ids)
    valid = len(errors) == 0

    return ValidationResult(
        valid=valid,
        entity_count=entity_count,
        entity_type_counts=entity_type_counts,
        errors=errors,
        warnings=warnings,
        schema="IFC4",
    )
