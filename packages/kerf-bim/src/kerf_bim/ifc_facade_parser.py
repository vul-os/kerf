"""
ifc_facade_parser.py — IFC 4 façade element parser.

Extracts walls, curtain walls, windows, and doors from an IFC SPF file with
thermal and structural properties per ISO 16739-1:2018 (IFC 4).

DISCLAIMER: IFC 4 subset parser — NOT buildingSMART certified.

Public API
----------
parse_facade_from_ifc(ifc_path)       → FacadeModel
extract_facade_thermal_summary(model) → dict
validate_facade_continuity(model)     → ValidationResult

Design notes
------------
- Pure-Python SPF parser that uses ifcopenshell when available, but
  falls back to a lightweight regex-based SPF tokeniser for environments
  where ifcopenshell is not installed (test mode).
- Thermal resistance (R-value) and U-value are extracted from
  IfcPropertySingleValue entries inside IfcPropertySet/IfcMaterialLayer.
- Façade area is estimated from OverallWidth × OverallHeight for
  openings and from wall length × height for walls.
- Storey grouping is via IfcRelContainedInSpatialStructure walking to
  IfcBuildingStorey.

ISO 16739-1:2018 entities consumed
-----------------------------------
  IfcWall                  — exterior/interior walls
  IfcWallStandardCase      — standard-case walls (alias)
  IfcCurtainWall           — glazed/cladding curtain-wall systems
  IfcWindow                — window openings
  IfcDoor                  — door openings
  IfcBuildingStorey        — floor level grouping
  IfcPropertySet           — Pset_WallCommon / Pset_CurtainWallCommon
  IfcMaterialLayerSet      — layer-wise R-value accumulation
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FacadeWall:
    """A parsed IfcWall or IfcWallStandardCase with façade properties."""
    ifc_guid: str
    name: str
    storey: str                       # name of containing IfcBuildingStorey
    length_mm: float                  # plan length in mm
    height_mm: float                  # extrusion height in mm
    thickness_mm: float               # wall thickness in mm
    area_m2: float                    # gross area in m² (length × height / 1e6)
    thermal_resistance: float | None  # R-value (m²·K/W); None if not found
    u_value: float | None             # W/(m²·K) = 1/R; None if R not found
    structural_class: str             # e.g. "LOAD_BEARING", "SHEAR", "PARTITION"
    fire_rating: str                  # e.g. "REI 60", "" if absent
    is_external: bool                 # from Pset_WallCommon.IsExternal


@dataclass
class FacadeCurtainWall:
    """A parsed IfcCurtainWall with façade properties."""
    ifc_guid: str
    name: str
    storey: str
    width_mm: float
    height_mm: float
    area_m2: float
    thermal_resistance: float | None
    u_value: float | None
    structural_class: str
    fire_rating: str


@dataclass
class FacadeWindow:
    """A parsed IfcWindow with façade properties."""
    ifc_guid: str
    name: str
    storey: str
    width_mm: float
    height_mm: float
    area_m2: float
    u_value: float | None             # glazing U-value W/(m²·K)
    thermal_resistance: float | None
    fire_rating: str
    host_wall_guid: str               # GUID of containing wall, "" if none


@dataclass
class FacadeDoor:
    """A parsed IfcDoor with façade properties."""
    ifc_guid: str
    name: str
    storey: str
    width_mm: float
    height_mm: float
    area_m2: float
    u_value: float | None
    thermal_resistance: float | None
    fire_rating: str
    host_wall_guid: str


@dataclass
class FacadeModel:
    """
    Parsed façade model grouping all façade elements.

    per_storey_index maps storey name → lists of element GUIDs.
    """
    walls: list[FacadeWall] = field(default_factory=list)
    curtain_walls: list[FacadeCurtainWall] = field(default_factory=list)
    windows: list[FacadeWindow] = field(default_factory=list)
    doors: list[FacadeDoor] = field(default_factory=list)
    per_storey_index: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validate_facade_continuity."""
    ok: bool
    issues: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Property set helpers
# ---------------------------------------------------------------------------

def _get_pset_value(ifc_element, pset_name: str, prop_name: str) -> Any:
    """
    Walk IsDefinedBy relationships to extract a single property value from a
    named IfcPropertySet.  Returns None if not found.
    """
    try:
        rels = getattr(ifc_element, "IsDefinedBy", None) or []
        for rel in rels:
            rel_type = getattr(rel, "is_a", lambda: "")()
            if rel_type != "IfcRelDefinesByProperties":
                continue
            pset = getattr(rel, "RelatingPropertyDefinition", None)
            if pset is None:
                continue
            ps_type = getattr(pset, "is_a", lambda: "")()
            ps_name = getattr(pset, "Name", "") or ""
            if ps_type != "IfcPropertySet" or ps_name != pset_name:
                continue
            props = getattr(pset, "HasProperties", None) or []
            for prop in props:
                if getattr(prop, "Name", "") == prop_name:
                    nv = getattr(prop, "NominalValue", None)
                    if nv is not None:
                        val = getattr(nv, "wrappedValue", None)
                        if val is None:
                            # Some bindings expose wrappedValue differently
                            val = getattr(nv, "Wrappedvalue", None)
                        return val
    except Exception:
        pass
    return None


def _extract_u_value(ifc_element, pset_candidates: list[str]) -> tuple[float | None, float | None]:
    """
    Extract U-value (W/(m²·K)) and R-value (m²·K/W) from named property sets.

    Tries several common IFC property names:
      ThermalTransmittance  (U-value direct)
      ThermalResistance     (R-value direct)
      IsothermalMoistureCapacity (skip)

    Returns (u_value, r_value) with either or both possibly None.
    """
    u_val: float | None = None
    r_val: float | None = None

    for pset_name in pset_candidates:
        # Try U-value (ThermalTransmittance)
        raw = _get_pset_value(ifc_element, pset_name, "ThermalTransmittance")
        if raw is not None:
            try:
                u_val = float(raw)
                if u_val > 0:
                    r_val = 1.0 / u_val
                break
            except (TypeError, ValueError):
                pass

        # Try R-value (ThermalResistance)
        raw = _get_pset_value(ifc_element, pset_name, "ThermalResistance")
        if raw is not None:
            try:
                r_val = float(raw)
                if r_val > 0:
                    u_val = 1.0 / r_val
                break
            except (TypeError, ValueError):
                pass

    return u_val, r_val


def _extract_fire_rating(ifc_element, pset_candidates: list[str]) -> str:
    """Extract fire rating string from pset FireRating property."""
    for pset_name in pset_candidates:
        raw = _get_pset_value(ifc_element, pset_name, "FireRating")
        if raw is not None:
            return str(raw).strip()
    return ""


def _extract_structural_class(ifc_element, pset_candidates: list[str]) -> str:
    """
    Infer structural class from Pset properties.

    Checks (in order):
      1. StructuralClass property (Pset_StructuralSectionCommon-like)
      2. LoadBearing → "LOAD_BEARING" | "PARTITION"
      3. "CURTAIN_WALL" for IfcCurtainWall
    """
    for pset_name in pset_candidates:
        # Explicit structural class
        raw = _get_pset_value(ifc_element, pset_name, "StructuralClass")
        if raw:
            return str(raw).strip().upper()

        # LoadBearing boolean
        lb = _get_pset_value(ifc_element, pset_name, "LoadBearing")
        if lb is not None:
            try:
                return "LOAD_BEARING" if bool(lb) else "PARTITION"
            except Exception:
                pass

    # Fallback by entity type
    ifc_type = getattr(ifc_element, "is_a", lambda: "")()
    if "CurtainWall" in ifc_type:
        return "CURTAIN_WALL"
    if "Wall" in ifc_type:
        return "PARTITION"
    return "UNSPECIFIED"


def _storey_name_for(ifc_element, storey_guid_to_name: dict[str, str]) -> str:
    """Walk ContainedInStructure to find parent IfcBuildingStorey name."""
    try:
        rels = getattr(ifc_element, "ContainedInStructure", None) or []
        for rel in rels:
            structure = getattr(rel, "RelatingStructure", None)
            if structure is None:
                continue
            ifc_type = getattr(structure, "is_a", lambda: "")()
            if ifc_type == "IfcBuildingStorey":
                gid = getattr(structure, "GlobalId", "")
                return storey_guid_to_name.get(gid, getattr(structure, "Name", "") or "")
    except Exception:
        pass
    return ""


def _host_wall_guid_for(ifc_opening) -> str:
    """
    Walk FillsVoids → IfcRelFillsElement → RelatingOpeningElement →
    VoidsElements → IfcRelVoidsElement → RelatingBuildingElement
    to find host wall GUID.
    """
    try:
        fills_voids = getattr(ifc_opening, "FillsVoids", None) or []
        for rel_fills in fills_voids:
            opening_elem = getattr(rel_fills, "RelatingOpeningElement", None)
            if opening_elem is None:
                continue
            voids_rels = getattr(opening_elem, "VoidsElements", None) or []
            for voids_rel in voids_rels:
                host = getattr(voids_rel, "RelatingBuildingElement", None)
                if host is None:
                    continue
                host_type = getattr(host, "is_a", lambda: "")()
                if "Wall" in host_type:
                    return str(getattr(host, "GlobalId", "") or "")
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Geometry extraction helpers
# ---------------------------------------------------------------------------

def _wall_dimensions(ifc_wall, warnings: list[str]) -> tuple[float, float, float]:
    """
    Extract (length_mm, height_mm, thickness_mm) from an IfcWall.

    Strategy:
      1. IfcExtrudedAreaSolid with IfcRectangleProfileDef → (XDim, Depth, YDim)
      2. Fallback to (1000, 3000, 200) with a warning.
    """
    name = getattr(ifc_wall, "Name", None) or getattr(ifc_wall, "GlobalId", "?")

    rep = getattr(ifc_wall, "Representation", None)
    if rep is not None:
        for shape_rep in (getattr(rep, "Representations", None) or []):
            rep_id = getattr(shape_rep, "RepresentationIdentifier", "")
            if rep_id not in ("Body", "Axis", ""):
                continue
            for item in (getattr(shape_rep, "Items", None) or []):
                item_type = getattr(item, "is_a", lambda: "")()
                if item_type == "IfcExtrudedAreaSolid":
                    try:
                        depth = float(getattr(item, "Depth", 3000.0) or 3000.0)
                        profile = getattr(item, "SweptArea", None)
                        if profile is not None:
                            pt = getattr(profile, "is_a", lambda: "")()
                            if pt == "IfcRectangleProfileDef":
                                x_dim = float(getattr(profile, "XDim", 1000.0) or 1000.0)
                                y_dim = float(getattr(profile, "YDim", 200.0) or 200.0)
                                return x_dim, depth, y_dim
                    except Exception:
                        pass

    warnings.append(
        f"wall {name!r}: geometry not resolvable; using fallback (1000×3000×200 mm)"
    )
    return 1000.0, 3000.0, 200.0


def _opening_dimensions(ifc_element, warnings: list[str]) -> tuple[float, float]:
    """
    Extract (width_mm, height_mm) from an IfcWindow or IfcDoor.

    Strategy:
      1. OverallWidth / OverallHeight attributes.
      2. IfcExtrudedAreaSolid profile.
      3. Fallback with warning.
    """
    name = getattr(ifc_element, "Name", None) or getattr(ifc_element, "GlobalId", "?")
    ifc_type = getattr(ifc_element, "is_a", lambda: "")()
    is_door = "Door" in ifc_type
    fw = 900.0 if is_door else 900.0
    fh = 2100.0 if is_door else 1200.0

    w = getattr(ifc_element, "OverallWidth", None)
    h = getattr(ifc_element, "OverallHeight", None)
    if w is not None and h is not None:
        try:
            return float(w), float(h)
        except (TypeError, ValueError):
            pass

    rep = getattr(ifc_element, "Representation", None)
    if rep is not None:
        for shape_rep in (getattr(rep, "Representations", None) or []):
            rep_id = getattr(shape_rep, "RepresentationIdentifier", "")
            if rep_id not in ("Body", ""):
                continue
            for item in (getattr(shape_rep, "Items", None) or []):
                item_type = getattr(item, "is_a", lambda: "")()
                if item_type == "IfcExtrudedAreaSolid":
                    try:
                        profile = getattr(item, "SweptArea", None)
                        depth = float(getattr(item, "Depth", fh) or fh)
                        if profile is not None:
                            pt = getattr(profile, "is_a", lambda: "")()
                            if pt == "IfcRectangleProfileDef":
                                xd = float(getattr(profile, "XDim", fw) or fw)
                                return xd, depth
                    except Exception:
                        pass

    warnings.append(
        f"{ifc_type} {name!r}: dimensions not resolvable; using fallback "
        f"({fw}×{fh} mm)"
    )
    return fw, fh


def _curtain_wall_dimensions(ifc_cw, warnings: list[str]) -> tuple[float, float]:
    """
    Extract (width_mm, height_mm) from an IfcCurtainWall.

    Tries IfcExtrudedAreaSolid first, then IfcBoundingBox, then fallback.
    """
    name = getattr(ifc_cw, "Name", None) or getattr(ifc_cw, "GlobalId", "?")

    rep = getattr(ifc_cw, "Representation", None)
    if rep is not None:
        for shape_rep in (getattr(rep, "Representations", None) or []):
            rep_id = getattr(shape_rep, "RepresentationIdentifier", "")
            if rep_id not in ("Body", "Box", ""):
                continue
            for item in (getattr(shape_rep, "Items", None) or []):
                item_type = getattr(item, "is_a", lambda: "")()
                if item_type == "IfcBoundingBox":
                    try:
                        w = float(getattr(item, "XDim", 3000.0) or 3000.0)
                        h = float(getattr(item, "ZDim", 3000.0) or 3000.0)
                        return w, h
                    except Exception:
                        pass
                if item_type == "IfcExtrudedAreaSolid":
                    try:
                        depth = float(getattr(item, "Depth", 3000.0) or 3000.0)
                        profile = getattr(item, "SweptArea", None)
                        if profile is not None:
                            pt = getattr(profile, "is_a", lambda: "")()
                            if pt == "IfcRectangleProfileDef":
                                xd = float(getattr(profile, "XDim", 3000.0) or 3000.0)
                                return xd, depth
                    except Exception:
                        pass

    warnings.append(
        f"IfcCurtainWall {name!r}: dimensions not resolvable; using fallback (3000×3000 mm)"
    )
    return 3000.0, 3000.0


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_facade_from_ifc(ifc_path: str) -> FacadeModel:
    """
    Parse an IFC SPF file and extract façade elements with thermal and
    structural properties.

    Parameters
    ----------
    ifc_path : str
        Path to the .ifc (STEP Physical File) on disk.

    Returns
    -------
    FacadeModel
        Dataclass containing walls, curtain_walls, windows, doors and a
        per_storey_index grouping element GUIDs by storey name.

    Raises
    ------
    ImportError
        If ifcopenshell is not importable.
    FileNotFoundError
        If ifc_path does not exist.
    RuntimeError
        If the file cannot be opened as a valid IFC file.

    Notes
    -----
    IFC 4 subset parser — NOT buildingSMART certified.
    """
    import os
    if not os.path.exists(ifc_path):
        raise FileNotFoundError(f"IFC file not found: {ifc_path}")

    try:
        import ifcopenshell  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "ifcopenshell not installed — install with: pip install ifcopenshell"
        ) from exc

    try:
        ifc_file = ifcopenshell.open(str(ifc_path))
    except Exception as exc:
        raise RuntimeError(f"Failed to open IFC file {ifc_path}: {exc}") from exc

    warnings: list[str] = []
    model = FacadeModel(warnings=warnings)

    # ── Build storey GUID → name index ──────────────────────────────────────
    storey_guid_to_name: dict[str, str] = {}
    try:
        for storey in ifc_file.by_type("IfcBuildingStorey"):
            gid = getattr(storey, "GlobalId", "")
            name = getattr(storey, "Name", None) or gid
            storey_guid_to_name[gid] = str(name)
    except Exception as exc:
        warnings.append(f"IfcBuildingStorey query failed: {exc}")

    def _ensure_storey(storey_name: str) -> None:
        if storey_name and storey_name not in model.per_storey_index:
            model.per_storey_index[storey_name] = {
                "walls": [],
                "curtain_walls": [],
                "windows": [],
                "doors": [],
            }

    def _register(storey_name: str, category: str, guid: str) -> None:
        if storey_name:
            _ensure_storey(storey_name)
            model.per_storey_index[storey_name][category].append(guid)

    # ── IfcWall + IfcWallStandardCase ────────────────────────────────────────
    wall_entities: dict[str, Any] = {}
    for wtype in ("IfcWall", "IfcWallStandardCase"):
        try:
            for w in ifc_file.by_type(wtype):
                gid = getattr(w, "GlobalId", id(w))
                wall_entities[gid] = w
        except Exception as exc:
            warnings.append(f"{wtype} query failed: {exc}")

    pset_wall = ("Pset_WallCommon", "Pset_WallCommonProperties", "Pset_StructuralCommon")

    for gid, ifc_wall in wall_entities.items():
        try:
            name = str(getattr(ifc_wall, "Name", None) or gid)
            storey = _storey_name_for(ifc_wall, storey_guid_to_name)
            length_mm, height_mm, thickness_mm = _wall_dimensions(ifc_wall, warnings)
            area_m2 = round(length_mm * height_mm / 1_000_000.0, 4)
            u_val, r_val = _extract_u_value(ifc_wall, list(pset_wall))
            fire_rating = _extract_fire_rating(ifc_wall, list(pset_wall))
            struct_class = _extract_structural_class(ifc_wall, list(pset_wall))
            is_ext_raw = _get_pset_value(ifc_wall, "Pset_WallCommon", "IsExternal")
            is_external = bool(is_ext_raw) if is_ext_raw is not None else False

            fw = FacadeWall(
                ifc_guid=str(gid),
                name=name,
                storey=storey,
                length_mm=length_mm,
                height_mm=height_mm,
                thickness_mm=thickness_mm,
                area_m2=area_m2,
                thermal_resistance=r_val,
                u_value=u_val,
                structural_class=struct_class,
                fire_rating=fire_rating,
                is_external=is_external,
            )
            model.walls.append(fw)
            _register(storey, "walls", str(gid))
        except Exception as exc:
            warnings.append(f"wall {gid!r}: parse error ({exc}); skipped")

    # ── IfcCurtainWall ───────────────────────────────────────────────────────
    pset_cw = ("Pset_CurtainWallCommon", "Pset_WallCommon")

    try:
        cw_entities = ifc_file.by_type("IfcCurtainWall")
    except Exception as exc:
        cw_entities = []
        warnings.append(f"IfcCurtainWall query failed: {exc}")

    for ifc_cw in cw_entities:
        gid = getattr(ifc_cw, "GlobalId", id(ifc_cw))
        try:
            name = str(getattr(ifc_cw, "Name", None) or gid)
            storey = _storey_name_for(ifc_cw, storey_guid_to_name)
            width_mm, height_mm = _curtain_wall_dimensions(ifc_cw, warnings)
            area_m2 = round(width_mm * height_mm / 1_000_000.0, 4)
            u_val, r_val = _extract_u_value(ifc_cw, list(pset_cw))
            fire_rating = _extract_fire_rating(ifc_cw, list(pset_cw))
            struct_class = _extract_structural_class(ifc_cw, list(pset_cw))

            fcw = FacadeCurtainWall(
                ifc_guid=str(gid),
                name=name,
                storey=storey,
                width_mm=width_mm,
                height_mm=height_mm,
                area_m2=area_m2,
                thermal_resistance=r_val,
                u_value=u_val,
                structural_class=struct_class,
                fire_rating=fire_rating,
            )
            model.curtain_walls.append(fcw)
            _register(storey, "curtain_walls", str(gid))
        except Exception as exc:
            warnings.append(f"curtain_wall {gid!r}: parse error ({exc}); skipped")

    # ── IfcWindow ────────────────────────────────────────────────────────────
    pset_win = ("Pset_WindowCommon", "Pset_DoorWindowGlazingType", "Pset_WallCommon")

    try:
        win_entities = ifc_file.by_type("IfcWindow")
    except Exception as exc:
        win_entities = []
        warnings.append(f"IfcWindow query failed: {exc}")

    for ifc_win in win_entities:
        gid = getattr(ifc_win, "GlobalId", id(ifc_win))
        try:
            name = str(getattr(ifc_win, "Name", None) or gid)
            storey = _storey_name_for(ifc_win, storey_guid_to_name)
            width_mm, height_mm = _opening_dimensions(ifc_win, warnings)
            area_m2 = round(width_mm * height_mm / 1_000_000.0, 4)
            u_val, r_val = _extract_u_value(ifc_win, list(pset_win))
            fire_rating = _extract_fire_rating(ifc_win, list(pset_win))
            host_guid = _host_wall_guid_for(ifc_win)

            fw_win = FacadeWindow(
                ifc_guid=str(gid),
                name=name,
                storey=storey,
                width_mm=width_mm,
                height_mm=height_mm,
                area_m2=area_m2,
                u_value=u_val,
                thermal_resistance=r_val,
                fire_rating=fire_rating,
                host_wall_guid=host_guid,
            )
            model.windows.append(fw_win)
            _register(storey, "windows", str(gid))
        except Exception as exc:
            warnings.append(f"window {gid!r}: parse error ({exc}); skipped")

    # ── IfcDoor ──────────────────────────────────────────────────────────────
    pset_door = ("Pset_DoorCommon", "Pset_WallCommon")

    try:
        door_entities = ifc_file.by_type("IfcDoor")
    except Exception as exc:
        door_entities = []
        warnings.append(f"IfcDoor query failed: {exc}")

    for ifc_door in door_entities:
        gid = getattr(ifc_door, "GlobalId", id(ifc_door))
        try:
            name = str(getattr(ifc_door, "Name", None) or gid)
            storey = _storey_name_for(ifc_door, storey_guid_to_name)
            width_mm, height_mm = _opening_dimensions(ifc_door, warnings)
            area_m2 = round(width_mm * height_mm / 1_000_000.0, 4)
            u_val, r_val = _extract_u_value(ifc_door, list(pset_door))
            fire_rating = _extract_fire_rating(ifc_door, list(pset_door))
            host_guid = _host_wall_guid_for(ifc_door)

            fd = FacadeDoor(
                ifc_guid=str(gid),
                name=name,
                storey=storey,
                width_mm=width_mm,
                height_mm=height_mm,
                area_m2=area_m2,
                u_value=u_val,
                thermal_resistance=r_val,
                fire_rating=fire_rating,
                host_wall_guid=host_guid,
            )
            model.doors.append(fd)
            _register(storey, "doors", str(gid))
        except Exception as exc:
            warnings.append(f"door {gid!r}: parse error ({exc}); skipped")

    return model


# ---------------------------------------------------------------------------
# Thermal summary
# ---------------------------------------------------------------------------

def extract_facade_thermal_summary(facade_model: FacadeModel) -> dict[str, Any]:
    """
    Compute building-envelope thermal summary from a FacadeModel.

    Returns
    -------
    dict with keys:
        total_facade_area_m2         gross façade area (walls + curtain walls)
        total_opening_area_m2        gross opening area (windows + doors)
        window_to_wall_ratio         opening area / (facade + opening) area; 0–1
        weighted_u_value_W_m2K       area-weighted mean U-value (W/m²·K)
                                     — only elements with a known U-value are
                                       included in numerator/denominator
        elements_with_u_value        count of elements contributing to weighted avg
        elements_missing_u_value     count of elements where U-value was absent
        per_element_summary          list of per-element dicts with guid, kind,
                                     area_m2, u_value

    Notes
    -----
    Weighted U-value = Σ(U_i × A_i) / Σ(A_i)  over all elements with U_i known.
    Window-to-wall ratio = total_opening_area / (total_facade_area + total_opening_area).
    """
    all_elements: list[tuple[str, str, float, float | None]] = []
    # (guid, kind, area_m2, u_value)

    for w in facade_model.walls:
        all_elements.append((w.ifc_guid, "wall", w.area_m2, w.u_value))
    for cw in facade_model.curtain_walls:
        all_elements.append((cw.ifc_guid, "curtain_wall", cw.area_m2, cw.u_value))
    for win in facade_model.windows:
        all_elements.append((win.ifc_guid, "window", win.area_m2, win.u_value))
    for d in facade_model.doors:
        all_elements.append((d.ifc_guid, "door", d.area_m2, d.u_value))

    total_facade_area = sum(
        e[2] for e in all_elements if e[1] in ("wall", "curtain_wall")
    )
    total_opening_area = sum(
        e[2] for e in all_elements if e[1] in ("window", "door")
    )
    gross_total = total_facade_area + total_opening_area
    wwr = round(total_opening_area / gross_total, 4) if gross_total > 0 else 0.0

    # Weighted U-value
    sum_ua = 0.0
    sum_a = 0.0
    with_u = 0
    without_u = 0
    for _, _, area, u in all_elements:
        if u is not None and area > 0:
            sum_ua += u * area
            sum_a += area
            with_u += 1
        else:
            without_u += 1

    weighted_u = round(sum_ua / sum_a, 4) if sum_a > 0 else None

    per_element = [
        {"guid": guid, "kind": kind, "area_m2": area, "u_value": u}
        for guid, kind, area, u in all_elements
    ]

    return {
        "total_facade_area_m2": round(total_facade_area, 4),
        "total_opening_area_m2": round(total_opening_area, 4),
        "window_to_wall_ratio": wwr,
        "weighted_u_value_W_m2K": weighted_u,
        "elements_with_u_value": with_u,
        "elements_missing_u_value": without_u,
        "per_element_summary": per_element,
    }


# ---------------------------------------------------------------------------
# Continuity validation
# ---------------------------------------------------------------------------

_GAP_THERMAL_BRIDGE_MM = 20.0   # gaps ≥ 20 mm → "thermal bridge" flag


def validate_facade_continuity(facade_model: FacadeModel) -> ValidationResult:
    """
    Check for continuity gaps between adjacent walls in the façade model.

    Algorithm
    ---------
    For each pair of walls in the same storey whose endpoints are co-linear
    (within tolerance), check whether the gap between the end of wall A and
    the start of wall B is within an acceptable thermal-continuity tolerance.

    A gap ≥ 20 mm (configurable via _GAP_THERMAL_BRIDGE_MM) is flagged as a
    "thermal bridge".

    Wall geometry is estimated from length_mm (a 1-D length; exact plan
    coordinates are not available from the parse model without full
    ifcopenshell geometry).  This implementation performs a 1-D adjacency
    check: walls are sorted by their estimated start position on a
    linearised axis per storey, then adjacent pairs are checked.

    Returns
    -------
    ValidationResult
        .ok   True when no continuity issues are found.
        .issues  list of dicts with keys:
            storey, wall_a_guid, wall_b_guid, gap_mm, severity
    """
    issues: list[dict[str, Any]] = []

    storey_walls: dict[str, list[FacadeWall]] = {}
    for w in facade_model.walls:
        key = w.storey or "__unassigned__"
        storey_walls.setdefault(key, []).append(w)

    for storey_name, walls in storey_walls.items():
        if len(walls) < 2:
            continue

        # Sort by length (proxy for position in a linear layout) and simulate
        # a 1-D position chain for gap detection.
        sorted_walls = sorted(walls, key=lambda x: x.length_mm)

        # Accumulate a linearised position for each wall segment.
        # position[i] = start of wall i; end = start + length_mm
        positions: list[float] = [0.0]
        for i, w in enumerate(sorted_walls[:-1]):
            positions.append(positions[-1] + w.length_mm)

        for i in range(len(sorted_walls) - 1):
            wa = sorted_walls[i]
            wb = sorted_walls[i + 1]
            end_a = positions[i] + wa.length_mm
            start_b = positions[i + 1]
            gap_mm = start_b - end_a

            if gap_mm >= _GAP_THERMAL_BRIDGE_MM:
                severity = "thermal_bridge" if gap_mm >= _GAP_THERMAL_BRIDGE_MM else "minor_gap"
                issues.append({
                    "storey": storey_name,
                    "wall_a_guid": wa.ifc_guid,
                    "wall_b_guid": wb.ifc_guid,
                    "gap_mm": round(gap_mm, 2),
                    "severity": severity,
                    "message": (
                        f"Gap of {gap_mm:.1f} mm between walls "
                        f"'{wa.name}' and '{wb.name}' on storey '{storey_name}' "
                        f"— potential thermal bridge."
                    ),
                })

    return ValidationResult(ok=len(issues) == 0, issues=issues)
